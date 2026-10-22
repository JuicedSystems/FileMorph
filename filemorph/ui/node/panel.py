"""The expanded mini window (canvas main board): glass panel with drop zone, recent conversions,
save toggle — plus an "All formats" page for everything that doesn't fit the node's pill."""
from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient, QRegion)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from ...core.formats import CATEGORIES, FORMATS
from . import motion as mo
from . import style as st

PW, PH = 340, 486      # panel box (canvas size)
M = 34                 # transparent margin for the drop shadow


def _icon_path(name: str) -> QPainterPath:
    p = QPainterPath()
    if name == "pin":
        p.moveTo(12, 16); p.lineTo(12, 22)
        p.moveTo(8.5, 3); p.lineTo(15.5, 3); p.lineTo(14.5, 9); p.lineTo(18, 13); p.lineTo(6, 13); p.lineTo(9.5, 9)
        p.closeSubpath()
    elif name == "minus":
        p.moveTo(5, 12); p.lineTo(19, 12)
    elif name == "upload":
        p.moveTo(12, 15); p.lineTo(12, 4)
        p.moveTo(7, 8.5); p.lineTo(12, 4); p.lineTo(17, 8.5)
        p.moveTo(5, 20); p.lineTo(19, 20)
    elif name == "back":
        p.moveTo(15, 5); p.lineTo(8, 12); p.lineTo(15, 19)
    elif name == "more":
        for x in (6, 12, 18):
            p.addEllipse(QPointF(x, 12), 0.9, 0.9)
    elif name == "check":
        p.moveTo(5.5, 12.5); p.lineTo(9.7, 16.7); p.lineTo(18.5, 7.3)
    elif name == "alert":
        p.addEllipse(QPointF(12, 12), 9, 9)
        p.moveTo(12, 7.5); p.lineTo(12, 12.8); p.moveTo(12, 16.3); p.lineTo(12, 16.4)
    elif name == "folder":
        p.moveTo(3.5, 7); p.quadTo(3.5, 5, 5.5, 5); p.lineTo(9.5, 5); p.lineTo(11.5, 7.5); p.lineTo(18.5, 7.5)
        p.quadTo(20.5, 7.5, 20.5, 9.5); p.lineTo(20.5, 17); p.quadTo(20.5, 19, 18.5, 19); p.lineTo(5.5, 19)
        p.quadTo(3.5, 19, 3.5, 17); p.closeSubpath()
    return p


def draw_icon(p: QPainter, name: str, center: QPointF, size: float, color: QColor, width: float = 1.8):
    p.save()
    p.translate(center)
    p.scale(size / 24, size / 24)
    p.translate(-12, -12)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(_icon_path(name))
    p.restore()


def paint_orb(p: QPainter, c: QPointF, d: float, colors, spin: float, blur_like: bool = True):
    """Small conic orb (header mini orb / tray)."""
    path = QPainterPath()
    path.addEllipse(c, d / 2, d / 2)
    p.save()
    p.setClipPath(path)
    g = QConicalGradient(c, -spin + 90)
    c1, c2, c3 = (QColor(x) for x in colors)
    g.setColorAt(0, c1); g.setColorAt(1 / 3, c3); g.setColorAt(2 / 3, c2); g.setColorAt(1, c1)
    p.fillRect(QRectF(c.x() - d, c.y() - d, 2 * d, 2 * d), QBrush(g))
    if blur_like:  # soft highlight in place of the CSS blur
        rg = QRadialGradient(QPointF(c.x() - d * 0.18, c.y() - d * 0.25), d * 0.7)
        rg.setColorAt(0, QColor(255, 255, 255, 70))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(c.x() - d, c.y() - d, 2 * d, 2 * d), QBrush(rg))
    p.restore()


# ------------------------------------------------------------------ small widgets
class IconButton(QAbstractButton):
    def __init__(self, icon: str, tip: str, checkable=False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCheckable(checkable)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        if self._hover or on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(255 * (0.1 if on and not self._hover else 0.08))))
            p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        col = QColor("#ffffff") if (self._hover or on) else QColor(st.DIM)
        draw_icon(p, self.icon_name, QPointF(20, 20), 18, col)
        if self.hasFocus():
            p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)


