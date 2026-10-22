"""Render the app mark to assets/icon.png and a multi-size assets/icon.ico."""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from filemorph.ui.widgets import app_icon_pixmap  # noqa: E402

app = QApplication([])
assets = ROOT / "assets"
assets.mkdir(exist_ok=True)
images = []
for size in (16, 24, 32, 48, 64, 128, 256):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_icon_pixmap(size).save(buf, "PNG")
    images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
images[-1].save(assets / "icon.png")
images[-1].save(assets / "icon.ico", sizes=[im.size for im in images], append_images=images[:-1])
print("wrote", assets / "icon.ico")
