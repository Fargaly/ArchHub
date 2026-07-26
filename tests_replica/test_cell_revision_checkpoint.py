"""Courts for the signed external universal-revision checkpoint."""
import json

import pytest

from nodelang.cell_revision_checkpoint import (
    RevisionCheckpointDenied,
    RevisionCheckpointGuard,
    RevisionCheckpointSigningAuthority,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import (
    LocalEd25519KmsProvider,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    project_signing_authority_protocol,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _provider():
    return MemorySigningKeyProvider(
        "archhub.local.universal-checkpoint", b"q" * 32
    )


def _cell(value):
    return Cell("root", NULL_CELL_ID, NULL_CELL_ID, value)


def _v2_authority(tmp_path, *, provider=None, reopen=False):
    path = tmp_path / "checkpoint-authority.sqlite3"
    authority_store = CellStore(path)
    provider = provider or LocalEd25519KmsProvider(
        provider_id="checkpoint-court", authority_id="revision-checkpoint"
    )
    if reopen:
        protocol = project_signing_authority_protocol(
            authority_store.snapshot(), prefix="court:checkpoint-signing"
        )
    else:
        protocol = bootstrap_signing_authority_protocol(
            authority_store, prefix="court:checkpoint-signing"
        )
        build_signing_key_descriptor(
            authority_store,
            protocol,
            provider,
            descriptor_id="court:checkpoint-key:v2",
            resource_version=provider.current_resource,
            authority_id="revision-checkpoint",
            purpose="universal-revision-checkpoint",
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2030-01-01T00:00:00Z",
            authorization_evidence="court:checkpoint-authorization",
            release_evidence="court:checkpoint-release",
        )
    return RevisionCheckpointSigningAuthority(
        authority_store,
        protocol,
        provider,
        "court:checkpoint-key:v2",
        "court:checkpoint-authorization",
    )


def test_checkpoint_follows_durable_commits_and_survives_key_rotation(tmp_path):
    database = tmp_path / "cells.sqlite3"
    checkpoint = tmp_path / "checkpoint.json"
    provider = _provider()
    store = CellStore(database)
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database-a",
        key_provider=provider,
    )
    guard.bind(store)
    store.commit(store.revision, create=(_cell(b"first"),))
    first = json.loads(checkpoint.read_text(encoding="ascii"))
    assert first["revision"] == 1
    provider.rotate(
        "archhub.local.universal-checkpoint", b"r" * 32
    )
    store.commit(store.revision, replace=(_cell(b"second"),))
    second = json.loads(checkpoint.read_text(encoding="ascii"))
    assert second["revision"] == 2
    assert second["key_version"] == 2
    assert b"q" * 32 not in checkpoint.read_bytes()
    assert b"r" * 32 not in checkpoint.read_bytes()
    guard.require_healthy()
    guard.close()
    store.close()

    reopened = CellStore(database)
    restarted = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database-a",
        key_provider=provider,
    )
    restarted.bind(reopened)
    restarted.require_healthy()
    restarted.close()
    reopened.close()


def test_checkpoint_rejects_database_rollback_and_same_revision_tampering(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    provider = _provider()
    current_path = tmp_path / "current.sqlite3"
    current = CellStore(current_path)
    current.commit(current.revision, create=(_cell(b"first"),))
    current.commit(current.revision, replace=(_cell(b"second"),))
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    guard.verify_or_initialize(current)
    current.close()

    old_path = tmp_path / "old.sqlite3"
    old = CellStore(old_path)
    old.commit(old.revision, create=(_cell(b"first"),))
    rollback_guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    with pytest.raises(RevisionCheckpointDenied, match="rolled back"):
        rollback_guard.verify_or_initialize(old)
    old.close()

    alternate_path = tmp_path / "alternate.sqlite3"
    alternate = CellStore(alternate_path)
    alternate.commit(alternate.revision, create=(_cell(b"different"),))
    alternate.commit(alternate.revision, replace=(_cell(b"tampered"),))
    tamper_guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    with pytest.raises(RevisionCheckpointDenied, match="digest"):
        tamper_guard.verify_or_initialize(alternate)
    alternate.close()


def test_trusted_prefix_verification_does_not_sign_an_unverified_new_head(
    tmp_path,
):
    checkpoint = tmp_path / "trusted-prefix.json"
    provider = _provider()
    store = CellStore(tmp_path / "trusted-prefix.sqlite3")
    store.commit(store.revision, create=(_cell(b"anchored"),))
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="trusted-prefix-database",
        key_provider=provider,
    )
    guard.verify_or_initialize(store)
    anchored = checkpoint.read_bytes()
    store.commit(store.revision, replace=(_cell(b"not-yet-admitted"),))

    restarted = RevisionCheckpointGuard(
        checkpoint,
        database_identity="trusted-prefix-database",
        key_provider=provider,
    )
    restarted.verify_trusted_prefix(store)

    assert checkpoint.read_bytes() == anchored
    assert json.loads(anchored)["revision"] == 1
    assert store.revision == 2
    store.close()


