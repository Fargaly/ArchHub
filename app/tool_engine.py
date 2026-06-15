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


# Map a ParamSpec type to a JSON-schema type for LLM tool schemas.
def _json_type(t: str) -> str:
    return {
        "number": "number", "range": "number",
        "bool": "boolean", "boolean": "boolean",
        "multi": "array", "list": "array",
    }.get((t or "").lower(), "string")


# Verbs that signal a write OUT to disk / a remote / another system rather
# than a mutation of the host application itself (CON-02). Kept in sync with
# the class guard in tests/test_connector_contract.py.
_OUTWARD_WRITE_PREFIXES = ("send_", "push_", "upload_")


def _side_effect_tag(op) -> str:
    """LLM-visible warning suffix for an op's description.

    Honest about WHAT the side effect is so the model treats it with the
    right care:
      * a `destructive` op that writes OUT (send/push/upload) → it touches
        disk/remote, not the host → "[WRITES TO DISK/REMOTE]".
      * any other `destructive` op → it mutates the host → "[MUTATES THE HOST]".
      * a non-destructive read → no tag.
    Either tag is advisory; the actual gate is the kind-derived policy.
    """
    if not getattr(op, "destructive", False):
        return ""
    _, _, verb = (getattr(op, "op_id", "") or "").partition(".")
    if verb.startswith(_OUTWARD_WRITE_PREFIXES):
        return " [WRITES TO DISK/REMOTE]"
    return " [MUTATES THE HOST]"


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


