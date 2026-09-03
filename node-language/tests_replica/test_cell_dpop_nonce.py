from __future__ import annotations

import base64
import json

import pytest

from nodelang.cell_dpop_nonce import (
    DpopNonceDenied,
    ResourceServerNonceBroker,
    extract_unverified_proof_nonce,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider


def _broker(provider=None, *, audience="https://api.archhub.test"):
    provider = provider or MemorySigningKeyProvider(
        "test:dpop-nonce", b"nonce-key-material-with-more-than-32-bytes"
    )
    return ResourceServerNonceBroker(
        key_provider=provider,
        key_id="test:dpop-nonce",
        audience=audience,
        lifetime_seconds=60,
    )


def _proof(nonce: str) -> bytes:
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=")
    header = encode(b'{"alg":"none","typ":"dpop+jwt"}')
    payload = encode(json.dumps({"nonce": nonce}).encode("utf-8"))
    return header + b"." + payload + b".untrusted-signature"


def test_nonce_is_token_audience_time_and_signature_bound():
    broker = _broker()
    nonce = broker.mint("access-token-a", now=1000)

    assert broker.verify(nonce, "access-token-a", now=1030) == nonce
    with pytest.raises(DpopNonceDenied, match="token binding"):
        broker.verify(nonce, "access-token-b", now=1030)
    with pytest.raises(DpopNonceDenied, match="audience"):
        _broker(audience="https://other.example").verify(
            nonce, "access-token-a", now=1030
        )
    with pytest.raises(DpopNonceDenied, match="time window"):
        broker.verify(nonce, "access-token-a", now=1060)


def test_nonce_tampering_and_unknown_key_fail_closed():
    provider = MemorySigningKeyProvider(
        "test:dpop-nonce", b"nonce-key-material-with-more-than-32-bytes"
    )
    broker = _broker(provider)
    nonce = broker.mint("access-token", now=1000)
    prefix, payload, signature = nonce.split(".")
    tampered = "%s.%s.%s" % (
        prefix,
        ("A" if payload[0] != "A" else "B") + payload[1:],
        signature,
    )
    with pytest.raises(DpopNonceDenied):
        broker.verify(tampered, "access-token", now=1001)

    foreign = _broker(MemorySigningKeyProvider(
        "test:dpop-nonce", b"different-key-material-with-more-than-32"
    ))
    with pytest.raises(DpopNonceDenied, match="signature"):
        foreign.verify(nonce, "access-token", now=1001)


def test_nonce_survives_key_rotation_while_old_version_is_retained():
    provider = MemorySigningKeyProvider(
        "test:dpop-nonce", b"nonce-key-material-with-more-than-32-bytes"
    )
    broker = _broker(provider)
    old_nonce = broker.mint("access-token", now=1000)
    provider.rotate(
        "test:dpop-nonce", b"rotated-key-material-with-more-than-32-bytes"
    )
    new_nonce = broker.mint("access-token", now=1001)

    assert broker.verify(old_nonce, "access-token", now=1002) == old_nonce
    assert broker.verify(new_nonce, "access-token", now=1002) == new_nonce


def test_unverified_nonce_extraction_is_bounded_and_confers_no_authority():
    nonce = _broker().mint("access-token", now=1000)
    proof = _proof(nonce)
    assert extract_unverified_proof_nonce(proof) == nonce
    with pytest.raises(DpopNonceDenied):
        extract_unverified_proof_nonce(b"not-a-jwt")
    with pytest.raises(DpopNonceDenied, match="no usable"):
        extract_unverified_proof_nonce(_proof("").replace(b'""', b"null"))
