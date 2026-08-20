"""Graph-held browser interaction protocol over generic Cell rewrites.

This module resolves only protocol relations, exact projected identities,
released authorization, and one stored rewrite rule. It owns no feature action
names. Device events and DOM geometry remain boundary facts supplied by a safe
projector; external effects remain outside this graph-only executor.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import hashlib
import hmac
import secrets
import threading
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_authorization import (
    AuthenticationBroker,
    AuthorizationDecision,
    AuthorizationProtocol,
    AuthorizationRequest,
    AuthorizationDenied,
    require_authorization,
)
from .cell_lifecycle import graph_content_digest
from .cell_protocols import (
    CellBatch,
    RelationMember,
    prepare_append_relation_member,
    read_relation,
)
from .cell_rules import (
    RuleProtocol,
    match_rule,
    read_rule,
    rule_content_digest,
)
from .cell_secret_keys import SigningKeyProvider
from .cell_transactions import (
    TransactionExecution,
    TransactionProtocol,
    execute_transaction,
    read_transaction,
    transaction_content_digest,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    RewriteResult,
    Snapshot,
)


@dataclass(slots=True)
class _InteractionProjectionCache:
    protocols: dict[
        tuple[int, int, str], tuple["InteractionProtocol", int]
    ]
    interactions: dict[
        tuple[int, int, str, str], tuple["Interaction", int]
    ]


_INTERACTION_PROJECTION_CACHE: ContextVar[
    _InteractionProjectionCache | None
] = ContextVar("interaction_projection_cache", default=None)


@contextmanager
def interaction_projection_scope():
    """Reuse verified interaction reads only inside one interpreter request."""
    existing = _INTERACTION_PROJECTION_CACHE.get()
    if existing is not None:
        yield
        return
    token = _INTERACTION_PROJECTION_CACHE.set(_InteractionProjectionCache({}, {}))
    try:
        yield
    finally:
        _INTERACTION_PROJECTION_CACHE.reset(token)


def with_interaction_projection_scope(function):
    """Run one interpreter entrypoint with exact-snapshot interaction reuse."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with interaction_projection_scope():
            return function(*args, **kwargs)
    return wrapped


ROLE_NAMES = (
    "vocabulary-member",
    "control",
    "event",
    "target",
    "input",
    "precondition",
    "action",
    "subject",
    "policy",
    "authorization-action",
    "authorization-object",
    "authorization-scope",
    "authorization-interface",
    "authorization-purpose",
    "authorization-classification",
    "authorization-audience",
    "authorization-lifecycle-state",
    "authorization-operational-state",
    "release-policy",
    "release-authorization-action",
    "release-authorization-object",
    "release-authorization-scope",
    "release-authorization-interface",
    "release-authorization-purpose",
    "release-authorization-classification",
    "release-authorization-audience",
    "release-authorization-lifecycle-state",
    "release-authorization-operational-state",
    "optimistic-view",
    "outcome",
    "failure",
    "lifecycle",
    "version",
    "digest",
    "release-signature",
    "release-signing-key",
    "release-signing-key-version",
    "evidence",
    "reviewer",
)

STATE_NAMES = ("draft", "released")

_SINGLE_REQUIRED = (
    "control",
    "event",
    "target",
    "action",
    "subject",
    "policy",
    "authorization-action",
    "authorization-object",
    "lifecycle",
    "version",
    "digest",
    "release-signature",
    "release-signing-key",
    "release-signing-key-version",
)


@dataclass(frozen=True, slots=True)
class InteractionProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown interaction role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown interaction state %r" % name) from exc


@dataclass(frozen=True, slots=True)
class InteractionBuild:
    root_id: str


@dataclass(frozen=True, slots=True)
class Interaction:
    root_id: str
    control_root: str
    event_root: str
    target_root: str
    input_roots: tuple[str, ...]
    precondition_roots: tuple[str, ...]
    action_root: str
    subject_root: str
    policy_root: str
    authorization_action_root: str
    authorization_object_root: str
    authorization_scope_roots: tuple[str, ...]
    authorization_interface_root: str | None
    authorization_purpose_root: str | None
    authorization_classification_root: str | None
    authorization_audience_root: str | None
    authorization_lifecycle_state_root: str | None
    authorization_operational_state_root: str | None
    release_policy_root: str | None
    release_authorization_action_root: str | None
    release_authorization_object_root: str | None
    release_authorization_scope_roots: tuple[str, ...]
    release_authorization_interface_root: str | None
    release_authorization_purpose_root: str | None
    release_authorization_classification_root: str | None
    release_authorization_audience_root: str | None
    release_authorization_lifecycle_state_root: str | None
    release_authorization_operational_state_root: str | None
    optimistic_view_root: str | None
    outcome_root: str | None
    failure_root: str | None
    lifecycle_root: str
    version_root: str
    digest_root: str
    release_signature_root: str
    release_signing_key_root: str
    release_signing_key_version_root: str
    evidence_roots: tuple[str, ...]
    reviewer_root: str | None


@dataclass(frozen=True, slots=True)
class InteractionExecution:
    interaction_root: str
    authorization: AuthorizationDecision
    rewrite: TransactionExecution


@dataclass(frozen=True, slots=True)
class InteractionAdmission:
    """Revision-bound authorization for one projected graph interaction."""

    interaction: Interaction
    authorization: AuthorizationDecision
    revision: int


class InteractionProjectionDenied(PermissionError):
    pass


class InteractionProjectionExpired(InteractionProjectionDenied):
    """The projected capability elapsed before any interaction executed."""


class InteractionReleaseDenied(PermissionError):
    pass


_RELEASE_MINT_KEY = object()


class InteractionReleaseHandle:
    """One-use process-held proof of an exact interaction review."""

    __slots__ = ("_fingerprint",)

    def __init__(self, key: object) -> None:
        if key is not _RELEASE_MINT_KEY:
            raise InteractionReleaseDenied(
                "interaction releases can only be minted by their broker"
            )
        self._fingerprint = secrets.token_hex(12)

    def __reduce_ex__(self, protocol):
        raise TypeError("interaction release handles cannot be serialized")


@dataclass(slots=True)
class _ReleaseEntry:
    interaction_root: str
    reviewer_root: str
    evidence_roots: tuple[str, ...]
    expires_at: float
    used: bool = False
    reservation: object | None = None


