"""Ambient self-build — "stem cells grow as you work".

Founder vision (Phase 4): ArchHub should BUILD ITSELF mid-work. The node
graph grows + wires itself as the user works — not only when they type a
command into the composer.

ONE-SYSTEM (per ONE-SYSTEM-PLAN-BEFORE-BUILD): this is NOT a new engine.
The ambient pass REUSES `composer_agent.run_agent_step` — the exact same
LLM-as-orchestrator that the composer already drives, with the exact same
7 canvas tools (spawn_node / add_wire / set_node_param / run_node /
run_workflow / query_graph / chat). The only thing we add here is:

  1. an AMBIENT NUDGE prefixed onto the user message — "given the graph +
     what just happened + brain facts, propose the NEXT 1-3 nodes/wires
     that advance the apparent goal" — so the same agent produces a small
     forward-growth proposal instead of answering a typed instruction.
  2. a PROPOSAL CAP — ambient passes may only propose a few mutations per
     turn (no runaway self-construction).

The USER-AGENCY gate is UNCHANGED and REUSED: `run_agent_step(mode=...)`
already gates every host/graph WRITE in Plan (default) + Auto, replacing
each with a typed `approval_required` action queued for the user. So an
ambient pass in Plan mode produces GHOST / PENDING proposals the user
accepts or dismisses — it NEVER auto-applies. In Auto/YOLO it applies
through the same approval/replay path (reversible). The bridge emits the
SAME `agent_step_done` signal; the JSX `onAgentStep` replays it through
the SAME approval queue. No parallel store, no parallel surface.

Off-thread + cap-bounded + gated-by-default = SAFE: the founder watches
the canvas grow as ghost proposals, and nothing runs without the gate.

────────────────────────────────────────────────────────────────────────────
AMBIENT DEFAULT-ON (founder steer 2026-06-22: "on / ambient") — the contract
────────────────────────────────────────────────────────────────────────────
Ambient self-extend is DEFAULT-ON: the ambient path may PROPOSE and BUILD
extensions proactively as the user works. The founder chose the ambient
default; the safety is not "off by default" but a THREE-PART contract every
ambient build is held to (so default-ON is safe):

  1. COURT-GATED — an ambient pass that proposes a BUILD (create_node_type /
     create_connector) routes through the SAME self-extend loop the typed
     composer uses (bridge.self_extend → run_self_extend → build → COURT →
     learn). The build is APPLIED/LEARNED ONLY on a GREEN court verdict; a red
     never applies (the court is the gate, not the ambient proposer).
  2. REVERSIBLE — a green build wrote a single removable local artifact; the UI
     offers an Undo (bridge.self_extend_undo → self_extend.undo_artifact, path-
     jailed to the self_extend dir). Red applies nothing → nothing to undo.
  3. VISIBLE — every ambient pass + every court verdict is SURFACED, never
     silent: the pass rides the SAME `agent_step_done` signal (tagged
     `ambient:true` so the JSX labels it "grow · …"), and each build's court
     verdict rides the `court_verdict` log. The founder always SEES what
     ambient proposed and how the court ruled.

`AMBIENT_DEFAULT_ON` is the single source of truth for the default; the bridge
+ JSX read it (an explicit user OFF still wins — USER-AGENCY). Honour Plan/Auto/
YOLO for explicit typed asks; ambient proposals ALWAYS pass through the court
regardless of mode (a green build in YOLO still required the court to green it).
"""
from __future__ import annotations

from typing import Any

# AMBIENT DEFAULT-ON (founder steer 2026-06-22). The single source of truth for
# whether ambient self-extend runs by default. True = the ambient path proposes/
# builds proactively (every build court-gated + reversible + visible, see the
# module docstring contract). An explicit user toggle OFF overrides this
# (USER-AGENCY) — this is only the DEFAULT when the user has expressed no
# preference. The bridge.ambient_grow slot + the JSX ambient effect both read it.
AMBIENT_DEFAULT_ON = True

# How many proposed mutations one ambient pass may surface. The pass asks
# the model for "1-3" next nodes/wires; we hard-cap the returned ACTION
# list so a model that over-produces can never flood the canvas / approval
# queue. WRITE actions count against the cap; pure reads (query_graph) and
# the trailing chat do not. This is the runaway-loop guard.
AMBIENT_MAX_PROPOSALS = 3

# The trigger events the JSX side debounces into an ambient pass. Recorded
# here (not just in the JSX) so the contract is one place + testable: a pass
# fires AFTER one of these SETTLES (composer turn done, a node finished
# cooking, a host was spawned). Mid-typing is skipped by the JSX idle guard.
AMBIENT_TRIGGERS = ("agent_step_done", "workflow_done", "node_spawned")


def ambient_default_on(user_pref: Any = None) -> bool:
    """Resolve whether ambient runs, honouring USER-AGENCY: an explicit user
    preference (True/False) ALWAYS wins; only when the user expressed no
    preference (None / unset) does the AMBIENT_DEFAULT_ON default apply. The
    bridge passes the persisted user toggle (or None) so default-ON is the
    out-of-box behaviour while a user OFF is respected."""
    if isinstance(user_pref, bool):
        return user_pref
    if isinstance(user_pref, str):
        v = user_pref.strip().lower()
        if v in ("1", "true", "on", "yes"):
            return True
        if v in ("0", "false", "off", "no"):
            return False
    return AMBIENT_DEFAULT_ON


