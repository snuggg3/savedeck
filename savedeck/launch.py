"""Game launching + play-session tracking.

The session watcher is the Cartridge→SavePoint integration: when a game is
launched from the library and its savepoint Game has process names configured,
SaveDeck waits for the process to appear and then disappear, and triggers an
immediate backup when you stop playing — saves are captured while fresh,
never while the game is mid-write.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time


class LaunchError(RuntimeError):
    pass


def launch_target(entry: dict) -> str:
    return (entry.get("launchTarget") or "").strip()


def launch(entry: dict):
    """Launch a library entry. Returns the Popen handle for exe targets."""
    target = launch_target(entry)
    if not target:
        raise LaunchError(f'"{entry.get("name")}" has no launch target configured')
    if "://" in target:
        os.startfile(target)  # steam://, com.epicgames.launcher://, custom protocols
        return None
    m = re.match(r'^"([^"]+)"\s*(.*)$', target)
    if m and os.path.isfile(m.group(1)):
        args = [m.group(1)] + m.group(2).split()
        return subprocess.Popen(args, cwd=os.path.dirname(m.group(1)))
    path = target.split()[0].strip('"')
    if target.lower().endswith(".exe") and os.path.isfile(target):
        return subprocess.Popen([target], cwd=os.path.dirname(target))
    if os.path.isfile(path):
        return subprocess.Popen([path], cwd=os.path.dirname(path))
    return subprocess.Popen(target, shell=True)


def watch_session(process_names, engine, game_id, log=print):
    """Wait for the game to start, then to stop, then back up its saves.

    Runs on a daemon thread. `process_names` are executable names like
    ["elden ring.exe"]. Polling is deliberately lazy (15 s) — this thread
    costs nothing while the game runs.
    """
    from savepoint.processes import is_running

    def _run():
        started = False
        for _ in range(12):  # up to 3 min for the game to appear
            if is_running(process_names):
                started = True
                break
            time.sleep(15)
        if not started:
            return
        log(f"playing - will back up saves when you stop")
        while is_running(process_names):
            time.sleep(15)
        time.sleep(20)  # let the game finish writing its saves
        try:
            engine.backup_now(game_id)
            log("game closed - backing up saves now")
        except Exception as e:
            log(f"post-play backup failed: {e}")

    threading.Thread(target=_run, daemon=True, name="savedeck-session").start()
