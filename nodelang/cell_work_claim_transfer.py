"""Graph-held custody transfer for one already-claimed governed Work.

This protocol never contains Work content, provider state, a task queue, or a
transport token. It binds the existing Work and exact source/target custody to
an expiring, receipt-backed claim reservation in the primary Universal graph.
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
    "transfer-member",
    "receipt-member",
    "work",
    "source-agent-session",
    "source-device-custody",
    "target-device-custody",
    "transfer-key",
    "work-digest",
    "confirmation-digest",
    "issued-at",
    "expires-at",
    "state",
    "receipt-transfer",
    "receipt-kind",
    "receipt-digest",
    "receipt-recorded-at",
)
STATE_NAMES = ("prepared", "released", "claimed", "cancelled")
RECEIPT_KINDS = ("release", "claim", "cancellation")

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CUSTODY_PREFIX = "device-custody:sha256:"


@dataclass(frozen=True, slots=True)
class WorkClaimTransferProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    receipt_kinds: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown work claim-transfer role") from exc


@dataclass(frozen=True, slots=True)
class WorkClaimTransferProjection:
    root_id: str
    work_root: str
    source_agent_session_root: str
    source_device_custody_root: str
    target_device_custody_root: str
    transfer_key: str
    work_digest: str
    confirmation_digest: str
    issued_at: float
    expires_at: float
    state_root: str
    state_incidence: str


@dataclass(frozen=True, slots=True)
class WorkClaimTransferReceiptProjection:
    root_id: str
    transfer_root: str
    kind_root: str
    digest: str
    recorded_at: float


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("work claim transfer %s is invalid" % label) from exc


def _one(members, role_root: str, label: str):
    values = [member for member in members if member.role_id == role_root]
    if len(values) != 1:
        raise InvalidCell("work claim transfer requires exactly one %s" % label)
    return values[0]


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise InvalidCell("work claim transfer %s must be a SHA-256 digest" % label)
    return value


def _custody(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(_CUSTODY_PREFIX)
        or len(value) > 256
    ):
        raise InvalidCell("work claim transfer %s is invalid" % label)
    return value


def _root(value: object, label: str) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise InvalidCell("work claim transfer %s is invalid" % label)
    return value


def _time(snapshot: Snapshot, root_id: str, label: str) -> float:
    try:
        value = float(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("work claim transfer %s is invalid" % label) from exc
    if not math.isfinite(value):
        raise InvalidCell("work claim transfer %s is invalid" % label)
    return value


def bootstrap_work_claim_transfer_protocol(
    store: CellStore,
    *,
    prefix: str = "work-claim-transfer-protocol",
) -> WorkClaimTransferProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_work_claim_transfer_protocol(store.snapshot(), prefix=prefix)
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
    return WorkClaimTransferProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(receipt_kinds),
    )


def project_work_claim_transfer_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "work-claim-transfer-protocol",
) -> WorkClaimTransferProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    receipt_kinds = {
        name: "%s:receipt-kind:%s" % (prefix, name)
        for name in RECEIPT_KINDS
    }
    required = {root_id, *roles.values(), *states.values(), *receipt_kinds.values()}
    if required - set(snapshot.cells):
        raise InvalidCell("work claim-transfer protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {
        roles["vocabulary-member"],
        roles["transfer-member"],
        roles["receipt-member"],
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work claim-transfer protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    expected = {*roles.values(), *states.values(), *receipt_kinds.values()}
    if vocabulary != expected:
        raise InvalidCell("work claim-transfer protocol vocabulary drifted")
    return WorkClaimTransferProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(receipt_kinds),
    )


def _transfer_root(transfer_key: str) -> str:
    return "work-claim-transfer:sha256:" + transfer_key


def _receipt_root(transfer_key: str, kind: str) -> str:
    return "work-claim-transfer-receipt:sha256:%s:%s" % (transfer_key, kind)


def work_claim_transfer_receipt_root(transfer_key: str, kind: str) -> str:
    """Return the deterministic graph identity for one transfer receipt."""
    key = _digest(transfer_key, "key")
    if kind not in RECEIPT_KINDS:
        raise InvalidCell("work claim transfer receipt kind is invalid")
    return _receipt_root(key, kind)


def read_work_claim_transfer(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    transfer_root: str,
) -> WorkClaimTransferProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("transfer-member")
    }
    if transfer_root not in registered:
        raise InvalidCell("work claim transfer is not registered")
    members = read_relation(snapshot, transfer_root, budget=160)
    allowed = {
        protocol.role(name)
        for name in (
            "work", "source-agent-session", "source-device-custody",
            "target-device-custody", "transfer-key", "work-digest",
            "confirmation-digest", "issued-at", "expires-at", "state",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work claim transfer contains an undeclared field")
    work_root = _root(
        _one(members, protocol.role("work"), "work").participant_id,
        "work",
    )
    source_session = _root(
        _one(
            members, protocol.role("source-agent-session"), "source session"
        ).participant_id,
        "source session",
    )
    source_custody = _custody(
        _one(
            members, protocol.role("source-device-custody"), "source custody"
        ).participant_id,
        "source custody",
    )
    target_custody = _custody(
        _one(
            members, protocol.role("target-device-custody"), "target custody"
        ).participant_id,
        "target custody",
    )
    key = _digest(
        _text(
            snapshot,
            _one(members, protocol.role("transfer-key"), "transfer key").participant_id,
            "transfer key",
        ),
        "key",
    )
    work_digest = _digest(
        _text(
            snapshot,
            _one(members, protocol.role("work-digest"), "work digest").participant_id,
            "work digest",
        ),
        "work digest",
    )
    confirmation_digest = _digest(
        _text(
            snapshot,
            _one(
                members, protocol.role("confirmation-digest"), "confirmation digest"
            ).participant_id,
            "confirmation digest",
        ),
        "confirmation digest",
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
    if (
        source_custody == target_custody
        or work_root not in snapshot.cells
        or source_session not in snapshot.cells
        or source_custody not in snapshot.cells
        or target_custody not in snapshot.cells
        or not issued_at < expires_at
        or expires_at - issued_at > 86_400
    ):
        raise InvalidCell("work claim transfer lifecycle is invalid")
    if state.participant_id not in protocol.states.values():
        raise InvalidCell("work claim transfer state is invalid")
    if transfer_root != _transfer_root(key):
        raise InvalidCell("work claim transfer identity drifted")
    return WorkClaimTransferProjection(
        transfer_root,
        work_root,
        source_session,
        source_custody,
        target_custody,
        key,
        work_digest,
        confirmation_digest,
        issued_at,
        expires_at,
        state.participant_id,
        state.incidence_id,
    )


def prepare_work_claim_transfer_issue(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    *,
    work_root: str,
    source_agent_session_root: str,
    source_device_custody_root: str,
    target_device_custody_root: str,
    transfer_key: str,
    work_digest: str,
    confirmation_digest: str,
    issued_at: float,
    expires_at: float,
) -> tuple[str, tuple[Cell, ...], tuple[Cell, ...]]:
    """Prepare one exact transfer without creating an unattached graph fact."""
    work = _root(work_root, "work")
    source_session = _root(source_agent_session_root, "source session")
    source_custody = _custody(source_device_custody_root, "source custody")
    target_custody = _custody(target_device_custody_root, "target custody")
    key = _digest(transfer_key, "key")
    digest = _digest(work_digest, "work digest")
    confirmation = _digest(confirmation_digest, "confirmation digest")
    try:
        issued = float(issued_at)
        expires = float(expires_at)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("work claim transfer timestamps are invalid") from exc
    if (
        source_custody == target_custody
        or not math.isfinite(issued)
        or not math.isfinite(expires)
        or not issued < expires
        or expires - issued > 86_400
    ):
        raise InvalidCell("work claim transfer lifecycle is invalid")
    root_id = _transfer_root(key)
    if root_id in snapshot.cells:
        existing = read_work_claim_transfer(snapshot, protocol, root_id)
        if (
            existing.work_root != work
            or existing.source_agent_session_root != source_session
            or existing.source_device_custody_root != source_custody
            or existing.target_device_custody_root != target_custody
            or existing.work_digest != digest
            or existing.confirmation_digest != confirmation
            or existing.issued_at != issued
            or existing.expires_at != expires
        ):
            raise InvalidCell("work claim transfer key was reused")
        return root_id, (), ()
    if {
        work, source_session, source_custody, target_custody,
    } - set(snapshot.cells):
        raise InvalidCell("work claim transfer participant is missing")
    values = {
        "transfer-key": key,
        "work-digest": digest,
        "confirmation-digest": confirmation,
        "issued-at": "%.6f" % issued,
        "expires-at": "%.6f" % expires,
    }
    relation = compose_relation_cells(
        (
            (protocol.role("work"), work),
            (protocol.role("source-agent-session"), source_session),
            (protocol.role("source-device-custody"), source_custody),
            (protocol.role("target-device-custody"), target_custody),
            *((protocol.role(name), root_id + ":" + name) for name in values),
            (protocol.role("state"), protocol.states["prepared"]),
        ),
        relation_id=root_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("transfer-member"),
        root_id,
        budget=100_000,
    )
    create = (
        tuple(
            _terminal(root_id + ":" + name, value)
            for name, value in values.items()
        )
        + tuple(relation.cells)
        + tuple(patch.create)
    )
    return root_id, create, tuple(patch.replace)


def issue_work_claim_transfer(
    store: CellStore,
    protocol: WorkClaimTransferProtocol,
    *,
    work_root: str,
    source_agent_session_root: str,
    source_device_custody_root: str,
    target_device_custody_root: str,
    transfer_key: str,
    work_digest: str,
    confirmation_digest: str,
    issued_at: float,
    expires_at: float,
) -> tuple[WorkClaimTransferProjection, int]:
    """Commit one standalone transfer for callers without a Work mutation."""
    snapshot = store.snapshot()
    root_id, create, replace = prepare_work_claim_transfer_issue(
        snapshot,
        protocol,
        work_root=work_root,
        source_agent_session_root=source_agent_session_root,
        source_device_custody_root=source_device_custody_root,
        target_device_custody_root=target_device_custody_root,
        transfer_key=transfer_key,
        work_digest=work_digest,
        confirmation_digest=confirmation_digest,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    if not create and not replace:
        return read_work_claim_transfer(snapshot, protocol, root_id), snapshot.revision
    revision = store.commit(snapshot.revision, create=create, replace=replace)
    return read_work_claim_transfer(store.snapshot(), protocol, root_id), revision


def read_work_claim_transfer_receipt(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    receipt_root: str,
) -> WorkClaimTransferReceiptProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("receipt-member")
    }
    if receipt_root not in registered:
        raise InvalidCell("work claim transfer receipt is not registered")
    members = read_relation(snapshot, receipt_root, budget=96)
    allowed = {
        protocol.role("receipt-transfer"),
        protocol.role("receipt-kind"),
        protocol.role("receipt-digest"),
        protocol.role("receipt-recorded-at"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("work claim transfer receipt contains an undeclared field")
    transfer_root = _one(
        members, protocol.role("receipt-transfer"), "receipt transfer"
    ).participant_id
    read_work_claim_transfer(snapshot, protocol, transfer_root)
    kind_root = _one(
        members, protocol.role("receipt-kind"), "receipt kind"
    ).participant_id
    if kind_root not in protocol.receipt_kinds.values():
        raise InvalidCell("work claim transfer receipt kind is invalid")
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
        _one(
            members, protocol.role("receipt-recorded-at"), "receipt time"
        ).participant_id,
        "receipt time",
    )
    return WorkClaimTransferReceiptProjection(
        receipt_root, transfer_root, kind_root, digest, recorded_at
    )


def prepare_work_claim_transfer_receipt(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    *,
    transfer_root: str,
    kind: str,
    receipt_digest: str,
    recorded_at: float | None = None,
) -> tuple[tuple[Cell, ...], tuple[Cell, ...]]:
    if kind not in protocol.receipt_kinds:
        raise InvalidCell("work claim transfer receipt kind is invalid")
    digest = _digest(receipt_digest, "receipt digest")
    now = time.time() if recorded_at is None else float(recorded_at)
    if not math.isfinite(now):
        raise InvalidCell("work claim transfer receipt time is invalid")
    transfer = read_work_claim_transfer(snapshot, protocol, transfer_root)
    expected, desired = {
        "release": ("prepared", "released"),
        "claim": ("released", "claimed"),
        "cancellation": (("prepared", "released"), "cancelled"),
    }[kind]
    expected_states = (
        (protocol.states[expected],)
        if isinstance(expected, str)
        else tuple(protocol.states[state] for state in expected)
    )
    desired_state = protocol.states[desired]
    if kind in {"release", "claim"} and now >= transfer.expires_at:
        raise InvalidCell("work claim transfer receipt expired")
    receipt_root = work_claim_transfer_receipt_root(transfer.transfer_key, kind)
    if receipt_root in snapshot.cells:
        receipt = read_work_claim_transfer_receipt(snapshot, protocol, receipt_root)
        if (
            receipt.transfer_root != transfer_root
            or receipt.kind_root != protocol.receipt_kinds[kind]
            or receipt.digest != digest
            or transfer.state_root != desired_state
        ):
            raise InvalidCell("work claim transfer receipt conflicts with evidence")
        return (), ()
    if transfer.state_root not in expected_states:
        raise InvalidCell("work claim transfer receipt would roll back state")
    values = {
        "receipt-digest": digest,
        "receipt-recorded-at": "%.6f" % now,
    }
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-transfer"), transfer_root),
            (protocol.role("receipt-kind"), protocol.receipt_kinds[kind]),
            *((protocol.role(name), receipt_root + ":" + name)
              for name in values),
        ),
        relation_id=receipt_root,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("receipt-member"),
        receipt_root,
        budget=100_000,
    )
    state_incidence = snapshot.cells.get(transfer.state_incidence)
    if state_incidence is None:
        raise InvalidCell("work claim transfer state incidence is missing")
    replacement = Cell(
        state_incidence.id,
        state_incidence.link0,
        desired_state,
        state_incidence.atom,
    )
    replacements = {replacement.id: replacement}
    replacements.update({cell.id: cell for cell in patch.replace})
    return (
        (
            *(_terminal(receipt_root + ":" + name, value)
              for name, value in values.items()),
            *relation.cells,
            *patch.create,
        ),
        tuple(replacements.values()),
    )


def record_work_claim_transfer_receipt(
    store: CellStore,
    protocol: WorkClaimTransferProtocol,
    *,
    transfer_root: str,
    kind: str,
    receipt_digest: str,
    recorded_at: float | None = None,
) -> tuple[WorkClaimTransferProjection, WorkClaimTransferReceiptProjection, int]:
    snapshot = store.snapshot()
    create, replace = prepare_work_claim_transfer_receipt(
        snapshot,
        protocol,
        transfer_root=transfer_root,
        kind=kind,
        receipt_digest=receipt_digest,
        recorded_at=recorded_at,
    )
    if not create and not replace:
        transfer = read_work_claim_transfer(snapshot, protocol, transfer_root)
        return (
            transfer,
            read_work_claim_transfer_receipt(
                snapshot, protocol,
                work_claim_transfer_receipt_root(transfer.transfer_key, kind)
            ),
            snapshot.revision,
        )
    revision = store.commit(snapshot.revision, create=create, replace=replace)
    current = store.snapshot()
    transfer = read_work_claim_transfer(current, protocol, transfer_root)
    return (
        transfer,
        read_work_claim_transfer_receipt(
            current, protocol,
            work_claim_transfer_receipt_root(transfer.transfer_key, kind)
        ),
        revision,
    )


def claim_transfer_is_permitted(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    transfer_root: str,
    *,
    device_custody_root: str,
    now: float,
) -> bool:
    transfer = read_work_claim_transfer(snapshot, protocol, transfer_root)
    current = float(now)
    if not math.isfinite(current):
        raise InvalidCell("work claim transfer claim time is invalid")
    return (
        transfer.state_root == protocol.states["released"]
        and current < transfer.expires_at
        and transfer.target_device_custody_root == _custody(
            device_custody_root, "claim custody"
        )
    )


def transfer_release_is_permitted(
    snapshot: Snapshot,
    protocol: WorkClaimTransferProtocol,
    transfer_root: str,
    *,
    agent_session_root: str,
    device_custody_root: str,
    now: float,
) -> bool:
    transfer = read_work_claim_transfer(snapshot, protocol, transfer_root)
    current = float(now)
    if not math.isfinite(current):
        raise InvalidCell("work claim transfer release time is invalid")
    return (
        transfer.state_root == protocol.states["prepared"]
        and current < transfer.expires_at
        and transfer.source_agent_session_root == _root(
            agent_session_root, "release session"
        )
        and transfer.source_device_custody_root == _custody(
            device_custody_root, "release custody"
        )
    )


__all__ = [
    "WorkClaimTransferProjection",
    "WorkClaimTransferProtocol",
    "WorkClaimTransferReceiptProjection",
    "bootstrap_work_claim_transfer_protocol",
    "claim_transfer_is_permitted",
    "issue_work_claim_transfer",
    "prepare_work_claim_transfer_issue",
    "prepare_work_claim_transfer_receipt",
    "project_work_claim_transfer_protocol",
    "read_work_claim_transfer",
    "read_work_claim_transfer_receipt",
    "record_work_claim_transfer_receipt",
    "transfer_release_is_permitted",
    "work_claim_transfer_receipt_root",
]
