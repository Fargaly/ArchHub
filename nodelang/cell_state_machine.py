"""Generic graph-held operational state machines and integrity-checked evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "state",
    "current-state",
    "transition",
    "from-state",
    "to-state",
    "event",
    "required-evidence-type",
    "required-evidence-admission",
    "evidence-type",
    "evidence",
    "payload",
    "digest",
    "issuer",
    "history",
    "history-member",
    "actor",
    "context",
    "timestamp",
)


@dataclass(frozen=True, slots=True)
class StateMachineProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown state-machine role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class Transition:
    root_id: str
    from_state_root: str
    to_state_root: str
    event_root: str
    required_evidence_type_roots: tuple[str, ...]
    required_evidence_admission_roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    root_id: str
    evidence_type_root: str
    payload_root: str
    digest_root: str
    issuer_root: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    """One graph-held proof requirement: evidence type from one issuer."""

    root_id: str
    evidence_type_root: str
    issuer_root: str


@dataclass(frozen=True, slots=True)
class StateMachine:
    root_id: str
    state_roots: tuple[str, ...]
    transition_roots: tuple[str, ...]
    current_state_root: str
    current_state_incidence: str
    history_root: str


@dataclass(frozen=True, slots=True)
class StateTransitionEvent:
    root_id: str
    event_root: str
    from_state_root: str
    to_state_root: str
    actor_root: str
    timestamp_root: str
    evidence_roots: tuple[str, ...]
    context_roots: tuple[str, ...]


def _values(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _values(members, role_id)
    if len(values) != 1:
        raise InvalidCell("state graph requires exactly one %s" % label)
    return values[0]


def _closed_roles(
    members: tuple[RelationMember, ...], allowed: set[str], label: str
) -> None:
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("%s contains an undeclared field" % label)


def bootstrap_state_machine_protocol(
    store: CellStore,
    *,
    prefix: str = "state-machine-protocol",
) -> StateMachineProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = prefix + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return StateMachineProtocol(root_id, MappingProxyType(roles))


def build_transition(
    store: CellStore,
    protocol: StateMachineProtocol,
    *,
    transition_id: str,
    from_state_root: str,
    to_state_root: str,
    event_root: str,
    required_evidence_type_roots: Iterable[str] = (),
    required_evidence_admission_roots: Iterable[str] = (),
) -> str:
    required = tuple(required_evidence_type_roots)
    admissions = tuple(required_evidence_admission_roots)
    if len(required) != len(set(required)):
        raise InvalidCell("transition repeats an evidence type")
    if len(admissions) != len(set(admissions)):
        raise InvalidCell("transition repeats an evidence admission")
    if required and admissions:
        raise InvalidCell(
            "transition cannot mix legacy evidence types and evidence admissions"
        )
    if from_state_root == to_state_root:
        raise InvalidCell("state transition must change state")
    snapshot = store.snapshot()
    referenced = (
        from_state_root, to_state_root, event_root, *required, *admissions
    )
    if any(root not in snapshot.cells for root in referenced):
        raise InvalidCell("transition references a missing node")
    admission_pairs = tuple(
        read_evidence_admission(snapshot, protocol, root)
        for root in admissions
    )
    if len({
        (item.evidence_type_root, item.issuer_root)
        for item in admission_pairs
    }) != len(admission_pairs):
        raise InvalidCell("transition repeats an evidence admission pair")
    batch = CellBatch(store)
    batch.relation([
        (protocol.role("from-state"), from_state_root),
        (protocol.role("to-state"), to_state_root),
        (protocol.role("event"), event_root),
        *((protocol.role("required-evidence-type"), root) for root in required),
        *((protocol.role("required-evidence-admission"), root) for root in admissions),
    ], relation_id=transition_id)
    batch.commit()
    return transition_id


def read_transition(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    transition_root: str,
) -> Transition:
    members = read_relation(snapshot, transition_root, budget=256)
    _closed_roles(members, {
        protocol.role("from-state"),
        protocol.role("to-state"),
        protocol.role("event"),
        protocol.role("required-evidence-type"),
        protocol.role("required-evidence-admission"),
    }, "state transition")
    required = _values(members, protocol.role("required-evidence-type"))
    admissions = _values(members, protocol.role("required-evidence-admission"))
    if len(required) != len(set(required)):
        raise InvalidCell("transition repeats an evidence type")
    if len(admissions) != len(set(admissions)):
        raise InvalidCell("transition repeats an evidence admission")
    if required and admissions:
        raise InvalidCell(
            "transition cannot mix legacy evidence types and evidence admissions"
        )
    admission_pairs = tuple(
        read_evidence_admission(snapshot, protocol, root)
        for root in admissions
    )
    if len({
        (item.evidence_type_root, item.issuer_root)
        for item in admission_pairs
    }) != len(admission_pairs):
        raise InvalidCell("transition repeats an evidence admission pair")
    return Transition(
        transition_root,
        _one(members, protocol.role("from-state"), "source state"),
        _one(members, protocol.role("to-state"), "target state"),
        _one(members, protocol.role("event"), "transition event"),
        (
            tuple(item.evidence_type_root for item in admission_pairs)
            if admission_pairs else required
        ),
        admissions,
    )


def build_evidence_admission(
    store: CellStore,
    protocol: StateMachineProtocol,
    *,
    admission_id: str,
    evidence_type_root: str,
    issuer_root: str,
) -> str:
    """Declare the exact graph issuer permitted for one evidence type."""
    snapshot = store.snapshot()
    if (
        evidence_type_root not in snapshot.cells
        or issuer_root not in snapshot.cells
    ):
        raise InvalidCell("evidence admission references a missing node")
    batch = CellBatch(store)
    batch.relation([
        (protocol.role("evidence-type"), evidence_type_root),
        (protocol.role("issuer"), issuer_root),
    ], relation_id=admission_id)
    batch.commit()
    return admission_id


def read_evidence_admission(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    admission_root: str,
) -> EvidenceAdmission:
    members = read_relation(snapshot, admission_root, budget=128)
    _closed_roles(members, {
        protocol.role("evidence-type"),
        protocol.role("issuer"),
    }, "evidence admission")
    return EvidenceAdmission(
        admission_root,
        _one(members, protocol.role("evidence-type"), "evidence type"),
        _one(members, protocol.role("issuer"), "evidence issuer"),
    )


def build_evidence(
    store: CellStore,
    protocol: StateMachineProtocol,
    *,
    evidence_id: str,
    evidence_type_root: str,
    payload: bytes,
    issuer_root: str,
) -> str:
    snapshot = store.snapshot()
    cells = _compose_evidence_cells(
        snapshot,
        protocol,
        evidence_id=evidence_id,
        evidence_type_root=evidence_type_root,
        payload=payload,
        issuer_root=issuer_root,
    )
    store.commit(snapshot.revision, create=cells)
    return evidence_id


def _compose_evidence_cells(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    *,
    evidence_id: str,
    evidence_type_root: str,
    payload: bytes,
    issuer_root: str,
) -> tuple[Cell, ...]:
    if type(payload) is not bytes:
        raise TypeError("evidence payload must be bytes")
    if len(payload) > 1_048_576:
        raise InvalidCell("evidence payload exceeds the graph envelope limit")
    if (
        evidence_type_root not in snapshot.cells
        or issuer_root not in snapshot.cells
    ):
        raise InvalidCell("evidence references a missing node")
    payload_root = evidence_id + ":payload"
    digest_root = evidence_id + ":digest"
    digest = hashlib.sha256(payload).hexdigest().encode("ascii")
    relation = compose_relation_cells([
        (protocol.role("evidence-type"), evidence_type_root),
        (protocol.role("payload"), payload_root),
        (protocol.role("digest"), digest_root),
        (protocol.role("issuer"), issuer_root),
    ], relation_id=evidence_id)
    cells = (
        Cell(payload_root, NULL_CELL_ID, NULL_CELL_ID, payload),
        Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, digest),
        *relation.cells,
    )
    if len({cell.id for cell in cells}) != len(cells):
        raise InvalidCell("evidence physical region repeats a cell identity")
    if any(cell.id in snapshot.cells for cell in cells):
        raise InvalidCell("evidence identity already exists")
    return cells


def read_evidence(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    evidence_root: str,
) -> Evidence:
    members = read_relation(snapshot, evidence_root, budget=128)
    _closed_roles(members, {
        protocol.role("evidence-type"),
        protocol.role("payload"),
        protocol.role("digest"),
        protocol.role("issuer"),
    }, "evidence")
    evidence_type = _one(
        members, protocol.role("evidence-type"), "evidence type"
    )
    payload_root = _one(members, protocol.role("payload"), "evidence payload")
    digest_root = _one(members, protocol.role("digest"), "evidence digest")
    issuer_root = _one(members, protocol.role("issuer"), "evidence issuer")
    payload = snapshot.cells[payload_root].atom
    expected = snapshot.cells[digest_root].atom
    actual = hashlib.sha256(payload).hexdigest().encode("ascii")
    if expected != actual:
        raise InvalidCell("evidence content digest does not match")
    return Evidence(
        evidence_root,
        evidence_type,
        payload_root,
        digest_root,
        issuer_root,
        payload,
    )


def build_state_machine(
    store: CellStore,
    protocol: StateMachineProtocol,
    *,
    machine_id: str,
    state_roots: Iterable[str],
    transition_roots: Iterable[str],
    initial_state_root: str,
) -> str:
    states = tuple(state_roots)
    transitions = tuple(transition_roots)
    if not states or len(states) != len(set(states)):
        raise InvalidCell("state machine states must be nonempty and unique")
    if len(transitions) != len(set(transitions)):
        raise InvalidCell("state machine repeats a transition")
    if initial_state_root not in states:
        raise InvalidCell("initial state is outside the state machine")
    snapshot = store.snapshot()
    if any(root not in snapshot.cells for root in states):
        raise InvalidCell("state machine references a missing state")
    for root in transitions:
        transition = read_transition(snapshot, protocol, root)
        if (
            transition.from_state_root not in states
            or transition.to_state_root not in states
        ):
            raise InvalidCell("transition state is outside the state machine")
    history_root = machine_id + ":history"
    history = compose_relation_cells((), relation_id=history_root)
    machine = compose_relation_cells([
        *((protocol.role("state"), root) for root in states),
        *((protocol.role("transition"), root) for root in transitions),
        (protocol.role("current-state"), initial_state_root),
        (protocol.role("history"), history_root),
    ], relation_id=machine_id)
    store.commit(
        snapshot.revision,
        create=(*history.cells, *machine.cells),
    )
    return machine_id


def read_state_machine(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    machine_root: str,
) -> StateMachine:
    members = read_relation(snapshot, machine_root, budget=100_000)
    _closed_roles(members, {
        protocol.role("state"),
        protocol.role("transition"),
        protocol.role("current-state"),
        protocol.role("history"),
    }, "state machine")
    states = _values(members, protocol.role("state"))
    transitions = _values(members, protocol.role("transition"))
    current = _one(
        members, protocol.role("current-state"), "current state"
    )
    history = _one(members, protocol.role("history"), "state history")
    if current not in states:
        raise InvalidCell("current state is outside the state machine")
    if len(states) != len(set(states)) or len(transitions) != len(set(transitions)):
        raise InvalidCell("state machine repeats a declaration")
    current_member = next(
        member for member in members
        if member.role_id == protocol.role("current-state")
    )
    return StateMachine(
        machine_root,
        states,
        transitions,
        current,
        current_member.incidence_id,
        history,
    )


def read_instance_state_machine(
    snapshot: Snapshot,
    assembly_protocol,
    protocol: StateMachineProtocol,
    instance_root: str,
) -> StateMachine:
    instance = read_relation(snapshot, instance_root, budget=100_000)
    capabilities = _values(
        instance, assembly_protocol.role("capability")
    )
    if protocol.root_id not in capabilities:
        raise InvalidCell("assembly instance has no state-machine capability")
    machines = []
    for root in _values(instance, assembly_protocol.role("rule")):
        try:
            machines.append(read_state_machine(snapshot, protocol, root))
        except InvalidCell:
            continue
    if len(machines) != 1:
        raise InvalidCell("assembly instance requires one operational state machine")
    return machines[0]


def _read_transition_event(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    root_id: str,
) -> StateTransitionEvent:
    members = read_relation(snapshot, root_id, budget=256)
    _closed_roles(members, {
        protocol.role("event"),
        protocol.role("from-state"),
        protocol.role("to-state"),
        protocol.role("actor"),
        protocol.role("context"),
        protocol.role("timestamp"),
        protocol.role("evidence"),
    }, "state history event")
    return StateTransitionEvent(
        root_id,
        _one(members, protocol.role("event"), "event"),
        _one(members, protocol.role("from-state"), "source state"),
        _one(members, protocol.role("to-state"), "target state"),
        _one(members, protocol.role("actor"), "actor"),
        _one(members, protocol.role("timestamp"), "timestamp"),
        _values(members, protocol.role("evidence")),
        _values(members, protocol.role("context")),
    )


def machine_history(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    machine_root: str,
) -> tuple[StateTransitionEvent, ...]:
    machine = read_state_machine(snapshot, protocol, machine_root)
    members = read_relation(snapshot, machine.history_root, budget=100_000)
    if any(member.role_id != protocol.role("history-member") for member in members):
        raise InvalidCell("state history contains an undeclared member")
    return tuple(
        _read_transition_event(snapshot, protocol, member.participant_id)
        for member in members
    )


def transition_machine(
    store: CellStore,
    protocol: StateMachineProtocol,
    machine_root: str,
    *,
    event_root: str,
    expected_state_root: str,
    actor_root: str,
    evidence_roots: Iterable[str] = (),
    trusted_issuer_roots: Iterable[str] = (),
    context_roots: Iterable[str] = (),
    additional_create: Iterable[Cell] = (),
    additional_replace: Iterable[Cell] = (),
) -> tuple[str, int]:
    """Apply one declared transition and its released sidecar composition atomically."""
    snapshot = store.snapshot()
    sidecar_create = tuple(additional_create)
    sidecar_replace = tuple(additional_replace)
    created_ids = [cell.id for cell in sidecar_create]
    replaced_ids = [cell.id for cell in sidecar_replace]
    if (
        len(created_ids) != len(set(created_ids))
        or len(replaced_ids) != len(set(replaced_ids))
        or set(created_ids) & set(replaced_ids)
        or any(cell.id in snapshot.cells for cell in sidecar_create)
        or any(cell.id not in snapshot.cells for cell in sidecar_replace)
    ):
        raise InvalidCell("state transition sidecar cells are invalid")
    augmented_cells = dict(snapshot.cells)
    augmented_cells.update((cell.id, cell) for cell in sidecar_replace)
    augmented_cells.update((cell.id, cell) for cell in sidecar_create)
    augmented = Snapshot(snapshot.revision, MappingProxyType(augmented_cells))
    history_event_root, create, replace = _prepare_transition(
        augmented,
        protocol,
        machine_root,
        event_root=event_root,
        expected_state_root=expected_state_root,
        actor_root=actor_root,
        evidence_roots=evidence_roots,
        trusted_issuer_roots=trusted_issuer_roots,
        context_roots=context_roots,
    )
    all_created_ids = [cell.id for cell in (*sidecar_create, *create)]
    if len(all_created_ids) != len(set(all_created_ids)):
        raise InvalidCell("state transition sidecar collides with transition cells")
    replacements = {cell.id: cell for cell in sidecar_replace}
    for cell in replace:
        existing = replacements.get(cell.id)
        if existing is not None and existing != cell:
            raise InvalidCell("state transition sidecar replacement conflicts")
        replacements[cell.id] = cell
    revision = store.commit(
        snapshot.revision,
        create=(*sidecar_create, *create),
        replace=tuple(replacements.values()),
    )
    return history_event_root, revision


def transition_machine_with_new_evidence(
    store: CellStore,
    protocol: StateMachineProtocol,
    machine_root: str,
    *,
    event_root: str,
    expected_state_root: str,
    actor_root: str,
    evidence_id: str,
    evidence_type_root: str,
    evidence_payload: bytes,
    evidence_issuer_root: str,
    trusted_issuer_roots: Iterable[str],
    context_roots: Iterable[str] = (),
) -> tuple[str, str, int]:
    """Create one proof and consume it in the transition atomically."""
    snapshot = store.snapshot()
    evidence_cells = _compose_evidence_cells(
        snapshot,
        protocol,
        evidence_id=evidence_id,
        evidence_type_root=evidence_type_root,
        payload=evidence_payload,
        issuer_root=evidence_issuer_root,
    )
    augmented_cells = dict(snapshot.cells)
    augmented_cells.update((cell.id, cell) for cell in evidence_cells)
    augmented = Snapshot(
        snapshot.revision,
        MappingProxyType(augmented_cells),
    )
    history_event_root, transition_create, replace = _prepare_transition(
        augmented,
        protocol,
        machine_root,
        event_root=event_root,
        expected_state_root=expected_state_root,
        actor_root=actor_root,
        evidence_roots=(evidence_id,),
        trusted_issuer_roots=trusted_issuer_roots,
        context_roots=context_roots,
    )
    revision = store.commit(
        snapshot.revision,
        create=(*evidence_cells, *transition_create),
        replace=replace,
    )
    return evidence_id, history_event_root, revision


def _prepare_transition(
    snapshot: Snapshot,
    protocol: StateMachineProtocol,
    machine_root: str,
    *,
    event_root: str,
    expected_state_root: str,
    actor_root: str,
    evidence_roots: Iterable[str],
    trusted_issuer_roots: Iterable[str],
    context_roots: Iterable[str],
) -> tuple[str, tuple[Cell, ...], tuple[Cell, ...]]:
    machine = read_state_machine(snapshot, protocol, machine_root)
    if machine.current_state_root != expected_state_root:
        raise InvalidCell("state transition rejected a stale expected state")
    if actor_root not in snapshot.cells or event_root not in snapshot.cells:
        raise InvalidCell("state transition references a missing node")
    contexts = tuple(context_roots)
    if (
        len(contexts) != len(set(contexts))
        or any(root not in snapshot.cells for root in contexts)
    ):
        raise InvalidCell("state transition context is missing or duplicated")
    candidates = []
    for root in machine.transition_roots:
        transition = read_transition(snapshot, protocol, root)
        if (
            transition.from_state_root == machine.current_state_root
            and transition.event_root == event_root
        ):
            candidates.append(transition)
    if not candidates:
        raise InvalidCell("state transition is not admitted")
    if len(candidates) != 1:
        raise InvalidCell("state transition declaration is ambiguous")
    transition = candidates[0]

    evidence_ids = tuple(evidence_roots)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise InvalidCell("state transition repeats evidence")
    evidence = tuple(
        read_evidence(snapshot, protocol, root) for root in evidence_ids
    )
    trusted_issuers = set(trusted_issuer_roots)
    if any(item.issuer_root not in trusted_issuers for item in evidence):
        raise InvalidCell("state transition evidence issuer is not trusted")
    provided_types = {item.evidence_type_root for item in evidence}
    if not set(transition.required_evidence_type_roots).issubset(provided_types):
        raise InvalidCell("state transition is missing required evidence")
    if transition.required_evidence_admission_roots:
        required_pairs = {
            (item.evidence_type_root, item.issuer_root)
            for item in (
                read_evidence_admission(snapshot, protocol, root)
                for root in transition.required_evidence_admission_roots
            )
        }
        provided_pairs = {
            (item.evidence_type_root, item.issuer_root)
            for item in evidence
        }
        if not required_pairs.issubset(provided_pairs):
            raise InvalidCell(
                "state transition evidence does not satisfy declared admissions"
            )

    token = uuid.uuid4().hex
    timestamp_root = "state-event:timestamp:%s" % token
    history_event_root = "state-event:%s" % token
    timestamp = repr(time.time()).encode("ascii")
    history_event = compose_relation_cells([
        (protocol.role("event"), event_root),
        (protocol.role("from-state"), machine.current_state_root),
        (protocol.role("to-state"), transition.to_state_root),
        (protocol.role("actor"), actor_root),
        *((protocol.role("context"), root) for root in contexts),
        (protocol.role("timestamp"), timestamp_root),
        *((protocol.role("evidence"), root) for root in evidence_ids),
    ], relation_id=history_event_root)
    history_patch = prepare_append_relation_members(
        snapshot,
        machine.history_root,
        ((protocol.role("history-member"), history_event_root),),
        budget=100_000,
    )
    incidence = snapshot.cells[machine.current_state_incidence]
    replacements = {
        incidence.id: Cell(
            incidence.id,
            incidence.link0,
            transition.to_state_root,
            incidence.atom,
        )
    }
    for cell in history_patch.replace:
        replacements[cell.id] = cell
    return (
        history_event_root,
        (
            Cell(timestamp_root, NULL_CELL_ID, NULL_CELL_ID, timestamp),
            *history_event.cells,
            *history_patch.create,
        ),
        tuple(replacements.values()),
    )


__all__ = [
    "StateMachineProtocol", "Transition", "Evidence", "EvidenceAdmission",
    "StateMachine",
    "StateTransitionEvent", "bootstrap_state_machine_protocol",
    "build_transition", "read_transition", "build_evidence_admission",
    "read_evidence_admission", "build_evidence", "read_evidence",
    "build_state_machine", "read_state_machine", "machine_history",
    "read_instance_state_machine", "transition_machine",
    "transition_machine_with_new_evidence",
]
