"""Pure source-assembly recording and opaque Cell identity remapping."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .cell_protocols import compose_relation_cells
from .unified_authority import _new_id
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell


class SourceCellBatch:
    """CellBatch-compatible recorder with no Store or persistence authority."""

    def __init__(self) -> None:
        self._cells: dict[str, Cell] = {}

    @property
    def cells(self) -> tuple[Cell, ...]:
        return tuple(self._cells.values())

    def add(self, cell: Cell) -> str:
        if cell.id in self._cells:
            raise InvalidCell("source assembly Cell identity is duplicated")
        self._cells[cell.id] = cell
        return cell.id

    def relation(
        self,
        members: Iterable[tuple[str, str]],
        *,
        relation_id: str | None = None,
    ):
        relation = compose_relation_cells(members, relation_id=relation_id)
        for cell in relation.cells:
            self.add(cell)
        return relation.build


def remap_source_cells(
    source_cells: Iterable[Cell],
) -> tuple[tuple[Cell, ...], dict[str, str]]:
    """Replace source-local names with fresh opaque identities exactly once."""
    cells = tuple(source_cells)
    source_ids = {cell.id for cell in cells}
    if len(source_ids) != len(cells):
        raise InvalidCell("source assembly identities are duplicated")
    for cell in cells:
        for linked in (cell.link0, cell.link1):
            if linked != NULL_CELL_ID and linked not in source_ids:
                raise InvalidCell("source assembly has an external graph link")
    identities = {source_id: _new_id() for source_id in source_ids}
    mapped = tuple(
        Cell(
            identities[cell.id],
            NULL_CELL_ID if cell.link0 == NULL_CELL_ID else identities[cell.link0],
            NULL_CELL_ID if cell.link1 == NULL_CELL_ID else identities[cell.link1],
            cell.atom,
        )
        for cell in cells
    )
    return mapped, identities


def source_modules_digest(version: str, modules: Iterable[object]) -> str:
    """Bind an installed assembly to the exact source modules that compose it."""
    digest = hashlib.sha256()
    digest.update(version.encode("utf-8"))
    for module in modules:
        name = str(getattr(module, "__name__", ""))
        filename = str(getattr(module, "__file__", ""))
        if not name or not filename:
            raise InvalidCell("source assembly module provenance is missing")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(Path(filename).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


__all__ = [
    "SourceCellBatch",
    "remap_source_cells",
    "source_modules_digest",
]