class Switch(QAbstractButton):
    """40x24 track, knob springs across (canvas .sw)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.knob = mo.Tween(0, 0.5)
        self.toggled.connect(lambda on: self.knob.to(16 if on else 0))
        self._t = QTimer(self, interval=16, timeout=self.update)
        self.toggled.connect(lambda _: self._t.start())

    def setChecked(self, on):  # noqa: N802
        super().setChecked(on)
        self.knob.set(16 if on else 0)

    def paintEvent(self, _):  # noqa: N802
        if not self.knob.active:
            self._t.stop()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.knob.value() / 16
        off, on = QColor(255, 255, 255, 41), QColor(st.SWITCH_ON)
        col = QColor.fromRgbF(off.redF() + (on.redF() - off.redF()) * min(1, max(0, k)),
                              off.greenF() + (on.greenF() - off.greenF()) * min(1, max(0, k)),
                              off.blueF() + (on.blueF() - off.blueF()) * min(1, max(0, k)),
                              off.alphaF() + (on.alphaF() - off.alphaF()) * min(1, max(0, k)))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 0, 40, 24), 12, 12)
        for i in range(3):  # knob shadow
            p.setBrush(QColor(0, 0, 0, 30 - i * 8))
            p.drawEllipse(QPointF(12 + self.knob.value(), 13 + i * 0.5), 9 + i, 9 + i)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(12 + self.knob.value(), 12), 9, 9)
        if self.hasFocus():
            p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(-1, -1, 42, 26), 13, 13)


class MiniOrb(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setFixedSize(34, 24)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_orb(p, QPointF(16, 12), 24, self.panel.colors, self.panel.spin)


class DropZone(QAbstractButton):
    """168px zone: dashed border + rotating gradient ring, icon tile, title, 'browse' link."""
    files_dropped = Signal(list)

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setFixedHeight(168)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Drop a file to convert, or browse your files")
        self.over = False
        self.grow = mo.Tween(1, 0.5)
        self.lift = mo.Tween(0, 0.5)
        self.ang = 0.0
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.lift.to(1)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        if not self.over:
            self.lift.to(0)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.over = True
            self.grow.to(1.025); self.lift.to(1)

    def dragLeaveEvent(self, e):  # noqa: N802
        self.over = False
        self.grow.to(1); self.lift.to(1 if self._hover else 0)

    def dropEvent(self, e):  # noqa: N802
        self.over = False
        self.grow.to(1); self.lift.to(0)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.files_dropped.emit(paths)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = self.grow.value()
        p.translate(r.center())
        p.scale(g, g)
        p.translate(-r.center())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * (0.07 if self.over else 0.025))))
        p.drawRoundedRect(r, 18, 18)
        pen = QPen(QColor(255, 255, 255, int(255 * 0.14)), 1.5)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 18, 18)
        # rotating comet ring: conic(transparent 0 58%, c1 72%, c2 84%, transparent 96%)
        c1, c2, _ = (QColor(x) for x in self.panel.colors)
        cg = QConicalGradient(r.center(), -self.ang + 90)
        t = QColor(c1); t.setAlpha(0)
        stops = [(0, t), (0.04, t), (0.16, c2), (0.28, c1), (0.42, QColor(c1.red(), c1.green(), c1.blue(), 0)),
                 (1, t)]
        for pos, col in stops:  # Qt runs counter-clockwise, so the CSS stops are mirrored
            cg.setColorAt(pos, col)
        p.setPen(QPen(QBrush(cg), 1.5))
        p.drawRoundedRect(r, 18, 18)
        if self.hasFocus():
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 20, 20)
        # icon tile
        lift = self.lift.value()
        cy = r.top() + 50 - 4 * lift
        s = 1 + 0.08 * lift
        tile = QRectF(-24 * s, -24 * s, 48 * s, 48 * s).translated(r.center().x(), cy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.07)))
        p.drawRoundedRect(tile, 14 * s, 14 * s)
        draw_icon(p, "upload", tile.center(), 22, QColor(st.INK))
        p.setFont(st.font(14, 600))
        p.setPen(QColor(st.INK))
        p.drawText(QRectF(r.left(), r.top() + 94, r.width(), 20), Qt.AlignCenter, "Drop a file to convert")
        f = st.font(12)
        p.setFont(f)
        fm = QFontMetricsF(f)
        a, b = "or ", "browse"
        c = " your files"
        total = fm.horizontalAdvance(a + b + c)
        x = r.center().x() - total / 2
        y = r.top() + 124
        p.setPen(QColor(st.DIM))
        p.drawText(QPointF(x, y + fm.ascent()), a)
        x += fm.horizontalAdvance(a)
        p.setPen(QColor(st.INK))
        p.drawText(QPointF(x, y + fm.ascent()), b)
        p.setPen(QPen(QColor(255, 255, 255, 102), 1))
        p.drawLine(QPointF(x, y + fm.ascent() + 3), QPointF(x + fm.horizontalAdvance(b), y + fm.ascent() + 3))
        x += fm.horizontalAdvance(b)
        p.setPen(QColor(st.DIM))
        p.drawText(QPointF(x, y + fm.ascent()), c)


class RecentRow(QAbstractButton):
    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.e = entry
        self.err = bool(entry.get("error"))
        self.setFixedHeight(56 if self.err else 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(entry.get("error") or entry.get("out", ""))
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect())
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 13))
            p.drawRoundedRect(r, 12, 12)
        top = 22 if not self.err else 18
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(st.DANGER) if self.err else st.kind_color(self.e.get("to_key")))
        p.drawEllipse(QPointF(12, top), 4, 4)
        # right side: ago, conversion
        fa = st.font(11)
        p.setFont(fa)
        p.setPen(QColor(st.LABEL))
        p.drawText(QRectF(r.right() - 60, top - 10, 52, 20), Qt.AlignRight | Qt.AlignVCenter, _ago(self.e.get("at", 0)))
        fc = st.font(10, 600, mono=True)
        conv = f"{self.e.get('from', '')} → {self.e.get('to', '')}"
        cw = QFontMetricsF(fc).horizontalAdvance(conv)
        p.setFont(fc)
        p.setPen(QColor(st.DIM))
        p.drawText(QRectF(r.right() - 64 - cw, top - 10, cw + 2, 20), Qt.AlignVCenter | Qt.AlignLeft, conv)
        fn = st.font(13)
        p.setFont(fn)
        p.setPen(QColor(st.INK))
        avail = r.width() - 26 - 72 - cw
        name = QFontMetricsF(fn).elidedText(self.e.get("name", ""), Qt.ElideMiddle, avail)
        p.drawText(QRectF(26, top - 10, avail, 20), Qt.AlignVCenter | Qt.AlignLeft, name)
        if self.err:
            fe = st.font(11)
            p.setFont(fe)
            p.setPen(QColor(st.DANGER))
            msg = QFontMetricsF(fe).elidedText(self.e["error"].split("\n")[0], Qt.ElideRight, r.width() - 34)
            p.drawText(QRectF(26, top + 9, r.width() - 34, 18), Qt.AlignVCenter | Qt.AlignLeft, msg)


def _ago(at: float) -> str:
    secs = max(0, int(time.time() - at))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


class FormatTile(QAbstractButton):
    """Chip in the All formats page — same language as the node's pill chips."""

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setFixedSize(66, 40)
        self.setCursor(Qt.PointingHandCursor)
        f = FORMATS[key]
        self.setToolTip(f"{f.label} (.{f.ext})")
        self.setAccessibleName(f"Convert to {f.label}")
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        p.setPen(QPen(QColor(255, 255, 255, 140 if on else 20), 1))
        p.setBrush(QColor(st.INDICATOR) if on else QColor(255, 255, 255, 20 if self._hover else 10))
        p.drawRoundedRect(r, 12, 12)
        p.setFont(st.font(12, 600, mono=True, spacing_em=0.04))
        p.setPen(QColor("#0a0b10") if on else QColor(st.INK))
        p.drawText(r, Qt.AlignCenter, FORMATS[self.key].ext.upper())
        if self.hasFocus():
            p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 13, 13)


