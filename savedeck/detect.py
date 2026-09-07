"""Installed-game detection (Steam / Epic / GOG) — Python port of
Cartridge's lib/detector.js, using the stdlib (winreg instead of PowerShell).

Every detector returns a list of dicts with the keys used by library entries:
    name          real game name
    source        steam | epic | gog
    installPath   install directory (when known)
    launchTarget  protocol URL / exe path ready to run
    thumb         cover art URL (Steam CDN / Epic storefront, best effort)
"""
from __future__ import annotations

import json
import os
import re

import requests

STEAM_LIB_URL = "https://steamcdn-a.akamaihd.net/steam/apps/{}/library_600x900.jpg"
STEAM_HEADER_URL = "https://steamcdn-a.akamaihd.net/steam/apps/{}/header.jpg"
EPIC_GRAPHQL = "https://store.epicgames.com/graphql"
_EPIC_QUERY = (
    'query search($term: String) { searchStore(term: $term, category: "games/edition",'
    ' limit: 6) { elements { title keyImages { type url } } } }'
)


# -- tiny Valve KeyValues (VDF) parser -----------------------------------------
def _read_string(text: str, pos: int):
    pos += 1  # skip opening quote
    out = []
    while pos < len(text) and text[pos] != '"':
        c = text[pos]
        if c == "\\" and pos + 1 < len(text):
            pos += 1
            c = text[pos]
        out.append(c)
        pos += 1
    return "".join(out), pos + 1


def parse_vdf(text: str) -> dict:
    """Parse Valve KeyValues format (libraryfolders.vdf / appmanifest .acf)."""
    pos, n = 0, len(text)

    def block():
        nonlocal pos
        d = {}
        while True:
            while pos < n and text[pos] not in '{}"':
                pos += 1  # whitespace / comments / stray chars
            if pos >= n or text[pos] == "}":
                pos += 1
                return d
            key, pos = _read_string(text, pos)
            while pos < n and text[pos] not in '{}"':
                pos += 1
            if pos < n and text[pos] == "{":
                pos += 1
                d[key] = block()
            elif pos < n and text[pos] == '"':
                val, pos = _read_string(text, pos)
                d[key] = val
            else:
                return d

    return block()


# -- Steam ----------------------------------------------------------------------
def _steam_root() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            val, _ = winreg.QueryValueEx(k, "SteamPath")
            if val:
                return val.replace("/", os.sep)
    except Exception:
        pass
    pf = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return os.path.join(pf, "Steam")


def _steam_libraries(root: str) -> list:
    libs = []
    vdf = os.path.join(root, "config", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            data = parse_vdf(f.read())
        folders = data.get("libraryfolders") or {}
        for entry in folders.values():
            if isinstance(entry, dict) and entry.get("path"):
                libs.append(entry["path"].replace("\\\\", "\\"))
    except Exception:
        pass
    if root not in libs:
        libs.append(root)
    return libs


def detect_steam_games() -> list:
    games = []
    root = _steam_root()
    for lib in _steam_libraries(root):
        apps_dir = os.path.join(lib, "steamapps")
        if not os.path.isdir(apps_dir):
            continue
        for fn in os.listdir(apps_dir):
            m = re.match(r"appmanifest_(\d+)\.acf$", fn, re.IGNORECASE)
            if not m:
                continue
            appid = m.group(1)
            try:
                with open(os.path.join(apps_dir, fn), encoding="utf-8",
                          errors="replace") as f:
                    data = parse_vdf(f.read()).get("AppState") or {}
            except OSError:
                continue
            try:
                if int(data.get("StateFlags", "0")) & 4 == 0:
                    continue  # not fully installed
            except (TypeError, ValueError):
                pass
            name = (data.get("name") or "").strip()
            if not name:
                continue
            install = os.path.join(lib, "steamapps", "common",
                                   data.get("installdir") or "")
            games.append({
                "name": name,
                "source": "steam",
                "appid": appid,
                "installPath": install if os.path.isdir(install) else None,
                "launchTarget": f"steam://rungameid/{appid}",
                "thumb": STEAM_LIB_URL.format(appid),
            })
    return games


# -- Epic Games Launcher ----------------------------------------------------------
def fetch_epic_thumbnail(name: str, timeout: int = 6):
    """Best-effort box art from the public Epic storefront search."""
    try:
        r = requests.post(EPIC_GRAPHQL, json={"query": _EPIC_QUERY,
                                              "variables": {"term": name}},
                          timeout=timeout,
                          headers={"User-Agent": "SaveDeck/1.0"})
        elements = (r.json().get("data", {}).get("searchStore") or {}
                    ).get("elements") or []
    except Exception:
        return None
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    target = norm(name)
    best, best_score = None, -1
    for el in elements:
        t = norm(el.get("title"))
        if t == target:
            score = 100
        elif t and (t in target or target in t):
            score = 60
        else:
            score = len(set(t.split()) & set(target.split()))
        if score > best_score:
            best_score, best = score, el
    if best_score < 1 or not best:
        return None
    for img in best.get("keyImages") or []:
        if img.get("type") in ("DieselGameBoxTall", "DieselGameBox",
                               "Thumbnail") and img.get("url"):
            return img["url"]
    return None


def detect_epic_games() -> list:
    manifests_dir = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                 "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(manifests_dir):
        return []
    games = []
    for fn in os.listdir(manifests_dir):
        if not fn.endswith(".item"):
            continue
        try:
            with open(os.path.join(manifests_dir, fn), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        name = (data.get("DisplayName") or "").strip()
        if not name or data.get("bIsIncompleteInstall"):
            continue
        launch = (f"com.epicgames.launcher://apps/{data.get('AppName')}"
                  "?action=launch&silent=true") if data.get("AppName") else None
        games.append({
            "name": name,
            "source": "epic",
            "installPath": data.get("InstallLocation") or None,
            "launchTarget": launch,
            "thumb": None,  # filled by fetch_epic_thumbnail during scans
        })
    return games


# -- GOG ---------------------------------------------------------------------------
def detect_gog_games() -> list:
    try:
        import winreg
    except ImportError:
        return []
    games = []
    for _hive, path in ((0, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
                        (0, r"SOFTWARE\GOG.com\Games")):
        try:
            import winreg as wr
            key = wr.OpenKey(wr.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    subkey_name = wr.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with wr.OpenKey(key, subkey_name) as sk:
                        def val(name, default=None):
                            try:
                                v, _ = wr.QueryValueEx(sk, name)
                                return v
                            except OSError:
                                return default
                        name = (val("gameName") or "").strip()
                        gog_path = val("path") or ""
                        exe = val("exe") or ""
                        launch_param = val("launchParam") or ""
                        if not name or not exe:
                            continue
                        exe_path = os.path.join(gog_path, exe)
                        games.append({
                            "name": name,
                            "source": "gog",
                            "installPath": gog_path or None,
                            "launchTarget": f'"{exe_path}" {launch_param}'.strip(),
                            "thumb": None,
                        })
                except OSError:
                    continue
        finally:
            wr.CloseKey(key)
        if games:
            break  # first registry path that worked is enough
    return games


def detect_installed_games() -> list:
    """Merge all sources, deduplicated by lowercase name (Cartridge parity)."""
    games, seen = [], set()
    for source_games in (detect_steam_games(), detect_epic_games(),
                         detect_gog_games()):
        for g in source_games:
            key = g["name"].lower()
            if key not in seen:
                seen.add(key)
                games.append(g)
    return games


