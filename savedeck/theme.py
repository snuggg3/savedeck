"""SaveDeck UI design system.

Cartridge's phosphor-terminal look (near-black green background, mono type,
1px separators, flat controls) built on the SavePoint theme structure.
Configure once with apply(root); dialogs pick the styles up automatically.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

# -- palette (Cartridge phosphor) -----------------------------------------
BG = "#0a0f0b"       # window background
PANEL = "#0f1712"    # raised surfaces: tiles, inputs, tree rows
CRUST = "#060906"    # deepest layer: header, status bar, log
SURFACE = "#1b2b1f"  # borders, hover, selection
BORDER = "#1d2f22"
TEXT = "#c8e6cd"
MUTED = "#7fae8c"
FAINT = "#4e6a56"
GREEN = "#4ade80"    # accent (phosphor)
RED = "#ff6b81"
YELLOW = "#ffd479"
BLUE = "#6ccaff"

MONO = "Consolas"
FONT = (MONO, 10)
FONT_SMALL = (MONO, 9)
FONT_BOLD = (MONO, 10, "bold")
FONT_TITLE = (MONO, 13, "bold")
FONT_LOGO = (MONO, 14, "bold")

STATUS_COLOR = {"ok": GREEN, "error": RED, "never": FAINT, "warn": YELLOW}


# -- native window frame ---------------------------------------------------
def _set_dark_frame(hwnd) -> None:
    import ctypes
    dwm = ctypes.windll.dwmapi
    on = ctypes.c_int(1)
    for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (pre-20H1: 19)
        if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on),
                                     ctypes.sizeof(on)) == 0:
            break
    r, g, b = int(CRUST[1:3], 16), int(CRUST[3:5], 16), int(CRUST[5:7], 16)
    color = ctypes.c_int((b << 16) | (g << 8) | r)
    dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))


def apply(root: tk.Tk) -> ttk.Style:
    """Configure global ttk styles + root for the terminal theme."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(background=BG)

    style.configure(".", background=BG, foreground=TEXT, font=FONT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Crust.TFrame", background=CRUST)
    style.configure("Sep.TFrame", background=BORDER)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Faint.TLabel", foreground=FAINT)
    style.configure("Bold.TLabel", font=FONT_BOLD)
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("Logo.TLabel", background=CRUST, foreground=GREEN,
                    font=FONT_LOGO)
    style.configure("Crust.TLabel", background=CRUST)
    style.configure("CrustMuted.TLabel", background=CRUST, foreground=MUTED)

    # -- buttons -----------------------------------------------------------
    style.configure("TButton", background=PANEL, foreground=TEXT,
                    bordercolor=BORDER, relief="flat", focusthickness=0,
                    padding=(10, 4))
    style.map("TButton",
              background=[("active", SURFACE), ("pressed", BORDER)],
              foreground=[("active", GREEN)])
    style.configure("Accent.TButton", background=SURFACE, foreground=GREEN,
                    bordercolor=BORDER, relief="flat", focusthickness=0,
                    padding=(10, 4))
    style.map("Accent.TButton",
              background=[("active", BORDER), ("pressed", BORDER)],
              foreground=[("disabled", FAINT)])

    # -- inputs --------------------------------------------------------------
    style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=3)
    style.map("TEntry", bordercolor=[("focus", GREEN)])
    style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", PANEL)],
              foreground=[("readonly", TEXT)])
    style.configure("TSpinbox", fieldbackground=PANEL, background=PANEL,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=2)
    style.configure("TCheckbutton", background=BG, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TRadiobutton", background=BG, foreground=TEXT)
    style.map("TRadiobutton", background=[("active", BG)])
    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=GREEN,
                    font=FONT_SMALL)
    for opt, val in (("*TCombobox*Listbox.background", PANEL),
                     ("*TCombobox*Listbox.foreground", TEXT),
                     ("*TCombobox*Listbox.selectBackground", SURFACE),
                     ("*TCombobox*Listbox.selectForeground", TEXT),
                     ("*TCombobox*Listbox.font", FONT)):
        root.option_add(opt, val)
    enable_dark_title_bar(root)

    # -- treeview + scrollbars -----------------------------------------------
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                    foreground=TEXT, rowheight=24, bordercolor=BORDER,
                    borderwidth=1, font=FONT)
    style.configure("Treeview.Heading", background=CRUST, foreground=MUTED,
                    font=FONT_SMALL, borderwidth=0, padding=(8, 5), relief="flat")
    style.map("Treeview.Heading", background=[("active", CRUST)])
    style.map("Treeview",
              background=[("selected", SURFACE)],
              foreground=[("selected", TEXT)])
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=PANEL,
                        troughcolor=BG, bordercolor=BG, arrowcolor=FAINT,
                        gripcount=0)
        style.map(f"{orient}.TScrollbar",
                  background=[("active", SURFACE), ("pressed", SURFACE)])
    return style


