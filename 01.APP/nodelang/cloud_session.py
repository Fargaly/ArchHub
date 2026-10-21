"""The account signed in to the cloud on THIS machine.

Identity is an email account, never a machine. The canonical profile record
locates its OS-protected session. Only the pinned cloud verifies its identity;
local graph requests reuse that bearer-bound proof without waiting on a network.
"""
from __future__ import annotations

import json
import os
import hashlib
import threading
import time
from pathlib import Path

_ACCOUNT_PENDING = object()
_account_verdicts: dict[str, tuple[float, object]] = {}
_account_checks: set[str] = set()
_account_lock = threading.Lock()


def _account_key(held):
    return hashlib.sha256((_pinned_base(held) + "|" + held["token"]).encode()).hexdigest()


def remember_verified_account(held, status, me):
    """Remember only an authenticated /v1/me answer, never editable file identity."""
    email = me.get("email") if isinstance(me, dict) else None
    value = email.strip().casefold() if status == 200 and isinstance(email, str) and "@" in email else None
    with _account_lock:
        now = time.monotonic()
        for key in tuple(_account_verdicts):
            if _account_verdicts[key][0] <= now:
                del _account_verdicts[key]
        answer = value if status in (200, 401, 403) else _ACCOUNT_PENDING
        _account_verdicts[_account_key(held)] = (now + (600 if value else 60), answer)
    return value


def cloud_session_path() -> Path:
    isolated = os.environ.get('ARCHHUB_TEST_STATE_DIR')
    if isolated:
        return Path(isolated).resolve() / 'brain' / 'cloud.json'
    return _roaming_directory() / 'ArchHub' / 'brain' / 'cloud.json'


def _roaming_directory() -> Path:
    """Ask Windows for the user's folder; agent APPDATA overrides are not identity."""
    if os.name != 'nt':
        configured = os.environ.get('APPDATA')
        if not configured:
            raise OSError('the account profile directory is unavailable')
        return Path(configured).resolve()
    import ctypes
    from ctypes import wintypes
    buffer = ctypes.create_unicode_buffer(260)
    locate = ctypes.WinDLL('shell32', use_last_error=True).SHGetFolderPathW
    locate.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR)
    locate.restype = ctypes.c_long
    if locate(None, 0x001a, None, 0, buffer) != 0 or not buffer.value:
        raise OSError('Windows account profile directory lookup failed')
    return Path(buffer.value)


def signed_in_cloud_account(path: Path | None = None, *, fetch=None, pending=None):
    """Resolve the protected bearer at the pin; local metadata is not identity."""
    record = path or cloud_session_path()
    try:
        from .cloud_signin import read_cloud_session
        held = read_cloud_session(record)
    except (OSError, ValueError):
        return None
    token = held.get("token") if isinstance(held, dict) else None
    if not isinstance(token, str) or not token.strip():
        return None
    expires = held.get("expires_at")
    if held.get("refused_at") or (type(expires) in (int, float) and expires <= time.time()):
        return None
    if fetch is not None:
        return remember_verified_account(held, *fetch(_pinned_base(held) + ME_PATH, token))
    key = _account_key(held)
    with _account_lock:
        cached = _account_verdicts.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return pending if cached[1] is _ACCOUNT_PENDING else cached[1]
        if key in _account_checks:
            return pending
        _account_checks.add(key)

    def verify():
        try:
            remember_verified_account(held, *_cloud_get(_pinned_base(held) + ME_PATH, token))
        except Exception:
            remember_verified_account(held, None, None)
        finally:
            with _account_lock:
                _account_checks.discard(key)

    threading.Thread(target=verify, name="archhub-account-check", daemon=True).start()
    return pending


