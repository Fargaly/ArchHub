"""Offline fixture generations preserve signed graph and exact history."""
import hashlib
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import declare_definition
from nodelang import unified_authority_runtime as runtime
from nodelang.universal_cell import DatabaseOwnerConflict, InvalidCell


PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw,
)


class Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = PUBLIC

    def sign(self, payload):
        return PRIVATE.sign(payload)


def provider():
    return MemorySigningKeyProvider("boot2-fixture", b"fixture-only-boot2-key-material-00000")


def provision(root):
    return runtime.provision_unified_authority(
        root, provider(), key_id="boot2-fixture", application_label="Fixture",
        principal_label="Fixture owner", bootstrap_session_label="Fixture session",
        bootstrap_session_public_key=PUBLIC, composition_labels=("Brain", "Interface"),
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vacuum_preserves_identity_every_revision_and_kind_counts(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "compacted"
    location = provision(source)
    authority = location.authority
    for index in range(3):
        declare_definition(
            authority, "Fixture definition %d" % index, {"index": index},
            caller=Caller(authority), command_id=str(uuid.uuid4()),
        )
    manifest = authority.manifest.to_json()
    revision = authority.store.revision
    chain = authority.store.revision_chain_digest()
    snapshots = tuple(dict(authority.store.at(r).cells) for r in range(revision + 1))
    before = runtime.authority_generation_census(location)
    authority.store.close()
    database_hash, pointer_hash = digest(location.database_path), digest(source / "CURRENT")
    started = time.perf_counter()
    compacted = runtime.vacuum_authority_fixture(source, destination, provider())
    elapsed = time.perf_counter() - started
    try:
        after = runtime.authority_generation_census(compacted)
        assert compacted.authority.manifest.to_json() == manifest
        assert compacted.authority.store.revision == revision
        assert compacted.authority.store.revision_chain_digest() == chain
        assert before["cell_count"] == after["cell_count"]
        assert before["version_cell_count"] == after["version_cell_count"]
        assert before["atom_shapes"] == after["atom_shapes"]
        assert before["role_counts"] == after["role_counts"]
        assert before["shape_counts"] == after["shape_counts"]
        assert after["free_pages"] == 0
        assert after["page_count"] <= before["page_count"]
        for r, cells in enumerate(snapshots):
            assert dict(compacted.authority.store.at(r).cells) == cells
        assert digest(location.database_path) == database_hash
        assert digest(source / "CURRENT") == pointer_hash
        print("BOOT2_GENERATION " + json.dumps({
            "before": before, "after": after, "vacuum_verify_select_seconds": elapsed,
            "revision": revision, "revision_chain_digest": chain,
        }, sort_keys=True))
    finally:
        compacted.authority.store.close()
    reopened = runtime.open_current_authority(source, provider())
    reopened.authority.store.close()


def test_vacuum_refuses_an_active_source_owner(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "compacted"
    location = provision(source)
    try:
        with pytest.raises(DatabaseOwnerConflict):
            runtime.vacuum_authority_fixture(source, destination, provider())
        assert not destination.exists()
    finally:
        location.authority.store.close()


@pytest.mark.parametrize("destination_name", ["source", "source/nested", "."])
def test_vacuum_refuses_overlapping_roots(tmp_path, destination_name):
    location = provision(tmp_path / "source")
    location.authority.store.close()
    with pytest.raises(InvalidCell, match="disjoint"):
        runtime.vacuum_authority_fixture(tmp_path / "source", tmp_path / destination_name, provider())


def test_vacuum_failed_verification_never_selects_destination(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "compacted"
    location = provision(source)
    location.authority.store.close()
    original = digest(location.database_path)
    wrong = MemorySigningKeyProvider("boot2-fixture", b"different-fixture-key-material-00000")
    with pytest.raises(InvalidCell):
        runtime.vacuum_authority_fixture(source, destination, wrong)
    assert not (destination / "CURRENT").exists()
    assert digest(location.database_path) == original
    reopened = runtime.open_current_authority(source, provider())
    reopened.authority.store.close()


def test_vacuum_atomic_selection_failure_keeps_source_recoverable(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "compacted"
    location = provision(source)
    location.authority.store.close()
    original_atomic = runtime._atomic_text

    def fail_selection(path, value):
        if path == destination / "CURRENT":
            raise OSError("fixture selection interrupted")
        return original_atomic(path, value)

    monkeypatch.setattr(runtime, "_atomic_text", fail_selection)
    with pytest.raises(OSError, match="fixture selection interrupted"):
        runtime.vacuum_authority_fixture(source, destination, provider())
    assert not (destination / "CURRENT").exists()
    reopened = runtime.open_current_authority(source, provider())
    reopened.authority.store.close()
    monkeypatch.setattr(runtime, "_atomic_text", original_atomic)
    recovered = provision(destination)
    try:
        assert recovered.authority.manifest == location.authority.manifest
    finally:
        recovered.authority.store.close()


def test_vacuum_refuses_default_live_runtime_even_when_missing(tmp_path, monkeypatch):
    live = tmp_path / "live"
    monkeypatch.setattr(runtime, "default_runtime_root", lambda: live)
    with pytest.raises(InvalidCell, match="live"):
        runtime.vacuum_authority_fixture(live, tmp_path / "compacted", provider())
    assert not live.exists()
