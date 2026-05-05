"""Secure storage for API keys and small settings."""
from __future__ import annotations
import base64, json, os
from pathlib import Path

SERVICE = "ArchHub"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
SECRETS_FILE = APP_DIR / "secrets.dat"
SETTINGS_FILE = APP_DIR / "settings.json"
APP_DIR.mkdir(parents=True, exist_ok=True)
_PAD = b"ArchHub-fallback-not-secure-use-keyring"

def _try_keyring():
    try:
        import keyring; return keyring
    except Exception:
        return None

def _xor(data: bytes) -> bytes:
    return bytes(b ^ _PAD[i % len(_PAD)] for i, b in enumerate(data))

def _read_file() -> dict:
    if not SECRETS_FILE.exists(): return {}
    try:
        return json.loads(_xor(base64.b64decode(SECRETS_FILE.read_bytes())).decode("utf-8"))
    except Exception:
        return {}

def _write_file(data: dict) -> None:
    SECRETS_FILE.write_bytes(base64.b64encode(_xor(json.dumps(data).encode("utf-8"))))

def _read_settings() -> dict:
    if not SETTINGS_FILE.exists(): return {}
    try: return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception: return {}

def save_setting(key: str, value) -> None:
    data = _read_settings(); data[key] = value
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_setting(key: str):
    return _read_settings().get(key)

def _track_provider(provider: str) -> None:
    known = set(load_setting("known_providers") or [])
    if provider not in known:
        known.add(provider); save_setting("known_providers", sorted(known))

def _file_save(provider: str, value: str) -> None:
    data = _read_file(); data[provider] = value; _write_file(data)
    known = set(load_setting("known_providers") or [])
    known.add(provider); save_setting("known_providers", sorted(known))

def _file_load(provider: str) -> str | None:
    return _read_file().get(provider)

def _file_delete(provider: str) -> None:
    data = _read_file(); data.pop(provider, None); _write_file(data)
    known = set(load_setting("known_providers") or [])
    known.discard(provider); save_setting("known_providers", sorted(known))

def save_api_key(provider: str, api_key: str) -> None:
    kr = _try_keyring()
    if kr: kr.set_password(SERVICE, provider, api_key); _track_provider(provider); return
    _file_save(provider, api_key)

_ENV_VAR_MAP = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai":    ["OPENAI_API_KEY"],
    "google":    ["GOOGLE_API_KEY", "GOOGLE_GENERATIVEAI_API_KEY"],
}

def load_api_key(provider: str) -> str | None:
    # 1. Keyring / obfuscated file (user-entered via Settings)
    kr = _try_keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, provider)
            if v: return v
        except Exception: pass
    stored = _file_load(provider)
    if stored:
        return stored
    # 2. Environment-variable fallback (auto-detected, no Settings entry needed)
    for env_name in _ENV_VAR_MAP.get(provider, []):
        v = os.environ.get(env_name)
        if v:
            return v
    return None

def delete_api_key(provider: str) -> None:
    kr = _try_keyring()
    if kr:
        try: kr.delete_password(SERVICE, provider)
        except Exception: pass
    _file_delete(provider)

def list_keys() -> list[str]:
    kr = _try_keyring()
    if kr: return load_setting("known_providers") or []
    return list(_read_file().keys())
