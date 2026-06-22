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


# ── Composer modes (USER-AGENCY MANDATE) ──────────────────────────────
# Plan (default) — every host WRITE is gated pending approval; reads run.
# Auto           — reads run automatically; writes still gated.
# YOLO           — everything runs free (opt-in, reversible).
# This is the backend half the founder's "all writes gated" chip promised
# but never had (ia-critique-ai-stemcells-2026-06-03 §4: "nothing reads
# detail.mode … composer_agent.py has no gate"). The gate physically
# lives here — the ai.agent cell that decides what it may write.
MODE_PLAN = "plan"
MODE_AUTO = "auto"
MODE_YOLO = "yolo"
_VALID_MODES = (MODE_PLAN, MODE_AUTO, MODE_YOLO)
_DEFAULT_MODE = MODE_PLAN   # default-gated, matching the chip + mandate

# The canvas primitives that MUTATE host / canvas state — these are the
# "writes" the Plan/Auto modes gate. `run_node` / `run_workflow` cook
# nodes (which call connector WRITE ops + mutate outputs); `set_node_param`
# / `add_wire` / `spawn_node` mutate the graph. The pure-READ primitives
# (`query_graph`, `chat`) are never gated. Keep this list aligned with
# TOOL_SCHEMA below.
WRITE_TOOLS = frozenset({
    "spawn_node", "add_wire", "set_node_param", "run_node", "run_workflow",
    # SEAM 1 (universal self-extension): the BUILD tools that let a composer ask
    # self-extend ArchHub — they WRITE a new capability (a library node / a
    # base.py connector file) to the local machine, so they are gated WRITES
    # under Plan/Auto (an approve-able build) exactly like a host mutation. An
    # approved build flows to agents.self_extend.run_self_extend (build → ROMA
    # court → brain.write), the ONE agent-driven loop.
    "create_node_type", "create_connector", "create_ui_widget",
})
# The subset of WRITE_TOOLS that SELF-EXTEND ArchHub (build a new capability)
# rather than mutate the canvas/host. The bridge routes an approved one of these
# through agents.self_extend instead of the canvas replay path.
#
# create_ui_widget (the UI RUNG, founder steer "ALLOW AGENT FREE-FORM UI CODE BUT
# PUT GUARDRAILS AGAINST BAD EDITS") lets the agent author REAL free-form widget
# code — but it is persisted to a widgets registry (NOT the monolith), rendered
# only inside the sandboxed error-boundaried AgentWidgetHost, court-gated on
# gate_kind 'ui_renders' (renders+visible / app-not-blanked / no errors), and
# AUTO-REVERTED on a red verdict. The court + auto-revert ARE the guardrail.
BUILD_TOOLS = frozenset({"create_node_type", "create_connector",
                         "create_ui_widget"})
# Pure reads — always allowed, in every mode.
READ_TOOLS = frozenset({"query_graph", "chat"})


def normalize_mode(mode: str | None) -> str:
    """Coerce an arbitrary mode string to one of the three valid modes.
    Unknown / empty → the default-gated Plan mode (fail SAFE — never
    silently fall through to running writes)."""
    m = (mode or "").strip().lower()
    return m if m in _VALID_MODES else _DEFAULT_MODE


def _is_write_tool(name: str) -> bool:
    return (name or "") in WRITE_TOOLS


def mode_gates_write(mode: str, tool_name: str) -> bool:
    """True iff a write by `tool_name` must be GATED (blocked pending
    approval) under `mode`. Plan + Auto gate every write; YOLO gates
    nothing. Reads are never gated."""
    if not _is_write_tool(tool_name):
        return False
    m = normalize_mode(mode)
    if m == MODE_YOLO:
        return False
    # Plan AND Auto both gate writes (Auto only auto-runs READS).
    return True


