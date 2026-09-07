"""GitHub backup provider.

Each backup run is pushed as a single git commit containing every changed
file, so the repository's commit history is the backup version history -
previous saves are always recoverable - without one-commit-per-file overhead.
Uses a private repository (recommended) plus a fine-grained personal access
token with "Contents: Read and write" permission.
"""
from __future__ import annotations

import base64
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

from .base import CloudProvider, RemoteVersion

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def _api_message(r) -> str:
    try:
        return r.json().get("message", r.text[:200])
    except Exception:
        return (r.text or "")[:200]


class GitHubProvider(CloudProvider):
    id = "github"
    display_name = "GitHub"

    def __init__(self):
        self._token = ""
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SaveDeck/1.0"

    def configure(self, token=None, **kw):
        self._token = token or ""

    def _headers(self, raw: bool = False) -> dict:
        h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method, url, *, ok=(200, 201, 204), retries=3, **kwargs):
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}) or {})
        kwargs["headers"] = headers
        last = None
        for attempt in range(retries):
            try:
                r = self._session.request(method, url, timeout=60, **kwargs)
                if r.status_code in ok:
                    return r
                if r.status_code == 401:
                    raise GitHubError("GitHub rejected the token (401). Check it in 'Settings...'.")
                if r.status_code == 404:
                    raise GitHubError(f"GitHub: not found (404): {_api_message(r)}")
                if 500 <= r.status_code < 600 or r.status_code == 429:
                    last = GitHubError(f"GitHub is having problems ({r.status_code}), retrying...")
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise GitHubError(f"GitHub error {r.status_code}: {_api_message(r)}")
            except (requests.ConnectionError, requests.Timeout) as e:
                last = GitHubError(f"Network problem: {e}")
                time.sleep(min(2 ** attempt, 8))
        raise last or GitHubError("GitHub request failed")

    # -- destination management ----------------------------------------
    def test_connection(self, repo: str = "") -> str:
        return f"Connected to GitHub as {self.get_account()}"

    def get_account(self) -> str:
        return self._request("GET", f"{API}/user").json().get("login", "")

    def repo_exists(self, repo: str) -> bool:
        try:
            self._request("GET", f"{API}/repos/{repo}")
            return True
        except GitHubError as e:
            if "404" in str(e):
                return False
            raise

    def create_repo(self, repo: str, private: bool = True) -> None:
        name = repo.split("/", 1)[1]
        self._request("POST", f"{API}/user/repos",
                      json={"name": name, "private": private, "auto_init": False})

    def _default_branch(self, repo: str) -> str:
        return self._request("GET", f"{API}/repos/{repo}").json().get("default_branch", "main")

    def _branch_head(self, repo: str, branch: str):
        try:
            r = self._request("GET", f"{API}/repos/{repo}/git/ref/heads/{branch}")
            return r.json()["object"]["sha"]
        except GitHubError as e:
            if "404" in str(e):
                return None  # empty repository, no commits yet
            raise

    # -- file operations -------------------------------------------------
    def _blob_sha(self, repo: str, local_path: str) -> str:
        with open(local_path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        return self._request("POST", f"{API}/repos/{repo}/git/blobs",
                             json={"content": content, "encoding": "base64"}).json()["sha"]

    def upload_file(self, repo: str, remote_path: str, local_path: str, message: str) -> None:
        self.upload_files(repo, [(remote_path, local_path)], message)

    def upload_files(self, repo: str, files, message: str) -> None:
        """Upload many files as a SINGLE commit (one version in history).

        This is the hot path for backups: instead of the ~7 API round-trips
        that upload_file used to need per file, a whole backup costs
        (blob calls, run in parallel) + one tree + one commit + one ref update.
        """
        files = [(rp, lp) for rp, lp in files if lp is not None]
        if not files:
            return
        for remote_path, local_path in files:
            size = os.path.getsize(local_path)
            if size > 95 * 1024 * 1024:
                raise GitHubError(f"'{remote_path}' is {size // 1048576} MB; "
                                  "GitHub supports up to ~100 MB per file")

        branch = self._default_branch(repo)
        # Blobs are independent of the branch state - upload them once,
        # in parallel, before any commit bookkeeping.
        with ThreadPoolExecutor(max_workers=min(8, len(files))) as pool:
            blob_shas = list(pool.map(lambda f: self._blob_sha(repo, f[1]), files))
        entries = [{"path": remote_path, "mode": "100644", "type": "blob", "sha": sha}
                   for (remote_path, _lp), sha in zip(files, blob_shas)]

        for attempt in range(4):
            try:
                head = self._branch_head(repo, branch)
                if head is None:
                    # Empty repository: create the very first commit and ref.
                    tree = self._request("POST", f"{API}/repos/{repo}/git/trees",
                                         json={"tree": entries}).json()["sha"]
                    commit = self._request("POST", f"{API}/repos/{repo}/git/commits",
                                           json={"message": message, "tree": tree}).json()["sha"]
                    self._request("POST", f"{API}/repos/{repo}/git/refs",
                                  json={"ref": f"refs/heads/{branch}", "sha": commit})
                else:
                    base_commit = self._request(
                        "GET", f"{API}/repos/{repo}/git/commits/{head}").json()
                    tree = self._request("POST", f"{API}/repos/{repo}/git/trees", json={
                        "base_tree": base_commit["tree"]["sha"],
                        "tree": entries}).json()["sha"]
                    commit = self._request("POST", f"{API}/repos/{repo}/git/commits", json={
                        "message": message, "tree": tree, "parents": [head]}).json()["sha"]
                    self._request("PATCH", f"{API}/repos/{repo}/git/refs/heads/{branch}",
                                  json={"sha": commit})
                return
            except GitHubError as e:
                # 409/422 usually means the branch moved (another upload in
                # flight) - retry with a fresh head; blob SHAs stay valid.
                if attempt < 3 and ("409" in str(e) or "422" in str(e)):
                    time.sleep(1 + attempt)
                    continue
                raise
        raise GitHubError("Upload kept conflicting with other uploads; please try again")

    def download_file(self, repo: str, remote_path: str, ref: str, dest_path: str) -> None:
        params = {"ref": ref} if ref else None
        r = self._request("GET", f"{API}/repos/{repo}/contents/"
                                 f"{urllib.parse.quote(remote_path)}",
                          params=params, headers={"Accept": "application/vnd.github.raw"},
                          ok=(200,))
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(r.content)

    def list_versions(self, repo: str, remote_path: str, limit: int = 50) -> list:
        r = self._request("GET", f"{API}/repos/{repo}/commits",
                          params={"path": remote_path, "per_page": min(limit, 100)}, ok=(200,))
        versions = []
        for c in r.json():
            msg = (c.get("commit", {}).get("message") or "").splitlines()[0][:90]
            date = c.get("commit", {}).get("committer", {}).get("date", "")
            versions.append(RemoteVersion(c["sha"], msg, date))
        return versions

    def list_tree(self, repo: str, ref: str, prefix: str = "") -> list:
        commit = self._request("GET", f"{API}/repos/{repo}/commits/{ref}", ok=(200,)).json()
        tree_sha = commit["commit"]["tree"]["sha"]
        tree = self._request("GET", f"{API}/repos/{repo}/git/trees/{tree_sha}",
                             params={"recursive": "1"}, ok=(200,)).json()
        if tree.get("truncated"):
            raise GitHubError("The repository is too large to list; restore not possible")
        prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        return [(e["path"], e.get("size", 0))
                for e in tree.get("tree", [])
                if e.get("type") == "blob" and (not prefix or e["path"].startswith(prefix))]

    def repo_size(self, repo: str):
        """Approximate repo size in bytes (GitHub reports it in KB)."""
        try:
            size_kb = self._request("GET", f"{API}/repos/{repo}").json().get("size", 0)
            return int(size_kb or 0) * 1024
        except Exception:
            return None