class InteractionReleaseBroker:
    """Trusted review boundary for one exact interaction definition."""

    def __init__(
        self,
        key_provider: SigningKeyProvider,
        *,
        key_id: str = "interaction-release",
    ) -> None:
        if not key_id:
            raise ValueError("interaction release signing key id is empty")
        self._key_provider = key_provider
        self._key_id = key_id
        self._entries: dict[InteractionReleaseHandle, _ReleaseEntry] = {}
        self._lock = threading.RLock()

    def mint_from_review(
        self,
        interaction_root: str,
        reviewer_root: str,
        evidence_roots: Iterable[str],
        *,
        lifetime_seconds: float = 120.0,
    ) -> InteractionReleaseHandle:
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError("interaction release lifetime must be within five minutes")
        evidence = tuple(sorted(evidence_roots))
        if not evidence or len(evidence) != len(set(evidence)):
            raise InvalidCell("interaction review evidence must be nonempty and unique")
        handle = InteractionReleaseHandle(_RELEASE_MINT_KEY)
        with self._lock:
            self._entries[handle] = _ReleaseEntry(
                interaction_root,
                reviewer_root,
                evidence,
                time.time() + lifetime_seconds,
            )
        return handle

    def reserve(
        self,
        handle: object,
        interaction_root: str,
        reviewer_root: str,
        evidence_roots: Iterable[str],
    ) -> object:
        evidence = tuple(sorted(evidence_roots))
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionReleaseHandle else None
            )
            if entry is None:
                raise InteractionReleaseDenied("unknown interaction release handle")
            if entry.used:
                raise InteractionReleaseDenied(
                    "interaction release handle was already used"
                )
            if entry.reservation is not None:
                raise InteractionReleaseDenied(
                    "interaction release handle is already reserved"
                )
            if time.time() >= entry.expires_at:
                raise InteractionReleaseDenied("interaction release handle expired")
            if (
                entry.interaction_root != interaction_root
                or entry.reviewer_root != reviewer_root
                or entry.evidence_roots != evidence
            ):
                raise InteractionReleaseDenied(
                    "interaction release does not match the reviewed definition"
                )
            reservation = object()
            entry.reservation = reservation
            return reservation

    def finalize(self, handle: object, reservation: object) -> None:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionReleaseHandle else None
            )
            if entry is None or entry.reservation is not reservation:
                raise InteractionReleaseDenied(
                    "interaction release reservation is invalid"
                )
            entry.used = True
            entry.reservation = None

    def cancel(self, handle: object, reservation: object) -> None:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionReleaseHandle else None
            )
            if entry is None or entry.reservation is not reservation:
                raise InteractionReleaseDenied(
                    "interaction release reservation is invalid"
                )
            entry.reservation = None

    def consume(
        self,
        handle: object,
        interaction_root: str,
        reviewer_root: str,
        evidence_roots: Iterable[str],
    ) -> None:
        """Compatibility helper for callers that consume without a commit."""
        reservation = self.reserve(
            handle, interaction_root, reviewer_root, evidence_roots
        )
        self.finalize(handle, reservation)

    def sign_release(self, digest: bytes) -> tuple[str, int, str]:
        reference = self._key_provider.current_reference(self._key_id)
        signature = self._key_provider.sign(
            reference.key_id, reference.version, bytes(digest)
        )
        return reference.key_id, reference.version, signature

    def verify_release(
        self,
        *,
        key_id: str,
        version: int,
        digest: bytes,
        signature: str,
    ) -> bool:
        if not hmac.compare_digest(key_id, self._key_id):
            return False
        return self._key_provider.verify(
            key_id, version, bytes(digest), signature
        )


_PROJECTION_MINT_KEY = object()


class InteractionProjectionHandle:
    """Process-held possession proof for one authenticated browser view."""

    __slots__ = ("_fingerprint",)

    def __init__(self, key: object) -> None:
        if key is not _PROJECTION_MINT_KEY:
            raise InteractionProjectionDenied(
                "projection handles can only be minted by their broker"
            )
        self._fingerprint = secrets.token_hex(12)

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def __reduce_ex__(self, protocol):
        raise TypeError("interaction projection handles cannot be serialized")


@dataclass(frozen=True, slots=True)
class InteractionProjectionLease:
    session_root: str
    subject_root: str
    view_root: str
    revision: int
    bindings: Mapping[str, str]
    requires_release: bool
    issued_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class InteractionProjectionIssue:
    """One lease and the exact interaction batch verified while issuing it."""

    lease: InteractionProjectionLease
    interactions: tuple[Interaction, ...]

    def __reduce_ex__(self, protocol):
        raise TypeError("interaction projection issues cannot be serialized")


@dataclass(slots=True)
class _ProjectionEntry:
    session_root: str
    subject_root: str
    view_root: str
    requires_release: bool
    active: bool = True
    lease: InteractionProjectionLease | None = None
    admitted_nontransaction_action_roots: frozenset[str] = frozenset()


