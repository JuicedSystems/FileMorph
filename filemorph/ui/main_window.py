"""FileMorph main window: drop -> choose format -> convert -> done."""
from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import proc
from ..core.converters import build_registry
from ..core.converters.office import NEEDS_OFFICE, backend_name
from ..core.formats import CATEGORIES, CATEGORY_LABEL, FORMATS, SUGGESTED, detect
from . import theme as th
from .widgets import DropZone, FlowLayout, FormatBadge, FormatChip, IconCircle, ProgressRing, human_size, icon
from .worker import ConvertWorker, downloads_dir, scan_folder

MAX_FILES = 500
QUALITY_TARGETS = {"jpg", "webp", "avif", "mp4", "mov", "mkv", "webm"}
_BUILTIN_PDF_LAYOUT = {"html_to_pdf", "doc_to_pdf", "sheet_to_pdf"}


def label(text: str = "", role: str | None = None, size: float = 10, weight=QFont.Weight.Normal,
          display=False, wrap=False) -> QLabel:
    lb = QLabel(text)
    lb.setFont(th.ui_font(size, weight, display))
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


class ElidedLabel(QLabel):
    def __init__(self, text="", mode=Qt.ElideMiddle, **kw):
        super().__init__(**kw)
        self._full, self._mode = text, mode
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._apply()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._apply()

    def _apply(self):
        super().setText(QFontMetrics(self.font()).elidedText(self._full, self._mode, max(40, self.width())))


