"""Forcing tests for the Universal CellStore atomic revision boundary.

The ignored runtime copy tested the retired typed ``Store``. This authority
court keeps the useful concurrency concern but binds it to the four-field
CellStore: commits are optimistic, serialized, revision-addressed transactions.
"""
from __future__ import annotations

import threading

import pytest

from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
)


def _leaf(root_id: str, atom: bytes) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def test_concurrent_commits_share_one_atomic_cellstore_revision_lock():
    store = CellStore()
    entered_guard = threading.Event()
    release_guard = threading.Event()
    guarded_done = threading.Event()
    competing_done = threading.Event()
    guarded_errors: list[BaseException] = []
    competing_errors: list[BaseException] = []

    def guard() -> None:
        entered_guard.set()
        if not release_guard.wait(timeout=5):
            raise TimeoutError("CellStore concurrency court did not release")

    def guarded_commit() -> None:
        try:
            store.commit(
                0,
                create=(_leaf("cellstore:concurrent:a", b"a"),),
                precommit_guard=guard,
            )
        except BaseException as exc:
            guarded_errors.append(exc)
        finally:
            guarded_done.set()

    def competing_commit() -> None:
        try:
            store.commit(0, create=(_leaf("cellstore:concurrent:b", b"b"),))
        except BaseException as exc:
            competing_errors.append(exc)
        finally:
            competing_done.set()

    guarded = threading.Thread(target=guarded_commit, name="cell-guarded")
    competing = threading.Thread(target=competing_commit, name="cell-competing")
    guarded.start()
    assert entered_guard.wait(timeout=5)
    competing.start()

    assert competing_done.wait(timeout=0.05) is False
    release_guard.set()
    guarded.join(timeout=5)
    competing.join(timeout=5)

    assert guarded.is_alive() is False
    assert competing.is_alive() is False
    assert guarded_errors == []
    assert len(competing_errors) == 1
    assert isinstance(competing_errors[0], Conflict)
    snapshot = store.snapshot()
    assert snapshot.revision == 1
    assert "cellstore:concurrent:a" in snapshot.cells
    assert "cellstore:concurrent:b" not in snapshot.cells
    assert store.revision_changes(1) == ("cellstore:concurrent:a",)


def test_snapshots_are_revision_bound_and_do_not_mutate_after_later_commits():
    store = CellStore()
    genesis = store.snapshot()
    first_revision = store.commit(
        0,
        create=(_leaf("cellstore:stable:a", b"first"),),
    )
    first = store.snapshot()
    second_revision = store.commit(
        first_revision,
        replace=(_leaf("cellstore:stable:a", b"second"),),
    )

    assert "cellstore:stable:a" not in genesis.cells
    assert first.revision == first_revision
    assert first.cells["cellstore:stable:a"].atom == b"first"
    assert store.at(first_revision).cells["cellstore:stable:a"].atom == b"first"
    assert store.at(second_revision).cells["cellstore:stable:a"].atom == b"second"
    assert store.revision_changes(second_revision) == ("cellstore:stable:a",)
    assert store.revision_chain_digest(first_revision) != (
        store.revision_chain_digest(second_revision)
    )
    with pytest.raises(TypeError):
        first.cells["cellstore:stable:b"] = _leaf("cellstore:stable:b", b"bad")
