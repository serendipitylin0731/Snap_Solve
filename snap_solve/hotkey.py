"""Capture shortcut persistence and Windows global hotkey registration."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence


DEFAULT_SHORTCUT = "Ctrl+Alt+S"
HOTKEY_ID = 0x5345
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


def load_shortcut() -> QKeySequence:
    value = QSettings("Snap Solve", "Snap Solve").value("capture_shortcut", DEFAULT_SHORTCUT)
    sequence = QKeySequence(str(value))
    try:
        windows_hotkey(sequence)
    except ValueError:
        return QKeySequence(DEFAULT_SHORTCUT)
    return sequence


def save_shortcut(sequence: QKeySequence) -> None:
    QSettings("Snap Solve", "Snap Solve").setValue(
        "capture_shortcut", sequence.toString(QKeySequence.SequenceFormat.PortableText))


def windows_hotkey(sequence: QKeySequence) -> tuple[int, int]:
    if sequence.count() != 1:
        raise ValueError("请选择一组快捷键")
    combination = sequence[0]
    modifiers = combination.keyboardModifiers()
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        raise ValueError("快捷键暂不支持 Win 键")
    flags = MOD_NOREPEAT
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        flags |= MOD_CONTROL
    if modifiers & Qt.KeyboardModifier.AltModifier:
        flags |= MOD_ALT
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        flags |= MOD_SHIFT
    if flags == MOD_NOREPEAT:
        raise ValueError("快捷键需要 Ctrl、Alt 或 Shift")
    key = int(combination.key())
    if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z) or int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        vk = key
    elif int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F11):
        vk = 0x70 + key - int(Qt.Key.Key_F1)
    else:
        raise ValueError("请选择字母、数字或 F1–F11 功能键")
    return flags, vk


def register_hotkey(window_id: int, sequence: QKeySequence) -> bool:
    modifiers, vk = windows_hotkey(sequence)
    if sys.platform != "win32":
        return False
    api = ctypes.windll.user32.RegisterHotKey
    api.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    api.restype = wintypes.BOOL
    return bool(api(wintypes.HWND(window_id), HOTKEY_ID, modifiers, vk))


def unregister_hotkey(window_id: int) -> None:
    if sys.platform != "win32":
        return
    api = ctypes.windll.user32.UnregisterHotKey
    api.argtypes = [wintypes.HWND, ctypes.c_int]
    api.restype = wintypes.BOOL
    api(wintypes.HWND(window_id), HOTKEY_ID)
