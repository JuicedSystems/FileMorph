"""Render the README images from the real UI (crisp 2x renders over a dark desktop backdrop).

usage: python marketing/readme_media.py <samples_dir> <out_dir>
Writes: states.png (drop -> pick -> convert -> done), panels.png (home / all formats / updates).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DPR = 2


def pump(s):
    end = time.time() + s
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.008)


def backdrop(w, h, seed=0) -> QImage:
    img = QImage(w * DPR, h * DPR, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor("#07080c"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    spots = [((.80, .05), 0.9, "#7c5cff"), ((.95, .95), 0.8, "#22d3ee"), ((.05, .95), 0.85, "#f472b6")]
    if seed % 2:
        spots = [((.15, .05), 0.9, "#7c5cff"), ((.05, .95), 0.8, "#22d3ee"), ((.95, .9), 0.85, "#f472b6")]
    for (fx, fy), fr, c in spots:
        g = QRadialGradient(QPointF(w * fx, h * fy), max(w, h) * fr * 0.6)
        col = QColor(c)
        col.setAlphaF(0.24)
        g.setColorAt(0, col)
        col.setAlphaF(0)
        g.setColorAt(1, col)
        p.fillRect(QRectF(0, 0, w, h), g)
    p.end()
    return img


def grab(widget) -> QImage:
    layer = QImage(widget.width() * DPR, widget.height() * DPR, QImage.Format_ARGB32_Premultiplied)
    layer.setDevicePixelRatio(DPR)
    layer.fill(QColor(0, 0, 0, 0))
    lp = QPainter(layer)
    lp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    widget.render(lp, QPoint())
    lp.end()
    return layer


def tile(widget, w, h, offset=QPoint(0, 0), seed=0) -> QImage:
    """The widget centred on its own piece of backdrop."""
    img = backdrop(w, h, seed)
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    layer = grab(widget)
    x = (w - widget.width()) // 2 + offset.x()
    y = (h - widget.height()) // 2 + offset.y()
    p.drawImage(QPoint(x, y), layer)
    p.end()
    return img


def label(img: QImage, text: str, num: int):
    """Numbered caption along the bottom edge (the app's own captions sit at the top)."""
    from filemorph.ui.node import style as st
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    f = st.font(15, 600)
    p.setFont(f)
    w, h = img.width() / DPR, img.height() / DPR
    y = h - 44
    badge = QRectF(18, y, 26, 26)
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(QColor(255, 255, 255, 18))
    p.drawEllipse(badge)
    p.setPen(QColor("#ffffff"))
    p.setFont(st.font(12, 700, mono=True))
    p.drawText(badge, Qt.AlignCenter, str(num))
    p.setFont(f)
    p.drawText(QRectF(52, y, w - 60, 26), Qt.AlignVCenter | Qt.AlignLeft, text)
    p.end()


def rounded(img: QImage, radius=18) -> QImage:
    out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(DPR)
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, img.width() / DPR, img.height() / DPR), radius, radius)
    p.setClipPath(path)
    p.drawImage(QPoint(0, 0), img)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 28), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.end()
    return out


