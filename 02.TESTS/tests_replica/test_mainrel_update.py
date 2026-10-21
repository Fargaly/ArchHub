"""A quiet update arms closed journals without a second physical backup."""
import json
import sqlite3
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from nodelang import application_update_recovery as recovery


def test_arm_without_app_copy_preserves_drift_refusal(tmp_path):
    app, state = tmp_path / 'app', tmp_path / 'state'
    app.mkdir()
    updates = state / 'updates'
    updates.mkdir(parents=True)
    (app / 'BUILD_ID').write_text('old', encoding='ascii')
    (updates / 'staged.json').write_text(json.dumps({'build_id': 'new', 'sha256': 'a' * 64}))
    (updates / 'ArchHub-Setup-0.exe').write_bytes(b'fixture installer')
    source = state / 'authority.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE work (value TEXT)')
    marker = recovery.arm_update(state, app, source, None, expected_build='new')
    receipt = recovery.validate_update_ready(state, app, source, None)
    assert receipt['format'] == 2
    assert receipt['recovery'] == {'owner': 'archhub-product-installer/v1', 'state': 'required-before-copy'}
    assert marker.is_file()
    assert not list(tmp_path.rglob('backups'))
    from nodelang.backup_retention import protected_update_backups
    assert protected_update_backups(state, state / 'backups') == ()
    with sqlite3.connect(source) as database:
        database.execute("INSERT INTO work VALUES ('later edit')")
    with pytest.raises(ValueError, match='changed'):
        recovery.validate_update_ready(state, app, source, None)


@pytest.mark.parametrize('receipt', [
    {'format': 2, 'recovery': {'path': 'not-installer-custody'}},
    {'format': 3, 'recovery': {'path': 'not-a-supported-format'}},
])
def test_retention_refuses_malformed_installer_only_marker(tmp_path, receipt):
    from nodelang.backup_retention import protected_update_backups
    updates = tmp_path / 'updates'
    updates.mkdir()
    (updates / 'update-ready.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='invalid'):
        protected_update_backups(tmp_path, tmp_path / 'backups')


@pytest.mark.parametrize('close_refused', [False, True])
def test_desktop_shutdown_uses_one_recovery_owner_only_after_close(tmp_path, monkeypatch, close_refused):
    from tests_replica.test_baboom_startup_lifecycle import launcher_names
    actions, armed = [], []

    def close():
        actions.append('close')
        if close_refused:
            raise ValueError('close refused')

    def arm(*args, **kwargs):
        actions.append('arm')
        armed.append((args, kwargs))

    monkeypatch.setattr(recovery, 'arm_update', arm)
    source = Path(__file__).resolve().parents[2] / "01.APP/nodelang/launcher.py"
    owner = SimpleNamespace(close=close, conversation_content=SimpleNamespace(_path=None),
        application_update=SimpleNamespace(apply_on_quit=lambda: True,
            close=lambda **kwargs: True, confirmed_build='new'))
    callback = launcher_names('_finish_application_shutdown', server=owner,
        _baboom_stop=threading.Event(), _update_rollback_requested=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=lambda: actions.append('quiesce')),
        _machine_pointer=None, state_dir=tmp_path, state_path=tmp_path / 'authority.sqlite3',
        __file__=str(source), Path=Path)['_finish_application_shutdown']
    assert callback() is (not close_refused)
    assert actions == (['quiesce', 'close'] if close_refused else ['quiesce', 'close', 'arm'])
    assert len(armed) == (0 if close_refused else 1)
    if armed:
        assert armed[0] == ((tmp_path, source.parent, tmp_path / 'authority.sqlite3', None),
                            {'expected_build': 'new'})
