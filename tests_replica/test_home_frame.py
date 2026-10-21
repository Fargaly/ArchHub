"""Authenticated Home metadata defers the unchanged saved Workspace owner."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import commit_intent, universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.lazy_application_registry import DeferredRegistryField
from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


@pytest.fixture(autouse=True)
def isolated_home_producers(monkeypatch):
    from nodelang import cloud_signin, pipeline_engines

    def refuse_live_probe(*args, **kwargs):
        raise AssertionError('Home replica court cannot probe live services')

    monkeypatch.setattr(pipeline_engines, '_brain_call', refuse_live_probe)
    monkeypatch.setattr(pipeline_engines, 'probe_connectors', refuse_live_probe)
    monkeypatch.setattr(ApplicationServer, '_probe_brain', staticmethod(lambda: {'ok': True, 'facts': 7}))
    monkeypatch.setattr(ApplicationServer, '_probe_hosts', staticmethod(lambda: []))
    monkeypatch.setattr(cloud_signin, 'sign_in_state', lambda *args, **kwargs: {
        'state': 'signed_out', 'signed_in': False, 'email': '',
        'expires_at': None, 'founder': False,
    })


@pytest.fixture
def saved_home_server(tmp_path, monkeypatch, request):
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(
        Path(app.__file__).parent / 'data/public_runtime_map.json'))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'h' * 32)
    keys.add_key('archhub.local.court-attestation', b'f' * 32)
    options = dict(universal_state_path=tmp_path / 'home.sqlite3',
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_brain_cloud_sync=False,
        enable_machine_projection_prewarm=False, live_watch=False)
    setup = ApplicationServer(**options)
    try:
        registry, store = setup.universal_registry, setup.universal_store
        context = registry.authorization.session.context(minimum_validity_seconds=5)
        with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='saved Home fixture'):
            if getattr(request, 'param', False):
                from nodelang.universal_graphs import create_graph
                create_graph(store, registry, 'Home metadata graph', authentication_context=context)
                # Creation enters the new graph; return through the admitted
                # root before entering its sibling public Map domain.
                app.set_universal_scope(store, registry, registry.canvas_root,
                    authentication_context=context)
            app.set_universal_scope(store, registry, registry.map.domains['ui'],
                authentication_context=context)
        expected = app.project_universal_canvas(store, registry, authentication_context=context)
        expected_theme = app.read_universal_theme(store, registry, authentication_context=context)
        if getattr(request, 'param', False):
            from nodelang.universal_graphs import project_graph_index
            expected['_graph_index'] = project_graph_index(store, registry,
                authentication_context=context)
    finally:
        setup.close()
    server = ApplicationServer(**options).start()
    try:
        yield server, expected, expected_theme
    finally:
        server.close()


def _get(server, path, *, authenticated=True):
    headers = {'Cookie': 'ArchHub-Session=' + server.browser_session_token} if authenticated else {}
    try:
        with urlopen(Request(server.url + path, headers=headers), timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as refused:
        return refused.code, json.loads(refused.read())


def test_authenticated_home_keeps_saved_nested_scope_deferred_then_workspace_loads(saved_home_server, monkeypatch):
    server, expected, (theme, metadata) = saved_home_server
    registry, store = server.universal_registry, server.universal_store
    work = object.__getattribute__(registry, 'workshop_workbench_root')
    assert isinstance(work, DeferredRegistryField) and work.group._values is None
    before = store.revision

    def forbidden(*args, **kwargs):
        pytest.fail('Home must not open the saved canvas, Work, or mutate graph Cells')

    saved_loader = registry.lazy_scope_loader
    object.__setattr__(registry, 'lazy_scope_loader', forbidden)
    try:
        with monkeypatch.context() as frame_only:
            for name in ('_project_universal_canvas_answer', '_session_canvas_roots',
                         '_canvas_roots', '_nested_canvas_scope', '_scope_label'):
                frame_only.setattr(app, name, forbidden)
            frame_only.setattr(work.group, 'factory', forbidden)
            frame_only.setattr(store, 'commit', forbidden)
            status, frame = _get(server, '/api/universal/canvas?screen=home')
    finally:
        object.__setattr__(registry, 'lazy_scope_loader', saved_loader)
    assert status == 200 and frame['ok'] is True and frame['canvas_deferred'] is True
    assert frame['revision'] == before == store.revision
    assert frame['nodes'] == frame['wires'] == [] and work.group._values is None
    assert frame['scope']['current'] == expected['scope']['current'] != registry.canvas_root
    assert [item['root'] for item in frame['scope']['trail']] == [
        item['root'] for item in expected['scope']['trail']]
    assert frame['authorization']['subject'] == expected['authorization']['subject']
    assert frame['authorization']['session'] == expected['authorization']['session']
    assert frame['configuration']['theme'] == theme
    assert all(frame['configuration'][key] == value for key, value in metadata.items())
    assert frame['configuration']['theme_fields'] == expected['configuration']['theme_fields']
    assert frame['configuration']['personal_wip_heads'] == expected['configuration']['personal_wip_heads']
    assert frame['configuration']['history'] == [] and frame['configuration']['history_deferred'] is True
    assert frame['interaction_projection'] == {'revision': before, 'bindings': []}
    status, full = _get(server, '/api/universal/canvas')
    assert status == 200 and not full.get('canvas_deferred')
    assert full['scope']['current'] == expected['scope']['current']
    assert [node['id'] for node in full['nodes']] == [node['id'] for node in expected['nodes']]
    assert full['interaction_projection']['bindings']
    for query in ('screen=workspace', 'screen=home&unknown=', 'screen=home&screen=home'):
        status, ordinary = _get(server, '/api/universal/canvas?' + query)
        assert status == 200 and not ordinary.get('canvas_deferred')
        assert ordinary['scope']['current'] == expected['scope']['current']


def test_home_selector_keeps_route_and_original_shell_theme_admissions(saved_home_server, monkeypatch):
    server, _, _ = saved_home_server
    status, _ = _get(server, '/api/universal/canvas?screen=home', authenticated=False)
    assert status == 403
    with pytest.raises(AuthorizationDenied, match='explicit authenticated context'):
        app.project_universal_home_frame(server.universal_store, server.universal_registry)
    original = app._require_application_authorization
    calls = []

    def deny_shell(snapshot, registry, action, root, **kwargs):
        calls.append((action, root))
        if root == registry.authorization.shell_scope_root:
            raise AuthorizationDenied('fixture revoked Shell read')
        return original(snapshot, registry, action, root, **kwargs)

    with monkeypatch.context() as refused:
        refused.setattr(app, '_require_application_authorization', deny_shell)
        status, body = _get(server, '/api/universal/canvas?screen=home')
    assert status == 403 and 'fixture revoked Shell read' in body['error']
    assert calls == [('read', server.universal_registry.authorization.shell_scope_root)]
    original_theme = app.read_universal_theme
    reads = []

    def verified_theme(*args, **kwargs):
        reads.append(kwargs['authentication_context'])
        return original_theme(*args, **kwargs)

    with monkeypatch.context() as admitted:
        admitted.setattr(app, 'read_universal_theme', verified_theme)
        status, frame = _get(server, '/api/universal/canvas?screen=home')
    assert status == 200 and reads and frame['canvas_deferred']


def test_baboom_first_catalogue_migration_authorizes_latest_head_and_retries(saved_home_server, monkeypatch):
    server, _, _ = saved_home_server
    store, registry = server.universal_store, server.universal_registry
    field = object.__getattribute__(registry, 'baboom_command_catalog')
    assert isinstance(field, DeferredRegistryField) and field.group._values is None
    original_factory = field.group.factory
    original_read = app._require_application_authorization
    attempts, admitted = [], []

    def first_demand():
        attempts.append(True)
        if len(attempts) == 1:
            raise app.InvalidCell('fixture first catalogue read refused')
        from nodelang.universal_cell import Cell, NULL_CELL_ID
        store.commit(store.revision, create=(Cell('test:home:catalogue-migration',
            NULL_CELL_ID, NULL_CELL_ID, b'verified first-demand fixture'),))
        return original_factory()

    def verified_read(snapshot, current, action, root, **kwargs):
        if action == 'inspect' and root == app._BABOOM_COMMAND_CATALOG_ROOT:
            admitted.append((snapshot.revision, store.revision))
        return original_read(snapshot, current, action, root, **kwargs)

    monkeypatch.setattr(field.group, 'factory', first_demand)
    monkeypatch.setattr(app, '_require_application_authorization', verified_read)
    context = registry.authorization.session.context(minimum_validity_seconds=5)
    with pytest.raises(app.InvalidCell, match='fixture first catalogue read refused'):
        app.resolve_universal_baboom_utterance(store, registry, utterance='baboom status',
            authentication_context=context)
    assert field.group._values is None and not admitted
    before = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='first-demand catalogue fixture'):
        command = app.resolve_universal_baboom_utterance(store, registry, utterance='baboom status',
            authentication_context=context)
    assert len(attempts) == 2 and field.group._values is not None and store.revision > before
    assert admitted and all(bound == current for bound, current in admitted)
    assert command['intent'] == 'status' and command['revision'] == store.revision


def test_released_theme_owner_scan_keeps_unrelated_saved_scope_deferred_and_unique(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(
        Path(app.__file__).parent / 'data/public_runtime_map.json'))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    keys.add_key('archhub.local.court-attestation', b's' * 32)
    path = tmp_path / 'released-home.sqlite3'
    store, registry = app.build_universal_application(resolve_map_path(), CellStore(path), key_provider=keys)
    member = 'test:home:saved-theme-member'
    try:
        store.commit(store.revision, create=(Cell(member, NULL_CELL_ID, NULL_CELL_ID, b'Saved member'),))
        domain = registry.map.domains['ui']
        view, _ = app.provision_universal_view_session(store, registry, member, visible_roots=(domain,))
        authority = registry.authorization
        member_context = authority.broker.mint_authenticated_context(member,
            tenant_root=authority.tenant_root, assurance_root=authority.assurance_root, lifetime_seconds=120)
        app.set_universal_scope(store, registry, domain, authentication_context=member_context)
        expected = app.project_universal_canvas(store, registry, authentication_context=member_context)
        source = app.preview_universal_theme(store, registry, {'accent': '#2266aa'})
        released, _ = app.promote_universal_theme_to_shared(store, registry, source_revision_root=source)
        app.assign_released_universal_theme(store, registry, authority.subject_root, released)
    finally:
        store.close()

    store = CellStore(path)
    try:
        store, registry = app.restore_universal_application(resolve_map_path(), store, key_provider=keys, lazy=True)
        assert view.root_id == 'app:view-session:' + app._part(member) and '%3A' in view.root_id
        assert app._is_application_view_root(registry.authorization.session.root_id, registry.authorization)
        assert app._is_application_view_root(view.root_id, registry.authorization)
        assert all(not app._is_application_view_root(view.root_id + suffix, registry.authorization)
            for suffix in (':scope-trail', ':scope-exposure', ':composition-history',
                           ':action-history', ':inspector-lens', ':properties-panel'))
        assert member not in {item.subject_root for item in registry.view_sessions.loaded_values()}
        saved_loader = registry.lazy_scope_loader

        def forbidden(*args, **kwargs):
            pytest.fail('released Home theme ownership must not open an unrelated saved scope')

        object.__setattr__(registry, 'lazy_scope_loader', forbidden)
        try:
            with monkeypatch.context() as metadata_only:
                metadata_only.setattr(app, '_nested_canvas_scope', forbidden)
                metadata_only.setattr(store, 'commit', forbidden)
                context = registry.authorization.session.context(minimum_validity_seconds=5)
                frame = app.project_universal_home_frame(store, registry, authentication_context=context)
        finally:
            object.__setattr__(registry, 'lazy_scope_loader', saved_loader)
        assert frame['configuration']['binding_mode'] == 'direct-release'
        assert frame['configuration']['theme']['accent'] == '#2266aa'
        assert registry.view_sessions[member].root_id == view.root_id
        assert app._read_view_scope_trail_structure(store.snapshot(), registry,
            registry.view_sessions[member])[-1] == expected['scope']['current'] == domain
        authority = registry.authorization
        member_context = authority.broker.mint_authenticated_context(member,
            tenant_root=authority.tenant_root, assurance_root=authority.assurance_root, lifetime_seconds=120)
        full = app.project_universal_canvas(store, registry, authentication_context=member_context)
        assert full['scope']['current'] == expected['scope']['current']
        assert [node['id'] for node in full['nodes']] == [node['id'] for node in expected['nodes']]
        # The original complete uniqueness scanner still refuses two owners;
        # a metadata-only read must never accept the first apparent match.
        original_views = registry.view_sessions
        founder = original_views[authority.subject_root]
        object.__setattr__(registry, 'view_sessions', {'first': founder, 'second': founder})
        try:
            with pytest.raises(InvalidCell, match='theme revision has no unique owning asset'):
                app._theme_revision_owner(store.snapshot(), registry, released)
        finally:
            object.__setattr__(registry, 'view_sessions', original_views)
    finally:
        store.close()


@pytest.mark.parametrize('saved_home_server', [True], indirect=True)
def test_home_graph_index_keeps_root_admission_and_titles_without_saved_canvas(saved_home_server, monkeypatch):
    server, expected, _ = saved_home_server
    store, registry = server.universal_store, server.universal_registry
    expected_index = expected['_graph_index']
    assert any(row['title'] == 'Home metadata graph' for row in expected_index['graphs'])
    original_roots = app._session_canvas_roots
    root_modes = []

    def admitted_roots(*args, **kwargs):
        root_modes.append(kwargs.get('root_only', False))
        return original_roots(*args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail('Home graph index must not project the full or saved nested canvas')

    before = store.revision
    saved_loader = registry.lazy_scope_loader
    object.__setattr__(registry, 'lazy_scope_loader', forbidden)
    try:
        with monkeypatch.context() as root_metadata:
            for name in ('project_universal_canvas', '_project_universal_canvas_answer',
                         '_nested_canvas_scope', '_read_view_scope_trail'):
                root_metadata.setattr(app, name, forbidden)
            root_metadata.setattr(app, '_session_canvas_roots', admitted_roots)
            root_metadata.setattr(store, 'commit', forbidden)
            status, index = _get(server, '/api/universal/graphs?screen=home')
    finally:
        object.__setattr__(registry, 'lazy_scope_loader', saved_loader)
    assert status == 200 and index['graphs'] == expected_index['graphs']
    assert index['current_graph'] == expected_index['current_graph']
    assert index['canvas']['canvas_deferred'] is True and root_modes == [True]
    assert index['canvas']['scope']['current'] == expected['scope']['current']
    assert store.revision == before
    status, _ = _get(server, '/api/universal/graphs?screen=home', authenticated=False)
    assert status == 403

    def denied_audience(*args, **kwargs):
        raise AuthorizationDenied('fixture root resource-audience grant revoked')

    with monkeypatch.context() as refused:
        refused.setattr(app, '_require_resource_audience_authority', denied_audience)
        status, body = _get(server, '/api/universal/graphs?screen=home')
    assert status == 403 and 'fixture root resource-audience grant revoked' in body['error']
