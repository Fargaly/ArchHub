"""X-MODE IS REAL — regression tests for the 2026-07-02 forensic-audit defect.

CONFIRMED defect (now fixed, these tests are the audit's attack scripts turned
assertions): the composer X-mode path (bridge self_extend_loop →
run_self_extend_loop → atomize_vision) IGNORED user_msg entirely and returned a
fixed 3-leaf hello_marker.py decomposition; _materialize_default_marker then
owned every leaf so the router/LLM was never consulted; the court greened a
sentinel the executor itself wrote — 'add Airtable support' produced
hello_marker.py.

Proven here:
  DECOMPOSE   a stubbed router returning a fixed plan → 'add a SketchUp
              connector' produces a create_connector leaf whose gate targets
              app/connectors/sketchup_connector.py (py_compile).
  REAL BUILD  the loop routes that leaf through the SAME machinery as
              run_self_extend (build_artifact → connectors.scaffold) — the
              connector file really lands on disk and the court greens the
              REAL artifact.
  NO MARKER   hello_marker.py is NEVER written for any ask — file absent and
              no write_file action for it (the materializer refuses any path
              not under a dir literally named self_extend_test_fixture).
  HONEST EXIT router=None → ONE gate_kind='manual' leaf, court escalates
              needs_root; the loop reports NOT green and learns nothing.
  LEARN REAL  the green-leaf brain fragment describes the REAL artifact
              (capability + path), never a marker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _ROOT / "personal-brain-mcp" / "src"
if str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))

pytest.importorskip("pydantic")
pytest.importorskip("personal_brain.roma")

from agents import composer_agent          # noqa: E402
from agents import self_extend             # noqa: E402
from connectors import scaffold            # noqa: E402


def _store():
    from personal_brain.storage import BrainStore
    return BrainStore.open(":memory:")


def _validating_brain_call(captured):
    """brain.write stand-in that VALIDATES each op against the REAL WriteOp
    schema (a malformed learn op fails the test, never silently passes)."""
    from personal_brain.models import WriteOp

    def _call(tool, args):
        captured.append((tool, args))
        if tool == "brain.write":
            for op in args.get("ops", []):
                WriteOp.model_validate(op)
            return {"ops_applied": len(args.get("ops", []))}
        return {"ok": True}

    return _call


# The fixed decomposition the stub router returns — what a real model would
# emit through the strict propose_build_plan tool for a SketchUp ask.
_SKETCHUP_PLAN = {
    "leaves": [{
        "tool": "create_connector",
        "title": "SketchUp connector",
        "args": {"host": "SketchUp", "label": "SketchUp",
                 "operations": [{"op_id": "list_components", "kind": "read",
                                 "label": "List components"}]},
    }],
}


class _PlanRouter:
    """Stub router: emits a fixed decomposition through the SAME
    on_tool_invocation/extra_tools surface llm_router.complete exposes.
    plan=None → no tool call, only freeform `text` (the garbage case)."""

    def __init__(self, plan=None, text=""):
        self.plan = plan
        self.text = text
        self.calls = []

    def complete(self, history=None, model="auto", on_chunk=None,
                 on_tool_invocation=None, extra_tools=None, **kw):
        self.calls.append({"history": history, "model": model,
                           "extra_tools": extra_tools})
        out = self.text
        if self.plan is not None:
            if on_tool_invocation is not None:
                on_tool_invocation(SimpleNamespace(
                    tool_name="propose_build_plan", arguments=self.plan))
            out = json.dumps(self.plan)
        if on_chunk and out:
            on_chunk(out)
        return SimpleNamespace(text=out)


@pytest.fixture(autouse=True)
def _jail_appdata(tmp_path, monkeypatch):
    """Jail %APPDATA% so the OLD marker path, were it ever written again, lands
    in tmp where we can assert its ABSENCE — never the founder's profile."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield


@pytest.fixture
def _clean_sketchup():
    path = scaffold.connector_path("sketchup")
    if path.exists():
        path.unlink()
    yield path
    if path.exists():
        path.unlink()


