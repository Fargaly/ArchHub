"""client_hook.py — BRV-02: legacy pre-prompt work-assignment helper.

This is a Brain control-plane projection used by supported clients at
pre-prompt time to ask for the next assigned leaf and receive an
`<assigned_leaf>` context block to prepend to the turn. It is not Universal Cell
product authority; Cell protocols are the target authority.

It is the symmetric counterpart to `tools/brainwrap.py`'s `<brain_context>`
pre-prompt inject: where brainwrap injects RECALL (relevant memory), this
injects DRIVE (the next unit of work the brain hands this runtime). Together
they are the pre-prompt the brain feeds every agent.

The helper calls the Cell-first active-work compatibility route. It creates a
Cell request/outcome record around the legacy projection before returning the
assigned leaf + its gate formatted as a ready-to-prepend string.

TWO transports, ONE contract:
  * GRAPH SESSION - all callers provide a vendor session identity and POST
                  `brain.work_assigned_block` to the daemon, mirroring
                  brainwrap.call_tool's SSE transport. It returns no assignment
                  when the graph is unavailable or the frontier is dry.

The block is bounded by stable markers so a wrapper can refresh it on each turn
instead of stacking duplicates (same convention as brainwrap's context block).
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import json
import os
import urllib.request
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # typing only — no runtime import cycle
    from .storage import BrainStore
    from .active_work import WorkLeaf


# Bounded markers so re-runs refresh (not stack) — mirrors brainwrap's
# <!-- brainwrap:context:start --> / :end convention.
ASSIGNED_START = "<!-- brain:assigned_leaf:start -->"
ASSIGNED_END = "<!-- brain:assigned_leaf:end -->"

# Daemon transport defaults — identical to tools/brainwrap.py so a single env
# var (BRAIN_DAEMON_URL) configures every client's brain endpoint.
DAEMON_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
_TIMEOUT = 6.0


# ───────────────────────── MCP transport (external clients) ─────────────


def _parse_sse(raw: bytes) -> dict:
    """Pull structuredContent / JSON text out of an MCP SSE response.
    Mirrors tools/brainwrap.py._parse_sse so the wire shape is identical."""
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except Exception:
                continue
            res = obj.get("result") or {}
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            for c in res.get("content") or []:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except Exception:
                        pass
    return {}


def _call_daemon(name: str, arguments: dict[str, Any],
                 *, timeout: float = _TIMEOUT) -> Optional[dict]:
    """POST one MCP tools/call to the daemon. Returns the structured result or
    None on any failure (so the caller degrades gracefully)."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _parse_sse(r.read())
    except Exception:
        return None


# ───────────────────────── formatting ──────────────────────────────────


def format_assigned_leaf(leaf: dict[str, Any]) -> str:
    """Render graph-owned Work as a session-bound `<assigned_leaf>` block."""
    if not leaf:
        return ""
    work_root = str(leaf.get("work_root") or "").strip()
    session_id = str(leaf.get("session_id") or "").strip()
    runtime = str(leaf.get("runtime") or "").strip()
    if not (work_root and session_id and runtime):
        return ""
    title = leaf.get("title", "")
    gate_kind = leaf.get("gate_kind", "manual")
    gate_spec = leaf.get("gate_spec") or {}
    transition = (
        "session_id=%r, vendor=%r, work_root=%r" % (
            session_id, runtime, work_root
        )
    )

    lines = [
        "<assigned_leaf>",
        "The Universal Cell graph assigns this work to your exact Agent Session.",
        f"  work_root: {work_root}",
        f"  work:      {title}",
        f"  gate:      {gate_kind}"
        + (f"  {json.dumps(gate_spec, separators=(',', ':'))}" if gate_spec else ""),
        f"  runtime:   {runtime}",
        f"  session:   {session_id}",
        "  release:   brain.universal_work_transition(%s, event='release')" % transition,
        "  blocked:   brain.universal_work_transition(%s, event='block', evidence=<reason>)" % transition,
        "  submit:    brain.universal_work_transition(%s, event='submit', evidence=<artifact proof>)" % transition,
        "  court:     brain.universal_work_court(%s)" % transition,
    ]
    lines.append("</assigned_leaf>")
    return "\n".join(lines)


def _wrap(block: str) -> str:
    """Bound the block with refresh markers (so a wrapper replaces, not stacks)."""
    if not block:
        return ""
    return f"{ASSIGNED_START}\n{block.rstrip()}\n{ASSIGNED_END}\n"


# ───────────────────────── the helper (the one call) ────────────────────


def _resolve_owner_inproc(store: "BrainStore") -> str:
    """In-process owner resolution honouring the cloud binding — reuses
    active_work._default_owner (same policy as roma._default_owner /
    server.resolve_default_owner), falling back to 'founder'."""
    try:
        from . import active_work as aw
        return aw._default_owner(store)
    except Exception:
        return "founder"


def next_assigned_leaf(
    *,
    runtime: str,
    session_id: Optional[str] = None,
    fit: Optional[list[str]] = None,
    owner_user: Optional[str] = None,
    agent_id: Optional[str] = None,
    store: "Optional[BrainStore]" = None,
) -> Optional[dict[str, Any]]:
    """Ask the brain for this runtime's next leaf and CLAIM it. Returns the leaf
    dict, or None when the frontier is dry / the daemon is unreachable.

    `store` remains a compatibility argument but is not read. The hook always
    calls the graph-session assignment route. This is the engine behind
    `assigned_leaf_block` for callers that need the structured graph Work."""
    if not (runtime or "").strip():
        raise ValueError("next_assigned_leaf requires a non-empty runtime")

    identity = str(session_id or "").strip()
    if not identity:
        return None
    args: dict[str, Any] = {
        "runtime": runtime,
        "session_id": identity,
        "wrap": False,
        "write": True,
    }
    if fit is not None:
        args["fit"] = list(fit)
    if owner_user:
        args["owner_user"] = owner_user
    if agent_id:
        args["agent_id"] = agent_id
    res = _call_daemon("brain.work_assigned_block", args)
    if not res or not res.get("ok") or res.get("universal") is not True:
        return None
    return res.get("leaf") or None


def assigned_leaf_block(
    *,
    runtime: str,
    session_id: Optional[str] = None,
    fit: Optional[list[str]] = None,
    owner_user: Optional[str] = None,
    agent_id: Optional[str] = None,
    store: "Optional[BrainStore]" = None,
    wrap: bool = True,
) -> str:
    """THE PRE-PROMPT CALL every client makes. Returns the `<assigned_leaf>`
    context string to prepend to the turn (bounded by refresh markers when
    `wrap`), or "" when the frontier is dry / the brain is unreachable (so a
    turn is never blocked by the drive being idle or offline).

    Usage (mirrors brainwrap context inject):
      block = assigned_leaf_block(runtime="codex", session_id=<vendor-session>)
      if block: prepend block to the system/context turn
    """
    leaf = next_assigned_leaf(
        runtime=runtime, session_id=session_id, fit=fit, owner_user=owner_user,
        agent_id=agent_id, store=store,
    )
    block = format_assigned_leaf(leaf) if leaf else ""
    return _wrap(block) if wrap else block