def row(images: list[QImage], gap=16) -> QImage:
    w = sum(i.width() for i in images) // DPR + gap * (len(images) - 1)
    h = max(i.height() for i in images) // DPR
    out = QImage(w * DPR, h * DPR, QImage.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(DPR)
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    x = 0
    for i in images:
        p.drawImage(QPoint(x, 0), i)
        x += i.width() // DPR + gap
    p.end()
    return out


def main():
    samples, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    s = QSettings("FileMorph", "FileMorph")
    s.clear()
    s.setValue("save_next", True)
    app = QApplication([])
    from filemorph.ui.node.controller import MorphController
    c = MorphController(app)
    c.node.move_center(QPoint(600, 400))
    work = Path(tempfile.mkdtemp())
    report = work / "Q3 Report.pdf"
    shutil.copy(samples / "sample.pdf", report)
    pump(1.0)
    c.node.intro_until = 0

    TW, TH = 420, 360
    shots = []
    # 1 drop
    c.node._hover_cap.fire()
    c.node._go("hover")
    pump(1.0)
    shots.append(("Drop a file on the orb", tile(c.node, TW, TH, QPoint(0, -8))))
    # 2 pick
    c.node._go("idle")
    pump(0.3)
    c.add_files([report])
    pump(1.4)
    c.node._set_hover(0)
    pump(0.8)
    shots.append(("Pick a format", tile(c.node, TW, TH, QPoint(0, -8), 1)))
    # 3 convert (state rendered directly so the shot doesn't depend on conversion speed)
    c.node.show_converting("Converting to DOCX…")
    c.node.set_progress(0.62)
    pump(1.2)
    shots.append(("Watch it morph", tile(c.node, TW, TH, QPoint(0, -8))))
    # 4 done
    c.node.show_done("Q3 Report.docx", "saved")
    pump(1.6)
    shots.append(("Done, saved next to the original", tile(c.node, TW, TH, QPoint(0, -8), 1)))
    tiles = []
    for n, (text, img) in enumerate(shots, 1):
        label(img, text, n)
        tiles.append(rounded(img))
    top = row(tiles[:2])
    bottom = row(tiles[2:])
    grid = QImage(top.width(), top.height() * 2 + 16 * DPR, QImage.Format_ARGB32_Premultiplied)
    grid.setDevicePixelRatio(DPR)
    grid.fill(QColor(0, 0, 0, 0))
    p = QPainter(grid)
    p.drawImage(QPoint(0, 0), top)
    p.drawImage(QPoint(0, top.height() // DPR + 16), bottom)
    p.end()
    grid.save(str(out / "states.png"))

    # ---- panel pages
    now = time.time()
    c.history = [
        {"name": "Vacation.jpg", "from": "HEIC", "to": "JPG", "to_key": "jpg", "at": now - 40, "out": str(work / "a")},
        {"name": "Q3 Report.docx", "from": "PDF", "to": "DOCX", "to_key": "docx", "at": now - 300, "out": str(work / "b")},
        {"name": "Budget.pdf", "from": "XLSX", "to": "PDF", "to_key": "pdf", "at": now - 3600, "out": str(work / "c")},
        {"name": "Interview.mp3", "from": "MOV", "to": "MP3", "to_key": "mp3", "at": now - 7200, "out": str(work / "d")},
        {"name": "Logo.svg", "from": "PNG", "to": "SVG", "to_key": "svg", "at": now - 86400, "out": str(work / "e")},
    ]
    c.files = []
    c.node.show_idle()
    pump(0.3)
    c.expand()
    c.panel.set_recent(c.history)
    pump(1.4)
    PW, PH = 400, 610
    panels = [("Your recent conversions", tile(c.panel, PW, PH, QPoint(0, -24), seed=1))]
    c.collapse()
    pump(0.4)
    c.add_files([report])
    pump(1.0)
    c._open_formats()
    pump(1.4)
    panels.append(("Every format, with options", tile(c.panel, PW, PH, QPoint(0, -24))))
    c.panel.show_updates("available", current="0.3.1", version="0.4.0", size="11.2 MB",
                         notes="- Batch rename on export\n- Faster PDF to Word\n- Sharper SVG tracing\n"
                               "- Smaller downloads with delta updates", blocked="")
    pump(1.2)
    panels.append(("Updates, only when you want them", tile(c.panel, PW, PH, QPoint(0, -24), seed=1)))
    ptiles = []
    for n, (text, img) in enumerate(panels, 1):
        label(img, text, n)
        ptiles.append(rounded(img))
    row(ptiles).save(str(out / "panels.png"))
    print("wrote", out / "states.png", out / "panels.png")
    c.quit()


if __name__ == "__main__":
    main()
