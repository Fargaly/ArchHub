"""Composer LLM-tool-orchestration path — REGRESSION GUARD.

Bug (pre-2026-06-03): `app/agents/composer_agent.run_agent_step` called
`router.complete(..., tool_schemas=TOOL_SCHEMA)`, but `LLMRouter.complete`
had NO such kwarg → TypeError → an `except TypeError` swallow fell back to
a tool-LESS `complete()` whose own comment said "the LLM won't see the
tools". Net effect: the Composer — the primary IDE (ARCHITECTURE LOCK) —
could never present spawn_node / run_node to the model, so the model could
never drive the canvas. The whole orchestration path was dead.

Fix: `complete()` now accepts `extra_tools` (and `tool_schemas` as a
back-compat alias). The caller's CLIENT-SIDE tools are merged into the
provider tool surface for that call; when the model invokes one, the
router records it via `on_tool_invocation` (NOT ToolEngine.invoke, which
doesn't own them) and feeds a neutral ack back so the tool loop continues.

These tests prove, WITHOUT a live model:
  (1) complete() accepts the composer's tools under both kwarg spellings
      (no TypeError) — the exact thing that was broken.
  (2) a real composer step (run_agent_step) presents spawn_node/run_node
      to the router and routes the invocations back into `actions`.
  (3) the composer's tools actually reach the provider call
      (`client.stream_completion(tools=...)`) — i.e. the model would SEE
      them — and a client-side tool call is acked, not dispatched to
      ToolEngine.
  (4) code-shape guards so the seam can't silently regress.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Package-name collision guard. TWO packages are named `agents` in this repo:
# app/agents/ (the Composer agent — composer_agent.py) and the repo-root
# agents/ (ceo_routine, hourly_report, ...). In full-suite order a prior test
# that imports the repo-root `agents` caches it in sys.modules and SHADOWS
# app/agents — so the in-test `from agents.composer_agent import ...` raises
# ModuleNotFoundError (the file passes alone, flakes only in the full suite).
# Load app/agents/composer_agent.py by EXPLICIT PATH and register it so every
# import below resolves regardless of collection order.
import importlib.util as _ilu  # noqa: E402


def _load_app_composer_agent():
    """Load app/agents/composer_agent.py by EXPLICIT PATH under a
    non-colliding module name, so the repo-root `agents` package can never
    shadow it (registering sys.modules['agents.composer_agent'] is NOT enough —
    `from agents.composer_agent import` re-resolves through the cached repo-root
    parent). Tests bind the names they need off `_CA`."""
    spec = _ilu.spec_from_file_location(
        "_app_agents_composer_agent", str(APP / "agents" / "composer_agent.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CA = _load_app_composer_agent()

from tool_engine import ToolInvocation  # the REAL invocation the live router fires


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _RecordingRouter:
    """Minimal duck-typed router that records the kwargs run_agent_step
    hands it, then drives the on_tool_invocation callback the way the real
    router does for a client-side (composer) tool. Lets us prove the
    composer presents its tools AND collects the resulting actions —
    without a live LLM."""

    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, *, history, model, on_chunk=None,
                 on_tool_invocation=None, on_reasoning=None, on_status=None,
                 session_pin=None, system_override=None,
                 extra_tools=None, tool_schemas=None):
        self.calls.append({
            "history": history,
            "model": model,
            "extra_tools": extra_tools,
            "tool_schemas": tool_schemas,
        })
        # Emulate the router accepting the composer's spawn_node tool and
        # the model calling it: fire the invocation callback so the
        # composer collects an action, exactly like the real loop.
        if on_tool_invocation is not None:
            # Drive _on_inv with the REAL ToolInvocation dataclass the live
            # router fires (tool_engine.ToolInvocation: .tool_name/.arguments,
            # NOT .name/.args). Guards the second wired-but-dead hop: if _on_inv
            # stops reading .tool_name — OR the dataclass attr is renamed — the
            # actions[0]["tool"] == "spawn_node" assertion below breaks loudly,
            # instead of silently labelling every live AI action "?".
            on_tool_invocation(ToolInvocation(
                id="inv-1",
                tool_name="spawn_node",
                arguments={"family": "revit", "title": "Walls"},
                status="ok",
                result={"status": "ok", "accepted": True},
            ))
        if on_chunk is not None:
            on_chunk("placing a revit node")

        class _Resp:
            text = "placing a revit node"
            tool_invocations: list = []
        return _Resp()


class _FakeStream:
    """Provider client stub for the end-to-end _complete_once test. First
    call returns a tool_use for the composer's spawn_node; second call
    returns final text. Records the `tools` list it was handed each call so
    the test can assert the composer's tools reached the provider."""

    def __init__(self):
        self.seen_tools: list[list] = []
        self._calls = 0

    def stream_completion(self, *, model, system, messages, tools,
                          on_chunk=None, on_reasoning=None, **kwargs):
        self.seen_tools.append(tools)
        self._calls += 1
        if self._calls == 1:
            return {
                "type": "tool_use",
                "text": "",
                "tool_calls": [{
                    "id": "tc_1",
                    "name": "spawn_node",
                    "input": {"family": "revit", "title": "Walls"},
                }],
            }
        if on_chunk is not None:
            on_chunk("done — node placed")
        return {"type": "final", "text": "done — node placed"}


