"""AgDR-0042 slice 2/6 — Library + Composer-turn extractors.

Each extractor is a pure function that writes nodes/edges into a
fresh MemoryGraph. Tests use in-memory graphs and per-test temp dirs
so they never touch the real on-disk plan history.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import MemoryGraph, Confidence  # noqa: E402
from memory.extractors import extract_library, extract_turns  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def g():
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


# ──────────────────────────────────────────────────────────────────────
#  LIBRARY EXTRACTOR
# ──────────────────────────────────────────────────────────────────────


def test_extract_library_emits_capability_nodes(g):
    """Registry-backed primitives (data.constant, render.comfyui, etc.)
    show up as kind=capability with lib:cap:<type> id."""
    stats = extract_library(g, infer_wires=False)
    assert stats["caps"] > 0
    caps = g.all_nodes(kind="capability")
    cap_ids = {c.id for c in caps}
    # Spot-check a few registry types we know ship in workflows.nodes.*
    for t in ("data.constant", "render.comfyui", "host.import_mesh"):
        assert f"lib:cap:{t}" in cap_ids, f"{t} missing from extracted caps"


def test_extract_library_emits_skill_nodes(g):
    """Library Skills (impl.kind=graph composites) show up as
    kind=skill with lib:skill:<type> id."""
    extract_library(g, infer_wires=False)
    skills = g.all_nodes(kind="skill")
    skill_ids = {s.id for s in skills}
    # The 3 shipped Skills auto-register on workflows import — they
    # should all appear in the extracted graph.
    for t in ("skill.revit_hero_render", "skill.photo_to_rhino_mass",
              "skill.drone_to_revit_walls"):
        assert f"lib:skill:{t}" in skill_ids, f"{t} missing from skills"


def test_extract_library_emits_contains_edges_for_skill_inner_nodes(g):
    """Each inner node inside a Skill's impl.graph should produce one
    `contains` edge from the skill → the capability of that type."""
    extract_library(g, infer_wires=False)
    contains = g.all_edges(relation="contains")
    assert len(contains) > 0
    # revit_hero_render contains viewport (host.export_viewport),
    # comfy (render.comfyui), upscale (render.image_edit), poll
    # (render.task_poll), out (output.parameter) — at least 3 of those
    # caps exist in the registry.
    sources = {e.source for e in contains}
    assert "lib:skill:skill.revit_hero_render" in sources
    targets_for_skill = {e.target for e in contains
                         if e.source == "lib:skill:skill.revit_hero_render"}
    assert any(t in targets_for_skill for t in (
        "lib:cap:render.comfyui",
        "lib:cap:render.image_edit",
        "lib:cap:host.export_viewport",
    )), f"no recognised inner caps in {targets_for_skill}"


def test_extract_library_contains_edges_are_extracted_confidence(g):
    extract_library(g, infer_wires=False)
    for e in g.all_edges(relation="contains"):
        assert e.confidence == Confidence.EXTRACTED


def test_extract_library_wires_with_off_skips_inferred(g):
    extract_library(g, infer_wires=False)
    assert g.count_edges(relation="wires_with") == 0


def test_extract_library_wires_with_on_emits_inferred(g):
    extract_library(g, infer_wires=True)
    wires = g.all_edges(relation="wires_with")
    assert len(wires) > 0, "wires_with edges should land when infer_wires=True"
    for e in wires:
        assert e.confidence == Confidence.INFERRED
    # Spot-check: vision.describe outputs string; llm.qwen takes
    # string `prompt` — so vision.describe → llm.qwen should appear.
    pairs = {(e.source, e.target) for e in wires}
    assert ("lib:cap:vision.describe", "lib:cap:llm.qwen") in pairs


def test_extract_library_skips_any_to_any_wires(g):
    extract_library(g, infer_wires=True)
    # ANY ports would link every node → every node (combinatorial
    # explosion). Verify no wires_with carries port_type='any'.
    for e in g.all_edges(relation="wires_with"):
        assert e.props.get("port_type") != "any"


def test_extract_library_is_idempotent(g):
    """Re-running on the same library yields the same counts (upserts,
    not duplicates)."""
    stats1 = extract_library(g, infer_wires=True)
    nodes1 = g.count_nodes()
    edges1 = g.count_edges()
    stats2 = extract_library(g, infer_wires=True)
    assert g.count_nodes() == nodes1, (
        f"node count drifted: {nodes1} → {g.count_nodes()}")
    assert g.count_edges() == edges1, (
        f"edge count drifted: {edges1} → {g.count_edges()}")
    assert stats1["nodes_added"] == stats2["nodes_added"]


def test_extract_library_does_not_emit_self_wires(g):
    extract_library(g, infer_wires=True)
    for e in g.all_edges(relation="wires_with"):
        assert e.source != e.target


# ──────────────────────────────────────────────────────────────────────
#  COMPOSER-TURN EXTRACTOR
# ──────────────────────────────────────────────────────────────────────


def _write_plan(project_dir: Path, plan_id: str, record: dict) -> Path:
    """Write a fake ai.plan record under project_dir/.archhub/plans/."""
    plans = project_dir / ".archhub" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    p = plans / f"{plan_id}.json"
    p.write_text(json.dumps(record), encoding="utf-8")
    return p


def test_extract_turns_no_plans_dir_returns_zero(g, tmp_path):
    stats = extract_turns(g, tmp_path)
    assert stats == {"turns_added": 0, "tools_added": 0,
                      "called_edges": 0, "used_edges": 0}


def test_extract_turns_emits_turn_node(g, tmp_path):
    _write_plan(tmp_path, "abc123", {
        "plan_id": "abc123",
        "prompt": "Render the hero view",
        "model": "claude-sonnet-4-5",
        "status": "ok",
        "ts": 1716000000,
        "plan": [],
    })
    stats = extract_turns(g, tmp_path)
    assert stats["turns_added"] == 1
    turn = g.get_node("turn:abc123")
    assert turn is not None
    assert turn.kind == "turn"
    assert turn.props["model"] == "claude-sonnet-4-5"
    assert turn.props["status"] == "ok"


def test_extract_turns_emits_tool_nodes_and_called_edges(g, tmp_path):
    _write_plan(tmp_path, "p1", {
        "plan_id": "p1",
        "prompt": "do work",
        "model": "x",
        "status": "ok",
        "ts": 1,
        "plan": [
            {"tool": "render.comfyui", "args": {"workflow": "..."}},
            {"tool": "vision.describe", "args": {"image_url": "x"}},
            {"tool": "render.comfyui", "args": {"workflow": "..."}},  # repeat
        ],
    })
    stats = extract_turns(g, tmp_path)
    assert stats["tools_added"] == 2  # de-duped by name
    assert stats["called_edges"] == 3
    # The tool node exists with kind='tool'
    cf = g.get_node("tool:render.comfyui")
    assert cf is not None and cf.kind == "tool"
    # 3 called edges from this turn
    out = g.neighbors("turn:p1", direction="out", relation="called")
    assert len(out) == 2  # MemoryGraph dedupes by (source, target, relation)


def test_extract_turns_called_edges_carry_args_preview(g, tmp_path):
    _write_plan(tmp_path, "p2", {
        "plan_id": "p2",
        "prompt": "p", "model": "x", "status": "ok", "ts": 0,
        "plan": [{"tool": "render.comfyui", "args": {"workflow": {"complex": "obj"}}}],
    })
    extract_turns(g, tmp_path)
    edges = g.neighbors("turn:p2", direction="out", relation="called")
    assert len(edges) == 1
    assert "workflow" in edges[0].props["args_preview"]


def test_extract_turns_skips_corrupt_records(g, tmp_path):
    """Half-written JSON or missing plan_id shouldn't crash the run."""
    plans = tmp_path / ".archhub" / "plans"
    plans.mkdir(parents=True)
    (plans / "good.json").write_text(json.dumps({
        "plan_id": "good", "prompt": "p", "model": "x", "status": "ok",
        "ts": 0, "plan": [],
    }), encoding="utf-8")
    (plans / "bad.json").write_text("{not json", encoding="utf-8")
    (plans / "missing_id.json").write_text(json.dumps({"plan": []}),
                                             encoding="utf-8")
    stats = extract_turns(g, tmp_path)
    assert stats["turns_added"] == 1  # only the 'good' record landed


