"""Plan-mode WRITE GATE — IA fix (ia-critique-ai-stemcells-2026-06-03 §4:
"The chip says 'all writes gated.' Nothing reads it.").

This is the backend half the dead Plan/Auto/YOLO chip never had. The
USER-AGENCY mandate: Plan (default) gates host writes pending approval,
Auto auto-runs reads but gates writes, YOLO runs free.

Pins:
  * `run_agent_step(mode="plan")` REFUSES a host-write tool — the write
    does NOT become an executable action; it becomes a typed
    `approval_required` action with named recoveries, and `gated` counts it.
  * READ tools (query_graph / chat) pass through in EVERY mode.
  * Auto gates writes too (only auto-runs reads).
  * YOLO runs the write (no gate).
  * Unknown / empty mode fails SAFE to Plan (gated).
  * The gate predicates (`mode_gates_write`, `gated_action`,
    `normalize_mode`) behave as documented.

No real LLM: a fake router drives `on_tool_invocation` with a duck-typed
invocation, exactly as llm_router does after a provider tool call.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from agents.composer_agent import (  # noqa: E402
    run_agent_step, mode_gates_write, gated_action, normalize_mode,
    WRITE_TOOLS, READ_TOOLS, MODE_PLAN, MODE_AUTO, MODE_YOLO,
)


# ─── Fakes ───────────────────────────────────────────────────────────


class _Inv:
    """Duck-typed ToolInvocation (matches llm_router's real attrs)."""
    def __init__(self, tool_name, arguments=None, result=None, status="ok"):
        self.tool_name = tool_name
        self.arguments = arguments or {}
        self.result = result
        self.status = status


class _Resp:
    def __init__(self, text=""):
        self.text = text
        self.model = "fake"


class _FakeRouter:
    """Calls on_tool_invocation with a scripted set of invocations, then
    returns a text response — the same callback contract run_agent_step
    relies on."""
    def __init__(self, invocations):
        self._invocations = invocations
        self.seen_kwargs = None

    def complete(self, **kwargs):
        self.seen_kwargs = kwargs
        cb = kwargs.get("on_tool_invocation")
        if cb:
            for inv in self._invocations:
                cb(inv)
        return _Resp(text="done")


# ─── 1. Plan mode REFUSES a write ────────────────────────────────────


def test_plan_mode_gates_a_write_tool():
    router = _FakeRouter([_Inv("run_node", {"node_id": "n1"})])
    out = run_agent_step(user_msg="cook it", graph={}, router=router,
                         mode="plan")
    assert out["mode"] == "plan"
    assert out["gated"] == 1, out
    assert len(out["actions"]) == 1
    act = out["actions"][0]
    # The write did NOT execute — it became a typed approval surface.
    assert act.get("gated") is True
    assert act["tool"] == "run_node"
    assert act["approval"]["type"] == "approval_required"
    # Named recoveries (typed, not freeform) — the USER-AGENCY contract.
    rec_ids = {r["id"] for r in act["approval"]["recoveries"]}
    assert {"approve_once", "switch_auto", "switch_yolo", "discard"} <= rec_ids


def test_plan_mode_gates_every_write_tool():
    """All five canvas-mutation primitives are gated in plan mode."""
    invs = [_Inv(name, {}) for name in sorted(WRITE_TOOLS)]
    router = _FakeRouter(invs)
    out = run_agent_step(user_msg="do stuff", graph={}, router=router,
                         mode="plan")
    assert out["gated"] == len(WRITE_TOOLS)
    assert all(a.get("gated") for a in out["actions"])


def test_plan_mode_is_the_default():
    """No mode arg → Plan → writes gated (fail-safe)."""
    router = _FakeRouter([_Inv("set_node_param", {"node_id": "n", "key": "k", "value": 1})])
    out = run_agent_step(user_msg="set it", graph={}, router=router)
    assert out["mode"] == "plan"
    assert out["gated"] == 1
    assert out["actions"][0].get("gated") is True


# ─── 2. Reads pass through in every mode ──────────────────────────────


@pytest.mark.parametrize("mode", [MODE_PLAN, MODE_AUTO, MODE_YOLO])
def test_read_tools_never_gated(mode):
    router = _FakeRouter([_Inv("query_graph", {}), _Inv("chat", {"text": "hi"})])
    out = run_agent_step(user_msg="look", graph={}, router=router, mode=mode)
    assert out["gated"] == 0
    assert len(out["actions"]) == 2
    assert all(not a.get("gated") for a in out["actions"])


# ─── 3. Auto gates writes; YOLO runs them ────────────────────────────


def test_auto_mode_still_gates_writes():
    router = _FakeRouter([_Inv("run_workflow", {})])
    out = run_agent_step(user_msg="run all", graph={}, router=router,
                         mode="auto")
    assert out["mode"] == "auto"
    assert out["gated"] == 1
    assert out["actions"][0].get("gated") is True


def test_yolo_mode_runs_writes_ungated():
    router = _FakeRouter([_Inv("run_node", {"node_id": "n1"},
                               result={"node_id": "n1", "ok": True})])
    out = run_agent_step(user_msg="just do it", graph={}, router=router,
                         mode="yolo")
    assert out["mode"] == "yolo"
    assert out["gated"] == 0
    act = out["actions"][0]
    assert not act.get("gated")
    assert act["tool"] == "run_node"
    # The real result is surfaced (the write actually ran).
    assert act["result"] == {"node_id": "n1", "ok": True}


# ─── 4. unknown / empty mode fails SAFE to plan ──────────────────────


@pytest.mark.parametrize("mode", ["", "  ", "nonsense", None, "PLAN", "Yolo"])
def test_unknown_mode_normalizes(mode):
    n = normalize_mode(mode)
    assert n in (MODE_PLAN, MODE_AUTO, MODE_YOLO)


def test_unknown_mode_gates_writes_failsafe():
    router = _FakeRouter([_Inv("add_wire", {"src_node": "a", "src_port": "o",
                                            "dst_node": "b", "dst_port": "i"})])
    out = run_agent_step(user_msg="wire", graph={}, router=router,
                         mode="garbage")
    # Garbage mode → plan → gated.
    assert out["mode"] == "plan"
    assert out["gated"] == 1


# ─── 5. predicate-level checks ───────────────────────────────────────


def test_mode_gates_write_predicate():
    assert mode_gates_write("plan", "run_node") is True
    assert mode_gates_write("auto", "run_node") is True
    assert mode_gates_write("yolo", "run_node") is False
    # Reads never gated.
    assert mode_gates_write("plan", "query_graph") is False
    assert mode_gates_write("plan", "chat") is False


def test_write_and_read_tool_sets_are_disjoint():
    assert WRITE_TOOLS.isdisjoint(READ_TOOLS)


def test_gated_action_shape():
    act = gated_action("run_node", {"node_id": "n1"}, "plan")
    assert act["gated"] is True
    assert act["tool"] == "run_node"
    assert act["args"] == {"node_id": "n1"}
    assert act["result"] is None          # the write did not run
    assert act["mode"] == "plan"
    assert act["approval"]["tool"] == "run_node"
    assert isinstance(act["approval"]["recoveries"], list)
    assert act["approval"]["recoveries"]  # non-empty


def test_no_router_returns_mode_and_zero_gated():
    out = run_agent_step(user_msg="x", graph={}, router=None, mode="plan")
    assert out["error"] == "missing_dep"
    assert out["mode"] == "plan"
    assert out["gated"] == 0
