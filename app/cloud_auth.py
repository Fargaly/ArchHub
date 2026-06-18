"""Browser PKCE sign-in flow for ArchHub Cloud.

Replaces the legacy "paste your API key" UX with the modern OAuth-
style flow every consumer SaaS uses:

  1. App generates a PKCE verifier + challenge.
  2. App spins up a local HTTP server on a random free port.
  3. App opens the user's default browser to
     cloud.archhub.io/signin?challenge=...&redirect=http://127.0.0.1:<port>/cb
  4. User signs in on the web (magic link or password). Backend
     redirects to the local callback with a one-time `code`.
  5. App POSTs {code, code_verifier} to /v1/auth/exchange → gets
     a bearer token + plan info. Stored encrypted via secrets_store.

The local server only runs during the sign-in window (max 5 min);
listens on 127.0.0.1 only so other hosts on the LAN can't hit it.

"Sign in with Google" (GoogleSignInWorker) reuses the SAME machinery — PKCE
verifier/challenge, one-shot 127.0.0.1 loopback, the same succeeded/failed
signals and the same _pair_brain handshake — differing only in how it obtains
the provider URL: it first GETs {base}/v1/auth/google/start?code_challenge=...&
redirect=<loopback> to receive {auth_url}, opens THAT, captures the loopback
?code=, then exchanges it via the identical cloud_client.exchange(code,
verifier). Both workers persist the token through cloud_client.set_token, which
now writes the daemon's cloud.json so sign-in activates cross-device sync.

Public API
----------
    SignInWorker(QObject)          # magic-link / email PKCE flow
    GoogleSignInWorker(QObject)    # "Sign in with Google" PKCE flow
        start()
        cancel()
        signals:
          succeeded(plan_dict)
          failed(message)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

from PyQt6.QtCore import QObject, pyqtSignal


_AUTH_PATH = "/signin"
_WAIT_TIMEOUT_S = 300   # 5 min user has to finish the browser flow
_AUTH_RETURN_STATE = "archhub"


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

        accepted_states = getattr(self.server, "accepted_states", None)
        if accepted_states is None:
            expected = getattr(self.server, "expected_state", "")
            accepted_states = {s for s in (expected, _AUTH_RETURN_STATE) if s}

        if state not in accepted_states:
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
class _BaseSignInWorker(QObject):
    """Shared engine for the browser PKCE sign-in dance, off the Qt main
    thread. Subclasses ONLY supply how the provider auth URL is resolved
    (`_resolve_auth_url`) — the PKCE pair, the one-shot 127.0.0.1 loopback
    server, the wait/cancel/timeout loop, the cloud_client.exchange call, the
    /v1/me fetch, and the _pair_brain handshake are identical for every flow.

    Signals + start()/cancel() match the original SignInWorker exactly so
    callers (bridge, settings_dialog, onboarding) are source-compatible.
    """
    succeeded = pyqtSignal(dict)    # plan/me payload
    failed    = pyqtSignal(str)      # human message

    # Human label used in error strings ("Sign-in …" by default).
    _flow_label = "Sign-in"

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
    def _resolve_auth_url(self, *, redirect: str, challenge: str,
                          state: str, verifier: str) -> str:
        """Return the URL to open in the browser for this flow.

        Subclass hook. `redirect` is the loopback callback the backend must
        send the one-time `code` to. May raise to abort the flow with the
        raised message surfaced to the user. Default raises (base is abstract).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            from cloud_client import exchange, me
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
        httpd.accepted_states = {state, _AUTH_RETURN_STATE}
        httpd.received_code = None
        httpd.timeout = 1.0

        redirect = f"http://127.0.0.1:{port}/cb"

        # Resolve the provider auth URL (magic-link builds it locally; Google
        # asks the backend for it). Errors here abort with a clear message.
        try:
            signin_url = self._resolve_auth_url(
                redirect=redirect, challenge=challenge,
                state=state, verifier=verifier,
            )
        except Exception as e:
            httpd.server_close()
            self.failed.emit(str(e) or f"{self._flow_label} couldn't start.")
            return
        if not signin_url:
            httpd.server_close()
            self.failed.emit(f"{self._flow_label} couldn't start "
                             "(no auth URL).")
            return

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
                self.failed.emit(f"{self._flow_label} cancelled.")
                return
            if time.time() - t0 > _WAIT_TIMEOUT_S:
                httpd.server_close()
                self.failed.emit(f"{self._flow_label} timed out. Try again.")
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
            self.failed.emit(f"{self._flow_label} exchange failed ({err}).")
            return

        # Fetch /v1/me so caller has plan + remaining_messages cached.
        info = me() or {}

        # Brain pairing (Track D · section 5 of CONTENT-ECOSYSTEM-2026-05-26):
        # immediately after the token mints, (a) announce this device's wiring
        # to the LOCAL brain so it knows we're now cloud-paired, then (b) POST
        # one (possibly empty) delta to /v1/brain/sync so the server creates
        # the per-user replica and stamps the initial HLC handshake. Both
        # calls are best-effort — sign-in MUST NOT fail if either is down,
        # per BRAIN-FIRST graceful-degrade clause.
        try:
            self._pair_brain(token=payload.get("token", ""))
        except Exception:
            pass

        self.succeeded.emit({**payload, "me": info})

    # ------------------------------------------------------------------
    def _pair_brain(self, *, token: str) -> None:
        """Wire the local brain to the just-minted cloud session.

        1. brain.set_owner — BIND the local brain to the signed-in cloud
           account so every owner-defaulted fragment / skill / wiring write
           is owned by this account's user_id (persists in brain_meta,
           survives daemon restart). This is the MAKE-IT-REAL chokepoint:
           BOTH onboarding first-run AND the Settings/Brain re-entry sign-in
           reach the daemon through here.
        2. brain.wiring_announce — tell the local daemon about this device.
        3. POST /v1/brain/sync — register the cloud-side replica + receive
           the initial HLC. Sends an empty delta on first pair so the cloud
           knows to provision storage but nothing leaks yet.

        Every step is best-effort: if the brain daemon is down OR the cloud
        is unreachable, sign-in still succeeds (BRAIN-FIRST graceful-degrade).
        When the daemon IS up, the binding is REAL — get_owner afterwards
        reports bound=true, owner_user=<the cloud user_id>.
        """
        # 0. Bind the local brain to this cloud account. Fetch the identity
        # (user_id + email) the cloud just minted, then call brain.set_owner
        # via the memory_gate BrainClient (the canonical way to call an
        # arbitrary brain tool). Graceful-degrade exactly like the announce
        # below — a down daemon must NOT fail sign-in.
        try:
            self._bind_owner()
        except Exception:
            pass   # brain daemon down / cloud unreachable — sign-in still works
        # 1. Local brain announce. The MCP HTTP client lives in the broker;
        # if it's unreachable we silently fall through (graceful-degrade).
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:8473/mcp",
                data=(
                    b'{"jsonrpc":"2.0","id":1,"method":"tools/call",'
                    b'"params":{"name":"brain.wiring_announce",'
                    b'"arguments":{"name":"archhub-cloud",'
                    b'"kind":"cloud","status":"active"}}}'
                ),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2.0).read()
        except Exception:
            pass   # brain daemon unreachable — sign-in still works
        # 2. Cloud-side pair handshake. Empty delta on first contact.
        if not token:
            return
        try:
            from cloud_client import base_url
            import urllib.request
            req = urllib.request.Request(
                f"{base_url()}/v1/brain/sync",
                data=b'{"since_hlc":"","delta":{"fragments":[],"wiring":[]}}',
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3.0).read()
        except Exception:
            pass   # cloud unreachable — desktop continues, retries on next sync

    # ------------------------------------------------------------------
    def _bind_owner(self) -> Optional[dict]:
        """Bind the local brain to the signed-in cloud account.

        Fetches the account identity from /v1/me (the NEW `user_id` field)
        and calls the local brain's `brain.set_owner(user_id, email)` so the
        default owner of every owner-defaulted write becomes that user_id —
        persisted in brain_meta, surviving daemon restart.

        Returns the brain.set_owner result dict on success, or None when the
        identity couldn't be fetched (not signed in / cloud down) or the brain
        daemon is unreachable. Best-effort by contract: never raises; callers
        wrap in try/except too. Reuses `memory_gate.BrainClient._call`, the
        canonical path to invoke an arbitrary brain tool.
        """
        # 1. Resolve the cloud identity. me_identity() reads the server's new
        #    user_id field and returns None unless a real user_id is present,
        #    so we never bind the brain to a blank owner.
        try:
            from cloud_client import me_identity
            ident = me_identity()
        except Exception:
            ident = None
        if not ident or not ident.get("user_id"):
            return None
        # 2. Call brain.set_owner via the memory_gate BrainClient. Short
        #    timeout so a wedged daemon can't stall sign-in; a refused
        #    connection raises and we return None (graceful-degrade).
        try:
            from memory_gate import BrainClient
            client = BrainClient()
            return client._call(
                "brain.set_owner",
                {
                    "user_id": ident["user_id"],
                    "email": ident.get("email") or "",
                },
                timeout=3.0,
            )
        except Exception:
            return None


