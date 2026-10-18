"""Upgrade old client entries using fixture profiles only."""
import json
import tomllib
import pytest

from nodelang import assistant_registration as registration
from nodelang.native_workshop_profile import SERVER_NAME
pytest_plugins = ("tests_replica.test_assistant_registration",)


def test_codex_runpy_is_migrated_not_left_on_deleted_module(machine):
    config = machine.profile / '.codex' / 'config.toml'
    config.parent.mkdir()
    legacy = {'command': r'C:\Python\python.exe',
              'args': ['-I', '-B', '-c', "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('nodelang.clean_coordination_mcp',run_name='__main__')", str(machine.install)],
              'env': {'ARCHHUB_COORDINATION_VENDOR': 'codex'}}
    text = 'model = "fixture"\n' + registration._codex_block(dict(legacy, env_vars=['CODEX_THREAD_ID']))
    config.write_text(text, encoding='utf-8')
    result = registration.migrate_codex(machine.install, machine.state, consent=True, environment=machine.env)
    assert result['state'] == 'registered', result
    assert tomllib.loads(config.read_text())['model'] == 'fixture'
    assert 'clean_coordination_mcp' not in config.read_text()
    assert result['backup']


def test_inline_runpy_loader_is_recognised_but_extra_code_is_refused():
    code = "import sys,runpy;sys.path.insert(0,r'C:\\ArchHub');runpy.run_module('nodelang.clean_coordination_mcp',run_name='__main__')"
    assert registration._retired_runpy_args(['-c', code])
    assert not registration._retired_runpy_args(['-c', code + ';print(1)'])
    assert not registration._retired_runpy_args(['-c', code.replace('clean_coordination_mcp', 'other')])


@pytest.mark.parametrize('state', ['migration_unconfirmed', 'config_unreadable', 'conflict'])
def test_setup_cli_refuses_unsuccessful_connector_migration(monkeypatch, state):
    monkeypatch.setattr(registration, 'migrate_install_connectors', lambda **_: [{'client': 'codex', 'state': state}])
    assert registration.main(['migrate-connectors']) == 1


def test_preflight_unknown_retired_entry_warns_without_writes(machine):
    config = machine.profile / '.codex/config.toml'
    config.parent.mkdir()
    text = '[mcp_servers.' + SERVER_NAME + ']\ncommand = "custom.exe"\nargs = ["nodelang.clean_coordination_mcp"]\n'
    config.write_text(text, encoding='utf-8')
    before = config.read_bytes()
    warnings = []
    assert registration.preflight_install_connectors(machine.env, warning=warnings.append)['codex'] == 'other'
    assert any(str(config) in row and 'unknown' in row for row in warnings)
    assert config.read_bytes() == before


@pytest.mark.parametrize('migration_status', [0, 1])
def test_setup_publishes_ready_only_after_managed_migration(tmp_path, monkeypatch, migration_status):
    import colleague_setup as setup
    monkeypatch.setattr(setup, '__file__', str(tmp_path / 'colleague_setup.py'))
    (tmp_path / 'launch_archhub_test.py').write_text('# fixture')
    (tmp_path / '.archhub-ready').write_text('old same-build marker')
    monkeypatch.setattr(setup, 'readiness_identity', lambda _: 'fixture-build')
    monkeypatch.setattr(setup, 'prepare_environment', lambda _: None)
    monkeypatch.setattr(setup, 'PACKAGES', [])
    monkeypatch.setattr(setup, 'ready_for_build', lambda _: True)
    monkeypatch.setattr(setup, 'verify_imports', lambda _: [])
    for name in ('print_host_installation_readiness', 'register_revit_add_ins',
                 'register_max_startup', 'register_autocad_add_ins', 'report_rhino_blender',
                 '_assistant_integration', '_assistant_hooks'):
        monkeypatch.setattr(setup, name, lambda *args: None)
    events = []
    monkeypatch.setattr(registration, 'main', lambda args: events.append('migrate') or migration_status)
    monkeypatch.setattr(setup, '_write_ready', lambda *args: events.append('ready'))
    status = setup.main()
    assert status == (8 if migration_status else 0)
    assert events == (['migrate'] if migration_status else ['migrate', 'ready'])
    if migration_status:
        assert not (tmp_path / '.archhub-ready').exists()


@pytest.mark.parametrize('override', [False, True])
def test_registration_and_setup_follow_exact_launcher_state_root(tmp_path, monkeypatch, override):
    import colleague_setup as setup
    import ast
    from pathlib import Path
    import os
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    if override:
        monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'explicit-state'))
    source = ast.parse((Path(__file__).resolve().parents[1] / 'launch_archhub_test.py').read_text(encoding='utf-8-sig'))
    assignment = next(node for node in source.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'state_dir' for target in node.targets))
    namespace = {'Path': Path, 'os': os}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), '<isolated-launcher-state>', 'exec'), namespace)
    assert setup._launcher_state_root() == namespace['state_dir']
    assert registration.install_roots()[1] == namespace['state_dir']


def test_gemini_deleted_module_is_migrated_with_encrypted_backup(machine):
    config = machine.profile / '.gemini' / 'settings.json'
    config.parent.mkdir()
    before = {'theme': 'fixture', 'mcpServers': {'other': {'url': 'https://fixture.invalid'},
        SERVER_NAME: {'command': r'C:\Python\python.exe', 'args': ['-m', 'nodelang.clean_coordination_mcp'],
                      'env': {'PYTHONPATH': str(machine.install), 'ARCHHUB_COORDINATION_VENDOR': 'gemini'}}}}
    config.write_text(json.dumps(before), encoding='utf-8')
    result = registration.migrate_gemini(machine.install, machine.state, consent=True, environment=machine.env)
    assert result['state'] == 'registered', result
    after = json.loads(config.read_text())
    assert after['theme'] == before['theme']
    assert after['mcpServers']['other'] == before['mcpServers']['other']
    assert 'clean_coordination_mcp' not in config.read_text()
    assert result['backup']
