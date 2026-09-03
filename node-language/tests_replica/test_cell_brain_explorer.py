"""Courts for browsing memory: folders are derived, never maintained."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_explorer import (
    SHELF_ROOT,
    folders,
    open_folder,
    shelve_fact,
    total_remembered,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell("fact:" + name, NULL_CELL_ID, NULL_CELL_ID, name.encode())
        for name in ("site", "client", "rate", "loose")
    ))
    return store


def _shelved(store):
    shelve_fact(store, fact_root="fact:site", kind="projects", title="Jumeirah villa")
    shelve_fact(store, fact_root="fact:client", kind="projects", title="Harbor package")
    shelve_fact(store, fact_root="fact:rate", kind="about you", title="Day rate")
    return store


def test_folders_are_derived_from_the_facts_that_exist():
    store = _shelved(_store())
    found = folders(store.snapshot())
    assert [(f.kind, f.count) for f in found] == [("about you", 1), ("projects", 2)]


def test_removing_a_fact_shrinks_its_folder_in_the_same_breath():
    store = _shelved(_store())
    snapshot = store.snapshot()
    store.commit(snapshot.revision, replace=(
        Cell("fact:client", NULL_CELL_ID, NULL_CELL_ID, b"client"),
    ))
    assert total_remembered(store.snapshot()) == 3


def test_a_fact_with_no_kind_cannot_be_shelved():
    store = _store()
    with pytest.raises(InvalidCell):
        shelve_fact(store, fact_root="fact:site", kind="  ", title="Villa")


def test_a_fact_with_no_title_cannot_be_shelved():
    store = _store()
    with pytest.raises(InvalidCell):
        shelve_fact(store, fact_root="fact:site", kind="projects", title=" ")


def test_a_fact_the_graph_does_not_hold_cannot_be_shelved():
    store = _store()
    with pytest.raises(InvalidCell):
        shelve_fact(store, fact_root="fact:imaginary", kind="projects", title="Ghost")


def test_the_same_fact_cannot_be_shelved_twice():
    store = _shelved(_store())
    with pytest.raises(InvalidCell):
        shelve_fact(store, fact_root="fact:site", kind="projects", title="Again")


def test_opening_a_folder_lists_it_by_title():
    store = _shelved(_store())
    inside = open_folder(store.snapshot(), "projects")
    assert [item.title for item in inside] == ["Harbor package", "Jumeirah villa"]


def test_a_folder_that_holds_nothing_does_not_exist():
    store = _shelved(_store())
    with pytest.raises(InvalidCell):
        open_folder(store.snapshot(), "invoices")


def test_an_unshelved_fact_is_in_no_folder():
    store = _shelved(_store())
    everything = [root for f in folders(store.snapshot()) for root in f.fact_roots]
    assert "fact:loose" not in everything


def test_no_shelf_shows_no_folders():
    store = CellStore()
    assert SHELF_ROOT not in store.snapshot().cells
    assert folders(store.snapshot()) == ()
    assert total_remembered(store.snapshot()) == 0
