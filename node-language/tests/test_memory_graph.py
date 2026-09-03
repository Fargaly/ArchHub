"""AgDR-0042 slice 1/6 — MemoryGraph core + SQLite.

Covers the contract a slice 2+ extractor (and the slice 3 query layer)
needs to rely on: idempotent upserts, indexed lookups by kind +
relation, neighbour traversal direction, batch transaction rollback,
round-trip via to_dict / from_dict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence, default_graph_path,
)


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def g():
    """Fresh in-memory graph per test — hermetic + fast."""
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


@pytest.fixture
def seeded(g):
    """A 3-node graph that mirrors the AgDR-0042 example shape."""
    g.add_node(MemoryNode(id="lib:cap:revit.read_walls", kind="capability",
                           label="Read walls", props={"category": "host"}))
    g.add_node(MemoryNode(id="lib:skill:hero_render", kind="skill",
                           label="Hero render"))
    g.add_node(MemoryNode(id="turn:2026-05-25:14:22", kind="turn",
                           label="Composer turn", props={"cost": 0.025}))
    g.add_edge(MemoryEdge(
        source="lib:skill:hero_render", target="lib:cap:revit.read_walls",
        relation="contains", confidence=Confidence.EXTRACTED))
    g.add_edge(MemoryEdge(
        source="turn:2026-05-25:14:22", target="lib:skill:hero_render",
        relation="used", confidence=Confidence.EXTRACTED))
    return g


# ── default path ──────────────────────────────────────────────────────


def test_default_graph_path_under_archhub_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = default_graph_path()
    assert "ArchHub" in str(p)
    assert "memory" in str(p)
    assert str(p).endswith("graph.sqlite")


# ── dataclasses round-trip ────────────────────────────────────────────


def test_memory_node_to_from_dict_round_trip():
    n = MemoryNode(id="x", kind="cap", label="X", props={"a": 1})
    n2 = MemoryNode.from_dict(n.to_dict())
    assert n2 == n


def test_memory_edge_to_from_dict_round_trip():
    e = MemoryEdge(source="a", target="b", relation="contains",
                    confidence=Confidence.INFERRED, props={"weight": 0.7})
    e2 = MemoryEdge.from_dict(e.to_dict())
    assert e2 == e


def test_memory_edge_default_confidence_is_extracted():
    e = MemoryEdge(source="a", target="b", relation="r")
    assert e.confidence == Confidence.EXTRACTED


def test_memory_edge_from_dict_unknown_confidence_falls_back():
    """Forward-compat — if a future version introduces a new
    confidence level, older readers shouldn't crash."""
    e = MemoryEdge.from_dict({
        "source": "a", "target": "b", "relation": "r",
        "confidence": "PARANORMAL",
    })
    assert e.confidence == Confidence.EXTRACTED


# ── add/get nodes ─────────────────────────────────────────────────────


def test_add_and_get_node(g):
    g.add_node(MemoryNode(id="n1", kind="cap", label="N1"))
    got = g.get_node("n1")
    assert got is not None
    assert got.id == "n1"
    assert got.kind == "cap"
    assert got.label == "N1"


def test_get_node_missing_returns_none(g):
    assert g.get_node("ghost") is None


def test_add_node_is_idempotent_upsert(g):
    g.add_node(MemoryNode(id="n", kind="cap"))
    g.add_node(MemoryNode(id="n", kind="cap", label="renamed",
                           props={"k": 1}))
    got = g.get_node("n")
    assert got.label == "renamed"
    assert got.props == {"k": 1}
    assert g.count_nodes() == 1


def test_all_nodes_filter_by_kind(seeded):
    caps = seeded.all_nodes(kind="capability")
    assert [n.id for n in caps] == ["lib:cap:revit.read_walls"]
    skills = seeded.all_nodes(kind="skill")
    assert [n.id for n in skills] == ["lib:skill:hero_render"]
    everything = seeded.all_nodes()
    assert len(everything) == 3


def test_count_nodes_by_kind(seeded):
    assert seeded.count_nodes() == 3
    assert seeded.count_nodes(kind="capability") == 1
    assert seeded.count_nodes(kind="skill") == 1
    assert seeded.count_nodes(kind="turn") == 1
    assert seeded.count_nodes(kind="absent") == 0


# ── add/get edges ─────────────────────────────────────────────────────


def test_add_edge_requires_both_endpoints(g):
    g.add_node(MemoryNode(id="a", kind="cap"))
    with pytest.raises(ValueError, match="target"):
        g.add_edge(MemoryEdge(source="a", target="ghost", relation="r"))
    g.add_node(MemoryNode(id="b", kind="cap"))
    # Now target exists — should work.
    g.add_edge(MemoryEdge(source="a", target="b", relation="r"))


def test_add_edge_missing_source_errors(g):
    g.add_node(MemoryNode(id="b", kind="cap"))
    with pytest.raises(ValueError, match="source"):
        g.add_edge(MemoryEdge(source="ghost", target="b", relation="r"))


def test_add_edge_is_idempotent_upsert(seeded):
    """Re-adding (source, target, relation) replaces confidence + props,
    doesn't duplicate the row."""
    seeded.add_edge(MemoryEdge(
        source="lib:skill:hero_render", target="lib:cap:revit.read_walls",
        relation="contains", confidence=Confidence.INFERRED,
        props={"weight": 0.9}))
    edges = seeded.neighbors("lib:skill:hero_render", relation="contains")
    assert len(edges) == 1
    assert edges[0].confidence == Confidence.INFERRED
    assert edges[0].props == {"weight": 0.9}


