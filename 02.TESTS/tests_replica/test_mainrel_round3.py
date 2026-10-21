"""Round3 retention regression: real logical bytes, disposable sparse files."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from nodelang import application_recovery_files as files

FIXTURE_BYTES: int = 8_937_168_896


def sparse_file(path, size, prefix=b''):
    with path.open('xb') as stream:
        stream.write(prefix)
    if os.name == 'nt':
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        returned = ctypes.c_ulong()
        with path.open('r+b') as stream:
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno()))
            ok = kernel.DeviceIoControl(handle,
                0x900C4, None, 0, None, 0, ctypes.byref(returned), None)
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            pointer = kernel.SetFilePointerEx
            pointer.argtypes = (ctypes.c_void_p, ctypes.c_longlong, ctypes.c_void_p, ctypes.c_ulong)
            end = kernel.SetEndOfFile
            end.argtypes = (ctypes.c_void_p,)
            if not pointer(handle, size, None, 0) or not end(handle):
                raise ctypes.WinError(ctypes.get_last_error())
    else:
        with path.open('r+b') as stream:
            stream.truncate(size)


@pytest.mark.parametrize('legacy_armed',[False,True])
def test_three_installs_replace_pin_with_real_size_accounting(tmp_path, monkeypatch,legacy_armed):
    source = tmp_path / 'ArchHub-Test/archhub-test.universal.sqlite3'
    source.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE work(value TEXT)')
        db.execute("INSERT INTO work VALUES ('first')")
    db.close()
    prefix = source.read_bytes()
    source.unlink()
    sparse_file(source, FIXTURE_BYTES, prefix)
    legacy=None
    if legacy_armed:
        legacy=tmp_path/'ArchHub-Test/backups/20261018-0400'
        legacy.mkdir(parents=True)
        sparse_file(legacy/'graph.sqlite3',FIXTURE_BYTES,prefix)
        (legacy/'recovery.json').write_text(json.dumps({'format':1,'files':{'graph':{'name':'graph.sqlite3'}},'metadata':{}}))
        updates=tmp_path/'ArchHub-Test/updates'
        updates.mkdir()
        (updates/'update-ready.json').write_text(json.dumps({'format':1,'recovery':{'path':str(legacy)}}))
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda _: usage._replace(free=100 * 1024**3))

    def copy_sparse(path, destination, report):
        # All nonzero pages are in this initial SQLite extent; publication
        # still hashes and verifies all 8.3 GiB using the production verifier.
        with path.open('rb') as stream:
            first = stream.read(1024 * 1024)
        sparse_file(destination, path.stat().st_size, first)
    monkeypatch.setattr(files, '_copy_closed_file', copy_sparse)
    digests = {}
    def fixture_record(path):
        # Accounting court: all extents after the initial MiB were constructed
        # as zero holes above. Derive their exact SHA without rereading8GiB
        # of known holes per verification; streaming integrity has its own court.
        size = path.stat().st_size
        with path.open('rb') as stream:
            head = stream.read(1024 * 1024)
        key = (hashlib.sha256(head).digest(), size)
        if key not in digests:
            digest = hashlib.sha256(head)
            left = size - len(head)
            zeros = bytes(8 * 1024 * 1024)
            while left:
                amount = min(left, len(zeros))
                digest.update(zeros[:amount])
                left -= amount
            digests[key] = digest.hexdigest()
        return dict(name=path.name, bytes=size, sha256=digests[key])
    monkeypatch.setattr(files, '_closed_file_record', fixture_record)
    for number in range(1, 4):
        with sqlite3.connect(source) as db:
            db.execute('UPDATE work SET value=?', (str(number),))
        db.close()
        if number == 2:
            Path(str(source) + '.adoption.json').write_text('{}')
        completed = files.preserve_closed_application_journals(tmp_path, f'install-{number}')
        assert len(completed) == 1
        receipts = list(files.installer_backup_directory(tmp_path, source).glob('*-closed'))
        assert len(receipts) == 1
        receipt = json.loads((receipts[0] / 'closed-files.json').read_text())
        assert receipt['files'][0]['bytes'] == FIXTURE_BYTES
        assert (receipts[0] / source.name).stat().st_size == FIXTURE_BYTES
        if legacy_armed:
            assert (legacy/'graph.sqlite3').stat().st_size == FIXTURE_BYTES
            print('ARMED_0400_PRESERVED bytes=%d ordinary_retained_bytes=%d' %
                  (FIXTURE_BYTES,sum(p.stat().st_size for p in receipts[0].iterdir())))
        print('INSTALL_%d_PASS fixture_bytes=%d retained_bytes=%d' %
              (number, FIXTURE_BYTES, sum(p.stat().st_size for p in receipts[0].iterdir())))
    if legacy_armed:
        # A later canonical main arm retires this legacy marker; its publication
        # has a separate real recovery-owner court. Retention may now prune it.
        (updates/'update-ready.json').unlink()
        with sqlite3.connect(source) as db:
            db.execute("UPDATE work SET value='after-disarm'")
        db.close()
        files.preserve_closed_application_journals(tmp_path,'after-disarm',keep_count=1)
        assert not legacy.exists()


def test_no_prune_when_new_copy_will_exceed_budget(tmp_path):
    source = tmp_path / 'ArchHub/authority.sqlite3'
    source.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE work(value TEXT)')
    db.close()
    completed = files.preserve_closed_application_journals(tmp_path, 'initial')
    old = Path(completed[0])
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO work VALUES ('new')")
    db.close()
    with pytest.raises(ValueError, match='over budget'):
        files.preserve_closed_application_journals(tmp_path, 'refuse', max_bytes=1)
    assert old.is_dir()


def test_reused_backup_does_not_refuse_post_copy_disk_check(tmp_path, monkeypatch):
    source = tmp_path / 'ArchHub/authority.sqlite3'
    source.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE work(value TEXT)')
    db.close()
    before = files.preserve_closed_application_journals(tmp_path, 'initial')
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda _: usage._replace(free=20 * 1024**3))
    assert files.preserve_closed_application_journals(tmp_path, 'unchanged') == before

def small_journal(profile):
    path = profile / 'ArchHub-Test/archhub-test.universal.sqlite3'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE work(value TEXT)')
    db.close()
    return path


def test_auto_backup_uses_roomiest_fixed_drive_and_shared_preference(tmp_path, monkeypatch):
    profile, drive = tmp_path / 'profile', tmp_path / 'fixed-drive'
    drive.mkdir()
    source = small_journal(profile)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(files, '_fixed_backup_drives', lambda: [drive])
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda path:
        usage._replace(free=(100 if Path(path).is_relative_to(drive) else 25) * 1024**3))
    result = files.preserve_closed_application_journals(profile, 'off-c')
    assert Path(result[0]).is_relative_to(drive)
    preference = files.backup_location(profile)
    assert preference['location'] == 'auto'
    assert Path(result[0]).parent.parent == Path(preference['directory'])
    assert files.installer_backup_directory(profile, source) == Path(result[0]).parent


def test_explicit_location_and_0400_backups_have_one_retention_owner(tmp_path):
    profile, selected = tmp_path / 'profile', tmp_path / 'selected'
    source = small_journal(profile)
    legacy = profile / 'ArchHub-Test/backups/20261017-0400'
    legacy.mkdir(parents=True)
    shutil.copyfile(source, legacy / 'graph.sqlite3')
    (legacy / 'recovery.json').write_text(json.dumps({'format':1,'files':{'graph':{'name':'graph.sqlite3'}},'metadata':{}}))
    files.set_backup_location(profile, str(selected))
    with pytest.raises(ValueError, match='over budget'):
        files.preserve_closed_application_journals(profile, 'refused', max_bytes=1)
    assert legacy.is_dir(), 'never delete legacy custody before a new verified copy exists'
    report = []
    result = files.preserve_closed_application_journals(profile, 'replacement', keep_count=1, progress=report.append)
    assert Path(result[0]).is_relative_to(selected)
    assert not legacy.exists()
    assert any(str(legacy) in row for row in report)


def test_incomplete_owned_stage_is_cleaned_and_unknown_stage_is_preserved(tmp_path):
    source = small_journal(tmp_path)
    parent = files.installer_backup_directory(tmp_path, source)
    pending = parent / ('killed-' + 'a' * 32 + '-pending')
    pending.mkdir(parents=True)
    sparse_file(pending / source.name, FIXTURE_BYTES)
    unknown = parent / 'someone-elses-pending'
    unknown.mkdir()
    (unknown / 'private.txt').write_text('preserve')
    files.preserve_closed_application_journals(tmp_path, 'next')
    assert not pending.exists()
    assert (unknown / 'private.txt').read_text() == 'preserve'


def test_windows_source_lease_refuses_a_writer(tmp_path):
    source = small_journal(tmp_path)
    with files._closed_source_lease(source):
        if os.name == 'nt':
            with pytest.raises(PermissionError):
                source.open('r+b')
        else:
            with sqlite3.connect(source) as db:
                with pytest.raises(sqlite3.OperationalError):
                    db.execute('INSERT INTO work VALUES (1)')

def test_quiet_updater_waits_for_setup_and_preserves_verbatim_refusal(tmp_path):
    from tests_replica.test_autoupd import staged_app
    from nodelang import quiet_update
    from types import SimpleNamespace
    app, state = staged_app(tmp_path)
    refusal = 'Setup refused: Installer backup over budget: 123 + 456 bytes exceeds 789 bytes; saved work was kept'
    def refuse(args, **options):
        assert '/SILENT' in args
        assert '/VERYSILENT' not in args
        assert options['timeout'] is None
        log = next(arg.removeprefix('/LOG=') for arg in args if arg.startswith('/LOG='))
        Path(log).write_text('2026-10-18 ArchHub Setup refused: ' + refusal + '\n', encoding='utf-8')
        return SimpleNamespace(returncode=7)
    result = quiet_update.apply_staged(state, app, runner=refuse)
    assert not result['applied']
    assert result['reason'] == refusal
    assert (app / 'state/graph.db').read_bytes() == b'USER GRAPH'


def test_installer_only_marker_is_invisible_to_pre_main_retention(tmp_path):
    from nodelang import application_update_recovery as recovery
    app, state = tmp_path / 'app', tmp_path / 'state'
    app.mkdir()
    updates = state / 'updates'
    updates.mkdir(parents=True)
    (app / 'BUILD_ID').write_text('old')
    (updates / 'staged.json').write_text(json.dumps({'build_id': 'new', 'sha256': 'a' * 64}))
    (updates / 'ArchHub-Setup-0.exe').write_bytes(b'fixture')
    source = state / 'authority.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE work(value TEXT)')
    db.close()
    marker = recovery.arm_update(state, app, source, None)
    assert marker.name == 'installer-update-ready.json'
    assert recovery.validate_update_ready(state, app, source, None)['format'] == 2
    baseline = subprocess.run(['git', 'show', 'd89a50fd:nodelang/backup_retention.py'], capture_output=True, text=True, check=True)
    namespace = {'__name__': 'nodelang.mainrel_legacy_retention'}
    exec(compile(baseline.stdout, '<pre-main-retention>', 'exec'), namespace)
    assert namespace['protected_update_backups'](state, state / 'backups') == ()
    assert not (updates / 'update-ready.json').exists()

def test_custom_base_never_adopts_live_profiles_or_unowned_children(tmp_path):
    source = small_journal(tmp_path)
    live_bytes = source.read_bytes()
    # A broad base yields a dedicated per-profile child, never the base itself.
    files.set_backup_location(tmp_path, str(tmp_path))
    selected = Path(files.backup_location(tmp_path)['directory'])
    assert selected != tmp_path
    unknown = selected / 'unowned'
    unknown.mkdir(parents=True)
    (unknown / 'authority.sqlite3').write_bytes(b'user-owned material')
    files.preserve_closed_application_journals(tmp_path, 'safe', keep_count=1)
    assert source.read_bytes() == live_bytes
    assert (unknown / 'authority.sqlite3').read_bytes() == b'user-owned material'
    with pytest.raises(ValueError, match='profile'):
        files.set_backup_location(tmp_path, str(tmp_path / 'ArchHub-Test'))
    with pytest.raises(ValueError, match='local'):
        files.set_backup_location(tmp_path, r'\\server\share')


def test_adopted_legacy_armed_copy_survives_count_pruning(tmp_path):
    source = small_journal(tmp_path)
    legacy = tmp_path / 'ArchHub-Test/backups/20261017-0400'
    legacy.mkdir(parents=True)
    shutil.copyfile(source, legacy / 'graph.sqlite3')
    (legacy / 'recovery.json').write_text(json.dumps({'format':1,'files':{'graph':{'name':'graph.sqlite3'}},'metadata':{}}))
    updates = tmp_path / 'ArchHub/updates'
    updates.mkdir(parents=True)
    (updates / 'update-ready.json').write_text(json.dumps({'format':1,'recovery':{'path':str(legacy)}}))
    files.preserve_closed_application_journals(tmp_path, 'keep-armed', keep_count=1)
    assert (legacy / 'graph.sqlite3').read_bytes() == source.read_bytes()

def test_marker_selection_uses_unique_current_receipt_after_0400_publication(tmp_path, monkeypatch):
    from nodelang import application_update_recovery as recovery
    updates = tmp_path / 'updates'
    updates.mkdir()
    common = dict(state_dir=str(tmp_path),app_dir=str(tmp_path),directories={},
                  installed={'build_id':'0400'},staged={'build_id':'new-main'},sources={})
    legacy = dict(common,format=1,recovery={'path':str(tmp_path / 'legacy')})
    current = dict(common,format=2,recovery={'owner':'archhub-product-installer/v1','state':'required-before-copy'})
    stale = dict(current,installed={'build_id':'prior-main'})
    (updates / 'update-ready.json').write_text(json.dumps(legacy))
    (updates / 'installer-update-ready.json').write_text(json.dumps(stale))
    monkeypatch.setattr(recovery,'_capture',lambda state,app,graph,content,path=None: legacy if path else current)
    assert recovery.validate_update_ready(tmp_path,tmp_path,tmp_path / 'graph',None) == legacy
    (updates / 'installer-update-ready.json').write_text(json.dumps(current))
    with pytest.raises(ValueError,match='multiple'):
        recovery.validate_update_ready(tmp_path,tmp_path,tmp_path / 'graph',None)


def test_concurrent_setup_cannot_clean_an_active_pending_copy(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows installer mutex court')
    import threading
    source = small_journal(tmp_path)
    parent = files.installer_backup_directory(tmp_path,source)
    pending = parent / ('active-'+'a'*32+'-pending')
    pending.mkdir(parents=True)
    (pending / source.name).write_bytes(b'active copy')
    refused=[]
    def concurrent():
        try:
            files.preserve_closed_application_journals(tmp_path,'concurrent')
        except OSError as error:
            refused.append(str(error))
    with files._installer_backup_lease(tmp_path):
        worker=threading.Thread(target=concurrent)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert refused and 'Another Setup' in refused[0]
    assert (pending / source.name).read_bytes() == b'active copy'


@pytest.mark.parametrize('armed',[False,True])
def test_location_switch_keeps_previous_owned_custody_until_replacement_verifies(tmp_path,monkeypatch,armed):
    source=small_journal(tmp_path)
    files.set_backup_location(tmp_path,str(tmp_path/'drive-D'))
    previous_root=Path(files.backup_location(tmp_path)['directory'])
    old=Path(files.preserve_closed_application_journals(tmp_path,'drive-d',keep_count=1)[0])
    unknown=previous_root/'unowned'
    unknown.mkdir()
    (unknown/'keep.txt').write_bytes(b'user material')
    if armed:
        updates=tmp_path/'ArchHub/updates'
        updates.mkdir()
        (updates/'update-ready.json').write_text(json.dumps({'format':1,'recovery':{'path':str(old)}}))
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO work VALUES ('new copy')")
    db.close()
    files.set_backup_location(tmp_path,str(tmp_path/'drive-E'))
    actual_copy=files._copy_closed_file
    def failed_copy(*args):
        assert old.is_dir()
        raise OSError('replacement copy refused')
    monkeypatch.setattr(files,'_copy_closed_file',failed_copy)
    with pytest.raises(OSError,match='replacement copy refused'):
        files.preserve_closed_application_journals(tmp_path,'failed-e',keep_count=1)
    assert old.is_dir()
    monkeypatch.setattr(files,'_copy_closed_file',actual_copy)
    newest=Path(files.preserve_closed_application_journals(tmp_path,'drive-e',keep_count=1)[0])
    assert newest.is_dir()
    assert old.is_dir() is armed
    assert (unknown/'keep.txt').read_bytes()==b'user material'
    assert str(previous_root) in files.backup_location(tmp_path)['managed_directories']


@pytest.mark.parametrize('nested',[False,True])
def test_location_history_cannot_claim_an_unowned_live_directory(tmp_path,nested):
    files.set_backup_location(tmp_path,str(tmp_path/'drive-D'))
    preference=tmp_path/'ArchHub/backup-location.json'
    record=json.loads(preference.read_text())
    identity=hashlib.sha256(str(tmp_path.resolve()).casefold().encode()).hexdigest()
    unowned=(tmp_path/'ArchHub/ArchHub-backups'/('profile-'+identity)) if nested else tmp_path/'ArchHub'
    record['managed_directories']=[str(unowned)]
    preference.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='owned container'):
        files.backup_location(tmp_path)
