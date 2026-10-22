"""Render the app icon (the orb) to assets/icon.png and a multi-size assets/icon.ico.

The .ico is used for FileMorph.exe, the installer (FileMorph-win-Setup.exe, via `vpk --icon`),
the Start menu / taskbar and Apps & features. Each size is drawn for its size (see
filemorph/ui/brand_icon.py), not scaled down from 256 px.
"""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from filemorph.ui.brand_icon import render  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # 20/40 = taskbar and Start at 125%/250% scaling

app = QGuiApplication([])
assets = ROOT / "assets"
assets.mkdir(exist_ok=True)
images = []
for size in SIZES:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    render(size).save(buf, "PNG")
    images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
big = images[-1]
big.save(assets / "icon.png")
big.save(assets / "icon.ico", format="ICO", sizes=[im.size for im in images], append_images=images[:-1])
print("wrote", assets / "icon.ico", [im.size[0] for im in images])
