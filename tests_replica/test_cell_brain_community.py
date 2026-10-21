"""Courts for incoming: quarantined on arrival, visible only once judged."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_community import (
    ADMITTED,
    COMMUNITY_ROOT,
    REJECTED,
    admitted,
    judge,
    quarantine,
    receive,
    rejected,
    subscribe,
    subscriptions,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

PEER = "firm:peer-studio"
STRANGER = "firm:stranger"
CLAIM = "revision clouds go on the changed region only"


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(PEER, NULL_CELL_ID, NULL_CELL_ID, b"peer studio"),
        Cell(STRANGER, NULL_CELL_ID, NULL_CELL_ID, b"stranger"),
    ))
    subscribe(store, PEER)
    return store


def test_subscribing_is_agreeing_to_hear_not_to_believe():
    store = _store()
    assert subscriptions(store.snapshot()) == (PEER,)
    root = receive(store, peer_root=PEER, claim=CLAIM)
    assert [e.root_id for e in quarantine(store.snapshot())] == [root]
    assert admitted(store.snapshot()) == ()


def test_nothing_is_accepted_from_a_peer_we_never_subscribed_to():
    store = _store()
    with pytest.raises(InvalidCell):
        receive(store, peer_root=STRANGER, claim=CLAIM)


def test_a_peer_the_graph_does_not_hold_cannot_be_subscribed_to():
    store = _store()
    with pytest.raises(InvalidCell):
        subscribe(store, "firm:ghost")


def test_subscribing_twice_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        subscribe(store, PEER)


def test_an_empty_claim_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        receive(store, peer_root=PEER, claim="   ")


def test_a_claim_that_is_actually_a_credential_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        receive(
            store, peer_root=PEER,
            claim="ah_live_9f3c1b7e5d2a8460bb17e4c9f0d3a25e",
        )


def test_admitting_makes_it_visible_and_leaves_quarantine_empty():
    store = _store()
    root = receive(store, peer_root=PEER, claim=CLAIM)
    assert judge(store, root, admit=True) == ADMITTED
    assert [e.claim for e in admitted(store.snapshot())] == [CLAIM]
    assert quarantine(store.snapshot()) == ()


def test_rejecting_keeps_the_record_and_never_makes_it_visible():
    store = _store()
    root = receive(store, peer_root=PEER, claim=CLAIM)
    assert judge(store, root, admit=False) == REJECTED
    assert admitted(store.snapshot()) == ()
    assert [e.claim for e in rejected(store.snapshot())] == [CLAIM]


def test_the_same_claim_from_the_same_peer_is_not_argued_twice():
    store = _store()
    receive(store, peer_root=PEER, claim=CLAIM)
    with pytest.raises(InvalidCell):
        receive(store, peer_root=PEER, claim=CLAIM)


def test_a_judged_item_cannot_be_judged_again():
    store = _store()
    root = receive(store, peer_root=PEER, claim=CLAIM)
    judge(store, root, admit=True)
    with pytest.raises(InvalidCell):
        judge(store, root, admit=False)


def test_judging_something_that_never_arrived_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        judge(store, "app:brain:community:incoming:nowhere", admit=True)


def test_no_community_hears_nothing():
    store = CellStore()
    assert COMMUNITY_ROOT not in store.snapshot().cells
    assert subscriptions(store.snapshot()) == ()
    assert admitted(store.snapshot()) == ()
