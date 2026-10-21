"""Courts for ownership: one owner, no default, consent to move."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_ownership import (
    CONSENT_ROLE,
    REGISTRY_ROOT,
    bind_owner,
    owned_by,
    read_owner,
    transfer_owner,
)
from nodelang.cell_protocols import prepare_append_relation_members
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "identity:founder"
PEER = "identity:peer"
FACT = "fact:site-visit"


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(FOUNDER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),
        Cell(PEER, NULL_CELL_ID, NULL_CELL_ID, b"peer"),
        Cell(FACT, NULL_CELL_ID, NULL_CELL_ID, b"site visit"),
        Cell("fact:other", NULL_CELL_ID, NULL_CELL_ID, b"other"),
    ))
    return store


def _consent(store, root_id, *participants):
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, root_id,
        tuple((CONSENT_ROLE, item) for item in participants), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return root_id


def test_a_root_gets_exactly_one_owner():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    assert read_owner(store.snapshot(), FACT) == FOUNDER


def test_an_unowned_root_raises_rather_than_assuming_an_owner():
    store = _store()
    with pytest.raises(InvalidCell):
        read_owner(store.snapshot(), FACT)


def test_a_second_owner_is_refused():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    with pytest.raises(InvalidCell):
        bind_owner(store, subject_root=FACT, owner_root=PEER)
    assert read_owner(store.snapshot(), FACT) == FOUNDER


def test_an_owner_the_graph_does_not_hold_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        bind_owner(store, subject_root=FACT, owner_root="identity:ghost")


def test_a_transfer_without_consent_is_refused_and_nothing_moves():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        transfer_owner(
            store, subject_root=FACT, to_owner_root=PEER,
            consent_root="consent:missing",
        )
    assert store.snapshot().revision == before
    assert read_owner(store.snapshot(), FACT) == FOUNDER


def test_consent_that_does_not_name_this_owner_is_refused():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    _consent(store, "consent:wrong", PEER, FACT)
    with pytest.raises(InvalidCell):
        transfer_owner(
            store, subject_root=FACT, to_owner_root=PEER,
            consent_root="consent:wrong",
        )
    assert read_owner(store.snapshot(), FACT) == FOUNDER


def test_consent_that_does_not_name_this_subject_is_refused():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    _consent(store, "consent:elsewhere", FOUNDER, "fact:other")
    with pytest.raises(InvalidCell):
        transfer_owner(
            store, subject_root=FACT, to_owner_root=PEER,
            consent_root="consent:elsewhere",
        )


def test_a_consented_transfer_moves_ownership_and_records_the_consent():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    _consent(store, "consent:handover", FOUNDER, FACT)
    assert transfer_owner(
        store, subject_root=FACT, to_owner_root=PEER,
        consent_root="consent:handover",
    ) == PEER
    assert read_owner(store.snapshot(), FACT) == PEER
    assert owned_by(store.snapshot(), FOUNDER) == ()
    assert owned_by(store.snapshot(), PEER) == (FACT,)


def test_transferring_to_the_current_owner_is_refused():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    _consent(store, "consent:noop", FOUNDER, FACT)
    with pytest.raises(InvalidCell):
        transfer_owner(
            store, subject_root=FACT, to_owner_root=FOUNDER,
            consent_root="consent:noop",
        )


def test_an_owner_sees_everything_they_hold():
    store = _store()
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    bind_owner(store, subject_root="fact:other", owner_root=FOUNDER)
    assert owned_by(store.snapshot(), FOUNDER) == ("fact:other", FACT)


def test_no_registry_owns_nothing():
    store = CellStore()
    assert REGISTRY_ROOT not in store.snapshot().cells
    assert owned_by(store.snapshot(), FOUNDER) == ()
