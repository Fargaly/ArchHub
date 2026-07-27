from __future__ import annotations

import hashlib
import hmac
import json
import time
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import MISSING, fields, replace
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc import jwk

import nodelang.cell_cloud_sessions as cloud_sessions
from nodelang.cell_attestations import (
    CourtAttestationBroker,
    CourtInvocation,
    CourtResult,
    bootstrap_attestation_protocol,
    build_court_definition,
    read_court_attestation,
)
from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    instantiate_catalog_definition,
    project_catalog,
)
from nodelang.cell_cloud_gate import CloudRequestGate
from nodelang.cell_cloud_sessions import (
    CloudSessionBroker,
    CloudSessionDenied,
    TenantAdmissionEvidence,
    bootstrap_cloud_session_protocol,
    device_root_for_thumbprint,
    project_cloud_session_protocol,
    provision_device_binding,
    verify_cloud_session_manifest,
)
from nodelang.cell_device_custody import (
    ActiveDeviceCustodyVerifier,
    bootstrap_device_custody_protocol,
    register_device_custody,
    revoke_device_custody,
)
from nodelang.cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
)
from nodelang.cell_federated_identity import (
    FederatedAuthentication,
    FederatedIdentityBroker,
    FederatedIdentityDenied,
    federated_subject_reference,
    federated_subject_root,
    provision_federated_identity_binding,
)
from nodelang.cell_identity import (
    RelationshipAuthorityBroker,
    bootstrap_identity_protocol,
    grant_authority_relationship,
    restore_relationship_authority_history,
    revoke_authority_relationship,
    verify_authority_relationship,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_registry_projection import project_identity_protocol
from nodelang.cell_native_auth import (
    NativeAuthenticationDenied,
    NativeAuthorizationBroker,
    SignedNativeClientAdmissionVerifier,
    activate_native_client_registration,
    bootstrap_native_authentication_protocol,
    build_native_client_registration,
    exchange_native_authorization_code,
    issue_native_cloud_session,
)
from nodelang.cell_oidc_discovery import OidcDiscoveryKeyResolver
from nodelang.cell_protocols import (
    CellBatch,
    prepare_append_relation_member,
    read_relation,
    remove_relation_member,
)
from nodelang.cell_lifecycle import (
    append_wip_graph_revision,
    graph_content_bytes,
    promote_revision,
    read_lifecycle_instance,
    read_revision,
    restore_revision_as_wip,
    state_heads,
)
from nodelang.cell_replay_policy_authority import (
    PublishedProofReplayPolicyVerifier,
)
from nodelang.native_cloud_login import NativeCloudLogin, NativeCloudLoginDenied
from nodelang.remote_native_cloud_login import (
    RemoteNativeCloudLoginBroker,
    ReturningDeviceAdmissionDenied,
    ReturningDeviceAdmissionVerifier,
)
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


ISSUER = "https://identity.example.test"
AUDIENCE = "archhub-desktop"
EXTERNAL_SUBJECT = "provider-user-48291"
NONCE = "one-time-login-nonce"
PROVIDER_KEY = b"provider-test-key-with-more-than-32-bytes"
CHECKS = (
    "signature",
    "issuer",
    "audience",
    "expiry",
    "nonce",
    "subject",
)


class _TestTenantAdmissionVerifier:
    """Explicit test boundary; production uses PublishedTenantAdmissionVerifier."""

    def verify(
        self,
        snapshot,
        *,
        tenant_root: str,
        subject_root: str,
        now: float,
    ) -> TenantAdmissionEvidence:
        del now
        if tenant_root not in snapshot.cells or subject_root not in snapshot.cells:
            raise PermissionError("test tenant or subject is absent")
        return TenantAdmissionEvidence(
            tenant_root,
            tenant_root,
            tenant_root,
            tenant_root,
        )


class _TestDeviceCustodyVerifier:
    """Explicit fixture boundary for tests that predate custody compositions."""

    def verify(self, snapshot, *, device_root: str, now: float) -> str:
        del now
        if device_root not in snapshot.cells:
            raise PermissionError("test device is absent")
        return device_root


class _TestReplayPolicyAuthorityVerifier:
    def verify(self, snapshot, protocol):
        policy = cloud_sessions.read_proof_replay_policy(
            snapshot, protocol
        )
        lifecycle_root = protocol.proof_replay_policy_lifecycle_root
        if lifecycle_root is None:
            raise PermissionError("test replay policy is not released")
        roots = {
            name: lifecycle_root + ":" + name
            for name in ("wip", "shared", "published")
        }
        if any(root not in snapshot.cells for root in roots.values()):
            raise PermissionError("test replay release evidence is absent")
        return cloud_sessions.ProofReplayPolicyReleaseEvidence(
            policy_root=policy.root_id,
            lifecycle_instance_root=lifecycle_root,
            wip_revision_root=roots["wip"],
            shared_revision_root=roots["shared"],
            published_revision_root=roots["published"],
            capacity=policy.capacity,
            retention_seconds=policy.retention_seconds,
        )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _assertion(*, now: float, **changes: object) -> bytes:
    payload: dict[str, object] = {
        "iss": ISSUER,
        "sub": EXTERNAL_SUBJECT,
        "aud": AUDIENCE,
        "nonce": NONCE,
        "iat": now,
        "auth_time": now - 1,
        "exp": now + 120,
        "assurance": "aal2",
        "method": "webauthn",
    }
    payload.update(changes)
    signature = hmac.new(PROVIDER_KEY, _canonical(payload), hashlib.sha256).hexdigest()
    return _canonical({"claims": payload, "signature": signature})


def _runner(invocation: CourtInvocation) -> CourtResult:
    try:
        document = json.loads(invocation.subject_content.decode("utf-8"))
        claims = document["claims"]
        signature = document["signature"]
    except Exception:
        claims = {}
        signature = ""
    expected_signature = hmac.new(
        PROVIDER_KEY, _canonical(claims), hashlib.sha256
    ).hexdigest()
    now = time.time()
    nonce_digest = hashlib.sha256(
        str(claims.get("nonce", "")).encode("utf-8")
    ).hexdigest()
    checks = {
        "signature": hmac.compare_digest(signature, expected_signature),
        "issuer": claims.get("iss")
        == invocation.external_parameters["expected_issuer"],
        "audience": claims.get("aud")
        == invocation.external_parameters["expected_audience"],
        "expiry": float(claims.get("exp", 0)) > now,
        "nonce": nonce_digest
        == invocation.external_parameters["expected_nonce_sha256"],
        "subject": bool(claims.get("sub")),
    }
    subject_reference = (
        federated_subject_reference(str(claims["iss"]), str(claims["sub"]))
        if checks["issuer"] and checks["subject"] else "invalid"
    )
    details = {
        "issuer": str(claims.get("iss", "")),
        "subject_reference": subject_reference,
        "audience": str(claims.get("aud", "")),
        "assurance": str(claims.get("assurance", "")),
        "authentication_method": str(claims.get("method", "")),
        "issued_at": str(claims.get("iat", "")),
        "auth_time": str(claims.get("auth_time", "")),
        "expires_at": str(claims.get("exp", "")),
    }
    return CourtResult(all(checks.values()), checks, details)


def _cell(root: str, value: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _world(
    *,
    bind_identity: bool = True,
    tenant_member: bool = True,
    store: CellStore | None = None,
    relationship_key_provider: MemorySigningKeyProvider | None = None,
):
    store = store or CellStore()
    identity = bootstrap_identity_protocol(store, prefix="test:identity")
    attestation = bootstrap_attestation_protocol(
        store, prefix="test:attestation"
    )
    roots = {
        "administrator": "test:subject:administrator",
        "subject": "test:subject:member",
        "tenant": "test:tenant:studio",
        "audience": "test:audience:desktop",
        "aal2": "test:assurance:aal2",
    }
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        _cell(roots["administrator"], "administrator"),
        _cell(roots["subject"], "member"),
        _cell(roots["tenant"], "studio"),
        _cell(roots["audience"], AUDIENCE),
        _cell(roots["aal2"], "aal2"),
    ))
    key_provider = relationship_key_provider or MemorySigningKeyProvider(
        "test:relationship-key", b"relationship-key-material-32-bytes+"
    )
    relationship_broker = RelationshipAuthorityBroker(
        (roots["administrator"],),
        key_provider=key_provider,
        key_id="test:relationship-key",
    )
    membership_root = None
    if tenant_member:
        handle = relationship_broker.mint_from_trusted_administrator(
            roots["administrator"]
        )
        membership_root = grant_authority_relationship(
            store,
            identity,
            relationship_broker,
            handle,
            relationship_id="test:membership:subject-tenant",
            source_root=roots["subject"],
            target_root=roots["tenant"],
            kind="membership",
            tenant_root=roots["tenant"],
            administrator_root=roots["administrator"],
            reason="tenant member",
        )
    binding_root = None
    if bind_identity:
        handle = relationship_broker.mint_from_trusted_administrator(
            roots["administrator"]
        )
        binding_root = provision_federated_identity_binding(
            store,
            identity,
            relationship_broker,
            handle,
            relationship_id="test:binding:provider-subject",
            issuer=ISSUER,
            external_subject=EXTERNAL_SUBJECT,
            local_subject_root=roots["subject"],
            tenant_root=roots["tenant"],
            audience_root=roots["audience"],
            administrator_root=roots["administrator"],
            reason="explicit provider identity binding",
        )
    court = build_court_definition(
        store,
        attestation,
        court_id="test:court:federated-identity",
        name="Federated identity assertion verification",
        builder_id="test:oidc-verifier",
        runner_version="1",
        policy_digest=hashlib.sha256(b"test-oidc-policy-v1").hexdigest(),
        checks=CHECKS,
    )
    court_broker = CourtAttestationBroker(
        key_provider=MemorySigningKeyProvider(
            "test:court-key", b"court-key-material-with-more-than-32"
        ),
        key_id="test:court-key",
    )
    court_broker.admit_court(
        store.snapshot(), attestation, court.root_id, _runner
    )
    authentication_broker = AuthenticationBroker()
    federated = FederatedIdentityBroker(
        attestation_protocol=attestation,
        attestation_broker=court_broker,
        verification_court_root=court.root_id,
        identity_protocol=identity,
        relationship_broker=relationship_broker,
        authentication_broker=authentication_broker,
        assurance_roots={"aal2": roots["aal2"]},
    )
    return {
        "store": store,
        "identity": identity,
        "relationship_broker": relationship_broker,
        "authentication_broker": authentication_broker,
        "federated": federated,
        "roots": roots,
        "binding_root": binding_root,
        "membership_root": membership_root,
        "relationship_key_provider": key_provider,
    }


def _authenticate(world, assertion: bytes, *, now: float):
    roots = world["roots"]
    return world["federated"].authenticate(
        world["store"],
        assertion,
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE,
        expected_nonce=NONCE,
        tenant_root=roots["tenant"],
        audience_root=roots["audience"],
        now=now,
    )