# ---------------------------------------------------------------------------
class SignInWorker(_BaseSignInWorker):
    """Magic-link / email PKCE sign-in. Builds the /signin URL locally and
    opens it — identical to the original flow (the backend redirects to the
    loopback with a one-time `code` after the user finishes in the browser)."""

    _flow_label = "Sign-in"

    def _resolve_auth_url(self, *, redirect: str, challenge: str,
                          state: str, verifier: str) -> str:
        from cloud_client import base_url
        qp = urlencode({
            "challenge": challenge,
            "state": state,
            "redirect": redirect,
            "client": "desktop",
        })
        return f"{base_url()}{_AUTH_PATH}?{qp}"


# ---------------------------------------------------------------------------
class GoogleSignInWorker(_BaseSignInWorker):
    """"Sign in with Google" PKCE sign-in.

    Same dance as SignInWorker (PKCE pair · one-shot 127.0.0.1 loopback · the
    same succeeded/failed signals · the same exchange + _pair_brain), except
    the provider URL is obtained from the backend: we GET
    {base}/v1/auth/google/start?code_challenge=<challenge>&redirect=<loopback>
    and open the returned {auth_url}. The backend runs the Google OAuth dance
    and redirects to our loopback with the one-time `code`, which we exchange
    via the EXISTING cloud_client.exchange(code, verifier) — so the token mint,
    cloud.json persistence, and brain pairing are all shared, unchanged.
    """

    _flow_label = "Google sign-in"

    def _resolve_auth_url(self, *, redirect: str, challenge: str,
                          state: str, verifier: str) -> str:
        from cloud_client import base_url
        qp = urlencode({
            "code_challenge": challenge,
            "redirect": redirect,
            # Older/live /auth/return sends state=archhub, while a future
            # backend may echo this generated state. The callback accepts both.
            "state": state,
            "client": "desktop",
        })
        url = f"{base_url()}/v1/auth/google/start?{qp}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ArchHub-desktop/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Google sign-in unavailable (HTTP {e.code})."
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                "Couldn't reach ArchHub Cloud to start Google sign-in — "
                "check your internet."
            ) from e
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        auth_url = (data.get("auth_url") or data.get("url") or "").strip() \
            if isinstance(data, dict) else ""
        if not auth_url:
            raise RuntimeError(
                "Google sign-in didn't return a sign-in URL. Try again."
            )
        return auth_url
