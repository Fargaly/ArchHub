"""Core node types for the graph-first architecture (ADR-003 Phase 1).

Three families register here:

  • host.*         — AEC application connectors (Revit/AutoCAD/Blender/...)
  • conversation.* — chat nodes carrying message history + LLM params
  • doc.*          — opened documents inside a host (Revit model, DWG, IFC)

Executors are **stubs** in Phase 1. They return well-typed envelopes
that downstream tests can pin without needing live host adapters or
LLM keys. Real wiring lands in Phase 4 (see ADR-003 action items).

The shapes are stable — Phase 4 will replace the body of each executor
with real `app/connectors/*` and `llm_router.complete` calls, but the
inputs/outputs/config schemas frozen here are the contract.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ===========================================================================
# 1. Host nodes (7 variants)
# ===========================================================================
#
# A Host node represents one AEC application. Its parameters declare which
# *version* of that host (Revit 2024 vs 2025). Its body carries the bridge
# session state — current document, last action, port number.
#
# Inputs are typed actions ("open file", "select wall types", "save"). Each
# Host has an EXEC input port so a Trigger/Cron node can fire actions on a
# schedule. Outputs carry the live state: opened document, current selection,
# warning count.
#
# The seven concrete types share one executor implementation parameterised by
# host family — DRY without losing per-host UX surface.

_HOST_FAMILIES = (
    ("revit",    "Revit",        "▲", "BIM authoring + documentation"),
    ("autocad",  "AutoCAD",      "◇", "2D drafting + 3D modelling"),
    ("blender",  "Blender",      "◈", "DCC + scripting + Python addons"),
    ("rhino",    "Rhino",        "◐", "NURBS modelling + Grasshopper"),
    ("max",      "3ds Max",      "◑", "Visualisation + rendering"),
    ("speckle",  "Speckle",      "⌬", "BIM data exchange + streams"),
    ("outlook",  "Outlook",      "✉", "Email + calendar + tasks"),
)


def _host_exec(config: dict, inputs: dict, ctx) -> dict:
    """Phase-1 stub. Returns a well-typed envelope so wired-downstream
    nodes have predictable inputs to test against.

    Phase 4 replaces this with a call into the matching adapter under
    `app/connectors/<family>_runner.py` — same return shape, real data.
    """
    family = config.get("_family") or config.get("family") or "revit"
    version = config.get("version") or ""
    action = (inputs.get("action") or "").strip()
    # Stub state — what a freshly-pinged adapter would report.
    return {
        "status":       "ok",
        "family":       family,
        "version":      version,
        "opened_doc":   config.get("default_doc", "") or None,
        "selection":    [],
        "state":        "idle" if not action else f"action: {action}",
        "tool_calls":   [],
    }


def _register_host_node(family: str, name: str, icon: str,
                         description: str) -> None:
    """Register one host.{family} type with the registry."""
    register(
        NodeSpec(
            type=f"host.{family}",
            category="host",
            display_name=name,
            description=description,
            inputs=[
                Port(name="action",  type=PortType.STRING,
                      description=f"Action to invoke on {name}"),
                Port(name="trigger", type=PortType.EXEC, exec=True,
                      description="Fire on incoming execution signal"),
            ],
            outputs=[
                Port(name="opened_doc",  type=PortType.DOCUMENT,
                      description="Currently-active document"),
                Port(name="selection",   type=PortType.SELECTION,
                      description="Current host selection"),
                Port(name="state",       type=PortType.STRING,
                      description="Bridge / session state"),
                Port(name="after",       type=PortType.EXEC, exec=True,
                      description="Fires after action completes"),
            ],
            config_schema={
                "_family":     {"type": "string", "default": family,
                                "hidden": True},
                "version":     {"type": "string", "default": "",
                                "description": f"{name} version (e.g. 2025)"},
                "default_doc": {"type": "string", "default": "",
                                "description": "Document to open on activate"},
                "auto_run":    {"type": "boolean", "default": False,
                                "description": "Re-execute on upstream param change"},
            },
            icon=icon,
        ),
        _host_exec,
    )


for _family, _name, _icon, _desc in _HOST_FAMILIES:
    _register_host_node(_family, _name, _icon, _desc)


# ===========================================================================
# 2. Conversation node — chat as a node
# ===========================================================================
#
# Body carries the list of chat turns. Params declare model, system prompt,
# temperature, max tokens. Inputs accept upstream context (a Document's
# contents, a previous Conversation's response, an extracted intent). Outputs
# emit the assistant's response, an extracted intent string (for downstream
# Logic nodes), and the full tool_trace dict.
#
# Phase 4 wires the executor to `llm_router.complete` with the body's history
# + the inputs as RAG context.

def _conversation_exec(config: dict, inputs: dict, ctx) -> dict:
    """Phase-1 stub. Echoes a deterministic response so tests can assert
    against shape. Phase 4 calls llm_router.complete(...)."""
    prompt = (inputs.get("prompt") or "").strip()
    if not prompt:
        return {"status": "error", "error": "prompt required"}
    body = config.get("body") or {"messages": []}
    if isinstance(body, dict):
        msgs = list(body.get("messages") or [])
    else:
        msgs = []
    response_text = f"[stub-{config.get('model', 'auto')}] {prompt[:80]}"
    return {
        "status":       "ok",
        "response":     response_text,
        "intent":       prompt.split()[0].lower() if prompt else "",
        "tool_trace":   [],
        "messages":     msgs + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response_text},
        ],
    }


register(
    NodeSpec(
        type="conversation.chat",
        category="ai",
        display_name="Conversation",
        description="A chat thread with the LLM. Body carries the turns.",
        inputs=[
            Port(name="prompt",  type=PortType.STRING, required=True,
                  description="User turn to append"),
            Port(name="context", type=PortType.ANY, multiple=True,
                  description="Upstream context (docs, intents, results)"),
            Port(name="system",  type=PortType.STRING,
                  description="System prompt override"),
            Port(name="trigger", type=PortType.EXEC, exec=True),
        ],
        outputs=[
            Port(name="response",    type=PortType.COMPLETION,
                  description="Latest assistant response"),
            Port(name="intent",      type=PortType.INTENT,
                  description="Extracted intent for Logic routing"),
            Port(name="tool_trace",  type=PortType.LIST,
                  description="Tool calls invoked during this turn"),
            Port(name="conversation", type=PortType.CONVERSATION,
                  description="Full thread (for downstream Conversation nodes)"),
            Port(name="after",       type=PortType.EXEC, exec=True),
        ],
        config_schema={
            "model":       {"type": "string", "default": "auto",
                            "description": "Router model id (auto = best per task)"},
            "system":      {"type": "string", "default": "",
                            "description": "System prompt"},
            "temperature": {"type": "number", "default": 0.7,
                            "min": 0.0, "max": 2.0},
            "max_tokens":  {"type": "number", "default": 4096},
            "auto_run":    {"type": "boolean", "default": False},
        },
        icon="✦",
    ),
    _conversation_exec,
)


# ===========================================================================
# 3. Document nodes (8 variants)
# ===========================================================================
#
# A Document node points at a file inside a host. Params declare path +
# version. Body caches last-read contents. Inputs accept edits (host-typed).
# Outputs emit contents, selection (subset of the doc's elements), warnings.
#
# Multi-document graphs are the unlock: two doc.revit nodes side-by-side
# + a doc.csv input + a Conversation tying them together = "import the
# schedule, compare against both Revit models, draft the discrepancy
# email" — all in ONE graph.

_DOC_FAMILIES = (
    ("revit",   "Revit Model",   "▣", PortType.DOCUMENT, ".rvt"),
    ("dwg",     "DWG Drawing",   "◇", PortType.DOCUMENT, ".dwg"),
    ("ifc",     "IFC Model",     "◰", PortType.IFC,      ".ifc"),
    ("blender", "Blender Scene", "◈", PortType.DOCUMENT, ".blend"),
    ("3dm",     "Rhino 3DM",     "◐", PortType.DOCUMENT, ".3dm"),
    ("max",     "3ds Max Scene", "◑", PortType.DOCUMENT, ".max"),
    ("csv",     "CSV Data",      "≡", PortType.CSV,      ".csv"),
    ("pdf",     "PDF Document",  "◫", PortType.FILE,     ".pdf"),
)


def _doc_exec(config: dict, inputs: dict, ctx) -> dict:
    """Phase-1 stub. Returns predictable doc envelope."""
    family = config.get("_family") or "revit"
    path = (inputs.get("path") or config.get("path") or "").strip()
    return {
        "status":   "ok",
        "family":   family,
        "path":     path,
        "version":  config.get("version", ""),
        "contents": None,                 # filled by Phase 4 adapter
        "selection": [],
        "warnings": [],
    }


def _register_doc_node(family: str, name: str, icon: str,
                        out_type: PortType, ext: str) -> None:
    register(
        NodeSpec(
            type=f"doc.{family}",
            category="document",
            display_name=name,
            description=f"Opened {ext} document. Connects to a Host node.",
            inputs=[
                Port(name="path",   type=PortType.PATH,
                      description=f"Absolute path to the {ext} file"),
                Port(name="host",   type=PortType.HOST,
                      description="Host node managing this document"),
                Port(name="trigger", type=PortType.EXEC, exec=True),
            ],
            outputs=[
                Port(name="document",  type=out_type,
                      description="The opened document reference"),
                Port(name="contents",  type=PortType.OBJECT,
                      description="Document body (parsed)"),
                Port(name="selection", type=PortType.SELECTION,
                      description="Active selection within this document"),
                Port(name="warnings",  type=PortType.LIST,
                      description="Health/QA warnings from the document"),
                Port(name="after",     type=PortType.EXEC, exec=True),
            ],
            config_schema={
                "_family":  {"type": "string", "default": family,
                              "hidden": True},
                "path":     {"type": "string", "default": "",
                              "description": f"Path to {ext} file"},
                "version":  {"type": "string", "default": "",
                              "description": "Document version label"},
                "read_only":{"type": "boolean", "default": False},
            },
            icon=icon,
        ),
        _doc_exec,
    )


for _family, _name, _icon, _out_type, _ext in _DOC_FAMILIES:
    _register_doc_node(_family, _name, _icon, _out_type, _ext)
