"""Settings > This PC: back up now, backup place, keep logs for N days, diagnostics."""
import json
import os
import time
import zipfile

import pytest

from nodelang import pc_maintenance as pm


def _state(tmp_path, **app):
    state = tmp_path / 'appstate'
    (state / 'settings').mkdir(parents=True)
    (state / 'settings' / 'settings.json').write_text(
        json.dumps({'applicationSettings': app, 'theme': 'dark-secret-value'}), encoding='utf-8')
    (state / 'settings' / 'router-token.json').write_text('{"t": "x"}', encoding='utf-8')
    return state


def _old_backup(dest, stamp, size):
    path = dest / f'archhub-backup-{stamp}.zip'
    path.write_bytes(b'x' * size)
    return path


def test_backup_zip_holds_settings_and_sessions_without_secret_files(tmp_path):
    state = _state(tmp_path, backup_count=3)
    sessions = tmp_path / 'sessions'
    (sessions / 'project').mkdir(parents=True)
    (sessions / 'a.archhub').write_text('{}', encoding='utf-8')
    (sessions / 'project' / 'b.archhub').write_text('{}', encoding='utf-8')
    (sessions / 'project' / 'deep').mkdir()
    (sessions / 'project' / 'deep' / 'c.archhub').write_text('{}', encoding='utf-8')
    dest = tmp_path / 'backups'
    result = pm.back_up_now(state, sessions, dest)
    with zipfile.ZipFile(result['path']) as zf:
        names = set(zf.namelist())
    assert names == {'settings/settings.json', 'sessions/a.archhub', 'sessions/project/b.archhub'}
    assert result['kept'] == 1 and result['removed'] == []
    assert not list(dest.glob('*.tmp'))


def test_backup_prunes_by_count_and_only_its_own_files(tmp_path):
    state = _state(tmp_path, backup_count=2)
    dest = tmp_path / 'backups'
    dest.mkdir()
    for stamp in ('20200101-000000', '20200102-000000', '20200103-000000'):
        _old_backup(dest, stamp, 10)
    (dest / 'mine.zip').write_bytes(b'keep')
    result = pm.back_up_now(state, tmp_path / 'none', dest)
    assert result['kept'] == 2
    assert sorted(result['removed']) == ['archhub-backup-20200101-000000.zip', 'archhub-backup-20200102-000000.zip']
    assert (dest / 'mine.zip').exists() and (dest / 'archhub-backup-20200103-000000.zip').exists()


def test_backup_prunes_by_space_but_keeps_the_new_one(tmp_path):
    state = _state(tmp_path, backup_count=10, backup_budget_bytes=1048576)
    dest = tmp_path / 'backups'
    dest.mkdir()
    for stamp in ('20200101-000000', '20200102-000000', '20200103-000000'):
        _old_backup(dest, stamp, 600 * 1024)
    result = pm.back_up_now(state, tmp_path / 'none', dest)
    assert result['kept'] == 2
    assert len(result['removed']) == 2 and os.path.exists(result['path'])
    # Even a budget below the new backup never deletes it.
    _old_backup(dest, '20200104-000000', 2 * 1024 * 1024)
    assert os.path.exists(pm.back_up_now(state, tmp_path / 'none', dest)['path'])


def test_backup_destination_resolution_and_errors(tmp_path, monkeypatch):
    assert pm.backup_destination('This PC', None, {}, state_dir=tmp_path) == tmp_path / 'Backups'
    assert pm.backup_destination('This PC', str(tmp_path / 'x'), {}) == tmp_path / 'x'
    assert pm.backup_destination('OneDrive', None, {'OneDrive': str(tmp_path)}) == tmp_path / 'ArchHub Backups'
    assert pm.backup_destination('Office server', str(tmp_path), {}) == tmp_path
    for place, folder, env in (('OneDrive', None, {}), ('OneDrive', None, {'OneDrive': str(tmp_path / 'gone')}),
                               ('Office server', None, {}), ('Office server', str(tmp_path / 'gone'), {}),
                               ('Dropbox', None, {})):
        with pytest.raises(ValueError):
            pm.backup_destination(place, folder, env)
    monkeypatch.setattr(pm, 'DRIVE_LETTERS', '')
    with pytest.raises(ValueError):
        pm.backup_destination('Google Drive', None, {})


def test_prune_logs_keeps_active_logs_and_removes_old_rotated(tmp_path):
    logs = tmp_path / 'logs'
    (logs / 'root').mkdir(parents=True)
    (logs / 'owner').mkdir()
    old = time.time() - 30 * 86400
    files = {'launcher.log': True, 'updates.log': True, 'owner/brain.log': True, 'owner/brain.log.1': False,
             'root/brain-20200101.log': False, 'root/launcher.log': True, 'owner/brain.log.2': True}
    for name in files:
        (logs / name).write_text('x', encoding='utf-8')
        if name != 'owner/brain.log.2':  # the one recent rotated log stays
            os.utime(logs / name, (old, old))
    removed = pm.prune_logs(tmp_path, 14)
    assert sorted(removed) == ['owner/brain.log.1', 'root/brain-20200101.log']
    for name, stays in files.items():
        assert (logs / name).exists() is stays
    for bad in (0, 91, '14'):
        with pytest.raises(ValueError):
            pm.prune_logs(tmp_path, bad)


def test_diagnostics_redacts_tokens_and_lists_setting_keys_only(tmp_path):
    state = _state(tmp_path, backup_count=3)
    (state / 'logs').mkdir()
    fake = 'sk-test' + 'A' * 24
    (state / 'logs' / 'brain.log').write_text(f'call with {fake} and Bearer abc.def ok\n', encoding='utf-8')
    (state / 'BUILD_ID').write_text('build-123\n', encoding='utf-8')
    result = pm.export_diagnostics(state, tmp_path / 'out' / 'diag.zip')
    with zipfile.ZipFile(result['path']) as zf:
        log = zf.read('logs/brain.log').decode()
        health = zf.read('health.json').decode()
    assert fake not in log and 'abc.def' not in log and log.count('[redacted]') == 2
    data = json.loads(health)
    assert data['build_id'] == 'build-123'
    assert data['settings_keys']['settings.json'] == ['applicationSettings', 'theme']
    assert 'dark-secret-value' not in health and '"x"' not in health
    assert result['files'] == ['logs/brain.log', 'health.json']
