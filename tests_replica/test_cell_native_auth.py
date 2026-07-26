from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc import jwk

import nodelang.cell_native_auth as cell_native_auth
from nodelang.cell_cloud_sessions import device_root_for_thumbprint
from nodelang.cell_native_auth import (
    NativeAuthenticationDenied,
    NativeAuthorizationBroker,
    NativeAuthorizationCode,
    NativeIdentityAssertion,
    SignedNativeClientAdmissionVerifier,
    activate_native_client_registration,
    bootstrap_native_authentication_protocol,
    build_native_client_registration,
    exchange_native_authorization_code,
    native_authorization_status,
    read_native_authorization_completion,
    read_native_authorization_transaction,
    read_native_client_registration,
)
from nodelang.cell_identity import (
    RelationshipAuthorityBroker,
    bootstrap_identity_protocol,
    revoke_authority_relationship,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_oidc_discovery import OidcDiscoveryKeyResolver
from nodelang.universal_cell import Conflict, NULL_CELL_ID, Cell, CellStore


ISSUER = "https://identity.archhub.test/tenant"
AUTHORIZATION_ENDPOINT = ISSUER + "/authorize"
TOKEN_ENDPOINT = ISSUER + "/token"
CLIENT_ID = "archhub-desktop"
DEVICE_THUMBPRINT = "A" * 43
NOW = 50_000.0


def _discovery_authority(**changes):
    metadata = {
        "issuer": ISSUER,
        "jwks_uri": ISSUER + "/jwks",
        "authorization_endpoint": AUTHORIZATION_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "id_token_signing_alg_values_supported": ["ES256"],
    }
    metadata.update(changes)
    key = jwk.ECKey.generate_key("P-256")
    key.ensure_kid()

    def provider(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json=metadata,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "max-age=300",
                },
            )
        return httpx.Response(
            200,
            json={"keys": [key.as_dict(private=False)]},
            headers={"Content-Type": "application/jwk-set+json"},
        )

    resolver = OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        allowed_algorithms=("ES256",),
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        clock=lambda: NOW,
    )
    return resolver.native_client_authority()


def _world(*, activate: bool = True):
    store = CellStore()
    protocol = bootstrap_native_authentication_protocol(
        store, prefix="test:native-auth"
    )
    identity = bootstrap_identity_protocol(store, prefix="test:native-identity")
    device_root = device_root_for_thumbprint(DEVICE_THUMBPRINT)
    store.commit(store.revision, create=(
        Cell(
            device_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            ("device-proof-key-thumbprint:" + DEVICE_THUMBPRINT).encode("ascii"),
        ),
        Cell("test:native:administrator", NULL_CELL_ID, NULL_CELL_ID, b"administrator"),
        Cell("test:native:tenant", NULL_CELL_ID, NULL_CELL_ID, b"tenant"),
        Cell("test:native:audience", NULL_CELL_ID, NULL_CELL_ID, CLIENT_ID.encode("ascii")),
    ))
    relationship_broker = RelationshipAuthorityBroker(
        ("test:native:administrator",),
        key_provider=MemorySigningKeyProvider(
            "test:native:key", b"native-relationship-key-material-32+"
        ),
        key_id="test:native:key",
    )
    registration = build_native_client_registration(
        store,
        protocol,
        _discovery_authority(),
        registration_id="test:native-client",
        client_id=CLIENT_ID,
        scopes=("openid", "profile"),
        now=NOW,
    )
    activation = relationship_broker.mint_from_trusted_administrator(
        "test:native:administrator"
    )
    activation_root = None
    if activate:
        activation_root = activate_native_client_registration(
            store,
            protocol,
            identity,
            relationship_broker,
            activation,
            registration_root=registration,
            relationship_id="test:native-client:activation",
            tenant_root="test:native:tenant",
            audience_root="test:native:audience",
            administrator_root="test:native:administrator",
            reason="founder approved native client",
            now=NOW,
        )
    verifier = SignedNativeClientAdmissionVerifier(
        native_protocol=protocol,
        identity_protocol=identity,
        relationship_broker=relationship_broker,
        tenant_root="test:native:tenant",
        audience_root="test:native:audience",
    )
    return (
        store,
        protocol,
        registration,
        verifier,
        identity,
        relationship_broker,
        activation_root,
    )


def _start():
    world = _world()
    store, protocol, registration, verifier = world[:4]
    broker = NativeAuthorizationBroker(verifier)
    started = broker.start(
        store,
        protocol,
        registration,
        redirect_port=49152,
        device_thumbprint=DEVICE_THUMBPRINT,
        now=NOW,
    )
    return (*world, broker, started)


