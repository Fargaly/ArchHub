"""Secure storage for API keys and small settings."""
from __future__ import annotations
import base64, importlib.util, json, os, tempfile, threading
from pathlib import Path

SERVICE = "ArchHub"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
SECRETS_FILE = APP_DIR / "secrets.dat"
SETTINGS_FILE = APP_DIR / "settings.json"
# Serialize this application's read-modify-write operations. Atomic replacement
# protects file contents, but alone cannot prevent two callbacks losing updates.
# Writers of secrets.dat also hold its cross-process named mutex
# (credential_lock.py beside this file) and refuse an observed outside change.
_SAVE_LOCK = threading.RLock()
_UNCHECKED = object()
_CREDENTIAL_LOCK_MODULE = None
# Legacy pad: only ever used to READ a file written before the DPAPI
# migration below; nothing is written with it any more.
_PAD = b"ArchHub-fallback-not-secure-use-keyring"
_DPAPI_MARK = b"ARCHHUB-DPAPI-1:"
_DPAPI_ENTROPY = b"ArchHub secrets.dat"
# Courts set ARCHHUB_TEST_SECRET_STORE=memory (tests_replica/conftest.py). That
# process, any copy of this file it loads by path, and every child it starts keep
# keys in this dict and never reach keyring, secrets.dat, an alias resolver or
# settings.json's provider index.
TEST_STORE_ENV = "ARCHHUB_TEST_SECRET_STORE"
_MEMORY_KEYS: dict = {}


def os_store_refused() -> bool:
    """True when this process must keep keys in memory, never in the OS store.

    Only a court may ask for that: pytest sets PYTEST_VERSION for its process
    and the children it starts. The variable anywhere else is refused, so a
    stray setting can never switch a real install to keys that vanish.
    """
    if os.environ.get(TEST_STORE_ENV) != "memory":
        return False
    if not os.environ.get("PYTEST_VERSION"):
        raise RuntimeError("ARCHHUB_TEST_SECRET_STORE=memory is for courts only; unset it")
    return True


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Windows DPAPI bound to the current user; the OS holds the key."""
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(raw: bytes) -> _Blob:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return _Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    inp, ent, out = _blob(data), _blob(_DPAPI_ENTROPY), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI refused (%s)" % ("protect" if protect else "unprotect"))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)

def _try_keyring():
    try:
        import keyring; return keyring
    except Exception:
        return None

def _xor(data: bytes) -> bytes:
    return bytes(b ^ _PAD[i % len(_PAD)] for i, b in enumerate(data))

def _read_file_state() -> tuple[bytes | None, dict]:
    """The exact bytes read and their entries; (None, {}) when no store exists."""
    if not SECRETS_FILE.exists(): return None, {}
    try:
        raw = SECRETS_FILE.read_bytes()
        if raw.startswith(_DPAPI_MARK):
            data = json.loads(_dpapi(base64.b64decode(raw[len(_DPAPI_MARK):], validate=True), protect=False).decode("utf-8"))
        else:
            # Pre-migration file: rewritten protected only after a successful read.
            data = json.loads(_xor(base64.b64decode(raw, validate=True)).decode("utf-8"))
        if type(data) is not dict:
            raise ValueError("invalid credential entries")
        return raw, data
    except Exception:
        # An unreadable existing store is not an empty store. Refuse saves and
        # deletes instead of replacing other providers' protected credentials.
        raise OSError("protected credential store is unreadable") from None


def _read_file() -> dict:
    return _read_file_state()[1]

def _replace_bytes(path: Path, payload: bytes, expected=_UNCHECKED) -> None:
    """Flush a sibling file before replacement; never truncate the saved value.

    With expected bytes (None when no file was read), replacement is refused if
    the file changed since that read; the other writer's file is left intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not _UNCHECKED and (path.read_bytes() if path.exists() else None) != expected:
            raise OSError("protected credential store changed; it was not replaced")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _write_file(data: dict, expected=_UNCHECKED) -> None:
    """Written with the user's DPAPI key; the hardcoded pad is never written again."""
    if os.name != "nt":
        raise OSError("the file fallback protects secrets with Windows DPAPI only; use keyring")
    payload = _DPAPI_MARK + base64.b64encode(_dpapi(json.dumps(data).encode("utf-8"), protect=True))
    _replace_bytes(SECRETS_FILE, payload, expected)

def _read_settings() -> dict:
    if not SETTINGS_FILE.exists(): return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if type(data) is not dict:
            raise ValueError("invalid settings entries")
        return data
    except (OSError, ValueError):
        raise OSError("saved settings are unreadable; existing file preserved") from None

def save_setting(key: str, value) -> None:
    with _SAVE_LOCK:
        data = _read_settings(); data[key] = value
        _replace_bytes(SETTINGS_FILE, json.dumps(data, indent=2).encode("utf-8"))

def load_setting(key: str):
    return _read_settings().get(key)


def _updated_provider_index(provider: str, *, remove=False) -> list[str]:
    if type(provider) is not str or not provider:
        raise ValueError("provider name must be a nonempty string")
    saved = load_setting("known_providers")
    if saved is None:
        saved = []
    if type(saved) is not list or any(type(item) is not str or not item for item in saved):
        raise OSError("saved provider index is unreadable; existing credentials preserved")
    known = set(saved)
    if remove:
        known.discard(provider)
    else:
        known.add(provider)
    return sorted(known)


