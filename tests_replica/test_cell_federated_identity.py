from __future__ import annotations

import hashlib
import hmac
import json
import time
import base64
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc import jwk

from nodelang.cell_attestations import (
    CourtAttestationBroker,
    CourtInvocation,
    CourtResult,
    bootstrap_attestation_protocol,
    build_court_definition,
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
from nodelang.cell_protocols import read_relation
from nodelang.native_cloud_login import NativeCloudLogin, NativeCloudLoginDenied
from nodelang.remote_native_cloud_login import (
    RemoteNativeCloudLoginBroker,
    ReturningDeviceAdmissionDenied,
    ReturningDeviceAdmissionVerifier,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


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
    protocol = bootstrap_cloud_session_protocol(
        world["store"], prefix="test:cloud-session"
    )
    broker = CloudSessionBroker(
        session_protocol=protocol,
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=_RequestProofVerifier(),
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
    cloud_broker = CloudSessionBroker(
        session_protocol=cloud_protocol,
        identity_protocol=world["identity"],
        relationship_broker=world["relationship_broker"],
        authentication_broker=world["authentication_broker"],
        request_proof_verifier=_RequestProofVerifier(),
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
