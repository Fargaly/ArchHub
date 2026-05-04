"""
MaxMCP — embedded HTTP server inside 3ds Max for live MCP control.

Place this file at:
    %LOCALAPPDATA%\\Autodesk\\3dsMax\\<version> - 64bit\\ENU\\scripts\\startup\\max_mcp_startup.py

3ds Max ships with Python 3 + PySide2 + pymxs. The Qt event loop is the same loop
3ds Max uses for UI, so a QTimer dequeue runs work on the safe thread.

Default URL: http://localhost:48886/max-mcp/<endpoint>
Verify with:  http://localhost:48886/max-mcp/ping
"""
from __future__ import annotations

import json
import queue
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:
    from PySide2 import QtCore
    from PySide2.QtWidgets import QApplication
except Exception:                                   # pragma: no cover
    from PySide6 import QtCore                      # newer Max
    from PySide6.QtWidgets import QApplication

from pymxs import runtime as rt


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 48886
ROUTE_PREFIX = "/max-mcp"


# ---------------------------------------------------------------------------
# Work queue: HTTP threads enqueue, a QTimer in the main thread dequeues
# ---------------------------------------------------------------------------
_work_queue: "queue.Queue[tuple[str, dict, queue.Queue]]" = queue.Queue()


def _enqueue_and_wait(kind: str, payload: dict, timeout: float = 180.0) -> dict:
    reply: queue.Queue = queue.Queue(maxsize=1)
    _work_queue.put((kind, payload, reply))
    try:
        return reply.get(timeout=timeout)
    except queue.Empty:
        return {"status": "error", "error": "Timed out waiting for 3ds Max."}


# ---------------------------------------------------------------------------
# Main-thread executor
# ---------------------------------------------------------------------------
def _run_kind(kind: str, payload: dict) -> dict:
    if kind == "ping":
        return {"status": "ok", "service": "max-mcp", "version": "0.2.0"}

    if kind == "info":
        return {
            "status": "ok",
            "max_version": str(rt.maxVersion()[0]),
            "scene_file": str(rt.maxFilePath) + str(rt.maxFileName),
            "object_count": int(rt.objects.count),
            "current_time": float(rt.currentTime),
        }

    if kind == "exec_python":
        code = payload.get("code") or ""
        if not code:
            return {"status": "error", "error": "Missing 'code'."}
        ns: dict[str, Any] = {
            "rt": rt,
            "result": None,
            "__name__": "__mcp_exec__",
        }
        try:
            with rt.UndoOn():
                exec(code, ns)
            value = ns.get("result")
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            return {"status": "ok", "result": value}
        except Exception as ex:
            return {
                "status": "error",
                "error": f"{type(ex).__name__}: {ex}",
                "traceback": traceback.format_exc(),
            }

    if kind == "exec_maxscript":
        script = payload.get("script") or ""
        if not script:
            return {"status": "error", "error": "Missing 'script'."}
        try:
            value = rt.execute(script)
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            return {"status": "ok", "result": value}
        except Exception as ex:
            return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}

    return {"status": "error", "error": f"Unknown kind: {kind}"}


def _drain_queue() -> None:
    while True:
        try:
            kind, payload, reply = _work_queue.get_nowait()
        except queue.Empty:
            return
        try:
            result = _run_kind(kind, payload)
        except Exception as ex:
            result = {"status": "error", "error": f"Executor crash: {ex}"}
        try:
            reply.put_nowait(result)
        except Exception:
            pass


_timer: QtCore.QTimer | None = None


def _install_timer() -> None:
    global _timer
    if _timer is not None:
        return
    app = QApplication.instance()
    if app is None:
        # No Qt app yet — Max not fully booted. Try again in a moment.
        QtCore.QTimer.singleShot(500, _install_timer)
        return
    _timer = QtCore.QTimer()
    _timer.setInterval(50)               # 20 Hz drain
    _timer.timeout.connect(_drain_queue)
    _timer.start()


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):    # silence default stderr logging
        pass

    def _route(self) -> str:
        path = (self.path or "/").split("?", 1)[0].rstrip("/")
        if path.startswith(ROUTE_PREFIX):
            path = path[len(ROUTE_PREFIX):]
        return path or "/"

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw}

    def _reply(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self._route()
        if path in ("/", "/ping"):
            return self._reply(_enqueue_and_wait("ping", {}))
        if path == "/info":
            return self._reply(_enqueue_and_wait("info", {}))
        return self._reply({"status": "error", "error": f"Unknown route: {path}"})

    def do_POST(self):
        path = self._route()
        body = self._read_body()
        if path == "/exec":
            return self._reply(_enqueue_and_wait("exec_python", body))
        if path == "/exec_maxscript":
            return self._reply(_enqueue_and_wait("exec_maxscript", body))
        return self._reply({"status": "error", "error": f"Unknown route: {path}"})


def _start_server() -> None:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    print(f"[MaxMCP] Listening on http://{HOST}:{PORT}{ROUTE_PREFIX}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
def _boot() -> None:
    threading.Thread(target=_start_server, name="MaxMCP-HTTP", daemon=True).start()
    _install_timer()


_boot()
