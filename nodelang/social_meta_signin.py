"""Sign in with Meta: fetch the founder's Facebook Login token, then list Pages
and linked Instagram professional accounts for explicit enrollment.

The Meta developer app's app id and secret are typed in Settings and kept in this
runtime's protected store (model_router.meta_app). The browser opens Facebook
Login, Meta returns ?code&state to a one-shot loopback on a fixed local port, and
the code is exchanged here. The user token and Page tokens are held only in this
attempt's memory. Status returns Page and Instagram ids/names only. The
authenticated Settings request must pick one Page; only then are page-bound
credentials enrolled through social_custody and the tokens forgotten.
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

REDIRECT_PORT = 48721
REDIRECT_PATH = "/meta/callback"
REDIRECT_URI = "http://127.0.0.1:%d%s" % (REDIRECT_PORT, REDIRECT_PATH)
GRAPH_VERSION = "v25.0"
AUTHORIZE_URL = "https://www.facebook.com/%s/dialog/oauth" % GRAPH_VERSION
TOKEN_URL = "https://graph.facebook.com/%s/oauth/access_token" % GRAPH_VERSION
USERINFO_URL = "https://graph.facebook.com/%s/me?fields=id,name" % GRAPH_VERSION
ME_URL = USERINFO_URL
PAGES_URL = "https://graph.facebook.com/%s/me/accounts?fields=id,name,access_token&limit=25" % GRAPH_VERSION
SCOPES = "pages_show_list pages_read_engagement pages_manage_posts pages_manage_engagement instagram_basic instagram_content_publish instagram_manage_comments"
WAIT_SECONDS = 600.0
READ_SECONDS = 5.0     # one callback request must arrive whole within this
_USER_ID = re.compile(r"[0-9]{1,32}")
_GRAPH_ID = re.compile(r"[0-9]{1,32}(?:_[0-9]{1,32})?")

_DONE_PAGE = ("<!doctype html><meta charset=utf-8><title>ArchHub</title>"
              "<h1>Facebook and Instagram are connected to ArchHub</h1>"
              "<p>You can close this tab and return to ArchHub.</p>")


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


class MetaNotReady(RuntimeError):
    """No Meta account is waiting to be enrolled (not signed in, failed or taken)."""


class _Listener(HTTPServer):
    """The loopback that receives Meta's redirect, held by this process alone.

    http.server turns SO_REUSEADDR on, which lets another socket bind the same
    127.0.0.1 port and take the callback. Here it is off, so no other socket can bind
    127.0.0.1:<port> while the attempt holds it; on Windows SO_EXCLUSIVEADDRUSE is set
    as well, Windows' documented guard. A socket may still bind the wildcard 0.0.0.0
    on the same port, but Meta redirects to 127.0.0.1 and the more specific
    listener, this one, receives it (tests_replica/test_meta_signin.py).
    """
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Callback(BaseHTTPRequestHandler):
    server_version = "ArchHub-meta/1.0"
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
            self._html(400, "<h1>Meta sign-in failed</h1><p>Security state mismatch. Retry from ArchHub.</p>")
            return
        if query.get("error"):
            self.server.denied = (query.get("error_description") or query.get("error") or ["denied"])[0][:200]
            self._html(400, "<h1>Meta sign-in was not completed</h1><p>Return to ArchHub.</p>")
            return
        code = (query.get("code") or [""])[0]
        if not code:
            self._html(400, "<h1>Meta sign-in failed</h1><p>No code returned. Retry from ArchHub.</p>")
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


class MetaSignIn:
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
        self._state = {"phase": "starting", "account_id": "", "name": "", "error": "", "pages": []}
        self._token: Optional[str] = None
        self._page_tokens: dict[str, str] = {}
        self._pages: dict[str, dict] = {}
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

    def take_page(self, page_id: str) -> dict:
        """Hand one selected Page credential to enrollment once, then forget all tokens."""
        with self._lock:
            if self._state["phase"] != "ready" or not self._token:
                raise MetaNotReady("no verified Meta Pages are waiting")
            if not isinstance(page_id, str) or not _GRAPH_ID.fullmatch(page_id) or page_id not in self._page_tokens:
                raise MetaNotReady("the selected Meta Page is not waiting")
            page = dict(self._pages[page_id])
            result = {"page": page, "page_token": self._page_tokens[page_id]}
            instagram = page.get("instagram")
            if isinstance(instagram, dict):
                result["instagram"] = dict(instagram)
                result["instagram_token"] = self._page_tokens[page_id]
            self._token = None
            self._page_tokens = {}
            self._pages = {}
            self._state.update(phase="taken", pages=[])
            return result

    def start(self) -> "MetaSignIn":
        self.thread = threading.Thread(target=self._run, name="archhub-meta-signin", daemon=True)
        self.thread.start()
        return self

    def _set(self, **patch) -> None:
        with self._lock:
            self._state.update(patch)

    def _fail(self, error: str) -> None:
        with self._lock:
            self._token = None
            self._page_tokens = {}
            self._pages = {}
            self._state.update(phase="failed", pages=[], error=error[:200])

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
        threading.Thread(target=lambda: _safe(opener, url), name="archhub-meta-browser", daemon=True).start()
        started = time.monotonic()
        try:
            while not server.received_code and not server.denied:
                if self._cancel:
                    self._fail("cancelled")
                    return
                if time.monotonic() - started > self._wait:
                    self._fail("timed out waiting for Meta")
                    return
                try:
                    server.handle_request()
                except Exception:
                    continue
        finally:
            server.server_close()
        if server.denied:
            self._fail("Meta did not grant access: %s" % server.denied)
            return
        self._set(phase="exchanging")
        try:
            status, body = self._form(token_url, {
                "grant_type": "authorization_code", "code": server.received_code,
                "redirect_uri": self.redirect_uri, "client_id": self._client_id,
                "client_secret": self._client_secret})
            token = body.get("access_token")
            if status != 200 or type(token) is not str or not token:
                self._fail("Meta refused the sign-in code (HTTP %s)" % status)
                return
            status, who = self._bearer(userinfo_url, token)
            user_id = who.get("id")
            if status != 200 or type(user_id) is not str or not _USER_ID.fullmatch(user_id):
                self._fail("Meta did not confirm which account signed in (HTTP %s)" % status)
                return
            status, pages_body = self._bearer(PAGES_URL, token)
            if status != 200:
                self._fail("Meta did not return managed Pages (HTTP %s)" % status)
                return
            public_pages, page_tokens, pages_by_id = self._read_pages(pages_body)
            if not public_pages:
                self._fail("Meta returned no Pages for this account")
                return
        except Exception as unreachable:
            self._fail("Meta could not be reached: %s" % type(unreachable).__name__)
            return
        with self._lock:
            self._token = token
            self._page_tokens = page_tokens
            self._pages = pages_by_id
            self._state.update(phase="ready", account_id="meta:user:" + user_id,
                               name=str(who.get("name") or "")[:120], pages=public_pages, error="")

    def _read_pages(self, pages_body: dict) -> tuple[list[dict], dict[str, str], dict[str, dict]]:
        rows = pages_body.get("data")
        if not isinstance(rows, list):
            return [], {}, {}
        public_pages, page_tokens, pages_by_id = [], {}, {}
        for row in rows[:25]:
            if not isinstance(row, dict):
                continue
            page_id, name, page_token = row.get("id"), row.get("name"), row.get("access_token")
            if (type(page_id) is not str or not _GRAPH_ID.fullmatch(page_id)
                    or type(page_token) is not str or not page_token
                    or any(ord(char) < 33 or ord(char) > 126 for char in page_token)):
                continue
            page = {"id": page_id, "name": str(name or page_id)[:120]}
            try:
                status, body = self._bearer(
                    "https://graph.facebook.com/%s/%s?%s" % (
                        GRAPH_VERSION, page_id,
                        urllib.parse.urlencode({"fields": "instagram_business_account{id,username}"}),
                    ),
                    page_token,
                )
                account = body.get("instagram_business_account") if status == 200 else None
                ig_id = account.get("id") if isinstance(account, dict) else None
                if isinstance(ig_id, str) and _GRAPH_ID.fullmatch(ig_id):
                    page["instagram"] = {"id": ig_id, "username": str(account.get("username") or "")[:120]}
            except Exception:
                pass
            public_pages.append(page)
            page_tokens[page_id] = page_token
            pages_by_id[page_id] = page
        return public_pages, page_tokens, pages_by_id


def _safe(opener, url) -> None:
    try:
        opener(url)
    except Exception:
        pass


_current: Optional[MetaSignIn] = None
_current_lock = threading.Lock()


def begin(client_id: str, client_secret: str, **options) -> dict:
    """Start one attempt, replacing a finished one; an active attempt is reused."""
    global _current
    with _current_lock:
        if _current is not None and _current.active:
            return {**_current.status(), "redirect_uri": _current.redirect_uri}
        _current = MetaSignIn(client_id, client_secret, **options).start()
        attempt = _current
    return {**attempt.status(), "redirect_uri": attempt.redirect_uri}


def current_status() -> dict:
    with _current_lock:
        attempt = _current
    if attempt is None:
        return {"phase": "idle", "account_id": "", "name": "", "error": "", "pages": [],
                "redirect_uri": REDIRECT_URI}
    return {**attempt.status(), "redirect_uri": attempt.redirect_uri}


def take_verified_page(page_id: str) -> dict:
    with _current_lock:
        attempt = _current
    if attempt is None:
        raise MetaNotReady("no verified Meta Pages are waiting")
    return attempt.take_page(page_id)


def cancel_current() -> dict:
    """Settings' Cancel: stop the waiting attempt, if any, and report its state."""
    with _current_lock:
        attempt = _current
    if attempt is not None and attempt.active:
        attempt.cancel()
        if attempt.thread is not None:
            attempt.thread.join(timeout=READ_SECONDS + 2)
    return current_status()
