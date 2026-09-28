"""Courts for the memory accelerators: fast, disposable, never the meaning.

Coordinator decision 2026-09-17 under SPEC.md 3.1: deleting an accelerator must
not change meaning. Every court compares the accelerated answer with the answer
the Cells give directly for the same session, and with the answer after the
accelerator was thrown away. Rebased on the session-bound memory (d810889).
"""
from __future__ import annotations

import math

import pytest

from nodelang.brain_memory_accelerators import MemoryListing, RecallCache, recall
from nodelang.cell_brain_memory import forget, memories, recall_memory, remember
from nodelang.cell_session_state import ACTIVE, CLOSED, move_to, open_session
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "app:users:founder"
COLLEAGUE = "app:users:colleague"
S_FOUNDER = "app:sessions:founder-desktop"
S_COLLEAGUE = "app:sessions:colleague-laptop"
VOCABULARY = ("rate", "revit", "sheet", "site", "client", "broker")


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(FOUNDER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),
        Cell(COLLEAGUE, NULL_CELL_ID, NULL_CELL_ID, b"colleague"),
    ))
    open_session(store, session_root=S_FOUNDER, owner_root=FOUNDER)
    open_session(store, session_root=S_COLLEAGUE, owner_root=COLLEAGUE)
    rows = (
        ("fact-rate", "site rate is 450", "fact", S_FOUNDER, 10),
        ("setup-revit", "revit broker listens locally", "setup", S_FOUNDER, 20),
        ("fact-sheets", "client wants A1 sheet sets", "fact", S_FOUNDER, 30),
        ("fact-colleague", "colleague site rate notes", "fact", S_COLLEAGUE, 40),
    )
    for fragment_id, text, kind, session, clock in rows:
        remember(store, session_root=session, fragment_id=fragment_id, text=text,
                 kind=kind, origin="desktop", clock=clock)
    return store


