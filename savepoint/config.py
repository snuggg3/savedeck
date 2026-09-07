"""Application configuration storage (atomic JSON file in %APPDATA%)."""
from __future__ import annotations

import json
import os
import shutil
import threading

from .models import Game

APP_NAME = "SavePoint"
LEGACY_APP_NAME = "CloudSaveGuard"  # app name before the 1.0 rename


def app_dir() -> str:
    """Directory holding config/state. Override with SAVEPOINT_HOME (useful for tests)."""
    base = os.environ.get("SAVEPOINT_HOME") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def ensure_migrated():
    """One-time migration of user data from the old 'CloudSaveGuard' folder."""
    old = os.environ.get("CLOUDSAVEGUARD_HOME") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), LEGACY_APP_NAME)
    new = app_dir()
    if os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(new)):
        return
    if not os.path.isdir(old):
        return
    # config file
    old_cfg, new_cfg = os.path.join(old, "config.json"), os.path.join(new, "config.json")
    if os.path.isfile(old_cfg) and not os.path.isfile(new_cfg):
        shutil.copy2(old_cfg, new_cfg)
    # per-game manifests
    old_state, new_state = os.path.join(old, "state"), os.path.join(new, "state")
    if os.path.isdir(old_state):
        os.makedirs(new_state, exist_ok=True)
        for fn in os.listdir(old_state):
            src, dst = os.path.join(old_state, fn), os.path.join(new_state, fn)
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.copy2(src, dst)
    # DPAPI fallback secrets (only used when the keyring package is unavailable)
    old_sec, new_sec = os.path.join(old, "secrets.bin"), os.path.join(new, "secrets.bin")
    if os.path.isfile(old_sec) and not os.path.isfile(new_sec):
        shutil.copy2(old_sec, new_sec)


def state_dir() -> str:
    d = os.path.join(app_dir(), "state")
    os.makedirs(d, exist_ok=True)
    return d


# -- config import / export ----------------------------------------------------
CONFIG_FORMAT = 1


def export_config(config: "Config", path: str) -> int:
    """Write games + provider settings to a JSON file. Returns game count.

    Credentials are NOT included (tokens live in the Windows Credential
    Manager and never leave this PC).
    """
    data = {
        "savepoint_config": CONFIG_FORMAT,
        "exported": now_iso(),
        "settings": {"provider": config.settings.get("provider", "github"),
                     "providers": config.settings.get("providers", {})},
        "games": [g.to_dict() for g in config.games],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return len(config.games)


def parse_config_export(path: str):
    """Read an exported config file. Returns (settings_subset, [Game]).

    Raises ValueError on malformed files. Settings contain only the
    provider-related subset - runtime flags (paused, notifications) are not
    carried across machines.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("games"), list):
        raise ValueError("Not a SavePoint config export")
    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    subset = {"provider": settings.get("provider", "github"),
              "providers": settings.get("providers", {})}
    games = [Game.from_dict(g) for g in data["games"] if isinstance(g, dict)]
    return subset, games


def now_iso() -> str:
    import datetime as dt
    return dt.datetime.now().isoformat(timespec="seconds")


class Config:
    def __init__(self):
        ensure_migrated()
        self.path = os.path.join(app_dir(), "config.json")
        self.settings = {"provider": "github", "providers": {}}
        self.games: list[Game] = []
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception:
            # Corrupted config: keep a copy instead of crashing.
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            return
        if isinstance(data.get("settings"), dict):
            self.settings.update(data["settings"])
        self.games = [Game.from_dict(g) for g in data.get("games", []) if isinstance(g, dict)]

    def save(self):
        with self._lock:
            data = {"settings": self.settings, "games": [g.to_dict() for g in self.games]}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------
    def add_game(self, game: Game):
        with self._lock:
            self.games.append(game)
            self.save()

    def get_game(self, game_id: str):
        return next((g for g in self.games if g.id == game_id), None)

    def remove_game(self, game: Game):
        with self._lock:
            self.games = [g for g in self.games if g.id != game.id]
            self.save()
