"""Design tokens for the Morph node UI (canvas option B: Shape-shift)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from ...core.formats import FORMATS

# Colorways from the canvas: conic aura colours c1, c2, c3
COLORWAYS: dict[str, tuple[str, str, str]] = {
    "Prism": ("#7c5cff", "#22d3ee", "#f472b6"),
    "Citrus": ("#a3e635", "#14b8a6", "#facc15"),
    "Frost": ("#e2e8f0", "#60a5fa", "#ffffff"),
}
DEFAULT_WAY = "Prism"

# Surfaces & text
BG = "#0a0b10"
INK = "#eef0f6"
DIM = "#a3a9ba"
LABEL = "#8d93a6"
SOFT_TEXT = "#c9cdd8"
INDICATOR = "#f5f6fa"
CAP_BG = QColor(13, 15, 22, int(0.84 * 255))
PANEL_BG = QColor(15, 17, 25, 255)  # canvas uses .82 + 30px backdrop blur; no blur on a desktop window
SUCCESS = "#7ee2a8"
DANGER = "#ff7a85"
SWITCH_ON = "#4f7cff"

# File-kind colours (canvas KINDS)
KIND_COLOR = {"image": "#6d28d9", "video": "#be185d", "audio": "#0f766e", "document": "#b45309",
              "sheet": "#b45309", "slides": "#b45309", "tools": "#0e7490", "other": "#475569"}


def kind_color(fmt_key: str | None) -> QColor:
    f = FORMATS.get(fmt_key or "")
    return QColor(KIND_COLOR.get(f.category if f else "other", KIND_COLOR["other"]))


_loaded = False
SANS = "Geist"
MONO = "Geist Mono"


def load_fonts() -> None:
    """Register the bundled Geist fonts (falls back to Segoe UI if missing)."""
    global _loaded, SANS, MONO
    if _loaded:
        return
    _loaded = True
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3])) / "assets" / "fonts"
    fams = set()
    for f in sorted(base.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            fams.update(QFontDatabase.applicationFontFamilies(fid))
    if "Geist" not in fams:
        SANS = "Segoe UI Variable Text" if sys.platform == "win32" else "Inter"
    if "Geist Mono" not in fams:
        MONO = "Cascadia Mono" if sys.platform == "win32" else "DejaVu Sans Mono"


def font(px: float, weight: int = 400, mono: bool = False, spacing_em: float = 0.0) -> QFont:
    f = QFont(MONO if mono else SANS)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing_em:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * spacing_em)
    return f


def qc(hex_or_color, alpha: float | None = None) -> QColor:
    c = QColor(hex_or_color)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c
