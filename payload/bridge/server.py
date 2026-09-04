"""ArchHub unified MCP server — single entry registered in Claude Desktop.

Reads %LOCALAPPDATA%/ArchHub/state.json on every tool call to determine which
connectors are toggled on, then namespaces tools accordingly. This means
toggling individual connectors in the ArchHub UI takes effect immediately
without restarting Claude Desktop.

For each active connector family, this server exposes:
  <family>_ping        — health check
  <family>_info        — basic state
  <family>_execute_*   — live code/script execution
  <family>_screenshot  — capture (where applicable)

The server is HTTP-based per host — Revit/AutoCAD listen on dedicated ports
(48884/48885), 3ds Max on 48886, Blender on its addon port (typically 9876).
This file just translates Claude tool calls into HTTP requests against
those local services.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
STATE_PATH = APP_DIR / "state.json"

# Per-host HTTP endpoints
ENDPOINTS = {
    "revit":   "http://localhost:48884",
    "autocad": "http://localhost:48885",
    "max":     "http://localhost:48886/max-mcp",
    "blender": "http://localhost:9876",   # blender addon default
}

mcp = FastMCP("archhub")

# The rest of the founder's hosts (Rhino, Blender, Max, Office, Outlook, Notion,
# Dropbox) are driven by the kernel's broker module -- one implementation for
# the app and for every agent. Find it in the worktree or the nested copy.
import sys as _sys
for _candidate in (Path(__file__).resolve().parents[2] / "node-language",
                   Path(__file__).resolve().parents[3] / "13.NODE-LANGUAGE"):
    if (_candidate / "nodelang" / "host_brokers.py").is_file() and str(_candidate) not in _sys.path:
        _sys.path.insert(0, str(_candidate))
try:
    from nodelang import host_brokers as _brokers
except Exception as _exc:  # noqa: BLE001
    _brokers = None
    _BROKERS_ERROR = str(_exc)


def _broker(engine: str, **params) -> Dict[str, Any]:
    if _brokers is None:
        return {"status": "error", "error": "kernel brokers unavailable: " + _BROKERS_ERROR}
    try:
        out, label = _brokers.ENGINES[engine](params, {})
        return {"status": "ok", "label": label, **out}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
def _load_active() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("active", []))
    except Exception:
        return set()


def _is_family_active(family: str) -> bool:
    """Return True iff ANY connector of this family is toggled on."""
    active = _load_active()
    return any(cid.startswith(f"{family}-") or cid == family for cid in active)


def _request(family: str, endpoint: str, method: str = "GET",
             body: Optional[Dict[str, Any]] = None,
             timeout: int = 240) -> Dict[str, Any]:
    if not _is_family_active(family):
        return {"status": "error",
                "error": f"{family} is not toggled on in ArchHub. "
                         f"Open ArchHub from the system tray and enable it."}
    base = ENDPOINTS.get(family)
    if base is None:
        return {"status": "error", "error": f"Unknown family: {family}"}

    url = f"{base}{endpoint}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {"status": "error", "error": "Non-JSON response", "raw": payload}
    except urllib.error.URLError as e:
        return {"status": "error",
                "error": (f"Cannot reach {url}. The host application "
                          f"({family}) needs to be running with a project open. "
                          f"Details: {e}")}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Revit
# ---------------------------------------------------------------------------
@mcp.tool()
def revit_ping() -> Dict[str, Any]:
    """Check if Revit is reachable through ArchHub."""
    return _request("revit", "/ping")

@mcp.tool()
def revit_info() -> Dict[str, Any]:
    """Active Revit document info."""
    return _request("revit", "/info")

@mcp.tool()
def revit_execute_csharp(code: str, transaction_name: str = "ArchHub") -> Dict[str, Any]:
    """
    Execute C# code live in Revit (Roslyn). Globals: UIApp, UIDoc, Doc.
    Imports: System, System.Collections.Generic, System.Linq,
    Autodesk.Revit.DB, Autodesk.Revit.UI. Set `result` to return data.
    """
    return _request("revit", "/exec", "POST",
                    {"code": code, "transaction_name": transaction_name})

@mcp.tool()
def revit_screenshot(output_path: str = r"C:\temp\revit_view.png", width_px: int = 1920) -> Dict[str, Any]:
    """Export the active Revit view as PNG."""
    return _request("revit", "/screenshot", "POST",
                    {"output_path": output_path, "width_px": width_px})


# ---------------------------------------------------------------------------
# AutoCAD
# ---------------------------------------------------------------------------
@mcp.tool()
def acad_ping() -> Dict[str, Any]:
    """Check if AutoCAD is reachable through ArchHub."""
    return _request("autocad", "/ping")

@mcp.tool()
def acad_info() -> Dict[str, Any]:
    """Active AutoCAD document info."""
    return _request("autocad", "/info")

@mcp.tool()
def acad_execute_csharp(code: str, transaction_name: str = "ArchHub") -> Dict[str, Any]:
    """
    Execute C# code live in AutoCAD (Roslyn). Globals: Doc, Db, Ed.
    Imports: System, System.Collections.Generic, System.Linq,
    Autodesk.AutoCAD.{ApplicationServices, DatabaseServices, EditorInput,
    Geometry, Runtime}. Set `result` to return data.
    """
    return _request("autocad", "/exec", "POST",
                    {"code": code, "transaction_name": transaction_name})


# ---------------------------------------------------------------------------
# 3ds Max
# ---------------------------------------------------------------------------
@mcp.tool()
def max_ping() -> Dict[str, Any]:
    """Check if 3ds Max is reachable through ArchHub."""
    return _request("max", "/ping")

@mcp.tool()
def max_info() -> Dict[str, Any]:
    """3ds Max scene info."""
    return _request("max", "/info")

@mcp.tool()
def max_execute_python(code: str) -> Dict[str, Any]:
    """
    Execute Python in 3ds Max via pymxs. Globals: rt = pymxs.runtime.
    Set `result` to return data.
    """
    return _request("max", "/exec", "POST", {"code": code})

@mcp.tool()
def max_execute_maxscript(script: str) -> Dict[str, Any]:
    """Execute MAXScript code in 3ds Max."""
    return _request("max", "/exec_maxscript", "POST", {"script": script})


# ---------------------------------------------------------------------------
# Blender (uses the official Blender MCP addon — same protocol)
# ---------------------------------------------------------------------------
@mcp.tool()
def blender_ping() -> Dict[str, Any]:
    """Check if Blender is reachable through ArchHub."""
    return _request("blender", "/ping")

@mcp.tool()
def blender_execute_python(code: str) -> Dict[str, Any]:
    """
    Execute Python code in the connected Blender instance with full bpy access.
    Set `result` to return JSON-serialisable data.
    """
    return _request("blender", "/exec", "POST", {"code": code})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()

@mcp.tool()
def hosts_state() -> Dict[str, Any]:
    """Every host the founder works with and its real state right now."""
    return _broker("connector.rows")


@mcp.tool()
def rhino_ping() -> Dict[str, Any]:
    """Is the Rhino bridge (:9879) answering?"""
    return _broker("rhino.exec", code="")


@mcp.tool()
def rhino_execute_python(code: str) -> Dict[str, Any]:
    """Run RhinoPython in the open Rhino model through its bridge."""
    return _broker("rhino.exec", code=code)


@mcp.tool()
def office_read(operation: str, name: str = "") -> Dict[str, Any]:
    """Read what Excel/Word/PowerPoint hold open: excel.list_workbooks, excel.list_worksheets, word.list_documents, word.list_paragraphs, powerpoint.list_presentations, powerpoint.list_slides."""
    return _broker("office.read", operation=operation, name=name)


@mcp.tool()
def outlook_inbox(count: int = 20) -> Dict[str, Any]:
    """Newest inbox items from the open Outlook (subject, sender, received)."""
    return _broker("outlook.inbox", count=count)


@mcp.tool()
def notion_search(query: str = "") -> Dict[str, Any]:
    """Search the founder's Notion workspace (needs the integration token)."""
    return _broker("notion.search", query=query)


@mcp.tool()
def dropbox_list(path: str = "") -> Dict[str, Any]:
    """Files under the Dropbox folder (relative path optional)."""
    return _broker("dropbox.list", path=path)