def test_checkpoint_tampering_wrong_key_and_disappearance_fail_closed(tmp_path):
    database = tmp_path / "cells.sqlite3"
    checkpoint = tmp_path / "checkpoint.json"
    provider = _provider()
    store = CellStore(database)
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    guard.bind(store)

    value = json.loads(checkpoint.read_text(encoding="ascii"))
    value["revision"] = 99
    checkpoint.write_text(json.dumps(value), encoding="ascii")
    with pytest.raises(RevisionCheckpointDenied, match="signature"):
        guard.verify_or_initialize(store)

    guard.close()
    checkpoint.unlink()
    missing = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    missing.verify_or_initialize(store)
    checkpoint.unlink()
    with pytest.raises(RevisionCheckpointDenied, match="disappeared"):
        missing.verify_or_initialize(store)

    wrong = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=MemorySigningKeyProvider(
            "archhub.local.universal-checkpoint", b"z" * 32
        ),
    )
    # Recreate a valid checkpoint with the original provider first.
    original = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database",
        key_provider=provider,
    )
    original.verify_or_initialize(store)
    with pytest.raises(RevisionCheckpointDenied, match="signature"):
        wrong.verify_or_initialize(store)
    store.close()


def test_v2_checkpoint_uses_graph_envelope_and_survives_restart(tmp_path):
    database = tmp_path / "cells-v2.sqlite3"
    checkpoint = tmp_path / "checkpoint-v2.json"
    authority = _v2_authority(tmp_path)
    store = CellStore(database)
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database-v2",
        signing_authority=authority,
    )
    guard.bind(store)
    store.commit(store.revision, create=(_cell(b"v2-first"),))
    record = json.loads(checkpoint.read_text(encoding="ascii"))

    assert record["format_version"] == 2
    assert "signature" not in record
    assert "key_reference" not in record
    assert record["envelope_root"] in authority.store.snapshot().cells
    guard.require_healthy()
    guard.close()
    store.close()
    provider = authority.provider
    authority.store.close()

    reopened_authority = _v2_authority(
        tmp_path, provider=provider, reopen=True
    )
    reopened = CellStore(database)
    restarted = RevisionCheckpointGuard(
        checkpoint,
        database_identity="logical-database-v2",
        signing_authority=reopened_authority,
    )
    restarted.bind(reopened)
    restarted.require_healthy()
    restarted.close()
    reopened.close()
    reopened_authority.store.close()


def test_checkpoint_migrates_dual_read_and_new_write_without_rewriting_v1(tmp_path):
    database = tmp_path / "migration.sqlite3"
    checkpoint = tmp_path / "migration-checkpoint.json"
    legacy = _provider()
    store = CellStore(database)
    store.commit(store.revision, create=(_cell(b"legacy"),))
    v1 = RevisionCheckpointGuard(
        checkpoint,
        database_identity="migration-database",
        key_provider=legacy,
    )
    v1.verify_or_initialize(store)
    first = checkpoint.read_bytes()
    assert json.loads(first)["format_version"] == 1

    authority = _v2_authority(tmp_path)
    migrating = RevisionCheckpointGuard(
        checkpoint,
        database_identity="migration-database",
        key_provider=legacy,
        signing_authority=authority,
    )
    migrating.bind(store)
    assert checkpoint.read_bytes() == first
    store.commit(store.revision, replace=(_cell(b"v2"),))
    second = json.loads(checkpoint.read_text(encoding="ascii"))

    assert second["format_version"] == 2
    assert second["revision"] == 2
    assert second["envelope_root"] in authority.store.snapshot().cells
    migrating.close()

    # A v2-only runtime cannot silently reinterpret a remaining v1 checkpoint.
    checkpoint.write_bytes(first)
    no_legacy_fallback = RevisionCheckpointGuard(
        checkpoint,
        database_identity="migration-database",
        signing_authority=authority,
    )
    with pytest.raises(RevisionCheckpointDenied, match="legacy"):
        no_legacy_fallback.verify_or_initialize(store)
    store.close()
    authority.store.close()