def test_extract_turns_skips_tmp_files(g, tmp_path):
    """ai.plan save uses atomic .tmp + rename — a .tmp shouldn't be
    picked up by the extractor."""
    plans = tmp_path / ".archhub" / "plans"
    plans.mkdir(parents=True)
    (plans / "real.json").write_text(json.dumps({
        "plan_id": "real", "prompt": "", "model": "", "status": "ok",
        "ts": 0, "plan": [],
    }), encoding="utf-8")
    (plans / "wip.tmp").write_text("{partial", encoding="utf-8")
    stats = extract_turns(g, tmp_path)
    assert stats["turns_added"] == 1


def test_extract_turns_used_edge_when_library_extracted_first(g, tmp_path):
    """When library extractor has populated lib:* nodes, a turn that
    called a known capability emits a `used` cross-source edge."""
    # First populate library so the cap exists.
    extract_library(g, infer_wires=False)
    assert g.get_node("lib:cap:render.comfyui") is not None
    # Then write a plan that used it.
    _write_plan(tmp_path, "u1", {
        "plan_id": "u1", "prompt": "", "model": "", "status": "ok",
        "ts": 0,
        "plan": [{"tool": "render.comfyui", "args": {}}],
    })
    extract_turns(g, tmp_path)
    used = g.neighbors("turn:u1", direction="out", relation="used")
    assert len(used) == 1
    assert used[0].target == "lib:cap:render.comfyui"


