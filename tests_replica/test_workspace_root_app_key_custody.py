"""Ping review 2026-10-12 (AGENTS T3): the Settings app signing key is never stored in the clear."""
import sys

import pytest

from nodelang import workspace_roots_catalogue as roots

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI custody is Windows-only")


def test_app_signing_key_is_dpapi_protected_never_plaintext(tmp_path):
    key_path = tmp_path / "workspace-roots.app-key.dpapi"
    signer = roots.AppWorkspaceRootSigner(key_path)
    blob = signer.public_blob()
    raw = key_path.read_bytes()
    assert b"PRIVATE KEY" not in raw and not raw.startswith(b"-----")
    assert not list(tmp_path.glob("*.pem")), "no plaintext key file is written"
    assert key_path.with_suffix(".pub").exists()
    payload = b"register bbc4"
    assert roots._ecdsa_verify_blob(blob, payload, signer.sign(payload))


def test_verification_reads_the_public_blob_without_the_private_key(tmp_path):
    key_path = tmp_path / "workspace-roots.app-key.dpapi"
    signer = roots.AppWorkspaceRootSigner(key_path)
    blob = signer.public_blob()
    key_path.unlink()  # private key gone: the public blob must still answer
    assert roots.AppWorkspaceRootSigner(key_path).public_blob() == blob


def test_a_plaintext_key_from_an_earlier_build_is_migrated_and_removed(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    legacy = tmp_path / "workspace-roots.app-key.pem"
    key = ec.generate_private_key(ec.SECP256R1())
    legacy.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    signer = roots.AppWorkspaceRootSigner(tmp_path / "workspace-roots.app-key.dpapi")
    payload = b"migrated"
    sig = signer.sign(payload)
    assert not legacy.exists(), "the plaintext key is removed after migration"
    assert roots._ecdsa_verify_blob(signer.public_blob(), payload, sig)
    assert signer.public_blob() == roots.AppWorkspaceRootSigner._public_blob_of(key)


def test_corrupt_protected_key_refuses_and_never_falls_back_to_plaintext(tmp_path):
    key_path = tmp_path / "workspace-roots.app-key.dpapi"
    signer = roots.AppWorkspaceRootSigner(key_path)
    signer.public_blob()
    key_path.write_bytes(b"not dpapi bytes")
    with pytest.raises(Exception):
        roots.AppWorkspaceRootSigner(key_path).sign(b"x")
    assert key_path.read_bytes() == b"not dpapi bytes", "a failed read never regenerates or overwrites the key"
    assert not list(tmp_path.glob("*.pem"))
