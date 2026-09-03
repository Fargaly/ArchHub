"""Courts for seats and invites: bound to an address, counted before given."""
from __future__ import annotations

import pytest

from nodelang.cell_users_seats import (
    FIRMS_ROOT,
    accept_invite,
    create_firm,
    invite,
    read_firm,
    token_is_readable,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

OWNER = "identity:founder"
MATE = "identity:mate"
STRANGER = "identity:stranger"
FIRM = "firm:fargool"
EMAIL = "mate@example.com"
TOKEN = "invite-9f3c1b7e5d2a"


def _store(seats=2):
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode())
        for root in (OWNER, MATE, STRANGER)
    ))
    create_firm(store, firm_root=FIRM, owner_root=OWNER, seats=seats)
    return store


def test_a_firm_buys_seats_and_the_owner_holds_the_first():
    store = _store()
    firm = read_firm(store.snapshot(), FIRM)
    assert (firm.seats, firm.seats_taken, firm.seats_free) == (2, 1, 1)
    assert firm.member_roots == (OWNER,)


def test_a_firm_with_no_seats_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        create_firm(store, firm_root="firm:free", owner_root=OWNER, seats=0)


def test_the_graph_never_holds_the_invite_token():
    store = _store()
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    assert token_is_readable(store.snapshot(), TOKEN) is False


def test_only_the_owner_may_invite():
    store = _store()
    with pytest.raises(InvalidCell):
        invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=MATE)


def test_a_short_token_is_refused_as_guessable():
    store = _store()
    with pytest.raises(InvalidCell):
        invite(store, firm_root=FIRM, email=EMAIL, token="short", inviter_root=OWNER)


def test_an_invite_without_a_real_address_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        invite(store, firm_root=FIRM, email="nobody", token=TOKEN, inviter_root=OWNER)


def test_the_invited_address_accepts_and_takes_a_seat():
    store = _store()
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    accept_invite(
        store, firm_root=FIRM, email=EMAIL, token=TOKEN, member_root=MATE)
    firm = read_firm(store.snapshot(), FIRM)
    assert firm.member_roots == (OWNER, MATE)
    assert firm.seats_free == 0


def test_a_forwarded_token_from_another_address_opens_nothing():
    store = _store()
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    with pytest.raises(InvalidCell):
        accept_invite(
            store, firm_root=FIRM, email="stranger@example.com",
            token=TOKEN, member_root=STRANGER,
        )
    assert read_firm(store.snapshot(), FIRM).member_roots == (OWNER,)


def test_an_invite_cannot_be_accepted_twice():
    store = _store(seats=3)
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    accept_invite(
        store, firm_root=FIRM, email=EMAIL, token=TOKEN, member_root=MATE)
    with pytest.raises(InvalidCell):
        accept_invite(
            store, firm_root=FIRM, email=EMAIL, token=TOKEN, member_root=STRANGER)


def test_a_firm_cannot_be_invited_into_beyond_its_seats():
    store = _store(seats=1)
    with pytest.raises(InvalidCell):
        invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)


def test_someone_who_already_holds_a_seat_cannot_take_another():
    store = _store(seats=3)
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    with pytest.raises(InvalidCell):
        accept_invite(
            store, firm_root=FIRM, email=EMAIL, token=TOKEN, member_root=OWNER)


def test_an_invite_for_one_firm_does_not_open_another():
    store = _store(seats=3)
    create_firm(store, firm_root="firm:other", owner_root=OWNER, seats=3)
    invite(store, firm_root=FIRM, email=EMAIL, token=TOKEN, inviter_root=OWNER)
    with pytest.raises(InvalidCell):
        accept_invite(
            store, firm_root="firm:other", email=EMAIL,
            token=TOKEN, member_root=MATE,
        )


def test_no_firms_hold_nothing():
    store = CellStore()
    assert FIRMS_ROOT not in store.snapshot().cells
