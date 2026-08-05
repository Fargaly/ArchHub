"""Localhost endpoint for the single clean ArchHub graph owner."""

from __future__ import annotations

import argparse
import urllib.request
import urllib.error
import sys
import threading
import time
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
from .universal_cell import DatabaseOwnerConflict, InvalidCell


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


def _healthy_owner_is_serving(host: str, port: int) -> bool:
    """True when a live instance already answers /health on this address."""
    try:
        with urllib.request.urlopen(
            "http://%s:%d/health" % (host, port), timeout=3
        ) as response:
            return json.loads(response.read().decode("utf-8")).get("ok") is True
    except Exception:
        return False


def _build_canvas_server(location, host: str, port: int):
    """Stand the browser canvas over the SAME owned authority.

    One process, one lock, two surfaces. The canvas opens -- never installs
    -- its subsystems: an owner is an operator, and installation is a
    migration someone runs deliberately.
    """
    from .application_server import ApplicationServer
    from .clean_browser_authority import open_clean_browser_authority
    from .runtime_caller_capability import WindowsDpapiCallerKeyStore
    from .unified_authority import composition_root
    from .cell_protocols import read_relation

    authority = location.authority
    key_store = WindowsDpapiCallerKeyStore(
        WindowsDpapiCallerKeyStore.default_path()
    )
    caller = key_store.bind_bootstrap(authority, "founder.bootstrap")
    browser = open_clean_browser_authority(authority, caller=caller)
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    grand = composition_root(authority, "Grand Map", caller=caller)
    scope = next(
        member.participant_id
        for member in read_relation(
            authority.store.snapshot(), grand, budget=100_000
        )
        if member.role_id == authority.role("composition")
    )
    return ApplicationServer.from_unified_authority(
        authority,
        browser_authority=browser,
        scope_caller=caller,
        scope_root=scope,
        authority_key_provider=provider,
        host=host,
        port=port,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8474)
    parser.add_argument("--canvas-port", type=int, default=8475)
    parser.add_argument(
        "--no-canvas",
        action="store_true",
        help="serve coordination only (a graph without canvas subsystems)",
    )
    args = parser.parse_args()
    # A supervisor restarts this unconditionally. Without these two exits a
    # second instance starts, blocks forever on the generation owner lock the
    # first one holds, and never binds: a live process serving nothing, which
    # is worse than no process because /health cannot report it.
    if _healthy_owner_is_serving(args.host, args.port):
        print(
            "clean coordination service already serving on %s:%d"
            % (args.host, args.port),
            file=sys.stderr,
        )
        return 0
    try:
        service, location = build_service(args.host, args.port)
    except DatabaseOwnerConflict as exc:
        print("clean coordination service cannot own the graph: %s" % exc,
              file=sys.stderr)
        return 75
    except OSError as exc:
        print("clean coordination service cannot bind %s:%d: %s"
              % (args.host, args.port, exc), file=sys.stderr)
        return 76
    # Both surfaces or neither. A half-serving owner holding the lock is
    # worse than no owner: it blocks recovery while delivering nothing, and
    # from outside it looks healthy because something answers. Any failure
    # past this point releases the lock and exits distinctly.
    canvas = None
    if not args.no_canvas:
        try:
            canvas = _build_canvas_server(
                location, args.host, args.canvas_port
            ).start()
        except Exception as exc:
            print(
                "clean owner cannot stand the canvas surface: %s" % exc,
                file=sys.stderr,
            )
            service.server_close()
            location.authority.store.close()
            return 77
        print(
            "canvas serving on %s" % canvas.url,
            file=sys.stderr,
        )
    # Both-or-neither holds at runtime too, and the watcher is the MAIN
    # thread: if the watcher dies the process dies and the OS releases the
    # lock, so "who watches the watchdog" bottoms out in process death
    # rather than in another thread. Liveness is a bounded probe of each
    # SURFACE, not thread aliveness -- a wedged thread is alive and serving
    # nothing, the exact state last night's dead-pid descriptor taught.
    # Teardown is ordered: the canvas socket closes before coordination, so
    # there is no window where the canvas answers while coordination
    # refuses and two agents see different halves of one owner.
    serve_thread = threading.Thread(
        target=lambda: service.serve_forever(poll_interval=0.25),
        name="clean-owner-coordination",
        daemon=True,
    )
    serve_thread.start()

    def _surface_answers(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                response.read(1)
                return True
        except urllib.error.HTTPError:
            # An HTTP status is an answer; refusing unauthenticated
            # requests is the canvas surface working, not failing.
            return True
        except Exception:
            return False

    coordination_url = "http://%s:%d/health" % (args.host, args.port)
    canvas_url = None if canvas is None else (
        canvas.url + "/api/universal/canvas"
    )
    failed_probes = 0
    exit_code = 0
    try:
        while True:
            time.sleep(5.0)
            if not serve_thread.is_alive():
                print("clean owner: coordination worker stopped",
                      file=sys.stderr)
                exit_code = 78
                break
            healthy = _surface_answers(coordination_url) and (
                canvas_url is None or _surface_answers(canvas_url)
            )
            if healthy:
                failed_probes = 0
                continue
            failed_probes += 1
            if failed_probes >= 3:
                print(
                    "clean owner: a surface stopped answering bounded "
                    "probes; taking the whole owner down for restart",
                    file=sys.stderr,
                )
                exit_code = 78
                break
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        if canvas is not None:
            canvas.close()
        service.shutdown()
        service.server_close()
        location.authority.store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CleanCoordinationRequestHandler",
    "MAX_REQUEST_BYTES",
    "build_bound_service",
    "build_service",
]
