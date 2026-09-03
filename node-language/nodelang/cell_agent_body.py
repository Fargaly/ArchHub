"""Governed agent bodies and sessions assembled from universal Cell relations.

This catalogue protocol adds no store, kind, runtime, model execution, proposal
mutation, capability invocation, or effect path. Every mutating entrypoint uses
released graph authority and an opaque authenticated context internally.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .cell_authorization import (
    ACTION_NAMES as AUTHORIZATION_ACTION_NAMES,
    ROLE_NAMES as AUTHORIZATION_ROLE_NAMES,
    AuthenticationBroker,
    AuthorizationDecision,
    AuthorizationDenied,
    AuthorizationEvaluation,
    AuthorizationProtocol,
    AuthorizationRequest,
    authorize_node_request,
    authorize_node_requests,
    evaluate_node_requests,
    read_authorization_rule,
    verify_authorization_policy,
)
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
    "body-member",
    "body-identity",
    "body-authority-policy",
    "body-authority-action",
    "body-authority-rule",
    "body-lifecycle",
    "body-state",
    "body-visibility",
    "body-model-binding",
    "body-creation-action",
    "body-creation-rule",
    "body-creation-reason",
    "body-creation-receipt",
    "session-member",
    "session-body",
    "session-subject",
    "session-owner-role",
    "session-view-session",
    "session-scope",
    "session-focus",
    "session-assignment",
    "session-model-binding",
    "session-context-registry",
    "session-proposal-registry",
    "session-context-cursor",
    "session-state",
    "session-close-reason",
    "session-view-action",
    "session-view-policy",
    "session-view-rule",
    "session-view-reason",
    "session-view-receipt",
    "session-scope-action",
    "session-scope-policy",
    "session-scope-rule",
    "session-scope-reason",
    "session-scope-receipt",
    "session-close-action",
    "session-close-policy",
    "session-close-rule",
    "session-close-authorization-reason",
    "session-close-receipt",
    "context-member",
    "context-session",
    "context-subject",
    "context-root",
    "context-provenance",
    "context-trust",
    "context-sensitivity",
    "context-audience",
    "context-lifecycle",
    "context-purpose",
    "context-interface",
    "context-observed-revision",
    "context-action",
    "context-policy",
    "context-rule",
    "context-authorization-reason",
    "context-authorization-receipt",
    "registry-interface",
    "registry-action",
    "registry-policy",
    "registry-rule",
    "registry-authorization-reason",
    "registry-authorization-receipt",
    "context-idempotency",
    "context-semantic-digest",
    "context-sequence",
    "receipt-subject",
    "receipt-principal",
    "receipt-tenant",
    "receipt-assurance",
    "receipt-policy",
    "receipt-policy-digest",
    "receipt-action",
    "receipt-object",
    "receipt-rule",
    "receipt-reason",
    "receipt-revision",
    "receipt-evaluated-at",
    "receipt-context-expires-at",
    "receipt-resolver-protocol",
    "receipt-resolver-revision",
    "receipt-resolver-evaluated-at",
    "receipt-resolver-evidence",
    "proposal-member",
)

STATE_NAMES = ("active", "closed", "unbound")
REGISTRY_NAMES = ("body", "session")
RELATION_BUDGET = 100_000
MAX_BODY_RULES = 256
MAX_CONTEXT_ENTRIES = 128
MAX_CONTEXT_RELATION_MEMBERS = 640
MAX_RECEIPT_RELATIONSHIPS = 4_096
MAX_RECEIPT_PRINCIPALS = 256
MAX_RECEIPT_RELATION_MEMBERS = 4_352
MAX_SESSION_READ_WORK = 100_000
_ANY = object()

ModelBindingVerifier = Callable[[Snapshot, str, str], object]
ProposalVerifier = Callable[[Snapshot, str, str], object]


@dataclass(slots=True)
class _ReadWorkBudget:
    remaining: int

    def consume(self, count: int, label: str) -> None:
        self.remaining -= count
        if self.remaining < 0:
            raise InvalidCell("%s exceeded the aggregate read budget" % label)


@dataclass(frozen=True, slots=True)
class AgentBodyProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown agent-body role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown agent-body state %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown agent-body registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class AgentBodyProjection:
    root_id: str
    identity_root: str
    authority_policy_root: str
    authority_action_roots: tuple[str, ...]
    authority_rule_roots: tuple[str, ...]
    lifecycle_root: str
    state_root: str
    visibility_root: str
    model_binding_root: str | None
    creation_action_root: str
    creation_rule_roots: tuple[str, ...]
    creation_reason: str
    creation_receipt_root: str


@dataclass(frozen=True, slots=True)
class AgentSessionProjection:
    root_id: str
    body_root: str
    subject_root: str
    owner_role_root: str
    view_session_root: str
    scope_root: str
    focus_root: str
    assignment_root: str
    model_binding_root: str | None
    context_registry_root: str
    proposal_registry_root: str
    context_cursor_root: str
    context_cursor: int
    state_root: str
    state_incidence: str
    view_action_root: str
    view_rule_roots: tuple[str, ...]
    view_reason: str
    view_receipt_root: str
    scope_action_root: str
    scope_rule_roots: tuple[str, ...]
    scope_reason: str
    scope_receipt_root: str
    close_action_root: str | None
    close_rule_roots: tuple[str, ...]
    close_authorization_reason: str | None
    close_receipt_root: str | None
    context_entry_roots: tuple[str, ...]
    proposal_roots: tuple[str, ...]
    close_reason_root: str | None


@dataclass(frozen=True, slots=True)
class ContextEntryProjection:
    root_id: str
    session_root: str
    subject_root: str
    context_root: str
    provenance_root: str
    trust_root: str
    sensitivity_root: str
    audience_root: str
    lifecycle_root: str
    purpose_root: str | None
    context_interface_root: str | None
    registry_interface_root: str | None
    observed_revision: int
    context_action_root: str
    context_policy_root: str
    context_rule_roots: tuple[str, ...]
    context_authorization_reason: str
    context_receipt_root: str
    registry_action_root: str
    registry_policy_root: str
    registry_rule_roots: tuple[str, ...]
    registry_authorization_reason: str
    registry_receipt_root: str
    idempotency_key: str
    semantic_digest: str
    sequence: int


@dataclass(frozen=True, slots=True)
class AuthorizationReceiptProjection:
    root_id: str
    revision: int
    evaluated_at: float
    context_expires_at: float
    subject_root: str
    principal_roots: tuple[str, ...]
    tenant_root: str | None
    assurance_root: str
    policy_root: str
    policy_digest: str
    action_root: str
    object_root: str
    rule_roots: tuple[str, ...]
    reason: str
    resolver_protocol_root: str | None
    resolver_revision: int | None
    resolver_evaluated_at: float | None
    resolver_evidence_roots: tuple[str, ...]


def _terminal(root_id: str, value: str | int) -> Cell:
    atom = (
        str(value).encode("ascii")
        if isinstance(value, int)
        else value.encode("utf-8")
    )
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


def _closed_roles(
    members: Iterable[RelationMember], allowed: Iterable[str], label: str
) -> None:
    admitted = frozenset(allowed)
    unexpected = tuple(
        member.role_id for member in members if member.role_id not in admitted
    )
    if unexpected:
        raise InvalidCell("%s contains unexpected roles: %r" % (label, unexpected))


def _ensure_roots(snapshot: Snapshot, roots: Iterable[str], label: str) -> None:
    missing = tuple(root for root in roots if root not in snapshot.cells)
    if missing:
        raise InvalidCell("%s references missing roots: %r" % (label, missing))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("%s is not a terminal Cell" % label)
        return cell.atom.decode("utf-8")
    except KeyError as exc:
        raise InvalidCell("%s root is missing" % label) from exc
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s is not UTF-8" % label) from exc


def _integer(snapshot: Snapshot, root_id: str, label: str) -> int:
    try:
        return int(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("%s is not an integer" % label) from exc


def _unique_roots(
    values: Iterable[str],
    label: str,
    *,
    limit: int = RELATION_BUDGET,
) -> tuple[str, ...]:
    roots_list: list[str] = []
    for root in values:
        if len(roots_list) >= limit:
            raise InvalidCell("%s budget exceeded" % label)
        if not isinstance(root, str) or not root:
            raise InvalidCell("%s contains an invalid root" % label)
        roots_list.append(root)
    roots = tuple(roots_list)
    if len(roots) != len(set(roots)):
        raise InvalidCell("%s contains duplicate roots" % label)
    return roots


def _assert_creates(
    snapshot: Snapshot, cells: Iterable[Cell], label: str
) -> tuple[Cell, ...]:
    created = tuple(cells)
    identities = tuple(cell.id for cell in created)
    if len(identities) != len(set(identities)):
        raise InvalidCell("%s creates duplicate physical identities" % label)
    existing = tuple(root for root in identities if root in snapshot.cells)
    if existing:
        raise InvalidCell("%s identities already exist: %r" % (label, existing))
    return created


def _protocol_for_prefix(prefix: str) -> AgentBodyProtocol:
    return AgentBodyProtocol(
        "%s:root" % prefix,
        MappingProxyType({
            name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
        }),
        MappingProxyType({
            name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES
        }),
        MappingProxyType({
            name: "%s:registry:%s" % (prefix, name)
            for name in REGISTRY_NAMES
        }),
    )


def _validate_registry(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    registry_name: str,
    member_role_name: str,
) -> tuple[str, ...]:
    root = protocol.registry(registry_name)
    if snapshot.cells[root].atom != b"":
        raise InvalidCell("agent-body registry drifted: %r" % root)
    members = read_relation(snapshot, root, budget=RELATION_BUDGET)
    expected_role = protocol.role(member_role_name)
    if any(member.role_id != expected_role for member in members):
        raise InvalidCell("agent-body registry contains an unexpected role")
    roots = tuple(member.participant_id for member in members)
    if len(roots) != len(set(roots)):
        raise InvalidCell("agent-body registry contains duplicate roots")
    return roots


def _validate_protocol(
    snapshot: Snapshot, protocol: AgentBodyProtocol
) -> None:
    if not protocol.root_id.endswith(":root"):
        raise InvalidCell("agent-body protocol identity is invalid")
    expected = _protocol_for_prefix(protocol.root_id[:-5])
    if protocol != expected:
        raise InvalidCell("agent-body protocol vocabulary mapping drifted")
    _ensure_roots(
        snapshot,
        (
            protocol.root_id,
            *protocol.roles.values(),
            *protocol.states.values(),
            *protocol.registries.values(),
        ),
        "agent-body protocol",
    )
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        if _text(snapshot, root, "agent-body protocol vocabulary") != name:
            raise InvalidCell("agent-body protocol vocabulary drifted")
    if snapshot.cells[protocol.root_id].atom != b"":
        raise InvalidCell("agent-body protocol vocabulary relation drifted")
    expected_members = tuple(
        (protocol.role("vocabulary-member"), root)
        for root in (
            *protocol.roles.values(),
            *protocol.states.values(),
            *protocol.registries.values(),
        )
    )
    actual_members = tuple(
        (member.role_id, member.participant_id)
        for member in read_relation(
            snapshot, protocol.root_id, budget=RELATION_BUDGET
        )
    )
    if actual_members != expected_members:
        raise InvalidCell("agent-body protocol vocabulary relation drifted")
    _validate_registry(snapshot, protocol, "body", "body-member")
    _validate_registry(snapshot, protocol, "session", "session-member")


def _validate_authorization_protocol(
    snapshot: Snapshot, protocol: AuthorizationProtocol
) -> None:
    if not protocol.root_id.endswith(":root"):
        raise InvalidCell("authorization protocol identity is invalid")
    prefix = protocol.root_id[:-5]
    expected_roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in AUTHORIZATION_ROLE_NAMES
    }
    expected_actions = {
        name: "%s:action:%s" % (prefix, name)
        for name in AUTHORIZATION_ACTION_NAMES
    }
    expected_effects = {
        name: "%s:effect:%s" % (prefix, name)
        for name in ("permit", "forbid")
    }
    expected_states = {
        name: "%s:state:%s" % (prefix, name)
        for name in ("draft", "released", "revoked")
    }
    if (
        dict(protocol.roles) != expected_roles
        or dict(protocol.actions) != expected_actions
        or dict(protocol.effects) != expected_effects
        or dict(protocol.states) != expected_states
    ):
        raise InvalidCell("authorization protocol vocabulary mapping drifted")
    roots = (
        *protocol.roles.values(),
        *protocol.actions.values(),
        *protocol.effects.values(),
        *protocol.states.values(),
    )
    _ensure_roots(snapshot, (protocol.root_id, *roots), "authorization protocol")
    for mapping in (
        protocol.roles,
        protocol.actions,
        protocol.effects,
        protocol.states,
    ):
        for name, root in mapping.items():
            if _text(snapshot, root, "authorization vocabulary") != name:
                raise InvalidCell("authorization protocol vocabulary drifted")
    expected_members = tuple(
        (protocol.role("vocabulary-member"), root) for root in roots
    )
    actual_members = tuple(
        (member.role_id, member.participant_id)
        for member in read_relation(
            snapshot, protocol.root_id, budget=RELATION_BUDGET
        )
    )
    if snapshot.cells[protocol.root_id].atom != b"" or actual_members != expected_members:
        raise InvalidCell("authorization protocol vocabulary relation drifted")


def bootstrap_agent_body_protocol(
    store: CellStore,
    *,
    prefix: str = "agent-body-protocol",
) -> AgentBodyProtocol:
    protocol = _protocol_for_prefix(prefix)
    batch = CellBatch(store)
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        batch.add(_terminal(root, name))
    for root in protocol.registries.values():
        batch.relation((), relation_id=root)
    batch.relation(
        (
            (protocol.role("vocabulary-member"), root)
            for root in (
                *protocol.roles.values(),
                *protocol.states.values(),
                *protocol.registries.values(),
            )
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    _validate_protocol(store.snapshot(), protocol)
    return protocol


def open_agent_body_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "agent-body-protocol",
) -> AgentBodyProtocol:
    protocol = _protocol_for_prefix(prefix)
    _validate_protocol(snapshot, protocol)
    return protocol


def list_agent_body_roots(
    snapshot: Snapshot, protocol: AgentBodyProtocol
) -> tuple[str, ...]:
    _validate_protocol(snapshot, protocol)
    return _validate_registry(snapshot, protocol, "body", "body-member")


def list_agent_session_roots(
    snapshot: Snapshot, protocol: AgentBodyProtocol
) -> tuple[str, ...]:
    _validate_protocol(snapshot, protocol)
    return _validate_registry(snapshot, protocol, "session", "session-member")


def _binding_root(protocol: AgentBodyProtocol, root: str | None) -> str:
    return protocol.state("unbound") if root is None else root


def _projected_binding(protocol: AgentBodyProtocol, root: str) -> str | None:
    return None if root == protocol.state("unbound") else root


def _require_request_binding(
    request: AuthorizationRequest,
    *,
    object_root: str,
    action_roots: tuple[str, ...],
    lineage_roots: tuple[str, ...],
    interface_root: str | None | object = _ANY,
    audience_root: str | None | object = _ANY,
    classification_root: str | None | object = _ANY,
    lifecycle_root: str | None | object = _ANY,
    purpose_root: str | None | object = _ANY,
    operational_root: str | None | object = _ANY,
    label: str,
) -> None:
    if request.object_root != object_root:
        raise InvalidCell("%s object does not match" % label)
    if request.action_root not in action_roots:
        raise InvalidCell("%s action is not declared by the agent body" % label)
    if tuple(request.resource_lineage_roots) != lineage_roots:
        raise InvalidCell("%s lineage does not match" % label)
    for actual, expected, field in (
        (request.interface_root, interface_root, "interface"),
        (request.audience_root, audience_root, "audience"),
        (request.classification_root, classification_root, "classification"),
        (request.lifecycle_state_root, lifecycle_root, "lifecycle"),
        (request.purpose_root, purpose_root, "purpose"),
        (request.operational_state_root, operational_root, "operational state"),
    ):
        if expected is not _ANY and actual != expected:
            raise InvalidCell("%s %s does not match" % (label, field))
    if request.now is not None:
        raise InvalidCell("%s cannot supply authorization time" % label)
    if request.invocation_count != 0:
        raise InvalidCell("%s cannot supply an invocation count" % label)


def _validate_body_authority(
    snapshot: Snapshot,
    authorization: AuthorizationProtocol,
    body: AgentBodyProjection,
) -> None:
    _validate_authorization_protocol(snapshot, authorization)
    actions = body.authority_action_roots
    rules = body.authority_rule_roots
    if not actions or len(actions) != len(set(actions)):
        raise InvalidCell("agent body requires unique authority actions")
    if any(root not in authorization.actions.values() for root in actions):
        raise InvalidCell("agent body action is outside authorization vocabulary")
    if not rules or len(rules) != len(set(rules)):
        raise InvalidCell("agent body requires unique authority rules")
    policy = verify_authorization_policy(
        snapshot, authorization, body.authority_policy_root
    )
    policy_rules = frozenset(policy.rule_roots)
    for root in rules:
        if root not in policy_rules:
            raise InvalidCell("agent body declares a rule outside its policy")
        rule = read_authorization_rule(snapshot, authorization, root)
        if rule.action_root not in actions:
            raise InvalidCell("agent body rule action is not declared")
        if rule.max_invocations_root is not None:
            raise InvalidCell(
                "agent body cannot use rules needing an untracked invocation counter"
            )
def _validate_decision(
    snapshot: Snapshot,
    authorization: AuthorizationProtocol,
    body: AgentBodyProjection,
    decision: AuthorizationDecision,
    *,
    expected_object_root: str,
    expected_rule_object_root: str,
    expected_interface_root: str | None | object = _ANY,
    expected_purpose_root: str | None | object = _ANY,
    expected_classification_root: str | None | object = _ANY,
    expected_audience_root: str | None | object = _ANY,
    expected_lifecycle_root: str | None | object = _ANY,
    expected_operational_root: str | None | object = _ANY,
    expected_subject_relation_root: str | None | object = _ANY,
    label: str,
) -> None:
    if not decision.allowed:
        raise AuthorizationDenied("%s denied: %s" % (label, decision.reason))
    if decision.subject_root != body.identity_root:
        raise AuthorizationDenied("%s authenticated subject does not match body" % label)
    if decision.policy_root != body.authority_policy_root:
        raise AuthorizationDenied("%s policy does not match body" % label)
    if decision.object_root != expected_object_root:
        raise AuthorizationDenied("%s decision object does not match" % label)
    if decision.action_root not in body.authority_action_roots:
        raise AuthorizationDenied("%s action is not declared by the body" % label)
    rules = _unique_roots(decision.determining_rule_roots, label + " rules")
    if not rules or not frozenset(rules).issubset(body.authority_rule_roots):
        raise AuthorizationDenied("%s rules are not declared by the body" % label)
    if decision.reason != "explicit-permit":
        raise AuthorizationDenied("%s is not an explicit permit" % label)
    for root in rules:
        rule = read_authorization_rule(snapshot, authorization, root)
        if (
            rule.effect_root != authorization.effects["permit"]
            or rule.action_root != decision.action_root
            or rule.object_root != expected_rule_object_root
        ):
            raise AuthorizationDenied("%s determining rule is not exact" % label)
        for actual, expected, field in (
            (rule.interface_root, expected_interface_root, "interface"),
            (rule.purpose_root, expected_purpose_root, "purpose"),
            (
                rule.classification_root,
                expected_classification_root,
                "classification",
            ),
            (rule.audience_root, expected_audience_root, "audience"),
            (
                rule.lifecycle_state_root,
                expected_lifecycle_root,
                "lifecycle",
            ),
            (
                rule.operational_state_root,
                expected_operational_root,
                "operational state",
            ),
            (
                rule.subject_relation_root,
                expected_subject_relation_root,
                "subject relation",
            ),
        ):
            if expected is not _ANY and actual != expected:
                raise AuthorizationDenied(
                    "%s determining rule %s is not exact" % (label, field)
                )


def _evaluate_agent_requests(
    snapshot: Snapshot,
    authorization: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    requests: Iterable[AuthorizationRequest],
    resolver_state: object | None,
) -> AuthorizationEvaluation:
    requested = tuple(requests)
    if resolver_state is not None:
        evaluated_at = getattr(resolver_state, "evaluated_at", None)
        if not isinstance(evaluated_at, (int, float)):
            raise AuthorizationDenied(
                "agent authority snapshot has no trusted evaluation time"
            )
        requested = tuple(
            replace(request, now=float(evaluated_at))
            for request in requested
        )
    return evaluate_node_requests(
        snapshot,
        authorization,
        policy_root,
        authentication_broker,
        authentication_context,
        requested,
        resolver_state=resolver_state,
    )


def _compose_authorization_receipt(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    evaluation: AuthorizationEvaluation,
    index: int,
    *,
    receipt_id: str,
) -> tuple[Cell, ...]:
    if evaluation.revision != snapshot.revision:
        raise InvalidCell("authorization receipt revision is stale")
    if (
        index < 0
        or index >= len(evaluation.decisions)
        or len(evaluation.decisions) != len(evaluation.identities)
    ):
        raise InvalidCell("authorization receipt evaluation is incomplete")
    decision = evaluation.decisions[index]
    identity = evaluation.identities[index]
    if decision.subject_root != identity.subject_root:
        raise AuthorizationDenied("authorization receipt subjects disagree")
    if identity.expires_at <= evaluation.evaluated_at:
        raise AuthorizationDenied("authorization receipt context was expired")
    policy = verify_authorization_policy(
        snapshot, authorization, evaluation.policy_root
    )
    if decision.policy_root != policy.root_id:
        raise AuthorizationDenied("authorization receipt policy disagrees")
    policy_digest = snapshot.cells[policy.digest_root].atom.decode("ascii")
    revision_root = receipt_id + ":revision"
    evaluated_root = receipt_id + ":evaluated-at"
    expires_root = receipt_id + ":context-expires-at"
    digest_root = receipt_id + ":policy-digest"
    reason_root = receipt_id + ":reason"
    resolver = evaluation.resolver_evidence
    resolver_revision_root = receipt_id + ":resolver-revision"
    resolver_evaluated_root = receipt_id + ":resolver-evaluated-at"
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-subject"), identity.subject_root),
            *(
                (protocol.role("receipt-principal"), root)
                for root in identity.principal_roots
            ),
            (
                protocol.role("receipt-tenant"),
                _binding_root(protocol, identity.tenant_root),
            ),
            (protocol.role("receipt-assurance"), identity.assurance_root),
            (protocol.role("receipt-policy"), decision.policy_root),
            (protocol.role("receipt-policy-digest"), digest_root),
            (protocol.role("receipt-action"), decision.action_root),
            (protocol.role("receipt-object"), decision.object_root),
            *(
                (protocol.role("receipt-rule"), root)
                for root in decision.determining_rule_roots
            ),
            (protocol.role("receipt-reason"), reason_root),
            (protocol.role("receipt-revision"), revision_root),
            (protocol.role("receipt-evaluated-at"), evaluated_root),
            (protocol.role("receipt-context-expires-at"), expires_root),
            *(() if resolver is None else (
                (
                    protocol.role("receipt-resolver-protocol"),
                    resolver.protocol_root,
                ),
                (
                    protocol.role("receipt-resolver-revision"),
                    resolver_revision_root,
                ),
                (
                    protocol.role("receipt-resolver-evaluated-at"),
                    resolver_evaluated_root,
                ),
                *(
                    (
                        protocol.role("receipt-resolver-evidence"),
                        root,
                    )
                    for root in resolver.relationship_roots
                ),
            )),
        ),
        relation_id=receipt_id,
    )
    return (
        _terminal(revision_root, evaluation.revision),
        _terminal(evaluated_root, repr(evaluation.evaluated_at)),
        _terminal(expires_root, repr(identity.expires_at)),
        _terminal(digest_root, policy_digest),
        _terminal(reason_root, decision.reason),
        *(() if resolver is None else (
            _terminal(resolver_revision_root, resolver.revision),
            _terminal(
                resolver_evaluated_root,
                repr(resolver.evaluated_at),
            ),
        )),
        *relation.cells,
    )


def _read_authorization_receipt(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    receipt_root: str,
    *,
    work_budget: _ReadWorkBudget | None = None,
) -> AuthorizationReceiptProjection:
    members = read_relation(
        snapshot,
        receipt_root,
        budget=MAX_RECEIPT_RELATION_MEMBERS + 1,
    )
    if len(members) > MAX_RECEIPT_RELATION_MEMBERS:
        raise InvalidCell("authorization receipt exceeds its member limit")
    if work_budget is not None:
        work_budget.consume(len(members), "authorization receipt")
    role_names = (
        "receipt-subject",
        "receipt-principal",
        "receipt-tenant",
        "receipt-assurance",
        "receipt-policy",
        "receipt-policy-digest",
        "receipt-action",
        "receipt-object",
        "receipt-rule",
        "receipt-reason",
        "receipt-revision",
        "receipt-evaluated-at",
        "receipt-context-expires-at",
        "receipt-resolver-protocol",
        "receipt-resolver-revision",
        "receipt-resolver-evaluated-at",
        "receipt-resolver-evidence",
    )
    _closed_roles(
        members,
        (protocol.role(name) for name in role_names),
        "authorization receipt",
    )
    expected_terminals = {
        "receipt-policy-digest": receipt_root + ":policy-digest",
        "receipt-reason": receipt_root + ":reason",
        "receipt-revision": receipt_root + ":revision",
        "receipt-evaluated-at": receipt_root + ":evaluated-at",
        "receipt-context-expires-at": receipt_root + ":context-expires-at",
    }
    terminal_roots = {
        name: _one(members, protocol.role(name), name).participant_id
        for name in expected_terminals
    }
    if terminal_roots != expected_terminals:
        raise InvalidCell("authorization receipt terminal ownership drifted")
    principals = _unique_roots(
        _participants(members, protocol.role("receipt-principal")),
        "authorization receipt principals",
        limit=MAX_RECEIPT_PRINCIPALS,
    )
    if not principals:
        raise InvalidCell("authorization receipt has no principal")
    rules = _unique_roots(
        _participants(members, protocol.role("receipt-rule")),
        "authorization receipt rules",
        limit=MAX_BODY_RULES,
    )
    if not rules:
        raise InvalidCell("authorization receipt has no determining rule")
    try:
        evaluated_at = float(
            _text(snapshot, terminal_roots["receipt-evaluated-at"], "evaluated at")
        )
        expires_at = float(
            _text(
                snapshot,
                terminal_roots["receipt-context-expires-at"],
                "context expiry",
            )
        )
    except ValueError as exc:
        raise InvalidCell("authorization receipt time is invalid") from exc
    revision = _integer(
        snapshot, terminal_roots["receipt-revision"], "receipt revision"
    )
    if revision < 0 or revision > snapshot.revision or expires_at <= evaluated_at:
        raise InvalidCell("authorization receipt time or revision is invalid")
    policy_root = _one(
        members, protocol.role("receipt-policy"), "receipt policy"
    ).participant_id
    policy = verify_authorization_policy(snapshot, authorization, policy_root)
    policy_digest = _text(
        snapshot, terminal_roots["receipt-policy-digest"], "policy digest"
    )
    if snapshot.cells[policy.digest_root].atom.decode("ascii") != policy_digest:
        raise InvalidCell("authorization receipt policy digest drifted")
    resolver_protocol_member = _optional(
        members,
        protocol.role("receipt-resolver-protocol"),
        "receipt resolver protocol",
    )
    resolver_revision_member = _optional(
        members,
        protocol.role("receipt-resolver-revision"),
        "receipt resolver revision",
    )
    resolver_evaluated_member = _optional(
        members,
        protocol.role("receipt-resolver-evaluated-at"),
        "receipt resolver evaluated at",
    )
    resolver_evidence_roots = _unique_roots(
        _participants(members, protocol.role("receipt-resolver-evidence")),
        "receipt resolver evidence",
        limit=MAX_RECEIPT_RELATIONSHIPS,
    )
    resolver_fields = (
        resolver_protocol_member,
        resolver_revision_member,
        resolver_evaluated_member,
    )
    if any(field is not None for field in resolver_fields) and not all(
        field is not None for field in resolver_fields
    ):
        raise InvalidCell("authorization resolver receipt is incomplete")
    resolver_protocol_root = None
    resolver_revision = None
    resolver_evaluated_at = None
    if resolver_protocol_member is not None:
        resolver_protocol_root = resolver_protocol_member.participant_id
        expected_resolver_revision = receipt_root + ":resolver-revision"
        expected_resolver_evaluated = receipt_root + ":resolver-evaluated-at"
        if (
            resolver_revision_member.participant_id
            != expected_resolver_revision
            or resolver_evaluated_member.participant_id
            != expected_resolver_evaluated
        ):
            raise InvalidCell(
                "authorization resolver receipt ownership drifted"
            )
        resolver_revision = _integer(
            snapshot,
            expected_resolver_revision,
            "resolver revision",
        )
        try:
            resolver_evaluated_at = float(_text(
                snapshot,
                expected_resolver_evaluated,
                "resolver evaluated at",
            ))
        except ValueError as exc:
            raise InvalidCell(
                "authorization resolver receipt time is invalid"
            ) from exc
        if (
            resolver_revision != revision
            or resolver_evaluated_at != evaluated_at
        ):
            raise InvalidCell(
                "authorization resolver receipt revision or time is invalid"
            )
        _ensure_roots(
            snapshot,
            (resolver_protocol_root, *resolver_evidence_roots),
            "authorization resolver receipt",
        )
    elif resolver_evidence_roots:
        raise InvalidCell(
            "authorization resolver evidence lacks its verified snapshot"
        )
    assurance_root = _one(
        members, protocol.role("receipt-assurance"), "receipt assurance"
    ).participant_id
    tenant_root = _projected_binding(
        protocol,
        _one(members, protocol.role("receipt-tenant"), "receipt tenant").participant_id,
    )
    for rule_root in rules:
        rule = read_authorization_rule(snapshot, authorization, rule_root)
        if rule.principal_root not in principals:
            raise InvalidCell("authorization receipt omitted rule principal")
        if rule.tenant_root is not None and rule.tenant_root != tenant_root:
            raise InvalidCell("authorization receipt tenant drifted")
        if rule.assurance_root is not None and rule.assurance_root != assurance_root:
            raise InvalidCell("authorization receipt assurance drifted")
    return AuthorizationReceiptProjection(
        receipt_root,
        revision,
        evaluated_at,
        expires_at,
        _one(members, protocol.role("receipt-subject"), "receipt subject").participant_id,
        principals,
        tenant_root,
        assurance_root,
        policy_root,
        policy_digest,
        _one(members, protocol.role("receipt-action"), "receipt action").participant_id,
        _one(members, protocol.role("receipt-object"), "receipt object").participant_id,
        rules,
        _text(snapshot, terminal_roots["receipt-reason"], "receipt reason"),
        resolver_protocol_root,
        resolver_revision,
        resolver_evaluated_at,
        resolver_evidence_roots,
    )


def _verify_authorization_receipt_integrity(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    receipt_root: str,
) -> AuthorizationReceiptProjection:
    """Verify one receipt against its released policy and determining rules."""
    receipt = _read_authorization_receipt(
        snapshot, protocol, authorization, receipt_root
    )
    if receipt.reason != "explicit-permit":
        raise InvalidCell(
            "authorization evidence receipt is not an explicit permit"
        )
    policy = verify_authorization_policy(
        snapshot, authorization, receipt.policy_root
    )
    if not set(receipt.rule_roots).issubset(policy.rule_roots):
        raise InvalidCell("authorization receipt rules left its policy")
    for rule_root in receipt.rule_roots:
        rule = read_authorization_rule(snapshot, authorization, rule_root)
        if (
            rule.effect_root != authorization.effects["permit"]
            or rule.action_root != receipt.action_root
        ):
            raise InvalidCell(
                "authorization receipt action differs from its determining rule"
            )
    return receipt


def _read_agent_body(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    body_root: str,
    *,
    validate_protocol: bool,
    model_binding_verifier: ModelBindingVerifier | None = None,
) -> AgentBodyProjection:
    registered = (
        list_agent_body_roots(snapshot, protocol)
        if validate_protocol
        else _validate_registry(snapshot, protocol, "body", "body-member")
    )
    if registered.count(body_root) != 1:
        raise InvalidCell("agent body is not registered exactly once")
    members = read_relation(snapshot, body_root, budget=RELATION_BUDGET)
    role_names = (
        "body-identity",
        "body-authority-policy",
        "body-authority-action",
        "body-authority-rule",
        "body-lifecycle",
        "body-state",
        "body-visibility",
        "body-model-binding",
        "body-creation-action",
        "body-creation-rule",
        "body-creation-reason",
        "body-creation-receipt",
    )
    _closed_roles(
        members,
        (protocol.role(name) for name in role_names),
        "agent body",
    )
    reason_root = _one(
        members, protocol.role("body-creation-reason"), "body creation reason"
    ).participant_id
    if reason_root != body_root + ":creation-reason":
        raise InvalidCell("agent body creation evidence is not canonically owned")
    state_root = _one(
        members, protocol.role("body-state"), "body state"
    ).participant_id
    if state_root not in (protocol.state("active"), protocol.state("closed")):
        raise InvalidCell("agent body state is outside the protocol")
    binding = _one(
        members, protocol.role("body-model-binding"), "body model binding"
    ).participant_id
    if binding != protocol.state("unbound"):
        if model_binding_verifier is None:
            raise InvalidCell(
                "agent model binding requires an unavailable released protocol"
            )
        model_binding_verifier(snapshot, binding, body_root)
    receipt_root = _one(
        members,
        protocol.role("body-creation-receipt"),
        "body creation receipt",
    ).participant_id
    body = AgentBodyProjection(
        body_root,
        _one(members, protocol.role("body-identity"), "body identity").participant_id,
        _one(
            members,
            protocol.role("body-authority-policy"),
            "body authority policy",
        ).participant_id,
        _participants(members, protocol.role("body-authority-action")),
        _participants(members, protocol.role("body-authority-rule")),
        _one(members, protocol.role("body-lifecycle"), "body lifecycle").participant_id,
        state_root,
        _one(members, protocol.role("body-visibility"), "body visibility").participant_id,
        _projected_binding(protocol, binding),
        _one(
            members,
            protocol.role("body-creation-action"),
            "body creation action",
        ).participant_id,
        _participants(members, protocol.role("body-creation-rule")),
        _text(snapshot, reason_root, "body creation reason"),
        receipt_root,
    )
    _validate_body_authority(snapshot, authorization, body)
    creation = AuthorizationDecision(
        True,
        body.authority_policy_root,
        body.identity_root,
        body.creation_action_root,
        body.identity_root,
        body.creation_rule_roots,
        body.creation_reason,
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        creation,
        expected_object_root=body.identity_root,
        expected_rule_object_root=body.identity_root,
        expected_interface_root=None,
        expected_purpose_root=None,
        expected_classification_root=None,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=protocol.state("active"),
        expected_subject_relation_root=None,
        label="agent body creation",
    )
    receipt = _read_authorization_receipt(
        snapshot, protocol, authorization, receipt_root
    )
    if (
        receipt.subject_root != body.identity_root
        or receipt.policy_root != body.authority_policy_root
        or receipt.action_root != body.creation_action_root
        or receipt.object_root != body.identity_root
        or receipt.rule_roots != body.creation_rule_roots
        or receipt.reason != body.creation_reason
    ):
        raise InvalidCell("agent body creation receipt drifted")
    return body


def read_agent_body(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    body_root: str,
    *,
    model_binding_verifier: ModelBindingVerifier | None = None,
) -> AgentBodyProjection:
    return _read_agent_body(
        snapshot,
        protocol,
        authorization,
        body_root,
        validate_protocol=True,
        model_binding_verifier=model_binding_verifier,
    )


def compose_agent_body(
    store: CellStore,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    creation_request: AuthorizationRequest,
    *,
    body_id: str,
    identity_root: str,
    authority_policy_root: str,
    authority_action_roots: Iterable[str],
    authority_rule_roots: Iterable[str],
    lifecycle_root: str,
    state_root: str,
    visibility_root: str,
    model_binding_root: str | None = None,
    resolver_state: object | None = None,
    model_binding_verifier: ModelBindingVerifier | None = None,
) -> AgentBodyProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    _validate_authorization_protocol(snapshot, authorization)
    if body_id in snapshot.cells:
        raise InvalidCell("agent body root already exists: %r" % body_id)
    actions = _unique_roots(
        authority_action_roots,
        "agent body actions",
        limit=len(AUTHORIZATION_ACTION_NAMES),
    )
    rules = _unique_roots(
        authority_rule_roots,
        "agent body rules",
        limit=MAX_BODY_RULES,
    )
    if not actions or not rules:
        raise InvalidCell("agent body requires actions and rules")
    if state_root != protocol.state("active"):
        raise InvalidCell("a new agent body must be active")
    if model_binding_root is not None:
        if model_binding_verifier is None:
            raise InvalidCell(
                "agent model binding requires an unavailable released protocol"
            )
        model_binding_verifier(snapshot, model_binding_root, body_id)
    binding = _binding_root(protocol, model_binding_root)
    _ensure_roots(
        snapshot,
        (
            identity_root,
            authority_policy_root,
            *actions,
            *rules,
            lifecycle_root,
            state_root,
            visibility_root,
            binding,
        ),
        "agent body",
    )
    provisional = AgentBodyProjection(
        body_id,
        identity_root,
        authority_policy_root,
        actions,
        rules,
        lifecycle_root,
        state_root,
        visibility_root,
        model_binding_root,
        creation_request.action_root,
        (),
        "",
        "",
    )
    _validate_body_authority(snapshot, authorization, provisional)
    _require_request_binding(
        creation_request,
        object_root=identity_root,
        action_roots=actions,
        lineage_roots=(),
        interface_root=None,
        audience_root=visibility_root,
        classification_root=None,
        lifecycle_root=lifecycle_root,
        purpose_root=None,
        operational_root=protocol.state("active"),
        label="agent body creation request",
    )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        authority_policy_root,
        authentication_broker,
        authentication_context,
        (creation_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    _validate_decision(
        snapshot,
        authorization,
        provisional,
        decision,
        expected_object_root=identity_root,
        expected_rule_object_root=identity_root,
        expected_interface_root=None,
        expected_purpose_root=None,
        expected_classification_root=None,
        expected_audience_root=visibility_root,
        expected_lifecycle_root=lifecycle_root,
        expected_operational_root=protocol.state("active"),
        expected_subject_relation_root=None,
        label="agent body creation",
    )
    reason_root = body_id + ":creation-reason"
    receipt_root = body_id + ":creation-receipt"
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        0,
        receipt_id=receipt_root,
    )
    relation = compose_relation_cells(
        (
            (protocol.role("body-identity"), identity_root),
            (protocol.role("body-authority-policy"), authority_policy_root),
            *((protocol.role("body-authority-action"), root) for root in actions),
            *((protocol.role("body-authority-rule"), root) for root in rules),
            (protocol.role("body-lifecycle"), lifecycle_root),
            (protocol.role("body-state"), state_root),
            (protocol.role("body-visibility"), visibility_root),
            (protocol.role("body-model-binding"), binding),
            (protocol.role("body-creation-action"), decision.action_root),
            *(
                (protocol.role("body-creation-rule"), root)
                for root in decision.determining_rule_roots
            ),
            (protocol.role("body-creation-reason"), reason_root),
            (protocol.role("body-creation-receipt"), receipt_root),
        ),
        relation_id=body_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("body"),
        protocol.role("body-member"),
        body_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(reason_root, decision.reason),
            *receipt_cells,
            *relation.cells,
            *append.create,
        ),
        "agent body",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=append.replace,
    )
    return read_agent_body(
        store.snapshot(),
        protocol,
        authorization,
        body_id,
        model_binding_verifier=model_binding_verifier,
    )


def _registry_participants(
    snapshot: Snapshot,
    registry_root: str,
    member_role: str,
    label: str,
    *,
    member_limit: int | None = None,
    work_budget: _ReadWorkBudget | None = None,
) -> tuple[str, ...]:
    if snapshot.cells[registry_root].atom != b"":
        raise InvalidCell("%s root atom drifted" % label)
    members = read_relation(
        snapshot,
        registry_root,
        budget=(
            RELATION_BUDGET
            if member_limit is None else member_limit + 1
        ),
    )
    if member_limit is not None and len(members) > member_limit:
        raise InvalidCell("%s exceeds its member limit" % label)
    if work_budget is not None:
        work_budget.consume(len(members), label)
    if any(member.role_id != member_role for member in members):
        raise InvalidCell("%s contains an unexpected role" % label)
    roots = tuple(member.participant_id for member in members)
    if len(roots) != len(set(roots)):
        raise InvalidCell("%s contains duplicate roots" % label)
    return roots


def _require_active(
    protocol: AgentBodyProtocol,
    body: AgentBodyProjection,
    session: AgentSessionProjection | None = None,
) -> None:
    if body.state_root != protocol.state("active"):
        raise PermissionError("agent body is not active")
    if session is not None and session.state_root != protocol.state("active"):
        raise PermissionError("agent session is not active")


def _session_decision(
    *,
    body: AgentBodyProjection,
    action_root: str,
    object_root: str,
    rule_roots: tuple[str, ...],
    reason: str,
) -> AuthorizationDecision:
    return AuthorizationDecision(
        True,
        body.authority_policy_root,
        body.identity_root,
        action_root,
        object_root,
        rule_roots,
        reason,
    )


def _project_context_entry(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    entry_root: str,
    *,
    work_budget: _ReadWorkBudget | None = None,
) -> ContextEntryProjection:
    members = read_relation(
        snapshot,
        entry_root,
        budget=MAX_CONTEXT_RELATION_MEMBERS + 1,
    )
    if len(members) > MAX_CONTEXT_RELATION_MEMBERS:
        raise InvalidCell("agent context entry exceeds its member limit")
    if work_budget is not None:
        work_budget.consume(len(members), "agent context entry")
    role_names = (
        "context-session",
        "context-subject",
        "context-root",
        "context-provenance",
        "context-trust",
        "context-sensitivity",
        "context-audience",
        "context-lifecycle",
        "context-purpose",
        "context-interface",
        "context-observed-revision",
        "context-action",
        "context-policy",
        "context-rule",
        "context-authorization-reason",
        "context-authorization-receipt",
        "registry-interface",
        "registry-action",
        "registry-policy",
        "registry-rule",
        "registry-authorization-reason",
        "registry-authorization-receipt",
        "context-idempotency",
        "context-semantic-digest",
        "context-sequence",
    )
    _closed_roles(
        members,
        (protocol.role(name) for name in role_names),
        "agent context entry",
    )
    roots = {
        name: _one(members, protocol.role(name), name).participant_id
        for name in (
            "context-session",
            "context-subject",
            "context-root",
            "context-provenance",
            "context-trust",
            "context-sensitivity",
            "context-audience",
            "context-lifecycle",
            "context-purpose",
            "context-interface",
            "context-observed-revision",
            "context-action",
            "context-policy",
            "context-authorization-reason",
            "context-authorization-receipt",
            "registry-interface",
            "registry-action",
            "registry-policy",
            "registry-authorization-reason",
            "registry-authorization-receipt",
            "context-idempotency",
            "context-semantic-digest",
            "context-sequence",
        )
    }
    canonical = {
        "context-observed-revision": entry_root + ":observed-revision",
        "context-authorization-reason": entry_root + ":context-reason",
        "registry-authorization-reason": entry_root + ":registry-reason",
        "context-idempotency": entry_root + ":idempotency-key",
        "context-semantic-digest": entry_root + ":semantic-digest",
        "context-sequence": entry_root + ":sequence",
    }
    if any(roots[name] != root for name, root in canonical.items()):
        raise InvalidCell("agent context terminal ownership drifted")
    context_rules = _unique_roots(
        _participants(members, protocol.role("context-rule")),
        "context decision rules",
    )
    registry_rules = _unique_roots(
        _participants(members, protocol.role("registry-rule")),
        "registry decision rules",
    )
    if not context_rules or not registry_rules:
        raise InvalidCell("agent context requires two determining rule sets")
    observed = _integer(
        snapshot, roots["context-observed-revision"], "context observed revision"
    )
    sequence = _integer(snapshot, roots["context-sequence"], "context sequence")
    if observed < 0 or observed > snapshot.revision or sequence < 1:
        raise InvalidCell("agent context revision or sequence is invalid")
    return ContextEntryProjection(
        entry_root,
        roots["context-session"],
        roots["context-subject"],
        roots["context-root"],
        roots["context-provenance"],
        roots["context-trust"],
        roots["context-sensitivity"],
        roots["context-audience"],
        roots["context-lifecycle"],
        _projected_binding(protocol, roots["context-purpose"]),
        _projected_binding(protocol, roots["context-interface"]),
        _projected_binding(protocol, roots["registry-interface"]),
        observed,
        roots["context-action"],
        roots["context-policy"],
        context_rules,
        _text(
            snapshot,
            roots["context-authorization-reason"],
            "context authorization reason",
        ),
        roots["context-authorization-receipt"],
        roots["registry-action"],
        roots["registry-policy"],
        registry_rules,
        _text(
            snapshot,
            roots["registry-authorization-reason"],
            "registry authorization reason",
        ),
        roots["registry-authorization-receipt"],
        _text(snapshot, roots["context-idempotency"], "context idempotency key"),
        _text(
            snapshot,
            roots["context-semantic-digest"],
            "context semantic digest",
        ),
        sequence,
    )


def _context_payload(
    entry: ContextEntryProjection,
    session: AgentSessionProjection,
    protocol: AgentBodyProtocol,
) -> dict[str, object]:
    return {
        "session": entry.session_root,
        "subject": entry.subject_root,
        "context": entry.context_root,
        "registry": session.context_registry_root,
        "scope": session.scope_root,
        "provenance": entry.provenance_root,
        "trust": entry.trust_root,
        "sensitivity": entry.sensitivity_root,
        "audience": entry.audience_root,
        "lifecycle": entry.lifecycle_root,
        "purpose": entry.purpose_root,
        "context_interface": entry.context_interface_root,
        "registry_interface": entry.registry_interface_root,
        "operational": protocol.state("active"),
        "observed_revision": entry.observed_revision,
        "sequence": entry.sequence,
        "context_decision": (
            entry.context_policy_root,
            entry.subject_root,
            entry.context_action_root,
            entry.context_root,
            entry.context_rule_roots,
            entry.context_authorization_reason,
        ),
        "registry_decision": (
            entry.registry_policy_root,
            entry.subject_root,
            entry.registry_action_root,
            session.context_registry_root,
            entry.registry_rule_roots,
            entry.registry_authorization_reason,
        ),
        "idempotency_key": entry.idempotency_key,
    }


def _context_digest(
    entry: ContextEntryProjection,
    session: AgentSessionProjection,
    protocol: AgentBodyProtocol,
) -> str:
    encoded = json.dumps(
        _context_payload(entry, session, protocol),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _context_replay_payload(
    entry: ContextEntryProjection,
    session: AgentSessionProjection,
    protocol: AgentBodyProtocol,
) -> dict[str, object]:
    payload = _context_payload(entry, session, protocol)
    payload.pop("observed_revision")
    payload.pop("sequence")
    return payload


def _context_identity(session_root: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(
        (session_root + "\x00" + idempotency_key).encode("utf-8")
    ).hexdigest()
    return "agent-context:" + digest


def _read_agent_session(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    session_root: str,
    *,
    validate_protocol: bool,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> AgentSessionProjection:
    work_budget = _ReadWorkBudget(MAX_SESSION_READ_WORK)
    registered = (
        list_agent_session_roots(snapshot, protocol)
        if validate_protocol
        else _validate_registry(snapshot, protocol, "session", "session-member")
    )
    if registered.count(session_root) != 1:
        raise InvalidCell("agent session is not registered exactly once")
    members = read_relation(snapshot, session_root, budget=RELATION_BUDGET)
    if len(members) > 1_024:
        raise InvalidCell("agent session exceeds its member limit")
    work_budget.consume(len(members), "agent session")
    role_names = (
        "session-body",
        "session-subject",
        "session-owner-role",
        "session-view-session",
        "session-scope",
        "session-focus",
        "session-assignment",
        "session-model-binding",
        "session-context-registry",
        "session-proposal-registry",
        "session-context-cursor",
        "session-state",
        "session-close-reason",
        "session-view-action",
        "session-view-policy",
        "session-view-rule",
        "session-view-reason",
        "session-view-receipt",
        "session-scope-action",
        "session-scope-policy",
        "session-scope-rule",
        "session-scope-reason",
        "session-scope-receipt",
        "session-close-action",
        "session-close-policy",
        "session-close-rule",
        "session-close-authorization-reason",
        "session-close-receipt",
    )
    owner_role_root = _one(
        members,
        protocol.role("session-owner-role"),
        "session owner role",
    ).participant_id
    _closed_roles(
        members,
        (*tuple(protocol.role(name) for name in role_names), owner_role_root),
        "agent session",
    )
    body_root = _one(
        members, protocol.role("session-body"), "session body"
    ).participant_id
    body = _read_agent_body(
        snapshot,
        protocol,
        authorization,
        body_root,
        validate_protocol=False,
        model_binding_verifier=model_binding_verifier,
    )
    subject = _one(
        members, protocol.role("session-subject"), "session subject"
    ).participant_id
    if subject != body.identity_root:
        raise InvalidCell("agent session subject drifted from body identity")
    owner = _one(members, owner_role_root, "session owner").participant_id
    if owner != subject:
        raise InvalidCell("agent session owner relation drifted from its subject")
    context_registry = _one(
        members,
        protocol.role("session-context-registry"),
        "session context registry",
    ).participant_id
    proposal_registry = _one(
        members,
        protocol.role("session-proposal-registry"),
        "session proposal registry",
    ).participant_id
    cursor_root = _one(
        members,
        protocol.role("session-context-cursor"),
        "session context cursor",
    ).participant_id
    if (
        context_registry != session_root + ":context-registry"
        or proposal_registry != session_root + ":proposal-registry"
        or cursor_root != session_root + ":context-cursor"
    ):
        raise InvalidCell("agent session canonical ownership drifted")
    context_roots = _registry_participants(
        snapshot,
        context_registry,
        protocol.role("context-member"),
        "agent session context registry",
        member_limit=MAX_CONTEXT_ENTRIES,
        work_budget=work_budget,
    )
    proposal_roots = _registry_participants(
        snapshot,
        proposal_registry,
        protocol.role("proposal-member"),
        "agent session proposal registry",
        member_limit=MAX_CONTEXT_ENTRIES,
        work_budget=work_budget,
    )
    if len(context_roots) > MAX_CONTEXT_ENTRIES:
        raise InvalidCell("agent session exceeds its context entry limit")
    if len(proposal_roots) > MAX_CONTEXT_ENTRIES:
        raise InvalidCell("agent session exceeds its proposal entry limit")
    if proposal_roots:
        if proposal_verifier is None:
            raise InvalidCell(
                "agent proposals require an unavailable verified protocol"
            )
        for proposal_root in proposal_roots:
            proposal_verifier(snapshot, proposal_root, session_root)
    cursor = _integer(snapshot, cursor_root, "agent session context cursor")
    if cursor != len(context_roots):
        raise InvalidCell("agent session context cursor drifted from its registry")
    state = _one(
        members, protocol.role("session-state"), "session state"
    )
    if state.participant_id not in (
        protocol.state("active"),
        protocol.state("closed"),
    ):
        raise InvalidCell("agent session state is outside the protocol")
    close_reason = _optional(
        members, protocol.role("session-close-reason"), "session close reason"
    )
    view_root = _one(
        members,
        protocol.role("session-view-session"),
        "session view-session",
    ).participant_id
    scope_root = _one(
        members, protocol.role("session-scope"), "session scope"
    ).participant_id
    view_policy = _one(
        members, protocol.role("session-view-policy"), "session view policy"
    ).participant_id
    scope_policy = _one(
        members, protocol.role("session-scope-policy"), "session scope policy"
    ).participant_id
    if view_policy != body.authority_policy_root or scope_policy != view_policy:
        raise InvalidCell("agent session policy drifted from its body")
    view_reason_root = _one(
        members, protocol.role("session-view-reason"), "session view reason"
    ).participant_id
    scope_reason_root = _one(
        members, protocol.role("session-scope-reason"), "session scope reason"
    ).participant_id
    if (
        view_reason_root != session_root + ":view-reason"
        or scope_reason_root != session_root + ":scope-reason"
    ):
        raise InvalidCell("agent session authority evidence is not canonically owned")
    view_action = _one(
        members, protocol.role("session-view-action"), "session view action"
    ).participant_id
    view_rules = _unique_roots(
        _participants(members, protocol.role("session-view-rule")),
        "session view rules",
    )
    view_reason = _text(snapshot, view_reason_root, "session view reason")
    scope_action = _one(
        members, protocol.role("session-scope-action"), "session scope action"
    ).participant_id
    scope_rules = _unique_roots(
        _participants(members, protocol.role("session-scope-rule")),
        "session scope rules",
    )
    scope_reason = _text(snapshot, scope_reason_root, "session scope reason")
    view_receipt_root = _one(
        members,
        protocol.role("session-view-receipt"),
        "session view receipt",
    ).participant_id
    scope_receipt_root = _one(
        members,
        protocol.role("session-scope-receipt"),
        "session scope receipt",
    ).participant_id
    _validate_decision(
        snapshot,
        authorization,
        body,
        _session_decision(
            body=body,
            action_root=view_action,
            object_root=view_root,
            rule_roots=view_rules,
            reason=view_reason,
        ),
        expected_object_root=view_root,
        expected_rule_object_root=view_root,
        expected_interface_root=None,
        expected_purpose_root=None,
        expected_classification_root=None,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=protocol.state("active"),
        expected_subject_relation_root=owner_role_root,
        label="agent session view",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        _session_decision(
            body=body,
            action_root=scope_action,
            object_root=scope_root,
            rule_roots=scope_rules,
            reason=scope_reason,
        ),
        expected_object_root=scope_root,
        expected_rule_object_root=scope_root,
        expected_interface_root=None,
        expected_purpose_root=None,
        expected_classification_root=None,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=protocol.state("active"),
        expected_subject_relation_root=owner_role_root,
        label="agent session scope",
    )
    for receipt_root, action_root, object_root, rules, reason, label in (
        (
            view_receipt_root,
            view_action,
            view_root,
            view_rules,
            view_reason,
            "view",
        ),
        (
            scope_receipt_root,
            scope_action,
            scope_root,
            scope_rules,
            scope_reason,
            "scope",
        ),
    ):
        receipt = _read_authorization_receipt(
            snapshot,
            protocol,
            authorization,
            receipt_root,
            work_budget=work_budget,
        )
        if (
            receipt.subject_root != subject
            or receipt.policy_root != body.authority_policy_root
            or receipt.action_root != action_root
            or receipt.object_root != object_root
            or receipt.rule_roots != rules
            or receipt.reason != reason
        ):
            raise InvalidCell("agent session %s receipt drifted" % label)
    close_action_member = _optional(
        members,
        protocol.role("session-close-action"),
        "session close action",
    )
    close_policy_member = _optional(
        members,
        protocol.role("session-close-policy"),
        "session close policy",
    )
    close_authorization_reason_member = _optional(
        members,
        protocol.role("session-close-authorization-reason"),
        "session close authorization reason",
    )
    close_receipt_member = _optional(
        members,
        protocol.role("session-close-receipt"),
        "session close receipt",
    )
    close_rules = _unique_roots(
        _participants(members, protocol.role("session-close-rule")),
        "session close rules",
    )
    close_action = None
    close_authorization_reason = None
    close_receipt_root = None
    if state.participant_id == protocol.state("closed"):
        if (
            close_action_member is None
            or close_policy_member is None
            or close_authorization_reason_member is None
            or close_receipt_member is None
            or not close_rules
        ):
            raise InvalidCell("closed agent session lacks authority evidence")
        if close_policy_member.participant_id != body.authority_policy_root:
            raise InvalidCell("agent session close policy drifted from its body")
        expected_reason_root = session_root + ":close-authorization-reason"
        if close_authorization_reason_member.participant_id != expected_reason_root:
            raise InvalidCell("agent session close evidence is not canonically owned")
        close_action = close_action_member.participant_id
        close_receipt_root = close_receipt_member.participant_id
        close_authorization_reason = _text(
            snapshot,
            expected_reason_root,
            "session close authorization reason",
        )
        _validate_decision(
            snapshot,
            authorization,
            body,
            _session_decision(
                body=body,
                action_root=close_action,
                object_root=session_root,
                rule_roots=close_rules,
                reason=close_authorization_reason,
            ),
            expected_object_root=session_root,
            expected_rule_object_root=scope_root,
            expected_interface_root=None,
            expected_purpose_root=None,
            expected_classification_root=None,
            expected_audience_root=body.visibility_root,
            expected_lifecycle_root=body.lifecycle_root,
            expected_operational_root=protocol.state("active"),
            expected_subject_relation_root=owner_role_root,
            label="agent session close",
        )
        close_receipt = _read_authorization_receipt(
            snapshot,
            protocol,
            authorization,
            close_receipt_root,
            work_budget=work_budget,
        )
        if (
            close_receipt.subject_root != subject
            or close_receipt.policy_root != body.authority_policy_root
            or close_receipt.action_root != close_action
            or close_receipt.object_root != session_root
            or close_receipt.rule_roots != close_rules
            or close_receipt.reason != close_authorization_reason
        ):
            raise InvalidCell("agent session close receipt drifted")
    elif (
        close_action_member is not None
        or close_policy_member is not None
        or close_authorization_reason_member is not None
        or close_receipt_member is not None
        or close_rules
        or close_reason is not None
    ):
        raise InvalidCell("active agent session contains close evidence")
    binding = _one(
        members, protocol.role("session-model-binding"), "session model binding"
    ).participant_id
    if binding != protocol.state("unbound"):
        if model_binding_verifier is None:
            raise InvalidCell(
                "agent session model binding requires an unavailable released protocol"
            )
        model_binding_verifier(snapshot, binding, body_root)
    focus_root = _one(
        members,
        protocol.role("session-focus"),
        "session focus",
    ).participant_id
    assignment_root = _one(
        members,
        protocol.role("session-assignment"),
        "session assignment",
    ).participant_id
    if (
        focus_root != protocol.state("unbound")
        or assignment_root != protocol.state("unbound")
    ):
        raise InvalidCell(
            "agent focus and assignment require unavailable released protocols"
        )
    session = AgentSessionProjection(
        session_root,
        body_root,
        subject,
        owner_role_root,
        view_root,
        scope_root,
        focus_root,
        assignment_root,
        _projected_binding(protocol, binding),
        context_registry,
        proposal_registry,
        cursor_root,
        cursor,
        state.participant_id,
        state.incidence_id,
        view_action,
        view_rules,
        view_reason,
        view_receipt_root,
        scope_action,
        scope_rules,
        scope_reason,
        scope_receipt_root,
        close_action,
        close_rules,
        close_authorization_reason,
        close_receipt_root,
        context_roots,
        proposal_roots,
        close_reason.participant_id if close_reason else None,
    )
    for expected_sequence, entry_root in enumerate(context_roots, 1):
        entry = _project_context_entry(
            snapshot,
            protocol,
            entry_root,
            work_budget=work_budget,
        )
        if (
            entry.session_root != session_root
            or entry.subject_root != subject
            or entry.sequence != expected_sequence
        ):
            raise InvalidCell("agent context entry drifted from its session")
        _validate_decision(
            snapshot,
            authorization,
            body,
            AuthorizationDecision(
                True,
                entry.context_policy_root,
                entry.subject_root,
                entry.context_action_root,
                entry.context_root,
                entry.context_rule_roots,
                entry.context_authorization_reason,
            ),
            expected_object_root=entry.context_root,
            expected_rule_object_root=entry.context_root,
            expected_interface_root=entry.context_interface_root,
            expected_purpose_root=entry.purpose_root,
            expected_classification_root=entry.sensitivity_root,
            expected_audience_root=entry.audience_root,
            expected_lifecycle_root=entry.lifecycle_root,
            expected_operational_root=protocol.state("active"),
            label="agent context selection",
        )
        _validate_decision(
            snapshot,
            authorization,
            body,
            AuthorizationDecision(
                True,
                entry.registry_policy_root,
                entry.subject_root,
                entry.registry_action_root,
                context_registry,
                entry.registry_rule_roots,
                entry.registry_authorization_reason,
            ),
            expected_object_root=context_registry,
            expected_rule_object_root=scope_root,
            expected_interface_root=entry.registry_interface_root,
            expected_purpose_root=entry.purpose_root,
            expected_classification_root=entry.sensitivity_root,
            expected_audience_root=entry.audience_root,
            expected_lifecycle_root=entry.lifecycle_root,
            expected_operational_root=protocol.state("active"),
            label="agent context registry mutation",
        )
        for receipt_root, action_root, object_root, rules, reason, label in (
            (
                entry.context_receipt_root,
                entry.context_action_root,
                entry.context_root,
                entry.context_rule_roots,
                entry.context_authorization_reason,
                "selection",
            ),
            (
                entry.registry_receipt_root,
                entry.registry_action_root,
                context_registry,
                entry.registry_rule_roots,
                entry.registry_authorization_reason,
                "registry",
            ),
        ):
            receipt = _read_authorization_receipt(
                snapshot,
                protocol,
                authorization,
                receipt_root,
                work_budget=work_budget,
            )
            if (
                receipt.subject_root != subject
                or receipt.policy_root != body.authority_policy_root
                or receipt.action_root != action_root
                or receipt.object_root != object_root
                or receipt.rule_roots != rules
                or receipt.reason != reason
            ):
                raise InvalidCell("agent context %s receipt drifted" % label)
        digest = _context_digest(entry, session, protocol)
        if (
            entry.semantic_digest != digest
            or entry.root_id
            != _context_identity(session_root, entry.idempotency_key)
        ):
            raise InvalidCell("agent context semantic identity drifted")
    return session


def read_agent_session(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    session_root: str,
    *,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> AgentSessionProjection:
    return _read_agent_session(
        snapshot,
        protocol,
        authorization,
        session_root,
        validate_protocol=True,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )


def begin_agent_session(
    store: CellStore,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    view_request: AuthorizationRequest,
    scope_request: AuthorizationRequest,
    *,
    session_id: str,
    body_root: str,
    subject_root: str,
    owner_role_root: str,
    view_session_root: str,
    scope_root: str,
    focus_root: str,
    assignment_root: str,
    resolver_state: object | None = None,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> AgentSessionProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    body = _read_agent_body(
        snapshot,
        protocol,
        authorization,
        body_root,
        validate_protocol=False,
        model_binding_verifier=model_binding_verifier,
    )
    _require_active(protocol, body)
    if subject_root != body.identity_root:
        raise PermissionError("agent session subject must equal body identity")
    if (
        focus_root != protocol.state("unbound")
        or assignment_root != protocol.state("unbound")
    ):
        raise InvalidCell(
            "agent focus and assignment require unavailable released protocols"
        )
    if session_id in snapshot.cells:
        raise InvalidCell("agent session root already exists: %r" % session_id)
    _ensure_roots(
        snapshot,
        (
            subject_root,
            owner_role_root,
            view_session_root,
            scope_root,
            focus_root,
            assignment_root,
        ),
        "agent session",
    )
    for request, object_root, label in (
        (view_request, view_session_root, "agent session view request"),
        (scope_request, scope_root, "agent session scope request"),
    ):
        _require_request_binding(
            request,
            object_root=object_root,
            action_roots=body.authority_action_roots,
            lineage_roots=(),
            interface_root=None,
            audience_root=body.visibility_root,
            classification_root=None,
            lifecycle_root=body.lifecycle_root,
            purpose_root=None,
            operational_root=protocol.state("active"),
            label=label,
        )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (view_request, scope_request),
        resolver_state,
    )
    decisions = evaluation.decisions
    if len(decisions) != 2:
        raise AuthorizationDenied("agent session authorization was incomplete")
    for decision, object_root, label in (
        (decisions[0], view_session_root, "agent session view"),
        (decisions[1], scope_root, "agent session scope"),
    ):
        _validate_decision(
            snapshot,
            authorization,
            body,
            decision,
            expected_object_root=object_root,
            expected_rule_object_root=object_root,
            expected_interface_root=None,
            expected_purpose_root=None,
            expected_classification_root=None,
            expected_audience_root=body.visibility_root,
            expected_lifecycle_root=body.lifecycle_root,
            expected_operational_root=protocol.state("active"),
            expected_subject_relation_root=owner_role_root,
            label=label,
        )
    if decisions[0].subject_root != decisions[1].subject_root:
        raise AuthorizationDenied("agent session decisions disagree on subject")
    context_registry = session_id + ":context-registry"
    proposal_registry = session_id + ":proposal-registry"
    cursor_root = session_id + ":context-cursor"
    view_reason_root = session_id + ":view-reason"
    scope_reason_root = session_id + ":scope-reason"
    view_receipt_root = session_id + ":view-receipt"
    scope_receipt_root = session_id + ":scope-receipt"
    view_receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        0,
        receipt_id=view_receipt_root,
    )
    scope_receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        1,
        receipt_id=scope_receipt_root,
    )
    context_relation = compose_relation_cells((), relation_id=context_registry)
    proposal_relation = compose_relation_cells((), relation_id=proposal_registry)
    session_relation = compose_relation_cells(
        (
            (protocol.role("session-body"), body_root),
            (protocol.role("session-subject"), subject_root),
            (protocol.role("session-owner-role"), owner_role_root),
            (owner_role_root, subject_root),
            (protocol.role("session-view-session"), view_session_root),
            (protocol.role("session-scope"), scope_root),
            (protocol.role("session-focus"), focus_root),
            (protocol.role("session-assignment"), assignment_root),
            (
                protocol.role("session-model-binding"),
                _binding_root(protocol, body.model_binding_root),
            ),
            (protocol.role("session-context-registry"), context_registry),
            (protocol.role("session-proposal-registry"), proposal_registry),
            (protocol.role("session-context-cursor"), cursor_root),
            (protocol.role("session-state"), protocol.state("active")),
            (protocol.role("session-view-action"), decisions[0].action_root),
            (protocol.role("session-view-policy"), decisions[0].policy_root),
            *(
                (protocol.role("session-view-rule"), root)
                for root in decisions[0].determining_rule_roots
            ),
            (protocol.role("session-view-reason"), view_reason_root),
            (protocol.role("session-view-receipt"), view_receipt_root),
            (protocol.role("session-scope-action"), decisions[1].action_root),
            (protocol.role("session-scope-policy"), decisions[1].policy_root),
            *(
                (protocol.role("session-scope-rule"), root)
                for root in decisions[1].determining_rule_roots
            ),
            (protocol.role("session-scope-reason"), scope_reason_root),
            (protocol.role("session-scope-receipt"), scope_receipt_root),
        ),
        relation_id=session_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("session"),
        protocol.role("session-member"),
        session_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(cursor_root, 0),
            _terminal(view_reason_root, decisions[0].reason),
            _terminal(scope_reason_root, decisions[1].reason),
            *view_receipt_cells,
            *scope_receipt_cells,
            *context_relation.cells,
            *proposal_relation.cells,
            *session_relation.cells,
            *append.create,
        ),
        "agent session",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=append.replace,
    )
    return read_agent_session(
        store.snapshot(),
        protocol,
        authorization,
        session_id,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )


def close_agent_session(
    store: CellStore,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    close_request: AuthorizationRequest,
    session_root: str,
    *,
    reason_root: str | None = None,
    resolver_state: object | None = None,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> int:
    snapshot = store.snapshot()
    session = read_agent_session(
        snapshot,
        protocol,
        authorization,
        session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    body = read_agent_body(
        snapshot,
        protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    _require_active(protocol, body)
    _require_request_binding(
        close_request,
        object_root=session_root,
        action_roots=body.authority_action_roots,
        lineage_roots=(session.scope_root,),
        interface_root=None,
        audience_root=body.visibility_root,
        classification_root=None,
        lifecycle_root=body.lifecycle_root,
        purpose_root=None,
        operational_root=protocol.state("active"),
        label="agent session close request",
    )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (close_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    _validate_decision(
        snapshot,
        authorization,
        body,
        decision,
        expected_object_root=session_root,
        expected_rule_object_root=session.scope_root,
        expected_interface_root=None,
        expected_purpose_root=None,
        expected_classification_root=None,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=protocol.state("active"),
        expected_subject_relation_root=session.owner_role_root,
        label="agent session close",
    )
    if session.state_root == protocol.state("closed"):
        if reason_root is not None and session.close_reason_root != reason_root:
            raise InvalidCell("closed agent session has a different reason")
        return snapshot.revision
    _require_active(protocol, body, session)
    authorization_reason_root = session_root + ":close-authorization-reason"
    receipt_root = session_root + ":close-receipt"
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        0,
        receipt_id=receipt_root,
    )
    append_members = [
        (protocol.role("session-close-action"), decision.action_root),
        (protocol.role("session-close-policy"), decision.policy_root),
        *(
            (protocol.role("session-close-rule"), root)
            for root in decision.determining_rule_roots
        ),
        (
            protocol.role("session-close-authorization-reason"),
            authorization_reason_root,
        ),
        (protocol.role("session-close-receipt"), receipt_root),
    ]
    if reason_root is not None:
        _ensure_roots(snapshot, (reason_root,), "agent session close")
        append_members.append(
            (protocol.role("session-close-reason"), reason_root)
        )
    append = prepare_append_relation_members(
        snapshot,
        session_root,
        append_members,
        budget=RELATION_BUDGET,
    )
    state = snapshot.cells[session.state_incidence]
    state_replacement = Cell(
        state.id, state.link0, protocol.state("closed"), state.atom
    )
    return authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=(
            _terminal(authorization_reason_root, decision.reason),
            *receipt_cells,
            *append.create,
        ),
        replace=(*append.replace, state_replacement),
    )


def append_context_entry(
    store: CellStore,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    context_request: AuthorizationRequest,
    registry_request: AuthorizationRequest,
    *,
    session_root: str,
    context_root: str,
    provenance_root: str,
    trust_root: str,
    sensitivity_root: str,
    audience_root: str,
    lifecycle_root: str,
    purpose_root: str | None,
    idempotency_key: str,
    resolver_state: object | None = None,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> str:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key.encode("utf-8")) > 512
    ):
        raise InvalidCell("agent context idempotency key is invalid")
    snapshot = store.snapshot()
    session = read_agent_session(
        snapshot,
        protocol,
        authorization,
        session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if len(session.context_entry_roots) >= MAX_CONTEXT_ENTRIES:
        raise InvalidCell("agent session context entry limit reached")
    body = read_agent_body(
        snapshot,
        protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    _require_active(protocol, body, session)
    _ensure_roots(
        snapshot,
        tuple(root for root in (
            context_root,
            provenance_root,
            trust_root,
            sensitivity_root,
            audience_root,
            lifecycle_root,
            purpose_root,
        ) if root is not None),
        "agent context",
    )
    for request, object_root, label in (
        (context_request, context_root, "agent context selection request"),
        (
            registry_request,
            session.context_registry_root,
            "agent context registry request",
        ),
    ):
        _require_request_binding(
            request,
            object_root=object_root,
            action_roots=body.authority_action_roots,
            lineage_roots=(session.scope_root,),
            audience_root=audience_root,
            classification_root=sensitivity_root,
            lifecycle_root=lifecycle_root,
            purpose_root=purpose_root,
            operational_root=protocol.state("active"),
            label=label,
        )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (context_request, registry_request),
        resolver_state,
    )
    decisions = evaluation.decisions
    if len(decisions) != 2:
        raise AuthorizationDenied("agent context authorization was incomplete")
    _validate_decision(
        snapshot,
        authorization,
        body,
        decisions[0],
        expected_object_root=context_root,
        expected_rule_object_root=context_root,
        expected_interface_root=context_request.interface_root,
        expected_purpose_root=purpose_root,
        expected_classification_root=sensitivity_root,
        expected_audience_root=audience_root,
        expected_lifecycle_root=lifecycle_root,
        expected_operational_root=protocol.state("active"),
        label="agent context selection",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        decisions[1],
        expected_object_root=session.context_registry_root,
        expected_rule_object_root=session.scope_root,
        expected_interface_root=registry_request.interface_root,
        expected_purpose_root=purpose_root,
        expected_classification_root=sensitivity_root,
        expected_audience_root=audience_root,
        expected_lifecycle_root=lifecycle_root,
        expected_operational_root=protocol.state("active"),
        label="agent context registry mutation",
    )
    if decisions[0].subject_root != decisions[1].subject_root:
        raise AuthorizationDenied("agent context decisions disagree on subject")
    sequence = session.context_cursor + 1
    provisional = ContextEntryProjection(
        "",
        session_root,
        session.subject_root,
        context_root,
        provenance_root,
        trust_root,
        sensitivity_root,
        audience_root,
        lifecycle_root,
        purpose_root,
        context_request.interface_root,
        registry_request.interface_root,
        snapshot.revision,
        decisions[0].action_root,
        decisions[0].policy_root,
        decisions[0].determining_rule_roots,
        decisions[0].reason,
        "",
        decisions[1].action_root,
        decisions[1].policy_root,
        decisions[1].determining_rule_roots,
        decisions[1].reason,
        "",
        idempotency_key,
        "",
        sequence,
    )
    digest = _context_digest(provisional, session, protocol)
    entry_id = _context_identity(session_root, idempotency_key)
    if entry_id in snapshot.cells:
        if entry_id in session.context_entry_roots:
            existing = _project_context_entry(snapshot, protocol, entry_id)
            if _context_replay_payload(
                existing, session, protocol
            ) == _context_replay_payload(provisional, session, protocol):
                return entry_id
            raise InvalidCell(
                "agent context idempotency key was reused for other content"
            )
        raise InvalidCell("derived agent context identity already exists elsewhere")
    observed_root = entry_id + ":observed-revision"
    context_reason_root = entry_id + ":context-reason"
    registry_reason_root = entry_id + ":registry-reason"
    context_receipt_root = entry_id + ":context-receipt"
    registry_receipt_root = entry_id + ":registry-receipt"
    context_receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        0,
        receipt_id=context_receipt_root,
    )
    registry_receipt_cells = _compose_authorization_receipt(
        snapshot,
        protocol,
        authorization,
        evaluation,
        1,
        receipt_id=registry_receipt_root,
    )
    idempotency_root = entry_id + ":idempotency-key"
    digest_root = entry_id + ":semantic-digest"
    sequence_root = entry_id + ":sequence"
    relation = compose_relation_cells(
        (
            (protocol.role("context-session"), session_root),
            (protocol.role("context-subject"), session.subject_root),
            (protocol.role("context-root"), context_root),
            (protocol.role("context-provenance"), provenance_root),
            (protocol.role("context-trust"), trust_root),
            (protocol.role("context-sensitivity"), sensitivity_root),
            (protocol.role("context-audience"), audience_root),
            (protocol.role("context-lifecycle"), lifecycle_root),
            (
                protocol.role("context-purpose"),
                _binding_root(protocol, purpose_root),
            ),
            (
                protocol.role("context-interface"),
                _binding_root(protocol, context_request.interface_root),
            ),
            (
                protocol.role("registry-interface"),
                _binding_root(protocol, registry_request.interface_root),
            ),
            (protocol.role("context-observed-revision"), observed_root),
            (protocol.role("context-action"), decisions[0].action_root),
            (protocol.role("context-policy"), decisions[0].policy_root),
            *(
                (protocol.role("context-rule"), root)
                for root in decisions[0].determining_rule_roots
            ),
            (
                protocol.role("context-authorization-reason"),
                context_reason_root,
            ),
            (
                protocol.role("context-authorization-receipt"),
                context_receipt_root,
            ),
            (protocol.role("registry-action"), decisions[1].action_root),
            (protocol.role("registry-policy"), decisions[1].policy_root),
            *(
                (protocol.role("registry-rule"), root)
                for root in decisions[1].determining_rule_roots
            ),
            (
                protocol.role("registry-authorization-reason"),
                registry_reason_root,
            ),
            (
                protocol.role("registry-authorization-receipt"),
                registry_receipt_root,
            ),
            (protocol.role("context-idempotency"), idempotency_root),
            (protocol.role("context-semantic-digest"), digest_root),
            (protocol.role("context-sequence"), sequence_root),
        ),
        relation_id=entry_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        session.context_registry_root,
        protocol.role("context-member"),
        entry_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(observed_root, snapshot.revision),
            _terminal(context_reason_root, decisions[0].reason),
            _terminal(registry_reason_root, decisions[1].reason),
            *context_receipt_cells,
            *registry_receipt_cells,
            _terminal(idempotency_root, idempotency_key),
            _terminal(digest_root, digest),
            _terminal(sequence_root, sequence),
            *relation.cells,
            *append.create,
        ),
        "agent context entry",
    )
    cursor = snapshot.cells[session.context_cursor_root]
    cursor_replacement = Cell(
        cursor.id, cursor.link0, cursor.link1, str(sequence).encode("ascii")
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=(*append.replace, cursor_replacement),
    )
    return entry_id


def read_context_entry(
    snapshot: Snapshot,
    protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    entry_root: str,
    *,
    model_binding_verifier: ModelBindingVerifier | None = None,
    proposal_verifier: ProposalVerifier | None = None,
) -> ContextEntryProjection:
    _validate_protocol(snapshot, protocol)
    entry = _project_context_entry(snapshot, protocol, entry_root)
    session = _read_agent_session(
        snapshot,
        protocol,
        authorization,
        entry.session_root,
        validate_protocol=False,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if session.context_entry_roots.count(entry_root) != 1:
        raise InvalidCell("agent context entry is not registered exactly once")
    return entry


__all__ = [
    "AgentBodyProtocol",
    "AgentBodyProjection",
    "AgentSessionProjection",
    "ContextEntryProjection",
]
