"""Sign in with LinkedIn: fetch the founder's LinkedIn access token and the account it
belongs to, so a LinkedIn Work posts as a provider-verified account.

The LinkedIn developer app's client id and secret are the founder's own, typed in
Settings and kept in this runtime's protected store (model_router.linkedin_app). The
flow is LinkedIn's authorization-code grant: the browser opens LinkedIn's consent
page, LinkedIn returns ?code&state to a one-shot loopback on a FIXED port (LinkedIn
matches the redirect exactly, so it cannot move), and the code is exchanged here.
The account is LinkedIn's own answer, /v2/userinfo `sub`, so account_id is
urn:li:person:<sub>. The token is held only in this attempt's memory until the
authenticated Settings request enrolls it through social_custody; status() never
shows it, and it is dropped once taken or when the attempt ends.

No PKCE, by LinkedIn's own rules. The flow a developer app gets is LinkedIn's
confidential 3-legged flow (/oauth/v2/authorization): its parameters are
response_type, client_id, redirect_uri, state and scope, the token request
authenticates with client_secret, and the redirect must equal a URL registered on
the app. LinkedIn's PKCE flow is a different endpoint (/oauth/native-pkce/
authorization, any loopback port, no secret) that LinkedIn enables per app on
request. (learn.microsoft.com/linkedin/shared/authentication/authorization-code-flow
and .../authorization-code-flow-native.) What PKCE would add here, a code useless
to whoever intercepts it, comes instead from the secret the exchange needs and the
listener below: only this process can hold the port, a silent connection cannot
stall it, it accepts one callback carrying this attempt's state, and it closes.
"""
from __future__ import annotations

import json
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

REDIRECT_PORT = 48720
REDIRECT_PATH = "/linkedin/callback"
REDIRECT_URI = "http://127.0.0.1:%d%s" % (REDIRECT_PORT, REDIRECT_PATH)
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile w_member_social"
WAIT_SECONDS = 600.0
READ_SECONDS = 5.0     # one callback request must arrive whole within this
_SUB = re.compile(r"[A-Za-z0-9_-]{1,64}")

_DONE_PAGE = ("<!doctype html><meta charset=utf-8><title>ArchHub</title>"
              "<h1>LinkedIn is connected to ArchHub</h1><p>You can close this tab and return to ArchHub.</p>")


def http_form(url: str, form: dict, *, timeout: float = 20.0) -> tuple[int, dict]:
    data = urllib.parse.urlencode(form).encode("ascii")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"})
    return _send(request, timeout)


def http_bearer(url: str, token: str, *, timeout: float = 20.0) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                                   "Accept": "application/json"})
    return _send(request, timeout)


def _send(request, timeout) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            status, raw = answer.status, answer.read(65536)
    except urllib.error.HTTPError as refused:
        status, raw = refused.code, refused.read(65536)
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


class LinkedInNotReady(RuntimeError):
    """No LinkedIn account is waiting to be enrolled (not signed in, failed or taken)."""


class _Listener(HTTPServer):
    """The loopback that receives LinkedIn's redirect, held by this process alone.

    http.server turns SO_REUSEADDR on, which lets another socket bind the same
    127.0.0.1 port and take the callback. Here it is off, so no other socket can bind
    127.0.0.1:<port> while the attempt holds it; on Windows SO_EXCLUSIVEADDRUSE is set
    as well, Windows' documented guard. A socket may still bind the wildcard 0.0.0.0
    on the same port, but LinkedIn redirects to 127.0.0.1 and the more specific
    listener, this one, receives it (tests_replica/test_linkedin_signin.py).
    """
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Callback(BaseHTTPRequestHandler):
    server_version = "ArchHub-linkedin/1.0"
    # A connection that sends nothing, or too little, is dropped after this long
    # instead of holding the one-at-a-time listener (and the attempt's deadline).
    timeout = READ_SECONDS

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - silence
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path != REDIRECT_PATH:
            self._html(404, "<h1>Not found</h1>")
            return
        state = (query.get("state") or [""])[0]
        if not secrets.compare_digest(state, getattr(self.server, "expected_state", "")) or not state:
            self._html(400, "<h1>LinkedIn sign-in failed</h1><p>Security state mismatch. Retry from ArchHub.</p>")
            return
        if query.get("error"):
            self.server.denied = (query.get("error_description") or query.get("error") or ["denied"])[0][:200]
            self._html(400, "<h1>LinkedIn sign-in was not completed</h1><p>Return to ArchHub.</p>")
            return
        code = (query.get("code") or [""])[0]
        if not code:
            self._html(400, "<h1>LinkedIn sign-in failed</h1><p>No code returned. Retry from ArchHub.</p>")
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


