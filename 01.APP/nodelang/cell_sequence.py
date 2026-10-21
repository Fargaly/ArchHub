"""A bounded generic sequence assembled directly from Universal Cells.

Each sequence Cell uses ``link0`` for the item identity and ``link1`` for the
next sequence Cell.  The structure is a reusable floor assembly; product
meaning is supplied by the graph relation that references the sequence root.
"""
from __future__ import annotations

from collections.abc import Iterable
import uuid

from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


def build_cell_sequence(items: Iterable[str]) -> tuple[str, tuple[Cell, ...]]:
    values = tuple(items)
    if any(type(value) is not str or value == NULL_CELL_ID for value in values):
        raise InvalidCell("cell sequence items must be non-null identities")
    if not values:
        return NULL_CELL_ID, ()
    roots = tuple(str(uuid.uuid4()) for _ in values)
    cells = tuple(
        Cell(
            root,
            item,
            roots[index + 1] if index + 1 < len(roots) else NULL_CELL_ID,
            b"",
        )
        for index, (root, item) in enumerate(zip(roots, values))
    )
    return roots[0], cells


def read_cell_sequence(
    snapshot: Snapshot,
    root: str,
    *,
    budget: int = 10_000,
) -> tuple[str, ...]:
    if root == NULL_CELL_ID:
        return ()
    if budget < 1:
        raise InvalidCell("cell sequence budget must be positive")
    values: list[str] = []
    seen: set[str] = set()
    cursor = root
    while cursor != NULL_CELL_ID:
        if len(values) >= budget:
            raise InvalidCell("cell sequence exceeded its traversal budget")
        if cursor in seen:
            raise InvalidCell("cell sequence contains a cycle")
        seen.add(cursor)
        cell = snapshot.cells.get(cursor)
        if (
            cell is None
            or cell.atom
            or cell.link0 == NULL_CELL_ID
            or cell.link0 not in snapshot.cells
        ):
            raise InvalidCell("cell sequence contains an invalid item")
        values.append(cell.link0)
        cursor = cell.link1
    return tuple(values)


__all__ = ["build_cell_sequence", "read_cell_sequence"]