def test_federated_identity_requires_verified_binding_and_membership():
    now = time.time()
    world = _world()
    authenticated = _authenticate(world, _assertion(now=now), now=now)
    resolved = world["authentication_broker"].resolve(authenticated.context)
    assert resolved.subject_root == world["roots"]["subject"]
    assert resolved.tenant_root == world["roots"]["tenant"]
    assert resolved.assurance_root == world["roots"]["aal2"]
    assert authenticated.external_identity_root == federated_subject_root(
        federated_subject_reference(ISSUER, EXTERNAL_SUBJECT)
    )


def test_raw_assertion_and_external_subject_never_enter_cells():
    now = time.time()
    world = _world()
    assertion = _assertion(now=now)
    authenticated = _authenticate(world, assertion, now=now)
    atoms = tuple(cell.atom for cell in world["store"].snapshot().cells.values())
    joined = b"\n".join(atoms)
    assert assertion not in joined
    assert EXTERNAL_SUBJECT.encode("utf-8") not in joined
    assert hashlib.sha256(assertion).hexdigest().encode("ascii") in joined
    assert authenticated.claims["subject_reference"].encode("ascii") in joined


@pytest.mark.parametrize("missing", ["binding", "membership"])
def test_valid_provider_proof_has_no_authority_without_graph_relationships(missing):
    now = time.time()
    world = _world(
        bind_identity=missing != "binding",
        tenant_member=missing != "membership",
    )
    with pytest.raises(FederatedIdentityDenied):
        _authenticate(world, _assertion(now=now), now=now)


@pytest.mark.parametrize("change", [
    {"iss": "https://attacker.example"},
    {"aud": "another-client"},
    {"nonce": "replayed-nonce"},
    {"exp": 1},
])
def test_invalid_provider_assertions_fail_closed(change):
    now = time.time()
    world = _world()
    with pytest.raises(FederatedIdentityDenied):
        _authenticate(world, _assertion(now=now, **change), now=now)


def test_stale_assertion_and_unreleased_assurance_fail_closed():
    now = time.time()
    world = _world()
    with pytest.raises(FederatedIdentityDenied, match="stale"):
        _authenticate(
            world,
            _assertion(now=now, iat=now - 301, exp=now + 60),
            now=now,
        )
    with pytest.raises(FederatedIdentityDenied, match="assurance"):
        _authenticate(
            world,
            _assertion(now=now, assurance="unknown"),
            now=now,
        )


def test_revoked_audience_binding_stops_new_authentication():
    now = time.time()
    world = _world()
    _authenticate(world, _assertion(now=now), now=now)
    handle = world["relationship_broker"].mint_from_trusted_administrator(
        world["roots"]["administrator"]
    )
    revoke_authority_relationship(
        world["store"],
        world["identity"],
        world["relationship_broker"],
        handle,
        world["binding_root"],
        administrator_root=world["roots"]["administrator"],
        reason="provider account unlinked",
        now=now + 1,
    )
    with pytest.raises(FederatedIdentityDenied, match="audience binding"):
        _authenticate(world, _assertion(now=now + 2), now=now + 2)


DEVICE_SECRET = b"test-device-proof-key-material"
DEVICE_THUMBPRINT = base64.urlsafe_b64encode(
    hashlib.sha256(b"test-device-public-key").digest()
).rstrip(b"=").decode("ascii")
RESOURCE_URI = "https://api.archhub.test/v1/graph"


def _request_proof(
    *, access_token: str, now: float, proof_id: str = "proof-1", **changes
) -> bytes:
    claims = {
        "jti": proof_id,
        "htm": "GET",
        "htu": RESOURCE_URI,
        "nonce": "server-request-nonce",
        "iat": now,
        "ath": hashlib.sha256(access_token.encode("ascii")).hexdigest(),
        "thumbprint": DEVICE_THUMBPRINT,
    }
    claims.update(changes)
    signature = hmac.new(
        DEVICE_SECRET, _canonical(claims), hashlib.sha256
    ).hexdigest()
    return _canonical({"claims": claims, "signature": signature})


class _RequestProofVerifier:
    @property
    def replay_retention_seconds(self) -> float:
        return 10.0

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
        document = json.loads(proof.decode("utf-8"))
        claims = document["claims"]
        expected_signature = hmac.new(
            DEVICE_SECRET, _canonical(claims), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(document["signature"], expected_signature):
            raise ValueError("invalid proof signature")
        expected = {
            "htm": http_method,
            "htu": target_uri,
            "nonce": expected_nonce,
            "ath": hashlib.sha256(access_token.encode("ascii")).hexdigest(),
            "thumbprint": expected_thumbprint,
        }
        if any(claims.get(name) != value for name, value in expected.items()):
            raise ValueError("request proof binding mismatch")
        if abs(float(claims["iat"]) - now) > 5:
            raise ValueError("request proof is stale")
        return str(claims["jti"])


def _session_world(
    *,
    now: float,
    world=None,
    store: CellStore | None = None,
    relationship_key_provider: MemorySigningKeyProvider | None = None,
    action_root: str | None = None,
    proof_replay_capacity: int | None = None,
    request_proof_verifier=None,
    real_replay_policy_authority: bool = False,
):
    world = world or _world(
        store=store,
        relationship_key_provider=relationship_key_provider,
    )
    authentication = _authenticate(world, _assertion(now=now), now=now)
    roots = world["roots"]
    snapshot = world["store"].snapshot()
    if action_root is None:
        action_root = "test:action:read"
        world["store"].commit(
            snapshot.revision, create=(_cell(action_root, "read"),)
        )
    handle = world["relationship_broker"].mint_from_trusted_administrator(
        roots["administrator"]
    )
    device_binding_root = provision_device_binding(
        world["store"],
        world["identity"],
        world["relationship_broker"],
        handle,
        relationship_id="test:binding:device-subject",
        proof_key_thumbprint=DEVICE_THUMBPRINT,
        subject_root=roots["subject"],
        tenant_root=roots["tenant"],
        audience_root=roots["audience"],
        administrator_root=roots["administrator"],
        reason="user enrolled this proof-of-possession device",
        now=now,
    )
    verifier = request_proof_verifier or _RequestProofVerifier()
    protocol = bootstrap_cloud_session_protocol(
        world["store"],
        prefix="test:cloud-session",
        proof_replay_capacity=(
            cloud_sessions.DEFAULT_PROOF_REPLAY_CAPACITY
            if proof_replay_capacity is None else proof_replay_capacity
        ),
        proof_replay_retention_seconds=verifier.replay_retention_seconds,
    )
    if real_replay_policy_authority:
        (
            protocol,
            replay_policy_verifier,
            replay_policy_revision_roots,
        ) = _released_replay_policy_authority(
            world["store"], protocol
        )
    else:
        replay_lifecycle_root = (
            protocol.root_id + ":test-proof-replay-policy-lifecycle"
        )
        world["store"].commit(
            world["store"].revision,
            create=(
                _cell(replay_lifecycle_root, "test lifecycle"),
                _cell(replay_lifecycle_root + ":wip", "WIP"),
                _cell(replay_lifecycle_root + ":shared", "Shared"),
                _cell(replay_lifecycle_root + ":published", "Published"),
            ),
        )
        protocol = cloud_sessions.bind_proof_replay_policy_lifecycle(
            world["store"], protocol, replay_lifecycle_root
        )
        replay_policy_verifier = _TestReplayPolicyAuthorityVerifier()
        replay_policy_revision_roots = ()
    broker = CloudSessionBroker(
        session_protocol=protocol,
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=verifier,
        replay_policy_authority_verifier=replay_policy_verifier,
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=_TestDeviceCustodyVerifier(),
        session_issuer_root=roots["administrator"],
    )
    issued = broker.issue(
        world["store"],
        authentication,
        proof_key_thumbprint=DEVICE_THUMBPRINT,
        allowed_action_roots=(action_root,),
        now=now,
    )
    world.update({
        "session_protocol": protocol,
        "session_broker": broker,
        "issued_session": issued,
        "action_root": action_root,
        "device_binding_root": device_binding_root,
        "replay_policy_authority_verifier": replay_policy_verifier,
        "replay_policy_revision_roots": replay_policy_revision_roots,
    })
    return world


def _authenticate_request(world, proof: bytes, *, now: float, **changes):
    values = {
        "requested_action_root": world["action_root"],
        "http_method": "GET",
        "target_uri": RESOURCE_URI,
        "expected_nonce": "server-request-nonce",
    }
    values.update(changes)
    return world["session_broker"].authenticate_request(
        world["store"],
        world["issued_session"].access_token,
        proof,
        now=now,
        **values,
    )


def _released_replay_policy_authority(
    store: CellStore,
    protocol,
    *,
    actor_root: str = "test:replay-policy:actor",
    release_to: str = "published",
):
    if release_to not in {"wip", "shared", "published"}:
        raise ValueError("unknown replay-policy fixture release state")
    assembly = bootstrap_assembly_protocol(
        store, prefix="test:replay-policy:assembly"
    )
    library = build_standard_library_v0(
        store,
        assembly,
        prefix="test:replay-policy:library",
        catalog_id="test:replay-policy:catalog",
    )
    store.commit(
        store.revision,
        create=(_cell(actor_root, "Replay policy approver"),),
    )
    instance = instantiate_catalog_definition(
        store,
        assembly,
        library.catalog_root,
        library.definition_roots[2],
    )
    wip = append_wip_graph_revision(
        store,
        assembly,
        library.lifecycle_protocol,
        instance.root_id,
        content_root=protocol.proof_replay_policy_root,
        actor_root=actor_root,
        reason="govern replay policy",
    )
    attestation = bootstrap_attestation_protocol(
        store, prefix="test:replay-policy:attestation"
    )
    court = build_court_definition(
        store,
        attestation,
        court_id="test:court:replay-policy-lifecycle",
        name="Replay policy lifecycle",
        builder_id="test:replay-policy-court",
        runner_version="1",
        policy_digest=hashlib.sha256(
            b"replay policy lifecycle court"
        ).hexdigest(),
        checks=("graph-digest", "target-state"),
    )

    def runner(invocation: CourtInvocation) -> CourtResult:
        checks = {
            "graph-digest": hashlib.sha256(
                invocation.subject_content
            ).hexdigest() == invocation.subject_digest,
            "target-state": invocation.external_parameters.get(
                "targetState"
            ) in (
                library.lifecycle_protocol.states["shared"],
                library.lifecycle_protocol.states["published"],
            ),
        }
        return CourtResult(
            all(checks.values()),
            checks,
            {"court": "replay-policy-lifecycle"},
        )

    broker = CourtAttestationBroker()
    broker.admit_court(
        store.snapshot(), attestation, court.root_id, runner
    )

    def promote(source_root: str, target_root: str) -> str:
        snapshot = store.snapshot()
        source = read_revision(
            snapshot, library.lifecycle_protocol, source_root
        )
        parameters = {
            "asset": instance.root_id,
            "targetState": target_root,
        }
        evidence_root = broker.run(
            store,
            attestation,
            court.root_id,
            subject_name=source_root,
            subject_content=graph_content_bytes(
                snapshot, source.content_root
            ),
            external_parameters=parameters,
        )
        receipt = broker.consume(
            store.snapshot(),
            attestation,
            evidence_root,
            purpose="promote:%s:%s" % (instance.root_id, target_root),
            expected_court_root=court.root_id,
            expected_subject_name=source_root,
            expected_subject_digest=store.read(
                source.content_digest_root
            ).atom.decode("ascii"),
            expected_parameters=parameters,
        )
        return promote_revision(
            store,
            assembly,
            library.lifecycle_protocol,
            instance.root_id,
            target_state_root=target_root,
            source_revision_root=source_root,
            actor_root=actor_root,
            evidence_roots=(evidence_root,),
            evidence_receipts=(receipt,),
            attestation_broker=broker,
        )

    revisions = [wip]
    if release_to in {"shared", "published"}:
        shared = promote(wip, library.lifecycle_protocol.states["shared"])
        revisions.append(shared)
    if release_to == "published":
        published = promote(
            revisions[-1], library.lifecycle_protocol.states["published"]
        )
        revisions.append(published)
    protocol = cloud_sessions.bind_proof_replay_policy_lifecycle(
        store, protocol, instance.root_id
    )
    verifier = PublishedProofReplayPolicyVerifier(
        assembly,
        library.lifecycle_protocol,
        attestation,
        broker,
        court.root_id,
        instance.root_id,
    )
    return protocol, verifier, tuple(revisions)


def _replay_policy_verifier_fixture(*, release_to: str):
    store = CellStore()
    protocol = bootstrap_cloud_session_protocol(
        store, prefix="test:replay-policy:cloud-session"
    )
    protocol, verifier, revisions = _released_replay_policy_authority(
        store,
        protocol,
        release_to=release_to,
    )
    return store, protocol, verifier, revisions


def _promote_replay_policy_fixture(
    store: CellStore,
    verifier: PublishedProofReplayPolicyVerifier,
    instance_root: str,
    source_root: str,
    target_root: str,
    actor_root: str,
) -> str:
    snapshot = store.snapshot()
    source = read_revision(
        snapshot, verifier._lifecycle, source_root
    )
    parameters = {
        "asset": instance_root,
        "targetState": target_root,
    }
    evidence_root = verifier._attestation_broker.run(
        store,
        verifier._attestation,
        verifier._promotion_court_root,
        subject_name=source_root,
        subject_content=graph_content_bytes(
            snapshot, source.content_root
        ),
        external_parameters=parameters,
    )
    receipt = verifier._attestation_broker.consume(
        store.snapshot(),
        verifier._attestation,
        evidence_root,
        purpose="promote:%s:%s" % (instance_root, target_root),
        expected_court_root=verifier._promotion_court_root,
        expected_subject_name=source_root,
        expected_subject_digest=store.read(
            source.content_digest_root
        ).atom.decode("ascii"),
        expected_parameters=parameters,
    )
    return promote_revision(
        store,
        verifier._assembly,
        verifier._lifecycle,
        instance_root,
        target_state_root=target_root,
        source_revision_root=source_root,
        actor_root=actor_root,
        evidence_roots=(evidence_root,),
        evidence_receipts=(receipt,),
        attestation_broker=verifier._attestation_broker,
    )


def test_device_bound_session_is_visible_but_token_secret_is_not_stored():
    now = time.time()
    world = _session_world(now=now)
    issued = world["issued_session"]
    session = verify_cloud_session_manifest(
        world["store"].snapshot(),
        world["session_protocol"],
        issued.session_root,
    )
    assert session.subject_root == world["roots"]["subject"]
    assert session.device_root.endswith(DEVICE_THUMBPRINT)
    joined = b"\n".join(
        cell.atom for cell in world["store"].snapshot().cells.values()
    )
    assert issued.access_token.encode("ascii") not in joined
    assert hashlib.sha256(
        issued.access_token.encode("ascii")
    ).hexdigest().encode("ascii") in joined


def test_cloud_session_binds_one_real_published_replay_policy_revision():
    now = time.time()
    world = _session_world(
        now=now,
        proof_replay_capacity=2,
        real_replay_policy_authority=True,
    )
    _wip, _shared, published = world["replay_policy_revision_roots"]
    session = verify_cloud_session_manifest(
        world["store"].snapshot(),
        world["session_protocol"],
        world["issued_session"].session_root,
    )
    relationship = verify_authority_relationship(
        world["store"].snapshot(),
        world["identity"],
        world["relationship_broker"],
        world["issued_session"].authority_relationship_root,
        now=now + 1,
    )
    assert session.proof_replay_policy_release_root == published
    assert published in session.evidence_roots
    assert published in relationship.evidence_roots

    policy = cloud_sessions.read_proof_replay_policy(
        world["store"].snapshot(), world["session_protocol"]
    )
    capacity_cell = world["store"].read(policy.capacity_root)
    world["store"].commit(
        world["store"].revision,
        replace=(Cell(
            capacity_cell.id,
            capacity_cell.link0,
            capacity_cell.link1,
            b"1",
        ),),
    )
    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="released-policy-drift-proof",
    )
    with pytest.raises(
        CloudSessionDenied,
        match="no active Published release",
    ):
        _authenticate_request(world, proof, now=now + 1)


