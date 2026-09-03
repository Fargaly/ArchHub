"""Short-lived native loopback login for the graph-governed cloud runtime.

This is physical callback machinery, not a second identity system.  The
authorization transaction, its completion, the external identity verification,
device binding, and the resulting Cloud Session remain existing Cell
compositions.  The browser callback code, PKCE verifier, provider tokens, and
access token live only in the owning process while the operator explicitly
completes sign-in.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from urllib.parse import parse_qsl, parse_qs, urlsplit

import httpx

from .cell_cloud_sessions import CloudSessionBroker, IssuedCloudSession
from .cell_federated_identity import FederatedIdentityBroker
from .cell_native_auth import (
    NativeAuthenticationDenied,
    NativeAuthenticationProtocol,
    NativeAuthorizationBroker,
    NativeAuthorizationCode,
    NativeClientAdmissionVerifier,
    StartedNativeAuthorization,
    exchange_native_authorization_code,
    issue_native_cloud_session,
)
from .universal_cell import CellStore


_MAX_CALLBACK_TARGET_BYTES = 8192
_MAX_WAIT_SECONDS = 660.0
_COMPLETE_HTML = b"""<!doctype html><meta charset=\"utf-8\"><title>ArchHub sign-in complete</title><p>Sign-in is complete. You can return to ArchHub.</p>"""
_INVALID_HTML = b"""<!doctype html><meta charset=\"utf-8\"><title>ArchHub sign-in not completed</title><p>This sign-in callback could not be accepted. Return to ArchHub and try again.</p>"""


class NativeCloudLoginDenied(PermissionError):
    """The native callback did not satisfy the released login boundary."""


class NativeCloudLoginTimeout(TimeoutError):
    """The operator did not complete the native callback in time."""


@dataclass(frozen=True, slots=True)
class StartedNativeCloudLogin:
    """Non-secret facts needed to let the operator complete native sign-in."""

    transaction_root: str
    authorization_url: str
    expires_at: float


class _LoopbackCallbackServer(ThreadingHTTPServer):
    """A non-reusable, IPv4-only loopback listener for one transaction."""

    allow_reuse_address = False
    daemon_threads = True


