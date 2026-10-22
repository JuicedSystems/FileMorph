"""Custom-painted widgets. Everything is drawn with QPainter so it's crisp at any DPI."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLayout, QSizePolicy, QWidget, QWidgetItem

from . import theme as th
from ..core.formats import FORMATS


# ----------------------------------------------------------------- icons

def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor, width: float = 1.8) -> None:
    """Line icons on a 24-unit grid."""
    p.save()
    p.translate(rect.topLeft())
    s = min(rect.width(), rect.height()) / 24
    p.scale(s, s)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    if name == "drop":       # arrow into tray
        path.moveTo(12, 3); path.lineTo(12, 14)
        path.moveTo(7.5, 9.5); path.lineTo(12, 14); path.lineTo(16.5, 9.5)
        path.moveTo(3.5, 14); path.lineTo(3.5, 18.5); path.quadTo(3.5, 20.5, 5.5, 20.5)
        path.lineTo(18.5, 20.5); path.quadTo(20.5, 20.5, 20.5, 18.5); path.lineTo(20.5, 14)
    elif name == "check":
        path.moveTo(6, 12.5); path.lineTo(10.2, 16.5); path.lineTo(18, 8)
    elif name == "x":
        path.moveTo(7, 7); path.lineTo(17, 17); path.moveTo(17, 7); path.lineTo(7, 17)
    elif name == "folder":
        path.moveTo(3.5, 7); path.quadTo(3.5, 5, 5.5, 5); path.lineTo(9.5, 5); path.lineTo(11.5, 7.5)
        path.lineTo(18.5, 7.5); path.quadTo(20.5, 7.5, 20.5, 9.5); path.lineTo(20.5, 17)
        path.quadTo(20.5, 19, 18.5, 19); path.lineTo(5.5, 19); path.quadTo(3.5, 19, 3.5, 17); path.closeSubpath()
    elif name == "open":     # box with arrow out
        path.moveTo(13, 4.5); path.lineTo(19.5, 4.5); path.lineTo(19.5, 11)
        path.moveTo(19.5, 4.5); path.lineTo(11, 13)
        path.moveTo(17, 14); path.lineTo(17, 18); path.quadTo(17, 19.5, 15.5, 19.5); path.lineTo(6, 19.5)
        path.quadTo(4.5, 19.5, 4.5, 18); path.lineTo(4.5, 8.5); path.quadTo(4.5, 7, 6, 7); path.lineTo(10, 7)
    elif name == "plus":
        path.moveTo(12, 5); path.lineTo(12, 19); path.moveTo(5, 12); path.lineTo(19, 12)
    elif name == "alert":
        path.addEllipse(QPointF(12, 12), 8.5, 8.5)
        path.moveTo(12, 7.5); path.lineTo(12, 12.8); path.moveTo(12, 16.2); path.lineTo(12, 16.3)
    elif name == "chevron":
        path.moveTo(8, 10); path.lineTo(12, 14); path.lineTo(16, 10)
    elif name == "arrow":
        path.moveTo(5, 12); path.lineTo(19, 12); path.moveTo(13.5, 6.5); path.lineTo(19, 12); path.lineTo(13.5, 17.5)
    p.drawPath(path)
    p.restore()


def icon(name: str, color: QColor, size: int = 18, width: float = 1.8) -> QIcon:
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        draw_icon(p, name, QRectF(0, 0, size, size), color, width)
        p.end()
        ic.addPixmap(pm)
    return ic


def app_icon_pixmap(size: int = 256, on_dark: bool = False) -> QPixmap:
    """The FileMorph mark (the orb); see ui/brand_icon.py."""
    from .brand_icon import render
    return QPixmap.fromImage(render(size))


# ----------------------------------------------------------- flow layout

class FlowLayout(QLayout):
    """Lays children out left-to-right, wrapping to new rows."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _layout(self, rect: QRect, test: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._spacing
            if nx - self._spacing > rect.right() + 1 and line_h > 0:
                x, y = rect.x(), y + line_h + self._spacing
                nx = x + hint.width() + self._spacing
                line_h = 0
            if not test:
                it.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x, line_h = nx, max(line_h, hint.height())
        return y + line_h - rect.y()


