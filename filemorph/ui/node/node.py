"""The floating Morph node — canvas option B, "Shape-shift".

idle        96px orb, conic aura rim, slow breath, caption on mouse-over
hover       file dragged over: grows to 120px, wobbles, bobbing down-arrow, "Release to convert"
picking     stretches into a pill of format chips; a white indicator springs to the hovered chip
converting  shrinks back to an orb that fills with liquid (moving wave) + percentage
done        check-mark draws itself, shockwave ring, squash-and-stretch, "<file> saved"
error       shake + red caption (click for details)

Everything is painted with QPainter on a frameless, translucent, always-on-top window.
Fully transparent pixels are click-through on Windows, so only the orb catches the mouse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFontMetricsF, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from . import motion as mo
from . import style as st

W, H = 500, 330          # window size (transparent around the node; fits the pill at spring overshoot)
CX, CY = W / 2, 188      # node centre inside the window
CW = 64                  # chip width in the pill
CAP_TOP = 34             # caption pill top edge
BASE = 96                # idle orb size


@dataclass
class Chip:
    key: str
    label: str
    more: bool = False
    enter: mo.Pulse = field(default_factory=lambda: mo.Pulse(0.55, mo.soft))


@dataclass
class Caption:
    parts: list  # [(kind, text)] kind in: text, dim, k, shiny, ok, alert
    born: mo.Pulse = field(default_factory=lambda: mo.Pulse(0.55, mo.spring))


class NodeWindow(QWidget):
    dropped = Signal(list)          # list[Path]
    clicked = Signal()              # orb clicked (idle/done/error)
    chip_picked = Signal(str)       # format key
    more_clicked = Signal()
    cancel_requested = Signal()
    stop_requested = Signal()      # cancel a running conversion (click or Esc while converting)
    menu_requested = Signal(QPoint)  # global pos
    moved = Signal(QPoint)          # new centre (global)

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("FileMorph")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(W, H)
        self._on_top = True
        self._apply_flags()

        self.c1, self.c2, self.c3 = (QColor(c) for c in st.COLORWAYS[st.DEFAULT_WAY])
        self.mode = "idle"
        self.wt, self.ht, self.brt = mo.Tween(BASE), mo.Tween(BASE), mo.Tween(BASE / 2)
        self.inset = mo.Tween(2, 0.6)
        self.glow = mo.Tween(0.2, 0.6, mo.ease_in_out)
        self.glow_r = mo.Tween(130, 0.6, mo.ease_in_out)  # tighter at rest so desktop icons stay clickable
        self.ind_x = mo.Tween(0, 0.5)
        self.ind_op = mo.Tween(0, 0.25, mo.linear)
        self.fill = mo.Tween(0, 0.15, mo.linear)
        self.glyph_in = mo.Pulse(0.55, mo.spring)
        self.check = mo.Pulse(0.5, mo.soft, delay=0.15)
        self.shock = mo.Pulse(0.85, mo.soft)
        self.squash = mo.Pulse(0.75, mo.linear)
        self.shake = mo.Pulse(0.5, mo.linear)
        self.mode_t = mo.now()
        self.spin = 0.0
        self.spin_speed = mo.Tween(60, 0.6, mo.ease_in_out)  # deg/s: 360/6s idle, 300 (1.2s) when busy
        self.last_t = mo.now()

        self.chips: list[Chip] = []
        self.hover_idx = -1
        self.progress = 0.0
        self.caption: Caption | None = None
        self.mouse_inside = False
        self.intro_until = mo.now() + 4.0  # show the idle hint briefly on launch
        self.intro_cap = mo.Pulse(0.55, mo.spring)
        self.intro_cap.fire()
        self._hover_cap = mo.Pulse(0.55, mo.spring)

        self._press: QPoint | None = None
        self._press_win: QPoint | None = None
        self._dragging = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._frame)
        self.timer.start(16)
        self.glyph_in.fire()

    # ------------------------------------------------------------- setup
    def _apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if self._on_top:
            flags |= Qt.WindowStaysOnTopHint
        vis = self.isVisible()
        self.setWindowFlags(flags)
        if vis:
            self.show()

    def set_on_top(self, on: bool):
        if on != self._on_top:
            self._on_top = on
            self._apply_flags()

    def set_colorway(self, colors: tuple[str, str, str]):
        self.c1, self.c2, self.c3 = (QColor(c) for c in colors)
        self.update()

    def center_global(self) -> QPoint:
        return self.pos() + QPoint(int(CX), int(CY))

    def move_center(self, p: QPoint):
        self.move(p - QPoint(int(CX), int(CY)))

    # ------------------------------------------------------------- states
    def _go(self, mode: str):
        prev = self.mode
        self.mode = mode
        self.mode_t = mo.now()
        if mode != "picking":
            self.glyph_in.fire()
        if mode in ("hover",):
            self.wt.to(120), self.ht.to(120), self.brt.to(40)
            self.inset.to(8)
        elif mode == "picking":
            w = len(self.chips) * CW + 12
            self.wt.to(w), self.ht.to(68), self.brt.to(34)
            self.inset.to(2)
        else:
            self.wt.to(BASE), self.ht.to(BASE), self.brt.to(BASE / 2)
            self.inset.to(2)
        busy = mode in ("hover", "converting")
        self.glow.to(0.42 if busy else 0.2)
        self.glow_r.to(205 if busy else 130)
        self.spin_speed.to(300 if mode in ("hover", "converting") else 60)
        if mode != "picking":
            self.hover_idx = -1
            self.ind_op.set(0)
        if prev != mode:
            self.update()

    def show_idle(self):
        self.caption = None
        self.progress = 0
        self.fill.set(0)
        self._go("idle")

    def show_picking(self, badge: str, name: str, chips: list[tuple[str, str]], more: bool):
        self.chips = [Chip(k, lbl) for k, lbl in chips]
        if more:
            self.chips.append(Chip("__more__", "•••", more=True))
        for i, c in enumerate(self.chips):
            c.enter.fire(delay=0.2 + i * 0.05)
        self.hover_idx = -1
        self.ind_op.set(0)
        self._set_caption([("k", badge), ("trunc", name), ("dim", "→ pick a format")])
        self._go("picking")
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def show_converting(self, text: str):
        self.progress = 0
        self.fill.set(0)
        self._set_caption([("shiny", text)])
        self._go("converting")

    def set_progress(self, p: float, text: str | None = None):
        self.progress = max(self.progress, min(1.0, p))
        self.fill.to(self.progress)
        if text and self.caption and self.caption.parts and self.caption.parts[0][0] == "shiny" \
                and self.caption.parts[0][1] != text:
            self.caption.parts = [("shiny", text)]

    def show_done(self, name: str, suffix: str = "saved"):
        self.fill.to(1.0)
        self.progress = 1.0
        self._set_caption([("ok", ""), ("trunc", name), ("dim", suffix)])
        self._go("done")
        self.check.fire()
        self.shock.fire()
        self.squash.fire()

    def show_cancelled(self):
        self.show_idle()
        self._set_caption([("dim", "Cancelled")])

    def show_error(self, msg: str):
        self._set_caption([("alert", ""), ("text", "Couldn't convert"), ("dim", "· click for details")])
        self.error_msg = msg
        self._go("error")
        self.shake.fire()

    def _set_caption(self, parts):
        self.caption = Caption(parts)
        self.caption.born.fire()

    # ------------------------------------------------------------- geometry
    def _shape_rect(self) -> QRectF:
        w, h = self.wt.value(), self.ht.value()
        return QRectF(-w / 2, -h / 2, w, h)

    def _radius(self, r: QRectF) -> float:
        return max(0.0, min(self.brt.value(), r.width() / 2, r.height() / 2))

    def _transform(self) -> QTransform:
        """Whole-shape motion: breath / wobble / squash / shake, around the node centre."""
        t = mo.now()
        tr = QTransform()
        tr.translate(CX, CY)
        if self.mode == "idle":
            s = 1 + 0.05 * mo.keyframe_wave(mo.loop(3.6, t))
            tr.scale(s, s)
        elif self.mode == "hover":
            k = mo.keyframe_wave(mo.loop(1.3, t - self.mode_t))
            tr.rotate(9 * k)
            tr.scale(1 + 0.04 * k, 1 + 0.04 * k)
        elif self.mode == "done" and self.squash.running:
            p = self.squash.raw()
            sx = mo.keyframes(p, [(0, 1), (.3, 1.25), (.55, .9), (.78, 1.04), (1, 1)])
            sy = mo.keyframes(p, [(0, 1), (.3, .78), (.55, 1.1), (.78, .97), (1, 1)])
            tr.scale(sx, sy)
        elif self.mode == "error" and self.shake.running:
            p = self.shake.raw()
            tr.translate(math.sin(p * math.pi * 6) * 7 * (1 - p), 0)
        return tr

    def _chip_rect(self, i: int, r: QRectF) -> QRectF:
        n = max(1, len(self.chips))
        cw = (r.width() - 12) / n
        return QRectF(r.left() + 6 + i * cw, r.top() + 6, cw, r.height() - 12)

    def _chip_at(self, pos: QPointF) -> int:
        if self.mode != "picking":
            return -1
        inv, ok = self._transform().inverted()
        p = inv.map(pos)
        r = self._shape_rect()
        for i in range(len(self.chips)):
            if self._chip_rect(i, r).contains(p):
                return i
        return -1

    def _in_shape(self, pos: QPointF) -> bool:
        inv, _ = self._transform().inverted()
        p = inv.map(pos)
        r = self._shape_rect().adjusted(-4, -4, 4, 4)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius(r), self._radius(r))
        return path.contains(p)

    # ------------------------------------------------------------- frame loop
    def showEvent(self, e):  # noqa: N802
        self.last_t = mo.now()
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        self.timer.stop()  # no frames at all while the node is hidden (panel open / tray only)
        super().hideEvent(e)

    def _frame(self):
        t = mo.now()
        dt = min(0.1, t - self.last_t)
        self.last_t = t
        self.spin = (self.spin + dt * self.spin_speed.value()) % 360
        if self.mode == "idle" and self.caption is None and not self.mouse_inside \
                and not any(x.active for x in (self.wt, self.ht, self.brt, self.glow)):
            # idle: ~15 fps is plenty for the slow breath and aura spin, and keeps CPU near zero
            self.timer.setInterval(66)
        else:
            self.timer.setInterval(16)
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        self._paint_glow(p)
        if self.mode == "done" and self.shock.running:
            self._paint_shock(p)
        p.save()
        p.setTransform(self._transform())
        r = self._shape_rect()
        rad = self._radius(r)
        self._paint_shadow(p, r, rad)
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        self._paint_aura(p, r)
        self._paint_inner(p, r, rad)
        if self.mode == "converting" and self.fill.value() > 0.001:
            self._paint_fill(p, r)
        if self.mode == "picking":
            self._paint_chips(p, r)
        else:
            self._paint_content(p)
        p.restore()
        # 0 0 0 1px rgba(255,255,255,.1) outline
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), rad + 0.5, rad + 0.5)
        p.restore()
        self._paint_caption(p)
        p.end()

    def _paint_glow(self, p: QPainter):
        # canvas: 380px circle of c1, blur(100px), opacity .2 idle / .42 on drop
        a = self.glow.value()
        rad = self.glow_r.value()
        g = QRadialGradient(QPointF(0, 0), rad)
        c = QColor(self.c1)
        for pos, k in ((0, 0.95), (0.3, 0.8), (0.55, 0.5), (0.8, 0.16), (1, 0)):
            c.setAlphaF(a * k)
            g.setColorAt(pos, QColor(c))
        # The window is shorter than the big drop glow: squash it vertically so it fades out
        # inside the window instead of being cut off by a hard edge.
        ry = min(rad, H - CY - 2, CY - 2)
        p.save()
        p.translate(CX, CY)
        p.scale(1.0, ry / rad if rad > 0 else 1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, 0), rad, rad)
        p.restore()

    def _paint_shock(self, p: QPainter):
        k = self.shock.value()
        rad = 48 * (1 + 1.8 * k)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.75 * (1 - k) * 1.2) if k < 1 else 0), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(CX, CY), rad, rad)

    def _paint_shadow(self, p: QPainter, r: QRectF, rad: float):
        # box-shadow: 0 30px 60px -18px rgba(0,0,0,.75) — approximated with stacked soft layers
        p.setPen(Qt.NoPen)
        layers = 10
        for i in range(layers):
            k = (i + 1) / layers
            grow = -18 + 30 * k
            rr = r.adjusted(-grow, -grow + 30, grow, grow + 30)
            if rr.width() <= 0 or rr.height() <= 0:
                continue
            p.setBrush(QColor(0, 0, 0, int(255 * 0.75 / layers * (1.25 - k))))
            rd = max(0.0, min(rad + grow, rr.width() / 2, rr.height() / 2))
            p.drawRoundedRect(rr, rd, rd)

    def _paint_aura(self, p: QPainter, r: QRectF):
        g = QConicalGradient(QPointF(0, 0), -self.spin + 90)
        g.setColorAt(0.0, self.c1)
        g.setColorAt(1 / 3, self.c3)   # CSS conic runs clockwise; Qt counter-clockwise
        g.setColorAt(2 / 3, self.c2)
        g.setColorAt(1.0, self.c1)
        p.fillRect(r.adjusted(-2, -2, 2, 2), QBrush(g))

    def _paint_inner(self, p: QPainter, r: QRectF, rad: float):
        ins = self.inset.value()
        inner = r.adjusted(ins, ins, -ins, -ins)
        if inner.width() <= 0 or inner.height() <= 0:
            return
        cx = inner.left() + inner.width() * 0.3
        cy = inner.top() + inner.height() * 0.2
        far = max(math.hypot(cx - x, cy - y) for x in (inner.left(), inner.right())
                  for y in (inner.top(), inner.bottom()))
        g = QRadialGradient(QPointF(cx, cy), far)
        g.setColorAt(0.0, QColor(255, 255, 255, int(255 * 0.16)))
        g.setColorAt(0.62, QColor(12, 14, 21, int(255 * 0.9)))
        g.setColorAt(1.0, QColor(12, 14, 21, int(255 * 0.9)))
        rr = max(0.0, rad - ins)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(inner, rr, rr)

    def _paint_fill(self, p: QPainter, r: QRectF):
        h = r.height() * self.fill.value()
        top = r.bottom() - h
        p.setPen(Qt.NoPen)
        p.setBrush(self.c2)
        p.drawRect(QRectF(r.left(), top, r.width(), h + 1))
        # wave: 200% wide, scrolls left by 50% every 1.1s
        phase = mo.loop(1.1)
        ww = r.width() * 2
        x0 = r.left() - phase * r.width()
        sx, sy = ww / 200, 11 / 20
        path = QPainterPath()
        y = top - 10
        pts = [(0, 10), (25, 0, 50, 10), (75, 20, 100, 10), (125, 0, 150, 10), (175, 20, 200, 10)]
        path.moveTo(x0, y + 10 * sy)
        for q in pts[1:]:
            path.quadTo(x0 + q[0] * sx, y + q[1] * sy, x0 + q[2] * sx, y + q[3] * sy)
        path.lineTo(x0 + ww, y + 20 * sy)
        path.lineTo(x0, y + 20 * sy)
        path.closeSubpath()
        p.drawPath(path)

    def _glyph_xform(self, p: QPainter):
        k = self.glyph_in.value()
        s = 0.4 + 0.6 * k
        p.rotate(-30 * (1 - self.glyph_in.raw()) if self.glyph_in.raw() < 1 else 0)
        p.scale(s, s)
        p.setOpacity(min(1.0, self.glyph_in.raw() * 2.2))

    def _paint_content(self, p: QPainter):
        p.save()
        white = QColor("#ffffff")
        if self.mode == "idle":
            self._glyph_xform(p)
            self._icon(p, [("M", 4, 8.5), ("h", 14), ("l", -3.5, -3.5), ("M", 20, 15.5), ("H", 6), ("l", 3.5, 3.5)],
                       30, 1.9, white)
        elif self.mode == "hover":
            if mo.now() - self.mode_t > 0.5:
                p.translate(0, 4 * mo.keyframe_wave(mo.loop(1.0, mo.now() - self.mode_t - 0.5)))
            self._glyph_xform(p)
            self._icon(p, [("M", 12, 4), ("v", 15), ("M", 6, 13), ("l", 6, 6), ("l", 6, -6)], 28, 2.0, white)
        elif self.mode == "converting":
            p.setFont(st.font(18, 600, mono=True))
            p.setPen(white)
            p.drawText(QRectF(-60, -14, 120, 28), Qt.AlignCenter, f"{round(self.progress * 100)}%")
        elif self.mode == "done":
            self._paint_check(p)
        elif self.mode == "error":
            self._glyph_xform(p)
            self._icon(p, [("M", 12, 6.5), ("v", 7), ("M", 12, 17.2), ("v", 0.3)], 30, 2.4, QColor(st.DANGER))
        p.restore()

    def _icon(self, p: QPainter, cmds, size: float, width: float, color: QColor):
        """Draw a 24-unit stroke icon centred at the origin."""
        s = size / 24
        path = QPainterPath()
        x = y = 0.0
        for c in cmds:
            op = c[0]
            if op == "M":
                x, y = c[1], c[2]
                path.moveTo(x, y)
            elif op == "l":
                x, y = x + c[1], y + c[2]
                path.lineTo(x, y)
            elif op == "h":
                x += c[1]
                path.lineTo(x, y)
            elif op == "H":
                x = c[1]
                path.lineTo(x, y)
            elif op == "v":
                y += c[1]
                path.lineTo(x, y)
        p.save()
        p.scale(s, s)
        p.translate(-12, -12)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.restore()

    def _paint_check(self, p: QPainter):
        k = self.check.value() if self.check.started else 0.0
        path = QPainterPath()
        path.moveTo(5.5, 12.5)
        path.lineTo(9.7, 16.7)
        path.lineTo(18.5, 7.3)
        s = 34 / 24
        p.scale(s, s)
        p.translate(-12, -12)
        if k <= 0:
            return
        total = path.length()
        part = QPainterPath()
        part.moveTo(path.pointAtPercent(0))
        steps = 24
        for i in range(1, steps + 1):
            part.lineTo(path.pointAtPercent(path.percentAtLength(total * k * i / steps)))
        pen = QPen(QColor("#ffffff"), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(part)

    def _paint_chips(self, p: QPainter, r: QRectF):
        n = len(self.chips)
        if not n:
            return
        cw = (r.width() - 12) / n
        # indicator (white pill with glow) under the hovered chip
        op = self.ind_op.value()
        if op > 0.01:
            ir = QRectF(r.left() + 6 + self.ind_x.value() * cw / CW, r.top() + 6, cw, r.height() - 12)
            p.setPen(Qt.NoPen)
            for i in range(6):  # 0 0 24px rgba(255,255,255,.3)
                g = 2 + i * 3
                p.setBrush(QColor(255, 255, 255, int(255 * 0.3 * op / 6 * (1 - i / 6))))
                p.drawRoundedRect(ir.adjusted(-g, -g, g, g), ir.height() / 2 + g, ir.height() / 2 + g)
            c = QColor(st.INDICATOR)
            c.setAlphaF(op)
            p.setBrush(c)
            p.drawRoundedRect(ir, ir.height() / 2, ir.height() / 2)
        f = st.font(13, 600, mono=True, spacing_em=0.04)
        p.setFont(f)
        for i, chip in enumerate(self.chips):
            if not chip.enter.started:
                continue
            k = chip.enter.value()
            cr = self._chip_rect(i, r)
            p.save()
            p.translate(cr.center())
            p.translate(0, 8 * (1 - k))
            sc = 0.7 + 0.3 * k
            p.scale(sc, sc)
            p.setOpacity(min(1.0, k * 1.4))
            on = i == self.hover_idx and op > 0.5
            col = QColor("#0a0b10") if on else QColor(st.INK)
            if chip.more:
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                for dx in (-7, 0, 7):
                    p.drawEllipse(QPointF(dx, 0), 2.1, 2.1)
            else:
                p.setPen(col)
                p.drawText(QRectF(-cr.width() / 2, -14, cr.width(), 28), Qt.AlignCenter, chip.label)
            p.restore()

    # ------------------------------------------------------------- caption
    def _caption_parts(self):
        if self.caption:
            if self.mode == "converting" and self.mouse_inside:
                return self.caption.parts + [("dim", "· click to cancel")], self.caption.born
            return self.caption.parts, self.caption.born
        if self.mode == "idle" and (self.mouse_inside or mo.now() < self.intro_until):
            return [("dim", "Drop a file · click to open")], self.intro_cap
        if self.mode == "hover":
            return [("text", "Release to convert")], self._hover_cap
        return None, None

    def _paint_caption(self, p: QPainter):
        parts, born = self._caption_parts()
        if not parts:
            return
        if self.mode == "picking" and not self.caption:
            return
        fs = st.font(13)
        fk = st.font(11, 700, mono=True, spacing_em=0.06)
        fm, fmk = QFontMetricsF(fs), QFontMetricsF(fk)
        items = []  # (kind, text, width)
        for kind, text in parts:
            if kind == "k":
                items.append((kind, text, fmk.horizontalAdvance(text) + 12))
            elif kind in ("ok", "alert"):
                items.append((kind, text, 14))
            else:
                if kind == "trunc":
                    text = fm.elidedText(text, Qt.ElideMiddle, 190)
                items.append((kind, text, fm.horizontalAdvance(text)))
        gap = 8
        inner_w = sum(i[2] for i in items) + gap * (len(items) - 1)
        w, h = inner_w + 28, 31
        k = born.value() if born else 1
        raw = born.raw() if born else 1
        p.save()
        p.translate(CX, CAP_TOP + h / 2)
        p.translate(0, -8 * (1 - k))
        sc = 0.88 + 0.12 * k
        p.scale(sc, sc)
        p.setOpacity(min(1.0, raw * 2.0))
        box = QRectF(-w / 2, -h / 2, w, h)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(st.CAP_BG)
        p.drawRoundedRect(box, h / 2, h / 2)
        x = box.left() + 14
        for kind, text, iw in items:
            if kind == "k":
                kr = QRectF(x, -9.5, iw, 19)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(255 * 0.12)))
                p.drawRoundedRect(kr, 6, 6)
                p.setFont(fk)
                p.setPen(QColor(st.INK))
                p.drawText(kr, Qt.AlignCenter, text)
            elif kind == "ok":
                p.save()
                p.translate(x + 7, 0)
                self._icon(p, [("M", 5, 12.5), ("l", 4.5, 4.5), ("l", 9.5, -9.5)], 14, 2.6, QColor(st.SUCCESS))
                p.restore()
            elif kind == "alert":
                p.save()
                p.translate(x + 7, 0)
                p.setPen(QPen(QColor(st.DANGER), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(0, 0), 6.2, 6.2)
                pen = QPen(QColor(st.DANGER), 1.8)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(0, -3), QPointF(0, 0.8))
                p.drawPoint(QPointF(0, 3.2))
                p.restore()
            elif kind == "shiny":
                path = QPainterPath()
                path.addText(QPointF(x, fm.ascent() / 2 - fm.descent() / 2 + 1), fs, text)
                ph = mo.loop(1.8)
                span = iw * 2.2
                off = x + (1.2 - 2.4 * ph) * iw * 0.5 - span * 0.1
                g = QLinearGradient(QPointF(off, -iw * 0.36), QPointF(off + span, iw * 0.36))
                g.setColorAt(0.3, QColor("#8f96aa"))
                g.setColorAt(0.5, QColor("#ffffff"))
                g.setColorAt(0.7, QColor("#8f96aa"))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawPath(path)
            else:
                p.setFont(fs)
                p.setPen(QColor(st.DIM if kind == "dim" else st.INK))
                p.drawText(QRectF(x, -h / 2, iw + 2, h), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += iw + gap
        p.restore()

    # ------------------------------------------------------------- input
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.RightButton:
            self.menu_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton or not self._in_shape(e.position()):
            e.ignore()
            return
        self._press = e.globalPosition().toPoint()
        self._press_win = self.pos()
        self._dragging = False

    def mouseMoveEvent(self, e):  # noqa: N802
        pos = e.position()
        inside = self._in_shape(pos)
        if inside != self.mouse_inside:
            self.mouse_inside = inside
            if inside and self.mode == "idle" and not self.caption:
                self.intro_cap.fire()
        self.setCursor(Qt.PointingHandCursor if inside else Qt.ArrowCursor)
        if self._press is not None:
            d = e.globalPosition().toPoint() - self._press
            if not self._dragging and (abs(d.x()) + abs(d.y())) > 4:
                self._dragging = True
            if self._dragging:
                self.move(self._press_win + d)
                return
        if self.mode == "picking":
            self._set_hover(self._chip_at(pos))

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._press is None:
            return
        dragged = self._dragging
        self._press = None
        self._dragging = False
        if dragged:
            self.moved.emit(self.center_global())
            return
        if self.mode == "picking":
            i = self._chip_at(e.position())
            if i >= 0:
                self._pick(i)
        elif self.mode in ("idle", "done", "error"):
            self.clicked.emit()
        elif self.mode == "converting":
            self.stop_requested.emit()

    def leaveEvent(self, e):  # noqa: N802
        self.mouse_inside = False
        if self.mode == "picking":
            self._set_hover(-1)

    def _set_hover(self, i: int):
        if i == self.hover_idx:
            return
        self.hover_idx = i
        if i >= 0:
            if self.ind_op.end < 0.5:
                self.ind_x.set(i * CW)  # appear in place, then glide between chips
            self.ind_x.to(i * CW, 0.5, mo.spring)
            self.ind_op.to(1, 0.25)
        else:
            self.ind_op.to(0, 0.25)

    def _pick(self, i: int):
        chip = self.chips[i]
        if chip.more:
            self.more_clicked.emit()
        else:
            self.chip_picked.emit(chip.key)

    def keyPressEvent(self, e):  # noqa: N802
        if self.mode == "picking":
            n = len(self.chips)
            if e.key() in (Qt.Key_Right, Qt.Key_Tab):
                self._set_hover((self.hover_idx + 1) % n)
            elif e.key() in (Qt.Key_Left, Qt.Key_Backtab):
                self._set_hover((self.hover_idx - 1) % n if self.hover_idx >= 0 else n - 1)
            elif e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._pick(max(0, self.hover_idx))
            elif e.key() == Qt.Key_Escape:
                self.cancel_requested.emit()
            return
        if e.key() == Qt.Key_Escape and self.mode == "converting":
            self.stop_requested.emit()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.mode == "idle":
            self.clicked.emit()

    def focusNextPrevChild(self, nxt):  # noqa: N802 - keep Tab inside the chip row
        return False if self.mode == "picking" else super().focusNextPrevChild(nxt)

    # drag & drop
    def _accepts(self, e) -> bool:
        md = e.mimeData()
        return md.hasUrls() and any(u.isLocalFile() for u in md.urls()) and self.mode != "converting"

    def dragEnterEvent(self, e):  # noqa: N802
        if self._accepts(e):
            e.acceptProposedAction()
            self._prev_mode = self.mode
            self._hover_cap.fire()
            self._saved_caption = self.caption
            self.caption = None
            self._go("hover")
        else:
            e.ignore()

    def dragMoveEvent(self, e):  # noqa: N802
        if self._accepts(e):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):  # noqa: N802
        if self.mode == "hover":
            prev = getattr(self, "_prev_mode", "idle")
            if prev == "picking":
                self.caption = getattr(self, "_saved_caption", None)
                self._go("picking")
            else:
                self.show_idle()

    def dropEvent(self, e):  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.dropped.emit(paths)
        else:
            self.show_idle()
