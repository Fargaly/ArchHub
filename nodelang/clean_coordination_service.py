"""Localhost endpoint for the single clean ArchHub graph owner."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Type

from .cell_secret_keys import WindowsDpapiSigningKeyProvider
from .clean_coordination_host import (
    CleanCoordinationHost,
    SignedCoordinationRequest,
)
from .runtime_caller_capability import WindowsDpapiCallerKeyStore
from .unified_authority_runtime import default_runtime_root, open_current_authority
from .universal_cell import InvalidCell


MAX_REQUEST_BYTES = 64 * 1024


class _CoordinationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, host: CleanCoordinationHost):
        self.coordination_host = host
        super().__init__(address, handler)


class CleanCoordinationRequestHandler(BaseHTTPRequestHandler):
    server: _CoordinationServer

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _write(self, status: int, payload: object) -> None:
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _admit_local_request(self) -> bool:
        origin = self.headers.get("Origin")
        if origin not in {None, "http://127.0.0.1", "http://localhost"}:
            self._write(403, {"ok": False, "error": "origin denied"})
            return False
        expected_port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in {
            "127.0.0.1:%s" % expected_port,
            "localhost:%s" % expected_port,
        }:
            self._write(403, {"ok": False, "error": "host denied"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write(404, {"ok": False, "error": "not found"})
            return
        if not self._admit_local_request():
            return
        authority = self.server.coordination_host.authority
        self._write(200, {
            "ok": True,
            "graph_id": authority.manifest.graph_id,
            "revision": authority.store.revision,
        })

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/coordination":
            self._write(404, {"ok": False, "error": "not found"})
            return
        if not self._admit_local_request():
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST_BYTES:
            self._write(413, {"ok": False, "error": "request size denied"})
            return
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            request = SignedCoordinationRequest.from_payload(payload)
            result = self.server.coordination_host.dispatch(request)
        except (InvalidCell, UnicodeError, json.JSONDecodeError) as exc:
            self._write(400, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._write(500, {"ok": False, "error": "coordination failed closed"})
            return
        self._write(200, result)


def build_service(
    host: str = "127.0.0.1",
    port: int = 8474,
    *,
    handler: Type[CleanCoordinationRequestHandler] = (
        CleanCoordinationRequestHandler
    ),
) -> tuple[_CoordinationServer, object]:
    if host != "127.0.0.1" or type(port) is not int or not 1024 <= port <= 65535:
        raise InvalidCell("clean coordination bind address is invalid")
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    location = open_current_authority(default_runtime_root(), provider)
    try:
        key_store = WindowsDpapiCallerKeyStore(
            WindowsDpapiCallerKeyStore.default_path()
        )
        graph_host = CleanCoordinationHost(location.authority, key_store)
        service = build_bound_service(graph_host, host, port, handler=handler)
    except Exception:
        location.authority.store.close()
        raise
    return service, location


def build_bound_service(
    graph_host: CleanCoordinationHost,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    handler: Type[CleanCoordinationRequestHandler] = (
        CleanCoordinationRequestHandler
    ),
) -> _CoordinationServer:
    """Bind an already-open authority host; port zero is test-only ephemeral."""
    if (
        host != "127.0.0.1"
        or type(port) is not int
        or port < 0
        or port > 65535
        or (port != 0 and port < 1024)
    ):
        raise InvalidCell("clean coordination bind address is invalid")
    return _CoordinationServer((host, port), handler, graph_host)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8474)
    args = parser.parse_args()
    service, location = build_service(args.host, args.port)
    try:
        service.serve_forever(poll_interval=0.25)
    finally:
        service.server_close()
        location.authority.store.close()


if __name__ == "__main__":
    main()


__all__ = [
    "CleanCoordinationRequestHandler",
    "MAX_REQUEST_BYTES",
    "build_bound_service",
    "build_service",
]
