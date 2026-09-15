"""Bounded pre-boot SQLite backup; never substitutes a graph or reads secrets."""
from contextlib import closing
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid


def backup_saved_journal(database, directory, *, timeout_seconds=2.0):
    """Publish a checked WAL-aware backup, or retain all previous backups.

    A timeout is a deferred backup, not a successful recovery guarantee. The
    caller may provide a longer explicit maintenance budget for large stores.
    """
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 3600:
        raise ValueError("Backup time budget is invalid")
    database, directory = Path(database).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    temporary = None
    def check_budget(*_):
        if time.monotonic() >= deadline:
            raise TimeoutError("Startup backup deferred: time budget exhausted")
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)) as source:
            source.execute("PRAGMA cache_size=-1024")
            # Pin a WAL snapshot so other connections' commits cannot restart
            # each incremental backup step. Keep rollback-journal behavior:
            # a long-lived reader there would delay the active writer.
            pinned = source.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            if pinned:
                source.execute("BEGIN")
                source.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
            page_size = source.execute("PRAGMA page_size").fetchone()[0]
            page_count = source.execute("PRAGMA page_count").fetchone()[0]
            if shutil.disk_usage(directory).free < page_size * page_count + 256 * 1024**2:
                raise OSError("Startup backup deferred: insufficient disk reserve")
            check_budget()
            fd, name = tempfile.mkstemp(prefix=".archhub-backup-", suffix=".part", dir=directory)
            os.close(fd)
            temporary = Path(name)
            with closing(sqlite3.connect(temporary, timeout=0.2)) as destination:
                destination.execute("PRAGMA cache_size=-1024")
                try:
                    source.backup(destination, pages=64, progress=check_budget, sleep=0.01)
                finally:
                    # Release WAL retention before potentially lengthy backup
                    # verification. Earlier failures close the source above.
                    if pinned:
                        source.rollback()
                destination.set_progress_handler(lambda:int(time.monotonic() >= deadline), 1000)
                if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RuntimeError("Startup backup did not pass SQLite quick_check")
                check_budget()
                if destination.execute("SELECT 1 FROM current_cells WHERE cell_id = ? LIMIT 1",
                        ("app:archhub",)).fetchone() is None:
                    raise RuntimeError("Startup backup is missing the application root")
            check_budget()
        target = directory / (database.name + ".snapshot-" + uuid.uuid4().hex + ".sqlite3")
        os.replace(temporary, target)
        temporary = None
        # Only this helper's committed snapshot names are retention candidates.
        # Legacy raw copies and all other recovery files remain untouched.
        pattern = re.compile(re.escape(database.name) + r"\.snapshot-[0-9a-f]{32}\.sqlite3")
        try:
            owned = [path for path in directory.iterdir()
                if pattern.fullmatch(path.name) and not path.is_symlink() and path.is_file()]
            for old in sorted(owned, key=lambda path:path.stat().st_mtime_ns, reverse=True)[2:]:
                if old != target and old.resolve().parent == directory:
                    old.unlink()
        except OSError:
            pass  # A valid new backup remains useful when retention is deferred.
        return target
    finally:
        if temporary is not None:
            original = sys.exception()
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Keep the failure which interrupted backup, with an exact
                # cleanup target for recovery rather than hiding that failure.
                if original is not None:
                    original.add_note("Incomplete backup cleanup failed: " + str(temporary))
                else:
                    raise