def test_real_replay_policy_verifier_denies_unbound_and_unreleased_states():
    store, protocol, verifier, _revisions = (
        _replay_policy_verifier_fixture(release_to="published")
    )
    with pytest.raises(InvalidCell, match="no lifecycle authority wire"):
        verifier.verify(
            store.snapshot(),
            replace(protocol, proof_replay_policy_lifecycle_root=None),
        )
    with pytest.raises(InvalidCell):
        verifier.verify(
            store.snapshot(),
            replace(
                protocol,
                proof_replay_policy_lifecycle_root=(
                    protocol.proof_replay_policy_root
                ),
            ),
        )
    definition_root = next(
        item["id"]
        for item in project_catalog(
            store.snapshot(),
            verifier._assembly,
            "test:replay-policy:catalog",
        )
        if item["name"] == "Versioned Asset"
    )
    other_instance = instantiate_catalog_definition(
        store,
        verifier._assembly,
        "test:replay-policy:catalog",
        definition_root,
    )
    read_lifecycle_instance(
        store.snapshot(),
        verifier._assembly,
        verifier._lifecycle,
        other_instance.root_id,
    )
    with pytest.raises(InvalidCell, match="wire was substituted"):
        verifier.verify(
            store.snapshot(),
            replace(
                protocol,
                proof_replay_policy_lifecycle_root=other_instance.root_id,
            ),
        )

    for release_to in ("wip", "shared"):
        draft_store, draft_protocol, draft_verifier, _ = (
            _replay_policy_verifier_fixture(release_to=release_to)
        )
        with pytest.raises(InvalidCell, match="one Published revision"):
            draft_verifier.verify(
                draft_store.snapshot(), draft_protocol
            )


def test_real_replay_policy_verifier_denies_multiple_published_heads():
    store, protocol, verifier, _revisions = (
        _replay_policy_verifier_fixture(release_to="published")
    )
    lifecycle = verifier._lifecycle
    instance = read_lifecycle_instance(
        store.snapshot(),
        verifier._assembly,
        lifecycle,
        protocol.proof_replay_policy_lifecycle_root,
    )
    pointer_root = instance.state_pointers[lifecycle.states["published"]]
    fake_revision_root = "test:replay-policy:forged-published-head"
    snapshot = store.snapshot()
    patch = prepare_append_relation_member(
        snapshot,
        pointer_root,
        lifecycle.role("revision"),
        fake_revision_root,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            Cell(
                fake_revision_root,
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"forged published head",
            ),
            *patch.create,
        ),
        replace=patch.replace,
    )
    with pytest.raises(InvalidCell, match="one Published revision"):
        verifier.verify(store.snapshot(), protocol)


def test_real_replay_policy_verifier_denies_forged_court_evidence():
    store, protocol, verifier, revisions = (
        _replay_policy_verifier_fixture(release_to="published")
    )
    published = read_revision(
        store.snapshot(), verifier._lifecycle, revisions[-1]
    )
    evidence = read_court_attestation(
        store.snapshot(),
        verifier._attestation,
        published.evidence_roots[0],
    )
    signature = store.read(evidence.signature_root)
    store.commit(
        store.revision,
        replace=(Cell(
            signature.id,
            signature.link0,
            signature.link1,
            b"forged-signature",
        ),),
    )
    with pytest.raises(InvalidCell, match="no admitted court evidence"):
        verifier.verify(store.snapshot(), protocol)


def test_real_replay_policy_verifier_denies_wrong_predecessor_evidence():
    store, protocol, verifier, revisions = (
        _replay_policy_verifier_fixture(release_to="published")
    )
    wip, _shared, published_root = revisions
    published_members = read_relation(
        store.snapshot(), published_root, budget=1024
    )
    predecessor_members = tuple(
        member
        for member in published_members
        if member.role_id == verifier._lifecycle.role("predecessor")
    )
    assert len(predecessor_members) == 1
    incidence = store.read(predecessor_members[0].incidence_id)
    store.commit(
        store.revision,
        replace=(Cell(
            incidence.id,
            incidence.link0,
            wip,
            incidence.atom,
        ),),
    )
    with pytest.raises(InvalidCell, match="no admitted court evidence"):
        verifier.verify(store.snapshot(), protocol)


def test_replacement_published_policy_invalidates_an_issued_session():
    now = time.time()
    world = _session_world(
        now=now,
        proof_replay_capacity=2,
        real_replay_policy_authority=True,
    )
    wip, _shared, published = world["replay_policy_revision_roots"]
    verifier = world["replay_policy_authority_verifier"]
    protocol = world["session_protocol"]
    actor_root = "test:replay-policy:actor"
    published_revision = read_revision(
        world["store"].snapshot(),
        verifier._lifecycle,
        published,
    )
    replacement_wip = restore_revision_as_wip(
        world["store"],
        verifier._assembly,
        verifier._lifecycle,
        protocol.proof_replay_policy_lifecycle_root,
        published,
        actor_root=actor_root,
        base_revision_root=wip,
        branch_root=published_revision.branch_root,
    )
    replacement_shared = _promote_replay_policy_fixture(
        world["store"],
        verifier,
        protocol.proof_replay_policy_lifecycle_root,
        replacement_wip,
        verifier._lifecycle.states["shared"],
        actor_root,
    )
    _promote_replay_policy_fixture(
        world["store"],
        verifier,
        protocol.proof_replay_policy_lifecycle_root,
        replacement_shared,
        verifier._lifecycle.states["published"],
        actor_root,
    )
    instance = read_lifecycle_instance(
        world["store"].snapshot(),
        verifier._assembly,
        verifier._lifecycle,
        protocol.proof_replay_policy_lifecycle_root,
    )
    assert len(state_heads(
        world["store"].snapshot(),
        verifier._lifecycle,
        instance.state_pointers[verifier._lifecycle.states["published"]],
    )) == 2

    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="replacement-policy-invalidates-session",
    )
    with pytest.raises(
        CloudSessionDenied,
        match="no active Published release",
    ):
        _authenticate_request(world, proof, now=now + 1)


