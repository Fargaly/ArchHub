"""The account signed in to the cloud on THIS machine.

Identity is an email account, never a machine. The canonical profile record
locates its OS-protected session. Only the pinned cloud verifies its identity;
local graph requests reuse that bearer-bound proof without waiting on a network.
"""
from __future__ import annotations

from .user_paths import state_directory

from concurrent.futures import Future
import json
import os
import hashlib
import hmac
import threading
import time
import urllib.request
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
    if isolated is not None:
        return state_directory().resolve() / 'brain' / 'cloud.json'
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


class _NoCloudRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def open_cloud_request(request, *, timeout):
    """A pinned cloud request never carries credentials through a redirect."""
    return urllib.request.build_opener(_NoCloudRedirect()).open(request, timeout=timeout)


def _cloud_get(url: str, bearer: str, timeout: float = 6.0):
    """(HTTP status, JSON object or None) of a GET with the bearer; (None, None) if unreachable."""
    import urllib.error
    request = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + bearer, "Accept": "application/json",
        "User-Agent": "ArchHub-desktop/2.0", "Cache-Control": "no-cache, no-store"})
    try:
        with open_cloud_request(request, timeout=timeout) as answer:
            code, raw = int(answer.status), answer.read(65537)
        if len(raw) > 65536:
            return code, None
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


_DESKTOP_ERRORS = {
    "signed_out": "Sign in to ArchHub to continue.",
    "session_invalid": "This ArchHub session cannot be used. Sign in again with the active account.",
    "unavailable": "ArchHub could not verify your account online. Check the connection and retry.",
}


class DesktopAccessRefused(PermissionError):
    code = "desktop_access_required"

    def __init__(self, state):
        super().__init__(_DESKTOP_ERRORS[state])
        self.state = state
        self.status = 503 if state == "unavailable" else 401


class _ResumeSigner:
    def __init__(self, key, base, subject, bearer):
        self._key, self._base, self._subject, self._bearer = key, base, subject, bearer

    def __call__(self, identity, path):
        payload = json.dumps([self._base, self._subject, identity, path], ensure_ascii=False, separators=(",", ":"))
        return "v2:" + hmac.digest(self._key, b"ArchHub desktop resume v2\0" + payload.encode(), "sha256").hex()

    def verify_legacy(self, identity, path, signature):
        payload = json.dumps([self._subject, identity, path], ensure_ascii=False, separators=(",", ":"))
        digest = hmac.digest(self._bearer.encode(), b"ArchHub desktop resume v1\0" + payload.encode(), "sha256").hex()
        return hmac.compare_digest(signature, digest)


class DesktopAccess:
    """Admit work using a fresh server verdict for the current protected account."""

    def __init__(self, path=None, *, fetch=None, clock=time.monotonic, offline_grace=300.0):
        # A network blip must not lock the founder out mid-work (2026-11-25): an unanswered check reuses the same
        # token's last verified answer for offline_grace seconds; 401/403 still locks at once.
        self._path = path
        self._fetch = fetch
        self._clock = clock
        self._grace = offline_grace
        self._in_flight = {}
        self._verified = {}  # key -> (when, account) of the last 200 answer for that base and token
        self._lock = threading.Lock()

    @staticmethod
    def _verdict(state, subject=None, email=None):
        return {"ok": True, "admitted": state == "admitted", "state": state,
                "subject": subject, "email": email}

    @staticmethod
    def _usable(held):
        expires = held.get("expires_at")
        return not held.get("refused_at") and (
            expires is None or type(expires) in (int, float) and expires > time.time())

    def _verify(self, base, bearer):
        key = hashlib.sha256((base + "|" + bearer).encode()).digest()
        with self._lock:
            pending = self._in_flight.get(key)
            leader = pending is None
            if leader:
                pending = self._in_flight[key] = Future()
        if not leader:
            return pending.result()
        try:
            result = (self._fetch or _cloud_get)(base + ME_PATH, bearer)
        except Exception:
            result = None, None  # private transport details never enter a refusal
        finally:
            with self._lock:
                self._in_flight.pop(key, None)
        now = self._clock()
        with self._lock:
            if result[0] == 200:
                self._verified = {key: (now, result[1])}  # one account at a time; a new token drops the old one
            elif result[0] not in (401, 403) and key in self._verified and now - self._verified[key][0] <= self._grace:
                result = 200, self._verified[key][1]
            elif result[0] in (401, 403):
                self._verified.pop(key, None)
        pending.set_result(result)
        return result

    def check(self, *, expected_bearer=None, bind_resume=False):
        from .cloud_signin import desktop_resume_key, read_cloud_session

        try:
            path = self._path or cloud_session_path()
            held = read_cloud_session(path)
            bearer = held.get("token")
            if not isinstance(bearer, str) or not bearer:
                return self._verdict("signed_out")
            if not self._usable(held) or (expected_bearer is not None and bearer != expected_bearer):
                return self._verdict("session_invalid")
            base = _pinned_base(held)
            code, account = self._verify(base, bearer)
            if code in (401, 403):
                return self._verdict("session_invalid")
            if code != 200 or not isinstance(account, dict):
                return self._verdict("unavailable")
            subject, email = account.get("user_id"), account.get("email")
            if (type(subject) not in (int, str) or not 0 < len(str(subject).strip()) <= 128
                    or not isinstance(email, str) or "@" not in email or len(email) > 320):
                return self._verdict("unavailable")
            subject, email = str(subject).strip(), email.strip().casefold()
            key = desktop_resume_key(path) if bind_resume else None
            # Signout/rotation during the network call invalidates that response.
            current = read_cloud_session(path)
            if current.get("token") != bearer or not self._usable(current) or _pinned_base(current) != base:
                return self._verdict("session_invalid")
        except (OSError, ValueError, TypeError):
            return self._verdict("unavailable")

        verdict = self._verdict("admitted", subject, email)
        if key is not None:
            verdict["_sign_resume_pointer"] = _ResumeSigner(key, base, subject, bearer)
        return verdict

    def require(self, *, subject=None, expected_bearer=None):
        result = self.check(expected_bearer=expected_bearer)
        if not result["admitted"]:
            raise DesktopAccessRefused(result["state"])
        if subject is not None and subject != result["subject"]:
            raise DesktopAccessRefused("session_invalid")
        return result


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
