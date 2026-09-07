"""SaveDeck dialogs: game/protection editor, settings, restore, password."""
from __future__ import annotations

import os
import threading
import tkinter as tk
import uuid
from tkinter import filedialog, messagebox, ttk

from savepoint.detector import suggest_locations
from savepoint.models import Game, safe_name

from savedeck import library as lib
from savedeck import theme as T


def _add_row(parent, r: int, label: str, widget, hint=None) -> int:
    """Grid a label (col 0) + widget (col 1) [+ optional hint (col 2)] on the
    same row. Returns the next free row."""
    ttk.Label(parent, text=label, style="Muted.TLabel").grid(
        row=r, column=0, sticky="e", padx=(0, 8), pady=3)
    widget.grid(row=r, column=1, sticky="we", pady=3)
    if hint is not None:
        hint.grid(row=r, column=2, padx=(6, 0), sticky="w")
    return r + 1


def _provider_ids():
    from savepoint.providers import provider_ids
    return provider_ids()


class GameDialog:
    """Edit a library entry and its save protection in one place.

    This is the SavePoint→Cartridge integration: the protection half can
    pre-fill save locations from SavePoint's heuristic detector, so going
    from 'game in the library' to 'saves backed up' is one click.
    """

    def __init__(self, parent, app, entry: dict, protect: bool = False,
                 is_new: bool = False):
        self.app = app
        self.entry = entry
        self.saved = False
        self.win = T.toplevel(parent, "SaveDeck - add game" if is_new
                              else "SaveDeck - edit game")
        frame = ttk.Frame(self.win, padding=14)
        frame.pack(fill="both", expand=True)

        # -- library section ------------------------------------------------
        lf = ttk.Labelframe(frame, text="LIBRARY", padding=10)
        lf.grid(row=0, column=0, sticky="ew")
        lf.columnconfigure(0, minsize=110)
        r = 0
        self.name = ttk.Entry(lf, width=44)
        self.name.insert(0, entry.get("name", ""))
        r = _add_row(lf, r, "Name", self.name)
        self.thumb = ttk.Entry(lf, width=44)
        self.thumb.insert(0, entry.get("thumbnail") or "")
        r = _add_row(lf, r, "Thumbnail URL", self.thumb)
        self.target = ttk.Entry(lf, width=44)
        self.target.insert(0, entry.get("launchTarget") or "")
        r = _add_row(
            lf, r, "Launch target", self.target,
            ttk.Label(lf, text="steam:// URL, protocol,\nexe path or command",
                      style="Faint.TLabel", font=T.FONT_SMALL))
        install_box = ttk.Frame(lf)
        self.install = ttk.Entry(install_box, width=36)
        self.install.insert(0, entry.get("installPath") or "")
        self.install.pack(side="left", fill="x", expand=True)
        ttk.Button(install_box, text="...", width=3,
                   command=self._browse_install).pack(side="left", padx=(6, 0))
        r = _add_row(lf, r, "Install path", install_box)
        lf.columnconfigure(1, weight=1)

        # -- protection section ------------------------------------------------
        pf = ttk.Labelframe(frame, text="SAVE PROTECTION", padding=10)
        pf.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        pf.columnconfigure(0, minsize=110)
        settings = app.config.settings
        default_repo = settings.get("default_repo", "")
        game = app.config.get_game(entry.get("sp_id") or "")

        r = 0
        self.provider = tk.StringVar(
            value=(game.provider if game else settings.get("provider", "github")))
        r = _add_row(
            pf, r, "Destination",
            ttk.Combobox(pf, textvariable=self.provider, state="readonly",
                         width=16, values=tuple(_provider_ids())))
        self.repo = ttk.Entry(pf, width=30)
        self.repo.insert(0, (game.repo if game else default_repo))
        r = _add_row(pf, r, "Repository / folder", self.repo,
                     ttk.Label(pf, text="user/repo or folder",
                               style="Faint.TLabel", font=T.FONT_SMALL))
        paths_box = ttk.Frame(pf)
        self.paths = T.listbox(paths_box, height=4, width=42)
        self.paths.pack(side="left", fill="both", expand=True)
        pbtns = ttk.Frame(paths_box)
        pbtns.pack(side="left", padx=(6, 0), fill="y")
        for text, cmd in (("Suggest", self._suggest),
                          ("Add...", self._add_path),
                          ("Remove", self._remove_path)):
            ttk.Button(pbtns, text=text, width=9,
                       command=cmd).pack(fill="x", pady=1)
        for p in (game.paths if game else []):
            self.paths.insert("end", p)
        r = _add_row(pf, r, "Save locations", paths_box)
        self.processes = ttk.Entry(pf, width=44)
        self.processes.insert(0, ", ".join(game.process_names) if game else "")
        r = _add_row(
            pf, r, "Game executables", self.processes,
            ttk.Label(pf, text="comma separated;\nenables post-play backup",
                      style="Faint.TLabel", font=T.FONT_SMALL))
        self.excludes = ttk.Entry(pf, width=44)
        self.excludes.insert(0, ", ".join(game.exclude_patterns) if game else "")
        r = _add_row(pf, r, "Exclude patterns", self.excludes)
        interval_row = ttk.Frame(pf)
        self.interval = tk.StringVar(
            value=str(game.interval_minutes if game else 60))
        ttk.Spinbox(interval_row, textvariable=self.interval, from_=0, to=10080,
                    width=7).pack(side="left")
        ttk.Label(interval_row, text="min (0 = watch only)",
                  style="Faint.TLabel").pack(side="left", padx=6)
        r = _add_row(pf, r, "Backup interval", interval_row)
        cap_row = ttk.Frame(pf)
        self.max_versions = tk.StringVar(
            value=str(game.max_versions if game else 0))
        ttk.Spinbox(cap_row, textvariable=self.max_versions, from_=0, to=200,
                    width=7).pack(side="left")
        ttk.Label(cap_row, text="0 = keep all",
                  style="Faint.TLabel").pack(side="left", padx=6)
        r = _add_row(pf, r, "Version cap", cap_row)
        self.skip_run = tk.BooleanVar(
            value=bool(game.skip_while_running) if game else False)
        ttk.Checkbutton(pf, text="Skip backups while the game is running",
                        variable=self.skip_run).grid(
            row=r, column=1, sticky="w", pady=2)
        r += 1
        self.enabled = tk.BooleanVar(value=bool(game.enabled) if game else True)
        ttk.Checkbutton(pf, text="Protection enabled",
                        variable=self.enabled).grid(row=r, column=1,
                                                    sticky="w", pady=2)
        pf.columnconfigure(1, weight=1)

        # -- buttons ------------------------------------------------------------
        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="CANCEL", command=self.win.destroy).pack(
            side="left", padx=4)
        ttk.Button(btns, text="SAVE", style="Accent.TButton",
                   command=self._save).pack(side="left")
        frame.columnconfigure(0, weight=1)
        self.name.focus_set()
        self.win.bind("<Return>", lambda _e: self._save())
        self.win.bind("<Escape>", lambda _e: self.win.destroy())

    # -- helpers ---------------------------------------------------------------
    def _browse_install(self):
        path = filedialog.askdirectory(parent=self.win)
        if path:
            self.install.delete(0, "end")
            self.install.insert(0, path)

    def _suggest(self):
        name = self.name.get().strip()
        if not name:
            return
        SuggestDialog(self.win, suggest_locations(name), self.paths)

    def _add_path(self):
        path = filedialog.askdirectory(parent=self.win) or \
            filedialog.askopenfilename(parent=self.win)
        if path:
            self.paths.insert("end", path)

    def _remove_path(self):
        for i in reversed(self.paths.curselection()):
            self.paths.delete(i)

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showwarning("SaveDeck", "Name is required.",
                                   parent=self.win)
            return
        entry = self.entry
        entry["name"] = name
        entry["thumbnail"] = self.thumb.get().strip() or None
        entry["launchTarget"] = self.target.get().strip() or None
        entry["installPath"] = self.install.get().strip() or None

        paths = list(self.paths.get(0, "end"))
        game = self.app.config.get_game(entry.get("sp_id") or "")
        if paths or game:
            if game is None:
                game = Game(id=uuid.uuid4().hex[:12], name=name)
                entry["sp_id"] = game.id
            game.name = name
            game.paths = paths
            game.provider = self.provider.get()
            game.repo = self.repo.get().strip()
            if not game.remote_folder:
                game.remote_folder = safe_name(name)
            game.process_names = [p.strip() for p in
                                  self.processes.get().split(",") if p.strip()]
            game.exclude_patterns = [p.strip() for p in
                                     self.excludes.get().split(",") if p.strip()]
            try:
                game.interval_minutes = int(self.interval.get() or 0)
                game.max_versions = int(self.max_versions.get() or 0)
            except ValueError:
                pass
            game.skip_while_running = bool(self.skip_run.get())
            game.enabled = bool(self.enabled.get()) and bool(paths)
            if game not in self.app.config.games:
                self.app.config.add_game(game)
            else:
                self.app.config.save()
            self.app.engine.refresh_watchers()
        lib.save_library(self.app.lib)
        self.saved = True
        self.win.destroy()


