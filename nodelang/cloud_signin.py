"""Sign in to the cloud from the desktop: email account, never a machine.

The app opens the founder's browser on the cloud's own sign-in (a magic link
to the email, or Google), the cloud sends a one-time code back to a loopback
server this module holds for that one attempt, the code is exchanged for a
bearer token with PKCE (RFC 7636), and the session lands in
%APPDATA%/ArchHub/brain/cloud.json - the one record the relay, the brain's
cloud sync and the local account routes already trust. Same dance as the
shipped desktop client of 2026-05 (app/cloud_auth.py), with nothing typed
into a box standing in for an identity.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from .cloud_relay import DEFAULT_BASE, SIGN_IN_AGAIN as _SIGN_IN_AGAIN, pinned_cloud_base

WAIT_SECONDS = 300.0
METHODS = ("google", "magic")
_DONE_PAGE = (
    "<h1>You are signed in</h1>"
    "<p>You can close this tab and return to ArchHub.</p>"
    "<style>body{font-family:system-ui;padding:60px;max-width:520px;"
    "margin:0 auto;color:#251f17;}h1{font-style:italic;letter-spacing:-0.02em;}"
    "</style>"
)


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) per RFC 7636, S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cloud_session_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "ArchHub" / "brain" / "cloud.json"


def read_cloud_session(path: Path) -> dict:
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def write_cloud_session(path: Path, patch: dict) -> dict:
    """Merge patch into cloud.json atomically; keys set to None are dropped."""
    held = read_cloud_session(path)
    for key, value in patch.items():
        if value is None:
            held.pop(key, None)
        else:
            held[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(path.parent),
        prefix=path.name + ".", suffix=".tmp",
    ) as handle:
        json.dump(held, handle, indent=2, sort_keys=True)
        tmp = handle.name
    os.replace(tmp, path)
    return held


def http_json(method: str, url: str, *, body: Optional[dict] = None,
              headers: Optional[dict] = None, timeout: float = 15.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    sent = {"Accept": "application/json", "User-Agent": "ArchHub-desktop/2.0"}
    if data is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=sent, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as failed:
        raw = failed.read()
        status = failed.code
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


class _Callback(BaseHTTPRequestHandler):
    """One-shot loopback: the cloud lands ?code&state here after consent."""

    server_version = "ArchHub-callback/2.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - silence
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        expected = getattr(self.server, "expected_state", "")
        # The cloud echoes the desktop's state on the Google path, but its
        # mailed link carries none and /auth/return forwards the fixed
        # marker "archhub" (cloud_backend/main.py, fwd_state). The magic path
        # accepts that marker: the one-time code is still bound to this
        # attempt's PKCE verifier, so a code landed here by anyone else
        # cannot be exchanged.
        marker_ok = getattr(self.server, "accepts_marker", False) and state == "archhub"
        if state != expected and not marker_ok:
            self._html(400, "<h1>Sign-in failed</h1><p>Security state mismatch. Retry from ArchHub.</p>")
            return
        if not code:
            self._html(400, "<h1>Sign-in failed</h1><p>No code returned. Retry from ArchHub.</p>")
            return
        self.server.received_code = code
        self._html(200, _DONE_PAGE)

    def _html(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class SignIn:
    """One sign-in attempt; status() is what the studio polls."""

    def __init__(self, method: str, *, base_url: str = "", path: Optional[Path] = None,
                 opener: Callable[[str], object] | None = None,
                 http: Callable[..., tuple[int, dict]] = http_json,
                 wait_seconds: float = WAIT_SECONDS) -> None:
        if method not in METHODS:
            raise ValueError("sign-in method must be one of " + ", ".join(METHODS))
        self.method = method
        self.base_url = pinned_cloud_base(base_url or DEFAULT_BASE)
        self.path = path or cloud_session_path()
        self._opener = opener
        self._http = http
        self._wait = wait_seconds
        self._cancel = False
        self._lock = threading.Lock()
        self._state = {"phase": "starting", "method": method, "email": "", "error": "", "url": ""}
        self.thread: Optional[threading.Thread] = None

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    @property
    def active(self) -> bool:
        return self.status()["phase"] in ("starting", "waiting", "exchanging")

    def cancel(self) -> None:
        self._cancel = True

    def start(self) -> "SignIn":
        self.thread = threading.Thread(target=self._run, name="archhub-cloud-signin", daemon=True)
        self.thread.start()
        return self

    def _set(self, **patch) -> None:
        with self._lock:
            self._state.update(patch)

    def auth_url(self, *, challenge: str, state: str, redirect: str) -> str:
        if self.method == "magic":
            query = urlencode({"challenge": challenge, "state": state,
                               "redirect": redirect, "client": "desktop"})
            return f"{self.base_url}/signin?{query}"
        query = urlencode({"code_challenge": challenge, "redirect": redirect,
                           "state": state, "client": "desktop"})
        status, payload = self._http("GET", f"{self.base_url}/v1/auth/google/start?{query}")
        url = str(payload.get("auth_url") or "")
        if status != 200 or not url:
            raise RuntimeError(str(payload.get("detail") or payload.get("error")
                                   or f"google sign-in unavailable ({status})"))
        return url

    def _run(self) -> None:
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(16)
        try:
            server = HTTPServer(("127.0.0.1", free_port()), _Callback)
        except OSError as failed:
            self._set(phase="failed", error=f"no loopback port: {failed}")
            return
        server.expected_state = state
        server.accepts_marker = self.method == "magic"
        server.received_code = None
        server.timeout = 0.5
        redirect = f"http://127.0.0.1:{server.server_port}/cb"
        try:
            url = self.auth_url(challenge=challenge, state=state, redirect=redirect)
        except Exception as failed:
            server.server_close()
            self._set(phase="failed", error=str(failed)[:200] or "sign-in could not start")
            return
        self._set(phase="waiting", url=url)
        opener = self._opener
        if opener is None:
            import webbrowser
            opener = webbrowser.open

        def _open() -> None:
            # On its own thread: the browser (or a court standing in for it)
            # may call the loopback before this thread is back in the loop.
            try:
                opener(url)
            except Exception as failed:
                self._set(phase="failed", error=f"browser did not open: {failed}"[:200])
                self._cancel = True

        threading.Thread(target=_open, name="archhub-cloud-signin-browser", daemon=True).start()
        started = time.monotonic()
        while not server.received_code:
            if self._cancel:
                server.server_close()
                if self.status()["phase"] != "failed":
                    self._set(phase="failed", error="cancelled")
                return
            if time.monotonic() - started > self._wait:
                server.server_close()
                self._set(phase="failed", error="timed out waiting for the browser")
                return
            try:
                server.handle_request()
            except Exception:
                continue
        code = str(server.received_code)
        server.server_close()
        self._set(phase="exchanging")
        try:
            status, payload = self._http(
                "POST", f"{self.base_url}/v1/auth/exchange",
                body={"code": code, "code_verifier": verifier})
        except Exception as unreachable:
            self._set(phase="failed", error=("the cloud did not answer the exchange: %s" % unreachable)[:200])
            return
        token = str(payload.get("token") or "")
        if status != 200 or not token:
            self._set(phase="failed", error=str(payload.get("error") or payload.get("detail")
                                                or f"exchange refused ({status})")[:200])
            return
        try:
            _status, me = self._http("GET", f"{self.base_url}/v1/me",
                                     headers={"Authorization": f"Bearer {token}"})
        except Exception:
            me = {}
        email = str(me.get("email") or payload.get("email") or "").strip().casefold()
        if "@" not in email:
            self._set(phase="failed", error="the cloud did not name the account")
            return
        write_cloud_session(self.path, {
            "token": token,
            "expires_at": payload.get("expires_at"),
            "email": email,
            "user_id": me.get("user_id") or payload.get("user_id"),
            "cloud_base_url": self.base_url,
            "refused_at": None,
        })
        self._set(phase="done", email=email)


_IDLE = {"phase": "idle", "method": "", "email": "", "error": "", "url": ""}
_CURRENT: dict = {"attempt": None}


def current_status() -> dict:
    """The attempt the studio is polling, or idle."""
    attempt = _CURRENT.get("attempt")
    return attempt.status() if attempt is not None else dict(_IDLE)


def begin(method: str, **options) -> dict:
    """Start one attempt; a second click while one waits joins it."""
    attempt = _CURRENT.get("attempt")
    if attempt is not None and attempt.active:
        return attempt.status()
    attempt = SignIn(method, **options).start()
    _CURRENT["attempt"] = attempt
    return attempt.status()


def sign_out(path: Optional[Path] = None, *, http: Callable[..., tuple[int, dict]] = http_json,
             wait: bool = False) -> dict:
    """Forget the session on this machine now; tell the cloud on its own thread.

    The app serves this under its one mutation lock; a 5 s cloud call held
    every canvas request behind it (audit 2026-09-06). The file is cleared
    before this returns; the cloud is told best-effort, off the caller's
    thread unless `wait` asks for it (courts do)."""
    record = path or cloud_session_path()
    held = read_cloud_session(record)
    token = str(held.get("token") or "")
    base = pinned_base(held)
    if token:
        def _tell_cloud() -> None:
            try:
                http("POST", f"{base}/v1/auth/logout", body={},
                     headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
            except Exception:
                pass
        if wait:
            _tell_cloud()
        else:
            threading.Thread(target=_tell_cloud, name="archhub-cloud-signout", daemon=True).start()
    if held:
        write_cloud_session(record, {"token": None, "expires_at": None,
                                     "email": None, "user_id": None, "refused_at": None})
    attempt = _CURRENT.get("attempt")
    if attempt is not None and not attempt.active:
        _CURRENT["attempt"] = None
    return {"signed_in": False, "email": ""}


def pinned_base(held: dict) -> str:
    """The pinned cloud base for a session record (cloud_relay.pinned_cloud_base)."""
    return pinned_cloud_base(held.get("cloud_base_url"))


# Whether the account owns the cockpit: only a live cloud answer, held in this
# process for ten minutes, never read from or written to cloud.json.
_FOUNDER_SECONDS = 600.0
_FOUNDER: dict = {}


def _founder_key(held: dict) -> str:
    return hashlib.sha256(("%s|%s|%s" % (
        pinned_base(held), str(held.get("email") or "").strip().casefold(),
        _held_bearer(held))).encode("utf-8")).hexdigest()


def _founder_cached(held: dict) -> Optional[bool]:
    seen = _FOUNDER.get(_founder_key(held))
    if seen is None or time.monotonic() - seen[0] >= _FOUNDER_SECONDS:
        return None
    return seen[1]


def _remember_founder(held: dict, owns: bool) -> None:
    _FOUNDER[_founder_key(held)] = (time.monotonic(), bool(owns))


# How long a probe answer for a record with no expiry date is trusted.
_PROBE_SECONDS = 600.0
_PROBED: dict = {}


def _held_bearer(held: dict) -> str:
    return str(held.get("token") or "")


def record_refusal(path: Optional[Path], refused_bearer: str, *,
                   now: Optional[float] = None) -> None:
    """The cloud refused this bearer as a session (401): mark the record expired.

    Only the bearer that was refused is marked; a record already carrying a
    newer sign-in is left alone. Sign-in clears the mark."""
    record = path or cloud_session_path()
    held = read_cloud_session(record)
    if refused_bearer and _held_bearer(held) == refused_bearer:
        write_cloud_session(record, {"refused_at": int(now if now is not None else time.time())})


def sign_in_state(path: Optional[Path] = None, *, now: Optional[float] = None) -> dict:
    """What the one session record on this machine says, without the network.

    signed_in: a bearer, an email and an expiry still ahead (or none recorded).
    expired:   the expiry passed, or the cloud refused this bearer.
    signed_out: no usable record."""
    record = path or cloud_session_path()
    held = read_cloud_session(record)
    email = str(held.get("email") or "").strip().casefold()
    if not _held_bearer(held) or "@" not in email:
        return {"state": "signed_out", "signed_in": False, "email": "", "expires_at": None,
                "founder": False}
    moment = time.time() if now is None else now
    expires = held.get("expires_at")
    expires = int(expires) if isinstance(expires, (int, float)) and not isinstance(expires, bool) else None
    lapsed = (expires is not None and expires <= moment) or bool(held.get("refused_at"))
    return {"state": "expired" if lapsed else "signed_in", "signed_in": not lapsed,
            "email": email, "expires_at": expires, "founder": _founder_cached(held) is True}


def _session_invalid(status: int, payload: object) -> bool:
    """Only a refused SESSION lapses the record: 401, or a 403 that says the
    session is invalid. The cockpit's 403 founder_only is about the account,
    never the session, and leaves the record alone."""
    if status == 401:
        return True
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return status == 403 and detail not in ("founder_only",)


def confirm_with_cloud(path: Optional[Path], *, now: Optional[float] = None,
                       http: Optional[Callable[..., tuple[int, dict]]] = None) -> Optional[str]:
    """Ask GET /v1/me what this session is: "expired", "signed_in", or None
    when the cloud did not answer. A live answer also records whether the
    account owns the cockpit."""
    record = path or cloud_session_path()
    held = read_cloud_session(record)
    bearer = _held_bearer(held)
    if not bearer:
        return None
    base = pinned_base(held)
    try:
        status, me = (http or http_json)(
            "GET", f"{base}/v1/me", headers={"Authorization": f"Bearer {bearer}"}, timeout=5.0)
    except Exception:
        return None
    if _session_invalid(status, me):
        record_refusal(record, bearer, now=now)
        return "expired"
    if status == 200:
        owns = me.get("founder")
        if not isinstance(owns, bool):
            # A cloud without the /v1/me field: its founder-only route decides.
            try:
                code, _ignored = (http or http_json)(
                    "GET", f"{base}/founder/api/system",
                    headers={"Authorization": f"Bearer {bearer}"}, timeout=5.0)
            except Exception:
                code = None
            owns = True if code == 200 else False if code == 403 else None
        if isinstance(owns, bool):
            _remember_founder(held, owns)
        return "signed_in"
    return None


def session_summary(path: Optional[Path] = None, *, now: Optional[float] = None,
                    http: Optional[Callable[..., tuple[int, dict]]] = None) -> dict:
    """The state Settings > Account shows. A record missing its expiry or its
    cockpit-owner answer is checked with the cloud once (GET /v1/me) and the
    answer held."""
    record = path or cloud_session_path()
    state = sign_in_state(record, now=now)
    held = read_cloud_session(record)
    if state["state"] != "signed_in" or (
            state["expires_at"] is not None and _founder_cached(held) is not None):
        return state
    fingerprint = hashlib.sha256(
        (str(record) + "|" + _held_bearer(held)).encode("utf-8")).hexdigest()
    moment = time.time() if now is None else now
    seen = _PROBED.get(fingerprint)
    if seen is not None and moment - seen < _PROBE_SECONDS:
        return state
    if confirm_with_cloud(record, now=moment, http=http) is not None:
        _PROBED[fingerprint] = moment
    return sign_in_state(record, now=now)


def cockpit_link(path: Optional[Path] = None, *, now: Optional[float] = None,
                 http: Optional[Callable[..., tuple[int, dict]]] = None) -> dict:
    """A one-time link that opens the founder cockpit on THIS session.

    The app spends its own session at the cloud's hand-off route
    (POST /founder/api/browser-code) for a single-use, five-minute claim link;
    the same link serves another device. No session, or an expired one, gets
    no link and the state to show, never a cockpit sign-in page."""
    record = path or cloud_session_path()
    state = sign_in_state(record, now=now)
    if state["state"] != "signed_in":
        return {"ok": False, "state": state["state"], "error": _SIGN_IN_AGAIN}
    held = read_cloud_session(record)
    bearer = _held_bearer(held)
    base = pinned_base(held)
    try:
        status, payload = (http or http_json)(
            "POST", f"{base}/founder/api/browser-code", body={},
            headers={"Authorization": f"Bearer {bearer}"}, timeout=10.0)
    except Exception as unreachable:
        return {"ok": False, "state": "signed_in",
                "error": ("the cloud did not answer: %s" % unreachable)[:200]}
    if status == 401 or (status == 403 and _session_invalid(status, payload)):
        record_refusal(record, bearer, now=now)
        return {"ok": False, "state": "expired", "error": _SIGN_IN_AGAIN}
    if status == 403:
        # founder_only: the cockpit answers a stale session and another
        # account the same way. /v1/me tells them apart; only a refused
        # session lapses the record.
        if confirm_with_cloud(record, now=now, http=http) == "expired":
            return {"ok": False, "state": "expired", "error": _SIGN_IN_AGAIN}
        _remember_founder(held, False)
        return {"ok": False, "state": "signed_in", "founder": False,
                "error": "This account does not own the cockpit."}
    claim = payload.get("claim_url")
    if status != 200 or not isinstance(claim, str) or not claim.startswith("https://"):
        return {"ok": False, "state": "signed_in",
                "error": "the cloud gave no cockpit link (%s)" % status}
    return {"ok": True, "state": "signed_in", "url": claim}


__all__ = [
    "METHODS", "SignIn", "begin", "cloud_session_path", "cockpit_link", "confirm_with_cloud", "current_status",
    "free_port", "http_json", "pkce_pair", "pinned_base", "read_cloud_session", "record_refusal",
    "session_summary", "sign_in_state", "sign_out", "write_cloud_session",
]
