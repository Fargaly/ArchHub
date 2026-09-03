"""Courts for sessions: the save guard, the debounce, and the one-way state."""
from __future__ import annotations

import pytest

from nodelang.cell_session_state import (
    ACTIVE,
    CLOSED,
    DRAFT,
    SESSIONS_ROOT,
    autosave,
    move_to,
    open_session,
    pin,
    read_session,
    replay,
    save,
    set_parameter,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

OWNER = "identity:founder"
SESSION = "session:jumeirah"


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(OWNER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    open_session(store, session_root=SESSION, owner_root=OWNER)
    return store


def test_a_new_session_is_a_draft_owned_by_who_opened_it():
    store = _store()
    session = read_session(store.snapshot(), SESSION)
    assert session.state == DRAFT
    assert session.owner_root == OWNER


def test_a_session_moves_only_forward():
    store = _store()
    assert move_to(store, SESSION, ACTIVE) == ACTIVE
    with pytest.raises(InvalidCell):
        move_to(store, SESSION, DRAFT)
    assert move_to(store, SESSION, CLOSED) == CLOSED
    with pytest.raises(InvalidCell):
        move_to(store, SESSION, ACTIVE)


def test_the_parameter_pool_holds_and_replaces():
    store = _store()
    set_parameter(store, SESSION, key="rate", value="900")
    assert read_session(store.snapshot(), SESSION).parameters["rate"] == "900"
    set_parameter(store, SESSION, key="rate", value="950")
    assert read_session(store.snapshot(), SESSION).parameters["rate"] == "950"


def test_a_parameter_without_a_name_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        set_parameter(store, SESSION, key="  ", value="x")


def test_a_save_round_trips_before_it_is_accepted():
    store = _store()
    save(store, SESSION, payload="nodes and wires")
    assert replay(store.snapshot(), SESSION) == ("nodes and wires",)


def test_saving_nothing_would_erase_the_session_and_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        save(store, SESSION, payload="")


def test_autosave_writes_once_and_then_stops_repeating_itself():
    store = _store()
    assert autosave(store, SESSION, payload="v1") is True
    settled = store.snapshot().revision
    assert autosave(store, SESSION, payload="v1") is False
    assert store.snapshot().revision == settled


def test_autosave_writes_again_when_the_payload_actually_changes():
    store = _store()
    autosave(store, SESSION, payload="v1")
    assert autosave(store, SESSION, payload="v2") is True
    assert replay(store.snapshot(), SESSION) == ("v1", "v2")


def test_the_same_payload_cannot_be_saved_twice():
    store = _store()
    save(store, SESSION, payload="v1")
    with pytest.raises(InvalidCell):
        save(store, SESSION, payload="v1")


def test_a_closed_session_accepts_nothing_more():
    store = _store()
    move_to(store, SESSION, ACTIVE)
    move_to(store, SESSION, CLOSED)
    with pytest.raises(InvalidCell):
        save(store, SESSION, payload="late")
    with pytest.raises(InvalidCell):
        set_parameter(store, SESSION, key="rate", value="1")


def test_a_session_can_be_pinned_once():
    store = _store()
    assert pin(store, SESSION) is True
    assert read_session(store.snapshot(), SESSION).pinned is True
    with pytest.raises(InvalidCell):
        pin(store, SESSION)


def test_replay_is_every_save_in_order():
    store = _store()
    for payload in ("v1", "v2", "v3"):
        save(store, SESSION, payload=payload)
    assert replay(store.snapshot(), SESSION) == ("v1", "v2", "v3")


def test_a_session_that_does_not_exist_answers_nothing():
    store = _store()
    with pytest.raises(InvalidCell):
        read_session(store.snapshot(), "session:nowhere")


def test_no_sessions_hold_nothing():
    store = CellStore()
    assert SESSIONS_ROOT not in store.snapshot().cells
