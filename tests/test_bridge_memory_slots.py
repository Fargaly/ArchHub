"""AgDR-0042 — bridge slots that expose MemoryGraph to JSX.

Mirrors the pattern used by test_bridge_agdr0041_slots: instantiate
the bridge with a real ToolEngine, call the slot like any method,
verify JSON envelope shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402
from tool_engine import ToolEngine  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    engine = ToolEngine(manager=_StubManager())
    # auto_extract_memory=False — tests own when the graph gets
    # populated; the boot hook would race + violate empty-graph
    # assertions.
    return _bridge_module.ArchHubBridge(
        tools=engine, auto_extract_memory=False)


# ── memory_query slot ────────────────────────────────────────────────


def test_memory_query_returns_ok_on_empty_graph(bridge_inst):
    """Fresh install / no extractor run yet → tool returns empty
    result list cleanly (not an error)."""
    out = json.loads(bridge_inst.memory_query(json.dumps({
        "question": "revit wall",
    })))
    assert out["status"] == "ok"
    assert out["results"] == []
    assert out["count"] == 0


def test_memory_query_bad_json_errors(bridge_inst):
    out = json.loads(bridge_inst.memory_query("{not json"))
    assert out["status"] == "error"


def test_memory_query_missing_question_errors(bridge_inst):
    out = json.loads(bridge_inst.memory_query(json.dumps({})))
    assert out["status"] == "error"
    assert "question" in out["error"]


def test_memory_query_with_results_after_extraction(bridge_inst, tmp_path,
                                                       monkeypatch):
    """Populate the default graph + verify the slot surfaces hits."""
    from memory import MemoryGraph, default_graph_path
    from memory.extractors import extract_library
    g = MemoryGraph.open(default_graph_path())
    try:
        extract_library(g, infer_wires=False)
    finally:
        g.close()
    out = json.loads(bridge_inst.memory_query(json.dumps({
        "question": "comfyui render", "limit": 5,
    })))
    assert out["status"] == "ok"
    assert out["count"] > 0
    ids = [r["id"] for r in out["results"]]
    assert "lib:cap:render.comfyui" in ids


def test_memory_query_kinds_filter_through_bridge(bridge_inst, tmp_path,
                                                     monkeypatch):
    from memory import MemoryGraph, default_graph_path
    from memory.extractors import extract_library
    g = MemoryGraph.open(default_graph_path())
    try:
        extract_library(g, infer_wires=False)
    finally:
        g.close()
    out = json.loads(bridge_inst.memory_query(json.dumps({
        "question": "revit hero", "kinds": ["skill"], "limit": 3,
    })))
    assert out["status"] == "ok"
    for r in out["results"]:
        assert r["kind"] == "skill"


# ── memory_stats slot ────────────────────────────────────────────────


def test_memory_stats_empty_graph(bridge_inst):
    out = json.loads(bridge_inst.memory_stats())
    assert out["status"] == "ok"
    assert out["total_nodes"] == 0
    assert out["total_edges"] == 0
    assert out["communities_total"] == 0
    assert out["by_kind"]["capability"] == 0


def test_memory_stats_after_library_extract(bridge_inst, tmp_path,
                                                monkeypatch):
    from memory import MemoryGraph, default_graph_path
    from memory.extractors import extract_library
    g = MemoryGraph.open(default_graph_path())
    try:
        extract_library(g, infer_wires=False)
    finally:
        g.close()
    out = json.loads(bridge_inst.memory_stats())
    assert out["status"] == "ok"
    assert out["total_nodes"] > 0
    assert out["by_kind"]["capability"] > 0
    assert out["by_kind"]["skill"] >= 3  # the 3 shipped Skills
    assert len(out["communities_top"]) > 0


# ── slot reachability ────────────────────────────────────────────────


def test_slots_present_on_bridge(bridge_inst):
    for name in ("memory_query", "memory_stats"):
        assert hasattr(bridge_inst, name)
        assert callable(getattr(bridge_inst, name))


def test_tools_missing_returns_error(monkeypatch):
    b = _bridge_module.ArchHubBridge(tools=None, auto_extract_memory=False)
    out = json.loads(b.memory_query(json.dumps({"question": "x"})))
    assert out["status"] == "error"
    assert "tool engine" in out["error"]
