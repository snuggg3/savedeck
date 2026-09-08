"""Self-update: check GitHub releases and install the new version.

Works for packaged builds (PyInstaller onedir + Inno Setup installer):
- prefers a `SaveDeck-Setup-<version>.exe` asset, run silently, or
- falls back to a `.zip` asset, staged and swapped by a small batch script
  after the running exe exits.

Check-out requires a GitHub token only because the repository is private:
the stored backup token (Contents: read) is reused.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile

import requests

from . import APP_NAME, VERSION
from .engine.credentials import get_secret

REPO = "snuggg3/savedeck"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _headers() -> dict:
    h = {"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/vnd.github+json"}
    token = get_secret("token:github")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check():
    """Return (current_version, latest_version, download_url|None).

    Raises RuntimeError on network/API failure.
    """
    r = requests.get(API, headers=_headers(), timeout=10)
    if r.status_code == 404:
        raise RuntimeError("no release published yet - a GitHub release "
                           "tagged v<version> with a SaveDeck-Setup asset "
                           "is needed")
    if r.status_code != 200:
        raise RuntimeError(f"GitHub returned {r.status_code}: "
                           f"{r.json().get('message', r.text[:120])}")
    data = r.json()
    tag = (data.get("tag_name") or "").lstrip("vV")
    assets = [(a["name"], a["url"]) for a in (data.get("assets") or [])]
    # NOTE: use the API asset url, not browser_download_url - the latter
    # returns 404 for private repos even with a token (no Bearer auth on
    # github.com download links). The API url serves the file when fetched
    # with Accept: application/octet-stream.
    url = None
    for name, u in assets:  # prefer the Inno Setup installer
        low = name.lower()
        if low.endswith(".exe") and "setup" in low:
            url = u
            break
    if url is None:
        for name, u in assets:
            if name.lower().endswith(".zip"):
                url = u
                break
    return VERSION, tag, url


def is_newer(latest: str, current: str = VERSION) -> bool:
    def parts(v: str) -> list:
        out = []
        for chunk in "".join(c if c.isdigit() else "." for c in v).split("."):
            if chunk:
                out.append(int(chunk))
        return out

    try:
        return parts(latest) > parts(current)
    except Exception:
        return False


def _download(url: str, dest: str, on_progress=None) -> None:
    headers = _headers()
    headers["Accept"] = "application/octet-stream"  # asset API endpoint
    with requests.get(url, headers=headers, stream=True,
                      timeout=(15, 60)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done, total)


def apply_update(url: str, on_progress=None) -> str:
    """Download the update and hand over to the new installer (or staged
    replace). Returns a human-readable status message."""
    if not getattr(sys, "frozen", False):
        return ("updates apply to the packaged app - running from source: "
                "git pull instead")
    tmp = tempfile.mkdtemp(prefix="savedeck-update-")
    local = os.path.join(tmp, url.split("/")[-1].split("?")[0])
    _download(url, local, on_progress)

    if local.lower().endswith(".exe"):
        proc = subprocess.Popen([local, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                                 "/NORESTART", "/CLOSEAPPLICATIONS",
                                 "/FORCECLOSEAPPLICATIONS"])
        # The running exe locks its own files, so SaveDeck must exit and
        # something must start the new build after Setup finishes: a small
        # batch waits for the installer process, then relaunches the app.
        app_dir = os.path.dirname(sys.executable)
        exe = os.path.basename(sys.executable)
        bat = os.path.join(tmp, "restart_after_install.bat")
        with open(bat, "w", encoding="utf-8") as f:
            f.write("@echo off\r\n"
                    ":wait\r\n"
                    f"tasklist /FI \"PID eq {proc.pid}\" | find "
                    f"\"{proc.pid}\" >nul && (timeout /t 1 /nobreak >nul "
                    "& goto wait)\r\n"
                    f"start \"\" \"{os.path.join(app_dir, exe)}\"\r\n"
                    "del \"%~f0\"\r\n")
        os.startfile(bat)
        return ("installer launched - SaveDeck will exit and the new "
                "version will start automatically")

    # portable zip: stage extracted files and swap them after we exit
    extract = os.path.join(tmp, "new")
    with zipfile.ZipFile(local) as z:
        z.extractall(extract)
    root = extract
    entries = os.listdir(extract)
    if len(entries) == 1 and os.path.isdir(os.path.join(extract, entries[0])):
        root = os.path.join(extract, entries[0])
    app_dir = os.path.dirname(sys.executable)
    exe = os.path.basename(sys.executable)
    bat = os.path.join(tmp, "apply_update.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n"
                f":wait\r\n"
                f"tasklist /FI \"PID eq {os.getpid()}\" | find "
                f"\"{os.getpid()}\" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n"
                f"xcopy /E /Y /I \"{root}\" \"{app_dir}\"\r\n"
                f"start \"\" \"{os.path.join(app_dir, exe)}\"\r\n"
                "del \"%~f0\"\r\n")
    os.startfile(bat)
    return "update staged - SaveDeck will restart into the new version"
