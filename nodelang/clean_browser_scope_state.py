"""Persist the clean browser session's current scope inside the one graph."""
from __future__ import annotations

import json

from .cell_protocols import read_relation
from .unified_authority import (
    UnifiedAuthority,
    _typed_relation_cells,
    validate_composition,
)
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell


_SCOPE_LABEL = "clean-browser-scope"
_SCOPE_LABEL_ROOT = "app:label:clean-browser-scope"


def _scope_state_root(session_root: str) -> str:
    return "app:clean-browser-scope:%s" % session_root


def read_clean_browser_scope(
    authority: UnifiedAuthority,
    session_root: str,
) -> str | None:
    snapshot = authority.store.snapshot()
    root_id = _scope_state_root(session_root)
    if root_id not in snapshot.cells:
        return None
    validate_composition(authority, snapshot, root_id)
    members = read_relation(snapshot, root_id, budget=256)
    session_members = tuple(
        member.participant_id
        for member in members
        if member.role_id == authority.role("session")
    )
    scope_members = tuple(
        member.participant_id
        for member in members
        if member.role_id == authority.role("scope")
    )
    if session_members != (session_root,):
        raise InvalidCell("clean browser scope session drifted")
    if len(scope_members) != 1 or scope_members[0] not in snapshot.cells:
        raise InvalidCell("clean browser scope root is invalid")
    return scope_members[0]


def write_clean_browser_scope(
    authority: UnifiedAuthority,
    session_root: str,
    scope_root: str,
) -> int:
    snapshot = authority.store.snapshot()
    if session_root not in snapshot.cells:
        raise InvalidCell("clean browser scope session is missing")
    if scope_root not in snapshot.cells:
        raise InvalidCell("clean browser scope target is missing")
    root_id = _scope_state_root(session_root)
    if root_id not in snapshot.cells:
        create = []
        if _SCOPE_LABEL_ROOT not in snapshot.cells:
            create.append(Cell(
                _SCOPE_LABEL_ROOT,
                NULL_CELL_ID,
                NULL_CELL_ID,
                json.dumps(_SCOPE_LABEL, separators=(",", ":")).encode("utf-8"),
            ))
        create.extend(_typed_relation_cells(
            root_id,
            authority.role("conforms-to"),
            authority.shape("composition"),
            (
                (authority.role("label"), _SCOPE_LABEL_ROOT),
                (authority.role("session"), session_root),
                (authority.role("scope"), scope_root),
            ),
        ))
        return authority.store.commit(snapshot.revision, create=tuple(create))
    validate_composition(authority, snapshot, root_id)
    members = read_relation(snapshot, root_id, budget=256)
    session_incidence = tuple(
        member for member in members
        if member.role_id == authority.role("session")
    )
    scope_incidence = tuple(
        member for member in members
        if member.role_id == authority.role("scope")
    )
    if len(session_incidence) != 1 or session_incidence[0].participant_id != session_root:
        raise InvalidCell("clean browser scope session drifted")
    if len(scope_incidence) != 1:
        raise InvalidCell("clean browser scope relation is incomplete")
    if scope_incidence[0].participant_id == scope_root:
        return snapshot.revision
    current_cell = snapshot.cells[scope_incidence[0].incidence_id]
    return authority.store.commit(
        snapshot.revision,
        replace=(Cell(
            current_cell.id,
            current_cell.link0,
            scope_root,
            current_cell.atom,
        ),),
    )


__all__ = [
    "read_clean_browser_scope",
    "write_clean_browser_scope",
]
