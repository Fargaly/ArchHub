"""Graph-held device-targeted policy for a governed Work handoff.

The handoff never carries a task body, credential, or transport token.  The
primary graph holds only the approved source and target Device Custody roots,
the task digest, expiry, delivery state, and a bounded receipt digest.  The
governed Work state machine remains the authority for claim and completion.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
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
    "handoff-member",
    "receipt-member",
    "source-device-custody",
    "target-device-custody",
    "handoff-key",
    "payload-digest",
    "issued-at",
    "expires-at",
    "state",
    "receipt-handoff",
    "receipt-kind",
    "receipt-digest",
    "receipt-recorded-at",
)
STATE_NAMES = ("prepared", "delivered", "cancelled")
RECEIPT_KINDS = ("delivery", "cancellation")

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CUSTODY_PREFIX = "device-custody:sha256:"


@dataclass(frozen=True, slots=True)
class WorkHandoffProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    receipt_kinds: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown work-handoff role") from exc


@dataclass(frozen=True, slots=True)
class WorkHandoffProjection:
    root_id: str
    source_device_custody_root: str
    target_device_custody_root: str
    handoff_key: str
    payload_digest: str
    issued_at: float
    expires_at: float
    state_root: str
    state_incidence: str


@dataclass(frozen=True, slots=True)
class WorkHandoffReceiptProjection:
    root_id: str
    handoff_root: str
    kind_root: str
    digest: str
    recorded_at: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("work handoff %s is invalid" % label) from exc


def _one(members, role_root: str, label: str):
    values = [member for member in members if member.role_id == role_root]
    if len(values) != 1:
        raise InvalidCell("work handoff requires exactly one %s" % label)
    return values[0]


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise InvalidCell("work handoff %s must be a SHA-256 digest" % label)
    return value


def _custody(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(_CUSTODY_PREFIX)
        or len(value) > 256
    ):
        raise InvalidCell("work handoff %s is invalid" % label)
    return value


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("work handoff %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("work handoff %s is invalid" % label)
    return value


def bootstrap_work_handoff_protocol(
    store: CellStore,
    *,
    prefix: str = "work-handoff-protocol",
) -> WorkHandoffProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_work_handoff_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    receipt_kinds = {
        name: "%s:receipt-kind:%s" % (prefix, name)
        for name in RECEIPT_KINDS
    }
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items(), *receipt_kinds.items()):
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values(), *receipt_kinds.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return WorkHandoffProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(receipt_kinds),
    )


def project_work_handoff_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "work-handoff-protocol",
) -> WorkHandoffProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    receipt_kinds = {
        name: "%s:receipt-kind:%s" % (prefix, name)
        for name in RECEIPT_KINDS
    }
    if {root_id, *roles.values(), *states.values(), *receipt_kinds.values()} - set(snapshot.cells):
        raise InvalidCell("work-handoff protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {
        roles["vocabulary-member"],
        roles["handoff-member"],
        roles["receipt-member"],
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work-handoff protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    expected = {*roles.values(), *states.values(), *receipt_kinds.values()}
    if vocabulary != expected:
        raise InvalidCell("work-handoff protocol vocabulary drifted")
    return WorkHandoffProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(receipt_kinds),
    )


def _handoff_root(handoff_key: str) -> str:
    return "work-handoff:sha256:" + handoff_key


def _receipt_root(handoff_key: str, kind: str) -> str:
    return "work-handoff-receipt:sha256:%s:%s" % (handoff_key, kind)


def read_work_handoff(
    snapshot: Snapshot,
    protocol: WorkHandoffProtocol,
    handoff_root: str,
) -> WorkHandoffProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("handoff-member")
    }
    if handoff_root not in registered:
        raise InvalidCell("work handoff is not registered")
    members = read_relation(snapshot, handoff_root, budget=128)
    allowed = {
        protocol.role(name)
        for name in (
            "source-device-custody", "target-device-custody", "handoff-key",
            "payload-digest", "issued-at", "expires-at", "state",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work handoff contains an undeclared field")
    source = _custody(
        _one(members, protocol.role("source-device-custody"), "source custody").participant_id,
        "source custody",
    )
    target = _custody(
        _one(members, protocol.role("target-device-custody"), "target custody").participant_id,
        "target custody",
    )
    key = _digest(
        _text(
            snapshot,
            _one(members, protocol.role("handoff-key"), "handoff key").participant_id,
            "handoff key",
        ),
        "key",
    )
    payload_digest = _digest(
        _text(
            snapshot,
            _one(members, protocol.role("payload-digest"), "payload digest").participant_id,
            "payload digest",
        ),
        "payload digest",
    )
    issued_at = _time(
        snapshot,
        _one(members, protocol.role("issued-at"), "issued at").participant_id,
        "issued at",
    )
    expires_at = _time(
        snapshot,
        _one(members, protocol.role("expires-at"), "expires at").participant_id,
        "expires at",
    )
    state = _one(members, protocol.role("state"), "state")
    if source == target or not issued_at < expires_at or expires_at - issued_at > 86_400:
        raise InvalidCell("work handoff lifecycle is invalid")
    if state.participant_id not in protocol.states.values():
        raise InvalidCell("work handoff state is invalid")
    if handoff_root != _handoff_root(key):
        raise InvalidCell("work handoff identity drifted")
    return WorkHandoffProjection(
        handoff_root,
        source,
        target,
        key,
        payload_digest,
        issued_at,
        expires_at,
        state.participant_id,
        state.incidence_id,
    )


def issue_work_handoff(
    store: CellStore,
    protocol: WorkHandoffProtocol,
    *,
    source_device_custody_root: str,
    target_device_custody_root: str,
    handoff_key: str,
    payload_digest: str,
    issued_at: float,
    expires_at: float,
) -> tuple[WorkHandoffProjection, int]:
    source = _custody(source_device_custody_root, "source custody")
    target = _custody(target_device_custody_root, "target custody")
    key = _digest(handoff_key, "key")
    digest = _digest(payload_digest, "payload digest")
    try:
        issued = float(issued_at)
        expires = float(expires_at)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("work handoff timestamps are invalid") from exc
    if (
        source == target
        or not math.isfinite(issued)
        or not math.isfinite(expires)
        or not issued < expires
        or expires - issued > 86_400
    ):
        raise InvalidCell("work handoff lifecycle is invalid")
    root_id = _handoff_root(key)
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
        existing = read_work_handoff(snapshot, protocol, root_id)
        if (
            existing.source_device_custody_root != source
            or existing.target_device_custody_root != target
            or existing.payload_digest != digest
            or existing.issued_at != issued
            or existing.expires_at != expires
        ):
            raise InvalidCell("work handoff key was reused")
        return existing, snapshot.revision
    if source not in snapshot.cells or target not in snapshot.cells:
        raise InvalidCell("work handoff device custody is missing")
    values = {
        "handoff-key": key,
        "payload-digest": digest,
        "issued-at": "%.6f" % issued,
        "expires-at": "%.6f" % expires,
    }
    relation = compose_relation_cells(
        (
            (protocol.role("source-device-custody"), source),
            (protocol.role("target-device-custody"), target),
            *((protocol.role(name), root_id + ":" + name) for name in values),
            (protocol.role("state"), protocol.states["prepared"]),
        ),
        relation_id=root_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("handoff-member"),
        root_id,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            *(_terminal(root_id + ":" + name, value)
              for name, value in values.items()),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_work_handoff(store.snapshot(), protocol, root_id), revision


def read_work_handoff_receipt(
    snapshot: Snapshot,
    protocol: WorkHandoffProtocol,
    receipt_root: str,
) -> WorkHandoffReceiptProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("receipt-member")
    }
    if receipt_root not in registered:
        raise InvalidCell("work handoff receipt is not registered")
    members = read_relation(snapshot, receipt_root, budget=96)
    allowed = {
        protocol.role("receipt-handoff"),
        protocol.role("receipt-kind"),
        protocol.role("receipt-digest"),
        protocol.role("receipt-recorded-at"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work handoff receipt contains an undeclared field")
    handoff_root = _one(members, protocol.role("receipt-handoff"), "receipt handoff").participant_id
    read_work_handoff(snapshot, protocol, handoff_root)
    kind_root = _one(members, protocol.role("receipt-kind"), "receipt kind").participant_id
    if kind_root not in protocol.receipt_kinds.values():
        raise InvalidCell("work handoff receipt kind is invalid")
    digest = _digest(
        _text(
            snapshot,
            _one(members, protocol.role("receipt-digest"), "receipt digest").participant_id,
            "receipt digest",
        ),
        "receipt digest",
    )
    recorded_at = _time(
        snapshot,
        _one(members, protocol.role("receipt-recorded-at"), "receipt time").participant_id,
        "receipt time",
    )
    return WorkHandoffReceiptProjection(
        receipt_root, handoff_root, kind_root, digest, recorded_at
    )


def record_work_handoff_receipt(
    store: CellStore,
    protocol: WorkHandoffProtocol,
    *,
    handoff_root: str,
    kind: str,
    receipt_digest: str,
    recorded_at: float | None = None,
) -> tuple[WorkHandoffProjection, WorkHandoffReceiptProjection, int]:
    if kind not in protocol.receipt_kinds:
        raise InvalidCell("work handoff receipt kind is invalid")
    digest = _digest(receipt_digest, "receipt digest")
    now = time.time() if recorded_at is None else float(recorded_at)
    if not math.isfinite(now):
        raise InvalidCell("work handoff receipt time is invalid")
    snapshot = store.snapshot()
    handoff = read_work_handoff(snapshot, protocol, handoff_root)
    if now >= handoff.expires_at and kind == "delivery":
        raise InvalidCell("work handoff delivery expired")
    desired_state = (
        protocol.states["delivered"]
        if kind == "delivery"
        else protocol.states["cancelled"]
    )
    if handoff.state_root not in {protocol.states["prepared"], desired_state}:
        raise InvalidCell("work handoff receipt would roll back its state")
    receipt_root = _receipt_root(handoff.handoff_key, kind)
    if receipt_root in snapshot.cells:
        receipt = read_work_handoff_receipt(snapshot, protocol, receipt_root)
        if (
            receipt.handoff_root != handoff_root
            or receipt.kind_root != protocol.receipt_kinds[kind]
            or receipt.digest != digest
        ):
            raise InvalidCell("work handoff receipt conflicts with existing evidence")
        if handoff.state_root != desired_state:
            raise InvalidCell("work handoff receipt conflicts with handoff state")
        return handoff, receipt, snapshot.revision
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-handoff"), handoff_root),
            (protocol.role("receipt-kind"), protocol.receipt_kinds[kind]),
            (protocol.role("receipt-digest"), receipt_root + ":digest"),
            (protocol.role("receipt-recorded-at"), receipt_root + ":recorded-at"),
        ),
        relation_id=receipt_root,
    )
    receipt_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("receipt-member"),
        receipt_root,
        budget=100_000,
    )
    state_incidence = snapshot.cells[handoff.state_incidence]
    replacements = list(receipt_patch.replace)
    if handoff.state_root != desired_state:
        replacements.append(Cell(
            state_incidence.id,
            state_incidence.link0,
            desired_state,
            state_incidence.atom,
        ))
    revision = store.commit(
        snapshot.revision,
        create=(
            _terminal(receipt_root + ":digest", digest),
            _terminal(receipt_root + ":recorded-at", "%.6f" % now),
            *relation.cells,
            *receipt_patch.create,
        ),
        replace=tuple(replacements),
    )
    current = store.snapshot()
    return (
        read_work_handoff(current, protocol, handoff_root),
        read_work_handoff_receipt(current, protocol, receipt_root),
        revision,
    )


def handoff_claim_is_permitted(
    snapshot: Snapshot,
    protocol: WorkHandoffProtocol,
    handoff_root: str,
    *,
    device_custody_root: str,
    now: float,
) -> bool:
    handoff = read_work_handoff(snapshot, protocol, handoff_root)
    current = float(now)
    if not math.isfinite(current):
        raise InvalidCell("work handoff claim time is invalid")
    return (
        handoff.state_root == protocol.states["delivered"]
        and current < handoff.expires_at
        and handoff.target_device_custody_root == _custody(
            device_custody_root, "claim custody"
        )
    )


__all__ = [
    "WorkHandoffProjection",
    "WorkHandoffProtocol",
    "WorkHandoffReceiptProjection",
    "bootstrap_work_handoff_protocol",
    "handoff_claim_is_permitted",
    "issue_work_handoff",
    "project_work_handoff_protocol",
    "read_work_handoff",
    "read_work_handoff_receipt",
    "record_work_handoff_receipt",
]
