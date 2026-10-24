"""Background conversion so the window never freezes."""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from ..core.engine import convert_file, fallback_dir, merge_to_pdf
from ..core.formats import detect
from ..core.recipes import render_name
from ..core.registry import Cancelled, ConversionError


def downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    return d if d.exists() else Path.home()


def can_write(folder: Path) -> bool:
    """Actually try: os.access() says yes to read-only shares, OneDrive placeholders and folders
    protected by Windows' Controlled Folder Access."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".filemorph-", suffix=".tmp"):
            pass
        return True
    except OSError:
        return False


def writable_dir(preferred: Path) -> Path:
    """Use the preferred folder if we can write there, else Downloads/FileMorph."""
    if can_write(preferred):
        return preferred
    fallback = fallback_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def scan_folder(root: Path, limit: int) -> list[Path]:
    """Convertible files under a folder, in a stable order, stopping as soon as `limit` is
    reached (so dropping C:\\ or a huge photo library doesn't freeze the app)."""
    out: list[Path] = []
    stack = [root]
    while stack and len(out) < limit:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        subdirs = []
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith((".", "$")):
                        subdirs.append(Path(e.path))
                elif e.is_file() and detect(Path(e.path)):
                    out.append(Path(e.path))
                    if len(out) >= limit:
                        break
            except OSError:
                continue
        stack.extend(reversed(subdirs))
    return out


class ConvertWorker(QObject):
    progress = Signal(int, float, str)   # file index, fraction of that file, status text
    file_done = Signal(int, list, str)   # file index, output paths, error message ("" = ok)
    finished = Signal(bool)              # True if cancelled

    def __init__(self, files: list[Path], dst_fmt: str, out_dir: Path | None, options: dict, combine: bool,
                 rename: str = ""):
        super().__init__()
        self.files = files
        self.dst = dst_fmt
        self.out_dir = out_dir
        self.options = options
        self.combine = combine
        self.rename = rename  # a recipe's name pattern ("{name} {date}"), "" = the usual names
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def _dir_for(self, f: Path) -> Path:
        return writable_dir(self.out_dir or f.parent)

    @Slot()
    def run(self):
        i = 0
        try:
            if self.combine:
                self._run_combined()
            else:
                for i, f in enumerate(self.files):
                    if self.cancel_event.is_set():
                        raise Cancelled()
                    self.progress.emit(i, 0.0, "Starting")
                    fmt = detect(f)
                    if fmt and fmt.key == self.dst:  # already in the target format: keep the original
                        self.file_done.emit(i, [str(f)], "")
                        continue
                    try:
                        outs = convert_file(f, self.dst, self._dir_for(f), self.options,
                                            lambda frac, msg, _i=i: self.progress.emit(_i, frac, msg),
                                            self.cancel_event, render_name(self.rename, f, i + 1))
                        self.file_done.emit(i, [str(o) for o in outs], "")
                    except ConversionError as e:
                        self.file_done.emit(i, [], str(e))
        except Cancelled:
            self.finished.emit(True)
            return
        except Exception as e:  # never let the thread die silently
            self.file_done.emit(i, [], f"Unexpected error: {e}")
        self.finished.emit(False)

    def _run_combined(self):
        first = self.files[0]
        name = f"{first.stem} (combined).pdf" if len(self.files) > 1 else f"{first.stem}.pdf"
        out = self._dir_for(first) / name
        try:
            outs = merge_to_pdf(self.files, out, self.options,
                                lambda frac, msg: self.progress.emit(0, frac, msg), self.cancel_event)
            self.file_done.emit(0, [str(o) for o in outs], "")
        except ConversionError as e:
            self.file_done.emit(0, [], str(e))
