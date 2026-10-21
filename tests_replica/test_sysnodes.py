"""System nodes use owner settings cells rather than engine presentation."""
import pytest
from nodelang import universal_application as app
from nodelang.universal_cell import InvalidCell


def test_generation_document_preserves_route_and_real_typed_defaults():
    route, generation = app._decode_composer_model_document(
        '{"route":"openrouter/vendor/model-a","generation":{"temperature":0.2,"top-p":0.8,"max tokens":2048}}')
    assert route == 'openrouter/vendor/model-a'
    assert generation == {'temperature':0.2, 'top-p':0.8, 'max tokens':2048}


def test_old_composer_route_migrates_without_losing_pick():
    assert app._decode_composer_model_document('openrouter/vendor/model-a') == (
        'openrouter/vendor/model-a', {'temperature':0.7, 'top-p':0.95, 'max tokens':4096})


@pytest.mark.parametrize('generation', [
    {'temperature':2.1}, {'top-p':-0.1}, {'max tokens':0},
    {'temperature':True}, {'max tokens':256.5}, {'unused':1},
])
def test_generation_rejects_invalid_and_unread_settings(generation):
    with pytest.raises(InvalidCell):
        app._normalize_model_defaults(generation)


def test_wire_labels_name_real_relation_and_flow():
    assert app._application_relation_label({'role_label':'owns work'}, 'a', 'b') == 'owns work'
    assert app._application_relation_label({'params':[{'label':'reason','value':'model request'}]}, 'a','b') == 'model request'
    assert app._application_relation_label({}, 'a','b') == 'a → b'

@pytest.fixture(scope='module')
def application():
    from nodelang.map_import import resolve_map_path
    return app.build_universal_application(resolve_map_path())


def test_every_application_node_exposes_owner_settings_or_real_open_action(application):
    store, registry = application
    canvas = app.project_universal_canvas(store, registry)
    nodes = [node for node in canvas['nodes'] if node.get('application')]
    assert nodes
    for node in nodes:
        assert node['params'] or node['actions'], node['label']
        assert all(row['label'] != 'halted' for row in node['params'])
        assert 'Scope for' not in str(node.get('subtitle', ''))
        assert 'Branch / loop / switch' not in str(node.get('subtitle', ''))
        assert all(row.get('editable') is True for row in node['params'])
        assert node['state']['members'] == node['member_count']
    system_ids = {node['id'] for node in nodes}
    system_wires = [wire for wire in canvas['wires'] if wire['source'] in system_ids and wire['target'] in system_ids]
    assert len(system_wires) == len(app._APPLICATION_SETTING_READS)
    assert all(wire['label'].strip() and wire['reader'] for wire in system_wires)
    assert all(wire['id'].startswith('app:relation:setting-reader:') for wire in system_wires)


def test_workshop_properties_and_runtime_use_exact_same_cell(application):
    store, registry = application
    root = app._system_tool_canvas_root('tool_workshop')
    app.apply_universal_canvas_gesture(store, registry, roots=[root], focus_root=root)
    canvas = app.project_universal_canvas(store, registry)
    row = next(row for row in canvas['properties'] if row['label']=='stale_claim_after_idle_minutes')
    node = next(row for row in canvas['nodes'] if row['id']==root)
    param = next(param for param in node['params'] if param['label']==row['label'])
    assert row['value_root'] == param['value_root']
    app.edit_universal_property(store, registry, row['relation'], '17')
    assert app._workshop_board_stale_claim_after_idle_minutes(store.snapshot(), registry) == 17
    canvas = app.project_universal_canvas(store, registry)
    assert next(row for row in canvas['properties'] if row['label']=='stale_claim_after_idle_minutes')['value'] == 17
    app._set_workshop_board_int_param(store, registry, 'stale_claim_after_idle_minutes', 19, lower=1, upper=1440)
    canvas = app.project_universal_canvas(store, registry)
    assert next(row for row in canvas['properties'] if row['label']=='stale_claim_after_idle_minutes')['value'] == 19
    with pytest.raises(InvalidCell):
        app.edit_universal_property(store, registry, row['relation'], '0')