def test_native_client_and_transaction_are_open_relations_without_secrets():
    (
        store,
        protocol,
        registration,
        _verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        _broker,
        started,
    ) = _start()
    client = read_native_client_registration(
        store.snapshot(), protocol, registration
    )
    transaction = read_native_authorization_transaction(
        store.snapshot(), protocol, started.transaction_root
    )
    query = parse_qs(urlsplit(started.authorization_url).query)

    assert client.root_id == registration
    assert transaction.client_root == registration
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [
        "http://127.0.0.1:49152/oauth/callback"
    ]
    assert query["scope"] == ["openid profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW
    ) == "pending"

    atoms = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert query["state"][0].encode("ascii") not in atoms
    assert query["nonce"][0].encode("ascii") not in atoms
    assert hashlib.sha256(
        query["state"][0].encode("ascii")
    ).hexdigest().encode("ascii") in atoms
    assert hashlib.sha256(
        query["nonce"][0].encode("ascii")
    ).hexdigest().encode("ascii") in atoms


def test_callback_requires_exact_state_and_response_issuer_then_is_one_use():
    (
        store,
        protocol,
        _registration,
        _verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        broker,
        started,
    ) = _start()
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]

    with pytest.raises(NativeAuthenticationDenied, match="state mismatched"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state="wrong",
            response_issuer=ISSUER,
            authorization_code="code-1",
            now=NOW + 1,
        )
    with pytest.raises(NativeAuthenticationDenied, match="issuer mismatched"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=state,
            response_issuer="https://attacker.test",
            authorization_code="code-1",
            now=NOW + 1,
        )

    capability = broker.complete(
        store,
        protocol,
        started.transaction_root,
        state=state,
        response_issuer=ISSUER,
        authorization_code="one-use-code",
        now=NOW + 1,
    )
    assert capability.transaction_root == started.transaction_root
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 1
    ) == "completed"
    completion = read_native_authorization_completion(
        store.snapshot(), protocol, capability.completion_root
    )
    assert completion.transaction_root == started.transaction_root
    atoms = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert b"one-use-code" not in atoms
    assert hashlib.sha256(b"one-use-code").hexdigest().encode("ascii") in atoms

    with pytest.raises(NativeAuthenticationDenied, match="no live secret custody"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=state,
            response_issuer=ISSUER,
            authorization_code="second-code",
            now=NOW + 2,
        )


def test_completion_commit_conflict_does_not_burn_secret_custody(monkeypatch):
    (
        store,
        protocol,
        _registration,
        _verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        broker,
        started,
    ) = _start()
    query = parse_qs(urlsplit(started.authorization_url).query)
    original_commit = store.commit
    failed = False

    def fail_first_completion(expected_revision, *, create=(), replace=()):
        nonlocal failed
        if not failed and any(
            cell.id.startswith("native-authorization-completion:")
            for cell in create
        ):
            failed = True
            raise Conflict("simulated completion conflict")
        return original_commit(
            expected_revision,
            create=create,
            replace=replace,
        )

    monkeypatch.setattr(store, "commit", fail_first_completion)
    with pytest.raises(Conflict, match="simulated completion conflict"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="retryable-code",
            now=NOW + 1,
        )
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 1
    ) == "pending"
    completed = broker.complete(
        store,
        protocol,
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="retryable-code",
        now=NOW + 1,
    )
    assert completed.transaction_root == started.transaction_root
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 1
    ) == "completed"


def test_completion_preparation_failure_does_not_lock_secret_custody(monkeypatch):
    (
        store,
        protocol,
        _registration,
        _verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        broker,
        started,
    ) = _start()
    query = parse_qs(urlsplit(started.authorization_url).query)
    original_prepare = cell_native_auth.prepare_append_relation_member
    failed = False

    def fail_first_completion(*args, **kwargs):
        nonlocal failed
        if (
            not failed
            and args[1] == protocol.root_id
            and args[2] == protocol.role("completion-member")
        ):
            failed = True
            raise RuntimeError("simulated completion preparation failure")
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(
        cell_native_auth,
        "prepare_append_relation_member",
        fail_first_completion,
    )
    with pytest.raises(
        RuntimeError, match="simulated completion preparation failure"
    ):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="retryable-preparation-code",
            now=NOW + 1,
        )
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 1
    ) == "pending"
    completed = broker.complete(
        store,
        protocol,
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="retryable-preparation-code",
        now=NOW + 1,
    )
    assert completed.transaction_root == started.transaction_root
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 1
    ) == "completed"


def test_client_requires_signed_tenant_activation_before_authorization():
    store, protocol, registration, verifier, *_rest = _world(activate=False)
    broker = NativeAuthorizationBroker(verifier)
    with pytest.raises(NativeAuthenticationDenied, match="activation is unavailable"):
        broker.start(
            store,
            protocol,
            registration,
            redirect_port=49152,
            device_thumbprint=DEVICE_THUMBPRINT,
            now=NOW,
        )


def test_revoking_client_tenant_activation_blocks_inflight_callback():
    (
        store,
        protocol,
        _registration,
        _verifier,
        identity,
        relationship_broker,
        activation_root,
        broker,
        started,
    ) = _start()
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    administration = relationship_broker.mint_from_trusted_administrator(
        "test:native:administrator"
    )
    revoke_authority_relationship(
        store,
        identity,
        relationship_broker,
        administration,
        activation_root,
        administrator_root="test:native:administrator",
        reason="founder withdrew this client's tenant access",
        now=NOW + 1,
    )
    with pytest.raises(NativeAuthenticationDenied, match="activation was revoked"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=state,
            response_issuer=ISSUER,
            authorization_code="must-not-pass",
            now=NOW + 2,
        )


