"""TESTISO: the test-state override owns every application write destination."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_state_override_isolates_owners(tmp_path):
    sentinel = tmp_path / 'sentinel'
    sentinel.mkdir()
    state = tmp_path / 'state'
    state.mkdir(exist_ok=True)
    env = dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(state),
               ARCHHUB_STATE_DIR=str(sentinel / 'wrong-state'),
               USERPROFILE=str(sentinel), HOME=str(sentinel),
               LOCALAPPDATA=str(sentinel), APPDATA=str(sentinel),
               PYTHONDONTWRITEBYTECODE='1')
    # Fail before any owner can create a file outside the selected state.
    probe = r'''
import os, sys
from pathlib import Path
sys.path[:0] = ['01.APP', '03.TOOLS']
from tools.real_app_check.profile_guard import install
state = Path(os.environ['ARCHHUB_TEST_STATE_DIR'])
install(state / 'guard.jsonl', protected=[os.environ['USERPROFILE']])
from nodelang import session_files, agent_budget, settings_owner, workshop_mailbox
assert session_files._default_sessions_directory().is_relative_to(state), 'sessions escape test state'
assert agent_budget.router_database().is_relative_to(state), 'router database escapes test state'
assert settings_owner.router_settings_path().is_relative_to(state), 'router settings escape test state'
assert workshop_mailbox.profile_database().is_relative_to(state), 'workshop escapes test state'
sessions = session_files.sessions_directory()
assert sessions.is_relative_to(state)
with agent_budget.connect() as db:
    assert db.execute('SELECT count(*) FROM requests').fetchone() == (0,)
from nodelang.model_router import _application_state_dir
assert _application_state_dir() == state
from nodelang import brain_files, persistence, workshop_config
from nodelang.runtime_credentials import BrowserCredentialVault
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.cell_revision_checkpoint import RevisionCheckpointGuard
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.checkpoint_authority_provisioning import default_checkpoint_authority_path
from nodelang.user_paths import state_directory
for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
    os.environ.pop(name, None)
for path in (brain_files._path(), persistence.default_state_path(),
             persistence.application_database_path(), workshop_config.app_state_dir(),
             BrowserCredentialVault.default_path(), WindowsDpapiCallerKeyStore.default_path(),
             WindowsDpapiSigningKeyProvider.default_path(),
             RevisionCheckpointGuard.default_path(state / 'journal.sqlite3'),
             default_checkpoint_authority_path(state / 'journal.sqlite3'),
             session_files.SessionFiles().metadata):
    assert path.is_relative_to(state), str(path)
from nodelang.quiet_update import _profile_instance
lock = _profile_instance(state)
try:
    assert lock.handle is not None, 'isolated recovery selected an existing profile mutex'
finally:
    lock.close()
for invalid in ('relative-state', '', '~'):
    os.environ['ARCHHUB_TEST_STATE_DIR'] = invalid
    try:
        state_directory()
    except ValueError:
        pass
    else:
        raise AssertionError('invalid test state was accepted: ' + repr(invalid))
'''
    before = _snapshot(sentinel)
    result = subprocess.run([sys.executable, '-B', '-c', probe], env=env,
                            capture_output=True, text=True, timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert _snapshot(sentinel) == before
    assert result.returncode == 0, result.stdout + result.stderr


def _snapshot(root):
    """Read metadata only; never create, repair, or remove profile contents."""
    if not root.exists():
        return None
    result = {}
    def walk(directory):
        with os.scandir(directory) as entries:
            for entry in entries:
                stat = entry.stat(follow_symlinks=False)
                result[os.path.relpath(entry.path, root)] = [stat.st_mtime_ns, stat.st_size]
                if entry.is_dir(follow_symlinks=False) and not os.path.isjunction(entry.path):
                    walk(entry.path)
    stat = root.stat()
    result['.'] = [stat.st_mtime_ns, stat.st_size]
    walk(root)
    return result


def test_release_profiles_unchanged():
    baseline = os.environ.get('ARCHHUB_TEST_PROFILE_SNAPSHOT')
    if not baseline:
        pytest.skip('Run this file as the release wrapper to compare profile snapshots')
    before = json.loads(Path(baseline).read_text(encoding='utf-8'))
    changed = {}
    for root, old in before.items():
        new = _snapshot(Path(root))
        if old != new:
            changed[root] = sorted(name for name in (old or {}).keys() | (new or {}).keys()
                                   if (old or {}).get(name) != (new or {}).get(name))
    assert not changed, 'Profile file lists or mtimes changed: ' + json.dumps(changed)


if __name__ == '__main__':
    # Run inside run-heavy. The guard is installed before pytest collection,
    # and is inherited by Python children through the existing guard wrapper.
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Volatile Environment') as key:
        home = Path(winreg.QueryValueEx(key, 'USERPROFILE')[0])
        local = Path(winreg.QueryValueEx(key, 'LOCALAPPDATA')[0])
        roaming = Path(winreg.QueryValueEx(key, 'APPDATA')[0])
    protected = [home / 'ArchHub', home / '.archhub', local / 'ArchHub',
                 local / 'ArchHub-Test', roaming / 'ArchHub']
    root = Path('.cache/testiso-release').resolve()
    root.mkdir(parents=True, exist_ok=True)
    sentinel = root / 'sentinel'
    sentinel.mkdir(exist_ok=True)
    state = root / 'state'
    state.mkdir(exist_ok=True)
    temporary = root / 'tmp'
    temporary.mkdir(exist_ok=True)
    protected.append(sentinel)
    before = {}
    for path in protected:
        before[str(path)] = _snapshot(path)
        print('TESTISO snapshot: ' + str(path), flush=True)
    baseline = root / 'profile-snapshot.json'
    baseline.write_text(json.dumps(before), encoding='utf-8')
    env = dict(os.environ, USERPROFILE=str(sentinel), HOME=str(sentinel),
               LOCALAPPDATA=str(sentinel), APPDATA=str(sentinel),
               TEMP=str(temporary), TMP=str(temporary),
               ARCHHUB_TEST_STATE_DIR=str(state),
               ARCHHUB_TEST_PROFILE_SNAPSHOT=str(baseline),
               ARCHHUB_PROFILE_GUARD_ROOTS=json.dumps([str(p) for p in protected]),
               ARCHHUB_PROFILE_GUARD_LOG=str(root / 'writes.jsonl'),
               PYTHONDONTWRITEBYTECODE='1', ARCHHUB_TEST_SECRET_STORE='memory')
    os.environ.update(env)
    sys.path[:0] = ['01.APP', '03.TOOLS']
    from tools.real_app_check.profile_guard import install
    install()
    result = pytest.main(['-p', 'no:cacheprovider', '--ignore-glob=*',
                          '--basetemp=' + str(root / 'pytest'), *sys.argv[1:]])
    changed = {}
    for path in protected:
        old, new = before[str(path)], _snapshot(path)
        if old != new:
            changed[str(path)] = [name for name in (old or {}).keys() | (new or {}).keys()
                                  if (old or {}).get(name) != (new or {}).get(name)]
    (root / 'snapshot-changes.json').write_text(json.dumps(changed, indent=2), encoding='utf-8')
    print('TESTISO profile snapshots changed: ' + json.dumps(changed), flush=True)
    raise SystemExit(result or bool(changed))