def _track_provider(provider: str) -> None:
    with _SAVE_LOCK:
        save_setting("known_providers", _updated_provider_index(provider))

def _exclusive_secrets_file():
    """Cross-process exclusion for secrets.dat through credential_lock.py beside this file."""
    global _CREDENTIAL_LOCK_MODULE
    with _SAVE_LOCK:
        if _CREDENTIAL_LOCK_MODULE is None:
            spec = importlib.util.spec_from_file_location(
                "_archhub_credential_lock", Path(__file__).resolve().with_name("credential_lock.py"))
            if spec is None or spec.loader is None:
                raise OSError("credential file lock is unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _CREDENTIAL_LOCK_MODULE = module
    return _CREDENTIAL_LOCK_MODULE.exclusive(SECRETS_FILE)

def _file_save(provider: str, value: str) -> None:
    with _SAVE_LOCK, _exclusive_secrets_file():
        raw, data = _read_file_state()
        known = _updated_provider_index(provider)
        data[provider] = value; _write_file(data, expected=raw)
        save_setting("known_providers", known)

def _file_load(provider: str) -> str | None:
    return _read_file().get(provider)

def _file_delete(provider: str) -> None:
    with _SAVE_LOCK, _exclusive_secrets_file():
        raw, data = _read_file_state()
        known = _updated_provider_index(provider, remove=True)
        data.pop(provider, None); _write_file(data, expected=raw)
        save_setting("known_providers", known)

def save_api_key(provider: str, api_key: str) -> None:
    if isinstance(provider, str) and provider.startswith("social-"):
        raise ValueError("Social credentials require account enrollment")
    if os_store_refused():
        _MEMORY_KEYS[provider] = api_key
        return
    with _SAVE_LOCK:
        known = _updated_provider_index(provider)
        kr = _try_keyring()
        if kr:
            kr.set_password(SERVICE, provider, api_key)
            save_setting("known_providers", known)
            return
        _file_save(provider, api_key)

_ENV_VAR_MAP = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai":    ["OPENAI_API_KEY"],
    "google":    ["GOOGLE_API_KEY", "GOOGLE_GENERATIVEAI_API_KEY"],
}

# Per-call breadcrumb showing where the last loaded key came from.
# Read by Settings → Secrets UI (agent-3-owned) to render the source row.
# Shape: {"source": "alias|keyring|file|env|none", "resolver": str|None,
#         "last4": str|None}
provider_meta: dict = {}


def _set_meta(provider: str, source: str, resolver: str | None,
              value: str | None) -> None:
    global provider_meta
    last4 = None
    if value:
        last4 = ("..." + value[-4:]) if len(value) >= 4 else ("..." + value)
    provider_meta = {
        "provider": provider,
        "source": source,
        "resolver": resolver,
        "last4": last4,
    }


def load_api_key(provider: str) -> str | None:
    if isinstance(provider, str) and provider.startswith("social-"):
        _set_meta(provider, source="none", resolver=None, value=None)
        return None
    if os_store_refused():
        value = _MEMORY_KEYS.get(provider)
        _set_meta(provider, source="memory" if value else "none", resolver=None, value=value)
        return value
    # 1. ResolverRegistry alias path (op://, wcm://, env://, file://, inline:)
    #    — refs only, never plain values. Per BRAIN-FIRST mandate.
    try:
        from resolver_registry import ResolverRegistry  # local import to dodge cycle
        reg = ResolverRegistry()
        result = reg.resolve_alias(provider)
        if "value" in result:
            _set_meta(provider, source="alias",
                      resolver=result.get("resolver"),
                      value=result["value"])
            return result["value"]
    except Exception:
        # Registry missing or import error — fall through to legacy.
        pass

    # 2. Legacy keyring / obfuscated file (user-entered via Settings)
    kr = _try_keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, provider)
            if v:
                _set_meta(provider, source="keyring", resolver=None, value=v)
                return v
        except Exception:
            pass
    stored = _file_load(provider)
    if stored:
        _set_meta(provider, source="file", resolver=None, value=stored)
        return stored

    # 3. Environment-variable fallback (auto-detected, no Settings needed)
    for env_name in _ENV_VAR_MAP.get(provider, []):
        v = os.environ.get(env_name)
        if v:
            _set_meta(provider, source="env", resolver=env_name, value=v)
            return v

    _set_meta(provider, source="none", resolver=None, value=None)
    return None

def delete_api_key(provider: str) -> None:
    if isinstance(provider, str) and provider.startswith("social-"):
        raise ValueError("Social credentials require account revocation")
    if os_store_refused():
        _MEMORY_KEYS.pop(provider, None)
        return
    with _SAVE_LOCK:
        _updated_provider_index(provider, remove=True)
        # Refuse known damaged local state before touching another store.
        _read_file()
        kr = _try_keyring()
        if kr:
            try:
                if kr.get_password(SERVICE, provider) is not None:
                    kr.delete_password(SERVICE, provider)
            except Exception:
                raise OSError("credential deletion failed; saved provider entry retained") from None
        _file_delete(provider)

def list_keys() -> list[str]:
    if os_store_refused():
        return [name for name in _MEMORY_KEYS if not name.startswith("social-")]
    kr = _try_keyring()
    names = (load_setting("known_providers") or []) if kr else _read_file().keys()
    return [name for name in names if isinstance(name, str) and not name.startswith("social-")]
