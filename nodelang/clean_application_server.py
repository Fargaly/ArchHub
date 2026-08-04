"""Authenticated local browser lens over the signed clean graph host.

This process owns disposable browser credentials only. It neither opens nor
copies the CellStore. Reads and writes pass through one graph-bound
``LocalCoordinationClient`` and therefore retain the caller session, command
signature, authorization, revision, receipt, and replay contracts.
"""
from __future__ import annotations

import base64
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from typing import Mapping, Protocol, Type
from urllib.parse import parse_qs, urlsplit

from .clean_application_view import STYLE, SCRIPT, render_clean_application_document
from .universal_cell import InvalidCell


MAX_BROWSER_REQUEST_BYTES = 64 * 1024
SESSION_LIFETIME_SECONDS = 3600.0


class SignedGraphClient(Protocol):
    def call(
        self,
        method: str,
        parameters: Mapping[str, object] | None = None,
        *,
        timeout_seconds: float = 35.0,
    ) -> dict[str, object]: ...


class _CleanApplicationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, client: SignedGraphClient):
        self.graph_client = client
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.bootstrap_token: str | None = secrets.token_urlsafe(32)
        self.issued_at = time.time()
        self.session_lock = threading.RLock()
        super().__init__(address, handler)

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%s" % self.server_address[1]

    @property
    def bootstrap_url(self) -> str:
        token = self.bootstrap_token
        return self.url + ("/?bootstrap=" + token if token else "/")

    def consume_bootstrap(self, supplied: str) -> bool:
        with self.session_lock:
            expected = self.bootstrap_token
            if (
                not expected
                or not supplied
                or not secrets.compare_digest(supplied, expected)
            ):
                return False
            self.bootstrap_token = None
            return True

    def session_valid(self, supplied: str) -> bool:
        return bool(
            supplied
            and time.time() - self.issued_at <= SESSION_LIFETIME_SECONDS
            and secrets.compare_digest(supplied, self.session_token)
        )


class CleanApplicationRequestHandler(BaseHTTPRequestHandler):
    server: _CleanApplicationHTTPServer

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )

    def _json(self, status: int, payload: object) -> None:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _local_request(self) -> bool:
        site = self.headers.get("Sec-Fetch-Site")
        if site not in {None, "none", "same-origin"}:
            self._json(403, {"ok": False, "error": "cross-site request denied"})
            return False
        origin = self.headers.get("Origin")
        if origin not in {
            None,
            "http://127.0.0.1:%s" % self.server.server_address[1],
        }:
            self._json(403, {"ok": False, "error": "origin denied"})
            return False
        host = self.headers.get("Host", "")
        if host != "127.0.0.1:%s" % self.server.server_address[1]:
            self._json(403, {"ok": False, "error": "host denied"})
            return False
        return True

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return ""
        morsel = cookie.get("ArchHub-Clean-Session")
        return morsel.value if morsel is not None else ""

    def _authenticated(self, *, unsafe: bool = False) -> bool:
        if not self._local_request():
            return False
        if not self.server.session_valid(self._cookie_token()):
            self._json(403, {"ok": False, "error": "browser session required"})
            return False
        if unsafe and not secrets.compare_digest(
            self.headers.get("X-ArchHub-CSRF", ""),
            self.server.csrf_token,
        ):
            self._json(403, {"ok": False, "error": "CSRF token denied"})
            return False
        return True

    def _set_cookie(self) -> None:
        self.send_header(
            "Set-Cookie",
            "ArchHub-Clean-Session=%s; Path=/; HttpOnly; SameSite=Strict; "
            "Max-Age=3600" % self.server.session_token,
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            if not self._local_request():
                return
            authenticated = self.server.session_valid(self._cookie_token())
            if not authenticated:
                bootstrap = (parse_qs(parsed.query).get("bootstrap") or [""])[0]
                if not self.server.consume_bootstrap(bootstrap):
                    self._json(403, {
                        "ok": False,
                        "error": "desktop bootstrap required",
                    })
                    return
            raw = render_clean_application_document(
                self.server.csrf_token
            ).encode("utf-8")
            style_hash = base64.b64encode(
                hashlib.sha256((":root{" + "".join(
                    "--%s:%s;" % (name.replace("_", "-"), value)
                    for name, value in __import__(
                        "nodelang.clean_application_view",
                        fromlist=["THEME"],
                    ).THEME.items()
                ) + "}" + STYLE).encode("utf-8")).digest()
            ).decode("ascii")
            script_hash = base64.b64encode(
                hashlib.sha256(SCRIPT.encode("utf-8")).digest()
            ).decode("ascii")
            self.send_response(200)
            self._security_headers()
            self._set_cookie()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; connect-src 'self'; "
                "style-src 'sha256-%s'; script-src 'sha256-%s'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                % (style_hash, script_hash),
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/scope-lens":
            if not self._authenticated():
                return
            parameters: dict[str, object] = {}
            scope = (parse_qs(parsed.query).get("scope_root") or [""])[0]
            if scope:
                parameters["scope_root"] = scope
            try:
                result = self.server.graph_client.call(
                    "scope_lens", parameters
                )
            except Exception:
                self._json(502, {
                    "ok": False,
                    "error": "signed graph read failed closed",
                })
                return
            self._json(200, result)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/revise-instance":
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._authenticated(unsafe=True):
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_BROWSER_REQUEST_BYTES:
            self._json(413, {"ok": False, "error": "request size denied"})
            return
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            if type(payload) is not dict:
                raise InvalidCell("visual edit request is invalid")
            result = self.server.graph_client.call("revise_instance", payload)
        except (InvalidCell, UnicodeError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._json(502, {
                "ok": False,
                "error": "signed graph edit failed closed",
            })
            return
        self._json(200, result)


def build_clean_application_service(
    client: SignedGraphClient,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    handler: Type[CleanApplicationRequestHandler] = CleanApplicationRequestHandler,
) -> _CleanApplicationHTTPServer:
    if (
        host != "127.0.0.1"
        or type(port) is not int
        or port < 0
        or port > 65535
        or (port != 0 and port < 1024)
    ):
        raise InvalidCell("clean application bind address is invalid")
    return _CleanApplicationHTTPServer((host, port), handler, client)


__all__ = [
    "CleanApplicationRequestHandler",
    "MAX_BROWSER_REQUEST_BYTES",
    "build_clean_application_service",
]
