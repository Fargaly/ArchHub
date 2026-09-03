from __future__ import annotations

from dataclasses import replace
import uuid

import pytest

from nodelang.cell_sequence import build_cell_sequence, read_cell_sequence
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    overlay_read_snapshot,
)


def _item(label: str) -> Cell:
    return Cell(str(uuid.uuid4()), NULL_CELL_ID, NULL_CELL_ID, label.encode("ascii"))


def test_sequence_is_one_generic_cell_per_item_and_round_trips_order():
    store = CellStore()
    items = tuple(_item(label) for label in ("first", "second", "third"))
    root, sequence = build_cell_sequence(item.id for item in items)
    store.commit(store.revision, create=(*items, *sequence))

    assert len(sequence) == len(items)
    assert read_cell_sequence(store.snapshot(), root) == tuple(
        item.id for item in items
    )
    assert all(cell.atom == b"" for cell in sequence)
    assert tuple(cell.link0 for cell in sequence) == tuple(item.id for item in items)


def test_empty_sequence_is_the_null_cell_without_persisted_scaffolding():
    root, cells = build_cell_sequence(())

    assert root == NULL_CELL_ID
    assert cells == ()
    assert read_cell_sequence(CellStore().snapshot(), root) == ()


def test_repeating_the_same_sequence_does_not_derive_semantic_identity_from_content():
    item = _item("same")
    first_root, first = build_cell_sequence((item.id,))
    second_root, second = build_cell_sequence((item.id,))

    assert first_root != second_root
    assert first[0].id != second[0].id


def test_sequence_rejects_cycles_dangling_items_and_budget_overrun():
    store = CellStore()
    items = tuple(_item(label) for label in ("a", "b"))
    root, sequence = build_cell_sequence(item.id for item in items)
    store.commit(store.revision, create=(*items, *sequence))
    snapshot = store.snapshot()

    cycle = overlay_read_snapshot(
        snapshot,
        replace=(replace(sequence[-1], link1=root),),
    )
    with pytest.raises(InvalidCell, match="cycle"):
        read_cell_sequence(cycle, root)

    dangling = overlay_read_snapshot(
        snapshot,
        replace=(replace(sequence[0], link0=str(uuid.uuid4())),),
    )
    with pytest.raises(InvalidCell, match="invalid item"):
        read_cell_sequence(dangling, root)

    with pytest.raises(InvalidCell, match="budget"):
        read_cell_sequence(snapshot, root, budget=1)
