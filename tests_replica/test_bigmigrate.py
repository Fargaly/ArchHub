"""Large journal courts: fixture profiles only, no installed application."""
from contextlib import contextmanager
from types import SimpleNamespace

from nodelang import persistence
from tests_replica import test_ogboot_upgrade_selection as upgrade_courts
from tests_replica.test_ogboot_upgrade_selection import (
    _selected, _journal, _bytes, _history, _prepare,
)

isolated_profile = upgrade_courts.isolated_profile


def test_progressing_journal_can_exceed_thirty_seconds(isolated_profile, monkeypatch, capsys):
    root = isolated_profile / "ArchHub"
    stale = _selected(root)
    legacy = _journal(isolated_profile / "ArchHub-Test" / "archhub-test.universal.sqlite3",
                      "large", 200, commits=12)
    before, expected = _bytes((stale, legacy)), _history(legacy)
    clock = {"now": 0.0}
    monkeypatch.setattr(persistence, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    original = persistence._application_journal_reader

    @contextmanager
    def slow_reader(path, **kwargs):
        # Every completed SQLite row takes four simulated seconds. Real SQL,
        # copying and readback run unchanged; enough rows cross the old 30s cap.
        with original(path, **kwargs) as database:
            def row_factory(cursor, row):
                clock["now"] += 4.0
                return row
            database.row_factory = row_factory
            yield database

    monkeypatch.setattr(persistence, "_application_journal_reader", slow_reader)
    selected = _prepare(root)
    assert clock["now"] > 30.0
    assert _history(selected) == expected
    assert _bytes((stale, legacy)) == before
    output = capsys.readouterr().out
    assert "Updating your data" in output
    assert "%" in output


def test_indexed_head_read_does_not_scale_with_revision_count(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    path = tmp_path / "head.sqlite3"
    with closing(sqlite3.connect(path)) as database:
        database.execute("CREATE TABLE revisions(revision INTEGER PRIMARY KEY,committed_at REAL)")
        database.executemany("INSERT INTO revisions VALUES(?,?)", ((i, float(i)) for i in range(200_000)))
        database.commit()
    work = []
    original = persistence._application_journal_reader

    @contextmanager
    def measured_reader(path, **kwargs):
        with original(path, **kwargs) as reader:
            reader.set_progress_handler(lambda: (work.append(1), 0)[1], 1)
            yield reader

    monkeypatch.setattr(persistence, "_application_journal_reader", measured_reader)
    assert persistence._journal_head(path) == (199_999.0, 199_999)
    assert len(work) < 100, len(work)


def test_busy_backup_is_a_stall_and_never_renews_progress(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    from nodelang.application_recovery_files import _backup_sqlite
    clock = {"now": 0.0}
    monkeypatch.setattr(persistence, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    observed = []
    budget = persistence._MigrationProgress(1.0, observed.append)

    class Busy:
        def backup(self, target, *, pages, progress, sleep):
            for _ in range(20):
                clock["now"] += 0.2
                progress(sqlite3.SQLITE_BUSY, 100, 100)

    path = tmp_path / "copy.sqlite3"
    path.touch()
    with pytest.raises(TimeoutError, match="no progress"):
        _backup_sqlite(Busy(), path, budget)
    assert observed == []
