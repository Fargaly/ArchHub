"""Real SQLite and Windows holder behavior, exclusively on synthetic profiles."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from nodelang import application_recovery_files as files


def journal(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE work (id INTEGER PRIMARY KEY, value BLOB)')
        db.executemany('INSERT INTO work VALUES (?, ?)', [(i, ('saved-' + str(i)).encode()) for i in range(40)])
        db.commit()
    return path


def identity(path):
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute('SELECT * FROM work ORDER BY id').fetchall()
    return len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()


@pytest.fixture(autouse=True)
def only_fixture_disks(monkeypatch):
    monkeypatch.setattr(files, '_fixed_backup_drives', lambda: [])


def test_empty_unheld_wal_and_truncate_journal_are_not_live_writers(tmp_path):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    Path(str(source) + '-wal').touch()
    Path(str(source) + '-journal').touch()
    before = identity(source)
    assert Path(str(source) + '-wal').exists()
    completed = files.preserve_closed_application_journals(tmp_path, 'same-build', close_writers=True)
    assert identity(source) == before
    assert identity(Path(completed[0]) / source.name) == before
    assert files.preserve_closed_application_journals(tmp_path, 'same-build', close_writers=True) == completed
    assert len(list(tmp_path.rglob('*-closed'))) == 1


def test_crashed_wal_and_all_companions_fold_without_row_loss(tmp_path):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    companions = [journal(Path(str(source) + suffix)) for suffix in ('.conversations.sqlite3', '.accelerators')]
    code = """
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('INSERT INTO work VALUES (99, zeroblob(300000))'); c.commit(); os._exit(0)
"""
    for path in [source, *companions]:
        subprocess.run([sys.executable, '-B', '-c', code, str(path)], check=True)
        assert Path(str(path) + '-wal').stat().st_size > 0
    # Read logically through WAL without causing the last writer's cleanup.
    readers = [sqlite3.connect(p.as_uri() + '?mode=ro', uri=True) for p in [source, *companions]]
    before = [identity(p) for p in [source, *companions]]
    for reader in readers:
        reader.close()
    result = files.preserve_closed_application_journals(tmp_path, 'wal-shape', close_writers=True)
    assert [identity(p) for p in [source, *companions]] == before
    assert identity(Path(result[0]) / source.name) == before[0]
    assert identity(Path(result[0]) / companions[0].name) == before[1]
    assert all(not Path(str(p) + '-wal').exists() or Path(str(p) + '-wal').stat().st_size == 0 for p in [source, *companions])


def test_same_build_with_new_rows_keeps_original_and_creates_verified_copy(tmp_path):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    first = Path(files.preserve_closed_application_journals(tmp_path, 'same-build', close_writers=True)[0])
    original = identity(first / source.name)
    with closing(sqlite3.connect(source)) as db:
        db.execute("INSERT INTO work VALUES (99, 'new saved work')")
        db.commit()
    second = Path(files.preserve_closed_application_journals(tmp_path, 'same-build', close_writers=True)[0])
    assert first != second and identity(first / source.name) == original
    assert identity(second / source.name) == identity(source)


def test_crashed_rollback_transaction_recovers_committed_rows(tmp_path):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    before = identity(source)
    code = """
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA cache_size=1');c.execute('BEGIN IMMEDIATE')
c.execute('INSERT INTO work VALUES (99,zeroblob(1000000))');os._exit(0)
"""
    subprocess.run([sys.executable, '-B', '-c', code, str(source)], check=True)
    assert Path(str(source) + '-journal').stat().st_size > 0
    completed = files.preserve_closed_application_journals(tmp_path, 'rollback', close_writers=True)
    assert identity(source) == before
    assert identity(Path(completed[0]) / source.name) == before


def test_reopened_writer_cannot_change_a_leased_backup(tmp_path, monkeypatch):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    before = identity(source)
    copy = files._copy_closed_file
    attempted = []
    def copy_with_reopen(original, destination, report):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);c.execute(\"INSERT INTO work VALUES(99,'respawned')\");c.commit()", str(source)],
            capture_output=True, text=True, timeout=10)
        attempted.append(result.returncode)
        assert result.returncode != 0
        copy(original, destination, report)
    monkeypatch.setattr(files, '_copy_closed_file', copy_with_reopen)
    completed = files.preserve_closed_application_journals(tmp_path, 'respawn', close_writers=True)
    assert attempted and identity(source) == before
    assert identity(Path(completed[0]) / source.name) == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows Restart Manager integration')
def test_unknown_live_writer_is_named_and_not_terminated(tmp_path):
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    marker = tmp_path / 'ready'
    child = subprocess.Popen([sys.executable, '-B', '-c',
        "import os,sqlite3,sys,time,pathlib;c=sqlite3.connect(sys.argv[1]);c.execute('BEGIN IMMEDIATE');pathlib.Path(sys.argv[2]).write_text(str(os.getpid()));time.sleep(120)",
        str(source), str(marker)], executable=sys._base_executable)
    try:
        wait_for(marker, child)
        with pytest.raises((OSError, ValueError), match=marker.read_text()):
            files.preserve_closed_application_journals(tmp_path, 'held', close_writers=True)
        assert child.poll() is None
        assert not list(tmp_path.rglob('*-closed'))
    finally:
        child.terminate()
        child.wait(10)


def wait_for(marker, child):
    deadline = time.monotonic() + 20
    while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), 'synthetic holder failed to start'


def mcp_holder(profile, source):
    app = profile / 'ArchHub'
    subprocess.run([sys.executable, '-B', '-m', 'venv', '--without-pip', str(app / '.venv')], check=True, capture_output=True)
    package = app / 'nodelang'
    package.mkdir(exist_ok=True)
    (package / '__init__.py').write_text('')
    (package / 'native_agent_mcp.py').write_text("""