def test_request_proof_mints_one_request_context_and_records_replay_identity():
    now = time.time()
    world = _session_world(now=now)
    token = world["issued_session"].access_token
    proof = _request_proof(access_token=token, now=now + 1)
    request_auth = _authenticate_request(world, proof, now=now + 1)
    resolved = world["authentication_broker"].resolve(
        request_auth.context, now=now + 2
    )
    assert resolved.subject_root == world["roots"]["subject"]
    assert request_auth.proof_use_root in world["store"].snapshot().cells
    with pytest.raises(CloudSessionDenied, match="replayed"):
        _authenticate_request(world, proof, now=now + 2)


def test_dpop_replay_window_grows_only_to_capacity_and_fails_closed_when_full():
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=2)
    assert (
        cloud_sessions.LEGACY_PROOF_USE_ROLE_NAME
        not in world["session_protocol"].roles
    )
    session = verify_cloud_session_manifest(
        world["store"].snapshot(),
        world["session_protocol"],
        world["issued_session"].session_root,
    )
    window = cloud_sessions.read_proof_replay_window(
        world["store"].snapshot(),
        world["session_protocol"],
        session.proof_replay_window_root,
    )
    assert window.capacity == 2
    assert window.retention_seconds == 10.0
    assert window.slot_roots == ()
    policy = cloud_sessions.read_proof_replay_policy(
        world["store"].snapshot(), world["session_protocol"]
    )
    assert policy.capacity == 2
    assert policy.retention_seconds == 10.0
    baseline = world["store"].retention_stats()
    protocol_members_before = read_relation(
        world["store"].snapshot(),
        world["session_protocol"].root_id,
        budget=100_000,
    )

    token = world["issued_session"].access_token
    first = _request_proof(
        access_token=token, now=now + 1, proof_id="fixed-window-proof-1"
    )
    second = _request_proof(
        access_token=token, now=now + 2, proof_id="fixed-window-proof-2"
    )
    first_auth = _authenticate_request(world, first, now=now + 1)
    _authenticate_request(world, second, now=now + 2)
    assert (
        world["store"].retention_stats()["current_cell_count"]
        == baseline["current_cell_count"] + 28
    )
    assert (
        world["store"].retention_stats()["version_cell_count"]
        == baseline["version_cell_count"] + 30
    )
    filled_window = cloud_sessions.read_proof_replay_window(
        world["store"].snapshot(),
        world["session_protocol"],
        session.proof_replay_window_root,
    )
    assert len(filled_window.slot_roots) == 2
    assert first_auth.proof_use_root in filled_window.slot_roots
    assert first_auth.proof_use_revision <= world["store"].revision
    assert first_auth.proof_use_evidence == (
        first_auth.proof_use_root,
        first_auth.proof_use_revision,
    )
    protocol_members_after = read_relation(
        world["store"].snapshot(),
        world["session_protocol"].root_id,
        budget=100_000,
    )
    assert protocol_members_after == protocol_members_before

    with pytest.raises(CloudSessionDenied, match="replayed"):
        _authenticate_request(world, first, now=now + 3)
    third = _request_proof(
        access_token=token, now=now + 3, proof_id="fixed-window-proof-3"
    )
    full_revision = world["store"].revision
    full_cells = world["store"].snapshot().cells
    with pytest.raises(CloudSessionDenied, match="replay window is full"):
        _authenticate_request(world, third, now=now + 3)
    assert world["store"].revision == full_revision
    assert world["store"].snapshot().cells == full_cells


def test_candidate_replay_policy_admits_a_64_request_per_second_window():
    class ProductionEnvelopeVerifier(_RequestProofVerifier):
        @property
        def replay_retention_seconds(self) -> float:
            return cloud_sessions.DEFAULT_PROOF_REPLAY_RETENTION_SECONDS

    now = float(int(time.time()))
    world = _session_world(
        now=now,
        request_proof_verifier=ProductionEnvelopeVerifier(),
    )
    policy = cloud_sessions.read_proof_replay_policy(
        world["store"].snapshot(), world["session_protocol"]
    )
    assert policy.capacity == 1024
    assert policy.retention_seconds == 15.0
    assert policy.capacity / policy.retention_seconds >= 64.0

    token = world["issued_session"].access_token
    started = time.perf_counter()
    for index in range(policy.capacity):
        observed_at = now + 1 + index / policy.capacity
        proof = _request_proof(
            access_token=token,
            now=observed_at,
            proof_id="released-capacity-proof-%04d" % index,
        )
        _authenticate_request(world, proof, now=observed_at)
    assert time.perf_counter() - started < 30.0

    revision = world["store"].revision
    cells = world["store"].snapshot().cells
    overflow = _request_proof(
        access_token=token,
        now=now + 2.1,
        proof_id="released-capacity-overflow",
    )
    with pytest.raises(CloudSessionDenied, match="replay window is full"):
        _authenticate_request(world, overflow, now=now + 2.1)
    assert world["store"].revision == revision
    assert world["store"].snapshot().cells == cells


def test_dpop_replay_window_reuses_expired_slot_and_preserves_history():
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    token = world["issued_session"].access_token
    first = _request_proof(
        access_token=token, now=now + 1, proof_id="historical-proof-1"
    )
    first_auth = _authenticate_request(world, first, now=now + 1)
    first_slot = cloud_sessions.read_proof_replay_slot(
        world["store"].at(first_auth.proof_use_revision),
        world["session_protocol"],
        first_auth.proof_use_root,
    )
    first_digest = hashlib.sha256(
        b"historical-proof-1"
    ).hexdigest()
    assert first_slot.proof_id_digest == first_digest

    second = _request_proof(
        access_token=token, now=now + 12, proof_id="historical-proof-2"
    )
    second_auth = _authenticate_request(world, second, now=now + 12)
    assert second_auth.proof_use_root == first_auth.proof_use_root
    current_slot = cloud_sessions.read_proof_replay_slot(
        world["store"].snapshot(),
        world["session_protocol"],
        second_auth.proof_use_root,
    )
    assert current_slot.proof_id_digest == hashlib.sha256(
        b"historical-proof-2"
    ).hexdigest()
    historical_slot = cloud_sessions.read_proof_replay_slot(
        world["store"].at(first_auth.proof_use_revision),
        world["session_protocol"],
        first_auth.proof_use_root,
    )
    assert historical_slot.proof_id_digest == first_digest


def test_dpop_replay_window_keeps_the_exact_expiry_boundary_closed():
    now = float(int(time.time()))
    world = _session_world(now=now, proof_replay_capacity=1)
    token = world["issued_session"].access_token
    first = _request_proof(
        access_token=token,
        now=now + 1,
        proof_id="exact-boundary-proof",
    )
    first_auth = _authenticate_request(world, first, now=now + 1)

    boundary_replay = _request_proof(
        access_token=token,
        now=now + 11,
        proof_id="exact-boundary-proof",
    )
    with pytest.raises(CloudSessionDenied, match="replayed"):
        _authenticate_request(world, boundary_replay, now=now + 11)

    after_boundary = _request_proof(
        access_token=token,
        now=now + 11.001,
        proof_id="after-boundary-proof",
    )
    after_auth = _authenticate_request(
        world,
        after_boundary,
        now=now + 11.001,
    )
    assert after_auth.proof_use_root == first_auth.proof_use_root
    assert isinstance(after_auth.proof_use_revision, int)
    assert after_auth.proof_use_evidence == (
        after_auth.proof_use_root,
        after_auth.proof_use_revision,
    )


def test_dpop_replay_window_preserves_fractional_expiry_precision():
    now = float(int(time.time()))
    world = _session_world(now=now, proof_replay_capacity=1)
    token = world["issued_session"].access_token
    first_observed_at = now + 1.0000004
    first = _request_proof(
        access_token=token,
        now=first_observed_at,
        proof_id="fractional-boundary-proof",
    )
    _authenticate_request(world, first, now=first_observed_at)

    before_exact_expiry = now + 11.0000003
    replay = _request_proof(
        access_token=token,
        now=before_exact_expiry,
        proof_id="fractional-boundary-proof",
    )
    with pytest.raises(CloudSessionDenied, match="replayed"):
        _authenticate_request(world, replay, now=before_exact_expiry)

    after_exact_expiry = first_observed_at + 10.000001
    replacement = _request_proof(
        access_token=token,
        now=after_exact_expiry,
        proof_id="fractional-boundary-replacement",
    )
    _authenticate_request(
        world,
        replacement,
        now=after_exact_expiry,
    )


def test_accepted_cloud_request_requires_revision_bound_proof_evidence():
    proof_revision_field = next(
        field
        for field in fields(cloud_sessions.CloudRequestAuthentication)
        if field.name == "proof_use_revision"
    )
    assert proof_revision_field.default is MISSING
    assert proof_revision_field.default_factory is MISSING