class PrimaryButton(QAbstractButton):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect())
        en = self.isEnabled()
        if en and self._hover:
            for i in range(5):
                g = 2 + i * 3
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(255 * 0.05 * (1 - i / 5))))
                p.drawRoundedRect(r.adjusted(4 - g / 2, 4 - g / 2, g / 2 - 4, g / 2 - 4), 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(st.INDICATOR) if en else QColor(255, 255, 255, 30))
        p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 20, 20)
        p.setFont(st.font(14, 600))
        p.setPen(QColor("#0a0b10") if en else QColor(st.LABEL))
        p.drawText(r, Qt.AlignCenter, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 23, 23)


class FlowBox(QWidget):
    """Fixed-width wrapping grid of tiles (no layout engine surprises)."""

    def __init__(self, widgets: list[QWidget], width: int, gap: int = 6, parent=None):
        super().__init__(parent)
        x = y = 0
        rowh = 0
        for w in widgets:
            w.setParent(self)
            sz = w.size()
            if x and x + sz.width() > width:
                x, y = 0, y + rowh + gap
                rowh = 0
            w.move(x, y)
            x += sz.width() + gap
            rowh = max(rowh, sz.height())
        self.setFixedSize(width, y + rowh)


def _label(text: str, px: float, color: str, weight: int = 400, spacing=0.0) -> QLabel:
    lb = QLabel(text)
    lb.setFont(st.font(px, weight, spacing_em=spacing))
    lb.setStyleSheet(f"color:{color};background:transparent;")
    return lb


