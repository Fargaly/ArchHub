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
from .runtime_presence_lease_storage import RuntimePresenceLeaseStorage
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


def ensure_store_lease_storage(
    store: CellStore,
    lease_storage: RuntimePresenceLeaseStorage | None = None,
) -> RuntimePresenceLeaseStorage:
    """Ensure one instance-owned lease storage attached to the CellStore without globals or monkeypatches."""
    storage = getattr(store, "_runtime_presence_lease_storage", None)
    if storage is None or storage._closed:
        if lease_storage is not None:
            storage = lease_storage
        else:
            storage = RuntimePresenceLeaseStorage(store.database_path)
        store._runtime_presence_lease_storage = storage
    return storage


@dataclass(frozen=True, slots=True)
class RuntimePresenceProtocol:
    root_id: str
    roles: Mapping[str, str]
    lease_storage: RuntimePresenceLeaseStorage | None = None

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
    generation: int = 1


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
    lease_storage: RuntimePresenceLeaseStorage | None = None,
) -> RuntimePresenceProtocol:
    storage = ensure_store_lease_storage(store, lease_storage)
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_runtime_presence_protocol(
            store.snapshot(),
            prefix=prefix,
            lease_storage=storage,
            store=store,
        )
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal(root, name))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return RuntimePresenceProtocol(
        root_id, MappingProxyType(roles), lease_storage=storage
    )


def project_runtime_presence_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "runtime-presence-protocol",
    lease_storage: RuntimePresenceLeaseStorage | None = None,
    store: CellStore | None = None,
) -> RuntimePresenceProtocol:
    if lease_storage is None and store is not None:
        lease_storage = ensure_store_lease_storage(store)
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
    protocol = RuntimePresenceProtocol(
        root_id, MappingProxyType(roles), lease_storage=lease_storage
    )
    if lease_storage is not None:
        import time as _time
        lease_storage.migrate_legacy_leases(snapshot, protocol, now=_time.time())
    return protocol


# SPEC 3.3: a runtime presence is a heartbeat. Its binding (agent session,
# device custody, runtime, first-seen time) and its lease are indexed records
# referenced by the graph-held agent session; no graph composition per
# presence. Presences composed as Cells by earlier releases remain readable.
BINDING_KIND = "runtime-presence"


