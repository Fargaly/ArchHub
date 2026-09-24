"""ArchHub Blender addon — HTTP bridge for live parametric modeling.

Exposes a minimal REST API on localhost:9876 so ArchHub can:
  GET  /ping      — health check
  GET  /info      — scene state
  POST /execute   — run bpy Python code
  POST /render    — trigger a render, save to file

CRITICAL: All bpy calls must run on Blender's main thread.
We use bpy.app.timers.register(fn, first_interval=0) to post work
from the HTTP thread to the main thread, with a threading.Event
for the response handshake.
"""

bl_info = {
    "name":        "ArchHub MCP Bridge",
    "author":      "ArchHub",
    "version":     (0, 6, 0),
    "blender":     (3, 6, 0),
    "location":    "Background service",
    "description": "Live HTTP bridge for ArchHub parametric design.",
    "category":    "Development",
}

import bpy
import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

PORT = int(os.environ.get("ARCHHUB_BLENDER_PORT", "9876"))
_server: Optional[HTTPServer] = None
_server_thread: Optional[threading.Thread] = None


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
# Main-thread dispatcher
# ---------------------------------------------------------------------------

class _MainThreadCall:
    """Packages a callable + args to run on the main Blender thread."""

    def __init__(self, fn, args=(), kwargs=None):
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}
        self._event = threading.Event()
        self._result = None
        self._error: Optional[str] = None

    def dispatch(self, timeout: float = 60.0) -> Any:
        """Register on main thread and block until done."""
        bpy.app.timers.register(self._run_on_main, first_interval=0)
        if not self._event.wait(timeout=timeout):
            raise TimeoutError(f"Main-thread call timed out after {timeout}s")
        if self._error:
            raise RuntimeError(self._error)
        return self._result

    def _run_on_main(self) -> None:
        try:
            self._result = self._fn(*self._args, **self._kwargs)
        except Exception as ex:
            self._error = f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"
        finally:
            self._event.set()
        return None   # Do not re-register the timer


def _call_main(fn, *args, timeout: float = 60.0, **kwargs) -> Any:
    return _MainThreadCall(fn, args, kwargs).dispatch(timeout=timeout)


# ---------------------------------------------------------------------------
# bpy operations (always called from main thread via _call_main)
# ---------------------------------------------------------------------------

def _ping_main() -> dict:
    return {
        "ok": True,
        "version": ".".join(str(v) for v in bl_info["version"]),
        "blender": bpy.app.version_string,
        "port": PORT,
    }


def _info_main() -> dict:
    scene = bpy.context.scene
    blend_file = bpy.data.filepath or "(unsaved)"
    objects = [
        {
            "name": obj.name,
            "type": obj.type,
            "visible": not obj.hide_viewport,
        }
        for obj in scene.objects
    ]
    return {
        "ok": True,
        "file": blend_file,
        "scene": scene.name,
        "frame_current": scene.frame_current,
        "objects": objects,
        "object_count": len(objects),
        "engine": scene.render.engine,
    }


def _execute_main(code: str) -> dict:
    """Execute arbitrary bpy Python code. Returns {"ok": True, "result": ...}."""
    namespace: dict = {"bpy": bpy, "result": None}
    try:
        exec(compile(code, "<archhub>", "exec"), namespace)
        result = namespace.get("result")
        # Ensure JSON-serialisable
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            result = str(result)
        return {"ok": True, "result": result}
    except Exception as ex:
        return {
            "ok": False,
            "status": "error",
            "error": f"{type(ex).__name__}: {ex}",
            "traceback": traceback.format_exc(),
        }


def _render_main(output_path: str, engine: str, samples: int,
                 resolution: list) -> dict:
    """Set render settings and render to file."""
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = "PNG"
    if resolution and len(resolution) >= 2:
        scene.render.resolution_x = int(resolution[0])
        scene.render.resolution_y = int(resolution[1])
    scene.render.resolution_percentage = 100

    # Samples (Cycles vs Eevee)
    if engine == "CYCLES":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
    elif engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = samples

    try:
        bpy.ops.render.render(write_still=True)
        return {"ok": True, "status": "ok", "output_path": output_path}
    except Exception as ex:
        return {
            "ok": False,
            "status": "error",
            "error": f"{type(ex).__name__}: {ex}",
        }


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _ArchHubHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler. Runs on the server thread — uses _call_main for bpy."""

    def log_message(self, fmt, *args) -> None:
        pass   # suppress default Apache-style log

    def _read_json_body(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg: str, status: int = 500) -> None:
        self._send_json({"ok": False, "status": "error", "error": msg}, status)

    def _refused(self, path: str) -> bool:
        refusal = bridge_refusal(self.headers, require_token=path != "/ping")
        if refusal is None:
            return False
        self._send_error_json(refusal[1], refusal[0])
        return True

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if self._refused(path):
            return
        if path == "/ping":
            try:
                result = _call_main(_ping_main, timeout=5.0)
                self._send_json(result)
            except Exception as ex:
                self._send_error_json(str(ex))

        elif path == "/info":
            try:
                result = _call_main(_info_main, timeout=10.0)
                self._send_json(result)
            except Exception as ex:
                self._send_error_json(str(ex))

        else:
            self._send_json({"ok": False, "error": f"Unknown endpoint: {path}"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if self._refused(path):
            return
        body = self._read_json_body()
        if body is None:
            self._send_error_json("Invalid JSON body", 400)
            return

        if path in ("/execute", "/exec"):
            code = body.get("code", "")
            if not code:
                self._send_error_json("Missing 'code' in body", 400)
                return
            try:
                result = _call_main(_execute_main, code, timeout=120.0)
                self._send_json(result)
            except TimeoutError:
                self._send_error_json("Execution timed out (120s)")
            except Exception as ex:
                self._send_error_json(str(ex))

        elif path == "/render":
            output_path = body.get("output_path", "")
            if not output_path:
                self._send_error_json("Missing 'output_path' in body", 400)
                return
            engine     = body.get("engine", "BLENDER_EEVEE")
            samples    = int(body.get("samples", 64))
            resolution = body.get("resolution", [1280, 720])
            try:
                result = _call_main(
                    _render_main, output_path, engine, samples, resolution,
                    timeout=600.0,
                )
                self._send_json(result)
            except TimeoutError:
                self._send_error_json("Render timed out (600s)")
            except Exception as ex:
                self._send_error_json(str(ex))

        else:
            self._send_json({"ok": False, "error": f"Unknown endpoint: {path}"}, 404)

    def do_OPTIONS(self) -> None:
        # Only a browser sends a preflight; it gets no CORS grant.
        self._send_error_json("browser requests are refused; ArchHub calls this bridge directly", 403)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def _start_server() -> None:
    global _server, _server_thread
    if _server is not None:
        return   # already running
    _server = HTTPServer(("127.0.0.1", PORT), _ArchHubHandler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    print(f"[ArchHub] HTTP bridge started on http://127.0.0.1:{PORT}")


def _stop_server() -> None:
    global _server, _server_thread
    if _server is not None:
        _server.shutdown()
        _server = None
    _server_thread = None
    print("[ArchHub] HTTP bridge stopped.")


def register():
    _start_server()


def unregister():
    _stop_server()


if __name__ == "__main__":
    register()
