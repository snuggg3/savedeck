"""Library store — SaveDeck's game collection (Cartridge-compatible).

A plain JSON file in the app data dir. Each entry is a dict:

    id            stable uuid (matches the SavePoint game id when protected)
    name          display name
    source        steam | epic | gog | manual
    thumbnail     image URL, data URL, local path or None
    installPath   install dir, when known
    launchTarget  steam:// URL, launcher protocol, exe path or shell command
    sizeBytes     install size (from scans)
    favorite      bool - floats to the top
    hidden        bool - moved to the private shelf
    sp_id         id of the linked savepoint.models.Game ("" = unprotected)
    addedAt       ISO timestamp

On first run it imports an existing Cartridge library and an existing
SavePoint config, so upgrading from either app is automatic.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
import shutil
import uuid

from . import home_dir


def data_dir() -> str:
    return home_dir()


def library_path() -> str:
    return os.path.join(data_dir(), "library.json")


def _empty() -> dict:
    return {"games": [], "lastScan": None}


def new_entry(name: str, **kw) -> dict:
    return {
        "id": kw.get("id") or uuid.uuid4().hex,
        "name": name,
        "source": kw.get("source", "manual"),
        "thumbnail": kw.get("thumbnail"),
        "installPath": kw.get("installPath"),
        "launchTarget": kw.get("launchTarget"),
        "sizeBytes": kw.get("sizeBytes"),
        "favorite": bool(kw.get("favorite")),
        "hidden": bool(kw.get("hidden")),
        "sp_id": kw.get("sp_id", ""),
        "addedAt": kw.get("addedAt") or datetime.datetime.now().isoformat(timespec="seconds"),
    }


def load_library() -> dict:
    try:
        with open(library_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data.get("games"), list) else _empty()
    except Exception:
        return _empty()


def save_library(library: dict) -> None:
    os.makedirs(data_dir(), exist_ok=True)
    tmp = library_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2)
    os.replace(tmp, library_path())


def find_entry(library: dict, entry_id: str):
    return next((g for g in library["games"] if g.get("id") == entry_id), None)


# -- one-time migrations -------------------------------------------------------
def migrate_from_cartridge() -> int:
    """Import the Cartridge library on first run. Returns imported count."""
    if os.path.isfile(library_path()):
        return 0
    src = os.path.join(os.environ.get("APPDATA", ""), "Cartridge", "data",
                       "library.json")
    if not os.path.isfile(src):
        return 0
    try:
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games") if isinstance(data, dict) else None
        if not isinstance(games, list):
            return 0
    except Exception:
        return 0
    lib = _empty()
    for g in games:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        lib["games"].append(new_entry(
            str(g["name"]),
            source=g.get("source") or "manual",
            thumbnail=g.get("thumbnail"),
            installPath=g.get("installPath"),
            launchTarget=g.get("launchTarget"),
            sizeBytes=g.get("sizeBytes"),
            favorite=bool(g.get("favorite")),
            hidden=bool(g.get("hidden")),
            addedAt=g.get("addedAt"),
        ))
    save_library(lib)
    return len(lib["games"])


def migrate_from_savepoint() -> bool:
    """Adopt an existing SavePoint config on first run.

    The vendored engine reads SAVEPOINT_HOME (pointed at SaveDeck's dir by
    savedeck/__init__), so its config.json, per-game state manifests and the
    DPAPI fallback secrets move in wholesale. The GitHub token itself is
    shared through the Windows Credential Manager either way.
    """
    cfg = os.path.join(data_dir(), "config.json")
    if os.path.isfile(cfg):
        return False
    old = os.path.join(os.environ.get("APPDATA", ""), "SavePoint")
    if not os.path.isfile(os.path.join(old, "config.json")):
        return False
    try:
        shutil.copy2(os.path.join(old, "config.json"), cfg)
        old_state = os.path.join(old, "state")
        if os.path.isdir(old_state):
            new_state = os.path.join(data_dir(), "state")
            os.makedirs(new_state, exist_ok=True)
            for fn in os.listdir(old_state):
                if fn.endswith(".json"):
                    dst = os.path.join(new_state, fn)
                    if not os.path.isfile(dst):
                        shutil.copy2(os.path.join(old_state, fn), dst)
        old_sec = os.path.join(old, "secrets.bin")
        if os.path.isfile(old_sec):
            shutil.copy2(old_sec, os.path.join(data_dir(), "secrets.bin"))
        return True
    except Exception:
        return False


# -- private shelf password -----------------------------------------------------
def _hidden_file() -> str:
    return os.path.join(data_dir(), "hidden.json")


def hidden_password_set() -> bool:
    return os.path.isfile(_hidden_file())


def set_hidden_password(password: str) -> None:
    if not password:
        try:
            os.remove(_hidden_file())
        except OSError:
            pass
        return
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 60_000)
    with open(_hidden_file(), "w", encoding="utf-8") as f:
        json.dump({"salt": base64.b64encode(salt).decode(),
                   "hash": base64.b64encode(digest).decode()}, f)


def verify_hidden_password(password: str) -> bool:
    try:
        with open(_hidden_file(), encoding="utf-8") as f:
            data = json.load(f)
        salt = base64.b64decode(data["salt"])
        digest = base64.b64decode(data["hash"])
    except Exception:
        return True  # no password set: nothing to verify
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 60_000)
    return hmac.compare_digest(digest, check)