def _read_presence_binding(storage, presence_root: str):
    if storage is None:
        return None
    row = storage.get_record(BINDING_KIND, presence_root)
    if row is None:
        return None
    payload = row["payload"]
    try:
        return (
            _validate_identity(
                str(payload["session"]), "agent session",
                prefix="app:agent-session:runtime:",
            ),
            _validate_identity(
                str(payload["custody"]), "device custody",
                prefix="device-custody:sha256:",
            ),
            _validate_runtime(str(payload["runtime"])),
            float(payload["issued_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCell("runtime presence binding record is malformed") from exc


def _presence_projection(
    presence_root, session, custody, runtime, issued_at, storage
) -> RuntimePresenceProjection:
    if storage is None:
        raise InvalidCell("runtime presence protocol has no active lease storage: fail closed")
    lease = storage.get_lease(presence_root)
    if lease is None:
        raise InvalidCell("runtime presence lease not found: fail closed")
    refreshed_at, expires_at, generation, owner = lease
    if owner != session:
        raise InvalidCell("runtime presence lease owner mismatch: fail closed")
    if not (issued_at - 1e-5 <= refreshed_at < expires_at):
        raise InvalidCell("runtime presence timestamps are invalid")
    return RuntimePresenceProjection(
        presence_root, session, custody, runtime, issued_at, refreshed_at,
        expires_at, generation=generation,
    )


def read_runtime_presence(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
    presence_root: str,
    *,
    lease_storage: RuntimePresenceLeaseStorage | None = None,
) -> RuntimePresenceProjection:
    active_storage = (
        lease_storage if lease_storage is not None else protocol.lease_storage
    )
    if presence_root not in snapshot.cells:
        if active_storage is None:
            raise InvalidCell("runtime presence protocol has no active lease storage: fail closed")
        binding = _read_presence_binding(active_storage, presence_root)
        if binding is None:
            raise InvalidCell("runtime presence is unknown")
        return _presence_projection(presence_root, *binding, active_storage)
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
    runtime = _validate_runtime(_text(snapshot, runtime_root, "runtime"))
    issued_at = _time(snapshot, issued_root, "issued-at")

    active_storage = (
        lease_storage if lease_storage is not None else protocol.lease_storage
    )
    if active_storage is None:
        raise InvalidCell("runtime presence protocol has no active lease storage: fail closed")

    lease = active_storage.get_lease(presence_root)
    if lease is None:
        raise InvalidCell("runtime presence lease not found: fail closed")

    refreshed_at, expires_at, generation, owner_token = lease
    if owner_token != session:
        raise InvalidCell("runtime presence lease owner mismatch: fail closed")

    if not (issued_at - 1e-5 <= refreshed_at < expires_at):
        raise InvalidCell("runtime presence timestamps are invalid")
    return RuntimePresenceProjection(
        presence_root,
        session,
        custody,
        runtime,
        issued_at,
        refreshed_at,
        expires_at,
        generation=generation,
    )


def list_runtime_presences(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
    *,
    lease_storage: RuntimePresenceLeaseStorage | None = None,
) -> tuple[RuntimePresenceProjection, ...]:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("presence-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("runtime-presence registry contains a duplicate")
    active_storage = (
        lease_storage if lease_storage is not None else protocol.lease_storage
    )
    if active_storage is not None:
        roots = roots + tuple(
            row["record_root"]
            for row in active_storage.list_records(BINDING_KIND, limit=10_000)
            if row["record_root"] not in roots
        )
    results = []
    for root in roots:
        try:
            results.append(
                read_runtime_presence(
                    snapshot, protocol, root, lease_storage=lease_storage
                )
            )
        except InvalidCell:
            continue
    return tuple(results)


def list_active_runtime_presences(
    snapshot: Snapshot,
    protocol: RuntimePresenceProtocol,
    *,
    now: float,
    lease_storage: RuntimePresenceLeaseStorage | None = None,
) -> tuple[RuntimePresenceProjection, ...]:
    current_time = _validate_now(now, "current time")
    return tuple(
        presence
        for presence in list_runtime_presences(
            snapshot, protocol, lease_storage=lease_storage
        )
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
    expected_generation: int | None = None,
    lease_storage: RuntimePresenceLeaseStorage | None = None,
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
    refreshed_at = float("%.6f" % _validate_now(now, "renewal time"))
    expires_at = float("%.6f" % (refreshed_at + _validate_lease_seconds(lease_seconds)))
    root_id = _presence_root(session)
    snapshot = store.snapshot()
    if session not in snapshot.cells or custody not in snapshot.cells:
        raise InvalidCell(
            "runtime presence session and device custody must already exist"
        )

    active_storage = (
        lease_storage
        if lease_storage is not None
        else (
            protocol.lease_storage
            if protocol.lease_storage is not None
            else ensure_store_lease_storage(store)
        )
    )

    if root_id in snapshot.cells:
        members = read_relation(snapshot, root_id, budget=128)
        existing_session = _one(members, protocol.role("presence-agent-session"), "agent session")
        existing_custody = _one(members, protocol.role("presence-device-custody"), "device custody")
        runtime_root = _one(members, protocol.role("presence-runtime"), "runtime")
        existing_runtime = _validate_runtime(_text(snapshot, runtime_root, "runtime"))

        if (
            existing_session != session
            or existing_custody != custody
            or existing_runtime != runtime
        ):
            raise InvalidCell("runtime presence binding drifted")

        existing_lease = active_storage.get_lease(root_id)
        if existing_lease is None:
            if expected_generation is not None:
                raise InvalidCell(
                    f"stale runtime presence lease writer: lease not found (expected {expected_generation})"
                )
            active_storage.create_initial_lease(root_id, session, refreshed_at, expires_at)
        else:
            active_storage.renew_lease(
                root_id,
                session,
                refreshed_at,
                expires_at,
                expected_generation=expected_generation,
            )
        return (
            read_runtime_presence(
                snapshot, protocol, root_id, lease_storage=active_storage
            ),
            store.revision,
        )

    binding = _read_presence_binding(active_storage, root_id)
    if binding is not None:
        if binding[:3] != (session, custody, runtime):
            raise InvalidCell("runtime presence binding drifted")
        if active_storage.get_lease(root_id) is None:
            if expected_generation is not None:
                raise InvalidCell(
                    f"stale runtime presence lease writer: lease not found (expected {expected_generation})"
                )
            active_storage.create_initial_lease(root_id, session, refreshed_at, expires_at)
        else:
            active_storage.renew_lease(
                root_id, session, refreshed_at, expires_at,
                expected_generation=expected_generation,
            )
        return (
            _presence_projection(root_id, *binding, active_storage),
            store.revision,
        )

    if expected_generation is not None:
        raise InvalidCell(
            f"stale runtime presence lease writer: lease not found (expected {expected_generation})"
        )

    # The first heartbeat of a session records its binding and lease; the
    # graph gains nothing. There is no graph-composition fallback.
    active_storage.put_record(
        BINDING_KIND,
        root_id,
        owner_root=session,
        state="bound",
        payload={
            "session": session,
            "custody": custody,
            "runtime": runtime,
            "issued_at": refreshed_at,
        },
        authority_revision=snapshot.revision,
        updated_at=refreshed_at,
        create_only=True,
        retire_states=("bound",),
    )
    active_storage.create_initial_lease(root_id, session, refreshed_at, expires_at)
    return (
        _presence_projection(
            root_id, session, custody, runtime, refreshed_at, active_storage
        ),
        store.revision,
    )


__all__ = [
    "RuntimePresenceProjection",
    "RuntimePresenceProtocol",
    "bootstrap_runtime_presence_protocol",
    "ensure_store_lease_storage",
    "list_active_runtime_presences",
    "list_runtime_presences",
    "project_runtime_presence_protocol",
    "read_runtime_presence",
    "renew_runtime_presence",
]
