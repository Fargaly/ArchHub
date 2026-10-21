"""Ping review 2026-10-12 (AGENTS T3): the Settings app signing key is never stored in the clear."""
import hashlib
from pathlib import Path
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


def test_default_app_key_lives_under_the_app_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile" / "LocalAppData"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    key_path = roots.default_app_key_path()
    assert key_path == tmp_path / "profile" / "LocalAppData" / "ArchHub" / "governance" / "workspace-roots.app-key.dpapi"


def test_workspace_window_approval_no_longer_opens_cng(monkeypatch):
    from nodelang import workspace_roots_signing as signing

    def refuse(*_args, **_kwargs):
        raise AssertionError("CNG workspace key was opened")

    monkeypatch.setattr(signing, "CngSigner", refuse)
    seen = []
    change = {"action": "register", "id": "alpha", "path": r"C:\alpha",
              "privacy": "private", "profile": "client", "writers": ["codex"]}

    def forward(body):
        seen.append(body)
        return {"forwarded": body}

    assert roots.approve_in_this_window(change, window_handle=1234, forward=forward) == {
        "forwarded": change}
    assert seen == [change]


def test_old_cng_signed_projection_verifies_from_pinned_blob_without_key_store(tmp_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key = ec.generate_private_key(ec.SECP256R1())
    blob = roots.AppWorkspaceRootSigner._public_blob_of(key)
    pin = roots.pin_document(blob, key_id=roots.KEY_ID)
    body = roots.snapshot_body([], hashlib.sha256(blob).hexdigest(), key_id=roots.KEY_ID)
    r, s = decode_dss_signature(key.sign(roots.canonical(body), ec.ECDSA(hashes.SHA256())))
    signature = (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()
    snapshot_path = tmp_path / "workspace-roots.json"
    pin_path = tmp_path / "workspace-roots.pin"
    snapshot_path.write_bytes(roots.canonical({**body, "signature": signature}))
    pin_path.write_bytes(roots.canonical(pin))

    class NoKeyStore:
        def verify_blob(self, *_args, **_kwargs):
            raise AssertionError("key store verifier was used")

    assert roots.verify_projection(body, NoKeyStore(), snapshot_path=snapshot_path,
                                   pin_path=pin_path) == "match"


def test_product_workspace_roots_code_has_no_cng_signer_or_verifier_calls():
    product = Path(__file__).resolve().parents[2] / "01.APP/nodelang" / "workspace_roots_catalogue.py"
    text = product.read_text(encoding="utf-8")
    forbidden = ("CngSigner(", "CngVerifier(", "workspace_roots_signing import Cng")
    assert not [token for token in forbidden if token in text]


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