class NativeCloudLogin:
    """Explicit loopback login that consumes existing graph authority.

    ``start`` only prepares the bounded local receiver and returns the provider
    URL.  It never opens a browser or issues a session by itself.  The caller
    retains control of the user gesture and calls ``wait_and_issue`` after the
    operator completes that gesture.  One instance owns exactly one login
    transaction and must be closed when abandoned.
    """

    def __init__(
        self,
        *,
        store: CellStore,
        protocol: NativeAuthenticationProtocol,
        registration_root: str,
        native_authorization_broker: NativeAuthorizationBroker,
        federated_identity_broker: FederatedIdentityBroker,
        cloud_session_broker: CloudSessionBroker,
        client_admission_verifier: NativeClientAdmissionVerifier,
        allowed_action_roots: tuple[str, ...],
    ) -> None:
        if not isinstance(store, CellStore):
            raise TypeError("native cloud login requires a Cell store")
        if not isinstance(protocol, NativeAuthenticationProtocol):
            raise TypeError("native cloud login requires its graph protocol")
        if not isinstance(registration_root, str) or not registration_root:
            raise ValueError("native cloud login registration is invalid")
        if not isinstance(native_authorization_broker, NativeAuthorizationBroker):
            raise TypeError("native cloud login requires the native authorization broker")
        if not isinstance(federated_identity_broker, FederatedIdentityBroker):
            raise TypeError("native cloud login requires the federated identity broker")
        if not isinstance(cloud_session_broker, CloudSessionBroker):
            raise TypeError("native cloud login requires the Cloud Session broker")
        if not hasattr(client_admission_verifier, "verify"):
            raise TypeError("native cloud login requires client admission verification")
        if (
            not allowed_action_roots
            or any(not isinstance(root, str) or not root for root in allowed_action_roots)
        ):
            raise ValueError("native cloud login requires released action roots")
        self._store = store
        self._protocol = protocol
        self._registration_root = registration_root
        self._native_authorization_broker = native_authorization_broker
        self._federated_identity_broker = federated_identity_broker
        self._cloud_session_broker = cloud_session_broker
        self._client_admission_verifier = client_admission_verifier
        self._allowed_action_roots = tuple(allowed_action_roots)
        self._condition = threading.Condition(threading.RLock())
        self._server: _LoopbackCallbackServer | None = None
        self._server_thread: threading.Thread | None = None
        self._started: StartedNativeCloudLogin | None = None
        self._callback_path = ""
        self._authorization_code: NativeAuthorizationCode | None = None
        self._closed = False

    @property
    def started(self) -> StartedNativeCloudLogin | None:
        """Return non-secret transaction state without exposing callback data."""
        with self._condition:
            return self._started

    def start(
        self,
        *,
        device_thumbprint: str,
        lifetime_seconds: float = 300.0,
    ) -> StartedNativeCloudLogin:
        """Bind a local ephemeral port and prepare one issued graph transaction."""
        with self._condition:
            if self._closed:
                raise NativeCloudLoginDenied("native cloud login is closed")
            if self._started is not None:
                raise NativeCloudLoginDenied("native cloud login already started")
            server = self._new_server()
            try:
                started = self._native_authorization_broker.start(
                    self._store,
                    self._protocol,
                    self._registration_root,
                    redirect_port=int(server.server_port),
                    device_thumbprint=device_thumbprint,
                    lifetime_seconds=lifetime_seconds,
                )
                callback_path = self._callback_path_from(started, server.server_port)
            except Exception:
                server.server_close()
                raise
            result = StartedNativeCloudLogin(
                transaction_root=started.transaction_root,
                authorization_url=started.authorization_url,
                expires_at=started.expires_at,
            )
            self._server = server
            self._callback_path = callback_path
            self._started = result
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.2},
                name="archhub-native-login-callback",
                daemon=True,
            )
            self._server_thread = thread
            thread.start()
            return result

    def wait_and_issue(
        self,
        *,
        timeout_seconds: float = 300.0,
        token_client: httpx.Client | None = None,
        session_lifetime_seconds: float = 900.0,
    ) -> IssuedCloudSession:
        """Wait for one accepted callback, then issue a device-bound session.

        The returned access token is process-held caller output.  It is never
        placed in a Cell, written to disk, logged, or retained by this object.
        """
        if (
            not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= _MAX_WAIT_SECONDS
        ):
            raise ValueError("native cloud login wait must be within eleven minutes")
        with self._condition:
            if self._started is None:
                raise NativeCloudLoginDenied("native cloud login was not started")
            if self._closed:
                raise NativeCloudLoginDenied("native cloud login is closed")
            deadline = time.monotonic() + float(timeout_seconds)
            while self._authorization_code is None and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NativeCloudLoginTimeout("native cloud login callback timed out")
                self._condition.wait(remaining)
            if self._closed:
                raise NativeCloudLoginDenied("native cloud login closed before session issuance")
            if self._authorization_code is None:
                raise NativeCloudLoginDenied("native cloud login closed before callback")
            authorization = self._authorization_code
            self._authorization_code = None
        try:
            assertion = exchange_native_authorization_code(
                authorization, client=token_client
            )
            return issue_native_cloud_session(
                self._store,
                assertion,
                federated_identity_broker=self._federated_identity_broker,
                cloud_session_broker=self._cloud_session_broker,
                client_admission_verifier=self._client_admission_verifier,
                allowed_action_roots=self._allowed_action_roots,
                lifetime_seconds=session_lifetime_seconds,
            )
        finally:
            self.close()

    def close(self) -> None:
        """Stop the temporary local listener; the graph transaction simply expires."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            server = self._server
            thread = self._server_thread
            self._server = None
            self._server_thread = None
            self._condition.notify_all()
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

    def _new_server(self) -> _LoopbackCallbackServer:
        owner = self

        class CallbackHandler(BaseHTTPRequestHandler):
            server_version = "ArchHubNativeLogin/1"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                accepted = owner._accept_callback(
                    self.path,
                    str(self.headers.get("Host") or ""),
                )
                content = _COMPLETE_HTML if accepted else _INVALID_HTML
                self.send_response(200 if accepted else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'")
                self.end_headers()
                self.wfile.write(content)

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                self.send_error(405)

            def log_message(self, _format: str, *_args: object) -> None:
                # Default http.server logging would leak callback query values.
                return

        return _LoopbackCallbackServer(("127.0.0.1", 0), CallbackHandler)

    @staticmethod
    def _callback_path_from(
        started: StartedNativeAuthorization,
        port: int,
    ) -> str:
        query = parse_qs(urlsplit(started.authorization_url).query, strict_parsing=True)
        redirect_values = query.get("redirect_uri") or []
        if len(redirect_values) != 1:
            raise NativeCloudLoginDenied("native authorization URL has no callback URI")
        callback = urlsplit(redirect_values[0])
        if (
            callback.scheme != "http"
            or callback.hostname != "127.0.0.1"
            or callback.port != port
            or not callback.path.startswith("/")
            or callback.query
            or callback.fragment
            or callback.username is not None
            or callback.password is not None
        ):
            raise NativeCloudLoginDenied("native authorization callback is not loopback-bound")
        return callback.path

    def _accept_callback(self, target: str, host: str) -> bool:
        """Validate one browser redirect without retaining its query data."""
        try:
            raw_target = target.encode("utf-8")
        except UnicodeEncodeError:
            return False
        if len(raw_target) > _MAX_CALLBACK_TARGET_BYTES:
            return False
        with self._condition:
            if (
                self._closed
                or self._started is None
                or self._server is None
                or self._authorization_code is not None
                or host.strip().lower() != "127.0.0.1:%s" % self._server.server_port
            ):
                return False
            expected_path = self._callback_path
            transaction_root = self._started.transaction_root
        parsed = urlsplit(target)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.path != expected_path
            or parsed.fragment
        ):
            return False
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            return False
        if len(pairs) != 3 or {key for key, _value in pairs} != {"code", "state", "iss"}:
            return False
        values = dict(pairs)
        if any(not value for value in values.values()):
            return False
        try:
            authorization = self._native_authorization_broker.complete(
                self._store,
                self._protocol,
                transaction_root,
                state=values["state"],
                response_issuer=values["iss"],
                authorization_code=values["code"],
            )
        except (NativeAuthenticationDenied, ValueError, TypeError):
            return False
        with self._condition:
            if self._closed or self._authorization_code is not None:
                return False
            self._authorization_code = authorization
            self._condition.notify_all()
        return True


__all__ = [
    "NativeCloudLogin",
    "NativeCloudLoginDenied",
    "NativeCloudLoginTimeout",
    "StartedNativeCloudLogin",
]
