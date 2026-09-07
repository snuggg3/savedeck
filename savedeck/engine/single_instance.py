"""Single-instance guard.

A named Windows mutex ensures only one SaveDeck runs at a time (two copies
would both watch the same folders and write interleaved log lines). A second
launch focuses the existing window instead of starting a second engine.
"""
from __future__ import annotations

import ctypes
import sys

MUTEX_NAME = r"Local\SaveDeck.SingleInstance"
ERROR_ALREADY_EXISTS = 183

# Keep in sync with the title set in main.py.
APP_TITLE = "SaveDeck v1.0.0 - game library + save protection"

_mutex = None  # keep the handle alive for the process lifetime


def acquire() -> bool:
    """Become the single running SaveDeck.

    Returns False if another copy already holds the mutex (caller should call
    focus_existing() and exit). On non-Windows or if anything fails, always
    allow running - the guard must never prevent the app from starting.
    """
    global _mutex
    if sys.platform != "win32":
        return True
    try:
        k32 = ctypes.windll.kernel32
        _mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
        return k32.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        return True


def focus_existing() -> bool:
    """Bring the already-running instance's window to the foreground."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if not hwnd:
            return False
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
