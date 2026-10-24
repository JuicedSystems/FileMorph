"""Watch folders: recipes that convert new files on their own, quietly, while FileMorph runs.

Only files that arrive after watching starts are touched (plus ones that arrived while FileMorph
was closed). A file is converted once it has stopped growing and can be opened, never twice, and
never when it is one of our own outputs, so saving into the watched folder can't loop.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QThread, QTimer, Signal, Slot

from ...core.engine import convert_file
from ...core.recipes import Ledger, Recipe, Settle, candidates, render_name
from ...core.registry import Cancelled, ConversionError
from ..worker import writable_dir

POLL_MS = 2000      # backstop for missed change notifications, and how settling is timed
BURST_MS = 3500     # one tray message per burst of files


class _Runner(QObject):
    """Converts one watched file at a time on a background thread."""
    done = Signal(str, str, list, str)   # recipe id, source, outputs, error

    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()

    @Slot(object, str, int)
    def run(self, recipe: Recipe, src: str, n: int):
        p = Path(src)
        try:
            out_dir = writable_dir(Path(recipe.save_dir) if recipe.save_dir else p.parent)
            outs = convert_file(p, recipe.target, out_dir, dict(recipe.options), None, self.cancel_event,
                                render_name(recipe.rename, p, n))
            self.done.emit(recipe.id, src, [str(o) for o in outs], "")
        except Cancelled:
            self.done.emit(recipe.id, src, [], "Cancelled")
        except ConversionError as e:
            self.done.emit(recipe.id, src, [], str(e))
        except Exception as e:  # noqa: BLE001 - never let the watch thread die
            self.done.emit(recipe.id, src, [], f"Unexpected error: {e}")


class WatchService(QObject):
    _submit = Signal(object, str, int)
    converted = Signal(object, str, list, str)   # recipe, source, outputs, error (for Recent)
    burst_done = Signal(str, int, int)            # recipe name, converted, failed

    def __init__(self, registry, recipes_fn, parent=None, ledger: Ledger | None = None):
        super().__init__(parent)
        self.registry = registry
        self.recipes_fn = recipes_fn      # -> current list[Recipe]
        self.ledger = ledger or Ledger()
        self.settle = Settle(quiet=POLL_MS / 1000)
        self.paused = False
        self._queue: list[tuple[str, str]] = []   # (recipe id, path) waiting
        self._busy: tuple[str, str] | None = None
        self._count: dict[str, list[int]] = {}    # recipe id -> [ok, failed] in this burst
        self._n: dict[str, int] = {}
        self.fs = QFileSystemWatcher(self)
        self.fs.directoryChanged.connect(lambda *_: QTimer.singleShot(300, self.scan))
        self.timer = QTimer(self, interval=POLL_MS, timeout=self.scan)
        self.burst = QTimer(self, singleShot=True, interval=BURST_MS, timeout=self._report)
        self.thread = QThread(self)
        self.runner = _Runner()
        self.runner.moveToThread(self.thread)
        self._submit.connect(self.runner.run)
        self.runner.done.connect(self._on_done)
        self.thread.start()
        self.refresh()

    # ------------------------------------------------------------- setup
    def watched(self) -> list[Recipe]:
        return [r for r in self.recipes_fn() if r.watching and r.watch_dir and Path(r.watch_dir).is_dir()]

    def refresh(self):
        """Recipes changed: watch exactly their folders."""
        want = sorted({str(Path(r.watch_dir)) for r in self.watched()})
        have = self.fs.directories()
        if have:
            self.fs.removePaths(have)
        if want:
            self.fs.addPaths(want)
        live = {r.id for r in self.watched()}
        self._queue = [q for q in self._queue if q[0] in live]
        if want and not self.paused:
            self.timer.start()
            QTimer.singleShot(0, self.scan)
        else:
            self.timer.stop()

    def set_paused(self, paused: bool):
        self.paused = paused
        self.refresh()

    def stop(self) -> bool:
        """For quit: stop watching, cancel the running file. True if the thread ended in time."""
        self.timer.stop()
        self._queue.clear()
        self.runner.cancel_event.set()
        self.thread.quit()
        return self.thread.wait(4000)

    # ------------------------------------------------------------- work
    def scan(self):
        if self.paused:
            return
        queued = set(self._queue) | ({self._busy} if self._busy else set())
        for r in self.watched():
            for p, st in candidates(r, self.registry, self.ledger):
                key = (r.id, str(p))
                if key not in queued and self.settle.ready(p, st):
                    self._queue.append(key)
                    queued.add(key)
        self._next()

    def _next(self):
        if self._busy or not self._queue:
            return
        rid, src = self._queue.pop(0)
        r = next((x for x in self.recipes_fn() if x.id == rid), None)
        if r is None or not os.path.exists(src):
            QTimer.singleShot(0, self._next)
            return
        self._busy = (rid, src)
        self._n[rid] = self._n.get(rid, 0) + 1
        self._submit.emit(r, src, self._n[rid])

    def _on_done(self, rid: str, src: str, outs: list, err: str):
        self._busy = None
        r = next((x for x in self.recipes_fn() if x.id == rid), None)
        if err != "Cancelled":
            # failures go in the ledger too: a file that can't convert isn't retried every 2 s
            self.ledger.add(rid, Path(src) if os.path.exists(src) else None, [Path(o) for o in outs])
            self.ledger.save()
            c = self._count.setdefault(rid, [0, 0])
            c[0 if outs else 1] += 1
            if r is not None:
                self.converted.emit(r, src, outs, err)
            self.burst.start()
        self._next()

    def _report(self):
        names = {r.id: r.name for r in self.recipes_fn()}
        for rid, (ok, bad) in self._count.items():
            self.burst_done.emit(names.get(rid, "a recipe"), ok, bad)
        self._count.clear()
        self._n.clear()

    @property
    def busy(self) -> bool:
        return self._busy is not None or bool(self._queue)