def test_dpop_replay_slot_reuse_stays_bounded_across_sqlite_reopen(tmp_path):
    now = time.time()
    path = tmp_path / "bounded-replay-history.sqlite3"
    key_provider = MemorySigningKeyProvider(
        "test:relationship-key",
        b"bounded-replay-relationship-key-material",
    )
    world = _session_world(
        now=now,
        store=CellStore(path),
        relationship_key_provider=key_provider,
        proof_replay_capacity=1,
    )
    issued = world["issued_session"]
    first_evidence = None
    fixed_current_count = None
    first_version_count = None

    for index in range(8):
        if index:
            store = CellStore(path)
            identity = project_identity_protocol(
                store.snapshot(),
                "test:identity",
            )
            relationship_broker = RelationshipAuthorityBroker(
                (world["roots"]["administrator"],),
                key_provider=key_provider,
                key_id="test:relationship-key",
            )
            restore_relationship_authority_history(
                store,
                identity,
                relationship_broker,
            )
            broker = CloudSessionBroker(
                session_protocol=project_cloud_session_protocol(
                    store.snapshot(),
                    prefix="test:cloud-session",
                ),
                identity_protocol=identity,
                relationship_broker=relationship_broker,
                authentication_broker=AuthenticationBroker(),
                request_proof_verifier=_RequestProofVerifier(),
                replay_policy_authority_verifier=(
                    _TestReplayPolicyAuthorityVerifier()
                ),
                tenant_admission_verifier=_TestTenantAdmissionVerifier(),
                device_custody_verifier=_TestDeviceCustodyVerifier(),
                session_issuer_root=world["roots"]["administrator"],
            )
        else:
            store = world["store"]
            broker = world["session_broker"]

        proof_now = now + 1 + (index * 12)
        proof_id = "durable-reused-proof-%02d" % index
        proof = _request_proof(
            access_token=issued.access_token,
            now=proof_now,
            proof_id=proof_id,
        )
        accepted = broker.authenticate_request(
            store,
            issued.access_token,
            proof,
            requested_action_root=world["action_root"],
            http_method="GET",
            target_uri=RESOURCE_URI,
            expected_nonce="server-request-nonce",
            now=proof_now,
        )
        stats = store.retention_stats()
        if first_evidence is None:
            first_evidence = accepted.proof_use_evidence
            fixed_current_count = stats["current_cell_count"]
            first_version_count = stats["version_cell_count"]
        else:
            assert accepted.proof_use_root == first_evidence[0]
            assert stats["current_cell_count"] == fixed_current_count
            assert stats["version_cell_count"] > first_version_count
        assert stats["resident_history_version_cell_count"] == 0
        store.close()

    final_store = CellStore(path)
    try:
        assert final_store.retention_stats()["current_cell_count"] == (
            fixed_current_count
        )
        assert final_store.retention_stats()[
            "resident_history_version_cell_count"
        ] == 0
        first_slot = cloud_sessions.read_proof_replay_slot(
            final_store.at(first_evidence[1]),
            project_cloud_session_protocol(
                final_store.snapshot(),
                prefix="test:cloud-session",
            ),
            first_evidence[0],
        )
        assert first_slot.proof_id_digest == hashlib.sha256(
            b"durable-reused-proof-00"
        ).hexdigest()
    finally:
        final_store.close()


@pytest.mark.parametrize("capacity", [0, -1, True, 1025])
def test_dpop_replay_window_rejects_invalid_capacity(capacity):
    now = time.time()
    with pytest.raises((TypeError, ValueError), match="replay capacity"):
        _session_world(now=now, proof_replay_capacity=capacity)


@pytest.mark.parametrize("retention", [0.0, float("nan"), float("inf"), 3601.0])
def test_dpop_replay_window_rejects_invalid_verifier_retention(retention):
    class InvalidRetentionVerifier(_RequestProofVerifier):
        @property
        def replay_retention_seconds(self) -> float:
            return retention

    with pytest.raises(ValueError, match="replay retention"):
        _session_world(
            now=time.time(),
            request_proof_verifier=InvalidRetentionVerifier(),
        )


def test_dpop_replay_window_denies_a_longer_verifier_than_session_policy():
    class LongerRetentionVerifier(_RequestProofVerifier):
        @property
        def replay_retention_seconds(self) -> float:
            return 20.0

    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    world["session_broker"] = CloudSessionBroker(
        session_protocol=world["session_protocol"],
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=LongerRetentionVerifier(),
        replay_policy_authority_verifier=(
            world["replay_policy_authority_verifier"]
        ),
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=_TestDeviceCustodyVerifier(),
        session_issuer_root=world["roots"]["administrator"],
    )
    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="retention-mismatch-proof",
    )
    with pytest.raises(
        CloudSessionDenied, match="shorter than verification"
    ):
        _authenticate_request(world, proof, now=now + 1)


def test_legacy_proof_verifier_uses_an_explicit_retention_adapter():
    class LegacyVerifier:
        def verify(self, *arguments, **keywords):
            return _RequestProofVerifier().verify(*arguments, **keywords)

    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    world["session_broker"] = CloudSessionBroker(
        session_protocol=world["session_protocol"],
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=LegacyVerifier(),
        replay_policy_authority_verifier=(
            world["replay_policy_authority_verifier"]
        ),
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=_TestDeviceCustodyVerifier(),
        session_issuer_root=world["roots"]["administrator"],
        proof_replay_retention_seconds=10.0,
    )
    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="legacy-verifier-adapter",
    )
    accepted = _authenticate_request(world, proof, now=now + 1)
    assert isinstance(accepted.proof_use_revision, int)


def test_pre_window_cloud_session_requires_explicit_reauthentication():
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    snapshot = world["store"].snapshot()
    session_root = world["issued_session"].session_root
    replay_incidence = next(
        member.incidence_id
        for member in read_relation(snapshot, session_root, budget=256)
        if member.role_id
        == world["session_protocol"].role("proof-replay-window")
    )
    remove_relation_member(
        world["store"], session_root, replay_incidence, budget=256
    )
    with pytest.raises(InvalidCell, match="proof replay window"):
        verify_cloud_session_manifest(
            world["store"].snapshot(),
            world["session_protocol"],
            session_root,
        )
    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="legacy-session-proof",
    )
    with pytest.raises(
        CloudSessionDenied, match="no unique active session"
    ):
        _authenticate_request(world, proof, now=now + 1)


def test_dpop_replay_window_rejects_foreign_policy_and_slot_value_roots():
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    snapshot = world["store"].snapshot()
    session = verify_cloud_session_manifest(
        snapshot,
        world["session_protocol"],
        world["issued_session"].session_root,
    )
    window = cloud_sessions.read_proof_replay_window(
        snapshot,
        world["session_protocol"],
        session.proof_replay_window_root,
    )
    capacity_member = next(
        member for member in read_relation(snapshot, window.root_id, budget=8)
        if member.role_id
        == world["session_protocol"].role("proof-replay-capacity")
    )
    foreign_capacity = _cell("test:foreign:replay-capacity", "1")
    incidence = snapshot.cells[capacity_member.incidence_id]
    world["store"].commit(
        snapshot.revision,
        create=(foreign_capacity,),
        replace=(Cell(
            incidence.id,
            incidence.link0,
            foreign_capacity.id,
            incidence.atom,
        ),),
    )
    with pytest.raises(InvalidCell, match="replay capacity"):
        verify_cloud_session_manifest(
            world["store"].snapshot(),
            world["session_protocol"],
            world["issued_session"].session_root,
        )

    clean = _session_world(now=now + 2, proof_replay_capacity=1)
    clean_snapshot = clean["store"].snapshot()
    clean_session = verify_cloud_session_manifest(
        clean_snapshot,
        clean["session_protocol"],
        clean["issued_session"].session_root,
    )
    clean_window = cloud_sessions.read_proof_replay_window(
        clean_snapshot,
        clean["session_protocol"],
        clean_session.proof_replay_window_root,
    )
    initial = _request_proof(
        access_token=clean["issued_session"].access_token,
        now=now + 3,
        proof_id="slot-to-tamper",
    )
    _authenticate_request(clean, initial, now=now + 3)
    clean_snapshot = clean["store"].snapshot()
    clean_window = cloud_sessions.read_proof_replay_window(
        clean_snapshot,
        clean["session_protocol"],
        clean_session.proof_replay_window_root,
    )
    slot_member = next(
        member for member in read_relation(
            clean_snapshot, clean_window.slot_roots[0], budget=8
        )
        if member.role_id
        == clean["session_protocol"].role("proof-id-digest")
    )
    foreign_digest = _cell(
        "test:foreign:proof-digest",
        hashlib.sha256(b"foreign").hexdigest(),
    )
    slot_incidence = clean_snapshot.cells[slot_member.incidence_id]
    clean["store"].commit(
        clean_snapshot.revision,
        create=(foreign_digest,),
        replace=(Cell(
            slot_incidence.id,
            slot_incidence.link0,
            foreign_digest.id,
            slot_incidence.atom,
        ),),
    )
    proof = _request_proof(
        access_token=clean["issued_session"].access_token,
        now=now + 4,
        proof_id="foreign-slot-proof",
    )
    with pytest.raises(CloudSessionDenied, match="replay window drifted"):
        _authenticate_request(clean, proof, now=now + 4)


def test_dpop_replay_window_conflict_never_overwrites_an_unexpired_proof(
    monkeypatch,
):
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    token = world["issued_session"].access_token
    proofs = tuple(
        _request_proof(
            access_token=token,
            now=now + 1,
            proof_id="contended-proof-%s" % index,
        )
        for index in range(2)
    )
    barrier = threading.Barrier(2)
    original_commit = CellStore.commit

    def synchronized_commit(store, expected_revision, **arguments):
        replace = tuple(arguments.get("replace", ()))
        create = tuple(arguments.get("create", ()))
        if any(
            ":proof-replay-window:slot:" in cell.id
            for cell in (*create, *replace)
        ):
            barrier.wait(timeout=5)
        return original_commit(store, expected_revision, **arguments)

    monkeypatch.setattr(CellStore, "commit", synchronized_commit)

    def attempt(proof):
        try:
            return _authenticate_request(world, proof, now=now + 1)
        except CloudSessionDenied as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(attempt, proofs))
    accepted = tuple(
        outcome for outcome in outcomes
        if not isinstance(outcome, Exception)
    )
    denied = tuple(
        outcome for outcome in outcomes if isinstance(outcome, Exception)
    )
    assert len(accepted) == 1
    assert len(denied) == 1
    assert "replay window is full" in str(denied[0])
    slot = cloud_sessions.read_proof_replay_slot(
        world["store"].snapshot(),
        world["session_protocol"],
        accepted[0].proof_use_root,
    )
    assert slot.proof_id_digest in {
        hashlib.sha256(b"contended-proof-0").hexdigest(),
        hashlib.sha256(b"contended-proof-1").hexdigest(),
    }


def test_dpop_replay_window_survives_unrelated_global_revision_conflicts(
    monkeypatch,
):
    now = time.time()
    world = _session_world(now=now, proof_replay_capacity=1)
    counter_root = "test:unrelated:commit-counter"
    snapshot = world["store"].snapshot()
    world["store"].commit(
        snapshot.revision, create=(_cell(counter_root, "0"),)
    )
    original_commit = CellStore.commit
    injected = 0

    def interfering_commit(store, expected_revision, **arguments):
        nonlocal injected
        create = tuple(arguments.get("create", ()))
        replace = tuple(arguments.get("replace", ()))
        is_replay = any(
            ":proof-replay-window:slot:" in cell.id
            for cell in (*create, *replace)
        )
        if is_replay and injected < 8:
            injected += 1
            current = store.snapshot()
            original_commit(
                store,
                current.revision,
                replace=(_cell(counter_root, str(injected)),),
            )
        return original_commit(store, expected_revision, **arguments)

    monkeypatch.setattr(CellStore, "commit", interfering_commit)
    proof = _request_proof(
        access_token=world["issued_session"].access_token,
        now=now + 1,
        proof_id="survives-global-contention",
    )
    accepted = _authenticate_request(world, proof, now=now + 1)
    assert injected == 8
    assert accepted.proof_use_root in world["store"].snapshot().cells
    assert world["store"].read(counter_root).atom == b"8"


