"""Exercise conditional freshness on the real existing ApplicationServer owner."""
from nodelang.application_server import ApplicationServer
from tests_replica.test_canvas_layout_save_is_one_act import _json


def test_repeated_owner_reads_use_one_index_and_only_the_requested_values(monkeypatch):
    from nodelang import universal_application as app, universal_pipeline as pipeline
    from nodelang.canvas_graph_owner import CanvasOwner
    from tests_replica.test_canvas_property_owner_index import _fixture
    store, registry = _fixture(owners=40, per_owner=2, orphans=0)
    original = app._text
    reads = []
    def text(snapshot, root):
        reads.append(root)
        return original(snapshot, root)
    monkeypatch.setattr(app, '_text', text)
    monkeypatch.setattr(pipeline, '_text', text)
    @app._with_canvas_property_owner_index
    def run():
        ops = CanvasOwner(store, registry, None)
        for i in range(5):
            assert ops._rows(None, 'index:owner:' + str(i))['title']['value'] == 'v'
    try:
        run()
        assert len(reads) <= 20, len(reads)
    finally:
        store.close()


def test_owner_rows_preserve_legacy_skip_of_an_unrelated_invalid_property():
    from nodelang import universal_application as app
    from nodelang.canvas_graph_owner import CanvasOwner
    from tests_replica.test_canvas_property_owner_index import _fixture
    store, registry = _fixture(owners=2, per_owner=1, orphans=0)
    try:
        patch = app.prepare_append_relation_members(store.snapshot(), registry.canvas_root,
            ((registry.roles['property'], 'index:value:0:0'),))
        store.commit(store.revision, create=patch.create, replace=patch.replace)
        assert CanvasOwner(store, registry, None)._rows(None, 'index:owner:1')['title']['value'] == 'v'
    finally:
        store.close()


