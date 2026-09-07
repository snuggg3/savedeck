"""Local/network-folder backup provider.

Useful for offline games, external drives, NAS paths - and as a working
example of how to implement the provider interface.

Layout inside the destination folder:
    <base>/history/<version-id>/<remote_path>   one snapshot per backup run
    <base>/latest/<remote_path>                 newest copy of each file
A version id is a point in time: restoring it brings back every file's
newest snapshot at or before that moment.
The `repo` field holds the destination folder path.
"""
from __future__ import annotations

import datetime as dt
import itertools
import os
import shutil
import threading

from .base import CloudProvider, RemoteVersion


class LocalFolderProvider(CloudProvider):
    id = "local_folder"
    display_name = "Local / network folder"

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def configure(self, **credentials):
        self.credentials = credentials  # no credentials needed

    # ------------------------------------------------------------------
    def test_connection(self, repo: str = "") -> str:
        if repo:
            os.makedirs(repo, exist_ok=True)
            probe = os.path.join(repo, ".savedeck_write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        return "Folder ready"

    def get_account(self) -> str:
        return ""

    def repo_exists(self, repo: str) -> bool:
        return bool(repo) and os.path.isdir(repo)

    def create_repo(self, repo: str, private: bool = True) -> None:
        os.makedirs(repo, exist_ok=True)

    # ------------------------------------------------------------------
    def _version_id(self) -> str:
        # Caller must hold self._lock (upload_file does).
        n = next(self._counter)
        return dt.datetime.now().strftime("%Y%m%dT%H%M%S") + f"_{n:04d}"

    def upload_file(self, repo: str, remote_path: str, local_path: str, message: str) -> None:
        self.upload_files(repo, [(remote_path, local_path)], message)

    def upload_files(self, repo: str, files, message: str) -> None:
        """Copy all files into ONE timestamped snapshot (one version)."""
        with self._lock:
            vid = self._version_id()
            for remote_path, local_path in files:
                parts = remote_path.split("/")
                hist = os.path.join(repo, "history", vid, *parts)
                latest = os.path.join(repo, "latest", *parts)
                os.makedirs(os.path.dirname(hist), exist_ok=True)
                shutil.copy2(local_path, hist)
                os.makedirs(os.path.dirname(latest), exist_ok=True)
                shutil.copy2(local_path, latest)

    def download_file(self, repo: str, remote_path: str, ref: str, dest_path: str) -> None:
        src = None
        if ref:
            # newest snapshot at or before `ref` that contains this file
            for vid in reversed(self._snapshot_dirs(repo)):
                if vid > ref:
                    continue
                cand = os.path.join(repo, "history", vid, *remote_path.split("/"))
                if os.path.isfile(cand):
                    src = cand
                    break
        if src is None:
            src = os.path.join(repo, "latest", *remote_path.split("/"))
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Backup file not found in history: {remote_path}")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        shutil.copy2(src, dest_path)

    def list_versions(self, repo: str, remote_path: str, limit: int = 50) -> list:
        hist = os.path.join(repo, "history")
        if not os.path.isdir(hist):
            return []
        versions = []
        for vid in sorted(os.listdir(hist), reverse=True)[:limit]:
            try:
                date = dt.datetime.strptime(vid.split("_")[0], "%Y%m%dT%H%M%S")
                date = date.isoformat(timespec="seconds")
            except ValueError:
                date = ""
            versions.append(RemoteVersion(vid, "Backup", date))
        return versions

    def _snapshot_dirs(self, repo: str):
        """All history snapshot ids, oldest first (ids sort chronologically)."""
        hist = os.path.join(repo, "history")
        if not os.path.isdir(hist):
            return []
        return sorted(os.listdir(hist))

    def list_tree(self, repo: str, ref: str, prefix: str = "") -> list:
        """Files under `prefix` as of version `ref` (state at that point in time).

        `ref` is treated as a point in time: for each file, the newest
        snapshot at or before `ref` wins. ref='' means latest state.
        """
        pre = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        if not ref:
            base = os.path.join(repo, "latest")
            if not os.path.isdir(base):
                return []
            out = []
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, base).replace(os.sep, "/")
                    if pre and not rel.startswith(pre):
                        continue
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    out.append((rel, size))
            return sorted(out)

        state = {}
        for vid in self._snapshot_dirs(repo):
            if vid > ref:
                break
            snap = os.path.join(repo, "history", vid)
            for dirpath, _dirs, files in os.walk(snap):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, snap).replace(os.sep, "/")
                    if pre and not rel.startswith(pre):
                        continue
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    state[rel] = (full, size)
        return sorted((rel, size) for rel, (_full, size) in state.items())

    def prune_versions(self, repo: str, prefix: str, keep: int) -> None:
        """Delete old version snapshots that only contain files of `prefix`."""
        hist = os.path.join(repo, "history")
        if not os.path.isdir(hist) or keep <= 0:
            return
        vids = sorted(os.listdir(hist))
        for vid in vids[:-keep] if len(vids) > keep else []:
            snap = os.path.join(hist, vid)
            entries = []
            for dirpath, _dirs, files in os.walk(snap):
                for fn in files:
                    entries.append(
                        os.path.relpath(os.path.join(dirpath, fn), snap).replace(os.sep, "/"))
            # Only remove snapshots that belong exclusively to this game.
            if entries and all(e.startswith(prefix.strip("/") + "/") for e in entries):
                shutil.rmtree(snap, ignore_errors=True)

    def repo_size(self, repo: str) -> int:
        """Total size of the backup folder on disk, in bytes."""
        total = 0
        for dirpath, _dirnames, filenames in os.walk(repo):
            for fn in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
        return total
