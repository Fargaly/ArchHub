"""Courts for recall by meaning: graph-held vectors, one model at a time."""
from __future__ import annotations

import math

import pytest

from nodelang.cell_brain_recall import (
    ADMITTED_MODELS,
    INDEX_ROOT,
    index_fact,
    indexed_facts,
    recall_by_similarity,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

MODEL = "local-minilm-v2"
DIM = ADMITTED_MODELS[MODEL]


def _vec(*head):
    values = list(head) + [0.0] * (DIM - len(head))
    return tuple(values[:DIM])


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell("fact:" + name, NULL_CELL_ID, NULL_CELL_ID, name.encode())
        for name in ("clouds", "sheets", "wires")
    ))
    return store


def test_an_indexed_fact_is_held_under_its_model():
    store = _store()
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(1.0))
    held = indexed_facts(store.snapshot(), MODEL)
    assert [fact for fact, _vector in held] == ["fact:clouds"]


def test_a_vector_of_the_wrong_size_is_refused_and_nothing_changes():
    store = _store()
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        index_fact(store, fact_root="fact:clouds", model=MODEL, vector=(1.0, 2.0))
    assert store.snapshot().revision == before
    assert indexed_facts(store.snapshot(), MODEL) == ()


def test_an_unadmitted_model_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        index_fact(store, fact_root="fact:clouds", model="guesswork", vector=_vec(1.0))


def test_a_vector_that_is_not_numbers_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        index_fact(
            store, fact_root="fact:clouds", model=MODEL,
            vector=_vec(float("nan")),
        )


def test_an_all_zero_vector_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec())


def test_a_fact_the_graph_does_not_hold_cannot_be_indexed():
    store = _store()
    with pytest.raises(InvalidCell):
        index_fact(store, fact_root="fact:imaginary", model=MODEL, vector=_vec(1.0))


def test_recall_returns_the_nearest_first():
    store = _store()
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(1.0, 0.0))
    index_fact(store, fact_root="fact:sheets", model=MODEL, vector=_vec(0.0, 1.0))
    index_fact(store, fact_root="fact:wires", model=MODEL, vector=_vec(0.9, 0.1))
    found = recall_by_similarity(store.snapshot(), model=MODEL, query=_vec(1.0, 0.0))
    assert [item.fact_root for item in found[:2]] == ["fact:clouds", "fact:wires"]
    assert math.isclose(found[0].similarity, 1.0, rel_tol=1e-9)


def test_recall_never_mixes_models():
    store = _store()
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(1.0))
    other = "cloud-embed-v3"
    wide = tuple([1.0] + [0.0] * (ADMITTED_MODELS[other] - 1))
    index_fact(store, fact_root="fact:sheets", model=other, vector=wide)
    found = recall_by_similarity(store.snapshot(), model=MODEL, query=_vec(1.0))
    assert [item.fact_root for item in found] == ["fact:clouds"]


def test_re_indexing_replaces_rather_than_duplicates():
    store = _store()
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(1.0, 0.0))
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(0.0, 1.0))
    held = indexed_facts(store.snapshot(), MODEL)
    assert len(held) == 1
    assert held[0][1][:2] == (0.0, 1.0)


def test_a_query_that_does_not_match_the_model_is_refused():
    store = _store()
    index_fact(store, fact_root="fact:clouds", model=MODEL, vector=_vec(1.0))
    with pytest.raises(InvalidCell):
        recall_by_similarity(store.snapshot(), model=MODEL, query=(1.0, 0.0))


def test_no_index_recalls_nothing():
    store = CellStore()
    assert INDEX_ROOT not in store.snapshot().cells
    assert recall_by_similarity(
        store.snapshot(), model=MODEL, query=_vec(1.0)) == ()