def _real_router():
    """A real LLMRouter over a real (empty) ToolEngine — no hosts probed,
    no providers configured. Enough to exercise _complete_once with a fake
    client."""
    from manager import ConnectorManager
    from tool_engine import ToolEngine
    from llm_router import LLMRouter
    return LLMRouter(ToolEngine(ConnectorManager()))


# ---------------------------------------------------------------------------
# (1) The exact break: complete() must accept the composer's tools.
# ---------------------------------------------------------------------------
def test_complete_signature_accepts_extra_tools_and_alias():
    import inspect
    from llm_router import LLMRouter
    params = inspect.signature(LLMRouter.complete).parameters
    assert "extra_tools" in params, (
        "complete() must accept extra_tools — the seam that lets the "
        "Composer present its canvas tools to the model."
    )
    assert "tool_schemas" in params, (
        "complete() must accept tool_schemas as a back-compat alias — the "
        "exact kwarg the Composer historically passed (and that used to "
        "raise TypeError)."
    )


def test_complete_tool_schemas_no_typeerror_live_guard(monkeypatch):
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _real_router()
    # Force the "no provider configured" soft-return path so complete()
    # returns a neutral LLMResponse instead of doing any I/O.
    monkeypatch.setattr(router, "configured_providers", lambda: [])
    # Both spellings must be accepted without TypeError.
    r1 = router.complete(history=[{"role": "user", "content": "hi"}],
                         model="auto", tool_schemas=TOOL_SCHEMA)
    r2 = router.complete(history=[{"role": "user", "content": "hi"}],
                         model="auto", extra_tools=TOOL_SCHEMA)
    assert r1.model == "(no provider configured)"
    assert r2.model == "(no provider configured)"


# ---------------------------------------------------------------------------
# (2) A real composer step presents its tools + collects the actions.
# ---------------------------------------------------------------------------
def test_run_agent_step_presents_spawn_and_run_node():
    run_agent_step = _CA.run_agent_step
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _RecordingRouter()
    out = run_agent_step(
        user_msg="add a revit walls node",
        graph={"nodes": [], "wires": []},
        router=router,
    )
    # The composer must have called the router exactly once, handing it the
    # canvas tool catalog via extra_tools (the supported name).
    assert len(router.calls) == 1
    presented = router.calls[0]["extra_tools"]
    assert presented is TOOL_SCHEMA or presented == TOOL_SCHEMA, (
        "run_agent_step must pass TOOL_SCHEMA to the router so the LLM can "
        "see the canvas tools."
    )
    names = {t["name"] for t in presented}
    assert {"spawn_node", "run_node"} <= names, (
        "spawn_node and run_node MUST be among the tools presented to the "
        "model — they were invisible before the fix."
    )
    # And the invocation the model 'made' flowed back into actions.
    assert out["actions"], "the tool invocation must be collected as an action"
    assert out["actions"][0]["tool"] == "spawn_node"
    assert out.get("error") is None
    assert "revit node" in out["text"]


