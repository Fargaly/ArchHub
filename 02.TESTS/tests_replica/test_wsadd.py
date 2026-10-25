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
        request = Request(server.url + '/api/universal/workspace-roots',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Cookie': 'ArchHub-Session=' + server.browser_session_token,
                'X-ArchHub-CSRF': csrf or server.browser_csrf_token})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)
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
