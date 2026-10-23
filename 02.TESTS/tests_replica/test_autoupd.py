"""AUTOUPD courts: real owners, local release and disposable app; no desktop."""
import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from nodelang import quiet_update as qu
from nodelang.application_update import ApplicationUpdate, UpdateRestartRefused
from nodelang.universal_cell import InvalidCell

ROOT = Path(__file__).resolve().parents[2]
OLD = ('old', '2026-10-15T00:00:00Z')
NEW = ('new', '2026-10-16T00:00:00Z')


def install_identity(app, identity):
    app.mkdir(parents=True, exist_ok=True)
    (app / 'BUILD_ID').write_text(identity[0], encoding='utf-8')
    (app / 'BUILD_METADATA.json').write_text(json.dumps(
        dict(format=1, build_id=identity[0], built_at=identity[1])), encoding='utf-8')


def release_fixture(tmp_path):
    asset = b'local-fixture-installer'
    manifest = dict(tag_name='build-new', draft=False, prerelease=False,
        body='BUILD_ID: new\nBUILT_AT: ' + NEW[1] + '\nSHA256 ' + qu.ASSET_NAME + ': '
             + hashlib.sha256(asset).hexdigest() + '\n',
        assets=[dict(name=qu.ASSET_NAME, size=len(asset), browser_download_url=
            'https://github.com/Fargaly/ArchHub/releases/download/build-new/' + qu.ASSET_NAME)])
    fixture = tmp_path / 'release.json'
    fixture.write_text(json.dumps(manifest), encoding='utf-8')

    def opener(request, timeout=0):
        return io.BytesIO(fixture.read_bytes() if request.full_url == qu.RELEASE_API else asset)
    return opener


def launcher_function(name, namespace):
    source = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8-sig'))
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<launcher-fixture>', 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('mode', ['rolled_back', 'applied'])
@pytest.mark.parametrize('launch_failed', [False, True])
def test_preboot_relaunch_uses_one_process_owner_and_never_falls_through(tmp_path, monkeypatch, mode, launch_failed):
    from nodelang import application_update_recovery as recovery
    source = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8-sig'))
    node = next(n for n in source.body if isinstance(n, ast.Try)
        and any(isinstance(child, ast.Name) and child.id == 'begin_update_boot' for child in ast.walk(n)))
    monkeypatch.setattr(qu, 'begin_update_boot', lambda *a: {'rolled_back': True} if mode == 'rolled_back'
        else {'staged': True, 'status': 'staged'})
    monkeypatch.setattr(qu, 'apply_staged', lambda *a, **kw: {'applied': True, 'build_id': 'new'})
    monkeypatch.setattr(recovery, 'validate_update_ready', lambda *a: None)
    calls = []
    def launch(command, **kwargs):
        calls.append((command, kwargs))
        if launch_failed:
            raise OSError('fixture launcher unavailable')
    namespace = dict(Path=Path, __file__=str(tmp_path / 'nodelang/launcher.py'), state_dir=tmp_path,
        state_path=tmp_path / 'graph.db', _instance_lock=SimpleNamespace(close=lambda: calls.append('close')),
        _update_preboot_process=SimpleNamespace(Popen=launch, CREATE_NO_WINDOW=123))
    with pytest.raises(SystemExit) as stopped:
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<preboot-fixture>', 'exec'), namespace)
    assert stopped.value.code == int(launch_failed)
    assert calls[0] == 'close' and len(calls) == 2
    assert calls[1] == (['wscript.exe', str(tmp_path / 'ArchHub.vbs')],
        {'close_fds': True, 'creationflags': 123})


def test_startup_stages_local_newer_manifest_before_first_wait(tmp_path, monkeypatch):
    app, state = tmp_path / 'app', tmp_path / 'state'
    install_identity(app, OLD)
    opener = release_fixture(tmp_path)
    stage = qu.stage_if_newer
    monkeypatch.setattr(qu, 'stage_if_newer', lambda state, app, **kw: stage(state, app, opener, **kw))
    owner = ApplicationUpdate(state, app, request_restart=lambda: None, first_boot=True)
    namespace = dict(time=SimpleNamespace(monotonic=lambda: 0),
        _update_stop=SimpleNamespace(is_set=lambda: False, wait=lambda delay: True),
        _stage_once=owner.check)
    launcher_function('_stage_update_quietly', namespace)()
    if owner._worker:
        owner._worker.join(timeout=5)
    assert owner.status()['state'] == 'ready', 'startup never staged/offered the local newer release'
    assert (state / 'updates' / qu.ASSET_NAME).read_bytes() == b'local-fixture-installer'
    assert qu.installed_build_id(app) == OLD[0]
    assert owner.close()


