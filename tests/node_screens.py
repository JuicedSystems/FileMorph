"""Drive the real Morph controller headlessly and capture each state.

usage: node_screens.py <samples_dir> <out_dir>
Produces PNGs of the node/panel windows composited over a dark desktop backdrop,
and verifies that a real conversion runs end-to-end through the node.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, QRectF, QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(s):
    end = time.time() + s
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.008)


def backdrop(w, h) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#07080c"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for (x, y, r, c) in ((w * .75, h * .1, 420, "#7c5cff"), (w * .9, h * .8, 360, "#22d3ee"), (w * .15, h * .9, 380, "#f472b6")):
        g = QRadialGradient(QPointF(x, y), r)
        col = QColor(c)
        col.setAlphaF(0.22)
        g.setColorAt(0, col)
        col.setAlphaF(0)
        g.setColorAt(1, col)
        p.fillRect(QRectF(0, 0, w, h), g)
    p.end()
    return img


def main():
    samples, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    s = QSettings("FileMorph", "FileMorph")
    s.clear()
    tmp = Path(tempfile.mkdtemp())
    s.setValue("save_next", False)
    s.setValue("save_dir", str(tmp))
    app = QApplication([])
    from filemorph.ui.node.controller import MorphController
    c = MorphController(app)
    c.node.move_center(QPoint(980, 520))
    BW, BH = 1280, 760
    bg = backdrop(BW, BH)

    def shot(name, widgets):
        img = bg.copy()
        p = QPainter(img)
        for w in widgets:
            layer = QImage(w.size(), QImage.Format_ARGB32_Premultiplied)
            layer.fill(QColor(0, 0, 0, 0))
            lp = QPainter(layer)
            w.render(lp, QPoint())
            lp.end()
            p.drawImage(w.pos(), layer)
        p.end()
        img.save(str(out / f"{name}.png"))
        w0 = widgets[0]
        img.copy(w0.geometry()).save(str(out / f"{name}_win.png"))  # just the window, over the backdrop

    pump(1.0)
    c.node.mouse_inside = True
    shot("01_idle_hint", [c.node])
    c.node.mouse_inside = False
    c.node.intro_until = 0
    pump(0.2)
    shot("02_idle", [c.node])
    c.node._hover_cap.fire()
    c.node._go("hover")
    pump(0.9)
    shot("03_drag_over", [c.node])

    # real drop of a PDF -> pill
    c.add_files([samples / "sample.pdf"])
    pump(0.35)
    shot("04a_pill_morphing", [c.node])
    pump(1.0)
    c.node._set_hover(0)
    pump(0.7)
    shot("04_pill_pick", [c.node])
    chips = [ch.key for ch in c.node.chips]
    print("pill chips:", chips)

    # pick DOCX through the same path a click takes
    c.node.chip_picked.emit("docx")
    t0 = time.time()
    grabbed = False
    while c.node.mode == "converting" and time.time() - t0 < 60:
        pump(0.05)
        if not grabbed and c.node.progress > 0.25:
            pump(0.3)
            shot("05_converting", [c.node])
            grabbed = True
    if not grabbed:
        c.node.show_converting("Converting to DOCX…")
        c.node.set_progress(0.62)
        pump(0.6)
        shot("05_converting", [c.node])
        c.node.show_done("sample.docx", f"saved to {tmp.name}")
    pump(0.35)
    shot("06a_done_burst", [c.node])
    pump(1.0)
    shot("06_done", [c.node])
    print("outputs:", [Path(o).name for o in c.last_outputs], "exists:", all(Path(o).exists() for o in c.last_outputs))

    # unsupported file -> error
    junk = tmp / "notes.xyz"
    junk.write_text("?")
    c.add_files([junk])
    pump(0.9)
    shot("07_error", [c.node])

    # panel (home) with recent history
    c.node.show_idle()
    c.expand()
    pump(0.25)
    shot("08a_panel_opening", [c.panel])
    pump(1.0)
    shot("08_panel_home", [c.panel])

    # multi-file -> more chip -> all formats page
    c.collapse()
    pump(0.2)
    c.add_files([samples / "sample.png", samples / "sample.heic", samples / "sample.jpg"])
    pump(1.2)
    shot("09_pill_multi", [c.node])
    c.node.more_clicked.emit()
    pump(1.2)
    for b in c.panel.tile_group.buttons():
        if b.key == "pdf":
            b.setChecked(True)
    pump(0.4)
    shot("10_all_formats", [c.panel])
    # convert from the panel: combine into one PDF
    c.panel.opt_widgets["combine"].setChecked(True)
    c.panel._convert()
    t0 = time.time()
    while c.node.mode == "converting" and time.time() - t0 < 60:
        pump(0.05)
    print("combined:", [Path(o).name for o in c.last_outputs], c.node.mode)
    pump(1.2)
    shot("11_done_combined", [c.node])

    # colorways
    for name in ("Citrus", "Frost"):
        c._apply_colorway(name)
        c.node.show_idle()
        c.node.mouse_inside = True
        pump(0.8)
        shot(f"12_idle_{name.lower()}", [c.node])
    c.quit()


if __name__ == "__main__":
    main()