# ---------------------------------------------------------------------------
# (3) End-to-end through _complete_once: the composer's tools reach the
#     provider call, and a client-side call is acked (not ToolEngine'd).
# ---------------------------------------------------------------------------
def test_extra_tools_reach_provider_and_are_acked():
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _real_router()
    client = _FakeStream()

    seen_invocations: list = []

    resp = router._complete_once(
        history=[{"role": "user", "content": "add a revit walls node"}],
        provider="anthropic",
        model_name="claude-test",
        note="",
        client=client,
        on_chunk=lambda _p: None,
        on_tool_invocation=lambda inv: seen_invocations.append(inv),
        extra_tools=TOOL_SCHEMA,
    )

    # The provider saw the composer's tools on the FIRST call — i.e. the
    # model would actually SEE spawn_node / run_node. (Anthropic wire shape
    # keeps `name` at the top level.)
    assert client.seen_tools, "stream_completion was never called"
    first_call_names = {t.get("name") for t in client.seen_tools[0]
                        if isinstance(t, dict)}
    assert {"spawn_node", "run_node"} <= first_call_names, (
        "the composer's tools must be merged into the provider tool "
        "surface for the call — this is what makes them visible to the LLM."
    )

    # The model's spawn_node call was routed to on_tool_invocation and
    # ACKED (status ok, accepted) — NOT dispatched to ToolEngine (which
    # would have returned 'Unknown tool: spawn_node').
    spawn_invs = [i for i in seen_invocations
                  if getattr(i, "tool_name", "") == "spawn_node"]
    assert spawn_invs, "spawn_node invocation should have fired the callback"
    final = spawn_invs[-1]
    assert final.status == "ok"
    assert (final.result or {}).get("accepted") is True
    assert "Unknown tool" not in str(final.result), (
        "client-side tools must NOT be dispatched to ToolEngine.invoke"
    )
    # The loop continued to a final text answer after the tool round-trip.
    assert "node placed" in (resp.text or "")


def test_extra_tools_not_filtered_for_small_models():
    """Google/Ollama trim the tool list, but the caller's explicit
    client-side tools must survive — they are appended AFTER the trim."""
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _real_router()
    client = _FakeStream()
    router._complete_once(
        history=[{"role": "user", "content": "add a node"}],
        provider="google",
        model_name="gemini-2.5-flash",
        note="",
        client=client,
        on_chunk=lambda _p: None,
        on_tool_invocation=lambda _i: None,
        extra_tools=TOOL_SCHEMA,
    )
    assert client.seen_tools
    # Google wire shape carries the name at the top level too.
    names = {t.get("name") for t in client.seen_tools[0]
             if isinstance(t, dict)}
    assert {"spawn_node", "run_node"} <= names


def test_system_override_stays_tool_less():
    """A specialised one-shot (system_override) must remain tool-LESS even
    if a caller passes extra_tools — Node Smith etc. must not be tempted
    into tool calls."""
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _real_router()
    client = _FakeStream()
    router._complete_once(
        history=[{"role": "user", "content": "generate a spec"}],
        provider="anthropic",
        model_name="claude-test",
        note="",
        client=client,
        on_chunk=lambda _p: None,
        on_tool_invocation=lambda _i: None,
        system_override="You output ONLY JSON.",
        extra_tools=TOOL_SCHEMA,
    )
    assert client.seen_tools
    assert client.seen_tools[0] == [], (
        "system_override one-shots must present NO tools, even when "
        "extra_tools is supplied."
    )