def test_card_metadata_preserves_read_only_and_technical_properties():
    from nodelang import universal_application as app, commit_intent
    server = ApplicationServer(enable_machine_transport=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        assert _json(server, '/api/universal/graph-create', {'title': 'Metadata court'})[0] == 200
        status, made = _json(server, '/api/universal/node-create', {'title': 'Value',
            'engine': 'data.constant', 'params': {'value': 'before', 'last_result': '{}',
                'last_attempt': '0', 'responsibility': 'owner'}, 'x': 80, 'y': 80})
        assert status == 200, made
        _, canvas = _json(server, '/api/universal/canvas')
        node = next(n for n in canvas['nodes'] if n['id'] == made['root'])
        rows = {p['label']: p for p in node['params']}
        assert rows['value']['editable'] is True
        assert all(rows[key]['editable'] is False for key in ('engine', 'last_result', 'last_attempt', 'responsibility'))
        row = rows['value']
        patch = app.prepare_append_relation_members(server.universal_store.snapshot(), row['relation'],
            ((server.universal_registry.roles['read-only'], row['value_root']),))
        with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub', reason='isolated read-only fixture'):
            server.universal_store.commit(server.universal_store.revision, create=patch.create, replace=patch.replace)
        status, refused = _json(server, '/api/universal/set-property', {'relation': row['relation'], 'value': 'after'})
        assert status == 400, refused
        assert 'read-only graph property cannot be edited' in refused['error']
        fresh = app.project_universal_canvas(server.universal_store, server.universal_registry)
        node = next(n for n in fresh['nodes'] if n['id'] == made['root'])
        row = next(p for p in node['params'] if p['label'] == 'value')
        assert row['editable'] is False and row['value'] == 'before'
    finally:
        server.close()


def test_unchanged_freshness_uses_the_admitted_session_projection(monkeypatch):
    server = ApplicationServer(enable_machine_transport=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        status, canvas = _json(server, '/api/universal/canvas')
        assert status == 200
        def forbid(*args, **kwargs):
            raise AssertionError('unchanged freshness must not project the graph')
        monkeypatch.setattr(server, 'project_interaction_canvas', forbid)
        status, result = _json(server, '/api/universal/canvas?since_revision=' + str(canvas['revision']))
        assert status == 200, result
        assert result == {'ok': True, 'unchanged': True, 'revision': canvas['revision'],
            'scope': canvas['scope']['current'], 'graph_id': canvas['application_root']}
        assert len(str(result).encode()) < 1024
        from nodelang.canvas_graph_owner import CanvasOwner
        monkeypatch.setattr(CanvasOwner, 'canvas', forbid)
        status, tick = _json(server, '/api/universal/canvas-op', {'op':'scheduler_tick','args':[],'since_revision':canvas['revision']})
        assert status == 200 and tick['unchanged'] is True, tick
        assert len(str(tick).encode()) < 1024
    finally:
        server.close()


def test_changed_freshness_returns_the_new_authorized_projection():
    server = ApplicationServer(enable_machine_transport=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        status, before = _json(server, '/api/universal/canvas')
        assert status == 200
        status, made = _json(server, '/api/universal/graph-create', {'title': 'FIXCANVAS isolated graph'})
        assert status == 200, made
        status, after = _json(server, '/api/universal/canvas?since_revision=' + str(before['revision']))
        assert status == 200, after
        assert after['revision'] > before['revision']
        assert after['scope']['current'] == made['graph']['id']
        assert not after.get('unchanged')
    finally:
        server.close()


def test_property_save_returns_the_committed_canvas_in_its_single_response():
    server = ApplicationServer(enable_machine_transport=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        status, _ = _json(server, '/api/universal/graph-create', {'title': 'Property court'})
        assert status == 200
        status, made = _json(server, '/api/universal/node-create',
            {'title': 'Value', 'engine': 'data.constant', 'params': {'value': 'before'}, 'x': 80, 'y': 80})
        assert status == 200, made
        _, canvas = _json(server, '/api/universal/canvas')
        node = next(node for node in canvas['nodes'] if node['id'] == made['root'])
        row = next(row for row in (node.get('properties') or node.get('params') or []) if row['label'] == 'value')
        assert row['editable'] is True
        status, saved = _json(server, '/api/universal/set-property', {'relation': row['relation'], 'value': 'after'})
        assert status == 200, saved
        fresh = saved['canvas']
        assert fresh['revision'] >= saved['revision']
        node = next(node for node in fresh['nodes'] if node['id'] == made['root'])
        assert next(row['value'] for row in (node.get('properties') or node.get('params') or []) if row['label'] == 'value') == 'after'
        status, delta = _json(server, '/api/universal/set-property', {'relation': row['relation'],
            'value': 'delta', 'projection_mode': 'interaction-delta-v1', 'projection_revision': fresh['revision']})
        assert status == 200, delta
        assert delta['projection_mode'] == 'interaction-delta-v1'
        assert delta['base_revision'] == fresh['revision']
        assert 'canvas' not in delta and 'nodes' not in delta
        changed = next(n for n in delta['node_patches'] if n['id'] == made['root'])
        assert next(p['value'] for p in changed['params'] if p['label'] == 'value') == 'delta'
    finally:
        server.close()


def test_clean_unchanged_freshness_reuses_the_same_authorized_view(tmp_path, monkeypatch):
    from tests_replica.test_clean_server_visual_projection import (
        _provision_clean_runtime, _start_clean_server, _issue_clean_session, _json as clean_json)
    built, provider = _provision_clean_runtime(tmp_path)
    _issue_clean_session(built, token='fixcanvas-clean-token', csrf='fixcanvas-clean-csrf')
    server = _start_clean_server(built, provider)
    try:
        status, canvas = clean_json(server.url, '/api/universal/canvas', token='fixcanvas-clean-token')
        assert status == 200, canvas
        def forbid(*args, **kwargs):
            raise AssertionError('unchanged clean freshness must not project the graph')
        monkeypatch.setattr(server, '_canvas', forbid)
        status, result = clean_json(server.url, '/api/universal/canvas?since_revision=' + str(canvas['revision']), token='fixcanvas-clean-token')
        assert status == 200, result
        assert result == {'ok': True, 'unchanged': True, 'revision': canvas['revision'],
            'scope': canvas['root'], 'graph_id': canvas['graph_id']}
        assert len(str(result).encode()) < 1024
    finally:
        server.close()
        built.location.authority.store.close()


def test_property_projection_reuses_one_index_per_immutable_request(monkeypatch):
    from nodelang import universal_application as app
    from tests_replica.test_canvas_property_owner_index import _fixture
    store, registry = _fixture(owners=40, per_owner=2, orphans=0)
    original=app.read_relation
    reads=[]
    def read(snapshot, root, **kwargs):
        reads.append(root)
        return original(snapshot, root, **kwargs)
    monkeypatch.setattr(app, 'read_relation', read)
    @app._with_canvas_property_owner_index
    def run(snapshot, roots):
        for _ in range(5):
            assert len(app._property_index(snapshot, registry, roots)) == 40
    try:
        snapshot=store.snapshot()
        roots=app._canvas_roots(snapshot, registry)[2]
        reads.clear()
        run(snapshot, roots)
        assert len(reads) <= len(roots), (len(reads), len(roots))
    finally:
        store.close()


def test_parameter_delta_omits_unchanged_ports_and_repeated_metadata():
    from copy import deepcopy
    from nodelang.application_server import _interaction_canvas_delta
    before={'revision':4,'configuration':{'design_system':{'control_catalog':{'controls':[]}}},
        'nodes':[{'id':'n','selected':False,'x':0,'y':0,'params':[{'value':'before'}],
            'ports':[{'id':'p','descriptor':[{'attributes':{'description':'x'*70000}}]}]}], 'wires':[],'connections':[],
        'action_history':{'root':'history','can_undo':True,'can_redo':False,'transactions':[{'root':'old','value':'x'*70000}]},
        'interaction_projection':{'revision':4,'bindings':[{'control':'n','description':'x'*70000}]}}
    after=deepcopy(before);after['revision']=5
    after['nodes'][0]['params']=[{'value':'after'}]
    after['action_history']['transactions'].insert(0,{'root':'new'})
    after['interaction_projection']['revision']=5
    delta=_interaction_canvas_delta(after,base_revision=4,previous_projection=before,compact=True)
    import json
    assert len(json.dumps(delta).encode()) < 65536
    assert 'ports' not in delta['node_patches'][0]


def test_requested_property_admission_matches_full_index_without_other_owner_reads(monkeypatch):
    from types import SimpleNamespace
    from nodelang import universal_application as app
    from tests_replica.test_canvas_property_owner_index import _fixture
    store, registry=_fixture(owners=40,per_owner=2,orphans=0)
    registry.roles['scope']=registry.roles['property']
    roots=('index:property:0:0',)
    monkeypatch.setattr(app,'_session_canvas_roots',lambda *a,**k:(('index:owner:0','index:owner:1'),(),roots))
    view=SimpleNamespace(properties_lens_root=registry.canvas_root)
    snapshot=store.snapshot();wanted=('index:property:1:0','index:property:10:0')
    try:
        full=app._session_editable_property_roots(snapshot,registry,view)
        original=app.read_relation;reads=[]
        def read(snapshot,root,**kw):reads.append(root);return original(snapshot,root,**kw)
        monkeypatch.setattr(app,'read_relation',read)
        targeted=app._session_editable_property_roots(snapshot,registry,view,wanted)
        assert targeted==full.intersection(wanted)=={'index:property:1:0'}
        assert set(reads)<=set(wanted)|{registry.canvas_root}
    finally:store.close()


def test_studio_bootstrap_defers_candidate_products_and_saves_one_real_socket_pair():
    import json
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    server=ApplicationServer(enable_machine_transport=False,enable_machine_projection_prewarm=False,live_watch=False).start()
    def studio(path,body=None):
        req=Request(server.url+path,data=None if body is None else json.dumps(body).encode(),headers={
            'Content-Type':'application/json','X-ArchHub-Session':server.browser_session_token,
            'X-ArchHub-CSRF':server.browser_csrf_token,'X-ArchHub-Renderer':'studio'})
        try:
            with urlopen(req,timeout=120) as response:return response.status,json.load(response)
        except HTTPError as e:return e.code,json.load(e)
    try:
        created=studio('/api/universal/graph-create',{'title':'Scoped socket pair'});assert created[0]==200,created
        a=studio('/api/universal/node-create',{'title':'Number','engine':'data.constant','params':{'value':'7'},'x':80,'y':80})[1]['root']
        b=studio('/api/universal/node-create',{'title':'Expression','engine':'math.expression','params':{'expression':'a+1'},'x':400,'y':80})[1]['root']
        status,before=studio('/api/universal/canvas');assert status==200,before
        status,opened=studio('/api/universal/graph-open',{'root':before['scope']['current']});assert status==200,opened
        before=opened['canvas'];assert 'topology_targets' in before and before['interaction_projection']['bindings']
        assert all('connect_choices' not in p for n in before['nodes'] for p in n['ports'])
        source=next(p['id'] for n in before['nodes'] if n['id']==a for p in n['ports'] if p['name']=='value' and p['side']=='source')
        target=next(p['id'] for n in before['nodes'] if n['id']==b for p in n['ports'] if p['name']=='a' and p['side']=='target')
        port=next(p for n in before['nodes'] if n['id']==a for p in n['ports'] if p['id']==source)
        binding=next(b for b in before['interaction_projection']['bindings'] if b['control']==port['connect_control'])
        index=next(i for i,p in enumerate(before['topology_targets']) if p['owner']==b and p['id']==target)
        body={'interaction':binding['interaction'],'control':binding['control'],'event':binding['event'],
              'revision':before['revision'],'projection_mode':'topology-delta-v1',
              'event_facts':[{'input':port['connect_event_fact_input'],'value':index}]}
        revision=server.universal_store.revision
        refused,denied=studio('/api/universal/interaction',{**body,'event_facts':[{'input':port['connect_event_fact_input'],'value':-1}]})
        assert refused==400 and server.universal_store.revision==revision,denied
        status,saved=studio('/api/universal/interaction',body);assert status==200,saved
        assert saved['projection_mode']=='topology-delta-v1'
        status,after=studio('/api/universal/canvas');assert status==200
        assert any(w['source']==a and w['target']==b for w in after['wires'])
        _,legacy=_json(server,'/api/universal/canvas')
        assert 'topology_targets' not in legacy
        assert any(p.get('connect_choices') is not None for n in legacy['nodes'] for p in n['ports'] if p.get('connect_control'))
        _,again=studio('/api/universal/canvas');assert 'topology_targets' in again
        assert all('connect_choices' not in p for n in again['nodes'] for p in n['ports'])
    finally:server.close()


def test_cached_property_projection_preserves_the_original_structural_bound():
    import pytest
    from nodelang import universal_application as app
    from nodelang.cell_protocols import CellBatch
    from nodelang.universal_cell import Cell, NULL_CELL_ID, MatchBudgetExceeded
    from tests_replica.test_canvas_property_owner_index import _fixture
    store, registry = _fixture(owners=1, per_owner=1, orphans=0)
    try:
        batch = CellBatch(store)
        roots = ['wide:value:' + str(i) for i in range(20)]
        for root in roots:
            batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, b'v'))
        batch.relation([(registry.roles['value'], root) for root in roots], relation_id='wide:property')
        batch.commit()
        with pytest.raises(MatchBudgetExceeded):
            app._property_index(store.snapshot(), registry, ('wide:property',))
    finally:
        store.close()
