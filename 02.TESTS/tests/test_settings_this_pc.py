"""Settings > This PC rows: each one has an owner value that changes real behaviour."""
import json
import os
import zipfile

import pytest


def _settings(tmp_path):
    from nodelang.nograph_server import JsonFile
    return JsonFile(tmp_path / 'settings.json', {})


@pytest.mark.parametrize('identity,value', [
    ('Appearance.Theme set', 'Blueprint'), ('Appearance.Density', 'Compact'), ('Appearance.UI scale', 120),
    ('Appearance.Snap to grid', True), ('Appearance.Wires', 'On hover'), ('Appearance.Wire width', 3),
    ('Appearance.Panel colour', '#112233'), ('Appearance.Event socket colour', '#00aaff')])
def test_look_rows_save_in_the_settings_owner_and_read_back(tmp_path, identity, value):
    from nodelang.settings_owner import appearance_settings
    settings = _settings(tmp_path)
    rows = appearance_settings('setAppearance', [identity, value], settings)['appearanceSettings']
    row = next(r for r in rows if r['id'] == identity)
    assert row['value'] == value and row['overridden'] is True
    assert json.loads((tmp_path / 'settings.json').read_text(encoding='utf-8'))[row['storageKey']] == value


@pytest.mark.parametrize('identity,value', [
    ('Appearance.Theme set', 'Neon'), ('Appearance.UI scale', 200), ('Appearance.Wire width', 0),
    ('Appearance.Snap to grid', 'yes'), ('Appearance.Text colour', 'red')])
def test_look_rows_refuse_values_outside_their_limits(tmp_path, identity, value):
    from nodelang.nograph_server import Refused
    from nodelang.settings_owner import appearance_settings
    with pytest.raises(Refused):
        appearance_settings('setAppearance', [identity, value], _settings(tmp_path))


def test_every_look_row_is_also_a_setting_node():
    from nodelang.canvas_documents import thing_items
    ids = {row['setting']['id'] for row in thing_items() if row.get('setting')}
    assert {'Appearance.Theme set', 'Appearance.Snap to grid', 'Appearance.Wires', 'Appearance.UI scale'} <= ids


def test_install_when_i_quit_never_installs_while_the_window_is_open(tmp_path):
    from nodelang.application_update import ApplicationUpdate, default_update_policy, save_application_setting
    save_application_setting('update_install_when_idle', False, tmp_path)
    assert default_update_policy(tmp_path)['install_when_idle'] is False
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update._policy = lambda: default_update_policy(tmp_path)
    update._auto_allowed, update.reload = (lambda: True), (lambda: None)
    assert update.install_if_safe(user_idle=True) is False
    assert update.install_if_safe(closing=True) is True
    save_application_setting('update_install_when_idle', True, tmp_path)
    assert update.install_if_safe(user_idle=True) is True


def test_back_up_now_writes_to_the_chosen_folder(tmp_path, monkeypatch):
    from nodelang import session_files
    from nodelang.settings_owner import maintenance_settings
    state, sessions, target = tmp_path / 'appstate', tmp_path / 'sessions', tmp_path / 'backups'
    for folder in (state / 'settings', sessions, target):
        folder.mkdir(parents=True)
    (sessions / 'one.archhub').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(session_files, 'sessions_directory', lambda: sessions)
    settings = _settings(tmp_path)
    with pytest.raises(ValueError):
        maintenance_settings('setMaintenance', ['backupDir', str(tmp_path / 'missing')], settings, state)
    with pytest.raises(ValueError):
        maintenance_settings('setMaintenance', ['backupTo', 'Mars'], settings, state)
    maintenance_settings('setMaintenance', ['backupDir', str(target)], settings, state)
    held = maintenance_settings('backUpNow', [], settings, state)['maintenance']
    assert held['lastBackup']['path'].startswith(str(target))
    with zipfile.ZipFile(held['lastBackup']['path']) as archive:
        assert any(name.endswith('one.archhub') for name in archive.namelist())


def test_cache_size_removes_oldest_cache_files_first(tmp_path, monkeypatch):
    from nodelang import pc_maintenance
    from nodelang.pc_maintenance import prune_cache
    monkeypatch.setattr(pc_maintenance, '_GB', 1000)  # 1 "GB" = 1000 bytes: no large files on disk
    cache = tmp_path / 'cache'
    cache.mkdir()
    old, new = cache / 'old.bin', cache / 'new.bin'
    for path in (old, new):
        path.write_bytes(b'x' * 700)
    os.utime(old, (1, 1))
    assert prune_cache(tmp_path, 1) == ['old.bin'] and new.exists()
    with pytest.raises(ValueError):
        prune_cache(tmp_path, 0)
