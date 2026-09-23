"""Runtime ownership as bounded indexed records (SPEC 3.3).

The ownership protocol, the runtime-ownership court and its signing key stay
graph authority. Each process lifetime's acquisition, drain and release is an
operational instance: it is recorded with its signed court evidence in the
primary database's operational record table, never as a graph revision.
"""
from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any, Mapping

from .runtime_presence_lease_storage import RuntimePresenceLeaseStorage
from .universal_cell import InvalidCell


KIND = "runtime-ownership"
LIVE_STATES = ("active", "draining")
TERMINAL_STATES = ("released", "failed")
TRANSITIONS = {
    "drain": ("active", "draining"),
    "release": ("draining", "released"),
    "fail-active": ("active", "failed"),
    "fail-draining": ("draining", "failed"),
}


@dataclass(frozen=True, slots=True)
class RuntimeOwnershipRecord:
    root_id: str
    resource_root: str
    holder_root: str
    generation: int
    state: str
    acquired_at: float
    predecessor_root: str | None
    evidence: Mapping[str, Any]
    transitions: tuple[Mapping[str, Any], ...]
    record_generation: int


def _projection(row: Mapping[str, Any]) -> RuntimeOwnershipRecord:
    payload = row["payload"]
    try:
        record = RuntimeOwnershipRecord(
            row["record_root"],
            str(payload["resource"]),
            str(payload["holder"]),
            int(payload["generation"]),
            str(row["state"]),
            float(payload["acquired_at"]),
            payload.get("predecessor"),
            payload["evidence"],
            tuple(payload.get("transitions") or ()),
            int(row["generation"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCell("runtime ownership record is malformed") from exc
    if record.resource_root != row["owner_root"]:
        raise InvalidCell("runtime ownership record resource drifted")
    if record.state not in LIVE_STATES + TERMINAL_STATES:
        raise InvalidCell("runtime ownership record state is unknown")
    return record


def _payload(record: RuntimeOwnershipRecord) -> dict[str, Any]:
    return {
        "resource": record.resource_root,
        "holder": record.holder_root,
        "generation": record.generation,
        "acquired_at": record.acquired_at,
        "predecessor": record.predecessor_root,
        "evidence": dict(record.evidence),
        "transitions": [dict(item) for item in record.transitions],
    }


def read_runtime_ownership(
    storage: RuntimePresenceLeaseStorage, root_id: str
) -> RuntimeOwnershipRecord | None:
    row = storage.get_record(KIND, root_id)
    return None if row is None else _projection(row)


def list_runtime_ownerships(
    storage: RuntimePresenceLeaseStorage,
    resource_root: str,
    *,
    states: tuple[str, ...] | None = None,
) -> tuple[RuntimeOwnershipRecord, ...]:
    rows = storage.list_records(
        KIND, owner_root=resource_root, states=states, limit=10_000
    )
    return tuple(sorted(
        (_projection(row) for row in rows), key=lambda item: item.generation
    ))


def acquire_runtime_ownership(
    storage: RuntimePresenceLeaseStorage,
    *,
    resource_root: str,
    holder_root: str,
    evidence: Mapping[str, Any],
    authority_revision: int,
    now: float,
) -> RuntimeOwnershipRecord:
    """Record one new live owner; a resource never has two."""
    existing = list_runtime_ownerships(storage, resource_root)
    if any(item.state in LIVE_STATES for item in existing):
        raise InvalidCell("resource already has a live owner")
    latest = existing[-1] if existing else None
    record = RuntimeOwnershipRecord(
        "ownership:" + uuid.uuid4().hex,
        resource_root,
        holder_root,
        1 if latest is None else latest.generation + 1,
        "active",
        float(now),
        None if latest is None else latest.root_id,
        dict(evidence),
        (),
        1,
    )
    storage.put_record(
        KIND,
        record.root_id,
        owner_root=resource_root,
        state="active",
        payload=_payload(record),
        authority_revision=authority_revision,
        updated_at=float(now),
        create_only=True,
        event="acquire",
        retire_states=TERMINAL_STATES,
    )
    return record


def transition_runtime_ownership(
    storage: RuntimePresenceLeaseStorage,
    root_id: str,
    *,
    event: str,
    evidence: Mapping[str, Any],
    authority_revision: int,
    now: float,
) -> RuntimeOwnershipRecord:
    if event not in TRANSITIONS:
        raise InvalidCell("ownership transition event is not admitted")
    current = read_runtime_ownership(storage, root_id)
    if current is None:
        raise InvalidCell("runtime ownership record is missing")
    source, target = TRANSITIONS[event]
    if current.state != source:
        raise InvalidCell("ownership transition source state is invalid")
    updated = RuntimeOwnershipRecord(
        current.root_id,
        current.resource_root,
        current.holder_root,
        current.generation,
        target,
        current.acquired_at,
        current.predecessor_root,
        current.evidence,
        (*current.transitions, {
            "event": event,
            "from": source,
            "to": target,
            "at": float(now),
            "evidence": dict(evidence),
        }),
        current.record_generation + 1,
    )
    storage.put_record(
        KIND,
        root_id,
        owner_root=current.resource_root,
        state=target,
        payload=_payload(updated),
        authority_revision=authority_revision,
        updated_at=float(now),
        expected_generation=current.record_generation,
        event=event,
    )
    return updated


__all__ = [
    "KIND",
    "LIVE_STATES",
    "RuntimeOwnershipRecord",
    "TERMINAL_STATES",
    "acquire_runtime_ownership",
    "list_runtime_ownerships",
    "read_runtime_ownership",
    "transition_runtime_ownership",
]