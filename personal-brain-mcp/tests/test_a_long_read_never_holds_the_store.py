"""A big listing must not freeze the brain.

Three thread dumps of the founder's daemon, taken while it answered nothing,
all showed the same shape: one thread active in list_fragments for
brain.list_facts, and brain.health queued behind it on the single shared
connection lock. The default limit scans 54,076 rows and takes 88 seconds on
his store, so any client listing facts took the whole daemon down with it.
"""
from __future__ import annotations

import threading
import time

import pytest

from datetime import datetime, timezone

from personal_brain.storage import (
    BrainStore,
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)


def _fact(index: int) -> Fragment:
    return Fragment(
        id="frag-%03d" % index,
        kind=FragmentKind.FACT,
        text="fact %d" % index,
        subject="user",
        predicate="knows",
        object="thing %d" % index,
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        owner_user="founder",
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="court",
            contributing_user="founder",
            created_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def store(tmp_path):
    made = BrainStore.open(tmp_path / "brain.db")
    for i in range(60):
        made.write_fragment(_fact(i))
    yield made
    made.close()


def test_a_big_read_does_not_take_the_shared_lock(store):
    """The lock stays held by a stand-in writer while the big listing runs."""
    store._lock.acquire()
    try:
        rows = store.list_fragments(limit=100_000)
    finally:
        store._lock.release()
    assert len(rows) == 60, len(rows)


def test_a_small_read_keeps_the_cheap_shared_path(store):
    assert len(store.list_fragments(limit=10)) == 10


def test_the_threshold_and_reader_are_real():
    import inspect

    source = inspect.getsource(BrainStore.list_fragments)
    assert "_OWN_READER_ABOVE" in source and "_open_reader()" in source
    reader = inspect.getsource(BrainStore._open_reader)
    assert "query_only=ON" in reader, "the extra connection must never write"
    assert BrainStore._OWN_READER_ABOVE >= 1000


def test_an_in_memory_store_still_answers():
    made = BrainStore.open(":memory:")
    try:
        assert made._path_for_readers is None
        assert made.list_fragments(limit=100_000) == []
    finally:
        made.close()


def test_a_status_read_answers_while_a_big_listing_runs(store):
    """The behaviour the founder lost: brain.health during a long listing."""
    store.set_meta("k", "v")
    done = threading.Event()

    def big():
        store.list_fragments(limit=100_000)
        done.set()

    worker = threading.Thread(target=big, daemon=True)
    store._lock.acquire()   # a writer holds the shared connection throughout
    try:
        worker.start()
        began = time.monotonic()
        worker.join(10)
        spent = time.monotonic() - began
    finally:
        store._lock.release()
    assert done.is_set(), "the big listing waited for the shared lock"
    assert spent < 10
