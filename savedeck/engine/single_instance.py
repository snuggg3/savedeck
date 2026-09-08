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
        hide_helper_windows()
        return True
    except Exception:
        return False


# Tk keeps hidden helper top-level windows around for menus and ttk
# dropdowns. Relaunching the exe (app-activation paths, e.g. a PowerToys
# keybind) can make Windows show them alongside the main window; they must
# never be visible, so we hide them again whenever SaveDeck takes focus.
HELPER_WINDOW_TITLES = ("TtkMonitorWindow", "EmbeddedMenuWindow",
                        "MenuWindow", "TtkMenuWindow")


def hide_helper_windows():
    """Hide stray visible Tk helper windows (menus / ttk popdowns)."""
    if sys.platform != "win32":
        return
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles = {t.lower() for t in HELPER_WINDOW_TITLES}
        strays = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                   wintypes.LPARAM)

        def on_window(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if buf.value.strip().lower() in titles:
                        strays.append(hwnd)
            return True

        enum_cb = proto(on_window)
        user32.EnumWindows(enum_cb, 0)
        for hwnd in strays:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass  # cosmetic cleanup - must never break launching/focusing
