"""BIGMIGRATE2 boot/recovery courts, isolated profiles and real SQLite work."""
from contextlib import closing
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from nodelang import persistence, application_recovery_files as recovery
from nodelang import application_recovery_restore_files as restore
from nodelang.clean_boot_surface import BootSurface
from tests_replica.test_launcher_boot_refusal import FakeClock, _launcher_names
from tests_replica import test_ogboot_upgrade_selection as _upgrade_selection
from tests_replica.test_ogboot_upgrade_selection import _prepare, _closed_backup
from tests_replica.test_bigmigrate_restart import _fixture

isolated_profile = _upgrade_selection.isolated_profile


def test_prepared_copy_bounds_unsynced_bytes_and_retains_final_sync(tmp_path, monkeypatch):
    source, target = tmp_path / "source.bin", tmp_path / "copy.bin"
    with source.open("wb") as stream:
        for _ in range(65):
            stream.write(b"b" * 1024**2)
    target.touch()
    sizes = []
    real_sync = os.fsync
    def synced(fd):
        sizes.append(os.fstat(fd).st_size)
        real_sync(fd)
    monkeypatch.setattr(os, "fsync", synced)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    restore._copy_exact(source, target, {"size_bytes": source.stat().st_size, "sha256": digest},
                        restore._file_identity(source), lambda: None)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert sizes[-1] == source.stat().st_size
    assert max(b-a for a,b in zip([0]+sizes, sizes)) <= 64*1024**2


@pytest.mark.parametrize("owner", ["copy", "restore"])
def test_integrity_reports_each_actual_sqlite_work_step(tmp_path, monkeypatch, owner):
    path = tmp_path / "graph.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE payload(value BLOB)")
        db.executemany("INSERT INTO payload VALUES(?)", [(bytes(range(256))*4096,)]*40)
        db.commit()
    clock, observed = FakeClock(), []
    monkeypatch.setattr(persistence, "time", clock)
    lease = persistence._MigrationProgress(30, lambda event: observed.append((clock.now, event)))
    connect = sqlite3.connect

    class ObservedConnection:
        def __init__(self, *args, **kwargs):
            self.db = connect(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def set_progress_handler(self, callback, interval):
            count = 0

            def step():
                nonlocal count
                count += 1
                clock.now += 4  # only real engine callbacks advance this clock
                return callback() if count % interval == 0 else 0

            self.db.set_progress_handler(step, 1)

    monkeypatch.setattr(sqlite3, "connect", ObservedConnection)
    if owner == "copy":
        with recovery._copy_connection(path, lease) as db:
            recovery._verify_database(db, lease)
    else:
        restore._verify_sqlite_readonly(path, lease)
    assert clock.now > 30
    assert observed
    assert max(b[0]-a[0] for a,b in zip([(0, None)]+observed, observed)) <= 10


@pytest.mark.parametrize("owner", ["copy", "restore"])
def test_integrity_still_rejects_foreign_key_corruption(tmp_path, owner):
    path = tmp_path / "invalid.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                         "CREATE TABLE child(id INTEGER REFERENCES parent(id));"
                         "INSERT INTO child VALUES(42);")
    with pytest.raises(ValueError, match="foreign_key_check"):
        if owner=="copy":
            with recovery._copy_connection(path, lambda: None) as db:
                recovery._verify_database(db, lambda: None)
        else:
            restore._verify_sqlite_readonly(path, lambda: None)


def test_splash_failure_actions_are_served_and_admitted_once():
    surface = BootSurface("127.0.0.1", 0).start()
    try:
        port = surface._server.server_address[1]
        base = "http://127.0.0.1:%d" % port
        surface.progress.fail("Synthetic migration stopped; saved data kept")
        with urlopen(base+"/api/universal/boot") as answer:
            state = json.load(answer)
        assert state["failure"]["message"].startswith("Synthetic migration")
        with urlopen(base) as answer:
            page = answer.read().decode()
        assert "Retry" in page and "Keep current version and close" in page
        payload = json.dumps({"action": "retry", "token": state["failure"]["token"]}).encode()
        with urlopen(Request(base+"/api/universal/boot/action", data=payload,
                             headers={"Content-Type":"application/json"})) as answer:
            assert json.load(answer)["ok"] is True
        assert surface.progress.wait_for_action() == "retry"
        assert surface.progress.choose("keep", state["failure"]["token"]) is False
        assert surface.progress.payload()["failure"] is None
    finally:
        surface._server.shutdown()
        surface._server.server_close()


@pytest.mark.parametrize("action", ["retry", "keep"])
def test_launcher_failure_uses_splash_choice_without_native_dialog(action):
    attempts, failures, arms = [], [], []

    def boot():
        if attempts:
            assert arms == [True], "retry must be watched before any new boot work"
        attempts.append(True)
        return (None, RuntimeError("synthetic migration")) if len(attempts)==1 else ("server", None)

    progress = SimpleNamespace(fail=failures.append, wait_for_action=lambda: action)
    def closed(code):
        raise SystemExit(code)
    namespace = _launcher_names("_open_saved_graph_with_recovery", _open_saved_graph=boot,
        _boot_surface=SimpleNamespace(progress=progress), _exit_process=closed,
        faulthandler=SimpleNamespace(cancel_dump_traceback_later=lambda: None), _boot_deadline=1,
        time=time, _arm_boot_watchdog=lambda: arms.append(True))
    if action == "keep":
        with pytest.raises(SystemExit) as failure:
            namespace["_open_saved_graph_with_recovery"]()
        assert failure.value.code == 0
        assert len(attempts) == 1
        assert arms == []
    else:
        assert namespace["_open_saved_graph_with_recovery"]() == ("server", None)
        assert len(attempts) == 2
    assert failures == ["synthetic migration"]


