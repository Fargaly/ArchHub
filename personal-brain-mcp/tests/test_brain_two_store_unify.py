"""BRV-01 GATE — the two-store memory unify round-trip (ONE-SYSTEM).

ArchHub used to run TWO disjoint knowledge stores reconciled only by the manual
band-aid tools/brain_unify.py:
  (a) app/memory/graph.py  MemoryGraph → graph.sqlite  (the AgDR-0042 graph)
  (b) personal-brain      BrainStore  → brain.db       (the daemon store)

personal_brain.graph_adapter.MemoryGraphStore unifies them to ONE store: it
presents the full MemoryGraph API but persists every node/edge as a Fragment
in the SAME brain.db. These tests pin the contract the founder's ONE-SYSTEM
mandate depends on — **a fact written via one path is readable via the other**:

  1. node written via the MemoryGraph surface (adapter.add_node)
     → readable via the brain surface (BrainStore.get_fragment / search).
  2. fact written via the brain surface (BrainStore.write_fragment with the
     canonical `graph:<id>` id) → readable via the MemoryGraph surface
     (adapter.get_node / all_nodes) — the SAME row, not a copy.
  3. it is literally ONE store: both surfaces report the same backing rows;
     a node count seen through the graph API matches the fragment row.
  4. edges round-trip + neighbors() works over the unified store.
  5. brain_unify.unify() now writes the SAME canonical rows the adapter reads
     (the band-aid is obsolete — its output is already visible to the unified
     graph with no second copy).
  6. app's MemoryGraph.open(brain_store=...) routes to the unified store, so
     the app extractor path and the brain share one graph.

These run against a single in-memory BrainStore (`:memory:`) for hermetic
isolation. RED on origin/main (the adapter + BrainStore graph primitives do
not exist there); GREEN after BRV-01.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The adapter + storage primitives live in the installed personal_brain package.
from personal_brain.graph_adapter import (  # noqa: E402
    MemoryGraphStore, MemoryNode, MemoryEdge, Confidence,
)
from personal_brain.models import FragmentKind, Scope  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store() -> BrainStore:
    s = BrainStore.open(":memory:")
    yield s
    s.close()


@pytest.fixture
def graph(store) -> MemoryGraphStore:
    """A unified graph view over the SAME in-memory brain store."""
    return MemoryGraphStore(store)


# ── 1. graph-write → brain-read ──────────────────────────────────────────


def test_node_written_via_graph_is_readable_via_brain(graph, store):
    """A node added through the MemoryGraph surface is the SAME fragment row
    the brain store reads — not a separate copy."""
    graph.add_node(MemoryNode(
        id="cap:revit.read_walls", kind="capability",
        label="Read walls from Revit", props={"cost": 3, "host": "revit"},
    ))

    # Brain surface sees it at the canonical id, with the brain_unify mapping.
    frag = store.get_fragment("graph:cap:revit.read_walls")
    assert frag is not None, "node not visible to the brain store"
    assert frag.kind == FragmentKind.FACT
    assert frag.predicate == "capability"
    assert frag.subject == "Read walls from Revit"
    assert "Read walls from Revit" in frag.text

    # And FTS search over the brain finds the same fact.
    hits = store.search_fragments("walls", k=10)
    assert any(h.id == "graph:cap:revit.read_walls" for h in hits)


# ── 2. brain-write → graph-read (the reverse direction) ──────────────────


def test_fact_written_via_brain_is_readable_via_graph(graph, store):
    """A fact written DIRECTLY through the brain store (at the canonical
    `graph:<id>` id) is visible through the MemoryGraph surface as a node —
    proving a single backing store, readable both ways."""
    from datetime import datetime, timezone
    from personal_brain.models import (
        Fragment, Provenance, Visibility, Confidence as FConfidence,
    )

    frag = Fragment(
        id="graph:dec:use-speckle-wires",
        kind=FragmentKind.DOCUMENT,
        text="Every wire is a Speckle send/receive",
        subject="Every wire is a Speckle send/receive",
        predicate="decision",
        scope=Scope.PROJECT,
        visibility=Visibility.PRIVATE,
        owner_user="founder",
        confidence=FConfidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="brain-direct",
            contributing_user="founder",
            created_at=datetime.now(timezone.utc),
        ),
        extra={
            "graph_node_id": "dec:use-speckle-wires",
            "graph_kind": "decision",
            "graph_props": {"agdr": "AgDR-0012"},
        },
    )
    store.write_fragment(frag)

    # MemoryGraph surface now sees it as a node — same row, decoded back.
    node = graph.get_node("dec:use-speckle-wires")
    assert node is not None, "brain-written fact not visible to the graph"
    assert node.kind == "decision"          # original graph kind recovered
    assert node.label == "Every wire is a Speckle send/receive"
    assert node.props == {"agdr": "AgDR-0012"}

    # And it shows up in all_nodes() filtered by the original kind.
    decisions = graph.all_nodes(kind="decision")
    assert [n.id for n in decisions] == ["dec:use-speckle-wires"]


# ── 3. it is literally ONE store ─────────────────────────────────────────


def test_single_backing_store_no_parallel_copy(graph, store):
    """The graph API and the brain API report the SAME backing rows — there is
    no second store, no sync. Round-tripping a node through the graph surface
    reads identical content back, and the counts agree."""
    graph.add_node(MemoryNode(id="skill:revfix", kind="skill",
                              label="revfix workflow", props={"sheets": 43}))

    # Graph count and the underlying fragment row agree (one store).
    assert graph.count_nodes() == 1
    assert store.count_graph_nodes() == 1
    assert store.get_fragment("graph:skill:revfix") is not None

    # Lossless round-trip through the graph surface.
    node = graph.get_node("skill:revfix")
    assert node.kind == "skill"
    assert node.label == "revfix workflow"
    assert node.props == {"sheets": 43}

    # Mutating via the graph surface updates the SAME row (no duplicate).
    graph.add_node(MemoryNode(id="skill:revfix", kind="skill",
                              label="revfix workflow v2", props={"sheets": 56}))
    assert graph.count_nodes() == 1
    assert store.count_graph_nodes() == 1
    assert graph.get_node("skill:revfix").label == "revfix workflow v2"
    assert "v2" in store.get_fragment("graph:skill:revfix").text


# ── 4. edges + neighbors over the unified store ──────────────────────────


def test_edges_round_trip_and_neighbors(graph, store):
    """Edges persist as first-class fragments and neighbors() works over the
    unified store; endpoint-existence is enforced like MemoryGraph."""
    graph.add_node(MemoryNode(id="a", kind="capability", label="A"))
    graph.add_node(MemoryNode(id="b", kind="decision", label="B"))
    graph.add_edge(MemoryEdge(source="a", target="b", relation="informs",
                              confidence=Confidence.EXTRACTED,
                              props={"weight": 1}))

    assert graph.count_edges() == 1
    out = graph.neighbors("a", direction="out")
    assert len(out) == 1
    assert out[0].source == "a" and out[0].target == "b"
    assert out[0].relation == "informs"
    assert out[0].props == {"weight": 1}
    assert graph.neighbors("b", direction="in")[0].source == "a"

    # The edge is a real brain.db fragment too (first-class, queryable). Its id
    # encodes the (source, target, relation) triple with an id-safe separator.
    edge_frag = store.get_fragment("graphedge:a||b||informs")
    assert edge_frag is not None
    assert edge_frag.predicate == "graph_edge"

    # Endpoint enforcement matches MemoryGraph.add_edge.
    with pytest.raises(ValueError):
        graph.add_edge(MemoryEdge(source="a", target="missing", relation="x"))

    # The incident edge also rides in the node fragment's legacy sidecar so
    # brain_unify-era readers keep seeing extra['graph_edges'].
    a_frag = store.get_fragment("graph:a")
    sidecar = a_frag.extra.get("graph_edges")
    assert isinstance(sidecar, list) and len(sidecar) == 1
    assert sidecar[0]["target"] == "b"


# ── 5. brain_unify.unify() now writes the SAME canonical rows ────────────


def test_brain_unify_output_visible_to_unified_graph(store):
    """The legacy band-aid (brain_unify.unify) writes the exact `graph:<id>`
    fragments the adapter reads — so its output is already part of the ONE
    graph, with no second copy. This is what makes the band-aid obsolete."""
    # brain_unify pulls memory from app/; wire app onto sys.path for import.
    _repo = Path(__file__).resolve().parents[2]
    for _p in (_repo / "tools", _repo / "app"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    import brain_unify  # noqa: E402
    from memory.graph import (  # noqa: E402
        MemoryGraph as AppGraph, MemoryNode as AppNode,
    )

    legacy = AppGraph.open(":memory:")
    legacy.add_node(AppNode(id="cap:x", kind="capability", label="Cap X",
                            props={"host": "revit"}))
    try:
        res = brain_unify.unify(legacy, store)
        assert res["imported"] == 1
    finally:
        legacy.close()

    # The unified graph surface sees the band-aid's import as a native node.
    graph = MemoryGraphStore(store)
    node = graph.get_node("cap:x")
    assert node is not None
    assert node.kind == "capability"
    assert node.label == "Cap X"
    assert node.props == {"host": "revit"}


# ── 6. app MemoryGraph.open(brain_store=...) routes to the unified store ──


def test_app_memory_graph_open_routes_to_brain_store(store):
    """app/memory/graph.py MemoryGraph.open(brain_store=...) returns the
    unified adapter, so the app extractor path and the brain share one graph:
    a node added through the app surface is a brain.db fragment."""
    _repo = Path(__file__).resolve().parents[2]
    for _p in (_repo / "app",):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    from memory.graph import MemoryGraph as AppGraph, MemoryNode as AppNode

    g = AppGraph.open(brain_store=store)
    # It's the unified adapter, backed by our store.
    assert isinstance(g, MemoryGraphStore)
    assert g.store is store

    g.add_node(AppNode(id="cap:unified", kind="capability", label="Unified"))
    # Visible to the brain store immediately — one store.
    assert store.get_fragment("graph:cap:unified") is not None
    # And visible to a SECOND independent adapter over the same store.
    other = MemoryGraphStore(store)
    assert other.get_node("cap:unified").label == "Unified"
