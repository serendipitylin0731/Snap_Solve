"""Windows capture behavior for the application's own window."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


WDA_EXCLUDEFROMCAPTURE = 0x11


def foreground_window() -> int | None:
    if sys.platform != "win32":
        return None
    api = ctypes.windll.user32.GetForegroundWindow
    api.argtypes = []
    api.restype = wintypes.HWND
    return api() or None


def restore_foreground(window_id: int | None) -> None:
    if sys.platform != "win32" or not window_id:
        return
    api = ctypes.windll.user32.SetForegroundWindow
    api.argtypes = [wintypes.HWND]
    api.restype = wintypes.BOOL
    api(wintypes.HWND(window_id))


def exclude_window_from_capture(window_id: int) -> bool:
    """Keep the app visible to the user while screen grabs see behind it."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return False
    api = ctypes.windll.user32.SetWindowDisplayAffinity
    api.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.restype = wintypes.BOOL
    return bool(api(wintypes.HWND(window_id), WDA_EXCLUDEFROMCAPTURE))
