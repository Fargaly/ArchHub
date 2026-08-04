"""Persistent governed attention, focus, obligations, decisions, and outcomes.

Every persisted item in this module is an ordinary universal Cell composition.
The module adds no Cell kind and no product operation to the physical kernel.
Ordering is an inspectable released sequence of priority-class roots; there is no
hidden score. Host projections in this module remain subject to the
no-hidden-interpreter equivalence court defined by SPEC.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_authorization import AuthorizationDecision
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "policy-member",
    "policy-class-order",
    "policy-status",
    "policy-digest",
    "policy-reviewer",
    "policy-evidence",
    "priority-member",
    "signal-member",
    "signal-source",
    "signal-source-revision",
    "signal-observer",
    "signal-provenance",
    "signal-subscription",
    "signal-trust",
    "signal-affected",
    "signal-observed-at",
    "signal-sensitivity",
    "signal-audience",
    "signal-idempotency",
    "signal-lifecycle",
    "subscription-member",
    "subscription-reaction",
    "subscription-observer",
    "subscription-provenance",
    "subscription-trust",
    "subscription-sensitivity",
    "subscription-audience",
    "subscription-lifecycle",
    "subscription-action",
    "subscription-authority",
    "subscription-rule",
    "subscription-cursor",
    "subscription-state",
    "obligation-member",
    "obligation-subject",
    "obligation-owner",
    "obligation-reviewer",
    "obligation-policy",
    "obligation-priority",
    "obligation-dependency",
    "obligation-court",
    "obligation-required-evidence",
    "obligation-state",
    "obligation-created-at",
    "obligation-due-at",
    "obligation-resolution-evidence",
    "eligibility-member",
    "eligibility-observer",
    "eligibility-candidate",
    "eligibility-action",
    "eligibility-scope",
    "eligibility-snapshot",
    "eligibility-state",
    "eligibility-reason",
    "eligibility-authority",
    "eligibility-rule",
    "eligibility-audience",
    "attention-member",
    "attention-observer",
    "attention-candidate",
    "attention-scope",
    "attention-snapshot",
    "attention-reason",
    "attention-policy",
    "attention-priority",
    "attention-eligibility",
    "attention-obligation",
    "attention-state",
    "attention-created-sequence",
    "attention-history",
    "focus-member",
    "focus-actor",
    "focus-session",
    "focus-scope",
    "focus-selected",
    "focus-primary",
    "focus-origin",
    "focus-reason",
    "focus-attention",
    "focus-state",
    "focus-previous",
    "focus-authority",
    "focus-consent-evidence",
    "focus-created-at",
    "decision-member",
    "decision-subject",
    "decision-action",
    "decision-actor",
    "decision-authority",
    "decision-evidence",
    "decision-state",
    "decision-created-at",
    "outcome-member",
    "outcome-decision",
    "outcome-provider",
    "outcome-state",
    "outcome-receipt",
    "outcome-reconciliation",
    "outcome-reason",
    "outcome-observed-at",
)

STATE_NAMES = (
    "wip",
    "released",
    "open",
    "blocked",
    "resolved",
    "allowed",
    "denied",
    "active",
    "invalidated",
    "suggested",
    "accepted",
    "rejected",
    "pending",
    "succeeded",
    "failed",
    "reconciled",
    "reversed",
)

ORIGIN_NAMES = ("user", "policy", "model")

REGISTRY_NAMES = (
    "policy",
    "signal",
    "subscription",
    "obligation",
    "eligibility",
    "attention",
    "focus",
    "decision",
    "outcome",
)


@dataclass(frozen=True, slots=True)
class AttentionProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    origins: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown attention role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown attention state %r" % name) from exc

    def origin(self, name: str) -> str:
        try:
            return self.origins[name]
        except KeyError as exc:
            raise InvalidCell("unknown focus origin %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown attention registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class PolicyProjection:
    root_id: str
    class_order_root: str
    class_roots: tuple[str, ...]
    status_root: str
    status_incidence: str
    digest_root: str
    reviewer_root: str | None
    evidence_root: str | None


@dataclass(frozen=True, slots=True)
class SignalProjection:
    root_id: str
    source_root: str
    source_revision: int
    observer_root: str
    provenance_root: str
    subscription_root: str | None
    trust_root: str
    affected_roots: tuple[str, ...]
    observed_at: str
    sensitivity_root: str
    audience_root: str
    idempotency_key: str
    lifecycle_root: str


@dataclass(frozen=True, slots=True)
class ObligationProjection:
    root_id: str
    subject_root: str
    owner_root: str
    reviewer_root: str
    policy_root: str
    priority_root: str
    state_root: str
    state_incidence: str
    dependency_roots: tuple[str, ...]
    court_roots: tuple[str, ...]
    required_evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedObligation:
    """One uncommitted, fully validated obligation graph patch."""

    root_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class EligibilityProjection:
    root_id: str
    observer_root: str
    candidate_root: str
    action_root: str
    scope_root: str
    snapshot_revision: int
    state_root: str
    reason_root: str
    authority_root: str
    audience_root: str


@dataclass(frozen=True, slots=True)
class AttentionProjection:
    root_id: str
    observer_root: str
    candidate_root: str
    scope_root: str
    snapshot_revision: int
    reason_roots: tuple[str, ...]
    policy_root: str
    priority_root: str
    eligibility_root: str
    obligation_root: str | None
    state_root: str
    state_incidence: str
    sequence: int
    history_root: str
    priority_index: int | None = None


@dataclass(frozen=True, slots=True)
class FocusProjection:
    root_id: str
    actor_root: str
    session_root: str
    scope_root: str
    selected_roots: tuple[str, ...]
    primary_root: str
    origin_root: str
    state_root: str
    state_incidence: str
    previous_root: str | None
    reason_roots: tuple[str, ...]
    attention_roots: tuple[str, ...]
    authority_root: str
    created_at: str
    consent_evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedFocusTransition:
    """One atomic graph patch for an already-authorised focus gesture."""

    root_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class DecisionProjection:
    root_id: str
    subject_root: str
    action_root: str
    actor_root: str
    authority_root: str
    evidence_roots: tuple[str, ...]
    state_root: str


@dataclass(frozen=True, slots=True)
class OutcomeProjection:
    root_id: str
    decision_root: str
    provider_root: str
    state_root: str
    receipt_root: str | None
    reconciliation_root: str | None
    reason_root: str | None


def _terminal(root_id: str, value: str | bytes | int) -> Cell:
    if isinstance(value, str):
        atom = value.encode("utf-8")
    elif isinstance(value, int):
        atom = str(value).encode("ascii")
    else:
        atom = value
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _for_role(
    members: Iterable[RelationMember], role_root: str
) -> tuple[RelationMember, ...]:
    return tuple(member for member in members if member.role_id == role_root)


def _one(
    members: Iterable[RelationMember], role_root: str, label: str
) -> RelationMember:
    found = _for_role(members, role_root)
    if len(found) != 1:
        raise InvalidCell("composition requires exactly one %s" % label)
    return found[0]


def _optional(
    members: Iterable[RelationMember], role_root: str, label: str
) -> RelationMember | None:
    found = _for_role(members, role_root)
    if len(found) > 1:
        raise InvalidCell("composition repeats %s" % label)
    return found[0] if found else None


def _participants(
    members: Iterable[RelationMember], role_root: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id
        for member in members
        if member.role_id == role_root
    )


def _atom_text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("expected a UTF-8 terminal Cell at %r" % root_id) from exc


def _atom_int(snapshot: Snapshot, root_id: str) -> int:
    try:
        return int(snapshot.cells[root_id].atom.decode("ascii"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("expected an integer terminal Cell at %r" % root_id) from exc


def _ensure_roots(snapshot: Snapshot, roots: Iterable[str], label: str) -> None:
    missing = tuple(root for root in roots if root not in snapshot.cells)
    if missing:
        raise InvalidCell("%s references missing roots: %r" % (label, missing))


def bootstrap_attention_protocol(
    store: CellStore,
    *,
    prefix: str = "attention-protocol",
) -> AttentionProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    origins = {name: "%s:origin:%s" % (prefix, name) for name in ORIGIN_NAMES}
    registries = {
        name: "%s:registry:%s" % (prefix, name) for name in REGISTRY_NAMES
    }
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items(), *origins.items()):
        batch.add(_terminal(root, name))
    for root in registries.values():
        batch.relation((), relation_id=root)
    root_id = "%s:root" % prefix
    batch.relation(
        [
            *((roles["vocabulary-member"], root) for root in roles.values()),
            *((roles["vocabulary-member"], root) for root in states.values()),
            *((roles["vocabulary-member"], root) for root in origins.values()),
            *((roles["vocabulary-member"], root) for root in registries.values()),
        ],
        relation_id=root_id,
    )
    batch.commit()
    return AttentionProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(origins),
        MappingProxyType(registries),
    )


def install_attention_protocol(
    authority,
    *,
    caller,
    command_id: str,
    prefix: str = "attention-protocol",
) -> AttentionProtocol:
    """Install the attention protocol through the signed authority history."""
    from .unified_authority import (
        COMMAND_BUDGET,
        commit_with_receipt,
        digest,
        find_receipt,
        validate_command_participants,
    )

    request_digest = digest({
        "intent": "install-attention-protocol",
        "prefix": prefix,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="install-attention-protocol",
        request_digest=request_digest,
        object_root=authority.manifest.application_root,
        scope_root=authority.manifest.application_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return open_attention_protocol(authority.store.snapshot(), prefix=prefix)
    try:
        return open_attention_protocol(snapshot, prefix=prefix)
    except InvalidCell:
        pass
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    origins = {name: "%s:origin:%s" % (prefix, name) for name in ORIGIN_NAMES}
    registries = {
        name: "%s:registry:%s" % (prefix, name) for name in REGISTRY_NAMES
    }
    cells: list[Cell] = []
    for name, root in (*roles.items(), *states.items(), *origins.items()):
        cells.append(_terminal(root, name))
    for root in registries.values():
        cells.extend(compose_relation_cells((), relation_id=root).cells)
    protocol = AttentionProtocol(
        "%s:root" % prefix,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(origins),
        MappingProxyType(registries),
    )
    cells.extend(compose_relation_cells(
        [
            *((roles["vocabulary-member"], root) for root in roles.values()),
            *((roles["vocabulary-member"], root) for root in states.values()),
            *((roles["vocabulary-member"], root) for root in origins.values()),
            *((roles["vocabulary-member"], root) for root in registries.values()),
        ],
        relation_id=protocol.root_id,
    ).cells)
    commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(cells),
        resource_replace=(),
        authenticated=authenticated,
        result_root=protocol.root_id,
        policy_proof=policy_proof,
    )
    return open_attention_protocol(authority.store.snapshot(), prefix=prefix)


def open_attention_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "attention-protocol",
) -> AttentionProtocol:
    protocol = AttentionProtocol(
        "%s:root" % prefix,
        MappingProxyType({
            name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
        }),
        MappingProxyType({
            name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES
        }),
        MappingProxyType({
            name: "%s:origin:%s" % (prefix, name) for name in ORIGIN_NAMES
        }),
        MappingProxyType({
            name: "%s:registry:%s" % (prefix, name)
            for name in REGISTRY_NAMES
        }),
    )
    _ensure_roots(
        snapshot,
        (
            protocol.root_id,
            *protocol.roles.values(),
            *protocol.states.values(),
            *protocol.origins.values(),
            *protocol.registries.values(),
        ),
        "attention protocol",
    )
    return protocol


def _registry_roots(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    registry_name: str,
    member_role: str,
) -> tuple[str, ...]:
    return _participants(
        read_relation(snapshot, protocol.registry(registry_name), budget=100_000),
        protocol.role(member_role),
    )


def _register_relation(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    root_id: str,
    members: Iterable[tuple[str, str]],
    registry_name: str,
    registry_member_role: str,
    create: Iterable[Cell] = (),
    extra_relation_cells: Iterable[Cell] = (),
) -> int:
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
        raise InvalidCell("composition root already exists: %r" % root_id)
    relation = compose_relation_cells(members, relation_id=root_id)
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry(registry_name),
        protocol.role(registry_member_role),
        root_id,
        budget=100_000,
    )
    created = tuple(create) + tuple(extra_relation_cells) + relation.cells + append.create
    identities = [cell.id for cell in created]
    if len(identities) != len(set(identities)):
        raise InvalidCell("composition creates duplicate physical identities")
    return store.commit(
        snapshot.revision,
        create=created,
        replace=append.replace,
    )


def _policy_digest(
    snapshot: Snapshot,
    policy: PolicyProjection,
    *,
    reviewer_root: str | None = None,
    evidence_root: str | None = None,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"ArchHub/attention-policy/v1\0")
    bound_reviewer = reviewer_root or policy.reviewer_root
    bound_evidence = evidence_root or policy.evidence_root
    for root_id in (
        policy.root_id,
        policy.class_order_root,
        *policy.class_roots,
        bound_reviewer,
        bound_evidence,
    ):
        if root_id is None:
            continue
        raw_id = root_id.encode("utf-8")
        raw_atom = snapshot.cells[root_id].atom
        digest.update(len(raw_id).to_bytes(8, "big"))
        digest.update(raw_id)
        digest.update(len(raw_atom).to_bytes(8, "big"))
        digest.update(raw_atom)
    return digest.hexdigest()


def read_attention_policy(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    policy_root: str,
) -> PolicyProjection:
    members = read_relation(snapshot, policy_root, budget=100_000)
    order_root = _one(
        members, protocol.role("policy-class-order"), "policy class order"
    ).participant_id
    status = _one(members, protocol.role("policy-status"), "policy status")
    digest_root = _one(
        members, protocol.role("policy-digest"), "policy digest"
    ).participant_id
    reviewer = _optional(
        members, protocol.role("policy-reviewer"), "policy reviewer"
    )
    evidence = _optional(
        members, protocol.role("policy-evidence"), "policy evidence"
    )
    order = read_relation(snapshot, order_root, budget=100_000)
    class_roots = _participants(order, protocol.role("priority-member"))
    if not class_roots:
        raise InvalidCell("attention policy has no priority classes")
    return PolicyProjection(
        policy_root,
        order_root,
        class_roots,
        status.participant_id,
        status.incidence_id,
        digest_root,
        reviewer.participant_id if reviewer else None,
        evidence.participant_id if evidence else None,
    )


def build_attention_policy(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    policy_id: str,
    ordered_classes: Iterable[tuple[str, str]],
) -> PolicyProjection:
    classes = tuple(ordered_classes)
    if not classes:
        raise InvalidCell("attention policy requires priority classes")
    class_ids = tuple(root for root, _ in classes)
    if len(class_ids) != len(set(class_ids)):
        raise InvalidCell("attention policy repeats a priority class")
    snapshot = store.snapshot()
    _ensure_roots(snapshot, (protocol.registry("policy"),), "policy registry")
    order_root = policy_id + ":class-order"
    digest_root = policy_id + ":digest"
    order = compose_relation_cells(
        ((protocol.role("priority-member"), root) for root in class_ids),
        relation_id=order_root,
    )
    policy = compose_relation_cells(
        (
            (protocol.role("policy-class-order"), order_root),
            (protocol.role("policy-status"), protocol.state("wip")),
            (protocol.role("policy-digest"), digest_root),
        ),
        relation_id=policy_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("policy"),
        protocol.role("policy-member"),
        policy_id,
        budget=100_000,
    )
    create = (
        *(_terminal(root, label) for root, label in classes),
        _terminal(digest_root, b""),
        *order.cells,
        *policy.cells,
        *append.create,
    )
    identities = [cell.id for cell in create]
    if len(identities) != len(set(identities)):
        raise InvalidCell("attention policy creates duplicate identities")
    store.commit(snapshot.revision, create=create, replace=append.replace)
    return read_attention_policy(store.snapshot(), protocol, policy_id)


class _OpaqueHandle:
    __slots__ = ("_marker",)

    def __init__(self, marker: object) -> None:
        self._marker = marker

    def __reduce__(self):
        raise TypeError("governance handles are process-local and not serializable")


@dataclass(frozen=True, slots=True)
class _PolicyGrant:
    policy_root: str
    reviewer_root: str
    evidence_root: str
    expires_at: float


class AttentionPolicyReleaseBroker:
    """One-use process-local authority for releasing an exact policy revision."""

    def __init__(self) -> None:
        self._marker = object()
        self._grants: dict[_OpaqueHandle, _PolicyGrant] = {}

    def issue(
        self,
        *,
        policy_root: str,
        reviewer_root: str,
        evidence_root: str,
        expires_at: float,
        now: float | None = None,
    ) -> _OpaqueHandle:
        current = time.time() if now is None else now
        if expires_at <= current:
            raise InvalidCell("policy release authority is already expired")
        handle = _OpaqueHandle(self._marker)
        self._grants[handle] = _PolicyGrant(
            policy_root, reviewer_root, evidence_root, expires_at
        )
        return handle

    def consume(
        self,
        handle: _OpaqueHandle,
        *,
        policy_root: str,
        reviewer_root: str,
        evidence_root: str,
        now: float | None = None,
    ) -> None:
        if not isinstance(handle, _OpaqueHandle) or handle._marker is not self._marker:
            raise PermissionError("invalid policy release authority")
        grant = self._grants.pop(handle, None)
        current = time.time() if now is None else now
        if grant is None or grant.expires_at < current:
            raise PermissionError("missing, consumed, or expired policy release authority")
        if grant != _PolicyGrant(
            policy_root, reviewer_root, evidence_root, grant.expires_at
        ):
            raise PermissionError("policy release authority scope mismatch")


def release_attention_policy(
    store: CellStore,
    protocol: AttentionProtocol,
    broker: AttentionPolicyReleaseBroker,
    handle: _OpaqueHandle,
    *,
    policy_root: str,
    reviewer_root: str,
    evidence_root: str,
    now: float | None = None,
) -> int:
    snapshot = store.snapshot()
    _ensure_roots(snapshot, (reviewer_root, evidence_root), "policy release")
    policy = read_attention_policy(snapshot, protocol, policy_root)
    if policy.status_root != protocol.state("wip"):
        raise InvalidCell("only a WIP attention policy can be released")
    broker.consume(
        handle,
        policy_root=policy_root,
        reviewer_root=reviewer_root,
        evidence_root=evidence_root,
        now=now,
    )
    digest = _policy_digest(
        snapshot,
        policy,
        reviewer_root=reviewer_root,
        evidence_root=evidence_root,
    ).encode("ascii")
    append = prepare_append_relation_members(
        snapshot,
        policy_root,
        (
            (protocol.role("policy-reviewer"), reviewer_root),
            (protocol.role("policy-evidence"), evidence_root),
        ),
        budget=100_000,
    )
    status = snapshot.cells[policy.status_incidence]
    digest_cell = snapshot.cells[policy.digest_root]
    return store.commit(
        snapshot.revision,
        create=append.create,
        replace=(
            *append.replace,
            Cell(status.id, status.link0, protocol.state("released"), status.atom),
            Cell(
                digest_cell.id,
                digest_cell.link0,
                digest_cell.link1,
                digest,
            ),
        ),
    )


def verify_attention_policy(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    policy_root: str,
) -> PolicyProjection:
    policy = read_attention_policy(snapshot, protocol, policy_root)
    if policy.status_root != protocol.state("released"):
        raise InvalidCell("attention policy is not released")
    if policy.reviewer_root is None or policy.evidence_root is None:
        raise InvalidCell("released attention policy lacks review evidence")
    recorded = _atom_text(snapshot, policy.digest_root)
    expected = _policy_digest(snapshot, policy)
    if recorded != expected:
        raise InvalidCell("released attention policy drifted")
    return policy


def read_signal(
    snapshot: Snapshot, protocol: AttentionProtocol, signal_root: str
) -> SignalProjection:
    members = read_relation(snapshot, signal_root, budget=100_000)
    source = _one(members, protocol.role("signal-source"), "signal source")
    revision = _one(
        members, protocol.role("signal-source-revision"), "signal source revision"
    )
    observer = _one(
        members, protocol.role("signal-observer"), "signal observer"
    )
    provenance = _one(
        members, protocol.role("signal-provenance"), "signal provenance"
    )
    subscription = _optional(
        members, protocol.role("signal-subscription"), "signal subscription"
    )
    trust = _one(members, protocol.role("signal-trust"), "signal trust")
    observed = _one(
        members, protocol.role("signal-observed-at"), "signal observed at"
    )
    sensitivity = _one(
        members, protocol.role("signal-sensitivity"), "signal sensitivity"
    )
    audience = _one(
        members, protocol.role("signal-audience"), "signal audience"
    )
    idempotency = _one(
        members, protocol.role("signal-idempotency"), "signal idempotency"
    )
    lifecycle = _one(
        members, protocol.role("signal-lifecycle"), "signal lifecycle"
    )
    affected = _participants(members, protocol.role("signal-affected"))
    if not affected:
        raise InvalidCell("signal has no affected roots")
    return SignalProjection(
        signal_root,
        source.participant_id,
        _atom_int(snapshot, revision.participant_id),
        observer.participant_id,
        provenance.participant_id,
        subscription.participant_id if subscription else None,
        trust.participant_id,
        affected,
        _atom_text(snapshot, observed.participant_id),
        sensitivity.participant_id,
        audience.participant_id,
        _atom_text(snapshot, idempotency.participant_id),
        lifecycle.participant_id,
    )


def record_signal(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    signal_id: str,
    source_root: str,
    source_revision: int,
    observer_root: str,
    provenance_root: str,
    trust_root: str,
    affected_roots: Iterable[str],
    observed_at: str,
    sensitivity_root: str,
    audience_root: str,
    idempotency_key: str,
    lifecycle_root: str,
    subscription_root: str | None = None,
) -> str:
    affected = tuple(dict.fromkeys(affected_roots))
    if not affected:
        raise InvalidCell("signal requires affected roots")
    snapshot = store.snapshot()
    for existing in _registry_roots(
        snapshot, protocol, "signal", "signal-member"
    ):
        projected = read_signal(snapshot, protocol, existing)
        if projected.idempotency_key != idempotency_key:
            continue
        if (
            projected.source_root == source_root
            and projected.source_revision == source_revision
            and projected.observer_root == observer_root
            and projected.provenance_root == provenance_root
            and projected.subscription_root == subscription_root
            and projected.trust_root == trust_root
            and projected.affected_roots == affected
            and projected.observed_at == observed_at
            and projected.sensitivity_root == sensitivity_root
            and projected.audience_root == audience_root
            and projected.lifecycle_root == lifecycle_root
        ):
            return existing
        raise InvalidCell("signal idempotency identity was reused for other content")
    revision_root = signal_id + ":source-revision"
    observed_root = signal_id + ":observed-at"
    idempotency_root = signal_id + ":idempotency"
    members = [
        (protocol.role("signal-source"), source_root),
        (protocol.role("signal-source-revision"), revision_root),
        (protocol.role("signal-observer"), observer_root),
        (protocol.role("signal-provenance"), provenance_root),
        (protocol.role("signal-trust"), trust_root),
        *((protocol.role("signal-affected"), root) for root in affected),
        (protocol.role("signal-observed-at"), observed_root),
        (protocol.role("signal-sensitivity"), sensitivity_root),
        (protocol.role("signal-audience"), audience_root),
        (protocol.role("signal-idempotency"), idempotency_root),
        (protocol.role("signal-lifecycle"), lifecycle_root),
    ]
    if subscription_root is not None:
        members.append((protocol.role("signal-subscription"), subscription_root))
    _register_relation(
        store,
        protocol,
        root_id=signal_id,
        members=members,
        registry_name="signal",
        registry_member_role="signal-member",
        create=(
            _terminal(revision_root, source_revision),
            _terminal(observed_root, observed_at),
            _terminal(idempotency_root, idempotency_key),
        ),
    )
    return signal_id


def read_obligation(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    obligation_root: str,
) -> ObligationProjection:
    members = read_relation(snapshot, obligation_root, budget=100_000)
    state = _one(members, protocol.role("obligation-state"), "obligation state")
    return ObligationProjection(
        obligation_root,
        _one(members, protocol.role("obligation-subject"), "obligation subject").participant_id,
        _one(members, protocol.role("obligation-owner"), "obligation owner").participant_id,
        _one(members, protocol.role("obligation-reviewer"), "obligation reviewer").participant_id,
        _one(members, protocol.role("obligation-policy"), "obligation policy").participant_id,
        _one(members, protocol.role("obligation-priority"), "obligation priority").participant_id,
        state.participant_id,
        state.incidence_id,
        _participants(members, protocol.role("obligation-dependency")),
        _participants(members, protocol.role("obligation-court")),
        _participants(members, protocol.role("obligation-required-evidence")),
    )


def list_obligations(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
) -> tuple[ObligationProjection, ...]:
    """Project every registered obligation in durable registry order."""
    return tuple(
        read_obligation(snapshot, protocol, root)
        for root in _registry_roots(
            snapshot, protocol, "obligation", "obligation-member"
        )
    )


def prepare_obligation(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    *,
    obligation_id: str,
    subject_root: str,
    owner_root: str,
    reviewer_root: str,
    policy_root: str,
    priority_root: str,
    dependency_roots: Iterable[str] = (),
    court_roots: Iterable[str] = (),
    required_evidence_roots: Iterable[str] = (),
    created_at: str,
    due_at: str | None = None,
) -> PreparedObligation:
    """Prepare an obligation for inclusion in a larger atomic graph change."""
    if obligation_id in snapshot.cells:
        raise InvalidCell("obligation root already exists")
    policy = verify_attention_policy(snapshot, protocol, policy_root)
    if priority_root not in policy.class_roots:
        raise InvalidCell("obligation priority is outside the released policy")
    dependencies = tuple(dependency_roots)
    courts = tuple(court_roots)
    evidence = tuple(required_evidence_roots)
    _ensure_roots(
        snapshot,
        (
            subject_root,
            owner_root,
            reviewer_root,
            policy_root,
            priority_root,
            *dependencies,
            *courts,
            *evidence,
        ),
        "obligation",
    )
    if len(dependencies) != len(set(dependencies)):
        raise InvalidCell("obligation repeats a dependency")
    if len(courts) != len(set(courts)):
        raise InvalidCell("obligation repeats a court")
    if len(evidence) != len(set(evidence)):
        raise InvalidCell("obligation repeats required evidence")
    created_root = obligation_id + ":created-at"
    due_root = obligation_id + ":due-at" if due_at is not None else None
    members = [
        (protocol.role("obligation-subject"), subject_root),
        (protocol.role("obligation-owner"), owner_root),
        (protocol.role("obligation-reviewer"), reviewer_root),
        (protocol.role("obligation-policy"), policy_root),
        (protocol.role("obligation-priority"), priority_root),
        (protocol.role("obligation-state"), protocol.state("open")),
        (protocol.role("obligation-created-at"), created_root),
        *((protocol.role("obligation-dependency"), root) for root in dependencies),
        *((protocol.role("obligation-court"), root) for root in courts),
        *((protocol.role("obligation-required-evidence"), root) for root in evidence),
    ]
    create = [_terminal(created_root, created_at)]
    if due_root is not None:
        members.append((protocol.role("obligation-due-at"), due_root))
        create.append(_terminal(due_root, due_at or ""))
    relation = compose_relation_cells(members, relation_id=obligation_id)
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("obligation"),
        protocol.role("obligation-member"),
        obligation_id,
        budget=100_000,
    )
    cells = (*create, *relation.cells, *append.create)
    if len({cell.id for cell in cells}) != len(cells):
        raise InvalidCell("obligation creates duplicate physical identities")
    return PreparedObligation(
        obligation_id,
        tuple(cells),
        append.replace,
    )


def record_obligation(
    store: CellStore,
    protocol: AttentionProtocol,
    **kwargs,
) -> str:
    snapshot = store.snapshot()
    prepared = prepare_obligation(snapshot, protocol, **kwargs)
    store.commit(
        snapshot.revision,
        create=prepared.create,
        replace=prepared.replace,
    )
    return prepared.root_id


def resolve_obligation(
    store: CellStore,
    protocol: AttentionProtocol,
    obligation_root: str,
    *,
    evidence_root: str,
) -> int:
    snapshot = store.snapshot()
    _ensure_roots(snapshot, (evidence_root,), "obligation resolution")
    obligation = read_obligation(snapshot, protocol, obligation_root)
    if obligation.state_root == protocol.state("resolved"):
        raise InvalidCell("obligation is already resolved")
    append = prepare_append_relation_member(
        snapshot,
        obligation_root,
        protocol.role("obligation-resolution-evidence"),
        evidence_root,
        budget=100_000,
    )
    state = snapshot.cells[obligation.state_incidence]
    return store.commit(
        snapshot.revision,
        create=append.create,
        replace=(
            *append.replace,
            Cell(state.id, state.link0, protocol.state("resolved"), state.atom),
        ),
    )


def read_eligibility(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    eligibility_root: str,
) -> EligibilityProjection:
    members = read_relation(snapshot, eligibility_root, budget=100_000)
    revision = _one(
        members, protocol.role("eligibility-snapshot"), "eligibility snapshot"
    ).participant_id
    return EligibilityProjection(
        eligibility_root,
        _one(members, protocol.role("eligibility-observer"), "eligibility observer").participant_id,
        _one(members, protocol.role("eligibility-candidate"), "eligibility candidate").participant_id,
        _one(members, protocol.role("eligibility-action"), "eligibility action").participant_id,
        _one(members, protocol.role("eligibility-scope"), "eligibility scope").participant_id,
        _atom_int(snapshot, revision),
        _one(members, protocol.role("eligibility-state"), "eligibility state").participant_id,
        _one(members, protocol.role("eligibility-reason"), "eligibility reason").participant_id,
        _one(members, protocol.role("eligibility-authority"), "eligibility authority").participant_id,
        _one(members, protocol.role("eligibility-audience"), "eligibility audience").participant_id,
    )


def record_eligibility_decision(
    store: CellStore,
    protocol: AttentionProtocol,
    decision: AuthorizationDecision,
    *,
    eligibility_id: str,
    scope_root: str,
    source_snapshot_revision: int,
    audience_root: str,
) -> str:
    reason_root = eligibility_id + ":reason"
    snapshot_root = eligibility_id + ":snapshot"
    _register_relation(
        store,
        protocol,
        root_id=eligibility_id,
        members=(
            (protocol.role("eligibility-observer"), decision.subject_root),
            (protocol.role("eligibility-candidate"), decision.object_root),
            (protocol.role("eligibility-action"), decision.action_root),
            (protocol.role("eligibility-scope"), scope_root),
            (protocol.role("eligibility-snapshot"), snapshot_root),
            (
                protocol.role("eligibility-state"),
                protocol.state("allowed" if decision.allowed else "denied"),
            ),
            (protocol.role("eligibility-reason"), reason_root),
            (protocol.role("eligibility-authority"), decision.policy_root),
            *((protocol.role("eligibility-rule"), root) for root in decision.determining_rule_roots),
            (protocol.role("eligibility-audience"), audience_root),
        ),
        registry_name="eligibility",
        registry_member_role="eligibility-member",
        create=(
            _terminal(reason_root, decision.reason),
            _terminal(snapshot_root, source_snapshot_revision),
        ),
    )
    return eligibility_id


def read_attention(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    attention_root: str,
) -> AttentionProjection:
    members = read_relation(snapshot, attention_root, budget=100_000)
    state = _one(members, protocol.role("attention-state"), "attention state")
    obligation = _optional(
        members, protocol.role("attention-obligation"), "attention obligation"
    )
    snapshot_root = _one(
        members, protocol.role("attention-snapshot"), "attention snapshot"
    ).participant_id
    sequence_root = _one(
        members,
        protocol.role("attention-created-sequence"),
        "attention created sequence",
    ).participant_id
    reasons = _participants(members, protocol.role("attention-reason"))
    if not reasons:
        raise InvalidCell("attention has no explicit reason")
    return AttentionProjection(
        attention_root,
        _one(members, protocol.role("attention-observer"), "attention observer").participant_id,
        _one(members, protocol.role("attention-candidate"), "attention candidate").participant_id,
        _one(members, protocol.role("attention-scope"), "attention scope").participant_id,
        _atom_int(snapshot, snapshot_root),
        reasons,
        _one(members, protocol.role("attention-policy"), "attention policy").participant_id,
        _one(members, protocol.role("attention-priority"), "attention priority").participant_id,
        _one(members, protocol.role("attention-eligibility"), "attention eligibility").participant_id,
        obligation.participant_id if obligation else None,
        state.participant_id,
        state.incidence_id,
        _atom_int(snapshot, sequence_root),
        _one(members, protocol.role("attention-history"), "attention history").participant_id,
    )


def record_attention(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    attention_id: str,
    observer_root: str,
    candidate_root: str,
    scope_root: str,
    source_snapshot_revision: int,
    reason_roots: Iterable[str],
    policy_root: str,
    priority_root: str,
    eligibility_root: str,
    obligation_root: str | None = None,
) -> str:
    reasons = tuple(dict.fromkeys(reason_roots))
    if not reasons:
        raise InvalidCell("attention requires explicit reasons")
    snapshot = store.snapshot()
    policy = verify_attention_policy(snapshot, protocol, policy_root)
    if priority_root not in policy.class_roots:
        raise InvalidCell("attention priority is outside the released policy")
    eligibility = read_eligibility(snapshot, protocol, eligibility_root)
    if eligibility.state_root != protocol.state("allowed"):
        raise PermissionError("denied candidates cannot enter attention")
    if (
        eligibility.observer_root != observer_root
        or eligibility.candidate_root != candidate_root
        or eligibility.scope_root != scope_root
        or eligibility.snapshot_revision != source_snapshot_revision
    ):
        raise PermissionError("attention does not match its eligibility decision")
    if obligation_root is not None:
        obligation = read_obligation(snapshot, protocol, obligation_root)
        if obligation.priority_root != priority_root:
            raise InvalidCell("attention priority disagrees with its obligation")
    existing_roots = _registry_roots(
        snapshot, protocol, "attention", "attention-member"
    )
    for existing_root in existing_roots:
        existing = read_attention(snapshot, protocol, existing_root)
        if (
            existing.state_root == protocol.state("active")
            and existing.observer_root == observer_root
            and existing.candidate_root == candidate_root
            and existing.scope_root == scope_root
        ):
            if (
                existing.policy_root == policy_root
                and existing.priority_root == priority_root
                and existing.eligibility_root == eligibility_root
                and existing.reason_roots == reasons
            ):
                return existing_root
            raise InvalidCell("active attention already exists for this candidate")
    sequence = len(existing_roots) + 1
    snapshot_root = attention_id + ":snapshot"
    sequence_root = attention_id + ":sequence"
    history_root = attention_id + ":history"
    history = compose_relation_cells((), relation_id=history_root)
    members = [
        (protocol.role("attention-observer"), observer_root),
        (protocol.role("attention-candidate"), candidate_root),
        (protocol.role("attention-scope"), scope_root),
        (protocol.role("attention-snapshot"), snapshot_root),
        *((protocol.role("attention-reason"), root) for root in reasons),
        (protocol.role("attention-policy"), policy_root),
        (protocol.role("attention-priority"), priority_root),
        (protocol.role("attention-eligibility"), eligibility_root),
        (protocol.role("attention-state"), protocol.state("active")),
        (protocol.role("attention-created-sequence"), sequence_root),
        (protocol.role("attention-history"), history_root),
    ]
    if obligation_root is not None:
        members.append((protocol.role("attention-obligation"), obligation_root))
    _register_relation(
        store,
        protocol,
        root_id=attention_id,
        members=members,
        registry_name="attention",
        registry_member_role="attention-member",
        create=(
            _terminal(snapshot_root, source_snapshot_revision),
            _terminal(sequence_root, sequence),
        ),
        extra_relation_cells=history.cells,
    )
    return attention_id


def ordered_attentions(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    *,
    observer_root: str,
    scope_root: str,
    policy_root: str,
) -> tuple[AttentionProjection, ...]:
    policy = verify_attention_policy(snapshot, protocol, policy_root)
    rank = {root: index for index, root in enumerate(policy.class_roots)}
    visible: list[AttentionProjection] = []
    for root in _registry_roots(
        snapshot, protocol, "attention", "attention-member"
    ):
        item = read_attention(snapshot, protocol, root)
        if (
            item.state_root != protocol.state("active")
            or item.observer_root != observer_root
            or item.scope_root != scope_root
            or item.policy_root != policy_root
            or item.priority_root not in rank
        ):
            continue
        eligibility = read_eligibility(
            snapshot, protocol, item.eligibility_root
        )
        if (
            eligibility.state_root != protocol.state("allowed")
            or eligibility.observer_root != item.observer_root
            or eligibility.candidate_root != item.candidate_root
            or eligibility.scope_root != item.scope_root
            or eligibility.snapshot_revision != item.snapshot_revision
        ):
            continue
        visible.append(AttentionProjection(
            item.root_id,
            item.observer_root,
            item.candidate_root,
            item.scope_root,
            item.snapshot_revision,
            item.reason_roots,
            item.policy_root,
            item.priority_root,
            item.eligibility_root,
            item.obligation_root,
            item.state_root,
            item.state_incidence,
            item.sequence,
            item.history_root,
            rank[item.priority_root],
        ))
    return tuple(sorted(visible, key=lambda item: (item.priority_index, item.sequence)))


def invalidate_attention(
    store: CellStore,
    protocol: AttentionProtocol,
    attention_root: str,
    *,
    reason_root: str,
) -> int:
    snapshot = store.snapshot()
    _ensure_roots(snapshot, (reason_root,), "attention invalidation")
    item = read_attention(snapshot, protocol, attention_root)
    if item.state_root != protocol.state("active"):
        raise InvalidCell("only active attention can be invalidated")
    history = prepare_append_relation_member(
        snapshot,
        item.history_root,
        protocol.role("attention-reason"),
        reason_root,
        budget=100_000,
    )
    state = snapshot.cells[item.state_incidence]
    return store.commit(
        snapshot.revision,
        create=history.create,
        replace=(
            *history.replace,
            Cell(state.id, state.link0, protocol.state("invalidated"), state.atom),
        ),
    )


def read_focus(
    snapshot: Snapshot, protocol: AttentionProtocol, focus_root: str
) -> FocusProjection:
    members = read_relation(snapshot, focus_root, budget=100_000)
    state = _one(members, protocol.role("focus-state"), "focus state")
    previous = _optional(members, protocol.role("focus-previous"), "previous focus")
    selected = _participants(members, protocol.role("focus-selected"))
    primary = _one(members, protocol.role("focus-primary"), "focus primary").participant_id
    reasons = _participants(members, protocol.role("focus-reason"))
    if not reasons:
        raise InvalidCell("focus requires explicit reasons")
    created_root = _one(
        members, protocol.role("focus-created-at"), "focus created at"
    ).participant_id
    if not selected or primary not in selected:
        raise InvalidCell("focus primary must be one of its selected roots")
    return FocusProjection(
        focus_root,
        _one(members, protocol.role("focus-actor"), "focus actor").participant_id,
        _one(members, protocol.role("focus-session"), "focus session").participant_id,
        _one(members, protocol.role("focus-scope"), "focus scope").participant_id,
        selected,
        primary,
        _one(members, protocol.role("focus-origin"), "focus origin").participant_id,
        state.participant_id,
        state.incidence_id,
        previous.participant_id if previous else None,
        reasons,
        _participants(members, protocol.role("focus-attention")),
        _one(
            members, protocol.role("focus-authority"), "focus authority"
        ).participant_id,
        _atom_text(snapshot, created_root),
        _participants(members, protocol.role("focus-consent-evidence")),
    )


def prepare_accepted_focus_transition(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    *,
    focus_id: str,
    actor_root: str,
    session_root: str,
    scope_root: str,
    selected_roots: Iterable[str],
    primary_root: str,
    origin: str,
    reason_roots: Iterable[str],
    attention_roots: Iterable[str],
    authority_root: str,
    consent_evidence_root: str,
    created_at: str,
    pending_roots: Iterable[str] = (),
) -> PreparedFocusTransition:
    """Prepare one accepted focus and resolve its predecessor in one commit.

    This is for an authenticated gesture whose exact consent evidence already
    exists in the graph. Model or policy suggestions still use
    :func:`propose_focus` and :func:`accept_focus` so they cannot silently take
    control of a user's session.
    """
    selected = tuple(dict.fromkeys(selected_roots))
    reasons = tuple(dict.fromkeys(reason_roots))
    attentions = tuple(dict.fromkeys(attention_roots))
    if not selected or primary_root not in selected:
        raise InvalidCell("focus primary must be selected")
    if not reasons:
        raise InvalidCell("focus requires explicit reasons")
    if focus_id in snapshot.cells:
        raise InvalidCell("focus root already exists: %r" % focus_id)
    try:
        origin_root = protocol.origin(origin)
    except InvalidCell:
        raise
    referenced = (
            actor_root,
            session_root,
            scope_root,
            *selected,
            *reasons,
            *attentions,
            authority_root,
            consent_evidence_root,
            origin_root,
            protocol.state("active"),
    )
    admitted_pending = frozenset(pending_roots)
    missing = tuple(
        root for root in referenced
        if root not in snapshot.cells and root not in admitted_pending
    )
    if missing:
        raise InvalidCell(
            "accepted focus references missing roots: %r" % (missing,)
        )

    previous: FocusProjection | None = None
    for root in _registry_roots(snapshot, protocol, "focus", "focus-member"):
        candidate = read_focus(snapshot, protocol, root)
        if (
            candidate.session_root == session_root
            and candidate.state_root == protocol.state("active")
        ):
            if previous is not None:
                raise InvalidCell("view session has several active focus roots")
            previous = candidate

    created_root = focus_id + ":created-at"
    members = [
        (protocol.role("focus-actor"), actor_root),
        (protocol.role("focus-session"), session_root),
        (protocol.role("focus-scope"), scope_root),
        *((protocol.role("focus-selected"), root) for root in selected),
        (protocol.role("focus-primary"), primary_root),
        (protocol.role("focus-origin"), origin_root),
        *((protocol.role("focus-reason"), root) for root in reasons),
        *((protocol.role("focus-attention"), root) for root in attentions),
        (protocol.role("focus-state"), protocol.state("active")),
        (protocol.role("focus-authority"), authority_root),
        (protocol.role("focus-created-at"), created_root),
        (protocol.role("focus-consent-evidence"), consent_evidence_root),
    ]
    if previous is not None:
        members.append((protocol.role("focus-previous"), previous.root_id))

    relation = compose_relation_cells(members, relation_id=focus_id)
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("focus"),
        protocol.role("focus-member"),
        focus_id,
        budget=100_000,
    )
    create = (_terminal(created_root, created_at), *relation.cells, *append.create)
    identities = tuple(cell.id for cell in create)
    if len(identities) != len(set(identities)):
        raise InvalidCell("focus transition creates duplicate physical identities")
    replacements = list(append.replace)
    if previous is not None:
        state = snapshot.cells[previous.state_incidence]
        replacements.append(Cell(
            state.id,
            state.link0,
            protocol.state("resolved"),
            state.atom,
        ))
    return PreparedFocusTransition(focus_id, create, tuple(replacements))


def propose_focus(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    focus_id: str,
    actor_root: str,
    session_root: str,
    scope_root: str,
    selected_roots: Iterable[str],
    primary_root: str,
    origin: str,
    reason_roots: Iterable[str],
    attention_roots: Iterable[str],
    authority_root: str,
    created_at: str,
) -> str:
    selected = tuple(dict.fromkeys(selected_roots))
    reasons = tuple(dict.fromkeys(reason_roots))
    if not selected or primary_root not in selected:
        raise InvalidCell("focus primary must be selected")
    if not reasons:
        raise InvalidCell("focus requires explicit reasons")
    snapshot = store.snapshot()
    previous = None
    for root in _registry_roots(snapshot, protocol, "focus", "focus-member"):
        focus = read_focus(snapshot, protocol, root)
        if focus.session_root == session_root and focus.state_root == protocol.state("active"):
            if previous is not None:
                raise InvalidCell("view session has several active focus roots")
            previous = root
    created_root = focus_id + ":created-at"
    members = [
        (protocol.role("focus-actor"), actor_root),
        (protocol.role("focus-session"), session_root),
        (protocol.role("focus-scope"), scope_root),
        *((protocol.role("focus-selected"), root) for root in selected),
        (protocol.role("focus-primary"), primary_root),
        (protocol.role("focus-origin"), protocol.origin(origin)),
        *((protocol.role("focus-reason"), root) for root in reasons),
        *((protocol.role("focus-attention"), root) for root in attention_roots),
        (protocol.role("focus-state"), protocol.state("suggested")),
        (protocol.role("focus-authority"), authority_root),
        (protocol.role("focus-created-at"), created_root),
    ]
    if previous is not None:
        members.append((protocol.role("focus-previous"), previous))
    _register_relation(
        store,
        protocol,
        root_id=focus_id,
        members=members,
        registry_name="focus",
        registry_member_role="focus-member",
        create=(_terminal(created_root, created_at),),
    )
    return focus_id


@dataclass(frozen=True, slots=True)
class _FocusGrant:
    focus_root: str
    actor_root: str
    session_root: str
    evidence_root: str
    expires_at: float


class FocusConsentBroker:
    """One-use evidence that an exact user accepted an exact suggested focus."""

    def __init__(self) -> None:
        self._marker = object()
        self._grants: dict[_OpaqueHandle, _FocusGrant] = {}

    def issue(
        self,
        *,
        focus_root: str,
        actor_root: str,
        session_root: str,
        evidence_root: str,
        expires_at: float,
        now: float | None = None,
    ) -> _OpaqueHandle:
        current = time.time() if now is None else now
        if expires_at <= current:
            raise InvalidCell("focus consent is already expired")
        handle = _OpaqueHandle(self._marker)
        self._grants[handle] = _FocusGrant(
            focus_root, actor_root, session_root, evidence_root, expires_at
        )
        return handle

    def consume(
        self,
        handle: _OpaqueHandle,
        *,
        focus_root: str,
        actor_root: str,
        session_root: str,
        evidence_root: str,
        now: float | None = None,
    ) -> None:
        if not isinstance(handle, _OpaqueHandle) or handle._marker is not self._marker:
            raise PermissionError("invalid focus consent")
        grant = self._grants.pop(handle, None)
        current = time.time() if now is None else now
        if grant is None or grant.expires_at < current:
            raise PermissionError("missing, consumed, or expired focus consent")
        if grant != _FocusGrant(
            focus_root, actor_root, session_root, evidence_root, grant.expires_at
        ):
            raise PermissionError("focus consent scope mismatch")


def accept_focus(
    store: CellStore,
    protocol: AttentionProtocol,
    broker: FocusConsentBroker,
    handle: _OpaqueHandle,
    *,
    focus_root: str,
    actor_root: str,
    session_root: str,
    evidence_root: str,
    now: float | None = None,
) -> int:
    snapshot = store.snapshot()
    _ensure_roots(snapshot, (evidence_root,), "focus consent")
    focus = read_focus(snapshot, protocol, focus_root)
    if focus.actor_root != actor_root or focus.session_root != session_root:
        raise PermissionError("focus acceptance actor or session mismatch")
    if focus.state_root != protocol.state("suggested"):
        raise InvalidCell("only suggested focus can be accepted")
    broker.consume(
        handle,
        focus_root=focus_root,
        actor_root=actor_root,
        session_root=session_root,
        evidence_root=evidence_root,
        now=now,
    )
    append = prepare_append_relation_member(
        snapshot,
        focus_root,
        protocol.role("focus-consent-evidence"),
        evidence_root,
        budget=100_000,
    )
    replacements = list(append.replace)
    target_state = snapshot.cells[focus.state_incidence]
    replacements.append(Cell(
        target_state.id,
        target_state.link0,
        protocol.state("active"),
        target_state.atom,
    ))
    for root in _registry_roots(snapshot, protocol, "focus", "focus-member"):
        if root == focus_root:
            continue
        existing = read_focus(snapshot, protocol, root)
        if (
            existing.session_root == session_root
            and existing.state_root == protocol.state("active")
        ):
            state = snapshot.cells[existing.state_incidence]
            replacements.append(Cell(
                state.id,
                state.link0,
                protocol.state("resolved"),
                state.atom,
            ))
    return store.commit(
        snapshot.revision,
        create=append.create,
        replace=replacements,
    )


def active_focus(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    *,
    session_root: str,
) -> FocusProjection | None:
    found = tuple(
        focus
        for focus in (
            read_focus(snapshot, protocol, root)
            for root in _registry_roots(
                snapshot, protocol, "focus", "focus-member"
            )
        )
        if focus.session_root == session_root
        and focus.state_root == protocol.state("active")
    )
    if len(found) > 1:
        raise InvalidCell("view session has several active focus roots")
    return found[0] if found else None


def read_decision(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    decision_root: str,
) -> DecisionProjection:
    members = read_relation(snapshot, decision_root, budget=100_000)
    return DecisionProjection(
        decision_root,
        _one(members, protocol.role("decision-subject"), "decision subject").participant_id,
        _one(members, protocol.role("decision-action"), "decision action").participant_id,
        _one(members, protocol.role("decision-actor"), "decision actor").participant_id,
        _one(members, protocol.role("decision-authority"), "decision authority").participant_id,
        _participants(members, protocol.role("decision-evidence")),
        _one(members, protocol.role("decision-state"), "decision state").participant_id,
    )


def record_decision(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    decision_id: str,
    subject_root: str,
    action_root: str,
    actor_root: str,
    authority_root: str,
    evidence_roots: Iterable[str],
    state: str,
    created_at: str,
) -> str:
    evidence = tuple(dict.fromkeys(evidence_roots))
    if not evidence:
        raise InvalidCell("decision requires evidence")
    if state not in {"suggested", "accepted", "rejected"}:
        raise InvalidCell("decision state is invalid")
    created_root = decision_id + ":created-at"
    _register_relation(
        store,
        protocol,
        root_id=decision_id,
        members=(
            (protocol.role("decision-subject"), subject_root),
            (protocol.role("decision-action"), action_root),
            (protocol.role("decision-actor"), actor_root),
            (protocol.role("decision-authority"), authority_root),
            *((protocol.role("decision-evidence"), root) for root in evidence),
            (protocol.role("decision-state"), protocol.state(state)),
            (protocol.role("decision-created-at"), created_root),
        ),
        registry_name="decision",
        registry_member_role="decision-member",
        create=(_terminal(created_root, created_at),),
    )
    return decision_id


def read_outcome(
    snapshot: Snapshot,
    protocol: AttentionProtocol,
    outcome_root: str,
) -> OutcomeProjection:
    members = read_relation(snapshot, outcome_root, budget=100_000)
    receipt = _optional(members, protocol.role("outcome-receipt"), "outcome receipt")
    reconciliation = _optional(
        members, protocol.role("outcome-reconciliation"), "outcome reconciliation"
    )
    reason = _optional(members, protocol.role("outcome-reason"), "outcome reason")
    return OutcomeProjection(
        outcome_root,
        _one(members, protocol.role("outcome-decision"), "outcome decision").participant_id,
        _one(members, protocol.role("outcome-provider"), "outcome provider").participant_id,
        _one(members, protocol.role("outcome-state"), "outcome state").participant_id,
        receipt.participant_id if receipt else None,
        reconciliation.participant_id if reconciliation else None,
        reason.participant_id if reason else None,
    )


def record_outcome(
    store: CellStore,
    protocol: AttentionProtocol,
    *,
    outcome_id: str,
    decision_root: str,
    provider_root: str,
    state: str,
    observed_at: str,
    receipt_root: str | None = None,
    reconciliation_root: str | None = None,
    reason_root: str | None = None,
) -> str:
    if state not in {"pending", "succeeded", "failed", "denied", "reconciled", "reversed"}:
        raise InvalidCell("outcome state is invalid")
    if state in {"succeeded", "reconciled", "reversed"} and (
        receipt_root is None or reconciliation_root is None
    ):
        raise InvalidCell("settled outcome requires receipt and reconciliation")
    if state in {"failed", "denied"} and reason_root is None:
        raise InvalidCell("failed or denied outcome requires a reason")
    observed_root = outcome_id + ":observed-at"
    members = [
        (protocol.role("outcome-decision"), decision_root),
        (protocol.role("outcome-provider"), provider_root),
        (protocol.role("outcome-state"), protocol.state(state)),
        (protocol.role("outcome-observed-at"), observed_root),
    ]
    for role, root in (
        ("outcome-receipt", receipt_root),
        ("outcome-reconciliation", reconciliation_root),
        ("outcome-reason", reason_root),
    ):
        if root is not None:
            members.append((protocol.role(role), root))
    _register_relation(
        store,
        protocol,
        root_id=outcome_id,
        members=members,
        registry_name="outcome",
        registry_member_role="outcome-member",
        create=(_terminal(observed_root, observed_at),),
    )
    return outcome_id


__all__ = [
    "AttentionProtocol",
    "PolicyProjection",
    "SignalProjection",
    "ObligationProjection",
    "PreparedObligation",
    "EligibilityProjection",
    "AttentionProjection",
    "FocusProjection",
    "DecisionProjection",
    "OutcomeProjection",
    "AttentionPolicyReleaseBroker",
    "FocusConsentBroker",
    "bootstrap_attention_protocol",
    "open_attention_protocol",
    "build_attention_policy",
    "read_attention_policy",
    "release_attention_policy",
    "verify_attention_policy",
    "record_signal",
    "read_signal",
    "prepare_obligation",
    "record_obligation",
    "read_obligation",
    "resolve_obligation",
    "record_eligibility_decision",
    "read_eligibility",
    "record_attention",
    "read_attention",
    "ordered_attentions",
    "invalidate_attention",
    "propose_focus",
    "read_focus",
    "accept_focus",
    "active_focus",
    "record_decision",
    "read_decision",
    "record_outcome",
    "read_outcome",
]
