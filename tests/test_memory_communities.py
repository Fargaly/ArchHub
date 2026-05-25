"""AgDR-0042 slice 5/6 — community detection.

Tests the union-find clustering over structural edges + the helpers
that materialise communities back onto node props or summary lists.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
    detect_communities, annotate_communities, community_stats,
)


@pytest.fixture
def g():
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


@pytest.fixture
def small(g):
    """Two clusters of 3 nodes each, joined by no structural edges.
       cluster A: a1, a2, a3 linked by `contains`
       cluster B: b1, b2, b3 linked by `used`
       Plus z1 — fully isolated singleton."""
    for nid in ("a1", "a2", "a3", "b1", "b2", "b3", "z1"):
        g.add_node(MemoryNode(id=nid, kind="capability", label=nid))
    g.add_edge(MemoryEdge(source="a1", target="a2", relation="contains"))
    g.add_edge(MemoryEdge(source="a2", target="a3", relation="contains"))
    g.add_edge(MemoryEdge(source="b1", target="b2", relation="used"))
    g.add_edge(MemoryEdge(source="b2", target="b3", relation="used"))
    return g


# ── detect_communities ───────────────────────────────────────────────


def test_empty_graph_returns_empty(g):
    assert detect_communities(g) == {}


def test_isolated_nodes_each_form_own_community(g):
    g.add_node(MemoryNode(id="x", kind="capability", label="x"))
    g.add_node(MemoryNode(id="y", kind="capability", label="y"))
    communities = detect_communities(g)
    assert len(communities) == 2
    # Each singleton's id is community:<own-id>.
    assert {"community:x", "community:y"} <= communities.keys()


def test_two_clusters_via_contains_edges(small):
    communities = detect_communities(small)
    # Three communities: A-cluster, B-cluster, z1 singleton.
    assert len(communities) == 3
    sizes = sorted(len(m) for m in communities.values())
    assert sizes == [1, 3, 3]


def test_community_id_is_smallest_member(small):
    communities = detect_communities(small)
    # The id format makes the cluster id deterministic.
    assert "community:a1" in communities
    assert "community:b1" in communities
    assert "community:z1" in communities


def test_community_ids_are_stable_across_runs(small):
    c1 = detect_communities(small)
    c2 = detect_communities(small)
    assert c1 == c2


def test_default_excludes_inferred_edges(g):
    g.add_node(MemoryNode(id="a", kind="capability", label="a"))
    g.add_node(MemoryNode(id="b", kind="capability", label="b"))
    g.add_edge(MemoryEdge(source="a", target="b", relation="wires_with",
                           confidence=Confidence.INFERRED))
    # Default detection ignores INFERRED + wires_with (it's not in
    # the structural set anyway). Both nodes stay singletons.
    communities = detect_communities(g)
    assert len(communities) == 2


def test_include_inferred_does_not_help_if_relation_excluded(g):
    """include_inferred=True but the relation itself isn't in the
    structural set → still no merge."""
    g.add_node(MemoryNode(id="a", kind="capability"))
    g.add_node(MemoryNode(id="b", kind="capability"))
    g.add_edge(MemoryEdge(source="a", target="b", relation="wires_with",
                           confidence=Confidence.INFERRED))
    communities = detect_communities(g, include_inferred=True)
    assert len(communities) == 2  # wires_with not in default relations


def test_custom_relation_set_can_merge_via_wires_with(g):
    g.add_node(MemoryNode(id="a", kind="capability"))
    g.add_node(MemoryNode(id="b", kind="capability"))
    g.add_edge(MemoryEdge(source="a", target="b", relation="wires_with",
                           confidence=Confidence.INFERRED))
    communities = detect_communities(
        g, relations=("wires_with",), include_inferred=True)
    assert len(communities) == 1


def test_extracted_wires_via_custom_set_merge(g):
    """An EXTRACTED edge in a custom set merges even with default
    include_inferred=False."""
    g.add_node(MemoryNode(id="a", kind="capability"))
    g.add_node(MemoryNode(id="b", kind="capability"))
    g.add_edge(MemoryEdge(source="a", target="b", relation="custom_rel",
                           confidence=Confidence.EXTRACTED))
    communities = detect_communities(g, relations=("custom_rel",))
    assert len(communities) == 1


def test_supersedes_relation_merges_decisions(g):
    g.add_node(MemoryNode(id="agdr:0001", kind="decision"))
    g.add_node(MemoryNode(id="agdr:0002", kind="decision"))
    g.add_edge(MemoryEdge(source="agdr:0002", target="agdr:0001",
                           relation="supersedes"))
    communities = detect_communities(g)
    assert len(communities) == 1


# ── annotate_communities ─────────────────────────────────────────────


def test_annotate_writes_community_id_to_props(small):
    n_annotated = annotate_communities(small)
    assert n_annotated > 0
    # Every annotated node should now carry its community_id in props.
    a1 = small.get_node("a1")
    a2 = small.get_node("a2")
    b1 = small.get_node("b1")
    z1 = small.get_node("z1")
    assert a1.props["community_id"] == a2.props["community_id"]
    assert a1.props["community_id"] != b1.props["community_id"]
    assert z1.props["community_id"] == "community:z1"


def test_annotate_is_idempotent(small):
    annotate_communities(small)
    snap = {n.id: n.props["community_id"] for n in small.all_nodes()}
    annotate_communities(small)
    again = {n.id: n.props["community_id"] for n in small.all_nodes()}
    assert snap == again


def test_annotate_preserves_other_props(g):
    g.add_node(MemoryNode(id="x", kind="capability",
                           label="x", props={"keep": "me", "ts": 42}))
    annotate_communities(g)
    n = g.get_node("x")
    assert n.props["keep"] == "me"
    assert n.props["ts"] == 42
    assert n.props["community_id"] == "community:x"


# ── community_stats ──────────────────────────────────────────────────


def test_stats_sorts_by_size_desc(small):
    stats = community_stats(small)
    sizes = [c["size"] for c in stats]
    assert sizes == sorted(sizes, reverse=True)
    # Two 3-clusters + one singleton.
    assert sizes == [3, 3, 1]


def test_stats_carries_dominant_kind_and_sample_labels(g):
    g.add_node(MemoryNode(id="cap1", kind="capability", label="cap one"))
    g.add_node(MemoryNode(id="cap2", kind="capability", label="cap two"))
    g.add_node(MemoryNode(id="sk1",  kind="skill",      label="skill alpha"))
    g.add_edge(MemoryEdge(source="sk1", target="cap1", relation="contains"))
    g.add_edge(MemoryEdge(source="sk1", target="cap2", relation="contains"))
    stats = community_stats(g)
    assert len(stats) == 1
    c = stats[0]
    assert c["size"] == 3
    # 2 caps + 1 skill → dominant_kind should be 'capability'.
    assert c["dominant_kind"] == "capability"
    # sample_labels capped at 3.
    assert 1 <= len(c["sample_labels"]) <= 3


def test_stats_empty_graph_returns_empty_list(g):
    assert community_stats(g) == []
