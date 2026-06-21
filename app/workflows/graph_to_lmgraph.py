"""workflows.graph → LM_GRAPH translator (SESSIONS-GRAPH lane).

THE BUG this kills (founder: "every chat session opens as ONE flat node"):
64/67 saved sessions render as a single `conversation.chat` blob. Two root
causes, both fixed here + in `session_graph_migrator` / `bridge`:

  1. WRAP-AS-ONE: `session_graph_migrator.wrap_legacy_as_graph` wrapped the
     WHOLE chat into ONE node. The real per-turn structure (user → AI →
     tools → output) lived only in the message log, never as a graph.

  2. SHAPE MISMATCH: even when a graph existed it was emitted in the
     `workflows.graph` shape — `{id, type, label, config, inputs, outputs,
     position}` — but the JSX canvas renderer (`studio-lm.jsx`) dispatches on
     `n.kind` / `n.cat` and draws sockets from `n.ins` / `n.outs` (arrays of
     `{id, label, t}`). A node with only `type` and `inputs`/`outputs` has no
     `kind`, so the renderer treats it as a portless unknown — it collapses to
     a single flat card and wires vanish.

This module is the PURE translator for cause (2): a `workflows.graph` dict
(the `Workflow.to_dict()` / `wrap_legacy_as_graph()` shape) → an `LM_GRAPH`
dict the JSX renderer consumes directly. Cause (1) is handled by
`decompose_session_to_graph` below, which reuses the EXISTING per-turn
decomposer (`workflows.chat_to_workflow`) — no parallel system (ONE-SYSTEM
mandate) — and only falls back to the single-node wrap when there are no
messages to decompose.

Pure data functions — no Qt, no LLM, no I/O. The reverse `kind`/`cat` map is
DERIVED from `node_grammar.PRIMITIVES` (the single source of truth), so it can
never drift from the palette; a grounding test asserts the round-trip.

LM_GRAPH node shape (what the JSX renderer needs):
    {
      "id":    str,
      "kind":  str,          # grammar kind: ai_chat / parameter / result / …
      "cat":   str,          # palette category: ai / input / output / connector
      "title": str,
      "sub":   str,
      "x": float, "y": float, "w": int, "h": int,
      "ins":   [{"id","label","t"}, ...],
      "outs":  [{"id","label","t"}, ...],
      "config": dict,        # carried from the engine node
      # ai_chat only: "messages": [{role, content}, ...]
      # connector  only: "host": str
    }

LM_GRAPH wire shape:
    {"id": str, "from": [nodeId, portId], "to": [nodeId, portId]}
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


# ── engine-type → (kind, cat) reverse map, DERIVED from the grammar ───────
# Building it from PRIMITIVES means the canvas-facing kind a placed node would
# get is the SAME kind we assign on the way back — no hand-maintained second
# copy that can drift (the exact failure node_grammar's grounding test guards).
# When two primitives resolve to the same engine type (e.g. several typed nodes
# all map to `transform.apply`), the FIRST non-hidden primitive wins, then any
# primitive — so `conversation.chat` resolves to the visible `ai_chat`, not the
# hidden legacy `ai` master.
def _build_reverse_index() -> dict[str, tuple[str, str]]:
    try:
        from .node_grammar import PRIMITIVES
    except Exception:  # pragma: no cover - import guard
        try:
            from workflows.node_grammar import PRIMITIVES  # type: ignore
        except Exception:
            return {}
    idx: dict[str, tuple[str, str]] = {}
    # Pass 1: visible (non-hidden) primitives — they own the slot.
    for p in PRIMITIVES:
        if getattr(p, "hidden", False):
            continue
        for et in p.engine_types.values():
            if et and et not in idx:
                idx[et] = (p.kind, p.cat)
    # Pass 2: hidden primitives fill engine types no visible one claimed
    # (legacy graphs that only resolve through a hidden master still map).
    for p in PRIMITIVES:
        if not getattr(p, "hidden", False):
            continue
        for et in p.engine_types.values():
            if et and et not in idx:
                idx[et] = (p.kind, p.cat)
    return idx


_REVERSE: dict[str, tuple[str, str]] = _build_reverse_index()

# Prefix → cat for engine types with NO grammar primitive (e.g. the
# `tool.<name>` nodes `chat_to_workflow` mints for each tool invocation, or
# `host.*` typed nodes). Mirrors node_grammar._PREFIX_CAT plus the tool family.
_PREFIX_CAT: list[tuple[str, str]] = [
    ("tool.",   "connector"),
    ("host.",   "connector"),
    ("connector.", "connector"),
    ("render.", "ai"),
    ("vision.", "ai"),
    ("mesh.",   "ai"),
    ("anim.",   "ai"),
    ("llm.",    "ai"),
    ("ai.",     "ai"),
    ("conversation.", "ai"),
    ("input.",  "input"),
    ("data.",   "input"),
    ("fs.",     "input"),
    ("output.", "output"),
    ("control.", "logic"),
    ("verify.", "logic"),
    ("sense.",  "logic"),
    ("math.",   "math"),
    ("text.",   "text"),
    ("transform.", "shape"),
    ("filter.", "shape"),
    ("share.",  "share"),
    ("adapter.", "adapter"),
    ("code.",   "code"),
    ("watch.",  "watch"),
    ("trigger.", "trigger"),
    ("subgraph.", "skill"),
]

# AI engine types whose canvas node renders the conversation rail. Only the
# chat node carries `messages`; the other AI typed nodes use the param rail.
_CHAT_TYPES = {"conversation.chat"}

# Explicit kind preference for engine types SHARED by several primitives, where
# the first-wins reverse map would pick a misleading kind. `data.constant` is
# the home of number/text/boolean/file/color typed nodes (all share it) — a
# chat follow-up / a generic constant reads best as `text`, not `number` (which
# `number` would win on PRIMITIVES order). Keeps the node card honest.
_TYPE_KIND_OVERRIDE: dict[str, tuple[str, str]] = {
    "data.constant": ("text", "input"),
}

# Fallback ports for typed/synth engine types that carry NO registry NodeSpec
# (so `_ports_for` returns empty). Without these the node renders portless and
# any wire touching it VANISHES on the canvas. The `tool.<name>` nodes
# `chat_to_workflow` mints take the args-in / result+ok-out shape it wires.
_TOOL_INS = [{"id": "args", "label": "args", "t": "any"}]
_TOOL_OUTS = [{"id": "result", "label": "result", "t": "any"},
              {"id": "ok", "label": "ok", "t": "boolean"}]


def kind_cat_for_type(engine_type: str) -> tuple[str, str]:
    """Reverse-map an engine `type` to the canvas (kind, cat).

    1. Exact grammar hit (derived from PRIMITIVES) — the common path.
    2. Prefix fallback for typed/synth types with no primitive
       (`tool.Read` → kind `tool.Read`, cat `connector`).
    3. Last resort: kind = the type itself, cat `node`.
    """
    t = engine_type or ""
    if t in _TYPE_KIND_OVERRIDE:
        return _TYPE_KIND_OVERRIDE[t]
    if t in _REVERSE:
        return _REVERSE[t]
    for pre, cat in _PREFIX_CAT:
        if t.startswith(pre):
            return (t, cat)
    return (t or "node", "node")


def _ports_for_type(engine_type: str) -> dict:
    """{in,out} grammar ports for an engine type, from the registry NodeSpec,
    in the canvas `{id, label, t}` shape. Empty arrays when unknown — the JSX
    self-heal (`_upgradeLegacyNodes`) can still backfill ai_chat / connector
    ports, but we populate them here so the FIRST render already has sockets."""
    try:
        from .node_grammar import _ports_for as _gp
    except Exception:  # pragma: no cover
        try:
            from workflows.node_grammar import _ports_for as _gp  # type: ignore
        except Exception:
            return {"in": [], "out": []}
    raw = _gp(engine_type or "")

    def _conv(lst: list) -> list[dict]:
        out: list[dict] = []
        for p in lst or []:
            pid = p.get("id") or ""
            if not pid:
                continue
            out.append({
                "id": pid,
                "label": pid,
                "t": str(p.get("type") or "any").lower(),
            })
        return out
    return {"in": _conv(raw.get("in")), "out": _conv(raw.get("out"))}


def _node_config(n: dict) -> dict:
    """The engine node's config dict — handles both the `config` (workflows.graph)
    and `params` (canvas) forms; always returns a plain dict."""
    cfg = n.get("config")
    if isinstance(cfg, dict):
        return dict(cfg)
    params = n.get("params")
    out: dict = {}
    for p in params or []:
        if isinstance(p, dict) and "k" in p:
            out[p["k"]] = p.get("v")
    return out


def _ports_from_portlist(ports: Any) -> list[dict]:
    """Convert a workflows.graph Port list (`[{name, type, ...}]`,
    `Port.to_dict()` shape) to the canvas `{id, label, t}` shape. The node's
    OWN ports win over grammar ports because they carry node-specific names —
    e.g. `chat_to_workflow` names a tool node's inputs after the tool's actual
    argument keys (`file_path`, `query`), and wires reference those exact ids."""
    out: list[dict] = []
    for p in ports or []:
        if not isinstance(p, dict):
            continue
        pid = p.get("name") or p.get("id") or ""
        if not pid:
            continue
        out.append({
            "id": pid,
            "label": pid,
            "t": str(p.get("type") or "any").lower(),
        })
    return out


def _normalise_messages(messages: Any) -> list[dict]:
    """Normalise a message list to `[{role, content}]`, accepting BOTH dict
    messages (loaded from disk) and ChatMessage objects (with .role/.content)
    — the same dual contract `chat_to_workflow` reads."""
    out: list[dict] = []
    for m in messages or []:
        if isinstance(m, dict):
            out.append({"role": m.get("role", "user"),
                        "content": m.get("content", "")})
        elif hasattr(m, "role"):
            out.append({"role": getattr(m, "role", "user"),
                        "content": getattr(m, "content", "")})
    return out


# ── Canvas message shape (the JSX renderer's REAL contract) ───────────────
# THE SESSION-REOPEN BUG this kills (founder: real chat-composer sessions
# reopen with an EMPTY canvas — the conversation is gone). Two persistence
# schemas diverged:
#   - chat-composer sessions persist/migrate the conversation as
#     `conversation.chat` config.body.messages (or top-level `_messages`) in the
#     `{role, content}` shape, BUT
#   - the live canvas (`studio-lm.jsx`) renders an ai node's messages reading
#     `m.me` (bool) + `m.text` (str) — `{me, text}` — NOT `{role, content}`.
# So a reopened chat node found NO `m.me`/`m.text` and rendered blank → "the
# conversation is gone". The single mechanism every session LOAD passes through
# (`decompose_session_to_graph` → `translate_graph_to_lmgraph`) now emits the
# canvas `{me, text}` shape, so ALL existing on-disk sessions reopen correctly,
# not just new ones. Lossless + idempotent: a message ALREADY in canvas shape
# (a re-loaded canvas graph node) passes through unchanged; `model`/`images` are
# preserved when present. role 'user' → me:true, anything else → me:false.
def _to_canvas_message(m: Any) -> dict:
    """Coerce ONE message (dict or ChatMessage) into the canvas `{me, text}`
    shape the JSX renderer reads, preserving order, model + images when present.

    Accepts:
      - persisted `{role, content}` (chat-composer / legacy `_messages` /
        config.body.messages) → role 'user' ⇒ me:true, else me:false;
        content ⇒ text.
      - already-canvas `{me, text}` (a re-loaded canvas graph node) → passes
        through unchanged (idempotent).
      - ChatMessage objects (.role/.content/.model/.images) → mapped.
    """
    if isinstance(m, dict):
        # Already canvas-shaped — keep it verbatim (idempotent re-load).
        if "me" in m or "text" in m:
            out = dict(m)
            out["me"] = bool(out.get("me", False))
            out.setdefault("text", out.get("content", "") or "")
            return out
        role = m.get("role", "user")
        out = {"me": (role == "user"), "text": m.get("content", "") or ""}
        model = m.get("model")
        images = m.get("images")
        # Preserve a collapsed-turn marker if the migrator stamped one so the
        # canvas can still render "Thinking ×N" after normalisation.
        if m.get("_collapsed_count"):
            out["_collapsed_count"] = m.get("_collapsed_count")
        if model:
            out["model"] = model
        if images:
            out["images"] = images
        return out
    # ChatMessage object.
    role = getattr(m, "role", "user")
    out = {"me": (role == "user"), "text": getattr(m, "content", "") or ""}
    model = getattr(m, "model", None)
    images = getattr(m, "images", None)
    if model:
        out["model"] = model
    if images:
        out["images"] = list(images)
    return out


def _canvas_messages(messages: Any) -> list[dict]:
    """Normalise a whole message list to the canvas `[{me, text}]` shape,
    preserving order. Lossless + idempotent (see `_to_canvas_message`)."""
    return [_to_canvas_message(m) for m in (messages or [])]


def _messages_from_config(cfg: dict) -> list[dict]:
    """Pull the chat history a conversation.chat node carries in
    config.body.messages (the wrap_legacy shape). Normalised to {role,content}.
    """
    body = cfg.get("body") if isinstance(cfg.get("body"), dict) else {}
    msgs = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(msgs, list):
        msgs = cfg.get("messages") if isinstance(cfg.get("messages"), list) else []
    out: list[dict] = []
    for m in msgs or []:
        if isinstance(m, dict):
            out.append({"role": m.get("role", "user"),
                        "content": m.get("content", "")})
    return out


# Simple auto-layout: lay nodes in dependency-ish columns. We don't run a full
# topo sort (cheap + deterministic is enough for a readable first paint); the
# user can drag afterwards. Engine `position` is honored when present + non-zero.
_COL_W = 280
_ROW_H = 150
_X0 = 80
_Y0 = 80


def _category_column(cat: str) -> int:
    """A coarse left→right column per category so a decomposed chat reads
    input → AI → tools/shape → output without overlapping cards."""
    order = {
        "input": 0, "trigger": 0,
        "ai": 1,
        "connector": 2, "shape": 2, "logic": 2, "math": 2,
        "text": 2, "code": 2, "watch": 2,
        "output": 3, "share": 3, "adapter": 3,
    }
    return order.get(cat, 1)


def translate_graph_to_lmgraph(graph: Optional[dict]) -> dict:
    """Translate a `workflows.graph`-shaped dict into an `LM_GRAPH` dict the
    JSX canvas renders directly. Pure: never mutates the input.

    Accepts both serialisations:
      - nodes with `type` + `inputs`/`outputs` + `config` + `position`
        (Workflow.to_dict / wrap_legacy_as_graph), and
      - nodes that already carry `kind`/`cat`/`ins`/`outs` (a canvas graph
        re-loaded) — those pass through with light backfill.
    Edges in either `edges` (src_node/src_port/dst_node/dst_port) or `wires`
    (from/to) form are normalised to LM_GRAPH `wires` ({id, from, to}).
    """
    if not isinstance(graph, dict):
        return {"nodes": [], "wires": []}

    src_nodes = graph.get("nodes") or []
    out_nodes: list[dict] = []
    # Track per-column row counters for auto-layout of un-positioned nodes.
    col_rows: dict[int, int] = {}

    for n in src_nodes:
        if not isinstance(n, dict):
            continue
        engine_type = n.get("type") or ""
        cfg = _node_config(n)

        # Prefer an already-canvas node's kind/cat; else reverse-map the type.
        kind = n.get("kind")
        cat = n.get("cat")
        if not kind:
            kind, cat2 = kind_cat_for_type(engine_type)
            if not cat:
                cat = cat2
        if not cat:
            _k, cat = kind_cat_for_type(engine_type)

        # Ports, in precedence order:
        #   1. an already-canvas node's `ins`/`outs` (a re-loaded canvas graph);
        #   2. the node's OWN `inputs`/`outputs` (workflows.graph shape — these
        #      carry node-specific port names that the graph's wires reference,
        #      e.g. a tool node's arg-key inputs from chat_to_workflow);
        #   3. grammar ports for the engine type (the registry NodeSpec);
        #   4. a tool.<name> fallback so a portless tool node still draws+wires.
        ins = n.get("ins") if isinstance(n.get("ins"), list) else None
        outs = n.get("outs") if isinstance(n.get("outs"), list) else None
        if ins is None and outs is None:
            own_in = _ports_from_portlist(n.get("inputs"))
            own_out = _ports_from_portlist(n.get("outputs"))
            if own_in or own_out:
                ins, outs = own_in, own_out
            else:
                ports = _ports_for_type(engine_type)
                ins, outs = ports["in"], ports["out"]
        if ins is None:
            ins = []
        if outs is None:
            outs = []
        # tool.<name> backfill. `chat_to_workflow` names a tool node's inputs
        # after its argument keys, BUT a no-argument tool call (screenshot,
        # read_clipboard, …) yields zero inputs while its edge still targets a
        # port literally named `args`. Ensure the `args` in-port exists so that
        # wire resolves; ensure result/ok out-ports exist for a portless tool.
        if engine_type.startswith("tool."):
            if not ins:
                ins = [dict(p) for p in _TOOL_INS]
            if not outs:
                outs = [dict(p) for p in _TOOL_OUTS]

        # Position: honor a real engine position, else auto-column-layout.
        pos = n.get("position") if isinstance(n.get("position"), dict) else {}
        px = pos.get("x")
        py = pos.get("y")
        if not (isinstance(px, (int, float)) and isinstance(py, (int, float))
                and (px or py)):
            col = _category_column(cat)
            row = col_rows.get(col, 0)
            col_rows[col] = row + 1
            px = _X0 + col * _COL_W
            py = _Y0 + row * _ROW_H
        # An x/y already on the node (canvas form) wins outright.
        if isinstance(n.get("x"), (int, float)):
            px = n["x"]
        if isinstance(n.get("y"), (int, float)):
            py = n["y"]

        title = n.get("title") or n.get("label") or kind
        sub = n.get("sub") or engine_type or kind

        lm: dict[str, Any] = {
            "id": n.get("id") or f"n_{uuid.uuid4().hex[:10]}",
            "kind": kind,
            "cat": cat,
            "title": title,
            "sub": sub,
            "x": float(px), "y": float(py),
            "w": int(n.get("w") or 220), "h": int(n.get("h") or 112),
            "ins": ins,
            "outs": outs,
            "config": cfg,
        }
        # The conversation node renders a chat rail — attach its messages so
        # the canvas shows the turns, not an empty card. A re-loaded canvas
        # node may already carry `messages` (canvas `{me,text}` shape); the
        # wrap form stashes them in config.body.messages (`{role,content}`).
        # Normalise EITHER source to the canvas `{me,text}` shape the JSX
        # renderer reads — this is the load-boundary that fixes the empty-
        # canvas reopen for chat-composer sessions (see _to_canvas_message).
        if kind == "ai_chat" or engine_type in _CHAT_TYPES:
            existing = n.get("messages")
            raw = (existing if isinstance(existing, list)
                   else _messages_from_config(cfg))
            lm["messages"] = _canvas_messages(raw)
        # Connector nodes carry a `host` the renderer reads for the badge.
        if cat == "connector":
            host = n.get("host") or cfg.get("host")
            if not host and engine_type.startswith("tool."):
                # tool.<name> — surface the tool name as the host badge.
                host = engine_type.split(".", 1)[1]
            if host:
                lm["host"] = host
        out_nodes.append(lm)

    # ── Edges → wires. Accept both edge shapes; emit {id, from, to}. ─────
    out_wires: list[dict] = []
    raw_edges = graph.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raw_edges = graph.get("wires") or []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        if "src_node" in e or "dst_node" in e:
            frm = [e.get("src_node"), e.get("src_port")]
            to = [e.get("dst_node"), e.get("dst_port")]
        elif isinstance(e.get("from"), (list, tuple)) and isinstance(e.get("to"), (list, tuple)):
            frm = list(e["from"])[:2]
            to = list(e["to"])[:2]
        else:
            continue
        if not frm or not to or frm[0] is None or to[0] is None:
            continue
        out_wires.append({
            "id": e.get("id") or f"w_{uuid.uuid4().hex[:10]}",
            "from": [frm[0], frm[1] if len(frm) > 1 else None],
            "to": [to[0], to[1] if len(to) > 1 else None],
        })

    result: dict[str, Any] = {"nodes": out_nodes, "wires": out_wires}
    # Carry identity + provenance so a canvas-side save round-trips the slot.
    for k in ("id", "name", "description"):
        if graph.get(k):
            result[k] = graph[k]
    return result


# ── Per-turn decomposition (cause 1) — reuse the EXISTING decomposer ──────
def decompose_session_to_graph(session, messages: Optional[list] = None,
                               *, name: str = "") -> dict:
    """Turn a session into a MODULAR, multi-node LM_GRAPH.

    Priority (ONE-SYSTEM — no parallel decomposer is minted):
      1. If the session already has a REAL multi-node graph (a user-built
         workflow), translate that graph 1:1 to LM_GRAPH shape.
      2. Else if there are chat messages, run the EXISTING per-turn decomposer
         (`workflows.chat_to_workflow`) — user-turn → input/constant,
         assistant-turn → llm node, each tool invocation → tool.* node, final
         text → output — then translate the resulting workflows.graph to
         LM_GRAPH. This is the logical, modular graph the spec asks for.
      3. Else (no messages, no graph) → the single conversation node wrap, so
         the canvas always has something to render.

    Pure-ish: reads the session + messages, returns a dict. No Qt / LLM / I/O.
    """
    stored = getattr(session, "graph", None)
    if isinstance(stored, dict):
        nodes = stored.get("nodes") or []
        # A real multi-node graph (NOT the single conversation.chat wrap) →
        # translate it directly; it's already the user's structure.
        non_conv = [n for n in nodes
                    if isinstance(n, dict)
                    and (n.get("type") or "") != "conversation.chat"]
        if len(nodes) > 1 or non_conv:
            return translate_graph_to_lmgraph(stored)

    # Decompose the chat history into a logical graph via the EXISTING tool.
    msg_list = list(messages or [])
    if not msg_list and isinstance(stored, dict):
        # The single-node wrap stashed messages in config.body.messages —
        # recover them so we can still decompose a graph-only session.
        for n in (stored.get("nodes") or []):
            if isinstance(n, dict) and (n.get("type") or "") == "conversation.chat":
                msg_list = _messages_from_config(_node_config(n))
                break

    if msg_list:
        # Build the multi-node workflows.graph via the migrator's decomposer
        # (which delegates to the ONE per-turn decomposer chat_to_workflow —
        # ONE-SYSTEM), then translate it to the canvas LM_GRAPH shape.
        try:
            from ..session_graph_migrator import decompose_legacy_as_graph
        except Exception:  # pragma: no cover
            from session_graph_migrator import decompose_legacy_as_graph  # type: ignore
        wf_dict = decompose_legacy_as_graph(session, msg_list, name=name)
        lm = translate_graph_to_lmgraph(wf_dict)
        # Attach the FULL conversation to the first AI node so the chat rail
        # still shows every turn (chat_to_workflow models turns as separate
        # llm nodes; the rail lives on the first one for continuity).
        ai_nodes = [n for n in lm["nodes"] if n.get("cat") == "ai"]
        if ai_nodes:
            ai_nodes[0]["kind"] = "ai_chat"
            # Canvas `{me,text}` shape — the JSX renderer reads m.me / m.text,
            # NOT m.role / m.content. Without this the rail rendered blank and
            # the conversation looked gone on reopen.
            ai_nodes[0]["messages"] = _canvas_messages(msg_list)
        return lm

    # No messages, no real graph → single-node wrap, translated to LM shape.
    try:
        from ..session_graph_migrator import wrap_legacy_as_graph
    except Exception:  # pragma: no cover
        from session_graph_migrator import wrap_legacy_as_graph  # type: ignore
    wrapped = wrap_legacy_as_graph(session, msg_list, name=name)
    return translate_graph_to_lmgraph(wrapped)