def test_extract_turns_skips_used_when_cap_unknown(g, tmp_path):
    """No library extraction → no `used` edge; the turn extractor
    silently skips rather than failing."""
    _write_plan(tmp_path, "u2", {
        "plan_id": "u2", "prompt": "", "model": "", "status": "ok",
        "ts": 0,
        "plan": [{"tool": "render.comfyui", "args": {}}],
    })
    extract_turns(g, tmp_path)
    # The turn + tool nodes land; the cross-source `used` edge does not.
    assert g.get_node("turn:u2") is not None
    assert g.count_edges(relation="used") == 0


def test_extract_turns_used_edge_prefers_skill_over_cap(g, tmp_path):
    """A plan calling `skill.revit_hero_render` should `used` the Skill
    node (lib:skill:…), not a hypothetical Capability of the same id."""
    extract_library(g, infer_wires=False)
    _write_plan(tmp_path, "u3", {
        "plan_id": "u3", "prompt": "", "model": "", "status": "ok",
        "ts": 0,
        "plan": [{"tool": "skill.revit_hero_render", "args": {}}],
    })
    extract_turns(g, tmp_path)
    used = g.neighbors("turn:u3", direction="out", relation="used")
    assert len(used) == 1
    assert used[0].target == "lib:skill:skill.revit_hero_render"


def test_extract_turns_is_idempotent(g, tmp_path):
    _write_plan(tmp_path, "i1", {
        "plan_id": "i1", "prompt": "p", "model": "x", "status": "ok",
        "ts": 0,
        "plan": [{"tool": "render.comfyui", "args": {}}],
    })
    extract_turns(g, tmp_path)
    nodes1 = g.count_nodes()
    edges1 = g.count_edges()
    extract_turns(g, tmp_path)
    assert g.count_nodes() == nodes1
    assert g.count_edges() == edges1