def test_same_head_source_edit_is_rejected_before_current(isolated_profile, monkeypatch):
    root, stale, source, _budget = _fixture(isolated_profile)
    _closed_backup(source)
    pointer = (root / "unified-authority/CURRENT").read_bytes()
    verify = persistence._verify_migrated_application

    def changing_copy(path, *args, **kwargs):
        evidence = verify(path, *args, **kwargs)
        # The same physical source now has the adopted basename. A direct byte
        # edit bypasses the graph owner/head, even with its mtime restored.
        stat = path.stat()
        with path.open("r+b") as stream:
            data = stream.read()
            position = data.index(b"x"*1024)
            stream.seek(position)
            stream.write(b"y")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return evidence

    monkeypatch.setattr(persistence, "_verify_migrated_application", changing_copy)
    with pytest.raises(ValueError, match="changed during migration"):
        _prepare(root)
    assert (root / "unified-authority/CURRENT").read_bytes() == pointer
    assert persistence.application_database_path(root) == stale


@pytest.mark.parametrize("mutation", ["unexpected-file", "verifier-write"])
def test_restore_keeps_pre_verifier_ownership_and_post_verifier_hash(isolated_profile, monkeypatch, mutation):
    root, _stale, source, _budget = _fixture(isolated_profile)
    closed = _closed_backup(source)
    closed_before = {path.name: path.read_bytes() for path in closed.iterdir()}
    # Explicit restore remains supported; boot no longer creates or restores an
    # internal page copy. Exercise the same owner on an authentic recovery.
    with closing(sqlite3.connect(source)) as database:
        backup = recovery.publish_application_recovery({"graph": database}, root / "recovery-court",
            verify_copies=lambda *_: {}, before_publish=lambda: None, deadline=time.monotonic() + 60)
    seen = []
    prepare, check_source = restore.prepare_application_restore, restore._check_source
    def injected(*args):
        check_source(*args)
        stages = list(root.glob(".application-recovery-restore-*"))
        if mutation=="unexpected-file" and stages:
            (stages[0]/"unexpected.txt").write_text("unowned fixture entry")
    def guarded(*args, **kwargs):
        def owner(paths, manifest, budget):
            seen.append(True)
            if mutation=="verifier-write":
                with closing(sqlite3.connect(paths["graph"])) as db:
                    db.execute("PRAGMA user_version=42")
        kwargs["verify_copies"] = owner
        return prepare(*args, **kwargs)
    monkeypatch.setattr(restore, "_check_source", injected)
    monkeypatch.setattr(restore, "prepare_application_restore", guarded)
    with pytest.raises(ValueError, match="unexpected|changed|manifest"):
        restore.prepare_application_restore(backup, root / "restored-court",
            output_names={"graph": "authority.sqlite3"}, verify_copies=lambda *_: None,
            before_publish=lambda: {}, deadline=time.monotonic() + 60)
    assert seen == ([] if mutation=="unexpected-file" else [True])
    assert {path.name: path.read_bytes() for path in closed.iterdir()} == closed_before


def test_failed_constructor_progress_hook_becomes_inert(isolated_profile, monkeypatch):
    from nodelang import desktop, model_execution_broker, project_work_execution_broker
    root, stale, _source, _budget = _fixture(isolated_profile)
    _closed_backup(_source)
    events, captured = [], []
    monkeypatch.setattr(desktop, "create_workshop_transport", lambda *_: None)
    monkeypatch.setattr(desktop, "create_social_execution_arguments", lambda: {})
    monkeypatch.setattr(model_execution_broker, "ApplicationOpenRouterCredentialResolver", lambda: None)
    monkeypatch.setattr(model_execution_broker, "ModelExecutionBroker", lambda **_: None)
    monkeypatch.setattr(project_work_execution_broker, "ProjectWorkExecutionBroker", lambda *_: None)
    def refused(**kwargs):
        callback = kwargs["universal_journal_progress_handler"]
        captured.append(callback)
        callback()
        count, replies = len(events), []
        other = threading.Thread(target=lambda: replies.append(callback()))
        other.start()
        other.join(5)
        assert replies == [0]
        assert len(events) == count, "unrelated threads cannot renew the constructor's lease"
        raise RuntimeError("constructor fixture refusal")
    namespace = _launcher_names("_boot_unsampled", state_dir=root, state_path=stale,
        machine_key_provider=None, _migration_progress=events.append,
        application_database_path=persistence.application_database_path, _saved_graph_exists=lambda *_: True,
        ApplicationServer=refused, Path=Path, os=os, __file__=__file__, PIPELINE_ENGINES={},
        descriptor_path=root/"descriptor.json", _machine_pointer=None)
    with pytest.raises(RuntimeError, match="constructor fixture refusal"):
        namespace["_boot_unsampled"]()
    assert events[-1] is None
    count = len(events)
    assert captured[0]() == 0
    assert len(events) == count, "a partial failed store must never re-arm the boot watchdog"
