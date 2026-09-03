from __future__ import annotations

import hashlib
from types import MappingProxyType

import httpx
import pytest
from joserfc import jwk, jwt

from nodelang.cell_attestations import CourtInvocation
from nodelang.cell_oidc import OidcAssertionCourtRunner
from nodelang.cell_oidc_discovery import (
    OidcDiscoveryDenied,
    OidcDiscoveryKeyResolver,
    VerifiedOidcDiscovery,
)


ISSUER = "https://identity.archhub.test/tenant"
JWKS_URI = "https://keys.archhub.test/oidc/jwks.json"
AUTHORIZATION_ENDPOINT = ISSUER + "/authorize"
TOKEN_ENDPOINT = ISSUER + "/token"
AUDIENCE = "archhub-desktop"
NONCE = "oidc-login-nonce"
NOW = 50_000.0


def _key():
    key = jwk.ECKey.generate_key("P-256")
    key.ensure_kid()
    return key


def _token(key, *, headers=None) -> bytes:
    protected = {"alg": "ES256", "kid": key.kid}
    protected.update(headers or {})
    return jwt.encode(
        protected,
        {
            "iss": ISSUER,
            "sub": "external-subject",
            "aud": AUDIENCE,
            "exp": NOW + 120,
            "iat": NOW - 2,
            "auth_time": NOW - 3,
            "nonce": NONCE,
            "acr": "urn:archhub:aal2",
            "amr": ["webauthn"],
        },
        key,
        algorithms=["ES256"],
    ).encode("ascii")


def _invocation(content: bytes) -> CourtInvocation:
    return CourtInvocation(
        "federated-identity-assertion",
        hashlib.sha256(content).hexdigest(),
        content,
        MappingProxyType({
            "expected_issuer": ISSUER,
            "expected_audience": AUDIENCE,
            "expected_nonce_sha256": hashlib.sha256(
                NONCE.encode("utf-8")
            ).hexdigest(),
        }),
    )


def _metadata(**changes):
    value = {
        "issuer": ISSUER,
        "jwks_uri": JWKS_URI,
        "id_token_signing_alg_values_supported": ["ES256"],
        "authorization_endpoint": AUTHORIZATION_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }
    value.update(changes)
    return value


class Provider:
    def __init__(self, key) -> None:
        self.key = key
        self.calls: list[str] = []
        self.metadata = _metadata()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if str(request.url) == ISSUER + "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json=self.metadata,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "max-age=300",
                },
            )
        if str(request.url) == JWKS_URI:
            return httpx.Response(
                200,
                json={"keys": [self.key.as_dict(private=False)]},
                headers={
                    "Content-Type": "application/jwk-set+json",
                    "Cache-Control": "max-age=300",
                },
            )
        return httpx.Response(404, json={})


def _resolver(provider: Provider) -> OidcDiscoveryKeyResolver:
    return OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        allowed_jwks_origins=("https://keys.archhub.test",),
        allowed_algorithms=("ES256",),
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        clock=lambda: NOW,
    )


def _runner(resolver):
    return OidcAssertionCourtRunner(
        issuer=ISSUER,
        audience=AUDIENCE,
        public_key_set=resolver,
        assurance_by_acr={"urn:archhub:aal2": "aal2"},
        allowed_algorithms=("ES256",),
        clock=lambda: NOW,
    )


def test_discovery_exact_issuer_and_allowlisted_jwks_verify_real_token():
    key = _key()
    provider = Provider(key)
    resolver = _resolver(provider)
    result = _runner(resolver)(_invocation(_token(key)))

    assert result.passed
    assert provider.calls == [
        ISSUER + "/.well-known/openid-configuration",
        JWKS_URI,
    ]
    snapshot = resolver.snapshot()
    assert snapshot.issuer == ISSUER
    assert snapshot.jwks_uri == JWKS_URI
    assert snapshot.key_ids == (key.kid,)
    assert snapshot.authorization_endpoint == AUTHORIZATION_ENDPOINT
    assert snapshot.token_endpoint == TOKEN_ENDPOINT
    assert snapshot.response_types == ("code",)
    assert snapshot.code_challenge_methods == ("S256",)
    assert snapshot.authorization_response_issuer_supported is True
    assert _runner(resolver)(_invocation(_token(key))).passed
    assert len(provider.calls) == 2