def test_model_options_persist_in_existing_owner_asset_and_reach_request_builder(application, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.agent_composer import _generation_options
    from types import SimpleNamespace
    store, registry = application
    current = app.read_universal_composer_model(store.snapshot(), registry)
    app.set_universal_composer_model(store, registry, 'openrouter/vendor/model-a',
        base_revision_root=current['revision'], generation={'temperature':.25, 'top-p':.8, 'max tokens':2048})
    canvas = app.project_universal_canvas(store, registry)
    assert canvas['configuration']['model_defaults']['temperature'] == .25
    model = next(node for node in canvas['nodes'] if node['id']==registry.map.domains['models'])
    temperature = next(row for row in model['params'] if row['label']=='temperature')
    setting = app.read_universal_composer_model(store.snapshot(), registry)
    assert temperature['value_root'] == setting['value_root']
    owner = SimpleNamespace(universal_store=store, universal_registry=registry)
    assert _generation_options(ApplicationServer._read_agent_generation(owner)) == {
        'temperature':.25, 'top_p':.8, 'max_tokens':2048}
    import json
    from io import BytesIO
    from nodelang import agent_composer, model_router
    captured = []
    def fake_provider(request, timeout):
        captured.append(json.loads(request.data))
        return BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps({'actions':[], 'answer':'fixture reply'})}, 'finish_reason':'stop'}]}).encode())
    def fake_route(*args, **kwargs):
        return model_router.route_chat(*args, **kwargs, opener=fake_provider, environ={},
            secrets_loader=lambda name:'synthetic-fixture-key' if name=='openrouter' else '', cloud_session=None)
    monkeypatch.setattr(agent_composer, 'route_chat', fake_route)
    monkeypatch.setattr(agent_composer, '_model_supports_tools', lambda model:True)
    agent_composer._chat('hello', 'fixture context', 'openrouter/vendor/model-a',
        generation=ApplicationServer._read_agent_generation(owner))
    assert captured and captured[0]['temperature'] == .25
    assert captured[0]['top_p'] == .8 and captured[0]['max_tokens'] == 2048
    saved_content = store.snapshot().cells[setting['value_root']].atom.decode()
    assert app._decode_composer_model_document(saved_content)[1]['temperature'] == .25


def test_accent_is_same_personal_settings_revision_and_repaints(application):
    store, registry = application
    canvas = app.project_universal_canvas(store, registry)
    app.preview_universal_theme(store, registry, {'accent':'#00aa44'},
        base_revision_root=canvas['configuration']['personal_wip_heads'][0])
    canvas = app.project_universal_canvas(store, registry)
    node = next(node for node in canvas['nodes'] if any(row.get('setting',{}).get('kind')=='theme' for row in node.get('params',[])))
    accent = next(row for row in node['params'] if row['label']=='accent')
    assert accent['value'] == canvas['configuration']['theme']['accent'] == '#00aa44'
    assert accent['value_root'] in store.snapshot().cells
    assert canvas['configuration']['design_system']['tokens']['action.primary']['value'] == '#00aa44'



def test_stale_claim_policy_changes_actual_release_eligibility(application, monkeypatch):
    store, registry = application
    monkeypatch.setattr(app.time, 'time', lambda:2200.0)
    monkeypatch.setattr(app, 'project_universal_governed_work_index', lambda *a, **k: {'items':[
        {'root':'fixture:work', 'claimant_session':'fixture:dead-agent', 'operational':{'current_state_label':'claimed'}}]})
    monkeypatch.setattr(app, '_governed_work_last_activity_at', lambda *a:1000.0)
    app._set_workshop_board_int_param(store, registry, 'stale_claim_after_idle_minutes',19,lower=1,upper=1440)
    assert app._workshop_board_plan(store, registry)['release'] == ('fixture:work',)
    app._set_workshop_board_int_param(store, registry, 'stale_claim_after_idle_minutes',21,lower=1,upper=1440)
    assert app._workshop_board_plan(store, registry)['release'] == ()


def test_every_real_application_open_action_commits_authorized_scope_and_returns(application):
    store, registry = application
    canvas = app.project_universal_canvas(store, registry)
    targets = app._project_scope_interaction_targets(canvas)
    roots = [node['id'] for node in canvas['nodes'] if node.get('application')]
    proven = []
    for root in roots:
        assert targets[root] == root
        before = store.revision
        opened = app._set_universal_scope_execution(store, registry, root)
        assert opened.revision > before
        assert opened.materialization.trail[-1] == root
        view = registry.view_sessions[registry.authorization.subject_root]
        assert app._read_view_scope_trail(store.snapshot(), registry, view)[-1] == root
        returned = app._set_universal_scope_execution(store, registry, registry.canvas_root)
        assert returned.materialization.trail[-1] == registry.canvas_root
        proven.append(root)
    assert proven == roots


