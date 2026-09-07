"""Cloud provider abstraction: implement this to add a new backup destination."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import NamedTuple


class RemoteVersion(NamedTuple):
    ref: str      # opaque version id (commit sha / timestamp id)
    label: str    # human-readable description
    date: str     # ISO timestamp


class CloudProvider(ABC):
    """A backup destination (GitHub, local folder, future: Drive, Dropbox...).

    To add a provider: subclass this, give it a unique `id`, implement the
    abstract methods and register it in providers/__init__.py.
    """

    id: str = "abstract"
    display_name: str = "Abstract provider"

    def configure(self, **credentials):
        """Receive provider credentials/settings before each use."""
        self.credentials = credentials

    @abstractmethod
    def test_connection(self, repo: str = "") -> str:
        """Verify credentials/settings; return a short status message."""

    @abstractmethod
    def repo_exists(self, repo: str) -> bool:
        """Does the destination exist / is it usable?"""

    @abstractmethod
    def create_repo(self, repo: str, private: bool = True) -> None:
        """Create a new destination."""

    @abstractmethod
    def upload_file(self, repo: str, remote_path: str, local_path: str, message: str) -> None:
        """Upload one file, creating a new version in the history."""

    def upload_files(self, repo: str, files, message: str) -> None:
        """Upload several files as a single version (one commit / snapshot).

        `files` is an iterable of (remote_path, local_path) pairs. The default
        implementation just calls upload_file per file; providers should
        override it when a destination supports batching (much faster).
        """
        for remote_path, local_path in files:
            self.upload_file(repo, remote_path, local_path, message)

    @abstractmethod
    def download_file(self, repo: str, remote_path: str, ref: str, dest_path: str) -> None:
        """Download `remote_path` as of version `ref` ('' = latest) to dest_path."""

    @abstractmethod
    def list_versions(self, repo: str, remote_path: str, limit: int = 50) -> list:
        """Return [RemoteVersion] for a remote file/folder, newest first."""

    @abstractmethod
    def list_tree(self, repo: str, ref: str, prefix: str = "") -> list:
        """Return [(remote_path, size)] of all files under `prefix` at version `ref`."""

    def prune_versions(self, repo: str, prefix: str, keep: int) -> None:
        """Optional: cap stored versions. Default: keep everything."""
        return None

    def repo_size(self, repo: str):
        """Approximate total size of the destination in bytes (None: unknown).

        Used by the storage report; may hit the network, so callers should
        run it off the UI thread and treat failures as None.
        """
        return None


def account_placeholder() -> str:
    return ""