class SuggestDialog:
    """Pick likely save locations found by SavePoint's detector."""

    def __init__(self, parent, candidates: list, paths_listbox):
        self.paths_listbox = paths_listbox
        self.win = T.toplevel(parent, "Suggested save locations",
                              resizable=(False, False))
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Likely save locations for this game:",
                  style="Muted.TLabel").pack(anchor="w")
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True, pady=6)
        self.vars = []
        if not candidates:
            ttk.Label(box, text="No likely locations found - add one manually.",
                      style="Faint.TLabel").pack(anchor="w")
        for c in candidates[:12]:
            var = tk.BooleanVar(value=False)
            self.vars.append((var, c))
            ttk.Checkbutton(box, text=c, variable=var).pack(anchor="w", pady=1)
        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        ttk.Button(btns, text="CANCEL",
                   command=self.win.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="ADD SELECTED", style="Accent.TButton",
                   command=self._apply).pack(side="right")

    def _apply(self):
        for var, path in self.vars:
            if var.get():
                self.paths_listbox.insert("end", path)
        self.win.destroy()


class PasswordDialog:
    """Unlock prompt for the private shelf."""

    def __init__(self, parent, on_ok):
        self.on_ok = on_ok
        self.win = T.toplevel(parent, "Private shelf", resizable=(False, False))
        frame = ttk.Frame(self.win, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Password:", style="Muted.TLabel").grid(
            row=0, column=0, padx=(0, 8))
        self.pw = ttk.Entry(frame, show="•", width=24)
        self.pw.grid(row=0, column=1)
        self.pw.focus_set()
        self.pw.bind("<Return>", lambda _e: self._check())
        ttk.Button(frame, text="UNLOCK", style="Accent.TButton",
                   command=self._check).grid(row=1, column=1, sticky="e",
                                             pady=(10, 0))

    def _check(self):
        if lib.verify_hidden_password(self.pw.get()):
            self.win.destroy()
            self.on_ok()
        else:
            messagebox.showerror("SaveDeck", "Wrong password.",
                                 parent=self.win)