class _Embedder:
    """Deterministic word-count embedding that records every call."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, model):
        self.calls.append((text, model))
        words = text.lower().split()
        vector = [float(sum(1 for w in words if w.startswith(v))) for v in VOCABULARY]
        return list(reversed(vector)) if model == "model-b" else vector


FILTERS = (
    {},
    {"kind": "setup"},
    {"include_forgotten": True},
    {"kind": "fact", "include_forgotten": True},
)


@pytest.mark.parametrize("filters", FILTERS)
def test_the_listing_answers_exactly_what_the_cells_answer(filters):
    store = _store()
    forget(store, session_root=S_FOUNDER, fragment_id="fact-sheets", origin="desktop",
           clock=35)
    listing = MemoryListing(store, session_root=S_FOUNDER)
    assert listing.memories(**filters) == memories(
        store.snapshot(), session_root=S_FOUNDER, **filters)


@pytest.mark.parametrize("filters", FILTERS)
def test_dropping_the_listing_changes_nothing_but_speed(filters):
    store = _store()
    listing = MemoryListing(store, session_root=S_FOUNDER)
    before = listing.memories(**filters)
    listing.drop()
    assert listing.memories(**filters) == before


def test_the_listing_is_built_once_per_revision_and_never_trusted_across_a_write():
    store = _store()
    listing = MemoryListing(store, session_root=S_FOUNDER)
    listing.memories()
    listing.memories(kind="fact")
    assert listing.builds == 1
    remember(store, session_root=S_FOUNDER, fragment_id="fact-new",
             text="new site rate 500", kind="fact", origin="phone", clock=50)
    assert "fact-new" in {m.fragment_id for m in listing.memories()}
    assert listing.builds == 2


def test_the_listing_writes_nothing():
    store = _store()
    settled = store.snapshot().revision
    MemoryListing(store, session_root=S_FOUNDER).memories(include_forgotten=True)
    assert store.snapshot().revision == settled


def test_a_listing_shows_only_its_own_session_owner():
    store = _store()
    founder = MemoryListing(store, session_root=S_FOUNDER).memories(include_forgotten=True)
    colleague = MemoryListing(store, session_root=S_COLLEAGUE).memories(
        include_forgotten=True)
    assert {m.owner_root for m in founder} == {FOUNDER}
    assert [m.fragment_id for m in colleague] == ["fact-colleague"]


def test_a_listing_reads_nothing_once_its_session_closes():
    store = _store()
    listing = MemoryListing(store, session_root=S_FOUNDER)
    assert listing.memories()
    move_to(store, S_FOUNDER, ACTIVE)
    move_to(store, S_FOUNDER, CLOSED)
    for _ in range(2):
        with pytest.raises(InvalidCell):
            listing.memories()


def _recall(store, embedder, cache, *, model="model-a", query="site rate",
            session=S_FOUNDER):
    return recall(MemoryListing(store, session_root=session), query, model=model,
                  embed=embedder, cache=cache, k=3)


def test_recall_ranks_by_meaning():
    found = _recall(_store(), _Embedder(), RecallCache())
    assert found[0][0].fragment_id == "fact-rate"
    assert all(-1.0 <= score <= 1.0 for _, score in found)


def test_recall_never_returns_another_owners_memory():
    found = _recall(_store(), _Embedder(), RecallCache(), query="colleague site rate notes")
    assert "fact-colleague" not in {memory.fragment_id for memory, _ in found}


def test_a_second_recall_reuses_the_vectors_and_gives_the_same_answer():
    store = _store()
    embedder, cache = _Embedder(), RecallCache()
    first = _recall(store, embedder, cache)
    computed = cache.computed
    assert _recall(store, embedder, cache) == first
    assert cache.computed == computed


def test_dropping_the_vectors_changes_nothing_but_speed():
    store = _store()
    embedder, cache = _Embedder(), RecallCache()
    first = _recall(store, embedder, cache)
    cache.drop()
    assert _recall(store, embedder, cache) == first
    assert cache.computed == 6


def test_an_edited_memory_gets_a_new_vector_and_the_old_one_is_never_used():
    store = _store()
    embedder, cache = _Embedder(), RecallCache()
    _recall(store, embedder, cache, query="client sheet")
    remember(store, session_root=S_FOUNDER, fragment_id="fact-rate",
             text="client sheet rate", kind="fact", origin="phone", clock=60)
    computed = cache.computed
    found = _recall(store, embedder, cache, query="client sheet")
    assert cache.computed == computed + 1
    assert embedder.calls[-1] == ("client sheet rate", "model-a")
    assert found[0][0].text in ("client sheet rate", "client wants A1 sheet sets")


def test_vectors_from_different_models_never_mix():
    store = _store()
    embedder, cache = _Embedder(), RecallCache()
    _recall(store, embedder, cache, model="model-a")
    computed = cache.computed
    _recall(store, embedder, cache, model="model-b")
    assert cache.computed == computed + 3


def test_a_missing_vector_is_recomputed_never_an_error():
    store = _store()
    embedder, cache = _Embedder(), RecallCache()
    first = _recall(store, embedder, cache)
    cache.discard(recall_memory(store.snapshot(), "setup-revit", session_root=S_FOUNDER))
    assert _recall(store, embedder, cache) == first
    assert embedder.calls[-1] == ("revit broker listens locally", "model-a")


def test_forgotten_memories_are_not_recalled():
    store = _store()
    forget(store, session_root=S_FOUNDER, fragment_id="fact-rate", origin="desktop",
           clock=70)
    found = _recall(store, _Embedder(), RecallCache())
    assert "fact-rate" not in {memory.fragment_id for memory, _ in found}


def test_recall_writes_nothing():
    store = _store()
    settled = store.snapshot().revision
    _recall(store, _Embedder(), RecallCache())
    assert store.snapshot().revision == settled


@pytest.mark.parametrize("bad", ([], [math.nan, 1.0], ["x"], None))
def test_an_embedding_that_is_not_numbers_is_refused(bad):
    store = _store()
    with pytest.raises(InvalidCell):
        recall(MemoryListing(store, session_root=S_FOUNDER), "site rate", model="model-a",
               embed=lambda text, model: bad, cache=RecallCache())
