"""Windows capture behavior for the application's own window."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_window_from_capture(window_id: int) -> bool:
    """Keep the app visible to the user while screen grabs see behind it."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return False
    api = ctypes.windll.user32.SetWindowDisplayAffinity
    api.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.restype = wintypes.BOOL
    return bool(api(wintypes.HWND(window_id), WDA_EXCLUDEFROMCAPTURE))
