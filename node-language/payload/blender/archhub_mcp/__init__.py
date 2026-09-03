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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg: str, status: int = 500) -> None:
        self._send_json({"ok": False, "status": "error", "error": msg}, status)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
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
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


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