import pathlib,sqlite3,sys,time
db=sqlite3.connect(sys.argv[1]);db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
db.execute('INSERT INTO work VALUES (99, zeroblob(700000))');db.commit()
pathlib.Path(sys.argv[2]).touch()
while True: time.sleep(1)
""", encoding='utf-8')
    marker = profile / 'mcp-ready'
    child = subprocess.Popen([str(app / '.venv/Scripts/python.exe'), '-B', '-m', 'nodelang.native_agent_mcp', str(source), str(marker)], cwd=app,
                             executable=sys._base_executable)
    wait_for(marker, child)
    return child


@pytest.mark.skipif(os.name != 'nt', reason='Windows Restart Manager integration')
def test_owned_mcp_holder_stops_and_data_survives(tmp_path):
    source = journal(tmp_path / 'ArchHub-Test/archhub-test.universal.sqlite3')
    child = mcp_holder(tmp_path, source)
    before = identity(source)
    assert Path(str(source) + '-wal').stat().st_size > 0
    try:
        completed = files.preserve_closed_application_journals(tmp_path, 'mcp-shape', close_writers=True)
        child.wait(10)
        assert identity(source) == before
        assert identity(Path(completed[0]) / source.name) == before
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(10)


@pytest.mark.skipif(os.name != 'nt', reason='Windows invocation grammar')
def test_python_command_arguments_cannot_impersonate_an_archhub_helper(tmp_path):
    from nodelang.installer_closed_profile import _python_role
    app = tmp_path / 'ArchHub'
    executable = str(app / '.venv/Scripts/python.exe')
    assert _python_role(app, [executable, str(app / 'nodelang/launcher.py')]) == 'desktop'
    assert _python_role(app, [executable, str(app / 'launch_archhub_test.py')]) == 'desktop'
    assert _python_role(app, [executable, 'user.py', '-m', 'nodelang.native_agent_mcp']) == ''
    assert _python_role(app, [executable, '-c', "print('-m nodelang.native_agent_mcp')", str(app)]) == ''
    assert _python_role(app, [executable, '-I', '-B', '-m', 'nodelang.native_agent_mcp']) == 'helper'
    code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('nodelang.clean_coordination_service',run_name='__main__')"
    assert _python_role(app, [executable, '-I', '-c', code, str(app)]) == 'helper'
    assert _python_role(app, [executable, '-I', '-c', code, str(tmp_path)]) == ''


@pytest.mark.skipif(os.name != 'nt', reason='Windows process access semantics')
def test_kernel_holder_is_waited_out_not_stopped():
    # Founder machine 2026-10-22: three installs refused with "Cannot stop journal holder:
    # System (PID 4)" right after the 10 GB graph closed; the kernel is never stopped.
    from types import SimpleNamespace
    from nodelang import installer_closed_profile as closed
    kernel = SimpleNamespace(process=SimpleNamespace(pid=4, started=None), name='System')
    with closed._process_handle(kernel) as (handle, _):
        assert handle is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing semantics')
def test_journal_lease_waits_out_a_brief_write_holder(tmp_path):
    # Founder machine 2026-10-22: [WinError 32] from the kernel for ~1 s after the 10 GB graph closed.
    import threading
    source = journal(tmp_path / 'ArchHub/authority.sqlite3')
    writer = open(source, 'r+b')
    threading.Timer(2.0, writer.close).start()
    started = time.monotonic()
    with files._closed_source_lease(source) as db:
        assert db.execute('SELECT COUNT(*) FROM work').fetchone()[0] == 40
    assert time.monotonic() - started >= 1.5
