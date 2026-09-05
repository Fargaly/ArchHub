"""Signed relationship authority over the universal-cell graph.

Subjects, tenants, groups, scopes, and resources remain ordinary Cells.  This
module gives one generic relation protocol authority semantics without adding
physical node types.  A relationship only affects authorization when its exact
graph shape verifies against the process-held broker and its current generation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationProtocol,
    AuthorizationRequest,
    _AuthenticationEntry,
    require_authorization,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .cell_secret_keys import (
    MemorySigningKeyProvider,
    SigningKeyProvider,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "relationship-member",
    "source",
    "target",
    "kind",
    "tenant",
    "scope",
    "action",
    "state",
    "issuer",
    "changed-by",
    "issued-at",
    "changed-at",
    "expires-at",
    "generation",
    "reason",
    "evidence",
    "digest",
    "signature",
    "key-reference",
    "key-version",
)

KIND_NAMES = (
    "membership",
    "delegation",
    "audience-binding",
)

STATE_NAMES = (
    "active",
    "revoked",
)


@dataclass(frozen=True, slots=True)
class IdentityProtocol:
    root_id: str
    roles: Mapping[str, str]
    kinds: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown identity role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class AuthorityRelationship:
    root_id: str
    source_root: str
    target_root: str
    kind_root: str
    tenant_root: str
    scope_root: str | None
    action_roots: tuple[str, ...]
    state_root: str
    issuer_root: str
    changed_by_root: str
    issued_at_root: str
    changed_at_root: str
    expires_at_root: str | None
    generation_root: str
    reason_root: str
    evidence_roots: tuple[str, ...]
    digest_root: str
    signature_root: str
    key_reference_root: str
    key_version_root: str
    state_incidence: str
    changed_by_incidence: str


@dataclass(frozen=True, slots=True)
class AuthorityRelationshipGrant:
    """One signed relationship region prepared for a caller-owned commit."""

    root_id: str
    generation: int
    cells: tuple[Cell, ...]


_VERIFIED_AUTHORITY_SNAPSHOT_KEY = object()


@dataclass(frozen=True, slots=True)
class VerifiedAuthoritySnapshot:
    """One sealed relationship verification pass for one immutable request."""

    _key: object
    _broker: object
    protocol_root: str
    revision: int
    evaluated_at: float
    registered_roots: tuple[str, ...]
    relationships: Mapping[str, AuthorityRelationship]
    active_relationships: tuple[AuthorityRelationship, ...]
    expired_roots: frozenset[str]
    invalid_reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        if self._key is not _VERIFIED_AUTHORITY_SNAPSHOT_KEY:
            raise TypeError(
                "verified authority snapshots can only be minted by verification"
            )


class RelationshipAuthorityDenied(PermissionError):
    pass


_ADMINISTRATION_KEY = object()
_EVIDENCE_REVISION_PATCH_KEY = object()
_REVOCATION_PATCH_KEY = object()


class RelationshipAdministrationHandle:
    __slots__ = ("_nonce",)

    def __init__(self, key: object) -> None:
        if key is not _ADMINISTRATION_KEY:
            raise TypeError("relationship authority handles are broker-only")
        self._nonce = secrets.token_hex(16)

    def __reduce_ex__(self, protocol):
        raise TypeError("relationship authority handles cannot be serialized")


@dataclass(frozen=True, slots=True)
class RelationshipEvidenceRevisionPatch:
    """Sealed relationship mutation prepared against one immutable snapshot."""

    _key: object
    _broker: object
    relationship_root: str
    expected_revision: int
    generation: int
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]

    def __post_init__(self) -> None:
        if self._key is not _EVIDENCE_REVISION_PATCH_KEY:
            raise TypeError(
                "relationship evidence patches can only be prepared by authority"
            )


@dataclass(frozen=True, slots=True)
class RelationshipRevocationPatch:
    """Sealed revocation prepared for one caller-owned atomic commit."""

    _key: object
    _broker: object
    relationship_root: str
    expected_revision: int
    generation: int
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]

    def __post_init__(self) -> None:
        if self._key is not _REVOCATION_PATCH_KEY:
            raise TypeError(
                "relationship revocation patches can only be prepared by authority"
            )


@dataclass(slots=True)
class _AdministrationEntry:
    administrator_root: str
    expires_at: float
    scope_digest: str | None = None
    used: bool = False


class RelationshipAuthorityBroker:
    """Process trust boundary for issuing and revoking graph relationships."""

    def __init__(
        self,
        trusted_administrators: Iterable[str],
        *,
        key_provider: SigningKeyProvider | None = None,
        key_id: str = "relationship-authority",
    ) -> None:
        administrators = frozenset(trusted_administrators)
        if not administrators:
            raise ValueError("relationship authority requires an administrator")
        self._administrators = administrators
        self._key_provider = (
            key_provider if key_provider is not None else MemorySigningKeyProvider(
                key_id, secrets.token_bytes(32)
            )
        )
        self._key_id = key_id
        self._handles: dict[
            RelationshipAdministrationHandle, _AdministrationEntry
        ] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.RLock()

    def mint_from_trusted_administrator(
        self,
        administrator_root: str,
        *,
        lifetime_seconds: float = 120.0,
    ) -> RelationshipAdministrationHandle:
        if administrator_root not in self._administrators:
            raise RelationshipAuthorityDenied(
                "identity is not a trusted relationship administrator"
            )
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError("relationship authority lifetime must be within five minutes")
        handle = RelationshipAdministrationHandle(_ADMINISTRATION_KEY)
        with self._lock:
            self._handles[handle] = _AdministrationEntry(
                administrator_root, time.time() + lifetime_seconds, None
            )
        return handle

    def mint_from_authorized_relationship_grant(
        self,
        snapshot: Snapshot,
        authorization_protocol: AuthorizationProtocol,
        policy_root: str,
        authentication_broker: AuthenticationBroker,
        authentication_context: object,
        request: AuthorizationRequest,
        *,
        administrator_root: str,
        relationship_id: str,
        source_root: str,
        target_root: str,
        kind: str,
        tenant_root: str,
        scope_root: str | None = None,
        action_roots: Iterable[str] = (),
        expires_at: float | None = None,
        reason: str,
        evidence_roots: Iterable[str] = (),
        lifetime_seconds: float = 120.0,
    ) -> RelationshipAdministrationHandle:
        """Mint one exact grant capability after released policy permits it."""
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError(
                "relationship authority lifetime must be within five minutes"
            )
        decision = require_authorization(
            snapshot,
            authorization_protocol,
            policy_root,
            authentication_broker,
            authentication_context,
            request,
        )
        governed_roots = {
            request.object_root, *request.resource_lineage_roots
        }
        if (
            decision.subject_root != administrator_root
            or request.object_root != tenant_root
            or request.action_root
            != authorization_protocol.actions["manage-policy"]
            or source_root not in governed_roots
            or target_root not in governed_roots
        ):
            raise RelationshipAuthorityDenied(
                "authorization does not govern the exact tenant relationship"
            )
        scope = _grant_administration_scope(
            relationship_id=relationship_id,
            source_root=source_root,
            target_root=target_root,
            kind=kind,
            tenant_root=tenant_root,
            scope_root=scope_root,
            action_roots=action_roots,
            expires_at=expires_at,
            reason=reason,
            evidence_roots=evidence_roots,
        )
        handle = RelationshipAdministrationHandle(_ADMINISTRATION_KEY)
        with self._lock:
            self._handles[handle] = _AdministrationEntry(
                administrator_root,
                time.time() + lifetime_seconds,
                hashlib.sha256(scope).hexdigest(),
            )
        return handle

    def mint_from_authorized_relationship_revoke(
        self,
        snapshot: Snapshot,
        identity_protocol: IdentityProtocol,
        authorization_protocol: AuthorizationProtocol,
        policy_root: str,
        authentication_broker: AuthenticationBroker,
        authentication_context: object,
        request: AuthorizationRequest,
        *,
        administrator_root: str,
        relationship_root: str,
        reason: str,
        lifetime_seconds: float = 120.0,
    ) -> RelationshipAdministrationHandle:
        """Mint one exact revocation capability after tenant policy permits it."""
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError(
                "relationship authority lifetime must be within five minutes"
            )
        relationship = verify_authority_relationship(
            snapshot, identity_protocol, self, relationship_root
        )
        decision = require_authorization(
            snapshot,
            authorization_protocol,
            policy_root,
            authentication_broker,
            authentication_context,
            request,
        )
        governed_roots = {
            request.object_root, *request.resource_lineage_roots
        }
        if (
            decision.subject_root != administrator_root
            or request.object_root != relationship.tenant_root
            or request.action_root
            != authorization_protocol.actions["manage-policy"]
            or relationship_root not in governed_roots
            or relationship.source_root not in governed_roots
            or relationship.target_root not in governed_roots
        ):
            raise RelationshipAuthorityDenied(
                "authorization does not govern the exact tenant revocation"
            )
        scope = _revoke_administration_scope(
            relationship_root, administrator_root, reason
        )
        handle = RelationshipAdministrationHandle(_ADMINISTRATION_KEY)
        with self._lock:
            self._handles[handle] = _AdministrationEntry(
                administrator_root,
                time.time() + lifetime_seconds,
                hashlib.sha256(scope).hexdigest(),
            )
        return handle

    def mint_from_authorized_relationship_evidence_revision(
        self,
        snapshot: Snapshot,
        identity_protocol: IdentityProtocol,
        authorization_protocol: AuthorizationProtocol,
        policy_root: str,
        authentication_broker: AuthenticationBroker,
        authentication_context: object,
        request: AuthorizationRequest,
        *,
        administrator_root: str,
        relationship_root: str,
        evidence_roots: Iterable[str],
        reason: str,
        lifetime_seconds: float = 120.0,
    ) -> RelationshipAdministrationHandle:
        """Mint one exact evidence-revision capability after policy permits it."""
        if lifetime_seconds <= 0 or lifetime_seconds > 300:
            raise ValueError(
                "relationship authority lifetime must be within five minutes"
            )
        relationship = verify_authority_relationship(
            snapshot, identity_protocol, self, relationship_root
        )
        evidence = tuple(dict.fromkeys(evidence_roots))
        decision = require_authorization(
            snapshot,
            authorization_protocol,
            policy_root,
            authentication_broker,
            authentication_context,
            request,
        )
        governed_roots = {
            request.object_root, *request.resource_lineage_roots
        }
        if (
            decision.subject_root != administrator_root
            or request.object_root != relationship.tenant_root
            or request.action_root
            != authorization_protocol.actions["manage-policy"]
            or relationship_root not in governed_roots
            or relationship.source_root not in governed_roots
            or relationship.target_root not in governed_roots
            or any(root not in governed_roots for root in evidence)
        ):
            raise RelationshipAuthorityDenied(
                "authorization does not govern the exact evidence revision"
            )
        scope = _revise_evidence_administration_scope(
            relationship_root, administrator_root, reason, evidence
        )
        handle = RelationshipAdministrationHandle(_ADMINISTRATION_KEY)
        with self._lock:
            self._handles[handle] = _AdministrationEntry(
                administrator_root,
                time.time() + lifetime_seconds,
                hashlib.sha256(scope).hexdigest(),
            )
        return handle

    def current_key_reference(self) -> tuple[str, int]:
        reference = self._key_provider.current_reference(self._key_id)
        return reference.key_id, reference.version

    def authorize_signature(
        self,
        handle: object,
        administrator_root: str,
        payload: bytes,
        key_reference: str,
        key_version: int,
        *,
        administration_scope: bytes,
        now: float | None = None,
    ) -> str:
        current = time.time() if now is None else now
        with self._lock:
            entry = (
                self._handles.get(handle)
                if type(handle) is RelationshipAdministrationHandle else None
            )
            if entry is None:
                raise RelationshipAuthorityDenied(
                    "unknown relationship authority handle"
                )
            if entry.used:
                raise RelationshipAuthorityDenied(
                    "relationship authority handle was already used"
                )
            if current >= entry.expires_at:
                raise RelationshipAuthorityDenied(
                    "relationship authority handle expired"
                )
            if entry.administrator_root != administrator_root:
                raise RelationshipAuthorityDenied(
                    "relationship authority administrator mismatch"
                )
            if entry.scope_digest is not None and not hmac.compare_digest(
                entry.scope_digest,
                hashlib.sha256(administration_scope).hexdigest(),
            ):
                raise RelationshipAuthorityDenied(
                    "relationship authority is scoped to another mutation"
                )
            material = self._key_provider.current_reference(self._key_id)
            if (
                material.key_id != key_reference
                or material.version != key_version
            ):
                raise RelationshipAuthorityDenied(
                    "relationship signing key changed before authorization"
                )
            entry.used = True
            return self._key_provider.sign(
                key_reference, key_version, payload
            )

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        key_reference: str,
        key_version: int,
    ) -> bool:
        return self._key_provider.verify(
            key_reference, key_version, payload, signature
        )

    def record_generation(self, relationship_root: str, generation: int) -> None:
        with self._lock:
            previous = self._generations.get(relationship_root, 0)
            if generation != previous + 1:
                raise RelationshipAuthorityDenied(
                    "relationship generation is not monotonic"
                )
            self._generations[relationship_root] = generation

    def verify_generation(self, relationship_root: str, generation: int) -> bool:
        with self._lock:
            return self._generations.get(relationship_root) == generation

    def restore_generation(self, relationship_root: str, generation: int) -> None:
        if generation < 1:
            raise RelationshipAuthorityDenied(
                "relationship generation must be positive"
            )
        with self._lock:
            previous = self._generations.get(relationship_root)
            if previous is not None and previous != generation:
                raise RelationshipAuthorityDenied(
                    "relationship generation restore conflicts with live authority"
                )
            self._generations[relationship_root] = generation


def _terminal(batch: CellBatch, root_id: str, value: str) -> str:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("identity authority values cannot be empty")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def _terminal_cell(root_id: str, value: str) -> Cell:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("identity authority values cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _atom(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("identity authority value is missing or invalid") from exc


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[RelationMember, ...]:
    return tuple(member for member in members if member.role_id == role_id)


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> RelationMember:
    found = _for_role(members, role_id)
    if len(found) != 1:
        raise InvalidCell("authority relationship requires one %s" % label)
    return found[0]


def _optional_one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> RelationMember | None:
    found = _for_role(members, role_id)
    if len(found) > 1:
        raise InvalidCell("authority relationship has multiple %s values" % label)
    return found[0] if found else None


def _payload(
    *,
    root_id: str,
    source_root: str,
    target_root: str,
    kind_root: str,
    tenant_root: str,
    scope_root: str | None,
    action_roots: Iterable[str],
    state_root: str,
    issuer_root: str,
    changed_by_root: str,
    issued_at: str,
    changed_at: str,
    expires_at: str | None,
    generation: int,
    reason: str,
    evidence_roots: Iterable[str],
    key_reference: str,
    key_version: int,
) -> bytes:
    fields = (
        root_id,
        source_root,
        target_root,
        kind_root,
        tenant_root,
        scope_root or "",
        *sorted(action_roots),
        state_root,
        issuer_root,
        changed_by_root,
        issued_at,
        changed_at,
        expires_at or "",
        str(generation),
        reason,
        *sorted(evidence_roots),
        key_reference,
        str(key_version),
    )
    digest = hashlib.sha256()
    for field in fields:
        raw = field.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.digest()


def _semantic_scope(fields: Iterable[str]) -> bytes:
    digest = hashlib.sha256()
    for field in fields:
        raw = field.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.digest()


def _grant_administration_scope(
    *,
    relationship_id: str,
    source_root: str,
    target_root: str,
    kind: str,
    tenant_root: str,
    scope_root: str | None,
    action_roots: Iterable[str],
    expires_at: float | None,
    reason: str,
    evidence_roots: Iterable[str],
) -> bytes:
    return _semantic_scope((
        "grant",
        relationship_id,
        source_root,
        target_root,
        kind,
        tenant_root,
        scope_root or "",
        *sorted(action_roots),
        "%.6f" % expires_at if expires_at is not None else "",
        reason,
        *sorted(evidence_roots),
    ))


def _revoke_administration_scope(
    relationship_root: str, administrator_root: str, reason: str
) -> bytes:
    return _semantic_scope((
        "revoke", relationship_root, administrator_root, reason
    ))


def _revise_evidence_administration_scope(
    relationship_root: str,
    administrator_root: str,
    reason: str,
    evidence_roots: Iterable[str],
) -> bytes:
    return _semantic_scope((
        "revise-evidence",
        relationship_root,
        administrator_root,
        reason,
        *sorted(evidence_roots),
    ))


def bootstrap_identity_protocol(
    store: CellStore, *, prefix: str = "identity-protocol"
) -> IdentityProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    kinds = {name: "%s:kind:%s" % (prefix, name) for name in KIND_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    batch = CellBatch(store)
    for name, root in (*roles.items(), *kinds.items(), *states.items()):
        _terminal(batch, root, name)
    root_id = prefix + ":root"
    batch.relation((
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in kinds.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ), relation_id=root_id)
    batch.commit()
    return IdentityProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(kinds),
        MappingProxyType(states),
    )


def prepare_authority_relationship_grant(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    relationship_id: str,
    source_root: str,
    target_root: str,
    kind: str,
    tenant_root: str,
    administrator_root: str,
    scope_root: str | None = None,
    action_roots: Iterable[str] = (),
    expires_at: float | None = None,
    reason: str = "granted",
    evidence_roots: Iterable[str] = (),
    pending_roots: Iterable[str] = (),
    now: float | None = None,
) -> AuthorityRelationshipGrant:
    """Prepare one exact signed relationship without publishing partial state."""
    if relationship_id in snapshot.cells:
        raise InvalidCell("authority relationship identity already exists")
    try:
        kind_root = protocol.kinds[kind]
    except KeyError as exc:
        raise InvalidCell("unknown authority relationship kind") from exc
    actions = tuple(dict.fromkeys(action_roots))
    evidence = tuple(dict.fromkeys(evidence_roots))
    pending = frozenset(pending_roots)
    if relationship_id in pending:
        raise InvalidCell("authority relationship identity collides with pending state")
    required = tuple(root for root in (
        source_root, target_root, tenant_root, administrator_root,
        scope_root, *actions, *evidence,
    ) if root is not None)
    if any(root not in snapshot.cells and root not in pending for root in required):
        raise InvalidCell("authority relationship references a missing cell")
    current = time.time() if now is None else now
    if expires_at is not None and expires_at <= current:
        raise InvalidCell("authority relationship expiry must be in the future")
    if not reason:
        raise InvalidCell("authority relationship requires a reason")
    issued = "%.6f" % current
    changed = issued
    expiry = "%.6f" % expires_at if expires_at is not None else None
    generation = 1
    state_root = protocol.states["active"]
    key_reference, key_version = broker.current_key_reference()
    signed = _payload(
        root_id=relationship_id,
        source_root=source_root,
        target_root=target_root,
        kind_root=kind_root,
        tenant_root=tenant_root,
        scope_root=scope_root,
        action_roots=actions,
        state_root=state_root,
        issuer_root=administrator_root,
        changed_by_root=administrator_root,
        issued_at=issued,
        changed_at=changed,
        expires_at=expiry,
        generation=generation,
        reason=reason,
        evidence_roots=evidence,
        key_reference=key_reference,
        key_version=key_version,
    )
    signature = broker.authorize_signature(
        administration_handle,
        administrator_root,
        signed,
        key_reference,
        key_version,
        administration_scope=_grant_administration_scope(
            relationship_id=relationship_id,
            source_root=source_root,
            target_root=target_root,
            kind=kind,
            tenant_root=tenant_root,
            scope_root=scope_root,
            action_roots=actions,
            expires_at=expires_at,
            reason=reason,
            evidence_roots=evidence,
        ),
        now=current,
    )
    digest = hashlib.sha256(signed).hexdigest()
    issued_root = relationship_id + ":issued-at"
    changed_root = relationship_id + ":changed-at"
    generation_root = relationship_id + ":generation"
    reason_root = relationship_id + ":reason"
    digest_root = relationship_id + ":digest"
    signature_root = relationship_id + ":signature"
    key_reference_root = relationship_id + ":key-reference"
    key_version_root = relationship_id + ":key-version"
    expiry_root = relationship_id + ":expires-at" if expiry is not None else None
    terminal_cells = (
        _terminal_cell(issued_root, issued),
        _terminal_cell(changed_root, changed),
        _terminal_cell(generation_root, "1"),
        _terminal_cell(reason_root, reason),
        _terminal_cell(digest_root, digest),
        _terminal_cell(signature_root, signature),
        _terminal_cell(key_reference_root, key_reference),
        _terminal_cell(key_version_root, str(key_version)),
        *((_terminal_cell(expiry_root, expiry),) if expiry_root else ()),
    )
    relation = compose_relation_cells((
        (protocol.roles["source"], source_root),
        (protocol.roles["target"], target_root),
        (protocol.roles["kind"], kind_root),
        (protocol.roles["tenant"], tenant_root),
        *((((protocol.roles["scope"], scope_root),) if scope_root else ())),
        *((protocol.roles["action"], root) for root in actions),
        (protocol.roles["state"], state_root),
        (protocol.roles["issuer"], administrator_root),
        (protocol.roles["changed-by"], administrator_root),
        (protocol.roles["issued-at"], issued_root),
        (protocol.roles["changed-at"], changed_root),
        *((((protocol.roles["expires-at"], expiry_root),) if expiry_root else ())),
        (protocol.roles["generation"], generation_root),
        (protocol.roles["reason"], reason_root),
        *((protocol.roles["evidence"], root) for root in evidence),
        (protocol.roles["digest"], digest_root),
        (protocol.roles["signature"], signature_root),
        (protocol.roles["key-reference"], key_reference_root),
        (protocol.roles["key-version"], key_version_root),
    ), relation_id=relationship_id)
    cells = (*terminal_cells, *relation.cells)
    cell_ids = tuple(cell.id for cell in cells)
    # `set(...).intersection(mapping)` walks the WHOLE graph: the snapshot is
    # a Mapping, not a set, so the intersection iterates every cell in it
    # through __iter__/__getitem__. Signing one relationship cost 186 ms of
    # nothing but that walk. The question is only "does any prepared id
    # already exist", so ask the graph about the handful of ids instead.
    if (
        len(cell_ids) != len(set(cell_ids))
        or any(cell_id in snapshot.cells for cell_id in cell_ids)
        or any(cell_id in pending for cell_id in cell_ids)
    ):
        raise InvalidCell("authority relationship prepared cells collide")
    return AuthorityRelationshipGrant(relationship_id, generation, tuple(cells))


def grant_authority_relationship(
    store: CellStore,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    relationship_id: str,
    source_root: str,
    target_root: str,
    kind: str,
    tenant_root: str,
    administrator_root: str,
    scope_root: str | None = None,
    action_roots: Iterable[str] = (),
    expires_at: float | None = None,
    reason: str = "granted",
    evidence_roots: Iterable[str] = (),
    now: float | None = None,
) -> str:
    """Issue one exact signed relationship and register it in the protocol."""
    snapshot = store.snapshot()
    prepared = prepare_authority_relationship_grant(
        snapshot,
        protocol,
        broker,
        administration_handle,
        relationship_id=relationship_id,
        source_root=source_root,
        target_root=target_root,
        kind=kind,
        tenant_root=tenant_root,
        administrator_root=administrator_root,
        scope_root=scope_root,
        action_roots=action_roots,
        expires_at=expires_at,
        reason=reason,
        evidence_roots=evidence_roots,
        now=now,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.roles["relationship-member"],
        prepared.root_id,
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(*prepared.cells, *patch.create),
        replace=patch.replace,
    )
    if revision <= snapshot.revision:
        raise InvalidCell("authority relationship was not committed")
    broker.record_generation(prepared.root_id, prepared.generation)
    return prepared.root_id


def read_authority_relationship(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    relationship_root: str,
) -> AuthorityRelationship:
    members = read_relation(snapshot, relationship_root, budget=128)
    source = _one(members, protocol.roles["source"], "source")
    target = _one(members, protocol.roles["target"], "target")
    kind = _one(members, protocol.roles["kind"], "kind")
    tenant = _one(members, protocol.roles["tenant"], "tenant")
    state = _one(members, protocol.roles["state"], "state")
    issuer = _one(members, protocol.roles["issuer"], "issuer")
    changed_by = _one(members, protocol.roles["changed-by"], "changed-by")
    issued = _one(members, protocol.roles["issued-at"], "issued-at")
    changed = _one(members, protocol.roles["changed-at"], "changed-at")
    generation = _one(members, protocol.roles["generation"], "generation")
    reason = _one(members, protocol.roles["reason"], "reason")
    digest = _one(members, protocol.roles["digest"], "digest")
    signature = _one(members, protocol.roles["signature"], "signature")
    key_reference = _one(
        members, protocol.roles["key-reference"], "key-reference"
    )
    key_version = _one(members, protocol.roles["key-version"], "key-version")
    scope = _optional_one(members, protocol.roles["scope"], "scope")
    expiry = _optional_one(members, protocol.roles["expires-at"], "expiry")
    return AuthorityRelationship(
        relationship_root,
        source.participant_id,
        target.participant_id,
        kind.participant_id,
        tenant.participant_id,
        scope.participant_id if scope else None,
        tuple(item.participant_id for item in _for_role(
            members, protocol.roles["action"]
        )),
        state.participant_id,
        issuer.participant_id,
        changed_by.participant_id,
        issued.participant_id,
        changed.participant_id,
        expiry.participant_id if expiry else None,
        generation.participant_id,
        reason.participant_id,
        tuple(item.participant_id for item in _for_role(
            members, protocol.roles["evidence"]
        )),
        digest.participant_id,
        signature.participant_id,
        key_reference.participant_id,
        key_version.participant_id,
        state.incidence_id,
        changed_by.incidence_id,
    )


def verify_authority_relationship(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    relationship_root: str,
    *,
    now: float | None = None,
    require_active: bool = True,
    allow_expired: bool = False,
    authority_snapshot: VerifiedAuthoritySnapshot | None = None,
) -> AuthorityRelationship:
    if authority_snapshot is not None:
        _require_compatible_authority_snapshot(
            snapshot,
            protocol,
            broker,
            authority_snapshot,
            now=authority_snapshot.evaluated_at if now is None else now,
        )
        try:
            relationship = authority_snapshot.relationships[relationship_root]
        except KeyError as exc:
            if relationship_root not in authority_snapshot.registered_roots:
                raise InvalidCell(
                    "authority relationship is not protocol-registered"
                ) from exc
            raise RelationshipAuthorityDenied(
                authority_snapshot.invalid_reasons.get(
                    relationship_root,
                    "authority relationship did not verify",
                )
            ) from exc
        if (
            relationship_root in authority_snapshot.expired_roots
            and not allow_expired
        ):
            raise RelationshipAuthorityDenied("authority relationship expired")
        if (
            require_active
            and relationship.state_root != protocol.states["active"]
        ):
            raise RelationshipAuthorityDenied("authority relationship is revoked")
        return relationship
    relationship, generation = _verify_signed_relationship_material(
        snapshot, protocol, broker, relationship_root
    )
    if not broker.verify_generation(relationship_root, generation):
        raise RelationshipAuthorityDenied(
            "authority relationship generation is stale or unknown"
        )
    expiry = (
        _atom(snapshot, relationship.expires_at_root)
        if relationship.expires_at_root else None
    )
    current = time.time() if now is None else now
    if expiry is not None:
        try:
            expiry_value = float(expiry)
        except ValueError as exc:
            raise InvalidCell("authority relationship expiry is invalid") from exc
        if current >= expiry_value and not allow_expired:
            raise RelationshipAuthorityDenied("authority relationship expired")
    if require_active and relationship.state_root != protocol.states["active"]:
        raise RelationshipAuthorityDenied("authority relationship is revoked")
    return relationship


def _require_compatible_authority_snapshot(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    authority_snapshot: VerifiedAuthoritySnapshot,
    *,
    now: float,
) -> None:
    if type(authority_snapshot) is not VerifiedAuthoritySnapshot:
        raise RelationshipAuthorityDenied("authority snapshot type is invalid")
    if authority_snapshot._broker is not broker:
        raise RelationshipAuthorityDenied("authority snapshot broker differs")
    if authority_snapshot.protocol_root != protocol.root_id:
        raise RelationshipAuthorityDenied("authority snapshot protocol differs")
    if authority_snapshot.revision != snapshot.revision:
        raise RelationshipAuthorityDenied("authority snapshot revision is stale")
    if authority_snapshot.evaluated_at != now:
        raise RelationshipAuthorityDenied("authority snapshot evaluation time differs")


def _verify_signed_relationship_material(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    relationship_root: str,
    *,
    registered_roots: frozenset[str] | None = None,
) -> tuple[AuthorityRelationship, int]:
    """Verify graph shape, digest, and signature without trusting RAM state."""
    registered = registered_roots
    if registered is None:
        registered = frozenset(
            member.participant_id for member in read_relation(
                snapshot, protocol.root_id, budget=100_000
            )
            if member.role_id == protocol.roles["relationship-member"]
        )
    if relationship_root not in registered:
        raise InvalidCell("authority relationship is not protocol-registered")
    relationship = read_authority_relationship(
        snapshot, protocol, relationship_root
    )
    if relationship.kind_root not in protocol.kinds.values():
        raise InvalidCell("authority relationship kind is outside vocabulary")
    if relationship.state_root not in protocol.states.values():
        raise InvalidCell("authority relationship state is outside vocabulary")
    try:
        generation = int(_atom(snapshot, relationship.generation_root))
    except ValueError as exc:
        raise InvalidCell("authority relationship generation is invalid") from exc
    try:
        key_version = int(_atom(snapshot, relationship.key_version_root))
    except ValueError as exc:
        raise InvalidCell("authority relationship key version is invalid") from exc
    if key_version < 1:
        raise InvalidCell("authority relationship key version is invalid")
    key_reference = _atom(snapshot, relationship.key_reference_root)
    issued = _atom(snapshot, relationship.issued_at_root)
    changed = _atom(snapshot, relationship.changed_at_root)
    expiry = (
        _atom(snapshot, relationship.expires_at_root)
        if relationship.expires_at_root else None
    )
    reason = _atom(snapshot, relationship.reason_root)
    signed = _payload(
        root_id=relationship.root_id,
        source_root=relationship.source_root,
        target_root=relationship.target_root,
        kind_root=relationship.kind_root,
        tenant_root=relationship.tenant_root,
        scope_root=relationship.scope_root,
        action_roots=relationship.action_roots,
        state_root=relationship.state_root,
        issuer_root=relationship.issuer_root,
        changed_by_root=relationship.changed_by_root,
        issued_at=issued,
        changed_at=changed,
        expires_at=expiry,
        generation=generation,
        reason=reason,
        evidence_roots=relationship.evidence_roots,
        key_reference=key_reference,
        key_version=key_version,
    )
    digest = hashlib.sha256(signed).hexdigest()
    if not hmac.compare_digest(_atom(snapshot, relationship.digest_root), digest):
        raise RelationshipAuthorityDenied("authority relationship digest drifted")
    if not broker.verify_signature(
        signed,
        _atom(snapshot, relationship.signature_root),
        key_reference,
        key_version,
    ):
        raise RelationshipAuthorityDenied("authority relationship signature failed")
    return relationship, generation


def _relationship_material_cell_ids(
    relationship: AuthorityRelationship,
) -> tuple[str, ...]:
    roots = [
        relationship.state_incidence,
        relationship.changed_by_incidence,
        relationship.issued_at_root,
        relationship.changed_at_root,
        relationship.generation_root,
        relationship.reason_root,
        relationship.digest_root,
        relationship.signature_root,
        relationship.key_reference_root,
        relationship.key_version_root,
    ]
    if relationship.expires_at_root:
        roots.append(relationship.expires_at_root)
    return tuple(dict.fromkeys(roots))


def _verify_sparse_historical_relationship_material(
    store: CellStore,
    revision: int,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    relationship: AuthorityRelationship,
) -> tuple[int, str]:
    """Verify one relationship generation without materialising a snapshot."""
    if relationship.kind_root not in protocol.kinds.values():
        raise InvalidCell("authority relationship kind is outside vocabulary")
    cells = store.cells_at(
        revision, _relationship_material_cell_ids(relationship)
    )
    state_root = cells[relationship.state_incidence].link1
    changed_by_root = cells[relationship.changed_by_incidence].link1
    if state_root not in protocol.states.values():
        raise InvalidCell("authority relationship state is outside vocabulary")
    try:
        generation = int(cells[relationship.generation_root].atom.decode("utf-8"))
    except ValueError as exc:
        raise InvalidCell("authority relationship generation is invalid") from exc
    try:
        key_version = int(cells[relationship.key_version_root].atom.decode("utf-8"))
    except ValueError as exc:
        raise InvalidCell("authority relationship key version is invalid") from exc
    if key_version < 1:
        raise InvalidCell("authority relationship key version is invalid")
    key_reference = cells[relationship.key_reference_root].atom.decode("utf-8")
    issued = cells[relationship.issued_at_root].atom.decode("utf-8")
    changed = cells[relationship.changed_at_root].atom.decode("utf-8")
    expiry = (
        cells[relationship.expires_at_root].atom.decode("utf-8")
        if relationship.expires_at_root else None
    )
    reason = cells[relationship.reason_root].atom.decode("utf-8")
    signed = _payload(
        root_id=relationship.root_id,
        source_root=relationship.source_root,
        target_root=relationship.target_root,
        kind_root=relationship.kind_root,
        tenant_root=relationship.tenant_root,
        scope_root=relationship.scope_root,
        action_roots=relationship.action_roots,
        state_root=state_root,
        issuer_root=relationship.issuer_root,
        changed_by_root=changed_by_root,
        issued_at=issued,
        changed_at=changed,
        expires_at=expiry,
        generation=generation,
        reason=reason,
        evidence_roots=relationship.evidence_roots,
        key_reference=key_reference,
        key_version=key_version,
    )
    digest = hashlib.sha256(signed).hexdigest()
    stored_digest = cells[relationship.digest_root].atom.decode("utf-8")
    if not hmac.compare_digest(stored_digest, digest):
        raise RelationshipAuthorityDenied("authority relationship digest drifted")
    signature = cells[relationship.signature_root].atom.decode("utf-8")
    if not broker.verify_signature(
        signed, signature, key_reference, key_version
    ):
        raise RelationshipAuthorityDenied("authority relationship signature failed")
    return generation, stored_digest


def verify_relationship_authority_snapshot(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    *,
    now: float | None = None,
) -> VerifiedAuthoritySnapshot:
    """Verify every registered relationship once for one graph revision/time."""
    current = time.time() if now is None else now
    registered = tuple(
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.roles["relationship-member"]
    )
    registered_roots = frozenset(registered)
    relationships: dict[str, AuthorityRelationship] = {}
    expired_roots: set[str] = set()
    invalid_reasons: dict[str, str] = {}
    for relationship_root in registered:
        try:
            relationship, generation = _verify_signed_relationship_material(
                snapshot,
                protocol,
                broker,
                relationship_root,
                registered_roots=registered_roots,
            )
            if not broker.verify_generation(relationship_root, generation):
                raise RelationshipAuthorityDenied(
                    "authority relationship generation is stale or unknown"
                )
            expiry = (
                _atom(snapshot, relationship.expires_at_root)
                if relationship.expires_at_root else None
            )
            if expiry is not None:
                try:
                    expiry_value = float(expiry)
                except ValueError as exc:
                    raise InvalidCell(
                        "authority relationship expiry is invalid"
                    ) from exc
                if current >= expiry_value:
                    expired_roots.add(relationship_root)
            relationships[relationship_root] = relationship
        except RelationshipAuthorityDenied as exc:
            invalid_reasons[relationship_root] = str(exc)
    active_relationships = tuple(
        relationships[root] for root in registered
        if root in relationships
        and root not in expired_roots
        and relationships[root].state_root == protocol.states["active"]
    )
    return VerifiedAuthoritySnapshot(
        _VERIFIED_AUTHORITY_SNAPSHOT_KEY,
        broker,
        protocol.root_id,
        snapshot.revision,
        current,
        registered,
        MappingProxyType(relationships),
        active_relationships,
        frozenset(expired_roots),
        MappingProxyType(invalid_reasons),
    )


def restore_relationship_authority_history(
    store: CellStore,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
) -> Mapping[str, int]:
    """Rebuild live anti-replay generations from the immutable Cell journal.

    The current graph is not trusted to state its own maximum generation.  All
    retained revisions are scanned, and only correctly signed relationship
    states contribute.  This catches an in-database replay of an older active
    relationship after a later signed revocation.
    """
    protocol_prefix = protocol.root_id + ":"
    # Ask the journal which revisions touched the registry instead of reading
    # every cell of every revision to find out. On the founder's graph that
    # read 21,700 revisions and 3M cells on each boot (boot-profile.log,
    # 2026-09-05: revision_cells + snapshot_at = a third of a 259s boot).
    # A store without the scoped read (in-memory courts) keeps the old walk.
    scoped = getattr(store, "revisions_touching", None)
    if callable(scoped):
        changed_by_revision = None
        registry_revisions = tuple(scoped(protocol.root_id))
    else:
        changed_by_revision = tuple(
            (revision, store.revision_changes(revision))
            for revision in store.revisions()
        )
        registry_revisions = tuple(
            revision for revision, changed_roots in changed_by_revision
            if any(
                root == protocol.root_id or root.startswith(protocol_prefix)
                for root in changed_roots
            )
        )
    historical_roots: set[str] = set()
    for revision in registry_revisions:
        snapshot = store.at(revision)
        if protocol.root_id not in snapshot.cells:
            continue
        try:
            roots = frozenset(
                member.participant_id for member in read_relation(
                    snapshot, protocol.root_id, budget=100_000
                )
                if member.role_id == protocol.roles["relationship-member"]
            )
        except (InvalidCell, KeyError):
            continue
        historical_roots.update(roots)
    current = store.snapshot()
    if protocol.root_id not in current.cells:
        return MappingProxyType({})
    try:
        latest_roots = frozenset(
            member.participant_id for member in read_relation(
                current, protocol.root_id, budget=100_000
            )
            if member.role_id == protocol.roles["relationship-member"]
        )
    except (InvalidCell, KeyError) as exc:
        raise RelationshipAuthorityDenied(
            "authority relationship registry is invalid"
        ) from exc
    historical_roots.update(latest_roots)
    missing = historical_roots - set(latest_roots)
    if missing:
        raise RelationshipAuthorityDenied(
            "authority relationship registry was rolled back"
        )

    historical_lookup = frozenset(historical_roots)
    current_relationships = {
        relationship_root: read_authority_relationship(
            current, protocol, relationship_root
        )
        for relationship_root in historical_roots
    }
    touched_by_revision: dict[int, set[str]] = {}
    if changed_by_revision is None:
        # The same attribution as the walk below -- a change under a
        # relationship root touches that root -- answered per root from the
        # journal index. Where roots nest, only the deepest keeps the change,
        # exactly as the walk stopped at the first ancestor it met.
        for relationship_root in historical_roots:
            for revision in scoped(relationship_root):
                touched_by_revision.setdefault(revision, set()).add(relationship_root)
        for revision, roots in touched_by_revision.items():
            shallow = {
                root for root in roots
                if any(other != root and other.startswith(root + ":") for other in roots)
            }
            roots.difference_update(shallow)
    else:
        for revision, changed_roots in changed_by_revision:
            touched_roots: set[str] = set()
            for changed_root in changed_roots:
                candidate = changed_root
                while True:
                    if candidate in historical_lookup:
                        touched_roots.add(candidate)
                        break
                    parent, separator, _tail = candidate.rpartition(":")
                    if not separator:
                        break
                    candidate = parent
            if touched_roots:
                touched_by_revision[revision] = touched_roots

    digests_by_root: dict[str, dict[int, set[str]]] = {
        relationship_root: {} for relationship_root in historical_roots
    }
    for revision in sorted(touched_by_revision):
        for relationship_root in sorted(touched_by_revision[revision]):
            try:
                generation, digest = (
                    _verify_sparse_historical_relationship_material(
                        store,
                        revision,
                        protocol,
                        broker,
                        current_relationships[relationship_root],
                    )
                )
            except (InvalidCell, RelationshipAuthorityDenied, KeyError):
                continue
            digests_by_root[relationship_root].setdefault(
                generation, set()
            ).add(digest)

    restored: dict[str, int] = {}
    for relationship_root in sorted(historical_roots):
        digests = digests_by_root[relationship_root]
        if not digests:
            raise RelationshipAuthorityDenied(
                "authority relationship history has no trusted signature"
            )
        if any(len(values) != 1 for values in digests.values()):
            raise RelationshipAuthorityDenied(
                "authority relationship generation has conflicting signatures"
            )
        maximum = max(digests)
        if set(digests) != set(range(1, maximum + 1)):
            raise RelationshipAuthorityDenied(
                "authority relationship generation history is discontinuous"
            )
        broker.restore_generation(relationship_root, maximum)
        restored[relationship_root] = maximum
    return MappingProxyType(restored)


def prepare_authority_relationship_revocation(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    relationship_root: str,
    *,
    administrator_root: str,
    reason: str,
    now: float | None = None,
) -> RelationshipRevocationPatch:
    """Prepare a signed revocation for an atomic wider transaction."""
    if not reason:
        raise InvalidCell("relationship revocation requires a reason")
    relationship = verify_authority_relationship(
        snapshot, protocol, broker, relationship_root, now=now
    )
    try:
        generation = int(_atom(snapshot, relationship.generation_root)) + 1
    except ValueError as exc:
        raise InvalidCell("authority relationship generation is invalid") from exc
    current = time.time() if now is None else now
    changed = "%.6f" % current
    issued = _atom(snapshot, relationship.issued_at_root)
    expiry = (
        _atom(snapshot, relationship.expires_at_root)
        if relationship.expires_at_root else None
    )
    state_root = protocol.states["revoked"]
    key_reference, key_version = broker.current_key_reference()
    signed = _payload(
        root_id=relationship.root_id,
        source_root=relationship.source_root,
        target_root=relationship.target_root,
        kind_root=relationship.kind_root,
        tenant_root=relationship.tenant_root,
        scope_root=relationship.scope_root,
        action_roots=relationship.action_roots,
        state_root=state_root,
        issuer_root=relationship.issuer_root,
        changed_by_root=administrator_root,
        issued_at=issued,
        changed_at=changed,
        expires_at=expiry,
        generation=generation,
        reason=reason,
        evidence_roots=relationship.evidence_roots,
        key_reference=key_reference,
        key_version=key_version,
    )
    signature = broker.authorize_signature(
        administration_handle,
        administrator_root,
        signed,
        key_reference,
        key_version,
        administration_scope=_revoke_administration_scope(
            relationship_root, administrator_root, reason
        ),
        now=current,
    )
    digest = hashlib.sha256(signed).hexdigest()
    state_incidence = snapshot.cells[relationship.state_incidence]
    changed_by_incidence = snapshot.cells[relationship.changed_by_incidence]
    replacements = (
        Cell(
            state_incidence.id,
            state_incidence.link0,
            state_root,
            state_incidence.atom,
        ),
        Cell(
            changed_by_incidence.id,
            changed_by_incidence.link0,
            administrator_root,
            changed_by_incidence.atom,
        ),
        Cell(
            relationship.changed_at_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            changed.encode("utf-8"),
        ),
        Cell(
            relationship.generation_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(generation).encode("ascii"),
        ),
        Cell(
            relationship.reason_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            reason.encode("utf-8"),
        ),
        Cell(
            relationship.digest_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            digest.encode("ascii"),
        ),
        Cell(
            relationship.signature_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            signature.encode("ascii"),
        ),
        Cell(
            relationship.key_reference_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            key_reference.encode("utf-8"),
        ),
        Cell(
            relationship.key_version_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(key_version).encode("ascii"),
        ),
    )
    return RelationshipRevocationPatch(
        _REVOCATION_PATCH_KEY,
        broker,
        relationship_root,
        snapshot.revision,
        generation,
        (),
        replacements,
    )


def record_authority_relationship_revocation(
    broker: RelationshipAuthorityBroker,
    patch: RelationshipRevocationPatch,
    committed_revision: int,
) -> None:
    """Advance revocation anti-replay state after its exact commit succeeds."""
    if (
        type(patch) is not RelationshipRevocationPatch
        or patch._key is not _REVOCATION_PATCH_KEY
        or patch._broker is not broker
    ):
        raise RelationshipAuthorityDenied(
            "relationship revocation patch was not issued by this broker"
        )
    if committed_revision != patch.expected_revision + 1:
        raise RelationshipAuthorityDenied(
            "relationship revocation patch commit revision does not match"
        )
    broker.record_generation(patch.relationship_root, patch.generation)


def revoke_authority_relationship(
    store: CellStore,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    relationship_root: str,
    *,
    administrator_root: str,
    reason: str,
    now: float | None = None,
) -> int:
    """Move one relationship to a signed, monotonically newer revoked state."""
    patch = prepare_authority_relationship_revocation(
        store.snapshot(),
        protocol,
        broker,
        administration_handle,
        relationship_root,
        administrator_root=administrator_root,
        reason=reason,
        now=now,
    )
    revision = store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    record_authority_relationship_revocation(broker, patch, revision)
    return revision


def prepare_authority_relationship_evidence_revision(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    relationship_root: str,
    *,
    administrator_root: str,
    evidence_roots: Iterable[str],
    reason: str,
    now: float | None = None,
) -> RelationshipEvidenceRevisionPatch:
    """Prepare a signed evidence revision for an atomic wider transaction."""
    if not reason:
        raise InvalidCell("relationship evidence revision requires a reason")
    relationship = verify_authority_relationship(
        snapshot, protocol, broker, relationship_root, now=now
    )
    evidence = tuple(dict.fromkeys(evidence_roots))
    if any(root not in snapshot.cells for root in evidence):
        raise InvalidCell("relationship evidence references a missing cell")
    members = read_relation(snapshot, relationship_root, budget=100_000)
    evidence_members = _for_role(members, protocol.roles["evidence"])
    if len(evidence) != len(evidence_members):
        raise InvalidCell(
            "relationship evidence revision must preserve evidence cardinality"
        )
    try:
        generation = int(_atom(snapshot, relationship.generation_root)) + 1
    except ValueError as exc:
        raise InvalidCell("authority relationship generation is invalid") from exc
    current = time.time() if now is None else now
    changed = "%.6f" % current
    issued = _atom(snapshot, relationship.issued_at_root)
    expiry = (
        _atom(snapshot, relationship.expires_at_root)
        if relationship.expires_at_root else None
    )
    key_reference, key_version = broker.current_key_reference()
    signed = _payload(
        root_id=relationship.root_id,
        source_root=relationship.source_root,
        target_root=relationship.target_root,
        kind_root=relationship.kind_root,
        tenant_root=relationship.tenant_root,
        scope_root=relationship.scope_root,
        action_roots=relationship.action_roots,
        state_root=relationship.state_root,
        issuer_root=relationship.issuer_root,
        changed_by_root=administrator_root,
        issued_at=issued,
        changed_at=changed,
        expires_at=expiry,
        generation=generation,
        reason=reason,
        evidence_roots=evidence,
        key_reference=key_reference,
        key_version=key_version,
    )
    signature = broker.authorize_signature(
        administration_handle,
        administrator_root,
        signed,
        key_reference,
        key_version,
        administration_scope=_revise_evidence_administration_scope(
            relationship_root, administrator_root, reason, evidence
        ),
        now=current,
    )
    digest = hashlib.sha256(signed).hexdigest()
    changed_by_incidence = snapshot.cells[relationship.changed_by_incidence]
    replacements = [
        Cell(
            changed_by_incidence.id,
            changed_by_incidence.link0,
            administrator_root,
            changed_by_incidence.atom,
        ),
        Cell(
            relationship.changed_at_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            changed.encode("utf-8"),
        ),
        Cell(
            relationship.generation_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(generation).encode("ascii"),
        ),
        Cell(
            relationship.reason_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            reason.encode("utf-8"),
        ),
        Cell(
            relationship.digest_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            digest.encode("ascii"),
        ),
        Cell(
            relationship.signature_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            signature.encode("ascii"),
        ),
        Cell(
            relationship.key_reference_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            key_reference.encode("utf-8"),
        ),
        Cell(
            relationship.key_version_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(key_version).encode("ascii"),
        ),
    ]
    replacements.extend(
        Cell(
            snapshot.cells[member.incidence_id].id,
            snapshot.cells[member.incidence_id].link0,
            evidence_root,
            snapshot.cells[member.incidence_id].atom,
        )
        for member, evidence_root in zip(evidence_members, evidence)
        if member.participant_id != evidence_root
    )
    return RelationshipEvidenceRevisionPatch(
        _EVIDENCE_REVISION_PATCH_KEY,
        broker,
        relationship_root,
        snapshot.revision,
        generation,
        (),
        tuple(replacements),
    )


def record_authority_relationship_evidence_revision(
    broker: RelationshipAuthorityBroker,
    patch: RelationshipEvidenceRevisionPatch,
    committed_revision: int,
) -> None:
    """Advance anti-replay state after the patch's exact commit succeeds."""
    if (
        type(patch) is not RelationshipEvidenceRevisionPatch
        or patch._key is not _EVIDENCE_REVISION_PATCH_KEY
        or patch._broker is not broker
    ):
        raise RelationshipAuthorityDenied(
            "relationship evidence patch was not issued by this broker"
        )
    if committed_revision != patch.expected_revision + 1:
        raise RelationshipAuthorityDenied(
            "relationship evidence patch commit revision does not match"
        )
    broker.record_generation(patch.relationship_root, patch.generation)


