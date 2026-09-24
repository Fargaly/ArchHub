#! python 3
# ^ Rhino-8 engine selector — MUST be line 1. This addon is CPython-3 only
#   (uses `from __future__ import annotations`, `http.server`, PEP-526
#   variable annotations). Rhino 8's default `_-RunPythonScript` engine is
#   IronPython 2.7, under which this file is a hard SyntaxError and the
#   server never binds. The `#! python 3` shebang forces the CPython-3
#   interpreter so the bridge actually starts. Do not remove.
"""ArchHub Rhino MCP bridge — HTTP server inside Rhino's embedded Python.

Drop this file into your Rhino scripts folder, then in Rhino run:
    _-RunPythonScript "C:\\Path\\To\\archhub_mcp.py"

Or place in `%APPDATA%\\McNeel\\Rhinoceros\\<version>\\scripts\\` and
auto-load via Rhino → Tools → PythonScript → Edit → Library.

Endpoints (default port 9879):
    GET  /ping         — health check
    GET  /info         — active doc info (path, units, layers, layer count)
    POST /execute      — run Python code with `rs`, `Rhino`, `sc`, `doc` globals
    GET  /screenshot   — capture current viewport to a PNG (returns path)

Marshalling — Rhino's API isn't thread-safe; HTTP handlers MUST hand work
to Rhino's UI thread. We use `Rhino.RhinoApp.InvokeOnUiThread` with a
threading.Event for the response handshake (same pattern as Blender addon).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

# Rhino-only imports — guarded so the file can be linted outside Rhino.
try:
    import rhinoscriptsyntax as rs  # type: ignore
    import scriptcontext as sc       # type: ignore
    import Rhino                       # type: ignore
    import System                      # type: ignore
    _IN_RHINO = True
except ImportError:
    rs = None
    sc = None
    Rhino = None
    System = None
    _IN_RHINO = False


PORT = int(os.environ.get("ARCHHUB_RHINO_PORT", "9879"))
HOST = "127.0.0.1"

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
# Main-thread dispatcher.
# Rhino's API is single-threaded. HTTP handler thread posts work to the UI
# thread via Rhino.RhinoApp.InvokeOnUiThread (Eto.Forms.Application.Invoke
# as fallback on older Rhino builds).
# ---------------------------------------------------------------------------
def _run_on_ui_thread(fn):
    """Marshal `fn` to Rhino's UI thread, block until done, return its result.
    Re-raises any exception that happened inside fn."""
    if not _IN_RHINO:
        return fn()
    result_box: dict[str, Any] = {}
    done = threading.Event()

    def _wrapped():
        try:
            result_box["value"] = fn()
        except Exception as ex:
            result_box["error"] = ex
            result_box["traceback"] = traceback.format_exc()
        finally:
            done.set()

    try:
        Rhino.RhinoApp.InvokeOnUiThread(System.Action(_wrapped))
    except Exception:
        # Older Rhino builds — fall back to Eto.
        try:
            import Eto  # type: ignore
            Eto.Forms.Application.Instance.Invoke(System.Action(_wrapped))
        except Exception as ex:
            return {"status": "error",
                    "error": f"Cannot marshal to Rhino UI thread: {ex}"}
    if not done.wait(timeout=120):
        return {"status": "error", "error": "UI thread timed out (120s)"}
    if "error" in result_box:
        return {"status": "error",
                "error": str(result_box["error"]),
                "traceback": result_box.get("traceback", "")}
    return result_box.get("value")


# ---------------------------------------------------------------------------
# Handlers — each returns a dict that the HTTPRequestHandler serialises.
# Run on Rhino's UI thread via _run_on_ui_thread.
# ---------------------------------------------------------------------------
def _handler_ping() -> dict:
    return {"status": "ok",
            "host": "rhino",
            "rhino_version": _safe_version(),
            "in_rhino": _IN_RHINO}


def _safe_version() -> str:
    try:
        return str(Rhino.RhinoApp.Version)
    except Exception:
        return "unknown"


def _handler_info() -> dict:
    def _body():
        doc = sc.doc
        path = doc.Path if doc else ""
        units = str(doc.ModelUnitSystem) if doc else "unknown"
        try:
            layer_count = doc.Layers.Count
        except Exception:
            layer_count = -1
        try:
            obj_count = doc.Objects.Count
        except Exception:
            obj_count = -1
        return {
            "status":        "ok",
            "doc_path":      path,
            "modified":      bool(doc.Modified) if doc else False,
            "units":         units,
            "layer_count":   layer_count,
            "object_count":  obj_count,
            "active_view":   _safe_active_view(),
            "rhino_version": _safe_version(),
        }
    return _run_on_ui_thread(_body)


def _safe_active_view() -> str:
    try:
        v = sc.doc.Views.ActiveView
        return v.ActiveViewport.Name if v else ""
    except Exception:
        return ""


def _handler_execute(payload: dict) -> dict:
    code = (payload or {}).get("code") or ""
    if not code:
        return {"status": "error", "error": "code is required"}
    timeout = int((payload or {}).get("timeout_seconds") or 60)

    def _body():
        globs: dict[str, Any] = {
            "__name__": "__archhub_exec__",
            "rs": rs,
            "sc": sc,
            "Rhino": Rhino,
            "System": System,
            "doc": sc.doc,
        }
        try:
            exec(code, globs)  # noqa: S102 — explicit escape hatch
        except Exception as ex:
            return {"status": "error",
                    "error": f"{type(ex).__name__}: {ex}",
                    "traceback": traceback.format_exc()}
        result = globs.get("result", None)
        # Best-effort JSON-serialisable result; otherwise stringify.
        try:
            json.dumps(result)
            serialised = result
        except Exception:
            serialised = repr(result)
        return {"status": "ok", "result": serialised}

    # NOTE: timeout enforcement only applies to the marshal wait — once
    # the code starts on the UI thread, Rhino runs it to completion.
    return _run_on_ui_thread(_body)


def _handler_screenshot(payload: dict) -> dict:
    out_path = (payload or {}).get("output_path") or os.path.join(
        tempfile.gettempdir(), "archhub_rhino_screenshot.png"
    )
    width  = int((payload or {}).get("width")  or 1920)
    height = int((payload or {}).get("height") or 1080)

    def _body():
        view = sc.doc.Views.ActiveView
        if view is None:
            return {"status": "error", "error": "No active view"}
        size = System.Drawing.Size(width, height)
        bmp = view.CaptureToBitmap(size)
        if bmp is None:
            return {"status": "error", "error": "CaptureToBitmap returned null"}
        try:
            bmp.Save(out_path)
        finally:
            try:
                bmp.Dispose()
            except Exception:
                pass
        return {"status": "ok", "output_path": out_path,
                "width": width, "height": height}
    return _run_on_ui_thread(_body)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class _ArchHubRequestHandler(BaseHTTPRequestHandler):
    server_version = "ArchHubRhino/0.1"

    def _send(self, status_code: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _refused(self) -> bool:
        refusal = bridge_refusal(self.headers, require_token=self.path != "/ping")
        if refusal is None:
            return False
        self._send(refusal[0], {"status": "error", "error": refusal[1]})
        return True

    def do_OPTIONS(self):  # noqa: N802
        # Only a browser sends a preflight; it gets no CORS grant.
        self._send(403, {"status": "error",
                         "error": "browser requests are refused; ArchHub calls this bridge directly"})

    def do_GET(self):  # noqa: N802
        if self._refused():
            return
        if self.path == "/ping":
            self._send(200, _handler_ping())
        elif self.path == "/info":
            self._send(200, _handler_info())
        elif self.path == "/screenshot":
            self._send(200, _handler_screenshot({}))
        else:
            self._send(404, {"status": "error", "error": "unknown path"})

    def do_POST(self):  # noqa: N802
        if self._refused():
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw or "{}")
        except Exception as ex:
            self._send(400, {"status": "error",
                              "error": f"bad json: {ex}"})
            return
        if self.path == "/execute":
            self._send(200, _handler_execute(payload))
        elif self.path == "/screenshot":
            self._send(200, _handler_screenshot(payload))
        else:
            self._send(404, {"status": "error", "error": "unknown path"})

    # Quiet stdout — Rhino's command line gets enough noise as it is.
    def log_message(self, format, *args):  # noqa: A002, N802
        return


def start():
    """Start the bridge server. Called from the script entry point or
    via `_-RunPythonScript archhub_mcp.py` in Rhino's command line."""
    global _server, _server_thread
    if _server is not None:
        return
    _server = HTTPServer((HOST, PORT), _ArchHubRequestHandler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, daemon=True,
        name="archhub-rhino-bridge",
    )
    _server_thread.start()
    print(f"[ArchHub] Rhino MCP bridge listening on {HOST}:{PORT}")


def stop():
    """Stop the bridge — call before closing Rhino if you want a clean exit."""
    global _server, _server_thread
    if _server is None:
        return
    try:
        _server.shutdown()
        _server.server_close()
    finally:
        _server = None
        _server_thread = None
    print("[ArchHub] Rhino MCP bridge stopped")


# Auto-start whenever this module is loaded inside Rhino — whether it was
# RUN as a script (`_-RunPythonScript` → __name__ == "__main__") OR IMPORTED
# by Rhino's PythonScript auto-load search path (__name__ == "archhub_mcp").
# The old guard required __main__, so library auto-load silently never armed
# the server. start() is idempotent (re-entry is a no-op), so a double
# trigger is harmless. Wrapped so a bind failure (e.g. port already taken by
# another Rhino instance) can never break Rhino's own load sequence.
if _IN_RHINO:
    try:
        start()
    except Exception as _start_ex:  # pragma: no cover - Rhino runtime only
        print(f"[ArchHub] Rhino MCP bridge failed to start: {_start_ex}")
