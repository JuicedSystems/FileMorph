"""The FileMorph app icon: the orb (colour rim, dark glass core, ⇄ arrows).

One source for the .exe / installer icon (packaging/make_icon.py), the window icon and the
classic window's logo. Small sizes are drawn with a thicker rim and bolder arrows so the mark
stays readable at 16-24 px instead of being a scaled-down 256 px picture.
"""
from __future__ import annotations

RIM = ("#22D3EE", "#8B5CF6", "#F472B6")  # Prism colorway, same as the floating orb


def _params(size: int) -> dict:
    """(outer rim radius, core radius, arrow stroke, arrow paths, highlights) in 256-unit space."""
    big = ("M70 102 H182 L154 74", "M186 154 H74 L102 182")
    if size <= 16:
        return dict(rim=128, core=94, stroke=34, arrows=("M62 100 H188 L160 72", "M194 156 H68 L96 184"), hi=False)
    if size <= 24:
        return dict(rim=126, core=98, stroke=30, arrows=("M64 100 H186 L158 72", "M192 156 H70 L98 184"), hi=False)
    if size <= 40:
        return dict(rim=124, core=102, stroke=26, arrows=("M66 100 H184 L156 72", "M190 156 H72 L100 184"), hi=False)
    if size <= 48:
        return dict(rim=122, core=106, stroke=20, arrows=big, hi=True)
    if size <= 64:
        return dict(rim=122, core=108, stroke=18, arrows=big, hi=True)
    return dict(rim=122, core=110, stroke=15, arrows=big, hi=True)


def icon_svg(size: int = 256) -> str:
    p = _params(size)
    c1, c2, c3 = RIM
    hi = ""
    if p["hi"]:
        hi = (f'<circle cx="128" cy="128" r="{p["core"]}" fill="url(#hi)"/>'
              f'<circle cx="128" cy="128" r="{p["core"]}" fill="url(#hi2)"/>')
    arrows = "".join(f'<path d="{d}"/>' for d in p["arrows"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 256 256">
<defs>
<linearGradient id="rim" x1="0.1" y1="0" x2="0.9" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="0.5" stop-color="{c2}"/><stop offset="1" stop-color="{c3}"/></linearGradient>
<radialGradient id="core" cx="0.33" cy="0.24" r="0.9"><stop offset="0" stop-color="#3d3a6b"/><stop offset="0.5" stop-color="#171a28"/><stop offset="1" stop-color="#0c0e15"/></radialGradient>
<radialGradient id="hi" cx="0.32" cy="0.2" r="0.42"><stop offset="0" stop-color="{c1}" stop-opacity="0.6"/><stop offset="1" stop-color="{c1}" stop-opacity="0"/></radialGradient>
<radialGradient id="hi2" cx="0.72" cy="0.78" r="0.4"><stop offset="0" stop-color="{c3}" stop-opacity="0.28"/><stop offset="1" stop-color="{c3}" stop-opacity="0"/></radialGradient>
</defs>
<circle cx="128" cy="128" r="{p["rim"]}" fill="url(#rim)"/>
<circle cx="128" cy="128" r="{p["core"]}" fill="url(#core)"/>
{hi}
<g fill="none" stroke="#ffffff" stroke-width="{p["stroke"]}" stroke-linecap="round" stroke-linejoin="round">{arrows}</g>
</svg>'''


def render(size: int = 256):
    """QImage (ARGB) of the icon at exactly size x size pixels. Needs a Q(Gui)Application."""
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(icon_svg(size).encode("utf-8")))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    r.render(p)
    p.end()
    return img
