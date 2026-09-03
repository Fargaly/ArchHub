"""Courts for sharing: only the owner shares, and only a redaction crosses."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_federation import (
    FEDERATION_ROOT,
    create_firm,
    firm_members,
    share_fact,
    visible_to,
)
from nodelang.cell_brain_ownership import bind_owner
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "identity:founder"
PEER = "identity:peer"
OUTSIDER = "identity:outsider"
FACT = "fact:day-rate"
FIRM = "firm:fargool"


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode())
        for root in (FOUNDER, PEER, OUTSIDER, FACT)
    ))
    bind_owner(store, subject_root=FACT, owner_root=FOUNDER)
    create_firm(store, firm_root=FIRM, member_roots=(FOUNDER, PEER))
    return store


def test_a_firm_is_the_people_in_it():
    store = _store()
    assert firm_members(store.snapshot(), FIRM) == (FOUNDER, PEER)


def test_an_empty_firm_cannot_exist():
    store = _store()
    with pytest.raises(InvalidCell):
        create_firm(store, firm_root="firm:empty", member_roots=())


def test_a_member_the_graph_does_not_hold_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        create_firm(store, firm_root="firm:ghosts", member_roots=("identity:ghost",))


def test_the_owner_can_share_a_redaction():
    store = _store()
    share_fact(
        store, fact_root=FACT, firm_root=FIRM,
        sharer_root=FOUNDER, redaction="a day rate exists",
    )
    seen = visible_to(store.snapshot(), PEER)
    assert [s.fact_root for s in seen] == [FACT]
    assert seen[0].redaction == "a day rate exists"


def test_someone_who_does_not_own_it_cannot_share_it():
    store = _store()
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root=FACT, firm_root=FIRM,
            sharer_root=PEER, redaction="a day rate exists",
        )
    assert visible_to(store.snapshot(), PEER) == ()


def test_sharing_with_no_redaction_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root=FACT, firm_root=FIRM,
            sharer_root=FOUNDER, redaction="   ",
        )


def test_a_redaction_that_is_actually_a_credential_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root=FACT, firm_root=FIRM, sharer_root=FOUNDER,
            redaction="ah_live_9f3c1b7e5d2a8460bb17e4c9f0d3a25e",
        )


def test_an_unowned_fact_cannot_be_shared():
    store = _store()
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        Cell("fact:orphan", NULL_CELL_ID, NULL_CELL_ID, b"orphan"),))
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root="fact:orphan", firm_root=FIRM,
            sharer_root=FOUNDER, redaction="something",
        )


def test_someone_outside_the_firm_sees_nothing():
    store = _store()
    share_fact(
        store, fact_root=FACT, firm_root=FIRM,
        sharer_root=FOUNDER, redaction="a day rate exists",
    )
    assert visible_to(store.snapshot(), OUTSIDER) == ()


def test_the_same_fact_cannot_be_shared_twice_with_one_firm():
    store = _store()
    share_fact(
        store, fact_root=FACT, firm_root=FIRM,
        sharer_root=FOUNDER, redaction="a day rate exists",
    )
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root=FACT, firm_root=FIRM,
            sharer_root=FOUNDER, redaction="again",
        )


def test_sharing_with_a_firm_that_does_not_exist_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        share_fact(
            store, fact_root=FACT, firm_root="firm:nowhere",
            sharer_root=FOUNDER, redaction="something",
        )


def test_no_federation_shows_nothing():
    store = CellStore()
    assert FEDERATION_ROOT not in store.snapshot().cells
    assert visible_to(store.snapshot(), FOUNDER) == ()
