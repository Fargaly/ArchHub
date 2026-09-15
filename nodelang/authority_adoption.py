"""Transient, existing-owner authorization for a later graph adoption.

This does not adopt, activate, grant successor rights, or consume a request.
The eventual adopter must verify immediately before its revision-checked commit
and record the request's consumption. Local history is not an external rollback
anchor. Snapshot hashing is deliberate full-source work, never a startup read.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import time
import uuid

from .cell_authorization import AuthorizationRequest, require_authorization
from .cell_identity import (
    RelationshipAuthorityDenied, active_membership_roots,
    verify_relationship_authority_snapshot,
)
from .cell_revision_checkpoint import snapshot_digest


class ApplicationAdoptionGate:
    """Owner-service boundary bound to its restored application registry.

    Construct only inside the existing application owner with its own store and
    registry. Neither object nor any policy/broker field comes from a request.
    The lower-level signer is a trusted in-process primitive, not an admission
    endpoint: a caller allowed to choose a policy could choose an unrelated one.
    This gate never falls back to the desktop founder's authentication context.
    """

    def __init__(self, store, registry):
        self._store = store
        self._registry = registry

    def _arguments(self, authentication_context):
        if authentication_context is None:
            raise RelationshipAuthorityDenied("adoption requires an explicit authenticated context")
        authority = self._registry.authorization
        request = AuthorizationRequest(
            action_root=authority.protocol.actions["manage-policy"],
            object_root=self._registry.application_root,
            resource_lineage_roots=(authority.scope_root,),
            purpose_root=authority.purpose_root,
            classification_root=authority.classification_root,
            audience_root=authority.audience_root,
        )
        arguments = (self._store, authority.identity_protocol, authority.protocol,
            authority.policy_root, authority.broker, authentication_context, request)
        binding = dict(application_root=self._registry.application_root,
            owner_root=authority.subject_root)
        return authority.relationship_broker, arguments, binding

    def authorize(self, *, authentication_context, successor_public_key,
            successor_key_provider, successor_key_id, request_id, lifetime_seconds=120.0):
        signer, arguments, binding = self._arguments(authentication_context)
        return signer.authorize_adoption(*arguments, **binding,
            successor_public_key=successor_public_key, request_id=request_id,
            successor_key_provider=successor_key_provider, successor_key_id=successor_key_id,
            lifetime_seconds=lifetime_seconds)

    def verify(self, statement, *, authentication_context, successor_public_key,
            successor_key_provider, successor_key_id):
        signer, arguments, binding = self._arguments(authentication_context)
        return verify_authority_adoption_authorization(statement, signer,
            *arguments, **binding, successor_public_key=successor_public_key,
            successor_key_provider=successor_key_provider, successor_key_id=successor_key_id)

    def context_factory(self, binding_root):
        """Bind input predicates to the owner's selected, attached graph descriptor."""
        from .application_policy_context import ApplicationPolicyContextFactory
        return ApplicationPolicyContextFactory.from_graph(
            self._store, self._registry, binding_root,
        )


@dataclass(frozen=True, slots=True)
class AuthorityAdoptionAuthorization:
    version: int
    request_id: str
    application_root: str
    owner_root: str
    tenant_root: str
    identity_protocol_root: str
    authorization_protocol_root: str
    policy_root: str
    authorization_request_digest: str
    source_revision: int
    source_snapshot_digest: str
    source_history_digest: str
    successor_key_fingerprint: str
    successor_authority_key_id: str
    successor_authority_key_version: int
    successor_authority_key_fingerprint: str
    issued_at: float
    expires_at: float
    key_id: str
    key_version: int
    signature: str = ""


