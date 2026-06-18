"""Session ↔ Graph migration helpers (ADR-003 Phase 2).

The graph-first pivot makes Session.graph the primary state container.
Existing v1.3.x sessions on disk only have `_messages` and the
legacy `parameters` + `chain` payload. We wrap them in a single
`conversation.chat` node so the new canvas can render them, and emit
back the messages list when the canvas hands a graph back to the
legacy chat surface.

Two functions:

  wrap_legacy_as_graph(session, messages)
      → dict shaped like workflows.graph.Workflow.to_dict() with one
        `conversation.chat` node whose body.messages holds the chat
        history. Round-trip-safe: extract_messages_from_graph yields
        the same list.

  extract_messages_from_graph(graph_dict)
      → the list of message dicts contained in the first
        `conversation.chat` node found. Empty list when the graph has
        no conversation node (a pure parametric session, say).

The migrator is a pure data function — no Qt, no LLM. Used by:
  - session_io.save_session (dual-write at save time)
  - the future Phase 3 Graph page (load any session as a graph)
  - the Phase 8 batch migration script
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


SCHEMA_VERSION = "1.0"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def wrap_legacy_as_graph(session, messages: Optional[list] = None,
                          *, name: str = "") -> dict:
    """Build a Workflow-dict that wraps the legacy session.

    The single node is `conversation.chat` carrying the message list
    in its body. The session id is reused as the workflow id so a
    later canvas-side save round-trips back to the same on-disk slot.
    Returns the dict (not a Workflow instance) so callers don't need
    to import workflows at session-save time.
    """
    msg_list: list[dict] = []
    for m in (messages or []):
        # Accept ChatMessage objects OR pre-dicted ones.
        if hasattr(m, "role") and hasattr(m, "content"):
            msg_list.append({"role": m.role, "content": m.content})
        elif isinstance(m, dict):
            msg_list.append({"role": m.get("role", "user"),
                              "content": m.get("content", "")})
    node_id = f"conv_{uuid.uuid4().hex[:10]}"
    conv_node = {
        "id":       node_id,
        "type":     "conversation.chat",
        "label":    name or "Conversation",
        "config":   {
            "model":       "auto",
            "system":      "",
            "temperature": 0.7,
            "max_tokens":  4096,
            "body":        {"messages": msg_list},
        },
        # The Conversation node spec carries the canonical port list;
        # we render an empty inputs/outputs at the wrap stage because
        # the registry IS the source of truth. Round-trip is keyed
        # by `type`, not by these arrays.
        "inputs":   [],
        "outputs":  [],
        "position": {"x": 0.0, "y": 0.0},
    }
    sid = getattr(session, "id", None) or uuid.uuid4().hex
    now = _utc()
    return {
        "id":              sid,
        "name":            name or "session",
        "description":     "Auto-wrapped from legacy session (ADR-003 Phase 2)",
        "schema_version":  SCHEMA_VERSION,
        "nodes":           [conv_node],
        "edges":           [],
        "triggers":        [],
        "inputs":          [],
        "outputs":         [],
        "metadata":        {
            "migrated_from": "legacy_session",
            "migrated_at":   now,
        },
        "created_at":      now,
        "updated_at":      now,
    }


def decompose_legacy_as_graph(session, messages: Optional[list] = None,
                              *, name: str = "") -> dict:
    """Build a MODULAR, multi-node Workflow-dict from a legacy chat.

    SESSIONS-GRAPH lane — root cause #1 fix. `wrap_legacy_as_graph` (above)
    is the on-DISK storage form: it keeps the whole chat in ONE
    `conversation.chat` node so the legacy chat surface can round-trip the
    message list (`extract_messages_from_graph`). That is correct for storage
    but WRONG for the canvas, which must render a logical node graph — one
    node per turn, a tool node per tool call — not a single flat blob.

    This function produces that decomposed graph by delegating to the EXISTING
    per-turn decomposer (`workflows.chat_to_workflow`) — no parallel decomposer
    is minted (ONE-SYSTEM mandate). Returns a `Workflow.to_dict()`-shaped dict
    (still the workflows.graph shape: id/type/label/config/inputs/outputs); the
    canvas-facing `graph_to_lmgraph.translate_graph_to_lmgraph` maps that to the
    JSX LM_GRAPH shape (kind/cat/ins/outs).

    Empty history → the single-node wrap (a chat with nothing to decompose
    still needs a node to render). The session id is reused as the workflow id
    so a later canvas save round-trips back to the same on-disk slot.
    """
    msg_list = list(messages or [])
    if not msg_list:
        return wrap_legacy_as_graph(session, msg_list, name=name)
    try:
        from workflows.chat_to_workflow import chat_to_workflow
    except Exception:  # pragma: no cover - import-path guard for packaging
        from app.workflows.chat_to_workflow import chat_to_workflow  # type: ignore
    sid = getattr(session, "id", None)
    wf = chat_to_workflow(msg_list, name=name or sid or "session")
    d = wf.to_dict()
    if sid:
        d["id"] = sid
    d.setdefault("metadata", {})
    d["metadata"]["migrated_from"] = "legacy_session_decomposed"
    d["metadata"]["migrated_at"] = _utc()
    return d


def extract_messages_from_graph(graph_dict: Optional[dict]) -> list[dict]:
    """Inverse of wrap_legacy_as_graph: pull messages back out of the
    first conversation.chat node we find. Empty list when no chat node.
    """
    if not isinstance(graph_dict, dict):
        return []
    nodes = graph_dict.get("nodes") or []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if (n.get("type") or "") != "conversation.chat":
            continue
        cfg = n.get("config") or {}
        body = cfg.get("body") or {}
        msgs = body.get("messages") or []
        if isinstance(msgs, list):
            return [
                {"role": m.get("role", "user"),
                 "content": m.get("content", "")}
                for m in msgs if isinstance(m, dict)
            ]
    return []


def update_graph_messages(graph_dict: dict, messages: list) -> dict:
    """Mutate a graph's first conversation.chat node body to hold a
    new messages list. Returns the same dict (mutated) so callers can
    chain. No-op when no chat node exists."""
    nodes = graph_dict.get("nodes") or []
    for n in nodes:
        if (n.get("type") or "") != "conversation.chat":
            continue
        n.setdefault("config", {})
        n["config"].setdefault("body", {})
        n["config"]["body"]["messages"] = [
            {"role": m.get("role", "user") if isinstance(m, dict)
                      else getattr(m, "role", "user"),
             "content": m.get("content", "") if isinstance(m, dict)
                         else getattr(m, "content", "")}
            for m in (messages or [])
        ]
        graph_dict["updated_at"] = _utc()
        break
    return graph_dict
