"""Tests for tools/brain_unify.unify — the graph.sqlite → brain.db importer.

Pins the contract the founder's data-unification ask depends on:
  1. a 3-node graph (cap / decision / skill) imports as 3 fragments with
     the right by_kind split + FragmentKind mapping;
  2. re-running is idempotent (imported=0, skipped=3) — re-import never
     duplicates;
  3. capability nodes land as FragmentKind.FACT with predicate="capability";
  4. fragment ids are the stable `graph:<node_id>` form.

These run against in-memory stores (`:memory:`) for hermetic isolation —
no real graph.sqlite / brain.db is touched here. The live end-to-end run
is the CLI (`python tools/brain_unify.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# brain_unify lives under tools/ and pulls memory from app/. Wire both
# the repo's tools dir AND app dir onto sys.path so the import resolves
# regardless of pytest's rootdir (tests run from personal-brain-mcp/).
_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "tools"
_APP = _REPO / "app"
for _p in (_TOOLS, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from memory.graph import MemoryGraph, MemoryEdge, MemoryNode  # noqa: E402
from personal_brain.models import FragmentKind, Scope  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402

import brain_unify  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def graph() -> MemoryGraph:
    """A tiny in-memory graph: 1 capability, 1 decision, 1 skill, plus
    one edge so the sidecar path is exercised."""
    g = MemoryGraph.open(":memory:")
    g.add_node(MemoryNode(
        id="cap:revit.read_walls", kind="capability",
        label="Read walls from Revit",
        props={"cost": 3, "host": "revit"},
    ))
    g.add_node(MemoryNode(
        id="dec:use-speckle-wires", kind="decision",
        label="Every wire is a Speckle send/receive",
        props={"agdr": "AgDR-0012"},
    ))
    g.add_node(MemoryNode(
        id="skill:revfix", kind="skill",
        label="revfix revision-table workflow",
        props={"sheets_done": 43},
    ))
    # capability → decision edge: lands in both nodes' sidecars.
    g.add_edge(MemoryEdge(
        source="cap:revit.read_walls", target="dec:use-speckle-wires",
        relation="informs",
    ))
    yield g
    g.close()


@pytest.fixture
def store() -> BrainStore:
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ── tests ────────────────────────────────────────────────────────────


def test_unify_imports_three_nodes_by_kind(graph, store):
    """3 nodes → 3 fragments; by_kind split correct; counts move."""
    result = brain_unify.unify(graph, store)

    assert result["imported"] == 3
    assert result["skipped"] == 0
    assert result["fragments_before"] == 0
    assert result["fragments_after"] == 3

    # Each graph kind imported exactly once, nothing skipped.
    assert result["by_kind"] == {
        "capability": {"imported": 1, "skipped": 0},
        "decision": {"imported": 1, "skipped": 0},
        "skill": {"imported": 1, "skipped": 0},
    }
    # Store really holds 3 fragments now.
    assert store.count_fragments() == 3


def test_unify_is_idempotent(graph, store):
    """Re-running imports nothing new and skips all 3 — no duplicates."""
    first = brain_unify.unify(graph, store)
    assert first["imported"] == 3

    second = brain_unify.unify(graph, store)
    assert second["imported"] == 0
    assert second["skipped"] == 3
    # Re-import must NOT grow the store.
    assert second["fragments_before"] == 3
    assert second["fragments_after"] == 3
    assert store.count_fragments() == 3
    assert second["by_kind"] == {
        "capability": {"imported": 0, "skipped": 1},
        "decision": {"imported": 0, "skipped": 1},
        "skill": {"imported": 0, "skipped": 1},
    }


def test_capability_maps_to_fact_with_predicate(graph, store):
    """capability → FragmentKind.FACT, predicate='capability'."""
    brain_unify.unify(graph, store)

    frag = store.get_fragment("graph:cap:revit.read_walls")
    assert frag is not None
    assert frag.kind == FragmentKind.FACT
    assert frag.predicate == "capability"
    # subject carries the human label; text is FTS-searchable.
    assert frag.subject == "Read walls from Revit"
    assert "Read walls from Revit" in frag.text

    # And the sibling mappings, for completeness:
    dec = store.get_fragment("graph:dec:use-speckle-wires")
    assert dec.kind == FragmentKind.DOCUMENT
    assert dec.predicate == "decision"

    skill = store.get_fragment("graph:skill:revfix")
    assert skill.kind == FragmentKind.FACT
    assert skill.predicate == "skill"


def test_fragment_id_is_graph_prefixed(graph, store):
    """Every fragment id is the stable `graph:<node_id>` form."""
    brain_unify.unify(graph, store)

    for node in graph.all_nodes():
        expected_id = f"graph:{node.id}"
        assert store.get_fragment(expected_id) is not None, (
            f"missing fragment for {expected_id}"
        )


# ── extra robustness (beyond the 4 required) ─────────────────────────


def test_scope_default_is_project(graph, store):
    """Imported fragments default to PROJECT scope (the founder ask)."""
    brain_unify.unify(graph, store)
    frag = store.get_fragment("graph:cap:revit.read_walls")
    assert frag.scope == Scope.PROJECT
    assert frag.owner_user == "founder"
    assert frag.provenance.contributing_agent == "brain_unify"


def test_edges_preserved_as_sidecar(graph, store):
    """The incident edge rides along in extra['graph_edges']."""
    brain_unify.unify(graph, store)
    frag = store.get_fragment("graph:cap:revit.read_walls")
    edges = frag.extra.get("graph_edges")
    assert isinstance(edges, list) and len(edges) == 1
    e = edges[0]
    assert e["source"] == "cap:revit.read_walls"
    assert e["target"] == "dec:use-speckle-wires"
    assert e["relation"] == "informs"


def test_changed_node_reimports(graph, store):
    """Mutating a node's label re-imports just that one (idempotency is
    content-based, not merely id-based)."""
    brain_unify.unify(graph, store)

    # Re-label the capability node, re-add (MemoryGraph upserts by id).
    graph.add_node(MemoryNode(
        id="cap:revit.read_walls", kind="capability",
        label="Read walls from Revit (v2)",
        props={"cost": 3, "host": "revit"},
    ))
    result = brain_unify.unify(graph, store)
    assert result["imported"] == 1
    assert result["skipped"] == 2
    # Still no net growth — it was an upsert, not an insert.
    assert store.count_fragments() == 3
    frag = store.get_fragment("graph:cap:revit.read_walls")
    assert "v2" in frag.text
