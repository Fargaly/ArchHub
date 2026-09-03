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


def _msg_field(m, name, default=None):
    """Read a field off a ChatMessage object OR a dict message."""
    if hasattr(m, name):
        return getattr(m, name)
    if isinstance(m, dict):
        return m.get(name, default)
    return default


def _has_tool_calls(m) -> bool:
    inv = _msg_field(m, "tool_invocations", []) or []
    return bool(inv)


def collapse_consecutive_turns(messages: list) -> list[dict]:
    """Collapse runs of consecutive same-kind turns into ONE logical turn.

    FIX 4 (founder, 2026-06-18): a long chat opened as a wall of ~66 near-
    identical `AI / Reasoning / llm.complete_with_tools` cards stacked in one
    column — every assistant turn became its own node. Mechanical, illogical.

    The DISTINCT steps a reader cares about are: the user's intents, the turns
    that actually DID something (a tool / host / connector call), and the final
    answer. Back-to-back pure-reasoning assistant turns (no tool calls) are ONE
    logical step — "thinking" — not N. This collapses each such run into a single
    assistant message that carries:
      - the concatenated content of the run (so nothing is lost — the rail still
        shows every turn; the NODE is the summary), and
      - `_collapsed_count` = how many turns it represents (the canvas renders
        "Thinking ×N", expandable).
    Consecutive user turns are likewise merged (rare, but keeps the DAG clean).

    A turn that calls tools is NEVER collapsed — it is a real decision/call and
    must stay its own node so the graph shows intent → calls → outputs. Returns
    a NEW list of plain dict messages (role/content + optional _collapsed_count
    + tool_invocations); never mutates the input. Round-trip is unaffected:
    callers that need the verbatim messages use the original list (the rail
    attaches the full history), and `extract_messages_from_graph` reads the
    on-disk single-node wrap, not this decomposed form.
    """
    out: list[dict] = []
    run: list = []          # current run of collapsible same-role messages
    run_role: Optional[str] = None

    def _flush():
        nonlocal run, run_role
        if not run:
            return
        if len(run) == 1:
            m = run[0]
            out.append({
                "role": _msg_field(m, "role", run_role) or run_role,
                "content": _msg_field(m, "content", "") or "",
            })
        else:
            joined = "\n\n".join(
                str(_msg_field(m, "content", "") or "") for m in run
            ).strip()
            out.append({
                "role": run_role,
                "content": joined,
                "_collapsed_count": len(run),
            })
        run = []
        run_role = None

    for m in (messages or []):
        role = _msg_field(m, "role", "user") or "user"
        # Collapsible iff it's a plain reasoning/user turn with NO tool calls.
        # Assistant turns WITH tool calls (and any non-user/assistant role, e.g.
        # tool/system) break the run and pass through untouched.
        collapsible = (role in ("assistant", "user")) and not _has_tool_calls(m)
        if collapsible and role == run_role:
            run.append(m)
            continue
        # Different kind (or a tool-bearing / special turn) → flush the run,
        # then either start a new run or emit the special turn as-is.
        _flush()
        if collapsible:
            run = [m]
            run_role = role
        else:
            d = {
                "role": role,
                "content": _msg_field(m, "content", "") or "",
            }
            inv = _msg_field(m, "tool_invocations", None)
            if inv:
                d["tool_invocations"] = inv
            out.append(d)
    _flush()
    return out


# Real left→right DAG layout. The translator (`graph_to_lmgraph`) honours a
# node's `position` when it is non-zero, falling back to a coarse category
# column otherwise — and that fallback put EVERY ai node at the same x, which is
# exactly the top-down column the founder hates. We compute a true dependency
# layout here (depth = longest path from a root) so the canvas opens as a
# branching left→right workflow on first paint.
_LAYOUT_COL_W = 280.0
_LAYOUT_ROW_H = 150.0
_LAYOUT_X0 = 80.0
_LAYOUT_Y0 = 80.0