def _default_marker() -> Path:
    return Path(composer_agent._appdata_self_extend_dir()) / "hello_marker.py"


# ── DECOMPOSE — the router (not a fixed marker plan) decides the leaves ──────


def test_sketchup_ask_decomposes_to_create_connector_leaf():
    router = _PlanRouter(plan=_SKETCHUP_PLAN)
    leaves = composer_agent.atomize_vision("add a SketchUp connector",
                                           router=router)
    assert len(leaves) == 1
    leaf = leaves[0]
    # The gate targets the REAL artifact the build tool writes.
    assert leaf["gate_kind"] == "py_compile"
    assert leaf["gate_spec"]["path"] == "app/connectors/sketchup_connector.py"
    # The build routing rides the leaf so the loop uses the proven machinery.
    assert leaf["gate_spec"]["build_tool"] == "create_connector"
    assert leaf["gate_spec"]["build_args"]["host"] == "SketchUp"
    # No marker anywhere in the plan.
    assert "hello_marker" not in json.dumps(leaves)


def test_decompose_call_uses_strict_json_tool_schema():
    router = _PlanRouter(plan=_SKETCHUP_PLAN)
    composer_agent.atomize_vision("add a SketchUp connector", router=router)
    assert len(router.calls) == 1
    sent = router.calls[0]["extra_tools"]
    assert [t["name"] for t in sent] == ["propose_build_plan"]
    leaves_schema = sent[0]["input_schema"]["properties"]["leaves"]
    assert leaves_schema["minItems"] == 1 and leaves_schema["maxItems"] == 4
    assert set(leaves_schema["items"]["properties"]["tool"]["enum"]) == {
        "create_connector", "create_node_type", "create_ui_widget"}
    # The router saw the USER'S ACTUAL ask (the old path never called it).
    hist = router.calls[0]["history"]
    assert any("SketchUp connector" in (m.get("content") or "")
               for m in hist if m.get("role") == "user")


def test_node_type_and_widget_proposals_map_to_their_gates():
    plan = {"leaves": [
        {"tool": "create_node_type",
         "args": {"type": "x.area_sum", "description": "sum areas"}},
        {"tool": "create_ui_widget",
         "args": {"id": "co2_panel", "code": "return React.createElement('div');"}},
    ]}
    leaves = composer_agent.atomize_vision("add area sum + a co2 panel",
                                           router=_PlanRouter(plan=plan))
    assert [l["gate_kind"] for l in leaves] == ["node_cooks", "ui_renders"]
    assert leaves[0]["gate_spec"]["type"] == "x.area_sum"
    assert leaves[1]["gate_spec"]["widget_id"] == "co2_panel"
    assert leaves[1]["gate_spec"]["testid"] == "agent-widget-co2_panel"


def test_garbage_plan_falls_back_to_one_manual_leaf():
    # Freeform prose, no tool call, no parseable JSON → honest manual leaf.
    leaves = composer_agent.atomize_vision(
        "add a SketchUp connector",
        router=_PlanRouter(plan=None, text="Sure! I would love to help."))
    assert len(leaves) == 1
    assert leaves[0]["gate_kind"] == "manual"
    # Unknown tool names are dropped, → manual too (never an invented build).
    leaves2 = composer_agent.atomize_vision(
        "wipe the disk",
        router=_PlanRouter(plan={"leaves": [{"tool": "rm_rf", "args": {}}]}))
    assert len(leaves2) == 1 and leaves2[0]["gate_kind"] == "manual"


# ── REAL BUILD + NO MARKER — the loop end-to-end on the stubbed plan ─────────


