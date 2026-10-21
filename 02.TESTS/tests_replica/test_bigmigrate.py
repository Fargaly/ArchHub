"""Large journal courts: fixture profiles only, no installed application."""
from contextlib import contextmanager
from types import SimpleNamespace

from nodelang import persistence
from tests_replica import test_ogboot_upgrade_selection as upgrade_courts

isolated_profile = upgrade_courts.isolated_profile


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
