"""Durability and recovery court for the universal-cell physical store."""
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    DatabaseOwnerConflict,
    InvalidCell,
    ReadOnlyJournalError,
    inspect_read_only_cell_journal,
    load_bounded_read_only_cell_snapshot,
    read_only_revision_chain_digest,
)


def _root(atom=b"before"):
    return Cell("root", NULL_CELL_ID, NULL_CELL_ID, atom)


def test_sqlite_wal_reopens_current_and_historical_snapshots(tmp_path: Path):
    path = tmp_path / "cells.sqlite3"
    store = CellStore(path)
    store.commit(store.revision, create=[_root()])
    first = store.revision
    store.commit(first, replace=[_root(b"after")])
    store.close()

    reopened = CellStore(path)
    assert reopened.revision == 2
    assert reopened.read("root").atom == b"after"
    assert reopened.at(first).cells["root"].atom == b"before"
    assert reopened.revisions() == (0, 1, 2)
    reopened.close()


def test_current_cells_index_tracks_the_latest_committed_cells(tmp_path: Path):
    path = tmp_path / "indexed-cells.sqlite3"
    store = CellStore(path)
    try:
        store.commit(store.revision, create=[_root(b"before")])
        store.commit(store.revision, replace=[_root(b"after")])
        indexed = store._journal._connection.execute(
            "SELECT revision, link0, link1, atom FROM current_cells WHERE cell_id=?",
            ("root",),
        ).fetchone()
        assert indexed == (2, NULL_CELL_ID, NULL_CELL_ID, b"after")
    finally:
        store.close()


def test_reopen_backfills_a_missing_current_cells_index_without_a_revision(tmp_path: Path):
    path = tmp_path / "backfill-current-cells.sqlite3"
    store = CellStore(path)
    store.commit(store.revision, create=[_root(b"before")])
    store.commit(store.revision, replace=[_root(b"after")])
    assert store.revision == 2
    store.close()

    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE current_cells")
        connection.commit()
    finally:
        connection.close()

    reopened = CellStore(path)
    try:
        assert reopened.revision == 2
        indexed = reopened._journal._connection.execute(
            "SELECT revision, atom FROM current_cells WHERE cell_id=?", ("root",)
        ).fetchone()
        assert indexed == (2, b"after")
    finally:
        reopened.close()


def test_online_backup_captures_committed_wal_history_without_overwrite(
    tmp_path: Path,
):
    source = CellStore(tmp_path / "live.sqlite3")
    source.commit(source.revision, create=[_root()])
    source.commit(source.revision, replace=[_root(b"after")])
    destination = tmp_path / "backup.sqlite3"
    assert source.backup_to(destination) == str(destination.resolve())

    backup = CellStore(destination)
    assert backup.revision == source.revision == 2
    assert backup.read("root").atom == b"after"
    assert backup.at(1).cells["root"].atom == b"before"
    backup.close()
    with pytest.raises(InvalidCell, match="already exists"):
        source.backup_to(destination)
    source.close()


def test_opaque_atoms_round_trip_all_byte_values(tmp_path: Path):
    path = tmp_path / "bytes.sqlite3"
    payload = bytes(range(256))
    store = CellStore(path)
    store.commit(store.revision, create=[_root(payload)])
    store.close()
    reopened = CellStore(path)
    assert reopened.read("root").atom == payload
    reopened.close()


def test_second_store_cannot_open_an_owned_database(tmp_path: Path):
    path = tmp_path / "concurrent.sqlite3"
    first = CellStore(path)
    # The denial must name WHICH owner holds it. One shared message for a
    # caller reopening its own store and for a genuine external holder is
    # unactionable: a supervisor cannot tell "my bug" from "someone else is
    # serving" and either retries forever or stops a healthy owner.
    with pytest.raises(DatabaseOwnerConflict, match="this same process"):
        CellStore(path)
    first.close()

    second = CellStore(path)
    second.commit(second.revision, create=[_root(b"second")])
    second.close()
    reopened = CellStore(path)
    assert reopened.read("root").atom == b"second"
    reopened.close()


