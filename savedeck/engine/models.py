"""Game configuration model."""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field


def safe_name(name: str) -> str:
    """Turn a game name into a safe remote folder name."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "", name or "").strip().replace(" ", "_")
    return cleaned or "game"


@dataclass
class Game:
    """A single game whose saves we protect."""

    id: str = ""
    name: str = ""
    paths: list = field(default_factory=list)      # save files / folders (absolute or ~-relative)
    provider: str = "github"                        # provider id, e.g. "github", "local_folder"
    repo: str = ""                                  # provider destination: "user/repo" or folder path
    remote_folder: str = ""                         # folder inside the destination, e.g. "saves/elixir"
    watch_changes: bool = True                      # back up shortly after files change
    interval_minutes: int = 60                      # periodic safety-net check (0 = never)
    enabled: bool = True
    exclude_patterns: list = field(default_factory=list)  # glob patterns, e.g. ["*.tmp"]
    max_versions: int = 0                           # keep N versions (0 = unlimited, local provider prunes)
    process_names: list = field(default_factory=list)     # game executables, e.g. ["elden ring.exe"]
    skip_while_running: bool = False                # don't back up while the game is running
    last_backup: str = ""                           # ISO timestamp of last successful backup
    last_status: str = "never"                      # never | ok | error
    last_error: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.remote_folder:
            self.remote_folder = safe_name(self.name)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Game":
        fields = Game.__dataclass_fields__
        return Game(**{k: v for k, v in d.items() if k in fields})
