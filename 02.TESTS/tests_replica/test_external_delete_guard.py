"""Hermetic external-guard candidate main(), committed snapshot + patch only.

Real Windows process/junction checks complement injected inventory failures.
This does not execute or accept the installed external hook.
"""
import importlib.util
import io
import json
import shutil
import subprocess
import sys

import pytest

from test_guard_own_scratch import ROOT, rig as isolated_rig, trace_write

rig = pytest.fixture(isolated_rig.__wrapped__)


@pytest.fixture(scope='module')
def committed_inputs():
    prefix = '05.EVIDENCE/guardownscratch/'
    return {name: subprocess.run(['git', 'show', 'HEAD:' + prefix + name], cwd=ROOT,
                                 check=True, capture_output=True).stdout
            for name in ('delete_guard.snapshot.txt', 'delete_guard.patch')}


@pytest.fixture
def guards(tmp_path, committed_inputs):
    directory = tmp_path / 'external-guard'
    directory.mkdir()
    snapshot = directory / 'delete_guard.snapshot.py'
    snapshot.write_bytes(committed_inputs['delete_guard.snapshot.txt'])
    candidate = directory / 'delete_guard.py'
    candidate.write_bytes(snapshot.read_bytes())
    patch = directory / 'delete_guard.patch'
    patch.write_bytes(committed_inputs['delete_guard.patch'])
    for args in (['--check'], []):
        result = subprocess.run(['git', 'apply', '--no-index', *args, str(patch)],
                                cwd=directory, capture_output=True, text=True)
        assert result.returncode == 0, (result.stdout, result.stderr)
    modules = []
    for path in (snapshot, candidate):
        spec = importlib.util.spec_from_file_location('guard_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def invoke(guard, rig, path, monkeypatch, capsys, *, session='owner'):
    for name, value in rig[3].items():
        monkeypatch.setenv(name, value)
    event = {'session_id': session, 'tool_name': 'PowerShell', 'cwd': str(rig[2]),
             'tool_input': {'command': f'Remove-Item -LiteralPath "{path}" -Recurse'}}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(event)))
    result = guard.main()
    captured = capsys.readouterr()
    assert result in (0, 2), captured
    return result, captured.err


def owned_marked_scratch(rig):
    root = rig[1] / 'claude/project/owner/scratchpad/build'
    trace_write(rig, root / '.git/HEAD', 'ref: refs/heads/main\n')
    return root


def inventory(monkeypatch, *, code=0, output='[]', error=None):
    def run(*args, **kwargs):
        assert args[0][0] == 'powershell', args
        if error:
            raise error
        return subprocess.CompletedProcess(args[0], code, stdout=output, stderr='')
    monkeypatch.setattr(subprocess, 'run', run)


def test_patch_applies_cleanly_to_committed_snapshot(guards):
    old, candidate = guards
    assert old.__file__ != candidate.__file__
    assert old._targets('rm -rf "C:/temp/probe"') == candidate._targets('rm -rf "C:/temp/probe"')


def test_live_other_process_still_refuses_owned_scratch(rig, guards, monkeypatch, capsys):
    root = owned_marked_scratch(rig)
    from nodelang import hook_decision as hd
    assert hd._trace_cleanup_target(root, str(rig[2]), rig[3], 'owner')
    process = subprocess.Popen([sys.executable, '-B', '-c',
                                'import time; time.sleep(60)', str(root)], env=rig[3])
    try:
        result, reason = invoke(guards[1], rig, root, monkeypatch, capsys)
        assert result == 2
        assert f'pid {process.pid} ' in reason and 'in use by' in reason
        assert (root / '.git/HEAD').exists()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_shared_lane_keeps_marker_refusal(rig, guards, monkeypatch, capsys):
    root = rig[1] / 'lane-shared'
    trace_write(rig, root / '.git/HEAD', 'ref: refs/heads/main\n')
    inventory(monkeypatch)
    result, reason = invoke(guards[1], rig, root, monkeypatch, capsys)
    assert result == 2 and 'active lane files' in reason