def revise_authority_relationship_evidence(
    store: CellStore,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    administration_handle: object,
    relationship_root: str,
    *,
    administrator_root: str,
    evidence_roots: Iterable[str],
    reason: str,
    now: float | None = None,
) -> int:
    """Atomically commit one signed evidence revision and record anti-replay."""
    patch = prepare_authority_relationship_evidence_revision(
        store.snapshot(),
        protocol,
        broker,
        administration_handle,
        relationship_root,
        administrator_root=administrator_root,
        evidence_roots=evidence_roots,
        reason=reason,
        now=now,
    )
    revision = store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    record_authority_relationship_evidence_revision(
        broker, patch, revision
    )
    return revision


def active_membership_roots(
    snapshot: Snapshot,
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
    subject_root: str,
    tenant_root: str,
    *,
    now: float | None = None,
    authority_snapshot: VerifiedAuthoritySnapshot | None = None,
) -> tuple[str, ...]:
    """Resolve transitive active memberships without copying grants per user."""
    verified = authority_snapshot or verify_relationship_authority_snapshot(
        snapshot, protocol, broker, now=now
    )
    current = verified.evaluated_at if now is None else now
    _require_compatible_authority_snapshot(
        snapshot, protocol, broker, verified, now=current
    )
    reached = {subject_root}
    changed = True
    while changed:
        changed = False
        for relation in verified.active_relationships:
            if (
                relation.kind_root == protocol.kinds["membership"]
                and relation.tenant_root == tenant_root
                and relation.source_root in reached
                and relation.target_root not in reached
            ):
                reached.add(relation.target_root)
                changed = True
    return tuple(sorted(reached - {subject_root}))


