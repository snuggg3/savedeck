"""SaveDeck - game library with built-in automatic save protection.

Everything lives in one data dir (%APPDATA%\\SaveDeck): the library, the
backup engine's config and per-game state, the cover-art cache and the log.
Credentials (GitHub token) go to the Windows Credential Manager.
"""
from __future__ import annotations

import os

APP_NAME = "SaveDeck"
VERSION = "1.0.1"


def home_dir() -> str:
    base = os.environ.get("SAVEDECK_HOME") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


HOME = home_dir()
