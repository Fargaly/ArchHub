"""Graph-held, privacy-bounded BABOOM foreground activity capsules.

The protocol records only a released application label tied to an already
proven BABOOM Agent Session and Device Custody. Window titles, documents,
paths, pixels, audio, keystrokes, clipboard content, and process metadata are
outside the protocol. A short expiry is a projection rule, so inactive devices
disappear without a cleanup mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "activity-member",
    "activity-agent-session",
    "activity-device-custody",
    "activity-app",
    "activity-observed-at",
    "activity-expires-at",
)

# Labels only: never process names, titles, or connector/provider selectors.
FOREGROUND_APP_LABELS = (
    "Codex",
    "Revit",
    "AutoCAD",
    "3ds Max",
    "Rhino",
    "Excel",
    "PowerPoint",
    "Word",
    "Browser",
    "Files",
    "VS Code",
    "Cursor",
)

_MIN_LEASE_SECONDS = 15.0
_MAX_LEASE_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class BaboomActivityProtocol:
    root_id: str
    roles: Mapping[str, str]
    app_roots: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM activity role") from exc


@dataclass(frozen=True, slots=True)
class BaboomActivityProjection:
    root_id: str
    agent_session_root: str
    device_custody_root: str
    app: str
    observed_at: float
    expires_at: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("BABOOM activity %s is invalid" % label) from exc


def _one(members, role_root: str, label: str) -> str:
    found = [member for member in members if member.role_id == role_root]
    if len(found) != 1:
        raise InvalidCell("BABOOM activity requires exactly one %s" % label)
    return found[0].participant_id


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("BABOOM activity %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("BABOOM activity %s is not finite" % label)
    return value


def _validate_identity(value: str, label: str, *, prefix: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value.encode("utf-8")) > 512
    ):
        raise InvalidCell("BABOOM activity %s is invalid" % label)
    return value


def _validate_now(value: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise InvalidCell("BABOOM activity %s is invalid" % label)
    return float(value)


def _validate_lease_seconds(value: float) -> float:
    seconds = _validate_now(value, "lease duration")
    if not _MIN_LEASE_SECONDS <= seconds <= _MAX_LEASE_SECONDS:
        raise InvalidCell("BABOOM activity lease duration is outside policy")
    return seconds


def _activity_root(agent_session_root: str) -> str:
    return "baboom-activity:sha256:" + hashlib.sha256(
        agent_session_root.encode("utf-8")
    ).hexdigest()


def _app_roots(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        label: "%s:app:%s" % (
            prefix,
            label.casefold().replace(" ", "-").replace(".", ""),
        )
        for label in FOREGROUND_APP_LABELS
    })


def bootstrap_baboom_activity_protocol(
    store: CellStore,
    *,
    prefix: str = "baboom-activity-protocol",
) -> BaboomActivityProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_baboom_activity_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    app_roots = _app_roots(prefix)
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    for label, root in app_roots.items():
        batch.add(_terminal(root, label))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *app_roots.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return BaboomActivityProtocol(root_id, MappingProxyType(roles), app_roots)


def project_baboom_activity_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "baboom-activity-protocol",
) -> BaboomActivityProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    app_roots = _app_roots(prefix)
    if any(_root not in snapshot.cells for _root in {root_id, *roles.values(), *app_roots.values()}):
        raise InvalidCell("BABOOM activity protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["activity-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM activity protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != {*roles.values(), *app_roots.values()}:
        raise InvalidCell("BABOOM activity protocol vocabulary drifted")
    return BaboomActivityProtocol(root_id, MappingProxyType(roles), app_roots)


def read_baboom_activity(
    snapshot: Snapshot,
    protocol: BaboomActivityProtocol,
    activity_root: str,
) -> BaboomActivityProjection:
    members = read_relation(snapshot, activity_root, budget=128)
    allowed = {
        protocol.role(name)
        for name in ROLE_NAMES
        if name not in ("vocabulary-member", "activity-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("BABOOM activity contains an undeclared field")
    session = _validate_identity(
        _one(members, protocol.role("activity-agent-session"), "agent session"),
        "agent session",
        prefix="app:agent-session:runtime:",
    )
    custody = _validate_identity(
        _one(members, protocol.role("activity-device-custody"), "device custody"),
        "device custody",
        prefix="device-custody:sha256:",
    )
    app_root = _one(members, protocol.role("activity-app"), "app")
    app_by_root = {root: label for label, root in protocol.app_roots.items()}
    try:
        app = app_by_root[app_root]
    except KeyError as exc:
        raise InvalidCell("BABOOM activity app is not released") from exc
    observed_at = _time(
        snapshot,
        _one(members, protocol.role("activity-observed-at"), "observed-at"),
        "observed-at",
    )
    expires_at = _time(
        snapshot,
        _one(members, protocol.role("activity-expires-at"), "expires-at"),
        "expires-at",
    )
    if not observed_at < expires_at:
        raise InvalidCell("BABOOM activity timestamps are invalid")
    return BaboomActivityProjection(
        activity_root, session, custody, app, observed_at, expires_at
    )


def list_baboom_activities(
    snapshot: Snapshot,
    protocol: BaboomActivityProtocol,
) -> tuple[BaboomActivityProjection, ...]:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("activity-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("BABOOM activity registry contains a duplicate")
    return tuple(read_baboom_activity(snapshot, protocol, root) for root in roots)


def list_active_baboom_activities(
    snapshot: Snapshot,
    protocol: BaboomActivityProtocol,
    *,
    now: float,
) -> tuple[BaboomActivityProjection, ...]:
    current_time = _validate_now(now, "current time")
    return tuple(
        activity for activity in list_baboom_activities(snapshot, protocol)
        if current_time < activity.expires_at
    )


def renew_baboom_activity(
    store: CellStore,
    protocol: BaboomActivityProtocol,
    *,
    agent_session_root: str,
    device_custody_root: str,
    app: str,
    now: float,
    lease_seconds: float,
) -> tuple[BaboomActivityProjection, int]:
    """Create or refresh the single foreground capsule for one BABOOM session."""
    session = _validate_identity(
        agent_session_root, "agent session", prefix="app:agent-session:runtime:"
    )
    custody = _validate_identity(
        device_custody_root, "device custody", prefix="device-custody:sha256:"
    )
    try:
        app_root = protocol.app_roots[app]
    except (KeyError, TypeError) as exc:
        raise InvalidCell("BABOOM activity app is not released") from exc
    observed_at = _validate_now(now, "observation time")
    expires_at = observed_at + _validate_lease_seconds(lease_seconds)
    root_id = _activity_root(session)
    snapshot = store.snapshot()
    if session not in snapshot.cells or custody not in snapshot.cells:
        raise InvalidCell(
            "BABOOM activity session and device custody must already exist"
        )
    relation = compose_relation_cells(
        (
            (protocol.role("activity-agent-session"), session),
            (protocol.role("activity-device-custody"), custody),
            (protocol.role("activity-app"), app_root),
            (protocol.role("activity-observed-at"), root_id + ":observed-at"),
            (protocol.role("activity-expires-at"), root_id + ":expires-at"),
        ),
        relation_id=root_id,
    )
    values = (
        _terminal(root_id + ":observed-at", "%.6f" % observed_at),
        _terminal(root_id + ":expires-at", "%.6f" % expires_at),
    )
    if root_id in snapshot.cells:
        existing = read_baboom_activity(snapshot, protocol, root_id)
        if (
            existing.agent_session_root != session
            or existing.device_custody_root != custody
        ):
            raise InvalidCell("BABOOM activity binding drifted")
        revision = store.commit(
            snapshot.revision,
            replace=(*values, *relation.cells),
        )
        return read_baboom_activity(store.snapshot(), protocol, root_id), revision
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("activity-member"),
        root_id,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(*values, *relation.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )
    return read_baboom_activity(store.snapshot(), protocol, root_id), revision


__all__ = [
    "BaboomActivityProjection",
    "BaboomActivityProtocol",
    "FOREGROUND_APP_LABELS",
    "bootstrap_baboom_activity_protocol",
    "list_active_baboom_activities",
    "list_baboom_activities",
    "project_baboom_activity_protocol",
    "read_baboom_activity",
    "renew_baboom_activity",
]
