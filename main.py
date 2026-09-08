"""SaveDeck entry point.

Usage:
    python main.py                start with the window visible
    python main.py --minimized    start hidden in the system tray (autostart)
"""
from __future__ import annotations

import os
import re
import sys
import threading
import tkinter as tk

from savedeck import APP_NAME, VERSION
from savedeck import library as lib
from savedeck.library import migrate_from_cartridge
from savedeck.engine.config import Config
from savedeck.engine.engine import BackupEngine
from savedeck.engine.single_instance import acquire, focus_existing
from savedeck.ui.app import SaveDeckApp
from savedeck import theme as T

APP_TITLE = f"SaveDeck v{VERSION} - game library + save protection"


def _make_tray(root: tk.Tk, config, engine, on_quit):
    """System tray icon (optional - needs pystray + pillow)."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    img = Image.new("RGB", (64, 64), (10, 15, 11))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([16, 6, 48, 58], radius=6, outline=(74, 222, 128), width=3)
    d.rectangle([24, 14, 40, 24], outline=(74, 222, 128), width=2)
    d.line([16, 44, 48, 44], fill=(74, 222, 128), width=2)

    def _open(icon=None, item=None):
        def show():
            from savedeck.engine.single_instance import hide_helper_windows
            root.deiconify()
            root.lift()
            root.focus_force()
            hide_helper_windows()
        root.after(0, show)

    def _backup_all(icon=None, item=None):
        for g in config.games:
            if g.enabled and g.paths:
                engine.backup_now(g.id)

    def _toggle_pause(icon=None, item=None):
        if engine.is_paused():
            engine.resume()
        else:
            engine.pause()

    def _quit(icon=None, item=None):
        if icon:
            icon.stop()
        root.after(0, on_quit)

    menu = pystray.Menu(
        pystray.MenuItem(f"Open {APP_NAME}", _open, default=True),
        pystray.MenuItem("Back up all games now", _backup_all),
        pystray.MenuItem("Pause backups", _toggle_pause,
                         checked=lambda item: engine.is_paused()),
        pystray.MenuItem("Quit", _quit),
    )
    icon = pystray.Icon("savedeck", img, APP_NAME, menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def _startup_update_check(engine):
    """Best-effort update notice for packaged builds (never blocks startup)."""
    if not getattr(sys, "frozen", False):
        return
    if engine.config.settings.get("check_updates", True) is False:
        return

    def worker():
        import time
        time.sleep(5)  # let the app settle first
        from savedeck import notify, update
        try:
            current, latest, url, name = update.check()
            if update.is_newer(latest, current) and url:
                notify.notify(
                    "SaveDeck - update available",
                    f"Version v{latest} is out. Open Settings > "
                    f"'Check for updates...' to install it.")
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def main():
    if not acquire():
        focus_existing()  # already running: just bring that window forward
        return

    imported = migrate_from_cartridge()
    if imported:
        print(f"SaveDeck: imported {imported} game(s) from Cartridge")

    config = Config()
    engine = BackupEngine(config)
    engine.start()

    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(900, 560)
    T.apply(root)
    saved_geo = config.settings.get("geometry", "")
    if isinstance(saved_geo, str) and \
            re.match(r"^\d+x\d+[+-]\d+[+-]\d+$", saved_geo):
        root.geometry(saved_geo)  # remembered size/position
    else:
        root.geometry("1220x800")
        T.center_on_screen(root, 1220, 800)
    app = SaveDeckApp(root, config, engine)

    minimized = "--minimized" in sys.argv[1:]
    state = {"tray": None, "quit": False}

    def quit_app():
        state["quit"] = True
        app.save_geometry()
        engine.stop()
        try:
            root.destroy()
        except tk.TclError:
            pass

    state["tray"] = _make_tray(root, config, engine, on_quit=quit_app)
    _startup_update_check(engine)

    def on_close():
        if state["tray"] is not None:
            app.save_geometry()
            root.withdraw()  # keep protecting saves in the background
        else:
            quit_app()

    if minimized:
        root.withdraw()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    if not state["quit"]:
        engine.stop()


if __name__ == "__main__":
    main()
