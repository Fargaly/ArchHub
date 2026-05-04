"""Secure storage for API keys and small settings.

Tries OS keyring first (Windows Credential Manager / macOS Keychain). Falls
back to an obfuscated file in %LOCALAPPDATA%/ArchHub/secrets.dat if keyring
isn't available.

The fallback is XOR-obfuscated only — it's not strong encryption. For a
production product, swap for a proper encrypted store keyed off a user
master password, or rely entirely on keyring (recommended).
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

SERVICE = "ArchHub"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
SECRETS_FILE = APP_DIR / "secrets.dat"
SETTINGS_FILE = APP_DIR / "settings.json"
APP_DIR.mkdir(parents=True, exist_ok=True)

# Static XOR pad — not security; just keeps the file from being plaintext.
_PAD = b"ArchHub-fallback-not-secure-use-keyring"


def _try_keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


# ---- API keys --------------------------------------------------------------

def save_api_key(provider: str, api_key: str) -> None:
    kr = _try_keyring()
    if kr:
        kr.set_password(SERVICE, provider, api_key)
        return
    _file_save(provider, api_key)


def load_api_key(provider: str) -> str | None:
    kr = _try_keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, provider)
            if v:
                return v
        except Exception:
            pass
    return _file_load(provider)


def delete_api_key(provider: str) -> None:
    kr = _try_keyring()
    if kr:
        try: kr.delete_password(SERVICE, provider)
        except Exception: pass
    _file_delete(provider)


def list_keys() -> list[str]:
    kr = _try_keyring()
    if kr:
        # keyring doesn't enumerate by service portably. We track which
        # providers have ever been saved in settings.json.
        return load_setting("known_providers") or []
    data = _read_file()
    return list(data.keys())


# ---- file fallback --------------------------------------------------------

def _xor(data: bytes) -> bytes:
    return bytes(b ^ _PAD[i % len(_PAD)] for i, b in enumerate(data))


def _read_file() -> dict:
    if not SECRETS_FILE.exists():
        return {}
    try:
        raw = SECRETS_FILE.read_bytes()
        decoded = _xor(base64.b64decode(raw)).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def _write_file(data: dict) -> None:
    raw = json.dumps(data).encode("utf-8")
    SECRETS_FILE.write_bytes(base64.b64encode(_xor(raw)))


def _file_save(provider: str, value: str) -> None:
    data = _read_file()
    data[provider] = value
    _write_file(data)
    # also remember in settings for list_keys()
    known = set(load_setting("known_providers") or [])
    known.add(provider)
    save_setting("known_providers", sorted(known))


def _file_load(provider: str) -> str | None:
    return _read_file().get(provider)


def _file_delete(provider: str) -> None:
    data = _read_file()
    data.pop(provider, None)
    _write_file(data)
    known = set(load_setting("known_providers") or [])
    known.discard(provider)
    save_setting("known_providers", sorted(known))


# ---- non-secret settings --------------------------------------------------

def save_setting(key: str, value) -> None:
    data = _read_settings()
    data[key] = value
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_setting(key: str):
    return _read_settings().get(key)


def _read_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Convenience wrapper used by save_api_key keyring path so list_keys returns
# something on systems with keyring installed.
def _track_provider(provider: str) -> None:
    known = set(load_setting("known_providers") or [])
    if provider not in known:
        known.add(provider)
        save_setting("known_providers", sorted(known))


def save_api_key(provider: str, api_key: str) -> None:    # noqa: F811 — override above
    kr = _try_keyring()
    if kr:
        kr.set_password(SERVICE, provider, api_key)
        _track_provider(provider)
        return
    _file_save(provider, api_key)
