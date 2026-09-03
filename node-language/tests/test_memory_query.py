"""AgDR-0042 slice 3/6 — memory.query BFS + memory_query tool.

Covers:
  * tokenisation (stopwords, case, short tokens)
  * seed pass (token-overlap on label + key props)
  * BFS depth + edge-confidence weighting
  * kind filter + score filter + limit
  * neighbors_summary helper
  * tool_engine memory_query handler (envelope shape, error paths)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence, query, neighbors_summary,
)
from memory.extractors import extract_library, extract_turns  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def g():
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


@pytest.fixture
def realistic(g):
    """Library-seeded graph with a handful of revit-flavoured caps."""
    extract_library(g, infer_wires=False)
    return g


# ── tokenisation ─────────────────────────────────────────────────────


def test_query_empty_question_returns_empty(g):
    assert query(g, "") == []
    assert query(g, "  ") == []


def test_query_only_stopwords_returns_empty(g):
    # All tokens stripped → no seeds.
    g.add_node(MemoryNode(id="anything", kind="capability", label="x"))
    assert query(g, "the and or to of") == []


def test_query_finds_token_match_on_label(g):
    g.add_node(MemoryNode(id="rev1", kind="capability",
                           label="Revit wall reader"))
    g.add_node(MemoryNode(id="other", kind="capability",
                           label="AutoCAD layer"))
    hits = query(g, "revit wall")
    ids = [h["id"] for h in hits]
    assert "rev1" in ids
    assert "other" not in ids


def test_query_finds_token_match_on_props(g):
    g.add_node(MemoryNode(id="r", kind="capability",
                           label="Plain label",
                           props={"category": "host", "type": "host.read_walls"}))
    hits = query(g, "host walls")
    assert any(h["id"] == "r" for h in hits)


def test_query_is_case_insensitive(g):
    g.add_node(MemoryNode(id="r", kind="capability", label="REVIT thing"))
    assert any(h["id"] == "r" for h in query(g, "revit"))


# ── ranking ──────────────────────────────────────────────────────────


def test_query_more_token_overlap_ranks_higher(g):
    g.add_node(MemoryNode(id="weak",   kind="capability",
                           label="Revit drawing"))
    g.add_node(MemoryNode(id="strong", kind="capability",
                           label="Revit wall takeoff schedule"))
    hits = query(g, "revit wall takeoff")
    # strong matches 3 tokens; weak matches 1.
    assert hits[0]["id"] == "strong"
    assert hits[1]["id"] == "weak"


def test_query_respects_limit(g):
    for i in range(10):
        g.add_node(MemoryNode(id=f"x{i}", kind="capability",
                               label=f"revit thing {i}"))
    hits = query(g, "revit", limit=3)
    assert len(hits) == 3


def test_query_kinds_filter(g):
    g.add_node(MemoryNode(id="c1", kind="capability", label="revit wall"))
    g.add_node(MemoryNode(id="s1", kind="skill",      label="revit wall qto"))
    g.add_node(MemoryNode(id="t1", kind="turn",       label="revit wall job"))
    # Skills only.
    only_skills = query(g, "revit wall", kinds=("skill",))
    assert all(h["kind"] == "skill" for h in only_skills)
    # Skill + cap.
    skill_cap = query(g, "revit wall", kinds=("skill", "capability"))
    kinds = {h["kind"] for h in skill_cap}
    assert "skill" in kinds and "capability" in kinds
    assert "turn" not in kinds


def test_query_min_score_filter(g):
    g.add_node(MemoryNode(id="hi", kind="capability", label="revit wall"))
    g.add_node(MemoryNode(id="lo", kind="capability", label="revit"))
    all_hits = query(g, "revit wall")
    # Both match at least one token; high-score filter should drop lo.
    hi_only = query(g, "revit wall", min_score=15.0)
    assert len(hi_only) < len(all_hits)


# ── BFS reachability ─────────────────────────────────────────────────


def test_query_bfs_lifts_skill_referenced_by_matching_turn(g):
    """A Skill that doesn't match the question text directly should
    still surface when a recent turn that DID match `used` it."""
    g.add_node(MemoryNode(id="lib:skill:hero", kind="skill",
                           label="Foo bar baz"))
    g.add_node(MemoryNode(id="turn:t1", kind="turn",
                           label="render revit hero view"))
    g.add_edge(MemoryEdge(source="turn:t1", target="lib:skill:hero",
                           relation="used",
                           confidence=Confidence.EXTRACTED))
    hits = query(g, "revit hero", kinds=("skill",))
    # The skill alone wouldn't match — but BFS from the turn pulls it in.
    assert any(h["id"] == "lib:skill:hero" for h in hits)


def test_query_bfs_lifts_capability_inside_skill_match(g):
    """A capability `contained` in a matching skill should bubble up."""
    g.add_node(MemoryNode(id="lib:cap:render.qweird",
                           kind="capability", label="qweird"))
    g.add_node(MemoryNode(id="lib:skill:revit_hero", kind="skill",
                           label="Revit hero render"))
    g.add_edge(MemoryEdge(
        source="lib:skill:revit_hero", target="lib:cap:render.qweird",
        relation="contains", confidence=Confidence.EXTRACTED))
    hits = query(g, "revit hero")
    ids = [h["id"] for h in hits]
    assert "lib:skill:revit_hero" in ids
    assert "lib:cap:render.qweird" in ids


def test_query_extracted_outranks_inferred(g):
    """Higher confidence boosts the propagated score more than INFERRED."""
    g.add_node(MemoryNode(id="seed", kind="capability", label="revit"))
    g.add_node(MemoryNode(id="ext",  kind="capability", label="other"))
    g.add_node(MemoryNode(id="inf",  kind="capability", label="other"))
    g.add_edge(MemoryEdge(source="seed", target="ext", relation="used",
                           confidence=Confidence.EXTRACTED))
    g.add_edge(MemoryEdge(source="seed", target="inf", relation="used",
                           confidence=Confidence.INFERRED))
    hits = {h["id"]: h["score"] for h in query(g, "revit")}
    assert hits["ext"] > hits["inf"]


# ── why provenance ───────────────────────────────────────────────────


def test_query_why_carries_matched_tokens(g):
    g.add_node(MemoryNode(id="r", kind="capability", label="Revit walls"))
    hits = query(g, "revit walls")
    assert hits[0]["why"], "why should be non-empty for a direct match"
    low = hits[0]["why"].lower()
    assert "revit" in low or "walls" in low


# ── realistic library smoke ──────────────────────────────────────────


def test_query_on_extracted_library_returns_render_caps(realistic):
    hits = query(realistic, "comfyui render workflow")
    ids = [h["id"] for h in hits]
    assert "lib:cap:render.comfyui" in ids


def test_query_on_extracted_library_finds_shipped_skill(realistic):
    hits = query(realistic, "revit hero render", kinds=("skill",))
    ids = [h["id"] for h in hits]
    assert "lib:skill:skill.revit_hero_render" in ids


# ── neighbors_summary ────────────────────────────────────────────────


def test_neighbors_summary_groups_by_relation(g):
    g.add_node(MemoryNode(id="a", kind="capability", label="a"))
    g.add_node(MemoryNode(id="b", kind="capability", label="b"))
    g.add_node(MemoryNode(id="c", kind="capability", label="c"))
    g.add_edge(MemoryEdge(source="a", target="b", relation="contains"))
    g.add_edge(MemoryEdge(source="a", target="c", relation="wires_with",
                           confidence=Confidence.INFERRED))
    g.add_edge(MemoryEdge(source="c", target="a", relation="used"))
    s = neighbors_summary(g, "a")
    assert s["status"] == "ok"
    assert s["out"]["contains"] == ["b"]
    assert s["out"]["wires_with"] == ["c"]
    assert s["in"]["used"] == ["c"]


def test_neighbors_summary_unknown_node_errors(g):
    s = neighbors_summary(g, "ghost")
    assert s["status"] == "error"


# ── tool_engine integration ──────────────────────────────────────────


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from tool_engine import ToolEngine
    return ToolEngine(manager=_StubManager())


def test_memory_query_tool_registered():
    from tool_engine import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "memory_query" in names


def test_memory_query_tool_routes_through_handler(engine, tmp_path,
                                                     monkeypatch):
    """Tool dispatch should land on `_invoke_memory_query`, which
    opens the default graph + runs query. With no extractor having
    run, the graph is empty → results=[]."""
    # Default graph path points to LOCALAPPDATA (mocked to tmp_path).
    out = engine._invoke_memory_query({"question": "revit wall"})
    assert out["status"] == "ok"
    assert out["results"] == []
    assert out["count"] == 0


def test_memory_query_tool_missing_question_errors(engine):
    out = engine._invoke_memory_query({})
    assert out["status"] == "error"
    assert "question" in out["error"]


def test_memory_query_tool_returns_real_hits(engine, tmp_path,
                                                monkeypatch):
    """Populate the default graph via the library extractor + verify
    the tool surfaces matching capabilities."""
    from memory import MemoryGraph, default_graph_path
    g = MemoryGraph.open(default_graph_path())
    try:
        extract_library(g, infer_wires=False)
    finally:
        g.close()
    out = engine._invoke_memory_query({
        "question": "comfyui render", "limit": 5,
    })
    assert out["status"] == "ok"
    assert out["count"] > 0
    ids = [r["id"] for r in out["results"]]
    assert "lib:cap:render.comfyui" in ids


def test_memory_query_tool_kinds_filter(engine, tmp_path, monkeypatch):
    from memory import MemoryGraph, default_graph_path
    g = MemoryGraph.open(default_graph_path())
    try:
        extract_library(g, infer_wires=False)
    finally:
        g.close()
    out = engine._invoke_memory_query({
        "question": "revit", "kinds": ["skill"], "limit": 5,
    })
    assert out["status"] == "ok"
    for r in out["results"]:
        assert r["kind"] == "skill"
