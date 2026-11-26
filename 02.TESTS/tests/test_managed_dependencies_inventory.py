"""Settings > This PC > Dependencies: Check all reads the npm agent-tool inventory, also on a profile with no global npm folder."""
import json
from pathlib import Path


def _npm(root, listed, calls):
    def run(args):
        calls.append(args[0])
        if args[0] == 'root':
            return str(root) + '\n'
        if args[0] == 'ls':
            if not Path(root).is_dir():
                raise ValueError('npm refused the operation: npm error code ENOENT')
            return json.dumps({'dependencies': listed})
        if args[0] == 'view':
            return json.dumps('2.0.0')
        raise AssertionError(args)
    return run


def test_a_profile_without_a_global_npm_folder_reads_every_tool_as_not_installed(tmp_path):
    from nodelang.managed_dependencies import ManagedDependencies, PACKAGES
    calls = []
    owner = ManagedDependencies(run=_npm(tmp_path / 'npm' / 'node_modules', {}, calls), find=lambda exe: None)
    rows = owner.check()
    assert [row['id'] for row in rows] and {row['state'] for row in rows} == {'Not installed'}
    assert {row['id'] for row in rows} <= set(PACKAGES)
    assert 'ls' not in calls, 'npm ls is not asked about a global folder that does not exist'


def test_an_installed_tool_reads_its_version_from_the_inventory(tmp_path):
    from nodelang.managed_dependencies import ManagedDependencies, PACKAGES
    root = tmp_path / 'npm' / 'node_modules'
    root.mkdir(parents=True)
    calls = []
    listed = {PACKAGES['codex']: {'version': '1.0.0'}}
    rows = ManagedDependencies(run=_npm(root, listed, calls), find=lambda exe: 'C:/tools/' + exe).check()
    codex = next(row for row in rows if row['id'] == 'codex')
    assert codex['state'] == 'Update ready' and codex['version'] == '1.0.0' and codex['availableVersion'] == '2.0.0'
    assert 'ls' in calls


def test_a_tool_from_its_own_installer_is_ready_and_a_lost_npm_executable_needs_repair(tmp_path):
    from nodelang.managed_dependencies import ManagedDependencies, PACKAGES
    root = tmp_path / 'npm' / 'node_modules'
    root.mkdir(parents=True)
    listed = {PACKAGES['opencode']: {'version': '2.0.0'}}
    found = {'codex'}   # Codex installed by its own installer; OpenCode listed by npm, its executable gone
    rows = {row['id']: row for row in ManagedDependencies(run=_npm(root, listed, []),
            find=lambda exe: 'C:/tools/' + exe if any(exe.startswith(f) for f in found) else None).check()}
    assert rows['codex']['state'] == 'Ready' and rows['codex']['version'] == 'External installation'
    assert rows['opencode']['state'] == 'Needs repair'
