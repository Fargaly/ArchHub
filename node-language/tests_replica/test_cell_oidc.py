"""OpenID Connect court using real signed ID tokens and a configured JWKS."""
from __future__ import annotations

import hashlib
from types import MappingProxyType

import pytest
from joserfc import jwk, jwt
from joserfc.jwk import KeySet

from nodelang.cell_attestations import CourtInvocation
from nodelang.cell_federated_identity import federated_subject_reference
from nodelang.cell_oidc import (
    OIDC_COURT_CHECKS,
    OidcAssertionCourtRunner,
    OidcConfigurationError,
)


ISSUER = "https://identity.archhub.test"
AUDIENCE = "archhub-desktop"
SUBJECT = "provider-user-123"
NONCE = "one-time-oidc-nonce"
NOW = 1_000_000.0


def _keys():
    private = jwk.ECKey.generate_key("P-256")
    private.ensure_kid()
    public_set = KeySet.import_key_set({
        "keys": [private.as_dict(private=False)]
    })
    return private, public_set


def _token(key, **changes) -> bytes:
    claims = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": AUDIENCE,
        "exp": NOW + 120,
        "iat": NOW - 2,
        "auth_time": NOW - 3,
        "nonce": NONCE,
        "acr": "urn:archhub:aal2",
        "amr": ["webauthn", "user-verification"],
    }
    claims.update(changes)
    return jwt.encode(
        {"alg": "ES256", "kid": key.kid},
        claims,
        key,
        algorithms=["ES256"],
    ).encode("ascii")


def _invocation(content: bytes, **parameter_changes) -> CourtInvocation:
    parameters = {
        "expected_issuer": ISSUER,
        "expected_audience": AUDIENCE,
        "expected_nonce_sha256": hashlib.sha256(
            NONCE.encode("utf-8")
        ).hexdigest(),
    }
    parameters.update(parameter_changes)
    return CourtInvocation(
        "federated-identity-assertion",
        hashlib.sha256(content).hexdigest(),
        content,
        MappingProxyType(parameters),
    )


def _runner(public_set):
    return OidcAssertionCourtRunner(
        issuer=ISSUER,
        audience=AUDIENCE,
        public_key_set=public_set,
        assurance_by_acr={"urn:archhub:aal2": "aal2"},
        clock=lambda: NOW,
    )


def test_real_oidc_signature_and_exact_claims_produce_pseudonymous_evidence():
    private, public_set = _keys()
    result = _runner(public_set)(_invocation(_token(private)))
    assert result.passed
    assert tuple(result.checks) == OIDC_COURT_CHECKS
    assert result.details["subject_reference"] == federated_subject_reference(
        ISSUER, SUBJECT
    )
    assert SUBJECT not in result.details.values()
    assert result.details["authentication_method"] == (
        "webauthn+user-verification"
    )


@pytest.mark.parametrize("changes", [
    {"iss": "https://attacker.test"},
    {"aud": "wrong-client"},
    {"exp": NOW - 1},
    {"iat": NOW - 301},
    {"auth_time": NOW + 10},
    {"nonce": "wrong"},
    {"sub": ""},
    {"acr": "unreleased-assurance"},
    {"aud": [AUDIENCE, "another"], "azp": "another"},
])
def test_oidc_claim_failures_are_explicit_court_failures(changes):
    private, public_set = _keys()
    result = _runner(public_set)(_invocation(_token(private, **changes)))
    assert not result.passed
    assert not all(result.checks.values())


def test_oidc_rejects_signature_from_key_outside_configured_jwks():
    _, public_set = _keys()
    attacker, _ = _keys()
    result = _runner(public_set)(_invocation(_token(attacker)))
    assert not result.passed
    assert result.checks["signature"] is False


def test_oidc_expected_parameters_cannot_select_another_issuer_or_audience():
    private, public_set = _keys()
    runner = _runner(public_set)
    result = runner(_invocation(
        _token(private), expected_issuer="https://attacker.test"
    ))
    assert not result.passed
    assert result.checks["signature"] is False


def test_oidc_configuration_rejects_symmetric_algorithms_and_http_issuer():
    _, public_set = _keys()
    with pytest.raises(OidcConfigurationError, match="asymmetric"):
        OidcAssertionCourtRunner(
            issuer=ISSUER,
            audience=AUDIENCE,
            public_key_set=public_set,
            assurance_by_acr={"a": "aal2"},
            allowed_algorithms=("HS256",),
        )
    with pytest.raises(OidcConfigurationError, match="HTTPS"):
        OidcAssertionCourtRunner(
            issuer="http://identity.test",
            audience=AUDIENCE,
            public_key_set=public_set,
            assurance_by_acr={"a": "aal2"},
        )
