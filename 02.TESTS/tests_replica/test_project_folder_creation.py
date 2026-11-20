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
    call.server = server
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


def test_office_template_copies_only_folders_and_preserves_source(owner, tmp_path):
    call, _, _, roots, _ = owner
    parent = tmp_path / 'customer'
    parent.mkdir()
    registered = call(action='register', path=str(parent))['root']
    source = tmp_path / 'template'
    (source / 'Alpha' / 'Beta').mkdir(parents=True)
    (source / 'Gamma').mkdir()
    original = source / 'private.txt'
    original.write_bytes(b'never copied')
    call(action='register', path=str(source))
    result = call(action='create', parent=registered['root_id'], name='Example', template='Office project tree', template_source=str(source))
    target = parent / 'Example'
    assert result['template'] == 'Office project tree'
    assert any(row['root_id'] == result['root']['root_id'] and row['path'] == str(target) for row in roots.read()['roots'])
    assert {p.relative_to(target).as_posix() for p in target.rglob('*')} == {'Alpha', 'Alpha/Beta', 'Gamma'}
    assert all(p.is_dir() for p in target.rglob('*'))
    assert original.read_bytes() == b'never copied'
    assert {p.relative_to(source).as_posix() for p in source.rglob('*')} == {'Alpha', 'Alpha/Beta', 'Gamma', 'private.txt'}


@pytest.mark.parametrize('fault', ['inside-source', 'junction-child', 'missing', 'governed', 'too-deep', 'too-many', 'unbound-iso', 'public-parent'])
def test_template_refuses_before_create_or_registration(owner, tmp_path, fault):
    import subprocess
    call, governed_parent, governed_registered, roots, _ = owner
    source = tmp_path / 'template'
    source.mkdir()
    parent = tmp_path / 'customer'
    parent.mkdir()
    kind = 'Office project tree'
    if fault == 'inside-source':
        parent = source / 'child'
        parent.mkdir()
    if fault == 'junction-child':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(source / 'redirect'), str(parent)], capture_output=True, stdin=subprocess.DEVNULL)
        assert result.returncode == 0, result.stderr
    if fault == 'missing':
        source = tmp_path / 'absent'
    if fault == 'too-deep':
        source.joinpath(*['Deep'] * 13).mkdir(parents=True)
    if fault == 'too-many':
        for i in range(1025):
            (source / str(i)).mkdir()
    if fault == 'unbound-iso':
        kind = 'ISO 19650 CDE tree'
    registered = call(action='register', path=str(parent), privacy='public' if fault == 'public-parent' else 'private')['root']
    if fault == 'governed':
        parent, registered = governed_parent, governed_registered
    if source.is_dir():
        call(action='register', path=str(source))
    before = roots.path.read_bytes()
    with pytest.raises((Refused, ValueError)):
        call(action='create', parent=registered['root_id'], name='Example', template=kind, template_source=str(source))
    assert not (parent / 'Example').exists()
    assert roots.path.read_bytes() == before


@pytest.mark.parametrize('change', ['none', 'remove', 'path', 'privacy', 'identity'])
def test_template_scan_releases_owner_lock_and_rechecks_parent(owner, tmp_path, monkeypatch, change):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from nodelang import workspace_roots_catalogue as catalogue
    call, _, _, roots, _ = owner
    parent, source, unrelated = [tmp_path / name for name in ('Parent', 'Template', 'Unrelated')]
    for directory in (parent, source, unrelated):
        directory.mkdir()
    (source / 'Alpha').mkdir()
    registered = call(action='register', path=str(parent))['root']
    call(action='register', path=str(source))
    entered, release = threading.Event(), threading.Event()
    original = catalogue.read_project_template
    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(catalogue, 'read_project_template', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(call, action='create', parent=registered['root_id'], name='Created', template='Office project tree', template_source=str(source))
        try:
            assert entered.wait(2)
            listed = pool.submit(call, action='list').result(timeout=2)
            assert listed['ok']
            other = pool.submit(call, action='register', path=str(unrelated)).result(timeout=2)
            if change == 'remove':
                call(action='unregister', id=registered['root_id'])
            elif change in ('path', 'privacy'):
                with roots.lock:
                    held = roots.read()
                    row = next(row for row in held['roots'] if row['root_id'] == registered['root_id'])
                    row['path' if change == 'path' else 'privacy'] = str(unrelated) if change == 'path' else 'public'
                    roots.write(held)
            elif change == 'identity':
                parent.rename(tmp_path / 'OldParent')
                parent.mkdir()
            before = roots.path.read_bytes()
        finally:
            release.set()
        if change == 'none':
            assert pending.result(timeout=3)['ok']
            assert (parent / 'Created' / 'Alpha').is_dir()
            assert any(row['root_id'] == other['root']['root_id'] for row in roots.read()['roots'])
        else:
            with pytest.raises(Refused):
                pending.result(timeout=3)
            assert not (parent / 'Created').exists()
            assert not (unrelated / 'Created').exists()
            assert roots.path.read_bytes() == before


def test_unregistered_template_requires_actual_picker_binding(owner, tmp_path):
    call, _, _, roots, _ = owner
    parent, source = tmp_path / 'Parent', tmp_path / 'Template'
    parent.mkdir()
    (source / 'Alpha').mkdir(parents=True)
    registered = call(action='register', path=str(parent))['root']
    before = roots.path.read_bytes()
    with pytest.raises(Refused):
        call(action='create', parent=registered['root_id'], name='Created', template='Office project tree', template_source=str(source), template_window='unpicked')
    assert not (parent / 'Created').exists()
    assert roots.path.read_bytes() == before


def test_picker_binding_cannot_be_reused_by_another_window(owner, tmp_path):
    call, _, _, roots, _ = owner
    parent, source = tmp_path / 'Parent', tmp_path / 'Template'
    parent.mkdir()
    (source / 'Alpha').mkdir(parents=True)
    registered = call(action='register', path=str(parent))['root']
    call.server.native_folder_picker = lambda _title: str(source)
    assert call(action='browse', template=True, template_window='first')['path'] == str(source)
    before = roots.path.read_bytes()
    with pytest.raises(Refused):
        call(action='create', parent=registered['root_id'], name='WrongWindow', template='Office project tree', template_source=str(source), template_window='second')
    assert not (parent / 'WrongWindow').exists()
    assert roots.path.read_bytes() == before
    assert call(action='create', parent=registered['root_id'], name='Selected', template='Office project tree', template_source=str(source), template_window='first')['ok']
    assert (parent / 'Selected' / 'Alpha').is_dir()


def test_template_unavailable_parent_identity_refuses_before_scan(owner, tmp_path, monkeypatch):
    from nodelang import workspace_roots_catalogue as catalogue
    call, _, _, roots, _ = owner
    parent, source = tmp_path / 'Parent', tmp_path / 'Template'
    parent.mkdir()
    source.mkdir()
    registered = call(action='register', path=str(parent))['root']
    call(action='register', path=str(source))
    before = roots.path.read_bytes()
    monkeypatch.setattr(catalogue, 'folder_identity', lambda _path: None)
    def no_scan(*_args):
        raise AssertionError('An unidentified parent must refuse before source enumeration')
    monkeypatch.setattr(catalogue, 'read_project_template', no_scan)
    with pytest.raises(Refused, match='identity is unavailable'):
        call(action='create', parent=registered['root_id'], name='Created', template='Office project tree', template_source=str(source))
    assert roots.path.read_bytes() == before
    assert list(parent.iterdir()) == []
    assert list(source.iterdir()) == []
