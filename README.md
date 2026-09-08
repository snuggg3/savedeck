# SAVEDECK

A **standalone gaming utility**: a fast, terminal-styled game library and
launcher with a built-in automatic save-backup engine — one lightweight
native window, one process.

```
▞ SAVEDECK   [search]  [A → Z]        HIDDEN  SCAN  + ADD  ⚙ SETTINGS
 ┌────────┐  ┌────────┐  ┌────────┐
 │ cover  │  │ cover  │  │ cover  │   ▶ RUN launches the game
 │ name   │  │ name   │  │ name   │   ● 2h ago  = saves backed up
 │ STEAM ●│  │ GOG ○  │  │ EPIC ▲ │   ○ never   = unprotected
 └────────┘  └────────┘  └────────┘
 12 GAMES · PROTECTING 9 · last scan 2h ago            SAVEDECK v1.0.0
```

## Why it's fast and light

SaveDeck is **Python + tkinter**, not Electron:

| | SaveDeck | Electron equivalent |
|---|---|---|
| Cold start | **< 1 s** | 2–5 s |
| Idle RAM | **~30–50 MB** | 150–300 MB |
| Idle CPU | ~0% (15 s scheduler tick) | higher |

Cover art is fetched and downscaled **once** per image in background threads,
then cached on disk (`%APPDATA%\SaveDeck\cache`) — tiles paint instantly after
the first run. The backup engine lives on daemon threads; closing the window
keeps it protecting saves from the system tray.

## Features

### Game library
- **Auto-detect** installed games: Steam (`libraryfolders.vdf` +
  `appmanifest_*.acf`), Epic (launcher manifests + storefront box art), GOG
  (Windows registry). `SCAN` adds new games, refreshes launch targets/art/sizes,
  and removes uninstalled entries (favorites, hidden and protected games are
  never touched).
- **Run** any game: `steam://rungameid`, Epic launcher protocol, GOG exe,
  or a manual launch target (exe path, protocol URL, shell command).
- **Open folder** on any game with a known install path.
- **Favorites** float to the top; **A → Z / Z → A** sorting; `/` to search.
- **Hidden games**: hide games behind an optional password (PBKDF2) — set or
  remove it from inside the hidden view.
- Cover art from the Steam CDN / Epic storefront, data URLs or local files.

### Automatic save protection
- Watches save folders (watchdog) with a 45 s quiet window, plus periodic
  safety-net backups and **catch-up on launch** for missed windows.
- **Only uploads what changed** (SHA-256 diffing); every backup is one version.
- **Destinations**: a private GitHub repo (commit history = version history)
  or a local/network folder. Providers are pluggable
  (`savedeck/engine/providers/base.py`).
- **Restore** any version in place, browsing files first with a size-level
  diff, restoring all or only picked files. Current saves are always
  safety-backed-up before a restore.
- **Secure**: tokens live in the Windows Credential Manager, never in files
  (DPAPI-encrypted fallback available).

### Library + protection together
- **Play-session aware backups**: launch a game from the library and SaveDeck
  waits for the process to appear, waits for it to exit, then backs the saves
  up immediately — fresh saves captured, never a half-written snapshot.
- **One-click protection**: right-click any tile → *Protect saves...* →
  the built-in heuristic detector suggests likely save locations; tick them
  and save. The library entry and the protection entry stay linked (`sp_id`).
- **Status badges on tiles**: `● 2h ago` (backed up), `▲` (last backup failed),
  `○` (never / unprotected), `○ OFF` (protection disabled).
- **Storage report**: versions, file counts and destination footprint per game.

## Install & self-update

Build a Windows installer (requires [PyInstaller](https://pyinstaller.org)
and [Inno Setup 6](https://jrsoftware.org/isinfo.php) with `iscc` on PATH):

```bat
pip install pyinstaller
packaging\build.bat        :: -> dist\SaveDeck-Setup-1.0.0.exe
```

Attach the produced `SaveDeck-Setup-<version>.exe` (or a portable
`SaveDeck-<version>-win64.zip`) to a GitHub release tagged `v<version>` —
the app updates itself:

- **⚙ SETTINGS → "Check for updates..."** compares against the latest release
  (using the stored GitHub token, since the repo is private), downloads it,
  and runs the new installer silently (`/VERYSILENT`, restarting the app).
- Packaged builds also show a toast when a new release is detected a few
  seconds after startup (disable with `"check_updates": false` in settings).
- Portable `.zip` assets are supported too: the update is staged and swapped
  by a small batch script after the running exe exits.

## Run (from source)

Requires Python 3.9+ (tested on 3.14).

```bat
python -m pip install -r requirements.txt
python main.py            :: or: python main.py --minimized  (autostart)
```

Then: **⚙ SETTINGS** → paste a fine-grained GitHub token (Contents:
read+write) → **TEST** → **SAVE TOKEN** → set the default repo (`user/repo`) →
**SCAN** → right-click a game → **Protect saves...**.

## Architecture

```
main.py                    entry point: engine, tray, window
savedeck/
  __init__.py              app identity + data dir (%APPDATA%\SaveDeck)
  library.py               library.json store + optional Cartridge import
  detect.py                Steam/Epic/GOG detection (stdlib: winreg + VDF parser)
  launch.py                launcher + play-session watcher (post-play backup)
  art.py                   cover-art fetch/downscale with disk cache
  notify.py                toast notifications (winotify)
  theme.py                 phosphor-terminal design system + window centering
  ui/app.py                main window: header, tile grid, status bar
  ui/dialogs.py            game/protection editor, settings, versions, storage
  engine/                  built-in backup engine
    engine.py              watcher + scheduler + backup/restore
    providers/             github / local_folder (add new ones here)
    config.py, models.py, credentials.py, detector.py, ...
```

Data lives in `%APPDATA%\SaveDeck\` (`library.json`, `config.json`, `state\`,
`cache\`, `savedeck.log`). *Export/Import config* moves the whole setup to a
new PC (tokens are not exported - they never leave the machine).

## Keyboard

- `/` or `Ctrl+F` — focus search · `Esc` — clear search
- `F5` — scan for installed games
- Double-click a tile — run · right-click — full menu

## Status bar

Every tray action is also in the status bar: **⏸ PAUSE / ▶ RESUME**,
**⇪ BACKUP ALL** (back up every protected game now) and **⏏ EXIT** (full
exit — closing the window only hides to the tray). Sort modes: A → Z,
Z → A, and *Recently backed up*.
