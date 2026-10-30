"""RELISO courts use synthetic profiles; no installed app or provider calls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / '03.TOOLS/tools/real_app_check'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_zero_idle_release_child_preserves_decoy_profile(tmp_path, monkeypatch):
    decoy = tmp_path / 'DECOY'
    for name, suffix in [('USERPROFILE', 'HOME'), ('HOME', 'HOME'), ('LOCALAPPDATA', 'LOCAL'),
                         ('APPDATA', 'ROAMING'), ('TEMP', 'TMP'), ('TMP', 'TMP')]:
        folder = decoy / suffix
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(folder))
    monkeypatch.delenv('ARCHHUB_PROFILE_GUARD_LOG', raising=False)
    from nodelang import workspace_roots_catalogue as roots
    home = decoy / 'HOME/.archhub'
    home.mkdir()
    (home / 'workspace-roots.json').write_bytes(b'{"roots":[{"path":"C:\\\\DECOY"}]}\r\n')
    (home / 'workspace-roots.pin').write_bytes(b'decoy unpinned projection\r\n')
    roots.AppWorkspaceRootSigner(roots.default_app_key_path()).public_blob()
    protected = (home, decoy / 'LOCAL/ArchHub/governance')
    before = [digest(p) for p in protected]
    gate = load('zero_idle_release', ROOT / '02.TESTS/tests/test_zero_idle_growth.py')
    state = tmp_path / 'RUN/STATE'
    state.mkdir(parents=True)
    # Run the release driver's exact app boot (nograph_launcher); nothing else.
    probe = tmp_path / 'BOOT.py'
    probe.write_text('import runpy\nns=runpy.run_path(' + repr(str(gate.DRIVER)) +
                     ',run_name="release_profile_probe")\nserver=ns["boot"]()\n'
                     'print("boot",server.public_url)\nserver.close()\n')
    gate.DRIVER = probe
    gate._run('profile-probe', ROOT / '01.APP', state)
    after = [digest(p) for p in protected]
    print('RELISO decoy pair/governance unchanged:', before == after)
    assert before == after, 'release child rewrote the decoy real workspace-roots profile'


@pytest.mark.parametrize('flags', [[], ['-I'], ['-E','-s']])
@pytest.mark.parametrize('area', ['HOME/.archhub', 'LOCAL/ArchHub/governance'])
def test_guard_refuses_caught_decoy_write_and_fails_process(tmp_path, flags, area):
    guard = load('profile_guard_court', TOOL / 'profile_guard.py')
    protected = tmp_path / 'DECOY' / area
    protected.mkdir(parents=True)
    sentinel = protected / 'workspace-roots.json'
    sentinel.write_text('preserve')
    env = {**os.environ, 'ARCHHUB_PROFILE_GUARD_LOG':str(tmp_path/'WRITES.jsonl'),
           'ARCHHUB_PROFILE_GUARD_ROOTS':json.dumps([guard._profile_path(protected)])}
    code = 'from pathlib import Path\ntry:\n Path('+repr(str(sentinel))+').write_text("bad")\nexcept AssertionError:\n pass\n'
    done = subprocess.run(guard.command([sys.executable, *flags, '-B', '-c', code]),
        env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 3, done.stderr
    assert sentinel.read_text() == 'preserve'
    assert 'PROFILE-WRITE-GUARD' in done.stderr
    assert (tmp_path/'WRITES.jsonl').stat().st_size > 0


def test_guarded_module_keeps_normal_import_path(tmp_path):
    guard = load('profile_guard_module', TOOL / 'profile_guard.py')
    (tmp_path/'probe_module.py').write_text('print("module reached")')
    env = {**os.environ, 'ARCHHUB_PROFILE_GUARD_LOG':str(tmp_path/'WRITES.jsonl')}
    env.pop('PYTHONPATH', None)
    done = subprocess.run(guard.command([sys.executable,'-B','-m','probe_module']),
        cwd=tmp_path,env=env,capture_output=True,text=True,timeout=20)
    assert done.returncode == 0, done.stderr
    assert 'module reached' in done.stdout


def test_parent_refuses_when_child_write_error_is_swallowed(tmp_path):
    guard = load('profile_guard_parent', TOOL / 'profile_guard.py')
    decoy = tmp_path/'DECOY/.archhub'
    decoy.mkdir(parents=True)
    target = decoy/'workspace-roots.json'
    target.write_text('preserve')
    receipt = tmp_path/'WRITES.jsonl'
    child = 'from pathlib import Path\ntry:\n Path('+repr(str(target))+').write_text("bad")\nexcept AssertionError:\n pass\n'
    parent = ('import sys,subprocess\nsys.path.insert(0,'+repr(str(TOOL))+')\n'
        'from profile_guard import install, command\ninstall('+repr(str(receipt))+')\n'
        'subprocess.run(command([sys.executable,"-B","-c",'+repr(child)+']),capture_output=True)\n')
    env = {**os.environ,'ARCHHUB_PROFILE_GUARD_ROOTS':json.dumps([guard._profile_path(decoy)])}
    env.pop('ARCHHUB_PROFILE_GUARD_LOG',None)
    done = subprocess.run([sys.executable,'-B','-c',parent],env=env,capture_output=True,text=True,timeout=20)
    assert done.returncode == 3, done.stderr
    assert target.read_text() == 'preserve'


def test_profile_cli_preserves_explicit_release_source(tmp_path):
    profile = tmp_path/'PROFILE'
    source = tmp_path/'SNAPSHOT'
    env = {**os.environ,'ARCHHUB_COURT_SOURCE':str(source),
           'ARCHHUB_OLD_GRAPH_SOURCE':str(tmp_path/'OLD')}
    env.pop('ARCHHUB_PROFILE_GUARD_LOG',None)
    code = 'import os,json; print(json.dumps(dict(os.environ)))'
    done = subprocess.run([sys.executable,'-B',str(TOOL/'profile_guard.py'),'--profile',str(profile),'-c',code],
        env=env,capture_output=True,text=True,timeout=20)
    assert done.returncode == 0, done.stderr
    selected = json.loads(done.stdout)
    assert selected['ARCHHUB_COURT_SOURCE'] == str(source)
    assert selected['ARCHHUB_OLD_GRAPH_SOURCE'] == env['ARCHHUB_OLD_GRAPH_SOURCE']
    for key in ('USERPROFILE','HOME','LOCALAPPDATA','APPDATA','TEMP','TMP','ARCHHUB_TEST_STATE_DIR'):
        assert Path(selected[key]).is_relative_to(profile)
