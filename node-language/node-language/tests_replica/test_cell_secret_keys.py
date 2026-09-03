"""Courts for external signing-key custody and rotation."""
import hashlib
import hmac
import os

import pytest

import nodelang.cell_secret_keys as cell_secret_keys
from nodelang.cell_secret_keys import (
    MemorySigningKeyProvider,
    SigningKeyError,
    SigningKeyReference,
    WindowsDpapiSigningKeyProvider,
)
from nodelang.cell_identity import (
    RelationshipAuthorityBroker,
    bootstrap_identity_protocol,
    grant_authority_relationship,
    verify_authority_relationship,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


class _OpaqueSigningProvider:
    """KMS-shaped test provider: callers can sign, but cannot export keys."""

    def __init__(self) -> None:
        self._keys = {1: b"opaque-provider-key-material-v1"}

    def current_reference(self, key_id: str) -> SigningKeyReference:
        return SigningKeyReference(key_id, 1)

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        return hmac.new(
            self._keys[version], payload, hashlib.sha256
        ).hexdigest()

    def verify(
        self, key_id: str, version: int, payload: bytes, signature: str
    ) -> bool:
        try:
            expected = self.sign(key_id, version, payload)
        except KeyError:
            return False
        return hmac.compare_digest(expected, signature)


def test_memory_key_provider_resolves_old_versions_after_rotation():
    provider = MemorySigningKeyProvider("authority", b"a" * 32)
    first = provider.current("authority")
    second = provider.rotate("authority", b"b" * 32)

    assert (first.version, first.secret) == (1, b"a" * 32)
    assert (second.version, second.secret) == (2, b"b" * 32)
    assert provider.resolve("authority", 1).secret == b"a" * 32
    assert provider.resolve("authority", 2).secret == b"b" * 32
    assert provider.key_fingerprint("authority", 1) != provider.key_fingerprint(
        "authority", 2
    )
    assert provider.key_fingerprint("authority", 1) == MemorySigningKeyProvider(
        "authority", b"a" * 32
    ).key_fingerprint("authority", 1)
    with pytest.raises(SigningKeyError):
        provider.resolve("authority", 3)


def test_relationship_authority_uses_non_exporting_signing_capability():
    provider = _OpaqueSigningProvider()
    assert not hasattr(provider, "current")
    assert not hasattr(provider, "resolve")
    store = CellStore()
    protocol = bootstrap_identity_protocol(store, prefix="opaque:identity")
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        Cell("opaque:admin", NULL_CELL_ID, NULL_CELL_ID, b"admin"),
        Cell("opaque:subject", NULL_CELL_ID, NULL_CELL_ID, b"subject"),
        Cell("opaque:tenant", NULL_CELL_ID, NULL_CELL_ID, b"tenant"),
    ))
    broker = RelationshipAuthorityBroker(
        ("opaque:admin",),
        key_provider=provider,
        key_id="kms:authority",
    )
    handle = broker.mint_from_trusted_administrator("opaque:admin")
    root = grant_authority_relationship(
        store,
        protocol,
        broker,
        handle,
        relationship_id="opaque:membership",
        source_root="opaque:subject",
        target_root="opaque:tenant",
        kind="membership",
        tenant_root="opaque:tenant",
        administrator_root="opaque:admin",
        reason="non-exporting provider court",
    )
    assert verify_authority_relationship(
        store.snapshot(), protocol, broker, root
    ).target_root == "opaque:tenant"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI court")
def test_windows_dpapi_key_ring_reopens_and_rotates_without_plaintext(tmp_path):
    path = tmp_path / "authority.dpapi.json"
    first_provider = WindowsDpapiSigningKeyProvider(path)
    first = first_provider.current("authority")
    assert first.version == 1
    assert first.secret not in path.read_bytes()

    reopened = WindowsDpapiSigningKeyProvider(path)
    assert reopened.current("authority") == first
    assert reopened.key_fingerprint("authority", 1) == first_provider.key_fingerprint(
        "authority", 1
    )
    second = reopened.rotate("authority")
    assert second.version == 2
    assert second.secret != first.secret
    assert reopened.resolve("authority", 1) == first
    assert reopened.resolve("authority", 2) == second
    payload = path.read_bytes()
    assert first.secret not in payload
    assert second.secret not in payload


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI court")
def test_windows_dpapi_key_provider_caches_repeated_verification_material(
    tmp_path, monkeypatch
):
    path = tmp_path / "authority.dpapi.json"
    provider = WindowsDpapiSigningKeyProvider(path)
    provider.current("authority")
    payload = b"relationship authority payload"

    decrypts = {"count": 0}
    original = cell_secret_keys._windows_dpapi

    def counted_dpapi(raw, entropy, *, protect):
        if not protect:
            decrypts["count"] += 1
        return original(raw, entropy, protect=protect)

    monkeypatch.setattr(cell_secret_keys, "_windows_dpapi", counted_dpapi)

    signature = provider.sign("authority", 1, payload)
    for _ in range(10):
        assert provider.verify("authority", 1, payload, signature)

    assert decrypts["count"] == 0
