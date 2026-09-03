"""Stable loopback gateway for exclusive Cell runtime worker handoff."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import http.client
from http.server import BaseHTTPRequestHandler
import ipaddress
import threading
import time
from typing import Callable, Iterator, Mapping
from urllib.parse import urlsplit

from .http_server import QuietThreadingHTTPServer


MAX_GATEWAY_BODY_BYTES = 1_048_576
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
})


class GatewayError(RuntimeError):
    pass


class GatewayUnavailable(GatewayError):
    pass


@dataclass(frozen=True, slots=True)
class BackendGeneration:
    url: str
    generation: int
    ownership_root: str


def _loopback_backend(value: str) -> tuple[str, int]:
    parsed = urlsplit(str(value))
    if parsed.scheme != "http" or parsed.username or parsed.password:
        raise GatewayError("runtime backend must be an unauthenticated HTTP URL")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise GatewayError("runtime backend URL must contain only origin")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise GatewayError("runtime backend must use a numeric loopback address") from exc
    if not address.is_loopback or parsed.port is None:
        raise GatewayError("runtime backend must use a loopback address and port")
    return str(address), int(parsed.port)


class RuntimeAdmissionGate:
    """Bounded request admission around one graph-proven backend generation."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._backend: BackendGeneration | None = None
        self._draining = True
        self._inflight: dict[int, int] = {}

    @property
    def backend(self) -> BackendGeneration | None:
        with self._condition:
            return self._backend

    @contextmanager
    def admit(self, timeout: float = 15.0) -> Iterator[BackendGeneration]:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._draining or self._backend is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GatewayUnavailable("runtime handoff admission timed out")
                self._condition.wait(remaining)
            backend = self._backend
            self._inflight[backend.generation] = (
                self._inflight.get(backend.generation, 0) + 1
            )
        try:
            yield backend
        finally:
            with self._condition:
                count = self._inflight.get(backend.generation, 0) - 1
                if count <= 0:
                    self._inflight.pop(backend.generation, None)
                else:
                    self._inflight[backend.generation] = count
                self._condition.notify_all()

    def begin_drain(
        self, expected_generation: int, *, timeout: float = 30.0
    ) -> BackendGeneration:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            backend = self._backend
            if backend is None or backend.generation != int(expected_generation):
                raise GatewayError("runtime drain generation is stale")
            self._draining = True
            while self._inflight.get(backend.generation, 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._draining = False
                    self._condition.notify_all()
                    raise GatewayUnavailable("runtime drain timed out")
                self._condition.wait(remaining)
            return backend

    def activate(self, backend: BackendGeneration) -> None:
        _loopback_backend(backend.url)
        if backend.generation <= 0 or not backend.ownership_root:
            raise GatewayError("runtime backend authority is incomplete")
        with self._condition:
            previous = self._backend
            if previous is not None and backend.generation <= previous.generation:
                raise GatewayError("runtime backend generation did not advance")
            if previous is not None and not self._draining:
                raise GatewayError("runtime backend cannot switch before drain")
            self._backend = backend
            self._draining = False
            self._condition.notify_all()


class RuntimeGateway:
    """Same-origin HTTP gateway whose public listener survives worker changes."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        admission_timeout: float = 15.0,
        backend_timeout: float = 30.0,
        activation_verifier: Callable[[BackendGeneration], None] | None = None,
    ) -> None:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise GatewayError("runtime gateway must bind to loopback")
        except ValueError as exc:
            raise GatewayError("runtime gateway host must be numeric loopback") from exc
        if activation_verifier is None:
            raise GatewayError(
                "runtime gateway requires a graph-backed activation verifier"
            )
        self.gate = RuntimeAdmissionGate()
        self.admission_timeout = float(admission_timeout)
        self.backend_timeout = float(backend_timeout)
        self.activation_verifier = activation_verifier
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def _error(self, status: int, message: bytes, *, retry=False):
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                if retry:
                    self.send_header("Retry-After", "1")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(message)

            def _body(self) -> bytes:
                if self.headers.get("Transfer-Encoding"):
                    raise GatewayError("chunked gateway requests are not admitted")
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise GatewayError("invalid request content length") from exc
                if length < 0 or length > MAX_GATEWAY_BODY_BYTES:
                    raise GatewayError("request body exceeds gateway limit")
                return self.rfile.read(length) if length else b""

            def _forward(self):
                try:
                    body = self._body()
                except GatewayError as exc:
                    self._error(413, str(exc).encode("utf-8"))
                    return
                try:
                    with owner.gate.admit(owner.admission_timeout) as backend:
                        host_value, port_value = _loopback_backend(backend.url)
                        headers = {
                            name: value for name, value in self.headers.items()
                            if name.lower() not in _HOP_BY_HOP
                            and name.lower() not in {"host", "content-length"}
                        }
                        headers["Host"] = "%s:%d" % (host_value, port_value)
                        headers["Content-Length"] = str(len(body))
                        connection = http.client.HTTPConnection(
                            host_value, port_value, timeout=owner.backend_timeout
                        )
                        try:
                            connection.request(self.command, self.path, body, headers)
                            response = connection.getresponse()
                            payload = response.read()
                            self.send_response(response.status, response.reason)
                            for name, value in response.getheaders():
                                if (
                                    name.lower() not in _HOP_BY_HOP
                                    and name.lower() != "content-length"
                                ):
                                    self.send_header(name, value)
                            self.send_header("Content-Length", str(len(payload)))
                            self.send_header(
                                "X-ArchHub-Runtime-Generation",
                                str(backend.generation),
                            )
                            self.end_headers()
                            if self.command != "HEAD":
                                self.wfile.write(payload)
                        finally:
                            connection.close()
                except GatewayUnavailable as exc:
                    self._error(503, str(exc).encode("utf-8"), retry=True)
                except (GatewayError, OSError, http.client.HTTPException) as exc:
                    self._error(502, ("runtime backend unavailable: " + str(exc)).encode("utf-8"))

            do_GET = _forward
            do_HEAD = _forward
            do_POST = _forward
            do_PUT = _forward
            do_PATCH = _forward
            do_DELETE = _forward
            do_OPTIONS = _forward

        self.httpd = QuietThreadingHTTPServer((host, int(port)), Handler)
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def start(self) -> "RuntimeGateway":
        if self.thread is None:
            self.thread = threading.Thread(
                target=self.httpd.serve_forever,
                name="archhub-runtime-gateway",
                daemon=True,
            )
            self.thread.start()
        return self

    def activate(self, backend: BackendGeneration) -> None:
        self.activation_verifier(backend)
        self.gate.activate(backend)

    def close(self) -> None:
        if self.thread is not None:
            self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None


__all__ = [
    "BackendGeneration", "GatewayError", "GatewayUnavailable",
    "RuntimeAdmissionGate", "RuntimeGateway",
]