# ---------------------------------------------------------------- badge

class FormatBadge(QWidget):
    """Coloured tile with the format's extension, e.g. a red 'PDF'."""

    def __init__(self, fmt_key: str | None, size: int = 44, text: str | None = None, parent=None):
        super().__init__(parent)
        self._fmt = fmt_key
        self._text = text
        self.setFixedSize(size, size)

    def set_format(self, key: str | None, text: str | None = None):
        self._fmt, self._text = key, text
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        f = FORMATS.get(self._fmt) if self._fmt else None
        col = th.color_for(f.key, f.category) if f else QColor("#6B6B73")
        # folded-corner document shape
        fold = r.width() * 0.26
        path = QPainterPath()
        rad = r.width() * 0.16
        path.moveTo(r.left() + rad, r.top())
        path.lineTo(r.right() - fold, r.top())
        path.lineTo(r.right(), r.top() + fold)
        path.lineTo(r.right(), r.bottom() - rad)
        path.quadTo(r.right(), r.bottom(), r.right() - rad, r.bottom())
        path.lineTo(r.left() + rad, r.bottom())
        path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - rad)
        path.lineTo(r.left(), r.top() + rad)
        path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPath(path)
        corner = QPainterPath()
        corner.moveTo(r.right() - fold, r.top())
        corner.lineTo(r.right() - fold, r.top() + fold * 0.75)
        corner.quadTo(r.right() - fold, r.top() + fold, r.right() - fold * 0.75, r.top() + fold)
        corner.lineTo(r.right(), r.top() + fold)
        corner.closeSubpath()
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawPath(corner)
        label = (self._text or (f.ext if f else "?")).upper()
        fs = r.width() * (0.26 if len(label) <= 3 else 0.21 if len(label) == 4 else 0.17)
        font = th.ui_font(1, QFont.Weight.Bold)
        font.setPixelSize(max(7, int(fs)))
        p.setFont(font)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r.adjusted(0, r.height() * 0.22, 0, 0), Qt.AlignCenter, label)


# ---------------------------------------------------------- format chip