def test_read_only_journal_probe_does_not_open_an_owner_or_write(tmp_path: Path, monkeypatch):
    path = tmp_path / "read-only.sqlite3"
    store = CellStore(path)
    try:
        store.commit(store.revision, create=[_root()])

        def forbidden_owner(*_args, **_kwargs):
            raise AssertionError("read-only probe must not acquire a database owner")

        monkeypatch.setattr(
            "nodelang.universal_cell.InterprocessOwnerFence", forbidden_owner
        )
        observed = inspect_read_only_cell_journal(path)

        assert observed.revision == 1
        assert observed.revision_count == 2
        assert observed.latest_revision_change_count == 1
        store.commit(store.revision, replace=[_root(b"after-read-only-probe")])
        with pytest.raises(ReadOnlyJournalError, match="budget"):
            inspect_read_only_cell_journal(path, max_revisions=1)
    finally:
        store.close()


def test_bounded_read_only_snapshot_never_opens_an_owner(tmp_path: Path, monkeypatch):
    path = tmp_path / "read-only-snapshot.sqlite3"
    store = CellStore(path)
    try:
        store.commit(store.revision, create=[_root(b"snapshot")])

        def forbidden_owner(*_args, **_kwargs):
            raise AssertionError("read-only snapshot must not acquire a database owner")

        monkeypatch.setattr(
            "nodelang.universal_cell.InterprocessOwnerFence", forbidden_owner
        )
        snapshot = load_bounded_read_only_cell_snapshot(path)

        assert snapshot.revision == 1
        assert snapshot.cells["root"].atom == b"snapshot"
        with pytest.raises(ReadOnlyJournalError, match="current-Cell budget"):
            load_bounded_read_only_cell_snapshot(path, max_current_cells=1)
        store.commit(store.revision, replace=[_root(b"still-owned")])
    finally:
        store.close()


def test_read_only_revision_chain_digest_matches_the_owned_journal(tmp_path: Path, monkeypatch):
    path = tmp_path / "read-only-digest.sqlite3"
    store = CellStore(path)
    try:
        store.commit(store.revision, create=[_root(b"first")])
        first = store.revision
        store.commit(store.revision, replace=[_root(b"second")])
        second = store.revision

        def forbidden_owner(*_args, **_kwargs):
            raise AssertionError("read-only digest must not acquire a database owner")

        monkeypatch.setattr(
            "nodelang.universal_cell.InterprocessOwnerFence", forbidden_owner
        )
        assert read_only_revision_chain_digest(path, first) == (
            store.revision_chain_digest(first)
        )
        assert read_only_revision_chain_digest(path, second) == (
            store.revision_chain_digest(second)
        )
        with pytest.raises(ReadOnlyJournalError, match="revision-Cell budget"):
            read_only_revision_chain_digest(path, second, max_revision_cells=1)
    finally:
        store.close()


def test_process_death_releases_database_ownership(tmp_path: Path):
    path = tmp_path / "process-death.sqlite3"
    script = "\n".join((
        "import os, sys",
        "from nodelang.universal_cell import CellStore",
        "store = CellStore(sys.argv[1])",
        "print('READY', flush=True)",
        "sys.stdin.buffer.read()",
        "os._exit(0)",
    ))
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        cwd=Path(__file__).parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "READY"
        with pytest.raises(DatabaseOwnerConflict, match="another live process"):
            CellStore(path)
        child.stdin.close()
        assert child.wait(timeout=10) == 0
        reopened = CellStore(path)
        reopened.close()
    finally:
        if child.poll() is None:
            child.stdin.close()
            child.wait(timeout=10)


def test_distinct_database_owners_can_coexist(tmp_path: Path):
    first = CellStore(tmp_path / "first.sqlite3")
    second = CellStore(tmp_path / "second.sqlite3")
    first.close()
    second.close()


def test_failure_before_sql_commit_recovers_exact_old_snapshot(tmp_path: Path):
    path = tmp_path / "rollback.sqlite3"

    def fail(stage):
        if stage == "before_commit":
            raise RuntimeError("injected interruption")

    store = CellStore(path, fault_injector=fail)
    with pytest.raises(RuntimeError):
        store.commit(store.revision, create=[_root()])
    store.close()
    reopened = CellStore(path)
    assert reopened.revision == 0
    assert set(reopened.snapshot().cells) == {NULL_CELL_ID}
    reopened.close()