def layout_dag(nodes: list[dict], edges: list[dict]) -> None:
    """Assign each node a `position` by dependency depth (longest path).

    Mutates the node dicts in place (sets `position={"x","y"}`). x is the node's
    topological depth × column-width → a real left→right flow; y stacks the
    nodes that SHARE a depth so siblings (e.g. several tools off one llm turn)
    branch into separate rows instead of overlapping. Deterministic; the user
    can drag afterwards. Cycles (shouldn't occur in a chat graph) are broken by
    a visited guard so this always terminates.
    """
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}
    succ: dict[str, list[str]] = {nid: [] for nid in by_id}
    indeg: dict[str, int] = {nid: 0 for nid in by_id}
    for e in (edges or []):
        s = e.get("src_node")
        t = e.get("dst_node")
        if s in by_id and t in by_id:
            succ[s].append(t)
            indeg[t] = indeg.get(t, 0) + 1

    # Longest-path depth via a stable BFS from the roots (indeg 0). A node's
    # depth is 1 + the max depth of its predecessors — computed by relaxing
    # along edges in topological-ish order with a visited cap to break cycles.
    depth: dict[str, int] = {nid: 0 for nid in by_id}
    from collections import deque
    queue = deque([nid for nid in by_id if indeg.get(nid, 0) == 0])
    if not queue:  # all nodes in a cycle (degenerate) — seed with insertion order
        queue = deque(by_id.keys())
    seen_relax: dict[str, int] = {}
    while queue:
        nid = queue.popleft()
        seen_relax[nid] = seen_relax.get(nid, 0) + 1
        if seen_relax[nid] > len(by_id) + 1:
            continue  # cycle guard
        for nxt in succ.get(nid, []):
            if depth[nxt] < depth[nid] + 1:
                depth[nxt] = depth[nid] + 1
            queue.append(nxt)

    # Group by depth (column) preserving node insertion order for stable rows.
    col_members: dict[int, list[str]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid in by_id:
            col_members.setdefault(depth.get(nid, 0), []).append(nid)

    for col, members in col_members.items():
        for row, nid in enumerate(members):
            by_id[nid]["position"] = {
                "x": _LAYOUT_X0 + col * _LAYOUT_COL_W,
                "y": _LAYOUT_Y0 + row * _LAYOUT_ROW_H,
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

    FIX 4 (founder, 2026-06-18 — "a wall of ~66 identical reasoning cards in one
    column"): before decomposing, consecutive same-kind reasoning turns are
    COLLAPSED into one logical "thinking ×N" turn (`collapse_consecutive_turns`)
    so the graph shows the DISTINCT steps (intent → the real tool/host calls →
    answer), not every turn. After decomposing, a real dependency layout
    (`layout_dag`) positions the nodes left→right by depth with branching, so the
    canvas opens as a clean workflow — NOT a top-down column. The full, verbatim
    conversation still rides on the rail (attached by graph_to_lmgraph from the
    ORIGINAL message list), so nothing is lost and round-trip is preserved.

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
    # Collapse before decomposing — the decomposer mints one llm node per
    # assistant turn, so collapsing the turns is what collapses the cards.
    collapsed = collapse_consecutive_turns(msg_list)
    wf = chat_to_workflow(collapsed, name=name or sid or "session")
    d = wf.to_dict()
    if sid:
        d["id"] = sid

    # Re-label the collapsed reasoning nodes "Thinking ×N" + carry the count so
    # the canvas can render them as a collapsible "N turns" node. We walk the
    # llm nodes in order and pair them with the collapsed assistant turns in
    # order (chat_to_workflow emits exactly one llm node per assistant turn).
    assistant_turns = [m for m in collapsed if (m.get("role") == "assistant")]
    llm_nodes = [n for n in d.get("nodes", [])
                 if (n.get("type") or "").startswith("llm.")]
    for node, turn in zip(llm_nodes, assistant_turns):
        cnt = int(turn.get("_collapsed_count") or 0)
        if cnt > 1:
            node["label"] = f"Thinking ×{cnt}"
            # `sub` is read by the translator BEFORE the engine type, so this
            # becomes the node card's subtitle — naming what the one node stands
            # for ("N reasoning turns"), expandable to the rail's full history.
            node["sub"] = f"{cnt} reasoning turns"
            cfg = node.setdefault("config", {})
            cfg["collapsed_count"] = cnt
            cfg["collapsed"] = True

    # Real left→right DAG layout so the canvas never opens as a stacked column.
    layout_dag(d.get("nodes", []), d.get("edges", []))

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
