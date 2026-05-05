"""Tool execution engine.

Owns the list of tools the LLM can call. Each tool:
  - has a JSON schema describing its inputs,
  - dispatches to a Python function or HTTP endpoint when invoked.

Tool families:
  revit_*       — HTTP to RevitMCP.dll (port 48884)
  acad_*        — HTTP to AcadMCP.dll (port 48885)
  max_*         — HTTP to max_mcp_startup.py (port 48886)
  blender_*     — HTTP to BlenderMCP addon (port 9876)
  speckle_*     — HTTPS to Speckle GraphQL (cloud)
  archhub_*     — local helpers (list connectors, prompt user, etc.)

Tool schemas exclude families whose connector is currently OFF, so the LLM
doesn't try to call something that isn't live.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from manager import ConnectorManager, ConnectorState
from speckle_client import SpeckleClient


# ---------------------------------------------------------------------------
@dataclass
class ToolInvocation:
    id: str
    tool_name: str
    arguments: dict
    status: str = "pending"           # pending | running | ok | error
    result: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "tool_name": self.tool_name,
                "arguments": self.arguments, "status": self.status,
                "result": self.result}


# ---------------------------------------------------------------------------
HOSTS = {
    "revit":   "http://localhost:48884",
    "acad":    "http://localhost:48885",
    "max":     "http://localhost:48886/max-mcp",
    "blender": "http://localhost:9876",
}


# Tool catalogue — single source of truth.
# Each entry: (name, family-key-in-active-set, description, input_schema, dispatch_fn)
TOOLS: list[dict] = [
    # Revit
    {
        "name": "revit_ping",
        "family": "revit",
        "description": "Verify the Revit MCP add-in is alive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("revit", "GET", "/ping", None),
    },
    {
        "name": "revit_info",
        "family": "revit",
        "description": "Return active Revit document info: title, path, units, active view, version.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("revit", "GET", "/info", None),
    },
    {
        "name": "revit_execute_csharp",
        "family": "revit",
        "description": (
            "Execute C# code live in Revit via Roslyn scripting. The code runs in the "
            "Revit API context, auto-wrapped in a Transaction. Globals: UIApp, UIDoc, Doc. "
            "Imports already in scope: System, System.Collections.Generic, System.Linq, "
            "Autodesk.Revit.DB, Autodesk.Revit.UI. Assign to a `result` variable to return data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "C# source to execute"},
                "transaction_name": {"type": "string", "description": "Name shown in Revit's Undo history",
                                     "default": "ArchHub"},
            },
            "required": ["code"],
        },
        "endpoint": ("revit", "POST", "/exec", ("code", "transaction_name")),
    },
    {
        "name": "revit_screenshot",
        "family": "revit",
        "description": "Export the active Revit view as a PNG to disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "width_px": {"type": "integer", "default": 1920},
            },
            "required": ["output_path"],
        },
        "endpoint": ("revit", "POST", "/screenshot", ("output_path", "width_px")),
    },

    # AutoCAD
    {
        "name": "acad_ping",
        "family": "acad",
        "description": "Verify the AutoCAD MCP plugin is alive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("acad", "GET", "/ping", None),
    },
    {
        "name": "acad_info",
        "family": "acad",
        "description": "Active AutoCAD document info.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("acad", "GET", "/info", None),
    },
    {
        "name": "acad_execute_csharp",
        "family": "acad",
        "description": (
            "Execute C# code live in AutoCAD via Roslyn. Auto-wrapped in DocumentLock + "
            "Transaction. Globals: Doc, Db, Ed. Imports: AutoCAD ApplicationServices, "
            "DatabaseServices, EditorInput, Geometry, Runtime."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "transaction_name": {"type": "string"}},
            "required": ["code"],
        },
        "endpoint": ("acad", "POST", "/exec", ("code", "transaction_name")),
    },

    # 3ds Max
    {
        "name": "max_ping",
        "family": "max",
        "description": "Verify the 3ds Max MCP startup script is alive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("max", "GET", "/ping", None),
    },
    {
        "name": "max_info",
        "family": "max",
        "description": "3ds Max scene info.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("max", "GET", "/info", None),
    },
    {
        "name": "max_execute_python",
        "family": "max",
        "description": (
            "Execute Python in 3ds Max via pymxs. Globals: rt = pymxs.runtime. "
            "Set `result` to return JSON-serialisable data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        "endpoint": ("max", "POST", "/exec", ("code",)),
    },
    {
        "name": "max_execute_maxscript",
        "family": "max",
        "description": "Execute MAXScript code in 3ds Max.",
        "input_schema": {
            "type": "object",
            "properties": {"script": {"type": "string"}},
            "required": ["script"],
        },
        "endpoint": ("max", "POST", "/exec_maxscript", ("script",)),
    },

    # Blender
    {
        "name": "blender_ping",
        "family": "blender",
        "description": "Verify the Blender MCP addon is alive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("blender", "GET", "/ping", None),
    },
    {
        "name": "blender_execute_python",
        "family": "blender",
        "description": (
            "Execute Python in Blender with full bpy access. Set `result` to return JSON-serialisable data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        "endpoint": ("blender", "POST", "/exec", ("code",)),
    },

    # Speckle
    {
        "name": "speckle_list_projects",
        "family": "speckle",
        "description": "List the user's Speckle projects.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("speckle", "list_projects"),
    },
    {
        "name": "speckle_get_project",
        "family": "speckle",
        "description": "Fetch a Speckle project by id, including its models and latest versions.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "endpoint": ("speckle", "get_project"),
    },

    # ArchHub local helpers (always available)
    {
        "name": "archhub_list_connectors",
        "family": "_local",
        "description": "List ArchHub connectors and their current state (active/ready/unavailable).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("_local", "list_connectors"),
    },
]


# ---------------------------------------------------------------------------
class ToolEngine:
    def __init__(self, manager: ConnectorManager):
        self.manager = manager
        self.speckle = SpeckleClient()

    # ---- schema export for LLMs -------------------------------------------

    def tool_schemas_for(self, provider: str) -> list[dict]:
        active_families = self._active_families()
        out: list[dict] = []
        for t in TOOLS:
            if t["family"] != "_local" and t["family"] not in active_families:
                continue
            if provider == "anthropic":
                out.append({
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                })
            elif provider == "openai":
                out.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                })
            elif provider == "ollama":
                # Ollama uses OpenAI-compatible function-calling format
                out.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                })
            elif provider == "google":
                # Gemini has its own format — not used by stub
                out.append({"name": t["name"], "description": t["description"]})
        return out

    def _active_families(self) -> set[str]:
        active = set()
        for e in self.manager.entries:
            if e.state != ConnectorState.ACTIVE:
                continue
            fam = e.family
            # Map family → tool prefix used in TOOLS
            if fam == "autocad":
                active.add("acad")
            else:
                active.add(fam)
        return active

    # ---- invocation -------------------------------------------------------

    def invoke(self, tool_name: str, args: dict) -> dict:
        tool = next((t for t in TOOLS if t["name"] == tool_name), None)
        if tool is None:
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        ep = tool["endpoint"]

        # _local family → built-in handlers
        if tool["family"] == "_local":
            handler = ep[1]
            if handler == "list_connectors":
                return {"status": "ok", "connectors": [
                    {"id": e.id, "name": e.display_name, "state": e.state.name}
                    for e in self.manager.entries
                ]}
            return {"status": "error", "error": f"Unknown local handler: {handler}"}

        # speckle family
        if tool["family"] == "speckle":
            handler = ep[1]
            try:
                return self.speckle.dispatch(handler, args)
            except Exception as ex:
                return {"status": "error", "error": str(ex)}

        # HTTP families: revit/acad/max/blender
        family, method, path, arg_keys = ep
        if family not in self._active_families():
            return {"status": "error",
                    "error": f"{family} connector is not active. Open Connectors to enable it."}
        body = None
        if arg_keys:
            body = {k: args[k] for k in arg_keys if k in args}
        return self._http(family, method, path, body)

    def _http(self, family: str, method: str, path: str, body: Optional[dict],
              timeout: int = 240) -> dict:
        url = f"{HOSTS[family]}{path}"
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
                    "error": f"Cannot reach {url}. Is the host application running? {e}"}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}
