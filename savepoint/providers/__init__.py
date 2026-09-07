"""Provider registry. Add new providers here (one line)."""
from __future__ import annotations

from .base import CloudProvider, RemoteVersion
from .github_provider import GitHubError, GitHubProvider
from .local_folder import LocalFolderProvider

_PROVIDERS = {}


def _register(cls):
    _PROVIDERS[cls.id] = cls()
    return cls


_register(GitHubProvider)
_register(LocalFolderProvider)


def provider_ids() -> list:
    return list(_PROVIDERS.keys())


def display_name(provider_id: str) -> str:
    p = _PROVIDERS.get(provider_id)
    return p.display_name if p else provider_id


def get_provider(provider_id: str) -> CloudProvider:
    if provider_id not in _PROVIDERS:
        raise KeyError(f"Unknown cloud provider: {provider_id}")
    return _PROVIDERS[provider_id]
