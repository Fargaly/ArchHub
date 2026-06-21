"""Ambient self-build ("stem cells grow as you work") — Phase 4 REGRESSION GUARD.

The ambient layer must:
  (1) REUSE composer_agent.run_agent_step (ONE-SYSTEM) — not a parallel engine.
  (2) In PLAN mode (default) NOT auto-apply: every proposed host/graph WRITE
      comes back GATED (typed approval_required) — a ghost proposal the user
      accepts/dismisses, never an executed mutation.
  (3) Cap proposals per pass (runaway-loop guard) — at most AMBIENT_MAX_PROPOSALS
      write actions survive however many the model emits.
  (4) Tag the pass + every action `ambient` so the JSX surfaces them as growth.
  (5) In YOLO, proposals come back ungated (apply through the replay path).

All proven WITHOUT a live model via a recording router double, exactly like
tests/test_composer_tool_surface.py.
"""
from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _load(name: str, rel: str):
    """Path-load an app/agents module under a non-colliding name (the repo has
    TWO `agents` packages — app/agents and repo-root agents — so a plain import
    flakes by collection order; see test_composer_tool_surface)."""
    spec = _ilu.spec_from_file_location(name, str(APP / rel))
    mod = _ilu.module_from_spec(spec)
    # Register so ambient_grow's `from agents.composer_agent import ...` and its
    # `from composer_agent import ...` fallback both resolve to the app copy.
    sys.modules.setdefault("composer_agent", _load_composer())
    spec.loader.exec_module(mod)
    return mod


def _load_composer():
    if "composer_agent" in sys.modules:
        return sys.modules["composer_agent"]
    spec = _ilu.spec_from_file_location(
        "composer_agent", str(APP / "agents" / "composer_agent.py"))
    mod = _ilu.module_from_spec(spec)
    sys.modules["composer_agent"] = mod
    spec.loader.exec_module(mod)
    return mod


_CA = _load_composer()
_AG = _load("_app_agents_ambient_grow", "agents/ambient_grow.py")

from tool_engine import ToolInvocation  # noqa: E402


class _ProposerRouter:
    """Duck-typed router that emulates the model proposing N spawn_node writes
    in one turn — used to prove the cap + the gate + the tags. `n` controls how
    many writes the 'model' emits."""

    def __init__(self, n=2):
        self.n = n
        self.calls = []

    def complete(self, *, history, model, on_chunk=None,
                 on_tool_invocation=None, **kwargs):
        self.calls.append({"history": history})
        if on_tool_invocation is not None:
            for i in range(self.n):
                on_tool_invocation(ToolInvocation(
                    id=f"inv-{i}", tool_name="spawn_node",
                    arguments={"family": "revit", "title": f"Walls{i}",
                               "node_id": f"ng:ai_chat:dead000{i}"},
                    status="ok",
                    result={"status": "ok", "accepted": True,
                            "node_id": f"ng:ai_chat:dead000{i}"}))
        if on_chunk is not None:
            on_chunk("proposing next nodes")

        class _Resp:
            text = "proposing next nodes"
            tool_invocations: list = []
        return _Resp()


def _graph():
    return {"nodes": [{"id": "n1", "title": "Revit"}], "wires": []}


# ── (1) ONE-SYSTEM — the ambient pass routes through run_agent_step ──────────
def test_ambient_reuses_composer_agent_not_a_new_engine():
    src = (APP / "agents" / "ambient_grow.py").read_text(encoding="utf-8")
    assert "run_agent_step" in src, (
        "ambient_grow MUST reuse composer_agent.run_agent_step — ONE-SYSTEM, "
        "no parallel engine."
    )
    # And it actually calls the router exactly once (one composer turn).
    r = _ProposerRouter(n=1)
    _AG.run_ambient_grow(graph=_graph(), router=r, mode="yolo")
    assert len(r.calls) == 1


def test_ambient_prompt_is_a_grow_nudge_not_a_question():
    p = _AG.ambient_prompt(last_turn="added walls", brain_facts="prefers PDF")
    assert "AMBIENT GROW PASS" in p
    assert "NEXT 1 to 3" in p
    assert "added walls" in p and "prefers PDF" in p


# ── (2) PLAN MODE DOES NOT AUTO-APPLY — proposals come back GATED ────────────
def test_plan_mode_does_not_auto_apply_proposals_are_gated():
    out = _AG.run_ambient_grow(graph=_graph(), router=_ProposerRouter(n=2),
                               mode="plan")
    assert out["ambient"] is True
    assert out["actions"], "a proposal should have been produced"
    for a in out["actions"]:
        # Every proposed WRITE is gated in Plan mode — NOT an executable action.
        assert a.get("gated") is True, (
            "Plan mode must GATE every proposed write — ghost proposal, never "
            "auto-applied."
        )
        assert a["approval"]["type"] == "approval_required"
        # A gated action carries NO executable result (the write didn't run).
        assert a.get("result") is None
    assert out["gated"] == len(out["actions"])


# ── (3) PROPOSAL CAP — runaway-loop guard ───────────────────────────────────
def test_proposals_are_capped():
    assert _AG.AMBIENT_MAX_PROPOSALS == 3
    # The model 'emits' 7 writes; the cap must trim to AMBIENT_MAX_PROPOSALS.
    out = _AG.run_ambient_grow(graph=_graph(), router=_ProposerRouter(n=7),
                               mode="plan")
    writes = [a for a in out["actions"]
              if a.get("gated") or a.get("tool") in _CA.WRITE_TOOLS]
    assert len(writes) <= _AG.AMBIENT_MAX_PROPOSALS, (
        "ambient pass must cap proposed writes — no runaway self-construction."
    )


def test_proposal_cap_is_overridable_lower():
    out = _AG.run_ambient_grow(graph=_graph(), router=_ProposerRouter(n=5),
                               mode="plan", max_proposals=1)
    writes = [a for a in out["actions"]
              if a.get("gated") or a.get("tool") in _CA.WRITE_TOOLS]
    assert len(writes) == 1


# ── (4) AMBIENT TAGS — surfaced as growth ───────────────────────────────────
def test_actions_and_envelope_tagged_ambient():
    out = _AG.run_ambient_grow(graph=_graph(), router=_ProposerRouter(n=2),
                               mode="yolo")
    assert out["ambient"] is True
    assert out["actions"]
    assert all(a.get("ambient") is True for a in out["actions"]), (
        "each ambient action must be tagged so the approval queue labels it "
        "as proposed growth."
    )


# ── (5) YOLO — proposals ungated (apply through the replay path) ─────────────
def test_yolo_mode_proposals_are_not_gated():
    out = _AG.run_ambient_grow(graph=_graph(), router=_ProposerRouter(n=2),
                               mode="yolo")
    for a in out["actions"]:
        assert not a.get("gated"), "YOLO must not gate — proposals apply."
        assert a["tool"] == "spawn_node"
    assert out["gated"] == 0


# ── Defensive: no router → safe envelope, no crash ──────────────────────────
def test_no_router_returns_safe_envelope():
    out = _AG.run_ambient_grow(graph=_graph(), router=None, mode="plan")
    assert out["actions"] == []
    assert out["ambient"] is True
    assert out.get("error") == "missing_dep"
