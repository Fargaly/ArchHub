"""client_hook.py — BRV-02: the shared pre-prompt driver helper.

THE BRAIN DRIVES EVERY AGENT. This is the ONE helper every client calls at
pre-prompt time — Claude Code, Codex, Gemini, the ArchHub composer — to ask the
brain *"what should I work on next?"* and receive its assignment as an
`<assigned_leaf>` context block to prepend to the turn.

It is the symmetric counterpart to `tools/brainwrap.py`'s `<brain_context>`
pre-prompt inject: where brainwrap injects RECALL (relevant memory), this
injects DRIVE (the next unit of work the brain hands this runtime). Together
they are the pre-prompt the brain feeds every agent.

The helper calls `active_work.next_leaf(runtime, fit)` (BRV-01) — which CLAIMS
the leaf atomically server-side, so the brain (not the agent) decides what each
runtime works on next, and two runtimes never grab the same leaf. It returns the
assigned leaf + its gate formatted as a ready-to-prepend string.

TWO transports, ONE contract:
  * IN-PROCESS  — pass a `BrainStore` (the composer / a daemon-local caller):
                  calls active_work.next_leaf directly. No network.
  * OVER MCP    — pass nothing (an external client: Codex / Gemini / a CLI):
                  POSTs `brain.work_next` to the daemon, mirroring
                  brainwrap.call_tool's SSE transport. Degrades to an empty
                  string when the daemon is unreachable (never blocks a turn).

The block is bounded by stable markers so a wrapper can refresh it on each turn
instead of stacking duplicates (same convention as brainwrap's context block).
"""
from __future__ import annotations

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
    """Render an assigned leaf (dict from next_leaf / brain.work_next) as the
    `<assigned_leaf>` block every client prepends. Names the work, the gate the
    leaf must pass to be DONE, and the leaf_id the client reports back to
    `brain.work_release`. Empty input → empty string (caller prepends nothing)."""
    if not leaf:
        return ""
    leaf_id = leaf.get("leaf_id", "")
    title = leaf.get("title", "")
    gate_kind = leaf.get("gate_kind", "manual")
    gate_spec = leaf.get("gate_spec") or {}
    runtime = leaf.get("runtime") or ""
    attempts = leaf.get("attempts", 0)
    note = (leaf.get("note") or "").strip()

    lines = [
        "<assigned_leaf>",
        "The brain assigns you this unit of work for this turn. Do it to "
        "completion, then report the outcome to brain.work_release.",
        f"  leaf_id:   {leaf_id}",
        f"  work:      {title}",
        f"  gate:      {gate_kind}"
        + (f"  {json.dumps(gate_spec, separators=(',', ':'))}" if gate_spec else ""),
    ]
    if runtime:
        lines.append(f"  runtime:   {runtime}")
    if attempts:
        lines.append(f"  attempt:   #{attempts + 1} (prior attempts re-opened this leaf)")
    if note:
        lines.append(f"  last note: {note}")
    lines.append(
        "  on done:   brain.work_release(leaf_id, done=true, "
        "evidence_ref=<proof the gate passed>)")
    lines.append(
        "  if blocked: brain.work_release(leaf_id, done=false, blocked=true, "
        "note=<why you need the founder>)  — never silently defer; there is no "
        "'later' state.")
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
    fit: Optional[list[str]] = None,
    owner_user: Optional[str] = None,
    agent_id: Optional[str] = None,
    store: "Optional[BrainStore]" = None,
) -> Optional[dict[str, Any]]:
    """Ask the brain for this runtime's next leaf and CLAIM it. Returns the leaf
    dict, or None when the frontier is dry / the daemon is unreachable.

    `store` given → in-process (calls active_work.next_leaf directly).
    `store` omitted → over MCP (POSTs brain.work_next to the daemon).

    This is the engine behind `assigned_leaf_block` — exposed separately for
    callers that want the structured leaf (e.g. the composer's own UI)."""
    if not (runtime or "").strip():
        raise ValueError("next_assigned_leaf requires a non-empty runtime")

    if store is not None:
        # in-process: import lazily so this module has no hard runtime dep on
        # active_work unless the in-process path is used.
        from . import active_work as aw
        owner = owner_user or _resolve_owner_inproc(store)
        leaf = aw.next_leaf(
            store, runtime=runtime, fit=fit,
            owner_user=owner, agent_id=agent_id,
        )
        return leaf.model_dump(mode="json") if leaf else None

    # over MCP: the daemon resolves the owner when omitted.
    args: dict[str, Any] = {"runtime": runtime}
    if fit is not None:
        args["fit"] = list(fit)
    if owner_user:
        args["owner_user"] = owner_user
    if agent_id:
        args["agent_id"] = agent_id
    res = _call_daemon("brain.work_next", args)
    if not res or not res.get("ok"):
        return None
    return res.get("leaf") or None


def assigned_leaf_block(
    *,
    runtime: str,
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
      block = assigned_leaf_block(runtime="codex", fit=["revit"])
      if block: prepend block to the system/context turn
    """
    leaf = next_assigned_leaf(
        runtime=runtime, fit=fit, owner_user=owner_user,
        agent_id=agent_id, store=store,
    )
    block = format_assigned_leaf(leaf) if leaf else ""
    return _wrap(block) if wrap else block
