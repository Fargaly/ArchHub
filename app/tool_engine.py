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
        active_families = self._active_families()
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