def test_v2_checkpoint_tampering_and_provider_substitution_fail_closed(tmp_path):
    checkpoint = tmp_path / "tamper-v2.json"
    authority = _v2_authority(tmp_path)
    store = CellStore(tmp_path / "tamper-v2.sqlite3")
    store.commit(store.revision, create=(_cell(b"v2"),))
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="tamper-v2",
        signing_authority=authority,
    )
    guard.verify_or_initialize(store)
    original = checkpoint.read_bytes()
    record = json.loads(original)
    record["revision"] = 99
    checkpoint.write_text(json.dumps(record), encoding="ascii")
    with pytest.raises(RevisionCheckpointDenied, match="signature"):
        guard.verify_or_initialize(store)

    checkpoint.write_bytes(original)
    foreign = LocalEd25519KmsProvider(
        provider_id="checkpoint-court", authority_id="revision-checkpoint"
    )
    wrong_authority = RevisionCheckpointSigningAuthority(
        authority.store,
        authority.protocol,
        foreign,
        authority.descriptor_root,
        authority.authorization_evidence,
    )
    wrong = RevisionCheckpointGuard(
        checkpoint,
        database_identity="tamper-v2",
        signing_authority=wrong_authority,
    )
    with pytest.raises(RevisionCheckpointDenied, match="signature"):
        wrong.verify_or_initialize(store)
    store.close()
    authority.store.close()


def test_v2_checkpoint_requires_the_selected_descriptor(tmp_path):
    checkpoint = tmp_path / "descriptor-substitution.json"
    authority = _v2_authority(tmp_path)
    store = CellStore(tmp_path / "descriptor-substitution.sqlite3")
    store.commit(store.revision, create=(_cell(b"v2"),))
    guard = RevisionCheckpointGuard(
        checkpoint,
        database_identity="descriptor-substitution",
        signing_authority=authority,
    )
    guard.verify_or_initialize(store)

    provider = authority.provider
    provider.rotate()
    substituted = build_signing_key_descriptor(
        authority.store,
        authority.protocol,
        provider,
        descriptor_id="court:checkpoint-key:v3",
        resource_version=provider.current_resource,
        authority_id="revision-checkpoint",
        purpose="universal-revision-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        predecessor_descriptor=authority.descriptor_root,
        authorization_evidence="court:checkpoint-authorization:v3",
        release_evidence="court:checkpoint-release:v3",
    )
    wrong = RevisionCheckpointGuard(
        checkpoint,
        database_identity="descriptor-substitution",
        signing_authority=RevisionCheckpointSigningAuthority(
            authority.store,
            authority.protocol,
            provider,
            substituted,
            "court:checkpoint-authorization:v3",
        ),
    )
    with pytest.raises(RevisionCheckpointDenied, match="signature is invalid"):
        wrong.verify_or_initialize(store)
    store.close()
    authority.store.close()


def test_v2_checkpoint_denies_recursive_authority_store(tmp_path):
    store = CellStore(tmp_path / "same-store.sqlite3")
    protocol = bootstrap_signing_authority_protocol(
        store, prefix="court:same-store-signing"
    )
    provider = LocalEd25519KmsProvider(
        provider_id="same-store", authority_id="checkpoint"
    )
    descriptor = build_signing_key_descriptor(
        store,
        protocol,
        provider,
        descriptor_id="court:same-store-key",
        resource_version=provider.current_resource,
        authority_id="checkpoint",
        purpose="revision-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:authorization",
        release_evidence="court:release",
    )
    authority = RevisionCheckpointSigningAuthority(
        store, protocol, provider, descriptor, "court:authorization"
    )
    guard = RevisionCheckpointGuard(
        tmp_path / "same-store.json",
        database_identity="same-store",
        signing_authority=authority,
    )

    with pytest.raises(RevisionCheckpointDenied, match="separate Cell store"):
        guard.verify_or_initialize(store)
    store.close()
