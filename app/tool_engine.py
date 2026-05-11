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
        "name": "blender_info",
        "family": "blender",
        "description": "Snapshot of the current Blender file: blend path, scene name, object count, render engine.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("blender", "info"),
    },
    {
        "name": "blender_save",
        "family": "blender",
        "description": "Save the current Blender file. Pass output_path to save-as a different .blend.",
        "input_schema": {
            "type": "object",
            "properties": {"output_path": {"type": "string"}},
            "required": [],
        },
        "endpoint": ("blender", "save"),
    },
    {
        "name": "blender_render",
        "family": "blender",
        "description": "Render the current scene at frame `frame` (defaults to current frame). Saves to output_path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "frame":       {"type": "integer", "default": -1},
                "engine":      {"type": "string", "enum": ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"]},
                "samples":     {"type": "integer", "default": 64},
            },
            "required": ["output_path"],
        },
        "endpoint": ("blender", "render"),
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
    {
        "name": "speckle_push_parameters",
        "family": "speckle",
        "description": "Push a JSON parameter object to a Speckle stream + branch. Creates a new commit. Returns the commit id + url. Use for syncing design parameters across the team.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "branch":     {"type": "string", "default": "main"},
                "parameters": {"type": "object"},
                "message":    {"type": "string", "default": "ArchHub: parameter push"},
            },
            "required": ["project_id", "parameters"],
        },
        "endpoint": ("speckle", "push_parameters"),
    },
    {
        "name": "speckle_pull_parameters",
        "family": "speckle",
        "description": "Pull the most-recent parameter object from a Speckle stream + branch. Returns the JSON the team last pushed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "branch":     {"type": "string", "default": "main"},
            },
            "required": ["project_id"],
        },
        "endpoint": ("speckle", "pull_parameters"),
    },

    # Outlook (classic) — drives via COM, no listener
    {
        "name": "outlook_info",
        "family": "outlook",
        "description": "Snapshot of Outlook inbox: total count, unread count, drafts count, default account email.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("outlook", "info"),
    },
    {
        "name": "outlook_list_inbox",
        "family": "outlook",
        "description": "Return the most recent inbox messages newest-first. Use unread_only=true to skip already-read mail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "unread_only": {"type": "boolean", "default": False},
            },
            "required": [],
        },
        "endpoint": ("outlook", "list_inbox"),
    },
    {
        "name": "outlook_search",
        "family": "outlook",
        "description": "Search the inbox. All filters optional and combine with AND. `query` matches subject and body, `sender` matches From-name OR email, `subject_contains` matches subject only, `days` restricts to the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "sender": {"type": "string"},
                "subject_contains": {"type": "string"},
                "days": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 30},
            },
            "required": [],
        },
        "endpoint": ("outlook", "search"),
    },
    {
        "name": "outlook_read_thread",
        "family": "outlook",
        "description": "Return the full thread + body for a single message (identified by entry_id). Includes parent + reply chain when Conversation API exposes it.",
        "input_schema": {
            "type": "object",
            "properties": {"entry_id": {"type": "string"}},
            "required": ["entry_id"],
        },
        "endpoint": ("outlook", "read_thread"),
    },
    {
        "name": "outlook_draft_reply",
        "family": "outlook",
        "description": "Create a Reply or Reply-All draft for the given message. By default the draft pops up in Outlook for the user to review + Send. Sets `send=true` only if the user has explicitly enabled 'allow ArchHub to send' in Settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "body":     {"type": "string"},
                "reply_all": {"type": "boolean", "default": False},
                "send":      {"type": "boolean", "default": False},
            },
            "required": ["entry_id"],
        },
        "endpoint": ("outlook", "draft_reply"),
    },
    {
        "name": "outlook_save_attachments",
        "family": "outlook",
        "description": "Save every attachment from the message identified by entry_id into dest_dir. Returns the list of saved paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "dest_dir": {"type": "string"},
            },
            "required": ["entry_id", "dest_dir"],
        },
        "endpoint": ("outlook", "save_attachments"),
    },
    {
        "name": "outlook_set_categories",
        "family": "outlook",
        "description": "Tag (categorize) a message with one or more Outlook category names. Categories appear as coloured tags + are filterable in the Outlook UI. Use mode='set' to replace existing categories, 'add' to append, 'remove' to drop. Categories that don't exist yet are auto-registered the first time the user views the message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "mode": {
                    "type": "string",
                    "enum": ["set", "add", "remove"],
                    "default": "set",
                },
            },
            "required": ["entry_id", "categories"],
        },
        "endpoint": ("outlook", "set_categories"),
    },
    {
        "name": "outlook_list_folders",
        "family": "outlook",
        "description": "Walk every folder in the user's MAPI store. Returns flat list of {path, name, item_count, folder_id}. Use folder_id with outlook_move_to_folder. Pass an empty `root` to enumerate from the default store root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": ""},
            },
            "required": [],
        },
        "endpoint": ("outlook", "list_folders"),
    },
    {
        "name": "outlook_create_folder",
        "family": "outlook",
        "description": "Create a new mail folder under parent_id. Pass empty parent_id to create under Inbox. Returns the new folder_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_id": {"type": "string", "default": ""},
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        "endpoint": ("outlook", "create_folder"),
    },
    {
        "name": "outlook_move_to_folder",
        "family": "outlook",
        "description": "Move a message identified by entry_id into the folder identified by folder_id. Returns the new entry_id (Outlook re-IDs on move).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "folder_id": {"type": "string"},
            },
            "required": ["entry_id", "folder_id"],
        },
        "endpoint": ("outlook", "move_to_folder"),
    },
    {
        "name": "outlook_mark_read",
        "family": "outlook",
        "description": "Toggle a message's read/unread flag. read=true marks read, read=false marks unread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "read": {"type": "boolean", "default": True},
            },
            "required": ["entry_id"],
        },
        "endpoint": ("outlook", "mark_read"),
    },
    {
        "name": "outlook_flag_for_followup",
        "family": "outlook",
        "description": "Set the standard Outlook 'Follow up' flag on a message. Optional due_offset_days schedules the follow-up that many days from today; reminder=true also sets a reminder pop-up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "due_offset_days": {"type": "integer", "default": 0},
                "reminder": {"type": "boolean", "default": False},
            },
            "required": ["entry_id"],
        },
        "endpoint": ("outlook", "flag_for_followup"),
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
                # Gemini wants name + description + JSONSchema params,
                # later wrapped in {"function_declarations": [...]} by
                # the GoogleClient. Pass the full input_schema here so
                # the client doesn't have to re-fetch.
                out.append({
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                })
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
        # Outlook auto-activates when classic Outlook is reachable via
        # COM — but COM dispatch on the Qt main thread crashes Qt6Core
        # if called repeatedly (status bar ticks every few seconds).
        # Cache the answer with a 30s TTL so the probe runs at most
        # twice per minute, on a worker thread.
        try:
            if self._outlook_active_cached():
                active.add("outlook")
        except Exception:
            pass
        return active

    # Outlook reachability cache state. Populated by the worker thread
    # `_refresh_outlook_async`. Initial state is False so the connector
    # doesn't auto-add until the first probe lands.
    _OL_TTL_SECONDS = 30.0

    def _outlook_active_cached(self) -> bool:
        import time as _t
        now = _t.time()
        last = getattr(self, "_outlook_last_check", 0.0)
        if now - last >= self._OL_TTL_SECONDS:
            # Refresh asynchronously so this caller never blocks on COM.
            self._outlook_last_check = now
            import threading
            threading.Thread(target=self._refresh_outlook_async,
                              daemon=True).start()
        return bool(getattr(self, "_outlook_reachable", False))

    def _refresh_outlook_async(self) -> None:
        try:
            from connectors.outlook_runner import is_reachable
            self._outlook_reachable = bool(is_reachable())
        except Exception:
            self._outlook_reachable = False

    # ---- invocation -------------------------------------------------------

    def invoke(self, tool_name: str, args: dict,
               session_pin: Optional[str] = None) -> dict:
        """Invoke one tool.

        session_pin — optional token used to disambiguate when multiple
        instances of the same host (e.g. two Revit windows) are alive.
        Tokens are resolved against each broker's pick_session(prefer=...)
        which matches against session_id, pid, doc_title substring, or
        SMTP for Outlook. Ignored for tools whose family has no broker
        (speckle, blender today, _local).
        """
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

        # outlook family — drives classic Outlook in-process via COM.
        # No localhost listener; we route directly to outlook_runner. The
        # session_pin (when present) is forwarded as `account` to handlers
        # that accept it, so the LLM can target one mailbox out of many.
        if tool["family"] == "outlook":
            handler = ep[1]
            try:
                from connectors import outlook_runner as _ol
                fn = getattr(_ol, handler, None)
                if fn is None:
                    return {"status": "error",
                            "error": f"Unknown outlook handler: {handler}"}
                # Pass kwargs the handler accepts (skip unknown keys).
                import inspect
                sig = inspect.signature(fn)
                merged = dict(args or {})
                if session_pin and "account" in sig.parameters:
                    merged.setdefault("account", session_pin)
                kwargs = {k: v for k, v in merged.items() if k in sig.parameters}
                result = fn(**kwargs)
                # Normalise list/dict results into the {status: ok, ...} envelope.
                if isinstance(result, dict):
                    if "status" not in result:
                        result = {"status": "ok", **result}
                    return result
                if isinstance(result, list):
                    return {"status": "ok", "items": result}
                return {"status": "ok", "result": result}
            except Exception as ex:
                return {"status": "error", "error": str(ex)[:300]}

        # HTTP families: revit/acad/max/blender
        family, method, path, arg_keys = ep
        if family not in self._active_families():
            return {"status": "error",
                    "error": f"{family} connector is not active. Open Connectors to enable it."}
        body = None
        if arg_keys:
            body = {k: args[k] for k in arg_keys if k in args}
        return self._http(family, method, path, body, session_pin=session_pin)

    # Family → (broker module, default-fallback URL). Broker is consulted
    # first so multi-instance hosts pick the right session; URL fallback
    # is used when the family has no broker (Blender today) or when the
    # broker reports zero healthy sessions but the legacy single port
    # might still answer.
    def _broker_for(self, family: str):
        try:
            if family == "revit":
                import revit_broker; return revit_broker
            if family == "max":
                import max_broker; return max_broker
            if family == "acad":
                import acad_broker; return acad_broker
        except Exception:
            return None
        return None

    def _http(self, family: str, method: str, path: str, body: Optional[dict],
              timeout: int = 240, session_pin: Optional[str] = None) -> dict:
        # Encode body once.
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        # Multi-session: resolve via broker first.
        broker = self._broker_for(family)
        if broker is not None:
            try:
                session = broker.pick_session(prefer=session_pin)
            except Exception:
                session = None
            if session is None and session_pin:
                return {"status": "error",
                        "error": f"No live {family} session matches '@{session_pin}'."}
            if session is not None:
                return broker.forward(session, path, body=data,
                                       method=method, timeout=timeout)

        # Fallback: direct legacy URL (Blender, or pre-broker hosts).
        url = f"{HOSTS[family]}{path}"
        headers = {"Accept": "application/json"}
        if data is not None:
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

    # Public helper used by chat input to resolve `@token` mentions.
    def list_pinnable_sessions(self) -> list[dict]:
        """Return every live session across every broker, flat list of
        {family, session_id, pid, doc_title, version, port}. Drives the
        @-mention popup in the chat composer."""
        out: list[dict] = []
        for fam, mod in (("revit", "revit_broker"),
                         ("max", "max_broker"),
                         ("acad", "acad_broker"),
                         ("outlook", "outlook_broker")):
            try:
                m = __import__(mod)
                for s in (m.list_sessions(prune=False) or []):
                    if not getattr(s, "healthy", False):
                        continue
                    out.append({
                        "family":     fam,
                        "session_id": s.session_id,
                        "pid":        getattr(s, "pid", 0),
                        "doc_title":  getattr(s, "doc_title", ""),
                        "version":    getattr(s, "version", ""),
                        "port":       getattr(s, "port", 0),
                    })
            except Exception:
                continue
        return out
