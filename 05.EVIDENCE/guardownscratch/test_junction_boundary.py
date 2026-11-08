"""Real Windows reparse boundaries, using the lane's existing isolated rig."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '01.APP'), str(ROOT / '02.TESTS/tests_replica')]
from test_guard_own_scratch import rig as isolated_rig, hook
from nodelang import hook_decision as hd

rig = pytest.fixture(isolated_rig.__wrapped__)


def junction(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                   check=True, capture_output=True)
    assert link.lstat().st_file_attributes & 0x400


@pytest.mark.parametrize('command', ['Remove-Item -LiteralPath "{target}" -Recurse',
                                    'rm -rf "{plain}" "{target}"',
                                    'rm -rf "{target}" "{plain}"'])
def test_reviewer_alias_refused(rig, command):
    _, temp, workspace, env = rig
    target = workspace / '70.COMPANY/72.HANDOFFS/preexisting.txt'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'preexisting protected bytes')
    before = target.stat().st_mtime_ns
    alias = temp / 'claude/junction-to-own-synthetic-workspace'
    junction(alias, workspace)
    path = alias / target.relative_to(workspace)
    plain = temp / 'plain.txt'
    plain.write_bytes(b'scratch')
    command = command.format(target=path, plain=plain)
    assert str(path) in hd._delete_targets(command, str(workspace))
    assert hd.founder_data_targeted(command, str(workspace), env)
    assert not hook(rig, path, command=command)[0]
    assert target.read_bytes() == b'preexisting protected bytes'
    assert target.stat().st_mtime_ns == before


def test_disposable_junction_allowed(rig):
    _, temp, workspace, env = rig
    target = temp / 'other-disposable/file.txt'
    target.parent.mkdir()
    target.write_bytes(b'scratch')
    link = temp / 'claude/disposable-link'
    junction(link, target.parent)
    path = link / target.name
    assert not hd.founder_data_targeted(f'Remove-Item -LiteralPath "{path}"', str(workspace), env)
    assert hook(rig, path)[0]


def test_plain_temp_allowed(rig):
    _, temp, _, _ = rig
    target = temp / 'plain.txt'
    target.write_bytes(b'scratch')
    assert hook(rig, target)[0]


def test_protected_alias_to_temp_stays_protected(rig):
    _, temp, workspace, env = rig
    target = temp / 'disposable/file.txt'
    target.parent.mkdir()
    target.write_bytes(b'scratch')
    link = workspace / '70.COMPANY/protected-link'
    junction(link, target.parent)
    path = link / target.name
    assert hd.founder_data_targeted(f'Remove-Item -LiteralPath "{path}"', str(workspace), env)


def test_inner_junction_cleanup_preserves_target(rig):
    _, temp, workspace, _ = rig
    lane = temp / 'lane-inner-junction-proof'
    target = workspace / '70.COMPANY/retained/bytes.bin'
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes(range(256)))
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    for relative in ('node_modules', 'target/msvc'):
        junction(lane / relative, target.parent)
    (lane / 'scratch.txt').write_bytes(b'disposable')
    assert lane.resolve().is_relative_to(temp.resolve())
    assert hook(rig, lane, recurse=True)[0]
    shutil.rmtree(lane)
    assert not lane.exists()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
    print(f'INNER-JUNCTION python: lane removed; target bytes survive; SHA256={before}')


def test_unreadable_resolution_refused(rig):
    _, temp, workspace, env = rig
    link = temp / 'claude/dangling-junction'
    junction(link, temp / 'missing-target')
    path = link / 'missing.txt'
    assert hd.founder_data_targeted(f'Remove-Item -LiteralPath "{path}"', str(workspace), env)
    assert not hook(rig, path)[0]


def test_resolution_access_denied_refused(rig, monkeypatch):
    _, temp, workspace, env = rig
    target = workspace / '70.COMPANY/retained'
    target.mkdir(parents=True)
    link = temp / 'claude/unreadable-junction'
    junction(link, target)
    original = Path.resolve

    def denied(path, *args, **kwargs):
        if path == link:
            raise PermissionError('resolution access denied')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', denied)
    assert hd.founder_data_targeted(f'Remove-Item -LiteralPath "{link}"', str(workspace), env)
