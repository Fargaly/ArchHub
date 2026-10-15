"""Home starts stored composite definitions, ranked by actual completed runs."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import commit_intent, universal_application as app, universal_pipeline as pipeline
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import NULL_CELL_ID, Cell


@pytest.fixture
def home(tmp_path, monkeypatch):
    from nodelang import pipeline_engines

    def refuse_live_probe(*args, **kwargs):
        raise AssertionError('Home template court cannot call live services')

    monkeypatch.setattr(pipeline_engines, '_brain_call', refuse_live_probe)
    monkeypatch.setattr(pipeline_engines, 'probe_connectors', refuse_live_probe)
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(
        Path(app.__file__).parent / 'data/public_runtime_map.json'))
    monkeypatch.setattr(ApplicationServer, '_probe_hosts', staticmethod(lambda: []))
    monkeypatch.setattr(ApplicationServer, '_probe_brain', staticmethod(lambda: {'ok': False}))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'h' * 32)
    keys.add_key('archhub.local.court-attestation', b'f' * 32)
    server = ApplicationServer(universal_state_path=tmp_path / 'home.sqlite3',
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_brain_cloud_sync=False, enable_machine_projection_prewarm=False,
        live_watch=False).start()
    try:
        yield server
    finally:
        server.close()


def request(server, path, body=None, expected=200):
    call = Request(server.url + path, headers={'Content-Type': 'application/json',
        'Origin': server.url, 'Cookie': 'ArchHub-Session=' + server.browser_session_token,
        'X-ArchHub-CSRF': server.browser_csrf_token},
        data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(call, timeout=60) as response:
            status, result = response.status, json.loads(response.read())
    except HTTPError as exc:
        status, result = exc.code, json.loads(exc.read())
    assert status == expected, result
    return result


def install_template(server, item, children=2, invalid_last=False):
    """The producer fixture writes the actual library relation, never UI rows."""
    store = server.universal_store
    roles = pipeline._ENGINE_LIBRARY_ROLES
    root = pipeline.engine_library_entry_root(item)
    parts = [{'title': 'Stored step ' + str(i), 'engine': 'library.filter_field',
              'params': {'template': '{value}', 'value': str(i)}} for i in range(children)]
    if invalid_last:
        parts[-1]['params']['definition'] = 'not-an-editable-parameter'
    cells = pipeline._entry_cells(item, item, 'A stored composite',
        {'engine': '', 'params': {}}, children=parts)
    section = pipeline.engine_library_section_root('home3-court')
    if section not in store.snapshot().cells:
        label = section + ':label'
        composed = app.compose_relation_cells(((roles['label'], label), (roles['entry'], root)),
            relation_id=section)
        cells += [Cell(label, NULL_CELL_ID, NULL_CELL_ID, b'Court templates'), *composed.cells]
        patch = app.prepare_append_relation_members(store.snapshot(), pipeline.ENGINE_LIBRARY_ROOT,
            ((roles['section'], section),))
    else:
        patch = app.prepare_append_relation_members(store.snapshot(), section, ((roles['entry'], root),))
    with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='stored template fixture'):
        store.commit(store.revision, create=tuple(cells) + patch.create, replace=patch.replace)
    return parts


def test_home_templates_empty_is_real_library_read(home):
    before = home.universal_store.revision
    payload = request(home, '/api/universal/node-library?templates=1')
    assert payload['templates'] == []
    assert home.universal_store.revision == before


def test_template_start_creates_one_group_with_exact_stored_children(home):
    parts = install_template(home, 'Court package', 3)
    listing = request(home, '/api/universal/node-library?templates=1')['templates']
    assert listing[0]['children'] == parts
    before = request(home, '/api/universal/canvas')
    started = request(home, '/api/universal/node-create', {'template': 'Court package',
        'expected_scope': before['scope']['current']})
    assert len(started['children']) == 3
    canvas = request(home, '/api/universal/canvas')
    new = {row['id'] for row in canvas['nodes']} - {row['id'] for row in before['nodes']}
    assert new == {started['root']}
    members = app.read_relation(home.universal_store.snapshot(), started['root'])
    inner = {m.participant_id for m in members if m.role_id == home.universal_registry.roles['member']}
    assert inner == set(started['children'])
    assert request(home, '/api/universal/node-library?templates=1')['templates'][0]['run_count'] == 0
    revision = home.universal_store.revision
    request(home, '/api/universal/node-create', {'template': 'missing'}, expected=400)
    request(home, '/api/universal/node-create', {'template': 'Court package',
        'expected_scope': 'stale-scope'}, expected=400)
    assert home.universal_store.revision == revision
    install_template(home, 'Invalid final child', 3, invalid_last=True)
    revision = home.universal_store.revision
    request(home, '/api/universal/node-create', {'template': 'Invalid final child'}, expected=400)
    assert home.universal_store.revision == revision, 'invalid later children leave no partial nodes'


def test_template_order_counts_completed_runs_and_survives_fresh_projection(home):
    install_template(home, 'Less used')
    install_template(home, 'Most used')
    context = home._resolve_browser_session(home.browser_session_token).context
    for item, runs in [('Less used', 1), ('Most used', 3)]:
        started = request(home, '/api/universal/node-create', {'template': item})
        with home.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION,
                actor='court', reason='run the stored composite'):
            app.set_universal_scope(home.universal_store, home.universal_registry,
                started['root'], authentication_context=context)
            for _ in range(runs):
                result = pipeline.run_universal_pipeline(home.universal_store,
                    home.universal_registry,
                    effect_engines={'library.filter_field': lambda params, feeds: ({'out': params['value']}, str(params['value']))},
                    authentication_context=context)
                assert not result['pending']
            pipeline.run_universal_pipeline(home.universal_store, home.universal_registry,
                effect_engines={'library.filter_field': lambda params, feeds: (_ for _ in ()).throw(
                    ValueError('fixture engine refused'))}, authentication_context=context)
            pipeline.run_universal_pipeline(home.universal_store, home.universal_registry,
                effect_engines={'library.filter_field': lambda params, feeds: ({'ok': False}, 'Refused')},
                authentication_context=context)
            app.set_universal_scope(home.universal_store, home.universal_registry,
                home.universal_registry.canvas_root, authentication_context=context)
    listing = request(home, '/api/universal/node-library?templates=1')['templates']
    assert [(row['id'], row['run_count']) for row in listing] == [('Most used', 3), ('Less used', 1)]
