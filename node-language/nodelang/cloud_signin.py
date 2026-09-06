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

from .cloud_relay import DEFAULT_BASE

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
        if state != getattr(self.server, "expected_state", ""):
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
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
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
        status, payload = self._http(
            "POST", f"{self.base_url}/v1/auth/exchange",
            body={"code": code, "code_verifier": verifier})
        token = str(payload.get("token") or "")
        if status != 200 or not token:
            self._set(phase="failed", error=str(payload.get("error") or payload.get("detail")
                                                or f"exchange refused ({status})")[:200])
            return
        _status, me = self._http("GET", f"{self.base_url}/v1/me",
                                 headers={"Authorization": f"Bearer {token}"})
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


def sign_out(path: Optional[Path] = None, *, http: Callable[..., tuple[int, dict]] = http_json) -> dict:
    """Forget the session on this machine; tell the cloud best-effort."""
    record = path or cloud_session_path()
    held = read_cloud_session(record)
    token = str(held.get("token") or "")
    base = str(held.get("cloud_base_url") or DEFAULT_BASE).rstrip("/")
    if token:
        try:
            http("POST", f"{base}/v1/auth/logout", body={},
                 headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        except Exception:
            pass
    if held:
        write_cloud_session(record, {"token": None, "expires_at": None,
                                     "email": None, "user_id": None})
    attempt = _CURRENT.get("attempt")
    if attempt is not None and not attempt.active:
        _CURRENT["attempt"] = None
    return {"signed_in": False, "email": ""}


def session_summary(path: Optional[Path] = None) -> dict:
    from .cloud_session import signed_in_cloud_account
    record = path or cloud_session_path()
    email = signed_in_cloud_account(record)
    return {"signed_in": bool(email), "email": email or ""}


__all__ = [
    "METHODS", "SignIn", "begin", "cloud_session_path", "current_status",
    "free_port", "http_json", "pkce_pair", "read_cloud_session",
    "session_summary", "sign_out", "write_cloud_session",
]
