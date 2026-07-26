"""Device-bound cloud sessions assembled from universal Cells and relations.

The access token and client private key never enter the graph. A visible
session manifest carries only non-secret references and digests. Its authority
is an ordinary signed delegation relationship whose evidence includes the
content-addressed manifest digest, identity verification, and device binding.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import secrets
import time
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from .cell_authorization import AuthenticationBroker, AuthenticationContext
from .cell_federated_identity import FederatedAuthentication
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    grant_authority_relationship,
    revoke_authority_relationship,
    verify_authority_relationship,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    Snapshot,
)


ROLE_NAMES = (
    "vocabulary-member",
    "session-member",
    "proof-use-member",
    "subject",
    "tenant",
    "device",
    "audience",
    "assurance",
    "authentication-method",
    "issued-at",
    "auth-time",
    "expires-at",
    "token-digest",
    "proof-key-thumbprint",
    "evidence",
    "manifest-digest",
    "session",
    "proof-id-digest",
    "http-method",
    "target-uri-digest",
    "observed-at",
)

MAX_TOKEN_LENGTH = 512
MAX_PROOF_BYTES = 64 * 1024


class CloudSessionDenied(PermissionError):
    pass


class RequestProofVerifier(Protocol):
    """Trusted RFC 9449 verifier boundary; implementations use JOSE code."""

    def verify(
        self,
        proof: bytes,
        *,
        access_token: str,
        expected_thumbprint: str,
        http_method: str,
        target_uri: str,
        expected_nonce: str,
        now: float,
    ) -> str:
        """Return the verified proof `jti`, or raise on any failed check."""


@dataclass(frozen=True, slots=True)
class TenantAdmissionEvidence:
    """The exact released tenant authority admitted for a cloud request."""

    tenant_root: str
    published_revision_root: str
    catalogue_root: str
    policy_root: str


class TenantAdmissionVerifier(Protocol):
    """Trusted graph verifier for one tenant's currently released authority."""

    def verify(
        self,
        snapshot: Snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        """Return current release evidence, or deny the subject and tenant."""


class DeviceCustodyVerifier(Protocol):
    """Trusted graph verifier for one device's active key custody."""

    def verify(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        now: float,
    ) -> str:
        """Return one active custody root, or deny the device."""


@dataclass(frozen=True, slots=True)
class CloudSessionProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown cloud-session role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class CloudSessionProjection:
    root_id: str
    subject_root: str
    tenant_root: str
    device_root: str
    audience_root: str
    assurance_root: str
    authentication_method_root: str
    issued_at_root: str
    auth_time_root: str
    expires_at_root: str
    token_digest_root: str
    proof_key_thumbprint_root: str
    evidence_roots: tuple[str, ...]
    manifest_digest_root: str


@dataclass(frozen=True, slots=True)
class IssuedCloudSession:
    session_root: str
    authority_relationship_root: str
    access_token: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class CloudRequestAuthentication:
    context: AuthenticationContext
    session_root: str
    proof_use_root: str
    device_root: str
    subject_root: str
    tenant_root: str
    audience_root: str
    assurance_root: str


def _terminal_cell(root_id: str, value: str) -> Cell:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("cloud-session values cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _atom(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise CloudSessionDenied(
            "cloud-session graph value is missing or invalid"
        ) from exc


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(members: tuple[RelationMember, ...], role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("cloud session requires exactly one %s" % label)
    return values[0]


def bootstrap_cloud_session_protocol(
    store: CellStore, *, prefix: str = "cloud-session-protocol"
) -> CloudSessionProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_terminal_cell(root, name))
    root_id = prefix + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return CloudSessionProtocol(root_id, MappingProxyType(roles))


def project_cloud_session_protocol(
    snapshot: Snapshot, *, prefix: str = "cloud-session-protocol"
) -> CloudSessionProtocol:
    """Recover the deterministic protocol vocabulary without writing Cells."""
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("cloud-session protocol is incomplete")
    return CloudSessionProtocol(root_id, MappingProxyType(roles))


def device_root_for_thumbprint(thumbprint: str) -> str:
    if (
        len(thumbprint) != 43
        or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in thumbprint
        )
    ):
        raise ValueError(
            "device proof-key thumbprint must be RFC 7638 SHA-256 base64url"
        )
    return "device-proof-key:sha256:" + thumbprint