# ------------------------------------------------------------------ panel window
class PanelWindow(QWidget):
    collapse_requested = Signal()
    files_dropped = Signal(list)
    browse_requested = Signal()
    recent_clicked = Signal(dict)
    convert_requested = Signal(str, dict, bool)   # target, options, combine
    on_top_toggled = Signal(bool)
    save_next_toggled = Signal(bool)
    change_folder = Signal()
    moved = Signal()
    menu_requested = Signal(QPoint)
    update_check = Signal()
    update_install = Signal()
    update_restart = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("FileMorph")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self._on_top = True
        self._apply_flags()
        self.setFixedSize(PW + 2 * M, PH + 2 * M)
        self.colors = st.COLORWAYS[st.DEFAULT_WAY]
        self.spin = 0.0
        self._last = mo.now()
        self.anim = mo.Pulse(0.7, mo.spring)
        self.origin = QPointF(PW, PH)
        self._snap: QPixmap | None = None
        self._drag: QPoint | None = None
        self.opt_widgets: dict = {}

        self.box = QWidget(self)
        self.box.setFixedSize(PW, PH)
        self.box.move(M, M)
        v = QVBoxLayout(self.box)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(14)

        # header
        self.head = QWidget()
        self.head.setFixedHeight(40)
        self.head.setCursor(Qt.OpenHandCursor)
        h = QHBoxLayout(self.head)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.back_btn = IconButton("back", "Back")
        self.back_btn.clicked.connect(self.show_home)
        self.back_btn.hide()
        h.addWidget(self.back_btn)
        self.mini = MiniOrb(self)
        h.addWidget(self.mini)
        self.title = _label("FileMorph", 15, st.INK, 600)
        h.addWidget(self.title, 1)
        self.pin_btn = IconButton("pin", "Keep on top", checkable=True)
        self.pin_btn.setChecked(True)
        self.pin_btn.toggled.connect(self.on_top_toggled)
        self.collapse_btn = IconButton("minus", "Collapse to node")
        self.collapse_btn.clicked.connect(self.collapse_requested)
        self.more_btn = IconButton("more", "More: updates, colorway, quit")
        self.more_btn.clicked.connect(lambda: self.menu_requested.emit(
            self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft())))
        h.addWidget(self.more_btn)
        h.addWidget(self.pin_btn)
        h.addWidget(self.collapse_btn)
        v.addWidget(self.head)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.home = self._build_home()
        self.formats = QWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.formats)

        self.timer = QTimer(self, interval=16, timeout=self._frame)

    # ------------------------------------------------------------- build
    def _build_home(self) -> QWidget:
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        self.zone = DropZone(self)
        self.zone.files_dropped.connect(self.files_dropped)
        self.zone.clicked.connect(self.browse_requested)
        v.addWidget(self.zone)
        sect = QVBoxLayout()
        sect.setSpacing(6)
        lab = _label("RECENT", 11, st.LABEL, 600, 0.08)
        lab.setContentsMargins(6, 0, 0, 0)
        sect.addWidget(lab)
        self.rows_host = QWidget()
        self.rows_l = QVBoxLayout(self.rows_host)
        self.rows_l.setContentsMargins(0, 0, 0, 0)
        self.rows_l.setSpacing(2)
        sect.addWidget(self.rows_host, 1)
        v.addLayout(sect, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(6, 0, 6, 0)
        self.save_label = _label("Save next to original", 13, st.SOFT_TEXT)
        foot.addWidget(self.save_label)
        self.folder_btn = _LinkButton("")
        self.folder_btn.clicked.connect(self.change_folder)
        foot.addWidget(self.folder_btn)
        foot.addStretch(1)
        self.switch = Switch()
        self.switch.setAccessibleName("Save next to original")
        self.switch.toggled.connect(self.save_next_toggled)
        foot.addWidget(self.switch)
        fw = QWidget()
        fw.setFixedHeight(40)
        fw.setLayout(foot)
        v.addWidget(fw)
        return pg

    def set_save_state(self, next_to: bool, folder_name: str):
        self.switch.blockSignals(True)
        self.switch.setChecked(next_to)
        self.switch.blockSignals(False)
        if next_to:
            self.save_label.setText("Save next to original")
            self.folder_btn.hide()
        else:
            self.save_label.setText("Save to")
            self.folder_btn.setText(folder_name)
            self.folder_btn.show()

    def set_recent(self, entries: list[dict]):
        _clear(self.rows_l)
        if not entries:
            empty = QLabel("Files you convert show up here.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setFont(st.font(12))
            empty.setStyleSheet(f"color:{st.LABEL};background:rgba(255,255,255,5);border-radius:12px;padding:0 24px;")
            self.rows_l.addWidget(empty, 1)
            return
        used = 0
        for e in entries:
            row = RecentRow(e)
            if used + row.height() > 190:
                break
            used += row.height() + 2
            row.clicked.connect(lambda _=False, ent=e: self.recent_clicked.emit(ent))
            self.rows_l.addWidget(row)
        self.rows_l.addStretch(1)

    # ------------------------------------------------------------- formats page
    def show_formats(self, summary: tuple[str, str], targets: list[str], selected: str | None,
                     options_spec: dict, settings):
        old = self.formats
        self.formats = QWidget()
        self.stack.insertWidget(1, self.formats)
        self.stack.removeWidget(old)
        old.deleteLater()
        v = QVBoxLayout(self.formats)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        # file summary
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
        badge = _Badge(summary[0])
        row.addWidget(badge)
        nm = _label(summary[1], 13, st.INK)
        nm.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(nm, 1)
        v.addLayout(row)
        # chips by category
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet("QScrollArea{background:transparent}QScrollArea>QWidget>QWidget{background:transparent}"
                         "QScrollBar:vertical{background:transparent;width:8px;margin:2px}"
                         "QScrollBar::handle:vertical{background:rgba(255,255,255,40);border-radius:3px;min-height:24px}"
                         "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page"
                         "{height:0;background:none}")
        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 4, 0)
        hv.setSpacing(6)
        self.tile_group = QButtonGroup(self)
        self.tile_group.setExclusive(True)
        first = None
        preselect = None
        for cat, cat_label in CATEGORIES:
            keys = [k for k in FORMATS if k in targets and FORMATS[k].category == cat]
            if not keys:
                continue
            lab = _label(cat_label.upper(), 11, st.LABEL, 600, 0.08)
            lab.setContentsMargins(6, 4, 0, 0)
            hv.addWidget(lab)
            tiles = []
            for k in keys:
                t = FormatTile(k)
                self.tile_group.addButton(t)
                t.toggled.connect(lambda on, key=k: on and self._tile_selected(key))
                tiles.append(t)
                first = first or t
                if k == selected:
                    preselect = t  # checked after the Convert button exists (toggled updates its label)
            hv.addWidget(FlowBox(tiles, 300, 6))
        hv.addStretch(1)
        sc.setWidget(host)
        v.addWidget(sc, 1)
        self.opt_host = QWidget()
        self.opt_l = QVBoxLayout(self.opt_host)
        self.opt_l.setContentsMargins(6, 0, 6, 0)
        self.opt_l.setSpacing(8)
        v.addWidget(self.opt_host)
        self.convert_btn = PrimaryButton("Convert")
        self.convert_btn.clicked.connect(self._convert)
        v.addWidget(self.convert_btn)
        self._options_spec = options_spec
        self._settings = settings
        self.stack.setCurrentWidget(self.formats)
        self.back_btn.show()
        self.mini.hide()
        self.title.setText("All formats")
        (preselect or first).setChecked(True) if (preselect or first) else None

    def _tile_selected(self, key: str):
        self.selected = key
        self.convert_btn.setText(f"Convert to {FORMATS[key].ext.upper()}")
        _clear(self.opt_l)
        self.opt_widgets = {}
        for spec in self._options_spec(key):
            kind, skey, title = spec[0], spec[1], spec[2]
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(_label(title, 13, st.SOFT_TEXT))
            hl.addStretch(1)
            if kind == "switch":
                sw = Switch()
                sw.setChecked(bool(self._settings.value(f"opt_{skey}", False, type=bool)))
                sw.toggled.connect(lambda on, k=skey: self._settings.setValue(f"opt_{k}", on))
                hl.addWidget(sw)
                self.opt_widgets[skey] = sw
            elif kind == "slider":
                s = QSlider(Qt.Horizontal)
                s.setRange(50, 100)
                s.setFixedWidth(150)
                s.setValue(int(self._settings.value("quality", 90)))
                s.setStyleSheet("QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,40);border-radius:2px}"
                                f"QSlider::sub-page:horizontal{{background:{st.SWITCH_ON};border-radius:2px}}"
                                "QSlider::handle:horizontal{background:#fff;width:16px;height:16px;margin:-6px 0;border-radius:8px}")
                val = _label(str(s.value()), 12, st.DIM)
                val.setFont(st.font(12, 600, mono=True))
                val.setFixedWidth(28)
                s.valueChanged.connect(lambda x, lb=val: (lb.setText(str(x)), self._settings.setValue("quality", x)))
                s.setCursor(Qt.PointingHandCursor)
                hl.addWidget(s)
                hl.addWidget(val)
                self.opt_widgets[skey] = s
            elif kind == "seg":
                choices, default = spec[3], spec[4]
                saved = self._settings.value(f"opt_{skey}", default)
                try:
                    saved = type(default)(saved)
                except (TypeError, ValueError):
                    saved = default
                grp = QButtonGroup(row)
                for text, value in choices:
                    b = _SegButton(text, value)
                    b.setChecked(value == saved)
                    grp.addButton(b)
                    hl.addWidget(b)
                if not grp.checkedButton():
                    grp.buttons()[0].setChecked(True)
                grp.buttonClicked.connect(lambda b, k=skey: self._settings.setValue(f"opt_{k}", b.value))
                self.opt_widgets[skey] = grp
            self.opt_l.addWidget(row)

    def _convert(self):
        opts, combine = {}, False
        for k, w in self.opt_widgets.items():
            if isinstance(w, QSlider):
                opts[k] = w.value()
            elif isinstance(w, Switch):
                if k == "combine":
                    combine = w.isChecked()
            elif isinstance(w, QButtonGroup) and w.checkedButton():
                opts[k] = w.checkedButton().value
        self.convert_requested.emit(self.selected, opts, combine)

    # ------------------------------------------------------------- updates page
    def show_updates(self, state: str, **kw):
        """state: checking | current | available | downloading | ready | installing | error | unavailable"""
        if getattr(self, "updates", None) is None:
            self.updates = QWidget()
            self.stack.addWidget(self.updates)
            self._upd_l = QVBoxLayout(self.updates)
            self._upd_l.setContentsMargins(6, 4, 6, 0)
            self._upd_l.setSpacing(10)
        _clear(self._upd_l)
        self._upd_progress = None
        L = self._upd_l
        cur = kw.get("current", "")

        def heading(icon, color, title, sub=""):
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(_StatusIcon(icon, color, spin=icon == "spin", colors=self.colors))
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(_label(title, 17, st.INK, 600))
            if sub:
                lb = _label(sub, 12, st.DIM)
                lb.setWordWrap(True)
                col.addWidget(lb)
            row.addLayout(col, 1)
            w = QWidget()
            w.setLayout(row)
            L.addWidget(w)

        if state == "checking":
            heading("spin", st.INK, "Checking for updates…", f"You have FileMorph {cur}")
            L.addStretch(1)
        elif state == "current":
            heading("check", st.SUCCESS, "You're up to date", f"FileMorph {cur} is the latest version.")
            L.addStretch(1)
            L.addWidget(self._secondary("Check again", self.update_check))
        elif state in ("available", "ready"):
            ver, size = kw.get("version", ""), kw.get("size", "")
            if state == "available":
                sub = f"You have {cur}" + (f" · {size} download" if size else "")
            else:
                sub = f"Downloaded and ready. You have {cur}."
            heading("up", st.SWITCH_ON, f"Version {ver} is available", sub)
            notes = (kw.get("notes") or "").strip()
            L.addWidget(_label("WHAT'S NEW", 11, st.LABEL, 600, 0.08))
            body = QLabel()
            body.setTextFormat(Qt.MarkdownText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(True)
            body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            body.setText(notes or "Improvements and fixes.")
            body.setFont(st.font(13))
            body.setStyleSheet(f"color:{st.SOFT_TEXT};background:transparent;")
            sc = QScrollArea()
            sc.setWidget(body)
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setStyleSheet("QScrollArea{background:rgba(255,255,255,6);border-radius:12px}"
                             "QScrollArea>QWidget>QWidget{background:transparent}"
                             "QScrollBar:vertical{background:transparent;width:8px;margin:2px}"
                             "QScrollBar::handle:vertical{background:rgba(255,255,255,40);border-radius:3px}"
                             "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page"
                             "{height:0;background:none}")
            body.setContentsMargins(12, 10, 12, 10)
            L.addWidget(sc, 1)
            if kw.get("blocked"):
                note = _label(kw["blocked"], 12, st.DIM)
                note.setWordWrap(True)
                L.addWidget(note)
            btn = PrimaryButton("Restart to update" if state == "ready" else "Update & restart")
            btn.setEnabled(not kw.get("blocked"))
            btn.clicked.connect(self.update_restart if state == "ready" else self.update_install)
            L.addWidget(btn)
            L.addWidget(self._secondary("Not now", self.show_home, link=True))
        elif state in ("downloading", "installing"):
            ver = kw.get("version", "")
            if state == "downloading":
                heading("up", st.SWITCH_ON, f"Downloading {ver}…",
                        "FileMorph will restart on its own when it's ready.")
            else:
                heading("spin", st.INK, "Installing…", "FileMorph is restarting with the new version.")
            L.addSpacing(6)
            self._upd_progress = _ProgressLine(self.colors)
            self._upd_progress.set(kw.get("pct", 0) / 100 if state == "downloading" else 1.0)
            L.addWidget(self._upd_progress)
            self._upd_pct = _label(f"{kw.get('pct', 0)}%" if state == "downloading" else "", 12, st.DIM)
            self._upd_pct.setFont(st.font(12, 600, mono=True))
            L.addWidget(self._upd_pct)
            L.addStretch(1)
        elif state == "error":
            heading("alert", st.DANGER, "Update didn't work", kw.get("message", ""))
            L.addStretch(1)
            L.addWidget(self._secondary("Try again", self.update_check))
        elif state == "unavailable":
            heading("alert", st.DIM, "Updates unavailable", kw.get("message", ""))
            L.addStretch(1)
        self.stack.setCurrentWidget(self.updates)
        self.back_btn.show()
        self.mini.hide()
        self.title.setText("Updates")

    def set_update_progress(self, pct: int):
        if self._upd_progress is not None:
            self._upd_progress.set(pct / 100)
            self._upd_pct.setText(f"{pct}%")

    def _secondary(self, text, slot, link=False):
        b = _LinkButton(text) if link else _GhostButton(text)
        b.clicked.connect(slot)
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addStretch(1) if link else None
        hl.addWidget(b, 0 if link else 1)
        hl.addStretch(1) if link else None
        return w

    def show_home(self):
        self.stack.setCurrentWidget(self.home)
        self.back_btn.hide()
        self.mini.show()
        self.title.setText("FileMorph")

    # ------------------------------------------------------------- window
    def _apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if self._on_top:
            flags |= Qt.WindowStaysOnTopHint
        vis = self.isVisible()
        self.setWindowFlags(flags)
        if vis:
            self.show()

    def set_on_top(self, on: bool):
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(on)
        self.pin_btn.blockSignals(False)
        if on != self._on_top:
            self._on_top = on
            self._apply_flags()

    def set_colorway(self, colors):
        self.colors = colors
        self.update()

    def open_at(self, node_center: QPoint, node_size: int, screen_rect):
        """Bottom-right corner sits just past the node, like the canvas; grows out of the node."""
        x = node_center.x() + node_size // 2 + 8 - PW
        y = node_center.y() + node_size // 2 + 8 - PH
        x = max(screen_rect.left() + 16, min(screen_rect.right() - 16 - PW, x))
        y = max(screen_rect.top() + 16, min(screen_rect.bottom() - 16 - PH, y))
        self.move(x - M, y - M)
        self.origin = QPointF(node_center.x() - x, node_center.y() - y)
        self.box.show()
        self.box.layout().activate()
        snap = QPixmap(self.box.size() * self.devicePixelRatioF())
        snap.setDevicePixelRatio(self.devicePixelRatioF())
        snap.fill(Qt.transparent)
        # DrawChildren only: no opaque window background in the opening animation
        self.box.render(snap, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        self._snap = snap
        self.box.hide()
        self.anim.fire()
        self.show()
        self.raise_()
        self.activateWindow()
        self.timer.start()

    def _frame(self):
        t = mo.now()
        self.spin = (self.spin + (t - self._last) * 60) % 360
        self.zone.ang = (self.zone.ang + (t - self._last) * (360 / (1.0 if self.zone.over else 3.5))) % 360
        self._last = t
        if self._snap is not None and not self.anim.running:
            self._snap = None
            self.box.show()
        self.mini.update()
        self.zone.update()
        self.update()

    def hideEvent(self, e):  # noqa: N802
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        animating = self._snap is not None
        k = self.anim.value() if animating else 1.0
        if animating:
            o = QPointF(M, M) + self.origin
            p.translate(o)
            s = 0.14 + 0.86 * k
            p.scale(s, s)
            p.translate(-o)
            p.setOpacity(min(1.0, self.anim.raw() * 2.5))
        box = QRectF(M, M, PW, PH)
        # shadow: 0 50px 100px -30px rgba(0,0,0,.85)
        p.setPen(Qt.NoPen)
        for i in range(12):
            kk = (i + 1) / 12
            g = -30 + 50 * kk
            rr = box.adjusted(-g, -g + 30, g, min(g + 30, M - 2 + 0.0))
            if rr.width() > 0 and rr.height() > 0:
                p.setBrush(QColor(0, 0, 0, int(255 * 0.85 / 12 * (1.2 - kk))))
                p.drawRoundedRect(rr, 24 + max(0, g), 24 + max(0, g))
        p.setBrush(st.PANEL_BG)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 24, 24)
        # inset 0 1px 0 rgba(255,255,255,.06)
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawLine(QPointF(box.left() + 20, box.top() + 1.5), QPointF(box.right() - 20, box.top() + 1.5))
        if animating and self._snap is not None:
            p.drawPixmap(QPointF(M, M), self._snap)

    # drag the panel by its header
    def mousePressEvent(self, e):  # noqa: N802
        pos = e.position().toPoint()
        if e.button() == Qt.LeftButton and self.head.geometry().translated(M, M).contains(pos):
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.moved.emit()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape:
            if self.stack.currentWidget() is not self.home:
                self.show_home()
            else:
                self.collapse_requested.emit()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.stack.currentWidget() is self.formats:
            self._convert()
        else:
            super().keyPressEvent(e)

    def box_global_rect(self):
        return self.geometry().adjusted(M, M, -M, -M)


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


class _StatusIcon(QWidget):
    """40px round tile with an icon; 'spin' draws a rotating gradient arc (checking/installing)."""

    def __init__(self, name, color, spin=False, colors=None):
        super().__init__()
        self.name, self.color, self.spin, self.colors = name, QColor(color), spin, colors
        self.setFixedSize(40, 40)
        self._a = 0.0
        if spin:
            self._t = QTimer(self, interval=16, timeout=self._tick)
            self._t.start()

    def _tick(self):
        self._a = (self._a + 6) % 360
        self.update()

    def showEvent(self, e):  # noqa: N802
        if self.spin:
            self._t.start()
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        if self.spin:
            self._t.stop()
        super().hideEvent(e)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        c = QPointF(20, 20)
        if self.spin:
            g = QConicalGradient(c, -self._a)
            c1, c2, _ = (QColor(x) for x in self.colors)
            g.setColorAt(0, c1); g.setColorAt(0.5, c2); g.setColorAt(0.75, QColor(0, 0, 0, 0)); g.setColorAt(1, c1)
            pen = QPen(QBrush(g), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(11, 11, 18, 18), int(-self._a * 16), 270 * 16)
        elif self.name == "up":
            draw_icon(p, "upload", c, 20, self.color)
        else:
            draw_icon(p, self.name, c, 20, self.color, 2.0)


class _ProgressLine(QWidget):
    """6px track; gradient fill in the colorway with a moving sheen."""

    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.setFixedHeight(10)
        self.val = mo.Tween(0, 0.4, mo.soft)
        self._t = QTimer(self, interval=16, timeout=self.update)
        self._t.start()

    def set(self, v: float):
        self.val.to(max(0.0, min(1.0, v)))

    def showEvent(self, e):  # noqa: N802
        self._t.start()
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        self._t.stop()
        super().hideEvent(e)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 2, self.width(), 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(r, 3, 3)
        w = r.width() * self.val.value()
        if w > 1:
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(r.topLeft(), r.topRight())
            c1, c2, c3 = (QColor(x) for x in self.colors)
            g.setColorAt(0, c1); g.setColorAt(0.5, c2); g.setColorAt(1, c3)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), 3, 3)
            sx = (mo.loop(1.6) * 1.4 - 0.2) * r.width()
            sh = QLinearGradient(QPointF(sx - 40, 0), QPointF(sx + 40, 0))
            sh.setColorAt(0, QColor(255, 255, 255, 0)); sh.setColorAt(0.5, QColor(255, 255, 255, 90))
            sh.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(sh))
            p.setClipRect(QRectF(r.left(), r.top(), w, r.height()))
            p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), 3, 3)


