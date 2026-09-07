"""Secure credential storage.

Uses the OS keyring (Windows Credential Manager) via the `keyring` package.
If `keyring` is unavailable on Windows, falls back to DPAPI-encrypted blobs,
which are bound to the current user account.
"""
from __future__ import annotations

import base64
import json
import os

SERVICE = "SavePoint"
_LEGACY_SERVICE = "CloudSaveGuard"  # credential service name before the rename

try:
    import keyring  # noqa: F401
    _KEYRING = True
except Exception:
    _KEYRING = False


# ----------------------------------------------------------------------
# DPAPI fallback (Windows only, no external dependencies)
# ----------------------------------------------------------------------
if os.name == "nt":
    import ctypes
    import ctypes.wintypes as wt

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _make_blob(data: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _protect_raw(data: bytes) -> bytes:
        pin, pout = _make_blob(data), _BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(pin), None, None, None, None, 0, ctypes.byref(pout)):
            raise OSError("DPAPI encryption failed")
        try:
            return ctypes.string_at(pout.pbData, pout.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(pout.pbData)

    def _unprotect_raw(data: bytes) -> bytes:
        pin, pout = _make_blob(data), _BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(pin), None, None, None, None, 0, ctypes.byref(pout)):
            raise OSError("DPAPI decryption failed")
        try:
            return ctypes.string_at(pout.pbData, pout.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(pout.pbData)


def _fallback_file() -> str:
    from .config import app_dir
    return os.path.join(app_dir(), "secrets.bin")


def _fallback_load() -> dict:
    try:
        with open(_fallback_file(), encoding="utf-8") as f:
            encrypted = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in encrypted.items():
        try:
            out[k] = _unprotect_raw(base64.b64decode(v)).decode("utf-8")
        except Exception:
            continue
    return out


def _fallback_store(store: dict):
    encrypted = {k: base64.b64encode(_protect_raw(v.encode("utf-8"))).decode()
                 for k, v in store.items()}
    tmp = _fallback_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(encrypted, f)
    os.replace(tmp, _fallback_file())


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def set_secret(name: str, value: str):
    if not value:
        delete_secret(name)
        return
    if _KEYRING:
        keyring.set_password(SERVICE, name, value)
    elif os.name == "nt":
        store = _fallback_load()
        store[name] = value
        _fallback_store(store)
    else:
        raise RuntimeError("No secure storage available - install the 'keyring' package")


def get_secret(name: str):
    if _KEYRING:
        try:
            value = keyring.get_password(SERVICE, name)
        except Exception:
            return None
        if value is None:
            # Migrate credentials stored under the pre-rename service name.
            try:
                legacy = keyring.get_password(_LEGACY_SERVICE, name)
            except Exception:
                legacy = None
            if legacy is not None:
                try:
                    keyring.set_password(SERVICE, name, legacy)
                    keyring.delete_password(_LEGACY_SERVICE, name)
                except Exception:
                    pass
                value = legacy
        return value
    if os.name == "nt":
        return _fallback_load().get(name)
    return None


def delete_secret(name: str):
    if _KEYRING:
        try:
            keyring.delete_password(SERVICE, name)
        except Exception:
            pass
    if os.name == "nt" and os.path.isfile(_fallback_file()):
        store = _fallback_load()
        if name in store:
            del store[name]
            _fallback_store(store)