class _RelationshipPrincipalResolver:
    def __init__(
        self,
        protocol: IdentityProtocol,
        broker: RelationshipAuthorityBroker,
    ) -> None:
        self._protocol = protocol
        self._broker = broker

    def __call__(
        self,
        snapshot: Snapshot,
        identity: _AuthenticationEntry,
        request: AuthorizationRequest,
        now: float,
    ) -> tuple[str, ...]:
        return self.resolve_batch(snapshot, identity, (request,), now)[0]

    def resolve_batch(
        self,
        snapshot: Snapshot,
        identity: _AuthenticationEntry,
        requests: tuple[AuthorizationRequest, ...],
        now: float,
    ) -> tuple[tuple[str, ...], ...]:
        authority_snapshot = verify_relationship_authority_snapshot(
            snapshot, self._protocol, self._broker, now=now
        )
        return self.resolve_batch_with_state(
            snapshot, identity, requests, now, authority_snapshot
        )

    def resolve_batch_with_state(
        self,
        snapshot: Snapshot,
        identity: _AuthenticationEntry,
        requests: tuple[AuthorizationRequest, ...],
        now: float,
        resolver_state: object,
    ) -> tuple[tuple[str, ...], ...]:
        protocol = self._protocol
        broker = self._broker
        if type(resolver_state) is not VerifiedAuthoritySnapshot:
            raise AuthorizationDenied("relationship resolver state is invalid")
        authority_snapshot = resolver_state
        _require_compatible_authority_snapshot(
            snapshot, protocol, broker, authority_snapshot, now=now
        )
        tenant = identity.tenant_root
        if tenant is None:
            raise AuthorizationDenied("authenticated subject has no tenant")
        memberships = active_membership_roots(
            snapshot,
            protocol,
            broker,
            identity.subject_root,
            tenant,
            now=now,
            authority_snapshot=authority_snapshot,
        )
        if tenant not in memberships:
            raise AuthorizationDenied("authenticated tenant membership is inactive")
        targets = {identity.subject_root, *memberships}
        resolved = []
        for request in requests:
            principals = set(memberships)
            scopes = {request.object_root, *request.resource_lineage_roots}
            for relation in authority_snapshot.active_relationships:
                if (
                    relation.kind_root == protocol.kinds["delegation"]
                    and relation.tenant_root == tenant
                    and relation.target_root in targets
                    and relation.scope_root in scopes
                    and request.action_root in relation.action_roots
                ):
                    principals.add(relation.source_root)
            resolved.append(tuple(sorted(principals)))
        return tuple(resolved)


def relationship_principal_resolver(
    protocol: IdentityProtocol,
    broker: RelationshipAuthorityBroker,
):
    """Create the request-time resolver used by the generic authorizer."""
    return _RelationshipPrincipalResolver(protocol, broker)


__all__ = [
    "IdentityProtocol",
    "AuthorityRelationship",
    "VerifiedAuthoritySnapshot",
    "RelationshipAuthorityDenied",
    "RelationshipAdministrationHandle",
    "RelationshipEvidenceRevisionPatch",
    "RelationshipRevocationPatch",
    "RelationshipAuthorityBroker",
    "bootstrap_identity_protocol",
    "grant_authority_relationship",
    "read_authority_relationship",
    "verify_authority_relationship",
    "verify_relationship_authority_snapshot",
    "restore_relationship_authority_history",
    "revoke_authority_relationship",
    "prepare_authority_relationship_revocation",
    "record_authority_relationship_revocation",
    "prepare_authority_relationship_evidence_revision",
    "record_authority_relationship_evidence_revision",
    "revise_authority_relationship_evidence",
    "active_membership_roots",
    "relationship_principal_resolver",
]
