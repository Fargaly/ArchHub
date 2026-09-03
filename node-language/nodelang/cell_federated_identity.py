"""Federated identity as verified evidence plus signed graph relationships.

An OpenID provider remains a cryptographic host boundary. Its raw assertion is
never graph data. An admitted court verifies the assertion and records only a
digest and pseudonymous subject reference. ArchHub authority exists only when
that reference has one active, signed audience binding to a local subject and
the subject has an active tenant membership.
"""
from __future__ import annotations

import hashlib
import math
import time
from types import MappingProxyType
from typing import Mapping

from .cell_attestations import (
    AttestationProtocol,
    CourtAttestationBroker,
    CourtEvidenceDenied,
)
from .cell_authorization import AuthenticationBroker, AuthenticationContext
from .cell_identity import (
    IdentityProtocol,
    RelationshipAuthorityBroker,
    RelationshipAuthorityDenied,
    active_membership_roots,
    grant_authority_relationship,
    verify_authority_relationship,
)
from .cell_protocols import read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ASSERTION_SUBJECT_NAME = "federated-identity-assertion"
MAX_ASSERTION_BYTES = 256 * 1024


class FederatedIdentityDenied(PermissionError):
    pass


_FEDERATED_AUTHENTICATION_KEY = object()


class FederatedAuthentication:
    """Broker-only proof that external verification and graph binding passed."""

    __slots__ = (
        "context",
        "evidence_root",
        "subject_root",
        "tenant_root",
        "audience_root",
        "assurance_root",
        "external_identity_root",
        "claims",
    )

    def __init__(
        self,
        key: object,
        context: AuthenticationContext,
        evidence_root: str,
        subject_root: str,
        tenant_root: str,
        audience_root: str,
        assurance_root: str,
        external_identity_root: str,
        claims: Mapping[str, str],
    ) -> None:
        if key is not _FEDERATED_AUTHENTICATION_KEY:
            raise TypeError(
                "federated authentication is identity-broker authority"
            )
        self.context = context
        self.evidence_root = evidence_root
        self.subject_root = subject_root
        self.tenant_root = tenant_root
        self.audience_root = audience_root
        self.assurance_root = assurance_root
        self.external_identity_root = external_identity_root
        self.claims = MappingProxyType(dict(claims))

    def __reduce_ex__(self, protocol):
        raise TypeError("federated authentication cannot be serialized")


def federated_subject_reference(issuer: str, subject: str) -> str:
    """Return a stable pseudonymous reference for one OIDC issuer/sub pair."""
    if not issuer or not subject:
        raise ValueError("federated issuer and subject are required")
    digest = hashlib.sha256()
    for value in (issuer, subject):
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def federated_subject_root(subject_reference: str) -> str:
    if (
        len(subject_reference) != 64
        or any(char not in "0123456789abcdef" for char in subject_reference)
    ):
        raise ValueError("federated subject reference must be lowercase SHA-256")
    return "federated-identity:sha256:" + subject_reference


def provision_federated_identity_binding(
    store: CellStore,
    protocol: IdentityProtocol,
    relationship_broker: RelationshipAuthorityBroker,
    administration_handle: object,
    *,
    relationship_id: str,
    issuer: str,
    external_subject: str,
    local_subject_root: str,
    tenant_root: str,
    audience_root: str,
    administrator_root: str,
    reason: str,
    evidence_roots: tuple[str, ...] = (),
    now: float | None = None,
) -> str:
    """Bind one external identity to one local subject and exact audience."""
    reference = federated_subject_reference(issuer, external_subject)
    external_root = federated_subject_root(reference)
    snapshot = store.snapshot()
    expected_atom = ("federated-subject-reference:" + reference).encode("ascii")
    existing = snapshot.cells.get(external_root)
    if existing is None:
        store.commit(snapshot.revision, create=(Cell(
            external_root, NULL_CELL_ID, NULL_CELL_ID, expected_atom
        ),))
    elif (
        existing.link0 != NULL_CELL_ID
        or existing.link1 != NULL_CELL_ID
        or existing.atom != expected_atom
    ):
        raise InvalidCell("federated identity reference identity drifted")
    return grant_authority_relationship(
        store,
        protocol,
        relationship_broker,
        administration_handle,
        relationship_id=relationship_id,
        source_root=external_root,
        target_root=local_subject_root,
        kind="audience-binding",
        tenant_root=tenant_root,
        scope_root=audience_root,
        administrator_root=administrator_root,
        reason=reason,
        evidence_roots=evidence_roots,
        now=now,
    )


