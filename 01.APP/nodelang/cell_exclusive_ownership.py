"""Graph-held exclusive ownership generations over arbitrary resources."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import time
from typing import Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "ownership-member",
    "resource",
    "holder",
    "generation",
    "state",
    "acquired-at",
    "predecessor",
    "evidence",
    "transition",
    "from-state",
    "to-state",
    "at",
)
STATE_NAMES = ("active", "draining", "released", "failed")


@dataclass(frozen=True, slots=True)
class OwnershipProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown ownership role") from exc


@dataclass(frozen=True, slots=True)
class OwnershipProjection:
    root_id: str
    resource_root: str
    holder_root: str
    generation: int
    generation_root: str
    state_root: str
    state_incidence: str
    acquired_at_root: str
    predecessor_root: str | None
    evidence_roots: tuple[str, ...]
    transition_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnershipTransitionProjection:
    root_id: str
    from_state_root: str
    to_state_root: str
    at_root: str
    at: float
    evidence_root: str


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _participants(members, role_root: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_root
    )


def _one(members, role_root: str, label: str) -> tuple[str, str]:
    found = tuple(member for member in members if member.role_id == role_root)
    if len(found) != 1:
        raise InvalidCell("ownership requires exactly one %s" % label)
    return found[0].participant_id, found[0].incidence_id


def bootstrap_ownership_protocol(
    store: CellStore, *, prefix: str = "exclusive-ownership-protocol"
) -> OwnershipProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_ownership_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items()):
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return OwnershipProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def project_ownership_protocol(
    snapshot: Snapshot, *, prefix: str = "exclusive-ownership-protocol"
) -> OwnershipProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    required = {root_id, *roles.values(), *states.values()}
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("ownership protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {roles["vocabulary-member"], roles["ownership-member"]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("ownership protocol has an undeclared member")
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != {*roles.values(), *states.values()}:
        raise InvalidCell("ownership vocabulary drifted")
    registered = _participants(members, roles["ownership-member"])
    if len(registered) != len(set(registered)):
        raise InvalidCell("ownership registry contains a duplicate")
    return OwnershipProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def read_ownership(
    snapshot: Snapshot,
    protocol: OwnershipProtocol,
    ownership_root: str,
) -> OwnershipProjection:
    members = read_relation(snapshot, ownership_root, budget=100_000)
    admitted = {
        protocol.role(name) for name in (
            "resource", "holder", "generation", "state", "acquired-at",
            "predecessor", "evidence", "transition",
        )
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("ownership contains an undeclared field")
    resource_root, _ = _one(
        members, protocol.role("resource"), "resource"
    )
    holder_root, _ = _one(members, protocol.role("holder"), "holder")
    generation_root, _ = _one(
        members, protocol.role("generation"), "generation"
    )
    state_root, state_incidence = _one(
        members, protocol.role("state"), "state"
    )
    acquired_at_root, _ = _one(
        members, protocol.role("acquired-at"), "acquired-at"
    )
    predecessors = _participants(members, protocol.role("predecessor"))
    evidence = _participants(members, protocol.role("evidence"))
    transitions = _participants(members, protocol.role("transition"))
    if len(predecessors) > 1:
        raise InvalidCell("ownership has multiple predecessors")
    if not evidence:
        raise InvalidCell("ownership has no acquisition evidence")
    if state_root not in protocol.states.values():
        raise InvalidCell("ownership state is not admitted")
    try:
        generation = int(snapshot.cells[generation_root].atom.decode("ascii"))
        acquired_at = float(
            snapshot.cells[acquired_at_root].atom.decode("ascii")
        )
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("ownership generation or time is invalid") from exc
    if generation <= 0 or acquired_at <= 0:
        raise InvalidCell("ownership generation or time is invalid")
    for root in (*evidence, *transitions):
        if root not in snapshot.cells:
            raise InvalidCell("ownership evidence or transition is missing")
    transition_projections = tuple(
        read_ownership_transition(snapshot, protocol, root)
        for root in transitions
    )
    current_state = protocol.states["active"]
    previous_time = acquired_at
    admitted_transitions = {
        (protocol.states["active"], protocol.states["draining"]),
        (protocol.states["draining"], protocol.states["released"]),
        (protocol.states["active"], protocol.states["failed"]),
        (protocol.states["draining"], protocol.states["failed"]),
    }
    for transition in transition_projections:
        pair = (transition.from_state_root, transition.to_state_root)
        if pair not in admitted_transitions:
            raise InvalidCell("ownership transition pair is not admitted")
        if transition.from_state_root != current_state:
            raise InvalidCell("ownership transition history is discontinuous")
        if transition.at < previous_time:
            raise InvalidCell("ownership transition time moved backwards")
        current_state = transition.to_state_root
        previous_time = transition.at
    if current_state != state_root:
        raise InvalidCell("ownership state lacks transition history")
    return OwnershipProjection(
        ownership_root,
        resource_root,
        holder_root,
        generation,
        generation_root,
        state_root,
        state_incidence,
        acquired_at_root,
        predecessors[0] if predecessors else None,
        evidence,
        transitions,
    )


def read_ownership_transition(
    snapshot: Snapshot,
    protocol: OwnershipProtocol,
    transition_root: str,
) -> OwnershipTransitionProjection:
    members = read_relation(snapshot, transition_root, budget=64)
    admitted = {
        protocol.role("from-state"),
        protocol.role("to-state"),
        protocol.role("at"),
        protocol.role("evidence"),
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("ownership transition contains an undeclared field")
    from_state, _ = _one(
        members, protocol.role("from-state"), "transition source"
    )
    to_state, _ = _one(
        members, protocol.role("to-state"), "transition target"
    )
    at_root, _ = _one(members, protocol.role("at"), "transition time")
    evidence_root, _ = _one(
        members, protocol.role("evidence"), "transition evidence"
    )
    if (
        from_state not in protocol.states.values()
        or to_state not in protocol.states.values()
    ):
        raise InvalidCell("ownership transition state is not admitted")
    try:
        at = float(snapshot.cells[at_root].atom.decode("ascii"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("ownership transition time is invalid") from exc
    if at <= 0 or evidence_root not in snapshot.cells:
        raise InvalidCell("ownership transition time or evidence is invalid")
    return OwnershipTransitionProjection(
        transition_root,
        from_state,
        to_state,
        at_root,
        at,
        evidence_root,
    )


def list_ownerships(
    snapshot: Snapshot, protocol: OwnershipProtocol
) -> tuple[OwnershipProjection, ...]:
    roots = _participants(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role("ownership-member"),
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("ownership registry contains a duplicate")
    return tuple(read_ownership(snapshot, protocol, root) for root in roots)


def verify_ownership_authority(
    snapshot: Snapshot, protocol: OwnershipProtocol
) -> tuple[OwnershipProjection, ...]:
    ownerships = list_ownerships(snapshot, protocol)
    by_resource: dict[str, list[OwnershipProjection]] = {}
    for ownership in ownerships:
        by_resource.setdefault(ownership.resource_root, []).append(ownership)
    live_states = {protocol.states["active"], protocol.states["draining"]}
    for resource_root, resource_ownerships in by_resource.items():
        ordered = sorted(resource_ownerships, key=lambda item: item.generation)
        if [item.generation for item in ordered] != list(
            range(1, len(ordered) + 1)
        ):
            raise InvalidCell("ownership generations are not contiguous")
        if sum(item.state_root in live_states for item in ordered) > 1:
            raise InvalidCell("resource has multiple live owners")
        for index, ownership in enumerate(ordered):
            expected = None if index == 0 else ordered[index - 1].root_id
            if ownership.predecessor_root != expected:
                raise InvalidCell("ownership predecessor chain drifted")
        if ordered and ordered[-1].resource_root != resource_root:
            raise InvalidCell("ownership resource drifted")
    return ownerships


def acquire_ownership(
    store: CellStore,
    protocol: OwnershipProtocol,
    *,
    resource_root: str,
    holder_root: str,
    evidence_root: str,
    acquired_at: float | None = None,
    ownership_root: str | None = None,
) -> tuple[OwnershipProjection, int]:
    snapshot = store.snapshot()
    required = {
        protocol.root_id, resource_root, holder_root, evidence_root,
        protocol.states["active"],
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("ownership acquisition root is missing")
    existing = [
        item for item in verify_ownership_authority(snapshot, protocol)
        if item.resource_root == resource_root
    ]
    live_states = {protocol.states["active"], protocol.states["draining"]}
    if any(item.state_root in live_states for item in existing):
        raise InvalidCell("resource already has a live owner")
    generation = len(existing) + 1
    root_id = ownership_root or "ownership:" + uuid.uuid4().hex
    if root_id in snapshot.cells:
        raise InvalidCell("ownership identity already exists")
    generation_cell = _terminal(root_id + ":generation", str(generation))
    acquired_cell = _terminal(
        root_id + ":acquired-at",
        repr(time.time() if acquired_at is None else float(acquired_at)),
    )
    members = [
        (protocol.role("resource"), resource_root),
        (protocol.role("holder"), holder_root),
        (protocol.role("generation"), generation_cell.id),
        (protocol.role("state"), protocol.states["active"]),
        (protocol.role("acquired-at"), acquired_cell.id),
        (protocol.role("evidence"), evidence_root),
    ]
    if existing:
        members.append((protocol.role("predecessor"), existing[-1].root_id))
    relation = compose_relation_cells(members, relation_id=root_id)
    registry_patch = prepare_append_relation_members(
        snapshot,
        protocol.root_id,
        ((protocol.role("ownership-member"), root_id),),
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            generation_cell,
            acquired_cell,
            *relation.cells,
            *registry_patch.create,
        ),
        replace=registry_patch.replace,
    )
    return read_ownership(store.snapshot(), protocol, root_id), revision


def transition_ownership(
    store: CellStore,
    protocol: OwnershipProtocol,
    ownership_root: str,
    *,
    event: str,
    evidence_root: str,
    transitioned_at: float | None = None,
) -> tuple[OwnershipProjection, int]:
    transitions = {
        "drain": ("active", "draining"),
        "release": ("draining", "released"),
        "fail-active": ("active", "failed"),
        "fail-draining": ("draining", "failed"),
    }
    if event not in transitions:
        raise InvalidCell("ownership transition event is not admitted")
    snapshot = store.snapshot()
    if evidence_root not in snapshot.cells:
        raise InvalidCell("ownership transition evidence is missing")
    current = read_ownership(snapshot, protocol, ownership_root)
    source_name, target_name = transitions[event]
    source_root = protocol.states[source_name]
    target_root = protocol.states[target_name]
    if current.state_root != source_root:
        raise InvalidCell("ownership transition source state is invalid")
    event_root = "%s:transition:%s" % (ownership_root, uuid.uuid4().hex)
    at_cell = _terminal(
        event_root + ":at",
        repr(time.time() if transitioned_at is None else float(transitioned_at)),
    )
    event_relation = compose_relation_cells((
        (protocol.role("from-state"), source_root),
        (protocol.role("to-state"), target_root),
        (protocol.role("at"), at_cell.id),
        (protocol.role("evidence"), evidence_root),
    ), relation_id=event_root)
    owner_patch = prepare_append_relation_members(
        snapshot,
        ownership_root,
        ((protocol.role("transition"), event_root),),
        budget=100_000,
    )
    state_incidence = snapshot.cells[current.state_incidence]
    revision = store.commit(
        snapshot.revision,
        create=(at_cell, *event_relation.cells, *owner_patch.create),
        replace=(
            Cell(
                state_incidence.id,
                state_incidence.link0,
                target_root,
                state_incidence.atom,
            ),
            *owner_patch.replace,
        ),
    )
    return read_ownership(store.snapshot(), protocol, ownership_root), revision


__all__ = [
    "OwnershipProjection",
    "OwnershipProtocol",
    "OwnershipTransitionProjection",
    "acquire_ownership",
    "bootstrap_ownership_protocol",
    "list_ownerships",
    "project_ownership_protocol",
    "read_ownership",
    "read_ownership_transition",
    "transition_ownership",
    "verify_ownership_authority",
]
