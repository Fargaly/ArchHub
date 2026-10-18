"""ADOPT acceptance: real isolated launcher/server, scaled chain-valid traces.

The explicit blocking-copy trap is the scaled-fixture alternative in the brief;
these courts make no claim to have run the independent 8 GB installed gate.
"""
from contextlib import closing, nullcontext
import hashlib
from http.cookiejar import CookieJar
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from nodelang import persistence
from nodelang.universal_cell import Cell, CellStore, DatabaseOwnerConflict, NULL_CELL_ID
from tests_replica.test_adopt import closed_backup, fixture
from tests_replica.test_launcher_boot_refusal import _launcher_names
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile
ROOT = Path(__file__).resolve().parents[1]


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _browser(server):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(server.bootstrap_url, timeout=10) as response:
        page = response.read().decode("utf-8")
        assert response.status == 200
    csrf = re.search(r'<meta name="archhub-csrf" content="([A-Za-z0-9_-]+)">', page).group(1)
    return opener, csrf


def _json(opener, server, path, body=None, csrf=None):
    request = Request(server.url + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-ArchHub-CSRF": csrf or ""},
        method="GET" if body is None else "POST")
    with opener.open(request, timeout=10) as response:
        assert response.status == 200
        return json.loads(response.read())


def _trace_shape(store, monkeypatch, *, per_day=24):
    """Real kernel commits: four namespaces, scaffold chains, sparse content."""
    import nodelang.universal_cell as kernel
    from nodelang import commit_intent
    now = time.time()
    prefixes = ("app:deliberation-payload:", "app:agent-session:",
                "app:workshop:", "app:baboom-session:")
    count = 0
    for day in range(60, 0, -1):
        cells = []
        for prefix in prefixes:
            previous = NULL_CELL_ID
            for index in range(per_day):
                ident = f"{prefix}scaled-{day}:view-receipt:chain:{index}"
                cells.append(Cell(ident, previous, NULL_CELL_ID,
                                  f"saved trace day {day}".encode() if index == 0 else b""))
                previous = ident
        with monkeypatch.context() as clock:
            clock.setattr(kernel, "time", SimpleNamespace(time=lambda d=day: now-d*86400))
            with commit_intent.declare(commit_intent.MIGRATION, actor="court",
                    reason="synthetic pre-upgrade trace-shaped journal"):
                store.commit(store.revision, create=tuple(cells))
        count += len(cells)
    return count


def test_real_launcher_opens_same_journal_and_saved_edit_without_copy(
        isolated_profile, tmp_path, monkeypatch, capsys):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang import application_recovery_files, desktop, existing_workshop_native_host, model_router

    root = isolated_profile / "ArchHub"
    stale = upgrade._selected(root)
    source = isolated_profile / "ArchHub-Test/archhub-test.universal.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r"*32)
    keys.add_key("archhub.local.court-attestation", b"c"*32)

    def factory(**kwargs):
        kwargs.update(universal_key_provider=keys, universal_workspace_root=tmp_path,
            enable_machine_transport=False, enable_universal_cloud_gateway=False,
            enable_brain_cloud_sync=False, live_watch=False)
        return ApplicationServer(**kwargs)

    saved = {"pan_x": 123.0, "pan_y": -456.0, "zoom": 0.82}
    seed = factory(universal_state_path=source).start()
    try:
        opener, csrf = _browser(seed)
        assert _json(opener, seed, "/api/universal/gesture", {"viewport": saved}, csrf)["ok"]
        assert _json(opener, seed, "/api/universal/canvas")["viewport"] == saved
        trace_cells = _trace_shape(seed.universal_store, monkeypatch)
    finally:
        seed.close()
    backup = closed_backup(source.parent, source)
    source_bytes = source.stat().st_size
    source_file_id = (source.stat().st_dev, source.stat().st_ino)
    stale_before = _digest(stale)
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
        head, revisions = db.execute("SELECT MAX(revision),COUNT(*) FROM revisions").fetchone()

    def blocking_copy(*_args, **_kwargs):
        raise AssertionError("RED: full journal copy blocks Studio boot (scaled slow-copy trap)")

    monkeypatch.setattr(application_recovery_files, "_backup_sqlite", blocking_copy)
    monkeypatch.setattr(desktop, "create_workshop_transport", lambda *_: None)
    monkeypatch.setattr(desktop, "create_social_execution_arguments", lambda: {})
    monkeypatch.setattr(desktop, "bind_coordination_surface", lambda *_: None)
    monkeypatch.setattr(existing_workshop_native_host, "ExistingWorkshopNativeHost", lambda *a, **k: None)
    monkeypatch.setattr(ApplicationServer, "enable_native_workshop_compliance", lambda *_: None)
    monkeypatch.setattr(model_router, "bind_local_cli_broker", lambda *_: None)
    events = []
    namespace = _launcher_names("_boot", "_boot_unsampled", state_dir=root,
        state_path=stale, machine_key_provider=keys, _migration_progress=events.append,
        _boot_step_seen=lambda *_: None, application_database_path=persistence.application_database_path,
        _saved_graph_exists=lambda *_: True, ApplicationServer=factory,
        Path=Path, os=os, __file__=str(ROOT/"launch_archhub_test.py"),
        PIPELINE_ENGINES={}, descriptor_path=root/"runtime-descriptor.json", _machine_pointer=None)
    started = time.monotonic()
    server = namespace["_boot"]()
    try:
        opener, _csrf = _browser(server)
        actual = _json(opener, server, "/api/universal/canvas")
        elapsed = time.monotonic()-started
        assert actual["viewport"] == saved, "the HTTP canvas must show the saved edit"
        selected = persistence.application_database_path(root)
        assert (selected.stat().st_dev, selected.stat().st_ino) == source_file_id
        assert source.is_file() and selected == source, "2230 must retain its flat journal"
        assert Path(server.universal_store.database_path) == selected
        assert server.universal_store.snapshot().cells[
            "app:agent-session:scaled-1:view-receipt:chain:0"].atom == b"saved trace day 1"
        assert elapsed <= 45, f"Studio HTTP usable after {elapsed:.6f}s"
    finally:
        server.close()
    assert _digest(stale) == stale_before
    assert (backup/"closed-files.json").is_file()
    output = capsys.readouterr().out
    adoption = re.search(r"adoption\s+: source head=(\d+) revisions=(\d+) receipts=verified:(\d+); "
                         r"selected head=(\d+) revisions=(\d+) receipts=verified:(\d+)", output)
    assert adoption, output
    left, right = adoption.groups()[:3], adoption.groups()[3:]
    assert left == right
    assert tuple(map(int, left[:2])) == (head, revisions)
    assert int(left[2]) > 0, "the fixture must exercise actual signed receipt verification"
    print("ADOPT_REAL_BOOT", json.dumps(dict(seconds=elapsed, trace_cells=trace_cells,
        source_bytes=source_bytes, saved_edit_http_visible=True,
        stale_byte_unchanged=True, same_inode=True, source_head=head, revision_count=revisions)))