def staged_app(tmp_path):
    app, state = tmp_path / 'app', tmp_path / 'state'
    install_identity(app, OLD)
    (app / 'nodelang').mkdir()
    (app / 'nodelang' / 'product.py').write_text('old code', encoding='utf-8')
    (app / 'state').mkdir()
    (app / 'state' / 'graph.db').write_bytes(b'USER GRAPH')
    assert qu.stage_if_newer(state, app, release_fixture(tmp_path))['staged']
    return app, state


def fixture_installer(app):
    def run(args, **kwargs):
        assert '/NOCLOSEAPPLICATIONS' in args and '/NORESTART' in args
        install_identity(app, NEW)
        (app / 'nodelang' / 'product.py').write_text('new code', encoding='utf-8')
        (app / 'nodelang' / 'added.py').write_text('new module', encoding='utf-8')
        return SimpleNamespace(returncode=0)
    return run


def test_stage_apply_confirm_retains_previous_build(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app), before_apply=lambda: None)['applied']
    assert qu.begin_update_boot(state, app)['status'] == 'awaiting_boot'
    assert qu.confirm_applied(state, app)['confirmed']
    assert (state / 'updates' / 'previous-build.zip').is_file()
    assert qu.begin_update_boot(state, app)['status'] == 'confirmed'
    assert (app / 'state' / 'graph.db').read_bytes() == b'USER GRAPH'