class InteractionProjectionBroker:
    """Bind callable graph interactions to one exact projected revision."""

    def __init__(
        self,
        release_broker: InteractionReleaseBroker | None = None,
    ) -> None:
        self._release_broker = release_broker
        self._entries: dict[InteractionProjectionHandle, _ProjectionEntry] = {}
        self._lock = threading.RLock()

    def mint(
        self,
        snapshot: Snapshot,
        *,
        session_root: str,
        subject_root: str,
        view_root: str,
        require_released: bool = False,
    ) -> InteractionProjectionHandle:
        required = {session_root, subject_root, view_root}
        if any(_root not in snapshot.cells for _root in required):
            raise InvalidCell("projection authority root is missing")
        handle = InteractionProjectionHandle(_PROJECTION_MINT_KEY)
        with self._lock:
            self._entries[handle] = _ProjectionEntry(
                session_root, subject_root, view_root, require_released
            )
        return handle

    def issue(
        self,
        handle: object,
        snapshot: Snapshot,
        protocol: InteractionProtocol,
        control_roots: Iterable[str],
        interaction_roots: Iterable[str],
        *,
        rule_protocol: RuleProtocol,
        transaction_protocol: TransactionProtocol,
        require_released: bool = False,
        admitted_nontransaction_action_roots: Iterable[str] | None = None,
        lifetime_seconds: float = 60.0,
        now: float | None = None,
        budget: int = 10_000,
    ) -> InteractionProjectionLease:
        return self.issue_with_interactions(
            handle,
            snapshot,
            protocol,
            control_roots,
            interaction_roots,
            rule_protocol=rule_protocol,
            transaction_protocol=transaction_protocol,
            require_released=require_released,
            admitted_nontransaction_action_roots=(
                admitted_nontransaction_action_roots
            ),
            lifetime_seconds=lifetime_seconds,
            now=now,
            budget=budget,
        ).lease

    def issue_with_interactions(
        self,
        handle: object,
        snapshot: Snapshot,
        protocol: InteractionProtocol,
        control_roots: Iterable[str],
        interaction_roots: Iterable[str],
        *,
        rule_protocol: RuleProtocol,
        transaction_protocol: TransactionProtocol,
        require_released: bool = False,
        admitted_nontransaction_action_roots: Iterable[str] | None = None,
        lifetime_seconds: float = 60.0,
        now: float | None = None,
        budget: int = 10_000,
        projected_interactions: tuple[Interaction, ...] | None = None,
    ) -> InteractionProjectionIssue:
        """Issue a lease over these interactions for this snapshot.

        ``projected_interactions`` lets a caller hand in the interactions it
        already read and verified against this same protocol -- a server
        whose interaction cells are process constants re-reads nothing per
        revision. Every other check here still runs on the snapshot given.
        """
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError("projection lease lifetime must be within five minutes")
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionProjectionHandle else None
            )
            if entry is None:
                raise InteractionProjectionDenied("unknown projection handle")
            if not entry.active:
                raise InteractionProjectionDenied("projection handle is revoked")
            required = {entry.session_root, entry.subject_root, entry.view_root}
            if any(root_id not in snapshot.cells for root_id in required):
                raise InteractionProjectionDenied(
                    "projection authority root no longer exists"
                )
            controls = tuple(control_roots)
            if len(controls) != len(set(controls)):
                raise InvalidCell("projected control identity is duplicated")
            interactions = tuple(interaction_roots)
            enforce_release = entry.requires_release or require_released
            projected_bindings: dict[str, list[str]] = {
                root_id: [] for root_id in controls
            }
            if projected_interactions is None:
                projected_interactions = (
                    _read_interactions_with_verified_protocol(
                        snapshot,
                        protocol,
                        interactions,
                        budget=budget,
                    )
                )
            elif tuple(
                item.root_id for item in projected_interactions
            ) != interactions:
                raise InvalidCell(
                    "pre-read interactions do not match the projected set"
                )
            for interaction in projected_interactions:
                if interaction.control_root not in projected_bindings:
                    raise InvalidCell(
                        "interaction control is outside the projection"
                    )
                projected_bindings[interaction.control_root].append(
                    interaction.root_id
                )
            if any(
                len(roots) != 1 for roots in projected_bindings.values()
            ):
                raise InvalidCell(
                    "each enabled projected control requires exactly one interaction"
                )
            bindings = MappingProxyType({
                control_root: roots[0]
                for control_root, roots in projected_bindings.items()
            })
            # A renewal with no new declaration keeps the exact capability
            # boundary that the trusted projector established for this handle.
            # A fresh handle therefore remains transaction-only by default.
            admitted_actions = (
                entry.admitted_nontransaction_action_roots
                if admitted_nontransaction_action_roots is None
                else frozenset(admitted_nontransaction_action_roots)
            )
            if any(
                root_id not in snapshot.cells for root_id in admitted_actions
            ):
                raise InteractionProjectionDenied(
                    "projected nontransaction action root is missing"
                )
            accepted_interactions: list[Interaction] = []
            for interaction in projected_interactions:
                if enforce_release:
                    if self._release_broker is None:
                        raise InteractionProjectionDenied(
                            "released projection lacks signing authority"
                        )
                    interaction = verify_released_interaction(
                        snapshot,
                        protocol,
                        transaction_protocol,
                        rule_protocol,
                        interaction.root_id,
                        release_broker=self._release_broker,
                        budget=budget,
                    )
                else:
                    if interaction.action_root in admitted_actions:
                        if (
                            not interaction.input_roots
                            or len(interaction.input_roots)
                            != len(set(interaction.input_roots))
                            or any(
                                root_id not in snapshot.cells
                                for root_id in interaction.input_roots
                            )
                        ):
                            raise InteractionProjectionDenied(
                                "projected interaction input authority is invalid"
                            )
                    else:
                        _validate_action_inputs(
                            snapshot,
                            transaction_protocol,
                            rule_protocol,
                            interaction,
                            budget=budget,
                        )
                if interaction.subject_root != entry.subject_root:
                    raise InteractionProjectionDenied(
                        "projected interaction subject does not match the view"
                    )
                accepted_interactions.append(interaction)
            issued_at = time.time() if now is None else float(now)
            lease = InteractionProjectionLease(
                entry.session_root,
                entry.subject_root,
                entry.view_root,
                snapshot.revision,
                bindings,
                enforce_release,
                issued_at,
                issued_at + float(lifetime_seconds),
            )
            entry.admitted_nontransaction_action_roots = admitted_actions
            entry.lease = lease
            return InteractionProjectionIssue(
                lease,
                tuple(accepted_interactions),
            )

    def resolve(
        self,
        handle: object,
        snapshot: Snapshot,
        *,
        expected_revision: int,
        control_root: str,
        interaction_root: str,
        now: float | None = None,
    ) -> InteractionProjectionLease:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionProjectionHandle else None
            )
            if entry is None:
                raise InteractionProjectionDenied("unknown projection handle")
            if not entry.active:
                raise InteractionProjectionDenied("projection handle is revoked")
            lease = entry.lease
            if lease is None:
                raise InteractionProjectionDenied("projection lease was not issued")
            current = time.time() if now is None else float(now)
            if current >= lease.expires_at:
                raise InteractionProjectionExpired("projection lease expired")
            if (
                snapshot.revision != expected_revision
                or lease.revision != expected_revision
            ):
                raise Conflict(
                    "expected revision %s, projected revision is %s, current revision is %s"
                    % (expected_revision, lease.revision, snapshot.revision)
                )
            if lease.bindings.get(control_root) != interaction_root:
                raise InteractionProjectionDenied(
                    "interaction is not admitted for the projected control"
                )
            return lease

    def verify_released(
        self,
        snapshot: Snapshot,
        protocol: InteractionProtocol,
        transaction_protocol: TransactionProtocol,
        rule_protocol: RuleProtocol,
        interaction_root: str,
        *,
        budget: int = 10_000,
    ) -> Interaction:
        """Verify through the broker-owned release-signing authority."""
        if self._release_broker is None:
            raise InteractionProjectionDenied(
                "released projection lacks signing authority"
            )
        return verify_released_interaction(
            snapshot,
            protocol,
            transaction_protocol,
            rule_protocol,
            interaction_root,
            release_broker=self._release_broker,
            budget=budget,
        )

    def revoke(self, handle: object) -> None:
        with self._lock:
            entry = (
                self._entries.get(handle)
                if type(handle) is InteractionProjectionHandle else None
            )
            if entry is None:
                raise InteractionProjectionDenied("unknown projection handle")
            entry.active = False
            entry.lease = None


