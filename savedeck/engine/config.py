"""SaveDeck backup-engine configuration storage (atomic JSON in %APPDATA%)."""
from __future__ import annotations

import json
import os
import threading

from .. import home_dir
from .models import Game

APP_NAME = "SaveDeck"


def app_dir() -> str:
    """Directory holding config/state (SaveDeck's data dir)."""
    base = home_dir()
    os.makedirs(base, exist_ok=True)
    return base


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
        "savedeck_config": CONFIG_FORMAT,
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
        raise ValueError("Not a SaveDeck config export")
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
