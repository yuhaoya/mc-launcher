from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor, themeColor

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


def accent_color(dark: bool | None = None) -> QColor:
    """跟随用户所选主题色的强调色。

    深色主题下自动提亮，否则深绿/深紫压在黑底上几乎看不清。
    """
    color = QColor(themeColor())
    if dark is None:
        dark = isDarkTheme()
    if dark:
        h, s, v, a = color.getHsvF()
        color.setHsvF(h, min(1.0, s * 0.8), min(1.0, v + 0.35), a)
    return color


def accent_pair() -> tuple[QColor, QColor]:
    """(浅色主题用色, 深色主题用色)。"""
    return accent_color(False), accent_color(True)


def rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"


def ui_fonts() -> list[str]:
    """按平台给出字体候选；Win7 没有 Segoe UI Variable，会自动落到后两个。"""
    if sys.platform == "win32":
        return ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
    if sys.platform == "darwin":
        return ["SF Pro Text", "PingFang SC", "Helvetica Neue"]
    return ["Noto Sans CJK SC", "Noto Sans", "DejaVu Sans"]


def ui_font() -> str:
    return ui_fonts()[0]


def apply_font(app: QApplication) -> None:
    font = QFont()
    font.setFamilies(ui_fonts())
    font.setPointSize(10)
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
        "accent": accent_color().name(),
        "success": "#6CCB5F",
        "warning": "#FCE100",
        "danger": "#FF99A4" if dark else "#C42B1C",
        "hover": "#383838" if dark else "#F5F5F5",
        "selected": "#2D4A63" if dark else "#E5F1FB",
    }