class PasswordSetDialog:
    """Set, change or remove the hidden-games password."""

    def __init__(self, parent):
        self.win = T.toplevel(parent, "Hidden games - password",
                              resizable=(False, False))
        frame = ttk.Frame(self.win, padding=16)
        frame.pack(fill="both", expand=True)
        has = lib.hidden_password_set()
        ttk.Label(frame,
                  text="A password is currently set for hidden games."
                  if has else "No password is set - hidden games are open "
                              "to anyone using this PC.",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=2,
                                             sticky="w")
        ttk.Label(frame, text="New password:", style="Muted.TLabel").grid(
            row=1, column=0, padx=(0, 8), pady=(12, 0), sticky="w")
        self.pw = ttk.Entry(frame, show="•", width=24)
        self.pw.grid(row=1, column=1, pady=(12, 0))
        ttk.Label(frame, text="Confirm:", style="Muted.TLabel").grid(
            row=2, column=0, padx=(0, 8), pady=(6, 0), sticky="w")
        self.pw2 = ttk.Entry(frame, show="•", width=24)
        self.pw2.grid(row=2, column=1, pady=(6, 0))
        ttk.Label(frame, text="Leave empty to remove the password.",
                  style="Faint.TLabel", font=T.FONT_SMALL).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        btns = ttk.Frame(frame)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="CANCEL",
                   command=self.win.destroy).pack(side="left", padx=4)
        if has:
            ttk.Button(btns, text="REMOVE",
                       command=self._remove).pack(side="left", padx=4)
        ttk.Button(btns, text="SET PASSWORD", style="Accent.TButton",
                   command=self._set).pack(side="left")
        self.pw.focus_set()
        self.win.bind("<Escape>", lambda _e: self.win.destroy())

    def _set(self):
        a, b = self.pw.get(), self.pw2.get()
        if a != b:
            messagebox.showerror("SaveDeck", "Passwords do not match.",
                                 parent=self.win)
            return
        lib.set_hidden_password(a)
        messagebox.showinfo("SaveDeck",
                            "Password removed - hidden games are open."
                            if not a else "Password set.", parent=self.win)
        self.win.destroy()

    def _remove(self):
        lib.set_hidden_password("")
        messagebox.showinfo("SaveDeck",
                            "Password removed - hidden games are open.",
                            parent=self.win)
        self.win.destroy()