def test_token_exchange_is_exact_public_client_pkce_and_discards_provider_tokens():
    (
        store,
        protocol,
        _registration,
        _verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        broker,
        started,
    ) = _start()
    query = parse_qs(urlsplit(started.authorization_url).query)
    capability = broker.complete(
        store,
        protocol,
        started.transaction_root,
        state=query["state"][0],
        response_issuer=ISSUER,
        authorization_code="authorization-code",
        now=NOW + 1,
    )
    seen = {}

    def provider(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = parse_qs(request.content.decode("ascii"))
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id_token": "signed.id.token",
                "access_token": "provider-access-secret",
                "refresh_token": "provider-refresh-secret",
                "token_type": "Bearer",
            },
            headers={"Content-Type": "application/json"},
        )

    client = httpx.Client(transport=httpx.MockTransport(provider))
    assertion = exchange_native_authorization_code(capability, client=client)

    assert seen["url"] == TOKEN_ENDPOINT
    assert seen["authorization"] is None
    assert seen["body"]["grant_type"] == ["authorization_code"]
    assert seen["body"]["code"] == ["authorization-code"]
    assert seen["body"]["client_id"] == [CLIENT_ID]
    assert seen["body"]["redirect_uri"] == [
        "http://127.0.0.1:49152/oauth/callback"
    ]
    assert len(seen["body"]["code_verifier"][0]) >= 43
    assert "client_secret" not in seen["body"]
    assert assertion.id_token == b"signed.id.token"
    assert assertion.expected_issuer == ISSUER
    assert assertion.expected_audience == CLIENT_ID
    assert assertion.expected_nonce == query["nonce"][0]
    assert assertion.device_thumbprint == DEVICE_THUMBPRINT

    atom_values = tuple(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert b"authorization-code" not in atom_values
    assert b"signed.id.token" not in atom_values
    assert b"provider-access-secret" not in atom_values
    assert b"provider-refresh-secret" not in atom_values
    with pytest.raises(NativeAuthenticationDenied, match="already consumed"):
        exchange_native_authorization_code(capability, client=client)


def test_expired_or_restarted_transaction_fails_closed():
    (
        store,
        protocol,
        _registration,
        verifier,
        _identity,
        _relationship_broker,
        _activation_root,
        broker,
        started,
    ) = _start()
    query = parse_qs(urlsplit(started.authorization_url).query)
    assert native_authorization_status(
        store.snapshot(), protocol, started.transaction_root, now=NOW + 301
    ) == "expired"
    with pytest.raises(NativeAuthenticationDenied, match="expired"):
        broker.complete(
            store,
            protocol,
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="late-code",
            now=NOW + 301,
        )
    with pytest.raises(NativeAuthenticationDenied, match="no live secret custody"):
        NativeAuthorizationBroker(verifier).complete(
            store,
            protocol,
            started.transaction_root,
            state=query["state"][0],
            response_issuer=ISSUER,
            authorization_code="restart-code",
            now=NOW + 2,
        )


@pytest.mark.parametrize("changes,build_time", [
    ({"code_challenge_methods_supported": []}, NOW),
    ({"response_types_supported": []}, NOW),
    ({"authorization_response_iss_parameter_supported": False}, NOW),
    ({"authorization_endpoint": None}, NOW),
    ({"token_endpoint": None}, NOW),
    ({}, NOW + 301),
])
def test_native_registration_rejects_incomplete_or_expired_discovery(
    changes, build_time
):
    store = CellStore()
    protocol = bootstrap_native_authentication_protocol(
        store, prefix="test:denied-native-auth"
    )
    with pytest.raises(NativeAuthenticationDenied):
        build_native_client_registration(
            store,
            protocol,
            _discovery_authority(**changes),
            registration_id="test:denied-native-client",
            client_id=CLIENT_ID,
            now=build_time,
        )


def test_native_capabilities_cannot_be_forged():
    with pytest.raises(TypeError):
        NativeAuthorizationCode(
            object(),
            transaction_root="transaction",
            completion_root="completion",
            registration_root="registration",
            issuer=ISSUER,
            client_id=CLIENT_ID,
            token_endpoint=TOKEN_ENDPOINT,
            redirect_uri="http://127.0.0.1:49152/oauth/callback",
            authorization_code="code",
            code_verifier="v" * 43,
            nonce="nonce",
            device_thumbprint=DEVICE_THUMBPRINT,
            tenant_root="tenant",
            audience_root="audience",
            client_authority_root="client-authority",
        )
    with pytest.raises(TypeError):
        NativeIdentityAssertion(
            object(),
            transaction_root="transaction",
            completion_root="completion",
            registration_root="registration",
            id_token=b"token",
            expected_issuer=ISSUER,
            expected_audience=CLIENT_ID,
            expected_nonce="nonce",
            device_thumbprint=DEVICE_THUMBPRINT,
            tenant_root="tenant",
            audience_root="audience",
            client_authority_root="client-authority",
        )
