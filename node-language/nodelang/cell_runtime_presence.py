"""Graph-held leases for currently proven device-bound runtime sessions.

The lease is deliberately small: it records the already-authorised Agent
Session, its Device Custody, runtime label, and bounded freshness timestamps.
Tokens, device proofs, host names, screens, and process details remain outside
the graph. Expiry is a projection rule, so an abandoned process cannot require
a cleanup mutation to stop appearing online.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
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
    "presence-member",
    "presence-agent-session",
    "presence-device-custody",
    "presence-runtime",
    "presence-issued-at",
    "presence-refreshed-at",
    "presence-expires-at",
)

_RUNTIME = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,127}\Z")
_MIN_LEASE_SECONDS = 15.0
_MAX_LEASE_SECONDS = 900.0


@dataclass(frozen=True, slots=True)
class RuntimePresenceProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown runtime-presence role") from exc


@dataclass(frozen=True, slots=True)
class RuntimePresenceProjection:
    root_id: str
    agent_session_root: str
    device_custody_root: str
    runtime: str
    issued_at: float
    refreshed_at: float
    expires_at: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("runtime presence %s is invalid" % label) from exc


def _one(members, role_root: str, label: str):
    found = [member for member in members if member.role_id == role_root]
    if len(found) != 1:
        raise InvalidCell("runtime presence requires exactly one %s" % label)
    return found[0].participant_id


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("runtime presence %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("runtime presence %s is not finite" % label)
    return value


def _validate_identity(value: str, label: str, *, prefix: str = "") -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > 512
        or (prefix and not value.startswith(prefix))
    ):
        raise InvalidCell("runtime presence %s is invalid" % label)
    return value


def _validate_runtime(value: str) -> str:
    if type(value) is not str or not _RUNTIME.fullmatch(value):
        raise InvalidCell("runtime presence runtime is invalid")
    return value


def _validate_now(value: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise InvalidCell("runtime presence %s is invalid" % label)
    return float(value)


def _validate_lease_seconds(value: float) -> float:
    seconds = _validate_now(value, "lease duration")
    if not _MIN_LEASE_SECONDS <= seconds <= _MAX_LEASE_SECONDS:
        raise InvalidCell("runtime presence lease duration is outside policy")
    return seconds


def _presence_root(agent_session_root: str) -> str:
    return "runtime-presence:sha256:" + hashlib.sha256(
        agent_session_root.encode("utf-8")
    ).hexdigest()


def bootstrap_runtime_presence_protocol(
    store: CellStore,
    *,
    prefix: str = "runtime-presence-protocol",
) -> RuntimePresenceProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_runtime_presence_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return RuntimePresenceProtocol(root_id, MappingProxyType(roles))


def project_runtime_presence_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "runtime-presence-protocol",
) -> RuntimePresenceProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    if any(_root not in snapshot.cells for _root in {root_id, *roles.values()}):
        raise InvalidCell("runtime-presence protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["presence-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("runtime-presence protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != set(roles.values()):
        raise InvalidCell("runtime-presence protocol vocabulary drifted")
    return RuntimePresenceProtocol(root_id, MappingProxyType(roles))


def read_runtime_presence(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
    presence_root: str,
) -> RuntimePresenceProjection:
    members = read_relation(snapshot, presence_root, budget=128)
    allowed = {
        protocol.role(name)
        for name in ROLE_NAMES
        if name not in ("vocabulary-member", "presence-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("runtime presence contains an undeclared field")
    session = _validate_identity(
        _one(members, protocol.role("presence-agent-session"), "agent session"),
        "agent session",
        prefix="app:agent-session:runtime:",
    )
    custody = _validate_identity(
        _one(members, protocol.role("presence-device-custody"), "device custody"),
        "device custody",
        prefix="device-custody:sha256:",
    )
    runtime_root = _one(members, protocol.role("presence-runtime"), "runtime")
    issued_root = _one(members, protocol.role("presence-issued-at"), "issued-at")
    refreshed_root = _one(
        members, protocol.role("presence-refreshed-at"), "refreshed-at"
    )
    expires_root = _one(members, protocol.role("presence-expires-at"), "expires-at")
    runtime = _validate_runtime(_text(snapshot, runtime_root, "runtime"))
    issued_at = _time(snapshot, issued_root, "issued-at")
    refreshed_at = _time(snapshot, refreshed_root, "refreshed-at")
    expires_at = _time(snapshot, expires_root, "expires-at")
    if not issued_at <= refreshed_at < expires_at:
        raise InvalidCell("runtime presence timestamps are invalid")
    return RuntimePresenceProjection(
        presence_root,
        session,
        custody,
        runtime,
        issued_at,
        refreshed_at,
        expires_at,
    )


def list_runtime_presences(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
) -> tuple[RuntimePresenceProjection, ...]:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("presence-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("runtime-presence registry contains a duplicate")
    return tuple(read_runtime_presence(snapshot, protocol, root) for root in roots)


def list_active_runtime_presences(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
    *,
    now: float,
) -> tuple[RuntimePresenceProjection, ...]:
    current_time = _validate_now(now, "current time")
    return tuple(
        presence for presence in list_runtime_presences(snapshot, protocol)
        if current_time < presence.expires_at
    )


def renew_runtime_presence(
    store: CellStore,
    protocol: RuntimePresenceProtocol,
    *,
    agent_session_root: str,
    device_custody_root: str,
    runtime: str,
    now: float,
    lease_seconds: float,
) -> tuple[RuntimePresenceProjection, int]:
    """Create or refresh one immutable-binding runtime presence lease."""
    session = _validate_identity(
        agent_session_root,
        "agent session",
        prefix="app:agent-session:runtime:",
    )
    custody = _validate_identity(
        device_custody_root,
        "device custody",
        prefix="device-custody:sha256:",
    )
    runtime = _validate_runtime(runtime)
    refreshed_at = _validate_now(now, "renewal time")
    expires_at = refreshed_at + _validate_lease_seconds(lease_seconds)
    root_id = _presence_root(session)
    snapshot = store.snapshot()
    if session not in snapshot.cells or custody not in snapshot.cells:
        raise InvalidCell(
            "runtime presence session and device custody must already exist"
        )

    if root_id in snapshot.cells:
        existing = read_runtime_presence(snapshot, protocol, root_id)
        if (
            existing.agent_session_root != session
            or existing.device_custody_root != custody
            or existing.runtime != runtime
        ):
            raise InvalidCell("runtime presence binding drifted")
        replacements = (
            _terminal(root_id + ":refreshed-at", "%.6f" % refreshed_at),
            _terminal(root_id + ":expires-at", "%.6f" % expires_at),
        )
        revision = store.commit(snapshot.revision, replace=replacements)
        return read_runtime_presence(store.snapshot(), protocol, root_id), revision

    values = {
        "runtime": runtime,
        "issued-at": "%.6f" % refreshed_at,
        "refreshed-at": "%.6f" % refreshed_at,
        "expires-at": "%.6f" % expires_at,
    }
    relation = compose_relation_cells(
        (
            (protocol.role("presence-agent-session"), session),
            (protocol.role("presence-device-custody"), custody),
            (protocol.role("presence-runtime"), root_id + ":runtime"),
            (protocol.role("presence-issued-at"), root_id + ":issued-at"),
            (protocol.role("presence-refreshed-at"), root_id + ":refreshed-at"),
            (protocol.role("presence-expires-at"), root_id + ":expires-at"),
        ),
        relation_id=root_id,
    )
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("presence-member"),
        root_id,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            *(_terminal(root_id + ":" + name, value)
              for name, value in values.items()),
            *relation.cells,
            *registry_patch.create,
        ),
        replace=registry_patch.replace,
    )
    return read_runtime_presence(store.snapshot(), protocol, root_id), revision


__all__ = [
    "RuntimePresenceProjection",
    "RuntimePresenceProtocol",
    "bootstrap_runtime_presence_protocol",
    "list_active_runtime_presences",
    "list_runtime_presences",
    "project_runtime_presence_protocol",
    "read_runtime_presence",
    "renew_runtime_presence",
]