def gated_action(tool_name: str, args: Any, mode: str) -> dict:
    """Build the typed-error approval action that REPLACES a blocked
    write. Per USER-AGENCY ("approval surfaces are typed errors with
    named recoveries"), this is not a freeform retry — it carries a
    typed `approval_required` shape with named recovery verbs the JSX
    surfaces as buttons. The write does NOT execute; it is queued."""
    return {
        "tool": tool_name,
        "args": args if isinstance(args, dict) else {},
        "result": None,
        # The gate marker the JSX consumer keys on (Wave A2). When
        # present, the JSX does NOT replay the write — it shows the
        # approval surface instead.
        "gated": True,
        "mode": normalize_mode(mode),
        "approval": {
            "type": "approval_required",
            "tool": tool_name,
            "reason": (
                f"Plan mode gates host writes. '{tool_name}' was queued "
                f"for your approval instead of running."
            ),
            # Named recoveries (typed, not freeform) — the JSX renders
            # these as buttons; each maps to a concrete next step.
            "recoveries": [
                {"id": "approve_once",
                 "label": "Approve & run once",
                 "detail": "Run this one write now, keep gating the rest."},
                {"id": "switch_auto",
                 "label": "Switch to Auto",
                 "detail": "Auto-run reads; keep gating writes."},
                {"id": "switch_yolo",
                 "label": "Switch to YOLO",
                 "detail": "Run everything without gating (reversible)."},
                {"id": "discard",
                 "label": "Discard",
                 "detail": "Drop this queued write."},
            ],
        },
    }


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
    # ── SEAM 1 — BUILD tools (universal self-extension) ───────────────────
    # These let the agent EXTEND ArchHub itself, not just operate the canvas.
    # LIBRARY-FIRST: ALWAYS call `query_graph`/`library` reasoning first — the
    # backend (agents.self_extend) runs library.search before create and REUSES
    # a match, so prefer describing the capability and let the build dedup. The
    # built artifact is AUTO-handed to the ROMA court (py_compile/registration
    # gate) and, on a GREEN verdict, AUTO-recorded in the brain as a learned
    # capability — no human stitches the organs.
    {
        "name": "create_node_type",
        "description": (
            "BUILD a new MODULAR library node type (a reusable canvas node) "
            "from a spec, then auto-verify it through the ROMA court and learn "
            "it. LIBRARY-FIRST: the backend searches the library first and "
            "REUSES an existing node if one matches — so call this only when no "
            "existing node fits. The spec MUST be modular: typed inputs/outputs, "
            "a config_schema (no hard-coded literals), description + examples. "
            "Gated under Plan/Auto (an approve-able build)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string",
                         "description": "unique kebab/snake type id, e.g. 'f_area'"},
                "display_name": {"type": "string"},
                "category": {"type": "string",
                             "description": "source|transform|filter|sink|ai"},
                "description": {"type": "string"},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "outputs": {"type": "array", "items": {"type": "string"}},
                "config_schema": {"type": "object"},
                "examples": {"type": "array"},
            },
            "required": ["type", "description"],
        },
    },
    {
        "name": "create_connector",
        "description": (
            "BUILD a new host CONNECTOR scaffold that implements the uniform "
            "connectors.base contract (typed ops, honest OpResult status), "
            "written as a real local file under app/connectors/, then auto-"
            "verify it through the ROMA court (py_compile on the new file) and "
            "learn it. Use this to teach ArchHub to talk to a NEW host/service. "
            "Each op body is an honest stub until filled in (never fabricated "
            "data). Gated under Plan/Auto (an approve-able build)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string",
                         "description": "host id, e.g. 'airtable' (→ airtable_connector.py)"},
                "label": {"type": "string", "description": "Human display name"},
                "description": {"type": "string"},
                "operations": {
                    "type": "array",
                    "description": "ops the connector exposes",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op_id": {"type": "string"},
                            "kind": {"type": "string", "enum": ["read", "action"]},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["op_id"],
                    },
                },
            },
            "required": ["host"],
        },
    },
    {
        "name": "create_ui_widget",
        "description": (
            "BUILD a new FREE-FORM UI widget — real component code the user asked "
            "for ('add a side panel with a slider that controls X'). You write the "
            "widget body as a JS function returning a React element; it is rendered "
            "ONLY inside ArchHub's sandboxed error-boundaried host (a side panel), "
            "so a bad widget can NEVER blank the app — it shows a fallback. The "
            "built widget is auto-verified through the ROMA court (gate_kind "
            "'ui_renders': it must RENDER + be VISIBLE, must NOT blank the app "
            "shell, and must raise zero errors) and, on a RED verdict, is "
            "AUTO-REVERTED (unregistered). On GREEN it is learned. Gated under "
            "Plan/Auto (an approve-able build). CODE CONTRACT: the body receives "
            "`React`, `bridge` (async slot caller: await bridge('slot', ...args)), "
            "and `api` (helpers); it MUST `return` a React element and set "
            "data-testid on the root to the widget id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                       "description": "unique snake/kebab widget id, e.g. 'co2_panel'"},
                "title": {"type": "string", "description": "Human display name"},
                "description": {"type": "string"},
                "code": {"type": "string",
                         "description": ("JS function body returning a React "
                                         "element; gets (React, bridge, api). Set "
                                         "data-testid={id} on the root element.")},
                "slots": {"type": "array", "items": {"type": "string"},
                          "description": "bridge slot names the widget reads"},
                "placement": {"type": "string", "enum": ["panel", "float"]},
            },
            "required": ["id", "code"],
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
        "SELF-EXTENSION: if the user asks for a capability ArchHub does not "
        "yet have, you may BUILD it — create_node_type (a new reusable canvas "
        "node) or create_connector (talk to a new host/service). LIBRARY-FIRST: "
        "do NOT mint a duplicate — only build when no existing node/host fits; "
        "the backend also searches the library first and reuses a match. A "
        "built capability is auto-verified by the court and only kept if it "
        "passes. "
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
    mode: str = _DEFAULT_MODE,
    model: str = "auto",
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
            on_chunk=..., on_tool_invocation=..., extra_tools=...)`
            (`tool_schemas=` is accepted as a back-compat alias).
        max_iters: Reserved for the future tool-loop bound. The actual
            loop is driven by the router today; we just cap our own
            invocation count via the callbacks.
        mode: Composer mode — "plan" (default, gates writes), "auto"
            (auto reads, gates writes), or "yolo" (runs free). This is
            the USER-AGENCY gate: in Plan/Auto, a host-WRITE tool the
            LLM calls is NOT emitted as an executable action — it is
            replaced by a typed `approval_required` action queued for
            the user. Defaults to Plan (fail-safe gated) so an absent /
            unknown mode never silently runs writes.

    Returns:
        Dict with keys `actions` (list of tool-invocation dicts), `text`
        (final assistant text), `mode` (the normalized mode), and
        `gated` (count of writes blocked pending approval). On failure,
        includes `error`.
    """
    mode = normalize_mode(mode)
    if not router:
        return {
            "actions": [],
            "text": "no router configured",
            "error": "missing_dep",
            "mode": mode,
            "gated": 0,
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
    gated_count = [0]   # mutable closure cell — # writes blocked this turn

    def _on_inv(inv: Any) -> None:
        try:
            name = (
                getattr(inv, "tool_name", None)   # real ToolInvocation attr
                or getattr(inv, "name", None)
                or getattr(inv, "tool", None)
                or "?"
            )
            args = (
                getattr(inv, "arguments", None)   # real ToolInvocation attr
                or getattr(inv, "args", None)
                or {}
            )
            # USER-AGENCY GATE — the real backend gate the "all writes
            # gated" chip promised. In Plan/Auto mode, a host-WRITE tool
            # does NOT become an executable canvas action: we replace it
            # with a typed approval_required action (named recoveries),
            # queued for the user, and never surface the write's result
            # back. YOLO (and all READ tools) pass straight through.
            if mode_gates_write(mode, name):
                gated_count[0] += 1
                actions.append(gated_action(name, args, mode))
                return
            result = getattr(inv, "result", None)
            action = {"tool": name, "args": args, "result": result}
            # SPAWN-ID CONTRACT (JSX half reads action.node_id): the router
            # ALLOCATES the new node id when spawn_node fires and returns it
            # in the ack (inv.result["node_id"], mirrored onto inv.arguments).
            # Surface it at the TOP LEVEL of the action so the JSX replay
            # (onAgentStep -> spawn_host_chat) places the node under THIS
            # id — making the id the model saw == the id on the canvas, so a
            # follow-up add_wire/run_node referencing it resolves. Absent
            # (older router / non-spawn tool) → omitted; JSX falls back to
            # minting its own id (back-compat).
            _node_id = None
            if isinstance(result, dict):
                _node_id = result.get("node_id")
            if not _node_id and isinstance(args, dict):
                _node_id = args.get("node_id")
            if _node_id:
                action["node_id"] = _node_id
            actions.append(action)
        except Exception:
            actions.append({"tool": "?", "args": {}, "result": None})

    text_buf: list[str] = []

    def _on_chunk(piece: str) -> None:
        if piece:
            text_buf.append(piece)

    try:
        # Hand the canvas primitives to the router as CLIENT-SIDE tools.
        # `extra_tools` merges TOOL_SCHEMA into the provider tool surface
        # for this call, so the LLM ACTUALLY SEES spawn_node / run_node /
        # add_wire / … and can call them. When it does, the router routes
        # the invocation to our `_on_inv` callback (it does NOT try to run
        # these through ToolEngine, which doesn't own them) and feeds a
        # neutral ack back to the model so its tool-use loop continues. We
        # collect each invocation in `actions` and the JSX side replays
        # them against the live canvas. (Before 2026-06-03 this passed
        # `tool_schemas=` to a signature that never accepted it → TypeError
        # → the tool-LESS fallback below → the LLM never saw the tools and
        # the whole orchestration path was dead. The router now supports
        # the kwarg natively; `tool_schemas` is still accepted as an
        # alias.)
        response = router.complete(
            history=history,
            model=model or "auto",
            on_chunk=_on_chunk,
            on_tool_invocation=_on_inv,
            extra_tools=TOOL_SCHEMA,
        )
        text = (
            getattr(response, "text", "") or "".join(text_buf)
        ).strip()
    except TypeError:
        # Defensive only: a STALE router build whose complete() predates
        # the extra_tools/tool_schemas kwarg. The supported router accepts
        # it (see app/llm_router.complete), so this path should never run
        # in a current tree — but if the composer is wired to an older
        # duck-typed client we degrade to a tool-LESS chat reply rather
        # than crashing the compose turn. The canvas won't mutate on this
        # path; the reply still streams.
        try:
            response = router.complete(
                history=history,
                model=model or "auto",
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
                "mode": mode,
                "gated": gated_count[0],
            }
    except Exception as ex:
        return {
            "actions": [],
            "text": "",
            "error": f"{type(ex).__name__}: {ex}",
            "mode": mode,
            "gated": gated_count[0],
        }

    # THE DRIVE (AgDR-0054): the composer may not return a turn that defers /
    # partials its own answer. Reuse the ONE shared no-later detector.
    completion = {"action": "allow", "deferral": []}
    try:
        import sys as _sys
        from pathlib import Path as _P
        _tools = str(_P(__file__).resolve().parents[2] / "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        import completion_gate as _cg
        _defer = _cg.scan_deferral(text)
        if _defer:
            completion = {"action": "block", "deferral": _defer,
                          "reason": "NOT DONE: composer reply defers work ("
                                    + ", ".join(_defer) + "). finish it or "
                                    "register a structured hold in active_work."}
    except Exception as _e:
        # FAIL CLOSED — surface the gate failure, never silently allow.
        completion = {"action": "error", "deferral": [],
                      "reason": "completion gate unavailable: " + str(_e)}
    return {"actions": actions, "text": text, "mode": mode,
            "gated": gated_count[0], "completion": completion}


# ─── Self-extend loop adapter (ask→build→COURT→learn) ─────────────────────
# The free-form self-extension entry point (bridge.self_extend_loop) atomizes a
# user request into a ROMA requirement tree, drives the unrolled loop the brain
# daemon cannot (run_to_dry can't cross HTTP — roma.py risk note), and uses
# run_agent_step ABOVE as the per-leaf EXECUTOR. These two pure helpers are the
# ONLY new composer surface: `atomize_vision` turns a request into leaf specs
# with built-in machine gates when the model returns none, and `compose_evidence`
# turns a run_agent_step result into the closing-evidence dict the court's
# diligence lens (court_harness.lens_diligence) + brain.enforce_diligence
# consume. run_agent_step's contract is UNCHANGED — it is REUSED, not edited.


def _appdata_self_extend_dir() -> str:
    """The real local directory the default self-extend example writes into
    (%APPDATA%/ArchHub/self_extend on Windows, ~/.archhub/self_extend else).
    A file under here is the machine-checkable artifact the court gates."""
    import os
    base = (os.environ.get("APPDATA")
            or os.path.join(os.path.expanduser("~"), ".archhub"))
    return os.path.join(base, "ArchHub", "self_extend")


def atomize_vision(user_msg: str,
                   decomposition: Optional[list[dict]] = None) -> list[dict]:
    """Map a free-form self-extend request to a list of ROMA leaf specs, each
    carrying a machine-checkable gate (gate_kind/gate_spec).

    If the caller already has a decomposition (e.g. the model proposed one, or a
    test passes the ONE example), it is returned UNCHANGED so the court gates
    exactly what was asked. Otherwise we build the DEFAULT decomposition: the
    "hello marker" proof — a real file written into %APPDATA%/ArchHub/self_extend
    that (1) exists, (2) compiles under py_compile, and (3) carries the proof
    sentinel. All three gates are built-in court probes (file_exists / py_compile
    in court_harness._BUILTIN_PROBES) — no CDP, no app, no risky host. This is the
    `one_example` from the binding spec, made executable."""
    if decomposition:
        return list(decomposition)
    import os
    marker = os.path.join(_appdata_self_extend_dir(), "hello_marker.py")
    marker_fwd = marker.replace("\\", "/")
    return [
        {
            "title": "Marker file exists on disk after the executor runs",
            "predicate": f"the file {marker_fwd} exists",
            "gate_kind": "file_exists",
            "gate_spec": {"path": marker_fwd},
        },
        {
            "title": "Marker file is real importable Python, not an empty shell",
            "predicate": "the marker file compiles under py_compile",
            "gate_kind": "py_compile",
            "gate_spec": {"path": marker_fwd},
        },
        {
            "title": "Marker file contains the proof sentinel string",
            "predicate": "the marker file contains GREETING = 'self-extend proven'",
            "gate_kind": "file_exists",
            "gate_spec": {"path": marker_fwd, "contains": "self-extend proven"},
        },
    ]


def compose_evidence(user_msg: str, graph: dict, leaf: Any,
                     run_result: dict) -> dict:
    """Turn a run_agent_step result into the court's closing-evidence dict.

    Returns EXACTLY the shape lens_diligence / brain.enforce_diligence consume
    (court_harness.py io_notes): {last_message, touched_files, file_contents,
    session_signals}. `touched_files` is every path the executor's actions named;
    `file_contents` reads each back so the artifact lens sees the real bytes the
    executor produced (never the executor's word). This makes the executor SHOW
    its work — the diligence juror refutes a bare completion claim."""
    rr = run_result if isinstance(run_result, dict) else {}
    actions = rr.get("actions") if isinstance(rr.get("actions"), list) else []
    touched: list[str] = []
    for a in actions:
        try:
            p = (a.get("args", {}) or {}).get("path")
        except Exception:
            p = None
        if p and p not in touched:
            touched.append(p)
    file_contents: dict[str, str] = {}
    for p in touched:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                file_contents[p] = fh.read()
        except Exception:
            # An unreadable / not-yet-written path is simply absent from
            # file_contents — the artifact lens (file_exists/py_compile) is the
            # authority on whether the real file satisfies the gate.
            pass
    last = (rr.get("text") or "").strip()
    if not last:
        last = (f"self-extend executor ran {len(actions)} action(s) for "
                f"'{leaf.title if leaf is not None else user_msg}'; "
                f"wrote {len(touched)} file(s).")
    return {
        "last_message": last,
        "touched_files": touched,
        "file_contents": file_contents,
        "session_signals": {
            "actions": len(actions),
            "gated": rr.get("gated", 0),
            "files_written": len(touched),
        },
    }
