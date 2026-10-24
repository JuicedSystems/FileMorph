"""Colours, fonts and the global stylesheet. Follows the Windows light/dark setting."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication


@dataclass
class Theme:
    dark: bool
    bg: str
    surface: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    ink: str          # primary button / selection
    ink_text: str
    success: str
    danger: str
    danger_bg: str
    warn_bg: str
    warn_text: str
    warn: str = "#E08A00"

    def q(self, name: str, alpha: int | None = None) -> QColor:
        c = QColor(getattr(self, name))
        if alpha is not None:
            c.setAlpha(alpha)
        return c


LIGHT = Theme(False, bg="#F4F4F2", surface="#FFFFFF", surface_hover="#F7F7F6", border="#E4E4E0",
              border_strong="#CFCFC9", text="#1B1B1F", muted="#6B6B73", faint="#9D9DA5",
              ink="#1B1B1F", ink_text="#FFFFFF", success="#16A34A", danger="#DC2626", danger_bg="#FEF2F2",
              warn_bg="#FFF7E6", warn_text="#8A5300")
DARK = Theme(True, bg="#141416", surface="#1D1D21", surface_hover="#25252A", border="#2E2E34",
             border_strong="#45454D", text="#EDEDF0", muted="#A0A0AA", faint="#6E6E78",
             ink="#F2F2F4", ink_text="#141416", success="#4ADE80", danger="#F87171", danger_bg="#2A1618",
             warn_bg="#2B2214", warn_text="#F5C77A", warn="#F5B740")

# One hue per family so a file's type is recognisable at a glance.
CATEGORY_COLOR = {
    "document": "#2F6FEB", "sheet": "#1A9A5B", "slides": "#E0661B",
    "image": "#C2398C", "audio": "#7C4DDB", "video": "#D93A3A", "tools": "#0E7490",
}
FORMAT_COLOR = {"pdf": "#D93A3A", "svg": "#E0901B", "gif": "#B0459C", "json": "#5B6B7F",
                "txt": "#5B6B7F", "md": "#5B6B7F", "html": "#D0532A"}


def color_for(fmt_key: str, category: str) -> QColor:
    return QColor(FORMAT_COLOR.get(fmt_key, CATEGORY_COLOR.get(category, "#666")))


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # pragma: no cover
        return False


def current() -> Theme:
    return DARK if system_is_dark() else LIGHT


def ui_font(size: float = 10, weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    if sys.platform == "win32":
        families = ["Segoe UI Variable Display" if display else "Segoe UI Variable Text", "Segoe UI"]
    elif sys.platform == "darwin":
        families = [".AppleSystemUIFont", "Helvetica Neue"]
    else:
        families = ["Inter", "Cantarell", "Noto Sans", "DejaVu Sans"]
    f = QFont()
    f.setFamilies(families)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def stylesheet(t: Theme) -> str:
    return f"""
    QWidget#Root {{ background: {t.bg}; }}
    QWidget {{ color: {t.text}; }}
    QLabel {{ background: transparent; }}
    QLabel[role="muted"] {{ color: {t.muted}; }}
    QLabel[role="faint"] {{ color: {t.faint}; }}
    QLabel[role="section"] {{ color: {t.muted}; letter-spacing: 0.6px; }}
    QLabel[role="error"] {{ color: {t.danger}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

    QFrame#Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
    QFrame#Banner {{ background: {t.warn_bg}; border-radius: 10px; }}
    QFrame#Banner QLabel {{ color: {t.warn_text}; }}

    QPushButton#Primary {{
        background: {t.ink}; color: {t.ink_text}; border: none; border-radius: 12px;
        padding: 0 22px; min-height: 46px; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {QColor(t.ink).lighter(135 if not t.dark else 92).name()}; }}
    QPushButton#Primary:pressed {{ background: {QColor(t.ink).lighter(160 if not t.dark else 85).name()}; }}
    QPushButton#Primary:disabled {{ background: {t.border}; color: {t.faint}; }}

    QPushButton#Secondary {{
        background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 12px;
        padding: 0 18px; min-height: 44px; font-weight: 600;
    }}
    QPushButton#Secondary:hover {{ background: {t.surface_hover}; }}

    QPushButton#Ghost, QToolButton#Ghost {{
        background: transparent; color: {t.muted}; border: none; border-radius: 8px; padding: 6px 10px;
    }}
    QPushButton#Ghost:hover, QToolButton#Ghost:hover {{ background: {t.border}; color: {t.text}; }}
    QToolButton#Ghost::menu-indicator {{ image: none; width: 0; }}

    QPushButton#Link {{ background: transparent; border: none; color: {t.text}; text-decoration: underline;
        padding: 0; font-weight: 600; }}
    QPushButton#Link:hover {{ color: {t.muted}; }}

    QPushButton#Small {{
        background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 5px 12px;
        color: {t.text}; font-weight: 600;
    }}
    QPushButton#Small:hover {{ background: {t.surface_hover}; border-color: {t.border_strong}; }}

    QPushButton#Seg {{ background: transparent; border: 1px solid {t.border}; padding: 5px 12px; color: {t.muted}; }}
    QPushButton#Seg:checked {{ background: {t.ink}; color: {t.ink_text}; border-color: {t.ink}; }}
    QPushButton#Seg[pos="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
    QPushButton#Seg[pos="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}

    QCheckBox {{ spacing: 8px; color: {t.text}; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid {t.border_strong};
        background: {t.surface}; }}
    QCheckBox::indicator:checked {{ background: {t.ink}; border-color: {t.ink}; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.ink}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.surface}; border: 2px solid {t.ink}; width: 14px; height: 14px;
        margin: -7px 0; border-radius: 9px; }}

    QMenu {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 18px; border-radius: 6px; color: {t.text}; }}
    QMenu::item:selected {{ background: {t.surface_hover}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 6px 8px; border-radius: 6px; }}
    """
