"""Drive the user-initiated update flow through the real panel with a fake Velopack backend.

usage: update_flow.py <out_dir>
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QPoint, QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from filemorph.core.updater import UpdateError, UpdateOffer  # noqa: E402

NOTES = """**New: one-click updates** — check from the ⋯ menu.

- PDF → Excel keeps merged header cells
- HEIC photos keep their date taken
- Faster SVG tracing on large images
"""


class FakeUpdater:
    """Mimics filemorph.core.updater.Updater against a pretend release feed."""

    def __init__(self, scenario="update"):
        self.scenario = scenario
        self.available = True
        self.why_unavailable = None
        self.applied = None

    def current_version(self):
        return "0.3.0"

    def pending_restart(self):
        return None

    def check(self):
        time.sleep(0.6)
        if self.scenario == "current":
            return None
        if self.scenario == "offline":
            raise UpdateError("Couldn't check for updates — check your internet connection and try again.")
        return UpdateOffer("0.4.0", NOTES, 18_400_000, True, raw="info")

    def download(self, offer, progress=None):
        for pct in range(0, 101, 5):
            time.sleep(0.05)
            if progress:
                progress(pct)

    def apply_and_restart(self, offer):
        self.applied = offer.version


def pump(s):
    end = time.time() + s
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    QSettings("FileMorph", "FileMorph").clear()
    app = QApplication([])
    import filemorph.ui.node.controller as ctl
    c = ctl.MorphController(app)
    c.node.move_center(QPoint(600, 520))

    def shot(name):
        w = c.panel
        layer = QImage(w.size(), QImage.Format_ARGB32_Premultiplied)
        layer.fill(QColor("#0b0c12"))
        p = QPainter(layer)
        w.render(p, QPoint())
        p.end()
        layer.save(str(out / f"{name}.png"))

    def wait_for(pred, t=10):
        end = time.time() + t
        while not pred() and time.time() < end:
            pump(0.05)

    # 1) the real updater in a source checkout -> "unavailable"
    c.check_updates()
    pump(1.0)
    shot("u0_unavailable")
    print("real updater available:", c.updater.available)

    # 2) update available -> download -> install
    fake = FakeUpdater("update")
    c.updater = fake
    c.update_runner.updater = fake
    c.check_updates()
    pump(0.3)
    shot("u1_checking")
    wait_for(lambda: c.offer is not None)
    pump(0.8)
    shot("u2_available")
    c.panel.update_install.emit()
    wait_for(lambda: c.panel._upd_progress is not None and c.panel._upd_progress.val.end >= 0.5)
    pump(0.3)
    shot("u3_downloading")
    wait_for(lambda: fake.applied is not None, 8)
    shot("u4_installing")
    print("applied version:", fake.applied)

    # 3) up to date
    fake2 = FakeUpdater("current")
    c.updater = c.update_runner.updater = fake2
    c.check_updates()
    pump(1.4)
    shot("u5_current")

    # 4) offline error
    fake3 = FakeUpdater("offline")
    c.updater = c.update_runner.updater = fake3
    c.check_updates()
    pump(1.4)
    shot("u6_error")

    # 5) blocked while converting
    fake4 = FakeUpdater("update")
    c.updater = c.update_runner.updater = fake4
    c.worker = object()  # pretend a conversion is running
    c.offer = None
    c.check_updates()
    wait_for(lambda: c.offer is not None)
    pump(0.6)
    shot("u7_blocked")
    c.panel.update_install.emit()
    pump(0.5)
    print("install while converting blocked:", fake4.applied is None)
    c.worker = None

    # 6) post-update note on the node
    c.panel.hide()
    c.node.show()
    c.show_updated("0.4.0")
    pump(0.9)
    layer = QImage(c.node.size(), QImage.Format_ARGB32_Premultiplied)
    layer.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer)
    c.node.render(p, QPoint())
    p.end()
    bg = QImage(c.node.size(), QImage.Format_ARGB32_Premultiplied)
    bg.fill(QColor("#0b0c12"))
    p = QPainter(bg)
    p.drawImage(0, 0, layer)
    p.end()
    bg.save(str(out / "u8_updated_note.png"))
    c.tray.hide()


if __name__ == "__main__":
    main()
