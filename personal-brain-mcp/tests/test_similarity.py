"""Brain #31 day-5 · similarity search tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
)
from personal_brain.similarity import find_similar
from personal_brain.storage import BrainStore


def _make(fid, *, kind=FragmentKind.IMAGE, phash=None, embedding=None,
          owner="founder", scope=Scope.USER, text="test"):
    return Fragment(
        id=fid, kind=kind, text=text, scope=scope, owner_user=owner,
        provenance=Provenance(contributing_agent="t",
                              contributing_user=owner),
        perceptual_hash=phash,
        embedding=embedding,
    )


@pytest.fixture
def store(tmp_path) -> BrainStore:
    return BrainStore.open(tmp_path / "t.db")


# ── Empty query / store ────────────────────────────────────────────


def test_find_similar_no_query_returns_empty(store):
    store.write_fragment(_make("img_1", phash="ffffffffffffffff"))
    assert find_similar(store) == []


def test_find_similar_empty_store_returns_empty(store):
    hits = find_similar(store, query_phash="0000000000000000")
    assert hits == []


# ── phash-only ranking ─────────────────────────────────────────────


def test_phash_ranks_closer_first(store):
    # 0xff is "1111" — distance 8 from 0xf0 (4 different lower bits)
    store.write_fragment(_make("near",  phash="ffffffffffffffff"))
    store.write_fragment(_make("far",   phash="0000000000000000"))
    store.write_fragment(_make("exact", phash="aaaaaaaaaaaaaaaa"))
    hits = find_similar(store, query_phash="aaaaaaaaaaaaaaaa", k=3)
    assert len(hits) == 3
    assert hits[0].fragment.id == "exact"
    assert hits[0].phash_distance == 0


def test_phash_limits_to_k(store):
    for i in range(10):
        store.write_fragment(_make(f"f{i}", phash=f"{i:016x}"))
    hits = find_similar(store, query_phash="0000000000000000", k=3)
    assert len(hits) == 3


def test_phash_skips_candidates_without_hash(store):
    """A fragment with no perceptual_hash can still appear if it has
    an embedding — but here with phash-only query it ranks lowest."""
    store.write_fragment(_make("with_phash",  phash="0000000000000000"))
    store.write_fragment(_make("no_phash"))  # no hash
    hits = find_similar(store, query_phash="0000000000000000", k=2)
    assert hits[0].fragment.id == "with_phash"


# ── Embedding-only ranking ─────────────────────────────────────────


def test_embedding_ranks_cosine_descending(store):
    # 3-dim embeddings for test simplicity (real CLIP is 512-dim).
    store.write_fragment(_make("along", embedding=[1.0, 0.0, 0.0]))
    store.write_fragment(_make("orth",  embedding=[0.0, 1.0, 0.0]))
    store.write_fragment(_make("anti",  embedding=[-1.0, 0.0, 0.0]))
    query = [1.0, 0.0, 0.0]
    hits = find_similar(store, query_embedding=query, k=3)
    assert hits[0].fragment.id == "along"
    assert hits[1].fragment.id == "orth"
    assert hits[2].fragment.id == "anti"


# ── Combined phash + embedding ─────────────────────────────────────


def test_combined_pre_filter_then_refine(store):
    """phash narrows the set; cosine refines the order within."""
    for i, (phash, emb) in enumerate([
        ("ffff000000000000", [1.0, 0.0, 0.0]),   # 0 distance · best cosine
        ("ffff000000000001", [0.5, 0.5, 0.0]),   # 1 distance · ok cosine
        ("0000ffffffffffff", [1.0, 0.0, 0.0]),   # far phash · would lose pre-filter
    ]):
        store.write_fragment(_make(f"f{i}", phash=phash, embedding=emb))
    hits = find_similar(
        store,
        query_phash="ffff000000000000",
        query_embedding=[1.0, 0.0, 0.0],
        max_phash=2,  # only top 2 by phash survive
        k=2,
    )
    ids = [h.fragment.id for h in hits]
    assert "f2" not in ids  # phash pre-filter eliminated
    assert hits[0].fragment.id == "f0"  # cosine refine wins


# ── Kind + scope filter ────────────────────────────────────────────


def test_default_kinds_is_image_and_geometry(store):
    """A FACT fragment shouldn't show up in find_similar by default."""
    store.write_fragment(_make("img", kind=FragmentKind.IMAGE,
                                  phash="0000000000000000"))
    store.write_fragment(_make("fact", kind=FragmentKind.FACT,
                                  phash="0000000000000000"))
    store.write_fragment(_make("geom", kind=FragmentKind.GEOMETRY,
                                  phash="0000000000000000"))
    hits = find_similar(store, query_phash="0000000000000000", k=10)
    ids = {h.fragment.id for h in hits}
    assert ids == {"img", "geom"}


def test_explicit_kinds_narrows_to_just_one_family(store):
    store.write_fragment(_make("img1", kind=FragmentKind.IMAGE,
                                  phash="0000000000000000"))
    store.write_fragment(_make("geom1", kind=FragmentKind.GEOMETRY,
                                  phash="0000000000000000"))
    hits = find_similar(
        store, query_phash="0000000000000000",
        kinds=[FragmentKind.GEOMETRY], k=10,
    )
    ids = {h.fragment.id for h in hits}
    assert ids == {"geom1"}


def test_scope_filter_restricts_search(store):
    store.write_fragment(_make("u_img", scope=Scope.USER,
                                  phash="0000000000000000"))
    store.write_fragment(_make("p_img", scope=Scope.PROJECT,
                                  phash="0000000000000000"))
    hits = find_similar(
        store, query_phash="0000000000000000",
        scope_filter=[Scope.USER], k=10,
    )
    assert {h.fragment.id for h in hits} == {"u_img"}


# ── Embedding persistence round-trip ───────────────────────────────


def test_embedding_persists_through_store(store):
    """The embedding column round-trips via struct.pack."""
    vec = [0.1, -0.2, 0.3, 0.4, 0.5]
    store.write_fragment(_make("emb_test", embedding=vec))
    back = store.get_fragment("emb_test")
    assert back.embedding is not None
    assert len(back.embedding) == 5
    for i in range(5):
        assert abs(back.embedding[i] - vec[i]) < 1e-9
