"""Court: the relationship-verification memo never outlives its key ring.

cell_identity memoises signed relationship verifications per immutable head so
a BABOOM frame does not re-run ~142 HMACs per revision. A memo keyed only by
the head kept every relationship valid after the key ring was replaced (71
invalid on HEAD, 0 with the memo), and it cached provider transport errors,
which providers report as False, for the whole revision. The memo must follow
the key ring's fingerprint, expire within its TTL for a provider without one,
and never remember a failure.
"""
import secrets
import time
from pathlib import Path

import pytest

import nodelang.cell_identity as cell_identity
from nodelang.application_server import ApplicationServer
from nodelang.cell_identity import verify_relationship_authority_snapshot
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


@pytest.fixture
def authority(tmp_path):
    server = ApplicationServer(
        universal_workspace_root=tmp_path,
        conversation_history_path=tmp_path / "content.sqlite3",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False,
    )
    cell_identity._MATERIAL_MEMO.clear()
    try:
        yield server
    finally:
        cell_identity._MATERIAL_MEMO.clear()
        server.close()


def _verify(server):
    authority = server.universal_registry.authorization
    return verify_relationship_authority_snapshot(
        server.universal_store.snapshot(), authority.identity_protocol,
        authority.relationship_broker)


def _provider(server):
    return server.universal_registry.authorization.relationship_broker._key_provider


def _replace_every_secret(provider):
    held = {key_id: dict(versions) for key_id, versions in provider._keys.items()}
    for key_id, versions in provider._keys.items():
        for version in versions:
            versions[version] = secrets.token_bytes(32)
    return held


def _restore(provider, held):
    for key_id, versions in held.items():
        provider._keys[key_id].update(versions)


def _count_signature_checks(monkeypatch):
    checks = [0]
    broker_class = cell_identity.RelationshipAuthorityBroker
    original = broker_class.verify_signature

    def counted(self, *args, **kwargs):
        checks[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(broker_class, "verify_signature", counted)
    return checks


def test_replacing_the_key_ring_without_a_commit_invalidates_the_memo(authority, monkeypatch):
    checks = _count_signature_checks(monkeypatch)
    first = _verify(authority)
    assert first.active_relationships and not first.invalid_reasons
    signed = checks[0]
    assert signed > 0
    _verify(authority)
    assert checks[0] == signed, "the same head and ring must reuse the memo"
    revision = authority.universal_store.revision
    held = _replace_every_secret(_provider(authority))
    try:
        replaced = _verify(authority)
        assert authority.universal_store.revision == revision
        assert not replaced.active_relationships
        assert set(replaced.invalid_reasons) == set(first.registered_roots)
    finally:
        _restore(_provider(authority), held)
    restored = _verify(authority)
    assert not restored.invalid_reasons
    assert len(restored.active_relationships) == len(first.active_relationships)


def test_a_transient_provider_error_does_not_stick(authority, monkeypatch):
    provider = _provider(authority)
    original = type(provider).verify
    failing = [True]

    def flaky(self, *args, **kwargs):
        if failing[0]:
            return False  # what KMS and DPAPI return for any transport exception
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(provider), "verify", flaky)
    glitched = _verify(authority)
    assert glitched.invalid_reasons and not glitched.active_relationships
    failing[0] = False
    recovered = _verify(authority)
    assert not recovered.invalid_reasons
    assert recovered.active_relationships


class _NoFingerprint:
    """A provider that, like KMS, cannot describe its key ring locally."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name == "key_ring_fingerprint":
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_a_provider_without_a_fingerprint_is_bounded_by_the_ttl(authority, monkeypatch):
    broker = authority.universal_registry.authorization.relationship_broker
    inner = broker._key_provider
    monkeypatch.setattr(broker, "_key_provider", _NoFingerprint(inner))
    clock = [1000.0]
    monkeypatch.setattr(cell_identity.time, "monotonic", lambda: clock[0])
    first = _verify(authority)
    assert first.active_relationships and not first.invalid_reasons
    held = _replace_every_secret(inner)
    try:
        clock[0] += cell_identity._MATERIAL_MEMO_TTL_SECONDS - 1
        assert not _verify(authority).invalid_reasons  # within the TTL
        clock[0] += 2
        expired = _verify(authority)
        assert set(expired.invalid_reasons) == set(first.registered_roots)
    finally:
        _restore(inner, held)
    assert cell_identity._MATERIAL_MEMO_TTL_SECONDS <= 60.0


def test_dpapi_fingerprint_changes_on_rotation_and_replacement(tmp_path):
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    ring = tmp_path / "ring.dpapi.json"
    provider = WindowsDpapiSigningKeyProvider(ring)
    assert provider.key_ring_fingerprint() == (str(Path(ring).resolve()), None)
    provider.current("archhub.local.relationship-authority")
    created = provider.key_ring_fingerprint()
    provider.rotate("archhub.local.relationship-authority")
    rotated = provider.key_ring_fingerprint()
    assert rotated != created and rotated[3] != created[3]
    saved = ring.read_bytes()
    other = WindowsDpapiSigningKeyProvider(tmp_path / "other.dpapi.json")
    other.current("archhub.local.relationship-authority")
    ring.write_bytes((tmp_path / "other.dpapi.json").read_bytes())
    time.sleep(0.01)
    assert provider.key_ring_fingerprint() != rotated
    ring.write_bytes(saved)
