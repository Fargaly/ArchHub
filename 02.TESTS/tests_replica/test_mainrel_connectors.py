"""Upgrade old client entries using fixture profiles only."""
import json
import os
import shutil
import subprocess
import sys
import tomllib
from types import SimpleNamespace
import pytest

from nodelang import assistant_registration as registration
from nodelang.native_workshop_profile import SERVER_NAME
from tests_replica.test_client_mcp_installation import _rig


@pytest.fixture
def machine(tmp_path, monkeypatch):
    install, state, profile, env = _rig(tmp_path / "Custom install with spaces")
    (install / ".venv/pyvenv.cfg").write_text(f"executable = {sys.executable}\n", encoding="utf-8")
    source = install / "nodelang/mcp_supervisor.py"
    source.write_text("print('migrated connector')\n", encoding="utf-8")
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (install, state))
    return SimpleNamespace(install=install, state=state, profile=profile, env=env,
                           supervisor=state.parent / "ArchHub-Runtime/mcp_supervisor.py", source=source)


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
    assert machine.supervisor.read_bytes() == machine.source.read_bytes()


def test_setup_commands_refresh_current_entries_without_rewriting_configs(machine):
    from pathlib import Path
    package = machine.install / 'nodelang'
    (package / '__init__.py').touch()
    for name in ('assistant_registration', 'client_mcp_installation', 'native_workshop_profile',
                 'workshop_config', 'user_paths'):
        shutil.copyfile(Path(registration.__file__).with_name(name + '.py'), package / (name + '.py'))
    env = dict(machine.env, ARCHHUB_TEST_STATE_DIR=str(machine.state),
               CODEX_HOME=str(machine.profile / '.codex'), SYSTEMROOT=os.environ['SYSTEMROOT'])
    codex = machine.profile / '.codex/config.toml'
    gemini = machine.profile / '.gemini/settings.json'
    codex.parent.mkdir()
    gemini.parent.mkdir()
    codex.write_text(registration._codex_block(registration.codex_entry(machine.install, machine.state)))
    gemini.write_text(json.dumps({'mcpServers': registration.mcp_server_spec(
        'gemini-cli', environment=env)['add']}))
    original = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (codex, gemini)]
    machine.supervisor.parent.mkdir()
    machine.supervisor.write_bytes(b'# earlier runtime')
    stamp = machine.supervisor.stat().st_mtime_ns
    command = [sys.executable, '-u', '-E', '-s', '-B', '-m', 'nodelang.assistant_registration']
    classifier = machine.profile / 'mainrel-connectors'
    shutil.copytree(package, classifier / 'nodelang')
    def setup(action, *args, cwd=machine.install):
        return subprocess.check_output([*command, action, *args], cwd=cwd, env=env, text=True, timeout=20)
    assert setup('preflight-connectors', str(machine.install), cwd=classifier) == ''
    registration.migrate_install_connectors(consent=False, environment=env)
    assert machine.supervisor.read_bytes() == b'# earlier runtime' and machine.supervisor.stat().st_mtime_ns == stamp
    assert setup('migrate-connectors').splitlines() == ['codex: registered', 'gemini-cli: registered']
    assert machine.supervisor.read_bytes() == machine.source.read_bytes()
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in (codex, gemini)] == original
    codex.unlink()
    gemini.unlink()
    first_install = machine.profile / 'Brand new install'
    assert setup('preflight-connectors', str(first_install), cwd=classifier) == ''
    assert not first_install.exists()


@pytest.mark.parametrize("present", [False, True])
def test_setup_without_managed_records_preserves_absent_or_unrecognised_runtime(machine, present):
    if present:
        machine.supervisor.parent.mkdir()
        machine.supervisor.write_bytes(b"x" * 10895)
        stamp = machine.supervisor.stat().st_mtime_ns
    registration.migrate_install_connectors(consent=True, environment=machine.env)
    if present:
        assert machine.supervisor.read_bytes() == b"x" * 10895 and machine.supervisor.stat().st_mtime_ns == stamp
    else:
        assert not machine.supervisor.parent.exists()


def test_migrate_connectors_refreshes_existing_runtime_supervisor_for_any_vendor(machine):
    """Setup migrate-connectors refreshes ArchHub-Runtime/mcp_supervisor.py even without Codex or Gemini configs."""
    machine.supervisor.parent.mkdir()
    machine.supervisor.write_bytes(b"# older supervisor using ARCHHUB_MCP_SUPERVISED\n")
    claude_cfg = machine.profile / ".claude.json"
    claude_before = (claude_cfg.read_bytes(), claude_cfg.stat().st_mtime_ns)
    registration.migrate_install_connectors(consent=True, environment=machine.env)
    assert machine.supervisor.read_bytes() == machine.source.read_bytes()
    assert (claude_cfg.read_bytes(), claude_cfg.stat().st_mtime_ns) == claude_before
    assert not (machine.profile / ".codex").exists()
    assert not (machine.profile / ".gemini").exists()


def test_setup_preflight_restores_relay_an_older_status_read_put_back(machine, monkeypatch):
    """The older installed app re-deploys its legacy relay on a status read; Setup's preflight puts its own back."""
    import hashlib
    from pathlib import Path
    from nodelang import client_mcp_installation as installation
    legacy = b"# legacy relay without drain receipts\n" * 7
    monkeypatch.setattr(installation, "LEGACY_SUPERVISOR", (len(legacy), hashlib.sha256(legacy).hexdigest()))
    machine.supervisor.parent.mkdir()
    machine.supervisor.write_bytes(legacy)
    staged = Path(registration.__file__).with_name("mcp_supervisor.py").read_bytes()
    assert registration.main(["preflight-connectors", str(machine.install)]) == 0
    assert machine.supervisor.read_bytes() == staged
    stamp = machine.supervisor.stat().st_mtime_ns
    assert registration.main(["preflight-connectors", str(machine.install)]) == 0  # already current: untouched
    assert machine.supervisor.stat().st_mtime_ns == stamp
    machine.supervisor.write_bytes(legacy + b"#")  # any other script, even one byte off, is left as it is
    assert registration.main(["preflight-connectors", str(machine.install)]) == 0
    assert machine.supervisor.read_bytes() == legacy + b"#"


def test_preflight_package_carries_the_relay_it_restores():
    from pathlib import Path
    import importlib.util
    root = Path(registration.__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("preflight_imports", root / "03.TOOLS/packaging/preflight_imports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path("01.APP/nodelang/mcp_supervisor.py") in module.import_closure(root)


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
    (tmp_path / 'nodelang/launcher.py').parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'nodelang/launcher.py').write_text('# fixture')
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
    from nodelang.user_paths import state_directory
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.delenv('ARCHHUB_STATE_DIR', raising=False)
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    if override:
        monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'explicit-state'))
    expected = tmp_path / 'explicit-state' if override else tmp_path / 'local' / 'ArchHub'
    assert state_directory() == setup._launcher_state_root() == registration.install_roots()[1] == expected


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
    assert machine.supervisor.read_bytes() == machine.source.read_bytes()