@pytest.mark.parametrize("reopen", [False, True])
def test_flat_journal_has_one_canonical_writer(isolated_profile, reopen):
    root, stale, source, _backup = fixture(isolated_profile)
    identity = (source.stat().st_dev, source.stat().st_ino)
    persistence.prepare_application_database(root, stale)
    selected = persistence.application_database_path(root)
    assert (selected.stat().st_dev, selected.stat().st_ino) == identity
    assert source.is_file() and selected == source, "one flat SQLite basename survives adoption"
    if reopen:
        with CellStore(selected) as owner:
            assert owner.snapshot().cells["app:archhub"].atom == b"saved edit"
    with CellStore(selected):
        with pytest.raises(DatabaseOwnerConflict):
            CellStore(selected)
    with CellStore(selected) as reopened:
        assert reopened.snapshot().cells["app:archhub"].atom == b"saved edit"


@pytest.mark.parametrize('kernel_revision', ['624300f2', 'e41d56aa'])
def test_installer_backup_restores_with_624_kernel_after_live_edit(isolated_profile, tmp_path, kernel_revision):
    root, stale, source, backup = fixture(isolated_profile)
    original = upgrade._history(source)
    digest = _digest(backup/source.name)
    persistence.prepare_application_database(root, stale)
    with CellStore(persistence.application_database_path(root)) as store:
        store.commit(store.revision, create=(Cell("work:after-upgrade", NULL_CELL_ID,
                                                  NULL_CELL_ID, b"new work"),))
    assert _digest(backup/source.name) == digest
    restored = tmp_path/"rollback.sqlite3"
    shutil.copyfile(backup/source.name, restored)
    assert upgrade._history(restored) == original
    old_source = subprocess.check_output(["git", "show", kernel_revision + ":nodelang/universal_cell.py"], cwd=ROOT)
    name = "nodelang._adopt_2230_kernel"
    spec = importlib.util.spec_from_loader(name, loader=None)
    old = importlib.util.module_from_spec(spec)
    sys.modules[name] = old
    try:
        exec(compile(old_source, kernel_revision + ":nodelang/universal_cell.py", "exec"), old.__dict__)
        with old.CellStore(restored) as previous:
            assert previous.snapshot().cells["app:archhub"].atom == b"saved edit"
            assert "work:after-upgrade" not in previous.snapshot().cells
            previous.commit(previous.revision, create=(old.Cell("work:rollback-edit",
                old.NULL_CELL_ID, old.NULL_CELL_ID, b"2230 writer works"),))
            assert previous.snapshot().cells["work:rollback-edit"].atom == b"2230 writer works"
    finally:
        sys.modules.pop(name, None)
    print("ADOPT_ROLLBACK_KERNEL", kernel_revision, digest)


_INTERRUPTED_POINTER = r"""
from pathlib import Path
import sys, threading
from nodelang import persistence, unified_authority_runtime as runtime
root, source, marker = map(Path, sys.argv[1:])
publish = runtime._atomic_text
def pause_before_pointer(path, value):
    if Path(path).name == 'CURRENT':
        marker.write_text(str(source))
        threading.Event().wait()
    return publish(path,value)
runtime._atomic_text = pause_before_pointer
persistence.prepare_application_database(root,persistence.application_database_path(root))
raise AssertionError('court did not reach CURRENT publication')
"""