def test_native_client_discovery_authority_is_resolver_only():
    provider = Provider(_key())
    authority = _resolver(provider).native_client_authority()
    assert type(authority) is VerifiedOidcDiscovery
    assert authority.snapshot.issuer == ISSUER
    with pytest.raises(TypeError):
        VerifiedOidcDiscovery(object(), authority.snapshot)


def test_unknown_kid_forces_one_bounded_jwks_refresh_for_rotation():
    old_key = _key()
    new_key = _key()
    attacker_key = _key()
    provider = Provider(old_key)
    resolver = _resolver(provider)
    assert _runner(resolver)(_invocation(_token(old_key))).passed

    provider.key = new_key
    assert _runner(resolver)(_invocation(_token(new_key))).passed
    calls_after_rotation = len(provider.calls)
    denied = _runner(resolver)(_invocation(_token(attacker_key)))
    assert not denied.passed
    assert not denied.checks["signature"]
    assert len(provider.calls) == calls_after_rotation


@pytest.mark.parametrize("metadata,match", [
    (_metadata(issuer="https://attacker.test"), "issuer mismatched"),
    (_metadata(jwks_uri="https://attacker.test/jwks"), "not allowlisted"),
    (
        _metadata(id_token_signing_alg_values_supported=["HS256", "none"]),
        "no allowed",
    ),
    (
        _metadata(token_endpoint="https://attacker.test/token"),
        "token endpoint origin is not allowlisted",
    ),
])
def test_discovery_metadata_mismatch_fails_closed(metadata, match):
    provider = Provider(_key())
    provider.metadata = metadata
    resolver = _resolver(provider)
    with pytest.raises(OidcDiscoveryDenied, match=match):
        resolver.preload()


def test_redirect_private_key_and_oversized_response_fail_closed():
    key = _key()

    def redirect(request: httpx.Request):
        return httpx.Response(302, headers={"Location": "https://attacker.test"})

    resolver = OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        allowed_jwks_origins=("https://keys.archhub.test",),
        client=httpx.Client(transport=httpx.MockTransport(redirect)),
        clock=lambda: NOW,
    )
    with pytest.raises(OidcDiscoveryDenied, match="did not return 200"):
        resolver.preload()

    provider = Provider(key)

    def unsafe_jwks(request: httpx.Request):
        if "openid-configuration" in str(request.url):
            return provider(request)
        return httpx.Response(
            200,
            json={"keys": [key.as_dict(private=True)]},
            headers={"Content-Type": "application/json"},
        )

    unsafe = OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        allowed_jwks_origins=("https://keys.archhub.test",),
        client=httpx.Client(transport=httpx.MockTransport(unsafe_jwks)),
        clock=lambda: NOW,
    )
    with pytest.raises(OidcDiscoveryDenied, match="private"):
        unsafe.preload()

    def oversized(request: httpx.Request):
        return httpx.Response(
            200,
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(2 * 1024 * 1024),
            },
        )

    too_large = OidcDiscoveryKeyResolver(
        issuer=ISSUER,
        client=httpx.Client(transport=httpx.MockTransport(oversized)),
        clock=lambda: NOW,
    )
    with pytest.raises(OidcDiscoveryDenied, match="too large"):
        too_large.preload()


def test_token_selected_key_url_is_rejected_even_when_signature_is_valid():
    key = _key()
    provider = Provider(key)
    resolver = _resolver(provider)
    token = _token(key, headers={"jku": "https://attacker.test/jwks"})
    result = _runner(resolver)(_invocation(token))
    assert not result.passed
    assert not result.checks["signature"]
