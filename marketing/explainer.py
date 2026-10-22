"""Render the FileMorph how-to explainer from the REAL app UI.

The actual NodeWindow / PanelWindow / MorphController are driven through a scripted story on a
painted desktop, on a virtual clock (frame-perfect motion), and piped to ffmpeg.

usage: python marketing/explainer.py <out.mp4> [--fps 30] [--preview N]   (--preview: every Nth frame as PNG)
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication  # noqa: E402

from filemorph.ui.node import motion as mo  # noqa: E402

# ------------------------------------------------------------------ virtual clock
VC = [1000.0]
mo.now = lambda: VC[0]          # every Tween/Pulse/loop in the app now runs on video time

W_OUT, H_OUT = 1920, 1080
LW, LH = 1440, 810              # logical desktop; scaled 4/3 to 1080p so the orb reads well
SCALE = W_OUT / LW
FPS = 30
TASKBAR = 46

ARGS = sys.argv[1:]
OUT = Path(ARGS[0]) if ARGS else ROOT / "marketing" / "FileMorph-how-to.mp4"
PREVIEW = int(ARGS[ARGS.index("--preview") + 1]) if "--preview" in ARGS else 0

app = QApplication([])
from filemorph.ui.node import style as st  # noqa: E402

st.load_fonts()
QSettings("FileMorph", "FileMorph").clear()
from filemorph.ui.node.controller import MorphController  # noqa: E402
from filemorph.ui.node.node import BASE, CX, CY  # noqa: E402
from filemorph.ui.node.panel import M as PM, paint_orb  # noqa: E402

C1, C2, C3 = (QColor(c) for c in st.COLORWAYS["Prism"])

# ------------------------------------------------------------------ real files for real targets
WORK = Path(tempfile.mkdtemp(prefix="fm-video-"))
SAMPLES = Path(os.environ.get("FM_SAMPLES", "/tmp/claude-0/sp/samples"))
REAL = {"Vacation.heic": "sample.heic", "Q3 Report.pdf": "sample.pdf", "Budget.xlsx": "sample.xlsx",
        "Interview.mov": "sample.mov", "Logo.png": "sample.png",
        "Receipt 1.jpg": "sample.jpg", "Receipt 2.jpg": "sample.jpg", "Receipt 3.heic": "sample.heic"}
for name, src in REAL.items():
    shutil.copyfile(SAMPLES / src, WORK / name)

ctl = MorphController(app)
ctl.tray.hide()
node, panel = ctl.node, ctl.panel
NODE_C = QPointF(880, 560)             # orb centre on the desktop
SCREEN = QRect(0, 0, LW, LH - TASKBAR)


# ------------------------------------------------------------------ desktop model
class Icon:
    def __init__(self, name, x, y, visible=True):
        self.name, self.x, self.y = name, x, y
        self.visible = visible
        self.ghost = False
        self.selected = False
        self.pop = mo.Pulse(0.8, mo.spring)
        self.pop.t0 = None

    @property
    def ext(self):
        return self.name.rsplit(".", 1)[-1].upper()[:4]

    @property
    def center(self):
        return QPointF(self.x + 44, self.y + 34)


def slot(i):
    col, row = divmod(i, 5)
    return 36 + col * 108, 40 + row * 118


DESK: list[Icon] = []
for i, n in enumerate(["FileMorph-Setup.exe", "Vacation.heic", "Receipt 1.jpg", "Receipt 2.jpg", "Receipt 3.heic",
                       "Interview.mov", "Q3 Report.pdf", "Budget.xlsx", "Logo.png"]):
    DESK.append(Icon(n, *slot(i)))


def icon(name) -> Icon:
    return next(i for i in DESK if i.name == name)


def add_icon(name) -> Icon:
    ic = Icon(name, *slot(len(DESK)))
    ic.pop.fire()
    DESK.append(ic)
    return ic


EXT_COLOR = {"EXE": "#334155", "HEIC": "#6d28d9", "JPG": "#6d28d9", "PNG": "#6d28d9", "PDF": "#d93a3a",
             "XLSX": "#1a9a5b", "PPTX": "#e0661b", "MOV": "#be185d", "MP3": "#0f766e", "DOCX": "#2f6feb"}


# ------------------------------------------------------------------ overlay state
class S:
    cursor = QPointF(720, 470)
    cursor_vis = False
    press = 0.0                       # click squish 0..1
    ripples: list = []                # (pos, t0)
    drag: list[Icon] = []             # icons being dragged (ghost follows cursor)
    caption = None                    # (num, title, sub, t0)
    title_card = None                 # (lines, t0, t_out)
    installer = None                  # (t0, progress)
    menu = None                       # (pos, hover_idx, t0)
    dim = 0.0
    node_vis = False
    node_in = mo.Pulse(0.7, mo.spring)
    sfx: list = []                    # (time, kind)


CAM_X, CAM_Y, CAM_Z = mo.Tween(LW / 2, 1.3, mo.ease_in_out), mo.Tween(LH / 2, 1.3, mo.ease_in_out), \
    mo.Tween(1.0, 1.3, mo.ease_in_out)


def cam(x, y, z, dur=1.3):
    for tw, v in ((CAM_X, x), (CAM_Y, y), (CAM_Z, z)):
        tw.to(v, dur, mo.ease_in_out)


def cam_now():
    z = CAM_Z.value()
    hw, hh = LW / (2 * z), LH / (2 * z)
    x = min(max(CAM_X.value(), hw), LW - hw)
    y = min(max(CAM_Y.value(), hh), LH - hh)
    return x, y, z


def cam_panel(dur=0.9):
    """Frame the glass panel just below the step caption (caption ~96px tall at the top of the screen)."""
    z = 1.3
    top = panel.pos().y() + PM
    cam(panel.pos().x() + PM + 170, top + (LH / (2 * z)) - (96 / z + 14), z, dur)


def sfx(kind, delay=0.0):
    S.sfx.append((VC[0] - START + delay, kind))


# ------------------------------------------------------------------ painting helpers
def font(px, w=400, mono=False, sp=0.0):
    return st.font(px, w, mono=mono, spacing_em=sp)


def paint_wallpaper(p: QPainter):
    p.fillRect(QRectF(0, 0, LW, LH), QColor("#07080c"))
    t = VC[0]
    for (x, y, r, c, ph) in ((1060, -120, 620, C1, 0), (1300, 560, 520, C2, 2), (160, 640, 560, C3, 4)):
        dx, dy = 70 * math.sin(t / 9 + ph), 50 * math.cos(t / 11 + ph)
        g = QRadialGradient(QPointF(x + dx, y + dy), r)
        col = QColor(c)
        col.setAlphaF(0.26)
        g.setColorAt(0, col)
        col.setAlphaF(0.0)
        g.setColorAt(1, col)
        p.fillRect(QRectF(0, 0, LW, LH), QBrush(g))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 12))
    for gx in range(0, LW, 24):
        for gy in range(0, LH, 24):
            p.drawEllipse(QPointF(gx, gy), 0.9, 0.9)


def paint_paper(p: QPainter, x, y, ext, alpha=1.0):
    p.save()
    p.setOpacity(p.opacity() * alpha)
    for i in range(4):  # drop shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 30 - i * 6))
        p.drawRoundedRect(QRectF(x - i, y + 4 + i, 44 + 2 * i, 56), 6, 6)
    path = QPainterPath()
    path.moveTo(x + 5, y)
    path.lineTo(x + 34, y)
    path.lineTo(x + 44, y + 10)
    path.lineTo(x + 44, y + 51)
    path.quadTo(x + 44, y + 56, x + 39, y + 56)
    path.lineTo(x + 5, y + 56)
    path.quadTo(x, y + 56, x, y + 51)
    path.lineTo(x, y + 5)
    path.quadTo(x, y, x + 5, y)
    p.setBrush(QColor("#f1f2f6"))
    p.drawPath(path)
    fold = QPainterPath()
    fold.moveTo(x + 34, y)
    fold.lineTo(x + 34, y + 8)
    fold.quadTo(x + 34, y + 10, x + 36, y + 10)
    fold.lineTo(x + 44, y + 10)
    fold.closeSubpath()
    p.setBrush(QColor("#bfc4d0"))
    p.drawPath(fold)
    p.setBrush(QColor(EXT_COLOR.get(ext, "#475569")))
    p.drawRect(QRectF(x, y + 32, 44, 15))
    p.setFont(font(9, 700, mono=True, sp=0.06))
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(x, y + 32, 44, 15), Qt.AlignCenter, ext)
    p.restore()


def paint_icons(p: QPainter):
    for ic in DESK:
        if not ic.visible:
            continue
        p.save()
        k = 1.0
        if ic.pop.t0 is not None:
            if not ic.pop.started:
                p.restore()
                continue
            k = ic.pop.value()
        a = 0.28 if ic.ghost else 1.0
        cx, cy = ic.x + 44, ic.y + 34
        p.translate(cx, cy)
        sc = (0.2 + 0.8 * k) * (0.92 if ic.ghost else 1)
        p.scale(sc, sc)
        p.translate(-cx, -cy)
        p.setOpacity(min(1.0, k * 1.5) * a)
        if ic.selected:
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(QRectF(ic.x, ic.y, 88, 108), 10, 10)
        paint_paper(p, ic.x + 22, ic.y + 10, ic.ext)
        p.setFont(font(12))
        fm = QFontMetricsF(p.font())
        name = fm.elidedText(ic.name, Qt.ElideMiddle, 96)
        r = QRectF(ic.x - 6, ic.y + 74, 100, 18)
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(r.translated(0, 1), Qt.AlignCenter, name)
        p.setPen(QColor("#eef0f6"))
        p.drawText(r, Qt.AlignCenter, name)
        p.restore()


def paint_taskbar(p: QPainter):
    r = QRectF(0, LH - TASKBAR, LW, TASKBAR)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(14, 16, 22, 215))
    p.drawRect(r)
    p.setPen(QPen(QColor(255, 255, 255, 16), 1))
    p.drawLine(r.topLeft(), r.topRight())
    # tray orb + clock
    paint_orb(p, QPointF(LW - 104, LH - TASKBAR / 2), 18, st.COLORWAYS["Prism"], (VC[0] * 60) % 360)
    p.setFont(font(12))
    p.setPen(QColor("#eef0f6"))
    p.drawText(QRectF(LW - 86, LH - TASKBAR + 6, 76, 16), Qt.AlignRight | Qt.AlignVCenter, "9:41 AM")
    p.drawText(QRectF(LW - 86, LH - TASKBAR + 24, 76, 16), Qt.AlignRight | Qt.AlignVCenter, "10/22/2026")


def render_widget(p: QPainter, w, pos: QPointF, opacity=1.0, scale=1.0, origin: QPointF | None = None):
    dpr = SCALE * cam_now()[2]
    layer = QImage(int(w.width() * dpr), int(w.height() * dpr), QImage.Format_ARGB32_Premultiplied)
    layer.setDevicePixelRatio(dpr)
    layer.fill(Qt.transparent)
    lp = QPainter(layer)
    w.render(lp, QPoint())
    lp.end()
    p.save()
    p.setOpacity(opacity)
    if scale != 1.0 and origin is not None:
        p.translate(origin)
        p.scale(scale, scale)
        p.translate(-origin)
    p.drawImage(pos, layer)
    p.restore()


def paint_node(p: QPainter):
    if not S.node_vis or not node.isVisible():
        return
    node._frame()
    k = S.node_in.value() if S.node_in.t0 is not None else 1.0
    pos = NODE_C - QPointF(CX, CY)
    render_widget(p, node, pos, opacity=min(1.0, k * 1.6), scale=0.2 + 0.8 * k, origin=NODE_C)


def paint_panel(p: QPainter):
    if not panel.isVisible():
        return
    panel._frame()
    render_widget(p, panel, QPointF(panel.pos()))


def paint_installer(p: QPainter):
    if not S.installer:
        return
    t0, prog = S.installer
    k = mo.spring(min(1.0, (VC[0] - t0) / 0.6))
    box = QRectF(LW / 2 - 190, LH / 2 - 70, 380, 140)
    p.save()
    p.translate(box.center())
    p.scale(0.9 + 0.1 * k, 0.9 + 0.1 * k)
    p.translate(-box.center())
    p.setOpacity(min(1.0, k * 2))
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.setBrush(QColor(15, 17, 25, 245))
    p.drawRoundedRect(box, 18, 18)
    paint_orb(p, QPointF(box.left() + 44, box.top() + 46), 36, st.COLORWAYS["Prism"], VC[0] * 120 % 360)
    p.setFont(font(17, 600))
    p.setPen(QColor("#eef0f6"))
    p.drawText(QRectF(box.left() + 76, box.top() + 26, 280, 22), Qt.AlignVCenter, "Installing FileMorph")
    p.setFont(font(13))
    p.setPen(QColor(st.DIM))
    p.drawText(QRectF(box.left() + 76, box.top() + 50, 280, 18), Qt.AlignVCenter, "No admin needed · just a moment")
    track = QRectF(box.left() + 28, box.bottom() - 36, box.width() - 56, 6)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 26))
    p.drawRoundedRect(track, 3, 3)
    g = QLinearGradient(track.topLeft(), track.topRight())
    g.setColorAt(0, C1)
    g.setColorAt(0.5, C2)
    g.setColorAt(1, C3)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * prog, 6), 3, 3)
    p.restore()


MENU_ITEMS = ["Open", "Open with", "Convert with FileMorph", "Share", "Copy", "Rename", "Properties"]


def paint_menu(p: QPainter):
    if not S.menu:
        return
    pos, hover, t0 = S.menu
    k = mo.soft(min(1.0, (VC[0] - t0) / 0.25))
    w, ih = 250, 34
    box = QRectF(pos.x(), pos.y(), w, ih * len(MENU_ITEMS) + 12)
    p.save()
    p.setOpacity(k)
    p.translate(0, -6 * (1 - k))
    for i in range(6):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 22 - i * 3))
        p.drawRoundedRect(box.adjusted(-i, -i + 6, i, i + 6), 12 + i, 12 + i)
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.setBrush(QColor(32, 33, 38, 250))
    p.drawRoundedRect(box, 10, 10)
    for i, item in enumerate(MENU_ITEMS):
        r = QRectF(box.left() + 6, box.top() + 6 + i * ih, w - 12, ih)
        if i == hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(r, 6, 6)
        if item == "Convert with FileMorph":
            paint_orb(p, QPointF(r.left() + 18, r.center().y()), 16, st.COLORWAYS["Prism"], VC[0] * 60 % 360)
        p.setFont(font(13, 600 if item == "Convert with FileMorph" else 400))
        p.setPen(QColor("#eef0f6"))
        p.drawText(r.adjusted(36, 0, 0, 0), Qt.AlignVCenter, item)
        if item in ("Open", "Share"):
            pass
    p.restore()


def paint_drag(p: QPainter):
    if not S.drag:
        return
    for i, ic in enumerate(S.drag[:3]):
        paint_paper(p, S.cursor.x() - 10 + i * 6, S.cursor.y() + 10 - i * 4, ic.ext, alpha=0.82)
    if len(S.drag) > 1:
        c = QPointF(S.cursor.x() + 40, S.cursor.y() + 12)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4f7cff"))
        p.drawEllipse(c, 11, 11)
        p.setFont(font(12, 700))
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignCenter, str(len(S.drag)))


def paint_cursor(p: QPainter):
    for pos, t0 in list(S.ripples):  # click ripples
        k = (VC[0] - t0) / 0.5
        if k >= 1:
            S.ripples.remove((pos, t0))
            continue
        e = mo.soft(k)
        p.setPen(QPen(QColor(255, 255, 255, int(200 * (1 - k))), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(pos, 6 + 22 * e, 6 + 22 * e)
    if not S.cursor_vis:
        return
    x, y = S.cursor.x(), S.cursor.y()
    s = 1.0 - 0.12 * S.press
    p.save()
    p.translate(x, y)
    p.scale(s * 1.05, s * 1.05)
    path = QPainterPath()
    path.moveTo(0, 0)
    path.lineTo(0, 21)
    path.lineTo(5.2, 16.2)
    path.lineTo(8.6, 24)
    path.lineTo(12, 22.5)
    path.lineTo(8.6, 15)
    path.lineTo(15.4, 15)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 70))
    p.drawPath(path.translated(1.5, 2))
    p.setPen(QPen(QColor("#111"), 1.3))
    p.setBrush(QColor("#ffffff"))
    p.drawPath(path)
    p.restore()


def paint_caption(p: QPainter):
    if not S.caption:
        return
    num, title, sub, t0, t_out = S.caption
    k = mo.spring(min(1.0, (VC[0] - t0) / 0.7))
    out = 0.0 if t_out is None else min(1.0, max(0.0, (VC[0] - t_out) / 0.35))
    p.save()
    p.setOpacity(min(1.0, (VC[0] - t0) / 0.3) * (1 - out))
    x0 = 0 if True else 0
    p.translate(-30 * (1 - k) - 20 * out, 0)
    f1, f2 = font(30, 650), font(17)
    w = max(QFontMetricsF(f1).horizontalAdvance(title), QFontMetricsF(f2).horizontalAdvance(sub)) + 120
    box = QRectF(LW - w - 40, 34, w, 96) if False else QRectF(560, 36, w, 96)
    box.moveLeft((LW - w) / 2)
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.setBrush(QColor(13, 15, 22, 214))
    p.drawRoundedRect(box, 24, 24)
    c = QPointF(box.left() + 50, box.center().y())
    path = QPainterPath()
    path.addEllipse(c, 26, 26)
    p.save()
    p.setClipPath(path)
    from PySide6.QtGui import QConicalGradient
    g = QConicalGradient(c, -VC[0] * 60)
    g.setColorAt(0, C1)
    g.setColorAt(1 / 3, C3)
    g.setColorAt(2 / 3, C2)
    g.setColorAt(1, C1)
    p.fillRect(QRectF(c.x() - 30, c.y() - 30, 60, 60), QBrush(g))
    p.setBrush(QColor(12, 14, 21, 210))
    p.setPen(Qt.NoPen)
    p.drawEllipse(c, 23.5, 23.5)
    p.restore()
    p.setFont(font(22, 700, mono=True))
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(c.x() - 26, c.y() - 26, 52, 52), Qt.AlignCenter, str(num))
    p.setFont(f1)
    p.drawText(QRectF(box.left() + 92, box.top() + 14, w, 40), Qt.AlignVCenter, title)
    p.setFont(f2)
    p.setPen(QColor(st.DIM))
    p.drawText(QRectF(box.left() + 92, box.top() + 54, w, 26), Qt.AlignVCenter, sub)
    p.restore()


def paint_title(p: QPainter):
    if not S.title_card:
        return
    lines, t0, t_out = S.title_card
    a_in = min(1.0, (VC[0] - t0) / 0.6)
    a_out = 0.0 if t_out is None else min(1.0, max(0.0, (VC[0] - t_out) / 0.5))
    a = a_in * (1 - a_out)
    p.save()
    p.fillRect(QRectF(0, 0, LW, LH), QColor(7, 8, 12, int(235 * a)))
    p.setOpacity(a)
    k = mo.spring(min(1.0, (VC[0] - t0) / 0.9))
    c = QPointF(LW / 2, LH / 2 - 110)
    d = 112 * (0.4 + 0.6 * k)
    glow = QRadialGradient(c, 240)
    gc = QColor(C1)
    gc.setAlphaF(0.35)
    glow.setColorAt(0, gc)
    gc.setAlphaF(0)
    glow.setColorAt(1, gc)
    p.fillRect(QRectF(0, 0, LW, LH), QBrush(glow))
    paint_orb(p, c, d, st.COLORWAYS["Prism"], VC[0] * 60 % 360)
    p.setPen(Qt.NoPen)
    rg = QRadialGradient(QPointF(c.x() - d * .2, c.y() - d * .3), d * .62)
    rg.setColorAt(0, QColor(255, 255, 255, 60))
    rg.setColorAt(.62, QColor(12, 14, 21, 225))
    rg.setColorAt(1, QColor(12, 14, 21, 225))
    p.setBrush(QBrush(rg))
    p.drawEllipse(c, d / 2 - 3, d / 2 - 3)
    pen = QPen(QColor("#ffffff"), 3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    s = d / 96
    for a1, b1, a2 in (((-16, -6), (14, -6), (8, -12)), ((16, 6), (-14, 6), (-8, 12))):
        path = QPainterPath(QPointF(c.x() + a1[0] * s, c.y() + a1[1] * s))
        path.lineTo(c.x() + b1[0] * s, c.y() + b1[1] * s)
        path.lineTo(c.x() + a2[0] * s, c.y() + a2[1] * s)
        p.drawPath(path)
    y = LH / 2 + 10
    for i, (text, px, w8, col) in enumerate(lines):
        kk = mo.spring(min(1.0, max(0.0, (VC[0] - t0 - 0.15 - i * 0.12) / 0.8)))
        p.save()
        p.setOpacity(a * min(1.0, kk * 1.5))
        p.translate(0, 14 * (1 - kk))
        p.setFont(font(px, w8))
        p.setPen(QColor(col))
        h = px * 1.5
        p.drawText(QRectF(0, y, LW, h), Qt.AlignCenter, text)
        p.restore()
        y += px * 1.5 + 6
    p.restore()


# ------------------------------------------------------------------ frame output
ffmpeg = None


def open_encoder(path: Path):
    from filemorph.core.converters.media import ffmpeg_exe
    return subprocess.Popen([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
                             "-s", f"{W_OUT}x{H_OUT}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset",
                             "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
                            stdin=subprocess.PIPE)


FRAME = [0]
PREV_DIR = OUT.parent / "preview"


def emit():
    img = QImage(W_OUT, H_OUT, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    cx, cy, z = cam_now()
    p.save()  # world space: the desktop seen through the camera
    p.translate(W_OUT / 2, H_OUT / 2)
    p.scale(SCALE * z, SCALE * z)
    p.translate(-cx, -cy)
    paint_wallpaper(p)
    paint_icons(p)
    paint_taskbar(p)
    paint_installer(p)
    paint_node(p)
    paint_panel(p)
    paint_menu(p)
    paint_drag(p)
    paint_cursor(p)
    p.restore()
    p.scale(SCALE, SCALE)  # screen space: captions and title cards don't zoom
    vignette = QRadialGradient(QPointF(LW / 2, LH / 2), LW * 0.75)
    vignette.setColorAt(0.6, QColor(0, 0, 0, 0))
    vignette.setColorAt(1.0, QColor(0, 0, 0, 120))
    p.fillRect(QRectF(0, 0, LW, LH), QBrush(vignette))
    paint_caption(p)
    paint_title(p)
    p.end()
    ffmpeg.stdin.write(img.constBits().tobytes())
    if PREVIEW and FRAME[0] % PREVIEW == 0:
        PREV_DIR.mkdir(parents=True, exist_ok=True)
        img.scaled(960, 540, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(PREV_DIR / f"f{FRAME[0]:05d}.png"))
    FRAME[0] += 1


def run(seconds: float, fn=None):
    n = max(1, round(seconds * FPS))
    for i in range(n):
        if fn:
            fn(i / max(1, n - 1))
        app.processEvents()
        emit()
        VC[0] += 1 / FPS


def ease_move(a: QPointF, b: QPointF, seconds: float, arc: float = 0.18, during=None):
    """Cursor glides a -> b on a gentle arc with ease-in-out."""
    mid = (a + b) / 2 + QPointF(-(b.y() - a.y()), b.x() - a.x()) * arc

    def f(t):
        e = mo.ease_in_out(t)
        S.cursor = (a * (1 - e) ** 2) + (mid * 2 * (1 - e) * e) + (b * e ** 2)
        if during:
            during(t, S.cursor)
    run(seconds, f)


def click(at: QPointF | None = None, double=False):
    if at is not None:
        S.cursor = at
    for _ in range(2 if double else 1):
        S.ripples.append((QPointF(S.cursor), VC[0]))
        sfx("click")
        run(0.08, lambda t: setattr(S, "press", 1.0))
        run(0.08, lambda t: setattr(S, "press", 0.0))


def caption(num, title, sub):
    if S.caption:
        S.caption = (*S.caption[:4], VC[0])
        run(0.3)
    S.caption = (num, title, sub, VC[0], None)
    sfx("whoosh_soft")


def chip_pos(i: int) -> QPointF:
    w = len(node.chips) * 64 + 12
    return QPointF(NODE_C.x() - w / 2 + 6 + i * 64 + 32, NODE_C.y())


def fake_convert(text: str, seconds: float, done_name: str, suffix="saved"):
    node.show_converting(text)
    sfx("whoosh")
    run(seconds, lambda t: node.set_progress(1 - (1 - t) ** 2.2))
    node.show_done(done_name, suffix)
    sfx("chime")


# ================================================================== the story
START = VC[0]
ffmpeg = open_encoder(OUT.with_suffix(".video.mp4"))
node.hide()
node.intro_until = 0

# 1 · Title -----------------------------------------------------------------
S.title_card = ([("FileMorph", 64, 700, "#ffffff"),
                 ("Convert any file. Just drop it.", 26, 400, st.DIM)], VC[0], None)
sfx("swell")
run(2.6)
S.title_card = (*S.title_card[:2], VC[0])
run(0.6)
S.title_card = None

# 2 · Install -----------------------------------------------------------------
S.cursor_vis = True
cam(LW / 2, LH / 2, 1.0, 0.01)
caption(1, "Install in one click", "No admin rights. No wizard. Ready in seconds.")
setup = icon("FileMorph-Setup.exe")
ease_move(QPointF(720, 470), setup.center, 0.9)
setup.selected = True
click(double=True)
S.installer = (VC[0], 0.0)
sfx("pop")
run(1.3, lambda t: setattr(S, "installer", (S.installer[0], mo.ease_in_out(t))))
S.installer = None
setup.selected = False
node.show()
node.show_idle()
node.intro_until = VC[0] + 3.0
node.intro_cap.fire()
S.node_vis = True
S.node_in.fire()
sfx("pop")
cam(560, 312, 1.3, 1.6)
ease_move(S.cursor, QPointF(700, 430), 1.6)

# 3 · Drop -----------------------------------------------------------------------
caption(2, "Drop a file on the orb", "Any file: photos, PDFs, Office docs, audio, video.")
vac = icon("Vacation.heic")
ease_move(S.cursor, vac.center, 0.9)
vac.selected = True
run(0.15)
vac.ghost = True
S.drag = [vac]
hovered = [False]


def drag_hover(t, cur):
    near = math.hypot(cur.x() - NODE_C.x(), cur.y() - NODE_C.y()) < 150
    if near and not hovered[0]:
        hovered[0] = True
        node._hover_cap.fire()
        node.caption = None
        node._go("hover")
        sfx("whoosh_soft")


ease_move(vac.center, NODE_C + QPointF(-6, 4), 1.5, arc=-0.12, during=drag_hover)
run(0.7)
S.drag = []
vac.ghost = vac.selected = False
sfx("drop")
ctl.add_files([WORK / "Vacation.heic"])
cam(NODE_C.x(), NODE_C.y() - 40, 1.9, 1.0)
run(1.4)

# 4 · Pick ------------------------------------------------------------------------
caption(3, "Pick a format", "Best options first. ••• shows every format.")
ease_move(S.cursor, chip_pos(2) + QPointF(4, 18), 0.6)
for i in (2, 1, 0, 1, 0):
    node._set_hover(i)
    sfx("tick")
    ease_move(S.cursor, chip_pos(i) + QPointF(4, 18), 0.32, arc=0.0)
run(0.3)
node._set_hover(0)
click()
fake_convert("Converting to JPG…", 1.7, "Vacation.jpg")
run(0.6)
caption(3, "Done. Saved next to the original.", "Click the orb to open it right away.")
cam(560, 312, 1.3, 1.1)
ease_move(S.cursor, QPointF(700, 420), 1.1)
add_icon("Vacation.jpg")
sfx("pop")
run(1.4)
node.show_idle()
run(0.4)

# 5 · Batch + combine ---------------------------------------------------------------
caption(4, "Batch it. Even into one PDF.", "Three receipt photos in, one tidy PDF out.")
group = [icon("Receipt 1.jpg"), icon("Receipt 2.jpg"), icon("Receipt 3.heic")]
ease_move(S.cursor, QPointF(group[0].x - 14, group[0].y - 12), 0.8)
for g in group:  # marquee-style selection
    run(0.12)
    g.selected = True
    sfx("tick")
ease_move(S.cursor, group[1].center, 0.4)
for g in group:
    g.ghost = True
S.drag = group
hovered[0] = False
ease_move(S.cursor, NODE_C + QPointF(-4, 6), 1.4, arc=-0.1, during=drag_hover)
run(0.6)
S.drag = []
for g in group:
    g.ghost = g.selected = False
sfx("drop")
ctl.add_files([WORK / g.name for g in group])
cam(NODE_C.x(), NODE_C.y() - 40, 1.9, 1.0)
run(1.3)
more_i = len(node.chips) - 1
ease_move(S.cursor, chip_pos(more_i) + QPointF(4, 18), 0.7)
node._set_hover(more_i)
sfx("tick")
run(0.35)
click()
c = QPoint(int(NODE_C.x()), int(NODE_C.y()))
node.hide()
panel.show_formats(ctl._summary(), ctl.targets, "pdf", ctl._options_for, ctl.settings)
panel.open_at(c, BASE, SCREEN)
cam_panel()
sfx("whoosh")
run(1.0)
box = QPointF(panel.pos()) + QPointF(PM, PM)
sw = panel.opt_widgets["combine"]
sw_pos = box + QPointF(sw.mapTo(panel.box, QPoint(20, 12)))
ease_move(S.cursor, sw_pos, 0.8)
click()
sw.setChecked(True)
run(0.5)
btn = panel.convert_btn
btn_pos = box + QPointF(btn.mapTo(panel.box, QPoint(btn.width() // 2, 22)))
ease_move(S.cursor, btn_pos, 0.6)
btn._hover = True
run(0.3)
click()
btn._hover = False
panel.hide()
node.show()
cam(NODE_C.x(), NODE_C.y() - 40, 1.9, 0.9)
node.show_converting("Converting 1 of 3 to PDF…")
sfx("whoosh")


def batch_prog(t):
    i = min(2, int(t * 3))
    node.set_progress(t, f"Converting {i + 1} of 3 to PDF…")


run(2.2, batch_prog)
node.show_done("Receipt 1 (combined).pdf", "saved")
sfx("chime")
run(0.9)
cam(560, 312, 1.3, 1.1)
ease_move(S.cursor, QPointF(720, 400), 1.1)
add_icon("Receipt 1 (combined).pdf")
sfx("pop")
run(1.0)
node.show_idle()

# 6 · Panel ------------------------------------------------------------------------
caption(5, "Click the orb for the panel", "Recent conversions, where files are saved, and settings.")
ctl.history = [
    {"name": "Receipt 1 (combined).pdf", "out": "x", "from": "JPG", "to": "PDF", "to_key": "pdf", "at": 0},
    {"name": "Vacation.jpg", "out": "x", "from": "HEIC", "to": "JPG", "to_key": "jpg", "at": 0},
]
import time as _t  # noqa: E402
for h in ctl.history:
    h["at"] = _t.time() - 30
panel.set_recent(ctl.history)
ease_move(S.cursor, NODE_C + QPointF(10, 12), 0.9)
node.mouse_inside = True
run(0.3)
click()
node.mouse_inside = False
panel.show_home()
node.hide()
panel.open_at(c, BASE, SCREEN)
cam_panel()
sfx("whoosh")
run(1.1)
box = QPointF(panel.pos()) + QPointF(PM, PM)
ease_move(S.cursor, box + QPointF(170, 300), 0.9)
run(0.8)
sw2 = panel.switch
ease_move(S.cursor, box + QPointF(sw2.mapTo(panel.box, QPoint(20, 12))), 0.8)
run(0.9)
col = panel.collapse_btn
ease_move(S.cursor, box + QPointF(col.mapTo(panel.box, QPoint(20, 20))), 0.6)
click()
panel.hide()
node.show()
node.show_idle()
run(0.4)

# 7 · Right-click --------------------------------------------------------------------
caption(6, "Or right-click any file", "“Convert with FileMorph” is right in Explorer.")
mov = icon("Interview.mov")
cam(330, 260, 1.6, 1.1)
ease_move(S.cursor, mov.center, 1.0)
mov.selected = True
click()
S.menu = (S.cursor + QPointF(6, 4), -1, VC[0])
run(0.5)
for i in range(3):
    S.menu = (S.menu[0], i, S.menu[2])
    ease_move(S.cursor, S.menu[0] + QPointF(80, 6 + 17 + i * 34), 0.22, arc=0)
run(0.35)
click()
S.menu = None
mov.selected = False
ctl.add_files([WORK / "Interview.mov"])
cam(NODE_C.x(), NODE_C.y() - 40, 1.9, 1.1)
sfx("pop")
run(1.1)
mp3_i = next((i for i, ch in enumerate(node.chips) if ch.key == "mp3"), 0)
ease_move(S.cursor, chip_pos(mp3_i) + QPointF(4, 18), 1.0)
node._set_hover(mp3_i)
sfx("tick")
run(0.35)
click()
fake_convert("Converting to MP3…", 1.6, "Interview.mp3")
run(0.8)
cam(560, 312, 1.3, 1.0)
add_icon("Interview.mp3")
sfx("pop")
run(1.0)
node.show_idle()

# 8 · Updates --------------------------------------------------------------------------
caption(7, "Updates, only when you want them", "Check from the ⋯ menu. Install with one click.")
ease_move(S.cursor, NODE_C + QPointF(8, 10), 0.8)
click()
node.hide()
panel.show_updates("checking", current="0.3.0")
panel.open_at(c, BASE, SCREEN)
cam_panel()
sfx("whoosh")
run(1.2)
panel.show_updates("available", current="0.3.0", version="0.4.0", size="18.4 MB",
                   notes="**New:** faster PDF → Word\n\n- HEIC photos keep their date taken\n"
                         "- Sharper SVG tracing\n- Smaller downloads with delta updates")
sfx("pop")
run(0.6)
box = QPointF(panel.pos()) + QPointF(PM, PM)
ease_move(S.cursor, box + QPointF(170, 418), 1.0)
run(1.6)
panel.hide()

# 9 · Outro -------------------------------------------------------------------------------
S.caption = (*S.caption[:4], VC[0])
S.cursor_vis = False
cam(LW / 2, LH / 2, 1.0, 1.2)
S.title_card = ([("FileMorph", 60, 700, "#ffffff"),
                 ("40+ formats  ·  Works offline  ·  Your files never leave your PC", 21, 400, st.DIM),
                 ("Drop. Pick. Done.", 26, 600, "#ffffff")], VC[0], None)
sfx("swell")
run(3.6)

ffmpeg.stdin.close()
ffmpeg.wait()
DURATION = FRAME[0] / FPS
print(f"frames={FRAME[0]} duration={DURATION:.1f}s events={len(S.sfx)}")


# ================================================================== sound
def synth(duration: float, events) -> np.ndarray:
    sr = 48000
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float64)
    t_all = np.arange(n) / sr
    # soft pad: Dmaj9-ish, slow swell, very low
    pad = np.zeros(n)
    for f, a in ((146.83, .5), (220.0, .35), (277.18, .25), (329.63, .22), (440.0, .1)):
        pad += a * np.sin(2 * np.pi * f * t_all + 0.3 * np.sin(2 * np.pi * 0.11 * t_all))
    env = np.minimum(1, t_all / 2.5) * np.minimum(1, (duration - t_all) / 2.5)
    pad *= 0.028 * env * (0.85 + 0.15 * np.sin(2 * np.pi * 0.05 * t_all))
    out += pad

    def add(t0, sig):
        i = int(t0 * sr)
        j = min(n, i + len(sig))
        if 0 <= i < n:
            out[i:j] += sig[: j - i]

    def tone(freqs, dur, amp, decay, sweep=0.0):
        tt = np.arange(int(dur * sr)) / sr
        s = sum(np.sin(2 * np.pi * (f + sweep * tt / dur) * tt) for f in freqs)
        return amp * s * np.exp(-tt * decay) * np.minimum(1, tt / 0.004)

    def noise(dur, amp, lo, hi):
        tt = np.arange(int(dur * sr)) / sr
        x = np.random.default_rng(7).standard_normal(len(tt))
        spec = np.fft.rfft(x)
        fr = np.fft.rfftfreq(len(tt), 1 / sr)
        spec[(fr < lo) | (fr > hi)] = 0
        y = np.fft.irfft(spec, len(tt))
        y /= np.abs(y).max() + 1e-9
        return amp * y * np.sin(np.pi * tt / dur) ** 2

    def mix(*sigs):
        m = max(len(x) for x in sigs)
        o = np.zeros(m)
        for x in sigs:
            o[: len(x)] += x
        return o

    lib = {
        "click": tone([1900], 0.035, 0.10, 120),
        "tick": tone([2600], 0.025, 0.05, 160),
        "pop": tone([520], 0.16, 0.20, 26, sweep=380),
        "drop": mix(tone([300], 0.22, 0.24, 18, sweep=-120), tone([900], 0.08, 0.05, 50)),
        "whoosh": noise(0.32, 0.10, 300, 5000),
        "whoosh_soft": noise(0.26, 0.05, 500, 4000),
        "chime": mix(tone([880, 1318.5], 0.9, 0.11, 5), tone([1760], 0.5, 0.03, 9)),
        "swell": mix(noise(1.4, 0.05, 150, 2500), tone([146.83, 220], 1.4, 0.05, 1.6)),
    }
    for t0, kind in events:
        add(t0, lib[kind])
    peak = np.abs(out).max()
    if peak > 0.95:
        out *= 0.95 / peak
    return out


audio = synth(DURATION + 0.2, S.sfx)
wav = OUT.with_suffix(".wav")
with wave.open(str(wav), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(48000)
    wf.writeframes((audio * 32767).astype(np.int16).tobytes())

from filemorph.core.converters.media import ffmpeg_exe  # noqa: E402
subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(OUT.with_suffix(".video.mp4")), "-i", str(wav),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(OUT)],
               check=True)
OUT.with_suffix(".video.mp4").unlink()
wav.unlink()
print("wrote", OUT)
shutil.rmtree(WORK, ignore_errors=True)