# ---------------------------------------------------------------------------
# (4) Code-shape guards — the seam exists and routes correctly.
# ---------------------------------------------------------------------------
def test_router_merges_extra_tools_and_skips_toolengine():
    src = (APP / "llm_router.py").read_text(encoding="utf-8")
    # The merge into the provider surface exists.
    assert "_client_tool_names" in src
    # The dispatch loop short-circuits client-side tools BEFORE the gate
    # and BEFORE ToolEngine.invoke.
    sc_idx = src.find("if inv.tool_name in _client_tool_names:")
    assert sc_idx != -1, "client-side short-circuit missing from dispatch loop"
    invoke_idx = src.find("self.tools.invoke(", sc_idx)
    assert sc_idx < invoke_idx, (
        "client-side tools must be handled BEFORE ToolEngine.invoke"
    )


def test_composer_passes_extra_tools_not_dead_kwarg():
    src = (APP / "agents" / "composer_agent.py").read_text(encoding="utf-8")
    assert "extra_tools=TOOL_SCHEMA" in src, (
        "composer must hand its tools to the router via extra_tools"
    )


# ---------------------------------------------------------------------------
# (5) SPAWN-ID CONTRACT — the worst bug: composer multi-node orchestration.
#     The router must ALLOCATE a real node id for spawn_node + return it in
#     the ack (was content-free {accepted:true}); the composer must surface
#     it in the action dict the JSX replays. Without this, a follow-up
#     add_wire/run_node the model emits references an id the canvas never had.
# ---------------------------------------------------------------------------
def test_spawn_node_ack_carries_real_node_id():
    """The real _complete_once path must put a non-empty node_id into the
    spawn_node ack (alongside accepted:True) — that is the id the model
    learns + the JSX will place the node under."""
    TOOL_SCHEMA = _CA.TOOL_SCHEMA
    router = _real_router()
    client = _FakeStream()
    seen: list = []
    router._complete_once(
        history=[{"role": "user", "content": "add a revit walls node"}],
        provider="anthropic", model_name="claude-test", note="",
        client=client,
        on_chunk=lambda _p: None,
        on_tool_invocation=lambda inv: seen.append(inv),
        extra_tools=TOOL_SCHEMA,
    )
    spawn = [i for i in seen if getattr(i, "tool_name", "") == "spawn_node"]
    assert spawn, "spawn_node invocation should have fired"
    res = spawn[-1].result or {}
    assert res.get("accepted") is True, "ack must stay back-compat (accepted)"
    node_id = res.get("node_id")
    assert node_id and isinstance(node_id, str), (
        "spawn_node ack MUST carry a real allocated node_id — TOOL_SCHEMA "
        "promises 'Returns the new node id' and follow-up wire/run calls "
        "need it. This was the dead-orchestration bug."
    )
    # The id is also mirrored onto the invocation arguments so the caller's
    # action dict (built from the invocation) carries it.
    assert (spawn[-1].arguments or {}).get("node_id") == node_id


class _SpawnAckRouter:
    """Duck-typed router that emulates the REAL router's spawn ack: it
    allocates a node id and returns it in the invocation result, exactly
    like _complete_once does for a client-side spawn_node call. Lets us
    prove run_agent_step lifts node_id into the action dict without a model."""

    def complete(self, *, history, model, on_chunk=None,
                 on_tool_invocation=None, **kwargs):
        if on_tool_invocation is not None:
            on_tool_invocation(ToolInvocation(
                id="inv-1", tool_name="spawn_node",
                arguments={"family": "revit", "node_id": "ng:ai_chat:dead0001"},
                status="ok",
                result={"status": "ok", "accepted": True,
                        "node_id": "ng:ai_chat:dead0001"},
            ))

        class _Resp:
            text = "placed"
            tool_invocations: list = []
        return _Resp()


def test_run_agent_step_surfaces_node_id_in_action():
    """The composer must lift the router-allocated node_id to the TOP LEVEL
    of the action dict so the JSX replay places the node under that id.

    The id-lift is only observable when the spawn write ACTUALLY runs, so
    this exercises an ungated mode. (Plan mode — now the default — gates
    writes per the USER-AGENCY mandate; that gate is covered by
    tests/test_plan_mode_gate.py. spawn_node in plan mode becomes a
    queued approval whose `args` still carry the id, but the top-level
    `node_id` lift is an executed-action contract — so we run YOLO here.)
    """
    run_agent_step = _CA.run_agent_step
    out = run_agent_step(
        user_msg="add a revit walls node",
        graph={"nodes": [], "wires": []},
        router=_SpawnAckRouter(),
        mode="yolo",   # ungated → the write runs → the id lifts
    )
    assert out["actions"], "the spawn invocation must be collected"
    act = out["actions"][0]
    assert act["tool"] == "spawn_node"
    assert act.get("node_id") == "ng:ai_chat:dead0001", (
        "run_agent_step must surface the allocated node_id at the action "
        "top level — the JSX onAgentStep reads action.node_id."
    )


