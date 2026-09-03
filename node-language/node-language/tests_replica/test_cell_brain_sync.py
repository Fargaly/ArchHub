"""Courts for sync: order cannot change the answer, and a replay is a no-op."""
from __future__ import annotations

import itertools

import pytest

from nodelang.cell_brain_sync import (
    apply_fragments,
    converged,
    export_since,
    held,
    make_fragment,
)
from nodelang.universal_cell import CellStore, InvalidCell

ROOTS = ("fact:rate", "fact:site")


def _fragments():
    return (
        make_fragment("fact:rate", "desktop", 1, "old rate"),
        make_fragment("fact:rate", "phone", 2, "new rate"),
        make_fragment("fact:site", "phone", 1, "Jumeirah"),
    )


def test_a_fragment_must_name_its_root_origin_and_clock():
    with pytest.raises(InvalidCell):
        make_fragment("", "desktop", 1, "x")
    with pytest.raises(InvalidCell):
        make_fragment("fact:rate", "  ", 1, "x")
    with pytest.raises(InvalidCell):
        make_fragment("fact:rate", "desktop", -1, "x")
    with pytest.raises(InvalidCell):
        make_fragment("fact:rate", "desktop", True, "x")


def test_the_later_clock_wins():
    store = CellStore()
    apply_fragments(store, _fragments())
    assert held(store.snapshot(), "fact:rate").value == "new rate"


def test_an_older_fragment_never_overwrites_a_newer_one():
    store = CellStore()
    apply_fragments(store, (make_fragment("fact:rate", "phone", 2, "new rate"),))
    apply_fragments(store, (make_fragment("fact:rate", "desktop", 1, "old rate"),))
    assert held(store.snapshot(), "fact:rate").value == "new rate"


def test_a_tie_is_broken_on_origin_not_on_who_spoke_first():
    left, right = CellStore(), CellStore()
    a = make_fragment("fact:rate", "alpha", 5, "from alpha")
    b = make_fragment("fact:rate", "zulu", 5, "from zulu")
    apply_fragments(left, (a, b))
    apply_fragments(right, (b, a))
    assert held(left.snapshot(), "fact:rate") == held(right.snapshot(), "fact:rate")
    assert held(left.snapshot(), "fact:rate").origin == "zulu"


def test_every_arrival_order_reaches_the_same_brain():
    reference = None
    for order in itertools.permutations(_fragments()):
        store = CellStore()
        apply_fragments(store, order)
        snapshot = store.snapshot()
        state = tuple(held(snapshot, root) for root in ROOTS)
        if reference is None:
            reference = state
        assert state == reference


def test_applying_the_same_batch_again_changes_nothing():
    store = CellStore()
    apply_fragments(store, _fragments())
    settled = store.snapshot().revision
    assert apply_fragments(store, _fragments()) == 0
    assert store.snapshot().revision == settled


def test_two_replicas_converge_after_exchanging_what_they_hold():
    desktop, phone = CellStore(), CellStore()
    apply_fragments(desktop, (make_fragment("fact:rate", "desktop", 1, "old rate"),))
    apply_fragments(phone, (
        make_fragment("fact:rate", "phone", 2, "new rate"),
        make_fragment("fact:site", "phone", 1, "Jumeirah"),
    ))
    assert not converged(desktop.snapshot(), phone.snapshot(), ROOTS)
    apply_fragments(desktop, export_since(phone.snapshot(), ROOTS))
    apply_fragments(phone, export_since(desktop.snapshot(), ROOTS))
    assert converged(desktop.snapshot(), phone.snapshot(), ROOTS)


def test_export_carries_provenance_not_just_the_value():
    store = CellStore()
    apply_fragments(store, _fragments())
    exported = export_since(store.snapshot(), ROOTS)
    assert {(f.root_id, f.origin, f.clock) for f in exported} == {
        ("fact:rate", "phone", 2), ("fact:site", "phone", 1),
    }


def test_export_since_a_clock_leaves_older_facts_alone():
    store = CellStore()
    apply_fragments(store, _fragments())
    assert [f.root_id for f in export_since(store.snapshot(), ROOTS, 2)] == ["fact:rate"]


def test_only_a_fragment_can_be_merged():
    store = CellStore()
    with pytest.raises(InvalidCell):
        apply_fragments(store, ({"root_id": "fact:rate"},))


def test_an_unheld_root_reads_as_nothing_rather_than_a_guess():
    store = CellStore()
    assert held(store.snapshot(), "fact:rate") is None
