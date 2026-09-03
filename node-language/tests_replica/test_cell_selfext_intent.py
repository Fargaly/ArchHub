"""Courts for the ask: the gate is structural, not advisory."""
from __future__ import annotations

import pytest

from nodelang.cell_selfext_intent import (
    INTENTS_ROOT,
    ask,
    assert_may_build,
    atomize,
    grant_scope,
    read_intent,
    record_library_search,
    requirement_tree,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "identity:founder"
OTHER = "identity:other"
INTENT = "intent:add-a-cost-node"
IN_SCOPE = "domain:nodes"
ALSO_IN = "domain:canvas"
OUT_OF_SCOPE = "domain:clients"
LIBRARY = "catalogue:node-library"


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode())
        for root in (FOUNDER, OTHER, IN_SCOPE, ALSO_IN, OUT_OF_SCOPE, LIBRARY)
    ))
    ask(store, intent_root=INTENT, text="add a cost node", asker_root=FOUNDER)
    return store


def test_asking_records_the_ask_and_grants_nothing():
    store = _store()
    intent = read_intent(store.snapshot(), INTENT)
    assert intent.text == "add a cost node"
    assert intent.granted_scope == ()
    assert intent.leaves == ()


def test_an_empty_intent_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        ask(store, intent_root="intent:blank", text="  ", asker_root=FOUNDER)


def test_an_intent_with_no_granted_scope_cannot_become_work():
    store = _store()
    with pytest.raises(InvalidCell):
        atomize(store, INTENT, leaf_roots=(IN_SCOPE,))


def test_only_the_asker_may_grant_scope():
    store = _store()
    with pytest.raises(InvalidCell):
        grant_scope(store, INTENT, scope_roots=(IN_SCOPE,), granter_root=OTHER)
    assert read_intent(store.snapshot(), INTENT).granted_scope == ()


def test_granting_nothing_is_not_a_grant():
    store = _store()
    with pytest.raises(InvalidCell):
        grant_scope(store, INTENT, scope_roots=(), granter_root=FOUNDER)


def test_work_outside_the_granted_scope_is_refused():
    store = _store()
    grant_scope(store, INTENT, scope_roots=(IN_SCOPE,), granter_root=FOUNDER)
    with pytest.raises(InvalidCell):
        atomize(store, INTENT, leaf_roots=(IN_SCOPE, OUT_OF_SCOPE))
    assert requirement_tree(store.snapshot(), INTENT) == ()


def test_work_inside_the_granted_scope_becomes_the_requirement_tree():
    store = _store()
    grant_scope(
        store, INTENT, scope_roots=(IN_SCOPE, ALSO_IN), granter_root=FOUNDER)
    atomize(store, INTENT, leaf_roots=(IN_SCOPE, ALSO_IN))
    assert requirement_tree(store.snapshot(), INTENT) == (ALSO_IN, IN_SCOPE)


def test_nothing_is_built_before_anything_is_atomized():
    store = _store()
    grant_scope(store, INTENT, scope_roots=(IN_SCOPE,), granter_root=FOUNDER)
    with pytest.raises(InvalidCell):
        assert_may_build(store.snapshot(), INTENT)


def test_nothing_is_built_until_the_library_was_searched():
    store = _store()
    grant_scope(store, INTENT, scope_roots=(IN_SCOPE,), granter_root=FOUNDER)
    atomize(store, INTENT, leaf_roots=(IN_SCOPE,))
    with pytest.raises(InvalidCell):
        assert_may_build(store.snapshot(), INTENT)
    record_library_search(store, INTENT, searched_root=LIBRARY)
    assert assert_may_build(store.snapshot(), INTENT) is True


def test_a_search_must_name_what_was_searched():
    store = _store()
    with pytest.raises(InvalidCell):
        record_library_search(store, INTENT, searched_root="catalogue:imaginary")


def test_an_intent_that_does_not_exist_answers_nothing():
    store = _store()
    with pytest.raises(InvalidCell):
        read_intent(store.snapshot(), "intent:nowhere")


def test_no_intents_hold_nothing():
    store = CellStore()
    assert INTENTS_ROOT not in store.snapshot().cells
