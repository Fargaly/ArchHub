"""Cell-native WIP state for composing an arbitrary released relation.

The browser never owns the semantic draft.  One view-session relation points to
the selected definition and to ordered entry relations.  Every entry explicitly
relates a contract role, an optional participant, and its order value.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping
import math
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


RELATION_COMPOSER_PROTOCOL_PREFIX = "app:relation-composer-protocol:v1"
RELATION_COMPOSER_ROLE_NAMES = (
    "vocabulary-member",
    "definition",
    "entry",
    "participant-role",
    "participant",
    "order",
    "x",
    "y",
)


@dataclass(frozen=True, slots=True)
class RelationComposerProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell(
                "unknown relation-composer role %r" % name
            ) from exc


@dataclass(frozen=True, slots=True)
class RelationComposerEntry:
    root_id: str
    role_root: str
    participant_root: str | None
    order: int


@dataclass(frozen=True, slots=True)
class RelationComposerDraft:
    root_id: str
    definition_root: str | None
    entries: tuple[RelationComposerEntry, ...]
    x: float | None
    y: float | None


@dataclass(frozen=True, slots=True)
class RelationComposerDraftPatch:
    root_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def relation_composer_draft_root(session_root: str) -> str:
    return session_root + ":relation-composer-draft"


def compose_relation_composer_protocol(
    batch: CellBatch,
    *,
    prefix: str = RELATION_COMPOSER_PROTOCOL_PREFIX,
) -> RelationComposerProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in RELATION_COMPOSER_ROLE_NAMES
    }
    for name, root_id in roles.items():
        batch.add(Cell(
            root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
    root_id = prefix + ":root"
    batch.relation(
        (
            (roles["vocabulary-member"], role_root)
            for role_root in roles.values()
        ),
        relation_id=root_id,
    )
    return RelationComposerProtocol(
        root_id=root_id,
        roles=MappingProxyType(roles),
    )


def open_relation_composer_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = RELATION_COMPOSER_PROTOCOL_PREFIX,
) -> RelationComposerProtocol:
    protocol = RelationComposerProtocol(
        root_id=prefix + ":root",
        roles=MappingProxyType({
            name: "%s:role:%s" % (prefix, name)
            for name in RELATION_COMPOSER_ROLE_NAMES
        }),
    )
    expected = {protocol.root_id, *protocol.roles.values()}
    if expected - set(snapshot.cells):
        raise InvalidCell("relation-composer protocol is incomplete")
    members = read_relation(snapshot, protocol.root_id, budget=64)
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == protocol.role("vocabulary-member")
    }
    if vocabulary != set(protocol.roles.values()):
        raise InvalidCell("relation-composer protocol vocabulary drifted")
    if any(
        member.role_id != protocol.role("vocabulary-member")
        for member in members
    ):
        raise InvalidCell("relation-composer protocol has an undeclared role")
    return protocol


def _classify_cells(
    snapshot: Snapshot,
    cells: Iterable[Cell],
) -> tuple[tuple[Cell, ...], tuple[Cell, ...]]:
    create = []
    replace = []
    for cell in cells:
        current = snapshot.cells.get(cell.id)
        if current is None:
            create.append(cell)
        elif current != cell:
            replace.append(cell)
    return tuple(create), tuple(replace)


def prepare_relation_composer_draft(
    snapshot: Snapshot,
    protocol: RelationComposerProtocol,
    session_root: str,
    definition_root: str | None,
    entries: Iterable[RelationComposerEntry],
    *,
    x: float | None = None,
    y: float | None = None,
) -> RelationComposerDraftPatch:
    """Prepare one exact graph draft without committing a partial state."""
    if session_root not in snapshot.cells:
        raise InvalidCell("relation-composer session is missing")
    if definition_root is not None and definition_root not in snapshot.cells:
        raise InvalidCell("relation-composer definition is missing")
    normalized = tuple(sorted(entries, key=lambda item: item.order))
    if len(normalized) > 256:
        raise InvalidCell("relation-composer draft exceeds 256 entries")
    if [entry.order for entry in normalized] != list(range(len(normalized))):
        raise InvalidCell("relation-composer entry order is not contiguous")
    if len({entry.root_id for entry in normalized}) != len(normalized):
        raise InvalidCell("relation-composer entry identity is duplicated")
    if (x is None) != (y is None):
        raise InvalidCell("relation-composer placement is incomplete")
    if x is not None and (
        not math.isfinite(float(x)) or not math.isfinite(float(y))
    ):
        raise InvalidCell("relation-composer placement is not finite")

    cells: list[Cell] = []
    for entry in normalized:
        if entry.role_root not in snapshot.cells:
            raise InvalidCell("relation-composer participant role is missing")
        if (
            entry.participant_root is not None
            and entry.participant_root not in snapshot.cells
        ):
            raise InvalidCell("relation-composer participant is missing")
        order_root = entry.root_id + ":order"
        cells.append(Cell(
            order_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(entry.order).encode("ascii"),
        ))
        relation = compose_relation_cells(
            (
                (protocol.role("participant-role"), entry.role_root),
                (protocol.role("order"), order_root),
                *((
                    (protocol.role("participant"), entry.participant_root),
                ) if entry.participant_root is not None else ()),
            ),
            relation_id=entry.root_id,
        )
        cells.extend(relation.cells)

    draft_root = relation_composer_draft_root(session_root)
    placement_members = ()
    if x is not None:
        x_root = draft_root + ":x"
        y_root = draft_root + ":y"
        cells.extend((
            Cell(
                x_root, NULL_CELL_ID, NULL_CELL_ID,
                repr(float(x)).encode("ascii"),
            ),
            Cell(
                y_root, NULL_CELL_ID, NULL_CELL_ID,
                repr(float(y)).encode("ascii"),
            ),
        ))
        placement_members = (
            (protocol.role("x"), x_root),
            (protocol.role("y"), y_root),
        )
    draft = compose_relation_cells(
        (
            *((
                (protocol.role("definition"), definition_root),
            ) if definition_root is not None else ()),
            *((protocol.role("entry"), entry.root_id) for entry in normalized),
            *placement_members,
        ),
        relation_id=draft_root,
    )
    cells.extend(draft.cells)
    create, replace = _classify_cells(snapshot, cells)
    return RelationComposerDraftPatch(draft_root, create, replace)


def new_relation_composer_entry(
    role_root: str,
    order: int,
    *,
    participant_root: str | None = None,
    prefix: str = "app:relation-composer-entry",
) -> RelationComposerEntry:
    return RelationComposerEntry(
        root_id="%s:%s" % (prefix, uuid.uuid4().hex),
        role_root=role_root,
        participant_root=participant_root,
        order=order,
    )


def read_relation_composer_draft(
    snapshot: Snapshot,
    protocol: RelationComposerProtocol,
    session_root: str,
) -> RelationComposerDraft | None:
    root_id = relation_composer_draft_root(session_root)
    if root_id not in snapshot.cells:
        return None
    members = read_relation(snapshot, root_id, budget=1_024)
    definitions = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("definition")
    )
    entry_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("entry")
    )
    x_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("x")
    )
    y_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("y")
    )
    if len(definitions) > 1:
        raise InvalidCell("relation-composer draft has multiple definitions")
    if len(x_roots) > 1 or len(y_roots) > 1 or bool(x_roots) != bool(y_roots):
        raise InvalidCell("relation-composer placement cardinality is invalid")
    if any(
        member.role_id not in (
            protocol.role("definition"), protocol.role("entry"),
            protocol.role("x"), protocol.role("y"),
        )
        for member in members
    ):
        raise InvalidCell("relation-composer draft has an undeclared member")
    if len(entry_roots) > 256 or len(set(entry_roots)) != len(entry_roots):
        raise InvalidCell("relation-composer draft entries are invalid")

    entries = []
    for entry_root in entry_roots:
        entry_members = read_relation(snapshot, entry_root, budget=16)
        roles = tuple(
            member.participant_id for member in entry_members
            if member.role_id == protocol.role("participant-role")
        )
        participants = tuple(
            member.participant_id for member in entry_members
            if member.role_id == protocol.role("participant")
        )
        orders = tuple(
            member.participant_id for member in entry_members
            if member.role_id == protocol.role("order")
        )
        if len(roles) != 1 or len(participants) > 1 or len(orders) != 1:
            raise InvalidCell("relation-composer entry cardinality is invalid")
        if any(
            member.role_id not in (
                protocol.role("participant-role"),
                protocol.role("participant"),
                protocol.role("order"),
            )
            for member in entry_members
        ):
            raise InvalidCell("relation-composer entry has an undeclared member")
        order_cell = snapshot.cells[orders[0]]
        if order_cell.link0 != NULL_CELL_ID or order_cell.link1 != NULL_CELL_ID:
            raise InvalidCell("relation-composer order is not terminal")
        try:
            order = int(order_cell.atom.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("relation-composer order is invalid") from exc
        entries.append(RelationComposerEntry(
            root_id=entry_root,
            role_root=roles[0],
            participant_root=participants[0] if participants else None,
            order=order,
        ))
    entries.sort(key=lambda item: item.order)
    if [entry.order for entry in entries] != list(range(len(entries))):
        raise InvalidCell("relation-composer entry order drifted")
    x = y = None
    if x_roots:
        placement_cells = (snapshot.cells[x_roots[0]], snapshot.cells[y_roots[0]])
        if any(
            cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID
            for cell in placement_cells
        ):
            raise InvalidCell("relation-composer placement is not terminal")
        try:
            x, y = (
                float(cell.atom.decode("ascii")) for cell in placement_cells
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("relation-composer placement is invalid") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise InvalidCell("relation-composer placement is not finite")
    return RelationComposerDraft(
        root_id=root_id,
        definition_root=definitions[0] if definitions else None,
        entries=tuple(entries),
        x=x,
        y=y,
    )


__all__ = [
    "RELATION_COMPOSER_PROTOCOL_PREFIX",
    "RELATION_COMPOSER_ROLE_NAMES",
    "RelationComposerDraft",
    "RelationComposerDraftPatch",
    "RelationComposerEntry",
    "RelationComposerProtocol",
    "compose_relation_composer_protocol",
    "new_relation_composer_entry",
    "open_relation_composer_protocol",
    "prepare_relation_composer_draft",
    "read_relation_composer_draft",
    "relation_composer_draft_root",
]
