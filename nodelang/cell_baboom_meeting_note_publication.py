"""Graph-held bindings for consented BABOOM meeting-note publications.

The binding proves that one connector delegation was created under one active
BABOOM meeting-notes consent session.  It carries no meeting title, attendee,
audio, transcript, note text, provider payload, or credential.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "binding-member",
    "binding-delegation",
    "binding-meeting-notes",
)

_BINDING_PREFIX = "app:baboom-meeting-note-publication:binding:"


@dataclass(frozen=True, slots=True)
class BaboomMeetingNotePublicationProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM meeting-note publication role") from exc


@dataclass(frozen=True, slots=True)
class BaboomMeetingNotePublicationProjection:
    root_id: str
    delegation_root: str
    meeting_notes_root: str


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _one(members, role_root: str, label: str) -> str:
    values = [member.participant_id for member in members if member.role_id == role_root]
    if len(values) != 1:
        raise InvalidCell(
            "BABOOM meeting-note publication requires exactly one %s" % label
        )
    return values[0]


def _require_root(value: str, label: str, prefix: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value.encode("utf-8")) > 512
    ):
        raise InvalidCell("BABOOM meeting-note publication %s is invalid" % label)
    return value


def bootstrap_baboom_meeting_note_publication_protocol(
    store: CellStore,
    *,
    prefix: str = "app:baboom-meeting-note-publication-protocol",
) -> BaboomMeetingNotePublicationProtocol:
    """Create or verify the append-only delegation-to-consent vocabulary."""
    root_id = prefix + ":root"
    roles = MappingProxyType({name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES})
    snapshot = store.snapshot()
    if root_id not in snapshot.cells:
        batch = CellBatch(store)
        for name, root in roles.items():
            batch.add(_terminal(root, name))
        batch.relation(
            ((roles["vocabulary-member"], root) for root in roles.values()),
            relation_id=root_id,
        )
        batch.commit()
        snapshot = store.snapshot()
    return project_baboom_meeting_note_publication_protocol(snapshot, prefix=prefix)


def project_baboom_meeting_note_publication_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "app:baboom-meeting-note-publication-protocol",
) -> BaboomMeetingNotePublicationProtocol:
    root_id = prefix + ":root"
    roles = MappingProxyType({name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES})
    if {root_id, *roles.values()} - set(snapshot.cells):
        raise InvalidCell("BABOOM meeting-note publication protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["binding-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM meeting-note publication protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != set(roles.values()):
        raise InvalidCell("BABOOM meeting-note publication vocabulary drifted")
    bindings = [
        member.participant_id
        for member in members
        if member.role_id == roles["binding-member"]
    ]
    if len(bindings) != len(set(bindings)):
        raise InvalidCell("BABOOM meeting-note publication registry has a duplicate")
    return BaboomMeetingNotePublicationProtocol(root_id, roles)


def read_baboom_meeting_note_publication(
    snapshot: Snapshot,
    protocol: BaboomMeetingNotePublicationProtocol,
    binding_root: str,
) -> BaboomMeetingNotePublicationProjection:
    if binding_root not in snapshot.cells:
        raise InvalidCell("BABOOM meeting-note publication binding is missing")
    registered = [
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("binding-member")
        and member.participant_id == binding_root
    ]
    if len(registered) != 1:
        raise InvalidCell("BABOOM meeting-note publication binding is not registered")
    members = read_relation(snapshot, binding_root, budget=64)
    allowed = {
        protocol.role("binding-delegation"),
        protocol.role("binding-meeting-notes"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM meeting-note publication binding has an undeclared field")
    delegation_root = _require_root(
        _one(members, protocol.role("binding-delegation"), "delegation"),
        "delegation",
        "app:baboom-connector-delegation:",
    )
    meeting_notes_root = _require_root(
        _one(members, protocol.role("binding-meeting-notes"), "meeting-notes consent"),
        "meeting-notes consent",
        "baboom-meeting-notes:session:",
    )
    if delegation_root not in snapshot.cells or meeting_notes_root not in snapshot.cells:
        raise InvalidCell("BABOOM meeting-note publication binding target is missing")
    return BaboomMeetingNotePublicationProjection(
        binding_root, delegation_root, meeting_notes_root
    )


def find_baboom_meeting_note_publication(
    snapshot: Snapshot,
    protocol: BaboomMeetingNotePublicationProtocol,
    delegation_root: str,
) -> BaboomMeetingNotePublicationProjection | None:
    delegation_root = _require_root(
        delegation_root, "delegation", "app:baboom-connector-delegation:"
    )
    matches = tuple(
        projection
        for projection in (
            read_baboom_meeting_note_publication(
                snapshot, protocol, member.participant_id
            )
            for member in read_relation(snapshot, protocol.root_id, budget=100_000)
            if member.role_id == protocol.role("binding-member")
        )
        if projection.delegation_root == delegation_root
    )
    if len(matches) > 1:
        raise InvalidCell("BABOOM meeting-note publication delegation is ambiguous")
    return matches[0] if matches else None


def create_baboom_meeting_note_publication(
    store: CellStore,
    protocol: BaboomMeetingNotePublicationProtocol,
    *,
    delegation_root: str,
    meeting_notes_root: str,
    binding_id: str | None = None,
) -> BaboomMeetingNotePublicationProjection:
    """Bind one released connector delegation to one active consent Cell."""
    delegation_root = _require_root(
        delegation_root, "delegation", "app:baboom-connector-delegation:"
    )
    meeting_notes_root = _require_root(
        meeting_notes_root,
        "meeting-notes consent",
        "baboom-meeting-notes:session:",
    )
    binding_root = binding_id or (_BINDING_PREFIX + uuid.uuid4().hex)
    _require_root(binding_root, "binding", _BINDING_PREFIX)
    snapshot = store.snapshot()
    if binding_root in snapshot.cells:
        raise InvalidCell("BABOOM meeting-note publication binding already exists")
    if delegation_root not in snapshot.cells or meeting_notes_root not in snapshot.cells:
        raise InvalidCell("BABOOM meeting-note publication binding target is missing")
    if find_baboom_meeting_note_publication(snapshot, protocol, delegation_root):
        raise InvalidCell("BABOOM meeting-note publication delegation is already bound")
    relation = compose_relation_cells(
        (
            (protocol.role("binding-delegation"), delegation_root),
            (protocol.role("binding-meeting-notes"), meeting_notes_root),
        ),
        relation_id=binding_root,
    )
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("binding-member"),
        binding_root,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*relation.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )
    return read_baboom_meeting_note_publication(
        store.snapshot(), protocol, binding_root
    )


__all__ = [
    "BaboomMeetingNotePublicationProtocol",
    "BaboomMeetingNotePublicationProjection",
    "bootstrap_baboom_meeting_note_publication_protocol",
    "project_baboom_meeting_note_publication_protocol",
    "read_baboom_meeting_note_publication",
    "find_baboom_meeting_note_publication",
    "create_baboom_meeting_note_publication",
]
