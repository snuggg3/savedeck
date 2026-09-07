"""SaveDeck — Cartridge + SavePoint combined.

Sets SAVEPOINT_HOME to SaveDeck's own data dir BEFORE savepoint.config is
imported anywhere, so the vendored backup engine stores its config, state
manifests and DPAPI fallback secrets inside %APPDATA%\\SaveDeck while the
GitHub token stays shared through the Windows Credential Manager.
"""
from __future__ import annotations

import os

APP_NAME = "SaveDeck"
VERSION = "1.0.0"


def home_dir() -> str:
    base = os.environ.get("SAVEDECK_HOME") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


HOME = home_dir()
os.environ.setdefault("SAVEPOINT_HOME", HOME)  # engine data lives with us
