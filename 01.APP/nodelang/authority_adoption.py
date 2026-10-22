"""Transient, existing-owner authorization for a later graph adoption.

The local migration executor consumes an existing-owner authorization in one
revision-checked bootstrap commit. Local history is not an external rollback
anchor. Snapshot hashing is deliberate adoption work, never a routine read.
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
    # The digest walks the whole graph (minutes at founder scale): the validity window
    # starts after it, or the statement is already expired when it is issued.
    source_digest = snapshot_digest(head.snapshot)
    issued_at = time.time()
    statement = AuthorityAdoptionAuthorization(2, request_id, application_root,
        owner_root, tenant, identity_protocol.root_id, authorization_protocol.root_id,
        policy_root, _request_digest(request), head.snapshot.revision,
        source_digest, head.chain_digest,
        hashlib.sha256(successor_public_key).hexdigest(), *successor_binding, issued_at,
        issued_at + lifetime_seconds, key_id, key_version)
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


def application_adoption_root(graph_id):
    """One immutable checkpoint identity within the newly admitted authority."""
    return str(uuid.uuid5(uuid.UUID(graph_id), 'application-authority-adoption/v1'))


def adopt_application_authority(store, key_provider, *, source_history_digest):
    """Anchor the receipt-owning application's retained history, without rewriting it.

    This is the trusted local migration owner, not a request endpoint. Its
    authenticated context comes only from the original receipt/key restoration.
    Publication of the unselected physical generation remains the migrator's job.
    """
    from types import SimpleNamespace
    from . import universal_application as application, commit_intent
    from .runtime_caller_capability import WindowsDpapiCallerKeyStore
    from .unified_authority import _initialize_unified_authority
    from .universal_cell import InvalidCell

    with store._lock:
        head = store.snapshot_transition()
        if head.snapshot.revision < 1 or head.chain_digest != source_history_digest:
            raise InvalidCell('application adoption history hash mismatch')
        if getattr(store, '_signed_commit_authority', None) is not None:
            raise InvalidCell('application adoption already has a signed owner')
        try:
            authorization = application._restore_application_authorization(store, key_provider)
            protocol = application.open_agent_body_protocol(head.snapshot,
                prefix=application._AGENT_BODY_PROTOCOL_PREFIX)
            body = application.read_agent_body(head.snapshot, protocol, authorization.protocol,
                application._AGENT_BODY_ROOT)
            session = application.read_agent_session(head.snapshot, protocol, authorization.protocol,
                application._AGENT_SESSION_ROOT)
            receipts = application._verify_application_agent_receipts(store, authorization,
                SimpleNamespace(protocol=protocol, body=body, session=session))
            if not receipts:
                raise InvalidCell('application adoption receipts are missing')
        except (InvalidCell, ValueError) as exc:
            raise InvalidCell('application adoption receipts invalid: ' + str(exc)) from exc
        gate = ApplicationAdoptionGate(store, SimpleNamespace(
            authorization=authorization, application_root='app:archhub'))
        context = authorization.session.context()
        key_id, _version = authorization.relationship_broker.current_key_reference()
        public_key = WindowsDpapiCallerKeyStore(
            WindowsDpapiCallerKeyStore.default_path()).ensure('founder.bootstrap')
        arguments = dict(authentication_context=context, successor_public_key=public_key,
            successor_key_provider=key_provider, successor_key_id=key_id)
        statement = gate.authorize(**arguments, request_id=str(uuid.uuid4()))
        if statement.source_history_digest != source_history_digest:
            raise InvalidCell('application adoption history hash changed')

        def admitted():
            gate.verify(statement, **arguments)

        admitted()
        with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub',
                reason='anchor original application receipts and history under its signed owner'):
            return _initialize_unified_authority(store, key_provider, key_id=key_id,
                application_label='ArchHub', principal_label='Application owner',
                bootstrap_session_label='Founder bootstrap',
                bootstrap_session_public_key=public_key, composition_labels=(),
                adoption=asdict(statement), precommit_guard=admitted)


def verify_application_adoption(authority):
    """Recheck the signed original history prefix, including superseded Cells."""
    from .universal_cell import InvalidCell
    from .unified_authority import _property_values
    store, manifest, key_provider = authority.store, authority.manifest, authority.key_provider
    accepted = store.at(manifest.accepted_revision + 1)
    try:
        statement = AuthorityAdoptionAuthorization(**_property_values(authority, accepted,
            application_adoption_root(manifest.graph_id)))
    except (InvalidCell, TypeError, ValueError) as exc:
        raise InvalidCell('application adoption record is missing or invalid') from exc
    if (statement.version != 2 or statement.source_revision != manifest.accepted_revision
            or statement.application_root != 'app:archhub'
            or statement.owner_root not in accepted.cells
            or (statement.successor_authority_key_id, statement.successor_authority_key_version,
                statement.successor_authority_key_fingerprint) !=
                (manifest.key_id, manifest.key_version, manifest.key_fingerprint)
            or not key_provider.verify(statement.key_id, statement.key_version,
                _payload(statement), statement.signature)):
        raise InvalidCell('application adoption owner signature or binding is invalid')
    if store.revision_chain_digest(statement.source_revision) != statement.source_history_digest:
        raise InvalidCell('application adoption history hash mismatch')
    # open_unified_authority already verifies this exact accepted snapshot.
    # The signed checkpoint must name its digest; hashing it again adds no proof.
    if statement.source_snapshot_digest != manifest.accepted_snapshot_digest:
        raise InvalidCell('application adoption source snapshot hash mismatch')


def _legacy_continuation_id(authority, revision):
    return 'app:legacy-continuation:%s:%d' % (authority.manifest.graph_id, revision)


def verify_legacy_continuation(authority, snapshot, parent_root, parent_revision):
    """A signed head may bridge only the exact recorded legacy history prefix."""
    from .universal_cell import InvalidCell
    cell = snapshot.cells.get(_legacy_continuation_id(authority, snapshot.revision))
    if cell is None or (cell.link0, cell.link1) != (authority.manifest.head_index_root, parent_root):
        raise InvalidCell('legacy continuation record is missing')
    try:
        record = json.loads(cell.atom)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidCell('legacy continuation record is invalid') from error
    if record != dict(anchor=parent_revision, through=snapshot.revision - 1,
            history=authority.store.revision_chain_digest(snapshot.revision - 1)):
        raise InvalidCell('legacy continuation history does not match')


def resume_application_legacy_authority(authority, *, index_budget: int = 10_000,
                                        record_budget: int = 100_000):
    """Re-sign the verified unsigned suffix left by the released 2230 kernel.

    Only the application's verified adoption manifest admits this transition.
    Existing signed history is audited first; immutable head records cannot be
    changed by the legacy writer. The new signed record binds every suffix byte
    and explicitly represents the gap in the same authority's head ancestry.
    """
    from types import SimpleNamespace
    from . import universal_application as application, unified_authority as unified, commit_intent
    from .cell_protocols import _relation_chain_ids, read_relation
    from .universal_cell import Cell, InvalidCell, revision_chain_digest_step
    store = authority.store
    with store._lock:
        snapshot = store.snapshot()
        current = unified._current_head_member(authority, snapshot)
        if current is None:
            return  # Ordinary signed verification reports a missing head.
        head = current.participant_id
        anchor = unified._decode_value(authority, snapshot,
            unified._single_member(snapshot, head, authority.role('head-revision')))
        if type(anchor) is not int or anchor >= snapshot.revision:
            return
        if authority.manifest.accepted_revision <= 1:
            raise InvalidCell('legacy continuation requires verified application adoption')
        historical = store.at(anchor)
        unified._verify_current_head(authority, historical)
        original = unified._current_head_member(authority, historical)
        if original != current:
            raise InvalidCell('legacy continuation changed the signed head index')
        protected = set(_relation_chain_ids(historical, authority.manifest.head_index_root, budget=index_budget))
        protected.add(current.incidence_id)
        # The entire head chain and its encoded values are immutable records.
        pending, seen = [head], set()
        value_roles = {authority.role(name) for name in ('parent-head-digest', 'head-revision',
            'snapshot-digest', 'key-id', 'key-version', 'key-fingerprint', 'signature')}
        while pending:
            root = pending.pop()
            if root in seen:
                continue
            seen.add(root)
            protected.update(_relation_chain_ids(historical, root, budget=record_budget))
            revision = unified._decode_value(authority, historical,
                unified._single_member(historical, root, authority.role('head-revision')))
            protected.add(_legacy_continuation_id(authority, revision))
            for member in read_relation(historical, root, budget=record_budget):
                protected.add(member.incidence_id)
                if member.role_id == authority.role('parent-head'):
                    pending.append(member.participant_id)
                if member.role_id in value_roles:
                    value = member.participant_id
                    protected.update(_relation_chain_ids(historical, value, budget=record_budget))
                    for part in read_relation(historical, value, budget=record_budget):
                        protected.update((part.incidence_id, part.participant_id))
        digest = bytes.fromhex(store.revision_chain_digest(anchor))
        for revision in range(anchor + 1, snapshot.revision + 1):
            changed = store._changed_at(revision)
            if any(cell.id in protected for cell in changed):
                raise InvalidCell('legacy continuation changed immutable signed head records')
            digest = revision_chain_digest_step(digest, revision, changed)
            if digest.hex() != store.revision_chain_digest(revision):
                raise InvalidCell('legacy continuation revision integrity does not match')
        authorization = application._restore_application_authorization(store, authority.key_provider)
        protocol = application.open_agent_body_protocol(snapshot, prefix=application._AGENT_BODY_PROTOCOL_PREFIX)
        body = application.read_agent_body(snapshot, protocol, authorization.protocol, application._AGENT_BODY_ROOT)
        session = application.read_agent_session(snapshot, protocol, authorization.protocol, application._AGENT_SESSION_ROOT)
        if not application._verify_application_agent_receipts(store, authorization,
                SimpleNamespace(protocol=protocol, body=body, session=session)):
            raise InvalidCell('legacy continuation application receipts are missing')
        marker = Cell(_legacy_continuation_id(authority, snapshot.revision + 1),
            authority.manifest.head_index_root, head, json.dumps(dict(anchor=anchor,
                through=snapshot.revision, history=digest.hex()), sort_keys=True).encode())
        with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub',
                reason='sign verified original-owner legacy continuation'):
            unified._commit_signed_change(authority, snapshot, create=(marker,), replace_cells=())
        print('  adoption   : verified legacy continuation anchor=%d through=%d signed=%d' %
            (anchor, snapshot.revision, store.revision), flush=True)
