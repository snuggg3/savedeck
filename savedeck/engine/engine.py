"""Background backup engine.

Responsibilities:
- watch save folders for changes (watchdog) with a debounce window
- periodically re-check games as a safety net
- scan save locations, hash files (sha256) and upload only what changed
- track per-game manifests so unchanged files are never re-uploaded
- restore previous versions (always safety-backing-up current files first)
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .config import Config, state_dir
from .credentials import get_secret
from .logging_util import write_log
from .models import Game, safe_name
from .processes import is_running
from .providers import get_provider

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except Exception:
    WATCHDOG_AVAILABLE = False

POLL_SECONDS = 15   # scheduler wake-up interval
QUIET_SECONDS = 45  # wait this long for "quiet" after a change before backing up


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _excluded(name: str, patterns) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, p.lower()) for p in patterns)


def _sanitize(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", label) or "root"


def scan_game(game: Game):
    """Scan all configured save locations.

    Returns (files, roots):
      files: {key: {"abs","sha","size"}} - key is the path relative to its
             save location; when a game has multiple locations every key is
             prefixed with a unique location label so keys stay unambiguous.
      roots: {label: absolute location path} - used to map keys back on restore.
    """
    patterns = [p.strip() for p in (game.exclude_patterns or []) if p.strip()]
    roots, used = [], set()
    for raw in game.paths:
        root = os.path.abspath(os.path.expanduser(raw))
        if not (os.path.isfile(root) or os.path.isdir(root)):
            continue
        label = _sanitize(os.path.basename(root.rstrip("\\/")) or f"root{len(roots) + 1}")
        base, i = label, 2
        while label in used:
            label = f"{base}_{i}"
            i += 1
        used.add(label)
        roots.append((label, root))

    prefixed = len(roots) > 1
    jobs = []   # (key, absolute path)
    for label, root in roots:
        if os.path.isfile(root):
            entries = [(root, os.path.basename(root))]
        else:
            entries = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not _excluded(d, patterns)]
                for fn in sorted(filenames):
                    if _excluded(fn, patterns):
                        continue
                    p = os.path.join(dirpath, fn)
                    entries.append((p, os.path.relpath(p, root)))
        for abs_p, rel in entries:
            key = rel.replace(os.sep, "/")
            if prefixed:
                key = f"{label}/{key}"
            jobs.append((key, abs_p))

    # Hash in parallel: large save folders (dozens of files) scan much faster.
    files = {}
    if jobs:
        workers = min(8, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            shas = list(pool.map(lambda j: _try_sha(j[1]), jobs))
        for (key, abs_p), sha in zip(jobs, shas):
            if sha is None:
                continue  # file vanished mid-scan
            try:
                size = os.path.getsize(abs_p)
            except OSError:
                continue
            files[key] = {"abs": abs_p, "sha": sha, "size": size}
    return files, {label: root for label, root in roots}


def _try_sha(path: str):
    try:
        return sha256_file(path)
    except OSError:
        return None


def _mtime_str(path: str) -> str:
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
    except OSError:
        return ""


def _matches_selection(rel: str, wanted: list) -> bool:
    """True if `rel` is one of `wanted` or sits below one of its folders."""
    return any(rel == w or rel.startswith(w.rstrip("/") + "/") for w in wanted)


# ----------------------------------------------------------------------
# Watchdog handler
# ----------------------------------------------------------------------
if WATCHDOG_AVAILABLE:
    class _ChangeHandler(FileSystemEventHandler):
        def __init__(self, engine, game_id):
            self._engine, self._game_id = engine, game_id

        def on_any_event(self, event):
            if getattr(event, "is_directory", False):
                return
            self._engine._mark_dirty(self._game_id)
else:
    class _ChangeHandler:  # placeholder when watchdog is missing
        def __init__(self, *a, **k):
            pass


class BackupEngine:
    def __init__(self, config: Config, log_cb=None):
        self.config = config
        self.log_cb = log_cb or (lambda level, msg: None)
        self._stop = threading.Event()
        self._paused = threading.Event()
        if config.settings.get("paused"):
            self._paused.set()  # paused state persists across restarts
        self._force = set()          # game ids explicitly requested by the user
        self._dirty = {}             # game id -> last change timestamp
        self._last_attempt = {}      # game id -> monotonic ts of last backup attempt
        self._busy = set()           # game ids currently being backed up
        self._lock = threading.RLock()
        self._observer = None

    # -- lifecycle -------------------------------------------------------
    def start(self):
        self.refresh_watchers()
        self.catch_up_missed()
        threading.Thread(target=self._loop, name="savedeck-scheduler", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._stop_observer()

    def log(self, level: str, msg: str):
        write_log(level, msg)
        self.log_cb(level, msg)

    # -- pause -------------------------------------------------------------
    def pause(self):
        self._paused.set()
        self.config.settings["paused"] = True
        self.config.save()
        self.log("info", "Backups paused - changes will be backed up when resumed")

    def resume(self):
        self._paused.clear()
        self.config.settings["paused"] = False
        self.config.save()
        self.log("info", "Backups resumed")

    def is_paused(self) -> bool:
        return self._paused.is_set()

    # -- catch-up ----------------------------------------------------------
    def catch_up_missed(self):
        """Back up games that missed their window while the PC was off/asleep.

        Called once at startup: any enabled game whose last backup is older
        than its interval (at least one hour) gets an immediate, staggered
        backup so nothing is lost just because the machine was off.
        """
        if self.is_paused() or not self.config.settings.get("catch_up_on_start", True):
            return
        now = time.time()
        pending = 0
        for game in self.config.games:
            if not (game.enabled and game.paths):
                continue
            if not self._is_stale(game, now):
                continue
            self.log("info", f"{game.name}: last backup {game.last_backup or 'never'} "
                             f"- catching up now")
            timer = threading.Timer(2 + pending * 3, self.backup_now, args=(game.id,))
            timer.daemon = True
            timer.start()
            pending += 1

    @staticmethod
    def _is_stale(game: Game, now: float = None) -> bool:
        window = max(game.interval_minutes, 60) * 60  # seconds
        if not game.last_backup:
            return True
        try:
            ts = dt.datetime.fromisoformat(game.last_backup).timestamp()
        except (ValueError, TypeError):
            return True
        return (now or time.time()) - ts >= window

    # -- watchers --------------------------------------------------------
    def refresh_watchers(self):
        self._stop_observer()
        if not WATCHDOG_AVAILABLE:
            self.log("warn", "watchdog not installed - change detection is off "
                             "(periodic backups still work)")
            return
        observer = Observer()
        scheduled = 0
        for game in self.config.games:
            if not (game.enabled and game.watch_changes):
                continue
            for p in game.paths:
                p = os.path.abspath(os.path.expanduser(p))
                watch_dir = p if os.path.isdir(p) else (os.path.dirname(p) or ".")
                if os.path.isdir(watch_dir):
                    try:
                        observer.schedule(_ChangeHandler(self, game.id), watch_dir,
                                          recursive=True)
                        scheduled += 1
                    except Exception as e:
                        self.log("warn", f"Cannot watch {p}: {e}")
        if scheduled:
            observer.daemon = True
            observer.start()
            self._observer = observer

    def _stop_observer(self):
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None

    def _mark_dirty(self, game_id: str):
        self._dirty[game_id] = time.time()

    # -- scheduling ------------------------------------------------------
    def _loop(self):
        while not self._stop.wait(POLL_SECONDS):
            for game in list(self.config.games):
                if self._stop.is_set():
                    break
                try:
                    self._maybe_backup(game)
                except Exception as e:
                    self._finish(game, "error", str(e))

    def _maybe_backup(self, game: Game):
        if not game.enabled or not game.paths or game.id in self._busy:
            return
        due = game.id in self._force
        if not due and game.watch_changes:
            changed_at = self._dirty.get(game.id)
            if changed_at and time.time() - changed_at >= QUIET_SECONDS \
                    and time.time() - self._last_attempt.get(game.id, 0) >= QUIET_SECONDS:
                due = True
        if not due and game.interval_minutes > 0:
            if game.last_backup:
                try:
                    last = dt.datetime.fromisoformat(game.last_backup)
                    if (dt.datetime.now() - last).total_seconds() >= game.interval_minutes * 60:
                        due = True
                except ValueError:
                    due = True
            else:
                due = True
        if not due and not game.last_backup \
                and (game.watch_changes or game.interval_minutes > 0):
            due = True  # never backed up -> do an initial backup once
        if not due:
            return
        self._force.discard(game.id)
        self._dirty.pop(game.id, None)
        self._last_attempt[game.id] = time.time()
        self.run_backup(game)

    def backup_now(self, game_id: str) -> bool:
        """User-triggered immediate backup (runs in its own thread)."""
        game = self.config.get_game(game_id)
        if not game or game.id in self._busy:
            return False

        def _run():
            try:
                self.run_backup(game)
            except Exception as e:
                self._finish(game, "error", str(e))
        threading.Thread(target=_run, daemon=True).start()
        return True

    # -- backup ----------------------------------------------------------
    def _provider_for(self, game: Game):
        provider = get_provider(game.provider)
        kw = {}
        if game.provider == "github":
            token = get_secret("token:github")
            if not token:
                raise RuntimeError("GitHub is not connected yet - open 'Settings...'")
            kw["token"] = token
        provider.configure(**kw)
        return provider

    def _folder(self, game: Game) -> str:
        return (game.remote_folder or safe_name(game.name)).strip("/").replace("\\", "/")

    def run_backup(self, game: Game):
        if self.is_paused():
            self.log("info", f"Backups are paused - skipping {game.name}")
            return
        if game.skip_while_running and game.process_names and is_running(game.process_names):
            self.log("info", f"{game.name}: game is running - waiting to back up "
                             f"(avoids snapshotting a half-written save)")
            return
        with self._lock:
            if game.id in self._busy:
                return
            self._busy.add(game.id)
        try:
            self._run_backup(game)
        finally:
            with self._lock:
                self._busy.discard(game.id)

    def _run_backup(self, game: Game):
        self.log("info", f"Checking {game.name}...")
        provider = self._provider_for(game)
        files, roots = scan_game(game)
        if not files:
            self._finish(game, "error", "No save files found at the configured paths")
            return
        manifest = self._load_manifest(game)
        known = dict(manifest.get("files", {}))
        changed = [k for k, v in files.items() if known.get(k) != v["sha"]]
        if not changed:
            self._finish(game, "ok", "Up to date (no changes)")
            return
        folder = self._folder(game)
        total = len(changed)
        self.log("info", f"Uploading {total} changed file(s)...")
        provider.upload_files(
            game.repo,
            [(f"{folder}/{key}", files[key]["abs"]) for key in changed],
            message=f"[{game.name}] backup {now_iso()} - {total} file(s)")
        for key in changed:
            known[key] = files[key]["sha"]
        self.log("info", f"  uploaded {total} file(s) as one version")
        # Locally deleted files: drop from the manifest but keep the remote
        # copies so accidental deletions can always be recovered.
        for k in [k for k in known if k not in files]:
            known.pop(k)
        manifest.update({"prefixed": len(roots) > 1, "roots": roots, "files": known})
        self._save_manifest(game, manifest)
        if game.max_versions:
            try:
                provider.prune_versions(game.repo, folder, game.max_versions)
            except Exception as e:
                self.log("warn", f"Could not prune old versions: {e}")
        self._finish(game, "ok", f"Backed up {total} file(s)")

    # -- versions / restore ----------------------------------------------
    def list_versions(self, game: Game, limit: int = 60) -> list:
        provider = self._provider_for(game)
        return provider.list_versions(game.repo, self._folder(game), limit=limit)

    def storage_info(self, game: Game, limit: int = 100) -> dict:
        """Cloud usage for the storage report (may hit the network).

        Returns {"versions", "files", "size"} - file count and total size of
        the latest version; None when it could not be determined.
        """
        provider = self._provider_for(game)
        folder = self._folder(game)
        versions = provider.list_versions(game.repo, folder, limit=limit)
        info = {"versions": len(versions), "files": None, "size": None}
        if versions:
            tree = provider.list_tree(game.repo, versions[0].ref, prefix=folder)
            info["files"] = len(tree)
            info["size"] = sum(s for _p, s in tree)
        return info

    def destination_size(self, game: Game):
        """Approximate total destination size in bytes (None: unknown)."""
        try:
            return self._provider_for(game).repo_size(game.repo)
        except Exception:
            return None

    def preview_version(self, game: Game, ref: str) -> dict:
        """Compare the current local saves against version `ref` (size diff).

        Returns {"rows": [...], "counts": {...}} where each row is
        {"rel", "status", "local_size", "remote_size", "local_mtime"}.
        Status is one of: "unchanged" (same size), "changed", "missing locally"
        (in the backup but deleted locally) and "not in this version"
        (created locally after this backup; cannot be restored from it).
        Comparison is size-based - instant and download-free.
        """
        provider = self._provider_for(game)
        folder = self._folder(game)
        files, _roots = scan_game(game)
        tree = provider.list_tree(game.repo, ref, prefix=folder)
        rows = []
        for path, size in sorted(tree):
            rel = path[len(folder) + 1:]
            local = files.get(rel)
            if local is None:
                status, local_size, mtime = "missing locally", None, ""
            elif local["size"] == size:
                status, local_size, mtime = "unchanged", local["size"], _mtime_str(local["abs"])
            else:
                status, local_size, mtime = "changed", local["size"], _mtime_str(local["abs"])
            rows.append({"rel": rel, "status": status, "local_size": local_size,
                         "remote_size": size, "local_mtime": mtime})
        remote_rels = {p[len(folder) + 1:] for p, _s in tree}
        for rel in sorted(set(files) - remote_rels):
            rows.append({"rel": rel, "status": "not in this version",
                         "local_size": files[rel]["size"], "remote_size": None,
                         "local_mtime": _mtime_str(files[rel]["abs"])})
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {"rows": rows, "counts": counts}

    def restore_version(self, game: Game, ref: str, dest: str = None, progress=None,
                        only=None):
        """Restore version `ref` of a game's saves.

        Current saves are safety-backed-up to the cloud first, so a restore
        can itself be undone. Files not present in the backup are left
        untouched (merge, never delete).
        `only` restricts the restore to specific files (relative keys, e.g.
        "slot1.sav" or "Saves/slot1.sav"); entries ending in "/" (or a bare
        folder name) also match everything below them.
        """
        provider = self._provider_for(game)
        folder = self._folder(game)

        self.log("info", f"Safety-backing up current saves of {game.name} before restore...")
        try:
            files, _roots = scan_game(game)
            provider.upload_files(
                game.repo,
                [(f"{folder}/{key}", info["abs"]) for key, info in files.items()],
                message=f"[{game.name}] pre-restore safety backup {now_iso()} "
                        f"- {len(files)} file(s)")
        except Exception as e:
            raise RuntimeError(f"Restore aborted: safety backup failed ({e})")

        tree = provider.list_tree(game.repo, ref, prefix=folder)
        if only is not None:
            wanted = [o.strip().strip("/").replace("\\", "/") for o in only if o and o.strip()]
            tree = [(p, s) for p, s in tree
                    if _matches_selection(p[len(folder) + 1:], wanted)]
            if not tree:
                raise RuntimeError("None of the selected files are in the selected "
                                   "backup version")
        if not tree:
            raise RuntimeError("No files found in the selected backup version")

        manifest = self._load_manifest(game)
        total = len(tree)
        for i, (path, _size) in enumerate(tree, 1):
            rel = path[len(folder) + 1:]
            target = self._restore_target(game, manifest, rel, dest)
            if not target:
                self.log("warn", f"Skipping {rel}: unknown save location")
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            provider.download_file(game.repo, path, ref, target)
            if progress:
                progress(i, total, rel)
        self.log("info", f"Restored {total} file(s) for {game.name}")
        self._finish(game, "ok", f"Restored {total} file(s) from backup")

    def _restore_target(self, game: Game, manifest: dict, rel: str, dest: str):
        """Map a remote relative key back to a local path (or export target)."""
        parts = rel.split("/")
        if dest:
            return os.path.join(dest, *parts)
        roots_map = manifest.get("roots") or {}
        if not roots_map and game.paths:
            first = os.path.abspath(os.path.expanduser(game.paths[0]))
            label = _sanitize(os.path.basename(first.rstrip("\\/")) or "root")
            roots_map = {label: first}
        if manifest.get("prefixed"):
            root = roots_map.get(parts[0])
            if not root:
                return None
            return os.path.join(os.path.abspath(os.path.expanduser(root)), *parts[1:])
        root = next(iter(roots_map.values()))
        return os.path.join(os.path.abspath(os.path.expanduser(root)), *parts)

    # -- state helpers -----------------------------------------------------
    def _finish(self, game: Game, status: str, msg: str):
        game.last_status = status
        game.last_error = "" if status == "ok" else msg
        if status == "ok":
            game.last_backup = now_iso()
        self.config.save()
        self.log("info" if status == "ok" else "error", f"{game.name}: {msg}")
        self.log("refresh", game.id)

    def _manifest_path(self, game: Game) -> str:
        return os.path.join(state_dir(), f"{game.id}.json")

    def _load_manifest(self, game: Game) -> dict:
        try:
            with open(self._manifest_path(game), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_manifest(self, game: Game, manifest: dict):
        tmp = self._manifest_path(game) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        os.replace(tmp, self._manifest_path(game))