def test_all_edges_filter_by_relation(seeded):
    contains = seeded.all_edges(relation="contains")
    assert len(contains) == 1
    used = seeded.all_edges(relation="used")
    assert len(used) == 1
    everything = seeded.all_edges()
    assert len(everything) == 2


# ── neighbours / traversal ────────────────────────────────────────────


def test_neighbors_out(seeded):
    out = seeded.neighbors("lib:skill:hero_render", direction="out")
    assert [e.target for e in out] == ["lib:cap:revit.read_walls"]


def test_neighbors_in(seeded):
    inb = seeded.neighbors("lib:skill:hero_render", direction="in")
    assert [e.source for e in inb] == ["turn:2026-05-25:14:22"]


def test_neighbors_both(seeded):
    both = seeded.neighbors("lib:skill:hero_render", direction="both")
    assert len(both) == 2


def test_neighbors_filter_by_relation(seeded):
    rel = seeded.neighbors(
        "lib:skill:hero_render", direction="both", relation="contains")
    assert len(rel) == 1
    assert rel[0].relation == "contains"


def test_neighbors_invalid_direction_raises(seeded):
    with pytest.raises(ValueError, match="direction"):
        seeded.neighbors("any", direction="sideways")


def test_neighbors_unknown_node_returns_empty(seeded):
    assert seeded.neighbors("ghost") == []


# ── remove ────────────────────────────────────────────────────────────


def test_remove_node_cascades_incident_edges(seeded):
    seeded.remove_node("lib:skill:hero_render")
    assert seeded.get_node("lib:skill:hero_render") is None
    # Both edges touching the deleted node should be gone.
    assert seeded.count_edges() == 0


def test_remove_node_returns_false_when_missing(g):
    assert g.remove_node("ghost") is False


def test_remove_edge(seeded):
    assert seeded.remove_edge(
        "lib:skill:hero_render", "lib:cap:revit.read_walls",
        "contains") is True
    assert seeded.count_edges() == 1


def test_remove_edge_returns_false_when_missing(seeded):
    assert seeded.remove_edge("a", "b", "c") is False


# ── batch + transactions ──────────────────────────────────────────────


def test_add_nodes_batch_returns_count(g):
    n = g.add_nodes([
        MemoryNode(id=f"n{i}", kind="batch") for i in range(20)
    ])
    assert n == 20
    assert g.count_nodes(kind="batch") == 20


def test_add_edges_batch_rolls_back_on_missing_endpoint(g):
    g.add_node(MemoryNode(id="a", kind="x"))
    g.add_node(MemoryNode(id="b", kind="x"))
    g.add_node(MemoryNode(id="c", kind="x"))
    edges = [
        MemoryEdge(source="a", target="b", relation="r"),
        MemoryEdge(source="a", target="c", relation="r"),
        MemoryEdge(source="a", target="ghost", relation="r"),  # rolls back
    ]
    with pytest.raises(ValueError, match="ghost"):
        g.add_edges(edges)
    # NEITHER of the prior valid edges should be persisted — transaction
    # rolled back the whole batch.
    assert g.count_edges() == 0


def test_transaction_rolls_back_on_exception(g):
    g.add_node(MemoryNode(id="seed", kind="x"))
    try:
        with g.transaction():
            g.add_node(MemoryNode(id="midway", kind="x"))
            raise RuntimeError("simulated extractor crash")
    except RuntimeError:
        pass
    # `seed` persists (committed pre-transaction); `midway` should not.
    assert g.get_node("seed") is not None
    assert g.get_node("midway") is None


# ── snapshot round-trip ───────────────────────────────────────────────


def test_to_dict_shape(seeded):
    d = seeded.to_dict()
    assert "nodes" in d and "edges" in d
    assert len(d["nodes"]) == 3
    assert len(d["edges"]) == 2
    # First node carries graphify-style envelope.
    n = d["nodes"][0]
    assert {"id", "kind", "label", "props"} <= n.keys()


def test_from_dict_round_trip(seeded):
    d = seeded.to_dict()
    g2 = MemoryGraph.from_dict(d)
    assert g2.count_nodes() == 3
    assert g2.count_edges() == 2
    out = g2.neighbors("lib:skill:hero_render", direction="both")
    assert len(out) == 2


# ── disk persistence ──────────────────────────────────────────────────


def test_writes_persist_across_open(tmp_path):
    """The whole point of the SQLite store — close + reopen reads the
    same nodes + edges back."""
    db = tmp_path / "graph.sqlite"
    g1 = MemoryGraph.open(db)
    g1.add_node(MemoryNode(id="persist", kind="cap", label="Persist me"))
    g1.add_node(MemoryNode(id="other", kind="cap"))
    g1.add_edge(MemoryEdge(source="persist", target="other",
                            relation="links_to"))
    g1.close()

    g2 = MemoryGraph.open(db)
    n = g2.get_node("persist")
    assert n is not None and n.label == "Persist me"
    assert g2.count_edges() == 1
    g2.close()


def test_schema_version_set_to_one(g):
    assert g.schema_version() == "1"