def test_failed_confirm_restores_previous_product_without_touching_graph(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    (app / 'BUILD_METADATA.json').write_text('{}', encoding='utf-8')
    result = qu.confirm_applied(state, app)
    assert not result['confirmed'] and result['rolled_back'], result
    assert qu.installed_build_id(app) == OLD[0]
    assert (app / 'nodelang' / 'product.py').read_text(encoding='utf-8') == 'old code'
    assert not (app / 'nodelang' / 'added.py').exists()
    assert (app / 'state' / 'graph.db').read_bytes() == b'USER GRAPH'
    assert not qu.stage_if_newer(state, app, release_fixture(tmp_path))['staged'], 'failed build must not loop'


def test_unconfirmed_boot_is_rolled_back_on_next_start(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    assert not qu.begin_update_boot(state, app).get('rolled_back')
    assert qu.begin_update_boot(state, app)['rolled_back']
    assert qu.installed_build_id(app) == OLD[0]


def test_corrupt_previous_build_refuses_boot_instead_of_opening_partial_code(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    qu.begin_update_boot(state, app)
    (state / 'updates' / 'previous-build.zip').write_bytes(b'corrupt')
    assert qu.begin_update_boot(state, app)['status'] == 'applying'


@pytest.mark.parametrize('reason', ['Save unsaved work before restarting.', 'A Workshop job is running; restart when it finishes.'])
def test_busy_restart_is_refused_with_one_line_and_retains_ready(tmp_path, reason):
    app, state = staged_app(tmp_path)
    restarts = []
    owner = ApplicationUpdate(state, app, request_restart=lambda: restarts.append(True),
        initial_stage=qu.staged_update(state, app), restart_refusal=lambda: reason)
    with pytest.raises(UpdateRestartRefused, match=reason):
        owner.reload()
    assert not restarts and owner.status()['state'] == 'ready'


def test_restart_guard_reads_real_execution_state_and_allows_settled_work():
    from nodelang.application_update import restart_block_reason
    host = SimpleNamespace(_native={'reservation':object()}, _status={'state':'executing'})
    owner = SimpleNamespace(_existing_workshop_native_host=host, _native_workshop_reservations={})
    assert restart_block_reason(owner) == 'A Workshop job is running; restart when it finishes.'
    host._status['state'] = 'settled'
    assert restart_block_reason(owner) is None
    owner._native_workshop_reservations['job'] = SimpleNamespace(_settled=None)
    assert restart_block_reason(owner)
    owner._native_workshop_reservations['job']._settled = {'ok':True}
    assert restart_block_reason(owner) is None


def test_window_quit_does_not_hard_kill_a_ready_update(monkeypatch):
    import threading
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8'))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_quit_from_window')
    started, queued = [], []
    monkeypatch.setattr(threading, 'Thread', lambda **kwargs: started.append(kwargs))
    namespace = dict(_window_quit_started={'value':False},
        server=SimpleNamespace(application_update=SimpleNamespace(apply_on_quit=lambda: True)),
        app=SimpleNamespace(closeAllWindows=lambda: None, topLevelWidgets=lambda: [], quit=lambda: None),
        QTimer=SimpleNamespace(singleShot=lambda delay, callback: queued.append(callback)))
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<quit-fixture>','exec'), namespace)
    namespace['_quit_from_window']()
    assert not started and len(queued) == 1, 'the ordinary watchdog must not kill an applying update'


def test_interval_has_one_inflight_download_and_quit_policy(tmp_path, monkeypatch):
    app, state = staged_app(tmp_path)
    checks = []
    owner = ApplicationUpdate(state, app, request_restart=lambda: None,
        policy=lambda: dict(check_interval_minutes=15, auto_apply_on_quit=False, channel='stable'))
    monkeypatch.setattr(owner, 'check', lambda: checks.append(True))
    monkeypatch.setattr('nodelang.application_update.time.monotonic', lambda: 100)
    owner.check_if_due()
    owner.check_if_due()
    assert checks == [True]
    assert not owner.apply_on_quit()


def test_catalogue_settings_write_through_the_existing_graph_property_owner():
    from nodelang import universal_application as app
    from nodelang.map_import import resolve_map_path
    store, registry = app.build_universal_application(resolve_map_path())
    initial = store.revision
    assert app.read_universal_update_policy(store.snapshot(), registry) == dict(
        check_interval_minutes=30, auto_apply_on_quit=True, channel='stable')
    assert store.revision == initial
    root = app._system_tool_canvas_root('tool_workshop')
    app.apply_universal_canvas_gesture(store, registry, roots=[root], focus_root=root)
    canvas = app.project_universal_canvas(store, registry)
    rows = {row['label']: row for row in canvas['properties'] if row['label'].startswith('update_')}
    assert set(rows) == {'update_check_interval_minutes','update_auto_apply_on_quit','update_preview_channel','update_shutdown_ms'}
    for key, value in [('update_check_interval_minutes','7'),('update_auto_apply_on_quit','false'),('update_preview_channel','true')]:
        app.edit_universal_property(store, registry, rows[key]['relation'], value)
    assert app.read_universal_update_policy(store.snapshot(), registry) == dict(
        check_interval_minutes=7, auto_apply_on_quit=False, channel='preview')
    revision = store.revision
    with pytest.raises(InvalidCell, match='outside its bound'):
        app.edit_universal_property(store, registry, rows['update_check_interval_minutes']['relation'], '0')
    assert store.revision == revision


def test_workshop_engine_uses_update_defaults_wired_feeds_and_the_same_settings_bounds():
    from nodelang.pipeline_engines import tool_settings
    held = tool_settings({'tool': 'workshop'}, {})[0]['out']
    assert {key: held.get(key) for key in ('update_check_interval_minutes',
        'update_auto_apply_on_quit', 'update_preview_channel')} == {
        'update_check_interval_minutes': 30, 'update_auto_apply_on_quit': True,
        'update_preview_channel': False}
    held = tool_settings({'tool': 'workshop', 'update_check_interval_minutes': 15}, {
        'update_check_interval_minutes': 7, 'update_auto_apply_on_quit': 0,
        'update_preview_channel': 1})[0]['out']
    assert held['update_check_interval_minutes'] == 7
    assert held['update_auto_apply_on_quit'] is False and held['update_preview_channel'] is True
    for key, value in [('update_check_interval_minutes', 0), ('update_check_interval_minutes', 1441),
            ('update_auto_apply_on_quit', 2), ('update_preview_channel', 'true')]:
        with pytest.raises(ValueError):
            tool_settings({'tool': 'workshop', key: value}, {})


def test_failed_installer_restores_previous_build_immediately(tmp_path):
    app, state = staged_app(tmp_path)
    install = fixture_installer(app)
    def failed(args, **kwargs):
        install(args, **kwargs)
        return SimpleNamespace(returncode=1)
    result = qu.apply_staged(state, app, runner=failed)
    assert not result['applied'] and result['rolled_back']
    assert qu.installed_build_id(app) == OLD[0]
    assert (app / 'state' / 'graph.db').read_bytes() == b'USER GRAPH'


def test_failed_confirm_with_a_missing_installer_still_restores_previous_build(tmp_path):
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    (state / 'updates' / qu.ASSET_NAME).unlink()
    assert qu.confirm_applied(state, app)['rolled_back']
    assert qu.installed_build_id(app) == OLD[0]


def test_preview_channel_is_opt_in_and_uses_the_same_digest_verifier(tmp_path):
    app, state = tmp_path / 'app', tmp_path / 'state'
    install_identity(app, OLD)
    release_fixture(tmp_path)
    preview = json.loads((tmp_path / 'release.json').read_text(encoding='utf-8'))
    preview['prerelease'] = True
    def opener(request, timeout=0):
        if request.full_url.endswith('?per_page=20'):
            return io.BytesIO(json.dumps([preview]).encode())
        if request.full_url == qu.RELEASE_API:
            return io.BytesIO(json.dumps(preview).encode())
        return io.BytesIO(b'local-fixture-installer')
    assert qu.read_latest_release(opener) is None
    assert qu.stage_if_newer(state, app, opener, channel='preview')['staged']


def test_emergency_recovery_uses_only_stdlib_and_refuses_a_running_owner(tmp_path):
    import runpy
    app, state = staged_app(tmp_path)
    assert qu.apply_staged(state, app, runner=fixture_installer(app))['applied']
    (app / 'nodelang' / '__init__.py').write_text('invalid Python !!!',encoding='utf-8')
    class Socket:
        busy = True
        def setsockopt(self, *args): pass
        def bind(self, address):
            if self.busy: raise OSError('existing desktop owns the lock')
        def close(self): pass
    socket = Socket()
    owner = runpy.run_path(qu.__file__)
    assert not owner['recover_failed_launch'](state, app, socket_factory=lambda: socket)['rolled_back']
    assert qu.installed_build_id(app) == NEW[0]
    socket.busy = False
    assert owner['recover_failed_launch'](state, app, socket_factory=lambda: socket)['rolled_back']
    assert qu.installed_build_id(app) == OLD[0]


def test_windows_bootstrap_maps_launch_exceptions_to_the_same_recovery_path(tmp_path):
    import os
    import subprocess
    if os.name != 'nt':
        pytest.skip('Windows script host fixture')
    source = (ROOT / "03.TOOLS/installer/ArchHub.vbs").read_text(encoding='utf-8')
    function = source[source.index('Function RunAndWait('):source.index('Function RecoverFailedUpdate()')]
    harness = tmp_path / 'bootstrap-fixture.vbs'
    harness.write_text('''Class ShellFixture
Function Run(command, style, wait)
If command = "missing" Then Err.Raise 5
Run = 7
End Function
End Class
Dim sh
Set sh = New ShellFixture
''' + function + '''
If RunAndWait("missing", 0) <> 1 Then WScript.Quit 1
If RunAndWait("finished", 0) <> 7 Then WScript.Quit 2
WScript.Echo "BOOTSTRAP PASS"
''', encoding='utf-8')
    result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/cscript.exe'), '//nologo', str(harness)],
        capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and 'BOOTSTRAP PASS' in result.stdout, result.stderr


def test_real_build_reader_reconciles_final_compiled_inventory(tmp_path):
    import os
    import subprocess
    if os.name != 'nt':
        pytest.skip('PowerShell build-reader fixture')
    script = tmp_path / 'inventory-fixture.ps1'
    script.write_text('''param([string]$Root)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $Root '03.TOOLS/installer/build_release.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Release build PowerShell syntax is invalid.' }
$functions = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in @('Assert-PlainAncestors','Read-StudioBuild')}, $true)
foreach ($function in $functions) { . ([scriptblock]::Create($function.Extent.Text)) }
$selectedRoot = Join-Path $Root '01.APP'; $utf8 = [Text.UTF8Encoding]::new($false, $true)
$plainDirectories = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$result = Read-StudioBuild
Write-Output $result.Files
''',encoding='utf-8')
    result = subprocess.run(['powershell','-NoProfile','-File',str(script),str(ROOT)], capture_output=True,
        text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW,
        env={key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'})
    manifest = json.loads((ROOT / "01.APP/nodelang/studio/compiled/manifest.json").read_text(encoding='utf-8'))
    assert result.returncode == 0 and int(result.stdout.strip()) == len(manifest['files']), result.stderr


@pytest.mark.parametrize('damage', ['extra', 'duplicate', 'escape', 'hash'])
def test_build_inventory_refuses_extra_duplicate_escaped_or_changed_output(tmp_path, damage):
    import os
    import subprocess
    if os.name != 'nt':
        pytest.skip('PowerShell build-reader fixture')
    root = tmp_path / 'PRODUCT'
    installer = root / 'INSTALLER'
    generated = root / 'NODELANG/STUDIO/COMPILED'
    installer.mkdir(parents=True)
    generated.mkdir(parents=True)
    (installer / 'build_release.ps1').write_bytes((ROOT / "03.TOOLS/installer/build_release.ps1").read_bytes())
    payload = b'void 0;'
    (generated / 'app.js').write_bytes(payload)
    record = dict(output='app.js',bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
    records = [record]
    if damage == 'extra':
        (generated / 'unlisted.js').write_bytes(payload)
    elif damage == 'duplicate':
        records.append(dict(record))
    elif damage == 'escape':
        record['output'] = '../app.js'
    else:
        (generated / 'app.js').write_bytes(b'changed;')
    (generated / 'manifest.json').write_text(json.dumps(dict(format=1,files=records)),encoding='utf-8')
    script = tmp_path / 'CHECK.ps1'
    script.write_text('''param([string]$Root)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $Root 'installer/build_release.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Release build PowerShell syntax is invalid.' }
$functions = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in @('Assert-PlainAncestors','Read-StudioBuild')}, $true)
foreach ($function in $functions) { . ([scriptblock]::Create($function.Extent.Text)) }
$selectedRoot = $Root; $utf8 = [Text.UTF8Encoding]::new($false, $true)
$plainDirectories = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
Read-StudioBuild
''',encoding='utf-8')
    result = subprocess.run(['powershell','-NoProfile','-File',str(script),str(root)], capture_output=True,
        text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW,
        env={key:value for key,value in os.environ.items() if key.upper() != 'PSMODULEPATH'})
    assert result.returncode != 0
    expected = {'extra':'inventory differs', 'duplicate':'duplicate Studio output',
                'escape':'Invalid or duplicate', 'hash':'does not match its manifest'}
    assert expected[damage] in result.stderr


@pytest.mark.parametrize("page_ready,studio_mounted,checks,verdict", [
    (True, False, 0, "confirm"),        # the graph page reported: confirmed at once
    (False, False, 0, "wait"),         # a new process still has time to reach Studio
    (False, True, 59, "confirm"),       # R11: the booted Studio confirms without waiting for the graph
    (False, True, 149, "confirm"),      # slow graph hydration is not a failed install
    (False, True, 150, "confirm"),      # the window reached the Studio: a slow graph page is not a failed install
    (False, False, 150, "rollback"),    # never reached the Studio: restore the previous build
])
def test_boot_acknowledgment_confirms_a_mounted_studio_and_rolls_back_only_a_dead_window(
        page_ready, studio_mounted, checks, verdict):
    assert qu.boot_acknowledgment(page_ready, studio_mounted, checks) == verdict




def test_boot_confirmation_waits_out_a_busy_update_lock(monkeypatch):
    """Build 31 rolled itself back because its confirmation met the boot-time update check."""
    from nodelang import quiet_update
    answers = iter([{"confirmed": False, "reason": "update operation busy"}] * 3
                   + [{"confirmed": True, "reason": "successful boot acknowledged"}])
    monkeypatch.setattr(quiet_update, "confirm_applied", lambda *a, **k: next(answers))
    slept = []
    result = quiet_update.confirm_when_free("state", "app", sleep=slept.append)
    assert result["confirmed"] and len(slept) == 3
    monkeypatch.setattr(quiet_update, "confirm_applied",
                        lambda *a, **k: {"confirmed": False, "reason": "installed BUILD_ID does not match staged build"})
    assert not quiet_update.confirm_when_free("state", "app", sleep=slept.append)["confirmed"]



def test_installer_runs_only_after_runtime_processes_are_stopped(tmp_path):
    """Build 33 rolled back because a leftover goose.exe locked runtime/goose/goose.exe."""
    from nodelang import quiet_update
    runtime = tmp_path / "app" / "runtime" / "goose"
    runtime.mkdir(parents=True)
    events = []
    class Proc:
        def __init__(self, pid, exe):
            self.pid, self.info = pid, {"pid": pid, "exe": exe}
        def terminate(self):
            events.append(("terminate", self.pid))
        def kill(self):
            events.append(("kill", self.pid))
    import psutil
    original = psutil.wait_procs
    psutil.wait_procs = lambda procs, timeout: (procs, [])
    try:
        stopped = quiet_update.stop_runtime_processes(tmp_path / "app", process_iter=lambda attrs: [
            Proc(1, str(runtime / "goose.exe")), Proc(2, str(tmp_path / "elsewhere.exe")), Proc(3, None)])
    finally:
        psutil.wait_procs = original
    assert stopped == [1] and events == [("terminate", 1)]