def bootstrap_interaction_protocol(
    store: CellStore,
    *,
    prefix: str = "interaction-protocol",
) -> InteractionProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(
            root_id,
            NULL_CELL_ID,
            NULL_CELL_ID,
            name.encode("ascii"),
        ))
    for name, root_id in states.items():
        batch.add(Cell(
            root_id,
            NULL_CELL_ID,
            NULL_CELL_ID,
            name.encode("ascii"),
        ))
    root_id = "%s:root" % prefix
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return InteractionProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
    )


def project_interaction_protocol(
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 256,
) -> InteractionProtocol:
    """Reconstruct the interaction vocabulary from its graph-held root."""
    members = read_relation(snapshot, root_id, budget=budget)
    if not members:
        raise InvalidCell("interaction protocol vocabulary is empty")
    vocabulary_roles = {member.role_id for member in members}
    if len(vocabulary_roles) != 1:
        raise InvalidCell(
            "interaction protocol vocabulary has inconsistent incidences"
        )
    vocabulary_role = next(iter(vocabulary_roles))
    by_label: dict[str, str] = {}
    for member in members:
        cell = snapshot.cells[member.participant_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("interaction protocol member is not terminal")
        try:
            label = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell(
                "interaction protocol member label is not ASCII"
            ) from exc
        if label in by_label:
            raise InvalidCell("interaction protocol repeats a member label")
        by_label[label] = member.participant_id
    expected = set(ROLE_NAMES).union(STATE_NAMES)
    if set(by_label) != expected:
        raise InvalidCell(
            "interaction protocol vocabulary is incomplete or extended"
        )
    if by_label["vocabulary-member"] != vocabulary_role:
        raise InvalidCell(
            "interaction protocol vocabulary role does not self-identify"
        )
    return InteractionProtocol(
        root_id,
        MappingProxyType({name: by_label[name] for name in ROLE_NAMES}),
        MappingProxyType({name: by_label[name] for name in STATE_NAMES}),
    )


def build_interaction(
    store: CellStore,
    protocol: InteractionProtocol,
    *,
    interaction_id: str,
    control_root: str,
    event_root: str,
    target_root: str,
    action_root: str,
    subject_root: str,
    policy_root: str,
    authorization_action_root: str,
    authorization_object_root: str,
    lifecycle_root: str | None = None,
    version: str = "0.1.0",
    evidence_roots: Iterable[str] = (),
    input_roots: Iterable[str] = (),
    precondition_roots: Iterable[str] = (),
    authorization_scope_roots: Iterable[str] = (),
    authorization_interface_root: str | None = None,
    authorization_purpose_root: str | None = None,
    authorization_classification_root: str | None = None,
    authorization_audience_root: str | None = None,
    authorization_lifecycle_state_root: str | None = None,
    authorization_operational_state_root: str | None = None,
    release_policy_root: str | None = None,
    release_authorization_action_root: str | None = None,
    release_authorization_object_root: str | None = None,
    release_authorization_scope_roots: Iterable[str] = (),
    release_authorization_interface_root: str | None = None,
    release_authorization_purpose_root: str | None = None,
    release_authorization_classification_root: str | None = None,
    release_authorization_audience_root: str | None = None,
    release_authorization_lifecycle_state_root: str | None = None,
    release_authorization_operational_state_root: str | None = None,
    optimistic_view_root: str | None = None,
    outcome_root: str | None = None,
    failure_root: str | None = None,
    batch: CellBatch | None = None,
) -> InteractionBuild:
    encoded_version = version.encode("utf-8")
    if not encoded_version:
        raise InvalidCell("interaction version cannot be empty")
    lifecycle = protocol.state("draft") if lifecycle_root is None else lifecycle_root
    evidence = tuple(evidence_roots)
    if len(evidence) != len(set(evidence)):
        raise InvalidCell("interaction evidence identities must be unique")
    release_authority = (
        release_policy_root,
        release_authorization_action_root,
        release_authorization_object_root,
    )
    release_scopes = tuple(release_authorization_scope_roots)
    release_context = (
        release_authorization_interface_root,
        release_authorization_purpose_root,
        release_authorization_classification_root,
        release_authorization_audience_root,
        release_authorization_lifecycle_state_root,
        release_authorization_operational_state_root,
    )
    if any(root is not None for root in release_authority) != all(
        root is not None for root in release_authority
    ):
        raise InvalidCell("interaction release authority must be complete")
    if (release_scopes or any(release_context)) and release_policy_root is None:
        raise InvalidCell("interaction release scope requires release authority")
    version_root = "%s:version" % interaction_id
    digest_root = "%s:digest" % interaction_id
    release_signature_root = "%s:release-signature" % interaction_id
    release_signing_key_root = "%s:release-signing-key" % interaction_id
    release_signing_key_version_root = (
        "%s:release-signing-key-version" % interaction_id
    )
    members = [
        (protocol.role("control"), control_root),
        (protocol.role("event"), event_root),
        (protocol.role("target"), target_root),
        (protocol.role("action"), action_root),
        (protocol.role("subject"), subject_root),
        (protocol.role("policy"), policy_root),
        (protocol.role("authorization-action"), authorization_action_root),
        (protocol.role("authorization-object"), authorization_object_root),
        (protocol.role("lifecycle"), lifecycle),
        (protocol.role("version"), version_root),
        (protocol.role("digest"), digest_root),
        (protocol.role("release-signature"), release_signature_root),
        (protocol.role("release-signing-key"), release_signing_key_root),
        (
            protocol.role("release-signing-key-version"),
            release_signing_key_version_root,
        ),
    ]
    members.extend((protocol.role("evidence"), root) for root in evidence)
    members.extend((protocol.role("input"), root) for root in input_roots)
    members.extend(
        (protocol.role("precondition"), root) for root in precondition_roots
    )
    members.extend(
        (protocol.role("authorization-scope"), root)
        for root in authorization_scope_roots
    )
    for role, root in (
        ("authorization-interface", authorization_interface_root),
        ("authorization-purpose", authorization_purpose_root),
        ("authorization-classification", authorization_classification_root),
        ("authorization-audience", authorization_audience_root),
        ("authorization-lifecycle-state", authorization_lifecycle_state_root),
        (
            "authorization-operational-state",
            authorization_operational_state_root,
        ),
    ):
        if root is not None:
            members.append((protocol.role(role), root))
    if release_policy_root is not None:
        members.extend((
            (protocol.role("release-policy"), release_policy_root),
            (
                protocol.role("release-authorization-action"),
                release_authorization_action_root,
            ),
            (
                protocol.role("release-authorization-object"),
                release_authorization_object_root,
            ),
        ))
        members.extend(
            (protocol.role("release-authorization-scope"), root)
            for root in release_scopes
        )
        for role, root in (
            (
                "release-authorization-interface",
                release_authorization_interface_root,
            ),
            (
                "release-authorization-purpose",
                release_authorization_purpose_root,
            ),
            (
                "release-authorization-classification",
                release_authorization_classification_root,
            ),
            (
                "release-authorization-audience",
                release_authorization_audience_root,
            ),
            (
                "release-authorization-lifecycle-state",
                release_authorization_lifecycle_state_root,
            ),
            (
                "release-authorization-operational-state",
                release_authorization_operational_state_root,
            ),
        ):
            if root is not None:
                members.append((protocol.role(role), root))
    for role, root in (
        ("optimistic-view", optimistic_view_root),
        ("outcome", outcome_root),
        ("failure", failure_root),
    ):
        if root is not None:
            members.append((protocol.role(role), root))
    owns_batch = batch is None
    if batch is None:
        batch = CellBatch(store)
    batch.add(Cell(version_root, NULL_CELL_ID, NULL_CELL_ID, encoded_version))
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    batch.add(Cell(
        release_signature_root, NULL_CELL_ID, NULL_CELL_ID, b""
    ))
    batch.add(Cell(
        release_signing_key_root, NULL_CELL_ID, NULL_CELL_ID, b""
    ))
    batch.add(Cell(
        release_signing_key_version_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"",
    ))
    batch.relation(members, relation_id=interaction_id)
    if owns_batch:
        batch.commit()
    return InteractionBuild(interaction_id)


def _for_role(
    members: tuple[RelationMember, ...],
    role_id: str,
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...],
    role_id: str,
    label: str,
) -> str:
    roots = _for_role(members, role_id)
    if len(roots) != 1:
        raise InvalidCell(
            "interaction requires exactly one %s participant" % label
        )
    return roots[0]


