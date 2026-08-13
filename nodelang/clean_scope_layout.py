"""Give the graph somewhere to put its nodes.

A canvas cannot draw what has no place. Every node carried a null
position, so the client computed NaN bounds and the whole layout
collapsed into an empty rectangle -- with every contract satisfied and
every court green, which is exactly the class of failure only a person
looking at the screen can catch.

The position is a graph fact like every other: it lands through a signed
revision on the node's own presentation contract, beside the panels it
already declares, so moving a node later is the same ordinary revision
rather than a special case. Nothing here decides what a node looks like;
it decides only where the graph says it currently is, once, so there is
something to move.
"""
from __future__ import annotations

import uuid

from .cell_protocols import read_relation
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    UnifiedAuthority,
    composition_root,
    read_definition,
    revise_definition,
)


LAYOUT_NAMESPACE = uuid.UUID("4b2c9f6e-6d3a-4f18-9f1b-2c6e8a7d5e40")


def _derived_command(command_id: str, *parts: str) -> str:
    """One opaque command identity per placement, derived not spliced.

    Command identities are opaque by law, so a readable id built by
    slicing and joining is refused -- correctly, and for the same reason
    the catalogue could not keep its names as identities.
    """
    return str(uuid.uuid5(LAYOUT_NAMESPACE, ":".join((command_id, *parts))))


COLUMN_STEP = 260
ROW_STEP = 190
COLUMNS = 4
MARGIN_X = 60
MARGIN_Y = 60


def _placed(index: int) -> dict[str, int]:
    return {
        "x": MARGIN_X + (index % COLUMNS) * COLUMN_STEP,
        "y": MARGIN_Y + (index // COLUMNS) * ROW_STEP,
    }


def install_scope_layout(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> int:
    """Place the nodes of one scope that the graph has never placed.

    Only nodes with no position are touched, so a node the founder has
    moved keeps where he put it and re-running changes nothing.
    """
    snapshot = authority.store.snapshot()
    definitions = [
        member.participant_id
        for member in read_relation(
            snapshot, scope_root, budget=COMMAND_BUDGET
        )
        if member.role_id == authority.role("definition")
    ]
    placed = 0
    for index, definition_root in enumerate(sorted(definitions)):
        current = read_definition(authority, definition_root, caller=caller)
        presentation = dict(current.contracts["presentation"])
        if presentation.get("position"):
            continue
        # The presentation contract already carries this node's panels.
        # Overwriting it to add a position would delete them, so the
        # position joins what is there.
        presentation["position"] = _placed(index)
        revise_definition(
            authority,
            definition_root,
            current.name,
            caller=caller,
            command_id=_derived_command(command_id, definition_root),
            version=current.version,
            defaults=dict(current.contracts["defaults"]),
            parameters=dict(current.contracts["parameters"]),
            interfaces=dict(current.contracts["interfaces"]),
            rules=dict(current.contracts["rules"]),
            presentation=presentation,
            courts=dict(current.contracts["courts"]),
            provenance=dict(current.contracts["provenance"]),
        )
        placed += 1
    return placed


def install_grand_map_layout(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> int:
    """Place every scope the canvas can open, not only the first."""
    grand = composition_root(authority, "Grand Map", caller=caller)
    snapshot = authority.store.snapshot()
    scopes = [
        member.participant_id
        for member in read_relation(snapshot, grand, budget=COMMAND_BUDGET)
        if member.role_id == authority.role("composition")
    ]
    placed = 0
    for scope in scopes:
        placed += install_scope_layout(
            authority,
            scope,
            caller=caller,
            command_id=_derived_command(command_id, "scope", scope),
        )
        inner = [
            member.participant_id
            for member in read_relation(
                authority.store.snapshot(), scope, budget=COMMAND_BUDGET
            )
            if member.role_id == authority.role("composition")
        ]
        for child in inner:
            placed += install_scope_layout(
                authority,
                child,
                caller=caller,
                command_id=_derived_command(command_id, "scope", child),
            )
    return placed


__all__ = [
    "install_grand_map_layout",
    "install_scope_layout",
]