def test_hard_killed_pointer_preparation_keeps_flat_custody_and_retries(isolated_profile, tmp_path):
    root, stale, source, backup = fixture(isolated_profile)
    from nodelang.application_recovery_files import preserve_closed_application_journals
    backup = Path(preserve_closed_application_journals(isolated_profile, 'pointer-kill')[0])
    identity = (source.stat().st_dev, source.stat().st_ino)
    current = root / 'unified-authority/CURRENT'
    selected_before, stale_before = current.read_bytes(), _digest(stale)
    backup_before = _digest(backup/source.name)
    marker = tmp_path / 'pointer-prepared.txt'
    process = subprocess.Popen([sys.executable, '-c', _INTERRUPTED_POINTER,
        str(root), str(source), str(marker)], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic()+20
        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=1) if process.poll() is not None else 'publication stalled'
        assert source.is_file() and current.read_bytes() == selected_before
        process.kill()
        process.wait(10)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
    assert source.stat().st_ino == identity[1]
    result = persistence.prepare_application_database(root,stale)
    assert result['state'] == 'adopted'
    assert persistence.application_database_path(root) == source
    assert (source.stat().st_dev, source.stat().st_ino) == identity
    assert _digest(stale) == stale_before and _digest(backup/source.name) == backup_before
    with CellStore(source) as store:
        assert store.read('app:archhub').atom == b'saved edit'


def test_background_trace_progress_never_rearms_the_boot_watchdog():
    events, admissions, watchdog = [], [], []
    stop = threading.Event()
    token = object()
    replies = iter((dict(status="copying", next_cursor={"offset": 1}, copied=3, exported=0, moved=0),
                    dict(status="waiting-for-idle", next_cursor=None, copied=3, exported=0, moved=0),
                    dict(status="retirement-admission-required", next_cursor=None, copied=3, exported=0, moved=0)))
    def maintain(**kwargs):
        admissions.append(kwargs)
        return next(replies)
    namespace = _launcher_names("_maintain_legacy_conversations",
        _update_stop=stop, _conversation_maintenance_context=lambda: token,
        _trace_background_priority=nullcontext, _trace_retention_cursor=None,
        _trace_retention_status=None, _migration_status=None, _boot_deadline=123.5,
        _arm_boot_watchdog=lambda: watchdog.append("armed"),
        server=SimpleNamespace(conversation_content=SimpleNamespace(maintain_legacy_trace_inventory=maintain)),
        _boot_surface=SimpleNamespace(progress=SimpleNamespace(migration=events.append)))
    assert namespace["_maintain_legacy_conversations"]() is True
    assert namespace["_maintain_legacy_conversations"]() is False
    assert namespace["_maintain_legacy_conversations"]() is False, "a refused, unproductive retirement must back off"
    assert namespace["_boot_deadline"] == 123.5
    assert watchdog == []
    assert [event["stage"] for event in events] == ["copying", "waiting-for-idle", "retirement-admission-required"]
    assert all(event["background"] is True for event in events)
    assert events[0]["completed"] == 3
    assert admissions[0] == dict(authentication_context=token, cursor=None,
        cancellation_event=stop, timeout_seconds=2.0)
    assert admissions[1]["cursor"] == {"offset": 1}
    stop.set()
    assert namespace["_maintain_legacy_conversations"]() is False
    assert len(admissions) == 3


def test_existing_update_worker_runs_trace_batches_and_preserves_auth_update_cadence(monkeypatch):
    from tests_replica.test_launcher_boot_refusal import FakeClock
    clock = FakeClock()
    renewals, refreshes, ordinary, updates, traces, thread_ids = [], [], [], [], [], []
    creator = threading.get_ident()
    class Stop:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, delay):
            clock.now += delay
            self.stopped = clock.now > 1920
            return self.stopped
    stop = Stop()
    def trace_batch():
        traces.append(clock.now)
        thread_ids.append(threading.get_ident())
        return len(traces) < 3
    monkeypatch.setitem(sys.modules, "nodelang.cloud_signin",
        SimpleNamespace(refresh_session=lambda: refreshes.append(clock.now)))
    namespace = _launcher_names("_stage_update_quietly", time=clock, _update_stop=stop,
        _renew_desktop_session=lambda: renewals.append(clock.now),
        _maintain_conversations=lambda: ordinary.append(clock.now),
        _maintain_legacy_conversations=trace_batch, _stage_once=lambda: updates.append(clock.now))
    namespace["_stage_update_quietly"]()
    assert traces[:3] == [30, 30.25, 30.5]
    assert all(ident == creator for ident in thread_ids), "trace passes must use the existing worker"
    assert renewals == refreshes == ordinary == list(range(60, 1921, 60))
    # Current main checks at startup and delegates its interval to the owner.
    assert updates == list(range(0, 1921, 60))
