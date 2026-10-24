"""Wires the floating node, the mini panel, the tray icon and the conversion engine together."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QSettings, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from ... import __version__
from ...core.converters import build_registry
from ...core.updater import Updater, UpdateError, human_size
from ...core.converters.office import NEEDS_OFFICE, backend_name
from ...core.formats import CATEGORIES, FORMATS, SUGGESTED, detect
from ...core import recipes as rc
from ...core import shell
from ...core.converters.ocr import looks_scanned
from ...core.converters.shrink import human
from ..main_window import open_path, reveal_path
from ...core import proc
from ..worker import ConvertWorker, downloads_dir, scan_folder
from . import style as st
from .node import BASE, NodeWindow
from .panel import PanelWindow, paint_orb
from .updates import UpdateRunner
from .watch import WatchService

MAX_FILES = 500
PILL_MAX = 5
RECIPE_CHIPS = 2   # at most this many recipe chips lead the pill
QUALITY_TARGETS = {"jpg", "webp", "avif", "mp4", "mov", "mkv", "webm"}
_BUILTIN_PDF_LAYOUT = {"html_to_pdf", "doc_to_pdf", "sheet_to_pdf"}
MENU_CSS = ("QMenu{background:#12141c;border:1px solid rgba(255,255,255,26);border-radius:12px;padding:6px;color:#eef0f6}"
            "QMenu::item{padding:8px 22px 8px 14px;border-radius:8px}"
            "QMenu::item:selected{background:rgba(255,255,255,20)}"
            "QMenu::separator{height:1px;background:rgba(255,255,255,20);margin:5px 8px}"
            "QMenu::indicator{width:14px;height:14px;margin-left:4px}")


class MorphController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        st.load_fonts()
        self.settings = QSettings("FileMorph", "FileMorph")
        self.registry = build_registry()
        self.files: list[Path] = []
        self.targets: list[str] = []
        self.target: str | None = None
        self.thread: QThread | None = None
        self.worker: ConvertWorker | None = None
        self.results: list = []
        self.last_outputs: list[str] = []
        self.history: list[dict] = self._load_history()
        self._retired: list[tuple[QThread, ConvertWorker]] = []  # cancelled runs still winding down
        self._incoming: list[Path] = []   # Explorer hand-offs, merged over a short window
        self._queued: list[Path] = []     # files that arrived during a conversion
        self._intake_timer = QTimer(self, singleShot=True, interval=350, timeout=self._flush_incoming)
        self._incoming_recipes: dict[str, list[Path]] = {}   # Explorer: right-click -> recipe
        self._queued_recipes: list[tuple[str, list[Path]]] = []
        self.recipes: list[rc.Recipe] = rc.load()
        self._recipe: rc.Recipe | None = None   # the recipe the current conversion runs

        self.node = NodeWindow()
        self.panel = PanelWindow()
        self._apply_colorway(self.settings.value("colorway", st.DEFAULT_WAY))
        on_top = self.settings.value("on_top", True, type=bool)
        self.node.set_on_top(on_top)
        self.panel.set_on_top(on_top)
        self._sync_save()
        self.panel.set_recent(self.history)

        n = self.node
        n.dropped.connect(self.add_files)
        n.clicked.connect(self._node_clicked)
        n.chip_picked.connect(self._chip_picked)
        n.more_clicked.connect(self._open_formats)
        n.cancel_requested.connect(self._cancel_pick)
        n.stop_requested.connect(self.cancel_conversion)
        n.menu_requested.connect(self._show_menu)
        n.moved.connect(lambda c: self.settings.setValue("node_pos", c))

        pnl = self.panel
        pnl.collapse_requested.connect(self.collapse)
        pnl.files_dropped.connect(self.add_files)
        pnl.browse_requested.connect(self.browse)
        pnl.recent_clicked.connect(self._recent_clicked)
        pnl.convert_requested.connect(self._convert_from_panel)
        pnl.recipes_requested.connect(self.show_recipes)
        pnl.recipe_saved.connect(self._save_recipe)
        pnl.recipe_deleted.connect(self._delete_recipe)
        pnl.recipe_watch.connect(self._set_watching)
        pnl.recipe_from_formats.connect(self._recipe_from_formats)
        pnl._editor_ctx = {"targets": self._recipe_targets(), "options_fn": self._recipe_options,
                           "targets_of": lambda k: set(self.registry.targets(k))}
        pnl.on_top_toggled.connect(self._set_on_top)
        pnl.save_next_toggled.connect(self._set_save_next)
        pnl.change_folder.connect(self._choose_folder)
        pnl.menu_requested.connect(self._show_menu)
        pnl.update_check.connect(self.check_updates)
        pnl.update_install.connect(self._install_update)
        pnl.update_restart.connect(self._restart_pending)
        self.updater: Updater | None = None
        self.update_runner: UpdateRunner | None = None
        self.offer = None
        self._panel_moved = False
        pnl.moved.connect(lambda: setattr(self, "_panel_moved", True))

        self.idle_timer = QTimer(self, singleShot=True, timeout=self._back_to_idle)
        self.watch = WatchService(self.registry, lambda: self.recipes, self)
        self.watch.converted.connect(self._watch_converted)
        self.watch.burst_done.connect(self._watch_burst)
        self._setup_tray()
        self._place_node()
        self.node.show()

    # ------------------------------------------------------------- placement & look
    def _screen_rect(self, at: QPoint | None = None):
        scr = QGuiApplication.screenAt(at) if at is not None else None
        return (scr or QGuiApplication.primaryScreen()).availableGeometry()

    def _place_node(self):
        saved = self.settings.value("node_pos")
        r = self._screen_rect(saved if isinstance(saved, QPoint) else None)
        if isinstance(saved, QPoint) and r.contains(saved):
            c = saved
        else:
            c = QPoint(r.right() - 150, r.bottom() - 130)
        self.node.move_center(c)

    def _apply_colorway(self, name: str):
        name = name if name in st.COLORWAYS else st.DEFAULT_WAY
        self.colorway = name
        cols = st.COLORWAYS[name]
        self.node.set_colorway(cols)
        self.panel.set_colorway(cols)
        if hasattr(self, "tray"):
            self.tray.setIcon(self._orb_icon())
        self.settings.setValue("colorway", name)

    def _orb_icon(self) -> QIcon:
        ic = QIcon()
        for s in (16, 20, 24, 32, 48, 64):
            pm = QPixmap(s, s)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            paint_orb(p, QPointF(s / 2, s / 2), s * 0.9, st.COLORWAYS[self.colorway], 30)
            p.end()
            ic.addPixmap(pm)
        return ic

    def _set_on_top(self, on: bool):
        self.settings.setValue("on_top", on)
        self.node.set_on_top(on)
        self.panel.set_on_top(on)
        if hasattr(self, "act_top"):
            self.act_top.setChecked(on)

    # ------------------------------------------------------------- tray & menu
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self._orb_icon(), self)
        self.tray.setToolTip("FileMorph — drop files on the orb")
        self.tray.activated.connect(self._tray_activated)
        self.tray_menu = self._build_menu()
        self.tray.setContextMenu(self.tray_menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _build_menu(self) -> QMenu:
        m = QMenu()
        m.setStyleSheet(MENU_CSS)
        m.addAction("Open FileMorph", self.expand)
        m.addAction("Convert files…", self.browse)
        m.addAction("Recipes…", self.show_recipes)
        self.act_pause = QAction("Pause watching folders", m, checkable=True, checked=False)
        self.act_pause.triggered.connect(self._pause_watching)
        m.addAction(self.act_pause)
        m.addSeparator()
        self.act_show = QAction("Show floating node", m, checkable=True, checked=True)
        self.act_show.triggered.connect(self._toggle_node)
        m.addAction(self.act_show)
        self.act_top = QAction("Keep on top", m, checkable=True,
                               checked=self.settings.value("on_top", True, type=bool))
        self.act_top.triggered.connect(self._set_on_top)
        m.addAction(self.act_top)
        sub = m.addMenu("Colorway")
        sub.setStyleSheet(MENU_CSS)
        grp = QActionGroup(sub)
        for name in st.COLORWAYS:
            a = QAction(name, sub, checkable=True, checked=name == self.colorway)
            a.triggered.connect(lambda _=False, n=name: self._apply_colorway(n))
            grp.addAction(a)
            sub.addAction(a)
        m.addSeparator()
        m.addAction("Check for updates…", self.check_updates)
        about = QAction(f"FileMorph {__version__}", m)
        about.setEnabled(False)
        m.addAction(about)
        m.addAction("Quit FileMorph", self.quit)
        return m

    def _tray_activated(self, reason):
        # Windows sends Trigger and then DoubleClick for a double-click: toggling on both would
        # hide and re-show (or the reverse). Single click toggles; a double-click always shows.
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_node(not self.node.isVisible() and not self.panel.isVisible())
        elif reason == QSystemTrayIcon.DoubleClick:
            self._toggle_node(True)

    def _show_node(self):
        """Make sure the orb is on screen (it may have been hidden from the tray)."""
        if self.panel.isVisible():
            self.panel.hide()
        if not self.node.isVisible():
            self.node.show()
        self.node.raise_()
        self.act_show.setChecked(True)

    def _toggle_node(self, show: bool):
        self.act_show.setChecked(show)
        if show:
            self.panel.hide()
            self.node.show()
            self.node.raise_()
        else:
            self.node.hide()
            self.panel.hide()

    def _show_menu(self, pos: QPoint):
        self.tray_menu.exec(pos)

    def quit(self):
        """Stop conversions and the tools they started, wait briefly for threads, then exit."""
        threads = [(self.thread, self.worker)] if self.thread else []
        threads += self._retired
        for _, w in threads:
            if w is not None:
                w.cancel()
        stuck = not self.watch.stop()
        if self.update_runner is not None and not self.update_runner.shutdown():
            stuck = True
        proc.kill_all(final=True)  # ffmpeg/pandoc/LibreOffice/Office instances: don't leave them running
        deadline = time.monotonic() + 6
        for t, _ in threads:
            try:
                t.quit()  # ends the thread's loop once the worker returns (the queued quit from
                # worker.finished can't run while this thread is blocked in wait())
                left = max(0, int((deadline - time.monotonic()) * 1000))
                if t.isRunning() and not t.wait(left):
                    stuck = True
            except RuntimeError:  # already deleted
                pass
        self.tray.hide()
        self.settings.sync()
        if stuck:
            # a pure-Python step can't be interrupted; exiting now is safe (output goes to a temp
            # folder first, and the Job Object reaps child processes) and avoids a Qt abort on
            # destroying a running QThread.
            os._exit(0)
        self.app.quit()

    # ------------------------------------------------------------- panel
    def expand(self):
        if self.worker:  # converting: the orb is the progress display; just bring it forward
            self._show_node()
            return
        self.panel.show_home()
        self.panel.set_recent(self.history)
        self._sync_save()
        c = self.node.center_global()
        self.node.hide()
        self.panel.open_at(c, BASE, self._screen_rect(c))

    def collapse(self):
        self.panel.hide()
        if self._panel_moved:
            # the node follows the panel's bottom-right corner when the panel was dragged
            box = self.panel.box_global_rect()
            c = QPoint(box.right() - BASE // 2 - 8 + 1, box.bottom() - BASE // 2 - 8 + 1)
            self.node.move_center(c)
            self.settings.setValue("node_pos", c)
            self._panel_moved = False
        self.node.show()
        self.node.raise_()
        self.act_show.setChecked(True)

    def browse(self):
        start = self.settings.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(None, "Choose files to convert", start, _file_filter())
        if paths:
            self.settings.setValue("last_dir", str(Path(paths[0]).parent))
            self.add_files([Path(p) for p in paths])

    def _recent_clicked(self, e: dict):
        out = e.get("out")
        if out and Path(out).exists():
            reveal_path(Path(out))

    def _open_formats(self):
        if not self.files:
            return
        c = self.node.center_global()
        self.node.hide()
        self.panel.show_formats(self._summary(), self.targets, None, self._options_for, self.settings)
        self.panel.open_at(c, BASE, self._screen_rect(c))

    # ------------------------------------------------------------- save location
    def _out_dir(self) -> Path | None:
        if self.settings.value("save_next", True, type=bool):
            return None
        d = self.settings.value("save_dir", "")
        return Path(d) if d and Path(d).exists() else downloads_dir()

    def _sync_save(self):
        nxt = self.settings.value("save_next", True, type=bool)
        d = self._out_dir()
        self.panel.set_save_state(nxt, (d.name or str(d)) if d else "")

    def _set_save_next(self, on: bool):
        self.settings.setValue("save_next", on)
        self._sync_save()

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(None, "Save converted files to",
                                             self.settings.value("save_dir", str(downloads_dir())))
        if d:
            self.settings.setValue("save_dir", d)
            self._sync_save()

    # ------------------------------------------------------------- intake
    def receive_paths(self, paths: list[Path], recipe: str | None = None):
        """Files handed over by Explorer (context menu, Send to, Open with, a recipe). Windows starts
        one FileMorph per selected file, so hand-offs arriving within a moment become one batch."""
        if recipe:
            self._incoming_recipes.setdefault(recipe, []).extend(Path(p) for p in paths)
        else:
            self._incoming += [Path(p) for p in paths]
        self._intake_timer.start()

    def _flush_incoming(self):
        paths, self._incoming = self._incoming, []
        jobs, self._incoming_recipes = self._incoming_recipes, {}
        for rid, rpaths in jobs.items():
            self.recipes = rc.load()  # Explorer's menu may be newer than what we loaded
            r = rc.find(self.recipes, rid)
            if r is None:
                self._fail("That recipe no longer exists. Open Recipes to see the ones you have.", "Recipe")
            else:
                self.run_recipe(r, rpaths)
        if not paths:
            return
        if self.worker:
            self._queue(paths)
            return
        if self.node.mode == "picking" and self.files:
            paths = self.files + paths  # still choosing: the new files join the current batch
        self.add_files(paths)

    def _queue(self, paths: list[Path], recipe: rc.Recipe | None = None):
        if recipe is not None:
            self._queued_recipes.append((recipe.id, list(paths)))
        else:
            self._queued += paths
        n = len(self._queued) + sum(len(b[1]) for b in self._queued_recipes)
        self.tray.showMessage("FileMorph", f"{n} file{'s' if n != 1 else ''} will open when this conversion "
                              "finishes.", QSystemTrayIcon.Information, 3000)

    def _expand(self, paths: list[Path]) -> tuple[list[Path], list[Path]]:
        """Files (folders opened up, duplicates dropped) -> (convertible, unknown)."""
        found: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                found += scan_folder(p, MAX_FILES - len(found))
            elif p.is_file():
                found.append(p)
            if len(found) >= MAX_FILES:
                break
        seen, files, unknown = set(), [], []
        for p in found:
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            (files if detect(p) else unknown).append(p)
        return files[:MAX_FILES], unknown

    def add_files(self, paths: list[Path]):
        if self.worker:
            self._queue([Path(p) for p in paths])
            return
        files, unknown = self._expand(paths)
        self.files = files
        self._recipe = None
        self._show_node()
        self.idle_timer.stop()
        self._done_has_errors = False
        if not self.files:
            name = unknown[0].name if unknown else "That item"
            self._fail(f"{name} isn't a file type FileMorph can convert.", name)
            return
        counts = Counter(detect(f).key for f in self.files)
        sets = [set(self.registry.targets(k)) | ({k} if len(self.files) > 1 else set()) for k in counts]
        common = set.intersection(*sets)
        primary = counts.most_common(1)[0][0]
        if not common:
            missing = [k for k in counts if k in NEEDS_OFFICE]
            if missing and backend_name() is None:
                msg = (f".{FORMATS[missing[0]].ext} files need Microsoft Office or the free LibreOffice installed "
                       "to convert.")
            elif len(self.files) > 1:
                msg = "These files don't share a format they can all become. Try them in separate groups."
            else:
                msg = "There's nothing this file can be converted to yet."
            self._fail(msg, self.files[0].name)
            return
        self.targets = self._ordered_targets(primary, common)
        if primary == "pdf" and "ocrpdf" in self.targets and looks_scanned(
                next(f for f in self.files if detect(f).key == "pdf")):
            self.targets.remove("ocrpdf")  # a scan: making it searchable is the likely wish
            self.targets.insert(0, "ocrpdf")
        fits = [r for r in self.recipes if all(r.accepts(k, self.registry) for k in counts)][:RECIPE_CHIPS]
        room = PILL_MAX - len(fits)
        pill = [(f"recipe:{r.id}", r.tag, r.name) for r in fits]
        pill += [(k, FORMATS[k].tag) for k in self.targets[:room]]
        # ••• also leads to the options (quality, combine into one PDF, ...) even when every
        # format already fits in the pill.
        more = len(self.targets) > room or any(self._options_for(t) for t in self.targets)
        badge, name = self._summary()
        self.node.show_picking(badge, name, pill, more)

    def _ordered_targets(self, primary: str, common: set) -> list[str]:
        sugg = [k for k in SUGGESTED.get(primary, []) if k in common]
        if len(self.files) > 1 and "pdf" in common and "pdf" not in sugg:
            sugg.insert(0, "pdf")
        cat_order = [c for c, _ in CATEGORIES]
        src_cat = FORMATS[primary].category
        rest = sorted((k for k in common if k not in sugg),
                      key=lambda k: (FORMATS[k].category != src_cat, cat_order.index(FORMATS[k].category),
                                     list(FORMATS).index(k)))
        return sugg + rest

    def _summary(self) -> tuple[str, str]:
        if len(self.files) == 1:
            f = self.files[0]
            return detect(f).ext.upper(), f.name
        counts = Counter(detect(f).key for f in self.files)
        badge = FORMATS[counts.most_common(1)[0][0]].ext.upper() if len(counts) == 1 else f"{len(self.files)}"
        return badge, f"{len(self.files)} files"

    def _cancel_pick(self):
        self.files = []
        self.node.show_idle()

    def cancel_conversion(self):
        """Stop at once from the user's point of view. The worker finishes winding down in the
        background (tools are killed within ~0.1 s; nothing is saved once cancelled)."""
        w, t = self.worker, self.thread
        if w is None:
            return
        w.cancel()
        for sig, slot in ((w.progress, self._on_progress), (w.file_done, self._on_file_done),
                          (w.finished, self._on_finished)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        entry = (t, w)
        self._retired.append(entry)
        t.finished.connect(lambda e=entry: e in self._retired and self._retired.remove(e))
        self.worker = None
        self.thread = None
        self.node.show_cancelled()
        QTimer.singleShot(2200, lambda: self.node.mode == "idle" and setattr(self.node, "caption", None))
        self._drain_queue()

    def _drain_queue(self, delay: int = 250):
        if self._queued_recipes and not self._queued:
            rid, paths = self._queued_recipes.pop(0)
            r = rc.find(self.recipes, rid)
            if r is not None:
                QTimer.singleShot(delay, lambda: self.worker is None and self.run_recipe(r, paths)
                                  or (self.worker is not None and self._queue(paths, r)))
            return
        if self._queued:
            paths, self._queued = self._queued, []
            QTimer.singleShot(delay, lambda: self.worker is None and self.add_files(paths)
                              or (self.worker is not None and self._queue(paths)))

    # ------------------------------------------------------------- options
    def _options_for(self, dst: str, src_keys: set[str] | None = None) -> list:
        """Option rows the All formats page (or the recipe editor) should show for this target."""
        out = []
        batch = src_keys is None
        src_keys = {detect(f).key for f in self.files} if batch else src_keys
        src_cats = {FORMATS[k].category for k in src_keys}
        fns = {e.fn.__name__ for k in src_keys for e in (self.registry.plan(k, dst) or [])}
        if batch and len(self.files) > 1 and dst == "pdf":
            out.append(("switch", "combine", "Combine into one PDF"))
        if dst in QUALITY_TARGETS:
            out.append(("slider", "quality", "Quality"))
        if dst in ("png", "jpg", "webp", "tiff") and src_cats & {"document", "sheet", "slides"}:
            out.append(("seg", "dpi", "Resolution", [("Screen", 96), ("Std", 150), ("Print", 300)], 150))
        if dst == "svg" and "image" in src_cats and "svg" not in src_keys:
            out.append(("seg", "svg_detail", "Detail", [("Simple", "simple"), ("Balanced", "balanced"),
                                                        ("Fine", "detailed")], "balanced"))
        if dst == "trace":
            out.append(("seg", "trace_detail", "Detail", [("Bold", "bold"), ("Balanced", "balanced"),
                                                          ("Fine", "fine")], "balanced"))
            out.append(("seg", "trace_darkness", "Darkness", [("Lighter", -25), ("Auto", 0), ("Darker", 25)], 0))
        if dst == "pdf" and fns & _BUILTIN_PDF_LAYOUT:
            out.append(("seg", "page_size", "Page", [("Letter", "letter"), ("A4", "a4")], "letter"))
        if dst == "gif" and "video" in src_cats:
            out.append(("seg", "gif_width", "Width", [("S", 360), ("M", 640), ("L", 960)], 640))
        if dst == "shrink":
            out.append(("seg", "shrink_strength", "Strength", [("Light", "light"), ("Balanced", "balanced"),
                                                               ("Strong", "strong")], "balanced"))
        return out

    def _default_options(self, dst: str) -> dict:
        """Options for a one-click pill conversion: last-used values."""
        opts = {}
        for spec in self._options_for(dst):
            kind, key = spec[0], spec[1]
            if kind == "slider":
                opts[key] = self._int_setting("quality", 90, 1, 100)
            elif kind == "seg":
                default = spec[4]
                v = self.settings.value(f"opt_{key}", default)
                try:
                    opts[key] = type(default)(v)
                except (TypeError, ValueError):
                    opts[key] = default
        return opts

    # ------------------------------------------------------------- convert
    def _chip_picked(self, key: str):
        if key.startswith("recipe:"):
            r = rc.find(self.recipes, key[7:])
            if r is not None:
                self.run_recipe(r, list(self.files))
            return
        self._recipe = None
        self.convert(key, self._default_options(key), False)

    def _convert_from_panel(self, dst: str, options: dict, combine: bool):
        self._recipe = None
        self.convert(dst, options, combine)

    def run_recipe(self, r: rc.Recipe, paths: list[Path]):
        """Convert with a saved recipe: its format, options, folder and file names."""
        if self.worker:
            self._queue(paths, r)
            return
        files, _unknown = self._expand(paths)
        files = [f for f in files if r.accepts(detect(f).key, self.registry)]
        if not files:
            what = "this file" if len(paths) == 1 else "these files"
            self._fail(f"“{r.name}” can't convert {what}.", Path(paths[0]).name if paths else r.name)
            return
        self.files = files
        self._recipe = r
        self.convert(r.target, dict(r.options), False)

    def convert(self, dst: str, options: dict, combine: bool):
        if not self.files or self.worker:
            return
        self.target = dst
        self._show_node()
        self._combine = combine
        self.results = [(f, [], "") for f in (self.files[:1] if combine else self.files)]
        self.node.show_converting(self._conv_text(0))
        self.thread = QThread(self)
        r = self._recipe
        out_dir = (Path(r.save_dir) if r.save_dir else None) if r else self._out_dir()
        self.worker = ConvertWorker(list(self.files), dst, out_dir, options, combine, r.rename if r else "")
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _conv_text(self, i: int) -> str:
        t = FORMATS[self.target].tag
        n = len(self.results)
        verb = {"shrink": "Shrinking", "ocrpdf": "Reading"}.get(self.target)
        if verb:
            return f"{verb}…" if n == 1 else f"{verb} {i + 1} of {n}…"
        return f"Converting to {t}…" if n == 1 else f"Converting {i + 1} of {n} to {t}…"

    def _on_progress(self, i: int, frac: float, msg: str):
        if self.worker is None or self.sender() is not self.worker:  # a cancelled run's queued signals
            return
        n = len(self.results)
        self.node.set_progress((i + frac) / n, self._conv_text(min(i, n - 1)))

    def _on_file_done(self, i: int, outs: list, err: str):
        if self.worker is None or self.sender() is not self.worker:
            return
        if i < len(self.results):
            self.results[i] = (self.results[i][0], outs, err)

    def _on_finished(self, cancelled: bool):
        if self.worker is None or self.sender() is not self.worker:
            return
        self.worker = None
        self.thread = None
        if cancelled:
            self.node.show_idle()
            self._drain_queue()
            return
        self._report()
        self._drain_queue(1800)  # let the "done" state show before the next batch opens

    def _report(self):
        ok = [r for r in self.results if r[1]]
        bad = [r for r in self.results if r[2]]
        now = time.time()
        to = FORMATS[self.target].tag
        for src, outs, err in self.results:
            fmt = detect(src)
            entry = {"from": fmt.ext.upper() if fmt else "?", "to": to, "to_key": self.target, "at": now}
            if err:
                entry.update(name=src.name, error=err)
                self.history.insert(0, entry)
            for o in outs[:1]:
                extra = f" (+{len(outs) - 1})" if len(outs) > 1 else ""
                self.history.insert(0, dict(entry, name=Path(o).name + extra, out=o))
        self.history = self.history[:20]
        self._save_history()
        self.panel.set_recent(self.history)
        self.last_outputs = [o for r in ok for o in r[1]]
        if ok and not bad:
            self._done_has_errors = False
            n = len(self.last_outputs)
            name = Path(self.last_outputs[0]).name if n == 1 else f"{n} {to} files"
            out_parent = Path(self.last_outputs[0]).parent
            src_parent = ok[0][0].parent
            # name the folder whenever it isn't next to the original (chosen folder or fallback)
            where = "" if out_parent == src_parent else f" to {out_parent.name or out_parent}"
            if self.target == "shrink":
                before = sum(_size(r[0]) for r in ok)
                after = sum(_size(Path(o)) for o in self.last_outputs)
                self.node.show_done(name, f"{human(before)} → {human(after)}" + (f" · saved{where}" if where else ""))
            else:
                self.node.show_done(name, f"saved{where}")
            self.idle_timer.start(3200)
        elif ok:
            self.node.show_done(f"{len(ok)} of {len(self.results)} converted", "· click for details")
            self._done_has_errors = True
            self.idle_timer.start(6000)
        else:
            self._fail(bad[0][2], bad[0][0].name, record=False)
        self._recipe = None

    def _fail(self, msg: str, name: str, record: bool = True):
        if record:
            self.history.insert(0, {"name": name, "error": msg, "from": Path(name).suffix[1:].upper() or "?",
                                    "to": "—", "to_key": None, "at": time.time()})
            self.history = self.history[:20]
            self._save_history()
            self.panel.set_recent(self.history)
        self._show_node()
        self.node.show_error(msg, "Already as small as it gets" if msg.startswith("Already as small") else "")
        self.idle_timer.start(6000)

    def _back_to_idle(self):
        if self.node.mode in ("done", "error"):
            self._done_has_errors = False
            self.node.show_idle()

    def _node_clicked(self):
        mode = self.node.mode
        if mode == "done" and self.last_outputs and not getattr(self, "_done_has_errors", False):
            self.idle_timer.stop()
            self.node.show_idle()
            out = Path(self.last_outputs[0])
            try:
                reveal_path(out) if len(self.last_outputs) > 1 else open_path(out)
            except OSError:
                # no app is set up to open this type (e.g. .avif, .webm): show it in its folder
                try:
                    reveal_path(out)
                except OSError:
                    pass
        elif mode in ("done", "error"):
            self.idle_timer.stop()
            self._done_has_errors = False
            self.node.show_idle()
            self.expand()
        else:
            self.expand()

    # ------------------------------------------------------------- updates (user-initiated only)
    def _open_panel_for(self, show):
        """Run `show()` to fill the panel, then make sure the panel is open."""
        show()
        if not self.panel.isVisible():
            c = self.node.center_global()
            self.node.hide()
            self.panel.open_at(c, BASE, self._screen_rect(c))

    def check_updates(self):
        if self.updater is None:
            self.updater = Updater()
            self.update_runner = UpdateRunner(self.updater, self)
            self.update_runner.checked.connect(self._update_checked)
            self.update_runner.progress.connect(self.panel.set_update_progress)
            self.update_runner.downloaded.connect(self._update_downloaded)
        cur = self.updater.current_version()
        if not self.updater.available:
            self._open_panel_for(lambda: self.panel.show_updates("unavailable", current=cur,
                                                                 message=self.updater.why_unavailable))
            return
        pending = self.updater.pending_restart()
        if pending:
            self._open_panel_for(lambda: self.panel.show_updates(
                "ready", current=cur, version=pending, notes="", blocked=self._update_blocked()))
            return
        if self.update_runner.busy:
            return
        self._open_panel_for(lambda: self.panel.show_updates("checking", current=cur))
        self.update_runner.check()

    def _update_blocked(self) -> str:
        return "Finish the current conversion first." if self.worker else ""

    def _updates_page_open(self) -> bool:
        upd = getattr(self.panel, "updates", None)
        return self.panel.isVisible() and upd is not None and self.panel.stack.currentWidget() is upd

    def _update_checked(self, offer, err: str):
        cur = self.updater.current_version()
        if not self._updates_page_open():
            # The user moved on (or closed the panel) while we checked: don't yank them back.
            if offer is not None:
                self.offer = offer
                self.tray.showMessage("FileMorph", f"Version {offer.version} is available. "
                                      "Open ⋯ → Check for updates to install it.", QSystemTrayIcon.Information, 6000)
            return
        if err:
            self.panel.show_updates("error", current=cur, title="Couldn't check for updates", message=err)
        elif offer is None:
            self.panel.show_updates("current", current=cur)
        else:
            self.offer = offer
            size = human_size(offer.size_bytes) if offer.size_bytes else ""
            self.panel.show_updates("available", current=cur, version=offer.version, size=size,
                                    notes=offer.notes_markdown, blocked=self._update_blocked())

    def _install_update(self):
        if not self.offer or self._update_blocked() or self.update_runner.busy:
            return
        self.panel.show_updates("downloading", current=self.updater.current_version(),
                                version=self.offer.version, pct=0)
        self.update_runner.download(self.offer)

    def _update_downloaded(self, err: str):
        if err:
            self.panel.show_updates("error", current=self.updater.current_version(),
                                    title="Couldn't download the update", message=err)
            return
        self.panel.show_updates("installing", current=self.updater.current_version(), version=self.offer.version)
        QTimer.singleShot(700, lambda: self._apply(lambda: self.updater.apply_and_restart(self.offer)))

    def _restart_pending(self):
        if self._update_blocked():
            return
        self.panel.show_updates("installing", current=self.updater.current_version())
        QTimer.singleShot(500, lambda: self._apply(self.updater.apply_pending))

    def _apply(self, fn):
        """Hand over to Velopack: it closes FileMorph, swaps in the new version and relaunches it."""
        if self._update_blocked():
            # A conversion started while the update was downloading: Velopack exits the process
            # immediately, so wait. The downloaded update stays ready for "Restart to update".
            self.panel.show_updates("ready", current=self.updater.current_version(),
                                    version=getattr(self.offer, "version", "") or (self.updater.pending_restart() or ""),
                                    notes=getattr(self.offer, "notes_markdown", "") or "",
                                    blocked=self._update_blocked())
            return
        self.settings.sync()
        try:
            self.tray.hide()
            fn()
        except UpdateError as e:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray.show()
            self.panel.show_updates("error", current=self.updater.current_version(),
                                    title="Couldn't install the update", message=str(e))

    def show_updated(self, version: str):
        """Called after Velopack relaunches us on a new version."""
        self.node._set_caption([("ok", ""), ("text", f"Updated to {version}")])
        self.node.update()
        QTimer.singleShot(5000, lambda: self.node.mode == "idle" and setattr(self.node, "caption", None))

    # ------------------------------------------------------------- recipes
    def _recipe_targets(self) -> list[str]:
        """Every format a recipe can make (anything some file type converts to)."""
        keys = set()
        for k, f in FORMATS.items():
            if not f.output_only:
                keys |= set(self.registry.targets(k))
        return [k for k in FORMATS if k in keys]

    def _recipe_options(self, dst: str) -> list:
        srcs = {k for k, f in FORMATS.items() if not f.output_only and dst in self.registry.targets(k)}
        return self._options_for(dst, srcs)

    def show_recipes(self):
        self.recipes = rc.load() or self.recipes
        self._open_panel_for(lambda: self.panel.show_recipes(self.recipes))

    def _recipe_from_formats(self, target: str, options: dict):
        srcs = {detect(f).key for f in self.files}
        opts = {k: v for k, v in options.items() if k != "combine"}
        self.panel.show_recipe_editor(None, self.panel._editor_ctx,
                                      {"target": target, "options": opts, "name": rc.default_name(target, srcs),
                                       "sources": sorted(srcs)})

    def _store_recipes(self):
        try:
            rc.save(self.recipes)
        except OSError as e:
            self.tray.showMessage("FileMorph", f"Couldn't save recipes: {e}", QSystemTrayIcon.Warning, 5000)
        try:
            shell.install_recipes(self.recipes)  # Explorer's right-click menu (installed copies only)
        except Exception:
            pass
        self.watch.refresh()

    def _start_watch(self, r: rc.Recipe):
        r.watch_since = time.time()
        self.watch.ledger.baseline(r)  # what's there now is left alone
        self.watch.ledger.save()

    def _save_recipe(self, new: rc.Recipe):
        old = rc.find(self.recipes, new.id)
        if new.watching and (old is None or not old.watching or old.watch_dir != new.watch_dir):
            self._start_watch(new)
        if old is None:
            self.recipes.append(new)
        else:
            self.recipes[self.recipes.index(old)] = new
        self._store_recipes()
        self.panel.show_recipes(self.recipes)

    def _delete_recipe(self, rid: str):
        self.recipes = [r for r in self.recipes if r.id != rid]
        self.watch.ledger.forget(rid)
        self.watch.ledger.save()
        self._store_recipes()
        self.panel.show_recipes(self.recipes)

    def _set_watching(self, rid: str, on: bool):
        r = rc.find(self.recipes, rid)
        if r is None or r.watching == on:
            return
        r.watching = on and bool(r.watch_dir)
        if r.watching:
            self._start_watch(r)
        self._store_recipes()

    def _pause_watching(self, paused: bool):
        self.watch.set_paused(paused)

    def _watch_converted(self, r: rc.Recipe, src: str, outs: list, err: str):
        fmt = detect(Path(src))
        entry = {"from": fmt.ext.upper() if fmt else "?", "to": FORMATS[r.target].tag, "to_key": r.target,
                 "at": time.time()}
        if err:
            self.history.insert(0, dict(entry, name=Path(src).name, error=err))
        for o in outs[:1]:
            extra = f" (+{len(outs) - 1})" if len(outs) > 1 else ""
            self.history.insert(0, dict(entry, name=Path(o).name + extra, out=o))
        self.history = self.history[:20]
        self._save_history()
        self.panel.set_recent(self.history)

    def _watch_burst(self, name: str, ok: int, bad: int):
        msg = f"Converted {ok} file{'s' if ok != 1 else ''} with “{name}”." if ok else ""
        if bad:
            msg += f" {bad} file{'s' if bad != 1 else ''} couldn't be converted: see Recent."
        icon = QSystemTrayIcon.Warning if bad else QSystemTrayIcon.Information
        self.tray.showMessage("FileMorph", msg.strip(), icon, 5000)

    # ------------------------------------------------------------- history
    def _load_history(self) -> list[dict]:
        """Recent conversions, keeping only well-formed entries (a damaged setting must never stop
        the panel from opening)."""
        try:
            data = json.loads(self.settings.value("history", "[]"))
        except (ValueError, TypeError):
            return []
        out = []
        for d in data if isinstance(data, list) else []:
            if not isinstance(d, dict) or not isinstance(d.get("name"), str):
                continue
            e = {"name": d["name"]}
            for k in ("from", "to", "to_key", "out", "error"):
                if isinstance(d.get(k), str):
                    e[k] = d[k]
            e.setdefault("from", "?")
            e.setdefault("to", "—")
            e["at"] = float(d["at"]) if isinstance(d.get("at"), (int, float)) else 0.0
            out.append(e)
        return out[:20]

    def _int_setting(self, key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(self.settings.value(key, default))))
        except (TypeError, ValueError):
            return default

    def _save_history(self):
        self.settings.setValue("history", json.dumps(self.history[:20]))


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _file_filter() -> str:
    exts = " ".join(f"*.{e}" for f in FORMATS.values() if not f.output_only for e in f.exts)
    return f"All supported files ({exts});;All files (*)"

