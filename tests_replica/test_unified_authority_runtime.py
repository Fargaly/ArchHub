from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import declare_definition
from nodelang.unified_authority_runtime import (
    open_current_authority,
    provision_unified_authority,
)
from nodelang.universal_cell import DatabaseOwnerConflict, InvalidCell


SECRET = b"archhub-clean-runtime-test-key" + b"0" * 8
CALLER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
CALLER_PUBLIC = CALLER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = CALLER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return CALLER_PRIVATE.sign(payload)


def _provider():
    return MemorySigningKeyProvider("clean-runtime", SECRET)


def _provision(root):
    return provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
    )


def test_provision_selects_one_complete_generation_and_reuses_it(tmp_path):
    first = _provision(tmp_path / "runtime")
    graph_id = first.authority.manifest.graph_id
    database = first.database_path
    manifest = first.manifest_path
    first.authority.store.close()

    second = _provision(tmp_path / "runtime")
    try:
        assert second.authority.manifest.graph_id == graph_id
        assert second.database_path == database
        assert second.manifest_path == manifest
        generations = tuple(
            item for item in (tmp_path / "runtime" / "generations").iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )
        assert len(generations) == 1
        assert (tmp_path / "runtime" / "CURRENT").read_text() == graph_id
    finally:
        second.authority.store.close()


def test_concurrent_provisioning_never_mints_two_graph_roots(tmp_path):
    root = tmp_path / "runtime"
    start = threading.Barrier(2)

    def provision_once():
        start.wait(timeout=10)
        try:
            location = _provision(root)
        except DatabaseOwnerConflict:
            return "active-owner", None
        try:
            return "opened", location.authority.manifest.graph_id
        finally:
            location.authority.store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: provision_once(), range(2)))

    graph_ids = {graph_id for _, graph_id in results if graph_id is not None}
    assert len(graph_ids) == 1
    assert {status for status, _ in results} <= {"opened", "active-owner"}
    current = open_current_authority(root, _provider())
    try:
        assert current.authority.manifest.graph_id == next(iter(graph_ids))
        generations = tuple(
            candidate
            for candidate in (root / "generations").iterdir()
            if candidate.is_dir() and not candidate.name.startswith(".")
        )
        assert len(generations) == 1
    finally:
        current.authority.store.close()


def test_current_pointer_fails_closed_on_escape_or_unknown_generation(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "CURRENT").write_text("../outside", encoding="ascii")
    with pytest.raises(InvalidCell, match="pointer"):
        open_current_authority(root, _provider())

    (root / "CURRENT").write_text(str(uuid.uuid4()), encoding="ascii")
    with pytest.raises(InvalidCell, match="incomplete"):
        open_current_authority(root, _provider())


def test_complete_unselected_generation_is_recovered_without_duplication(tmp_path):
    root = tmp_path / "runtime"
    first = _provision(root)
    graph_id = first.authority.manifest.graph_id
    first.authority.store.close()
    (root / "CURRENT").unlink()

    recovered = _provision(root)
    try:
        assert recovered.authority.manifest.graph_id == graph_id
        assert (root / "CURRENT").read_text() == graph_id
        generations = tuple(
            item for item in (root / "generations").iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )
        assert len(generations) == 1
    finally:
        recovered.authority.store.close()


def test_invalid_generation_is_preserved_and_replaced_only_by_exact_identity(tmp_path):
    root = tmp_path / "runtime"
    first = _provision(root)
    old_graph_id = first.authority.manifest.graph_id
    old_generation = first.generation_root
    first.authority.store.close()
    (old_generation / "bootstrap.json").write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidCell):
        _provision(root)
    with pytest.raises(InvalidCell, match="changed before replacement"):
        provision_unified_authority(
            root,
            _provider(),
            key_id="clean-runtime",
            application_label="ArchHub",
            principal_label="Founder",
            bootstrap_session_label="Runtime test session",
            bootstrap_session_public_key=CALLER_PUBLIC,
            composition_labels=("Brain", "Projects", "Interface"),
            replace_invalid_current=str(uuid.uuid4()),
        )

    replacement = provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
        replace_invalid_current=old_graph_id,
    )
    try:
        assert replacement.authority.manifest.graph_id != old_graph_id
        assert old_generation.is_dir()
        assert (root / "CURRENT").read_text() == replacement.authority.manifest.graph_id
    finally:
        replacement.authority.store.close()


