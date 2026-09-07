"""Running-process enumeration (stdlib only, Windows).

Used for two things:
- "don't back up while the game is running" (avoid snapshotting half-written
  save files), and
- auto-detecting played games (match running executables against save folders).

On non-Windows platforms every function degrades gracefully (empty / False).
"""
from __future__ import annotations

import os


def running_process_names() -> list:
    """Lowercased base names of all running executables (e.g. 'cyberpunk2077.exe').

    Returns [] on non-Windows or if enumeration fails.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x2
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value or -1
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap in (0, -1):
            return []
        names, entry = [], PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.append(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
        return names
    except Exception:
        return []


def is_running(executables) -> bool:
    """True if any of `executables` (e.g. ['elden ring.exe']) is running.

    Matching is case-insensitive and a missing '.exe' suffix is tolerated.
    """
    wanted = set()
    for name in executables or []:
        name = (name or "").strip().lower()
        if not name:
            continue
        wanted.add(name)
        wanted.add(name if name.endswith(".exe") else name + ".exe")
    if not wanted:
        return False
    return bool(wanted & set(running_process_names()))
