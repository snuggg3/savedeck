"""Main SaveDeck window — header, tile grid, status bar.

Performance notes: the engine starts on daemon threads, tiles paint before
cover art loads (art is fetched/downscaled once per image in worker threads
and cached on disk), and the status bar refreshes on a lazy 15 s timer, so
the window appears in well under a second and idles near-zero CPU.
"""
from __future__ import annotations

import datetime as dt
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from concurrent.futures import ThreadPoolExecutor

from savedeck import VERSION, art, detect, launch
from savedeck import library as lib
from savedeck import theme as T
from savedeck.ui import dialogs

IMG_W, IMG_H = 170, 255   # 2:3 portrait (Steam library covers)
TILE_W = 190
PAD = 14
SOURCE_LABEL = {"steam": "STEAM", "epic": "EPIC", "gog": "GOG",
                "manual": "MANUAL"}


def time_ago(iso: str) -> str:
    if not iso:
        return "never"
    try:
        ts = dt.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return "never"
    secs = (dt.datetime.now() - ts).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                continue
    return total


class SaveDeckApp:
    def __init__(self, root: tk.Tk, config, engine):
        self.root = root
        self.config = config
        self.engine = engine
        self.lib = lib.load_library()
        self.showing_hidden = False
        self.q = queue.Queue()
        self._imgs = {}          # entry id -> PhotoImage (prevent GC)
        self._cols = 0
        engine.log_cb = lambda level, msg: self.q.put(("log", level, msg))
        self._build_header()
        self._build_grid()
        self._build_status()
        self._bind_keys()
        self.populate()
        self.root.after(150, self._poll)
        self.root.after(15000, self._refresh_status_loop)

    # -- layout -------------------------------------------------------------
    def _build_header(self):
        header = ttk.Frame(self.root, style="Crust.TFrame",
                           padding=(14, 10, 14, 10))
        header.pack(fill="x", side="top")
        ttk.Label(header, text="▞ SAVEDECK", style="Logo.TLabel").pack(side="left")

        self.search_var = tk.StringVar()
        self._search_job = None
        self.search_var.trace_add("write", self._on_search)  # debounced
        self.search = ttk.Entry(header, textvariable=self.search_var, width=24)
        self.search.pack(side="left", padx=(24, 6))

        self.sort_var = tk.StringVar(value="A → Z")
        sort = ttk.Combobox(header, textvariable=self.sort_var, state="readonly",
                            width=9,
                            values=("A → Z", "Z → A", "Recently backed up"))
        sort.pack(side="left", padx=(16, 0))
        sort.bind("<<ComboboxSelected>>", lambda _e: self.populate())

        btns = ttk.Frame(header, style="Crust.TFrame")
        btns.pack(side="right")
        self.hidden_btn = ttk.Button(btns, text="HIDDEN",
                                     command=self.open_hidden)
        self.hidden_btn.pack(side="left", padx=3)
        self.pw_btn = ttk.Button(btns, text="🔑 PASSWORD",
                                 command=self.set_password)
        # password management lives inside the hidden view
        ttk.Button(btns, text="SCAN", command=self.scan).pack(side="left", padx=3)
        ttk.Button(btns, text="+ ADD", command=self.add_manual).pack(
            side="left", padx=3)
        ttk.Button(btns, text="⚙ SETTINGS", command=self.open_settings).pack(
            side="left", padx=3)

    def _on_search(self, *_args):
        """Debounce search repopulation (one rebuild per pause in typing)."""
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(180, self._search_apply)

    def _search_apply(self):
        self._search_job = None
        self.populate()

    def _build_grid(self):
        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(mid, bg=T.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=T.BG)
        self._inner_win = self.canvas.create_window((0, 0), window=self.inner,
                                                    anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _build_status(self):
        bar = ttk.Frame(self.root, style="Crust.TFrame", padding=(14, 4, 14, 4))
        bar.pack(fill="x", side="bottom")
        self.status_left = ttk.Label(bar, text="", style="Crust.TLabel")
        self.status_left.pack(side="left")
        self.status_msg = ttk.Label(bar, text="", style="CrustMuted.TLabel")
        self.status_msg.pack(side="left", padx=(20, 0))
        # every tray action is also available here
        right = ttk.Frame(bar, style="Crust.TFrame")
        right.pack(side="right")
        ttk.Label(right, text=f"v{VERSION}",
                  style="CrustMuted.TLabel").pack(side="left", padx=(8, 4))
        self.pause_btn = ttk.Button(right, text="⏸ PAUSE", width=9,
                                    command=self.toggle_pause_all)
        self.pause_btn.pack(side="left", padx=2)
        ttk.Button(right, text="⇪ BACKUP ALL", width=12,
                   command=self.backup_all).pack(side="left", padx=2)
        ttk.Button(right, text="⏏ EXIT", width=7,
                   command=self.quit_app).pack(side="left", padx=2)

    def _bind_keys(self):
        self.root.bind("/", self._focus_search)
        self.root.bind("<Control-f>", self._focus_search)
        self.root.bind("<Escape>", self._clear_search)
        self.root.bind("<F5>", lambda _e: self.scan())

    def _focus_search(self, _e=None):
        self.search.focus_set()
        return "break"

    def _clear_search(self, _e=None):
        self.search_var.set("")
        self.canvas.focus_set()

    def _on_wheel(self, e):
        # never scroll into blank space when the whole grid fits the view
        region = self.canvas.cget("scrollregion").split()
        if len(region) == 4:
            try:
                if int(region[3]) - int(region[1]) <= self.canvas.winfo_height():
                    return
            except (ValueError, tk.TclError):
                pass
        delta = -1 if getattr(e, "delta", 120) > 0 or getattr(e, "num", 0) == 4 else 1
        self.canvas.yview_scroll(delta * 3, "units")

    def _on_resize(self, event):
        cols = max(1, (event.width - PAD) // (TILE_W + 10))
        if cols != self._cols:
            self._cols = cols
            self.populate()

    # -- population ------------------------------------------------------------
    def _backup_ts(self, entry: dict) -> str:
        game = self._sp_game(entry)
        return game.last_backup if game else ""

    def visible_games(self) -> list:
        query = self.search_var.get().lower().strip()
        games = [g for g in self.lib["games"]
                 if bool(g.get("hidden")) == self.showing_hidden]
        if query:
            games = [g for g in games if query in g.get("name", "").lower()]
        mode = self.sort_var.get()
        if mode == "Recently backed up":
            games.sort(key=self._backup_ts, reverse=True)
            games.sort(key=lambda g: not g.get("favorite"))  # stable: favs first
            return games
        reverse = mode == "Z → A"
        return sorted(games, key=lambda g: (not g.get("favorite"),
                                            g.get("name", "").lower()),
                      reverse=reverse)

    def populate(self):
        games = self.visible_games()
        # skip the (relatively expensive) rebuild when nothing visible changed
        sig = tuple((g.get("id"), g.get("favorite"), self._meta_line(g))
                    for g in games)
        if sig == getattr(self, "_last_sig", None) and self.inner.winfo_children():
            return
        self._last_sig = sig
        for child in self.inner.winfo_children():
            child.destroy()
        cols = self._cols or 4
        for i, entry in enumerate(games):
            self._make_tile(self.inner, entry).grid(
                row=i // cols, column=i % cols, padx=5, pady=8, sticky="n")
        for c in range(cols):
            self.inner.columnconfigure(c, weight=1)
        if not games:
            msg = ("no hidden games" if self.showing_hidden
                   else "no games - press SCAN or + ADD")
            ttk.Label(self.inner, text=msg, style="Faint.TLabel").grid(
                row=0, column=0, pady=60)
        # fresh content starts at the top - never show blank space above row 0
        self.canvas.yview_moveto(0)
        self._refresh_status()

    def _sp_game(self, entry: dict):
        return self.config.get_game(entry.get("sp_id") or "")

    def _make_tile(self, parent, entry: dict) -> tk.Frame:
        tile = tk.Frame(parent, bg=T.PANEL, highlightthickness=1,
                        highlightbackground=T.BORDER)
        img = tk.Label(tile, bg=T.PANEL, width=IMG_W, height=IMG_H, anchor="center")
        img.pack(padx=4, pady=(4, 0))
        name = entry.get("name", "")
        star = "★ " if entry.get("favorite") else ""
        ttk.Label(tile, text=f"{star}{name[:26]}", style="Bold.TLabel").pack(
            padx=4, pady=(4, 0))
        ttk.Label(tile, text=self._meta_line(entry), style="Faint.TLabel",
                  font=T.FONT_SMALL).pack(padx=4, pady=(0, 2))

        row = tk.Frame(tile, bg=T.PANEL)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text="▶ RUN", width=8, style="Accent.TButton",
                   command=lambda: self.run_game(entry)).pack(side="left")
        ttk.Button(row, text="★", width=3,
                   command=lambda: self.toggle_favorite(entry)).pack(
            side="left", padx=3)
        ttk.Button(row, text="⋯", width=3,
                   command=lambda: self.tile_menu(entry, tile)).pack(side="left")

        for w in (tile, img):
            w.bind("<Double-Button-1>", lambda _e, en=entry: self.run_game(en))
            w.bind("<Button-3>",
                   lambda e, en=entry, t=tile: self.tile_menu(en, t, e))
            w.bind("<Enter>", lambda _e, t=tile: t.configure(
                highlightbackground=T.GREEN))
            w.bind("<Leave>", lambda _e, t=tile: t.configure(
                highlightbackground=T.BORDER))
        self._load_art(entry, img)
        return tile

    def _meta_line(self, entry: dict) -> str:
        src = SOURCE_LABEL.get(entry.get("source"), "MANUAL")
        game = self._sp_game(entry)
        if game is None:
            return f"{src} · UNPROTECTED"
        if not game.enabled or not game.paths:
            return f"{src} · ○ OFF"
        dot = {"ok": "●", "error": "▲", "never": "○"}.get(game.last_status, "○")
        return f"{src} · {dot} {time_ago(game.last_backup)}"

    def _load_art(self, entry: dict, label: tk.Label):
        size = (IMG_W, IMG_H)

        def worker():
            p = art.tile_image(entry, size)
            if p:
                self.q.put(("art", entry.get("id", ""), p, label))

        threading.Thread(target=worker, daemon=True).start()


    @staticmethod
    def _game_folder(entry: dict) -> str:
        """Best-effort install/source folder for a library entry."""
        path = entry.get("installPath") or ""
        if os.path.isdir(path):
            return path
        target = (entry.get("launchTarget") or "").strip()
        if target and "://" not in target:
            m = re.match(r'^"([^"]+)"', target)
            exe = m.group(1) if m else target.split()[0].strip('"')
            if os.path.isfile(exe):
                return os.path.dirname(exe)
        return ""

    def open_folder(self, entry: dict):
        folder = self._game_folder(entry)
        if folder:
            os.startfile(folder)

    def tile_menu(self, entry: dict, tile: tk.Frame, event=None):
        menu = tk.Menu(tile, tearoff=0, bg=T.PANEL, fg=T.TEXT,
                       activebackground=T.SURFACE, activeforeground=T.GREEN,
                       font=T.FONT_SMALL)
        menu.add_command(label="▶ Run", command=lambda: self.run_game(entry))
        if self._game_folder(entry):
            menu.add_command(label="Open folder",
                             command=lambda: self.open_folder(entry))
        game = self._sp_game(entry)
        if game:
            menu.add_command(label="⛨ Back up now",
                             command=lambda: self.backup_now(entry))
            menu.add_command(label="Restore saves...",
                             command=lambda: dialogs.VersionsDialog(
                                 tile, self.engine, game, on_done=self.populate))
        menu.add_separator()
        menu.add_command(label="Favorite",
                         command=lambda: self.toggle_favorite(entry))
        menu.add_command(label="Protect saves..." if not game
                         else "Edit protection...",
                         command=lambda: self.protect_game(entry))
        menu.add_command(label="Edit...",
                         command=lambda: self.edit_game(entry))
        menu.add_command(label="Unhide" if entry.get("hidden") else "Hide",
                         command=lambda: self.toggle_hidden(entry))
        menu.add_separator()
        menu.add_command(label="Remove from library",
                         command=lambda: self.remove_game(entry))
        # open at the cursor: a fixed tile offset makes the button release land
        # on a random item and "click" it
        if event is not None:
            x, y = event.x_root, event.y_root
        else:
            x, y = tile.winfo_rootx() + 20, tile.winfo_rooty() + 20
        try:
            menu.tk_popup(x, y + 1)
        finally:
            menu.grab_release()

    # -- actions --------------------------------------------------------------
    def backup_all(self):
        n = 0
        for g in self.config.games:
            if g.enabled and g.paths:
                self.engine.backup_now(g.id)
                n += 1
        self._set_status_msg(f"backing up {n} protected game(s)..."
                             if n else "no protected games to back up")

    def toggle_pause_all(self):
        if self.engine.is_paused():
            self.engine.resume()
            self._set_status_msg("backups resumed")
        else:
            self.engine.pause()
            self._set_status_msg("backups paused")
        self._refresh_status()

    def quit_app(self):
        """Full exit (window close only hides to the tray)."""
        self.engine.stop()
        self.root.destroy()

    def run_game(self, entry: dict):
        if self.config.settings.get("confirm_launch") and \
                not messagebox.askyesno(
                    "SaveDeck", f"Launch \"{entry.get('name')}\"?",
                    parent=self.root):
            return
        try:
            launch.launch(entry)
        except Exception as e:
            messagebox.showerror("SaveDeck", f"Could not launch "
                                             f"\"{entry.get('name')}\":\n{e}",
                                 parent=self.root)
            return
        game = self._sp_game(entry)
        if game and game.process_names:
            launch.watch_session(game.process_names, self.engine, game.id,
                                 log=lambda m: self.q.put(("log", "info",
                                                           f"{game.name}: {m}")))
        self._set_status_msg(f"launching {entry.get('name')}...")

    def backup_now(self, entry: dict):
        game = self._sp_game(entry)
        if game:
            self.engine.backup_now(game.id)
            self._set_status_msg(f"backing up {entry.get('name')}...")

    def toggle_favorite(self, entry: dict):
        entry["favorite"] = not entry.get("favorite")
        lib.save_library(self.lib)
        self.populate()

    def toggle_hidden(self, entry: dict):
        entry["hidden"] = not entry.get("hidden")
        lib.save_library(self.lib)
        self.populate()

    def remove_game(self, entry: dict):
        if not messagebox.askyesno(
                "SaveDeck",
                f"Remove \"{entry.get('name')}\" from the library?\n\n"
                "Backed-up saves are kept in the cloud.", parent=self.root):
            return
        self.lib["games"] = [g for g in self.lib["games"]
                             if g.get("id") != entry.get("id")]
        lib.save_library(self.lib)
        self.populate()

    def protect_game(self, entry: dict):
        dialogs.GameDialog(self.root, self, entry, protect=True)

    def edit_game(self, entry: dict):
        dialogs.GameDialog(self.root, self, entry, protect=False)

    def add_manual(self):
        entry = lib.new_entry("New game")
        if dialogs.GameDialog(self.root, self, entry, protect=False,
                              is_new=True).saved:
            self.lib["games"].append(entry)
            lib.save_library(self.lib)
            self.populate()

    def open_hidden(self):
        if not self.showing_hidden and lib.hidden_password_set():
            dialogs.PasswordDialog(self.root, on_ok=self._toggle_hidden_view)
        else:
            self._toggle_hidden_view()

    def _toggle_hidden_view(self):
        self.showing_hidden = not self.showing_hidden
        self.hidden_btn.configure(
            text="LIBRARY" if self.showing_hidden else "HIDDEN")
        if self.showing_hidden:
            self.pw_btn.pack(side="left", padx=3, after=self.hidden_btn)
        else:
            self.pw_btn.pack_forget()
        self.populate()

    def set_password(self):
        dialogs.PasswordSetDialog(self.root)

    def open_settings(self):
        dialogs.SettingsDialog(self.root, self)

    # -- scan ----------------------------------------------------------------
    def scan(self):
        self._set_status_msg("scanning for installed games...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            detected = detect.detect_installed_games()
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [(g, pool.submit(detect.fetch_epic_thumbnail, g["name"]))
                           for g in detected if g["source"] == "epic"]
                for g, fut in futures:
                    g["thumb"] = fut.result()
            for g in detected:
                if g.get("installPath") and not g.get("sizeBytes"):
                    g["sizeBytes"] = dir_size(g["installPath"])
            self.q.put(("scan_done", detected))
        except Exception as e:
            self.q.put(("log", "error", f"Scan failed: {e}"))

    def _apply_scan(self, detected: list):
        installed = {g["name"].lower(): g for g in detected}
        added = updated = removed = 0
        keep = []
        for entry in self.lib["games"]:
            src = entry.get("source")
            det = installed.pop(entry.get("name", "").lower(), None) \
                if src in ("steam", "epic", "gog") else None
            if det:
                for field in ("installPath", "launchTarget", "sizeBytes"):
                    if det.get(field):
                        entry[field] = det[field]
                if det.get("thumb") and not entry.get("thumbnail"):
                    entry["thumbnail"] = det["thumb"]
                updated += 1
            elif (src in ("steam", "epic", "gog") and not entry.get("favorite")
                  and not entry.get("hidden") and not entry.get("sp_id")):
                removed += 1
                continue  # uninstalled: drop it (Cartridge parity)
            keep.append(entry)
        installed_names = {e["name"].lower() for e in keep}
        for key, det in installed.items():
            if key in installed_names:
                continue
            keep.append(lib.new_entry(
                det["name"], source=det["source"], thumbnail=det.get("thumb"),
                installPath=det.get("installPath"),
                launchTarget=det.get("launchTarget"),
                sizeBytes=det.get("sizeBytes")))
            added += 1
        self.lib["games"] = keep
        self.lib["lastScan"] = dt.datetime.now().isoformat(timespec="seconds")
        lib.save_library(self.lib)
        self.populate()
        self._set_status_msg(f"scan complete: {added} added, "
                             f"{updated} updated, {removed} removed")
        unprotected = sum(1 for e in keep if not e.get("sp_id"))
        if unprotected:
            self._set_status_msg(f"scan complete - {unprotected} game(s) "
                                 f"have no save protection yet")

    # -- status / polling -----------------------------------------------------
    def _set_status_msg(self, msg: str):
        try:
            self.status_msg.configure(text=msg)
        except tk.TclError:
            pass

    def _refresh_status(self):
        games = self.lib["games"]
        protected = sum(1 for e in games if self._sp_game(e))
        paused = self.engine.is_paused()
        state = "PAUSED" if paused else "PROTECTING"
        self.status_left.configure(
            text=f"{len(games)} GAMES · {state} {protected} · "
                 f"last scan {time_ago(self.lib.get('lastScan'))}")
        if hasattr(self, "pause_btn"):
            self.pause_btn.configure(text="▶ RESUME" if paused else "⏸ PAUSE")

    def _refresh_status_loop(self):
        self._refresh_status()
        # Tk helper windows (menus/ttk popdowns) must stay hidden; external
        # app-activation (keybind relaunches) can make them visible
        from savedeck.engine.single_instance import hide_helper_windows
        hide_helper_windows()
        self.root.after(15000, self._refresh_status_loop)

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    _k, level, text = msg
                    self._set_status_msg(text)
                    notify_on = self.config.settings.get("notify_on_failures",
                                                         True)
                    if level == "error" and notify_on:
                        from savedeck import notify
                        notify.notify("SaveDeck - backup failed", text)
                elif kind == "art":
                    _k, eid, path, label = msg
                    try:
                        from PIL import ImageTk
                        img = ImageTk.PhotoImage(file=path)
                        self._imgs[eid] = img
                        label.configure(image=img, width=IMG_W, height=IMG_H)
                    except Exception:
                        pass
                elif kind == "scan_done":
                    self._apply_scan(msg[1])
        except queue.Empty:
            pass
        self.root.after(150, self._poll)




