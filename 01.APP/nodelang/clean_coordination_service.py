"""Localhost endpoint for the single clean ArchHub graph owner."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import psutil
from typing import Type

from .http_server import ThreadingHTTPServer
from .clean_coordination_host import CleanCoordinationHost
from .cell_authorization import AuthorizationDenied
from .runtime_activity import RuntimeClosing
from .universal_cell import InvalidCell


# A valid 64 KiB mailbox record can expand sixfold in a JSON envelope.
MAX_REQUEST_BYTES = 512 * 1024


class _CoordinationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, host: CleanCoordinationHost):
        self.coordination_host = host
        super().__init__(address, handler)

    def shutdown(self, *, timeout_seconds: float = 30.0):
        self.coordination_host.begin_shutdown()
        super().shutdown()
        if not self.coordination_host.activity.wait_for_idle(timeout_seconds):
            raise TimeoutError('coordination requests have not settled; application owner stays open')


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
        from .application_machine_transport import MachinePipePeer, _observe_machine_process
        try:
            pid = next((row.pid for row in psutil.net_connections(kind='tcp4')
                if tuple(row.laddr) == self.client_address
                and tuple(row.raddr) == self.server.server_address and row.pid), None)
            if pid is None:
                raise PermissionError('local caller process is unavailable')
            process = psutil.Process(pid)
            if process.username() != psutil.Process().username():
                raise PermissionError('local caller belongs to another user')
            self.coordination_peer = _observe_machine_process(pid) or MachinePipePeer(pid, process.create_time())
        except (psutil.Error, OSError) as refused:
            self._write(403, {"ok": False, "error": str(refused)})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write(404, {"ok": False, "error": "not found"})
            return
        if not self._admit_local_request():
            return
        graph_host = self.server.coordination_host
        self._write(200, {
            "ok": True,
            "graph_id": graph_host.store.authority_identity,
            "revision": graph_host.store.revision,
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
            json.dumps(payload, allow_nan=False)
            result = self.server.coordination_host.dispatch(payload, peer=self.coordination_peer)
        except RuntimeClosing as exc:
            self._write(503, {"ok":False, "error":str(exc)})
            return
        except AuthorizationDenied as exc:
            self._write(403, {"ok": False, "error": str(exc)})
            return
        except (InvalidCell, ValueError, UnicodeError) as exc:
            self._write(400, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._write(500, {"ok": False, "error": "coordination failed closed"})
            return
        self._write(200, result)


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


__all__ = ["CleanCoordinationRequestHandler", "MAX_REQUEST_BYTES", "build_bound_service"]