def _optional(
    members: tuple[RelationMember, ...],
    role_id: str,
    label: str,
) -> str | None:
    roots = _for_role(members, role_id)
    if len(roots) > 1:
        raise InvalidCell("interaction repeats %s participant" % label)
    return roots[0] if roots else None


def _read_interaction_with_verified_protocol(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    interaction_root: str,
    *,
    budget: int = 10_000,
) -> Interaction:
    cache = _INTERACTION_PROJECTION_CACHE.get()
    cache_key = (
        snapshot.revision,
        id(snapshot.cells),
        protocol.root_id,
        interaction_root,
    )
    cached = cache.interactions.get(cache_key) if cache is not None else None
    if cached is not None and budget >= cached[1]:
        return cached[0]
    members = read_relation(snapshot, interaction_root, budget=budget)
    if cached is not None:
        return cached[0]
    admitted_roles = frozenset(protocol.roles.values()) - {
        protocol.role("vocabulary-member")
    }
    if any(member.role_id not in admitted_roles for member in members):
        raise InvalidCell("interaction contains an undeclared protocol role")
    singles = {
        name: _one(members, protocol.role(name), name)
        for name in _SINGLE_REQUIRED
    }
    inputs = _for_role(members, protocol.role("input"))
    preconditions = _for_role(members, protocol.role("precondition"))
    authorization_scopes = _for_role(
        members, protocol.role("authorization-scope")
    )
    release_scopes = _for_role(
        members, protocol.role("release-authorization-scope")
    )
    evidence = _for_role(members, protocol.role("evidence"))
    for label, roots in (
        ("input", inputs),
        ("precondition", preconditions),
        ("authorization scope", authorization_scopes),
        ("release authorization scope", release_scopes),
        ("evidence", evidence),
    ):
        if len(roots) != len(set(roots)):
            raise InvalidCell("interaction repeats %s participant" % label)
    def optional(name: str, label: str) -> str | None:
        return _optional(members, protocol.role(name), label)

    interaction = Interaction(
        root_id=interaction_root,
        control_root=singles["control"],
        event_root=singles["event"],
        target_root=singles["target"],
        input_roots=inputs,
        precondition_roots=preconditions,
        action_root=singles["action"],
        subject_root=singles["subject"],
        policy_root=singles["policy"],
        authorization_action_root=singles["authorization-action"],
        authorization_object_root=singles["authorization-object"],
        authorization_scope_roots=authorization_scopes,
        authorization_interface_root=optional(
            "authorization-interface", "authorization interface"
        ),
        authorization_purpose_root=optional(
            "authorization-purpose", "authorization purpose"
        ),
        authorization_classification_root=optional(
            "authorization-classification", "authorization classification"
        ),
        authorization_audience_root=optional(
            "authorization-audience", "authorization audience"
        ),
        authorization_lifecycle_state_root=optional(
            "authorization-lifecycle-state", "authorization lifecycle state"
        ),
        authorization_operational_state_root=optional(
            "authorization-operational-state", "authorization operational state"
        ),
        release_policy_root=optional("release-policy", "release policy"),
        release_authorization_action_root=_optional(
            members,
            protocol.role("release-authorization-action"),
            "release authorization action",
        ),
        release_authorization_object_root=_optional(
            members,
            protocol.role("release-authorization-object"),
            "release authorization object",
        ),
        release_authorization_scope_roots=release_scopes,
        release_authorization_interface_root=optional(
            "release-authorization-interface", "release authorization interface"
        ),
        release_authorization_purpose_root=optional(
            "release-authorization-purpose", "release authorization purpose"
        ),
        release_authorization_classification_root=optional(
            "release-authorization-classification",
            "release authorization classification",
        ),
        release_authorization_audience_root=optional(
            "release-authorization-audience", "release authorization audience"
        ),
        release_authorization_lifecycle_state_root=optional(
            "release-authorization-lifecycle-state",
            "release authorization lifecycle state",
        ),
        release_authorization_operational_state_root=optional(
            "release-authorization-operational-state",
            "release authorization operational state",
        ),
        optimistic_view_root=optional("optimistic-view", "optimistic view"),
        outcome_root=optional("outcome", "outcome"),
        failure_root=optional("failure", "failure"),
        lifecycle_root=singles["lifecycle"],
        version_root=singles["version"],
        digest_root=singles["digest"],
        release_signature_root=singles["release-signature"],
        release_signing_key_root=singles["release-signing-key"],
        release_signing_key_version_root=(
            singles["release-signing-key-version"]
        ),
        evidence_roots=evidence,
        reviewer_root=optional("reviewer", "reviewer"),
    )
    if cache is not None:
        cache.interactions[cache_key] = (interaction, budget)
    return interaction


