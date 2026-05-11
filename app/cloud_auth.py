"""Browser PKCE sign-in flow for ArchHub Cloud.

Replaces the legacy "paste your API key" UX with the modern OAuth-
style flow every consumer SaaS uses:

  1. App generates a PKCE verifier + challenge.
  2. App spins up a local HTTP server on a random free port.
  3. App opens the user's default browser to
     cloud.archhub.app/signin?challenge=...&redirect=http://127.0.0.1:<port>/cb
  4. User signs in on the web (magic link or password). Backend
     redirects to the local callback with a one-time `code`.
  5. App POSTs {code, code_verifier} to /v1/auth/exchange → gets
     a bearer token + plan info. Stored encrypted via secrets_store.

The local server only runs during the sign-in window (max 5 min);
listens on 127.0.0.1 only so other hosts on the LAN can't hit it.

Public API
----------
    SignInWorker(QObject)
        start()
        cancel()
        signals:
          succeeded(plan_dict)
          failed(message)
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

from PyQt6.QtCore import QObject, pyqtSignal


_AUTH_PATH = "/signin"
_WAIT_TIMEOUT_S = 300   # 5 min user has to finish the browser flow


# ---------------------------------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Verifier is 64 hex chars,
    challenge is base64url(sha256(verifier)) per RFC 7636."""
    verifier = secrets.token_urlsafe(48)   # ~64 chars, URL-safe
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _free_port() -> int:
    """Ask the OS for any free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot HTTP handler. Captures the `code` query param,
    serves a friendly thank-you page, then signals the parent thread."""

    server_version = "ArchHub-callback/1.0"
    # Populated by parent: server.received_code, server.expected_state
    received_code: Optional[str] = None

    def log_message(self, fmt: str, *args) -> None:
        # Silence the default stderr access log — this is a desktop
        # app, the user shouldn't see CLI noise.
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [""])[0]

        if state != getattr(self.server, "expected_state", ""):
            self._html(400,
                "<h1>Sign-in failed</h1>"
                "<p>Security state mismatch. Please retry from the app.</p>"
            )
            return

        if not code:
            self._html(400,
                "<h1>Sign-in failed</h1>"
                "<p>No code returned. Please retry from the app.</p>"
            )
            return

        self.server.received_code = code   # picked up by SignInWorker
        self._html(200,
            "<h1>You're signed in</h1>"
            "<p>You can close this tab and return to ArchHub.</p>"
            "<style>body{font-family:system-ui;padding:60px;"
            "max-width:520px;margin:0 auto;color:#251f17;}"
            "h1{font-style:italic;letter-spacing:-0.02em;}"
            "</style>"
        )

    def _html(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


# ---------------------------------------------------------------------------
class SignInWorker(QObject):
    """Drives the full browser sign-in dance off the Qt main thread."""
    succeeded = pyqtSignal(dict)    # plan/me payload
    failed    = pyqtSignal(str)      # human message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            from cloud_client import base_url, exchange, me
        except Exception as e:
            self.failed.emit(f"Cloud module unavailable: {e}")
            return

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)

        try:
            port = _free_port()
            httpd = HTTPServer(("127.0.0.1", port), _CallbackHandler)
        except Exception as e:
            self.failed.emit(f"Couldn't open local callback port: {e}")
            return
        httpd.expected_state = state
        httpd.received_code = None
        httpd.timeout = 1.0

        redirect = f"http://127.0.0.1:{port}/cb"
        qp = urlencode({
            "challenge": challenge,
            "state": state,
            "redirect": redirect,
            "client": "desktop",
        })
        signin_url = f"{base_url()}{_AUTH_PATH}?{qp}"

        # Open the user's default browser.
        try:
            import webbrowser
            webbrowser.open(signin_url)
        except Exception as e:
            httpd.server_close()
            self.failed.emit(f"Couldn't open browser: {e}")
            return

        # Wait for callback (or cancel / timeout).
        t0 = time.time()
        while not httpd.received_code:
            if self._cancel:
                httpd.server_close()
                self.failed.emit("Sign-in cancelled.")
                return
            if time.time() - t0 > _WAIT_TIMEOUT_S:
                httpd.server_close()
                self.failed.emit("Sign-in timed out. Try again.")
                return
            try:
                httpd.handle_request()
            except Exception:
                # Treat hiccups as benign; keep polling until timeout.
                continue

        code = httpd.received_code
        httpd.server_close()

        ok, payload = exchange(code, verifier)
        if not ok:
            err = (payload.get("error") or "unknown") if isinstance(payload, dict) else "unknown"
            self.failed.emit(f"Sign-in exchange failed ({err}).")
            return

        # Fetch /v1/me so caller has plan + remaining_messages cached.
        info = me() or {}
        self.succeeded.emit({**payload, "me": info})
