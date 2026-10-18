"""Independent hard-stop courts; every process/profile belongs to tmp_path."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from nodelang import persistence
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID, _SqliteJournal
from tests_replica import test_ogboot_upgrade_selection as upgrade_courts
from tests_replica.test_ogboot_upgrade_selection import (
    _selected, _journal, _bytes, _history, _prepare, _closed_backup,
)

isolated_profile = upgrade_courts.isolated_profile


def _fixture(local):
    root = local / "ArchHub"
    stale = _selected(root)
    legacy = _journal(local / "ArchHub-Test" / "archhub-test.universal.sqlite3", "legacy", 200)
    # A real page copy, larger than the copier's 64-page batch/cache. Keep the
    # append-only schema and head/history correspondence; no synthetic padding.
    with closing(sqlite3.connect(legacy, isolation_level=None)) as database:
        revision = database.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] + 1
        database.execute("BEGIN IMMEDIATE")
        database.execute("INSERT INTO revisions VALUES (?,?)", (revision, 300))
        values = (revision, "work:payload", NULL_CELL_ID, NULL_CELL_ID, b"x" * (2 * 1024**2))
        database.execute("INSERT INTO cell_versions VALUES (?,?,?,?,?)", values)
        database.execute("INSERT INTO current_cells VALUES (?,?,?,?,?)",
                         (values[1], values[0], *values[2:]))
        database.execute("COMMIT")
        database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    budget = legacy.stat().st_size + 128 * 1024 + 4096
    assert budget < 2 * legacy.stat().st_size
    return root, stale, legacy, budget


def test_journal_constructor_index_work_reports_progress(isolated_profile):
    path = _journal(isolated_profile / "constructor.sqlite3", "legacy", 200)
    with CellStore(path) as store:
        store.commit(store.revision, create=tuple(
            Cell("work:index:" + str(index), NULL_CELL_ID, NULL_CELL_ID, b"value")
            for index in range(2048)))
    with closing(sqlite3.connect(path)) as database:
        database.execute("DROP INDEX idx_current_cells_revision")
    calls = []

    def progress():
        calls.append(1)
        return 0

    journal = _SqliteJournal(path, None, progress_handler=progress)
    try:
        assert calls, "constructor's index work must be observable before it returns"
    finally:
        journal.close()


def test_rollback_does_not_delete_a_previously_published_generation(isolated_profile, monkeypatch):
    root, stale, legacy, _budget = _fixture(isolated_profile)
    _closed_backup(legacy)
    expected = _history(legacy)
    published = _prepare(root)
    assert _history(published) == expected
    current = root / "unified-authority" / "CURRENT"
    generation = root / "unified-authority/generations" / current.read_text().strip()
    # Simulate a real rollback after successful publication, all within this
    # fixture. An unselected UUID generation remains retained application data.
    current.write_text(stale.parent.name, encoding="ascii")
    before = _bytes((stale, legacy, published, generation / "migration.json"))
    locator = Path(str(published) + ".adoption.json")
    before.pop(str(locator))  # The selection locator follows the new CURRENT.
    original_unlink = Path.unlink

    def protect_published(path, *args, **kwargs):
        assert path != published and not path.is_relative_to(generation), "retry must never delete published journal or generation metadata"
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", protect_published)
    selected = _prepare(root)
    assert _history(selected) == expected
    after = _bytes((stale, legacy, published, generation / "migration.json"))
    after.pop(str(locator))
    assert after == before
    selection = root / "unified-authority/generations" / current.read_text().strip()
    assert (published.parent / json.loads(locator.read_text())["generation_relative_path"]).resolve() == selection


def test_alias_ancestor_is_refused_before_any_migration_cleanup(isolated_profile, tmp_path):
    root, stale, legacy, _budget = _fixture(isolated_profile)
    _closed_backup(legacy)
    real_backups = tmp_path / "real-backups"
    stage = real_backups / ".journal-migration-copy-owned"
    stage.mkdir(parents=True)
    payload = stage / "graph.sqlite3"
    payload.write_bytes(b"owned fixture bytes must survive an aliased parent")
    alias = root / "backups"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(real_backups)],
            text=True, capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        alias.symlink_to(real_backups, target_is_directory=True)
    before, pointer = payload.read_bytes(), (root / "unified-authority" / "CURRENT").read_bytes()
    source_bytes = _bytes((stale, legacy))
    try:
        with pytest.raises(ValueError, match="alias"):
            _prepare(root)
        assert payload.read_bytes() == before
        assert (root / "unified-authority" / "CURRENT").read_bytes() == pointer
        assert _bytes((stale, legacy)) == source_bytes
    finally:
        # Remove only the junction/symlink itself, never traverse its target.
        if os.name == "nt":
            alias.rmdir()
        else:
            alias.unlink()


def test_constructor_sqlite_interrupt_preserves_clear_stall_message(tmp_path, monkeypatch):
    from nodelang import universal_cell
    now = {"seconds": 0.0}
    monkeypatch.setattr(persistence, "time", SimpleNamespace(monotonic=lambda: now["seconds"]))
    lease = persistence._MigrationProgress(1.0, None)

    def stalled_constructor(*_args, progress_handler, **_kwargs):
        now["seconds"] = 2.0
        try:
            progress_handler()
        except TimeoutError:
            # sqlite3 turns exceptions from a progress handler into INTERRUPT.
            raise sqlite3.OperationalError("interrupted") from None
        raise AssertionError("the migration lease should have expired")

    monkeypatch.setattr(universal_cell, "_SqliteJournal", stalled_constructor)
    with pytest.raises(TimeoutError, match="no progress.*saved graph kept in place"):
        with persistence._migration_store(tmp_path / "not-created.sqlite3", lease):
            pytest.fail("constructor stall must refuse before admitting a store")
    assert not (tmp_path / "not-created.sqlite3").exists()
