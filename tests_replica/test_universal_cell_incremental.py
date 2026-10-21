"""Incremental dependency court with clean-recomputation equivalence."""
import pytest

from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    MatchBudgetExceeded,
)


def _chain_store():
    store = CellStore()
    store.commit(store.revision, create=[
        Cell("leaf", NULL_CELL_ID, NULL_CELL_ID, b"one"),
        Cell("branch", "leaf", NULL_CELL_ID, b""),
        Cell("root", "branch", NULL_CELL_ID, b""),
    ])
    return store


def test_transitive_change_invalidates_cached_observation():
    store = _chain_store()
    before = store.fingerprint("root", budget=32)
    assert store.fingerprint_computes("root") == 1
    assert store.fingerprint("root", budget=32) == before
    assert store.fingerprint_computes("root") == 1

    store.commit(store.revision, replace=[
        Cell("leaf", NULL_CELL_ID, NULL_CELL_ID, b"two")
    ])
    after = store.fingerprint("root", budget=32)
    assert after != before
    assert store.fingerprint_computes("root") == 2


def test_unrelated_change_does_not_recompute_root():
    store = _chain_store()
    observed = store.fingerprint("root", budget=32)
    store.commit(store.revision, create=[
        Cell("unrelated", NULL_CELL_ID, NULL_CELL_ID, b"elsewhere")
    ])
    assert store.fingerprint("root", budget=32) == observed
    assert store.fingerprint_computes("root") == 1


def test_incremental_result_equals_clean_recomputation():
    store = _chain_store()
    store.fingerprint("root", budget=32)
    store.commit(store.revision, replace=[
        Cell("leaf", NULL_CELL_ID, NULL_CELL_ID, b"changed")
    ])
    incremental = store.fingerprint("root", budget=32)

    clean = CellStore()
    clean.commit(clean.revision, create=[
        cell
        for cell_id, cell in store.snapshot().cells.items()
        if cell_id != NULL_CELL_ID
    ])
    assert clean.fingerprint("root", budget=32) == incremental


def test_cycles_are_finite_and_deterministic():
    store = CellStore()
    store.commit(store.revision, create=[
        Cell("a", "b", NULL_CELL_ID, b"A"),
        Cell("b", "a", NULL_CELL_ID, b"B"),
    ])
    assert store.fingerprint("a", budget=16) == store.fingerprint("a", budget=16)


def test_observation_budget_prevents_unbounded_traversal():
    store = _chain_store()
    with pytest.raises(MatchBudgetExceeded):
        store.fingerprint("root", budget=1)


def test_post_commit_events_are_bounded_and_observer_failure_cannot_rollback():
    store = _chain_store()
    events = []
    unsubscribe = store.subscribe(events.append)
    store.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("observer")))
    store.commit(store.revision, create=[
        Cell("new", NULL_CELL_ID, NULL_CELL_ID, b"new")
    ])
    assert store.read("new").atom == b"new"
    assert events[-1].revision == store.revision
    assert events[-1].touched == frozenset({"new"})
    assert store.listener_failures() == ("RuntimeError: observer",)
    unsubscribe()
    store.commit(store.revision, replace=[
        Cell("new", NULL_CELL_ID, NULL_CELL_ID, b"changed")
    ])
    assert len(events) == 1


def test_overlay_depth_is_bounded_without_mutating_older_snapshots():
    store = CellStore()
    original = store.snapshot()
    for index in range(100):
        store.commit(store.revision, create=(Cell(
            "cell-%s" % index,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(index).encode("ascii"),
        ),))

    current = store.snapshot()
    assert set(original.cells) == {NULL_CELL_ID}
    assert len(current.cells) == 101
    assert all(
        current.cells["cell-%s" % index].atom == str(index).encode("ascii")
        for index in range(100)
    )


def test_dense_snapshot_reuses_the_bounded_persistent_read_view():
    store = CellStore()
    store._COPY_ON_COMMIT_CELL_LIMIT = 1
    for index in range(4):
        store.commit(store.revision, create=(Cell(
            "dense-cell-%s" % index,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(index).encode("ascii"),
        ),))

    layered = store.snapshot()
    dense = store.dense_snapshot()

    assert dense.revision == layered.revision == store.revision
    assert dict(dense.cells) == dict(layered.cells)
    assert dense.cells is layered.cells
    assert store.snapshot().cells is layered.cells
    with pytest.raises(TypeError):
        dense.cells["forbidden"] = Cell(
            "forbidden", NULL_CELL_ID, NULL_CELL_ID, b"forbidden"
        )


def test_dense_snapshot_is_cached_per_revision_and_invalidated_by_commit():
    store = CellStore()
    store._COPY_ON_COMMIT_CELL_LIMIT = 1
    store.commit(store.revision, create=(Cell(
        "dense-cache-a", NULL_CELL_ID, NULL_CELL_ID, b"a"
    ),))

    first = store.dense_snapshot()
    second = store.dense_snapshot()

    assert second is first
    store.commit(store.revision, create=(Cell(
        "dense-cache-b", NULL_CELL_ID, NULL_CELL_ID, b"b"
    ),))
    current = store.dense_snapshot()

    assert current is not first
    assert current.revision == first.revision + 1
    assert "dense-cache-b" in current.cells
    assert "dense-cache-b" not in first.cells


def test_candidate_overlay_is_immutable_and_preserves_its_base_snapshot():
    from nodelang.universal_cell import overlay_read_snapshot

    store = CellStore()
    store.commit(store.revision, create=(Cell(
        "overlay-existing", NULL_CELL_ID, NULL_CELL_ID, b"before"
    ),))
    base = store.dense_snapshot()
    candidate = overlay_read_snapshot(
        base,
        create=(Cell(
            "overlay-created", NULL_CELL_ID, NULL_CELL_ID, b"created"
        ),),
        replace=(Cell(
            "overlay-existing", NULL_CELL_ID, NULL_CELL_ID, b"after"
        ),),
    )

    assert candidate.revision == base.revision + 1
    assert candidate.cells["overlay-existing"].atom == b"after"
    assert candidate.cells["overlay-created"].atom == b"created"
    assert base.cells["overlay-existing"].atom == b"before"
    assert "overlay-created" not in base.cells
    assert store.snapshot().cells["overlay-existing"].atom == b"before"
    with pytest.raises(TypeError):
        candidate.cells["forbidden"] = Cell(
            "forbidden", NULL_CELL_ID, NULL_CELL_ID, b"forbidden"
        )
