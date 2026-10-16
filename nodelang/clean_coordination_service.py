"""Localhost endpoint for the single clean ArchHub graph owner."""

from __future__ import annotations

import os
import time
from http.server import BaseHTTPRequestHandler
import json
from typing import Type

from .cell_secret_keys import WindowsDpapiSigningKeyProvider
from .http_server import ThreadingHTTPServer
from .clean_coordination_host import (
    CleanCoordinationHost,
    SignedCoordinationRequest,
)
from .runtime_caller_capability import WindowsDpapiCallerKeyStore
from .runtime_activity import RuntimeClosing
from .unified_authority_runtime import open_current_authority
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
        except RuntimeClosing as exc:
            self._write(503, {"ok":False, "error":str(exc)})
            return
        except (InvalidCell, UnicodeError, json.JSONDecodeError) as exc:
            self._write(400, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._write(500, {"ok": False, "error": "coordination failed closed"})
            return
        self._write(200, result)


def _service_boot_note(line: str, runtime_root=None) -> None:
    try:
        from pathlib import Path as _Path
        root = (
            _Path(runtime_root)
            if runtime_root
            else _Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "unified-authority"
        )
        if root.is_dir():
            with (root / "boot-timing.log").open("a", encoding="utf-8") as log:
                log.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  boot phase: " + line + chr(10))
    except Exception:
        pass


def build_service(
    host: str = "127.0.0.1",
    *,
    port: int,
    handler: Type[CleanCoordinationRequestHandler] = (
        CleanCoordinationRequestHandler
    ),
    runtime_root,
) -> tuple[_CoordinationServer, object]:
    if host != "127.0.0.1" or type(port) is not int or not 1024 <= port <= 65535:
        raise InvalidCell("clean coordination bind address is invalid")
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    # The root is REQUIRED, with no default here. A library that defaults
    # to the founder's live generation makes owning production the thing
    # that happens when a caller says nothing -- and the owner fence cannot
    # help, because a court that acquires a free live lock, asserts, and
    # exits was a perfectly legitimate owner for its whole short life, and
    # took the founder's service down when it left. Only the entry point
    # below is allowed to name the live graph.
    # The port is required for the same reason the root is, and the pair
    # is worse than either alone: a caller who says nothing would take its
    # own graph and the founder's port. During any restart window that
    # binds 8474 successfully, backed by a throwaway fixture, and every
    # agent reaching it enrols against a temp directory and is told ok.
    _opening = time.monotonic()
    location = open_current_authority(runtime_root, provider)
    _service_boot_note(
        "open_current_authority %.1fs" % (time.monotonic() - _opening),
        runtime_root,
    )
    try:
        _binding = time.monotonic()
        key_store = WindowsDpapiCallerKeyStore(
            WindowsDpapiCallerKeyStore.default_path()
        )
        graph_host = CleanCoordinationHost(
            location.authority,
            key_store,
            runtime_root=runtime_root,
        )
        service = build_bound_service(graph_host, host, port, handler=handler)
        _service_boot_note(
            "bind coordination %.1fs" % (time.monotonic() - _binding),
            runtime_root,
        )
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


def main(argv=None):
    """Compatibility module entry: the installed desktop owns every surface."""
    if argv:
        raise ValueError('independent server launch flags are retired')
    from .desktop import main as desktop_main
    return desktop_main()


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["CleanCoordinationRequestHandler", "MAX_REQUEST_BYTES", "build_bound_service", "build_service"]