class SettingsDialog:
    """Credentials, default destination, notifications, import/export."""

    def __init__(self, parent, app):
        self.app = app
        self.win = T.toplevel(parent, "SaveDeck - settings")
        frame = ttk.Frame(self.win, padding=14)
        frame.pack(fill="both", expand=True)
        settings = app.config.settings

        gf = ttk.Labelframe(frame, text="GITHUB BACKUP", padding=10)
        gf.pack(fill="x")
        ttk.Label(gf, text="Token", style="Muted.TLabel").grid(
            row=0, column=0, padx=(0, 8), pady=3, sticky="w")
        self.token = ttk.Entry(gf, width=42, show="•")
        self.token.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(gf, text="TEST", command=self._test).grid(
            row=0, column=2, padx=6)
        ttk.Button(gf, text="SAVE TOKEN", command=self._save_token).grid(
            row=0, column=3)
        ttk.Label(gf, text="Default repo", style="Muted.TLabel").grid(
            row=1, column=0, padx=(0, 8), pady=3, sticky="w")
        self.repo = ttk.Entry(gf, width=42)
        self.repo.insert(0, settings.get("default_repo", ""))
        self.repo.grid(row=1, column=1, sticky="we", pady=3)
        ttk.Label(gf, text="user/repo", style="Faint.TLabel",
                  font=T.FONT_SMALL).grid(row=1, column=2, columnspan=2,
                                          sticky="w")
        ttk.Label(gf, text="Fine-grained PAT, Contents: read+write. The token "
                           "lives in the Windows Credential Manager and is "
                           "shared with SavePoint.", style="Faint.TLabel",
                  font=T.FONT_SMALL).grid(row=2, column=0, columnspan=4,
                                          sticky="w", pady=(4, 0))
        gf.columnconfigure(1, weight=1)
        self.test_result = ttk.Label(frame, text="", style="Faint.TLabel")
        self.test_result.pack(anchor="w", pady=(4, 8))

        bf = ttk.Labelframe(frame, text="BACKUP ENGINE", padding=10)
        bf.pack(fill="x")
        self.paused = tk.BooleanVar(value=app.engine.is_paused())
        ttk.Checkbutton(bf, text="Pause all backups", variable=self.paused,
                        command=self._toggle_pause).pack(anchor="w")
        self.notify_var = tk.BooleanVar(
            value=settings.get("notify_on_failures", True))
        ttk.Checkbutton(bf, text="Toast notification when a backup fails",
                        variable=self.notify_var,
                        command=self._toggle_notify).pack(anchor="w")

        mf = ttk.Labelframe(frame, text="MAINTENANCE", padding=10)
        mf.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(mf)
        row.pack(fill="x")
        ttk.Button(row, text="Storage report...",
                   command=self._storage).pack(side="left", padx=2)
        ttk.Button(row, text="Export config...",
                   command=self._export).pack(side="left", padx=2)
        ttk.Button(row, text="Import config...",
                   command=self._import).pack(side="left", padx=2)
        ttk.Button(row, text="Open log",
                   command=self._open_log).pack(side="left", padx=2)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="CLOSE", command=self.win.destroy).pack(
            side="right")
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        self._apply_settings()

    def _apply_settings(self):
        self.app.config.settings["default_repo"] = self.repo.get().strip()
        self.app.config.save()

    def _save_token(self):
        from savepoint.credentials import set_secret
        set_secret("token:github", self.token.get().strip())
        self.test_result.configure(text="token saved "
                                        "(Windows Credential Manager)",
                                   foreground=T.GREEN)

    def _test(self):
        from savepoint.providers import get_provider
        self.test_result.configure(text="testing...", foreground=T.MUTED)

        def worker():
            try:
                prov = get_provider("github")
                if self.token.get().strip():
                    prov.configure(token=self.token.get().strip())
                msg = prov.test_connection()
                self.win.after(0, lambda: self.test_result.configure(
                    text=msg, foreground=T.GREEN))
            except Exception as e:
                self.win.after(0, lambda: self.test_result.configure(
                    text=str(e), foreground=T.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_pause(self):
        if self.paused.get():
            self.app.engine.pause()
        else:
            self.app.engine.resume()
        self.app._refresh_status()

    def _toggle_notify(self):
        self.app.config.settings["notify_on_failures"] = self.notify_var.get()
        self.app.config.save()

    def _export(self):
        from savepoint.config import export_config
        path = filedialog.asksaveasfilename(
            parent=self.win, defaultextension=".json",
            filetypes=[("SaveDeck config", "*.json")],
            initialfile="savedeck-config.json")
        if not path:
            return
        self._apply_settings()
        n = export_config(self.app.config, path)
        messagebox.showinfo("SaveDeck", f"Exported {n} game(s).",
                            parent=self.win)

    def _import(self):
        from savepoint.config import parse_config_export
        path = filedialog.askopenfilename(
            parent=self.win,
            filetypes=[("SaveDeck/SavePoint config", "*.json")])
        if not path:
            return
        try:
            _subset, games = parse_config_export(path)
        except ValueError as e:
            messagebox.showerror("SaveDeck", str(e), parent=self.win)
            return
        by_name = {g.name.lower(): i for i, g in
                   enumerate(self.app.config.games)}
        imported = 0
        for g in games:
            idx = by_name.get(g.name.lower())
            if idx is not None:
                g.id = self.app.config.games[idx].id  # one engine entry per game
                self.app.config.games[idx] = g
            else:
                self.app.config.games.append(g)
            imported += 1
        self.app.config.save()
        self.app.engine.refresh_watchers()
        messagebox.showinfo("SaveDeck", f"Imported {imported} game(s).",
                            parent=self.win)

    def _open_log(self):
        from savedeck import home_dir
        log = os.path.join(home_dir(), "savepoint.log")
        if os.path.isfile(log):
            os.startfile(log)

    def _storage(self):
        StorageDialog(self.win, self.app)


class StorageDialog:
    """Per-game cloud usage report (versions / files / size)."""

    def __init__(self, parent, app):
        self.app = app
        self.win = T.toplevel(parent, "Storage report")
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)
        cols = ("game", "versions", "files", "size")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        for cid, text, w in (("game", "GAME", 200), ("versions", "VERSIONS", 90),
                             ("files", "FILES", 80), ("size", "SIZE", 90)):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=w, anchor="w" if cid == "game" else "e")
        self.tree.pack(fill="both", expand=True)
        self.status = ttk.Label(frame, text="measuring...", style="Faint.TLabel")
        self.status.pack(anchor="w", pady=(6, 0))
        self.total = [0, 0, 0]
        games = [g for g in app.config.games if g.enabled and g.paths]
        if not games:
            self.status.configure(text="no protected games yet")
        for g in games:
            self.tree.insert("", "end", iid=g.id,
                             values=(g.name, "…", "…", "…"))
            threading.Thread(target=self._measure, args=(g,),
                             daemon=True).start()

    def _fmt(self, n) -> str:
        if n is None:
            return "?"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return "?"

    def _measure(self, game):
        try:
            info = self.app.engine.storage_info(game)
        except Exception:
            info = {"versions": "?", "files": None, "size": None}
        try:
            size = self.app.engine.destination_size(game)
        except Exception:
            size = None
        total = size if size is not None else info.get("size")
        self.win.after(0, lambda: self._update(game, info, total))

    def _update(self, game, info, total):
        try:
            self.tree.item(game.id, values=(
                game.name, info.get("versions", "?"),
                info.get("files") if info.get("files") is not None else "?",
                self._fmt(total)))
        except tk.TclError:
            return
        if isinstance(total, (int, float)):
            self.total[2] += total
        self.status.configure(
            text=f"total destination footprint: {self._fmt(self.total[2])}")