# Where the founder question goes is the ONE cloud pin (cloud_relay's
# pinned_cloud_base): cloud.json is editable, so a base it names off the pin is
# never used. None means "the pin"; only a court sets a loopback stand-in here.
FOUNDER_CHECK_BASES: tuple[str, ...] | None = None
# A route the cloud serves to founder accounts only (founder_cockpit
# require_founder: 200 for a founder's bearer token, 403 for anyone else).
FOUNDER_CHECK_PATH = "/founder/api/system"
ME_PATH = "/v1/me"
_FOUNDER_TTL_SECONDS = 600.0
_founder_verdicts: dict[str, tuple[float, str | None]] = {}


def _cloud_get(url: str, bearer: str, timeout: float = 6.0):
    """(HTTP status, JSON object or None) of a GET with the bearer; (None, None) if unreachable."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + bearer, "Accept": "application/json",
        "User-Agent": "ArchHub-desktop/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            code, raw = int(answer.status), answer.read(65536)
    except urllib.error.HTTPError as refused:
        return int(refused.code), None
    except (OSError, ValueError):
        return None, None
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        body = None
    return code, body if isinstance(body, dict) else None


def _pinned_base(held: dict) -> str:
    """The one cloud host a bearer is sent to, from the one pin.

    cloud_relay.pinned_cloud_base (the sign-in lane's single pin) decides when
    this build carries it; before it lands, only the one default address is
    used -- never a base read from cloud.json.
    """
    value = held.get("cloud_base_url")
    if FOUNDER_CHECK_BASES is not None:  # a court's loopback stand-in
        base = str(value or "").rstrip("/")
        return base if base in FOUNDER_CHECK_BASES else FOUNDER_CHECK_BASES[0]
    from . import cloud_relay
    pin = getattr(cloud_relay, "pinned_cloud_base", None)
    return pin(value) if pin is not None else cloud_relay.DEFAULT_BASE


def signed_in_founder_account(path: Path | None = None, *, fetch=None) -> str | None:
    """The founder account the CLOUD names for this machine's session, else None.

    Nothing written on this disk decides it: cloud.json is editable, so the
    only thing taken from it is the bearer token (and a base URL, honoured only
    when it is one of the pinned cloud hosts). The cloud is asked twice with
    that token: /v1/me says WHICH account the token belongs to -- the email
    returned here is the cloud's, never the file's -- and the founder-only
    route says whether that account is a founder; only its 200 grants the
    tier. A refusal, no session, or an unreachable cloud means no founder.
    Definite answers are remembered in this process only, for ten minutes.
    """
    record = path or cloud_session_path()
    try:
        from .cloud_signin import read_cloud_session
        held = read_cloud_session(record)
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    bearer = str(held.get("token") or "")
    if not bearer:
        return None
    base = _pinned_base(held)
    import hashlib
    import time
    key = hashlib.sha256(("%s|%s" % (base, bearer)).encode("utf-8")).hexdigest()
    now = time.monotonic()
    cached = _founder_verdicts.get(key)
    if cached is not None and now - cached[0] < _FOUNDER_TTL_SECONDS:
        return cached[1]
    get = fetch or _cloud_get
    code, me = get(base + ME_PATH, bearer)
    if code in (401, 403):
        _founder_verdicts[key] = (now, None)
        return None
    email = str((me or {}).get("email") or "").strip().casefold()
    if code != 200 or "@" not in email:
        return None
    verdict, _body = get(base + FOUNDER_CHECK_PATH, bearer)
    if verdict in (200, 401, 403):
        _founder_verdicts[key] = (now, email if verdict == 200 else None)
    return email if verdict == 200 else None


def login_standing(mail: str, stored_tier: str, cloud_founder: str | None) -> tuple[str, bool]:
    """(tier, founder) a sign-in answers with: founder ONLY on the cloud's word.

    A graph can already hold a founder record (an old graph, a copied graph);
    that record never makes a sign-in a founder. Without the cloud's verdict
    for this very account, a stored "founder" tier answers as "free".
    """
    founder = cloud_founder is not None and cloud_founder == str(mail).strip().casefold()
    if founder:
        return "founder", True
    return ("free" if stored_tier == "founder" else stored_tier), False


__all__ = ["cloud_session_path", "login_standing",
           "signed_in_cloud_account", "signed_in_founder_account"]
