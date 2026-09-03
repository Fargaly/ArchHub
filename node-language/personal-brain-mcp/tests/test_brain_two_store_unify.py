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
    # is now the OPAQUE sha256 of the length-prefixed triple (BRV-01 data-loss
    # re-fix — the old literal "a||b||informs" id collided when a node id
    # contained '|'); the triple is recovered from extra, never the id.
    edge_id = store._edge_fragment_id("a", "b", "informs")
    assert edge_id.startswith("graphedge:")
    assert "||" not in edge_id  # no literal separator → no forge-able boundary
    edge_frag = store.get_fragment(edge_id)
    assert edge_frag is not None
    assert edge_frag.predicate == "graph_edge"
    assert edge_frag.extra.get("source") == "a"
    assert edge_frag.extra.get("target") == "b"
    assert edge_frag.extra.get("relation") == "informs"

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


# ── GATE (a): edge-id collision — the court refutation (DATA LOSS) ────────


def test_edge_id_collision_two_distinct_edges_both_retrievable(graph, store):
    """COURT REFUTATION RE-FIX (data loss). The old _edge_fragment_id joined
    (source, target, relation) with a literal '||' and ASSERTED node ids never
    contain '|'. That invariant is FALSE — extractor slugs interpolate
    un-sanitised names (_doc_id("a||x") → "doc:a||x", _tool_id, _cap_id), so
    two DISTINCT edges forged the SAME id and silently overwrote each other:

        (a||x) -[r]-> (y)   and   (a) -[r]-> (x||y)

    both mapped to graphedge:a||x||y → ONE row (regression vs the standalone
    store's composite (source,target,relation) PRIMARY KEY).

    RED on the pre-fix branch: count_edges()==1, neighbors('a||x') empty.
    GREEN after: TWO rows, BOTH retrievable via neighbors()."""
    # Nodes whose ids contain the old separator (a doc literally named a||x.md).
    for nid in ("a||x", "y", "a", "x||y"):
        graph.add_node(MemoryNode(id=nid, kind="capability", label=nid))

    graph.add_edge(MemoryEdge(source="a||x", target="y", relation="r"))
    graph.add_edge(MemoryEdge(source="a", target="x||y", relation="r"))

    # Two DISTINCT edges → two rows (no collision/overwrite).
    assert graph.count_edges() == 2, "edge-id collision: distinct edges overwrote"

    # The distinct fragment ids prove the hash separates them.
    id1 = store._edge_fragment_id("a||x", "y", "r")
    id2 = store._edge_fragment_id("a", "x||y", "r")
    assert id1 != id2
    assert store.get_fragment(id1) is not None
    assert store.get_fragment(id2) is not None

    # BOTH edges are retrievable via neighbors() — neither was lost.
    out_axy = graph.neighbors("a||x", direction="out")
    out_a = graph.neighbors("a", direction="out")
    assert [(e.source, e.target, e.relation) for e in out_axy] == [("a||x", "y", "r")]
    assert [(e.source, e.target, e.relation) for e in out_a] == [("a", "x||y", "r")]

    # Incoming side too — the targets see exactly their own edge.
    assert [e.source for e in graph.neighbors("y", direction="in")] == ["a||x"]
    assert [e.source for e in graph.neighbors("x||y", direction="in")] == ["a"]

    # remove-by-triple still hits the right row (hash recomputed from triple).
    assert graph.remove_edge("a||x", "y", "r") is True
    assert graph.count_edges() == 1
    assert graph.neighbors("a", direction="out")  # the OTHER edge survives


def test_edge_id_no_separator_collision_fuzz(graph, store):
    """Belt-and-braces: a spread of triples whose components carry the literal
    separator (and other delimiters) all get DISTINCT ids — the hash is
    injective over the length-prefixed triple, so no value can forge a
    boundary."""
    triples = [
        ("a||b", "c", "r"),
        ("a", "b||c", "r"),
        ("a|", "|b", "r"),
        ("a", "b", "||"),
        ("a||b||c", "d", "r"),
        ("", "a||b", "r"),
        ("x", "y", "z"),
    ]
    ids = {store._edge_fragment_id(*t) for t in triples}
    assert len(ids) == len(triples), "two distinct triples hashed to one id"


# ── GATE (b): from_dict round-trip (drop-in completeness) ─────────────────