# Hand-maintained host tool list — Revit/AutoCAD/Max/Blender/Rhino/
# Speckle transports, AI delegations, local helpers.
#
# NOT the only tool registry: ~116 connector ops live in
# `connectors.base`, and `tool_schemas_for()` emits BOTH lists to the
# LLM. The two overlap for 6 hosts. Collapsing them into one — so the
# model never sees duplicate tools for the same host — is tracked in
# docs/ROADMAP.md (tool-registry unification). Until then this is a
# hand list, not the single source of truth.
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

    # Rhino — HTTP bridge running inside Rhino's embedded Python.
    # Activated when the user runs `_-RunPythonScript archhub_mcp.py`
    # at the Rhino command line (see payload/rhino/README.md).
    {
        "name": "rhino_ping",
        "family": "rhino",
        "description": "Verify the Rhino MCP bridge is alive on :9879.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("rhino", "ping"),
    },
    {
        "name": "rhino_info",
        "family": "rhino",
        "description": "Active Rhino document info — path, units, layer count, object count, active view.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("rhino", "info"),
    },
    {
        "name": "rhino_execute_python",
        "family": "rhino",
        "description": (
            "Execute Python code live in Rhino's context. Globals pre-loaded: "
            "`rs` (rhinoscriptsyntax), `sc` (scriptcontext), `Rhino` (.NET API), "
            "`doc` (sc.doc), `System`. Assign to `result` to return data. "
            "Runs on Rhino's UI thread."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "required": ["code"],
        },
        "endpoint": ("rhino", "execute_python"),
    },
    {
        "name": "rhino_screenshot",
        "family": "rhino",
        "description": "Capture the active viewport to a PNG. Optional output_path / width / height.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "width":  {"type": "integer", "default": 1920},
                "height": {"type": "integer", "default": 1080},
            },
            "required": [],
        },
        "endpoint": ("rhino", "screenshot"),
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
        "name": "outlook_execute_python",
        "family": "outlook",
        "description": (
            "ESCAPE HATCH — run arbitrary Python with full Outlook "
            "COM access. Globals: outlook (Application), ns (MAPI "
            "Namespace), inbox / sent / drafts (default folders), "
            "pythoncom, datetime, json, re. Set `result` to return "
            "data. Stdout captured.\n"
            "\n"
            "Use when no named outlook tool fits. Examples:\n"
            "  - 'count messages per sender per week'\n"
            "  - 'find emails from Q1 mentioning Tower-A and "
            "    forward to bob@'\n"
            "  - 'move every newsletter to a Newsletters folder'\n"
            "  - 'export inbox to CSV'\n"
            "\n"
            "Prefer named tools (list_inbox / set_categories / "
            "auto_categorize_by_sender) for common ops — they're "
            "faster + clearer. Reach for execute_python only when "
            "the request needs custom logic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "required": ["code"],
        },
        "endpoint": ("outlook", "execute_python"),
    },
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
        "description": (
            "Return the full thread + body for a single message. "
            "REQUIRES a real entry_id obtained from outlook_list_inbox "
            "or outlook_search FIRST — entry_id is an opaque Outlook "
            "MAPI identifier, NOT a description or placeholder. To "
            "process every message in a folder: call outlook_list_inbox, "
            "then call outlook_read_thread once per item['entry_id']."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": (
                        "Opaque MAPI entry id (e.g. "
                        "'00000000A1B2C3...AC0001'). Get from "
                        "outlook_list_inbox[i]['entry_id'] or "
                        "outlook_search[i]['entry_id']."
                    ),
                },
            },
            "required": ["entry_id"],
        },
        "endpoint": ("outlook", "read_thread"),
    },
    {
        "name": "outlook_draft_reply",
        "family": "outlook",
        "description": (
            "Create a Reply or Reply-All draft for a single message. "
            "REQUIRES a real entry_id from outlook_list_inbox / "
            "outlook_search. By default the draft pops up in Outlook "
            "for the user to review + Send. Set send=true only when "
            "explicitly told."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "Opaque MAPI entry id from list/search.",
                },
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
        "description": (
            "Save every attachment from one message into dest_dir. "
            "REQUIRES a real entry_id from outlook_list_inbox / "
            "outlook_search. Returns the list of saved paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "Opaque MAPI entry id from list/search.",
                },
                "dest_dir": {"type": "string"},
            },
            "required": ["entry_id", "dest_dir"],
        },
        "endpoint": ("outlook", "save_attachments"),
    },
    {
        "name": "outlook_set_categories",
        "family": "outlook",
        "description": (
            "Tag one message with category names. Categories appear "
            "as coloured tags + are filterable in the Outlook UI. "
            "REQUIRES a real entry_id from outlook_list_inbox / "
            "outlook_search — entry_id is an opaque MAPI id, NOT a "
            "description. For bulk categorisation: list_inbox first, "
            "then loop set_categories per item['entry_id']. "
            "mode='set' replaces, 'add' appends, 'remove' drops. "
            "Unknown categories auto-register on first set."
        ),
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
        "name": "outlook_set_categories_by_filter",
        "family": "outlook",
        "description": (
            "BULK categorise every email matching a filter, in ONE "
            "call — no per-message loop needed. The tool internally "
            "lists the inbox + applies categories to every match. "
            "Use this instead of looping outlook_set_categories "
            "yourself.\n"
            "\n"
            "Filter fields combine with AND (all optional):\n"
            "  sender_contains: substring of sender name OR email\n"
            "  subject_contains: substring of subject line\n"
            "  body_contains: substring of body text\n"
            "  days: last N days (0 = unlimited)\n"
            "  unread_only: true → skip read messages\n"
            "  limit: cap on messages scanned (default 500)\n"
            "\n"
            "Example: tag every Autodesk message 'Vendor':\n"
            "  outlook_set_categories_by_filter(\n"
            "    sender_contains='@autodesk.com',\n"
            "    categories=['Vendor'])\n"
            "Returns: {matched, touched, sample (first 5 subjects), "
            "errors, applied_categories, filter}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "sender_contains": {"type": "string"},
                "subject_contains": {"type": "string"},
                "body_contains": {"type": "string"},
                "days": {"type": "integer", "default": 0},
                "unread_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 500},
                "mode": {
                    "type": "string",
                    "enum": ["set", "add", "remove"],
                    "default": "set",
                },
            },
            "required": ["categories"],
        },
        "endpoint": ("outlook", "set_categories_by_filter"),
    },
    {
        "name": "outlook_list_sent_items",
        "family": "outlook",
        "description": (
            "List recent messages from the Sent Items folder. "
            "Mirror of outlook_list_inbox but for outgoing mail. "
            "Each item has entry_id / subject / to (list of "
            "recipients) / sent_on / body_preview / categories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "days": {"type": "integer", "default": 0},
            },
            "required": [],
        },
        "endpoint": ("outlook", "list_sent_items"),
    },
    {
        "name": "outlook_auto_categorize_by_subject_keywords",
        "family": "outlook",
        "description": (
            "Content-based bulk categoriser. Takes a "
            "{keyword: category_name} map. For each keyword, tags "
            "every message whose subject OR body contains the "
            "keyword (case-insensitive) with the matching category. "
            "Each message can land in multiple categories. "
            "include_sent=true also scans Sent Items.\n"
            "\n"
            "USE THIS when user wants categorisation by PROJECT "
            "CONTENT (e.g. 'sort by project name') AND you already "
            "know the project keywords. If projects are unknown, "
            "use outlook_auto_categorize_by_sender first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword_map": {
                    "type": "object",
                    "description": (
                        "Map of keyword → category name. "
                        "Example: {'Tower-A': 'Tower-A', "
                        "'RFI': 'RFIs', 'invoice': 'Finance'}."
                    ),
                },
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 500},
                "include_sent": {"type": "boolean", "default": False},
            },
            "required": ["keyword_map"],
        },
        "endpoint": ("outlook", "auto_categorize_by_subject_keywords"),
    },
    {
        "name": "outlook_auto_categorize_by_sender",
        "family": "outlook",
        "description": (
            "ZERO-ARGUMENT one-shot categoriser. Walks recent inbox, "
            "groups every email by sender domain, derives a category "
            "name from each domain (e.g. 'autodesk.com' → 'Autodesk'), "
            "and tags every message with the derived category. "
            "Returns a summary: total touched, per-domain breakdown, "
            "any errors.\n"
            "\n"
            "USE THIS FOR REQUESTS LIKE 'categorise all my emails by "
            "project' WHEN PROJECTS AREN'T NAMED. The model does not "
            "need to loop, read messages, or guess IDs. Call once "
            "with no args and report the summary back to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 500},
                "min_messages": {"type": "integer", "default": 2},
            },
            "required": [],
        },
        "endpoint": ("outlook", "auto_categorize_by_sender"),
    },
    {
        "name": "outlook_list_distinct_senders",
        "family": "outlook",
        "description": (
            "Walk the last N days of inbox + return unique sender "
            "domains with counts + 3 sample subjects per domain. "
            "Helps you propose sensible project / category names "
            "WITHOUT reading every message body. Cheap (one COM "
            "call). Typical use: derive a category map, then call "
            "outlook_set_categories_by_filter once per category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 500},
            },
            "required": [],
        },
        "endpoint": ("outlook", "list_distinct_senders"),
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

    # Procore (construction PM) — drives Procore's REST API. No host
    # install required; user pastes a Personal Access Token in
    # Settings → Sign-ins → Procore and the tools become live.
    # Always-on like the `ai` family: the schema is exposed to the LLM
    # even when no token is saved, so the model can suggest signing in
    # rather than silently lacking the capability.
    {
        "name": "procore_ping",
        "family": "procore",
        "description": "Verify the Procore API is reachable with the saved access token. Pings /me.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("procore", "is_reachable"),
    },
    {
        "name": "procore_info",
        "family": "procore",
        "description": "Snapshot of the active Procore context: company name, active project name + id, user role. Requires procore_access_token saved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer",
                                "description": "Override the saved active project id."},
                "company_id": {"type": "integer",
                                "description": "Override the saved active company id."},
            },
            "required": [],
        },
        "endpoint": ("procore", "info"),
    },
    {
        "name": "procore_list_projects",
        "family": "procore",
        "description": "List Procore projects the user can access within a company. Pass company_id to target a different company than the saved default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "integer"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_projects"),
    },
    {
        "name": "procore_list_users",
        "family": "procore",
        "description": "List users on the active Procore project. Use this to resolve a name to an id for assignee_id on create_rfi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_users"),
    },
    {
        "name": "procore_list_rfis",
        "family": "procore",
        "description": (
            "List RFIs on the active Procore project, newest first. "
            "Each item carries id, number, subject, status, assignee, "
            "due_date. Filter by status='open' / 'closed' / 'draft' etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer",
                                "description": "Override the active project id."},
                "status": {"type": "string",
                            "description": "Procore RFI status filter (open / closed / draft)."},
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_rfis"),
    },
    {
        "name": "procore_get_rfi",
        "family": "procore",
        "description": (
            "Fetch the full body of one Procore RFI by id. REQUIRES a "
            "real rfi_id from procore_list_rfis — RFI ids are integers "
            "assigned by Procore, NOT placeholders. Returns the full "
            "RFI envelope (question, responses, attachments, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfi_id":     {"type": "integer",
                                "description": "Procore RFI id (integer)."},
                "project_id": {"type": "integer"},
            },
            "required": ["rfi_id"],
        },
        "endpoint": ("procore", "get_rfi"),
    },
    {
        "name": "procore_create_rfi",
        "family": "procore",
        "description": (
            "Create a new RFI on the active Procore project. WRITES to "
            "a live construction database — by default the user is "
            "prompted to approve before submission (ai_behaviour policy "
            "= 'ask'). assignee_id can be resolved via procore_list_users."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":      {"type": "string",
                                  "description": "Short RFI subject line."},
                "question":     {"type": "string",
                                  "description": "The RFI question body. Markdown OK."},
                "project_id":   {"type": "integer"},
                "assignee_id":  {"type": "integer",
                                  "description": "Procore user id of the primary assignee."},
                "due_date":     {"type": "string",
                                  "description": "Due date as YYYY-MM-DD."},
            },
            "required": ["subject", "question"],
        },
        "endpoint": ("procore", "create_rfi"),
    },
    {
        "name": "procore_list_submittals",
        "family": "procore",
        "description": "List submittals on the active Procore project. Each item carries id, number, title, status, ball_in_court.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "status":     {"type": "string"},
                "limit":      {"type": "integer", "default": 20},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_submittals"),
    },
    {
        "name": "procore_list_change_orders",
        "family": "procore",
        "description": "List change orders (CCOs / PCOs) on the active Procore project. Each item has id, number, title, status, amount.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "status":     {"type": "string"},
                "limit":      {"type": "integer", "default": 20},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_change_orders"),
    },
    {
        "name": "procore_list_daily_logs",
        "family": "procore",
        "description": "List daily-log entries from the active Procore project. Pass log_date='YYYY-MM-DD' to target one date; omit for most recent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "log_date":   {"type": "string",
                                "description": "YYYY-MM-DD"},
                "limit":      {"type": "integer", "default": 10},
            },
            "required": [],
        },
        "endpoint": ("procore", "list_daily_logs"),
    },

    # ArchHub local helpers (always available)
    {
        "name": "archhub_list_connectors",
        "family": "_local",
        "description": "List ArchHub connectors and their current state (active/ready/unavailable).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("_local", "list_connectors"),
    },

    # ─── Library tools (AgDR-0013 §"Composer tool surface") ──────────
    # LIBRARY-FIRST mandate: the Composer agent searches the library
    # BEFORE composing a new node. Layer 3 (library_gate) enforces the
    # ordering structurally; Layer 4 (library_validator) enforces
    # MODULARITY on every new spec.
    {
        "name": "library_search",
        "family": "_local",
        "description": (
            "Search the ArchHub library for an existing node-type that "
            "matches the caller's intent. CALL THIS BEFORE library_create_node_type. "
            "Returns matches sorted by similarity score (>=30 = match)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "What the new node should do, in natural language.",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "input", "connector", "ai", "logic", "output",
                        "skill", "shape", "watch", "note", "glue", "adapter",
                    ],
                    "description": "Optional category filter.",
                },
                "limit": {
                    "type": "integer",
                    "default": 8,
                    "description": "Max results to return.",
                },
            },
            "required": ["intent"],
        },
        "endpoint": ("_local", "library_search"),
    },
    {
        "name": "library_list_node_types",
        "family": "_local",
        "description": (
            "List every registered node-type, optionally filtered by "
            "category. Use this for an inventory; use library_search "
            "to find a match for an intent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional category filter.",
                },
            },
            "required": [],
        },
        "endpoint": ("_local", "library_list_node_types"),
    },
    {
        "name": "library_inspect",
        "family": "_local",
        "description": (
            "Return the full ModularNodeSpec for one registered "
            "node-type (typed inputs, outputs, config_schema, "
            "description, examples, side_effects)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "Canonical type name, e.g. 'revit.tag_by_room'.",
                },
            },
            "required": ["node_type"],
        },
        "endpoint": ("_local", "library_inspect"),
    },
    {
        "name": "library_create_node_type",
        "family": "_local",
        "description": (
            "Register a new modular node-type in the library. MUST be "
            "preceded by library_search this turn (LIBRARY-FIRST "
            "mandate). The `spec` must satisfy ModularNodeSpec — typed "
            "inputs + outputs, parameterised config_schema, description "
            "(>=80 chars), examples (>=1 for pure, >=2 for host_write / "
            "network)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "ModularNodeSpec JSON object — see AgDR-0014 §Token 1+ for the contract.",
                },
            },
            "required": ["spec"],
        },
        "endpoint": ("_local", "library_create_node_type"),
    },
    {
        "name": "library_delete_node_type",
        "family": "_local",
        "description": (
            "Remove a registered node-type from the library. "
            "User-confirmation is required (the bridge surfaces a "
            "dialog before this fires)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "Canonical type name to delete.",
                },
            },
            "required": ["node_type"],
        },
        "endpoint": ("_local", "library_delete_node_type"),
    },

    # AgDR-0038 — Composer Capability Node authoring. node_search finds
    # an existing Capability Node to reuse (LIBRARY-FIRST); node_create
    # mints a new one as data (typed I/O + an `impl` block) — the
    # Composer designs node types without a developer hand-coding each.
    {
        "name": "node_search",
        "family": "_local",
        "description": (
            "Search existing Capability Nodes for one matching an "
            "intent. CALL THIS BEFORE node_create — reuse beats a "
            "duplicate. Returns matches ranked by score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "What the node should do, in natural language.",
                },
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["intent"],
        },
        "endpoint": ("_local", "node_search"),
    },
    {
        "name": "node_create",
        "family": "_local",
        "description": (
            "Mint a Capability Node from a data spec — typed inputs + "
            "outputs + an `impl` block. PREFER impl.kind=graph: compose "
            "the logic from wired primitives (the AgDR-0040 modular "
            "model). Other kinds: connector (one host op), ai (one LLM "
            "call), passthrough. python is a LAST-RESORT sealed leaf — "
            "use it only for a computation no primitive can express. "
            "MUST be preceded by node_search this turn. Registers the "
            "node executable + placeable. Returns {type, inputs, outputs}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "Capability spec — see AgDR-0038 §'Capability spec — canonical shape'.",
                },
            },
            "required": ["spec"],
        },
        "endpoint": ("_local", "node_create"),
    },
    {
        "name": "node_place",
        "family": "_local",
        "description": (
            "Place an instance of a registered node type on the canvas. "
            "Returns an add_node delta — {node_id, type, resolved "
            "inputs + outputs}. Use node_search / node_create first to "
            "get a type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string",
                         "description": "Registered node type, e.g. 'pdf.extract_revisions'."},
                "config": {"type": "object",
                           "description": "Optional node config values."},
                "x": {"type": "number", "description": "Canvas x (optional)."},
                "y": {"type": "number", "description": "Canvas y (optional)."},
            },
            "required": ["type"],
        },
        "endpoint": ("_local", "node_place"),
    },
    {
        "name": "graph_wire",
        "family": "_local",
        "description": (
            "Wire one node's output port to another node's input port. "
            "Returns an add_wire delta. Full port-type checking runs at "
            "cook time via Workflow.validate()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_node": {"type": "string"},
                "src_port": {"type": "string"},
                "dst_node": {"type": "string"},
                "dst_port": {"type": "string"},
            },
            "required": ["src_node", "src_port", "dst_node", "dst_port"],
        },
        "endpoint": ("_local", "graph_wire"),
    },
    # AgDR-0041 Property 3 — freeze a node so it returns its cached
    # value + downstream keeps cooking. Useful for an expensive
    # upstream stage you want to pin while iterating later stages.
    {
        "name": "node_freeze",
        "family": "_local",
        "description": (
            "Freeze (or unfreeze) a node by id. Frozen nodes return "
            "their last cached output; upstream changes do not re-cook "
            "them. Pass state=false to unfreeze. Emits a set_node "
            "delta with {frozen: bool}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "state":   {"type": "boolean",
                            "description": "true = freeze (default), false = unfreeze."},
            },
            "required": ["node_id"],
        },
        "endpoint": ("_local", "node_freeze"),
    },
    # Tier 1 — ComfyUI workflow → Capability Node spec auto-import.
    # Founder's 2026-05-24 assimilation: paste a JSON, get a typed
    # ArchHub node back that wraps comfyui.run_workflow under the
    # hood. Pass register=true to also persist it to the library.
    {
        "name": "library_import_comfyui_workflow",
        "family": "_local",
        "description": (
            "Import a ComfyUI API-format workflow JSON as an ArchHub "
            "Capability Node. Open input ports (CLIPTextEncode, "
            "LoadImage, Primitive*) become the node's inputs; "
            "SaveImage / PreviewImage / VHS_VideoCombine sinks become "
            "its outputs. Pass register=true to also register the spec "
            "with the library; otherwise just returns the spec for "
            "caller inspection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow":     {"description": "ComfyUI workflow JSON (object or string)."},
                "type_name":    {"type": "string",
                                  "description": "Capability type id, e.g. 'comfy.archviz_v1'."},
                "display_name": {"type": "string"},
                "description":  {"type": "string"},
                "category":     {"type": "string", "default": "render"},
                "register":     {"type": "boolean", "default": False},
            },
            "required": ["workflow", "type_name"],
        },
        "endpoint": ("_local", "library_import_comfyui_workflow"),
    },
    # AgDR-0041 Property 2 — type-compatible swap suggestions.
    # Powers the right-click "swap with…" menu by returning nodes
    # whose port types match the target's signature.
    {
        "name": "library_suggest_swaps",
        "family": "_local",
        "description": (
            "Find registered node types whose ports match the target's "
            "I/O signature. Use this to swap one node for a compatible "
            "alternative without breaking the wire. Pass either `type` "
            "(lift I/O from the registry) OR explicit `in_types` + "
            "`out_types` arrays. Returns ranked alternatives + their "
            "ports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type":      {"type": "string",
                              "description": "Existing registered type whose I/O to mirror."},
                "in_types":  {"type": "array", "items": {"type": "string"},
                              "description": "Required input port types."},
                "out_types": {"type": "array", "items": {"type": "string"},
                              "description": "Required output port types."},
                "limit":     {"type": "integer", "default": 10},
            },
        },
        "endpoint": ("_local", "library_suggest_swaps"),
    },
    # AgDR-0041 Property 4 — delete-with-auto-bridge analyzer. Given
    # the graph + a node about to be deleted, return either an
    # auto-bridge wire (compat types) or a broken-wire dialog with
    # recovery options. UI calls this BEFORE actually removing the
    # node so the user can decide.
    {
        "name": "graph_on_node_delete",
        "family": "_local",
        "description": (
            "Analyse the impact of deleting a node. Returns one of: "
            "(a) silent_delete — no incident wires, safe; "
            "(b) auto_bridge — upstream src port type matches "
            "downstream dst port type, wire(s) to add after delete; "
            "(c) broken_wire — type mismatch, recovery dialog should "
            "offer adapter / restore / swap. The UI calls this BEFORE "
            "removing the node so the user decides."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "graph":   {"type": "object",
                            "description": "Full graph snapshot "
                                            "(nodes + wires/edges)."},
            },
            "required": ["node_id", "graph"],
        },
        "endpoint": ("_local", "graph_on_node_delete"),
    },
    # AgDR-0042 D1·C slice 3/6 — memory.query() exposed as an LLM tool.
    # Back-compat shim around node_search; the LLM gets a richer ranker
    # that joins library + Composer-turn signals into one queryable
    # graph. Falls through to an empty result list cleanly when the
    # memory graph hasn't been populated yet (first run / fresh install).
    {
        "name": "memory_query",
        "family": "_local",
        "description": (
            "Search the shared-memory knowledge graph. Returns ranked "
            "nodes (Capabilities, Skills, prior Composer turns, "
            "decisions) matching the question. Each hit carries `id`, "
            "`kind`, `label`, `score`, and a one-line `why` provenance "
            "string. Use this in place of `node_search` whenever the "
            "user asks 'find me a Skill / Capability / prior workflow "
            "that does X' — the graph join lifts relevance beyond pure "
            "name matching by including past usage + skill composition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "kinds":    {"type": "array", "items": {"type": "string"},
                              "description": "Filter by node kind, e.g. "
                                              "['skill'] or "
                                              "['capability','skill']."},
                "limit":    {"type": "integer", "default": 10},
                "min_score": {"type": "number", "default": 0.0},
            },
            "required": ["question"],
        },
        "endpoint": ("_local", "memory_query"),
    },
    # AgDR-0041 Property 5 — live validator. UI calls this on every
    # graph edit (debounced) to colour wires + nodes green/yellow/red
    # without waiting for cook. Returns the same issue shape as
    # Workflow.validate_v2() but accepts the lighter JSX graph
    # snapshot ({nodes:[{id,ins,outs}], wires:[{from,to}]}).
    {
        "name": "graph_validate",
        "family": "_local",
        "description": (
            "Validate a graph snapshot. Returns a list of issues: "
            "duplicate_id / missing_src / missing_dst / "
            "unknown_src_port / unknown_dst_port / type_mismatch / "
            "unset_input. Each issue carries level (err/warn), code, "
            "node_id, edge_id, and msg. UI uses this to paint wires + "
            "nodes green / yellow / red live, before cook."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "graph": {"type": "object",
                          "description": "Graph snapshot — accepts the "
                                          "JSX {nodes, wires} shape or the "
                                          "Workflow {nodes, edges} shape."},
            },
            "required": ["graph"],
        },
        "endpoint": ("_local", "graph_validate"),
    },
    # AgDR-0041 Property 6 — bypass a node so the runner skips its
    # executor and passes upstream input directly to the downstream
    # output (port-name match, then type-only fallback). No cache held.
    {
        "name": "node_bypass",
        "family": "_local",
        "description": (
            "Bypass (or un-bypass) a node by id. Bypassed nodes are "
            "skipped by the runner; upstream input flows through to "
            "downstream output by port-name match. Pass state=false to "
            "re-enable. Use this to A/B-test wires or temporarily skip "
            "an expensive cloud call (e.g. an upscale stage). Emits a "
            "set_node delta with {bypassed: bool}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "state":   {"type": "boolean",
                            "description": "true = bypass (default), false = un-bypass."},
            },
            "required": ["node_id"],
        },
        "endpoint": ("_local", "node_bypass"),
    },

    # AI-as-tool — call other models from inside a chat turn. The
    # primary LLM can delegate to ChatGPT for code, Gemini for vision /
    # long context, or LM Studio for offline / privacy-bound work.
    # No host needs to be installed; configuration is per-provider
    # API key in Settings → Sign-ins.
    {
        "name": "ai_chatgpt_ask",
        "family": "ai",
        "description": (
            "Ask OpenAI (GPT-5.5 / GPT-5.4 / o-series) a question and "
            "return the answer text. Default model: gpt-5.4-mini (cheap "
            "+ fast). Bump to gpt-5.5 for reasoning, gpt-5.5-pro for the "
            "heaviest work. Requires an OpenAI API key + active billing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                            "description": "The question / instruction to send."},
                "model": {"type": "string",
                          "description": "OpenAI model id, e.g. 'gpt-5.5', 'gpt-5.5-pro', 'gpt-5.4-mini', 'gpt-5.4-nano'. Default: gpt-5.4-mini."},
                "system": {"type": "string",
                            "description": "Optional system prompt."},
                "temperature": {"type": "number",
                                 "description": "0.0-2.0. Lower = more deterministic. Ignored for Pro / o-series."},
                "max_tokens": {"type": "integer",
                                "description": "Cap on the response length."},
            },
            "required": ["prompt"],
        },
        "endpoint": ("ai", "chatgpt_ask"),
    },
    {
        "name": "ai_codex_ask",
        "family": "ai",
        "description": (
            "Ask OpenAI Codex (gpt-5.3-codex / gpt-5.1-codex-max / "
            "gpt-5.1-codex-mini) for code-focused work — refactors, "
            "patches, tests, code review. Codex variants are tuned for "
            "code generation + cheaper than gpt-5.5 for equal-quality "
            "code output. Defaults to temperature 0.1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                            "description": "The question / instruction (code-focused)."},
                "model": {"type": "string",
                          "description": "Codex model id: 'gpt-5.3-codex' (default), 'gpt-5.1-codex-max', 'gpt-5.1-codex-mini'."},
                "system": {"type": "string",
                            "description": "Optional system prompt."},
                "temperature": {"type": "number",
                                 "description": "Default 0.1 — code work rewards low temperatures."},
                "max_tokens": {"type": "integer"},
            },
            "required": ["prompt"],
        },
        "endpoint": ("ai", "codex_ask"),
    },
    {
        "name": "ai_gemini_ask",
        "family": "ai",
        "description": (
            "Ask Google Gemini a question and return the answer text. "
            "Strengths: long-context retrieval, image understanding, "
            "fast/cheap general queries. Requires a Google AI API key "
            "in Settings → Sign-ins."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                            "description": "The question / instruction to send."},
                "model": {"type": "string",
                          "description": "Gemini model id, e.g. 'gemini-2.5-flash', 'gemini-2.5-pro'. Default: gemini-2.5-flash."},
                "system": {"type": "string",
                            "description": "Optional system instruction."},
                "temperature": {"type": "number",
                                 "description": "0.0–2.0. Lower = more deterministic."},
            },
            "required": ["prompt"],
        },
        "endpoint": ("ai", "gemini_ask"),
    },
    {
        "name": "ai_lmstudio_ask",
        "family": "ai",
        "description": (
            "Ask the model currently loaded in LM Studio (local, "
            "OpenAI-compatible). No API key needed for localhost. "
            "Strengths: offline / privacy-bound work, free inference. "
            "LM Studio must be running with a model loaded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                            "description": "The question / instruction."},
                "model": {"type": "string",
                          "description": "Model id LM Studio should use; pass 'auto' (default) for whichever is loaded."},
                "system": {"type": "string",
                            "description": "Optional system prompt."},
                "base_url": {"type": "string",
                              "description": "LM Studio server URL. Default: http://localhost:1234/v1."},
                "temperature": {"type": "number",
                                 "description": "0.0–2.0."},
            },
            "required": ["prompt"],
        },
        "endpoint": ("ai", "lmstudio_ask"),
    },
    {
        "name": "ai_antigravity_ask",
        "family": "ai",
        "description": (
            "Ask Google Antigravity (experimental coding agent). NOTE: "
            "Antigravity has no public API yet — the tool errors with "
            "instructions on how to track availability. Listed so the "
            "model can suggest it and the user can be told it's coming."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                            "description": "The question / instruction."},
                "model": {"type": "string",
                          "description": "Antigravity model id (when available)."},
                "system": {"type": "string",
                            "description": "Optional system prompt."},
            },
            "required": ["prompt"],
        },
        "endpoint": ("ai", "antigravity_ask"),
    },
    {
        "name": "ai_list_providers",
        "family": "ai",
        "description": (
            "List configured AI-as-tool providers + which are reachable. "
            "Returns { provider: { configured, reachable?, models } } "
            "so the primary model can decide which ai_*_ask tool to call."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "endpoint": ("ai", "list_providers"),
    },
    {
        "name": "ai_detect_local",
        "family": "ai",
        "description": (
            "Detect ALL LLM backends on the user's machine: Claude, GPT, "
            "Gemini, OpenRouter, Ollama (with model list), LM Studio "
            "(with loaded model), Codex CLI, ArchHub Cloud. Returns "
            "per-provider {status:'live'|'available'|'missing', models, "
            "note}. Cheap probes only (no paid API calls). The primary "
            "model uses this to pick the best ai_*_ask tool — e.g. if "
            "OpenAI is quota-blocked, fall through to Anthropic or LM "
            "Studio."
        ),
        "input_schema": {"type": "object",
                          "properties": {"force": {"type": "boolean",
                                                    "description": "Skip the 25s cache"}},
                          "required": []},
        "endpoint": ("ai", "detect_local"),
    },
]