# ---------------------------------------------------------------------------
# (6) TOOLENGINE RACE — the whitelist filter must be per-call + thread-safe,
#     never a mutation of the shared ToolEngine.tool_schemas_for.
# ---------------------------------------------------------------------------
def test_allowed_tool_names_filters_without_mutating_engine():
    """complete()'s allowed_tool_names whitelist filters the ToolEngine
    surface for the call via a local copy — the shared engine method is the
    SAME object before and after (no monkey-patch)."""
    TOOL_SCHEMA = _CA.TOOL_SCHEMA  # parity (path-loaded, collision-immune)
    router = _real_router()
    client = _FakeStream()
    # The old monkey-patch REPLACED the instance attribute with a closure,
    # so the engine's __dict__ gained a 'tool_schemas_for' entry shadowing
    # the class method. The thread-safe path never sets that instance attr;
    # the bound method still resolves from the CLASS. Compare the underlying
    # function identity (bound-method objects are freshly created per access,
    # so `is` on the bound method is unreliable) AND assert no instance-level
    # override was installed.
    func_before = router.tools.tool_schemas_for.__func__
    assert "tool_schemas_for" not in router.tools.__dict__, (
        "precondition: engine starts with no instance-level override"
    )
    router._complete_once(
        history=[{"role": "user", "content": "do a thing"}],
        provider="anthropic", model_name="claude-test", note="",
        client=client,
        on_chunk=lambda _p: None,
        on_tool_invocation=lambda _i: None,
        allowed_tool_names={"some_nonexistent_tool"},
    )
    # The shared engine's method is untouched — the old bug REPLACED it with
    # an instance-level closure (would appear in __dict__ + change __func__).
    assert router.tools.tool_schemas_for.__func__ is func_before, (
        "allowed_tool_names must NOT mutate the shared ToolEngine — it was a "
        "per-turn monkey-patch that corrupted concurrent chat/workflow turns."
    )
    assert "tool_schemas_for" not in router.tools.__dict__, (
        "no instance-level tool_schemas_for override may be installed — the "
        "filter must be a per-call local copy inside the router."
    )
    # And the surface the provider saw was filtered to the whitelist (empty
    # here, since the test ToolEngine has no 'some_nonexistent_tool').
    assert client.seen_tools
    names = {t.get("name") for t in client.seen_tools[0] if isinstance(t, dict)}
    assert "some_nonexistent_tool" not in names


def test_complete_with_tools_node_does_not_monkeypatch_engine():
    """Code-shape guard: the workflow node must NOT reassign
    ctx.tool_engine.tool_schemas_for — it routes the whitelist through the
    router's per-call allowed_tool_names instead."""
    src = (APP / "workflows" / "nodes" / "llm.py").read_text(encoding="utf-8")
    assert "ctx.tool_engine.tool_schemas_for =" not in src, (
        "the complete_with_tools node must not mutate the shared ToolEngine; "
        "pass allowed_tool_names to the router instead."
    )
    assert "allowed_tool_names" in src, (
        "the node must forward its whitelist via the router's "
        "allowed_tool_names per-call filter."
    )


def test_complete_signature_accepts_sampling_and_whitelist():
    """complete() must accept the new optional kwargs (back-compat additive)."""
    import inspect
    from llm_router import LLMRouter
    params = inspect.signature(LLMRouter.complete).parameters
    for p in ("temperature", "max_tokens", "allowed_tool_names"):
        assert p in params, f"complete() must accept {p}"
        assert params[p].default is None, f"{p} must default to None (back-compat)"