@pytest.mark.parametrize('family', [False, True])
def test_changed_scratch_cannot_waive_live_marker(rig, guards, monkeypatch, capsys, family):
    root = rig[1] / 'claude/project/owner/scratchpad/build'
    session = 'child' if family else 'owner'
    parent = 'owner' if family else None
    trace_write(rig, root / '.git/HEAD', 'ref: refs/heads/main\n', session=session, parent=parent)
    trace_write(rig, root / 'content.txt', session=session, parent=parent)
    from nodelang import hook_decision as hd
    assert hd._trace_cleanup_target(root, str(rig[2]), rig[3], session)
    trace_write(rig, root / 'content.txt', 'other bytes\n', session='other')
    assert not hd._trace_cleanup_target(root, str(rig[2]), rig[3], session)
    inventory(monkeypatch)
    result, reason = invoke(guards[1], rig, root, monkeypatch, capsys, session=session)
    assert result == 2 and 'active lane files' in reason


@pytest.mark.parametrize('case', ['nonzero', 'empty-output', 'malformed', 'null', 'missing-fields', 'timeout'])
def test_inventory_unknown_keeps_live_marker_refusal(rig, guards, monkeypatch, capsys, case):
    root = owned_marked_scratch(rig)
    output = {'nonzero': '[]', 'empty-output': '', 'malformed': '{', 'null': 'null',
              'missing-fields': '[{}]', 'timeout': '[]'}[case]
    inventory(monkeypatch, code=1 if case == 'nonzero' else 0, output=output,
              error=subprocess.TimeoutExpired('inventory', 20) if case == 'timeout' else None)
    result, reason = invoke(guards[1], rig, root, monkeypatch, capsys)
    assert result == 2 and 'active lane files' in reason


def test_verified_empty_inventory_allows_owned_marked_scratch(rig, guards, monkeypatch, capsys):
    root = owned_marked_scratch(rig)
    inventory(monkeypatch)
    assert invoke(guards[0], rig, root, monkeypatch, capsys)[0] == 2
    assert invoke(guards[1], rig, root, monkeypatch, capsys) == (0, '')


@pytest.mark.parametrize('case', ['empty', 'unavailable', 'live-user'])
def test_legacy_no_marker_result_unchanged(rig, guards, monkeypatch, capsys, case):
    root = rig[1] / 'ordinary-temp'
    root.mkdir()
    (root / 'bytes.txt').write_bytes(b'ordinary scratch')
    output = f'123456\t0\tworker.exe\tworker "{root}"' if case == 'live-user' else ''
    inventory(monkeypatch, output=output,
              error=OSError('inventory unavailable') if case == 'unavailable' else None)
    before = invoke(guards[0], rig, root, monkeypatch, capsys)
    after = invoke(guards[1], rig, root, monkeypatch, capsys)
    assert after == before
    assert after[0] == (2 if case == 'live-user' else 0)


@pytest.mark.parametrize('engine', ['python', 'powershell'])
def test_temp_lane_inner_junctions_are_not_followed(rig, guards, monkeypatch, capsys, engine):
    lane = rig[1] / 'lane-inner-junctions'
    target = rig[2] / '70.COMPANY/retained/bytes.bin'
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes(range(256)))
    before = target.stat().st_mtime_ns
    for relative in ('node_modules', 'target/msvc'):
        link = lane / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target.parent)],
                       check=True, capture_output=True)
        assert link.is_junction()
    # A marker in the protected target must never be scanned through the junction.
    marker = target.parent / 'PROGRESS.md'
    marker.write_bytes(b'protected active work')
    links, live = guards[1]._scan(lane)
    # The bounded scan skips target/ entirely; scanning that directory still stops at msvc.
    assert links == [str(lane / 'node_modules')] and live == []
    nested_links, nested_live = guards[1]._scan(lane / 'target')
    assert nested_links == [str(lane / 'target/msvc')] and nested_live == []
    assert invoke(guards[1], rig, lane, monkeypatch, capsys) == (0, '')
    assert lane.resolve().is_relative_to(rig[1].resolve())
    if engine == 'python':
        shutil.rmtree(lane)
    else:
        powershell = shutil.which('pwsh')
        assert powershell, 'PowerShell 7 must be on PATH'
        subprocess.run([powershell, '-NoProfile', '-Command',
                        'Remove-Item -LiteralPath $env:ARCHHUB_TEST_DELETE_LANE -Recurse -Force'],
                       check=True, capture_output=True, timeout=30,
                       env=dict(rig[3], ARCHHUB_TEST_DELETE_LANE=str(lane)))
    assert not lane.exists()
    assert target.read_bytes() == bytes(range(256))
    assert target.stat().st_mtime_ns == before
    assert marker.read_bytes() == b'protected active work'
