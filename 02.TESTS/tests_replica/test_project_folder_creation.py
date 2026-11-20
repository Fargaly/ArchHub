"""Actual files and the existing workspace/Settings owners; no host execution."""
import hashlib
from types import SimpleNamespace

import pytest
from nodelang.nograph_server import Refused


@pytest.fixture
def owner(tmp_path, monkeypatch):
    for key in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR'):
        value = tmp_path / key
        value.mkdir()
        monkeypatch.setenv(key, str(value))
    from nodelang.nograph_server import JsonFile, r_workspace_roots
    governed = tmp_path / 'Governed'
    (governed / '00.GOVERNANCE').mkdir(parents=True)
    (governed / '10.PRODUCT').mkdir()
    parent = governed / '70.COMPANY' / '_WIP' / 'Projects'
    parent.mkdir(parents=True)
    settings = JsonFile(tmp_path / 'settings.json', {})
    roots = JsonFile(tmp_path / 'workspaces.json', {'roots': [], 'imported_legacy': True})
    server = SimpleNamespace(files={'workspaces': roots, 'settings': settings}, workspace_built_in=lambda: str(governed))
    def call(**body):
        return r_workspace_roots(server, SimpleNamespace(body=body))
    registered = call(action='register', path=str(parent))['root']
    return call, parent, registered, roots, settings


def test_new_project_creates_and_registers_actual_governed_folder(owner):
    call, parent, registered, roots, settings = owner
    result = call(action='create', parent=registered['root_id'], name='Demo Project')
    project = parent / 'Demo Project'
    assert result['root']['path'] == str(project)
    assert {p.name for p in project.iterdir()} == {'README.md', 'REGISTER.md', '_WIP'}
    assert (project / '_WIP').is_dir()
    register = (project / 'REGISTER.md').read_text(encoding='utf8')
    assert 'README.md' in register and '_WIP/' in register
    assert hashlib.sha256((project / 'README.md').read_bytes()).hexdigest() in register
    assert any(row['path'] == str(project) for row in roots.read()['roots'])
    assert any(row['root_id'] == result['root']['root_id'] and row['project_template'] == 'Governed work folder' for row in call(action='list')['roots'])
    assert settings.read() == {}


def test_existing_folder_registration_and_collision_preserve_every_byte(owner):
    call, parent, registered, roots, _ = owner
    existing = parent / 'Existing'
    existing.mkdir()
    source = existing / 'original.txt'
    source.write_bytes(b'original project content')
    call(action='register', path=str(existing))
    before = roots.path.read_bytes()
    with pytest.raises((ValueError, Refused)):
        call(action='create', parent=registered['root_id'], name='Existing')
    assert source.read_bytes() == b'original project content'
    assert list(existing.iterdir()) == [source]
    assert roots.path.read_bytes() == before


@pytest.mark.parametrize('name', ['', '..', '../escape', 'a/b', 'a\\b', 'C:\\outside', '/outside', 'CON', 'LPT1.txt', 'NUL', 'bad:name', 'bad.', 'bad ', 'x|y', 'x\nline'])
def test_unsafe_names_write_nothing(owner, name):
    call, parent, registered, roots, _ = owner
    before = roots.path.read_bytes()
    with pytest.raises((ValueError, Refused)):
        call(action='create', parent=registered['root_id'], name=name)
    assert list(parent.iterdir()) == []
    assert roots.path.read_bytes() == before


def test_unknown_parent_refuses_before_writing(owner):
    call, parent, _, roots, _ = owner
    before = roots.path.read_bytes()
    with pytest.raises(Refused):
        call(action='create', parent='not-registered', name='Outside')
    assert list(parent.iterdir()) == []
    assert roots.path.read_bytes() == before


def test_unrelated_customer_root_stays_an_empty_folder(owner, tmp_path):
    call, _, _, _, settings = owner
    customer = tmp_path / 'Customer'
    customer.mkdir()
    row = call(action='register', path=str(customer))['root']
    result = call(action='create', parent=row['root_id'], name='New Customer Project')
    assert result['template'] == 'Empty folder'
    assert list((customer / 'New Customer Project').iterdir()) == []
    assert settings.read() == {}


def test_governed_workspace_root_rejects_root_dump(owner):
    call, parent, _, _, _ = owner
    governed = parent.parents[2]
    row = call(action='register', path=str(governed))['root']
    with pytest.raises(Refused, match='numbered'):
        call(action='create', parent=row['root_id'], name='Loose Project')
    assert not (governed / 'Loose Project').exists()