class _GhostButton(QAbstractButton):
    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(255, 255, 255, 20 if self._hover else 8))
        p.drawRoundedRect(r, 20, 20)
        p.setFont(st.font(13, 600))
        p.setPen(QColor(st.INK))
        p.drawText(r, Qt.AlignCenter, self.text())


class _Badge(QWidget):
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        f = st.font(11, 700, mono=True, spacing_em=0.06)
        self.f = f
        self.setFixedSize(int(QFontMetricsF(f).horizontalAdvance(text) + 14), 22)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 31))
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.setFont(self.f)
        p.setPen(QColor(st.INK))
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.text)


class _SegButton(QAbstractButton):
    def __init__(self, text, value):
        super().__init__()
        self.setText(text)
        self.value = value
        self.setCheckable(True)
        f = st.font(12, 500)
        self.f = f
        self.setFixedSize(int(QFontMetricsF(f).horizontalAdvance(text) + 20), 30)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 33))
            p.drawRoundedRect(r, 9, 9)
        p.setFont(self.f)
        p.setPen(QColor("#ffffff") if self.isChecked() else QColor(st.DIM))
        p.drawText(r, Qt.AlignCenter, self.text())


class _LinkButton(QAbstractButton):
    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.f = st.font(13, 500)

    def setText(self, t):  # noqa: N802
        super().setText(t)
        self.setFixedSize(int(QFontMetricsF(st.font(13, 500)).horizontalAdvance(t) + 8), 24)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.f)
        p.setPen(QColor(st.INK))
        fm = QFontMetricsF(self.f)
        p.drawText(QPointF(4, 12 + fm.ascent() / 2 - 2), self.text())
        p.setPen(QPen(QColor(255, 255, 255, 102), 1))
        y = 12 + fm.ascent() / 2 + 1
        p.drawLine(QPointF(4, y), QPointF(4 + fm.horizontalAdvance(self.text()), y))
