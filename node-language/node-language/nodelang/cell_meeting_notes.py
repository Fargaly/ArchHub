"""Graph-held consent sessions for BABOOM meeting-note stewardship.

The graph records a bounded consent state only. Meeting titles, participants,
audio, transcripts, note text, calendar values, and external identifiers never
enter this protocol. Founder-supplied note content remains local until a
separately approved connector effect writes it and settles with a digest-only
receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
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
    "session-member",
    "session-agent-session",
    "session-device-custody",
    "session-capture-mode",
    "session-state",
    "session-opened-at",
    "session-expires-at",
)
CAPTURE_MODE_NAMES = ("founder-supplied",)
STATE_NAMES = ("active", "closed")

_SESSION_PREFIX = "baboom-meeting-notes:session:"
_MIN_LEASE_SECONDS = 60.0
_MAX_LEASE_SECONDS = 4.0 * 60.0 * 60.0


@dataclass(frozen=True, slots=True)
class BaboomMeetingNotesProtocol:
    root_id: str
    roles: Mapping[str, str]
    capture_modes: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM meeting-notes role") from exc


@dataclass(frozen=True, slots=True)
class BaboomMeetingNotesProjection:
    root_id: str
    agent_session_root: str
    device_custody_root: str
    capture_mode: str
    state: str
    opened_at: float
    expires_at: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("BABOOM meeting-notes %s is invalid" % label) from exc


def _one(members, role_root: str, label: str) -> str:
    found = [member for member in members if member.role_id == role_root]
    if len(found) != 1:
        raise InvalidCell("BABOOM meeting-notes requires exactly one %s" % label)
    return found[0].participant_id


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("BABOOM meeting-notes %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("BABOOM meeting-notes %s is not finite" % label)
    return value


def _validate_identity(value: str, label: str, *, prefix: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value.encode("utf-8")) > 512
    ):
        raise InvalidCell("BABOOM meeting-notes %s is invalid" % label)
    return value


def _validate_now(value: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise InvalidCell("BABOOM meeting-notes %s is invalid" % label)
    return float(value)


def _validate_lease_seconds(value: float) -> float:
    seconds = _validate_now(value, "lease duration")
    if not _MIN_LEASE_SECONDS <= seconds <= _MAX_LEASE_SECONDS:
        raise InvalidCell("BABOOM meeting-notes lease duration is outside policy")
    return seconds


def _mapping_roots(prefix: str, segment: str, names: tuple[str, ...]) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:%s:%s" % (prefix, segment, name)
        for name in names
    })


def bootstrap_baboom_meeting_notes_protocol(
    store: CellStore,
    *,
    prefix: str = "baboom-meeting-notes-protocol",
) -> BaboomMeetingNotesProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_baboom_meeting_notes_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    capture_modes = _mapping_roots(prefix, "capture-mode", CAPTURE_MODE_NAMES)
    states = _mapping_roots(prefix, "state", STATE_NAMES)
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    for name, root in capture_modes.items():
        batch.add(_terminal(root, name))
    for name, root in states.items():
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *capture_modes.values(), *states.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return BaboomMeetingNotesProtocol(
        root_id,
        MappingProxyType(roles),
        capture_modes,
        states,
    )


def project_baboom_meeting_notes_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "baboom-meeting-notes-protocol",
) -> BaboomMeetingNotesProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    capture_modes = _mapping_roots(prefix, "capture-mode", CAPTURE_MODE_NAMES)
    states = _mapping_roots(prefix, "state", STATE_NAMES)
    if any(_root not in snapshot.cells for _root in {root_id, *roles.values(), *capture_modes.values(), *states.values()}):
        raise InvalidCell("BABOOM meeting-notes protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["session-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM meeting-notes protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != {*roles.values(), *capture_modes.values(), *states.values()}:
        raise InvalidCell("BABOOM meeting-notes protocol vocabulary drifted")
    return BaboomMeetingNotesProtocol(
        root_id,
        MappingProxyType(roles),
        capture_modes,
        states,
    )


def read_baboom_meeting_notes(
    snapshot: Snapshot,
    protocol: BaboomMeetingNotesProtocol,
    session_root: str,
) -> BaboomMeetingNotesProjection:
    members = read_relation(snapshot, session_root, budget=128)
    allowed = {
        protocol.role(name)
        for name in ROLE_NAMES
        if name not in ("vocabulary-member", "session-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM meeting-notes session contains an undeclared field")
    agent_session_root = _validate_identity(
        _one(members, protocol.role("session-agent-session"), "agent session"),
        "agent session",
        prefix="app:agent-session:runtime:",
    )
    device_custody_root = _validate_identity(
        _one(members, protocol.role("session-device-custody"), "device custody"),
        "device custody",
        prefix="device-custody:sha256:",
    )
    capture_mode_root = _one(
        members, protocol.role("session-capture-mode"), "capture mode"
    )
    state_root = _one(members, protocol.role("session-state"), "state")
    capture_mode_by_root = {
        root: name for name, root in protocol.capture_modes.items()
    }
    state_by_root = {root: name for name, root in protocol.states.items()}
    try:
        capture_mode = capture_mode_by_root[capture_mode_root]
        state = state_by_root[state_root]
    except KeyError as exc:
        raise InvalidCell("BABOOM meeting-notes session is not released") from exc
    opened_at = _time(
        snapshot,
        _one(members, protocol.role("session-opened-at"), "opened-at"),
        "opened-at",
    )
    expires_at = _time(
        snapshot,
        _one(members, protocol.role("session-expires-at"), "expires-at"),
        "expires-at",
    )
    if not opened_at < expires_at:
        raise InvalidCell("BABOOM meeting-notes timestamps are invalid")
    return BaboomMeetingNotesProjection(
        session_root,
        agent_session_root,
        device_custody_root,
        capture_mode,
        state,
        opened_at,
        expires_at,
    )


def list_baboom_meeting_notes(
    snapshot: Snapshot,
    protocol: BaboomMeetingNotesProtocol,
) -> tuple[BaboomMeetingNotesProjection, ...]:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("session-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("BABOOM meeting-notes registry contains a duplicate")
    return tuple(read_baboom_meeting_notes(snapshot, protocol, root) for root in roots)


def list_active_baboom_meeting_notes(
    snapshot: Snapshot,
    protocol: BaboomMeetingNotesProtocol,
    *,
    now: float,
) -> tuple[BaboomMeetingNotesProjection, ...]:
    current_time = _validate_now(now, "current time")
    return tuple(
        session for session in list_baboom_meeting_notes(snapshot, protocol)
        if session.state == "active" and current_time < session.expires_at
    )


def _session_relation(
    protocol: BaboomMeetingNotesProtocol,
    *,
    session_root: str,
    agent_session_root: str,
    device_custody_root: str,
    capture_mode: str,
    state: str,
    opened_at: float,
    expires_at: float,
):
    try:
        capture_mode_root = protocol.capture_modes[capture_mode]
        state_root = protocol.states[state]
    except KeyError as exc:
        raise InvalidCell("BABOOM meeting-notes value is not released") from exc
    relation = compose_relation_cells(
        (
            (protocol.role("session-agent-session"), agent_session_root),
            (protocol.role("session-device-custody"), device_custody_root),
            (protocol.role("session-capture-mode"), capture_mode_root),
            (protocol.role("session-state"), state_root),
            (protocol.role("session-opened-at"), session_root + ":opened-at"),
            (protocol.role("session-expires-at"), session_root + ":expires-at"),
        ),
        relation_id=session_root,
    )
    values = (
        _terminal(session_root + ":opened-at", "%.6f" % opened_at),
        _terminal(session_root + ":expires-at", "%.6f" % expires_at),
    )
    return relation, values


def start_baboom_meeting_notes(
    store: CellStore,
    protocol: BaboomMeetingNotesProtocol,
    *,
    agent_session_root: str,
    device_custody_root: str,
    now: float,
    lease_seconds: float,
    capture_mode: str = "founder-supplied",
) -> tuple[BaboomMeetingNotesProjection, int]:
    """Start or renew the one consented note session for a BABOOM presence."""
    agent_session_root = _validate_identity(
        agent_session_root, "agent session", prefix="app:agent-session:runtime:"
    )
    device_custody_root = _validate_identity(
        device_custody_root, "device custody", prefix="device-custody:sha256:"
    )
    if capture_mode not in protocol.capture_modes:
        raise InvalidCell("BABOOM meeting-notes capture mode is not released")
    opened_at = _validate_now(now, "opening time")
    expires_at = opened_at + _validate_lease_seconds(lease_seconds)
    snapshot = store.snapshot()
    if agent_session_root not in snapshot.cells or device_custody_root not in snapshot.cells:
        raise InvalidCell(
            "BABOOM meeting-notes session and device custody must already exist"
        )
    active = tuple(
        session for session in list_active_baboom_meeting_notes(
            snapshot, protocol, now=opened_at
        )
        if session.agent_session_root == agent_session_root
    )
    if len(active) > 1:
        raise InvalidCell("BABOOM meeting-notes active session is ambiguous")
    if active:
        existing = active[0]
        if (
            existing.device_custody_root != device_custody_root
            or existing.capture_mode != capture_mode
        ):
            raise InvalidCell("BABOOM meeting-notes active session binding drifted")
        relation, values = _session_relation(
            protocol,
            session_root=existing.root_id,
            agent_session_root=agent_session_root,
            device_custody_root=device_custody_root,
            capture_mode=capture_mode,
            state="active",
            opened_at=existing.opened_at,
            expires_at=expires_at,
        )
        revision = store.commit(
            snapshot.revision,
            replace=(*values, *relation.cells),
        )
        return read_baboom_meeting_notes(
            store.snapshot(), protocol, existing.root_id
        ), revision

    session_root = _SESSION_PREFIX + uuid.uuid4().hex
    relation, values = _session_relation(
        protocol,
        session_root=session_root,
        agent_session_root=agent_session_root,
        device_custody_root=device_custody_root,
        capture_mode=capture_mode,
        state="active",
        opened_at=opened_at,
        expires_at=expires_at,
    )
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("session-member"),
        session_root,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(*values, *relation.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )
    return read_baboom_meeting_notes(store.snapshot(), protocol, session_root), revision


def close_baboom_meeting_notes(
    store: CellStore,
    protocol: BaboomMeetingNotesProtocol,
    *,
    session_root: str,
    agent_session_root: str,
    device_custody_root: str,
) -> tuple[BaboomMeetingNotesProjection, int]:
    """Close one consent session without importing any meeting content."""
    snapshot = store.snapshot()
    existing = read_baboom_meeting_notes(snapshot, protocol, session_root)
    if existing.state != "active":
        raise InvalidCell("BABOOM meeting-notes session is not active")
    if (
        existing.agent_session_root != _validate_identity(
            agent_session_root, "agent session", prefix="app:agent-session:runtime:"
        )
        or existing.device_custody_root != _validate_identity(
            device_custody_root, "device custody", prefix="device-custody:sha256:"
        )
    ):
        raise InvalidCell("BABOOM meeting-notes session binding drifted")
    relation, values = _session_relation(
        protocol,
        session_root=existing.root_id,
        agent_session_root=existing.agent_session_root,
        device_custody_root=existing.device_custody_root,
        capture_mode=existing.capture_mode,
        state="closed",
        opened_at=existing.opened_at,
        expires_at=existing.expires_at,
    )
    revision = store.commit(
        snapshot.revision,
        replace=(*values, *relation.cells),
    )
    return read_baboom_meeting_notes(store.snapshot(), protocol, session_root), revision


__all__ = [
    "BaboomMeetingNotesProjection",
    "BaboomMeetingNotesProtocol",
    "CAPTURE_MODE_NAMES",
    "STATE_NAMES",
    "bootstrap_baboom_meeting_notes_protocol",
    "close_baboom_meeting_notes",
    "list_active_baboom_meeting_notes",
    "list_baboom_meeting_notes",
    "project_baboom_meeting_notes_protocol",
    "read_baboom_meeting_notes",
    "start_baboom_meeting_notes",
]