class DragOverlay(QWidget):
    """Shown over the window while files are dragged onto a non-empty state."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = t.q("bg")
        c.setAlpha(225)
        p.fillRect(self.rect(), c)
        pen = QPen(t.q("ink"), 2)
        pen.setDashPattern([5, 5])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(14, 14, -14, -14), 20, 20)
        p.setFont(th.ui_font(15, QFont.Weight.DemiBold, display=True))
        p.setPen(t.q("text"))
        p.drawText(self.rect(), Qt.AlignCenter, "Drop to add files")


# ======================================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("FileMorph")
        self.setAcceptDrops(True)
        self.resize(620, 720)
        self.setMinimumSize(480, 560)
        self.settings = QSettings("FileMorph", "FileMorph")
        self.registry = build_registry()
        self.files: list[Path] = []
        self.targets: dict[str, list] = {}
        self.selected: str | None = None
        self.thread: QThread | None = None
        self.worker: ConvertWorker | None = None
        self.results: list[tuple[Path, list[str], str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 20)
        root.setSpacing(12)
        root.addLayout(self._header())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.page_empty = self._build_empty()
        self.page_choose = self._build_choose()
        self.page_progress = self._build_progress()
        self.page_done = self._build_done()
        for pg in (self.page_empty, self.page_choose, self.page_progress, self.page_done):
            self.stack.addWidget(pg)
        self.overlay = DragOverlay(self)

        QShortcut(QKeySequence.Open, self, activated=self.browse)
        QShortcut(QKeySequence(Qt.Key_Return), self, activated=self._enter)
        QShortcut(QKeySequence(Qt.Key_Enter), self, activated=self._enter)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape)
        self.apply_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------ chrome
    def _header(self):
        h = QHBoxLayout()
        h.setSpacing(10)
        self.mark = QLabel()
        h.addWidget(self.mark)
        h.addWidget(label("FileMorph", size=13, weight=QFont.Weight.Bold, display=True))
        h.addStretch(1)
        self.header_hint = label("Private · works offline", "faint", 9)
        self.header_hint.setToolTip("Files are converted on this computer and never uploaded.")
        h.addWidget(self.header_hint)
        return h

    def apply_theme(self):
        t = th.current()
        from .widgets import app_icon_pixmap
        pm = app_icon_pixmap(64, on_dark=t.dark)
        pm.setDevicePixelRatio(2)
        self.mark.setPixmap(pm)
        QApplication.instance().setStyleSheet(th.stylesheet(t) + _checkbox_css(t))
        self._refresh_icons()
        for w in self.findChildren(QWidget):
            w.update()

    def _refresh_icons(self):
        t = th.current()
        self.clear_btn.setIcon(icon("x", t.q("muted"), 16))
        self.add_btn.setIcon(icon("plus", t.q("muted"), 16))
        self.save_btn.setIcon(icon("folder", t.q("muted"), 16))

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self.overlay.setGeometry(self.rect())

    # ------------------------------------------------------------ page: empty
    def _build_empty(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(14)
        self.drop = DropZone()
        self.drop.clicked.connect(self.browse)
        v.addWidget(self.drop, 1)
        cats = QHBoxLayout()
        cats.setSpacing(6)
        cats.addStretch(1)
        for key, _ in CATEGORIES:
            if key != "tools":  # SHRINK/OCR are things to do, not kinds of file you can drop
                cats.addWidget(_Pill(CATEGORY_LABEL[key], th.CATEGORY_COLOR[key]))
        cats.addStretch(1)
        v.addLayout(cats)
        sub = label("40+ formats including PDF, Word, Excel, PowerPoint, PNG, JPG, SVG, HEIC, MP3 and MP4",
                    "faint", 9, wrap=True)
        sub.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        return pg

    # ------------------------------------------------------------ page: choose
    def _build_choose(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # source file card
        self.file_card = QFrame(objectName="Card")
        fc = QVBoxLayout(self.file_card)
        fc.setContentsMargins(14, 12, 10, 12)
        fc.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.src_badge = FormatBadge(None, 44)
        top.addWidget(self.src_badge)
        txt = QVBoxLayout()
        txt.setSpacing(1)
        self.src_name = ElidedLabel()
        self.src_name.setFont(th.ui_font(11, QFont.Weight.DemiBold))
        self.src_meta = label("", "muted", 9)
        txt.addWidget(self.src_name)
        txt.addWidget(self.src_meta)
        top.addLayout(txt, 1)
        self.add_btn = QToolButton(objectName="Ghost", toolTip="Add more files (Ctrl+O)")
        self.add_btn.clicked.connect(self.browse)
        self.clear_btn = QToolButton(objectName="Ghost", toolTip="Start over (Esc)")
        self.clear_btn.clicked.connect(self.reset)
        top.addWidget(self.add_btn)
        top.addWidget(self.clear_btn)
        fc.addLayout(top)
        self.file_list = QWidget()
        self.file_list_l = QVBoxLayout(self.file_list)
        self.file_list_l.setContentsMargins(56, 0, 4, 0)
        self.file_list_l.setSpacing(2)
        fc.addWidget(self.file_list)
        v.addWidget(self.file_card)

        # "needs office" banner
        self.banner = QFrame(objectName="Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 10, 10)
        self.banner_text = label("", size=9, wrap=True)
        bl.addWidget(self.banner_text, 1)
        get_lo = QPushButton("Get LibreOffice", objectName="Small")
        get_lo.setCursor(Qt.PointingHandCursor)
        get_lo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.libreoffice.org/download/")))
        bl.addWidget(get_lo)
        v.addWidget(self.banner)

        head = QHBoxLayout()
        head.addWidget(label("Convert to", size=12, weight=QFont.Weight.DemiBold, display=True))
        head.addStretch(1)
        v.addLayout(head)

        # chips, in a scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chip_host = QWidget()
        self.chip_layout = QVBoxLayout(self.chip_host)
        self.chip_layout.setContentsMargins(0, 0, 6, 0)
        self.chip_layout.setSpacing(8)
        self.scroll.setWidget(self.chip_host)
        v.addWidget(self.scroll, 1)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chip_group.buttonToggled.connect(self._chip_toggled)

        # options
        self.options_box = QFrame(objectName="Card")
        self.options_l = QVBoxLayout(self.options_box)
        self.options_l.setContentsMargins(14, 10, 14, 10)
        self.options_l.setSpacing(8)
        v.addWidget(self.options_box)

        # footer
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.save_btn = QToolButton(objectName="Ghost")
        self.save_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.save_btn.setPopupMode(QToolButton.InstantPopup)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFont(th.ui_font(9.5))
        self.save_menu = QMenu(self)
        self.save_btn.setMenu(self.save_menu)
        self.save_menu.aboutToShow.connect(self._fill_save_menu)
        self._update_save_label()
        foot.addWidget(self.save_btn)
        foot.addStretch(1)
        self.convert_btn = QPushButton("Convert", objectName="Primary")
        self.convert_btn.setFont(th.ui_font(10.5, QFont.Weight.DemiBold))
        self.convert_btn.setCursor(Qt.PointingHandCursor)
        self.convert_btn.setMinimumWidth(190)
        self.convert_btn.clicked.connect(self.start)
        foot.addWidget(self.convert_btn)
        v.addLayout(foot)
        return pg

    # ------------------------------------------------------------ page: progress
    def _build_progress(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setSpacing(10)
        v.addStretch(2)
        self.ring = ProgressRing()
        v.addWidget(self.ring, 0, Qt.AlignHCenter)
        v.addSpacing(10)
        self.prog_title = label("Converting…", size=14, weight=QFont.Weight.DemiBold, display=True)
        self.prog_title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.prog_title)
        self.prog_file = ElidedLabel()
        self.prog_file.setAlignment(Qt.AlignCenter)
        self.prog_file.setFont(th.ui_font(10))
        v.addWidget(self.prog_file)
        self.prog_status = label("", "muted", 9.5)
        self.prog_status.setAlignment(Qt.AlignCenter)
        v.addWidget(self.prog_status)
        v.addStretch(3)
        self.cancel_btn = QPushButton("Cancel", objectName="Secondary")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFixedWidth(140)
        self.cancel_btn.clicked.connect(self.cancel)
        v.addWidget(self.cancel_btn, 0, Qt.AlignHCenter)
        return pg

    # ------------------------------------------------------------ page: done
    def _build_done(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)
        self.done_icon = IconCircle()
        v.addWidget(self.done_icon, 0, Qt.AlignHCenter)
        self.done_title = label("", size=16, weight=QFont.Weight.DemiBold, display=True)
        self.done_title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.done_title)
        self.done_sub = label("", "muted", 9.5, wrap=True)
        self.done_sub.setAlignment(Qt.AlignCenter)
        v.addWidget(self.done_sub)
        v.addSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.results_l = QVBoxLayout(host)
        self.results_l.setContentsMargins(0, 0, 6, 0)
        self.results_l.setSpacing(8)
        self.results_l.addStretch(1)
        sc.setWidget(host)
        v.addWidget(sc, 1)
        foot = QHBoxLayout()
        foot.setSpacing(10)
        again = QPushButton("Convert to another format", objectName="Secondary")
        again.setCursor(Qt.PointingHandCursor)
        again.clicked.connect(self._again)
        self.again_btn = again
        more = QPushButton("Convert more files", objectName="Primary")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(self.reset)
        foot.addWidget(again, 1)
        foot.addWidget(more, 1)
        v.addLayout(foot)
        return pg

    # ============================================================ files
    def browse(self):
        if self.stack.currentWidget() is self.page_progress:
            return
        start = str(self.files[0].parent) if self.files else self.settings.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert", start, _file_filter())
        if paths:
            self.settings.setValue("last_dir", str(Path(paths[0]).parent))
            self.add_files([Path(p) for p in paths], replace=self.stack.currentWidget() is not self.page_choose)

    def receive_paths(self, paths: list[Path]):
        """Files handed over from Explorer: queued during a conversion; a fresh batch on the
        Done page; added to the selection only while choosing a format."""
        if self.stack.currentWidget() is self.page_progress:
            self._queued = getattr(self, "_queued", []) + list(paths)
            return
        self.add_files(paths, replace=self.stack.currentWidget() is not self.page_choose)

    def add_files(self, paths: list[Path], replace: bool = False):
        if self.stack.currentWidget() is self.page_progress:
            return
        found: list[Path] = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                found += scan_folder(p, MAX_FILES - len(found))
            elif p.is_file():
                found.append(p)
        base = [] if replace else list(self.files)
        seen = {str(p.resolve()).lower() for p in base}
        unknown = []
        for p in found:
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            if detect(p) is None:
                unknown.append(p.name)
                continue
            seen.add(key)
            base.append(p)
        self.files = base[:MAX_FILES]
        if not self.files:
            if unknown:
                self._show_message("Unsupported file", f"FileMorph doesn't recognise {unknown[0]}.")
            return
        self._populate_choose(unknown)
        self.stack.setCurrentWidget(self.page_choose)
        self.activateWindow()
        self.raise_()

    def remove_file(self, p: Path):
        self.files = [f for f in self.files if f != p]
        if self.files:
            self._populate_choose([])
        else:
            self.reset()

    def reset(self):
        if self.stack.currentWidget() is self.page_progress:
            return
        self.files = []
        self.selected = None
        self.stack.setCurrentWidget(self.page_empty)

    # ============================================================ choose page
    def _populate_choose(self, unknown: list[str]):
        fmts = [detect(f) for f in self.files]
        counts = Counter(f.key for f in fmts)
        total = sum(f.stat().st_size for f in self.files if f.exists())
        if len(self.files) == 1:
            f, fm = self.files[0], fmts[0]
            self.src_badge.set_format(fm.key)
            self.src_name.setText(f.name)
            self.src_meta.setText(f"{fm.label} · {human_size(total)}")
        else:
            main = counts.most_common(1)[0][0]
            self.src_badge.set_format(main if len(counts) == 1 else None, str(len(self.files)))
            self.src_name.setText(f"{len(self.files)} files")
            kinds = ", ".join(f"{n} {FORMATS[k].ext.upper()}" for k, n in counts.most_common(3))
            more = " …" if len(counts) > 3 else ""
            self.src_meta.setText(f"{kinds}{more} · {human_size(total)}")
        if unknown:
            self.src_meta.setText(self.src_meta.text() + f"  ·  skipped {len(unknown)} unsupported")

        # list of files when several
        _clear_layout(self.file_list_l)
        self.file_list.setVisible(len(self.files) > 1)
        if len(self.files) > 1:
            for f in self.files[:6]:
                self.file_list_l.addWidget(_FileLine(f, self.remove_file))
            if len(self.files) > 6:
                self.file_list_l.addWidget(label(f"and {len(self.files) - 6} more", "faint", 9))

        # targets common to every file
        # A file already in the target format is fine in a batch (kept as-is, or merged when combining).
        sets = [set(self.registry.targets(k)) | ({k} if len(self.files) > 1 else set()) for k in counts]
        common = set.intersection(*sets)
        primary = counts.most_common(1)[0][0]
        self.targets = {k: self.registry.plan(primary, k) or [] for k in common}

        # office banner
        missing = [k for k in counts if k in NEEDS_OFFICE] if backend_name() is None else []
        if missing:
            ext = ", ".join("." + FORMATS[k].ext for k in missing)
            self.banner_text.setText(f"More options for {ext} files unlock with Microsoft Office or the free "
                                     f"LibreOffice installed.")
        self.banner.setVisible(bool(missing))
        self._build_chips(primary)

    def _build_chips(self, primary: str):
        for b in self.chip_group.buttons():
            self.chip_group.removeButton(b)
        _clear_layout(self.chip_layout)
        if not self.targets:
            msg = ("These files don't share a format they can all be converted to. Try converting them in "
                   "separate groups." if len(self.files) > 1 else "There's nothing this file can be converted to yet.")
            m = label(msg, "muted", 10, wrap=True)
            self.chip_layout.addWidget(m)
            self.chip_layout.addStretch(1)
            self.selected = None
            self._update_options()
            return

        suggested = [k for k in SUGGESTED.get(primary, []) if k in self.targets][:5]
        if suggested:
            self.chip_layout.addWidget(label("POPULAR", "section", 8, QFont.Weight.DemiBold))
            self.chip_layout.addWidget(self._chip_row(suggested, large=True))
        for cat, cat_label in CATEGORIES:
            keys = [k for k in FORMATS if k in self.targets and FORMATS[k].category == cat and k not in suggested]
            if keys:
                self.chip_layout.addSpacing(4)
                self.chip_layout.addWidget(label(cat_label.upper(), "section", 8, QFont.Weight.DemiBold))
                self.chip_layout.addWidget(self._chip_row(keys))
        self.chip_layout.addStretch(1)

        keep = self.selected if self.selected in self.targets else None
        choice = keep or (suggested[0] if suggested else next(iter(sorted(self.targets))))
        for b in self.chip_group.buttons():
            if b.fmt.key == choice:
                b.setChecked(True)
        self.selected = choice
        self._update_options()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(0))

    def _chip_row(self, keys: list[str], large=False) -> QWidget:
        host = QWidget()
        fl = FlowLayout(host, spacing=8)
        for k in keys:
            chip = FormatChip(k, large)
            self.chip_group.addButton(chip)
            chip.activated.connect(self.start)  # double-click = convert right away
            fl.addWidget(chip)
        return host

    def _chip_toggled(self, btn, checked):
        if checked:
            self.selected = btn.fmt.key
            self._update_options()

    # ------------------------------------------------------------ options
    def _update_options(self):
        _clear_layout(self.options_l)
        for w in getattr(self, "opt_widgets", {}).values():
            if isinstance(w, QButtonGroup):
                w.deleteLater()  # groups are owned by the window, not the cleared layout
        self.opt_widgets = {}
        dst = self.selected
        self.convert_btn.setEnabled(dst is not None)
        if dst is None:
            self.convert_btn.setText("Convert")
            self.options_box.hide()
            return
        n = len(self.files)
        self.convert_btn.setText(f"Convert {'all ' if n > 1 else ''}to {FORMATS[dst].tag}")
        src_cats = {detect(f).category for f in self.files}
        src_keys = {detect(f).key for f in self.files}
        plan_fns = {e.fn.__name__ for k in src_keys for e in (self.registry.plan(k, dst) or [])}
        rows = 0

        if n > 1 and dst == "pdf":
            cb = QCheckBox("Combine into a single PDF")
            cb.setFont(th.ui_font(9.5))
            cb.setChecked(self.settings.value("combine_pdf", False, type=bool))
            cb.toggled.connect(lambda on: self.settings.setValue("combine_pdf", on))
            self.opt_widgets["combine"] = cb
            self.options_l.addWidget(cb)
            rows += 1
        if dst in QUALITY_TARGETS:
            self.options_l.addLayout(self._quality_row())
            rows += 1
        if dst in ("png", "jpg", "webp", "tiff") and src_cats & {"document", "sheet", "slides"}:
            self.options_l.addLayout(self._segmented("Resolution", "dpi",
                                                     [("Screen", 96), ("Standard", 150), ("Print", 300)], 150))
            rows += 1
        if dst == "svg" and "image" in src_cats and "svg" not in src_keys:
            self.options_l.addLayout(self._segmented("Detail", "svg_detail",
                                                     [("Simple", "simple"), ("Balanced", "balanced"),
                                                      ("Detailed", "detailed")], "balanced"))
            rows += 1
        if dst == "trace":
            self.options_l.addLayout(self._segmented("Detail", "trace_detail",
                                                     [("Bold", "bold"), ("Balanced", "balanced"), ("Fine", "fine")],
                                                     "balanced"))
            self.options_l.addLayout(self._segmented("Darkness", "trace_darkness",
                                                     [("Lighter", -25), ("Auto", 0), ("Darker", 25)], 0))
            rows += 2
        if dst == "pdf" and plan_fns & _BUILTIN_PDF_LAYOUT:
            self.options_l.addLayout(self._segmented("Page size", "page_size",
                                                     [("Letter", "letter"), ("A4", "a4")], "letter"))
            rows += 1
        if dst == "gif" and src_cats & {"video"}:
            self.options_l.addLayout(self._segmented("Width", "gif_width",
                                                     [("Small", 360), ("Medium", 640), ("Large", 960)], 640))
            rows += 1
        if any(e.engine in ("msoffice", "libreoffice") for k in src_keys for e in (self.registry.plan(k, dst) or [])):
            note = label(f"Uses {backend_name()} for best fidelity", "faint", 8.5)
            self.options_l.addWidget(note)
            rows += 1
        self.options_box.setVisible(rows > 0)

    def _quality_row(self):
        h = QHBoxLayout()
        h.addWidget(label("Quality", size=9.5))
        s = QSlider(Qt.Horizontal)
        s.setRange(50, 100)
        s.setValue(int(self.settings.value("quality", 90)))
        s.setCursor(Qt.PointingHandCursor)
        val = label(str(s.value()), "muted", 9.5)
        val.setFixedWidth(26)
        s.valueChanged.connect(lambda x: (val.setText(str(x)), self.settings.setValue("quality", x)))
        self.opt_widgets["quality"] = s
        h.addWidget(s, 1)
        h.addWidget(val)
        return h

    def _segmented(self, title: str, key: str, choices: list[tuple[str, object]], default):
        h = QHBoxLayout()
        h.setSpacing(0)
        h.addWidget(label(title, size=9.5))
        h.addSpacing(12)
        h.addStretch(1)
        grp = QButtonGroup(self)
        saved = self.settings.value(f"opt_{key}", default)
        values = [c[1] for c in choices]
        try:
            saved = type(default)(saved) if saved is not None else default
        except (TypeError, ValueError):  # damaged setting
            saved = default
        if saved not in values:
            saved = default
        for i, (text, value) in enumerate(choices):
            b = QPushButton(text, objectName="Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(th.ui_font(9))
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(choices) - 1 else "mid")
            b.setProperty("value", value)
            b.setChecked(value == saved)
            grp.addButton(b)
            h.addWidget(b)
        grp.buttonClicked.connect(lambda b: self.settings.setValue(f"opt_{key}", b.property("value")))
        self.opt_widgets[key] = grp
        return h

    def _collect_options(self) -> dict:
        opts: dict = {}
        for key, w in getattr(self, "opt_widgets", {}).items():
            if isinstance(w, QSlider):
                opts[key] = w.value()
            elif isinstance(w, QButtonGroup) and w.checkedButton():
                opts[key] = w.checkedButton().property("value")
        return opts

    # ------------------------------------------------------------ save location
    def _out_dir(self) -> Path | None:
        mode = self.settings.value("save_mode", "same")
        if mode == "downloads":
            return downloads_dir()
        if mode == "custom":
            d = self.settings.value("save_dir", "")
            if d and Path(d).exists():
                return Path(d)
        return None  # same folder as each original

    def _update_save_label(self):
        d = self._out_dir()
        name = "Same folder as original" if d is None else ("Downloads" if d == downloads_dir() else d.name or str(d))
        self.save_btn.setText(f"Save to: {name}")
        self.save_btn.setToolTip(str(d) if d else "Each converted file is saved next to its original")

    def _fill_save_menu(self):
        self.save_menu.clear()
        mode = self.settings.value("save_mode", "same")
        for key, text in (("same", "Same folder as original"), ("downloads", "Downloads")):
            a = QAction(text, self.save_menu, checkable=True, checked=mode == key)
            a.triggered.connect(lambda _=False, k=key: self._set_save_mode(k))
            self.save_menu.addAction(a)
        custom = self.settings.value("save_dir", "")
        if custom:
            a = QAction(Path(custom).name or custom, self.save_menu, checkable=True, checked=mode == "custom")
            a.triggered.connect(lambda: self._set_save_mode("custom"))
            self.save_menu.addAction(a)
        self.save_menu.addSeparator()
        choose = QAction("Choose folder…", self.save_menu)
        choose.triggered.connect(self._choose_folder)
        self.save_menu.addAction(choose)

    def _set_save_mode(self, mode):
        self.settings.setValue("save_mode", mode)
        self._update_save_label()

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Save converted files to",
                                             self.settings.value("save_dir", str(Path.home())))
        if d:
            self.settings.setValue("save_dir", d)
            self._set_save_mode("custom")

    # ============================================================ convert
    def start(self):
        if not self.files or not self.selected:
            return
        combine = bool(self.opt_widgets.get("combine") and self.opt_widgets["combine"].isChecked())
        self.results = [(f, [], "") for f in self.files] if not combine else [(self.files[0], [], "")]
        self.ring.reset()
        self.prog_title.setText("Converting…")
        self.prog_status.setText("")
        self._job_count = 1 if combine else len(self.files)
        self._combine = combine
        self.stack.setCurrentWidget(self.page_progress)
        self._on_progress(0, 0.0, "Starting")

        self.thread = QThread(self)
        self.worker = ConvertWorker(list(self.files), self.selected, self._out_dir(), self._collect_options(), combine)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.cancel_btn.setEnabled(True)
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.prog_status.setText("Stopping…")

    def _on_progress(self, i: int, frac: float, msg: str):
        n = self._job_count
        dst = FORMATS[self.selected].tag
        if self._combine:
            self.prog_file.setText(f"{len(self.files)} files → one PDF")
        else:
            self.prog_file.setText(f"{self.files[i].name}  →  {dst}")
            if n > 1:
                self.prog_title.setText(f"Converting {i + 1} of {n}")
        self.prog_status.setText(msg)
        self.ring.set_progress((i + frac) / n)

    def _on_file_done(self, i: int, outs: list, err: str):
        f = self.results[i][0]
        self.results[i] = (f, outs, err)

    def _on_finished(self, cancelled: bool):
        self.worker = None
        self.thread = None
        if cancelled:
            self.ring.reset()
            self.stack.setCurrentWidget(self.page_choose)
            self._drain_queue()
            return
        self.ring.set_progress(1.0)
        QTimer.singleShot(250, self._show_results)

    def _show_results(self):
        while self.results_l.count() > 1:
            w = self.results_l.takeAt(0).widget()
            if w:
                _dispose(w)
        ok = [r for r in self.results if r[1]]
        bad = [r for r in self.results if r[2]]
        n_out = sum(len(r[1]) for r in ok)
        dst = FORMATS[self.selected].tag
        if not bad:
            self.done_icon.set("check", "success")
            self.done_title.setText("Done!")
            what = f"{n_out} {dst} file{'s' if n_out != 1 else ''}"
            folder = Path(ok[0][1][0]).parent if ok else None
            self.done_sub.setText(f"Created {what} in {folder.name or folder}" if folder else "")
        elif not ok:
            self.done_icon.set("alert", "danger")
            self.done_title.setText("Couldn't convert" if len(bad) == 1 else "Nothing was converted")
            self.done_sub.setText("See the details below.")
        else:
            self.done_icon.set("check", "warn")
            self.done_title.setText(f"{len(ok)} of {len(self.results)} converted")
            self.done_sub.setText(f"{len(bad)} file{'s' if len(bad) > 1 else ''} couldn't be converted — see below.")
        idx = 0
        shown = 0
        for src, outs, err in self.results:
            if err:
                self.results_l.insertWidget(idx, _ResultRow(src, None, err))
                idx += 1
            for o in outs:
                if shown >= 60:
                    break
                self.results_l.insertWidget(idx, _ResultRow(src, Path(o), ""))
                idx += 1
                shown += 1
        if n_out > shown:
            self.results_l.insertWidget(idx, label(f"and {n_out - shown} more files", "faint", 9))
        self.again_btn.setVisible(bool(self.files))
        self.stack.setCurrentWidget(self.page_done)
        QApplication.alert(self)  # flash the taskbar if the window is in the background
        self._drain_queue()

    def _drain_queue(self):
        queued, self._queued = getattr(self, "_queued", []), []
        if queued:
            QTimer.singleShot(1500, lambda: self.add_files(queued, replace=True))

    def _again(self):
        self._populate_choose([])
        self.stack.setCurrentWidget(self.page_choose)

    # ============================================================ keyboard & drop
    def _enter(self):
        if self.stack.currentWidget() is self.page_choose and self.convert_btn.isEnabled():
            self.start()
        elif self.stack.currentWidget() is self.page_empty:
            self.browse()

    def _escape(self):
        cur = self.stack.currentWidget()
        if cur is self.page_progress:
            self.cancel()
        elif cur is self.page_choose or cur is self.page_done:
            self.reset()

    def _show_message(self, title, text):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, title, text)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()) \
                and self.stack.currentWidget() is not self.page_progress:
            e.acceptProposedAction()
            if self.stack.currentWidget() is self.page_empty:
                self.drop.set_active(True)
            else:
                self.overlay.setGeometry(self.rect())
                self.overlay.show()
                self.overlay.raise_()

    def dragLeaveEvent(self, e):  # noqa: N802
        self.drop.set_active(False)
        self.overlay.hide()

    def dropEvent(self, e):  # noqa: N802
        self.drop.set_active(False)
        self.overlay.hide()
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            replace = self.stack.currentWidget() is not self.page_choose
            self.add_files(paths, replace=replace)

    def closeEvent(self, e):  # noqa: N802
        if self.worker:
            self.worker.cancel()
            proc.kill_all(final=True)
            if self.thread:
                self.thread.quit()
            if self.thread and self.thread.isRunning() and not self.thread.wait(6000):
                os._exit(0)  # a step that can't be interrupted: exit rather than let Qt abort
        super().closeEvent(e)


# ======================================================================
class _Pill(QLabel):
    def __init__(self, text, color):
        super().__init__(text)
        self.color = color
        self.setFont(th.ui_font(8.5, QFont.Weight.DemiBold))
        self.setContentsMargins(18, 4, 10, 4)

    def paintEvent(self, e):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(t.q("border"), 1))
        p.setBrush(t.q("surface"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self.height() / 2, self.height() / 2)
        from PySide6.QtGui import QColor
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(10 - 3, self.height() // 2 - 3, 6, 6)
        p.setPen(t.q("muted"))
        p.setFont(self.font())
        p.drawText(self.rect().adjusted(18, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class _FileLine(QWidget):
    def __init__(self, path: Path, on_remove):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(FormatBadge(detect(path).key, 20))
        name = ElidedLabel(path.name)
        name.setFont(th.ui_font(9))
        h.addWidget(name, 1)
        size = label(human_size(path.stat().st_size) if path.exists() else "", "faint", 8.5)
        h.addWidget(size)
        x = QToolButton(objectName="Ghost", toolTip="Remove")
        x.setIcon(icon("x", th.current().q("faint"), 12))
        x.setIconSize(QSize(12, 12))
        x.setCursor(Qt.PointingHandCursor)
        x.clicked.connect(lambda: on_remove(path))
        h.addWidget(x)


class _ResultRow(QFrame):
    def __init__(self, src: Path, out: Path | None, err: str):
        super().__init__(objectName="Card")
        t = th.current()
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 10, 10)
        h.setSpacing(12)
        if out:
            fm = detect(out)
            h.addWidget(FormatBadge(fm.key if fm else None, 36, None if fm else out.suffix[1:4] or "DIR"), 0, Qt.AlignTop)
        else:
            ic = QLabel()
            ic.setPixmap(icon("alert", t.q("danger"), 28).pixmap(28, 28))
            ic.setFixedSize(36, 36)
            ic.setAlignment(Qt.AlignCenter)
            h.addWidget(ic, 0, Qt.AlignTop)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        name = ElidedLabel((out or src).name)
        name.setFont(th.ui_font(10, QFont.Weight.DemiBold))
        txt.addWidget(name)
        if out:
            size = human_size(out.stat().st_size) if out.exists() and out.is_file() else "folder"
            meta = ElidedLabel(f"{size} · {out.parent}", Qt.ElideMiddle)
            meta.setFont(th.ui_font(8.5))
            meta.setProperty("role", "muted")
            txt.addWidget(meta)
        else:
            msg = label(err, "error", 9, wrap=True)
            msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
            txt.addWidget(msg)
        h.addLayout(txt, 1)
        if out:
            op = QPushButton("Open", objectName="Small")
            op.setCursor(Qt.PointingHandCursor)
            op.setFont(th.ui_font(9, QFont.Weight.DemiBold))
            op.clicked.connect(lambda: open_path(out))
            fo = QPushButton(objectName="Small", toolTip="Show in folder")
            fo.setIcon(icon("folder", t.q("text"), 16))
            fo.setCursor(Qt.PointingHandCursor)
            fo.clicked.connect(lambda: reveal_path(out))
            h.addWidget(op, 0, Qt.AlignVCenter)
            h.addWidget(fo, 0, Qt.AlignVCenter)


def _checkbox_css(t) -> str:
    """Qt stylesheets can't draw a tick, so render one to a small PNG and reference it."""
    import tempfile
    path = Path(tempfile.gettempdir()) / f"filemorph-check-{'d' if t.dark else 'l'}.png"
    if not path.exists():
        icon("check", t.q("ink_text"), 18, 2.6).pixmap(36, 36).save(str(path))
    return f"QCheckBox::indicator:checked {{ image: url({path.as_posix()}); }}"


def _dispose(w: QWidget):
    """Remove a widget right now (deleteLater alone leaves it painted until the next loop pass)."""
    w.hide()
    w.setParent(None)
    w.deleteLater()


def _clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            _dispose(it.widget())
        elif it.layout():
            _clear_layout(it.layout())


def _file_filter() -> str:
    groups = []
    all_exts = []
    for cat, cat_label in CATEGORIES:
        exts = [f"*.{e}" for f in FORMATS.values() if f.category == cat and not f.output_only for e in f.exts]
        if not exts:
            continue
        all_exts += exts
        groups.append(f"{cat_label} ({' '.join(exts)})")
    return ";;".join([f"All supported files ({' '.join(all_exts)})"] + groups + ["All files (*)"])


def open_path(p: Path):
    if sys.platform == "win32":
        os.startfile(str(p))  # noqa: S606
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def reveal_path(p: Path):
    if sys.platform == "win32":
        # one pre-quoted argument: Explorer splits /select on commas, so paths must be quoted
        subprocess.Popen(f'explorer /select,"{p}"')  # noqa: S603,S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])  # noqa: S603,S607
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