def test_redirected_parent_refuses_without_touching_target(owner, tmp_path):
    import os
    if os.name != 'nt':
        pytest.skip('Windows junction court')
    import subprocess
    call, parent, _, roots, _ = owner
    target = tmp_path / 'Elsewhere'
    target.mkdir()
    link = parent / 'Redirected'
    script = '$null=New-Item -ItemType Junction -Path $env:PROJECT_TEST_LINK -Target $env:PROJECT_TEST_TARGET'
    env = {**os.environ, 'PROJECT_TEST_LINK': str(link), 'PROJECT_TEST_TARGET': str(target)}
    result = subprocess.run(['powershell', '-NoProfile', '-Command', script], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    try:
        linked = call(action='register', path=str(link))['root']
        before = roots.path.read_bytes()
        with pytest.raises(Refused, match='redirected'):
            call(action='create', parent=linked['root_id'], name='Outside')
        assert not list(target.iterdir())
        assert roots.path.read_bytes() == before
    finally:
        link.rmdir()  # Remove the junction itself, never recurse through its target.


def test_select_registered_workspace_changes_only_its_existing_settings_owner(owner):
    call, parent, registered, roots, settings = owner
    before = roots.path.read_bytes()
    settings.update({'theme': 'Light'})
    result = call(action='select', id=registered['root_id'])
    assert result['root']['path'] == str(parent)
    assert settings.read() == {'theme': 'Light', 'activeWorkspace': registered['root_id']}
    assert roots.path.read_bytes() == before
    assert not list(parent.iterdir())
    saved = settings.path.read_bytes()
    with pytest.raises(Refused):
        call(action='select', id='missing-workspace')
    assert settings.path.read_bytes() == saved


@pytest.mark.parametrize('older_action', ['register', 'unregister'])
def test_overlapping_registry_update_keeps_new_project(owner, tmp_path, monkeypatch, older_action):
    import threading
    call, parent, registered, roots, _ = owner
    other = tmp_path / 'Other'
    other.mkdir()
    victim = call(action='register', path=str(other))['root'] if older_action == 'unregister' else None
    read = roots.read
    arrived, release, created = threading.Event(), threading.Event(), threading.Event()
    held_once, errors = [], []

    def paused_read():
        value = read()
        if threading.current_thread().name == 'older-workspace-operation' and not held_once:
            held_once.append(True)
            arrived.set()
            assert release.wait(3), 'test must release the older transaction'
        return value

    monkeypatch.setattr(roots, 'read', paused_read)

    def older():
        try:
            call(action='register', path=str(other)) if older_action == 'register' else call(action='unregister', id=victim['root_id'])
        except Exception as error:
            errors.append(error)

    def newer():
        try:
            call(action='create', parent=registered['root_id'], name='Concurrent')
        except Exception as error:
            errors.append(error)
        finally:
            created.set()

    first = threading.Thread(target=older, name='older-workspace-operation', daemon=True)
    second = threading.Thread(target=newer, daemon=True)
    first.start()
    try:
        assert arrived.wait(3)
        second.start()
        created.wait(.3)  # The old route allowed creation to finish against this stale read.
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    rows = read()['roots']
    assert (parent / 'Concurrent').is_dir()
    assert any(row['path'] == str(parent / 'Concurrent') for row in rows)
    assert any(row['path'] == str(other) for row in rows) == (older_action == 'register')


def test_simultaneous_normal_register_calls_keep_all_ten_rows(owner, tmp_path):
    import threading
    call, _, _, roots, _ = owner
    successes, errors, folders = [], [], []
    for pair in range(5):
        start = threading.Barrier(3)

        def add(folder):
            try:
                start.wait(3)
                successes.append(call(action='register', path=str(folder)))
            except Exception as error:
                errors.append(error)

        pair_threads = []
        for side in range(2):
            folder = tmp_path / ('Concurrent-%s-%s' % (pair, side))
            folder.mkdir()
            folders.append(folder)
            thread = threading.Thread(target=add, args=(folder,), daemon=True)
            pair_threads.append(thread)
            thread.start()
        start.wait(3)
        for thread in pair_threads:
            thread.join(3)
            assert not thread.is_alive()
    assert not errors and len(successes) == 10
    paths = {row['path'] for row in roots.read()['roots']}
    assert len(paths) == 11  # The existing parent plus all ten successful registrations.
    assert all(folder.is_dir() and str(folder) in paths for folder in folders)


def test_readding_same_resolved_windows_folder_keeps_original_open_id_and_metadata(owner):
    call, parent, registered, roots, _ = owner
    held = roots.read()
    held['roots'][0]['settings'] = {'Appearance.Theme': 'Light'}
    roots.write(held)
    original = roots.read()['roots'][0]
    aliases = [str(parent), str(parent / '.'), str(parent.parent / parent.name)]
    import os
    if os.name == 'nt':
        aliases.append(str(parent).swapcase())
    for alias in aliases:
        result = call(action='register', path=alias, privacy='public')
        assert result['root'] == original
        assert result['root']['root_id'] == registered['root_id']
        assert roots.read()['roots'] == [original]
    assert call(action='select', id=registered['root_id'])['root'] == original


def test_preference_refresh_keeps_selected_workspace_and_separate_document_scope(owner, tmp_path):
    call, _, registered, roots, settings = owner
    other = tmp_path / 'Document Project'
    other.mkdir()
    document_root = call(action='register', path=str(other))['root']
    call(action='select', id=registered['root_id'])
    from nodelang.settings_owner import PreferenceScope
    document = {'id': 'saved-workflow', 'properties': {'project': document_root['root_id']}}
    result = PreferenceScope(settings, roots, document=document).read()
    assert result['activeWorkspace'] == registered['root_id']
    assert result['settingsDestination']['workspace'] == document_root['root_id']
    assert document['properties']['project'] == document_root['root_id']
