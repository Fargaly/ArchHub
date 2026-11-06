"""Disposable test state, run attribution and a final real-profile scan."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

import pytest

# Use the existing child wrapper so grandchildren keep the same provenance.
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / '03.TOOLS'),
                str(Path(__file__).resolve().parent / 'tests')]
from tools.real_app_check.profile_guard import install
from test_state_isolation import _sessions_snapshot, _profile_leaks, _run_context


def pytest_configure(config):
    """Collection precedes fixtures, so prepare their guarded context before imports."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Volatile Environment') as key:
        home = Path(winreg.QueryValueEx(key, 'USERPROFILE')[0])
        local = Path(winreg.QueryValueEx(key, 'LOCALAPPDATA')[0])
    directory = Path(__file__).resolve().parents[1] / '.cache' / 'testiso-release'
    directory.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='pytest-', dir=directory))
    sentinel = root / 'sentinel'
    sentinel.mkdir()
    state = root / 'state'
    state.mkdir()
    temporary = root / 'tmp'
    temporary.mkdir()
    protected = [home / 'ArchHub', home / '.archhub', local / 'ArchHub', sentinel]
    marker = str(uuid4())
    context = {'before': {str(path): _sessions_snapshot(path) for path in protected},
               'run': {'marker': marker, 'started': time.time(), 'pids': [str(os.getpid())],
                       'sessions': [marker + ':' + str(os.getpid())]}}
    baseline = root / 'profile-snapshot.json'
    baseline.write_text(json.dumps(context), encoding='utf-8')
    log = root / 'writes.jsonl'
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    config._testiso_context = context
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
        patch.setenv(name, str(sentinel))
    for name in ('TEMP', 'TMP'):
        patch.setenv(name, str(temporary))
    for name, value in {
        'ARCHHUB_TEST_STATE_DIR': str(state),
        'ARCHHUB_TEST_RUN_ID': marker,
        'ARCHHUB_TEST_PROCESS_DIR': str(root / 'processes'),
        'ARCHHUB_TEST_PROFILE_SNAPSHOT': str(baseline),
        'ARCHHUB_PROFILE_GUARD_ROOTS': json.dumps([str(path) for path in protected]),
        'ARCHHUB_PROFILE_GUARD_LOG': str(log),
        'ARCHHUB_TEST_SECRET_STORE': 'memory',
        'PYTHONDONTWRITEBYTECODE': '1',
    }.items():
        patch.setenv(name, value)
    patch.setattr(subprocess, 'Popen', subprocess.Popen)
    install()


@pytest.fixture(scope='session', autouse=True)
def testiso_run(request):
    """Own the final scan regardless of the scan test's position in the release list."""
    yield request.config._testiso_context
    context = _run_context()
    leaks = _profile_leaks(context['before'], context['run'], time.time())
    report = Path(os.environ['ARCHHUB_TEST_PROFILE_SNAPSHOT']).with_name('profile-leaks.json')
    report.write_text(json.dumps(leaks, indent=2), encoding='utf-8')
    assert not leaks, 'Test writes reached real profiles: ' + json.dumps(leaks)
    log = Path(os.environ['ARCHHUB_PROFILE_GUARD_LOG'])
    assert not log.exists() or not log.stat().st_size, 'Protected profile write attempts'
    request.config.pluginmanager.get_plugin('terminalreporter').write_line(
        'TESTISO final profile leaks: ' + json.dumps(leaks) + '; protected write attempts: 0')


@pytest.fixture(autouse=True)
def test_state_directory(tmp_path, monkeypatch, testiso_run):
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    # Exercise the normal default, without changing a user's saved settings.
    (state / 'settings').mkdir()
    (state / 'settings' / 'settings.json').write_text(
        json.dumps({'sessionsFolder': str(state / 'Sessions')}), encoding='utf-8')
