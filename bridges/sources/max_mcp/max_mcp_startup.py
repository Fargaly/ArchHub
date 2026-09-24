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


# --- BEGIN ArchHub bridge caller check (identical in every Python bridge) ---
# Every route but /ping runs only for a caller that sends this install's
# bridge secret; browser requests are refused and no CORS header is sent.
# The ArchHub app (nodelang/host_bridge_auth.py) creates the secret in its
# credential store, the Windows Credential Locker through keyring; it is read
# back here exactly as keyring wrote it and compared in constant time.
import ctypes as _ah_ctypes
import hmac as _ah_hmac
from ctypes import wintypes as _ah_wintypes

BRIDGE_TOKEN_HEADER = "X-ArchHub-Bridge-Token"
_BRIDGE_SECRET_SERVICE = "ArchHub"
_BRIDGE_SECRET_USER = "archhub-host-bridge"


class _AhCredential(_ah_ctypes.Structure):
    _fields_ = [("Flags", _ah_wintypes.DWORD), ("Type", _ah_wintypes.DWORD),
                ("TargetName", _ah_wintypes.LPWSTR), ("Comment", _ah_wintypes.LPWSTR),
                ("LastWritten", _ah_wintypes.FILETIME),
                ("CredentialBlobSize", _ah_wintypes.DWORD),
                ("CredentialBlob", _ah_ctypes.POINTER(_ah_ctypes.c_ubyte)),
                ("Persist", _ah_wintypes.DWORD), ("AttributeCount", _ah_wintypes.DWORD),
                ("Attributes", _ah_ctypes.c_void_p), ("TargetAlias", _ah_wintypes.LPWSTR),
                ("UserName", _ah_wintypes.LPWSTR)]


def _ah_read_credential(target):
    """(user, secret) of one generic Windows credential, or None."""
    try:
        advapi = _ah_ctypes.WinDLL("advapi32", use_last_error=True)
    except (OSError, AttributeError):
        return None
    read = advapi.CredReadW
    read.argtypes = (_ah_wintypes.LPCWSTR, _ah_wintypes.DWORD, _ah_wintypes.DWORD,
                     _ah_ctypes.POINTER(_ah_ctypes.POINTER(_AhCredential)))
    read.restype = _ah_wintypes.BOOL
    advapi.CredFree.argtypes = (_ah_ctypes.c_void_p,)
    found = _ah_ctypes.POINTER(_AhCredential)()
    if not read(target, 1, 0, _ah_ctypes.byref(found)):  # CRED_TYPE_GENERIC
        return None
    try:
        cred = found.contents
        size = int(cred.CredentialBlobSize)
        if not cred.CredentialBlob or size <= 0 or size > 4096 or size % 2:
            return None
        blob = _ah_ctypes.string_at(cred.CredentialBlob, size)
        return (cred.UserName or "", blob.decode("utf-16-le"))
    except (ValueError, UnicodeDecodeError):
        return None
    finally:
        advapi.CredFree(found)


def bridge_secret(service=_BRIDGE_SECRET_SERVICE, user=_BRIDGE_SECRET_USER):
    """The bridge secret where keyring put it: the service target, else user@service."""
    found = _ah_read_credential(service)
    if found is None or found[0] != user:
        found = _ah_read_credential(user + "@" + service)
    if found is None or found[0] != user or len(found[1]) < 32:
        return None
    return found[1]


def bridge_refusal(headers, require_token=True):
    """None when the caller may proceed, else (http_status, reason)."""
    if headers.get("Origin") is not None or headers.get("Sec-Fetch-Mode") is not None:
        return 403, "browser requests are refused; ArchHub calls this bridge directly"
    if not require_token:
        return None
    try:
        secret = bridge_secret()
    except Exception:
        secret = None
    if not secret:
        return 503, "ArchHub has not provisioned this bridge's caller secret; open ArchHub once"
    given = headers.get(BRIDGE_TOKEN_HEADER) or ""
    if not _ah_hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8")):
        return 401, "caller is not authenticated"
    return None
# --- END ArchHub bridge caller check ---


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

    def _reply(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refused(self, path: str) -> bool:
        refusal = bridge_refusal(self.headers, require_token=path not in ("/", "/ping"))
        if refusal is None:
            return False
        self._reply({"status": "error", "error": refusal[1]}, refusal[0])
        return True

    def do_OPTIONS(self):
        # Only a browser sends a preflight; it gets no CORS grant.
        self._reply({"status": "error",
                     "error": "browser requests are refused; ArchHub calls this bridge directly"}, 403)

    def do_GET(self):
        path = self._route()
        if self._refused(path):
            return
        if path in ("/", "/ping"):
            return self._reply(_enqueue_and_wait("ping", {}))
        if path == "/info":
            return self._reply(_enqueue_and_wait("info", {}))
        return self._reply({"status": "error", "error": f"Unknown route: {path}"})

    def do_POST(self):
        path = self._route()
        if self._refused(path):
            return
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


# Inside 3ds Max this always boots. A court loads the handler without binding
# the shared 48886-48899 range, where a live Revit or AutoCAD may be listening.
if _os.environ.get("ARCHHUB_MAXMCP_AUTOSTART", "1") != "0":
    _boot()
