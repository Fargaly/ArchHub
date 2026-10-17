"""Independent hard-stop courts; every process/profile belongs to tmp_path."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import pytest

from nodelang import backup_retention, persistence
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID, _SqliteJournal
from tests_replica import test_ogboot_upgrade_selection as upgrade_courts
from tests_replica.test_ogboot_upgrade_selection import (
    _selected, _journal, _bytes, _history, _prepare,
)

isolated_profile = upgrade_courts.isolated_profile


_CHILD = r'''
from pathlib import Path
import json
import sys
import threading
from nodelang import (backup_retention, persistence, application_recovery_files,
                      application_recovery_restore_files)
root, marker, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
backup_retention.backup_policy = lambda *_: {"keep_count": 3, "max_bytes": int(sys.argv[4])}
def stopped(value):
    marker.write_text(str(value), encoding="utf-8")
    threading.Event().wait()
if mode == "pages":
    original_backup = application_recovery_files._backup_sqlite
    def pausing_backup(source, path, check_budget):
        class ObservedWork:
            def __call__(self):
                check_budget()
            def advance(self, stage, completed=None, total=None):
                check_budget.advance(stage, completed, total)
                if stage == "Copying journal pages" and 512 <= completed < total:
                    stopped(json.dumps({"completed": completed, "total": total, "path": str(path)}))
        return original_backup(source, path, ObservedWork())
    application_recovery_files._backup_sqlite = pausing_backup
if mode == "published":
    def stop_before_restore(recovery, *args, **kwargs):
        stopped(recovery)
    application_recovery_restore_files.prepare_application_restore = stop_before_restore
persistence.prepare_application_database(root, persistence.application_database_path(root),
                                         on_progress=lambda status: None)
raise AssertionError("court did not reach its interruption boundary")
'''


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


def _kill_at_boundary(root, marker, mode, budget):
    log_path = marker.with_suffix(".log")
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(root), str(marker), mode, str(budget)],
            cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=os.environ.copy())
        try:
            deadline = time.monotonic() + 60
            while not marker.exists():
                assert process.poll() is None, log_path.read_text(encoding="utf-8", errors="replace")
                assert time.monotonic() < deadline, "owned child never reached interruption boundary"
                time.sleep(0.02)
            process.kill()
            process.wait(timeout=10)
            assert process.returncode != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def test_hard_kill_during_page_copy_restarts_with_one_copy_budget(isolated_profile, monkeypatch, tmp_path):
    root, stale, legacy, budget = _fixture(isolated_profile)
    monkeypatch.setattr(backup_retention, "backup_policy", lambda *_: {"keep_count": 3, "max_bytes": budget})
    current = root / "unified-authority" / "CURRENT"
    pointer, before, expected = current.read_bytes(), _bytes((stale, legacy)), _history(legacy)
    marker = tmp_path / "copy-paused"
    _kill_at_boundary(root, marker, "pages", budget)
    paused = json.loads(marker.read_text(encoding="utf-8"))
    assert 0 < paused["completed"] < paused["total"]
    abandoned = Path(paused["path"]).parent
    assert abandoned.is_dir()
    assert current.read_bytes() == pointer
    assert persistence.application_database_path(root) == stale.resolve()
    assert _bytes((stale, legacy)) == before
    selected = _prepare(root)
    assert _history(selected) == expected
    assert _bytes((stale, legacy)) == before
    assert selected != stale.resolve()
    assert not abandoned.exists(), "retry must reclaim its abandoned migration-only stage"


def test_hard_kill_after_publication_reuses_verified_backup(isolated_profile, monkeypatch, tmp_path):
    from nodelang import application_recovery_files
    root, stale, legacy, budget = _fixture(isolated_profile)
    monkeypatch.setattr(backup_retention, "backup_policy", lambda *_: {"keep_count": 3, "max_bytes": budget})
    current = root / "unified-authority" / "CURRENT"
    pointer, before, expected = current.read_bytes(), _bytes((stale, legacy)), _history(legacy)
    marker = tmp_path / "published-paused"
    _kill_at_boundary(root, marker, "published", budget)
    backup = Path(marker.read_text(encoding="utf-8"))
    assert backup.parent == root / "backups"
    assert (backup / "recovery.json").is_file()
    backup_bytes = _bytes((backup / "graph.sqlite3", backup / "recovery.json"))
    assert current.read_bytes() == pointer
    assert _bytes((stale, legacy)) == before

    def no_second_backup(*_args, **_kwargs):
        raise AssertionError("retry must restore the verified published backup, not copy another")

    monkeypatch.setattr(application_recovery_files, "_backup_sqlite", no_second_backup)
    selected = _prepare(root)
    assert _history(selected) == expected
    assert _bytes((stale, legacy)) == before
    assert _bytes((backup / "graph.sqlite3", backup / "recovery.json")) == backup_bytes
    receipt = json.loads((selected.parent / "migration.json").read_text(encoding="utf-8"))
    assert Path(receipt["backup_path"]) == backup
    assert [path for path in (root / "backups").iterdir() if path.name.startswith("journal-migration-")] == [backup]


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
    expected = _history(legacy)
    published = _prepare(root)
    assert _history(published) == expected
    current = root / "unified-authority" / "CURRENT"
    # Simulate a real rollback after successful publication, all within this
    # fixture. An unselected UUID generation remains retained application data.
    current.write_text(stale.parent.name, encoding="ascii")
    before = _bytes((stale, legacy, published, published.parent / "migration.json"))
    original_unlink = Path.unlink

    def protect_published(path, *args, **kwargs):
        assert path.parent != published.parent, "retry must never delete a previously published generation"
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", protect_published)
    selected = _prepare(root)
    assert _history(selected) == expected
    assert _bytes((stale, legacy, published, published.parent / "migration.json")) == before


def test_alias_ancestor_is_refused_before_any_migration_cleanup(isolated_profile, tmp_path):
    root, stale, legacy, _budget = _fixture(isolated_profile)
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
            persistence._discard_migration_stage(alias / stage.name, {payload.name}, lambda: None)
        assert payload.read_bytes() == before
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


@pytest.mark.parametrize("unrelated_file", [False, True])
def test_retry_reclaims_only_owned_atomic_and_accelerator_remnants(isolated_profile, unrelated_file):
    root, stale, legacy, _budget = _fixture(isolated_profile)
    current = root / "unified-authority" / "CURRENT"
    pointer, source_bytes, expected = current.read_bytes(), _bytes((stale, legacy)), _history(legacy)
    staging_id = uuid.uuid5(uuid.NAMESPACE_URL, 'archhub-journal-migration:' +
        str(legacy.resolve()) + ':' + repr(persistence._journal_head(legacy))).hex
    prepared = stale.parent.parent / ('.journal-migration-prepared-' + staging_id)
    prepared.mkdir()
    remnants = {
        'authority.sqlite3': b'interrupted private preparation',
        'authority.sqlite3.accelerators-journal': b'interrupted private proof cache',
        '.adoption.json.' + '0' * 32 + '.tmp': b'partial atomic adoption manifest',
        '.migration.json.' + 'f' * 32 + '.tmp': b'partial atomic migration manifest',
    }
    if unrelated_file:
        remnants['unrelated-user-notes.txt'] = b'unknown files must never be deleted'
    for name, data in remnants.items():
        (prepared / name).write_bytes(data)

    if unrelated_file:
        with pytest.raises(ValueError, match="unknown files"):
            _prepare(root)
        assert {path.name: path.read_bytes() for path in prepared.iterdir()} == remnants
        assert current.read_bytes() == pointer
        assert persistence.application_database_path(root) == stale.resolve()
    else:
        selected = _prepare(root)
        assert _history(selected) == expected
        assert selected != stale.resolve()
        assert not prepared.exists(), "owned unselectable preparation must be reclaimed on retry"
    assert _bytes((stale, legacy)) == source_bytes