# ---------------------------------------------------------------------------
class ToolEngine:
    def __init__(self, manager: ConnectorManager):
        self.manager = manager
        self.speckle = SpeckleClient()

    # ---- schema export for LLMs -------------------------------------------

    def tool_schemas_for(self, provider: str) -> list[dict]:
        """Tool schemas for the LLM, in the provider's wire format.

        ROOT-CAUSE FIX (2026-05-16): this used to be a hardcoded
        if/elif over exactly four provider names — anthropic / openai /
        ollama / google. Any provider NOT in that list (openrouter,
        relay, archhub_cloud, lmstudio) silently fell through and got an
        EMPTY tool list. So when the auto-router fell back to OpenRouter
        — its #2 pick in every routing branch — the model received ZERO
        tools, and a tool-less model asked a factual question FABRICATES
        a <function_calls>/<function_result> block and lies about the
        result (founder bug: "no files open in AutoCAD" while a drawing
        was open).

        OpenRouterClient / the relay client are OpenAIClient subclasses
        — they already support tool calls. The only gap was the schema
        export. Now: Anthropic and Google get their own shapes; EVERY
        other provider speaks OpenAI function-calling. No configured
        provider is ever silently tool-less again.
        """
        # Claude Code CLI runs as a headless agent: its tools arrive via
        # `--mcp-config` (an ArchHub MCP server), never as request-time
        # schemas. Phase 1 has no ArchHub tool bridge yet — either way
        # the request-time schema list is empty for claude_cli.
        if provider in ("claude_cli", "codex_cli"):
            return []
        active_families = self._active_families()

        # Wire format: Anthropic + Google have bespoke shapes; everything
        # else (openai, ollama, openrouter, relay, archhub_cloud,
        # lmstudio — all OpenAI-compatible) uses OpenAI function-calling.
        if provider == "anthropic":
            fmt = "anthropic"
        elif provider == "google":
            fmt = "google"
        else:
            fmt = "openai"

        def _wire(name: str, description: str, schema: dict) -> dict:
            if fmt == "anthropic":
                return {"name": name, "description": description,
                        "input_schema": schema}
            if fmt == "google":
                # Gemini wants name + description + JSONSchema params,
                # later wrapped in {"function_declarations": [...]} by
                # the GoogleClient.
                return {"name": name, "description": description,
                        "parameters": schema}
            return {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": schema}}

        out: list[dict] = []
        for t in TOOLS:
            # Always-on families: `_local` (ArchHub helpers), `ai`
            # (AI-as-tool delegations), and `procore` (SaaS — auth via
            # access token, no host install required). Per-provider key
            # may still be missing — handler returns a clean error
            # rather than the tool being filtered out, so the model can
            # suggest signing in instead of silently ignoring the
            # capability.
            if (t["family"] not in ("_local", "ai", "procore")
                    and t["family"] not in active_families):
                continue
            out.append(_wire(t["name"], t["description"], t["input_schema"]))
        # ── Founder bug 2026-05-15 (root): the LLM hallucinated host
        # results because the 116 real, working connector ops were a
        # SEPARATE registry the model could not see. Unify — emit every
        # connector op as a real tool. The model now calls the actual op
        # (e.g. autocad.list_documents) and gets real data or an honest
        # error; it has no reason to fabricate. Ops are namespaced
        # `host.op` so `invoke()` can route them to connectors.base.run_op.
        for spec in self._connector_tool_specs():
            out.append(_wire(spec["name"], spec["description"],
                              spec["input_schema"]))
        return out

    # Connector-op tool specs, cached 20s. Each of the 16 connectors'
    # ops becomes an LLM tool. _CONNECTOR_TOOL_SAFE names use a double
    # underscore in place of the dot so providers that reject '.' in a
    # tool name still accept it; invoke() maps back.
    _CONN_TOOLS_TTL = 20.0

    def _connector_tool_specs(self) -> list:
        import time as _t
        now = _t.time()
        last = getattr(self, "_conn_tools_ts", 0.0)
        cached = getattr(self, "_conn_tools_cache", None)
        if cached is not None and (now - last) < self._CONN_TOOLS_TTL:
            return cached
        specs: list = []
        # AgDR-0034 audit fix (e) — the "." -> "__" tool-name encoding
        # is NOT invertible when an op_id itself contains "__". Carry
        # the raw op_id in a side map; invoke() resolves through it
        # instead of decoding the tool name.
        op_by_name: dict = {}
        try:
            from connectors.base import all_connectors
            for c in all_connectors():
                for op in c.ops():
                    props = {}
                    required = []
                    for p in (op.inputs or []):
                        props[p.id] = {"type": _json_type(p.type),
                                       "description": p.help or p.label or p.id}
                        if p.required:
                            required.append(p.id)
                    _tname = op.op_id.replace(".", "__")
                    op_by_name[_tname] = op.op_id
                    specs.append({
                        "name": _tname,
                        "description": (op.label or op.op_id) + " — "
                                       + (op.description or "")
                                       + _side_effect_tag(op),
                        "input_schema": {"type": "object",
                                          "properties": props,
                                          "required": required},
                    })
        except Exception:
            specs = []
            op_by_name = {}
        self._conn_tools_cache = specs
        self._conn_op_by_name = op_by_name
        self._conn_tools_ts = now
        return specs

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
        # Founder bug 2026-05-15 (root cause): the LLM was hallucinating
        # `<tool_call>` blocks + fabricating results ("Drawing1.dwg open").
        # WHY: a host's tools were exposed to the model ONLY when the
        # connector entry was manager-ACTIVE — a Settings toggle. The
        # AutoCAD BROKER was live (the user could ping it) but the entry
        # was never toggled, so the model had NO acad_* tool, wanted one,
        # and role-played a fake. FIX: expose a family's tools whenever
        # the host is genuinely REACHABLE right now — broker listener
        # answering — regardless of the manager toggle. A model that has
        # the real tool has no reason to fabricate.
        try:
            for fam in self._reachable_broker_families_cached():
                active.add("acad" if fam == "autocad" else fam)
        except Exception:
            pass
        # Rhino auto-activates when the in-Rhino HTTP bridge answers on
        # :9879. Same cache pattern as Outlook — cheap TCP probe but we
        # don't want to run it on every schema call.
        try:
            if self._rhino_active_cached():
                active.add("rhino")
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

    _RH_TTL_SECONDS = 30.0

    def _rhino_active_cached(self) -> bool:
        import time as _t
        now = _t.time()
        last = getattr(self, "_rhino_last_check", 0.0)
        if now - last >= self._RH_TTL_SECONDS:
            self._rhino_last_check = now
            import threading
            threading.Thread(target=self._refresh_rhino_async,
                              daemon=True).start()
        return bool(getattr(self, "_rhino_reachable", False))

    def _refresh_rhino_async(self) -> None:
        try:
            from connectors.rhino_runner import is_reachable as _rh_reachable
            self._rhino_reachable = bool(_rh_reachable())
        except Exception:
            self._rhino_reachable = False

    # Broker-host reachability cache (revit / autocad / max). A live
    # broker listener = the model gets that host's real tools, so it
    # never has to fabricate a tool call. 30s TTL, refreshed off-thread.
    _BROKER_TTL_SECONDS = 30.0
    _BROKER_PORTS = {"revit": 48884, "autocad": 48885, "max": 48886}

    def _reachable_broker_families_cached(self) -> set:
        import time as _t
        now = _t.time()
        last = getattr(self, "_broker_last_check", 0.0)
        if now - last >= self._BROKER_TTL_SECONDS:
            self._broker_last_check = now
            import threading
            threading.Thread(target=self._refresh_brokers_async,
                              daemon=True).start()
        return set(getattr(self, "_broker_reachable", set()))

    def _refresh_brokers_async(self) -> None:
        import socket
        live = set()
        for fam, port in self._BROKER_PORTS.items():
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    live.add(fam)
            except Exception:
                pass
        self._broker_reachable = live

    # ---- invocation -------------------------------------------------------

    def invoke(self, tool_name: str, args: dict,
               session_pin: Optional[str] = None,
               *, user_confirmed: bool = False) -> dict:
        """Invoke one tool.

        session_pin — optional token used to disambiguate when multiple
        instances of the same host (e.g. two Revit windows) are alive.
        Tokens are resolved against each broker's pick_session(prefer=...)
        which matches against session_id, pid, doc_title substring, or
        SMTP for Outlook. Ignored for tools whose family has no broker
        (speckle, blender today, _local).

        user_confirmed — when True, bypass the 'ask' policy gate. Used
        by the chat layer after the user clicks Approve on a pending
        tool invocation. 'deny' policy is NOT bypassable.
        """
        # ── Connector-op tools (host__op) route to connectors.base.run_op.
        # Founder bug 2026-05-15 root fix: the 116 real connector ops are
        # now the LLM's tools. A model that calls autocad__list_documents
        # gets REAL data — it never has to fabricate.
        if "__" in tool_name and not next(
                (t for t in TOOLS if t["name"] == tool_name), None):
            # AgDR-0034 audit fix (e) — resolve through the raw-op_id
            # map; the "__" -> "." decode is lossy for op_ids that
            # themselves contain "__". Fallback decode only if the map
            # has not been built yet (it always is before the LLM can
            # call a connector tool).
            op_id = getattr(self, "_conn_op_by_name", {}).get(
                tool_name) or tool_name.replace("__", ".")
            try:
                from ai_behaviour import get_tool_policy
                pol = get_tool_policy(tool_name)
            except Exception:
                pol = "allow"
            if pol == "deny":
                return {"status": "error", "policy": "deny",
                        "error": f"Tool {tool_name!r} blocked by user policy."}
            if pol == "ask" and not user_confirmed:
                return {"status": "needs_confirmation", "tool_name": tool_name,
                        "arguments": args, "policy": "ask",
                        "reason": f"{op_id} needs your approval."}
            try:
                from connectors.base import run_op
                res = run_op(op_id, **(args or {}))
                d = res.to_dict() if hasattr(res, "to_dict") else {}
                if d.get("ok"):
                    return {"status": "ok", "result": d.get("value"),
                            "preview": d.get("value_preview", "")}
                return {"status": "error",
                        "error": d.get("error") or "connector op failed"}
            except Exception as ex:
                return {"status": "error",
                        "error": f"{type(ex).__name__}: {ex}"}

        tool = next((t for t in TOOLS if t["name"] == tool_name), None)
        if tool is None:
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        # User policy gate — Settings → AI Behaviour. Three policies:
        #   allow → fire immediately
        #   ask   → return needs_confirmation; chat UI prompts user
        #   deny  → hard block; returns error status
        try:
            from ai_behaviour import get_tool_policy
            policy = get_tool_policy(tool_name)
        except Exception:
            policy = "allow"
        if policy == "deny":
            return {
                "status": "error",
                "error": (
                    f"Tool {tool_name!r} is blocked by user policy "
                    f"(Settings → AI Behaviour → Tool permissions)."
                ),
                "policy": "deny",
            }
        if policy == "ask" and not user_confirmed:
            return {
                "status": "needs_confirmation",
                "tool_name": tool_name,
                "arguments": args,
                "reason": (
                    f"{tool_name} needs your approval. "
                    "Settings → AI Behaviour → Tool permissions "
                    "to change."
                ),
                "policy": "ask",
            }

        ep = tool["endpoint"]

        # _local family → built-in handlers
        if tool["family"] == "_local":
            handler = ep[1]
            if handler == "list_connectors":
                return {"status": "ok", "connectors": [
                    {"id": e.id, "name": e.display_name, "state": e.state.name}
                    for e in self.manager.entries
                ]}
            # Library handlers (AgDR-0013 §"Composer tool surface").
            # These dispatch to the in-process library module. The
            # LIBRARY-FIRST gate (Layer 3) runs BEFORE this point in the
            # router; we never see denied calls here.
            if handler.startswith("library_"):
                return self._invoke_library_handler(handler, args or {})
            # AgDR-0038 Capability Node tools (node_search / node_create /
            # node_place / graph_wire).
            if (handler.startswith("node_") or handler == "graph_wire"
                    or handler == "graph_on_node_delete"
                    or handler == "graph_validate"):
                return self._invoke_node_handler(handler, args or {})
            # AgDR-0042 slice 3/6 — memory.query() exposed as a tool.
            if handler == "memory_query":
                return self._invoke_memory_query(args or {})
            return {"status": "error", "error": f"Unknown local handler: {handler}"}

        # speckle family
        if tool["family"] == "speckle":
            handler = ep[1]
            try:
                return self.speckle.dispatch(handler, args)
            except Exception as ex:
                return {"status": "error", "error": str(ex)}

        # ai family — call other LLMs as tools (ChatGPT / Gemini /
        # LM Studio / Antigravity). No host install required; each
        # handler in ai_runner.py uses the user's saved API key for
        # that provider. session_pin is ignored — there is no concept
        # of a session for these calls.
        if tool["family"] == "ai":
            handler = ep[1]
            try:
                from connectors import ai_runner as _ai
                fn = getattr(_ai, handler, None)
                if fn is None:
                    return {"status": "error",
                            "error": f"Unknown ai handler: {handler}"}
                import inspect
                sig = inspect.signature(fn)
                kwargs = {k: v for k, v in (args or {}).items()
                          if k in sig.parameters}
                result = fn(**kwargs)
                if isinstance(result, dict):
                    if "status" not in result:
                        result = {"status": "ok", **result}
                    return result
                return {"status": "ok", "result": result}
            except Exception as ex:
                return {"status": "error", "error": str(ex)[:300]}

        # rhino family — HTTP bridge inside Rhino's embedded Python.
        # Dispatch mirrors outlook: handler name in ep[1], rhino_runner
        # exposes one function per handler. No session pin (Rhino has
        # one active doc per process).
        if tool["family"] == "rhino":
            handler = ep[1]
            try:
                from connectors import rhino_runner as _rh
                fn = getattr(_rh, handler, None)
                if fn is None:
                    return {"status": "error",
                            "error": f"Unknown rhino handler: {handler}"}
                import inspect
                sig = inspect.signature(fn)
                kwargs = {k: v for k, v in (args or {}).items()
                          if k in sig.parameters}
                result = fn(**kwargs)
                if isinstance(result, dict):
                    if "status" not in result:
                        result = {"status": "ok", **result}
                    return result
                return {"status": "ok", "result": result}
            except Exception as ex:
                return {"status": "error", "error": str(ex)[:300]}

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

        # procore family — REST/SaaS, no host install. Routes directly
        # to procore_runner. The session_pin (when present) is forwarded
        # as `project_id` to handlers that accept it, so a chat-time
        # "@token" can target a different project than the saved default.
        if tool["family"] == "procore":
            handler = ep[1]
            try:
                from connectors import procore_runner as _pc
                fn = getattr(_pc, handler, None)
                if fn is None:
                    return {"status": "error",
                            "error": f"Unknown procore handler: {handler}"}
                import inspect
                sig = inspect.signature(fn)
                merged = dict(args or {})
                if session_pin and "project_id" in sig.parameters \
                        and not merged.get("project_id"):
                    try:
                        merged["project_id"] = int(session_pin)
                    except Exception:
                        pass
                kwargs = {k: v for k, v in merged.items() if k in sig.parameters}
                result = fn(**kwargs)
                # is_reachable returns a bare bool — normalise into the
                # standard envelope so the chat layer can render it.
                if isinstance(result, bool):
                    return {"status": "ok", "reachable": result}
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

    # ---- library tool dispatch -------------------------------------------

    def _invoke_library_handler(self, handler: str, args: dict) -> dict:
        """Dispatch one of the five library_* tools to app/library.py.

        The five tools (AgDR-0013 §"Composer tool surface"):
          library_search          -> library.search(intent, ...)
          library_list_node_types -> library.list_node_types(category?)
          library_inspect         -> library.inspect(node_type)
          library_create_node_type-> library.create_node_type(spec)
          library_delete_node_type-> library.delete_node_type(node_type)

        Returns a dict with `status: ok|error`. Validator violations from
        `library.create_node_type` come back as `status:error` with a
        `violations` list — the LLM can correct in one retry.
        """
        try:
            import library as _lib
        except Exception as ex:
            return {
                "status": "error",
                "error": f"library module import failed: {ex}",
            }

        try:
            if handler == "library_search":
                results = _lib.search(
                    intent=args.get("intent", ""),
                    input_schema=args.get("input_schema"),
                    output_schema=args.get("output_schema"),
                    category=args.get("category"),
                    limit=int(args.get("limit", 8)),
                )
                return {"status": "ok", "results": results,
                        "count": len(results)}

            if handler == "library_list_node_types":
                items = _lib.list_node_types(category=args.get("category"))
                return {"status": "ok", "items": items, "count": len(items)}

            if handler == "library_inspect":
                spec = _lib.inspect(args.get("node_type", ""))
                return {"status": "ok", "spec": spec}

            if handler == "library_create_node_type":
                result = _lib.create_node_type(args.get("spec") or {})
                return {"status": "ok", **result}

            if handler == "library_delete_node_type":
                result = _lib.delete_node_type(args.get("node_type", ""))
                return {"status": "ok", **result}

            if handler == "library_import_comfyui_workflow":
                # Tier 1 — paste a ComfyUI JSON, get a Capability Node
                # spec back. Caller can then library_create_node_type
                # to register it, or inspect first.
                try:
                    from workflows.comfyui_import import (
                        analyze_workflow, to_capability_spec)
                except Exception as ex:
                    return {"status": "error",
                            "error": f"comfyui_import unavailable: {ex}"}
                wf = args.get("workflow")
                if wf is None:
                    return {"status": "error",
                            "error": "library_import_comfyui_workflow "
                                     "needs `workflow` (JSON object or string)"}
                type_name = str(args.get("type_name", "") or "").strip()
                if not type_name:
                    return {"status": "error",
                            "error": "type_name required (e.g. "
                                     "'comfy.archviz_v1')"}
                try:
                    summary = analyze_workflow(wf)
                    spec = to_capability_spec(
                        workflow=wf,
                        type_name=type_name,
                        display_name=str(args.get("display_name", "") or ""),
                        description=str(args.get("description", "") or ""),
                        category=str(args.get("category", "render") or "render"),
                    )
                except ValueError as ex:
                    return {"status": "error", "error": str(ex)}
                register_now = bool(args.get("register", False))
                registered = False
                if register_now:
                    try:
                        _lib.create_node_type(spec)
                        registered = True
                    except _lib.RegistrationError as ex:
                        return {"status": "error",
                                "error": f"spec validator rejected: {ex}",
                                "violations": ex.violations,
                                "spec": spec}
                    except _lib.DuplicateTypeError:
                        registered = False  # already exists, spec returned
                return {"status": "ok", "spec": spec, "summary": summary,
                        "registered": registered}

            if handler == "library_suggest_swaps":
                # AgDR-0041 P2 — type-compatible swap suggestions over
                # the in-process workflows.registry (the live set the
                # canvas actually wires against). Custom Capability
                # nodes minted via node_create also live here once
                # registered, so the suggester covers both.
                target_type = str(args.get("type", "") or "").strip()
                in_types  = [str(t).lower() for t in (args.get("in_types")  or [])]
                out_types = [str(t).lower() for t in (args.get("out_types") or [])]
                limit = int(args.get("limit", 10))
                try:
                    import workflows.registry as _wreg
                except Exception as ex:
                    return {"status": "error",
                            "error": f"registry unavailable: {ex}"}
                if target_type and not (in_types or out_types):
                    spec_tup = _wreg.get(target_type)
                    if spec_tup is None:
                        return {"status": "error",
                                "error": f"unknown node type {target_type!r}"}
                    spec, _ = spec_tup
                    in_types  = [getattr(p.type, "value", str(p.type))
                                 for p in (spec.inputs or [])]
                    out_types = [getattr(p.type, "value", str(p.type))
                                 for p in (spec.outputs or [])]
                results: list = []
                for spec in _wreg.all_specs():
                    if spec.type == target_type:
                        continue
                    spec_in  = [getattr(p.type, "value", str(p.type)).lower()
                                for p in (spec.inputs or [])]
                    spec_out = [getattr(p.type, "value", str(p.type)).lower()
                                for p in (spec.outputs or [])]
                    in_match  = all(t in spec_in  or t == "any" or "any" in spec_in
                                    for t in in_types)  if in_types  else True
                    out_match = all(t in spec_out or t == "any" or "any" in spec_out
                                    for t in out_types) if out_types else True
                    if not (in_match and out_match):
                        continue
                    score = (10 if in_match else 0) + (10 if out_match else 0)
                    if target_type:
                        tgt_spec = _wreg.get(target_type)
                        if tgt_spec and tgt_spec[0].category == spec.category:
                            score += 5
                    results.append((score, spec))
                results.sort(key=lambda p: -p[0])
                out_list = [
                    {"type": s.type,
                     "display_name": s.display_name or s.type,
                     "category": s.category,
                     "score": sc,
                     "in":  [getattr(p.type, "value", str(p.type))
                             for p in (s.inputs or [])],
                     "out": [getattr(p.type, "value", str(p.type))
                             for p in (s.outputs or [])]}
                    for sc, s in results[:max(1, limit)]
                ]
                return {"status": "ok", "results": out_list,
                        "count": len(out_list)}

            return {"status": "error",
                    "error": f"Unknown library handler: {handler}"}

        except _lib.RegistrationError as ex:
            # The validator rejected the spec. Surface the violations so
            # the LLM can correct in one retry (the layer-3 gate would
            # already have caught this if the router is wired; this is
            # belt-and-braces for direct calls / tests).
            return {"status": "error", "error": str(ex),
                    "violations": ex.violations}
        except _lib.DuplicateTypeError as ex:
            return {"status": "error", "error": str(ex),
                    "code": "duplicate_type"}
        except _lib.UnknownTypeError as ex:
            return {"status": "error", "error": str(ex),
                    "code": "unknown_type"}
        except Exception as ex:
            return {"status": "error",
                    "error": f"{type(ex).__name__}: {ex}"}

    # ---- AgDR-0042 slice 3/6 — memory.query() handler --------------------

    def _invoke_memory_query(self, args: dict) -> dict:
        """Handler for the `memory_query` LLM tool.

        Opens the default MemoryGraph + runs `query()` against the
        question + filters. Lazy-opens the graph per call (SQLite open
        is microseconds at this scale); a future hot-path optimisation
        can cache the handle, but keeping it stateless avoids cross-
        request bleed (different users / sessions) at the cost of a
        few µs.

        Falls through to {status:'ok', results:[]} when the graph file
        doesn't exist yet (first run / fresh install / before any
        extractor has been called) — the LLM gets an honest "nothing
        here yet" rather than a crash, mirroring node_search's
        empty-library behaviour.
        """
        question = str(args.get("question", "") or "").strip()
        if not question:
            return {"status": "error", "error": "memory_query needs `question`"}
        try:
            from memory import MemoryGraph
            from memory.query import query as _mq
        except Exception as ex:
            return {"status": "error",
                    "error": f"memory package unavailable: {ex}"}
        try:
            g = MemoryGraph.open()
            try:
                kinds = args.get("kinds")
                limit = int(args.get("limit", 10))
                min_score = float(args.get("min_score", 0.0))
                results = _mq(
                    g, question,
                    kinds=tuple(kinds) if kinds else None,
                    limit=limit, min_score=min_score,
                )
                return {"status": "ok", "results": results,
                        "count": len(results)}
            finally:
                g.close()
        except Exception as ex:
            return {"status": "error",
                    "error": f"{type(ex).__name__}: {ex}"}

    # ---- AgDR-0038 — Capability Node tool dispatch -----------------------

    def _invoke_node_handler(self, handler: str, args: dict) -> dict:
        """Dispatch the Composer's Capability-Node tools (AgDR-0038).

          node_search  -> rank persisted Capability specs by intent
          node_create  -> register a Capability spec; it becomes an
                          immediately executable + placeable node type

        node_create is the O(1) replacement for hand-designing a node
        type (grammar primitive + registry spec + executor + AgDR each).
        """
        import re as _re
        try:
            import workflows.custom_nodes as _cn
        except Exception as ex:
            return {"status": "error",
                    "error": f"custom_nodes import failed: {ex}"}
        try:
            if handler == "node_search":
                intent = str(args.get("intent", "") or "").lower().strip()
                limit = int(args.get("limit", 8))
                if not intent:
                    return {"status": "ok", "results": [], "count": 0}
                words = {w for w in _re.findall(r"[a-z0-9_]+", intent)
                         if len(w) > 1}
                ranked: list = []
                for spec in _cn.list_specs():
                    hay = " ".join(
                        str(spec.get(k, "")) for k in
                        ("type", "display_name", "description", "category")
                    ).lower()
                    score = 50 if intent in hay else 0
                    score += 5 * sum(1 for w in words if w in hay)
                    if score > 0:
                        ranked.append((score, spec))
                ranked.sort(key=lambda p: -p[0])
                results = [
                    {"type": s.get("type"),
                     "display_name": s.get("display_name") or s.get("type"),
                     "category": s.get("category"),
                     "score": sc}
                    for sc, s in ranked[:max(1, limit)]
                ]
                return {"status": "ok", "results": results,
                        "count": len(results)}

            if handler == "node_create":
                spec = args.get("spec") or {}
                if not isinstance(spec, dict) or not spec.get("type"):
                    return {"status": "error",
                            "error": "node_create needs a spec dict "
                                     "carrying a `type`"}
                new_type = str(spec.get("type"))

                def _sig_words(s: dict) -> set:
                    text = (str(s.get("display_name", "")) + " " +
                            str(s.get("description", ""))).lower()
                    return {w for w in _re.findall(r"[a-z0-9_]+", text)
                            if len(w) > 1}

                # LIBRARY-FIRST (AgDR-0038 Delta 3) — refuse a near-
                # duplicate of an existing Capability Node; the Composer
                # should reuse it. Same `type` is an UPDATE — allowed.
                new_words = _sig_words(spec)
                if new_words:
                    for other in _cn.list_specs():
                        if other.get("type") == new_type:
                            continue
                        ow = _sig_words(other)
                        if ow and len(new_words & ow) / len(new_words) >= 0.7:
                            return {
                                "status": "error",
                                "code": "duplicate",
                                "error": "a near-identical Capability Node "
                                         f"already exists: "
                                         f"'{other.get('type')}' — reuse it "
                                         "instead of minting a duplicate "
                                         "(LIBRARY-FIRST).",
                                "reuse": other.get("type"),
                            }

                node_spec = _cn.register_spec(spec)   # validates + registers
                _cn.write_spec(spec)                  # persist to disk

                # Auto-promote to the library so the node is searchable +
                # grows the inventory by use (AgDR-0038 Delta 3).
                # Best-effort: a non-modular spec is still a working node,
                # just not library-promoted until it meets the bar.
                promoted = False
                promo_note = ""
                try:
                    import library as _lib2
                    try:
                        _lib2.create_node_type(spec)
                    except _lib2.DuplicateTypeError:
                        _lib2.delete_node_type(new_type)
                        _lib2.create_node_type(spec)
                    promoted = True
                except Exception as ex:
                    promo_note = f"{type(ex).__name__}: {ex}"

                result = {
                    "status": "ok",
                    "type": node_spec.type,
                    "inputs": [p.name for p in node_spec.inputs],
                    "outputs": [p.name for p in node_spec.outputs],
                    "library_promoted": promoted,
                    "library_note": promo_note,
                }
                # AgDR-0040 slice 4 — steer the Composer toward composed
                # logic. A python node still mints (sealed leaf), but the
                # result nudges graph for next time.
                impl_kind = ((spec.get("impl") or {}).get("kind")
                             or ("python" if spec.get("code") else ""))
                if impl_kind == "python":
                    result["hint"] = (
                        "minted as impl.kind=python — a sealed leaf. If "
                        "this logic can be expressed as wired primitives, "
                        "prefer impl.kind=graph: inspectable, reusable, "
                        "composable.")
                return result

            if handler == "node_place":
                type_name = str(args.get("type", "") or "").strip()
                if not type_name:
                    return {"status": "error",
                            "error": "node_place needs a `type`"}
                import workflows.registry as _reg
                hit = _reg.get(type_name)
                if not hit:
                    return {"status": "error",
                            "error": f"type '{type_name}' is not registered "
                                     f"— node_create it first"}
                spec = hit[0]
                import uuid as _uuid

                def _port(p):
                    return {"name": p.name,
                            "type": getattr(p.type, "value", str(p.type))}

                node_id = "n_" + _uuid.uuid4().hex[:8]
                node = {
                    "id": node_id,
                    "type": type_name,
                    "category": spec.category,
                    "title": spec.display_name,
                    "config": args.get("config") or {},
                    "x": args.get("x", 200),
                    "y": args.get("y", 200),
                    "inputs": [_port(p) for p in spec.inputs],
                    "outputs": [_port(p) for p in spec.outputs],
                }
                return {"status": "ok", "op": "add_node",
                        "node_id": node_id, "node": node}

            if handler == "graph_wire":
                src_n = str(args.get("src_node", "") or "").strip()
                src_p = str(args.get("src_port", "") or "").strip()
                dst_n = str(args.get("dst_node", "") or "").strip()
                dst_p = str(args.get("dst_port", "") or "").strip()
                if not (src_n and src_p and dst_n and dst_p):
                    return {"status": "error",
                            "error": "graph_wire needs src_node, src_port, "
                                     "dst_node, dst_port"}
                if src_n == dst_n:
                    return {"status": "error",
                            "error": "cannot wire a node to itself"}
                return {"status": "ok", "op": "add_wire",
                        "wire": {"from": [src_n, src_p],
                                 "to": [dst_n, dst_p]}}

            # AgDR-0041 Property 4 — delete with auto-bridge.
            # Given the graph + a node_id about to be deleted, return:
            #   - {action:"auto_bridge", wire:[...]}  if upstream src
            #     port type == downstream dst port type (or ANY).
            #   - {action:"silent_delete"}            if no impacted wires.
            #   - {action:"broken_wire", issues:[...], adapters:[...]}
            #     if a wire would be type-mismatched after delete.
            if handler == "graph_on_node_delete":
                nid = str(args.get("node_id", "") or "").strip()
                graph = args.get("graph") or {}
                if not nid:
                    return {"status": "error",
                            "error": "graph_on_node_delete needs node_id"}
                nodes = graph.get("nodes") or []
                edges = graph.get("wires") or graph.get("edges") or []
                node_map = {n.get("id"): n for n in nodes}
                if nid not in node_map:
                    return {"status": "error",
                            "error": f"node {nid!r} not in graph"}
                # Wires touching this node.
                def _src(e):
                    return e.get("src_node") or (e.get("from", ["", ""])[0])
                def _src_p(e):
                    return e.get("src_port") or (e.get("from", ["", ""])[1])
                def _dst(e):
                    return e.get("dst_node") or (e.get("to", ["", ""])[0])
                def _dst_p(e):
                    return e.get("dst_port") or (e.get("to", ["", ""])[1])
                upstream  = [e for e in edges if _dst(e) == nid]
                downstream = [e for e in edges if _src(e) == nid]
                if not upstream and not downstream:
                    return {"status": "ok", "action": "silent_delete",
                            "note": "no incident wires"}
                # Try to auto-bridge: 1 upstream + 1 downstream + matching type.
                def _port_type(n_id, p_name, side):
                    """Look up the port type on a node (side='in'|'out')."""
                    n = node_map.get(n_id) or {}
                    ports = n.get("ins") if side == "in" else n.get("outs")
                    for p in (ports or []):
                        if isinstance(p, dict) and (p.get("id") or p.get("name")) == p_name:
                            return (p.get("t") or p.get("type") or "any").lower()
                    return "any"
                proposals: list = []
                for up in upstream:
                    src_n, src_p = _src(up), _src_p(up)
                    src_t = _port_type(src_n, src_p, "out")
                    for dn in downstream:
                        dst_n, dst_p = _dst(dn), _dst_p(dn)
                        dst_t = _port_type(dst_n, dst_p, "in")
                        compatible = (src_t == dst_t
                                       or src_t == "any" or dst_t == "any")
                        proposals.append({
                            "src": [src_n, src_p, src_t],
                            "dst": [dst_n, dst_p, dst_t],
                            "compatible": compatible,
                        })
                bridges = [p for p in proposals if p["compatible"]]
                broken  = [p for p in proposals if not p["compatible"]]
                if bridges and not broken:
                    wires = [{"from": p["src"][:2], "to": p["dst"][:2]}
                             for p in bridges]
                    return {"status": "ok", "action": "auto_bridge",
                            "wires": wires,
                            "note": f"{len(wires)} compatible bridge(s)"}
                if broken:
                    return {"status": "ok", "action": "broken_wire",
                            "broken": broken,
                            "compatible": bridges,
                            "note": ("type mismatch on delete — "
                                     "show recovery dialog")}
                return {"status": "ok", "action": "silent_delete"}

            # AgDR-0041 Property 5 — live validator over the JSX graph
            # snapshot. Returns same shape as Workflow.validate_v2() so
            # the GraphHealthPanel can colour wires + nodes consistently
            # whether the source is a saved Workflow or the live canvas.
            if handler == "graph_validate":
                graph = args.get("graph") or {}
                nodes = graph.get("nodes") or []
                edges = graph.get("wires") or graph.get("edges") or []
                issues: list[dict] = []
                # Duplicate ids.
                seen: set = set()
                dup: set = set()
                for n in nodes:
                    nid = n.get("id")
                    if nid in seen:
                        dup.add(nid)
                    seen.add(nid)
                for nid in dup:
                    issues.append({
                        "level": "err", "code": "duplicate_id",
                        "node_id": nid, "edge_id": None,
                        "msg": f"Duplicate node id {nid!r}."})
                node_map = {n.get("id"): n for n in nodes}
                # Port lookup tolerant of JSX (ins/outs) + Workflow
                # (inputs/outputs) shape.
                def _ports(n, side):
                    if side == "in":
                        return n.get("ins") or n.get("inputs") or []
                    return n.get("outs") or n.get("outputs") or []
                def _port_id(p):
                    return p.get("id") or p.get("name") if isinstance(p, dict) else None
                def _port_type(p):
                    if not isinstance(p, dict): return "any"
                    return (p.get("t") or p.get("type") or "any").lower()
                def _required(p):
                    return bool(isinstance(p, dict) and p.get("required"))
                # Edge accessors — JSX {from:[n,p],to:[n,p]} OR
                # Workflow {src_node,src_port,dst_node,dst_port}.
                def _src(e):
                    return e.get("src_node") or (e.get("from", ["", ""])[0])
                def _src_p(e):
                    return e.get("src_port") or (e.get("from", ["", ""])[1])
                def _dst(e):
                    return e.get("dst_node") or (e.get("to", ["", ""])[0])
                def _dst_p(e):
                    return e.get("dst_port") or (e.get("to", ["", ""])[1])
                def _edge_id(e):
                    return (e.get("id") or
                            f"{_src(e)}.{_src_p(e)}→{_dst(e)}.{_dst_p(e)}")
                wired_in: set = set()
                for e in edges:
                    eid = _edge_id(e)
                    s_n, s_p, d_n, d_p = _src(e), _src_p(e), _dst(e), _dst_p(e)
                    wired_in.add((d_n, d_p))
                    if s_n not in node_map:
                        issues.append({
                            "level": "err", "code": "missing_src",
                            "node_id": None, "edge_id": eid,
                            "msg": (f"Edge {eid}: src_node {s_n!r} missing.")})
                        continue
                    if d_n not in node_map:
                        issues.append({
                            "level": "err", "code": "missing_dst",
                            "node_id": None, "edge_id": eid,
                            "msg": (f"Edge {eid}: dst_node {d_n!r} missing.")})
                        continue
                    src_ports = _ports(node_map[s_n], "out")
                    dst_ports = _ports(node_map[d_n], "in")
                    src_port = next((p for p in src_ports
                                       if _port_id(p) == s_p), None)
                    dst_port = next((p for p in dst_ports
                                       if _port_id(p) == d_p), None)
                    if src_port is None:
                        issues.append({
                            "level": "err", "code": "unknown_src_port",
                            "node_id": s_n, "edge_id": eid,
                            "msg": (f"Edge {eid}: src_port {s_p!r} not on "
                                    f"node {s_n!r}.")})
                    if dst_port is None:
                        issues.append({
                            "level": "err", "code": "unknown_dst_port",
                            "node_id": d_n, "edge_id": eid,
                            "msg": (f"Edge {eid}: dst_port {d_p!r} not on "
                                    f"node {d_n!r}.")})
                    if src_port is not None and dst_port is not None:
                        st = _port_type(src_port)
                        dt = _port_type(dst_port)
                        if st != dt and st != "any" and dt != "any":
                            issues.append({
                                "level": "err", "code": "type_mismatch",
                                "node_id": d_n, "edge_id": eid,
                                "msg": (f"Edge {eid}: type {st!r} from "
                                        f"{s_n!r}.{s_p!r} does not match "
                                        f"{dt!r} on {d_n!r}.{d_p!r}.")})
                # Unset-required-input — warn only, cook may still proceed
                # if a default exists.
                for n in nodes:
                    nid = n.get("id")
                    for p in _ports(n, "in"):
                        pid = _port_id(p)
                        if _required(p) and (nid, pid) not in wired_in:
                            issues.append({
                                "level": "warn", "code": "unset_input",
                                "node_id": nid, "edge_id": None,
                                "msg": (f"Node {nid!r}: required input "
                                        f"{pid!r} unset.")})
                # Summary stats so the UI can render a one-line badge
                # without a second pass.
                counts = {"err": 0, "warn": 0}
                for iss in issues:
                    counts[iss.get("level", "warn")] = (
                        counts.get(iss.get("level", "warn"), 0) + 1)
                return {"status": "ok",
                        "issues": issues,
                        "errors": counts.get("err", 0),
                        "warnings": counts.get("warn", 0),
                        "valid": counts.get("err", 0) == 0}

            # AgDR-0041 Property 3 + 6 — let Composer toggle node state.
            # Both emit a `set_node` delta with the field flipped; UI
            # applies it + canvas re-renders + runner picks up next cook.
            if handler in ("node_freeze", "node_bypass"):
                node_id = str(args.get("node_id", "") or "").strip()
                if not node_id:
                    return {"status": "error",
                            "error": f"{handler} needs node_id"}
                field = "frozen" if handler == "node_freeze" else "bypassed"
                state_raw = args.get("state")
                state = True if state_raw is None else bool(state_raw)
                return {"status": "ok", "op": "set_node",
                        "node_id": node_id,
                        "patch": {field: state},
                        "note": (f"{node_id} {field}={state} "
                                  f"({'❄' if field == 'frozen' else '○'})")}

            return {"status": "error",
                    "error": f"Unknown node handler: {handler}"}
        except ValueError as ex:
            # _spec_from_dict rejected a malformed spec — surface it so
            # the LLM can correct in one retry.
            return {"status": "error", "error": str(ex)}
        except Exception as ex:
            return {"status": "error",
                    "error": f"{type(ex).__name__}: {ex}"}

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
