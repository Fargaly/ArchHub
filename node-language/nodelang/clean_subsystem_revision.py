"""Replace a subsystem the Interface already holds, through one signed command.

Installing refuses a graph that already carries a different source. That is
right for an install and wrong as the only option: three subsystems -- the
visual descriptors, the scope interactions, the browser authority -- each
answer "a different source is already installed" and none of them offers a
way to carry a new one. On a graph that has been installed once, every
descriptor and every interaction is frozen for good. A row rendering a
contract where it should render a count cannot be corrected; a control the
graph should now offer cannot be added. The graph accepts its first
install and refuses to learn anything after it.

This is the ordinary way to change one: the Interface stops holding the
old subsystem and holds the new one instead, in a single revision, with a
receipt naming both.

It is deliberately not a fallback for install. Install still refuses
drift; this refuses a graph with nothing installed, and refuses to replace
a subsystem with itself. Neither one can quietly stand in for the other,
so "nothing is installed" and "what is installed must change" stay
different questions with different answers.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .cell_protocols import (
    prepare_append_relation_members,
    prepare_remove_relation_members,
    read_relation,
)
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    UnifiedAuthority,
    commit_with_receipt,
    composition_root,
    digest,
    find_receipt,
    validate_command_participants,
)
from .universal_cell import Cell, InvalidCell, overlay_read_snapshot


def replace_interface_subsystem(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    intent: str,
    held_root: str,
    replacement_root: str,
    replacement_cells: Iterable[Cell],
    source_digest: str,
):
    """Point the Interface at a new subsystem in place of the one it holds."""
    if held_root == replacement_root:
        raise InvalidCell("a subsystem cannot be replaced by itself")
    request_digest = digest({
        "intent": intent,
        "held": held_root,
        "replacement": replacement_root,
        "source-digest": source_digest,
    })
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent=intent,
        request_digest=request_digest,
        object_root=interface_root,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return existing
    stale: Sequence[str] = tuple(
        member.incidence_id
        for member in read_relation(
            snapshot, interface_root, budget=COMMAND_BUDGET
        )
        if member.role_id == authority.role("composition")
        and member.participant_id == held_root
    )
    if not stale:
        raise InvalidCell(
            "the Interface does not hold the subsystem being replaced"
        )
    # A replacement cell whose identity is derived rather than minted may
    # already be in the graph, unchanged. Presenting it as a creation is
    # refused, and presenting every one as new is what made revising an
    # interaction set rewrite a million cells that had not changed.
    create: list[Cell] = []
    carried: list[Cell] = []
    for cell in replacement_cells:
        held = snapshot.cells.get(cell.id)
        if held is None:
            create.append(cell)
        elif held != cell:
            carried.append(cell)
    removal = prepare_remove_relation_members(
        snapshot, interface_root, stale, budget=COMMAND_BUDGET
    )
    replace: list[Cell] = [*carried, *removal.replace]
    staged = overlay_read_snapshot(snapshot, replace=removal.replace)
    append = prepare_append_relation_members(
        staged,
        interface_root,
        ((authority.role("composition"), replacement_root),),
        budget=COMMAND_BUDGET,
    )
    create.extend(append.create)
    replace.extend(append.replace)
    # Dropping the old member and appending the new one can touch the same
    # incidence twice, and a cell cannot be created and replaced in one
    # patch. The later version of each wins, and only cells that already
    # exist stay in the replace half.
    merged: dict[str, Cell] = {cell.id: cell for cell in create}
    rest: dict[str, Cell] = {}
    for cell in replace:
        if cell.id in merged:
            merged[cell.id] = cell
        else:
            rest[cell.id] = cell
    return commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(merged.values()),
        resource_replace=tuple(rest.values()),
        authenticated=authenticated,
        result_root=replacement_root,
        policy_proof=policy_proof,
    )


__all__ = ["replace_interface_subsystem"]