def test_loop_builds_real_connector_never_the_marker(tmp_path, _clean_sketchup):
    conn = _clean_sketchup
    captured = []
    out = self_extend.run_self_extend_loop(
        "add a SketchUp connector",
        graph={"nodes": [], "wires": []},
        router=_PlanRouter(plan=_SKETCHUP_PLAN),
        brain_call=_validating_brain_call(captured),
        store=_store(),
    )
    # The REAL artifact landed where the gate points; the court greened IT.
    assert conn.exists(), "the SketchUp connector file was not written"
    assert out["ok"] is True and out["dry"] is True
    leaf_rows = [p for p in out["leaves"] if not p["terminal"]]
    assert len(leaf_rows) == 1
    assert leaf_rows[0]["verdict"] == "green"
    assert leaf_rows[0]["evidence_ref"]
    # Payload keys unchanged (the UI panel reads them) + Undo path is REAL.
    assert {"tree_id", "leaf_id", "predicate", "verdict", "reason",
            "evidence_ref", "sweep", "learned", "artifact_path",
            "terminal"} <= set(leaf_rows[0])
    assert leaf_rows[0]["artifact_path"].replace("\\", "/").endswith(
        "app/connectors/sketchup_connector.py")
    # hello_marker.py was NEVER written — not at the old default path, not
    # anywhere under the jailed profile.
    assert not _default_marker().exists()
    assert list(tmp_path.rglob("hello_marker.py")) == []
    # LEARN REAL — the fragment names the REAL artifact, never a marker.
    writes = [a for (t, a) in captured if t == "brain.write"]
    assert len(writes) == 1
    frag = writes[0]["ops"][0]["fragment"]
    text = frag["text"].replace("\\", "/")
    assert "connector 'sketchup'" in text
    assert "sketchup_connector.py" in text
    assert "marker" not in text.lower()
    assert leaf_rows[0]["learned"] is True


def test_materializer_refuses_everything_but_the_test_fixture_dir(tmp_path):
    # The OLD guard ('self_extend' anywhere in the path) let the executor green
    # its own sentinel. Now: a self_extend dir is NOT enough...
    outside = tmp_path / "self_extend" / "hello_marker.py"
    res = self_extend._materialize_default_marker({"path": str(outside)})
    assert res["actions"] == []
    assert not outside.exists(), "materializer must not write outside the fixture dir"
    # ...only a dir literally named self_extend_test_fixture is owned.
    inside = tmp_path / "self_extend_test_fixture" / "proof_marker.py"
    res2 = self_extend._materialize_default_marker({"path": str(inside)})
    assert inside.exists()
    assert any(a.get("tool") == "write_file" for a in res2["actions"])


# ── HONEST EXIT — no router → manual leaf → needs_root, never a fake green ──


def test_router_none_is_honest_needs_root():
    leaves = composer_agent.atomize_vision("add Airtable support", router=None)
    assert len(leaves) == 1
    assert leaves[0]["gate_kind"] == "manual"
    assert "cannot decompose without a model" in leaves[0]["predicate"]

    captured = []
    out = self_extend.run_self_extend_loop(
        "add Airtable support",
        graph={"nodes": [], "wires": []},
        router=None,
        brain_call=lambda t, a: (captured.append((t, a)) or {"ops_applied": 1}),
        store=_store(),
    )
    # NOT green: the loop surfaces needs_root honestly (dry=False, ok=False).
    assert out["ok"] is False and out["dry"] is False
    leaf_rows = [p for p in out["leaves"] if not p["terminal"]]
    assert leaf_rows and all(p["verdict"] == "needs_root" for p in leaf_rows)
    assert out["leaves"][-1]["terminal"] is True
    assert out["leaves"][-1]["verdict"] == "needs_root"
    # Nothing fabricated, nothing learned.
    assert not _default_marker().exists()
    assert [t for (t, a) in captured if t == "brain.write"] == []


def test_airtable_ask_no_router_never_writes_hello_marker(tmp_path):
    # The audit's literal reproduction: 'add Airtable support' used to produce
    # hello_marker.py. It must NEVER again — for ANY ask, router or not.
    for ask in ("add Airtable support", "add a hello marker file",
                "self-extend yourself"):
        out = self_extend.run_self_extend_loop(
            ask, graph={"nodes": [], "wires": []}, router=None,
            brain_call=lambda t, a: {"ops_applied": 1}, store=_store(),
        )
        assert out["ok"] is False
    assert not _default_marker().exists()
    assert list(tmp_path.rglob("hello_marker.py")) == []