def test_staged_initializer_must_pass_before_current_pointer_changes(tmp_path):
    root = tmp_path / "runtime"
    created: list[str] = []

    def fail_after_write(authority):
        declare_definition(
            authority,
            "Rejected staged definition",
            {"state": "candidate"},
            caller=_Caller(authority),
            command_id="7029117e-d38a-4fe4-b0f6-9c4207de0b15",
        )
        raise RuntimeError("initializer court failure")

    with pytest.raises(RuntimeError, match="initializer court failure"):
        provision_unified_authority(
            root,
            _provider(),
            key_id="clean-runtime",
            application_label="ArchHub",
            principal_label="Founder",
            bootstrap_session_label="Runtime test session",
            bootstrap_session_public_key=CALLER_PUBLIC,
            composition_labels=("Brain", "Projects", "Interface"),
            initialize=fail_after_write,
        )
    assert not (root / "CURRENT").exists()

    def pass_initializer(authority):
        result = declare_definition(
            authority,
            "Accepted staged definition",
            {"state": "accepted"},
            caller=_Caller(authority),
            command_id="bbe1ab26-689c-4c18-9e23-41f08f884d4a",
        )
        created.append(result.root_id)

    accepted = provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
        initialize=pass_initializer,
    )
    try:
        assert len(created) == 1
        assert created[0] in accepted.authority.store.snapshot().cells
        assert (root / "CURRENT").read_text() == accepted.authority.manifest.graph_id
    finally:
        accepted.authority.store.close()


def _boot_proof(location):
    import json

    return json.loads(
        (location.generation_root / "accepted-proof.json").read_text(encoding="utf-8")
    )


def test_boot_proof_records_the_audited_head_and_reuses_it(tmp_path):
    """Opening twice must not re-audit a history that did not move."""
    root = tmp_path / "runtime"
    provisioned = _provision(root)
    provisioned.authority.store.close()

    first = open_current_authority(root, _provider())
    revision = first.authority.store.snapshot().revision
    first.authority.store.close()
    recorded = _boot_proof(first)
    assert recorded["head"].startswith("head:%d:" % revision)
    # The prefix is named by what its rows say, not only by how many there
    # are, so a history rewritten in place cannot pass for the one that
    # was audited.
    assert len(recorded["head"].split(":")) == 5
    # The digest names its formula: the chained prefix ("v2-" + 64 hex)
    # costs only the rows since the last recorded link at the next boot.
    digest_part = recorded["head"].split(":")[4]
    assert digest_part.startswith("v2-") and len(digest_part) == 3 + 64

    second = open_current_authority(root, _provider())
    try:
        assert _boot_proof(second)["head"] == recorded["head"]
    finally:
        second.authority.store.close()


