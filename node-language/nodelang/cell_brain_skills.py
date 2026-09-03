"""The brain's skill library: what it learned, and what may be promoted.

`brain_skills` lived in the superseded app as a folder of files. A skill is not
a file -- it is a graph-held assembly with a purpose, the work it was learned
from, and the evidence that earned it. Promotion is the catalogue's own release
court: a skill without evidence cannot be promoted, so "the brain learned this"
can never be a claim.

Recall is by purpose, out of the graph. Delete the library and recall returns
nothing -- there is no second place a skill is remembered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .cell_catalog import (
    AssemblyProtocol,
    build_definition,
    build_interface,
    read_definition,
    release_definition,
    verify_released_definition,
)
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot

SKILL_LIBRARY_ROOT = "app:brain:skill-library"


@dataclass(frozen=True, slots=True)
class Skill:
    root_id: str
    name: str
    purpose: str
    learned_from: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    released: bool


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("skill text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_skill_library(store: CellStore, protocol: AssemblyProtocol) -> str:
    """The one place skills are remembered."""
    snapshot = store.snapshot()
    if SKILL_LIBRARY_ROOT in snapshot.cells:
        return SKILL_LIBRARY_ROOT
    marker = SKILL_LIBRARY_ROOT + ":marker"
    store.commit(snapshot.revision, create=(
        _terminal(marker, "brain-skill-library"),
        Cell(SKILL_LIBRARY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, SKILL_LIBRARY_ROOT,
        ((protocol.role("shared"), marker),), budget=10_000,
    )
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return SKILL_LIBRARY_ROOT


def mint_skill(
    store: CellStore,
    protocol: AssemblyProtocol,
    *,
    skill_id: str,
    name: str,
    purpose: str,
    learned_from: Iterable[str],
    evidence_roots: Iterable[str] = (),
) -> str:
    """Record a skill as a DRAFT. Drafting is not learning; release is."""
    purpose = purpose.strip()
    if not purpose:
        raise InvalidCell("a skill without a purpose cannot be recalled")
    learned = tuple(dict.fromkeys(learned_from))
    if not learned:
        raise InvalidCell("a skill must name the work it was learned from")
    library = ensure_skill_library(store, protocol)

    purpose_root = skill_id + ":purpose"
    body_root = skill_id + ":body"
    contract_root = skill_id + ":contract"
    store.commit(store.snapshot().revision, create=(
        _terminal(purpose_root, purpose),
        _terminal(body_root, name),
        _terminal(contract_root, "skill"),
    ))
    interface = build_interface(
        store, protocol,
        interface_id=skill_id + ":interface",
        target_root=body_root,
        contract_root=contract_root,
    )
    build_definition(
        store, protocol,
        definition_id=skill_id,
        name=name,
        version="1.0.0",
        # The contract the interface points at is part of the skill's own
        # region: a boundary the region does not declare is refused.
        part_roots=(body_root, contract_root, *interface.part_roots),
        interface_roots=(interface.root_id,),
        evidence_roots=tuple(evidence_roots),
        shared_roots=(purpose_root, *learned),
    )
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, library,
        ((protocol.role("definition-dependency"), skill_id),), budget=100_000,
    )
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return skill_id


def promote_skill(
    store: CellStore,
    protocol: AssemblyProtocol,
    skill_root: str,
) -> bytes:
    """Promote a skill. The catalogue refuses one with no evidence."""
    return release_definition(store, protocol, skill_root)


def read_skill(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    skill_root: str,
) -> Skill:
    definition = read_definition(snapshot, protocol, skill_root)
    purpose_root = skill_root + ":purpose"
    if purpose_root not in definition.shared_roots:
        raise InvalidCell("skill does not carry its purpose")
    learned = tuple(
        root for root in definition.shared_roots
        if root != purpose_root
        and not root.startswith(protocol.root_id)
        and root not in protocol.roles.values()
        and root not in protocol.states.values()
    )
    return Skill(
        skill_root,
        _text(snapshot, definition.name_root),
        _text(snapshot, purpose_root),
        learned,
        definition.evidence_roots,
        definition.lifecycle_root == protocol.states["released"],
    )


def recall_skills(
    snapshot: Snapshot,
    protocol: AssemblyProtocol,
    purpose: str,
    *,
    released_only: bool = True,
) -> tuple[Skill, ...]:
    """Every skill the graph holds for a purpose. No index, no cache."""
    if SKILL_LIBRARY_ROOT not in snapshot.cells:
        return ()
    wanted = purpose.strip().lower()
    found = []
    for member in read_relation(snapshot, SKILL_LIBRARY_ROOT, budget=100_000):
        if member.role_id != protocol.role("definition-dependency"):
            continue
        skill = read_skill(snapshot, protocol, member.participant_id)
        if released_only and not skill.released:
            continue
        if wanted and wanted not in skill.purpose.lower():
            continue
        found.append(skill)
    return tuple(found)