def provision_device_binding(
    store: CellStore,
    protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    relationship_id: str,
    proof_key_thumbprint: str,
    subject_root: str,
    tenant_root: str,
    audience_root: str,
    administrator_root: str,
    reason: str,
    evidence_roots: tuple[str, ...] = (),
    now: float | None = None,
) -> str:
    """Provision one device public-key identity for a subject and audience."""
    device_root = device_root_for_thumbprint(proof_key_thumbprint)
    expected_atom = (
        "device-proof-key-thumbprint:" + proof_key_thumbprint
    ).encode("ascii")
    snapshot = store.snapshot()
    existing = snapshot.cells.get(device_root)
    if existing is None:
        store.commit(snapshot.revision, create=(Cell(
            device_root, NULL_CELL_ID, NULL_CELL_ID, expected_atom
        ),))
    elif (
        existing.link0 != NULL_CELL_ID
        or existing.link1 != NULL_CELL_ID
        or existing.atom != expected_atom
    ):
        raise InvalidCell("device proof-key identity drifted")
    return grant_authority_relationship(
        store,
        protocol,
        relationship_broker,
        administration_handle,
        relationship_id=relationship_id,
        source_root=device_root,
        target_root=subject_root,
        kind="audience-binding",
        tenant_root=tenant_root,
        scope_root=audience_root,
        administrator_root=administrator_root,
        reason=reason,
        evidence_roots=evidence_roots,
        now=now,
    )