def enable_dark_title_bar(window) -> None:
    """Render the native Windows title bar dark (best effort, never fatal).

    If the window handle does not exist yet (window not shown), a <Map>
    retry is scheduled — the retry never re-binds itself, so a UI that maps
    many child widgets (tile grids etc.) cannot accumulate handlers.
    """
    if sys.platform != "win32":
        return

    def _retry(_event=None):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            if hwnd:
                _set_dark_frame(hwnd)
        except Exception:
            pass

    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            window.bind("<Map>", _retry, add="+")
            return
        _set_dark_frame(hwnd)
    except Exception:
        pass


# -- window placement -----------------------------------------------------------
def center_on_screen(window, width: int = None, height: int = None) -> None:
    """Center a window on the screen (clamped to visible area)."""
    window.update_idletasks()
    sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
    w = width or window.winfo_width()
    h = height or window.winfo_height()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2 - 20)  # slightly above center: looks better
    window.geometry(f"+{x}+{y}")


def center_over_parent(window) -> None:
    """Center a dialog over its parent window (clamped to the screen)."""
    window.update_idletasks()
    try:
        px, py = window.master.winfo_rootx(), window.master.winfo_rooty()
        pw, ph = window.master.winfo_width(), window.master.winfo_height()
        sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
        w, h = window.winfo_width(), window.winfo_height()
        x = max(0, px + (pw - w) // 2)
        y = max(0, py + (ph - h) // 3)
        x = min(x, sw - w) if sw > w else 0
        y = min(y, sh - h - 40) if sh > h else 0
        window.geometry(f"+{x}+{y}")
    except tk.TclError:
        center_on_screen(window)


# -- factory helpers ----------------------------------------------------------
def toplevel(parent, title: str, grab: bool = True,
             resizable=(True, True)) -> tk.Toplevel:
    """A themed modal dialog window, centered over its parent.

    Centering happens twice: immediately (parent-relative) and again on
    <Map>, when the dialog's final content size is known. The <Map> handler
    never re-binds itself, so handler count stays bounded.
    """
    t = tk.Toplevel(parent)
    t.configure(background=BG)
    t.title(title)
    t.transient(parent)
    enable_dark_title_bar(t)
    center_over_parent(t)
    t.bind("<Map>", lambda e: center_over_parent(t) if e.widget is t else None,
           add="+")
    if grab:
        t.grab_set()
    t.resizable(*resizable)
    return t


def text(parent, height: int = 7, wrap: str = "none", **kw) -> tk.Text:
    """A dark monospaced read-only text area (log style)."""
    w = tk.Text(parent, height=height, state="disabled", font=FONT_SMALL,
                background=CRUST, foreground=TEXT, insertbackground=TEXT,
                selectbackground=SURFACE, selectforeground=TEXT,
                relief="flat", borderwidth=0, highlightthickness=1,
                highlightbackground=BORDER, highlightcolor=BORDER,
                padx=8, pady=6, wrap=wrap, **kw)
    for tag, color in (("info", TEXT), ("warn", YELLOW), ("error", RED),
                       ("stamp", FAINT)):
        w.tag_configure(tag, foreground=color)
    return w


def listbox(parent, **kw) -> tk.Listbox:
    return tk.Listbox(parent, font=FONT_SMALL, background=PANEL,
                      foreground=TEXT, selectbackground=SURFACE,
                      selectforeground=TEXT, relief="flat",
                      highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=BORDER, activestyle="none", **kw)


def separator(parent) -> ttk.Frame:
    return ttk.Frame(parent, style="Sep.TFrame", height=1)