def test_from_dict_round_trip_and_schema_version(store):
    """MemoryGraphStore must be a TRUE drop-in for app MemoryGraph: it now
    exposes from_dict + schema_version (app/memory/sync.py pull() uses
    from_dict for cross-device receive). A to_dict snapshot round-trips
    through from_dict byte-identically."""
    src = MemoryGraphStore(store)
    src.add_node(MemoryNode(id="cap:a", kind="capability", label="A",
                            props={"host": "revit", "cost": 3}))
    src.add_node(MemoryNode(id="dec:b", kind="decision", label="B"))
    src.add_edge(MemoryEdge(source="cap:a", target="dec:b", relation="informs",
                            confidence=Confidence.INFERRED, props={"w": 2}))
    snap = src.to_dict()

    # schema_version present + matches the app graph's snapshot schema ("1").
    assert src.schema_version() == "1"

    # from_dict rebuilds an equivalent graph in a FRESH in-memory brain store
    # (default path is :memory:, never clobbering an on-disk store).
    rebuilt = MemoryGraphStore.from_dict(snap)
    try:
        assert rebuilt.count_nodes() == 2
        assert rebuilt.count_edges() == 1
        n = rebuilt.get_node("cap:a")
        assert n.kind == "capability" and n.props == {"host": "revit", "cost": 3}
        e = rebuilt.all_edges()[0]
        assert (e.source, e.target, e.relation) == ("cap:a", "dec:b", "informs")
        assert e.confidence == Confidence.INFERRED and e.props == {"w": 2}
        # Snapshot is stable across the round-trip (the wire shape is identical
        # to MemoryGraph's — that's what makes a snapshot interchangeable).
        assert rebuilt.to_dict() == snap
    finally:
        rebuilt.close()


def test_from_dict_matches_app_memory_graph_signature():
    """The adapter's from_dict accepts the SAME call the app sync path makes:
    MemoryGraph.from_dict(snapshot, path=...). Proven by calling it positionally
    exactly as app/memory/sync.py pull() does."""
    snap = {
        "nodes": [{"id": "n1", "kind": "capability", "label": "N1", "props": {}}],
        "edges": [],
    }
    # positional (data, path) — the app sync call shape.
    g = MemoryGraphStore.from_dict(snap, ":memory:")
    try:
        assert g.get_node("n1") is not None
    finally:
        g.close()


# ── GATE (c): runtime ADOPTION + one-time migration (no data loss) ───────