def read_cloud_session(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    session_root: str,
) -> CloudSessionProjection:
    members = read_relation(snapshot, session_root, budget=256)
    allowed = {
        protocol.role(name) for name in (
            "subject",
            "tenant",
            "device",
            "audience",
            "assurance",
            "authentication-method",
            "issued-at",
            "auth-time",
            "expires-at",
            "token-digest",
            "proof-key-thumbprint",
            "evidence",
            "manifest-digest",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("cloud session contains an undeclared field")
    return CloudSessionProjection(
        session_root,
        _one(members, protocol.role("subject"), "subject"),
        _one(members, protocol.role("tenant"), "tenant"),
        _one(members, protocol.role("device"), "device"),
        _one(members, protocol.role("audience"), "audience"),
        _one(members, protocol.role("assurance"), "assurance"),
        _one(
            members,
            protocol.role("authentication-method"),
            "authentication method",
        ),
        _one(members, protocol.role("issued-at"), "issued-at"),
        _one(members, protocol.role("auth-time"), "auth-time"),
        _one(members, protocol.role("expires-at"), "expires-at"),
        _one(members, protocol.role("token-digest"), "token digest"),
        _one(
            members,
            protocol.role("proof-key-thumbprint"),
            "proof-key thumbprint",
        ),
        _for_role(members, protocol.role("evidence")),
        _one(members, protocol.role("manifest-digest"), "manifest digest"),
    )


def _manifest_payload(
    snapshot: Snapshot, session: CloudSessionProjection
) -> bytes:
    document = {
        "root": session.root_id,
        "subject": session.subject_root,
        "tenant": session.tenant_root,
        "device": session.device_root,
        "audience": session.audience_root,
        "assurance": session.assurance_root,
        "authentication_method": _atom(
            snapshot, session.authentication_method_root
        ),
        "issued_at": _atom(snapshot, session.issued_at_root),
        "auth_time": _atom(snapshot, session.auth_time_root),
        "expires_at": _atom(snapshot, session.expires_at_root),
        "token_digest": _atom(snapshot, session.token_digest_root),
        "proof_key_thumbprint": _atom(
            snapshot, session.proof_key_thumbprint_root
        ),
        "evidence": sorted(session.evidence_roots),
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def verify_cloud_session_manifest(
    snapshot: Snapshot,
    protocol: CloudSessionProtocol,
    session_root: str,
) -> CloudSessionProjection:
    registered = {
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("session-member")
    }
    if session_root not in registered:
        raise CloudSessionDenied("cloud session is not protocol-registered")
    session = read_cloud_session(snapshot, protocol, session_root)
    digest = hashlib.sha256(_manifest_payload(snapshot, session)).hexdigest()
    expected_root = "cloud-session-manifest:sha256:" + digest
    if session.manifest_digest_root != expected_root:
        raise CloudSessionDenied("cloud session manifest digest drifted")
    if _atom(snapshot, expected_root) != digest:
        raise CloudSessionDenied("cloud session manifest evidence drifted")
    if session.device_root != device_root_for_thumbprint(
        _atom(snapshot, session.proof_key_thumbprint_root)
    ):
        raise CloudSessionDenied("cloud session device binding drifted")
    return session


class CloudSessionBroker:
    """Issue and authenticate short-lived, proof-of-possession sessions."""

    def __init__(
        self,
        *,
        session_protocol: CloudSessionProtocol,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
        authentication_broker: AuthenticationBroker,
        request_proof_verifier: RequestProofVerifier,
        tenant_admission_verifier: TenantAdmissionVerifier,
        device_custody_verifier: DeviceCustodyVerifier,
        session_issuer_root: str,
    ) -> None:
        self._session_protocol = session_protocol
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker
        self._authentication_broker = authentication_broker
        self._request_proof_verifier = request_proof_verifier
        self._tenant_admission_verifier = tenant_admission_verifier
        if not hasattr(device_custody_verifier, "verify"):
            raise TypeError("cloud session requires device custody verification")
        self._device_custody_verifier = device_custody_verifier
        self._session_issuer_root = session_issuer_root

    def _tenant_admission(
        self,
        snapshot: Snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        try:
            evidence = self._tenant_admission_verifier.verify(
                snapshot,
                tenant_root=tenant_root,
                subject_root=subject_root,
                now=now,
            )
        except Exception as exc:
            raise CloudSessionDenied(
                "cloud session tenant release is inactive"
            ) from exc
        if (
            type(evidence) is not TenantAdmissionEvidence
            or evidence.tenant_root != tenant_root
            or any(
                root not in snapshot.cells
                for root in (
                    evidence.published_revision_root,
                    evidence.catalogue_root,
                    evidence.policy_root,
                )
            )
        ):
            raise CloudSessionDenied(
                "cloud session tenant release evidence drifted"
            )
        return evidence

    def _verified_device_binding(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        subject_root: str,
        tenant_root: str,
        audience_root: str,
        now: float,
    ) -> str:
        matches = []
        for member in read_relation(
            snapshot, self._identity_protocol.root_id, budget=100_000
        ):
            if member.role_id != self._identity_protocol.roles[
                "relationship-member"
            ]:
                continue
            try:
                relationship = verify_authority_relationship(
                    snapshot,
                    self._identity_protocol,
                    self._relationship_broker,
                    member.participant_id,
                    now=now,
                )
            except (RelationshipAuthorityDenied, InvalidCell, KeyError):
                continue
            if (
                relationship.kind_root
                == self._identity_protocol.kinds["audience-binding"]
                and relationship.source_root == device_root
                and relationship.target_root == subject_root
                and relationship.tenant_root == tenant_root
                and relationship.scope_root == audience_root
            ):
                matches.append(relationship.root_id)
        if len(matches) != 1:
            raise CloudSessionDenied(
                "device requires one active subject/audience binding"
            )
        return matches[0]

    def _verified_device_custody(
        self,
        snapshot: Snapshot,
        *,
        device_root: str,
        now: float,
    ) -> str:
        try:
            custody_root = self._device_custody_verifier.verify(
                snapshot,
                device_root=device_root,
                now=now,
            )
        except Exception as exc:
            raise CloudSessionDenied(
                "cloud session device custody is inactive"
            ) from exc
        if (
            not isinstance(custody_root, str)
            or not custody_root
            or custody_root not in snapshot.cells
        ):
            raise CloudSessionDenied(
                "cloud session device custody evidence drifted"
            )
        return custody_root

    def issue(
        self,
        store: CellStore,
        authentication: FederatedAuthentication,
        *,
        proof_key_thumbprint: str,
        allowed_action_roots: Iterable[str],
        lifetime_seconds: float = 900.0,
        now: float | None = None,
    ) -> IssuedCloudSession:
        if type(authentication) is not FederatedAuthentication:
            raise CloudSessionDenied(
                "session issuance requires broker-verified identity"
            )
        current = time.time() if now is None else now
        if lifetime_seconds <= 0 or lifetime_seconds > 3600:
            raise ValueError("cloud session lifetime must be within one hour")
        identity = self._authentication_broker.resolve(
            authentication.context, now=current
        )
        if (
            identity.subject_root != authentication.subject_root
            or identity.tenant_root != authentication.tenant_root
            or identity.assurance_root != authentication.assurance_root
        ):
            raise CloudSessionDenied("federated identity context drifted")
        actions = tuple(dict.fromkeys(allowed_action_roots))
        snapshot = store.snapshot()
        required = {
            authentication.subject_root,
            authentication.tenant_root,
            authentication.audience_root,
            authentication.assurance_root,
            authentication.evidence_root,
            *actions,
        }
        if not actions or any(root not in snapshot.cells for root in required):
            raise CloudSessionDenied(
                "session scope references missing or empty graph authority"
            )
        tenant_admission = self._tenant_admission(
            snapshot,
            tenant_root=authentication.tenant_root,
            subject_root=authentication.subject_root,
            now=current,
        )
        device_root = device_root_for_thumbprint(proof_key_thumbprint)
        device_custody_root = self._verified_device_custody(
            snapshot,
            device_root=device_root,
            now=current,
        )
        device_binding_root = self._verified_device_binding(
            snapshot,
            device_root=device_root,
            subject_root=authentication.subject_root,
            tenant_root=authentication.tenant_root,
            audience_root=authentication.audience_root,
            now=current,
        )
        external_expiry = float(authentication.claims["expires_at"])
        expires_at = min(current + lifetime_seconds, external_expiry)
        if expires_at <= current:
            raise CloudSessionDenied("federated identity expired before issuance")
        token = "ah_dpop_" + secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        session_root = "cloud-session:" + secrets.token_hex(16)
        values = {
            "authentication-method": authentication.claims[
                "authentication_method"
            ],
            "issued-at": "%.6f" % current,
            "auth-time": authentication.claims["auth_time"],
            "expires-at": "%.6f" % expires_at,
            "token-digest": token_digest,
            "proof-key-thumbprint": proof_key_thumbprint,
        }
        value_cells = {
            name: _terminal_cell("%s:%s" % (session_root, name), value)
            for name, value in values.items()
        }
        provisional = CloudSessionProjection(
            session_root,
            authentication.subject_root,
            authentication.tenant_root,
            device_root,
            authentication.audience_root,
            authentication.assurance_root,
            value_cells["authentication-method"].id,
            value_cells["issued-at"].id,
            value_cells["auth-time"].id,
            value_cells["expires-at"].id,
            value_cells["token-digest"].id,
            value_cells["proof-key-thumbprint"].id,
            (
                authentication.evidence_root,
                device_custody_root,
                device_binding_root,
                tenant_admission.published_revision_root,
            ),
            "",
        )
        temp_cells = dict(snapshot.cells)
        temp_cells.update({cell.id: cell for cell in value_cells.values()})
        temp_snapshot = Snapshot(snapshot.revision, MappingProxyType(temp_cells))
        manifest_digest = hashlib.sha256(
            _manifest_payload(temp_snapshot, provisional)
        ).hexdigest()
        manifest_root = "cloud-session-manifest:sha256:" + manifest_digest
        manifest_cell = _terminal_cell(manifest_root, manifest_digest)
        relation = compose_relation_cells((
            (self._session_protocol.role("subject"), authentication.subject_root),
            (self._session_protocol.role("tenant"), authentication.tenant_root),
            (self._session_protocol.role("device"), device_root),
            (self._session_protocol.role("audience"), authentication.audience_root),
            (self._session_protocol.role("assurance"), authentication.assurance_root),
            (self._session_protocol.role("authentication-method"), value_cells["authentication-method"].id),
            (self._session_protocol.role("issued-at"), value_cells["issued-at"].id),
            (self._session_protocol.role("auth-time"), value_cells["auth-time"].id),
            (self._session_protocol.role("expires-at"), value_cells["expires-at"].id),
            (self._session_protocol.role("token-digest"), value_cells["token-digest"].id),
            (self._session_protocol.role("proof-key-thumbprint"), value_cells["proof-key-thumbprint"].id),
            (self._session_protocol.role("evidence"), authentication.evidence_root),
            (self._session_protocol.role("evidence"), device_custody_root),
            (self._session_protocol.role("evidence"), device_binding_root),
            (self._session_protocol.role("evidence"), tenant_admission.published_revision_root),
            (self._session_protocol.role("manifest-digest"), manifest_root),
        ), relation_id=session_root)
        patch = prepare_append_relation_member(
            snapshot,
            self._session_protocol.root_id,
            self._session_protocol.role("session-member"),
            session_root,
            budget=100_000,
        )
        store.commit(
            snapshot.revision,
            create=(
                *value_cells.values(),
                manifest_cell,
                *relation.cells,
                *patch.create,
            ),
            replace=patch.replace,
        )
        authority_root = session_root + ":authority"
        handle = self._relationship_broker.mint_from_trusted_administrator(
            self._session_issuer_root
        )
        grant_authority_relationship(
            store,
            self._identity_protocol,
            self._relationship_broker,
            handle,
            relationship_id=authority_root,
            source_root=session_root,
            target_root=authentication.subject_root,
            kind="delegation",
            tenant_root=authentication.tenant_root,
            scope_root=authentication.audience_root,
            action_roots=actions,
            administrator_root=self._session_issuer_root,
            expires_at=expires_at,
            reason="device-bound federated cloud session",
            evidence_roots=(
                manifest_root,
                authentication.evidence_root,
                device_custody_root,
                device_binding_root,
                tenant_admission.published_revision_root,
            ),
            now=current,
        )
        return IssuedCloudSession(
            session_root, authority_root, token, expires_at
        )

    def _session_for_token(
        self, snapshot: Snapshot, token_digest: str
    ) -> CloudSessionProjection:
        matches = []
        for member in read_relation(
            snapshot, self._session_protocol.root_id, budget=100_000
        ):
            if member.role_id != self._session_protocol.role("session-member"):
                continue
            try:
                session = verify_cloud_session_manifest(
                    snapshot, self._session_protocol, member.participant_id
                )
            except (CloudSessionDenied, InvalidCell, KeyError):
                continue
            if _atom(snapshot, session.token_digest_root) == token_digest:
                matches.append(session)
        if len(matches) != 1:
            raise CloudSessionDenied("access token has no unique active session")
        return matches[0]

    def _authority(
        self,
        snapshot: Snapshot,
        session: CloudSessionProjection,
        *,
        requested_action_root: str,
        now: float,
    ):
        root = session.root_id + ":authority"
        try:
            relationship = verify_authority_relationship(
                snapshot,
                self._identity_protocol,
                self._relationship_broker,
                root,
                now=now,
            )
        except (RelationshipAuthorityDenied, InvalidCell, KeyError) as exc:
            raise CloudSessionDenied("cloud session authority is inactive") from exc
        if (
            relationship.kind_root
            != self._identity_protocol.kinds["delegation"]
            or relationship.source_root != session.root_id
            or relationship.target_root != session.subject_root
            or relationship.tenant_root != session.tenant_root
            or relationship.scope_root != session.audience_root
            or requested_action_root not in relationship.action_roots
            or session.manifest_digest_root not in relationship.evidence_roots
        ):
            raise CloudSessionDenied("cloud session authority scope drifted")
        device_custody_root = self._verified_device_custody(
            snapshot,
            device_root=session.device_root,
            now=now,
        )
        if (
            device_custody_root not in session.evidence_roots
            or device_custody_root not in relationship.evidence_roots
        ):
            raise CloudSessionDenied(
                "cloud session device custody evidence changed"
            )
        self._verified_device_binding(
            snapshot,
            device_root=session.device_root,
            subject_root=session.subject_root,
            tenant_root=session.tenant_root,
            audience_root=session.audience_root,
            now=now,
        )
        tenant_admission = self._tenant_admission(
            snapshot,
            tenant_root=session.tenant_root,
            subject_root=session.subject_root,
            now=now,
        )
        if (
            tenant_admission.published_revision_root
            not in session.evidence_roots
            or tenant_admission.published_revision_root
            not in relationship.evidence_roots
        ):
            raise CloudSessionDenied(
                "cloud session tenant release revision changed"
            )
        if session.tenant_root not in active_membership_roots(
            snapshot,
            self._identity_protocol,
            self._relationship_broker,
            session.subject_root,
            session.tenant_root,
            now=now,
        ):
            raise CloudSessionDenied("cloud session tenant membership is inactive")
        return relationship

    def _record_proof_use(
        self,
        store: CellStore,
        *,
        session: CloudSessionProjection,
        token_digest: str,
        requested_action_root: str,
        proof_id: str,
        http_method: str,
        target_uri: str,
        observed_at: float,
    ) -> str:
        proof_digest = hashlib.sha256(proof_id.encode("utf-8")).hexdigest()
        use_root = "%s:proof-use:%s" % (session.root_id, proof_digest)
        for _ in range(4):
            snapshot = store.snapshot()
            current_session = verify_cloud_session_manifest(
                snapshot,
                self._session_protocol,
                session.root_id,
            )
            if (
                current_session != session
                or _atom(snapshot, current_session.token_digest_root)
                != token_digest
            ):
                raise CloudSessionDenied(
                    "cloud session changed during request admission"
                )
            self._authority(
                snapshot,
                current_session,
                requested_action_root=requested_action_root,
                now=observed_at,
            )
            if use_root in snapshot.cells:
                raise CloudSessionDenied("request proof was replayed")
            values = {
                "proof-id-digest": proof_digest,
                "http-method": http_method,
                "target-uri-digest": hashlib.sha256(
                    target_uri.encode("utf-8")
                ).hexdigest(),
                "observed-at": "%.6f" % observed_at,
            }
            cells = {
                name: _terminal_cell("%s:%s" % (use_root, name), value)
                for name, value in values.items()
            }
            relation = compose_relation_cells((
                (self._session_protocol.role("session"), session.root_id),
                (self._session_protocol.role("proof-id-digest"), cells["proof-id-digest"].id),
                (self._session_protocol.role("http-method"), cells["http-method"].id),
                (self._session_protocol.role("target-uri-digest"), cells["target-uri-digest"].id),
                (self._session_protocol.role("observed-at"), cells["observed-at"].id),
            ), relation_id=use_root)
            patch = prepare_append_relation_member(
                snapshot,
                self._session_protocol.root_id,
                self._session_protocol.role("proof-use-member"),
                use_root,
                budget=100_000,
            )
            try:
                store.commit(
                    snapshot.revision,
                    create=(*cells.values(), *relation.cells, *patch.create),
                    replace=patch.replace,
                )
                return use_root
            except Conflict:
                continue
        raise CloudSessionDenied("request proof recording was contended")

    def authenticate_request(
        self,
        store: CellStore,
        access_token: str,
        proof: bytes,
        *,
        requested_action_root: str,
        http_method: str,
        target_uri: str,
        expected_nonce: str,
        now: float | None = None,
    ) -> CloudRequestAuthentication:
        if (
            not access_token.startswith("ah_dpop_")
            or len(access_token) > MAX_TOKEN_LENGTH
        ):
            raise CloudSessionDenied("access token shape is invalid")
        proof_bytes = bytes(proof)
        if not proof_bytes or len(proof_bytes) > MAX_PROOF_BYTES:
            raise CloudSessionDenied("request proof size is invalid")
        if not http_method or not target_uri or not expected_nonce:
            raise CloudSessionDenied("request binding fields are required")
        current = time.time() if now is None else now
        token_digest = hashlib.sha256(access_token.encode("ascii")).hexdigest()
        snapshot = store.snapshot()
        session = self._session_for_token(snapshot, token_digest)
        relationship = self._authority(
            snapshot,
            session,
            requested_action_root=requested_action_root,
            now=current,
        )
        try:
            expires_at = float(_atom(snapshot, session.expires_at_root))
        except ValueError as exc:
            raise CloudSessionDenied("cloud session expiry is invalid") from exc
        if expires_at <= current:
            raise CloudSessionDenied("cloud session expired")
        expected_thumbprint = _atom(
            snapshot, session.proof_key_thumbprint_root
        )
        try:
            proof_id = self._request_proof_verifier.verify(
                proof_bytes,
                access_token=access_token,
                expected_thumbprint=expected_thumbprint,
                http_method=http_method,
                target_uri=target_uri,
                expected_nonce=expected_nonce,
                now=current,
            )
        except Exception as exc:
            raise CloudSessionDenied("request proof verification failed") from exc
        if not isinstance(proof_id, str) or not proof_id:
            raise CloudSessionDenied("request proof verifier returned no identity")
        proof_use_root = self._record_proof_use(
            store,
            session=session,
            token_digest=token_digest,
            requested_action_root=requested_action_root,
            proof_id=proof_id,
            http_method=http_method,
            target_uri=target_uri,
            observed_at=current,
        )
        # This context is per-request. Every subsequent HTTP request must
        # present and record a fresh proof, so revocation is checked again.
        context = self._authentication_broker.mint_authenticated_context(
            session.subject_root,
            tenant_root=session.tenant_root,
            assurance_root=session.assurance_root,
            lifetime_seconds=min(5.0, max(0.001, expires_at - current)),
        )
        return CloudRequestAuthentication(
            context,
            session.root_id,
            proof_use_root,
            session.device_root,
            session.subject_root,
            session.tenant_root,
            session.audience_root,
            session.assurance_root,
        )

    def revoke(
        self,
        store: CellStore,
        session_root: str,
        *,
        administrator_root: str,
        reason: str,
        now: float | None = None,
    ) -> int:
        handle = self._relationship_broker.mint_from_trusted_administrator(
            administrator_root
        )
        return revoke_authority_relationship(
            store,
            self._identity_protocol,
            self._relationship_broker,
            handle,
            session_root + ":authority",
            administrator_root=administrator_root,
            reason=reason,
            now=now,
        )


__all__ = [
    "CloudSessionDenied",
    "RequestProofVerifier",
    "TenantAdmissionEvidence",
    "TenantAdmissionVerifier",
    "CloudSessionProtocol",
    "DeviceCustodyVerifier",
    "CloudSessionProjection",
    "IssuedCloudSession",
    "CloudRequestAuthentication",
    "CloudSessionBroker",
    "bootstrap_cloud_session_protocol",
    "project_cloud_session_protocol",
    "device_root_for_thumbprint",
    "provision_device_binding",
    "read_cloud_session",
    "verify_cloud_session_manifest",
]