class LinkedInSignIn:
    """One attempt; status() is what Settings polls. The token never appears in it."""

    def __init__(self, client_id: str, client_secret: str, *,
                 opener: Callable[[str], object] | None = None,
                 form: Callable[..., tuple[int, dict]] = http_form,
                 bearer: Callable[..., tuple[int, dict]] = http_bearer,
                 port: int = REDIRECT_PORT, wait_seconds: float = WAIT_SECONDS,
                 authorize_url: str = AUTHORIZE_URL, token_url: str = TOKEN_URL,
                 userinfo_url: str = USERINFO_URL) -> None:
        self._client_id, self._client_secret = client_id, client_secret
        self._opener, self._form, self._bearer = opener, form, bearer
        self._port, self._wait = port, wait_seconds
        self._urls = (authorize_url, token_url, userinfo_url)
        self._lock = threading.Lock()
        self._state = {"phase": "starting", "account_id": "", "name": "", "error": ""}
        self._token: Optional[str] = None
        self._cancel = False
        self.thread: Optional[threading.Thread] = None

    @property
    def redirect_uri(self) -> str:
        return "http://127.0.0.1:%d%s" % (self._port, REDIRECT_PATH)

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    @property
    def active(self) -> bool:
        return self.status()["phase"] in ("starting", "waiting", "exchanging")

    def cancel(self) -> None:
        """Stop waiting; the listener closes within its poll interval."""
        self._cancel = True

    def take(self) -> tuple[str, str]:
        """Hand the verified account and its token to enrollment once, then forget the token."""
        with self._lock:
            if self._state["phase"] != "ready" or not self._token:
                raise LinkedInNotReady("no verified LinkedIn account is waiting")
            token, self._token = self._token, None
            self._state.update(phase="taken")
            return self._state["account_id"], token

    def start(self) -> "LinkedInSignIn":
        self.thread = threading.Thread(target=self._run, name="archhub-linkedin-signin", daemon=True)
        self.thread.start()
        return self

    def _set(self, **patch) -> None:
        with self._lock:
            self._state.update(patch)

    def _fail(self, error: str) -> None:
        with self._lock:
            self._token = None
            self._state.update(phase="failed", error=error[:200])

    def _run(self) -> None:
        state = secrets.token_urlsafe(24)
        try:
            server = _Listener(("127.0.0.1", self._port), _Callback)
        except OSError:
            self._fail("port %d on this machine is busy; close what uses it and retry" % self._port)
            return
        server.expected_state, server.received_code, server.denied, server.timeout = state, None, None, 0.5
        authorize, token_url, userinfo_url = self._urls
        url = authorize + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": self._client_id, "redirect_uri": self.redirect_uri,
            "state": state, "scope": SCOPES})
        self._set(phase="waiting")          # the URL (it carries state) is never reported
        opener = self._opener
        if opener is None:
            import webbrowser
            opener = webbrowser.open
        threading.Thread(target=lambda: _safe(opener, url), name="archhub-linkedin-browser", daemon=True).start()
        started = time.monotonic()
        try:
            while not server.received_code and not server.denied:
                if self._cancel:
                    self._fail("cancelled")
                    return
                if time.monotonic() - started > self._wait:
                    self._fail("timed out waiting for LinkedIn")
                    return
                try:
                    server.handle_request()
                except Exception:
                    continue
        finally:
            server.server_close()
        if server.denied:
            self._fail("LinkedIn did not grant access: %s" % server.denied)
            return
        self._set(phase="exchanging")
        try:
            status, body = self._form(token_url, {
                "grant_type": "authorization_code", "code": server.received_code,
                "redirect_uri": self.redirect_uri, "client_id": self._client_id,
                "client_secret": self._client_secret})
            token = body.get("access_token")
            if status != 200 or type(token) is not str or not token:
                self._fail("LinkedIn refused the sign-in code (HTTP %s)" % status)
                return
            status, who = self._bearer(userinfo_url, token)
            sub = who.get("sub")
            if status != 200 or type(sub) is not str or not _SUB.fullmatch(sub):
                self._fail("LinkedIn did not confirm which account signed in (HTTP %s)" % status)
                return
        except Exception as unreachable:
            self._fail("LinkedIn could not be reached: %s" % type(unreachable).__name__)
            return
        with self._lock:
            self._token = token
            self._state.update(phase="ready", account_id="urn:li:person:" + sub,
                               name=str(who.get("name") or "")[:120], error="")


def _safe(opener, url) -> None:
    try:
        opener(url)
    except Exception:
        pass


_current: Optional[LinkedInSignIn] = None
_current_lock = threading.Lock()


def begin(client_id: str, client_secret: str, **options) -> dict:
    """Start one attempt, replacing a finished one; an active attempt is reused."""
    global _current
    with _current_lock:
        if _current is not None and _current.active:
            return {**_current.status(), "redirect_uri": _current.redirect_uri}
        _current = LinkedInSignIn(client_id, client_secret, **options).start()
        attempt = _current
    return {**attempt.status(), "redirect_uri": attempt.redirect_uri}


def current_status() -> dict:
    with _current_lock:
        attempt = _current
    if attempt is None:
        return {"phase": "idle", "account_id": "", "name": "", "error": "", "redirect_uri": REDIRECT_URI}
    return {**attempt.status(), "redirect_uri": attempt.redirect_uri}


def take_verified() -> tuple[str, str]:
    with _current_lock:
        attempt = _current
    if attempt is None:
        raise LinkedInNotReady("no verified LinkedIn account is waiting")
    return attempt.take()


def cancel_current() -> dict:
    """Settings' Cancel: stop the waiting attempt, if any, and report its state."""
    with _current_lock:
        attempt = _current
    if attempt is not None and attempt.active:
        attempt.cancel()
        if attempt.thread is not None:
            attempt.thread.join(timeout=READ_SECONDS + 2)
    return current_status()