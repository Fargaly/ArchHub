"""OpenRouter PKCE OAuth flow.

Provides real OAuth sign-in for OpenRouter — the user clicks a button,
the browser opens, they click Authorize, ArchHub catches the redirect on
a localhost port, exchanges the code for an OpenRouter API key, and
saves it via secrets_store. Zero clipboard interaction.

Flow (OpenRouter PKCE — public, no client_id required):

    1. ArchHub generates a 256-bit code_verifier and its SHA-256
       code_challenge (base64url-encoded).
    2. ArchHub starts an HTTP listener on 127.0.0.1:<random port>.
    3. ArchHub opens
           https://openrouter.ai/auth?callback_url=<localhost>&
                                     code_challenge=<challenge>&
                                     code_challenge_method=S256
       in the user's browser.
    4. The user clicks "Authorize ArchHub".
    5. OpenRouter redirects the browser to the localhost callback with
       ?code=<auth_code>.
    6. ArchHub POSTs {code, code_verifier, code_challenge_method:'S256'}
       to https://openrouter.ai/api/v1/auth/keys, receives an API key.
    7. The HTTP listener shuts down; the dialog closes; the key is
       stored as the user's OpenRouter credential.

The whole flow is self-contained — no app registration, no client_id,
no client_secret to leak.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socket
import threading
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Optional


AUTHORIZE_URL = "https://openrouter.ai/auth"
TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT_RANGE = (54545, 54565)


@dataclass
class _OAuthState:
    code: Optional[str] = None
    error: Optional[str] = None


def _pick_free_port() -> int:
    """Find an unused TCP port in DEFAULT_PORT_RANGE. Falls back to OS-pick."""
    start, end = DEFAULT_PORT_RANGE
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((LOOPBACK_HOST, port))
                return port
            except OSError:
                continue
    # Last resort: let the OS choose any free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((LOOPBACK_HOST, 0))
        return s.getsockname()[1]


def _make_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches the browser redirect, stashes the auth code on the server."""

    def do_GET(self):                                # noqa: N802 (stdlib API)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
        err = (params.get("error") or [None])[0]

        state: _OAuthState = self.server.oauth_state                # type: ignore[attr-defined]
        if code:
            state.code = code
        elif err:
            state.error = err

        body = (
            "<html><head><title>ArchHub — Signed in</title>"
            "<style>body{font-family:system-ui,-apple-system,sans-serif;"
            "background:#1a1a1c;color:#f4efe8;text-align:center;padding:80px;}"
            "h1{font-weight:600;}.ok{color:#cc785c;}</style></head><body>"
            f"<h1 class='ok'>{'Signed in.' if code else 'Sign-in failed.'}</h1>"
            "<p>You can close this tab and return to ArchHub.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args, **_kwargs):                       # noqa: N802
        # Silence the default stderr access log.
        return


class OpenRouterOAuth:
    """One-shot PKCE flow. Construct → start() → poll completed/result/error.

    The dialog UI drives this object; it does not run its own event loop
    so it stays compatible with Qt's main loop.
    """

    def __init__(self):
        self.code_verifier, self.code_challenge = _make_pkce_pair()
        self.port = _pick_free_port()
        self.callback_url = f"http://{LOOPBACK_HOST}:{self.port}/callback"
        # OpenRouter scopes the auto-created app entry by `name`. Without
        # one, the server tries to upsert against an inferred default
        # and returns 409 "Failed to create or update app while creating
        # auth code" when the user has any prior app under the same
        # implicit name. Pin our own + add a short uuid suffix so retries
        # land on a fresh row instead of colliding with a stale one.
        import uuid as _uuid
        app_name = f"ArchHub-{_uuid.uuid4().hex[:6]}"
        self.app_name = app_name
        self.authorize_url = (
            f"{AUTHORIZE_URL}"
            f"?callback_url={urllib.parse.quote(self.callback_url, safe='')}"
            f"&code_challenge={self.code_challenge}"
            f"&code_challenge_method=S256"
            f"&name={urllib.parse.quote(app_name, safe='')}"
        )

        self._state = _OAuthState()
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---- public API -------------------------------------------------------

    def start(self) -> bool:
        """Start the local HTTP listener and open the browser. Returns False
        if the listener could not be started."""
        try:
            self._server = http.server.HTTPServer(
                (LOOPBACK_HOST, self.port), _CallbackHandler
            )
        except OSError as ex:
            self._state.error = f"Could not bind {LOOPBACK_HOST}:{self.port} — {ex}"
            return False
        self._server.oauth_state = self._state                       # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        try:
            webbrowser.open(self.authorize_url, new=2)
        except Exception as ex:
            self._state.error = f"Could not open browser: {ex}"
            self.stop()
            return False
        return True

    def stop(self) -> None:
        try:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
        except Exception:
            pass
        self._server = None
        self._thread = None

    @property
    def code(self) -> Optional[str]:
        return self._state.code

    @property
    def error(self) -> Optional[str]:
        return self._state.error

    @property
    def completed(self) -> bool:
        return self._state.code is not None or self._state.error is not None

    def exchange_code_for_key(self) -> str:
        """Trade the captured auth code for an OpenRouter API key.
        Caller MUST have observed `completed` and have no error."""
        if not self._state.code:
            raise RuntimeError("No auth code available — start() then wait.")

        payload = json.dumps({
            "code": self._state.code,
            "code_verifier": self.code_verifier,
            "code_challenge_method": "S256",
        }).encode("utf-8")
        req = urllib.request.Request(
            TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        key = data.get("key") or data.get("api_key")
        if not key:
            raise RuntimeError(
                f"OpenRouter did not return an API key. Response: {data}"
            )
        return key
