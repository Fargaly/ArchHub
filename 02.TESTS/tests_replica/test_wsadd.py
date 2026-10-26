"""WSADD: real desktop route/catalogue and managed-backup custody, fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app import secrets_store as store
from nodelang import application_recovery_files as recovery
from nodelang import workspace_roots_catalogue as roots
from tests_replica import test_accountstore, test_nokey
from tests_replica.test_workspace_roots_catalogue import _Key

vault = test_accountstore.vault
owner = test_nokey.owner


@pytest.fixture
def browser(owner, monkeypatch):
    server, root = owner
    home = root / 'REGISTRY'
    home.mkdir()
    monkeypatch.setattr(roots, 'default_snapshot_path', lambda: home / 'workspace-roots.json')
    monkeypatch.setattr(roots, 'default_pin_path', lambda: home / 'workspace-roots.pin')
    monkeypatch.setattr(roots, 'default_last_good_path', lambda: home / 'last-good.json')
    key = _Key()
    key_path = home / 'workspace-roots.app-key.dpapi'
    key_path.touch()  # The court signer below substitutes for an existing app key.
    monkeypatch.setattr(roots, 'default_app_key_path', lambda: key_path)
    monkeypatch.setattr(roots, 'app_signing_components', lambda: (lambda pinned: key, key.fingerprint, key))
    server.workspace_roots_boot = 'missing'
    server.start()

    def post(body, csrf=None):
        current = post.server
        request = Request(current.url + '/api/universal/workspace-roots',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Cookie': 'ArchHub-Session=' + current.browser_session_token,
                'X-ArchHub-CSRF': csrf or current.browser_csrf_token})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)
    post.server = server
    return server, root, post


def test_picker_registers_in_desktop_owner_and_logs_each_attempt(browser, capsys):
    server, root, post = browser
    folder = root / 'CLIENT'
    folder.mkdir()
    calls = []
    server.native_folder_picker = lambda title: calls.append(title) or str(folder)
    status, picked = post({'action': 'browse'})
    assert status == 200 and Path(picked['path']) == folder
    status, added = post({'action': 'register', 'path': picked['path'],
                         'privacy': 'private', 'profile': 'client'})
    assert status == 200, added
    status, listed = post({'action': 'list'})
    assert status == 200 and Path(listed['roots'][0]['path']) == folder
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert 'workspace browse: selected' in output
    assert 'workspace register: completed' in output


def test_cancel_and_refusal_are_explicit_and_logged(browser, capsys):
    server, root, post = browser
    server.native_folder_picker = lambda title: ''
    status, answer = post({'action': 'browse'})
    assert status == 200 and answer['cancelled'] is True
    assert answer['message'] == 'Folder selection cancelled'
    status, answer = post({'action': 'register', 'path': str(root / 'MISSING'),
                           'privacy': 'private', 'profile': 'client'})
    assert status != 200 and answer['error']
    output = capsys.readouterr().out
    assert 'workspace browse: cancelled' in output
    assert 'workspace register: refused: ' + answer['error'] in output
    assert post({'action': 'list'})[1]['roots'] == []


def test_desktop_repairs_projection_from_graph_and_retries(browser, monkeypatch):
    server, root, post = browser
    home = root / "REGISTRY"
    expected_receipts = 0
    for index, damage in enumerate(("missing-pin", "foreign-pin", "unsigned", "mismatch")):
        folder = root / ("CLIENT" + str(index))
        folder.mkdir()
        root_id = "client" + str(index)
        status, added = post({"action": "register", "id": root_id,
            "path": str(folder), "privacy": "private"})
        assert status == 200, added
        catalogue = roots.find_workspace_root_catalogue(server.workspace_roots_authority,
            caller=server.workspace_roots_caller)
        before = roots.read_state(server.workspace_roots_authority, catalogue,
            caller=server.workspace_roots_caller)
        document = json.loads((home / "workspace-roots.json").read_text())
        if damage == "missing-pin":
            (home / "workspace-roots.pin").unlink()
        elif damage == "foreign-pin":
            (home / "workspace-roots.pin").write_text(json.dumps(roots.pin_document(_Key().public_blob())))
        elif damage == "unsigned":
            document["signature"] = "0" * 128
            (home / "workspace-roots.json").write_text(json.dumps(document))
        else:
            body = {key: value for key, value in document.items() if key != "signature"}
            body["roots"] = []
            factory, _fingerprint, verifier = roots.app_signing_components()
            roots.write_projection(body, factory(body["key_fingerprint"]).sign(roots.canonical(body)),
                verifier.public_blob())
        assert roots.boot_check(server.workspace_roots_authority, catalogue,
            caller=server.workspace_roots_caller) == {
                "missing-pin": "unpinned", "foreign-pin": "unpinned",
                "unsigned": "unsigned", "mismatch": "mismatch"}[damage]
        server._check_workspace_roots()
        assert server.workspace_roots_boot == "match", damage
        assert roots.read_state(server.workspace_roots_authority, catalogue,
            caller=server.workspace_roots_caller) == before
        repaired = json.loads((home / "workspace-roots.json").read_text())
        assert [entry["id"] for entry in repaired["roots"]] == [root_id]
        expected_receipts += 1
        # Damage after startup must be repaired for every owner change action too.
        (home / "workspace-roots.pin").unlink()
        action = ("register", "update-writers", "unregister", "unregister")[index]
        change = {"action": action, "id": root_id}
        if action == "register":
            other = root / "OTHER"
            other.mkdir()
            change.update(id="other", path=str(other), privacy="private")
        elif action == "update-writers":
            change["writers"] = ["codex"]
        status, answer = post(change)
        assert status == 200, answer
        assert answer["projection"] == answer["boot"] == "match"
        expected_receipts += 1
        receipts = [json.loads(line) for line in (home / "private-grant-events.log").read_text().splitlines()]
        assert len(receipts) == expected_receipts
        assert all(line["outcome"] == "ok" for line in receipts)
        server._check_workspace_roots()
        assert len((home / "private-grant-events.log").read_text().splitlines()) == expected_receipts
        if action == "register":
            assert post({"action": "unregister", "id": "other"})[0] == 200
        if action != "unregister":
            assert post({"action": "unregister", "id": root_id})[0] == 200
        assert folder.is_dir()
    folder = root / "FAILED"
    folder.mkdir()
    assert post({"action": "register", "id": "failed", "path": str(folder), "privacy": "private"})[0] == 200
    before = server.universal_store.revision
    (home / "workspace-roots.pin").unlink()
    original = roots.write_projection

    def denied(*args, **kwargs):
        raise PermissionError("registry folder is read-only")

    monkeypatch.setattr(roots, "write_projection", denied)
    server._check_workspace_roots()
    status, answer = post({"action": "unregister", "id": "failed"})
    assert status == 400
    assert "registry folder is read-only" in answer["error"]
    assert "republish it" not in answer["error"]
    assert server.universal_store.revision == before
    monkeypatch.setattr(roots, "write_projection", original)
    status, answer = post({"action": "unregister", "id": "failed"})
    assert status == 200, answer


def test_refused_browser_never_opens_picker(browser):
    server, _root, post = browser
    server.native_folder_picker = lambda title: pytest.fail('unauthenticated picker')
    assert post({'action': 'browse'}, csrf='wrong')[0] == 403


def test_fixws_absent_catalogue_archives_then_recovers_over_http(browser, monkeypatch, request):
    server, root, post = browser
    home = root / 'REGISTRY'
    # Create only a disposable pre-existing DPAPI key; recovery itself must never mint one.
    key_path = home / 'workspace-roots.app-key.dpapi'
    key_path.unlink()
    signer = roots.AppWorkspaceRootSigner(key_path)
    blob = signer.public_blob()
    protected_key = key_path.read_bytes()
    monkeypatch.setattr(roots, 'app_signing_components', lambda: (
        lambda pinned: signer, lambda: hashlib.sha256(blob).hexdigest(), roots.AppWorkspaceRootVerifier(key_path)))
    old = {name: data for name, data in (
        ('workspace-roots.json', b'{"roots":[{"path":"C:\\\\STALE"}]}\r\n'),
        ('workspace-roots.pin', b'old unpinned public projection\r\n'))}
    for name, data in old.items():
        (home / name).write_bytes(data)
    assert roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller) is None
    server._check_workspace_roots()  # Startup has no authenticated HTTP commit context.
    assert server.workspace_roots_boot == 'match', server._workspace_roots_repair_error
    status, answer = post({'action': 'list'})
    assert status == 200 and answer['boot'] == answer['projection'] == 'match', json.dumps(answer, indent=2)
    assert answer['health']['message'] == 'Workspaces are ready.'
    assert answer['health']['recovery']['message'] == (
        'Workspace list restored from the graph. Previous local files were archived.')
    archive = Path(answer['health']['recovery']['archive'])
    assert post({'action': 'list'})[1]['health']['recovery'] is None
    manifest = json.loads((archive / 'receipt.json').read_text())
    assert manifest['state'] == 'complete'
    for entry in manifest['files']:
        assert (archive / entry['name']).read_bytes() == old[entry['name']]
        assert entry['sha256'] == hashlib.sha256(old[entry['name']]).hexdigest()
    assert answer['roots'] == [] and Path(answer['built_in']['path']) == root / 'BUILTIN'
    revision = server.universal_store.revision
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    database = server.universal_store.database_path
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    provider.add_key('archhub.local.private-root-grants', b'g' * 32)
    for _ in range(2):
        server.close()
        server = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
            universal_workspace_root=root / 'BUILTIN', private_root_grants_path=root / 'private-root-grants.json',
            enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
        request.addfinalizer(server.close)
        server.start()
        post.server = server
        assert key_path.read_bytes() == protected_key
        health = post({'action': 'list'})[1]['health']
        assert health['state'] == 'ready' and health['recovery'] is None
        assert server.universal_store.revision == revision
        assert list((home / 'ARCHIVE').glob('*/' + archive.name)) == [archive]
    receipts = [json.loads(line) for line in (home / 'private-grant-events.log').read_text().splitlines()]
    assert len(receipts) == 1 and receipts[0]['outcome'] == 'ok'
    folder = root / 'CLIENT'
    folder.mkdir()
    marker = folder / 'keep.txt'
    marker.write_text('user files survive')
    status, added = post({'action': 'register', 'id': 'client', 'path': str(folder), 'privacy': 'private'})
    assert status == 200 and added['projection'] == 'match', added
    state = roots.current_registry_state(server.workspace_roots_authority, caller=server.workspace_roots_caller)
    for runtime in ('claude', 'codex', 'opencode'):
        container, digest, entry = roots.root_bound_registration('workspace-roots/client/' + runtime + '.txt',
            runtime=runtime, registry_state=state)
        assert container and digest and entry['id'] == 'client'
        (folder / (runtime + '.txt')).write_text(runtime)
        assert (folder / (runtime + '.txt')).read_text() == runtime
    held = root / 'CLIENT-HELD'
    folder.rename(held)
    folder.mkdir()
    assert post({'action': 'list'})[1]['roots'][0]['available'] is False
    folder.rmdir()
    held.rename(folder)
    assert post({'action': 'unregister', 'id': 'client'})[0] == 200
    assert marker.read_text() == 'user files survive'


def test_fixws_missing_key_archives_and_starts_fresh(browser, monkeypatch, request):
    server, root, post = browser
    home = root / 'REGISTRY'
    old = {'workspace-roots.json': b'old unsigned projection', 'workspace-roots.pin': b'old pin'}
    for name, data in old.items():
        (home / name).write_bytes(data)
    key_path = home / 'workspace-roots.app-key.dpapi'
    key_path.unlink()
    monkeypatch.setattr(roots, 'app_signing_components', lambda: pytest.fail('boot minted a key'))
    server._check_workspace_roots()
    assert server.workspace_roots_boot == 'missing', server._workspace_roots_repair_error
    answer = post({'action': 'list'})[1]
    assert answer['health']['state'] == 'idle' and answer['roots'] == []
    assert answer['health']['recovery'] is None
    assert not key_path.exists()
    assert roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller) is None
    receipts = list((home / 'ARCHIVE').glob('*/*/receipt.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt['state'] == 'complete' and receipt['outcome'] == 'fresh'
    for entry in receipt['files']:
        assert (receipts[0].parent / entry['name']).read_bytes() == old[entry['name']]
        assert entry['sha256'] == hashlib.sha256(old[entry['name']]).hexdigest()
        assert not (home / entry['name']).exists()
    monkeypatch.setattr(roots, 'app_signing_components', lambda: (
        lambda pin: roots.AppWorkspaceRootSigner(key_path),
        lambda: hashlib.sha256(roots.AppWorkspaceRootSigner(key_path).public_blob()).hexdigest(),
        roots.AppWorkspaceRootVerifier(key_path)))
    folder = root / 'CLIENT'
    folder.mkdir()
    assert post({'action': 'register', 'id': 'client', 'path': str(folder), 'privacy': 'private'})[0] == 200
    assert key_path.exists()
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    database = server.universal_store.database_path
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    provider.add_key('archhub.local.private-root-grants', b'g' * 32)
    for _ in range(2):
        server.close()
        server = ApplicationServer(universal_state_path=database, universal_key_provider=provider,
            universal_workspace_root=root / 'BUILTIN', private_root_grants_path=root / 'private-root-grants.json',
            enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
        request.addfinalizer(server.close)
        server.start()
        post.server = server
        listed = post({'action': 'list'})[1]
        assert listed['boot'] == 'match' and listed['health']['recovery'] is None
        assert [entry['root_id'] for entry in listed['roots']] == ['client']
        assert list((home / 'ARCHIVE').glob('*/*/receipt.json')) == receipts
    assert post({'action': 'unregister', 'id': 'client'})[0] == 200


def test_fixws_empty_profile_and_interrupted_recovery_retry(browser, monkeypatch):
    server, root, post = browser
    home = root / 'REGISTRY'
    # Fresh built-in-only profile reaches a terminal state without a false archive notice.
    status, answer = post({'action': 'list'})
    assert status == 200 and answer['boot'] == 'missing', answer
    assert answer['roots'] == [] and answer['health']['recovery'] is None
    assert answer['health']['state'] == 'idle'
    assert answer['health']['message'] == 'No other workspaces yet.'
    folder = root / 'CLIENT'
    folder.mkdir()
    assert post({'action': 'register', 'id': 'client', 'path': str(folder), 'privacy': 'private'})[0] == 200
    catalogue = roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller)
    original = roots.write_projection
    monkeypatch.setattr(roots, 'write_projection', lambda *a, **k: (_ for _ in ()).throw(PermissionError('publish denied')))
    (home / 'workspace-roots.pin').unlink()
    answer = post({'action': 'list'})[1]
    assert answer['health']['state'] == 'error' and 'publish denied' in answer['health']['detail']
    monkeypatch.setattr(roots, 'write_projection', original)
    assert post({'action': 'list'})[1]['health']['state'] == 'ready'
    assert roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller) == catalogue


def test_fixws_fresh_keyless_profile_first_register_works(owner, isolated_profile):
    server, root = owner
    assert roots.registry_dir() == isolated_profile / '.archhub'
    assert roots.default_app_key_path().is_relative_to(Path(os.environ['LOCALAPPDATA']))
    assert server.workspace_roots_boot == 'missing', server._workspace_roots_repair_error
    assert not roots.default_app_key_path().exists()
    assert not roots.default_snapshot_path().exists()
    assert not (roots.registry_dir() / 'ARCHIVE').exists()
    folder = root / 'CLIENT'
    folder.mkdir()
    server.start()
    request = Request(server.url + '/api/universal/workspace-roots',
        data=json.dumps({'action': 'register', 'path': str(folder), 'privacy': 'private'}).encode(),
        headers={'Content-Type': 'application/json',
                 'Cookie': 'ArchHub-Session=' + server.browser_session_token,
                 'X-ArchHub-CSRF': server.browser_csrf_token})
    with urlopen(request, timeout=30) as response:
        assert response.status == 200
        assert json.load(response)['projection'] == 'match'
    assert roots.default_app_key_path().exists()
    assert not (roots.registry_dir() / 'ARCHIVE').exists()


def test_profile_write_guard_blocks_mutations_before_they_happen(tmp_path, tmp_path_factory):
    code = '''
import functools, os, sqlite3, sys
from pathlib import Path
from tests_replica.conftest import _deny_profile_write, _profile_path
root = Path(sys.argv[1])
attempts = []
sys.addaudithook(functools.partial(_deny_profile_write,
    protected=(_profile_path(root),), attempts=attempts))
for action in (lambda: (root / "file").write_text("bad"), lambda: root.mkdir(),
               lambda: os.replace(root.parent / "source", root / "dest"),
               lambda: os.open(root / "file", os.O_CREAT | os.O_WRONLY),
               lambda: sqlite3.connect(root / "db"),
               lambda: os.remove(root / "file")):
    try:
        action()
    except AssertionError:
        pass
    else:
        raise AssertionError("profile mutation was admitted")
assert len(attempts) == 6 and not root.exists()
if os.name == "nt":
    assert _profile_path("\\\\\\\\?\\\\" + str(root)) == _profile_path(root)
'''
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(
        str(Path(__file__).resolve().parents[2] / folder) for folder in ('01.APP', '02.TESTS'))}
    result = subprocess.run([os.sys.executable, '-c', code, str(tmp_path / 'PROTECTED')],
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    from tests_replica import conftest
    session = conftest.no_live_profile_writes.__wrapped__(tmp_path_factory)
    next(session)
    attempt = ('open', str(tmp_path / 'PROTECTED'))
    try:
        conftest._PROFILE_WRITE_ATTEMPTS.append(attempt)
        with pytest.raises(AssertionError):
            next(session)
    finally:
        conftest._PROFILE_WRITE_ATTEMPTS.remove(attempt)
        session.close()


def test_fixws_mutation_keeps_repair_notice_for_the_following_list(browser):
    _server, root, post = browser
    (root / 'REGISTRY' / 'workspace-roots.pin').write_bytes(b'old unpinned projection')
    folder = root / 'CLIENT'
    folder.mkdir()
    status, added = post({'action': 'register', 'path': str(folder), 'privacy': 'private'})
    assert status == 200 and added['health']['recovery'] is None, added
    assert post({'action': 'list'})[1]['health']['recovery']['message'] == (
        'Workspace list restored from the graph. Previous local files were archived.')
    assert post({'action': 'list'})[1]['health']['recovery'] is None


def test_fixws_first_enrollment_faults_preserve_pair_and_resume(browser, monkeypatch):
    server, root, post = browser
    home = root / 'REGISTRY'
    old = {'workspace-roots.json': b'old unsigned projection', 'workspace-roots.pin': b'old public pin'}
    for name, data in old.items():
        (home / name).write_bytes(data)
    components = roots.app_signing_components
    key_bytes = (home / 'workspace-roots.app-key.dpapi').read_bytes()
    def unreadable():
        raise ValueError('app key unreadable')
    monkeypatch.setattr(roots, 'app_signing_components', unreadable)
    assert 'app key unreadable' in post({'action': 'list'})[1]['health']['detail']
    assert (home / 'workspace-roots.app-key.dpapi').read_bytes() == key_bytes
    signer, fingerprint, _verifier = components()
    monkeypatch.setattr(roots, 'app_signing_components', lambda: (signer, fingerprint, _Key()))
    assert 'could not be verified' in post({'action': 'list'})[1]['health']['detail']
    assert not (home / 'ARCHIVE').exists()
    monkeypatch.setattr(roots, 'app_signing_components', components)
    atomic = roots._atomic_write
    def archive_denied(target, data):
        if 'ARCHIVE' in target.parts:
            raise PermissionError('archive denied')
        return atomic(target, data)
    monkeypatch.setattr(roots, '_atomic_write', archive_denied)
    answer = post({'action': 'list'})[1]
    assert answer['health']['message'] == 'ArchHub could not archive the previous workspace list. Nothing was replaced.'
    assert roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller) is None
    for name, data in old.items():
        assert (home / name).read_bytes() == data
    monkeypatch.setattr(roots, '_atomic_write', atomic)
    pin = roots.pin_signing_key
    monkeypatch.setattr(roots, 'pin_signing_key', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('interrupted before pin')))
    assert 'interrupted before pin' in post({'action': 'list'})[1]['health']['detail']
    catalogue = roots.find_workspace_root_catalogue(server.workspace_roots_authority,
        caller=server.workspace_roots_caller)
    assert catalogue is not None
    archives = list((home / 'ARCHIVE').glob('*/*/receipt.json'))
    assert len(archives) == 1
    archive = archives[0].parent
    (archive / 'workspace-roots.json').write_bytes(b'corrupt archive')
    monkeypatch.setattr(roots, 'pin_signing_key', pin)
    assert 'archived workspace list could not be verified' in post({'action': 'list'})[1]['health']['detail']
    assert roots.read_state(server.workspace_roots_authority, catalogue,
        caller=server.workspace_roots_caller)[2] is None
    (archive / 'workspace-roots.json').write_bytes(old['workspace-roots.json'])
    def completion_denied(target, data):
        if target.name == 'receipt.json' and json.loads(data).get('state') == 'complete':
            raise PermissionError('interrupted after publish')
        return atomic(target, data)
    monkeypatch.setattr(roots, '_atomic_write', completion_denied)
    assert 'interrupted after publish' in post({'action': 'list'})[1]['health']['detail']
    assert roots.boot_check(server.workspace_roots_authority, catalogue,
        caller=server.workspace_roots_caller) == 'match'
    monkeypatch.setattr(roots, '_atomic_write', atomic)
    answer = post({'action': 'list'})[1]
    assert answer['health']['state'] == 'ready' and json.loads(archives[0].read_text())['state'] == 'complete'
    assert list((home / 'ARCHIVE').glob('*/*/receipt.json')) == archives
    for name, data in old.items():
        assert (archive / name).read_bytes() == data


def test_rendered_add_round_trips_through_desktop_catalogue(browser):
    server, root, post = browser
    folder = root / 'CLIENT'
    folder.mkdir()
    server.native_folder_picker = lambda title: str(folder)
    driver = Path(__file__).resolve().parents[1] / 'tests_js/wsadd.test.cjs'
    environment = {**os.environ, 'WSADD_OWNER_URL': server.url,
        'WSADD_OWNER_SESSION': server.browser_session_token,
        'WSADD_OWNER_CSRF': server.browser_csrf_token,
        'WSADD_OWNER_FOLDER': str(folder)}
    result = subprocess.run(['node', '--test', '--test-name-pattern=desktop owner Add', str(driver)],
        env=environment, capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(post({'action': 'list'})[1]['roots'][0]['path']) == folder


def test_launcher_folder_picker_uses_qt_thread_and_distinguishes_timeout(monkeypatch):
    import ast
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication, QFileDialog
    from nodelang.gui_thread import GuiThreadAsker
    from tests_replica.test_browse_dialog_runs_on_the_gui_thread import _from_worker
    app = QApplication.instance() or QApplication([])
    asker = GuiThreadAsker(app)
    launcher = Path(__file__).resolve().parents[2] / '01.APP/nodelang/launcher.py'
    tree = ast.parse(launcher.read_text(encoding='utf-8'))
    picker = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == '_pick_folder')
    window = object()
    calls = []
    def dialog(parent, title, directory):
        assert parent is window and directory == ''
        assert QThread.currentThread() is app.thread()
        calls.append(title)
        return 'C:/FIXTURE/CLIENT'
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', dialog)
    namespace = {'_ask_on_gui_thread': asker, 'window': window}
    exec(compile(ast.Module(body=[picker], type_ignores=[]), str(launcher), 'exec'), namespace)
    assert _from_worker(app, lambda: namespace['_pick_folder']('Fixture folder'))['value'] == 'C:/FIXTURE/CLIENT'
    assert calls == ['Fixture folder']
    namespace['_ask_on_gui_thread'] = lambda call, timeout: None
    with pytest.raises(TimeoutError, match='Folder picker timed out'):
        namespace['_pick_folder']('Fixture folder')


@pytest.fixture(params=['auto', 'custom'])
def external(vault, request):
    # E:-style managed destination, physically inside this lane's one fixture.
    volume = vault.root.parent / 'EXTERNAL'
    volume.mkdir()
    selected = recovery.set_backup_location(vault.root.parent, str(volume))
    if request.param == 'auto':
        selected = recovery.set_backup_location(vault.root.parent, 'auto', directory=selected['directory'])
    return Path(selected['directory'])


def test_stub_archives_to_managed_external_directory(vault, external, monkeypatch):
    raw = b'Og8='
    store.SECRETS_FILE.write_bytes(raw)
    def cross_volume(*args):
        raise OSError(17, 'cannot rename across volumes')
    monkeypatch.setattr(store.os, 'rename', cross_volume)
    store.archive_legacy_credentials()
    digest = hashlib.sha256(raw).hexdigest()
    archive = external / ('secrets-legacy-' + digest + '.dat')
    assert archive.read_bytes() == raw
    assert archive.with_suffix('.sha256').read_bytes() == (digest + '\n').encode('ascii')
    assert not store.SECRETS_FILE.exists()
    before = {p.name: p.stat().st_mtime_ns for p in external.iterdir()}
    store.archive_legacy_credentials()
    assert {p.name: p.stat().st_mtime_ns for p in external.iterdir()} == before


@pytest.mark.parametrize('suffix', ['.dat', '.sha256'])
def test_collision_never_overwrites_or_removes_original(vault, external, suffix):
    raw = b'Og8='
    store.SECRETS_FILE.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    external.mkdir(parents=True)
    existing = (external / ('secrets-legacy-' + digest + '.dat')).with_suffix(suffix)
    existing.write_bytes(b'prior bytes')
    with pytest.raises(OSError):
        store.archive_legacy_credentials()
    assert existing.read_bytes() == b'prior bytes'
    assert store.SECRETS_FILE.read_bytes() == raw


def test_receipt_write_failure_preserves_original(vault, external, monkeypatch):
    raw = b'Og8='
    store.SECRETS_FILE.write_bytes(raw)
    real_sync = store.os.fsync
    calls = []
    def fail_receipt(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError('fixture disk full')
        real_sync(fd)
    monkeypatch.setattr(store.os, 'fsync', fail_receipt)
    with pytest.raises(OSError, match='fixture disk full'):
        store.archive_legacy_credentials()
    assert store.SECRETS_FILE.read_bytes() == raw
    assert list(external.iterdir()) == []
    store.archive_legacy_credentials()
    assert not store.SECRETS_FILE.exists()


def test_outside_writer_cannot_replace_or_write_source_during_copy(vault, external, monkeypatch):
    store.SECRETS_FILE.write_bytes(b'Og8=')
    real_sync = store.os.fsync
    calls = []
    replacement = vault.root / 'REPLACEMENT.dat'
    replacement.write_bytes(b'changed')
    def change_original(fd):
        real_sync(fd)
        with pytest.raises(PermissionError):
            store.SECRETS_FILE.write_bytes(b'changed')
        with pytest.raises(PermissionError):
            store.os.replace(replacement, store.SECRETS_FILE)
        calls.append(fd)
    monkeypatch.setattr(store.os, 'fsync', change_original)
    store.archive_legacy_credentials()
    assert len(calls) == 2
    assert replacement.read_bytes() == b'changed'
    assert list(external.glob('*.dat'))[0].read_bytes() == b'Og8='


def test_external_archive_removes_the_settings_warning(vault, external, monkeypatch):
    from tests_replica.test_accountstore import controls
    store.SECRETS_FILE.write_bytes(b'Og8=')
    vault.names.append('notion-mcp')
    vault.values['notion-mcp'] = 'fixture-os-item'
    result = controls(monkeypatch).readControls()
    assert not result['controlErrors']
    assert result['secrets'][0]['id'] == 'notion-mcp'
    assert list(external.glob('secrets-legacy-*.dat'))


def test_fixws_fresh_idle_rendered_over_http(browser):
    server, _root, _post = browser
    driver = Path(__file__).resolve().parents[1] / 'tests_js/wsadd.test.cjs'
    environment = {**os.environ, 'WSADD_OWNER_URL': server.url,
        'WSADD_OWNER_SESSION': server.browser_session_token, 'WSADD_OWNER_CSRF': server.browser_csrf_token}
    result = subprocess.run(['node', '--test', '--test-name-pattern=fresh idle owner', str(driver)],
        env=environment, capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('stage', ['copy', 'retire'])
def test_fixws_keyless_interruption_resumes_one_archive(browser, monkeypatch, stage):
    _server, root, post = browser
    home = root / 'REGISTRY'
    old = {'workspace-roots.json': b'old unsigned projection', 'workspace-roots.pin': b'old pin'}
    for name, data in old.items():
        (home / name).write_bytes(data)
    (home / 'workspace-roots.app-key.dpapi').unlink()
    atomic, unlink = roots._atomic_write, Path.unlink
    def interrupted_copy(target, data):
        if 'ARCHIVE' in target.parts and target.name == 'workspace-roots.pin':
            raise PermissionError('copy interrupted')
        return atomic(target, data)
    def interrupted_retire(path, *args, **kwargs):
        if path == home / 'workspace-roots.pin':
            raise PermissionError('retirement interrupted')
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        if stage == 'copy':
            patch.setattr(roots, '_atomic_write', interrupted_copy)
        else:
            patch.setattr(Path, 'unlink', interrupted_retire)
        assert post({'action': 'list'})[1]['health']['state'] == 'error'
    receipts = list((home / 'ARCHIVE').glob('*/*/receipt.json'))
    assert len(receipts) == 1
    answer = post({'action': 'list'})[1]
    assert answer['boot'] == 'missing' and answer['health']['state'] == 'idle', answer
    assert list((home / 'ARCHIVE').glob('*/*/receipt.json')) == receipts
    for name, data in old.items():
        assert (receipts[0].parent / name).read_bytes() == data
        assert not (home / name).exists()
    assert json.loads(receipts[0].read_text())['state'] == 'complete'
    assert not roots.default_app_key_path().exists()