def test_failure_after_sql_commit_recovers_complete_new_snapshot(tmp_path: Path):
    path = tmp_path / "committed.sqlite3"

    def fail(stage):
        if stage == "after_commit":
            raise RuntimeError("injected process death")

    store = CellStore(path, fault_injector=fail)
    with pytest.raises(RuntimeError):
        store.commit(store.revision, create=[_root()])
    store.close()
    reopened = CellStore(path)
    assert reopened.revision == 1
    assert reopened.read("root") == _root()
    reopened.close()


def test_durable_history_is_exact_without_a_resident_version_archive(
    tmp_path: Path,
):
    path = tmp_path / "lazy-history.sqlite3"
    memory = CellStore()
    durable = CellStore(path)
    try:
        for store in (memory, durable):
            store.commit(store.revision, create=[_root(b"version-000")])
            for index in range(1, 101):
                store.commit(
                    store.revision,
                    replace=[_root(("version-%03d" % index).encode("ascii"))],
                )
        expected_digest = memory.revision_chain_digest()
        expected_revisions = memory.revisions()
        expected_changes = {
            revision: memory.revision_changes(revision)
            for revision in expected_revisions
        }
    finally:
        durable.close()

    reopened = CellStore(path)
    try:
        assert reopened.revision == memory.revision == 101
        assert reopened.read("root").atom == b"version-100"
        assert reopened.revisions() == expected_revisions
        assert reopened.revision_chain_digest() == expected_digest
        assert {
            revision: reopened.revision_changes(revision)
            for revision in expected_revisions
        } == expected_changes
        for revision in (1, 2, 50, 100):
            assert reopened.at(revision) == memory.at(revision)
            assert reopened.cells_at(revision, ("root",)) == (
                memory.cells_at(revision, ("root",))
            )
        assert reopened.cell_created_revision("root") == 1
        stats = reopened.retention_stats()
        assert stats["revision_count"] == 102
        assert stats["version_cell_count"] == 102
        assert stats["resident_history_version_cell_count"] == 0
        assert stats["historical_snapshot_count"] <= 2
        assert not reopened._versions
        assert reopened._cell_history_index is None
    finally:
        reopened.close()
        memory.close()


def test_sqlite_uses_the_head_bound_reader_not_the_eager_adapter(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "head-reader.sqlite3"
    created = CellStore(path)
    created.commit(created.revision, create=[_root()])
    created.close()

    def forbidden_eager_load(_journal):
        raise AssertionError("built-in SQLite must not materialize durable history")

    monkeypatch.setattr(
        "nodelang.universal_cell._SqliteJournal.load",
        forbidden_eager_load,
    )
    reopened = CellStore(path)
    try:
        assert reopened.revision == 1
        assert reopened.read("root") == _root()
        assert reopened.at(0).cells[NULL_CELL_ID].id == NULL_CELL_ID
    finally:
        reopened.close()


def test_durable_append_advances_the_bound_reader_without_resident_history(
    tmp_path: Path,
):
    store = CellStore(tmp_path / "advance-head.sqlite3")
    try:
        initial = store.revision_chain_digest()
        store.commit(store.revision, create=[_root(b"first")])
        first = store.revision_chain_digest()
        store.commit(store.revision, replace=[_root(b"second")])
        second = store.revision_chain_digest()

        assert len({initial, first, second}) == 3
        assert store.at(1).cells["root"].atom == b"first"
        assert store.cells_at(1, ("root",))["root"].atom == b"first"
        assert store.revision_changes(2) == ("root",)
        assert store.retention_stats()["resident_history_version_cell_count"] == 0
        assert not store._versions
    finally:
        store.close()


def test_forged_sqlite_genesis_is_denied_without_leaking_the_owner_fence(
    tmp_path: Path,
):
    path = tmp_path / "forged-genesis.sqlite3"
    created = CellStore(path)
    created.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE cell_versions SET atom=? WHERE revision=0 AND cell_id=?",
            (b"forged", NULL_CELL_ID),
        )
        connection.execute(
            "UPDATE current_cells SET atom=? WHERE revision=0 AND cell_id=?",
            (b"forged", NULL_CELL_ID),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(InvalidCell, match="genesis"):
        CellStore(path)
    with pytest.raises(InvalidCell, match="genesis"):
        CellStore(path)
