"""Courts for fanout: redactions out, quarantine in, nothing written directly."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_community import admitted, quarantine, subscribe
from nodelang.cell_brain_fanout import fanout_apply, fanout_export, outbox
from nodelang.cell_brain_federation import create_firm, share_fact
from nodelang.cell_brain_ownership import bind_owner
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

OWNER = "identity:founder"
MATE = "identity:mate"
PEER = "firm:peer-studio"
FIRM = "firm:fargool"
FACT = "fact:day-rate"
SECOND = "fact:site"


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode())
        for root in (OWNER, MATE, PEER, FACT, SECOND)
    ))
    bind_owner(store, subject_root=FACT, owner_root=OWNER)
    bind_owner(store, subject_root=SECOND, owner_root=OWNER)
    create_firm(store, firm_root=FIRM, member_roots=(OWNER, MATE))
    return store


def test_the_outbox_holds_only_what_the_owner_shared():
    store = _store()
    assert outbox(store.snapshot(), FIRM) == ()
    share_fact(
        store, fact_root=FACT, firm_root=FIRM,
        sharer_root=OWNER, redaction="a day rate exists",
    )
    cards = outbox(store.snapshot(), FIRM)
    assert [c.fact_root for c in cards] == [FACT]


def test_export_carries_redactions_and_never_the_fact():
    store = _store()
    share_fact(
        store, fact_root=FACT, firm_root=FIRM,
        sharer_root=OWNER, redaction="a day rate exists",
    )
    exported = fanout_export(store.snapshot(), FIRM)
    assert exported == ("a day rate exists",)
    assert FACT not in exported


def test_export_lists_every_shared_fact_once():
    store = _store()
    for fact, redaction in ((FACT, "a day rate exists"), (SECOND, "a site exists")):
        share_fact(
            store, fact_root=fact, firm_root=FIRM,
            sharer_root=OWNER, redaction=redaction,
        )
    assert fanout_export(store.snapshot(), FIRM) == (
        "a day rate exists", "a site exists")


def test_applying_a_peer_card_lands_in_quarantine_not_in_memory():
    store = _store()
    subscribe(store, PEER)
    fanout_apply(store, peer_root=PEER, claims=("their day rate exists",))
    assert [e.claim for e in quarantine(store.snapshot())] == [
        "their day rate exists"]
    assert admitted(store.snapshot()) == ()


def test_applying_from_an_unsubscribed_peer_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        fanout_apply(store, peer_root=PEER, claims=("anything",))


def test_applying_the_same_card_twice_is_refused():
    store = _store()
    subscribe(store, PEER)
    fanout_apply(store, peer_root=PEER, claims=("their day rate exists",))
    with pytest.raises(InvalidCell):
        fanout_apply(store, peer_root=PEER, claims=("their day rate exists",))


def test_an_empty_firm_has_nothing_to_send():
    store = _store()
    with pytest.raises(InvalidCell):
        outbox(store.snapshot(), "firm:nowhere")
