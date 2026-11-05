"""Installed governance must not require the builder's workspace."""
from pathlib import Path

import pytest

from nodelang import workshop_gateway


def test_colleague_gateway_uses_shipped_sources(monkeypatch, tmp_path):
    from nodelang import workspace_roots_catalogue
    (tmp_path / '00.GOVERNANCE/03.AGENT-HOOKS').mkdir(parents=True)
    monkeypatch.delenv('ARCHHUB_GOVERNANCE_HOOKS_DIR', raising=False)
    monkeypatch.setattr(workspace_roots_catalogue, 'built_in_path', lambda: str(tmp_path))
    assert workshop_gateway.governance_dir() == Path(workshop_gateway.__file__).parent
    assert len(workshop_gateway.stamp()) == 64


def test_explicit_workspace_governance_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('ARCHHUB_GOVERNANCE_HOOKS_DIR', str(tmp_path))
    assert workshop_gateway.governance_dir() == tmp_path


def test_generated_rules_preserve_user_text_and_update_once(tmp_path):
    from nodelang.agent_onboard import install_rules
    root = tmp_path / 'install'
    (root / 'docs').mkdir(parents=True)
    spec = root / 'docs/SPEC.md'
    spec.write_text('1. Everything is a node.\n', encoding='utf-8')
    home = tmp_path / 'profile'
    (home / '.codex').mkdir(parents=True)
    target = home / '.codex/AGENTS.md'
    target.write_text('My own instructions.\n', encoding='utf-8')
    env = {'USERPROFILE': str(home), 'APPDATA': str(home), 'LOCALAPPDATA': str(home), 'TEMP': str(home), 'TMP': str(home)}
    install_rules('codex', root, env)
    first = target.read_bytes()
    install_rules('codex', root, env)
    assert target.read_bytes() == first
    spec.write_text('1. Files are portable.\n', encoding='utf-8')
    install_rules('codex', root, env)
    text = target.read_text(encoding='utf-8')
    assert text.startswith('My own instructions.\n')
    assert text.count('ARCHHUB-PRODUCT:BEGIN') == 1
    assert 'Files are portable.' in text and 'Everything is a node.' not in text


def test_damaged_rule_markers_are_left_untouched(tmp_path):
    from nodelang.agent_onboard import install_rules
    home = tmp_path / 'profile'
    (home / '.claude').mkdir(parents=True)
    target = home / '.claude/CLAUDE.md'
    original = b'personal\n<!-- ARCHHUB-PRODUCT:BEGIN -->\n'
    target.write_bytes(original)
    with pytest.raises(ValueError, match='ambiguous'):
        install_rules('claude-code', tmp_path, {'USERPROFILE': str(home), 'APPDATA': str(home), 'LOCALAPPDATA': str(home), 'TEMP': str(home), 'TMP': str(home)})
    assert target.read_bytes() == original


def _workspace_care(name):
    import importlib.util
    folder = Path('C:/Users/fargaly/00.ARCHUB/00.GOVERNANCE/01.WORKSPACE-CARE')
    spec = importlib.util.spec_from_file_location(name, folder / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hourly_folder_names_scan_private_names_without_file_reads(tmp_path, monkeypatch):
    care = _workspace_care('gen_register')
    workspace = tmp_path / 'workspace'
    for name in ('20.CLIENTS/21.PROJECT/lowercase', '60.PERSONAL/badname',
                 '50.TOOLING/51.SCRIPTS/52.VALID', '10.PRODUCT/11.APP/python_package'):
        (workspace / name).mkdir(parents=True)
    private_file = workspace / '20.CLIENTS/21.PROJECT/private.txt'
    private_file.write_text('fixture only', encoding='utf-8')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('folder scan opened a file'))
        report = care.folder_names(workspace)
    assert {row['path'] for row in report['invalid']} == {
        '20.CLIENTS/21.PROJECT/lowercase', '60.PERSONAL/badname', '10.PRODUCT/11.APP/python_package'}
    assert care.main(['--folders-only', '--root', str(workspace)]) == 0
    assert (workspace / '00.GOVERNANCE/05.WORKSPACE-REPORTS/folder-names.json').is_file()


def test_steward_reports_in_existing_numbered_folder(tmp_path, monkeypatch):
    care = _workspace_care('workspace_steward')
    monkeypatch.syspath_prepend(str(Path(care.__file__).parent))
    (tmp_path / '00.GOVERNANCE').mkdir()
    assert care.main(['--root', str(tmp_path), '--no-dedup', '--no-tier-scan', '--no-copy-scan']) == 0
    assert list((tmp_path / '00.GOVERNANCE/05.WORKSPACE-REPORTS').glob('*.json'))
    assert not (tmp_path / '00.GOVERNANCE/reports').exists()
