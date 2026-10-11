"""Desktop bridge to the cloud-owned social OAuth broker."""
from __future__ import annotations

import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

from .cloud_relay import DEFAULT_BASE, pinned_cloud_base
from .cloud_signin import cloud_session_path, read_cloud_session

WAIT_SECONDS = 600.0
_CURRENT: dict[str, "CloudSocialAttempt"] = {}


def _request(method: str, url: str, *, bearer: str, body: Optional[dict] = None,
             headers: Optional[dict] = None, timeout: float = 10.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    sent = {"Accept": "application/json", "Authorization": "Bearer " + bearer,
            "User-Agent": "ArchHub-desktop/2.0"}
    if data is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    request = urllib.request.Request(url, method=method, headers={
        **sent}, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(65536), response.status
    except urllib.error.HTTPError as refused:
        raw, status = refused.read(65536), refused.code
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SocialGrantNotReady(RuntimeError):
    pass


class _ReturnHandler(BaseHTTPRequestHandler):
    server_version = "ArchHub-social-return/1.0"

    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/oauth/return":
            self._html(404, "<h1>Not found</h1>")
            return
        provider = (query.get("provider") or [""])[0]
        grant = (query.get("grant") or [""])[0]
        if provider != getattr(self.server, "provider", "") or not grant:
            self.server.error = "social grant return did not match this attempt"
            self._html(400, "<h1>Social sign-in failed</h1><p>Retry from ArchHub.</p>")
            return
        self.server.grant = grant
        self._html(200, "<h1>Social account connected</h1><p>You can close this tab and return to ArchHub.</p>")

    def _html(self, status: int, body: str) -> None:
        payload = ("<!doctype html><meta charset=utf-8><title>ArchHub</title>" + body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class CloudSocialAttempt:
    def __init__(self, provider: str, token: str, base: str, *,
                 opener=None, http: Callable[..., tuple[int, dict]] = _request,
                 port: Optional[int] = None, wait_seconds: float = WAIT_SECONDS) -> None:
        self.provider = provider
        self._token, self._base, self._opener, self._http = token, base, opener, http
        self._port, self._wait = port or _free_port(), wait_seconds
        self._device_session = secrets.token_urlsafe(24)
        self._nonce = secrets.token_urlsafe(24)
        self._lock = threading.Lock()
        self._state = {"phase": "starting", "provider": provider, "account_id": "", "name": "", "error": ""}
        self._token_to_store: Optional[str] = None
        self._page_secrets: dict[str, dict] = {}
        self._pages: dict[str, dict] = {}
        self._cancel = False
        self.thread: Optional[threading.Thread] = None

    @property
    def return_url(self) -> str:
        return "http://127.0.0.1:%d/oauth/return" % self._port

    @property
    def redirect_uri(self) -> str:
        return self.return_url

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    @property
    def active(self) -> bool:
        return self.status()["phase"] in ("starting", "waiting", "exchanging")

    def cancel(self) -> None:
        self._cancel = True
        self._fail("cancelled")

    def start(self) -> "CloudSocialAttempt":
        self.thread = threading.Thread(target=self._run, name="archhub-social-oauth-" + self.provider, daemon=True)
        self.thread.start()
        return self

    def take(self) -> tuple[str, str]:
        with self._lock:
            if self._state["phase"] != "ready" or not self._token_to_store:
                raise SocialGrantNotReady("no verified social account is waiting")
            token, self._token_to_store = self._token_to_store, None
            self._state["phase"] = "taken"
            return self._state["account_id"], token

    def take_page(self, page_id: str) -> dict:
        with self._lock:
            if self.provider != "meta" or self._state["phase"] != "ready":
                raise SocialGrantNotReady("no verified Meta Pages are waiting")
            page = self._pages.get(page_id)
            secret = self._page_secrets.get(page_id)
            if not page or not secret or not secret.get("page_token"):
                raise SocialGrantNotReady("the selected Meta Page is not waiting")
            self._state["phase"] = "taken"
            self._token_to_store = None
            self._page_secrets = {}
            self._pages = {}
            selected = {"page": dict(page), "page_token": secret["page_token"]}
            if isinstance(secret.get("instagram"), dict) and secret.get("instagram_token"):
                selected["instagram"] = dict(secret["instagram"])
                selected["instagram_token"] = secret["instagram_token"]
            return selected

    def _set(self, **patch) -> None:
        with self._lock:
            self._state.update(patch)

    def _fail(self, error: str) -> None:
        with self._lock:
            self._token_to_store = None
            self._state.update(phase="failed", error=error[:200])

    def _run(self) -> None:
        try:
            server = HTTPServer(("127.0.0.1", self._port), _ReturnHandler)
        except OSError:
            self._fail("local social grant return port is busy; retry")
            return
        server.provider, server.grant, server.error, server.timeout = self.provider, "", "", 0.5
        code, payload = self._http(
            "GET",
            self._base + "/oauth/" + self.provider + "/start?" + urllib.parse.urlencode({
                "return_url": self.return_url,
                "nonce": self._nonce,
            }),
            bearer=self._token,
            headers={"X-ArchHub-Device-Session": self._device_session},
        )
        url = str(payload.get("auth_url") or "")
        if code != 200 or not url:
            server.server_close()
            self._fail("Coming soon")
            return
        opener = self._opener
        if opener is None:
            import webbrowser
            opener = webbrowser.open
        self._set(phase="waiting")
        threading.Thread(target=lambda: opener(url), name="archhub-social-browser", daemon=True).start()
        started = time.monotonic()
        try:
            while not server.grant and not server.error:
                if self._cancel:
                    self._fail("cancelled")
                    return
                if time.monotonic() - started > self._wait:
                    self._fail("timed out waiting for social sign-in")
                    return
                server.handle_request()
        finally:
            server.server_close()
        if server.error:
            self._fail(server.error)
            return
        self._set(phase="exchanging")
        code, granted = self._http("POST", self._base + "/oauth/" + self.provider + "/consume",
                                   bearer=self._token, body={"grant": server.grant},
                                   headers={"X-ArchHub-Device-Session": self._device_session})
        token = granted.get("access_token")
        account_id = granted.get("account_id")
        if code != 200 or not isinstance(token, str) or not isinstance(account_id, str):
            self._fail("social grant could not be consumed")
            return
        with self._lock:
            if self.provider == "meta":
                pages = [page for page in granted.get("pages", []) if isinstance(page, dict) and isinstance(page.get("id"), str)]
                secrets_by_page = granted.get("page_secrets") if isinstance(granted.get("page_secrets"), dict) else {}
                self._page_secrets = {pid: secret for pid, secret in secrets_by_page.items() if isinstance(pid, str) and isinstance(secret, dict)}
                self._pages = {page["id"]: page for page in pages}
                self._state.update(phase="ready", account_id=account_id, name=str(granted.get("name") or ""), pages=pages)
            else:
                self._token_to_store = token
                self._state.update(phase="ready", account_id=account_id, name=str(granted.get("name") or ""))


def _session(path: Optional[Path]) -> tuple[str, str]:
    held = read_cloud_session(path or cloud_session_path())
    token = str(held.get("token") or "")
    if not token:
        return "", pinned_cloud_base(DEFAULT_BASE)
    return token, pinned_cloud_base(held.get("cloud_base_url") or DEFAULT_BASE)


def status(provider: str, *, path: Optional[Path] = None,
           http: Callable[..., tuple[int, dict]] = _request) -> dict:
    token, base = _session(path)
    if provider not in ("linkedin", "meta") or not token:
        return {"state": "missing"}
    code, payload = http("GET", f"{base}/oauth/{provider}/status", bearer=token)
    if code != 200 or payload.get("state") != "configured":
        return {"state": "missing"}
    return {"state": "saved", "source": "archhub-cloud"}


def start(provider: str, *, path: Optional[Path] = None,
          opener=None, http: Callable[..., tuple[int, dict]] = _request) -> dict:
    token, base = _session(path)
    if provider not in ("linkedin", "meta") or not token:
        return {"phase": "failed", "error": "Sign in to the ArchHub cloud first."}
    current = _CURRENT.get(provider)
    if current and current.active:
        return current.status()
    attempt = CloudSocialAttempt(provider, token, base, opener=opener, http=http)
    _register_local_attempt(provider, attempt)
    attempt.start()
    _CURRENT[provider] = attempt
    return attempt.status()


def _register_local_attempt(provider: str, attempt: CloudSocialAttempt) -> None:
    if provider == "linkedin":
        from . import social_linkedin_signin
        with social_linkedin_signin._current_lock:
            social_linkedin_signin._current = attempt
    elif provider == "meta":
        from . import social_meta_signin
        with social_meta_signin._current_lock:
            social_meta_signin._current = attempt


def current_status(provider: str) -> dict:
    attempt = _CURRENT.get(provider)
    return attempt.status() if attempt else {"phase": "idle"}


def take_verified(provider: str) -> tuple[str, str]:
    attempt = _CURRENT.get(provider)
    if attempt is None:
        raise SocialGrantNotReady("no verified social account is waiting")
    return attempt.take()


def take_verified_page(page_id: str) -> dict:
    attempt = _CURRENT.get("meta")
    if attempt is None:
        raise SocialGrantNotReady("no verified Meta Pages are waiting")
    return attempt.take_page(page_id)