def _read_interactions_with_verified_protocol(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    interaction_roots: Iterable[str],
    *,
    budget: int = 10_000,
) -> tuple[Interaction, ...]:
    """Read a bounded interaction set after one exact protocol verification."""
    cache = _INTERACTION_PROJECTION_CACHE.get()
    protocol_key = (snapshot.revision, id(snapshot.cells), protocol.root_id)
    cached_protocol = (
        cache.protocols.get(protocol_key) if cache is not None else None
    )
    if cached_protocol is None:
        projected_protocol = project_interaction_protocol(
            snapshot, protocol.root_id, budget=budget
        )
        if cache is not None:
            cache.protocols[protocol_key] = (projected_protocol, budget)
    else:
        projected_protocol, verified_budget = cached_protocol
        if budget < verified_budget:
            read_relation(snapshot, protocol.root_id, budget=budget)
    if projected_protocol != protocol:
        raise InvalidCell("interaction protocol authority drifted")
    return tuple(
        _read_interaction_with_verified_protocol(
            snapshot,
            protocol,
            interaction_root,
            budget=budget,
        )
        for interaction_root in interaction_roots
    )


def read_interaction(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    interaction_root: str,
    *,
    budget: int = 10_000,
) -> Interaction:
    return _read_interactions_with_verified_protocol(
        snapshot,
        protocol,
        (interaction_root,),
        budget=budget,
    )[0]


def _interaction_content_digest(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    interaction: Interaction,
    *,
    reviewer_root: str | None = None,
    budget: int = 10_000,
) -> bytes:
    """Fingerprint callable meaning while preserving mutable data identities."""
    reviewer = interaction.reviewer_root or reviewer_root
    if reviewer is None:
        raise InvalidCell("interaction digest requires a reviewer")
    if interaction.reviewer_root is not None and reviewer_root not in (
        None, interaction.reviewer_root
    ):
        raise InvalidCell("interaction reviewer does not match the release")

    canonical = bytearray(b"ArchHub/universal-cell-interaction/v1\x00")

    def field(value: bytes) -> None:
        canonical.extend(len(value).to_bytes(8, "big"))
        canonical.extend(value)

    field(interaction.root_id.encode("utf-8"))
    excluded_roles = {
        protocol.role("lifecycle"),
        protocol.role("digest"),
        protocol.role("release-signature"),
        protocol.role("release-signing-key"),
        protocol.role("release-signing-key-version"),
        protocol.role("reviewer"),
    }
    members = read_relation(snapshot, interaction.root_id, budget=budget)
    for member in sorted(
        (
            member for member in members
            if member.role_id not in excluded_roles
        ),
        key=lambda member: (member.role_id, member.participant_id),
    ):
        field(member.role_id.encode("utf-8"))
        field(member.participant_id.encode("utf-8"))

    field(b"reviewer")
    field(reviewer.encode("utf-8"))
    field(b"action-transaction")
    field(transaction_content_digest(
        snapshot,
        transaction_protocol,
        rule_protocol,
        interaction.action_root,
        budget=budget,
    ))
    for precondition_root in sorted(interaction.precondition_roots):
        field(b"precondition-rule")
        field(precondition_root.encode("utf-8"))
        field(rule_content_digest(
            snapshot,
            rule_protocol,
            precondition_root,
            budget=budget,
        ))

    content_roots = (
        ("version", interaction.version_root),
        ("event", interaction.event_root),
        *(("evidence", root) for root in interaction.evidence_roots),
        *(((("optimistic-view", interaction.optimistic_view_root),))
          if interaction.optimistic_view_root is not None else ()),
        *(((("outcome", interaction.outcome_root),))
          if interaction.outcome_root is not None else ()),
        *(((("failure", interaction.failure_root),))
          if interaction.failure_root is not None else ()),
    )
    for label, root in sorted(content_roots):
        field(label.encode("ascii"))
        field(root.encode("utf-8"))
        field(graph_content_digest(snapshot, root, budget=budget))
    return hashlib.sha256(canonical).hexdigest().encode("ascii")


def _validate_action_inputs(
    snapshot: Snapshot,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    interaction: Interaction,
    *,
    budget: int,
) -> None:
    transaction = read_transaction(
        snapshot,
        transaction_protocol,
        interaction.action_root,
        budget=budget,
    )
    if interaction.target_root not in {
        step.target_root for step in transaction.steps
    }:
        raise InvalidCell(
            "interaction target is not a continuing transaction target"
        )
    constant_inputs = frozenset(
        constant
        for step in transaction.steps
        for constant in read_rule(
            snapshot, rule_protocol, step.rule_root, budget=budget
        ).replacement_constants.values()
    )
    if not set(interaction.input_roots).issubset(constant_inputs):
        raise InvalidCell(
            "interaction input is not explicitly bound into its action rule"
        )