def ambient_prompt(*, last_turn: str = "", brain_facts: str = "") -> str:
    """The ambient NUDGE handed to run_agent_step as the `user_msg`. It is
    NOT a user instruction — it is a standing directive that turns the same
    composer agent into a forward-growth proposer, grounded in (a) the
    current graph (the agent already gets a graph summary in its system
    prompt), (b) the last composer turn / what just happened, and (c) brain
    facts. Kept tight so the model proposes SMALL, concrete next steps.
    """
    parts = [
        "AMBIENT GROW PASS. The user is actively working on this graph. "
        "Do NOT answer a question — instead look at the current graph and "
        "propose the NEXT 1 to 3 nodes and/or wires that most obviously "
        "advance what the user appears to be building. Prefer wiring up "
        "existing dangling outputs, adding the natural downstream node "
        "(e.g. a filter after a list, a schedule/PDF after a filter, a "
        "conversation to reason over a host's output), or connecting two "
        "nodes the user clearly intends to join. ",
        "Use the canvas tools (spawn_node / add_wire / set_node_param) to "
        "express the proposal. Propose AT MOST 3 mutations. If the graph "
        "is already complete or there is no obvious next step, make NO tool "
        "calls and reply with a one-line note. Never run hosts here. ",
    ]
    if last_turn:
        parts.append("WHAT JUST HAPPENED: " + last_turn.strip()[:600] + " ")
    if brain_facts:
        parts.append("RELEVANT MEMORY: " + brain_facts.strip()[:600] + " ")
    return "".join(parts)


def _cap_actions(actions: list, max_writes: int = AMBIENT_MAX_PROPOSALS) -> list:
    """Hard-cap the proposed WRITE actions to `max_writes`. Reads + chat
    pass through uncapped (they never mutate). This is the runaway guard:
    however many tool calls the model emitted, an ambient pass can only
    surface a few writes (gated or not) per turn.

    A gated action carries `gated:true` / an approval payload; an ungated
    write is any action whose tool is a known write tool. Both count.
    """
    try:
        from agents.composer_agent import WRITE_TOOLS
    except Exception:
        try:
            from composer_agent import WRITE_TOOLS  # path-loaded fallback
        except Exception:
            WRITE_TOOLS = frozenset({
                "spawn_node", "add_wire", "set_node_param",
                "run_node", "run_workflow",
            })
    out: list = []
    writes = 0
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        tool = a.get("tool") or ""
        is_write = bool(a.get("gated")) or (tool in WRITE_TOOLS)
        if is_write:
            if writes >= max_writes:
                continue   # drop over-cap proposals — never flood the canvas
            writes += 1
        out.append(a)
    return out


def run_ambient_grow(
    *,
    graph: dict,
    router: Any,
    focused_node_id: str = "",
    mode: str = "plan",
    last_turn: str = "",
    brain_facts: str = "",
    max_proposals: int = AMBIENT_MAX_PROPOSALS,
) -> dict:
    """Run ONE ambient grow pass and return the SAME result shape
    `run_agent_step` returns (`actions` / `text` / `mode` / `gated`), so the
    bridge can emit it on the SAME `agent_step_done` signal and the JSX
    `onAgentStep` replays it through the SAME approval queue — zero new
    plumbing.

    This is a thin wrapper over `run_agent_step` (ONE-SYSTEM): it builds the
    ambient nudge, calls the composer agent in the user's current mode
    (default Plan → every write gated → ghost proposals), then caps the
    proposed writes. The pass is marked `ambient:true` so the JSX can label
    the queued proposals as growth (distinct from a typed-composer write).
    """
    # Reuse the composer agent — import the SAME run_agent_step the composer
    # slot uses. Two package-name collisions exist (`agents` app vs repo-root),
    # so try both spellings, matching the test-suite loader convention.
    try:
        from agents.composer_agent import run_agent_step
    except Exception:
        from composer_agent import run_agent_step  # path-loaded fallback

    if not router:
        return {"actions": [], "text": "no router configured",
                "error": "missing_dep", "mode": mode, "gated": 0,
                "ambient": True}

    msg = ambient_prompt(last_turn=last_turn, brain_facts=brain_facts)
    result = run_agent_step(
        user_msg=msg,
        graph=graph if isinstance(graph, dict) else {},
        focused_node_id=focused_node_id or "",
        router=router,
        mode=mode or "plan",
    )
    if not isinstance(result, dict):
        return {"actions": [], "text": "", "error": "bad_result",
                "mode": mode, "gated": 0, "ambient": True}

    # Cap the proposals (runaway guard) + tag every surviving action + the
    # envelope as ambient so the JSX surfaces them as GHOST growth proposals.
    capped = _cap_actions(result.get("actions") or [], max_proposals)
    for a in capped:
        if isinstance(a, dict):
            a["ambient"] = True
    result["actions"] = capped
    result["ambient"] = True
    # Recompute the gated count over the capped set so the badge is honest.
    result["gated"] = sum(
        1 for a in capped if isinstance(a, dict) and a.get("gated"))
    return result
