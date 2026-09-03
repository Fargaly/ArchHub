"""Hybrid recall — BM25 lane beside dense embeddings, per-query alpha.

Machine gate for the `hybrid_recall` slice (Tier-1: Query-Adaptive Hybrid
Search):

  (a) exact-code query flips the ranking: a memory pure-dense ranks 4th is
      ranked 1st by the 0.5-alpha hybrid,
  (b) no-code query → alpha 1.0 → ranking BIT-IDENTICAL to pure dense
      (zero-risk regression),
  (c) BM25 Okapi hand-check on a 3-doc corpus (idf/tf arithmetic in the
      comments, tolerance 1e-6),
  (d) tokenizer preserves exact-code tokens (CW22, AP_CORNICE) whole,
  (w) the `retrieve_facts(hybrid_alpha=...)` wire: default == explicit 1.0
      (exact order), and 0.5 surfaces the code-bearing fragment.

Every expected value below is hand-computed — none of these tests can pass on
a stub implementation that returns constants or echoes its input.

Run: cd personal-brain-mcp && PYTHONPATH=src python -m pytest tests/test_hybrid_recall.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain.hybrid_recall import (
    BM25,
    blend,
    hybrid_scores,
    predict_alpha,
    tokenize,
)
from personal_brain.models import Fragment, FragmentKind, Provenance
from personal_brain.retrieval import retrieve_facts
from personal_brain.storage import BrainStore


# ─────────────────────── (d) tokenizer ─────────────────────────────────


def test_tokenizer_keeps_code_tokens_whole():
    # Codes stay verbatim; prose lowercases; punctuation splits; underscore
    # does NOT split a code.
    assert tokenize("AP_CORNICE ring profile, CW22.") == [
        "AP_CORNICE", "ring", "profile", "CW22",
    ]
    # Mixed-case prose is lowercased (not a code), digits pass through.
    assert tokenize("Tower wall 9820") == ["tower", "wall", "9820"]
    # A lowercased variant does NOT collide with the preserved code token —
    # exactness is the point of the lane.
    assert tokenize("ap_cornice") == ["ap_cornice"]
    assert tokenize("") == []


# ─────────────────────── (c) BM25 hand-check ───────────────────────────


def test_bm25_okapi_hand_computed_three_docs():
    """3-doc corpus, every number derived by hand (k1=1.5, b=0.75).

    Corpus (tokenized):
        d0 = [wall, takeoff, schedule]   |d0| = 3
        d1 = [wall, wall, paint]         |d1| = 3
        d2 = [cornice, profile]          |d2| = 2
    N = 3, avgdl = (3+3+2)/3 = 8/3.

    idf(t) = ln(1 + (N - df + 0.5)/(df + 0.5)):
        wall:    df=2 → ln(1 + 1.5/2.5) = ln(1.6)  = 0.47000362924573563
        cornice: df=1 → ln(1 + 2.5/1.5) = ln(8/3)  = 0.9808292530117263

    Length norm k1·(1 - b + b·dl/avgdl):
        dl=3 → 1.5·(0.25 + 0.75·(3/(8/3))) = 1.5·(0.25 + 0.84375) = 1.640625
        dl=2 → 1.5·(0.25 + 0.75·(2/(8/3))) = 1.5·(0.25 + 0.5625)  = 1.21875

    score = idf · tf·(k1+1)/(tf + norm):
        q='wall',    d0: 0.47000363·(1·2.5)/(1+1.640625) = 0.4449738501734775
        q='wall',    d1: 0.47000363·(2·2.5)/(2+1.640625) = 0.6454985466035854
        q='wall',    d2: term absent → 0.0
        q='cornice', d2: 0.98082925·(1·2.5)/(1+1.21875)  = 1.1051597217033537
    """
    bm = BM25(["wall takeoff schedule", "wall wall paint", "cornice profile"])

    assert bm.idf("wall") == pytest.approx(0.47000362924573563, abs=1e-6)
    assert bm.idf("cornice") == pytest.approx(0.9808292530117263, abs=1e-6)

    wall = bm.scores("wall")
    assert wall[0] == pytest.approx(0.4449738501734775, abs=1e-6)
    assert wall[1] == pytest.approx(0.6454985466035854, abs=1e-6)  # tf=2 > tf=1
    assert wall[2] == pytest.approx(0.0, abs=1e-6)

    cornice = bm.scores("cornice")
    assert cornice[0] == pytest.approx(0.0, abs=1e-6)
    assert cornice[1] == pytest.approx(0.0, abs=1e-6)
    assert cornice[2] == pytest.approx(1.1051597217033537, abs=1e-6)


# ─────────────────────── predict_alpha heuristic ───────────────────────


def test_predict_alpha_code_queries_get_half():
    assert predict_alpha("AP_CORNICE") == 0.5        # [A-Z_]{4,}
    assert predict_alpha("CW22 drift") == 0.5        # [A-Z]{2,}[0-9_]
    assert predict_alpha("sheet 9820") == 0.5        # \d{2,}


def test_predict_alpha_prose_stays_pure_dense():
    assert predict_alpha("ring profile sketch notes") == 1.0
    assert predict_alpha("what did the founder say about renders") == 1.0
    assert predict_alpha("") == 1.0


# ─────────────────────── (a) hybrid flips exact-code ranking ───────────


# 10 memory texts; index 3 is the only one containing the code. Dense scores
# are a PASSED-IN stub of the embedding similarity (descending by index), so
# pure dense ranks the target 4th.
_TEXTS = [
    "wall takeoff quantity schedule for the tower",       # dense 0.90 (1st)
    "revit sheet revision workflow notes",                # dense 0.85 (2nd)
    "cornice ring detail sketch for the crown",           # dense 0.80 (3rd)
    "AP_CORNICE ring profile",                            # dense 0.75 (4th) ← target
    "speckle wire between max and revit",                 # dense 0.50
    "render enhance recipe with geometry lock",           # dense 0.40
    "personal budget conversion plan",                    # dense 0.30
    "broker ports for the revit session",                 # dense 0.20
    "missoni facade slab edge offsets",                   # dense 0.15
    "submittal comment audit report",                     # dense 0.10
]
_DENSE = [0.90, 0.85, 0.80, 0.75, 0.50, 0.40, 0.30, 0.20, 0.15, 0.10]


def test_pure_dense_ranks_code_doc_fourth_hybrid_ranks_it_first():
    """query 'AP_CORNICE' → predict_alpha = 0.5 → target jumps 4th → 1st.

    Hand-check of the blend:
      min-max(dense): lo=0.10, hi=0.90, span=0.80
          doc0 → 1.0        doc3 → (0.75-0.10)/0.80 = 0.8125
      BM25 lane: only doc3 contains the token AP_CORNICE (tokenizer preserves
      it), every other doc scores 0 → after min-max doc3=1.0, rest=0.0.
      blend(alpha=0.5):
          doc3 → 0.5·0.8125 + 0.5·1.0 = 0.90625   ← max
          doc0 → 0.5·1.0000 + 0.5·0.0 = 0.50
    """
    query = "AP_CORNICE"

    # Precondition the fixture actually encodes: pure dense puts target 4th.
    dense_order = sorted(range(10), key=lambda i: _DENSE[i], reverse=True)
    assert dense_order.index(3) == 3  # 0-based position 3 == ranked 4th

    assert predict_alpha(query) == 0.5
    hybrid = hybrid_scores(query, _TEXTS, _DENSE)  # alpha=None → 0.5

    assert hybrid[3] == pytest.approx(0.90625, abs=1e-9)
    assert hybrid[0] == pytest.approx(0.50, abs=1e-9)
    hybrid_order = sorted(range(10), key=lambda i: hybrid[i], reverse=True)
    assert hybrid_order[0] == 3  # target is now ranked 1st


# ─────────────────────── (b) no-code query = pure dense regression ─────


def test_no_code_query_is_bit_identical_to_pure_dense():
    query = "ring profile sketch"  # no code tokens
    assert predict_alpha(query) == 1.0

    out = hybrid_scores(query, _TEXTS, _DENSE)
    # BIT-identical values, not just same order: alpha==1.0 must return the
    # dense scores untouched (no min-max normalization, no BM25 pass).
    assert out == _DENSE

    order = sorted(range(10), key=lambda i: out[i], reverse=True)
    assert order == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]  # exact dense order


# ─────────────────────── blend edge behavior ───────────────────────────


def test_blend_edges():
    # alpha=0 → pure BM25 order; constant dense lane normalizes to zeros and
    # contributes nothing (honest neutral).
    out = blend([0.7, 0.7, 0.7], [0.0, 2.0, 1.0], 0.0)
    assert out == [0.0, 1.0, 0.5]
    # Length mismatch must fail loudly, never silently misalign candidates.
    with pytest.raises(ValueError):
        blend([1.0], [1.0, 2.0], 0.5)


# ─────────────────────── (w) retrieve_facts wire ───────────────────────


class _StubEmbedder:
    """Deterministic dense lane for the wiring test: encode() carries the raw
    text, cosine() looks the ITEM text up in a fixed score table. Lets the
    test pin the exact dense score per fragment without a model."""

    dim = 1
    backend_name = "stub-table"

    def __init__(self, table):
        self.table = table  # text -> dense score

    def encode(self, text):
        return [text]

    def encode_batch(self, texts):
        return [[t] for t in texts]

    def cosine(self, a, b):
        # a = encoded query, b = encoded item text
        return self.table.get(b[0], 0.0)


def _prov():
    return Provenance(
        contributing_agent="test",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


def _frag(fid, text):
    # No subject/object → the text fed to both lanes is exactly `text`.
    # last_used_at None + zero counts → recency and importance identical for
    # every fragment, so ranking is driven by relevance alone.
    return Fragment(
        id=fid,
        kind=FragmentKind.FACT,
        text=text,
        owner_user="founder",
        provenance=_prov(),
    )


# All five contain 'ring' so the FTS5 OR-candidate stage returns all of them
# for the query below; only fA contains the code.
_WIRE_DOCS = {
    "fA": ("AP_CORNICE ring profile", 0.60),
    "fB": ("ring detail sketch for the podium", 0.90),
    "fC": ("ring workflow notes", 0.80),
    "fD": ("crown ring mockup", 0.70),
    "fE": ("ring spacer note", 0.10),
}


@pytest.fixture
def wired_store():
    s = BrainStore.open(":memory:")
    for fid, (text, _score) in _WIRE_DOCS.items():
        s.write_fragment(_frag(fid, text))
    yield s
    s.close()


def _wire_embedder():
    return _StubEmbedder({text: score for text, score in _WIRE_DOCS.values()})


def test_retrieve_facts_default_bit_identical_to_alpha_one(wired_store):
    """ZERO-RISK gate: hybrid_alpha omitted and hybrid_alpha=1.0 must walk the
    identical (original) code path — exact same ids in the exact same order.

    Expected pure-dense order by the stub scores: fB(.9) fC(.8) fD(.7) fA(.6)
    fE(.1) — the code doc sits 4th.
    """
    kwargs = dict(owner_user="founder", k=5, embedder=_wire_embedder())
    default_ids = [f.id for f in retrieve_facts(wired_store, "AP_CORNICE ring", **kwargs)]
    explicit_ids = [
        f.id for f in retrieve_facts(
            wired_store, "AP_CORNICE ring", hybrid_alpha=1.0, **kwargs
        )
    ]
    assert default_ids == ["fB", "fC", "fD", "fA", "fE"]
    assert explicit_ids == default_ids


def test_retrieve_facts_hybrid_alpha_surfaces_code_fragment(wired_store):
    """hybrid_alpha=0.5 lifts fA (the only AP_CORNICE holder) to rank 1.

    Blend hand-check (recency/importance identical across docs, so order is
    decided by the blended relevance):
      dense min-max: lo=0.1, hi=0.9 → fA=(0.6-0.1)/0.8=0.625, fB=1.0
      BM25: 'ring' appears in all 5 docs (idf=ln(1+0.5/5.5)≈0.087, tiny);
      AP_CORNICE only in fA (idf=ln(1+4.5/1.5)=ln 4≈1.386, dominant) → fA is
      the BM25 max by an order of magnitude → min-max ≈ fA=1.0, others ≲0.05.
      fA ≈ 0.5·0.625 + 0.5·1.0 = 0.8125  >  fB ≈ 0.5·1.0 + ~0.02 ≈ 0.52.
    """
    ids = [
        f.id for f in retrieve_facts(
            wired_store, "AP_CORNICE ring",
            owner_user="founder", k=5,
            embedder=_wire_embedder(), hybrid_alpha=0.5,
        )
    ]
    assert ids[0] == "fA"
    # Dense lane still orders the rest: fB before fC before fD.
    assert ids.index("fB") < ids.index("fC") < ids.index("fD")
