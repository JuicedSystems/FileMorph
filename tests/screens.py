"""Render the real window in each state to PNGs (headless). usage: screens.py <samples> <outdir> [--dark]"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(ms=150):
    end = time.time() + ms / 1000
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def main():
    samples, out = Path(sys.argv[1]), Path(sys.argv[2])
    dark = "--dark" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    from filemorph.ui import theme as th
    if dark:
        th.current = lambda: th.DARK  # force dark for the screenshot
    app = QApplication([])
    app.setStyle("Fusion")
    QSettings("FileMorph", "FileMorph").clear()
    app.setFont(th.ui_font(10))
    from filemorph.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(600, 700)
    w.show()
    pump()
    suf = "_dark" if dark else ""

    def shot(name):
        pump(200)
        w.grab().save(str(out / f"{name}{suf}.png"))

    shot("1_empty")
    w.drop.set_active(True)
    shot("1b_dragging")
    w.drop.set_active(False)

    w.add_files([samples / "sample.pdf"], replace=True)
    shot("2_choose_pdf")

    w.add_files([samples / "sample.heic", samples / "sample.png", samples / "sample.jpg"], replace=True)
    for b in w.chip_group.buttons():
        if b.fmt.key == "pdf":
            b.setChecked(True)
    shot("3_choose_multi_images")

    w.add_files([samples / "sample.png"], replace=True)
    for b in w.chip_group.buttons():
        if b.fmt.key == "svg":
            b.setChecked(True)
    shot("3b_png_svg_options")

    w.add_files([samples / "sample.mp4"], replace=True)
    shot("3c_video")

    # real conversion -> progress -> done
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    QSettings("FileMorph", "FileMorph").setValue("save_mode", "custom")
    QSettings("FileMorph", "FileMorph").setValue("save_dir", str(tmp))
    w.add_files([samples / "sample.pdf", samples / "sample.docx", samples / "sample.xlsx"], replace=True)
    for b in w.chip_group.buttons():
        if b.fmt.key == "pdf":
            b.setChecked(True)
    w.opt_widgets["combine"].setChecked(True)
    shot("3d_mixed_combine")
    w.start()
    w._on_progress(1, 0.45, "Laying out page 1")
    w.ring._anim.stop()
    w.ring._set_value(0.48)
    shot("4_progress")
    t0 = time.time()
    while w.stack.currentWidget() is not w.page_done and time.time() - t0 < 120:
        pump(100)
    shot("5_done")

    # error state
    bad = tmp / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    w.add_files([bad, samples / "sample.pdf"], replace=True)
    for b in w.chip_group.buttons():
        if b.fmt.key == "docx":
            b.setChecked(True)
    w.start()
    t0 = time.time()
    while w.stack.currentWidget() is not w.page_done and time.time() - t0 < 120:
        pump(100)
    shot("6_done_partial")
    print("results:", [(r[0].name, len(r[1]), r[2][:60]) for r in w.results])


if __name__ == "__main__":
    main()
