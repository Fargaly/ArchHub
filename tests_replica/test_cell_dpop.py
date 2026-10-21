"""RFC 9449 proof court using real asymmetric JOSE signatures."""
from __future__ import annotations

import base64
import hashlib
import time

import pytest
from joserfc import jwk, jwt

from nodelang.cell_dpop import DpopProofDenied, JoseRfc9449ProofVerifier


TOKEN = "ah_dpop_client-secret-token"
NONCE = "server-issued-unpredictable-nonce"
URI = "https://api.archhub.test/v1/graph"


def _ath(token: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(token.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


def _proof(key, *, now: float, **changes) -> bytes:
    claims = {
        "jti": "proof-id-1234567890",
        "htm": "GET",
        "htu": URI,
        "iat": now,
        "ath": _ath(TOKEN),
        "nonce": NONCE,
    }
    claims.update(changes)
    return jwt.encode(
        {
            "typ": "dpop+jwt",
            "alg": "ES256",
            "jwk": key.as_dict(private=False),
        },
        claims,
        key,
        algorithms=["ES256"],
        default_type=None,
    ).encode("ascii")


def _verify(verifier, key, proof: bytes, *, now: float, **changes):
    values = {
        "access_token": TOKEN,
        "expected_thumbprint": key.thumbprint(),
        "http_method": "GET",
        "target_uri": URI,
        "expected_nonce": NONCE,
        "now": now,
    }
    values.update(changes)
    return verifier.verify(proof, **values)


def test_real_es256_dpop_verifies_exact_request_and_rfc7638_key():
    now = time.time()
    key = jwk.ECKey.generate_key("P-256")
    verifier = JoseRfc9449ProofVerifier()
    assert verifier.replay_retention_seconds == 15.0
    proof = _proof(
        key,
        now=now,
        htu="https://API.ARCHHUB.TEST:443/v1/graph",
    )
    assert _verify(
        verifier,
        key,
        proof,
        now=now,
        target_uri=URI + "?projection=canvas",
    ) == "proof-id-1234567890"
    assert len(key.thumbprint()) == 43


@pytest.mark.parametrize(("claim", "value"), [
    ("htm", "POST"),
    ("htu", "https://api.archhub.test/v1/other"),
    ("nonce", "wrong"),
    ("ath", "wrong"),
    ("iat", 1),
    ("jti", "short"),
])
def test_dpop_rejects_wrong_request_bindings(claim, value):
    now = time.time()
    key = jwk.ECKey.generate_key("P-256")
    proof = _proof(key, now=now, **{claim: value})
    with pytest.raises(DpopProofDenied):
        _verify(JoseRfc9449ProofVerifier(), key, proof, now=now)


def test_dpop_rejects_wrong_session_key_and_modified_signature():
    now = time.time()
    key = jwk.ECKey.generate_key("P-256")
    other = jwk.ECKey.generate_key("P-256")
    proof = _proof(key, now=now)
    with pytest.raises(DpopProofDenied, match="session-bound"):
        _verify(JoseRfc9449ProofVerifier(), other, proof, now=now)
    compact = proof.decode("ascii")
    replacement = "A" if compact[-1] != "A" else "B"
    modified = (compact[:-1] + replacement).encode("ascii")
    with pytest.raises(DpopProofDenied, match="signature"):
        _verify(JoseRfc9449ProofVerifier(), key, modified, now=now)


def test_dpop_rejects_symmetric_algorithm_configuration():
    with pytest.raises(ValueError, match="asymmetric"):
        JoseRfc9449ProofVerifier(allowed_algorithms=("HS256",))


def test_dpop_rejects_non_https_non_local_target():
    now = time.time()
    key = jwk.ECKey.generate_key("P-256")
    proof = _proof(key, now=now, htu="http://api.archhub.test/v1/graph")
    with pytest.raises(DpopProofDenied, match="HTTPS"):
        _verify(JoseRfc9449ProofVerifier(), key, proof, now=now)