def test_cloud_session_protocol_migrates_only_missing_replay_vocabulary():
    store = CellStore()
    prefix = "test:legacy-cloud-session"
    new_names = set(cloud_sessions.PROOF_REPLAY_ROLE_NAMES)
    legacy_names = (
        *tuple(
            name for name in cloud_sessions.ROLE_NAMES
            if name not in new_names
        ),
        cloud_sessions.LEGACY_PROOF_USE_ROLE_NAME,
    )
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in legacy_names
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_cell(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in roles.values()
        ),
        relation_id=prefix + ":root",
    )
    batch.commit()
    revision_before = store.revision

    protocol = cloud_sessions.ensure_cloud_session_protocol(
        store, prefix=prefix
    )
    assert store.revision == revision_before + 1
    assert set(protocol.roles) == set(cloud_sessions.ROLE_NAMES)
    assert cloud_sessions.project_cloud_session_protocol(
        store.snapshot(), prefix=prefix
    ) == protocol


def test_cloud_session_protocol_migration_rejects_missing_legacy_vocabulary():
    store = CellStore()
    prefix = "test:damaged-cloud-session"
    legacy_names = (
        *tuple(
            name for name in cloud_sessions.ROLE_NAMES
            if name not in cloud_sessions.PROOF_REPLAY_ROLE_NAMES
            and name != "subject"
        ),
        cloud_sessions.LEGACY_PROOF_USE_ROLE_NAME,
    )
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in legacy_names
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(_cell(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in roles.values()
        ),
        relation_id=prefix + ":root",
    )
    batch.commit()

    with pytest.raises(InvalidCell, match="legacy protocol vocabulary"):
        cloud_sessions.ensure_cloud_session_protocol(store, prefix=prefix)


@pytest.mark.parametrize("proof_change", [
    {"htm": "POST"},
    {"htu": "https://api.archhub.test/v1/other"},
    {"nonce": "wrong"},
    {"ath": "0" * 64},
    {"thumbprint": "1" * 43},
])
def test_request_proof_is_bound_to_method_uri_nonce_token_and_device(proof_change):
    now = time.time()
    world = _session_world(now=now)
    token = world["issued_session"].access_token
    proof = _request_proof(
        access_token=token, now=now + 1, **proof_change
    )
    with pytest.raises(CloudSessionDenied, match="proof verification"):
        _authenticate_request(world, proof, now=now + 1)


def test_revoked_device_or_session_denies_the_next_request():
    now = time.time()
    world = _session_world(now=now)
    token = world["issued_session"].access_token
    proof = _request_proof(access_token=token, now=now + 1)
    handle = world["relationship_broker"].mint_from_trusted_administrator(
        world["roots"]["administrator"]
    )
    revoke_authority_relationship(
        world["store"],
        world["identity"],
        world["relationship_broker"],
        handle,
        world["device_binding_root"],
        administrator_root=world["roots"]["administrator"],
        reason="device was lost",
        now=now + 0.5,
    )
    with pytest.raises(CloudSessionDenied, match="device"):
        _authenticate_request(world, proof, now=now + 1)

    second = _session_world(now=now + 2)
    second["session_broker"].revoke(
        second["store"],
        second["issued_session"].session_root,
        administrator_root=second["roots"]["administrator"],
        reason="sign out this session",
        now=now + 2.5,
    )
    proof = _request_proof(
        access_token=second["issued_session"].access_token, now=now + 3
    )
    with pytest.raises(CloudSessionDenied, match="inactive"):
        _authenticate_request(second, proof, now=now + 3)


def test_federated_authentication_capability_cannot_be_forged():
    with pytest.raises(TypeError):
        FederatedAuthentication(
            object(), None, "evidence", "subject", "tenant", "audience",
            "assurance", "external", {},
        )


def test_session_authority_revocation_and_proof_replay_survive_reopen(tmp_path):
    now = time.time()
    path = tmp_path / "cloud-authority.sqlite3"
    key_provider = MemorySigningKeyProvider(
        "test:relationship-key", b"persistent-relationship-key-material"
    )
    world = _session_world(
        now=now,
        store=CellStore(path),
        relationship_key_provider=key_provider,
    )
    issued = world["issued_session"]
    proof = _request_proof(
        access_token=issued.access_token, now=now + 1, proof_id="durable-proof"
    )
    _authenticate_request(world, proof, now=now + 1)
    world["store"].close()

    reopened = CellStore(path)
    identity = project_identity_protocol(reopened.snapshot(), "test:identity")
    relationship_broker = RelationshipAuthorityBroker(
        (world["roots"]["administrator"],),
        key_provider=key_provider,
        key_id="test:relationship-key",
    )
    restore_relationship_authority_history(
        reopened, identity, relationship_broker
    )
    authentication_broker = AuthenticationBroker()
    session_broker = CloudSessionBroker(
        session_protocol=project_cloud_session_protocol(
            reopened.snapshot(), prefix="test:cloud-session"
        ),
        identity_protocol=identity,
        relationship_broker=relationship_broker,
        authentication_broker=authentication_broker,
        request_proof_verifier=_RequestProofVerifier(),
        replay_policy_authority_verifier=(
            _TestReplayPolicyAuthorityVerifier()
        ),
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=_TestDeviceCustodyVerifier(),
        session_issuer_root=world["roots"]["administrator"],
    )
    with pytest.raises(CloudSessionDenied, match="replayed"):
        session_broker.authenticate_request(
            reopened,
            issued.access_token,
            proof,
            requested_action_root=world["action_root"],
            http_method="GET",
            target_uri=RESOURCE_URI,
            expected_nonce="server-request-nonce",
            now=now + 2,
        )
    fresh_proof = _request_proof(
        access_token=issued.access_token, now=now + 2, proof_id="fresh-proof"
    )
    session_broker.authenticate_request(
        reopened,
        issued.access_token,
        fresh_proof,
        requested_action_root=world["action_root"],
        http_method="GET",
        target_uri=RESOURCE_URI,
        expected_nonce="server-request-nonce",
        now=now + 2,
    )
    session_broker.revoke(
        reopened,
        issued.session_root,
        administrator_root=world["roots"]["administrator"],
        reason="security logout after restart",
        now=now + 3,
    )
    reopened.close()

    final_store = CellStore(path)
    final_identity = project_identity_protocol(
        final_store.snapshot(), "test:identity"
    )
    final_relationship_broker = RelationshipAuthorityBroker(
        (world["roots"]["administrator"],),
        key_provider=key_provider,
        key_id="test:relationship-key",
    )
    restore_relationship_authority_history(
        final_store, final_identity, final_relationship_broker
    )
    final_broker = CloudSessionBroker(
        session_protocol=project_cloud_session_protocol(
            final_store.snapshot(), prefix="test:cloud-session"
        ),
        identity_protocol=final_identity,
        relationship_broker=final_relationship_broker,
        authentication_broker=AuthenticationBroker(),
        request_proof_verifier=_RequestProofVerifier(),
        replay_policy_authority_verifier=(
            _TestReplayPolicyAuthorityVerifier()
        ),
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=_TestDeviceCustodyVerifier(),
        session_issuer_root=world["roots"]["administrator"],
    )
    post_revoke_proof = _request_proof(
        access_token=issued.access_token,
        now=now + 4,
        proof_id="post-revoke-proof",
    )
    with pytest.raises(CloudSessionDenied, match="inactive"):
        final_broker.authenticate_request(
            final_store,
            issued.access_token,
            post_revoke_proof,
            requested_action_root=world["action_root"],
            http_method="GET",
            target_uri=RESOURCE_URI,
            expected_nonce="server-request-nonce",
            now=now + 4,
        )
    final_store.close()


def test_cloud_request_gate_combines_session_proof_and_exact_policy():
    now = time.time()
    world = _world()
    authorization = bootstrap_authorization_protocol(
        world["store"], prefix="test:cloud-authorization"
    )
    world = _session_world(
        now=now,
        world=world,
        action_root=authorization.actions["read"],
    )
    object_root = "test:cloud-object:graph"
    other_root = "test:cloud-object:other"
    world["store"].commit(world["store"].revision, create=(
        _cell(object_root, "governed graph"),
        _cell(other_root, "other graph"),
    ))
    rule = build_authorization_rule(
        world["store"],
        authorization,
        rule_id="test:cloud-rule:member-read-graph",
        effect="permit",
        principal_root=world["roots"]["subject"],
        object_root=object_root,
        action_root=authorization.actions["read"],
        tenant_root=world["roots"]["tenant"],
        assurance_root=world["roots"]["aal2"],
    )
    policy = build_authorization_policy(
        world["store"],
        authorization,
        (rule,),
        policy_id="test:cloud-policy",
        version="1.0.0",
    )
    release_broker = PolicyReleaseBroker()
    release_handle = release_broker.mint_from_trusted_administrator(
        policy, world["roots"]["administrator"]
    )
    release_authorization_policy(
        world["store"],
        authorization,
        policy,
        release_broker,
        release_handle,
        administrator_root=world["roots"]["administrator"],
    )
    gate = CloudRequestGate(
        session_broker=world["session_broker"],
        authorization_protocol=authorization,
        authentication_broker=world["authentication_broker"],
        policy_root=policy,
    )
    token = world["issued_session"].access_token
    allowed = gate.authorize(
        world["store"],
        token,
        _request_proof(
            access_token=token, now=now + 1, proof_id="gate-proof-allowed"
        ),
        action_root=authorization.actions["read"],
        object_root=object_root,
        http_method="GET",
        target_uri=RESOURCE_URI,
        request_nonce="server-request-nonce",
        now=now + 1,
    )
    assert allowed.decision.allowed
    assert allowed.decision.object_root == object_root

    with pytest.raises(AuthorizationDenied, match="default-deny"):
        gate.authorize(
            world["store"],
            token,
            _request_proof(
                access_token=token,
                now=now + 2,
                proof_id="gate-proof-denied-object",
            ),
            action_root=authorization.actions["read"],
            object_root=other_root,
            http_method="GET",
            target_uri=RESOURCE_URI,
            request_nonce="server-request-nonce",
            now=now + 2,
        )

    handle = world["relationship_broker"].mint_from_trusted_administrator(
        world["roots"]["administrator"]
    )
    revoke_authority_relationship(
        world["store"],
        world["identity"],
        world["relationship_broker"],
        handle,
        world["membership_root"],
        administrator_root=world["roots"]["administrator"],
        reason="tenant access removed",
        now=now + 2.5,
    )
    with pytest.raises(CloudSessionDenied, match="membership"):
        gate.authorize(
            world["store"],
            token,
            _request_proof(
                access_token=token,
                now=now + 3,
                proof_id="gate-proof-after-membership-revoke",
            ),
            action_root=authorization.actions["read"],
            object_root=object_root,
            http_method="GET",
            target_uri=RESOURCE_URI,
            request_nonce="server-request-nonce",
            now=now + 3,
        )


