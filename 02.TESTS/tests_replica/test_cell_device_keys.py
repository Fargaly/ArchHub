"""Windows CNG custody court for the device-bound DPoP capability."""
import base64
import hashlib
import os
import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from nodelang.cell_device_keys import (
    DeviceProofKeyError,
    SOFTWARE_PROVIDER,
    WindowsCngDeviceProofKey,
    WindowsCngRecipientKey,
)
from nodelang.cell_dpop import JoseRfc9449ProofVerifier


TOKEN = "ah_dpop_cng-device-court-token"
NONCE = "archhub-server-nonce-for-cng-court"
URI = "https://api.archhub.test/v1/graph"


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG court")
def test_software_custody_requires_explicit_permission():
    with pytest.raises(DeviceProofKeyError, match="explicit permission"):
        WindowsCngDeviceProofKey(
            "ArchHub.Test." + uuid.uuid4().hex,
            provider=SOFTWARE_PROVIDER,
            create_if_missing=True,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG court")
def test_persisted_cng_key_signs_rfc9449_without_private_key_export():
    key_name = "ArchHub.Test." + uuid.uuid4().hex
    key = None
    reopened = None
    try:
        key = WindowsCngDeviceProofKey(
            key_name,
            provider=SOFTWARE_PROVIDER,
            create_if_missing=True,
            allow_software=True,
        )
        reference = key.reference
        assert reference.key_name == key_name
        assert reference.provider == SOFTWARE_PROVIDER
        assert reference.algorithm == "ES256"
        assert reference.hardware_backed is False
        assert len(reference.thumbprint) == 43
        assert set(reference.public_jwk) == {"crv", "kty", "x", "y"}
        assert reference.public_jwk["crv"] == "P-256"
        assert reference.public_jwk["kty"] == "EC"
        assert not {"d", "k", "p", "q"}.intersection(reference.public_jwk)
        key.close()
        key = None

        reopened = WindowsCngDeviceProofKey(
            key_name,
            provider=SOFTWARE_PROVIDER,
            allow_software=True,
        )
        assert reopened.reference == reference
        now = time.time()
        proof = reopened.dpop_proof(
            http_method="GET",
            target_uri=URI + "?projection=canvas",
            access_token=TOKEN,
            nonce=NONCE,
            issued_at=now,
            proof_id="cng-proof-id-1234567890",
        )
        assert JoseRfc9449ProofVerifier(
            allowed_algorithms=("ES256",)
        ).verify(
            proof,
            access_token=TOKEN,
            expected_thumbprint=reference.thumbprint,
            http_method="GET",
            target_uri=URI,
            expected_nonce=NONCE,
            now=now,
        ) == "cng-proof-id-1234567890"
    finally:
        cleanup = reopened or key
        if cleanup is None:
            try:
                cleanup = WindowsCngDeviceProofKey(
                    key_name,
                    provider=SOFTWARE_PROVIDER,
                    allow_software=True,
                )
            except DeviceProofKeyError:
                cleanup = None
        if cleanup is not None:
            cleanup.delete_test_key()
            cleanup.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG court")
def test_device_key_rejects_unsafe_provider_and_digest_shape():
    with pytest.raises(DeviceProofKeyError, match="not allowed"):
        WindowsCngDeviceProofKey(
            "ArchHub.Test." + uuid.uuid4().hex,
            provider="Untrusted Provider",
        )
    key_name = "ArchHub.Test." + uuid.uuid4().hex
    key = WindowsCngDeviceProofKey(
        key_name,
        provider=SOFTWARE_PROVIDER,
        create_if_missing=True,
        allow_software=True,
    )
    try:
        with pytest.raises(ValueError, match="SHA-256"):
            key.sign_digest(b"short")
    finally:
        key.delete_test_key()
        key.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG court")
def test_nonexporting_recipient_key_derives_the_p256_secret_for_an_ephemeral_sender():
    key_name = "ArchHub.Test." + uuid.uuid4().hex
    key = WindowsCngRecipientKey(
        key_name,
        provider=SOFTWARE_PROVIDER,
        create_if_missing=True,
        allow_software=True,
    )
    try:
        reference = key.reference
        assert reference.algorithm == "ECDH-ES"
        assert reference.hardware_backed is False
        assert not {"d", "k", "p", "q"}.intersection(reference.public_jwk)

        sender = ec.generate_private_key(ec.SECP256R1())
        sender_numbers = sender.public_key().public_numbers()
        encode = lambda number: base64.urlsafe_b64encode(
            int(number).to_bytes(32, "big")
        ).rstrip(b"=").decode("ascii")
        sender_jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": encode(sender_numbers.x),
            "y": encode(sender_numbers.y),
        }
        recipient_public = ec.EllipticCurvePublicNumbers(
            int.from_bytes(base64.urlsafe_b64decode(reference.public_jwk["x"] + "="), "big"),
            int.from_bytes(base64.urlsafe_b64decode(reference.public_jwk["y"] + "="), "big"),
            ec.SECP256R1(),
        ).public_key()
        assert key.derive_shared_secret(sender_jwk) == hashlib.sha256(
            sender.exchange(ec.ECDH(), recipient_public)
        ).digest()
    finally:
        key.delete_test_key()
        key.close()
