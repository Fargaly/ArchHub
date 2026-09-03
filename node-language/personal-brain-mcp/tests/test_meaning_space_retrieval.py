"""BRV-08 — MEANING_SPACE graph-signal recall ranker.

Proves a GRAPH ranker (hubness / geodesic / graph_rank) exists and CHANGES the
ranking versus the FTS+cosine-only ranker on a fixture. Before this work the
brain had FTS5 + vector cosine + the Generative-Agents triple-score and NO
graph/geodesic/hubness signal anywhere, so the `raw ⊕ graph` dual-retrieval bet
(acceptance #8) was untestable. These tests are the machine gate for that leaf.

RED on origin/main: `personal_brain.meaning_space` does not exist and
`retrieval.retrieve_facts_graph` is undefined → collection/import fails.
GREEN on the branch: the module + ranker exist and the graph order differs from
the cosine-only order in the documented, graph-driven way.

Run: pytest -k "retrieval and (graph or geodesic or hubness)" -p no:cacheprovider
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain.embeddings import get_embedder
from personal_brain.meaning_space import MeaningGraph, graph_signals
from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
)
from personal_brain.storage import BrainStore
from personal_brain import retrieval


# ─────────────────────────── fixtures ──────────────────────────────────


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _prov():
    return Provenance(
        contributing_agent="claude-sonnet-4.7",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


def _frag(fid, text, subject=None, predicate=None, obj=None, extra=None):
    return Fragment(
        id=fid,
        kind=FragmentKind.FACT,
        text=text,
        subject=subject,
        predicate=predicate,
        object=obj,
        owner_user="founder",
        provenance=_prov(),
        extra=extra or {},
    )


def _seed_tower_graph(store):
    """A small meaning-space around topic 'tower-a':

      anchor  — strong lexical match to the query 'tower wall takeoff';
                also the subject hub 'tower-a'.
      hub1    — LOW lexical match, but co-subject 'tower-a' (a hub, one hop
                from the anchor in meaning-space).
      hub2    — LOW lexical match, co-subject 'tower-a' (a hub).
      noise1  — HIGHER lexical match than the hubs (it shares 'tower' + 'wall'
                with the query) but graph-ISOLATED: its own subject
                'podium-spec' shares no subject/object with the tower cluster
                and it declares no refs.
    """
    frags = [
        _frag("anchor", "Tower-A wall takeoff quantity schedule",
              subject="tower-a", predicate="has", obj="wall-takeoff"),
        _frag("hub1", "structural grid spacing eight metres east bay",
              subject="tower-a", predicate="has", obj="grid"),
        _frag("hub2", "floor count nineteen levels above ground",
              subject="tower-a", predicate="has", obj="floors"),
        _frag("noise1", "tower podium external wall cladding panel type",
              subject="podium-spec", predicate="has", obj="cladding"),
    ]
    for f in frags:
        store.write_fragment(f)
    return frags


# ─────────────────────── pure graph-signal unit tests ──────────────────


def test_meaning_graph_hubness_and_geodesic_are_real_graph_signals():
    """The graph signals are derived from the fragment graph, not faked.

    'tower-a' co-subject fragments are mutual neighbours (a hub); a fragment in
    a different subject is isolated (hubness 0, geodesic 0 from the hub seed).
    """
    frags = [
        _frag("a", "x", subject="tower-a", obj="o1"),
        _frag("b", "y", subject="tower-a", obj="o2"),
        _frag("c", "z", subject="tower-a", obj="o3"),
        _frag("iso", "isolated", subject="other-topic", obj="o4"),
    ]
    g = MeaningGraph(frags)
    hub = g.hubness()
    # a/b/c are mutually connected (degree 2 of 3 possible) → 0.667; iso → 0.
    assert hub["a"] == pytest.approx(2 / 3)
    assert hub["b"] == pytest.approx(2 / 3)
    assert hub["iso"] == 0.0
    assert g.edge_count >= 3  # the tower-a triangle

    # Geodesic from seed 'a': a=1.0, its neighbours 0.5, isolated 0.0.
    geo = g.geodesic_proximity(["a"])
    assert geo["a"] == 1.0
    assert geo["b"] == pytest.approx(0.5)
    assert geo["iso"] == 0.0


def test_meaning_graph_pagerank_is_a_distribution_and_neutral_when_no_edges():
    # No edges → uniform distribution (the honest neutral, never faked).
    iso = [_frag(f"n{i}", "t", subject=f"s{i}", obj=f"o{i}") for i in range(4)]
    g = MeaningGraph(iso)
    assert g.edge_count == 0
    rank = g.graph_rank()
    assert sum(rank.values()) == pytest.approx(1.0, abs=1e-6)
    for v in rank.values():
        assert v == pytest.approx(0.25, abs=1e-6)

    # A node pointed at by others (in-edges) outranks a leaf with none.
    hubbed = [
        _frag("center", "c", subject="center", obj="z"),
        _frag("p1", "p", subject="p1", obj="center"),   # p1.object == center.subject → p1→center
        _frag("p2", "p", subject="p2", obj="center"),
        _frag("p3", "p", subject="p3", obj="center"),
    ]
    g2 = MeaningGraph(hubbed)
    r2 = g2.graph_rank()
    assert r2["center"] > r2["p1"]


def test_graph_signals_bundle_keys_present():
    frags = [_frag("a", "x", subject="t", obj="u"), _frag("b", "y", subject="t", obj="v")]
    sig = graph_signals(frags, seeds=["a"])
    assert set(sig["a"]) == {"hubness", "graph_rank", "geodesic"}
    assert sig["a"]["geodesic"] == 1.0          # seed
    assert sig["b"]["geodesic"] == pytest.approx(0.5)  # one hop


# ───────────────── the acceptance gate: graph ≠ FTS-only ────────────────


def test_graph_ranker_changes_ranking_vs_fts_cosine_only(store):
    """ACCEPTANCE (#8): the graph ranker re-orders relative to the FTS+cosine
    ranker. Specifically a structural HUB (`hub2`, LOW cosine, co-subject with
    the query anchor) is promoted ABOVE a graph-ISOLATED fragment with a
    STRICTLY HIGHER raw cosine (`noise1`) — a flip the cosine-only ranker
    cannot make, because cosine alone always ranks `noise1` higher.
    """
    _seed_tower_graph(store)
    emb = get_embedder(prefer="lexical")  # deterministic, dep-free
    q = "tower wall takeoff"

    fts_order = [f.id for f in retrieval.retrieve_facts(
        store, q, owner_user="founder", k=5, embedder=emb)]
    graph_order, dbg = retrieval.retrieve_facts_graph(
        store, q, owner_user="founder", k=5, embedder=emb, return_debug=True)
    graph_order = [f.id for f in graph_order]

    # 1. The two rankers must genuinely produce a different order.
    assert graph_order != fts_order, (
        f"graph ranker did not change the ranking — fts={fts_order} "
        f"graph={graph_order}; the graph signal is inert"
    )

    # 2. 'noise1' genuinely has the higher raw cosine of the pair — so the
    #    cosine-only ranker ranks it ABOVE the structural hub 'hub2'.
    assert dbg["noise1"]["cosine"] > dbg["hub2"]["cosine"]
    assert fts_order.index("noise1") < fts_order.index("hub2"), (
        f"fixture invalid: cosine-only ranker did not put noise1 above hub2 "
        f"({fts_order})"
    )

    # 3. The graph ranker FLIPS that: 'hub2' (a hub, co-subject with the anchor)
    #    now outranks the isolated 'noise1' despite the LOWER cosine — the
    #    graph signal (hubness) overrode the cosine gap.
    assert graph_order.index("hub2") < graph_order.index("noise1"), (
        f"graph signal failed to promote the hub over the isolated fact: "
        f"{graph_order}"
    )

    # 4. The promotion is graph-driven, not a cosine artefact: hub2's cosine is
    #    strictly below noise1's, yet hub2 ends with the higher FINAL score, and
    #    the differentiator is the graph signal — hub2 is a hub, noise1 is not.
    assert dbg["hub2"]["cosine"] < dbg["noise1"]["cosine"]
    assert dbg["hub2"]["final"] > dbg["noise1"]["final"]
    assert dbg["hub2"]["hubness"] > 0.0          # a real hub
    assert dbg["noise1"]["hubness"] == 0.0       # isolated — honest zero


def test_graph_ranker_degrades_to_cosine_when_no_edges(store):
    """When the candidate set is fully disconnected (no shared subject/object,
    no refs) every graph signal is its honest neutral, so the graph ranker
    returns the same top fragment as cosine — no fabricated graph effect.
    """
    for i, txt in enumerate([
        "pump station flow rate calculation",
        "lighting lux level office desk",
        "fire rating two hour partition wall",
    ]):
        store.write_fragment(_frag(f"d{i}", txt, subject=f"topic{i}", obj=f"obj{i}"))
    emb = get_embedder(prefer="lexical")
    q = "fire rating partition"
    graph = retrieval.retrieve_facts_graph(store, q, owner_user="founder", k=3, embedder=emb)
    assert graph, "expected non-empty graph retrieval"
    # The fire-rating fact is the strongest cosine match and there are no edges
    # to perturb the order → it stays on top.
    assert graph[0].id == "d2"
