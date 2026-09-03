"""Released graph-held authorization for every universal-cell interface.

Rules combine relationship scope (principal and resource lineage) with exact
subject/object/action/environment attributes.  The evaluator is deliberately
domain-neutral, default-deny, and forbid-overrides-permit.  Authentication and
policy-release authority are process-local trust handles; writing an atom that
says "authenticated" or "released" cannot mint either authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "policy-member",
    "effect",
    "principal",
    "object",
    "action",
    "interface",
    "purpose",
    "tenant",
    "assurance",
    "classification",
    "audience",
    "lifecycle-state",
    "operational-state",
    "subject-relation",
    "expires-at",
    "max-invocations",
    "version",
    "lifecycle",
    "digest",
)

ACTION_NAMES = (
    "create",
    "read",
    "inspect",
    "traverse",
    "edit",
    "connect",
    "execute",
    "share",
    "merge",
    "promote",
    "publish",
    "deploy",
    "export",
    "declassify",
    "delete",
    "restore",
    "manage-policy",
)

OPTIONAL_RULE_FIELDS = (
    "interface",
    "purpose",
    "tenant",
    "assurance",
    "classification",
    "audience",
    "lifecycle-state",
    "operational-state",
    "subject-relation",
    "expires-at",
    "max-invocations",
)


@dataclass(frozen=True, slots=True)
class AuthorizationProtocol:
    root_id: str
    roles: Mapping[str, str]
    actions: Mapping[str, str]
    effects: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown authorization role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class AuthorizationRule:
    root_id: str
    effect_root: str
    principal_root: str
    object_root: str
    action_root: str
    interface_root: str | None
    purpose_root: str | None
    tenant_root: str | None
    assurance_root: str | None
    classification_root: str | None
    audience_root: str | None
    lifecycle_state_root: str | None
    operational_state_root: str | None
    subject_relation_root: str | None
    expires_at_root: str | None
    max_invocations_root: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    root_id: str
    rule_roots: tuple[str, ...]
    version_root: str
    lifecycle_root: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    action_root: str
    object_root: str
    resource_lineage_roots: tuple[str, ...] = ()
    interface_root: str | None = None
    purpose_root: str | None = None
    classification_root: str | None = None
    audience_root: str | None = None
    lifecycle_state_root: str | None = None
    operational_state_root: str | None = None
    invocation_count: int = 0
    now: float | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    policy_root: str
    subject_root: str
    action_root: str
    object_root: str
    determining_rule_roots: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class AuthorizationIdentityEvidence:
    subject_root: str
    principal_roots: tuple[str, ...]
    tenant_root: str | None
    assurance_root: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class AuthorizationResolverEvidence:
    protocol_root: str
    revision: int
    evaluated_at: float
    relationship_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorizationEvaluation:
    revision: int
    evaluated_at: float
    policy_root: str
    identities: tuple[AuthorizationIdentityEvidence, ...]
    decisions: tuple[AuthorizationDecision, ...]
    resolver_evidence: AuthorizationResolverEvidence | None = None


class AuthorizationDenied(PermissionError):
    pass


_AUTHENTICATION_KEY = object()
_POLICY_RELEASE_KEY = object()


class AuthenticationContext:
    __slots__ = ("_nonce",)

    def __init__(self, key: object) -> None:
        if key is not _AUTHENTICATION_KEY:
            raise TypeError(
                "authenticated context can only be minted by its broker"
            )
        self._nonce = secrets.token_hex(16)

    def __reduce_ex__(self, protocol):
        raise TypeError("authenticated contexts cannot be serialized")


@dataclass(frozen=True, slots=True)
class _AuthenticationEntry:
    subject_root: str
    principal_roots: tuple[str, ...]
    tenant_root: str | None
    assurance_root: str
    expires_at: float


class AuthenticationBroker:
    """Trusted identity boundary; contexts are reusable but short-lived."""

    def __init__(self) -> None:
        self._entries: dict[AuthenticationContext, _AuthenticationEntry] = {}
        self._graph_resolver: Callable[
            [Snapshot, _AuthenticationEntry, AuthorizationRequest, float],
            Iterable[str],
        ] | None = None
        self._graph_batch_resolver: Callable[
            [
                Snapshot,
                _AuthenticationEntry,
                tuple[AuthorizationRequest, ...],
                float,
            ],
            Iterable[Iterable[str]],
        ] | None = None
        self._graph_stateful_batch_resolver: Callable[
            [
                Snapshot,
                _AuthenticationEntry,
                tuple[AuthorizationRequest, ...],
                float,
                object,
            ],
            Iterable[Iterable[str]],
        ] | None = None
        self._lock = threading.RLock()

    def bind_graph_resolver(
        self,
        resolver: Callable[
            [Snapshot, _AuthenticationEntry, AuthorizationRequest, float],
            Iterable[str],
        ],
    ) -> None:
        """Bind the one request-time relationship resolver for this broker."""
        if not callable(resolver):
            raise TypeError("authentication graph resolver must be callable")
        with self._lock:
            if self._graph_resolver is not None:
                raise RuntimeError("authentication graph resolver is already bound")
            self._graph_resolver = resolver
            batch_resolver = getattr(resolver, "resolve_batch", None)
            self._graph_batch_resolver = (
                batch_resolver if callable(batch_resolver) else None
            )
            stateful_batch_resolver = getattr(
                resolver, "resolve_batch_with_state", None
            )
            self._graph_stateful_batch_resolver = (
                stateful_batch_resolver
                if callable(stateful_batch_resolver) else None
            )

    def mint_authenticated_context(
        self,
        subject_root: str,
        *,
        principal_roots: Iterable[str] = (),
        tenant_root: str | None,
        assurance_root: str,
        lifetime_seconds: float = 300.0,
    ) -> AuthenticationContext:
        if lifetime_seconds <= 0 or lifetime_seconds > 3600:
            raise ValueError(
                "authentication context lifetime must be within one hour"
            )
        principals = tuple(dict.fromkeys((subject_root, *principal_roots)))
        handle = AuthenticationContext(_AUTHENTICATION_KEY)
        with self._lock:
            self._entries[handle] = _AuthenticationEntry(
                subject_root,
                principals,
                tenant_root,
                assurance_root,
                time.time() + lifetime_seconds,
            )
        return handle

    def resolve(self, handle: object, *, now: float | None = None) -> _AuthenticationEntry:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is AuthenticationContext else None
            )
            if entry is None:
                raise AuthorizationDenied("unknown authenticated context")
            current = time.time() if now is None else now
            if current >= entry.expires_at:
                raise AuthorizationDenied("authenticated context expired")
            return entry

    def resolve_for_request(
        self,
        snapshot: Snapshot,
        handle: object,
        request: AuthorizationRequest,
        *,
        now: float | None = None,
        resolver_state: object | None = None,
    ) -> _AuthenticationEntry:
        """Resolve identity and live graph-derived principals for one request."""
        return self.resolve_for_requests(
            snapshot,
            handle,
            (request,),
            now=now,
            resolver_state=resolver_state,
        )[0]

    def resolve_for_requests(
        self,
        snapshot: Snapshot,
        handle: object,
        requests: Iterable[AuthorizationRequest],
        *,
        now: float | None = None,
        resolver_state: object | None = None,
    ) -> tuple[_AuthenticationEntry, ...]:
        """Resolve one immutable graph revision for an exact request batch."""
        requested = tuple(requests)
        if not requested:
            return ()
        current = time.time() if now is None else now
        entry = self.resolve(handle, now=current)
        with self._lock:
            resolver = self._graph_resolver
            batch_resolver = self._graph_batch_resolver
            stateful_batch_resolver = self._graph_stateful_batch_resolver
        if resolver is None:
            if resolver_state is not None:
                raise AuthorizationDenied(
                    "authentication resolver state has no bound consumer"
                )
            return tuple(entry for _request in requested)
        if resolver_state is not None and stateful_batch_resolver is None:
            raise AuthorizationDenied(
                "authentication graph resolver rejected external state"
            )
        derived_sets = tuple(
            stateful_batch_resolver(
                snapshot, entry, requested, current, resolver_state
            )
            if resolver_state is not None
            and stateful_batch_resolver is not None
            else batch_resolver(snapshot, entry, requested, current)
            if resolver_state is None and batch_resolver is not None
            else (
                resolver(snapshot, entry, request, current)
                for request in requested
            )
        )
        if len(derived_sets) != len(requested):
            raise AuthorizationDenied(
                "graph identity batch resolver returned the wrong result count"
            )
        resolved = []
        for derived_values in derived_sets:
            derived = tuple(derived_values)
            if any(not isinstance(root, str) or not root for root in derived):
                raise AuthorizationDenied(
                    "graph identity resolver returned invalid roots"
                )
            resolved.append(_AuthenticationEntry(
                entry.subject_root,
                tuple(dict.fromkeys((*entry.principal_roots, *derived))),
                entry.tenant_root,
                entry.assurance_root,
                entry.expires_at,
            ))
        return tuple(resolved)

    def revoke(self, handle: object) -> None:
        with self._lock:
            if type(handle) is AuthenticationContext:
                self._entries.pop(handle, None)

    def commit_authenticated(
        self,
        handle: object,
        store: CellStore,
        expected_revision: int,
        *,
        create: Iterable[Cell] = (),
        replace: Iterable[Cell] = (),
    ) -> int:
        """Commit while the opaque context is live and cannot be revoked."""
        with self._lock:
            self.resolve(handle)
            return store.commit(
                expected_revision,
                create=create,
                replace=replace,
                precommit_guard=lambda: self.resolve(handle),
            )


class PolicyReleaseHandle:
    __slots__ = ("_nonce",)

    def __init__(self, key: object) -> None:
        if key is not _POLICY_RELEASE_KEY:
            raise TypeError("policy release can only be minted by its broker")
        self._nonce = secrets.token_hex(16)

    def __reduce_ex__(self, protocol):
        raise TypeError("policy-release handles cannot be serialized")


@dataclass(slots=True)
class _PolicyReleaseEntry:
    policy_root: str
    administrator_root: str
    expires_at: float
    used: bool = False


class PolicyReleaseBroker:
    """Trusted administrative boundary for one exact policy release."""

    def __init__(self) -> None:
        self._entries: dict[PolicyReleaseHandle, _PolicyReleaseEntry] = {}
        self._lock = threading.RLock()

    def mint_from_trusted_administrator(
        self,
        policy_root: str,
        administrator_root: str,
        *,
        lifetime_seconds: float = 120.0,
    ) -> PolicyReleaseHandle:
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError("policy release lifetime must be within five minutes")
        handle = PolicyReleaseHandle(_POLICY_RELEASE_KEY)
        with self._lock:
            self._entries[handle] = _PolicyReleaseEntry(
                policy_root,
                administrator_root,
                time.time() + lifetime_seconds,
            )
        return handle

    def consume(
        self,
        handle: object,
        policy_root: str,
        administrator_root: str,
    ) -> None:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is PolicyReleaseHandle else None
            )
            if entry is None:
                raise AuthorizationDenied("unknown policy-release handle")
            if entry.used:
                raise AuthorizationDenied("policy-release handle was already used")
            if time.time() >= entry.expires_at:
                raise AuthorizationDenied("policy-release handle expired")
            if (
                entry.policy_root != policy_root
                or entry.administrator_root != administrator_root
            ):
                raise AuthorizationDenied("policy release does not match authority")
            entry.used = True


def _new_terminal(batch: CellBatch, root_id: str, value: str) -> str:
    encoded = value.encode("utf-8")
    if not encoded:
        raise InvalidCell("authorization values cannot be empty")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("authorization graph requires exactly one %s" % label)
    return values[0]


def _optional(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str | None:
    values = _for_role(members, role_id)
    if len(values) > 1:
        raise InvalidCell("authorization graph repeats %s" % label)
    return values[0] if values else None


def _closed_roles(
    members: tuple[RelationMember, ...], allowed: set[str], label: str
) -> None:
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("%s contains an undeclared field" % label)


def bootstrap_authorization_protocol(
    store: CellStore,
    *,
    prefix: str = "authorization-protocol",
) -> AuthorizationProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    actions = {
        name: "%s:action:%s" % (prefix, name) for name in ACTION_NAMES
    }
    effects = {
        name: "%s:effect:%s" % (prefix, name)
        for name in ("permit", "forbid")
    }
    states = {
        name: "%s:state:%s" % (prefix, name)
        for name in ("draft", "released", "revoked")
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        _new_terminal(batch, root, name)
    for name, root in actions.items():
        _new_terminal(batch, root, name)
    for name, root in effects.items():
        _new_terminal(batch, root, name)
    for name, root in states.items():
        _new_terminal(batch, root, name)
    root_id = prefix + ":root"
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in actions.values()),
        *((roles["vocabulary-member"], root) for root in effects.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ], relation_id=root_id)
    batch.commit()
    return AuthorizationProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(actions),
        MappingProxyType(effects),
        MappingProxyType(states),
    )


def build_authorization_rule(
    store: CellStore,
    protocol: AuthorizationProtocol,
    *,
    rule_id: str,
    effect: str,
    principal_root: str,
    object_root: str,
    action_root: str,
    interface_root: str | None = None,
    purpose_root: str | None = None,
    tenant_root: str | None = None,
    assurance_root: str | None = None,
    classification_root: str | None = None,
    audience_root: str | None = None,
    lifecycle_state_root: str | None = None,
    operational_state_root: str | None = None,
    subject_relation_root: str | None = None,
    expires_at: float | None = None,
    max_invocations: int | None = None,
) -> str:
    if effect not in protocol.effects:
        raise InvalidCell("authorization rule effect is unknown")
    if action_root not in protocol.actions.values():
        raise InvalidCell("authorization rule action is outside the vocabulary")
    referenced = tuple(root for root in (
        principal_root,
        object_root,
        action_root,
        interface_root,
        purpose_root,
        tenant_root,
        assurance_root,
        classification_root,
        audience_root,
        lifecycle_state_root,
        operational_state_root,
        subject_relation_root,
    ) if root is not None)
    snapshot = store.snapshot()
    if any(root not in snapshot.cells for root in referenced):
        raise InvalidCell("authorization rule references a missing node")
    if expires_at is not None and expires_at <= time.time():
        raise InvalidCell("authorization rule expiry must be in the future")
    if max_invocations is not None and max_invocations < 1:
        raise InvalidCell("authorization rule invocation budget is invalid")

    batch = CellBatch(store)
    expires_root = None
    if expires_at is not None:
        expires_root = _new_terminal(
            batch, rule_id + ":expires-at", repr(float(expires_at))
        )
    budget_root = None
    if max_invocations is not None:
        budget_root = _new_terminal(
            batch, rule_id + ":max-invocations", str(max_invocations)
        )
    fields = (
        ("interface", interface_root),
        ("purpose", purpose_root),
        ("tenant", tenant_root),
        ("assurance", assurance_root),
        ("classification", classification_root),
        ("audience", audience_root),
        ("lifecycle-state", lifecycle_state_root),
        ("operational-state", operational_state_root),
        ("subject-relation", subject_relation_root),
        ("expires-at", expires_root),
        ("max-invocations", budget_root),
    )
    batch.relation([
        (protocol.role("effect"), protocol.effects[effect]),
        (protocol.role("principal"), principal_root),
        (protocol.role("object"), object_root),
        (protocol.role("action"), action_root),
        *((protocol.role(name), root) for name, root in fields if root),
    ], relation_id=rule_id)
    batch.commit()
    return rule_id


def read_authorization_rule(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    rule_root: str,
) -> AuthorizationRule:
    members = read_relation(snapshot, rule_root, budget=128)
    allowed = {
        protocol.role(name) for name in (
            "effect", "principal", "object", "action", *OPTIONAL_RULE_FIELDS
        )
    }
    _closed_roles(members, allowed, "authorization rule")
    return AuthorizationRule(
        rule_root,
        _one(members, protocol.role("effect"), "rule effect"),
        _one(members, protocol.role("principal"), "rule principal"),
        _one(members, protocol.role("object"), "rule object"),
        _one(members, protocol.role("action"), "rule action"),
        *(
            _optional(members, protocol.role(name), "rule " + name)
            for name in OPTIONAL_RULE_FIELDS
        ),
    )


def build_authorization_policy(
    store: CellStore,
    protocol: AuthorizationProtocol,
    rule_roots: Iterable[str],
    *,
    policy_id: str,
    version: str,
) -> str:
    roots = tuple(rule_roots)
    if len(roots) != len(set(roots)):
        raise InvalidCell("authorization policy repeats a rule")
    snapshot = store.snapshot()
    for root in roots:
        read_authorization_rule(snapshot, protocol, root)
    batch = CellBatch(store)
    version_root = _new_terminal(batch, policy_id + ":version", version)
    digest_root = policy_id + ":digest"
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    batch.relation([
        *((protocol.role("policy-member"), root) for root in roots),
        (protocol.role("version"), version_root),
        (protocol.role("lifecycle"), protocol.states["draft"]),
        (protocol.role("digest"), digest_root),
    ], relation_id=policy_id)
    batch.commit()
    return policy_id


def read_authorization_policy(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
) -> AuthorizationPolicy:
    members = read_relation(snapshot, policy_root, budget=100_000)
    allowed = {
        protocol.role(name) for name in (
            "policy-member", "version", "lifecycle", "digest"
        )
    }
    _closed_roles(members, allowed, "authorization policy")
    policy = AuthorizationPolicy(
        policy_root,
        _for_role(members, protocol.role("policy-member")),
        _one(members, protocol.role("version"), "policy version"),
        _one(members, protocol.role("lifecycle"), "policy lifecycle"),
        _one(members, protocol.role("digest"), "policy digest"),
    )
    if len(policy.rule_roots) != len(set(policy.rule_roots)):
        raise InvalidCell("authorization policy repeats a rule")
    return policy


def _digest_bytes(digest, raw: bytes) -> None:
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)


def _rule_digest(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    rule_root: str,
) -> bytes:
    read_authorization_rule(snapshot, protocol, rule_root)
    members = read_relation(snapshot, rule_root, budget=128)
    digest = hashlib.blake2b(digest_size=32)
    _digest_bytes(digest, rule_root.encode("utf-8"))
    owned_value_roles = {
        protocol.role("expires-at"),
        protocol.role("max-invocations"),
    }
    for member in members:
        _digest_bytes(digest, member.role_id.encode("utf-8"))
        _digest_bytes(digest, member.participant_id.encode("utf-8"))
        if member.role_id in owned_value_roles:
            _digest_bytes(digest, snapshot.cells[member.participant_id].atom)
    return digest.digest()


def _policy_digest(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy: AuthorizationPolicy,
) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    _digest_bytes(digest, policy.root_id.encode("utf-8"))
    _digest_bytes(digest, snapshot.cells[policy.version_root].atom)
    for rule_root in policy.rule_roots:
        _digest_bytes(digest, _rule_digest(snapshot, protocol, rule_root))
    return digest.hexdigest().encode("ascii")


def release_authorization_policy(
    store: CellStore,
    protocol: AuthorizationProtocol,
    policy_root: str,
    release_broker: PolicyReleaseBroker,
    release_handle: object,
    *,
    administrator_root: str,
) -> bytes:
    snapshot = store.snapshot()
    if administrator_root not in snapshot.cells:
        raise InvalidCell("policy administrator is missing")
    policy = read_authorization_policy(snapshot, protocol, policy_root)
    if policy.lifecycle_root != protocol.states["draft"]:
        raise InvalidCell("only a draft authorization policy can be released")
    release_broker.consume(
        release_handle, policy_root, administrator_root
    )
    digest = _policy_digest(snapshot, protocol, policy)
    members = read_relation(snapshot, policy_root, budget=100_000)
    lifecycle_member = next(
        member for member in members
        if member.role_id == protocol.role("lifecycle")
    )
    lifecycle_incidence = snapshot.cells[lifecycle_member.incidence_id]
    digest_cell = snapshot.cells[policy.digest_root]
    store.commit(snapshot.revision, replace=(
        Cell(
            digest_cell.id,
            digest_cell.link0,
            digest_cell.link1,
            digest,
        ),
        Cell(
            lifecycle_incidence.id,
            lifecycle_incidence.link0,
            protocol.states["released"],
            lifecycle_incidence.atom,
        ),
    ))
    return digest


def verify_authorization_policy(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
) -> AuthorizationPolicy:
    policy = read_authorization_policy(snapshot, protocol, policy_root)
    if policy.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("authorization policy is not released")
    expected = snapshot.cells[policy.digest_root].atom
    actual = _policy_digest(snapshot, protocol, policy)
    if not expected or not hmac.compare_digest(expected, actual):
        raise InvalidCell("released authorization policy has drifted")
    return policy


def _request_roots(request: AuthorizationRequest) -> tuple[str, ...]:
    return tuple(root for root in (
        request.action_root,
        request.object_root,
        *request.resource_lineage_roots,
        request.interface_root,
        request.purpose_root,
        request.classification_root,
        request.audience_root,
        request.lifecycle_state_root,
        request.operational_state_root,
    ) if root is not None)


def _rule_matches(
    snapshot: Snapshot,
    rule: AuthorizationRule,
    identity: _AuthenticationEntry,
    request: AuthorizationRequest,
    *,
    now: float,
) -> bool:
    if rule.principal_root not in identity.principal_roots:
        return False
    if rule.object_root not in (
        request.object_root, *request.resource_lineage_roots
    ):
        return False
    if rule.action_root != request.action_root:
        return False
    if rule.tenant_root is not None and rule.tenant_root != identity.tenant_root:
        return False
    if (
        rule.assurance_root is not None
        and rule.assurance_root != identity.assurance_root
    ):
        return False
    for required, actual in (
        (rule.interface_root, request.interface_root),
        (rule.purpose_root, request.purpose_root),
        (rule.classification_root, request.classification_root),
        (rule.audience_root, request.audience_root),
        (rule.lifecycle_state_root, request.lifecycle_state_root),
        (rule.operational_state_root, request.operational_state_root),
    ):
        if required is not None and required != actual:
            return False
    if rule.subject_relation_root is not None:
        object_members = read_relation(
            snapshot, request.object_root, budget=100_000
        )
        if not any(
            member.role_id == rule.subject_relation_root
            and member.participant_id == identity.subject_root
            for member in object_members
        ):
            return False
    if rule.expires_at_root is not None:
        try:
            expires_at = float(
                snapshot.cells[rule.expires_at_root].atom.decode("ascii")
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("authorization rule expiry is invalid") from exc
        if now >= expires_at:
            return False
    if rule.max_invocations_root is not None:
        try:
            maximum = int(
                snapshot.cells[rule.max_invocations_root].atom.decode("ascii")
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell(
                "authorization rule invocation budget is invalid"
            ) from exc
        if request.invocation_count < 0 or request.invocation_count >= maximum:
            return False
    return True


def _evaluate_authorization_request(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy: AuthorizationPolicy,
    rules: tuple[AuthorizationRule, ...],
    identity: _AuthenticationEntry,
    request: AuthorizationRequest,
    *,
    current: float,
) -> AuthorizationDecision:
    context_roots = tuple(root for root in (
        identity.subject_root,
        *identity.principal_roots,
        identity.tenant_root,
        identity.assurance_root,
    ) if root is not None)
    if any(root not in snapshot.cells for root in context_roots):
        raise InvalidCell("authenticated context references a missing node")
    if request.action_root not in protocol.actions.values():
        raise InvalidCell("authorization request action is outside vocabulary")
    if request.invocation_count < 0:
        raise InvalidCell("authorization request invocation count is invalid")
    if any(root not in snapshot.cells for root in _request_roots(request)):
        raise InvalidCell("authorization request references a missing node")

    permits: list[str] = []
    forbids: list[str] = []
    for rule in rules:
        if not _rule_matches(
            snapshot, rule, identity, request, now=current
        ):
            continue
        if rule.effect_root == protocol.effects["forbid"]:
            forbids.append(rule.root_id)
        elif rule.effect_root == protocol.effects["permit"]:
            permits.append(rule.root_id)
        else:
            raise InvalidCell("authorization rule effect is invalid")
    if forbids:
        return AuthorizationDecision(
            False,
            policy.root_id,
            identity.subject_root,
            request.action_root,
            request.object_root,
            tuple(forbids),
            "explicit-forbid",
        )
    if permits:
        return AuthorizationDecision(
            True,
            policy.root_id,
            identity.subject_root,
            request.action_root,
            request.object_root,
            tuple(permits),
            "explicit-permit",
        )
    return AuthorizationDecision(
        False,
        policy.root_id,
        identity.subject_root,
        request.action_root,
        request.object_root,
        (),
        "default-deny",
    )


def evaluate_node_requests(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    requests: Iterable[AuthorizationRequest],
    *,
    resolver_state: object | None = None,
) -> AuthorizationEvaluation:
    """Return decisions and exact identity evidence from one evaluation pass."""
    requested = tuple(requests)
    explicit_times = {request.now for request in requested if request.now is not None}
    if len(explicit_times) > 1:
        raise InvalidCell("authorization batch requests disagree on evaluation time")
    current = next(iter(explicit_times), time.time())
    policy = verify_authorization_policy(snapshot, protocol, policy_root)
    identities = authentication_broker.resolve_for_requests(
        snapshot,
        authentication_context,
        requested,
        now=current,
        resolver_state=resolver_state,
    )
    rules = tuple(
        read_authorization_rule(snapshot, protocol, root)
        for root in policy.rule_roots
    )
    decisions = tuple(
        _evaluate_authorization_request(
            snapshot,
            protocol,
            policy,
            rules,
            identity,
            request,
            current=current,
        )
        for request, identity in zip(requested, identities)
    )
    resolver_evidence = None
    if resolver_state is not None:
        protocol_root = getattr(resolver_state, "protocol_root", None)
        revision = getattr(resolver_state, "revision", None)
        evaluated_at = getattr(resolver_state, "evaluated_at", None)
        relationships = getattr(resolver_state, "active_relationships", None)
        if all(value is not None for value in (
            protocol_root, revision, evaluated_at, relationships
        )):
            relationship_roots = tuple(
                getattr(relationship, "root_id", None)
                for relationship in relationships
            )
            if (
                not isinstance(protocol_root, str)
                or not protocol_root
                or revision != snapshot.revision
                or not isinstance(evaluated_at, (int, float))
                or evaluated_at > current
                or len(relationship_roots) > 4_096
                or any(
                    not isinstance(root, str) or not root
                    for root in relationship_roots
                )
                or len(relationship_roots) != len(set(relationship_roots))
            ):
                raise AuthorizationDenied(
                    "authorization resolver evidence is invalid"
                )
            resolver_evidence = AuthorizationResolverEvidence(
                protocol_root,
                revision,
                float(evaluated_at),
                relationship_roots,
            )
    return AuthorizationEvaluation(
        snapshot.revision,
        current,
        policy.root_id,
        tuple(
            AuthorizationIdentityEvidence(
                identity.subject_root,
                identity.principal_roots,
                identity.tenant_root,
                identity.assurance_root,
                identity.expires_at,
            )
            for identity in identities
        ),
        decisions,
        resolver_evidence,
    )


def authorize_node_request(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    request: AuthorizationRequest,
    *,
    resolver_state: object | None = None,
) -> AuthorizationDecision:
    """Evaluate one exact interface request; missing authority always denies."""
    return evaluate_node_requests(
        snapshot,
        protocol,
        policy_root,
        authentication_broker,
        authentication_context,
        (request,),
        resolver_state=resolver_state,
    ).decisions[0]


def authorize_node_requests(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    requests: Iterable[AuthorizationRequest],
    *,
    resolver_state: object | None = None,
) -> tuple[AuthorizationDecision, ...]:
    """Evaluate an exact request set against one policy and graph revision."""
    return evaluate_node_requests(
        snapshot,
        protocol,
        policy_root,
        authentication_broker,
        authentication_context,
        requests,
        resolver_state=resolver_state,
    ).decisions


def require_authorization(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    request: AuthorizationRequest,
    *,
    resolver_state: object | None = None,
) -> AuthorizationDecision:
    decision = authorize_node_request(
        snapshot,
        protocol,
        policy_root,
        authentication_broker,
        authentication_context,
        request,
        resolver_state=resolver_state,
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "authorization denied: %s" % decision.reason
        )
    return decision


def require_authorizations(
    snapshot: Snapshot,
    protocol: AuthorizationProtocol,
    policy_root: str,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    requests: Iterable[AuthorizationRequest],
    *,
    resolver_state: object | None = None,
) -> tuple[AuthorizationDecision, ...]:
    decisions = authorize_node_requests(
        snapshot,
        protocol,
        policy_root,
        authentication_broker,
        authentication_context,
        requests,
        resolver_state=resolver_state,
    )
    for decision in decisions:
        if not decision.allowed:
            raise AuthorizationDenied(
                "authorization denied: %s" % decision.reason
            )
    return decisions


__all__ = [
    "AuthorizationProtocol",
    "AuthorizationRule",
    "AuthorizationPolicy",
    "AuthorizationRequest",
    "AuthorizationDecision",
    "AuthorizationIdentityEvidence",
    "AuthorizationResolverEvidence",
    "AuthorizationEvaluation",
    "AuthorizationDenied",
    "AuthenticationContext",
    "AuthenticationBroker",
    "PolicyReleaseHandle",
    "PolicyReleaseBroker",
    "bootstrap_authorization_protocol",
    "build_authorization_rule",
    "read_authorization_rule",
    "build_authorization_policy",
    "read_authorization_policy",
    "release_authorization_policy",
    "verify_authorization_policy",
    "evaluate_node_requests",
    "authorize_node_request",
    "authorize_node_requests",
    "require_authorization",
    "require_authorizations",
]
