"""One-command release: bump version, commit+push, build, publish.

Usage (run with the Python that has PyInstaller installed):
    python packaging/release.py            # auto-bump patch (1.0.0 -> 1.0.1)
    python packaging/release.py 1.2.0      # explicit version

Steps:
  1. rewrite VERSION (savedeck/__init__.py) + MyAppVersion (SaveDeck.iss)
  2. commit + push (auth via the stored GitHub token, fallback to plain git)
  3. PyInstaller onedir build, then Inno Setup installer (auto-finds ISCC)
  4. create the GitHub release v<version> and upload SaveDeck-Setup-*.exe
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT_FILE = os.path.join(ROOT, "savedeck", "__init__.py")
ISS_FILE = os.path.join(ROOT, "packaging", "SaveDeck.iss")
REPO = "snuggg3/savedeck"


def run(cmd, **kw):
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def current_version() -> str:
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', read(INIT_FILE))
    if not m:
        raise SystemExit("cannot find VERSION in savedeck/__init__.py")
    return m.group(1)


def bump(version: str) -> str:
    parts = (version.split(".") + ["0", "0"])[:3]
    return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"


def is_newer(a: str, b: str) -> bool:
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    return pa > pb


def set_version(new: str):
    init = read(INIT_FILE)
    with open(INIT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(re.sub(r'VERSION\s*=\s*"[^"]+"', f'VERSION = "{new}"', init))
    iss = read(ISS_FILE)
    with open(ISS_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(re.sub(r'define MyAppVersion "[^"]+"',
                       f'define MyAppVersion "{new}"', iss))


def git_token() -> str | None:
    sys.path.insert(0, ROOT)
    try:
        from savedeck.engine.credentials import get_secret
        return get_secret("token:github")
    except Exception:
        return None


def git_push():
    token = git_token()
    if token:
        import base64
        enc = base64.b64encode(f"snuggg3:{token}".encode()).decode()
        ok = run(["git", "-c", f"http.extraheader=AUTHORIZATION: basic {enc}",
                  "push", "origin", "main"])
    else:
        ok = run(["git", "push", "origin", "main"])
    if ok.returncode != 0:
        raise SystemExit("git push failed - release tag would point at the "
                         "wrong commit. Push manually and re-run.")


def git_log_since(last_tag: str | None) -> str:
    rng = f"{last_tag}..HEAD" if last_tag else "-15"
    r = subprocess.run(["git", "log", rng, "--pretty=- %s (%h)"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    return "\n".join(lines[:20]) or "- maintenance release"


def last_tag() -> str | None:
    r = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                       cwd=ROOT, capture_output=True, text=True)
    tag = (r.stdout or "").strip()
    return tag or None


def find_iscc() -> str:
    from shutil import which
    if which("iscc"):
        return "iscc"
    candidates = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LocalAppData", "")
    for base in (os.path.join(lad, "Programs"), pf, pf86):
        if base:
            for ver in ("7", "6"):
                candidates.append(os.path.join(base, f"Inno Setup {ver}",
                                               "ISCC.exe"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise SystemExit("ISCC.exe not found - install Inno Setup 6/7")


def github_api(token: str, method: str, url: str, payload=None):
    import requests
    headers = {"User-Agent": "SaveDeck-release",
               "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        r = requests.request(method, url, headers=headers,
                             data=json.dumps(payload), timeout=30)
    else:
        r = requests.request(method, url, headers=headers, timeout=30)
    if r.status_code not in (200, 201):
        raise SystemExit(f"GitHub {method} {url} -> {r.status_code}: "
                         f"{r.text[:200]}")
    return r.json()


def upload_asset(token: str, release_id: int, path: str):
    import requests
    name = os.path.basename(path)
    url = (f"https://uploads.github.com/repos/{REPO}/releases/"
           f"{release_id}/assets?name={name}")
    headers = {"User-Agent": "SaveDeck-release",
               "Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with open(path, "rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=600)
    if r.status_code not in (200, 201):
        raise SystemExit(f"asset upload failed ({r.status_code}): "
                         f"{r.text[:200]}")
    return r.json()


def main():
    current = current_version()
    new = sys.argv[1] if len(sys.argv) > 1 else bump(current)
    if not is_newer(new, current):
        raise SystemExit(f"new version ({new}) must be greater than the "
                         f"current one ({current})")
    print(f"releasing v{new} (current v{current})")

    # 1. bump version files
    set_version(new)
    print(f"version bumped in savedeck/__init__.py and packaging/SaveDeck.iss")

    # 2. commit + push
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"release v{new}"])
    git_push()

    # 3. build: PyInstaller onedir + Inno Setup installer
    installer = os.path.join(ROOT, "dist",
                             f"SaveDeck-Setup-{new}.exe")
    pyi = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--windowed", "--onedir", "--name", "SaveDeck",
               "--exclude-module", "matplotlib", "--exclude-module", "numpy",
               "--exclude-module", "scipy", "--exclude-module", "PyQt5",
               "--exclude-module", "PySide6", "--exclude-module", "IPython",
               "main.py"])
    if pyi.returncode != 0:
        raise SystemExit("PyInstaller build failed")
    iscc = find_iscc()
    print(f"using Inno compiler: {iscc}")
    iss = run([iscc, os.path.join("packaging", "SaveDeck.iss")])
    if iss.returncode != 0:
        raise SystemExit("Inno Setup compile failed")
    if not os.path.isfile(installer):
        raise SystemExit(f"installer not found: {installer}")

    # 4. publish the GitHub release
    token = git_token()
    prev = last_tag()
    since = prev or "the previous release"
    body = (f"SaveDeck v{new}\n\nChanges since {since}:\n"
            f"{git_log_since(prev)}")
    rel = github_api(token, "POST",
                     f"https://api.github.com/repos/{REPO}/releases",
                     {"tag_name": f"v{new}", "target_commitish": "main",
                      "name": f"SaveDeck {new}", "body": body,
                      "draft": False, "prerelease": False})
    asset = upload_asset(token, rel["id"], installer)
    print(f"\nRELEASE OK: v{new}")
    print(f"  release: {rel['html_url']}")
    print(f"  asset  : {asset['name']} "
          f"({asset['size'] // 1024 // 1024} MB)")
    print("Installed apps will pick this up via 'Check for updates...'.")


if __name__ == "__main__":
    main()