def _payload(statement):
    values = asdict(statement)
    del values["signature"]
    return b"ArchHub/authority-adoption-authorization/v2\0" + json.dumps(
        values, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _request_digest(request):
    # A caller-supplied historical clock must never freeze live policy checks.
    values = asdict(replace(request, now=None))
    return hashlib.sha256(json.dumps(values, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _successor_binding(provider, key_id):
    from .cell_secret_keys import SigningKeyReference
    reference = provider.current_reference(key_id)
    SigningKeyReference(reference.key_id, reference.version)
    fingerprint = provider.key_fingerprint(reference.key_id, reference.version)
    if (reference.key_id != key_id or type(fingerprint) is not str or
            len(fingerprint) != 64 or any(value not in "0123456789abcdef" for value in fingerprint)):
        raise RelationshipAuthorityDenied("adoption successor key reference is invalid")
    return reference.key_id, reference.version, fingerprint


def _verify_successor_binding(statement, provider, key_id):
    if (statement.successor_authority_key_id, statement.successor_authority_key_version,
            statement.successor_authority_key_fingerprint) != _successor_binding(provider, key_id):
        raise RelationshipAuthorityDenied("adoption successor authority key changed")


def _authorize(snapshot, relationship_broker, identity_protocol,
        authorization_protocol, policy_root, authentication_broker,
        authentication_context, request, application_root, owner_root, now):
    if (type(application_root) is not str or not application_root or
            type(owner_root) is not str or not owner_root or
            application_root not in snapshot.cells or owner_root not in snapshot.cells or
            request.object_root != application_root or
            request.action_root != authorization_protocol.actions["manage-policy"]):
        raise RelationshipAuthorityDenied("adoption requires exact application manage-policy")
    identity = authentication_broker.resolve(authentication_context, now=now)
    if identity.subject_root != owner_root or not identity.tenant_root:
        raise RelationshipAuthorityDenied("adoption owner authentication does not match")
    verified = verify_relationship_authority_snapshot(
        snapshot, identity_protocol, relationship_broker, now=now)
    memberships = active_membership_roots(snapshot, identity_protocol,
        relationship_broker, owner_root, identity.tenant_root,
        now=now, authority_snapshot=verified)
    if identity.tenant_root not in memberships:
        raise RelationshipAuthorityDenied("adoption requires existing signed tenant membership")
    decision = require_authorization(snapshot, authorization_protocol, policy_root,
        authentication_broker, authentication_context, replace(request, now=now),
        resolver_state=verified)
    if decision.subject_root != owner_root:
        raise RelationshipAuthorityDenied("adoption policy subject does not match")
    return identity.tenant_root


def _prepare_adoption_statement(relationship_broker, store, identity_protocol,
        authorization_protocol, policy_root, authentication_broker,
        authentication_context, request, *, application_root, owner_root,
        successor_public_key, successor_key_provider, successor_key_id,
        request_id, lifetime_seconds=120.0):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if type(request_id) is not str:
        raise ValueError("adoption request identity must be a UUID")
    uuid.UUID(request_id)
    if (type(lifetime_seconds) not in (int, float) or
            not math.isfinite(lifetime_seconds) or not 0 < lifetime_seconds <= 300):
        raise ValueError("adoption authorization lifetime must be within five minutes")
    if type(successor_public_key) is not bytes:
        raise ValueError("successor public key must be bytes")
    Ed25519PublicKey.from_public_bytes(successor_public_key)
    successor_binding = _successor_binding(successor_key_provider, successor_key_id)
    head = store.snapshot_transition()
    now = time.time()
    tenant = _authorize(head.snapshot, relationship_broker, identity_protocol,
        authorization_protocol, policy_root, authentication_broker,
        authentication_context, request, application_root, owner_root, now)
    key_id, key_version = relationship_broker.current_key_reference()
    statement = AuthorityAdoptionAuthorization(2, request_id, application_root,
        owner_root, tenant, identity_protocol.root_id, authorization_protocol.root_id,
        policy_root, _request_digest(request), head.snapshot.revision,
        snapshot_digest(head.snapshot), head.chain_digest,
        hashlib.sha256(successor_public_key).hexdigest(), *successor_binding, now,
        now + lifetime_seconds, key_id, key_version)
    _fresh(store, statement)
    _verify_successor_binding(statement, successor_key_provider, successor_key_id)
    return statement


def _fresh(store, statement):
    head = store.snapshot_transition()
    if (head.snapshot.revision != statement.source_revision or
            head.chain_digest != statement.source_history_digest):
        raise RelationshipAuthorityDenied("adoption source changed")
    return head


def verify_authority_adoption_authorization(statement, relationship_broker, store,
        identity_protocol, authorization_protocol, policy_root,
        authentication_broker, authentication_context, request, *,
        application_root, owner_root, successor_public_key, successor_key_provider,
        successor_key_id):
    """Recheck source, signature and current permission; return required base revision."""
    if type(statement) is not AuthorityAdoptionAuthorization or statement.version != 2:
        raise RelationshipAuthorityDenied("adoption authorization format is invalid")
    now = time.time()
    if (not math.isfinite(statement.issued_at) or not math.isfinite(statement.expires_at)
            or not statement.issued_at <= now < statement.expires_at
            or not 0 < statement.expires_at - statement.issued_at <= 300):
        raise RelationshipAuthorityDenied("adoption authorization expired or invalid")
    _verify_successor_binding(statement, successor_key_provider, successor_key_id)
    if (type(successor_public_key) is not bytes or
            (statement.application_root, statement.owner_root,
             statement.identity_protocol_root, statement.authorization_protocol_root,
             statement.policy_root, statement.authorization_request_digest,
             statement.successor_key_fingerprint) !=
            (application_root, owner_root, identity_protocol.root_id,
             authorization_protocol.root_id, policy_root, _request_digest(request),
             hashlib.sha256(successor_public_key).hexdigest())):
        raise RelationshipAuthorityDenied("adoption authorization binding does not match")
    if not relationship_broker.verify_signature(_payload(statement), statement.signature,
            statement.key_id, statement.key_version):
        raise RelationshipAuthorityDenied("adoption authorization signature is invalid")
    head = _fresh(store, statement)
    tenant = _authorize(head.snapshot, relationship_broker, identity_protocol,
        authorization_protocol, policy_root, authentication_broker,
        authentication_context, request, application_root, owner_root, now)
    if tenant != statement.tenant_root or snapshot_digest(head.snapshot) != statement.source_snapshot_digest:
        raise RelationshipAuthorityDenied("adoption source or tenant does not match")
    _fresh(store, statement)
    _verify_successor_binding(statement, successor_key_provider, successor_key_id)
    return statement.source_revision
