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
PORT_FIRST = 48886           # first-free in this range wins (multi-session)
PORT_LAST  = 48899
ROUTE_PREFIX = "/max-mcp"

# Where session metadata lands so ArchHub's broker can route to a
# specific 3ds Max instance. Mirrors Revit's session-file pattern.
import os as _os
import json as _json
from pathlib import Path as _Path
from datetime import datetime as _dt, timezone as _tz
SESSIONS_DIR = (
    _Path(_os.environ.get("LOCALAPPDATA",
                           str(_Path.home() / "AppData" / "Local")))
    / "ArchHub" / "sessions"
)
_SESSION_FILE: _Path | None = None
_BOUND_PORT: int | None = None


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


def _bind_first_free(host: str) -> "ThreadingHTTPServer | None":
    """Try ports in [PORT_FIRST..PORT_LAST]. First successful bind wins.

    Required for multi-session 3ds Max — without this, a second Max
    instance silently fails to bind 48886 and stays invisible to
    ArchHub. Mirrors Revit DLL's port-range bind from v0.27.5.
    """
    for p in range(PORT_FIRST, PORT_LAST + 1):
        try:
            srv = ThreadingHTTPServer((host, p), _Handler)
        except OSError:
            continue
        global _BOUND_PORT
        _BOUND_PORT = p
        print(f"[MaxMCP] Listening on http://{host}:{p}{ROUTE_PREFIX}")
        return srv
    print(f"[MaxMCP] Could not bind any port in [{PORT_FIRST}..{PORT_LAST}]")
    return None


def _start_server() -> None:
    srv = _bind_first_free(HOST)
    if srv is None:
        return
    _publish_session_file()
    _start_heartbeat_thread()
    srv.serve_forever()


# ---------------------------------------------------------------------------
# Session registry — ArchHub broker scans this directory.
# ---------------------------------------------------------------------------
def _scene_title() -> str:
    try:
        return f"{rt.maxFilePath}{rt.maxFileName}".strip()
    except Exception:
        return ""


def _max_version() -> str:
    try:
        return str(rt.maxVersion()[0])
    except Exception:
        return ""


def _publish_session_file() -> None:
    global _SESSION_FILE
    if _BOUND_PORT is None:
        return
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    pid = _os.getpid()
    path = SESSIONS_DIR / f"max-{pid}.json"
    _write_session(path, pid, heartbeat=False)
    _SESSION_FILE = path


def _write_session(path: "_Path", pid: int, heartbeat: bool) -> None:
    now = _dt.now(_tz.utc).isoformat()
    payload = {
        "session_id":     f"max-{pid}",
        "family":         "max",
        "pid":            pid,
        "port":           _BOUND_PORT,
        "version":        _max_version(),
        "doc_title":      _scene_title(),
        "started_at":     now,
        "last_heartbeat": now,
        "heartbeat":      heartbeat,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(payload), encoding="utf-8")
    try:
        tmp.replace(path)
    except Exception:
        path.write_text(_json.dumps(payload), encoding="utf-8")


def _start_heartbeat_thread() -> None:
    pid = _os.getpid()

    def _loop() -> None:
        import time as _t
        while True:
            _t.sleep(10)
            if _SESSION_FILE is None:
                continue
            try:
                _write_session(_SESSION_FILE, pid, heartbeat=True)
            except Exception:
                pass
    threading.Thread(target=_loop, name="MaxMCP-Heartbeat",
                     daemon=True).start()


def _cleanup_session_file() -> None:
    if _SESSION_FILE is not None and _SESSION_FILE.exists():
        try:
            _SESSION_FILE.unlink()
        except Exception:
            pass


import atexit as _atexit
_atexit.register(_cleanup_session_file)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
def _boot() -> None:
    threading.Thread(target=_start_server, name="MaxMCP-HTTP", daemon=True).start()
    _install_timer()


_boot()