def _native_cloud_login_world(
    *,
    now: float,
    device_reference: DeviceProofKeyReference | None = None,
):
    world = _world()
    store = world["store"]
    roots = world["roots"]
    device_thumbprint = (
        DEVICE_THUMBPRINT
        if device_reference is None
        else device_reference.thumbprint
    )
    action_root = "test:native-action:read"
    store.commit(store.revision, create=(_cell(action_root, "read"),))

    administration = world[
        "relationship_broker"
    ].mint_from_trusted_administrator(roots["administrator"])
    provision_device_binding(
        store,
        world["identity"],
        world["relationship_broker"],
        administration,
        relationship_id="test:native:device-binding",
        proof_key_thumbprint=device_thumbprint,
        subject_root=roots["subject"],
        tenant_root=roots["tenant"],
        audience_root=roots["audience"],
        administrator_root=roots["administrator"],
        reason="user enrolled this native desktop device",
        now=now,
    )
    device_binding_root = "test:native:device-binding"
    device_custody_protocol = bootstrap_device_custody_protocol(
        store, prefix="test:native-device-custody"
    )
    device_custody_root = None
    if device_reference is not None:
        device_custody_root, _ = register_device_custody(
            store,
            device_custody_protocol,
            device_reference,
            enrolled_at=now,
        )
    cloud_protocol = bootstrap_cloud_session_protocol(
        store, prefix="test:native-cloud-session"
    )
    native_replay_lifecycle_root = (
        cloud_protocol.root_id + ":test-proof-replay-policy-lifecycle"
    )
    store.commit(
        store.revision,
        create=(
            _cell(native_replay_lifecycle_root, "test lifecycle"),
            _cell(native_replay_lifecycle_root + ":wip", "WIP"),
            _cell(native_replay_lifecycle_root + ":shared", "Shared"),
            _cell(
                native_replay_lifecycle_root + ":published",
                "Published",
            ),
        ),
    )
    cloud_protocol = cloud_sessions.bind_proof_replay_policy_lifecycle(
        store, cloud_protocol, native_replay_lifecycle_root
    )
    cloud_broker = CloudSessionBroker(
        session_protocol=cloud_protocol,
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=_RequestProofVerifier(),
        replay_policy_authority_verifier=(
            _TestReplayPolicyAuthorityVerifier()
        ),
        tenant_admission_verifier=_TestTenantAdmissionVerifier(),
        device_custody_verifier=(
            ActiveDeviceCustodyVerifier(device_custody_protocol)
            if device_reference is not None
            else _TestDeviceCustodyVerifier()
        ),
        session_issuer_root=roots["administrator"],
    )

    native_protocol = bootstrap_native_authentication_protocol(
        store, prefix="test:native-login"
    )
    discovery_key = jwk.ECKey.generate_key("P-256")
    discovery_key.ensure_kid()

    def discovery_provider(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": ISSUER + "/jwks",
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                    "authorization_response_iss_parameter_supported": True,
                    "id_token_signing_alg_values_supported": ["ES256"],
                },
                headers={"Content-Type": "application/json"},
            )
        return httpx.Response(
            200,
            json={"keys": [discovery_key.as_dict(private=False)]},
            headers={"Content-Type": "application/jwk-set+json"},
        )

    discovery = OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        allowed_algorithms=("ES256",),
        client=httpx.Client(transport=httpx.MockTransport(discovery_provider)),
        clock=lambda: now,
    ).native_client_authority()
    registration = build_native_client_registration(
        store,
        native_protocol,
        discovery,
        registration_id="test:native-login:client",
        client_id=AUDIENCE,
        now=now,
    )
    client_administration = world[
        "relationship_broker"
    ].mint_from_trusted_administrator(roots["administrator"])
    client_activation_root = activate_native_client_registration(
        store,
        native_protocol,
        world["identity"],
        world["relationship_broker"],
        client_administration,
        registration_root=registration,
        relationship_id="test:native-login:client-activation",
        tenant_root=roots["tenant"],
        audience_root=roots["audience"],
        administrator_root=roots["administrator"],
        reason="founder approved this native client for this tenant",
        now=now,
    )
    client_admission_verifier = SignedNativeClientAdmissionVerifier(
        native_protocol=native_protocol,
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        tenant_root=roots["tenant"],
        audience_root=roots["audience"],
    )
    native_broker = NativeAuthorizationBroker(client_admission_verifier)
    return {
        "world": world,
        "store": store,
        "roots": roots,
        "action_root": action_root,
        "cloud_protocol": cloud_protocol,
        "cloud_broker": cloud_broker,
        "native_protocol": native_protocol,
        "registration": registration,
        "client_activation_root": client_activation_root,
        "client_admission_verifier": client_admission_verifier,
        "native_broker": native_broker,
        "device_thumbprint": device_thumbprint,
        "device_custody_protocol": device_custody_protocol,
        "device_custody_root": device_custody_root,
        "device_binding_root": device_binding_root,
    }


def _remote_native_cloud_login_world(*, now: float):
    key = jwk.ECKey.generate_key("P-256")
    public_jwk = key.as_dict(private=False)
    reference = DeviceProofKeyReference(
        "ArchHub.Test.RemoteDevice",
        PLATFORM_PROVIDER,
        "ES256",
        jwk.thumbprint(public_jwk),
        public_jwk,
        True,
    )
    setup = _native_cloud_login_world(
        now=now,
        device_reference=reference,
    )
    verifier = ReturningDeviceAdmissionVerifier(
        device_custody_protocol=setup["device_custody_protocol"],
        identity_protocol=setup["world"]["identity"],
        relationship_broker=setup["world"]["relationship_broker"],
        tenant_root=setup["roots"]["tenant"],
        audience_root=setup["roots"]["audience"],
    )
    broker = RemoteNativeCloudLoginBroker(
        store=setup["store"],
        protocol=setup["native_protocol"],
        registration_root=setup["registration"],
        native_authorization_broker=setup["native_broker"],
        federated_identity_broker=setup["world"]["federated"],
        cloud_session_broker=setup["cloud_broker"],
        client_admission_verifier=setup["client_admission_verifier"],
        returning_device_verifier=verifier,
        allowed_action_roots=(setup["action_root"],),
    )
    return setup, broker


def _remote_token_client(*, now: float, nonce: str, marker: list[str] | None = None):
    raw_id_token = _assertion(now=now, nonce=nonce)

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        if marker is not None:
            marker.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "id_token": raw_id_token.decode("ascii"),
                "access_token": "provider-token-must-not-persist",
                "refresh_token": "provider-refresh-must-not-persist",
            },
            headers={"Content-Type": "application/json"},
        )

    return (
        httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        raw_id_token,
    )


