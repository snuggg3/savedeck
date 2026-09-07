# SAVEDECK

**One app instead of two:** [Cartridge](https://github.com/snuggg3/cartridge)'s
game library + launcher fused with [SavePoint](https://github.com/snuggg3/savepoint)'s
automatic save-backup engine, in a single lightweight native window.

```
â–ž SAVEDECK   [search]  [A â†’ Z]        SHELF  SCAN  + ADD  âš™ SETTINGS
 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”
 â”‚ cover  â”‚  â”‚ cover  â”‚  â”‚ cover  â”‚   â–¶ RUN launches the game
 â”‚ name   â”‚  â”‚ name   â”‚  â”‚ name   â”‚   â— 2h ago  = saves backed up
 â”‚ STEAM â—â”‚  â”‚ GOG â—‹  â”‚  â”‚ EPIC â–² â”‚   â—‹ never   = unprotected
 â””â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”˜
 12 GAMES Â· PROTECTING 9 Â· last scan 2h ago            SAVEDECK v1.0.0
```

## Why it's fast and light

SaveDeck is **Python + tkinter** (SavePoint's stack), not Electron:

| | SaveDeck | Electron equivalent |
|---|---|---|
| Cold start | **< 1 s** | 2â€“5 s |
| Idle RAM | **~30â€“50 MB** | 150â€“300 MB |
| Idle CPU | ~0% (15 s scheduler tick) | higher |

Cover art is fetched and downscaled **once** per image in background threads,
then cached on disk (`%APPDATA%\SaveDeck\cache`) â€” tiles paint instantly after
the first run. The backup engine lives on daemon threads; closing the window
keeps it protecting saves from the system tray.

## Features

### Library (from Cartridge)
- **Auto-detect** installed games: Steam (`libraryfolders.vdf` +
  `appmanifest_*.acf`), Epic (launcher manifests + storefront box art), GOG
  (Windows registry). `SCAN` adds new games, refreshes launch targets/art/sizes,
  and removes uninstalled entries (favorites, hidden and protected games are
  never touched).
- **Run** any game: `steam://rungameid`, Epic launcher protocol, GOG exe,
  or a manual launch target (exe path, protocol URL, shell command).
- **Favorites** float to the top; **A â†’ Z / Z â†’ A** sorting; `/` to search.
- **Hidden games**: hide games behind an optional password (PBKDF2) — set or remove it from inside the hidden view.
- Cover art from the Steam CDN / Epic storefront, data URLs or local files.

### Save protection (from SavePoint)
- Watches save folders (watchdog) with a 45 s quiet window, plus periodic
  safety-net backups and **catch-up on launch** for missed windows.
- **Only uploads what changed** (SHA-256 diffing); every backup is one version.
- **Destinations**: a private GitHub repo (commit history = version history)
  or a local/network folder. Providers are pluggable
  (`savepoint/providers/base.py`).
- **Restore** any version in place, browsing files first with a size-level
  diff, restoring all or only picked files. Current saves are always
  safety-backed-up before a restore.
- **Secure**: tokens live in the Windows Credential Manager, never in files
  (DPAPI-encrypted fallback available).

### The fusion (possible only combined)
- **Play-session aware backups**: launch a game from the library and SaveDeck
  waits for the process to appear, waits for it to exit, then backs the saves
  up immediately â€” fresh saves captured, never a half-written snapshot.
- **One-click protection**: right-click any tile â†’ *Protect saves...* â†’
  SavePoint's heuristic detector suggests likely save locations; tick them and
  save. The library entry and the protection entry stay linked (`sp_id`).
- **Status badges on tiles**: `â— 2h ago` (backed up), `â–²` (last backup failed),
  `â—‹` (never / unprotected), `â—‹ OFF` (protection disabled).
- **Your existing data migrates automatically on first run**: Cartridge's
  `library.json` is imported, SavePoint's `config.json` + per-game state is
  adopted, and the GitHub token is shared through the Credential Manager.
- **Storage report**: versions, file counts and destination footprint per game.

## Run

Requires Python 3.9+ (tested on 3.14).

```bat
python -m pip install -r requirements.txt
python main.py            :: or: python main.py --minimized  (autostart)
```

Then: **âš™ SETTINGS** â†’ paste a fine-grained GitHub token (Contents:
read+write) â†’ **TEST** â†’ **SAVE TOKEN** â†’ set the default repo (`user/repo`) â†’
**SCAN** â†’ right-click a game â†’ **Protect saves...**.

## Architecture

```
main.py                    entry point: migrations, engine, tray, window
savedeck/
  __init__.py              data dir (%APPDATA%\SaveDeck) + SAVEPOINT_HOME bridge
  library.py               library.json store + Cartridge/SavePoint migrations
  detect.py                Steam/Epic/GOG detection (port of Cartridge's detector.js)
  launch.py                launcher + play-session watcher (post-play backup)
  art.py                   cover-art fetch/downscale with disk cache
  notify.py                toast notifications (winotify)
  theme.py                 phosphor-terminal design system
  ui/app.py                main window: header, tile grid, status bar
  ui/dialogs.py            game/protection editor, settings, versions, storage
savepoint/                 vendored SavePoint engine (unchanged core)
  engine.py                watcher + scheduler + backup/restore
  providers/               github / local_folder (add new ones here)
  config.py, models.py, credentials.py, detector.py, ...
```

Data lives in `%APPDATA%\SaveDeck\` (`library.json`, `config.json`, `state\`,
`cache\`, `savepoint.log`). Because both apps can read the same config schema,
*Export/Import config* moves the whole setup to a new PC.

> Note: SaveDeck **replaces** SavePoint and Cartridge when running â€” don't run
> SavePoint alongside it with a migrated config, or both engines will watch
> the same save folders.

## Keyboard

- `/` â€” focus search Â· `Esc` â€” clear search
- `F5` â€” scan for installed games
- Double-click a tile â€” run Â· right-click â€” full menu
