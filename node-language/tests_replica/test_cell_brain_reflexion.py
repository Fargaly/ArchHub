"""Courts for reflexion: a failure closes only when a control exists."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_reflexion import (
    CONTROLLED,
    LEDGER_ROOT,
    OPEN,
    RECURRED,
    control_failure,
    failed_controls,
    occurrences,
    read_reflexion,
    record_failure,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

SIGNATURE = "group-settle-timeout"


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell("evidence:court-log", NULL_CELL_ID, NULL_CELL_ID, b"group settle timeout"),
        Cell("control:visibility-follows-members", NULL_CELL_ID, NULL_CELL_ID, b"court"),
        Cell("control:second-attempt", NULL_CELL_ID, NULL_CELL_ID, b"court"),
    ))
    return store


def _record(store, what="group reported success and the canvas did not move"):
    return record_failure(
        store,
        signature=SIGNATURE,
        what_happened=what,
        evidence_roots=("evidence:court-log",),
    )


def test_a_recorded_failure_carries_its_evidence_and_opens():
    store = _store()
    root = _record(store)
    entry = read_reflexion(store.snapshot(), root)
    assert entry.signature == SIGNATURE
    assert entry.evidence_roots == ("evidence:court-log",)
    assert entry.state == OPEN
    assert entry.root_cause is None


def test_a_failure_without_evidence_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        record_failure(
            store, signature=SIGNATURE, what_happened="it broke", evidence_roots=(),
        )


def test_a_failure_without_a_signature_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        record_failure(
            store, signature="   ", what_happened="it broke",
            evidence_roots=("evidence:court-log",),
        )


def test_a_root_cause_with_no_control_cannot_close_it_and_nothing_changes():
    store = _store()
    root = _record(store)
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        control_failure(store, root, root_cause="the view was never told", control_roots=())
    assert store.snapshot().revision == before
    assert read_reflexion(store.snapshot(), root).state == OPEN


def test_a_control_with_no_root_cause_is_refused():
    store = _store()
    root = _record(store)
    with pytest.raises(InvalidCell):
        control_failure(
            store, root, root_cause="  ",
            control_roots=("control:visibility-follows-members",),
        )


def test_naming_the_cause_and_the_control_closes_it():
    store = _store()
    root = _record(store)
    assert control_failure(
        store, root,
        root_cause="grouping never updated what the view can see",
        control_roots=("control:visibility-follows-members",),
    ) == CONTROLLED
    entry = read_reflexion(store.snapshot(), root)
    assert entry.state == CONTROLLED
    assert entry.control_roots == ("control:visibility-follows-members",)
    assert entry.root_cause.startswith("grouping never updated")


def test_a_controlled_failure_cannot_be_closed_twice():
    store = _store()
    root = _record(store)
    control_failure(
        store, root, root_cause="cause",
        control_roots=("control:visibility-follows-members",),
    )
    with pytest.raises(InvalidCell):
        control_failure(
            store, root, root_cause="cause",
            control_roots=("control:second-attempt",),
        )


def test_the_same_failure_again_is_a_recurrence_not_a_new_problem():
    store = _store()
    first = _record(store)
    control_failure(
        store, first, root_cause="cause",
        control_roots=("control:visibility-follows-members",),
    )
    second = _record(store, "it happened again")
    assert read_reflexion(store.snapshot(), second).state == RECURRED
    assert len(occurrences(store.snapshot(), SIGNATURE)) == 2


def test_a_recurrence_names_the_control_that_did_not_work():
    store = _store()
    first = _record(store)
    control_failure(
        store, first, root_cause="cause",
        control_roots=("control:visibility-follows-members",),
    )
    _record(store, "it happened again")
    assert failed_controls(store.snapshot(), SIGNATURE) == (
        "control:visibility-follows-members",
    )


def test_one_occurrence_blames_no_control():
    store = _store()
    _record(store)
    assert failed_controls(store.snapshot(), SIGNATURE) == ()


def test_no_ledger_remembers_nothing():
    store = CellStore()
    assert LEDGER_ROOT not in store.snapshot().cells
    assert occurrences(store.snapshot(), SIGNATURE) == ()