def release_interaction(
    store: CellStore,
    protocol: InteractionProtocol,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    broker: InteractionReleaseBroker,
    handle: object,
    interaction_root: str,
    *,
    reviewer_root: str,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    budget: int = 10_000,
) -> int:
    """Atomically bind one reviewed draft to its exact callable definition."""
    snapshot = store.snapshot()
    interaction = read_interaction(
        snapshot, protocol, interaction_root, budget=budget
    )
    if interaction.lifecycle_root != protocol.state("draft"):
        raise InvalidCell("only a draft interaction can be released")
    if interaction.reviewer_root is not None:
        raise InvalidCell("draft interaction already records a reviewer")
    release_authority = (
        interaction.release_policy_root,
        interaction.release_authorization_action_root,
        interaction.release_authorization_object_root,
    )
    if any(root is None for root in release_authority):
        raise InvalidCell("interaction release authority is incomplete")
    if (
        not interaction.evidence_roots
        or len(interaction.evidence_roots) != len(set(interaction.evidence_roots))
    ):
        raise InvalidCell("interaction release requires unique review evidence")
    required = {
        reviewer_root,
        interaction.version_root,
        interaction.digest_root,
        interaction.release_signature_root,
        interaction.release_signing_key_root,
        interaction.release_signing_key_version_root,
        *interaction.evidence_roots,
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("interaction release authority or evidence is missing")
    identity = authentication_broker.resolve(authentication_context)
    if identity.subject_root != reviewer_root:
        raise InteractionReleaseDenied(
            "interaction reviewer does not match authenticated identity"
        )
    require_authorization(
        snapshot,
        authorization_protocol,
        interaction.release_policy_root,
        authentication_broker,
        authentication_context,
        AuthorizationRequest(
            action_root=interaction.release_authorization_action_root,
            object_root=interaction.release_authorization_object_root,
            resource_lineage_roots=interaction.release_authorization_scope_roots,
            interface_root=interaction.release_authorization_interface_root,
            purpose_root=interaction.release_authorization_purpose_root,
            classification_root=(
                interaction.release_authorization_classification_root
            ),
            audience_root=interaction.release_authorization_audience_root,
            lifecycle_state_root=(
                interaction.release_authorization_lifecycle_state_root
            ),
            operational_state_root=(
                interaction.release_authorization_operational_state_root
            ),
        ),
    )
    _validate_action_inputs(
        snapshot,
        transaction_protocol,
        rule_protocol,
        interaction,
        budget=budget,
    )
    for precondition_root in interaction.precondition_roots:
        read_rule(snapshot, rule_protocol, precondition_root, budget=budget)
    version_cell = snapshot.cells[interaction.version_root]
    digest_cell = snapshot.cells[interaction.digest_root]
    signature_cell = snapshot.cells[interaction.release_signature_root]
    signing_key_cell = snapshot.cells[interaction.release_signing_key_root]
    signing_key_version_cell = snapshot.cells[
        interaction.release_signing_key_version_root
    ]
    if (
        version_cell.link0 != NULL_CELL_ID
        or version_cell.link1 != NULL_CELL_ID
        or not version_cell.atom
    ):
        raise InvalidCell("interaction version must be a nonempty terminal cell")
    if (
        digest_cell.link0 != NULL_CELL_ID
        or digest_cell.link1 != NULL_CELL_ID
        or digest_cell.atom
    ):
        raise InvalidCell("draft interaction digest cell is invalid")
    for label, cell in (
        ("release signature", signature_cell),
        ("release signing key", signing_key_cell),
        ("release signing key version", signing_key_version_cell),
    ):
        if (
            cell.link0 != NULL_CELL_ID
            or cell.link1 != NULL_CELL_ID
            or cell.atom
        ):
            raise InvalidCell("draft interaction %s cell is invalid" % label)

    digest = _interaction_content_digest(
        snapshot,
        protocol,
        transaction_protocol,
        rule_protocol,
        interaction,
        reviewer_root=reviewer_root,
        budget=budget,
    )
    members = read_relation(snapshot, interaction_root, budget=budget)
    lifecycle_member = next(
        member for member in members
        if member.role_id == protocol.role("lifecycle")
    )
    lifecycle_incidence = snapshot.cells[lifecycle_member.incidence_id]
    append = prepare_append_relation_member(
        snapshot,
        interaction_root,
        protocol.role("reviewer"),
        reviewer_root,
        budget=budget,
    )
    reservation = broker.reserve(
        handle,
        interaction_root,
        reviewer_root,
        interaction.evidence_roots,
    )
    try:
        key_id, key_version, signature = broker.sign_release(digest)
        key_id_atom = key_id.encode("ascii")
        key_version_atom = str(key_version).encode("ascii")
        signature_atom = signature.encode("ascii")
        if not key_id_atom or not signature_atom:
            raise InteractionReleaseDenied(
                "interaction release signature is incomplete"
            )
        revision = store.commit(
            snapshot.revision,
            create=append.create,
            replace=(
                *append.replace,
                Cell(
                    lifecycle_incidence.id,
                    lifecycle_incidence.link0,
                    protocol.state("released"),
                    lifecycle_incidence.atom,
                ),
                Cell(
                    digest_cell.id,
                    digest_cell.link0,
                    digest_cell.link1,
                    digest,
                ),
                Cell(
                    signature_cell.id,
                    signature_cell.link0,
                    signature_cell.link1,
                    signature_atom,
                ),
                Cell(
                    signing_key_cell.id,
                    signing_key_cell.link0,
                    signing_key_cell.link1,
                    key_id_atom,
                ),
                Cell(
                    signing_key_version_cell.id,
                    signing_key_version_cell.link0,
                    signing_key_version_cell.link1,
                    key_version_atom,
                ),
            ),
        )
    except BaseException:
        broker.cancel(handle, reservation)
        raise
    broker.finalize(handle, reservation)
    return revision


def verify_released_interaction(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    interaction_root: str,
    *,
    release_broker: InteractionReleaseBroker,
    budget: int = 10_000,
) -> Interaction:
    interaction = read_interaction(
        snapshot, protocol, interaction_root, budget=budget
    )
    if interaction.lifecycle_root != protocol.state("released"):
        raise InvalidCell("interaction is not released")
    if interaction.reviewer_root is None or not interaction.evidence_roots:
        raise InvalidCell("released interaction lacks review evidence")
    recorded = snapshot.cells[interaction.digest_root].atom
    expected = _interaction_content_digest(
        snapshot,
        protocol,
        transaction_protocol,
        rule_protocol,
        interaction,
        budget=budget,
    )
    if not recorded or not hmac.compare_digest(recorded, expected):
        raise InvalidCell("released interaction digest does not match behavior")
    signature_cell = snapshot.cells[interaction.release_signature_root]
    signing_key_cell = snapshot.cells[interaction.release_signing_key_root]
    version_cell = snapshot.cells[interaction.release_signing_key_version_root]
    for label, cell in (
        ("release signature", signature_cell),
        ("release signing key", signing_key_cell),
        ("release signing key version", version_cell),
    ):
        if (
            cell.link0 != NULL_CELL_ID
            or cell.link1 != NULL_CELL_ID
            or not cell.atom
        ):
            raise InvalidCell("released interaction %s is invalid" % label)
    try:
        key_id = signing_key_cell.atom.decode("ascii")
        key_version = int(version_cell.atom.decode("ascii"))
        signature = signature_cell.atom.decode("ascii")
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("released interaction signature metadata is invalid") from exc
    if key_version < 1 or not release_broker.verify_release(
        key_id=key_id,
        version=key_version,
        digest=expected,
        signature=signature,
    ):
        raise InvalidCell("released interaction signature is invalid")
    return interaction


def project_control_interactions(
    snapshot: Snapshot,
    protocol: InteractionProtocol,
    control_roots: Iterable[str],
    interaction_roots: Iterable[str],
    *,
    budget: int = 10_000,
) -> Mapping[str, str]:
    """Require one admitted interaction for every enabled projected control."""
    controls = tuple(control_roots)
    if len(controls) != len(set(controls)):
        raise InvalidCell("projected control identity is duplicated")
    bindings: dict[str, list[str]] = {root: [] for root in controls}
    for interaction_root in interaction_roots:
        interaction = read_interaction(
            snapshot, protocol, interaction_root, budget=budget
        )
        if interaction.control_root not in bindings:
            raise InvalidCell("interaction control is outside the projection")
        bindings[interaction.control_root].append(interaction.root_id)
    if any(len(roots) != 1 for roots in bindings.values()):
        raise InvalidCell(
            "each enabled projected control requires exactly one interaction"
        )
    return MappingProxyType({
        control_root: roots[0] for control_root, roots in bindings.items()
    })


def execute_interaction(
    store: CellStore,
    interaction_protocol: InteractionProtocol,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    projection_broker: InteractionProjectionBroker,
    projection_handle: object,
    *,
    interaction_root: str,
    control_root: str,
    event_root: str,
    expected_revision: int,
    budget: int = 10_000,
) -> InteractionExecution:
    """Authorize and execute one admitted graph-only interaction."""
    admission = admit_interaction(
        store,
        interaction_protocol,
        transaction_protocol,
        rule_protocol,
        authorization_protocol,
        authentication_broker,
        authentication_context,
        projection_broker,
        projection_handle,
        interaction_root=interaction_root,
        control_root=control_root,
        event_root=event_root,
        expected_revision=expected_revision,
        budget=budget,
    )
    interaction = admission.interaction
    authorization_request = AuthorizationRequest(
        action_root=interaction.authorization_action_root,
        object_root=interaction.authorization_object_root,
        resource_lineage_roots=interaction.authorization_scope_roots,
        interface_root=interaction.authorization_interface_root,
        purpose_root=interaction.authorization_purpose_root,
        classification_root=interaction.authorization_classification_root,
        audience_root=interaction.authorization_audience_root,
        lifecycle_state_root=interaction.authorization_lifecycle_state_root,
        operational_state_root=interaction.authorization_operational_state_root,
    )

    def precommit_guard() -> None:
        current = store.snapshot()
        projection_broker.resolve(
            projection_handle,
            current,
            expected_revision=expected_revision,
            control_root=control_root,
            interaction_root=interaction_root,
        )
        require_authorization(
            current,
            authorization_protocol,
            interaction.policy_root,
            authentication_broker,
            authentication_context,
            authorization_request,
        )

    rewrite = execute_transaction(
        store,
        transaction_protocol,
        rule_protocol,
        interaction.action_root,
        expected_revision=expected_revision,
        precommit_guard=precommit_guard,
        budget=budget,
    )
    return InteractionExecution(
        interaction.root_id, admission.authorization, rewrite
    )


def admit_interaction(
    store: CellStore,
    interaction_protocol: InteractionProtocol,
    transaction_protocol: TransactionProtocol,
    rule_protocol: RuleProtocol,
    authorization_protocol: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    projection_broker: InteractionProjectionBroker,
    projection_handle: object,
    *,
    interaction_root: str,
    control_root: str,
    event_root: str,
    expected_revision: int,
    admitted_nontransaction_action_roots: Iterable[str] = (),
    budget: int = 10_000,
) -> InteractionAdmission:
    """Verify one lease, identity, policy, input authority, and precondition."""
    snapshot = store.snapshot()
    if snapshot.revision != expected_revision:
        raise Conflict(
            "expected revision %s, current revision is %s"
            % (expected_revision, snapshot.revision)
        )
    lease = projection_broker.resolve(
        projection_handle,
        snapshot,
        expected_revision=expected_revision,
        control_root=control_root,
        interaction_root=interaction_root,
    )
    interaction = read_interaction(
        snapshot, interaction_protocol, interaction_root, budget=budget
    )
    if lease.requires_release:
        interaction = projection_broker.verify_released(
            snapshot,
            interaction_protocol,
            transaction_protocol,
            rule_protocol,
            interaction_root,
            budget=budget,
        )
    if interaction.control_root != control_root:
        raise AuthorizationDenied("interaction control does not match the request")
    if interaction.event_root != event_root:
        raise AuthorizationDenied("interaction event does not match the request")
    identity = authentication_broker.resolve(authentication_context)
    if interaction.subject_root != identity.subject_root:
        raise AuthorizationDenied("interaction subject does not match identity")
    if interaction.target_root not in snapshot.cells:
        raise InvalidCell("interaction target is missing")

    decision = require_authorization(
        snapshot,
        authorization_protocol,
        interaction.policy_root,
        authentication_broker,
        authentication_context,
        AuthorizationRequest(
            action_root=interaction.authorization_action_root,
            object_root=interaction.authorization_object_root,
            resource_lineage_roots=interaction.authorization_scope_roots,
            interface_root=interaction.authorization_interface_root,
            purpose_root=interaction.authorization_purpose_root,
            classification_root=interaction.authorization_classification_root,
            audience_root=interaction.authorization_audience_root,
            lifecycle_state_root=interaction.authorization_lifecycle_state_root,
            operational_state_root=(
                interaction.authorization_operational_state_root
            ),
        ),
    )
    admitted_actions = frozenset(admitted_nontransaction_action_roots)
    if admitted_actions:
        if interaction.action_root not in admitted_actions:
            raise AuthorizationDenied(
                "interaction action is outside the projected authority"
            )
        if (
            not interaction.input_roots
            or len(interaction.input_roots) != len(set(interaction.input_roots))
            or any(
                root_id not in snapshot.cells
                for root_id in interaction.input_roots
            )
        ):
            raise InvalidCell("interaction input authority is invalid")
    else:
        _validate_action_inputs(
            snapshot,
            transaction_protocol,
            rule_protocol,
            interaction,
            budget=budget,
        )
    for precondition_root in interaction.precondition_roots:
        match_rule(
            store,
            rule_protocol,
            precondition_root,
            interaction.target_root,
            expected_revision=expected_revision,
            budget=budget,
        )
    return InteractionAdmission(interaction, decision, expected_revision)


__all__ = [
    "InteractionProtocol",
    "InteractionBuild",
    "Interaction",
    "InteractionExecution",
    "InteractionAdmission",
    "InteractionReleaseDenied",
    "InteractionReleaseHandle",
    "InteractionReleaseBroker",
    "InteractionProjectionDenied",
    "InteractionProjectionExpired",
    "InteractionProjectionHandle",
    "InteractionProjectionLease",
    "InteractionProjectionBroker",
    "interaction_projection_scope",
    "with_interaction_projection_scope",
    "bootstrap_interaction_protocol",
    "project_interaction_protocol",
    "build_interaction",
    "read_interaction",
    "release_interaction",
    "verify_released_interaction",
    "project_control_interactions",
    "admit_interaction",
    "execute_interaction",
]
