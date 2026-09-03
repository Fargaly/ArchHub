"""AgDR-0042 — bridge slots that expose MemoryGraph to JSX.

Mirrors the pattern used by test_bridge_agdr0041_slots: instantiate
the bridge with a real ToolEngine, call the slot like any method,
verify JSON envelope shape.
"""
from __future__ import annotations

import json
import sys
import time
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


# AgDR-0036 follow-up — memory_query + memory_stats are now ASYNC via
# `_cached_async`: the slot returns the cached value INSTANTLY (an empty
# placeholder on a cold cache) and recomputes on the background pool,
# emitting `memory_changed` when fresh data lands. SQLite + the
# brain.health HTTP call run ONLY on the worker — never the Qt main
# thread. This helper re-calls the slot (cheap, microseconds when warm)
# until `pred` is satisfied, mirroring how the JSX re-pulls on the
# `memory_changed` signal. It lets the assertions test the SAME real
# data the slot used to return synchronously.
def _poll_slot(call, pred, timeout=6.0):
    deadline = time.time() + timeout
    out = json.loads(call())
    while time.time() < deadline and not pred(out):
        time.sleep(0.02)
        out = json.loads(call())
    return out


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
    out = _poll_slot(
        lambda: bridge_inst.memory_query(json.dumps({
            "question": "comfyui render", "limit": 5,
        })),
        lambda o: o.get("count", 0) > 0)
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
    # Poll until the off-thread query lands a kind-filtered result set.
    out = _poll_slot(
        lambda: bridge_inst.memory_query(json.dumps({
            "question": "revit hero", "kinds": ["skill"], "limit": 3,
        })),
        lambda o: o.get("status") == "ok" and o.get("count", 0) > 0)
    assert out["status"] == "ok"
    for r in out["results"]:
        assert r["kind"] == "skill"


# ── memory_stats slot ────────────────────────────────────────────────


def test_memory_stats_empty_graph(bridge_inst, monkeypatch):
    """Empty store → all-zero stats.

    Post ONE-SYSTEM unify (docs/audits/brain-unify-design-2026-05-28.md)
    `memory_stats` reads its canonical counts from the brain daemon
    (`brain.health`), NOT from graph.sqlite. The daemon is a SEPARATE
    process, so pointing LOCALAPPDATA/XDG at a tmp dir (which the fixture
    does) only isolates the staging graph — it does NOT empty the daemon.
    To genuinely test the "empty store → 0" contract we must isolate the
    canonical store too: stub the daemon health to an EMPTY store. This
    keeps the test deterministic AND off the user's real ~/AppData
    brain.db (which carries hundreds of real facts), instead of asserting
    against whatever the live daemon happens to hold.
    """
    # Stub accepts the new optional `timeout` kwarg the worker passes.
    monkeypatch.setattr(
        bridge_inst, "_brain_tool",
        lambda tool, args, timeout=4.0: {"ok": True, "facts": 0,
                                         "skills": 0, "db_path": None},
    )
    # memory_stats is async (_cached_async): poll past the cold-cache
    # 'pending' placeholder until the worker lands the real snapshot.
    out = _poll_slot(lambda: bridge_inst.memory_stats(),
                     lambda o: o.get("source") not in (None, "pending"))
    assert out["status"] == "ok"
    assert out["source"] == "brain.db"  # canonical path, empty store
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
    # Daemon may be down on CI → source 'brain.db' or 'graph.sqlite';
    # either way the staging-graph counts are populated. Poll past the
    # cold-cache placeholder until real counts land.
    out = _poll_slot(lambda: bridge_inst.memory_stats(),
                     lambda o: o.get("total_nodes", 0) > 0)
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
