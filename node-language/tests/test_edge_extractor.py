"""AgDR-0042 slice 6/6 — edge extractor (similar_to + realized_by).

Hermetic: every test builds a small in-memory MemoryGraph so we never
touch the user's real graph.sqlite. The extractor loads the always-
available lexical embedder (offline, no model download).

Covers the deliverable's 5 required cases:
  1. near-duplicate capabilities → ≥1 similar_to edge
  2. disjoint-vocab nodes → no similar_to at a high threshold
  3. idempotent: second run adds 0
  4. isolated count drops after extraction on a seeded graph
  5. capability + matching decision → realized_by edge
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import MemoryGraph, Confidence  # noqa: E402
from memory.graph import MemoryNode, MemoryEdge  # noqa: E402
from memory.extractors.edges import extract_edges, _isolated_count  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def g():
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


def _cap(g, cid, label, type_, category="aec.qto"):
    g.add_node(MemoryNode(
        id=cid, kind="capability", label=label,
        props={"type": type_, "category": category, "source": "test"}))


def _dec(g, did, label, **props):
    g.add_node(MemoryNode(id=did, kind="decision", label=label, props=props))


# ── 1. near-duplicate capabilities → similar_to ──────────────────────


def test_near_duplicate_caps_create_similar_to(g):
    # Three caps with heavily-overlapping vocabulary.
    _cap(g, "lib:cap:aec.qto_pricing", "QTO Pricing Estimator",
         "aec.qto_pricing", "aec.qto")
    _cap(g, "lib:cap:aec.cost_estimate", "QTO Cost Estimate Pricing",
         "aec.cost_estimate", "aec.qto")
    _cap(g, "lib:cap:aec.schedule_builder", "QTO Schedule Pricing Builder",
         "aec.schedule_builder", "aec.qto")

    stats = extract_edges(g, sim_threshold=0.3)
    sims = g.all_edges(relation="similar_to")
    assert len(sims) >= 1, f"expected >=1 similar_to, got {len(sims)}: {sims}"
    for e in sims:
        assert e.confidence == Confidence.INFERRED
        assert "cosine" in e.props
        assert 0.0 <= e.props["cosine"] <= 1.0
    assert stats["similar_to"] >= 1


def test_similar_to_is_symmetric_single_pair(g):
    """An unordered pair is emitted once, not twice (no A-B AND B-A)."""
    _cap(g, "lib:cap:aec.dxf_reader", "DXF Reader file import drawing",
         "aec.dxf_reader", "aec.files")
    _cap(g, "lib:cap:aec.ifc_reader", "IFC Reader file import drawing",
         "aec.ifc_reader", "aec.files")
    extract_edges(g, sim_threshold=0.3)
    sims = g.all_edges(relation="similar_to")
    pairs = {tuple(sorted((e.source, e.target))) for e in sims}
    # No duplicate orientation: edge count == unique unordered-pair count.
    assert len(sims) == len(pairs)
    for e in sims:
        assert e.source <= e.target  # canonical orientation


# ── 2. disjoint vocab → no similar_to at high threshold ──────────────


def test_disjoint_vocab_no_similar_to(g):
    # Two caps sharing no meaningful tokens.
    _cap(g, "lib:cap:aec.revit_wall", "Revit Wall masonry partition host",
         "aec.revit_wall", "aec.revit")
    _cap(g, "lib:cap:llm.classify", "Sentiment classifier language model",
         "llm.classify", "llm")
    extract_edges(g, sim_threshold=0.82)
    sims = g.all_edges(relation="similar_to")
    between = [e for e in sims
              if {e.source, e.target} ==
              {"lib:cap:aec.revit_wall", "lib:cap:llm.classify"}]
    assert between == [], f"unrelated nodes should not link: {between}"


# ── 3. idempotent ────────────────────────────────────────────────────


def test_extract_edges_is_idempotent(g):
    _cap(g, "lib:cap:aec.qto_pricing", "QTO Pricing Estimator",
         "aec.qto_pricing", "aec.qto")
    _cap(g, "lib:cap:aec.cost_estimate", "QTO Cost Estimate Pricing",
         "aec.cost_estimate", "aec.qto")
    _cap(g, "lib:cap:aec.schedule_builder", "QTO Schedule Pricing Builder",
         "aec.schedule_builder", "aec.qto")
    _dec(g, "agdr:0001", "QTO pricing engine decision", agdr_id="AgDR-0001",
         status="executed")

    s1 = extract_edges(g, sim_threshold=0.3)
    n1, e1 = g.count_nodes(), g.count_edges()
    s2 = extract_edges(g, sim_threshold=0.3)
    assert g.count_nodes() == n1
    assert g.count_edges() == e1, "second run must add no new edges"
    assert s2["added"] == s1["added"]
    # The newly-added count from the graph's POV is stable: re-run upserts
    # the same triples, so total edge count is unchanged.


def test_idempotent_even_with_preexisting_structural_edges(g):
    """A graph that already has builds_on edges stays consistent."""
    _dec(g, "agdr:0001", "First decision about pipelines", agdr_id="AgDR-0001")
    _dec(g, "agdr:0002", "Second decision about pipelines", agdr_id="AgDR-0002")
    g.add_edge(MemoryEdge(source="agdr:0002", target="agdr:0001",
                          relation="builds_on", confidence=Confidence.EXTRACTED))
    before = g.count_edges()
    extract_edges(g, sim_threshold=0.3)
    mid = g.count_edges()
    extract_edges(g, sim_threshold=0.3)
    after = g.count_edges()
    assert after == mid
    assert mid >= before  # similarity edges added on first run only


# ── 4. isolation drops after extraction ──────────────────────────────


def test_isolated_count_drops_after_extraction(g):
    # Seed a cluster of related caps + decisions, all initially isolated.
    _cap(g, "lib:cap:aec.qto_pricing", "QTO Pricing Estimator cost",
         "aec.qto_pricing", "aec.qto")
    _cap(g, "lib:cap:aec.cost_estimate", "QTO Cost Estimate pricing",
         "aec.cost_estimate", "aec.qto")
    _cap(g, "lib:cap:aec.schedule_builder", "QTO Schedule cost pricing",
         "aec.schedule_builder", "aec.qto")
    _cap(g, "lib:cap:aec.dxf_reader", "DXF Reader drawing file import",
         "aec.dxf_reader", "aec.files")
    _cap(g, "lib:cap:aec.ifc_reader", "IFC Reader drawing file import",
         "aec.ifc_reader", "aec.files")
    _dec(g, "agdr:0001", "QTO pricing cost estimate engine",
         agdr_id="AgDR-0001", status="executed")
    _dec(g, "agdr:0002", "QTO pricing schedule cost rollup",
         agdr_id="AgDR-0002", status="executed")

    iso_before, total = _isolated_count(g)
    assert iso_before == total, "every seeded node starts isolated"

    stats = extract_edges(g, sim_threshold=0.3)
    iso_after, _ = _isolated_count(g)

    assert stats["isolated_before"] == iso_before
    assert stats["isolated_after"] == iso_after
    assert iso_after < iso_before, (
        f"isolation must drop: {iso_before} -> {iso_after}")
    assert stats["isolated_pct_after"] < 100.0


# ── 5. capability + matching decision → realized_by ──────────────────


def test_capability_matching_decision_realized_by(g):
    # A decision whose text clearly names the capability's slug.
    _cap(g, "lib:cap:aec.qto_pricing", "QTO Pricing", "aec.qto_pricing",
         "aec.qto")
    _dec(g, "agdr:0050",
         "Adopt the qto_pricing engine for takeoffs",
         agdr_id="AgDR-0050", status="executed")

    stats = extract_edges(g, sim_threshold=0.82)  # high → force mention path
    rb = g.all_edges(relation="realized_by")
    assert len(rb) >= 1, f"expected >=1 realized_by, got {rb}"
    e = rb[0]
    assert e.source == "lib:cap:aec.qto_pricing"
    assert e.target == "agdr:0050"
    assert e.confidence == Confidence.INFERRED
    assert stats["realized_by"] >= 1


def test_realized_by_via_embedding_similarity(g):
    """realized_by can also fire on embedding cosine alone (no mention)."""
    _cap(g, "lib:cap:aec.cost_estimate",
         "cost estimate takeoff pricing rollup", "aec.cost_estimate", "aec.qto")
    _dec(g, "agdr:0051",
         "cost estimate takeoff pricing rollup workflow",
         agdr_id="AgDR-0051", status="executed")
    extract_edges(g, sim_threshold=0.4)
    rb = g.all_edges(relation="realized_by")
    assert any(e.source == "lib:cap:aec.cost_estimate"
               and e.target == "agdr:0051" for e in rb)
    for e in rb:
        assert e.confidence == Confidence.INFERRED


def test_realized_by_direction_is_cap_to_decision(g):
    _cap(g, "lib:cap:aec.qto_pricing", "QTO Pricing", "aec.qto_pricing")
    _dec(g, "agdr:0050", "qto_pricing engine", agdr_id="AgDR-0050")
    extract_edges(g, sim_threshold=0.82)
    for e in g.all_edges(relation="realized_by"):
        assert e.source.startswith("lib:cap:")
        assert e.target.startswith("agdr:")


# ── return-shape contract ────────────────────────────────────────────


def test_return_dict_has_all_keys(g):
    _cap(g, "lib:cap:a", "alpha beta gamma", "a.b")
    stats = extract_edges(g, sim_threshold=0.5)
    for k in ("added", "similar_to", "realized_by",
              "isolated_before", "isolated_after", "isolated_pct_after"):
        assert k in stats, f"missing key {k} in {stats}"
    assert stats["added"] == stats["similar_to"] + stats["realized_by"]


def test_empty_graph_no_crash(g):
    stats = extract_edges(g)
    assert stats["added"] == 0
    assert stats["isolated_pct_after"] == 0.0