def test_app_memory_graph_default_open_uses_brain_store(tmp_path, monkeypatch):
    """ADOPTION: app MemoryGraph.open() — with NO brain_store arg, the way the
    real runtime callers (bridge.py, tool_engine.py) call it — DEFAULTS to the
    unified brain.db, so the running app writes ONE store. Proven by: the
    returned object is the adapter, and a node added through the default-open
    graph is a brain.db fragment readable via a brain-surface adapter over the
    SAME default path."""
    _repo = Path(__file__).resolve().parents[2]
    for _p in (_repo / "app", _repo / "personal-brain-mcp" / "src"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    # Sandbox BOTH the brain.db (APPDATA/XDG) and graph.sqlite (LOCALAPPDATA/XDG)
    # to tmp so we never touch the developer's real stores, and make sure the
    # env opt-out is OFF for this test (the conftest in app/tests sets it; this
    # is the brain-mcp suite so it isn't, but be explicit + future-proof).
    monkeypatch.delenv("ARCHHUB_MEMORY_STANDALONE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    from personal_brain.graph_adapter import MemoryGraphStore as Adapter
    from personal_brain.storage import default_brain_path
    import importlib
    import memory.graph as appgraph
    importlib.reload(appgraph)  # pick up the patched env in path resolvers

    g = appgraph.MemoryGraph.open()  # NO brain_store, NO standalone — the default
    try:
        assert isinstance(g, Adapter), (
            "default MemoryGraph.open() did not route to the unified store"
        )
        g.add_node(appgraph.MemoryNode(
            id="cap:adopted", kind="capability", label="Adopted"))
    finally:
        g.close()

    # The node landed in the canonical brain.db at the daemon's path — read it
    # back via an independent adapter over that SAME file (one store, on disk).
    brain_db = default_brain_path()
    assert Path(brain_db).exists(), "unified open did not create brain.db"
    verify = Adapter.open(str(brain_db))
    try:
        node = verify.get_node("cap:adopted")
        assert node is not None and node.label == "Adopted"
    finally:
        verify.close()


def test_default_open_migrates_existing_graph_sqlite_no_data_loss(
    tmp_path, monkeypatch
):
    """MIGRATION (no data loss): a PRE-EXISTING standalone graph.sqlite — the
    founder's existing memory — is folded into brain.db the first time the
    unified path opens, with every node + edge preserved and none lost. The
    fold is marker-gated + idempotent (a second open does not duplicate)."""
    _repo = Path(__file__).resolve().parents[2]
    for _p in (_repo / "app", _repo / "personal-brain-mcp" / "src"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    monkeypatch.delenv("ARCHHUB_MEMORY_STANDALONE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    import importlib
    import memory.graph as appgraph
    importlib.reload(appgraph)
    from personal_brain.graph_adapter import MemoryGraphStore as Adapter
    from personal_brain.storage import BrainStore, default_brain_path

    # 1. Seed a LEGACY standalone graph.sqlite at the default graph path with
    #    real nodes + edges (the founder's existing memory).
    legacy_path = appgraph.default_graph_path()
    Path(legacy_path).parent.mkdir(parents=True, exist_ok=True)
    legacy = appgraph.MemoryGraph.open(str(legacy_path), standalone=True)
    try:
        legacy.add_node(appgraph.MemoryNode(id="cap:old1", kind="capability",
                                            label="Old One", props={"k": 1}))
        legacy.add_node(appgraph.MemoryNode(id="dec:old2", kind="decision",
                                            label="Old Two"))
        legacy.add_edge(appgraph.MemoryEdge(
            source="cap:old1", target="dec:old2", relation="informs"))
        assert legacy.count_nodes() == 2 and legacy.count_edges() == 1
    finally:
        legacy.close()

    # Pre-condition: brain.db has none of these yet.
    assert not Path(default_brain_path()).exists() or \
        BrainStore.open(str(default_brain_path())).count_graph_nodes() == 0

    # 2. Default-open the unified graph → triggers the one-time fold.
    g = appgraph.MemoryGraph.open()
    try:
        assert isinstance(g, Adapter)
        # Every legacy node + edge is now in the unified store — none lost.
        assert g.get_node("cap:old1").props == {"k": 1}
        assert g.get_node("dec:old2").label == "Old Two"
        nbrs = g.neighbors("cap:old1", direction="out")
        assert [(e.source, e.target, e.relation) for e in nbrs] == [
            ("cap:old1", "dec:old2", "informs")
        ]
        assert g.count_nodes() == 2 and g.count_edges() == 1
    finally:
        g.close()

    # 3. Marker stamped → a SECOND open is a no-op fold (no duplication).
    store = BrainStore.open(str(default_brain_path()))
    try:
        assert store.get_meta("migrated_from_graph"), "migration marker not set"
    finally:
        store.close()

    g2 = appgraph.MemoryGraph.open()
    try:
        assert g2.count_nodes() == 2 and g2.count_edges() == 1  # still 2/1
    finally:
        g2.close()


def test_standalone_opt_out_keeps_graph_sqlite(tmp_path, monkeypatch):
    """The explicit OPT-OUT (standalone=True / env) keeps the legacy
    graph.sqlite path reachable for tests/offline/the CLI — it must NOT be the
    unified adapter and must expose the raw sqlite internals the edge-extractor
    CLI pokes (._conn)."""
    _repo = Path(__file__).resolve().parents[2]
    for _p in (_repo / "app", _repo / "personal-brain-mcp" / "src"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    import importlib
    import memory.graph as appgraph
    importlib.reload(appgraph)
    from personal_brain.graph_adapter import MemoryGraphStore as Adapter

    # explicit flag
    g = appgraph.MemoryGraph.open(":memory:", standalone=True)
    try:
        assert not isinstance(g, Adapter)
        assert hasattr(g, "_conn")  # raw sqlite handle the CLI needs
    finally:
        g.close()

    # env opt-out
    monkeypatch.setenv("ARCHHUB_MEMORY_STANDALONE", "1")
    importlib.reload(appgraph)
    g2 = appgraph.MemoryGraph.open(":memory:")
    try:
        assert not isinstance(g2, Adapter)
    finally:
        g2.close()
