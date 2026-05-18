"""Composer Agent — LLM-as-orchestrator.

User types natural language into the composer. We hand it to Claude
along with a tool schema describing every canvas-mutation primitive,
and the graph state. Claude returns tool calls. We execute them
against the bridge's existing slots and feed the results back.
Loop until Claude returns text or no more tool calls.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


# Tool catalog — JSON schema that Claude sees. Each tool maps to one
# bridge slot (or a small helper on top of one).
TOOL_SCHEMA = [
    {
        "name": "spawn_node",
        "description": (
            "Spawn a node on the canvas. family is the kebab-case host "
            "family (revit/outlook/...) or node type id (i_conv, "
            "r_walls, ...). Returns the new node id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "family": {
                    "type": "string",
                    "description": "host family or library item id",
                },
                "title": {"type": "string"},
                "x":     {"type": "number"},
                "y":     {"type": "number"},
            },
            "required": ["family"],
        },
    },
    {
        "name": "add_wire",
        "description": "Add a wire between two nodes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "src_node": {"type": "string"},
                "src_port": {"type": "string"},
                "dst_node": {"type": "string"},
                "dst_port": {"type": "string"},
            },
            "required": [
                "src_node", "src_port", "dst_node", "dst_port",
            ],
        },
    },
    {
        "name": "set_node_param",
        "description": "Set a parameter on a node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "key":     {"type": "string"},
                "value":   {},
            },
            "required": ["node_id", "key", "value"],
        },
    },
    {
        "name": "run_node",
        "description": "Cook a single node and return its output envelope.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "run_workflow",
        "description": "Cook every sink node in the graph.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_graph",
        "description": "Return the current graph (nodes + wires).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "chat",
        "description": (
            "Just stream a chat reply into the focused conversation "
            "node, no canvas action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


# Host-status summary is expensive (~10-15 TCP/HTTP/process probes).
# Cache it 30s so a burst of agent_step calls doesn't re-probe every
# time. Founder bug 2026-05-15: probing on the Qt main thread froze the
# UI; agent_step is now threaded, but the cache keeps even the threaded
# path cheap.
_HOST_STATUS_CACHE: dict = {"ts": 0.0, "value": ""}
_HOST_STATUS_TTL = 30.0


def _host_status_summary() -> str:
    """Return a compact line listing each known host + whether ArchHub
    can actually reach it RIGHT NOW. Founder bug 2026-05-15: agent
    invented C# AutoCAD .NET code while talking to an offline broker —
    no signal told the LLM the broker was dead. Inject host status into
    the system prompt so the model says 'broker offline' instead of
    fabricating tool calls. Result is cached 30s.
    """
    import time as _t
    now = _t.time()
    if (now - _HOST_STATUS_CACHE["ts"]) < _HOST_STATUS_TTL and _HOST_STATUS_CACHE["value"]:
        return _HOST_STATUS_CACHE["value"]
    summary = _host_status_summary_uncached()
    _HOST_STATUS_CACHE["ts"] = now
    _HOST_STATUS_CACHE["value"] = summary
    return summary


def _host_status_summary_uncached() -> str:
    try:
        from host_detector import detect_all_hosts as _det1
        a = _det1() or {}
    except Exception:
        a = {}
    try:
        from local_llm_detector import detect_all_local_llms as _det2
        b = _det2() or []
    except Exception:
        b = []
    parts = []
    for hid, h in a.items():
        if not isinstance(h, dict):
            continue
        st = (h.get("status") or "").lower()
        parts.append(f"{hid}={st}")
    for row in b:
        if not isinstance(row, dict):
            continue
        if row.get("running"):
            parts.append(f"{row.get('id')}=live")
        elif row.get("installed"):
            parts.append(f"{row.get('id')}=installed")
    # Founder bug 2026-05-15: agent invented AutoCAD .NET code because no
    # status was given for broker-based hosts (revit/autocad/max). Flag
    # them as "no_status" so the LLM treats as unknown and asks the user.
    BROKER_HOSTS = ("revit", "autocad", "max", "blender",
                    "rhino", "speckle", "dropbox")
    known = {p.split("=", 1)[0] for p in parts}
    for h in BROKER_HOSTS:
        if h not in known:
            parts.append(f"{h}=no_status (broker not probed — assume offline)")
    return ", ".join(parts) if parts else "(no host status available)"


def system_prompt(graph: dict) -> str:
    """Build the agent system prompt. Includes a compact graph summary
    plus a real-time host-availability strip so the LLM doesn't invent
    tool calls against an offline broker.
    """
    nodes = graph.get("nodes") or []
    wires = graph.get("wires") or []
    n = len(nodes)
    w = len(wires)
    return (
        "You are an ArchHub agent that operates a graph-based AEC "
        "workspace. When the user types intent, decide which tools to "
        "call. Available node families: revit, autocad, max, blender, "
        "rhino, speckle, outlook, teams, word, excel, powerpoint, "
        "photoshop, illustrator, indesign, notion, lmstudio, "
        "antigravity. Available node-type ids: i_conv (conversation), "
        "i_think (LLM reasoning), r_walls (list_walls), r_doors, "
        "f_param (filter by parameter), a_dims (create dimensions), "
        "c_sched (build schedule), o_pdf (publish pdf), o_email (send "
        "email). Wires connect output port to input port. Use "
        "add_wire after spawning. "
        f"Current graph has {n} nodes and {w} wires. "
        "HOST STATUS (only use hosts marked 'live' for real work; for "
        "'missing' / 'installed' / 'unavailable' hosts, tell the user "
        "the broker is offline — DO NOT invent results, do not fabricate "
        "tool outputs, do not write code that pretends to talk to it): "
        + _host_status_summary()
    )


def run_agent_step(
    *,
    user_msg: str,
    graph: dict,
    focused_node_id: str = "",
    router: Any = None,
    max_iters: int = 4,
) -> dict:
    """One step of the composer agent. Returns a list of actions for
    the JSX side to execute, plus the final assistant text.

    Args:
        user_msg: The natural-language input from the composer.
        graph: The current LM_GRAPH dict (nodes + wires).
        focused_node_id: The id of the conversation node the composer
            is currently anchored to, if any.
        router: The LLMRouter instance (or compatible duck-typed
            client) that owns `.complete(history=..., model=...,
            on_chunk=..., on_tool_invocation=..., tool_schemas=...)`.
        max_iters: Reserved for the future tool-loop bound. The actual
            loop is driven by the router today; we just cap our own
            invocation count via the callbacks.

    Returns:
        Dict with keys `actions` (list of tool-invocation dicts) and
        `text` (final assistant text). On failure, includes `error`.
    """
    if not router:
        return {
            "actions": [],
            "text": "no router configured",
            "error": "missing_dep",
        }

    # Build a conversation [{role, content}] history. A leading
    # `role:"system"` message is folded into the system prompt by
    # llm_router._complete_once, and the composer keeps the full tool
    # surface — it drives the graph through real tool calls. (Earlier
    # this used a bogus `role:"system_override"` role that provider
    # APIs 400 on, silently degrading every compose turn.)
    history: list[dict] = [
        {"role": "system", "content": system_prompt(graph)},
        {"role": "user", "content": user_msg},
    ]

    # We collect actions via the tool-invocation callback. Each
    # invocation ALSO becomes a step the JSX side replays so the
    # canvas mutates in real time. The router handles the actual
    # tool-loop (Claude is already set up for tool-use via providers).
    actions: list = []

    def _on_inv(inv: Any) -> None:
        try:
            name = (
                getattr(inv, "name", None)
                or getattr(inv, "tool", None)
                or "?"
            )
            args = (
                getattr(inv, "args", None)
                or getattr(inv, "arguments", None)
                or {}
            )
            result = getattr(inv, "result", None)
            actions.append(
                {"tool": name, "args": args, "result": result}
            )
        except Exception:
            actions.append({"tool": "?", "args": {}, "result": None})

    text_buf: list[str] = []

    def _on_chunk(piece: str) -> None:
        if piece:
            text_buf.append(piece)

    try:
        # NOTE: this calls the real router with our tool catalog. The
        # router's _execute_tool dispatcher needs to recognise these
        # tool names — if it doesn't yet, the LLM still gets the
        # schema and decides "no tool call" and returns plain text.
        response = router.complete(
            history=history,
            model="auto",
            on_chunk=_on_chunk,
            on_tool_invocation=_on_inv,
            tool_schemas=TOOL_SCHEMA,
        )
        text = (
            getattr(response, "text", "") or "".join(text_buf)
        ).strip()
    except TypeError:
        # Older router signature with no tool_schemas kwarg — fall
        # back to the plain complete() path. The LLM won't see the
        # canvas tools but at least the chat reply still streams.
        try:
            response = router.complete(
                history=history,
                model="auto",
                on_chunk=_on_chunk,
                on_tool_invocation=_on_inv,
            )
            text = (
                getattr(response, "text", "") or "".join(text_buf)
            ).strip()
        except Exception as ex:
            return {
                "actions": [],
                "text": "",
                "error": f"{type(ex).__name__}: {ex}",
            }
    except Exception as ex:
        return {
            "actions": [],
            "text": "",
            "error": f"{type(ex).__name__}: {ex}",
        }

    return {"actions": actions, "text": text}
