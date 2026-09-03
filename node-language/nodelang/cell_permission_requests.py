"""Interpreted human decisions over the released Permission Request assembly."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import time
from types import MappingProxyType
from typing import Mapping
import uuid

from .cell_catalog import AssemblyProtocol
from .cell_protocols import RelationMember, read_relation
from .cell_state_machine import (
    StateMachineProtocol,
    read_instance_state_machine,
    read_transition,
    transition_machine_with_new_evidence,
)
from .universal_cell import CellStore, InvalidCell, Snapshot


FIELD_NAMES = frozenset({
    "requester", "action", "object", "parameters", "reason", "expires-at",
})
USER_DECISION_EVENTS = frozenset({"approve", "reject", "cancel"})


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    root_id: str
    definition_root: str
    machine_root: str
    fields: Mapping[str, str]
    field_roots: Mapping[str, str]


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = tuple(
        item.participant_id for item in members if item.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("permission request requires exactly one %s" % label)
    return values[0]


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("permission request %s is not UTF-8 text" % label) from exc


def read_permission_request(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    operational: StateMachineProtocol,
    instance_root: str,
    *,
    expected_definition_root: str,
) -> PermissionRequest:
    instance = read_relation(snapshot, instance_root, budget=100_000)
    definition = _one(
        instance, assembly.role("provenance"), "definition provenance"
    )
    if definition != expected_definition_root:
        raise InvalidCell("node is not a released Permission Request instance")
    fields: dict[str, str] = {}
    roots: dict[str, str] = {}
    for interface_root in (
        item.participant_id for item in instance
        if item.role_id == assembly.role("interface")
    ):
        interface = read_relation(snapshot, interface_root, budget=100_000)
        name_root = _one(interface, assembly.role("name"), "interface name")
        name = _text(snapshot, name_root, "interface name")
        if name not in FIELD_NAMES:
            continue
        if name in fields:
            raise InvalidCell("permission request repeats a declared field")
        target_root = _one(
            interface, assembly.role("interface-target"), "interface target"
        )
        fields[name] = _text(snapshot, target_root, name)
        roots[name] = target_root
    if set(fields) != FIELD_NAMES:
        raise InvalidCell("permission request is missing a declared field")
    machine = read_instance_state_machine(
        snapshot, assembly, operational, instance_root
    )
    return PermissionRequest(
        instance_root,
        definition,
        machine.root_id,
        MappingProxyType(fields),
        MappingProxyType(roots),
    )


def _expiry_timestamp(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidCell(
                "permission request expiry must be UTC ISO-8601 or epoch seconds"
            ) from exc
        if parsed.tzinfo is None:
            raise InvalidCell("permission request expiry must include a timezone")
        result = parsed.astimezone(timezone.utc).timestamp()
    if not math.isfinite(result):
        raise InvalidCell("permission request expiry must be finite")
    return result


def _validate_approvable(request: PermissionRequest, *, now: float) -> bytes:
    defaults = {
        "requester": "unassigned",
        "action": "unconfigured",
        "object": "unwired",
        "parameters": "empty",
        "reason": "unset",
        "expires-at": "unset",
    }
    incomplete = tuple(
        name for name, default in defaults.items()
        if not request.fields[name].strip()
        or request.fields[name].strip() == default
    )
    if incomplete:
        raise InvalidCell(
            "permission request is incomplete: %s" % ", ".join(incomplete)
        )
    try:
        parameters = json.loads(request.fields["parameters"])
    except json.JSONDecodeError as exc:
        raise InvalidCell("permission request parameters must be JSON") from exc
    if not isinstance(parameters, dict):
        raise InvalidCell("permission request parameters must be a JSON object")
    expires_at = _expiry_timestamp(request.fields["expires-at"])
    if expires_at <= now:
        raise InvalidCell("permission request has expired")
    canonical = json.dumps(
        dict(request.fields),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return canonical


def decide_permission_request(
    store: CellStore,
    assembly: AssemblyProtocol,
    operational: StateMachineProtocol,
    instance_root: str,
    *,
    expected_definition_root: str,
    event_root: str,
    expected_state_root: str,
    actor_root: str,
    context_roots: tuple[str, ...] | list[str] = (),
    now: float | None = None,
) -> tuple[str, str, int]:
    """Atomically issue and consume the authenticated user's decision proof."""
    decided_at = time.time() if now is None else float(now)
    if not math.isfinite(decided_at):
        raise InvalidCell("permission decision time must be finite")
    snapshot = store.snapshot()
    request = read_permission_request(
        snapshot,
        assembly,
        operational,
        instance_root,
        expected_definition_root=expected_definition_root,
    )
    machine = read_instance_state_machine(
        snapshot, assembly, operational, instance_root
    )
    if machine.current_state_root != expected_state_root:
        raise InvalidCell("state transition rejected a stale expected state")
    candidates = []
    for root in machine.transition_roots:
        transition = read_transition(snapshot, operational, root)
        if (
            transition.from_state_root == machine.current_state_root
            and transition.event_root == event_root
        ):
            candidates.append(transition)
    if len(candidates) != 1:
        raise InvalidCell("permission decision transition is not admitted")
    transition = candidates[0]
    event_label = _text(snapshot, transition.event_root, "decision event")
    if event_label not in USER_DECISION_EVENTS:
        raise InvalidCell("permission decision event requires an adapter")
    if len(transition.required_evidence_type_roots) != 1:
        raise InvalidCell("permission decision requires one evidence type")
    evidence_type = transition.required_evidence_type_roots[0]
    if _text(snapshot, evidence_type, "decision evidence type") != "user decision":
        raise InvalidCell("permission decision evidence contract is invalid")
    canonical = (
        _validate_approvable(request, now=decided_at)
        if event_label == "approve"
        else json.dumps(
            dict(request.fields),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )
    payload = json.dumps({
        "actor": actor_root,
        "decision": event_label,
        "recorded_at": decided_at,
        "request": request.root_id,
        "request_digest": hashlib.sha256(canonical).hexdigest(),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    evidence_id = "permission-decision:%s" % uuid.uuid4().hex
    return transition_machine_with_new_evidence(
        store,
        operational,
        request.machine_root,
        event_root=event_root,
        expected_state_root=expected_state_root,
        actor_root=actor_root,
        evidence_id=evidence_id,
        evidence_type_root=evidence_type,
        evidence_payload=payload,
        evidence_issuer_root=actor_root,
        trusted_issuer_roots=(actor_root,),
        context_roots=tuple(context_roots),
    )


__all__ = [
    "PermissionRequest", "read_permission_request", "decide_permission_request",
]
