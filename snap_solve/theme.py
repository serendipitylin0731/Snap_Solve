"""Application colors, theme preference, and the native Windows caption."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from string import Template

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication


THEME_MODES = ("system", "light", "dark")

LIGHT = {
    "bg": "#f3f7fd", "card": "#ffffff", "text": "#1c2d46",
    "title": "#142845", "muted": "#71839c", "border": "#dfe7f2",
    "button": "#ffffff", "button_hover": "#edf3fb", "input": "#f9fbff",
    "accent": "#326cf0", "accent_hover": "#245bd8", "accent_disabled": "#aac4fb",
    "teal": "#0d9188", "selection": "#bad2ff", "disabled": "#9aa9bc",
}

DARK = {
    "bg": "#111b2b", "card": "#1b2a3e", "text": "#e8f0fb",
    "title": "#f1f6ff", "muted": "#a1b2c8", "border": "#304159",
    "button": "#25364d", "button_hover": "#30465f", "input": "#162438",
    "accent": "#6293ff", "accent_hover": "#79a4ff", "accent_disabled": "#3b527b",
    "teal": "#65d8c9", "selection": "#315a9a", "disabled": "#8293a8",
}

STYLE = Template("""
QWidget { color: $text; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: $bg; }
QFrame#header { background: $bg; border: 0; }
QFrame#questionCard, QFrame#solutionCard {
    background: $card; border: 1px solid $border; border-radius: 16px;
}
QFrame#questionCard { border-top: 3px solid $accent; }
QFrame#solutionCard { border-top: 3px solid $teal; }
QLabel#title { color: $title; font-size: 23px; font-weight: 700; }
QLabel#section { color: $title; font-size: 15px; font-weight: 700; }
QLabel#questionSection { color: $accent; font-size: 15px; font-weight: 700; }
QLabel#solutionSection { color: $teal; font-size: 15px; font-weight: 700; }
QLabel#muted { color: $muted; }
QPushButton {
    border: 1px solid $border; border-radius: 9px; background: $button;
    padding: 9px 15px; font-weight: 600;
}
QPushButton:hover { background: $button_hover; }
QPushButton:disabled { color: $disabled; background: $button_hover; }
QPushButton#primary {
    background: $accent; color: white; border-color: $accent; padding: 10px 20px;
}
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:disabled {
    background: $accent_disabled; border-color: $accent_disabled; color: white;
}
QPushButton#quiet { border: 0; color: $accent; background: transparent; padding: 8px 10px; }
QPushButton#quiet:hover { background: $button_hover; }
QCheckBox { spacing: 9px; font-weight: 600; }
QCheckBox::indicator { width: 17px; height: 17px; }
QSlider::groove:horizontal { height: 5px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    background: $accent; border: 2px solid $card; width: 16px; margin: -7px 0; border-radius: 9px;
}
QSlider::handle:horizontal:hover { background: $accent_hover; }
QPlainTextEdit, QLineEdit, QKeySequenceEdit, QComboBox {
    border: 1px solid $border; border-radius: 10px; background: $input;
    padding: 10px; selection-background-color: $selection;
}
QPlainTextEdit:focus, QLineEdit:focus, QKeySequenceEdit:focus, QComboBox:focus {
    border-color: $accent;
}
QComboBox QAbstractItemView {
    background: $card; color: $text; selection-background-color: $selection;
    border: 1px solid $border;
}
QComboBox::drop-down { border: 0; background: transparent; width: 28px; }
QComboBox::down-arrow { image: none; }
""")


def load_theme_mode() -> str:
    value = QSettings("Snap Solve", "Snap Solve").value("theme_mode", "system")
    return value if value in THEME_MODES else "system"


def save_theme_mode(mode: str) -> None:
    if mode not in THEME_MODES:
        raise ValueError("无效的外观模式")
    QSettings("Snap Solve", "Snap Solve").setValue("theme_mode", mode)


def uses_dark_colors(mode: str) -> bool:
    if mode == "system":
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return mode == "dark"


def style_sheet(dark: bool) -> str:
    return STYLE.substitute(DARK if dark else LIGHT)


def match_native_caption(window, dark: bool) -> bool:
    """Give the Windows 11 caption the same background as the content."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 22000:
        return False
    palette = DARK if dark else LIGHT
    api = ctypes.windll.dwmapi.DwmSetWindowAttribute
    api.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    api.restype = ctypes.c_long
    hwnd = wintypes.HWND(int(window.winId()))

    def set_attribute(attribute: int, value: int) -> bool:
        data = ctypes.c_int(value)
        return api(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0

    def colorref(value: str) -> int:
        color = int(value[1:], 16)
        return ((color & 0xff) << 16) | (color & 0xff00) | (color >> 16)

    set_attribute(20, int(dark))  # DWMWA_USE_IMMERSIVE_DARK_MODE
    caption = set_attribute(35, colorref(palette["bg"]))  # DWMWA_CAPTION_COLOR
    set_attribute(36, colorref(palette["title"]))  # DWMWA_TEXT_COLOR
    set_attribute(34, colorref(palette["bg"]))  # DWMWA_BORDER_COLOR
    return caption