def test_returning_device_reauthenticates_without_a_preexisting_cloud_session():
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    cloud_members_before = tuple(
        member for member in read_relation(
            setup["store"].snapshot(),
            setup["cloud_protocol"].root_id,
            budget=100_000,
        )
        if member.role_id == setup["cloud_protocol"].role("session-member")
    )
    assert cloud_members_before == ()

    started = broker.start(
        device_thumbprint=setup["device_thumbprint"],
        redirect_port=49161,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    token_client, raw_id_token = _remote_token_client(
        now=now + 1,
        nonce=query["nonce"][0],
    )
    issued = broker.complete_and_issue(
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="returning-device-code",
        token_client=token_client,
        now=now + 1,
    )
    session = verify_cloud_session_manifest(
        setup["store"].snapshot(),
        setup["cloud_protocol"],
        issued.session_root,
    )
    assert session.device_root.endswith(setup["device_thumbprint"])
    atoms = tuple(cell.atom for cell in setup["store"].snapshot().cells.values())
    assert raw_id_token not in atoms
    assert b"returning-device-code" not in atoms
    assert b"provider-token-must-not-persist" not in atoms
    assert b"provider-refresh-must-not-persist" not in atoms
    assert issued.access_token.encode("ascii") not in atoms


def test_oidc_alone_cannot_enroll_an_unknown_device_key():
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    unknown = "A" * 43
    with pytest.raises(
        ReturningDeviceAdmissionDenied,
        match="active returning-device custody",
    ):
        broker.start(
            device_thumbprint=unknown,
            redirect_port=49162,
            now=now,
        )
    assert device_root_for_thumbprint(unknown) not in setup["store"].snapshot().cells


def test_custody_revocation_after_start_denies_before_provider_exchange():
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    started = broker.start(
        device_thumbprint=setup["device_thumbprint"],
        redirect_port=49163,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    revoke_device_custody(
        setup["store"],
        setup["device_custody_protocol"],
        setup["device_custody_root"],
        reason="device reported lost",
    )
    exchanges: list[str] = []
    token_client, _raw_id_token = _remote_token_client(
        now=now + 1,
        nonce=query["nonce"][0],
        marker=exchanges,
    )
    with pytest.raises(
        ReturningDeviceAdmissionDenied,
        match="active returning-device custody",
    ):
        broker.complete_and_issue(
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="must-not-be-exchanged",
            token_client=token_client,
            now=now + 1,
        )
    assert exchanges == []


@pytest.mark.parametrize(
    ("revoked_root", "error"),
    (
        ("device_binding_root", "returning-device identity binding"),
        ("membership_root", "tenant membership"),
    ),
)
def test_graph_authority_revocation_after_start_denies_before_exchange(
    revoked_root,
    error,
):
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    started = broker.start(
        device_thumbprint=setup["device_thumbprint"],
        redirect_port=49164,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    root = (
        setup[revoked_root]
        if revoked_root in setup
        else setup["world"][revoked_root]
    )
    relationship_broker = setup["world"]["relationship_broker"]
    administrator = setup["roots"]["administrator"]
    handle = relationship_broker.mint_from_trusted_administrator(administrator)
    revoke_authority_relationship(
        setup["store"],
        setup["world"]["identity"],
        relationship_broker,
        handle,
        root,
        administrator_root=administrator,
        reason="returning-device authority withdrawn",
        now=now + 0.5,
    )
    exchanges: list[str] = []
    token_client, _raw_id_token = _remote_token_client(
        now=now + 1,
        nonce=query["nonce"][0],
        marker=exchanges,
    )
    with pytest.raises(ReturningDeviceAdmissionDenied, match=error):
        broker.complete_and_issue(
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="must-not-reach-provider",
            token_client=token_client,
            now=now + 1,
        )
    assert exchanges == []


def test_revoked_custody_denies_an_already_issued_cloud_session():
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    started = broker.start(
        device_thumbprint=setup["device_thumbprint"],
        redirect_port=49165,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    token_client, _raw_id_token = _remote_token_client(
        now=now + 1,
        nonce=query["nonce"][0],
    )
    issued = broker.complete_and_issue(
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="issued-before-custody-revocation",
        token_client=token_client,
        now=now + 1,
    )
    revoke_device_custody(
        setup["store"],
        setup["device_custody_protocol"],
        setup["device_custody_root"],
        reason="device reported lost after session issuance",
    )
    proof = _request_proof(
        access_token=issued.access_token,
        now=now + 2,
        proof_id="proof-after-custody-revocation",
        thumbprint=setup["device_thumbprint"],
    )
    with pytest.raises(CloudSessionDenied, match="device custody is inactive"):
        setup["cloud_broker"].authenticate_request(
            setup["store"],
            issued.access_token,
            proof,
            requested_action_root=setup["action_root"],
            http_method="GET",
            target_uri=RESOURCE_URI,
            expected_nonce="server-request-nonce",
            now=now + 2,
        )


def test_custody_revocation_racing_request_admission_denies_before_proof_use():
    now = time.time()
    setup, broker = _remote_native_cloud_login_world(now=now)
    started = broker.start(
        device_thumbprint=setup["device_thumbprint"],
        redirect_port=49166,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    token_client, _raw_id_token = _remote_token_client(
        now=now + 1,
        nonce=query["nonce"][0],
    )
    issued = broker.complete_and_issue(
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="issued-before-racing-custody-revocation",
        token_client=token_client,
        now=now + 1,
    )
    active_verifier = ActiveDeviceCustodyVerifier(
        setup["device_custody_protocol"]
    )

    class RevokeAfterVerification:
        def __init__(self):
            self.revoked = False

        def verify(self, snapshot, *, device_root, now):
            custody_root = active_verifier.verify(
                snapshot,
                device_root=device_root,
                now=now,
            )
            if not self.revoked:
                self.revoked = True
                revoke_device_custody(
                    setup["store"],
                    setup["device_custody_protocol"],
                    setup["device_custody_root"],
                    reason="device lost during request admission",
                )
            return custody_root

    setup["cloud_broker"]._device_custody_verifier = (
        RevokeAfterVerification()
    )
    proof = _request_proof(
        access_token=issued.access_token,
        now=now + 2,
        proof_id="proof-racing-custody-revocation",
        thumbprint=setup["device_thumbprint"],
    )
    with pytest.raises(CloudSessionDenied, match="device custody is inactive"):
        setup["cloud_broker"].authenticate_request(
            setup["store"],
            issued.access_token,
            proof,
            requested_action_root=setup["action_root"],
            http_method="GET",
            target_uri=RESOURCE_URI,
            expected_nonce="server-request-nonce",
            now=now + 2,
        )


def test_native_callback_flows_through_identity_court_into_device_session():
    now = time.time()
    setup = _native_cloud_login_world(now=now)
    world = setup["world"]
    store = setup["store"]
    roots = setup["roots"]
    action_root = setup["action_root"]
    cloud_protocol = setup["cloud_protocol"]
    cloud_broker = setup["cloud_broker"]
    native_protocol = setup["native_protocol"]
    registration = setup["registration"]
    client_activation_root = setup["client_activation_root"]
    client_admission_verifier = setup["client_admission_verifier"]
    native_broker = setup["native_broker"]
    started = native_broker.start(
        store,
        native_protocol,
        registration,
        redirect_port=49153,
        device_thumbprint=DEVICE_THUMBPRINT,
        now=now,
    )
    query = parse_qs(urlsplit(started.authorization_url).query)
    callback = native_broker.complete(
        store,
        native_protocol,
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="native-provider-code",
        now=now + 1,
    )
    raw_id_token = _assertion(now=now, nonce=query["nonce"][0])

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ISSUER + "/token"
        return httpx.Response(
            200,
            json={
                "id_token": raw_id_token.decode("ascii"),
                "access_token": "external-access-token-not-retained",
                "refresh_token": "external-refresh-token-not-retained",
            },
            headers={"Content-Type": "application/json"},
        )

    assertion = exchange_native_authorization_code(
        callback,
        client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    issued = issue_native_cloud_session(
        store,
        assertion,
        federated_identity_broker=world["federated"],
        cloud_session_broker=cloud_broker,
        client_admission_verifier=client_admission_verifier,
        allowed_action_roots=(action_root,),
        now=now + 1,
    )
    session = verify_cloud_session_manifest(
        store.snapshot(), cloud_protocol, issued.session_root
    )
    assert session.subject_root == roots["subject"]
    assert session.tenant_root == roots["tenant"]
    assert session.device_root.endswith(DEVICE_THUMBPRINT)
    atoms = tuple(cell.atom for cell in store.snapshot().cells.values())
    assert raw_id_token not in atoms
    assert b"native-provider-code" not in atoms
    assert b"external-access-token-not-retained" not in atoms
    assert b"external-refresh-token-not-retained" not in atoms

    second_started = native_broker.start(
        store,
        native_protocol,
        registration,
        redirect_port=49154,
        device_thumbprint=DEVICE_THUMBPRINT,
        now=now + 2,
    )
    second_query = parse_qs(urlsplit(second_started.authorization_url).query)
    second_callback = native_broker.complete(
        store,
        native_protocol,
        second_started.transaction_root,
        state=second_query["state"][0],
        response_issuer=ISSUER,
        authorization_code="second-native-provider-code",
        now=now + 3,
    )
    second_raw_id_token = _assertion(
        now=now + 2, nonce=second_query["nonce"][0]
    )

    def second_token_endpoint(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id_token": second_raw_id_token.decode("ascii")},
            headers={"Content-Type": "application/json"},
        )

    second_assertion = exchange_native_authorization_code(
        second_callback,
        client=httpx.Client(transport=httpx.MockTransport(second_token_endpoint)),
    )
    revocation = world[
        "relationship_broker"
    ].mint_from_trusted_administrator(roots["administrator"])
    revoke_authority_relationship(
        store,
        world["identity"],
        world["relationship_broker"],
        revocation,
        client_activation_root,
        administrator_root=roots["administrator"],
        reason="founder withdrew this native client's tenant access",
        now=now + 4,
    )
    with pytest.raises(NativeAuthenticationDenied, match="activation was revoked"):
        issue_native_cloud_session(
            store,
            second_assertion,
            federated_identity_broker=world["federated"],
            cloud_session_broker=cloud_broker,
            client_admission_verifier=client_admission_verifier,
            allowed_action_roots=(action_root,),
            now=now + 5,
        )

    with pytest.raises(NativeAuthenticationDenied, match="already consumed"):
        issue_native_cloud_session(
            store,
            assertion,
            federated_identity_broker=world["federated"],
            cloud_session_broker=cloud_broker,
            client_admission_verifier=client_admission_verifier,
            allowed_action_roots=(action_root,),
            now=now + 2,
        )


def test_native_loopback_login_issues_a_device_bound_cloud_session_without_secret_cells():
    now = time.time()
    setup = _native_cloud_login_world(now=now)
    login = NativeCloudLogin(
        store=setup["store"],
        protocol=setup["native_protocol"],
        registration_root=setup["registration"],
        native_authorization_broker=setup["native_broker"],
        federated_identity_broker=setup["world"]["federated"],
        cloud_session_broker=setup["cloud_broker"],
        client_admission_verifier=setup["client_admission_verifier"],
        allowed_action_roots=(setup["action_root"],),
    )
    started = login.start(device_thumbprint=DEVICE_THUMBPRINT)
    query = parse_qs(urlsplit(started.authorization_url).query)
    callback_uri = query["redirect_uri"][0]
    assert callback_uri.startswith("http://127.0.0.1:")
    raw_id_token = _assertion(
        now=time.time(), nonce=query["nonce"][0]
    )

    with httpx.Client(trust_env=False) as callback_client:
        rejected = callback_client.get(
            callback_uri,
            params={
                "code": "rejected-native-provider-code",
                "state": "mismatched-state",
                "iss": ISSUER,
            },
        )
        assert rejected.status_code == 400
        assert b"rejected-native-provider-code" not in rejected.content

        accepted = callback_client.get(
            callback_uri,
            params={
                "code": "accepted-native-provider-code",
                "state": query["state"][0],
                "iss": ISSUER,
            },
        )
        assert accepted.status_code == 200
        assert b"accepted-native-provider-code" not in accepted.content
        assert accepted.headers["cache-control"] == "no-store"

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ISSUER + "/token"
        assert not request.url.params
        return httpx.Response(
            200,
            json={
                "id_token": raw_id_token.decode("ascii"),
                "access_token": "external-access-token-not-retained",
                "refresh_token": "external-refresh-token-not-retained",
            },
            headers={"Content-Type": "application/json"},
        )

    issued = login.wait_and_issue(
        timeout_seconds=5.0,
        token_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    session = verify_cloud_session_manifest(
        setup["store"].snapshot(),
        setup["cloud_protocol"],
        issued.session_root,
    )
    assert session.subject_root == setup["roots"]["subject"]
    assert session.tenant_root == setup["roots"]["tenant"]
    assert session.device_root.endswith(DEVICE_THUMBPRINT)
    atoms = tuple(cell.atom for cell in setup["store"].snapshot().cells.values())
    assert raw_id_token not in atoms
    assert b"rejected-native-provider-code" not in atoms
    assert b"accepted-native-provider-code" not in atoms
    assert b"external-access-token-not-retained" not in atoms
    assert b"external-refresh-token-not-retained" not in atoms
    assert issued.access_token.encode("ascii") not in atoms


def test_closed_native_loopback_login_cannot_issue_after_a_valid_callback():
    setup = _native_cloud_login_world(now=time.time())
    login = NativeCloudLogin(
        store=setup["store"],
        protocol=setup["native_protocol"],
        registration_root=setup["registration"],
        native_authorization_broker=setup["native_broker"],
        federated_identity_broker=setup["world"]["federated"],
        cloud_session_broker=setup["cloud_broker"],
        client_admission_verifier=setup["client_admission_verifier"],
        allowed_action_roots=(setup["action_root"],),
    )
    started = login.start(device_thumbprint=DEVICE_THUMBPRINT)
    query = parse_qs(urlsplit(started.authorization_url).query)
    with httpx.Client(trust_env=False) as callback_client:
        accepted = callback_client.get(
            query["redirect_uri"][0],
            params={
                "code": "accepted-then-cancelled-code",
                "state": query["state"][0],
                "iss": ISSUER,
            },
        )
    assert accepted.status_code == 200
    login.close()
    with pytest.raises(NativeCloudLoginDenied, match="closed"):
        login.wait_and_issue(timeout_seconds=1.0)
    atoms = tuple(cell.atom for cell in setup["store"].snapshot().cells.values())
    assert b"accepted-then-cancelled-code" not in atoms