class FormatChip(QAbstractButton):
    """Selectable tile showing a target format: big extension, small description."""
    activated = Signal()  # double-click

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.setChecked(True)
        self.activated.emit()

    def __init__(self, fmt_key: str, large: bool = False, parent=None):
        super().__init__(parent)
        self.fmt = FORMATS[fmt_key]
        self.large = large
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(f"{self.fmt.label} (.{self.fmt.ext})")
        self._hover = False
        self.setAccessibleName(f"Convert to {self.fmt.label}")

    def sizeHint(self):  # noqa: N802
        return QSize(116, 64) if self.large else QSize(108, 52)

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        sel = self.isChecked()
        bg = t.q("surface_hover") if (self._hover and not sel) else t.q("surface")
        p.setBrush(bg)
        p.setPen(QPen(t.q("ink") if sel else (t.q("border_strong") if self._hover else t.q("border")),
                      2 if sel else 1))
        p.drawRoundedRect(r, 11, 11)
        if self.hasFocus() and not sel:
            p.setPen(QPen(t.q("faint"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 8, 8)
        # colour dot
        dot = th.color_for(self.fmt.key, self.fmt.category)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QPointF(r.left() + 14, r.top() + (20 if self.large else 17)), 3.5, 3.5)
        # extension
        f = th.ui_font(13 if self.large else 11.5, QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(t.q("text"))
        top = r.top() + (8 if self.large else 6)
        p.drawText(QRectF(r.left() + 24, top, r.width() - 28, 24), Qt.AlignVCenter | Qt.AlignLeft,
                   self.fmt.ext.upper())
        # description
        p.setFont(th.ui_font(8.5 if self.large else 8))
        p.setPen(t.q("muted"))
        desc = p.fontMetrics().elidedText(self.fmt.label, Qt.ElideRight, int(r.width() - 20))
        p.drawText(QRectF(r.left() + 10, r.bottom() - (26 if self.large else 22), r.width() - 16, 20),
                   Qt.AlignVCenter | Qt.AlignLeft, desc)
        if sel:  # check mark
            c = QPointF(r.right() - 13, r.top() + 13)
            p.setBrush(t.q("ink"))
            p.drawEllipse(c, 8, 8)
            draw_icon(p, "check", QRectF(c.x() - 7, c.y() - 7, 14, 14), t.q("ink_text"), 2.2)


# ------------------------------------------------------------ drop zone

class DropZone(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._phase = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(260)
        self._timer = QTimer(self, interval=40, timeout=self._tick)

    def set_active(self, on: bool):
        self._active = on
        self._timer.start() if on else self._timer.stop()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.6) % 16
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setBrush(t.q("surface") if not self._active else t.q("ink", 14 if not t.dark else 22))
        pen = QPen(t.q("ink") if self._active else t.q("border_strong"), 2 if self._active else 1.6)
        pen.setDashPattern([5, 5])
        pen.setDashOffset(-self._phase)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawRoundedRect(r, 22, 22)
        # icon circle
        cx, cy = r.center().x(), r.center().y() - 34
        p.setPen(Qt.NoPen)
        p.setBrush(t.q("ink") if self._active else t.q("bg"))
        p.drawEllipse(QPointF(cx, cy), 34, 34)
        draw_icon(p, "drop", QRectF(cx - 16, cy - 16, 32, 32),
                  t.q("ink_text") if self._active else t.q("text"), 2.0)
        p.setPen(t.q("text"))
        p.setFont(th.ui_font(15, QFont.Weight.DemiBold, display=True))
        p.drawText(QRectF(r.left(), cy + 46, r.width(), 28), Qt.AlignCenter,
                   "Release to add files" if self._active else "Drop files here")
        p.setFont(th.ui_font(10))
        p.setPen(t.q("muted"))
        p.drawText(QRectF(r.left(), cy + 76, r.width(), 22), Qt.AlignCenter, "or click to browse")


# ---------------------------------------------------------- progress ring

class ProgressRing(QWidget):
    def __init__(self, parent=None, size: int = 132):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._value = 0.0
        self._done = False
        self._spin = 0.0
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setDuration(350)
        self._timer = QTimer(self, interval=16, timeout=self._spin_tick)
        self._timer.start()

    def _spin_tick(self):
        self._spin = (self._spin + 4) % 360
        if self._value < 0.02:
            self.update()

    def get_value(self):
        return self._value

    def _set_value(self, v):
        self._value = v
        self.update()

    value = Property(float, get_value, _set_value)

    def set_progress(self, v: float):
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(1.0, v)))
        self._anim.start()

    def reset(self):
        self._anim.stop()
        self._value = 0.0
        self.update()

    def paintEvent(self, _):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 9
        r = QRectF(self.rect()).adjusted(w, w, -w, -w)
        p.setPen(QPen(t.q("border"), w, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(r)
        pen = QPen(t.q("ink"), w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        if self._value < 0.02:  # indeterminate spinner until real progress arrives
            p.drawArc(r, int(-self._spin * 16), int(-80 * 16))
            pct = ""
        else:
            p.drawArc(r, 90 * 16, int(-self._value * 360 * 16))
            pct = f"{int(round(self._value * 100))}%"
        p.setPen(t.q("text"))
        p.setFont(th.ui_font(19, QFont.Weight.DemiBold, display=True))
        p.drawText(self.rect(), Qt.AlignCenter, pct)


class IconCircle(QWidget):
    """Big status glyph on the result page."""

    def __init__(self, name: str = "check", parent=None, size: int = 72):
        super().__init__(parent)
        self.name = name
        self.color_key = "success"
        self.setFixedSize(size, size)

    def set(self, name: str, color_key: str):
        self.name, self.color_key = name, color_key
        self.update()

    def paintEvent(self, _):  # noqa: N802
        t = th.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = t.q(self.color_key)
        p.setPen(Qt.NoPen)
        bg = QColor(c)
        bg.setAlpha(36)
        p.setBrush(bg)
        r = QRectF(self.rect())
        p.drawEllipse(r)
        p.setBrush(c)
        p.drawEllipse(r.adjusted(12, 12, -12, -12))
        inner = r.adjusted(22, 22, -22, -22)
        draw_icon(p, self.name if self.name != "alert" else "x", inner, QColor("#FFFFFF"), 2.6)


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