def test_external_settings_read_signed_host_owner_and_existing_consent_file(tmp_path):
    import uuid
    from nodelang.application_server import _project_external_setting_owners
    from nodelang.cloud_publish_consent import record_cloud_publish_consent, withdraw_cloud_publish_consent
    from nodelang.host_enable import set_host_enabled, _value_root
    from tests_replica.test_clean_server_admission import _provision_clean_runtime
    built, _provider = _provision_clean_runtime(tmp_path, root_name='sysnodes-owner')
    authority = built.location.authority
    projection = {'nodes':[
        {'id':'connectors', 'application':True, 'params':[]},
        {'id':'cloud', 'application':True, 'params':[]},
    ], 'selected':'connectors'}
    state_dir = tmp_path/'cloud-state'
    state_dir.mkdir()
    record_cloud_publish_consent(state_dir, account='fixture@example.test')
    set_host_enabled(authority, 'revit', False, caller=built.caller, command_id=str(uuid.uuid4()))
    def project():
        return _project_external_setting_owners(projection, connectors_root='connectors',cloud_root='cloud',
            host_authority=authority, state_dir=state_dir, account='fixture@example.test')
    canvas = project()
    host = canvas['nodes'][0]['params'][0]
    assert host['value_root'] == _value_root('revit','enabled')
    assert host['value'] is False and canvas['properties'][0]['value_root'] == host['value_root']
    assert canvas['nodes'][1]['params'][0]['value'] is True
    set_host_enabled(authority, 'revit', True, caller=built.caller, command_id=str(uuid.uuid4()))
    withdraw_cloud_publish_consent(state_dir)
    canvas = project()
    assert canvas['nodes'][0]['params'][0]['value'] is True
    assert canvas['nodes'][1]['params'][0]['value'] is False
    assert len(canvas['nodes'][0]['params']) == 1
    authority.store.close()


def test_generation_survives_disk_reopen_in_same_composer_asset(tmp_path):
    from nodelang.universal_cell import CellStore
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.map_import import resolve_map_path
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r'*32)
    keys.add_key('archhub.local.court-attestation', b'c'*32)
    path = tmp_path/'sysnodes.sqlite3'
    store, registry = app.build_universal_application(resolve_map_path(), CellStore(path),key_provider=keys)
    app.set_universal_composer_model(store, registry, '',generation={'temperature':.35,'top-p':.9,'max tokens':1024})
    original = app.read_universal_composer_model(store.snapshot(),registry)
    store.close()
    reopened, restored = app.restore_universal_application(resolve_map_path(),CellStore(path),key_provider=keys)
    try:
        current = app.read_universal_composer_model(reopened.snapshot(),restored)
        assert current['generation']['temperature'] == .35
        assert current['value_root'] == original['value_root']
        canvas = app.project_universal_canvas(reopened,restored)
        assert canvas['configuration']['model_defaults']['max tokens'] == 1024
        assert len([wire for wire in canvas['wires'] if wire['id'].startswith('app:relation:setting-reader:')]) == 8
    finally:
        reopened.close()


def test_application_reader_relations_are_immutable_without_revision_change(application):
    store, registry = application
    canvas = app.project_universal_canvas(store, registry)
    wire = next(wire for wire in canvas['wires'] if wire['id'].startswith('app:relation:setting-reader:'))
    before = store.revision
    reason = 'application reader relations describe code reads and cannot be rewired or disconnected'
    with pytest.raises(InvalidCell, match=reason):
        app.disconnect_universal_connection(store, registry, wire['id'])
    assert store.revision == before
    with pytest.raises(InvalidCell, match=reason):
        app.rewire_universal_connection(store, registry, wire['source_incidence'],wire['target'])
    assert store.revision == before
    app.apply_universal_canvas_gesture(store,registry,roots=[wire['id']],focus_root=wire['id'],
        expected_scope=canvas['scope']['current'])
    selected = app.project_universal_canvas(store,registry)
    held = next(row for row in selected['wires'] if row['id']==wire['id'])
    assert held['selected'] is True and 'disconnect_control' not in held
    assert not any(key.endswith('_rewire_control') for key in held)
