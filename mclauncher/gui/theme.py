from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

ACCENTS: dict[str, str] = {
    "blue": "#0F6CBD",
    "green": "#107C10",
    "purple": "#8764B8",
    "orange": "#CA5010",
}

THEMES = {
    "auto": Theme.AUTO,
    "light": Theme.LIGHT,
    "dark": Theme.DARK,
}


def apply_theme(mode: str = "auto", accent: str = "blue") -> None:
    setTheme(THEMES.get(mode, Theme.AUTO))
    setThemeColor(ACCENTS.get(accent, ACCENTS["blue"]))


def rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"


def ui_font() -> str:
    if sys.platform == "win32":
        return "Segoe UI Variable Text"
    if sys.platform == "darwin":
        return "SF Pro Text"
    return "Noto Sans CJK SC"


def apply_font(app: QApplication) -> None:
    font = QFont(ui_font(), 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)


def palette() -> dict[str, str]:
    dark = isDarkTheme()
    return {
        "bg": "#202020" if dark else "#F3F3F3",
        "layer": "#272727" if dark else "#FFFFFF",
        "card": "#2B2B2B" if dark else "#FFFFFF",
        "card_alt": "#323232" if dark else "#FAFAFA",
        "text": "#FFFFFF" if dark else "#1A1A1A",
        "secondary": "#C8C8C8" if dark else "#5C5C5C",
        "tertiary": "#9A9A9A" if dark else "#8A8A8A",
        "border": "#3D3D3D" if dark else "#E5E5E5",
        "accent": "#4CC2FF" if dark else "#0F6CBD",
        "success": "#6CCB5F",
        "warning": "#FCE100",
        "danger": "#FF99A4" if dark else "#C42B1C",
        "hover": "#383838" if dark else "#F5F5F5",
        "selected": "#2D4A63" if dark else "#E5F1FB",
    }
