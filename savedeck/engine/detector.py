"""Heuristic helper that finds likely save-file locations for a game.

Scans the usual Windows save locations (Saved Games, Documents\\My Games,
%APPDATA%, %LOCALAPPDATA%, Documents) and ranks candidate folders by name
similarity to the game plus how recently their contents were modified.
"""
from __future__ import annotations

import os
import re
import time

_SCORING_BUDGET = 400  # max filesystem entries inspected per candidate


def _base_dirs() -> list:
    up = os.path.expanduser("~")
    return [
        os.path.join(up, "Saved Games"),
        os.path.join(up, "Documents", "My Games"),
        os.path.join(up, "Documents"),
        os.environ.get("APPDATA", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]


def _latest_mtime(path: str, depth: int = 2) -> float:
    """Most recent modification time under `path` (bounded scan)."""
    best, count = 0.0, 0

    def walk(p: str, d: int):
        nonlocal best, count
        if count > _SCORING_BUDGET:
            return
        try:
            entries = os.scandir(p)
        except OSError:
            return
        with entries:
            for e in entries:
                count += 1
                if count > _SCORING_BUDGET:
                    return
                try:
                    if e.is_dir(follow_symlinks=False):
                        if d < depth:
                            walk(e.path, d + 1)
                    else:
                        m = e.stat().st_mtime
                        if m > best:
                            best = m
                except OSError:
                    continue
    walk(path, 0)
    return best


def suggest_locations(name: str = "", limit: int = 25) -> list:
    """Return likely save locations, best guess first."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) >= 3]
    now = time.time()
    scored = {}
    for base in _base_dirs():
        if not base or not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for entry in entries:
            if entry.startswith(".") or entry.startswith("$"):
                continue
            path = os.path.join(base, entry)
            if not os.path.isdir(path):
                continue
            score = 0
            low = entry.lower()
            if tokens and any(t in low for t in tokens):
                score += 10
            mtime = _latest_mtime(path)
            if mtime:
                age_days = (now - mtime) / 86400
                if age_days < 14:
                    score += 8
                elif age_days < 90:
                    score += 4
            if score >= 8:
                scored[path] = score
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])[:limit]
    return [p for p, _ in ranked]


# -- played-game detection -----------------------------------------------------
_NOISE_SUFFIX = re.compile(
    r"[._-]?(win64|win32|x64|x86|dx11|dx12|steam|demo|beta|alpha|game|"
    r"enhanced|ultimate|definitive|remaster)$", re.IGNORECASE)


def detect_running_games(known_names, limit: int = 5) -> list:
    """Look for running programs that have same-named save folders.

    `known_names` is a set of lowercase names to ignore (configured games and
    previously dismissed suggestions). Returns up to `limit` dicts:
    {"name", "exe", "path"} where `path` is a likely save folder.
    """
    from .processes import running_process_names

    save_dirs = {}
    for base in _base_dirs():
        if not base or not os.path.isdir(base):
            continue
        try:
            for entry in os.listdir(base):
                if entry.startswith(".") or entry.startswith("$"):
                    continue
                p = os.path.join(base, entry)
                if os.path.isdir(p):
                    save_dirs.setdefault(entry.lower(), p)
        except OSError:
            continue

    known = {n.lower() for n in known_names or []}
    results, seen = [], set()
    for exe in running_process_names():
        stem = exe[:-4] if exe.lower().endswith(".exe") else exe
        while True:
            stripped = _NOISE_SUFFIX.sub("", stem)
            if stripped == stem:
                break
            stem = stripped
        token = stem.strip().lower().replace("_", " ").replace("-", " ").strip()
        if len(token) < 3 or token in known or token in seen:
            continue
        folder = save_dirs.get(token) or save_dirs.get(stem.strip().lower())
        if not folder:
            continue
        seen.add(token)
        display = stem.strip().replace("_", " ").replace("-", " ").strip()
        display = display[:1].upper() + display[1:]
        results.append({"name": display or stem, "exe": exe, "path": folder})
        if len(results) >= limit:
            break
    return results