class VersionsDialog:
    """Browse backup versions and restore (all or selected files)."""

    def __init__(self, parent, engine, game, on_done=None):
        self.engine = engine
        self.game = game
        self.on_done = on_done
        self.versions = []
        self.win = T.toplevel(parent, f"SaveDeck - versions: {game.name}")
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Version:", style="Muted.TLabel").pack(side="left")
        self.choice = ttk.Combobox(top, state="readonly", width=44)
        self.choice.pack(side="left", padx=8)
        ttk.Button(top, text="PREVIEW", command=self._preview).pack(side="left")
        ttk.Button(top, text="REFRESH", command=self._load).pack(
            side="left", padx=6)

        cols = ("file", "status", "local", "remote")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        for cid, text, w in (("file", "FILE", 260), ("status", "STATUS", 120),
                             ("local", "LOCAL", 90), ("remote", "REMOTE", 90)):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=w, anchor="w" if cid == "file" else "e")
        self.tree.pack(fill="both", expand=True, pady=(10, 0))

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="RESTORE SELECTED FILES",
                   command=lambda: self._restore(True)).pack(side="left")
        ttk.Button(btns, text="RESTORE ALL", style="Accent.TButton",
                   command=lambda: self._restore(False)).pack(side="left",
                                                              padx=6)
        self.status = ttk.Label(frame, text="", style="Faint.TLabel")
        self.status.pack(anchor="w", pady=(6, 0))
        self._load()

    def _load(self):
        self.status.configure(text="loading versions...")
        def worker():
            try:
                versions = self.engine.list_versions(self.game)
            except Exception as e:
                self.win.after(0, lambda: self.status.configure(
                    text=str(e), foreground=T.RED))
                return
            self.win.after(0, lambda: self._fill(versions))
        threading.Thread(target=worker, daemon=True).start()

    def _fill(self, versions):
        self.versions = versions
        self.choice["values"] = [
            f"{v.label}  ({v.date})" for v in versions]
        if versions:
            self.choice.current(0)
            self.status.configure(
                text=f"{len(versions)} version(s) - newest first")
        else:
            self.status.configure(text="no backup versions found yet")

    def _preview(self):
        idx = self.choice.current()
        if idx < 0:
            return
        ref = self.versions[idx].ref
        self.status.configure(text="comparing...")
        def worker():
            try:
                result = self.engine.preview_version(self.game, ref)
            except Exception as e:
                self.win.after(0, lambda: self.status.configure(
                    text=str(e), foreground=T.RED))
                return
            self.win.after(0, lambda: self._fill_rows(result))
        threading.Thread(target=worker, daemon=True).start()

    def _fill_rows(self, result):
        self.tree.delete(*self.tree.get_children())
        for row in result["rows"]:
            self.tree.insert("", "end", iid=row["rel"], values=(
                row["rel"], row["status"],
                row["local_size"] if row["local_size"] is not None else "-",
                row["remote_size"] if row["remote_size"] is not None else "-"))
        counts = result["counts"]
        self.status.configure(text="  ·  ".join(
            f"{k}: {v}" for k, v in sorted(counts.items())))

    def _restore(self, selected: bool):
        idx = self.choice.current()
        if idx < 0:
            messagebox.showinfo("SaveDeck", "Select a version first.",
                                parent=self.win)
            return
        ref = self.versions[idx].ref
        only = None
        if selected:
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo("SaveDeck", "Select files in the list "
                                                "(or use RESTORE ALL).",
                                    parent=self.win)
                return
            only = list(sel)
        if not messagebox.askyesno(
                "SaveDeck",
                "Current saves are backed up to the cloud first, so a "
                "restore can itself be undone.\n\nRestore "
                f"{'the selected files' if only else 'this version'} of "
                f"\"{self.game.name}\"?", parent=self.win):
            return
        self.status.configure(text="restoring...")
        def worker():
            try:
                self.engine.restore_version(
                    self.game, ref, only=only,
                    progress=lambda i, n, rel: self.win.after(
                        0, lambda i=i, n=n, rel=rel: self.status.configure(
                            text=f"restoring {i}/{n}: {rel}")))
                self.win.after(0, lambda: self.status.configure(
                    text="restore complete", foreground=T.GREEN))
                if self.on_done:
                    self.win.after(0, self.on_done)
            except Exception as e:
                self.win.after(0, lambda: self.status.configure(
                    text=f"restore failed: {e}", foreground=T.RED))
        threading.Thread(target=worker, daemon=True).start()





