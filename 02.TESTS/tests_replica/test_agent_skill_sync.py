"""Filesystem courts; the native CLI round trip is also run in the lane fixture."""
import json
from pathlib import Path

import pytest

from tools import agent_skill_sync as sync
from contextlib import contextmanager


@contextmanager
def held_windows_handle(path, *, directory=False):
    """Hold a real watcher-style handle without delete sharing."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x80000000, 3 if directory else 1,
                                None, 3, 0x02000000 if directory else 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='real Windows handles')
@pytest.mark.parametrize('legacy', [False, True])
def test_held_directory_archives_by_copy_and_updates_in_place(installation, legacy):
    source, home, native, _calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    target = home / '.agents/skills/sample'
    if legacy:
        (target / sync.OWNERSHIP_MARKER).unlink()
    (target / 'SKILL.md').write_bytes(b'---\nname: sample\n---\nstale held directory')
    (target / 'obsolete.txt').write_bytes(b'preserve me')
    before = sync._tree(target)
    with held_windows_handle(target, directory=True):
        result = sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
        assert not result['deferred']
        assert sync._contents(target) == sync._tree(source / 'skills/sample')
    assert any(sync._tree(a) == before for a in
               (home / '.archhub/skill-archive/agents').glob('sample-*'))


@pytest.mark.skipif(__import__('os').name != 'nt', reason='real Windows handles')
def test_locked_file_warns_once_continues_other_skills_and_retries(installation, capsys):
    source, home, native, _calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    target = home / '.agents/skills/sample'
    (target / 'SKILL.md').write_bytes(b'stale locked file')
    other = home / '.codex/skills/sample/SKILL.md'
    other.write_bytes(b'stale other runtime')
    before = sync._tree(target)
    capsys.readouterr()
    with held_windows_handle(target / 'SKILL.md'):
        result = sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
        assert result['deferred'] == [str(target)]
        assert sync._tree(target) == before
        assert other.read_bytes() == (source / 'skills/sample/SKILL.md').read_bytes()
        output = capsys.readouterr().out
        assert output.count('SKILLSYNC WARNING: skill in use; retry next commit:') == 1
        assert str(target) in output and 'SKILLSYNC REFUSED' not in output
    assert any(sync._tree(a) == before for a in
               (home / '.archhub/skill-archive/agents').glob('sample-*'))
    assert not sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)['deferred']
    assert sync._contents(target) == sync._tree(source / 'skills/sample')


def test_malformed_source_version_refused_without_claude(installation, monkeypatch):
    source, home, _native, _calls = installation
    metadata = source / '.claude-plugin/plugin.json'
    metadata.write_text(json.dumps({'name': 'archhub', 'version': 'invalid'}))
    monkeypatch.setattr(sync.shutil, 'which', lambda _name: None)
    with pytest.raises(sync.SkillSyncRefused, match='numeric semantic version'):
        sync.synchronize(source, home)


@pytest.fixture
def installation(tmp_path):
    source, home = tmp_path / 'MARKET' / 'PLUGIN', tmp_path / 'HOME'
    skill = source / 'skills' / 'sample'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: fixture\n---\ncurrent\n')
    (skill / 'reference.txt').write_bytes(b'exact\r\nbytes\n')
    manifest = source / '.claude-plugin' / 'plugin.json'
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({'name': 'archhub', 'version': '0.1.1'}))
    market = source.parent / '.claude-plugin' / 'marketplace.json'
    market.parent.mkdir()
    market.write_text(json.dumps({'name': 'archhub-local', 'plugins': [
        {'name': 'archhub', 'source': './PLUGIN'}]}))
    calls = []

    def native(command, **kwargs):
        import shutil
        from subprocess import CompletedProcess
        calls.append(command)
        if command[1:4] == ['plugin', 'marketplace', 'add']:
            registry = home / '.claude/plugins/known_marketplaces.json'
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(json.dumps({'archhub-local': {'source': {
                'source': 'directory', 'path': str(source.parent)}, 'installLocation': str(source.parent)}}))
            return CompletedProcess(command, 0)
        data = json.loads(manifest.read_bytes())
        cache = home / '.claude/plugins/cache/archhub-local/archhub' / data['version']
        shutil.copytree(source, cache, dirs_exist_ok=True)
        registry = home / '.claude/plugins/installed_plugins.json'
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps({'version': 2, 'plugins': {'archhub@archhub-local': [
            {'scope': 'user', 'version': data['version'], 'installPath': str(cache)}]}}))
        return CompletedProcess(command, 0)

    return source, home, native, calls


def test_sync_then_refuse_each_runtime_drift(installation):
    source, home, native, calls = installation
    with pytest.raises(sync.SkillSyncRefused):
        sync.check(source, home)
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert sync.check(source, home)['skills'] == 1
    for relative in ('.codex/skills', '.agents/skills', '.config/opencode/skills'):
        target = home / relative / 'sample' / 'reference.txt'
        target.write_bytes(b'stale')
        with pytest.raises(sync.SkillSyncRefused, match='reference.txt'):
            sync.check(source, home)
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
        assert target.read_bytes() == b'exact\r\nbytes\n'
    assert len(calls) == 2  # marketplace add + install; no plugin churn for other runtimes


def test_updates_version_and_removes_obsolete_files_only(installation):
    source, home, native, calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    before = json.loads((source / '.claude-plugin/plugin.json').read_bytes())['version']
    unrelated = home / '.agents/skills/personal/SKILL.md'
    unrelated.parent.mkdir()
    unrelated.write_text('mine')
    (source / 'skills/sample/reference.txt').unlink()
    (source / 'skills/sample/SKILL.md').write_bytes(b'new content')
    with pytest.raises(sync.SkillSyncRefused):
        sync.check(source, home)
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert json.loads((source / '.claude-plugin/plugin.json').read_bytes())['version'] != before
    assert not (home / '.agents/skills/sample/reference.txt').exists()
    assert unrelated.read_text() == 'mine'
    assert sync.check(source, home)['skills'] == 1
    assert calls[-1][1:3] == ['plugin', 'update']


def test_shadow_and_same_version_cache_corruption(installation):
    source, home, native, calls = installation
    shadow = home / '.claude/skills/sample/SKILL.md'
    shadow.parent.mkdir(parents=True)
    shadow.write_text('stale shadow')
    (shadow.parent / '.archhub-skill-owner').write_text('archhub@archhub-local')
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert shadow.read_bytes() == (source / 'skills/sample/SKILL.md').read_bytes()
    record = json.loads((home / '.claude/plugins/installed_plugins.json').read_bytes())['plugins']['archhub@archhub-local'][0]
    (Path(record['installPath']) / 'skills/sample/SKILL.md').write_text('corrupt')
    with pytest.raises(sync.SkillSyncRefused):
        sync.check(source, home)
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert sync.check(source, home)['skills'] == 1
    assert calls[-1][1:3] == ['plugin', 'update']


@pytest.mark.parametrize('root', ['.claude/skills', '.opencode/skills', '.agents/skills',
                                  '.codex/skills', '.config/opencode/skills'])
@pytest.mark.parametrize('marker', [None, 'another-plugin'])
def test_foreign_same_name_folder_is_reported_and_untouched(installation, root, marker):
    source, home, native, _calls = installation
    foreign = home / root / 'sample'
    foreign.mkdir(parents=True)
    (foreign / 'SKILL.md').write_bytes(b'personal skill\r\n')
    if marker is not None:
        (foreign / '.archhub-skill-owner').write_text(marker)
    before = sync._tree(foreign)
    result = sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert sync._tree(foreign) == before
    assert str(foreign) in result['skipped']
    assert sync.check(source, home)['skipped'] == result['skipped']


@pytest.mark.parametrize('root', ['.claude/skills', '.opencode/skills'])
def test_marked_shadow_is_regenerated(installation, root):
    source, home, native, _calls = installation
    shadow = home / root / 'sample'
    shadow.mkdir(parents=True)
    (shadow / 'SKILL.md').write_text('stale owned copy')
    (shadow / '.archhub-skill-owner').write_text('archhub@archhub-local')
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert (shadow / 'SKILL.md').read_bytes() == (source / 'skills/sample/SKILL.md').read_bytes()
    assert (shadow / '.archhub-skill-owner').read_text() == 'archhub@archhub-local'


def test_failed_cli_never_reports_success(installation):
    from subprocess import CalledProcessError
    source, home, _native, _calls = installation
    def failed(command, **kwargs):
        raise CalledProcessError(1, command)
    with pytest.raises(CalledProcessError):
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=failed)
    assert not (home / '.codex/skills/sample').exists()


def test_redirect_refused_before_writes(installation, monkeypatch):
    source, home, native, calls = installation
    target = home / '.agents/skills/sample'
    from types import SimpleNamespace
    original = Path.lstat
    def redirected(path, *args, **kwargs):
        if path == target:
            return SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', redirected)
    with pytest.raises(sync.SkillSyncRefused, match='redirected'):
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert calls == []


def test_wrong_registered_marketplace_refused_before_version_write(installation):
    source, home, native, _calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    manifest = source / '.claude-plugin/plugin.json'
    before = manifest.read_bytes()
    registry = home / '.claude/plugins/known_marketplaces.json'
    registry.write_text(json.dumps({'archhub-local': {'source': {'source': 'github', 'repo': 'other/repo'}}}))
    with pytest.raises(sync.SkillSyncRefused, match='registered marketplace'):
        sync.check(source, home)
    with pytest.raises(sync.SkillSyncRefused, match='registered marketplace'):
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert manifest.read_bytes() == before


def test_registry_parent_traversal_refused(installation):
    source, home, native, _calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    registry = home / '.claude/plugins/installed_plugins.json'
    data = json.loads(registry.read_bytes())
    data['plugins']['archhub@archhub-local'][0]['installPath'] = str(
        home / '.claude/plugins/cache/archhub-local/archhub/../../../../OUTSIDE')
    registry.write_text(json.dumps(data))
    with pytest.raises(sync.SkillSyncRefused, match='outside its native cache'):
        sync.check(source, home)


def test_overlapping_source_output_refused_before_writes(installation):
    import shutil
    source, home, native, calls = installation
    overlapping = home / '.agents/skills/sample'
    overlapping.parent.mkdir(parents=True)
    shutil.copytree(source, overlapping)
    market = overlapping.parent / '.claude-plugin/marketplace.json'
    market.parent.mkdir()
    market.write_text(json.dumps({'name': 'archhub-local', 'plugins': [
        {'name': 'archhub', 'source': './sample'}]}))
    with pytest.raises(sync.SkillSyncRefused, match='overlap'):
        sync.synchronize(overlapping, home, runner=native)
    assert (overlapping / 'skills/sample/SKILL.md').exists()
    assert calls == []


def test_metadata_replace_failure_preserves_source(installation, monkeypatch):
    source, home, native, calls = installation
    metadata = source / '.claude-plugin/plugin.json'
    before = metadata.read_bytes()
    def refused(*args):
        raise OSError('replace refused')
    monkeypatch.setattr(sync.os, 'replace', refused)
    with pytest.raises(OSError, match='replace refused'):
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert metadata.read_bytes() == before
    assert list(metadata.parent.iterdir()) == [metadata]
    assert calls == []


def test_deleted_skill_is_retired_without_touching_unrelated_names(installation):
    import shutil
    source, home, native, _calls = installation
    remaining = source / 'skills/remaining'
    remaining.mkdir()
    (remaining / 'SKILL.md').write_text('remaining')
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    shutil.rmtree(source / 'skills/sample')
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    for root in ('.agents/skills', '.codex/skills', '.config/opencode/skills'):
        assert not (home / root / 'sample').exists()
        assert (home / root / 'remaining/SKILL.md').read_text() == 'remaining'
    assert sync.check(source, home)['skills'] == 1


def test_cli_exit_zero_without_published_bytes_is_refused(installation):
    from subprocess import CompletedProcess
    source, home, native, _calls = installation
    def unpublished(command, **kwargs):
        if command[1:4] == ['plugin', 'marketplace', 'add']:
            return native(command, **kwargs)
        return CompletedProcess(command, 0)
    with pytest.raises(sync.SkillSyncRefused, match='did not publish'):
        sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=unpublished)
    assert not (home / '.codex/skills/sample').exists()


def test_unreadable_source_directory_is_not_silently_omitted(installation, monkeypatch):
    source, _home, _native, _calls = installation
    blocked = source / 'skills/sample/references'
    blocked.mkdir()
    (blocked / 'rule.txt').write_text('required rule')
    original = sync.os.scandir
    def unreadable(path):
        if Path(path) == blocked:
            raise PermissionError('source directory unreadable')
        return original(path)
    monkeypatch.setattr(sync.os, 'scandir', unreadable)
    with pytest.raises(PermissionError, match='source directory unreadable'):
        sync._tree(source / 'skills')


@pytest.mark.parametrize('root', ['.agents/skills', '.codex/skills', '.config/opencode/skills',
                                  '.claude/skills', '.opencode/skills'])
def test_legacy_copy_adopted_and_archived(installation, root):
    source, home, native, _calls = installation
    target = home / root / 'sample'
    target.mkdir(parents=True)
    old = b'---\nname: sample\ndescription: old\n---\nold rules\n'
    (target / 'SKILL.md').write_bytes(old)
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert sync._contents(target) == sync._tree(source / 'skills/sample')
    assert sync._owned(target, 'archhub@archhub-local')
    archived = list((home / '.archhub/skill-archive' / root.split('/')[-2].lstrip('.')).glob('sample-*/SKILL.md'))
    assert len(archived) == 1 and archived[0].read_bytes() == old
    for scan in ('.agents/skills', '.codex/skills', '.config/opencode/skills', '.claude/skills', '.opencode/skills'):
        for path in (home / scan).rglob('SKILL.md'):
            assert path.parent.name == 'sample'
            assert sync._owned(path.parent, 'archhub@archhub-local')
            assert sync._contents(path.parent) == sync._tree(source / 'skills/sample')


def test_missing_cli_repairs_files_and_warns(installation, monkeypatch, capsys):
    source, home, _native, calls = installation
    monkeypatch.setattr(sync.shutil, 'which', lambda _name: None)
    result = sync.synchronize(source, home)
    assert result['native_skipped']
    assert calls == []
    assert sync._contents(home / '.codex/skills/sample') == sync._tree(source / 'skills/sample')
    assert 'WARNING' in capsys.readouterr().out
    assert sync.check(source, home)['native_skipped']


def test_foreign_warning_every_check(installation, capsys):
    source, home, native, _calls = installation
    target = home / '.agents/skills/sample'
    target.mkdir(parents=True)
    (target / 'SKILL.md').write_text('---\nname: personal\n---\nmy work')
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    for _ in range(2):
        capsys.readouterr()
        sync.check(source, home)
        assert str(target) in capsys.readouterr().out


def test_historical_skill_blob_adopted(installation):
    import subprocess
    source, home, native, _calls = installation
    old = b'legacy rule without frontmatter\n'
    path = source / 'skills/sample/SKILL.md'
    current = path.read_bytes()
    path.write_bytes(old)
    subprocess.run(['git', 'init', str(source)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Court', '-c',
                    'user.email=court@example.invalid', 'commit', '-m', 'legacy'],
                   check=True, capture_output=True)
    path.write_bytes(current)
    target = home / '.codex/skills/sample'
    target.mkdir(parents=True)
    (target / 'SKILL.md').write_bytes(old)
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    assert sync._contents(target) == sync._tree(path.parent)
    assert next((home / '.archhub/skill-archive/codex').glob('sample-*/SKILL.md')).read_bytes() == old


def test_clean_check_never_runs_a_cli(installation, monkeypatch):
    source, home, native, _calls = installation
    sync.synchronize(source, home, claude_executable=Path('claude.exe').absolute(), runner=native)
    def unexpected(*args, **kwargs):
        raise AssertionError('clean hash check spawned a CLI')
    monkeypatch.setattr(sync.subprocess, 'run', unexpected)
    assert sync.check(source, home, claude_executable=Path('claude.exe').absolute())['skills'] == 1