def _atom(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise FederatedIdentityDenied(
            "federated identity graph value is missing or invalid"
        ) from exc


def _required_detail(details: Mapping[str, object], name: str) -> str:
    value = details.get(name)
    if not isinstance(value, str) or not value:
        raise FederatedIdentityDenied(
            "identity verification omitted %s" % name
        )
    return value


def _timestamp(details: Mapping[str, object], name: str) -> float:
    value = _required_detail(details, name)
    try:
        parsed = float(value)
    except ValueError as exc:
        raise FederatedIdentityDenied(
            "identity verification returned invalid %s" % name
        ) from exc
    if not math.isfinite(parsed):
        raise FederatedIdentityDenied(
            "identity verification returned invalid %s" % name
        )
    return parsed


class FederatedIdentityBroker:
    """Bridge admitted identity evidence into generic authorization contexts."""

    def __init__(
        self,
        *,
        attestation_protocol: AttestationProtocol,
        attestation_broker: CourtAttestationBroker,
        verification_court_root: str,
        identity_protocol: IdentityProtocol,
        relationship_broker: RelationshipAuthorityBroker,
        authentication_broker: AuthenticationBroker,
        assurance_roots: Mapping[str, str],
    ) -> None:
        if not assurance_roots:
            raise ValueError("federated identity requires assurance mappings")
        self._attestation_protocol = attestation_protocol
        self._attestation_broker = attestation_broker
        self._verification_court_root = verification_court_root
        self._identity_protocol = identity_protocol
        self._relationship_broker = relationship_broker
        self._authentication_broker = authentication_broker
        self._assurance_roots = MappingProxyType(dict(assurance_roots))

    def _resolve_subject(
        self,
        snapshot: Snapshot,
        *,
        external_root: str,
        tenant_root: str,
        audience_root: str,
        now: float,
    ) -> str:
        roots = (
            member.participant_id
            for member in read_relation(
                snapshot, self._identity_protocol.root_id, budget=100_000
            )
            if member.role_id
            == self._identity_protocol.roles["relationship-member"]
        )
        subjects: set[str] = set()
        for root in roots:
            try:
                relationship = verify_authority_relationship(
                    snapshot,
                    self._identity_protocol,
                    self._relationship_broker,
                    root,
                    now=now,
                )
            except (RelationshipAuthorityDenied, InvalidCell, KeyError):
                continue
            if (
                relationship.kind_root
                == self._identity_protocol.kinds["audience-binding"]
                and relationship.source_root == external_root
                and relationship.tenant_root == tenant_root
                and relationship.scope_root == audience_root
            ):
                subjects.add(relationship.target_root)
        if not subjects:
            raise FederatedIdentityDenied(
                "external identity has no active audience binding"
            )
        if len(subjects) != 1:
            raise FederatedIdentityDenied(
                "external identity has ambiguous audience bindings"
            )
        subject_root = next(iter(subjects))
        memberships = active_membership_roots(
            snapshot,
            self._identity_protocol,
            self._relationship_broker,
            subject_root,
            tenant_root,
            now=now,
        )
        if tenant_root not in memberships:
            raise FederatedIdentityDenied(
                "external identity subject is not an active tenant member"
            )
        return subject_root

    def authenticate(
        self,
        store: CellStore,
        assertion: bytes,
        *,
        expected_issuer: str,
        expected_audience: str,
        expected_nonce: str,
        tenant_root: str,
        audience_root: str,
        max_assertion_age_seconds: float = 300.0,
        context_lifetime_seconds: float = 300.0,
        now: float | None = None,
    ) -> FederatedAuthentication:
        """Verify an assertion, resolve signed bindings, and mint short authority."""
        content = bytes(assertion)
        if not content or len(content) > MAX_ASSERTION_BYTES:
            raise FederatedIdentityDenied("identity assertion size is invalid")
        if not expected_issuer or not expected_audience or not expected_nonce:
            raise FederatedIdentityDenied(
                "issuer, audience, and nonce are required"
            )
        if max_assertion_age_seconds <= 0 or context_lifetime_seconds <= 0:
            raise ValueError("identity lifetimes must be positive")
        snapshot = store.snapshot()
        if _atom(snapshot, audience_root) != expected_audience:
            raise FederatedIdentityDenied(
                "audience graph root does not match requested audience"
            )
        parameters = {
            "expected_audience": expected_audience,
            "expected_issuer": expected_issuer,
            "expected_nonce_sha256": hashlib.sha256(
                expected_nonce.encode("utf-8")
            ).hexdigest(),
        }
        try:
            evidence_root = self._attestation_broker.run(
                store,
                self._attestation_protocol,
                self._verification_court_root,
                subject_name=ASSERTION_SUBJECT_NAME,
                subject_content=content,
                external_parameters=parameters,
            )
            statement = self._attestation_broker.verify(
                store.snapshot(),
                self._attestation_protocol,
                evidence_root,
                expected_court_root=self._verification_court_root,
                expected_subject_name=ASSERTION_SUBJECT_NAME,
                expected_subject_digest=hashlib.sha256(content).hexdigest(),
                expected_parameters=parameters,
                max_age_seconds=max_assertion_age_seconds,
            )
        except CourtEvidenceDenied as exc:
            raise FederatedIdentityDenied(
                "federated identity verification failed"
            ) from exc
        try:
            details = statement["predicate"]["details"]
        except (KeyError, TypeError) as exc:
            raise FederatedIdentityDenied(
                "identity evidence has no verified claims"
            ) from exc
        if not isinstance(details, Mapping):
            raise FederatedIdentityDenied(
                "identity evidence claims are invalid"
            )
        claims = {
            name: _required_detail(details, name)
            for name in (
                "issuer",
                "subject_reference",
                "audience",
                "assurance",
                "authentication_method",
                "issued_at",
                "auth_time",
                "expires_at",
            )
        }
        if claims["issuer"] != expected_issuer:
            raise FederatedIdentityDenied("verified identity issuer mismatched")
        if claims["audience"] != expected_audience:
            raise FederatedIdentityDenied("verified identity audience mismatched")
        current = time.time() if now is None else now
        issued_at = _timestamp(details, "issued_at")
        auth_time = _timestamp(details, "auth_time")
        expires_at = _timestamp(details, "expires_at")
        if issued_at > current + 5 or current - issued_at > max_assertion_age_seconds:
            raise FederatedIdentityDenied("verified identity assertion is stale")
        if auth_time > current + 5:
            raise FederatedIdentityDenied("verified authentication time is future")
        if expires_at <= current:
            raise FederatedIdentityDenied("verified identity assertion expired")
        assurance_root = self._assurance_roots.get(claims["assurance"])
        if assurance_root is None or assurance_root not in store.snapshot().cells:
            raise FederatedIdentityDenied(
                "identity assurance is not released"
            )
        external_root = federated_subject_root(claims["subject_reference"])
        subject_root = self._resolve_subject(
            store.snapshot(),
            external_root=external_root,
            tenant_root=tenant_root,
            audience_root=audience_root,
            now=current,
        )
        lifetime = min(
            context_lifetime_seconds,
            max(0.0, expires_at - current),
            3600.0,
        )
        if lifetime <= 0:
            raise FederatedIdentityDenied("identity authority lifetime elapsed")
        context = self._authentication_broker.mint_authenticated_context(
            subject_root,
            tenant_root=tenant_root,
            assurance_root=assurance_root,
            lifetime_seconds=lifetime,
        )
        return FederatedAuthentication(
            _FEDERATED_AUTHENTICATION_KEY,
            context,
            evidence_root,
            subject_root,
            tenant_root,
            audience_root,
            assurance_root,
            external_root,
            claims,
        )


__all__ = [
    "ASSERTION_SUBJECT_NAME",
    "MAX_ASSERTION_BYTES",
    "FederatedIdentityDenied",
    "FederatedAuthentication",
    "FederatedIdentityBroker",
    "federated_subject_reference",
    "federated_subject_root",
    "provision_federated_identity_binding",
]
