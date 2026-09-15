"""Prepare additive application structure without activating a successor authority.

The caller still owes current owner authorization, policy/protocol equivalence,
an atomic signed head and durable adoption provenance. This planner cannot
replace existing nodes or connections and performs no store mutations.
"""
from dataclasses import dataclass

from .cell_protocols import read_relation, prepare_append_relation_members
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID, Snapshot, _validate_cell


@dataclass(frozen=True, slots=True)
class ApplicationExtensionPlan:
    base_revision: int
    application_root: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]
    retained_incidence_ids: tuple[str, ...]


def prepare_application_extension(snapshot: Snapshot, application_root: str, *,
        successor_cells, members, budget: int = 10_000) -> ApplicationExtensionPlan:
    """Append successor membership while retaining source root and incidences.

    This is a trusted preparation primitive, not an authorization endpoint.
    Its output must be combined with the remaining adoption changes and verified
    immediately before the single revision-checked adoption commit.
    """
    if type(budget) is not int or not 1 <= budget <= 100_000:
        raise InvalidCell("application extension budget is invalid")
    if application_root == NULL_CELL_ID or application_root not in snapshot.cells:
        raise InvalidCell("application extension requires an existing non-null root")
    created = []
    for cell in successor_cells:
        if len(created) >= budget:
            raise InvalidCell("application extension exceeds its cell budget")
        if type(cell) is not Cell:
            raise InvalidCell("application extension requires Cells")
        _validate_cell(cell)
        created.append(cell)
    by_id = {cell.id: cell for cell in created}
    if (len(by_id) != len(created) or
            any(root in snapshot.cells for root in by_id)):
        raise InvalidCell("application extension cannot replace existing identities")
    for cell in created:
        if any(link != NULL_CELL_ID and link not in by_id and link not in snapshot.cells
                for link in (cell.link0, cell.link1)):
            raise InvalidCell("application extension has an unresolved link")
    pairs = []
    for pair in members:
        if len(pairs) >= budget:
            raise InvalidCell("application extension exceeds its membership budget")
        if (type(pair) not in (tuple, list) or len(pair) != 2 or
                any(type(root) is not str for root in pair)):
            raise InvalidCell("application extension membership is invalid")
        role, participant = pair
        if (participant not in by_id or
                (role not in by_id and role not in snapshot.cells) or role == NULL_CELL_ID):
            raise InvalidCell("application extension must attach new resolved structure")
        pairs.append((role, participant))
    if not pairs or len(set(pairs)) != len(pairs):
        raise InvalidCell("application extension memberships are empty or duplicated")
    old_members = read_relation(snapshot, application_root, budget=budget)
    patch = prepare_append_relation_members(snapshot, application_root, pairs, budget=budget)
    if any(cell.id in by_id or cell.id in snapshot.cells for cell in patch.create):
        raise InvalidCell("application extension incidence identity collision")
    return ApplicationExtensionPlan(snapshot.revision, application_root,
        (*created, *patch.create), patch.replace,
        tuple(member.incidence_id for member in old_members))
