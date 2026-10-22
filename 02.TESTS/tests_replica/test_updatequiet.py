"""R11: silent updater and new-process acknowledgment, fixture profiles only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from nodelang import assistant_registration as registration, quiet_update as qu
from nodelang.application_update import update_decision
from nodelang.native_workshop_profile import SERVER_NAME
from tests_replica.test_autoupd import staged_app, fixture_installer, launcher_function, install_identity, OLD

ROOT = Path(__file__).resolve().parents[2]


def test_quiet_setup_arguments_and_successful_relaunch_admission(tmp_path):
    app, state = staged_app(tmp_path)
    calls = []
    def install(args, **kwargs):
        calls.append((args, kwargs))
        return fixture_installer(app)(args, **kwargs)
    assert qu.apply_staged(state, app, runner=install)['applied']
    args, options = calls[0]
    assert args == [str(state / 'updates' / qu.ASSET_NAME), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                    '/NORESTART', '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/SP-',
                    '/LOG=' + str(state / 'updates/setup.log'), '/DIR=' + str(app)]
    assert options.get('creationflags', 0) & subprocess.CREATE_NO_WINDOW
    assert options['timeout'] is None


@pytest.mark.parametrize('damage', [None, 'identity', 'metadata', 'installer'])
def test_booted_build_reconciles_applying_only_with_matching_identity(tmp_path, damage):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    marker = state / 'updates/staged.json'
    data = json.loads(marker.read_text())
    data['phase'] = 'applying'
    marker.write_text(json.dumps(data))
    if damage == 'identity':
        install_identity(app, OLD)
    if damage == 'metadata':
        (app / 'BUILD_METADATA.json').write_text('{}')
    if damage == 'installer':
        (state / 'updates' / qu.ASSET_NAME).write_bytes(b'changed installer')
    result = qu.confirm_applied(state, app, rollback=False)
    assert result['confirmed'] is (damage is None)
    assert json.loads(marker.read_text())['phase'] == ('confirmed' if damage is None else 'applying')
    if damage is None:
        assert 'status' not in json.loads(marker.read_text()), 'phase is the one persisted update state'


def test_interrupted_installer_handoff_allows_one_matching_new_boot(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    marker = state / 'updates/staged.json'
    data = json.loads(marker.read_text())
    marker.write_text(json.dumps(dict(data, phase='applying')))
    result = qu.begin_update_boot(state, app)
    assert result['status'] == 'awaiting_boot' and not result.get('rolled_back')
    assert qu.confirm_applied(state, app, rollback=False)['confirmed']
    assert json.loads(marker.read_text())['phase'] == 'confirmed'


def test_build22_slow_graph_never_rolls_back_a_booted_studio(tmp_path, monkeypatch):
    """1528's 60 page polls elapsed despite its Studio window having booted."""
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    assert qu.begin_update_boot(state, app)['status'] == 'awaiting_boot'
    scheduled = []
    monkeypatch.setitem(sys.modules, 'PyQt6.QtCore', SimpleNamespace(
        QTimer=SimpleNamespace(singleShot=lambda *args: scheduled.append(args))))
    ns = dict(Path=Path, __file__=str(app / 'nodelang/launcher.py'), state_dir=state,
              _update_boot={'pending': True, 'checks': 60}, _booted={'done': True},
              _update_rollback_requested=threading.Event(),
              view=SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=lambda script, callback: callback(False))))
    launcher_function('_acknowledge_update_surface', ns)()
    for worker in threading.enumerate():
        if worker.name == 'archhub-update-boot-ack':
            worker.join(timeout=5)
    assert not ns['_update_boot']['pending'], 'booted app must not wait for the graph poll'
    assert not scheduled
    assert not ns['_update_rollback_requested'].is_set()
    assert json.loads((state / 'updates/staged.json').read_text())['phase'] == 'confirmed'


def test_real_rollback_reason_survives_the_next_launcher_check(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    assert qu.begin_update_boot(state, app)['status'] == 'awaiting_boot'
    rolled = qu.begin_update_boot(state, app)
    assert rolled['rolled_back']
    checked = update_decision(qu.staged_update(state, app), qu.installed_build_id(app))
    assert 'previous update boot did not confirm' in checked['log']
    assert '\n' not in checked['log']


def test_foreign_connector_warning_is_logged_and_visible_without_any_box(tmp_path, monkeypatch):
    """Compile and execute the installer's actual warning branches with Inno.

    No payload, icons, registry, uninstaller, profile changes or desktop automation.
    The old suppressible branch is safely suppressed, then detected in Setup log.
    """
    iscc = Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Inno Setup 6/ISCC.exe'
    assert iscc.is_file(), 'native installer court requires Inno Setup 6'
    app, state = staged_app(tmp_path)
    (app / '.venv/Scripts').mkdir(parents=True)
    (app / '.venv/Scripts/python.exe').write_bytes(b'')
    (app / 'runtime').mkdir()
    (app / 'runtime/node.exe').write_bytes(b'')
    (app / 'nodelang/native_agent_mcp.py').write_text('')
    home = tmp_path / 'PROFILE'
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.' + SERVER_NAME + ']\ncommand = "foreign.exe"\n')
    before = config.read_bytes()
    env = {'USERPROFILE': str(home), 'LOCALAPPDATA': str(tmp_path / 'LOCAL'),
           'ARCHHUB_TEST_STATE_DIR': str(state), 'PATH': ''}
    monkeypatch.setattr(registration, 'install_roots', lambda environment=None: (app, state))
    warnings = []
    rows = registration.migrate_install_connectors(consent=True, environment=env, warning=warnings.append)
    assert rows[0]['state'] == 'skipped_unmanaged'
    assert config.read_bytes() == before
    connection = next(c for c in registration.readiness(env)['clients'] if c['client'] == 'codex')
    assert connection['state'] == 'conflict' and connection['config'] == str(config)
    assert 'unmanaged entry; left untouched' in connection['reason']
    source = (ROOT / '03.TOOLS/installer/ArchHub.iss').read_text(encoding='utf-8-sig')
    branches = re.findall(r"if ConnectorWarnings <> '' then\s+([^;]+;)", source)
    assert len(branches) == 2, 'preflight and post-install warning paths both exercised'
    warning = warnings[0].replace("'", "''")
    code = '\n'.join(branches)
    script = tmp_path / 'WARNING.iss'
    script.write_text('''[Setup]
AppName=UPDATEQUIET fixture
AppVersion=0
DefaultDirName={src}\\INSTALL
CreateAppDir=no
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=WARNING
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var ConnectorWarnings: String;
begin
  if CurStep = ssPostInstall then begin
    ConnectorWarnings := '%s';
    Log(ConnectorWarnings);
    %s
  end;
end;
''' % (warning, code), encoding='utf-8')
    built = subprocess.run([str(iscc), '/Q', str(script)], capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    assert built.returncode == 0, built.stdout + built.stderr
    log = tmp_path / 'setup.log'
    result = subprocess.run([str(tmp_path / 'WARNING.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                             '/SP-', '/NORESTART', '/LOG=' + str(log)], timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    raw = log.read_bytes()
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    assert 'unknown or unmanaged entry; left untouched' in text
    assert 'message box' not in text.lower(), text
    assert config.read_bytes() == before