def test_boot_proof_is_refused_when_stored_history_is_rewritten(tmp_path):
    """A rewritten history must not inherit the proof of the one it replaced.

    Loading cross-checks the version journal against the current-cell
    index, so a tamper in one table alone is caught before any proof is
    consulted. A tamper written consistently to both passes that check,
    and from there the only thing standing between the graph and a
    rewritten history is the verification the proof lets us skip.

    Rewriting in place leaves the row count and the newest row exactly as
    they were. A proof naming the prefix by those two numbers matches the
    forgery, skips the verification, and the graph opens as trusted -- so
    the recorded prefix is named by what its rows say.
    """
    import sqlite3

    root = tmp_path / "runtime"
    provisioned = _provision(root)
    provisioned.authority.store.close()

    first = open_current_authority(root, _provider())
    database = first.database_path
    first.authority.store.close()

    connection = sqlite3.connect(database)
    try:
        before = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions"
        ).fetchone()
        target = connection.execute(
            "SELECT cell_id, revision, atom FROM current_cells"
            " WHERE atom IS NOT NULL AND LENGTH(atom) > 4"
            " ORDER BY cell_id LIMIT 1"
        ).fetchone()
        assert target is not None
        cell_id, revision, atom = target
        forged = bytes([atom[0] ^ 0x01]) + atom[1:]
        # A real attacker with raw file access removes the append-only
        # fence first; the store must still catch the rewrite by re-hashing.
        for trigger in (
            "cell_versions_append_only_update",
            "cell_versions_append_only_delete",
            "revisions_append_only_update",
            "revisions_append_only_delete",
        ):
            connection.execute("DROP TRIGGER IF EXISTS %s" % trigger)
        connection.execute(
            "UPDATE cell_versions SET atom = ?"
            " WHERE cell_id = ? AND revision = ?",
            (forged, cell_id, revision),
        )
        connection.execute(
            "UPDATE current_cells SET atom = ? WHERE cell_id = ?",
            (forged, cell_id),
        )
        connection.commit()
        after = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions"
        ).fetchone()
    finally:
        connection.close()
    assert before == after, "the rewrite must leave count and newest row alone"

    with pytest.raises(InvalidCell):
        reopened = open_current_authority(root, _provider())
        reopened.authority.store.close()


def test_boot_audit_still_catches_a_rewrite_above_the_accepted_revision(tmp_path):
    """The signed-history walk, not only the accepted digest, must bite.

    A rewrite inside the accepted prefix is caught by the bootstrap digest
    before the walk runs, which makes it a poor witness for the walk. This
    tampers with a cell written after the accepted revision, where the only
    thing that can notice is the audit of the signed head chain -- the same
    audit that now reads its revisions one named cell at a time.
    """
    import sqlite3

    root = tmp_path / "runtime"
    provisioned = _provision(root)
    accepted = provisioned.authority.manifest.accepted_revision
    declared = declare_definition(
        provisioned.authority,
        "Definition written after bootstrap",
        {"state": "candidate"},
        caller=_Caller(provisioned.authority),
        command_id="0f1d0a7c-2b52-4c0e-9f2c-1d4b6b7a9c31",
    )
    provisioned.authority.store.close()

    first = open_current_authority(root, _provider())
    database = first.database_path
    assert first.authority.store.snapshot().revision > accepted
    first.authority.store.close()

    connection = sqlite3.connect(database)
    try:
        target = connection.execute(
            "SELECT cell_id, revision, atom FROM cell_versions"
            " WHERE revision > ? AND atom IS NOT NULL AND LENGTH(atom) > 4"
            " ORDER BY rowid DESC LIMIT 1",
            (accepted,),
        ).fetchone()
        assert target is not None, "nothing was written above the accepted revision"
        cell_id, revision, atom = target
        forged = bytes([atom[0] ^ 0x01]) + atom[1:]
        # A real attacker with raw file access removes the append-only
        # fence first; the store must still catch the rewrite by re-hashing.
        for trigger in (
            "cell_versions_append_only_update",
            "cell_versions_append_only_delete",
            "revisions_append_only_update",
            "revisions_append_only_delete",
        ):
            connection.execute("DROP TRIGGER IF EXISTS %s" % trigger)
        connection.execute(
            "UPDATE cell_versions SET atom = ?"
            " WHERE cell_id = ? AND revision = ?",
            (forged, cell_id, revision),
        )
        connection.execute(
            "UPDATE current_cells SET atom = ? WHERE cell_id = ?",
            (forged, cell_id),
        )
        connection.commit()
    finally:
        connection.close()
    assert declared.root_id

    with pytest.raises(InvalidCell):
        reopened = open_current_authority(root, _provider())
        reopened.authority.store.close()
