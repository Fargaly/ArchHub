"""Generic graph-held status events for released authorities.

The governed subject is never rewritten to express revocation.  A separately
authorised, append-only event records its current status and pins the exact
subject digest that was reviewed.  Consumers resolve this ledger before use.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_lifecycle import graph_content_digest
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
    "status-entry-member",
    "status-subject",
    "status-subject-digest",
    "status-state",
    "status-actor",
    "status-source-revision",
    "status-policy",
    "status-action",
    "status-rule",
    "status-reason",
    "status-authorization-receipt",
    "status-created-revision",
    "status-digest",
)
STATE_NAMES = ("active", "suspended", "revoked")
RELATION_BUDGET = 100_000
MAX_RULES = 256
MAX_TEXT_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class StatusLedgerProtocol:
    root_id: str
    registry_root: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown status-ledger role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown status-ledger state %r" % name) from exc


@dataclass(frozen=True, slots=True)
class StatusEventProjection:
    root_id: str
    subject_root: str
    subject_digest_root: str
    subject_digest: str
    state_root: str
    actor_root: str
    source_revision_root: str
    source_revision: int
    policy_root: str
    action_root: str
    rule_roots: tuple[str, ...]
    reason_root: str
    reason: str
    authorization_receipt_root: str
    created_revision_root: str
    created_revision: int
    digest_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class PreparedStatusEvent:
    root_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def _protocol_for_prefix(prefix: str) -> StatusLedgerProtocol:
    return StatusLedgerProtocol(
        prefix + ":root",
        prefix + ":registry",
        MappingProxyType({
            name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
        }),
        MappingProxyType({
            name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES
        }),
    )


def _terminal(root: str, value: str | int) -> Cell:
    raw = str(value).encode("utf-8")
    if not raw or len(raw) > MAX_TEXT_BYTES:
        raise InvalidCell("status-ledger value is outside bounds")
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, raw)


def _text(snapshot: Snapshot, root: str, label: str) -> str:
    try:
        cell = snapshot.cells[root]
    except KeyError as exc:
        raise InvalidCell("%s is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s is not a terminal value" % label)
    try:
        value = cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s is not UTF-8" % label) from exc
    if not value or len(cell.atom) > MAX_TEXT_BYTES:
        raise InvalidCell("%s is outside bounds" % label)
    return value


def _integer(snapshot: Snapshot, root: str, label: str) -> int:
    value = _text(snapshot, root, label)
    if not value.isascii() or not value.isdigit():
        raise InvalidCell("%s is not a non-negative integer" % label)
    return int(value)


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _one(members: tuple[RelationMember, ...], role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("status event requires exactly one %s" % label)
    return values[0]


def _validate_protocol(
    snapshot: Snapshot, protocol: StatusLedgerProtocol
) -> None:
    expected = _protocol_for_prefix(protocol.root_id.removesuffix(":root"))
    if protocol != expected:
        raise InvalidCell("status-ledger vocabulary mapping drifted")
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        if _text(snapshot, root, "status-ledger vocabulary") != name:
            raise InvalidCell("status-ledger vocabulary drifted")
    members = read_relation(snapshot, protocol.root_id, budget=RELATION_BUDGET)
    expected_members = tuple(
        (protocol.role("vocabulary-member"), root)
        for root in (
            *protocol.roles.values(),
            *protocol.states.values(),
            protocol.registry_root,
        )
    )
    if snapshot.cells[protocol.root_id].atom != b"" or tuple(
        (member.role_id, member.participant_id) for member in members
    ) != expected_members:
        raise InvalidCell("status-ledger vocabulary relation drifted")
    registry = read_relation(
        snapshot, protocol.registry_root, budget=RELATION_BUDGET
    )
    if snapshot.cells[protocol.registry_root].atom != b"" or any(
        member.role_id != protocol.role("status-entry-member")
        for member in registry
    ):
        raise InvalidCell("status-ledger registry drifted")
    roots = tuple(member.participant_id for member in registry)
    if len(roots) != len(set(roots)):
        raise InvalidCell("status-ledger registry repeats an event")


def bootstrap_status_ledger_protocol(
    store: CellStore, *, prefix: str = "status-ledger-protocol"
) -> StatusLedgerProtocol:
    protocol = _protocol_for_prefix(prefix)
    batch = CellBatch(store)
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        batch.add(_terminal(root, name))
    batch.relation((), relation_id=protocol.registry_root)
    batch.relation(
        (
            (protocol.role("vocabulary-member"), root)
            for root in (
                *protocol.roles.values(),
                *protocol.states.values(),
                protocol.registry_root,
            )
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    _validate_protocol(store.snapshot(), protocol)
    return protocol


def open_status_ledger_protocol(
    snapshot: Snapshot, *, prefix: str = "status-ledger-protocol"
) -> StatusLedgerProtocol:
    protocol = _protocol_for_prefix(prefix)
    _validate_protocol(snapshot, protocol)
    return protocol


def _event_digest(
    snapshot: Snapshot, event: StatusEventProjection
) -> str:
    digest = hashlib.blake2b(digest_size=32)
    values = (
        event.root_id,
        event.subject_root,
        event.subject_digest,
        event.state_root,
        event.actor_root,
        str(event.source_revision),
        event.policy_root,
        event.action_root,
        *event.rule_roots,
        event.reason,
        event.authorization_receipt_root,
        str(event.created_revision),
    )
    for value in values:
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    # The subject and receipt are already pinned by their explicit verified
    # digests. Hashing their entire reachable closures would make this event
    # recursively depend on the status ledger that contains it.
    for root in (
        event.actor_root,
        event.policy_root,
        event.action_root,
        *event.rule_roots,
    ):
        raw = graph_content_digest(snapshot, root, budget=RELATION_BUDGET)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def read_status_event(
    snapshot: Snapshot,
    protocol: StatusLedgerProtocol,
    event_root: str,
) -> StatusEventProjection:
    _validate_protocol(snapshot, protocol)
    registry = read_relation(
        snapshot, protocol.registry_root, budget=RELATION_BUDGET
    )
    if sum(
        member.participant_id == event_root
        and member.role_id == protocol.role("status-entry-member")
        for member in registry
    ) != 1:
        raise InvalidCell("status event is not registered exactly once")
    members = read_relation(snapshot, event_root, budget=RELATION_BUDGET)
    allowed = {
        protocol.role(name)
        for name in ROLE_NAMES
        if name not in ("vocabulary-member", "status-entry-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("status event contains an undeclared field")
    rule_roots = _for_role(members, protocol.role("status-rule"))
    if not rule_roots or len(rule_roots) > MAX_RULES or len(rule_roots) != len(set(rule_roots)):
        raise InvalidCell("status event rules are outside bounds")
    subject_digest_root = _one(
        members, protocol.role("status-subject-digest"), "subject digest"
    )
    source_revision_root = _one(
        members, protocol.role("status-source-revision"), "source revision"
    )
    reason_root = _one(members, protocol.role("status-reason"), "reason")
    created_revision_root = _one(
        members, protocol.role("status-created-revision"), "created revision"
    )
    digest_root = _one(members, protocol.role("status-digest"), "digest")
    event = StatusEventProjection(
        event_root,
        _one(members, protocol.role("status-subject"), "subject"),
        subject_digest_root,
        _text(snapshot, subject_digest_root, "status subject digest"),
        _one(members, protocol.role("status-state"), "state"),
        _one(members, protocol.role("status-actor"), "actor"),
        source_revision_root,
        _integer(snapshot, source_revision_root, "status source revision"),
        _one(members, protocol.role("status-policy"), "policy"),
        _one(members, protocol.role("status-action"), "action"),
        rule_roots,
        reason_root,
        _text(snapshot, reason_root, "status reason"),
        _one(
            members,
            protocol.role("status-authorization-receipt"),
            "authorization receipt",
        ),
        created_revision_root,
        _integer(snapshot, created_revision_root, "status created revision"),
        digest_root,
        _text(snapshot, digest_root, "status digest"),
    )
    if event.state_root not in protocol.states.values():
        raise InvalidCell("status event state is outside the vocabulary")
    if (
        event.source_revision + 1 != event.created_revision
        or event.created_revision > snapshot.revision
    ):
        raise InvalidCell("status event revision evidence drifted")
    for root in (
        event.subject_root,
        event.actor_root,
        event.policy_root,
        event.action_root,
        *event.rule_roots,
        event.authorization_receipt_root,
    ):
        if root not in snapshot.cells:
            raise InvalidCell("status event references a missing root")
    actual = _event_digest(snapshot, event)
    if not hmac.compare_digest(event.digest, actual):
        raise InvalidCell("status event has drifted")
    return event


def status_events_for_subject(
    snapshot: Snapshot,
    protocol: StatusLedgerProtocol,
    subject_root: str,
) -> tuple[StatusEventProjection, ...]:
    _validate_protocol(snapshot, protocol)
    registry = read_relation(
        snapshot, protocol.registry_root, budget=RELATION_BUDGET
    )
    events = tuple(
        event
        for event in (
            read_status_event(snapshot, protocol, member.participant_id)
            for member in registry
        )
        if event.subject_root == subject_root
    )
    revisions = tuple(event.created_revision for event in events)
    if len(revisions) != len(set(revisions)):
        raise InvalidCell("status history branches at one revision")
    revoked = tuple(
        event for event in events if event.state_root == protocol.state("revoked")
    )
    if len(revoked) > 1:
        raise InvalidCell("status history repeats irreversible revocation")
    if revoked and any(
        event.created_revision > revoked[0].created_revision for event in events
    ):
        raise InvalidCell("status history continues after irreversible revocation")
    return tuple(sorted(events, key=lambda item: item.created_revision))


def current_status(
    snapshot: Snapshot,
    protocol: StatusLedgerProtocol,
    subject_root: str,
) -> StatusEventProjection | None:
    events = status_events_for_subject(snapshot, protocol, subject_root)
    return events[-1] if events else None


def assert_subject_usable(
    snapshot: Snapshot,
    protocol: StatusLedgerProtocol,
    subject_root: str,
    subject_digest: str,
) -> None:
    event = current_status(snapshot, protocol, subject_root)
    if event is None:
        return
    if not hmac.compare_digest(event.subject_digest, subject_digest):
        raise InvalidCell("status subject digest does not match current authority")
    if event.state_root == protocol.state("revoked"):
        raise InvalidCell("authority is revoked")
    if event.state_root == protocol.state("suspended"):
        raise InvalidCell("authority is suspended")


def prepare_status_event(
    snapshot: Snapshot,
    protocol: StatusLedgerProtocol,
    *,
    event_id: str,
    subject_root: str,
    subject_digest: str,
    state_root: str,
    actor_root: str,
    policy_root: str,
    action_root: str,
    rule_roots: Iterable[str],
    reason: str,
    authorization_receipt_root: str,
    pending_evidence_cells: Iterable[Cell] = (),
) -> PreparedStatusEvent:
    _validate_protocol(snapshot, protocol)
    if event_id in snapshot.cells:
        raise InvalidCell("status event identity already exists")
    if state_root not in protocol.states.values():
        raise InvalidCell("status event state is outside the vocabulary")
    rules = tuple(dict.fromkeys(rule_roots))
    if not rules or len(rules) > MAX_RULES:
        raise InvalidCell("status event requires bounded determining rules")
    if not subject_digest or len(subject_digest.encode("utf-8")) > 128:
        raise InvalidCell("status subject digest is outside bounds")
    existing = status_events_for_subject(snapshot, protocol, subject_root)
    if any(event.state_root == protocol.state("revoked") for event in existing):
        raise InvalidCell("authority is already revoked")
    pending = tuple(pending_evidence_cells)
    pending_ids = tuple(cell.id for cell in pending)
    if len(pending_ids) != len(set(pending_ids)) or any(
        root in snapshot.cells for root in pending_ids
    ):
        raise InvalidCell("pending status evidence conflicts with committed graph")
    overlay = Snapshot(
        snapshot.revision,
        MappingProxyType({
            **snapshot.cells,
            **{cell.id: cell for cell in pending},
        }),
    )
    required = (
        subject_root,
        actor_root,
        policy_root,
        action_root,
        *rules,
        authorization_receipt_root,
    )
    if any(root not in overlay.cells for root in required):
        raise InvalidCell("status event evidence is missing")
    source_revision = snapshot.revision
    created_revision = source_revision + 1
    roots = {
        "subject-digest": event_id + ":subject-digest",
        "source-revision": event_id + ":source-revision",
        "reason": event_id + ":reason",
        "created-revision": event_id + ":created-revision",
        "digest": event_id + ":digest",
    }
    draft = StatusEventProjection(
        event_id,
        subject_root,
        roots["subject-digest"],
        subject_digest,
        state_root,
        actor_root,
        roots["source-revision"],
        source_revision,
        policy_root,
        action_root,
        rules,
        roots["reason"],
        reason,
        authorization_receipt_root,
        roots["created-revision"],
        created_revision,
        roots["digest"],
        "",
    )
    digest = _event_digest(overlay, draft)
    terminals = (
        _terminal(roots["subject-digest"], subject_digest),
        _terminal(roots["source-revision"], source_revision),
        _terminal(roots["reason"], reason),
        _terminal(roots["created-revision"], created_revision),
        _terminal(roots["digest"], digest),
    )
    relation = compose_relation_cells(
        (
            (protocol.role("status-subject"), subject_root),
            (protocol.role("status-subject-digest"), roots["subject-digest"]),
            (protocol.role("status-state"), state_root),
            (protocol.role("status-actor"), actor_root),
            (protocol.role("status-source-revision"), roots["source-revision"]),
            (protocol.role("status-policy"), policy_root),
            (protocol.role("status-action"), action_root),
            *((protocol.role("status-rule"), root) for root in rules),
            (protocol.role("status-reason"), roots["reason"]),
            (
                protocol.role("status-authorization-receipt"),
                authorization_receipt_root,
            ),
            (protocol.role("status-created-revision"), roots["created-revision"]),
            (protocol.role("status-digest"), roots["digest"]),
        ),
        relation_id=event_id,
    )
    registry = prepare_append_relation_members(
        snapshot,
        protocol.registry_root,
        ((protocol.role("status-entry-member"), event_id),),
        budget=RELATION_BUDGET,
    )
    return PreparedStatusEvent(
        event_id,
        (*terminals, *relation.cells, *registry.create),
        registry.replace,
    )
