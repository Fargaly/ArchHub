"""Usage-derived defaults are ordinary, connected, user-owned composites."""
import pytest
from nodelang import commit_intent, universal_application as app, universal_pipeline as pipeline
from nodelang.pipeline_engines import PIPELINE_ENGINES
from nodelang.library_engines import engine_runs
from test_home3_templates import home, request


@pytest.mark.parametrize('existing', ['empty-section', 'colliding-item', 'user-composite'])
def test_old_catalogue_members_and_edits_win_over_first_seed(existing):
    from nodelang.universal_cell import CellStore
    store = CellStore()
    roles = pipeline._ENGINE_LIBRARY_ROLES
    section = pipeline.engine_library_section_root('starter')
    cells = [pipeline._text_cell(role, name) for name,role in roles.items()]
    cells.append(pipeline._text_cell(section+':label', 'My section'))
    members = [(roles['label'], section+':label')]
    if existing != 'empty-section':
        item = 'tpl-sheet-register' if existing == 'colliding-item' else 'my-composite'
        children = None if existing == 'colliding-item' else [
            {'title':'Read', 'engine':'revit.read', 'params':{}},
            {'title':'Watch', 'engine':'watch.preview', 'params':{}}]
        cells += pipeline._entry_cells(item, 'My unchanged entry', 'Mine',
            {'engine':'revit.read','params':{}}, children=children)
        members.append((roles['entry'], pipeline.engine_library_entry_root(item)))
    cells += list(app.compose_relation_cells(members, relation_id=section).cells)
    cells += list(app.compose_relation_cells(((roles['section'],section),), relation_id=pipeline.ENGINE_LIBRARY_ROOT).cells)
    with commit_intent.declare(commit_intent.MIGRATION,actor='court',reason='old catalogue migration'):
        store.commit(store.revision,create=cells)
        pipeline.seed_engine_library(store, None)
        before=store.revision
        assert pipeline.seed_engine_library(store, None) == 0
        assert store.revision == before
    groups=pipeline.read_engine_library(store.snapshot())
    starter=next(group for group in groups if group['cat']=='My section')
    if existing != 'empty-section':
        assert starter['items'][0]['title']=='My unchanged entry'
    if existing == 'user-composite':
        assert [entry['id'] for group in groups for entry in group['items'] if entry.get('children')] == ['my-composite']
    assert pipeline._STARTER_MARKER in store.snapshot().cells


def test_fresh_profile_has_runnable_zero_run_starters(home):
    rows = request(home, '/api/universal/node-library?templates=1')['templates']
    assert len(rows) >= 4
    assert all(row['run_count'] == 0 for row in rows)
    import json
    from pathlib import Path
    Path('evidence/tpl_fresh_templates.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    catalogue = request(home, '/api/universal/node-library')['groups']
    engines = {item['engine'] for group in catalogue for item in group['items']}
    for row in rows:
        assert all(part['engine'] in engines for part in row['children'])
        assert all(engine_runs(part['engine'], PIPELINE_ENGINES) for part in row['children'])
    # Edits alter the same catalogue definition; the next Start consumes them.
    edited = rows[0]
    edited['children'][1]['params']['direction'] = 'desc'
    request(home, '/api/universal/node-create', {'template':edited['id'],
        'update':{'title':'My sheet register', 'children':edited['children']}})
    listing = request(home, '/api/universal/node-library?templates=1')['templates']
    assert listing[0]['title'] == 'My sheet register'
    assert listing[0]['children'] == edited['children']
    started = request(home, '/api/universal/node-create', {'template':edited['id']})
    properties = pipeline._owner_properties(home.universal_store.snapshot(), home.universal_registry)
    assert properties[started['children'][1]]['direction'][1] == 'desc'
    before = home.universal_store.revision
    edited['children'][1]['input']['child'] = 100
    request(home, '/api/universal/node-create', {'template':edited['id'],
        'update':{'title':'Invalid', 'children':edited['children']}}, expected=400)
    assert home.universal_store.revision == before


def test_seeding_is_idempotent_and_deleted_starters_stay_deleted(home):
    store, registry = home.universal_store, home.universal_registry
    rows = request(home, '/api/universal/node-library?templates=1')['templates']
    assert rows
    before = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='repeat seed'):
        assert pipeline.seed_engine_library(store, registry) == 0
    assert store.revision == before
    for row in rows:
        request(home, '/api/universal/node-create', {'template':row['id'], 'delete':True})
    assert request(home, '/api/universal/node-library?templates=1')['templates'] == []
    with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='repeat after deletion'):
        pipeline.seed_engine_library(store, registry)
    assert request(home, '/api/universal/node-library?templates=1')['templates'] == []


def test_starter_chains_run_real_engines_on_fake_transports_and_count(home, monkeypatch):
    from types import SimpleNamespace as Obj
    from nodelang import clean_revit_adapter, host_brokers, notion_mcp
    records = [dict(id='b', number='02', name='Second', type='Wall', level='L2', family='B'),
               dict(id='a', number='01', name='First', type='Wall', level='L1', family='A')]
    calls = []
    monkeypatch.setattr(clean_revit_adapter, 'live_sessions', lambda: [{'revit_version': '2026'}])
    def invoke(op, params):
        calls.append(op)
        assert op in {'revit.list_sheets', 'revit.list_walls', 'revit.list_cad_imports', 'revit.list_titleblocks'}
        fields = {'revit.list_sheets':('id','number','name'), 'revit.list_walls':('id','name','type','level'),
                  'revit.list_cad_imports':('id','name'), 'revit.list_titleblocks':('id','name','family')}[op]
        return {'result':[{key:row[key] for key in fields} for row in records]}
    monkeypatch.setattr(clean_revit_adapter, 'invoke', invoke)
    class Items:
        def Sort(self, field, reverse):
            assert (field, reverse) == ('[ReceivedTime]', True)
        def Item(self, index):
            if index > 2:
                raise IndexError
            return Obj(Subject='Mail '+str(index), SenderName='Sender', ReceivedTime='2026-10-'+str(13+index), UnRead=True)
    monkeypatch.setattr(host_brokers, '_com_alive', lambda name: name == 'Outlook.Application')
    monkeypatch.setattr(host_brokers, '_outlook_application', lambda: Obj(GetNamespace=lambda name:
        Obj(GetDefaultFolder=lambda number: Obj(Items=Items()))))
    monkeypatch.setattr(host_brokers, '_notion_token', lambda: '')
    monkeypatch.setattr(notion_mcp, 'connected', lambda: True)
    monkeypatch.setattr(notion_mcp, 'search', lambda query: [{'id':'source', 'title':'Real source', 'url':'https://example.test/source'}])
    store, registry = home.universal_store, home.universal_registry
    context = home._resolve_browser_session(home.browser_session_token).context
    outputs=[]
    outcome=pipeline._pipeline_outcome
    def capture(nodes, wires, evaluation, written, revision):
        outputs.append(evaluation.node_outputs)
        return outcome(nodes,wires,evaluation,written,revision)
    monkeypatch.setattr(pipeline, '_pipeline_outcome', capture)
    rows = request(home, '/api/universal/node-library?templates=1')['templates']
    assert len(rows) >= 4
    assert [row['scenario_frequency'] for row in rows] == sorted(
        [row['scenario_frequency'] for row in rows], reverse=True)
    for row in reversed(rows):
        started = request(home, '/api/universal/node-create', {'template': row['id']})
        assert len(started['children']) == len(row['children'])
        with home.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='execute starter'):
            app.set_universal_scope(store, registry, started['root'], authentication_context=context)
            canvas = app.project_universal_canvas(store, registry, authentication_context=context)
            assert len(canvas['wires']) == len(row['children']) - 1
            result = pipeline.run_universal_pipeline(store, registry, effect_engines=PIPELINE_ENGINES,
                authentication_context=context)
            assert not result['pending'], result
            assert result['ran'] == len(row['children'])
            watched=outputs[-1][started['children'][-1]]['out']
            assert watched['columns'] == row['children'][2]['params']['columns'].split(',')
            assert len(watched['rows']) == (1 if row['id']=='tpl-notion-review' else 2)
            expected_first={'tpl-sheet-register':'01','tpl-model-table':'First','tpl-titleblocks':'A',
                            'tpl-cad-inventory':'First','tpl-inbox-review':'Mail 2','tpl-notion-review':'Real source'}
            assert watched['rows'][0][0] == expected_first[row['id']]
            app.set_universal_scope(store, registry, registry.canvas_root, authentication_context=context)
        listing = request(home, '/api/universal/node-library?templates=1')['templates']
        assert next(r for r in listing if r['id'] == row['id'])['run_count'] == 1
        if row == rows[-1]:
            assert listing[0]['id'] == row['id'], 'real runs beat source frequency'
    assert set(calls) == {'revit.list_sheets', 'revit.list_walls', 'revit.list_cad_imports', 'revit.list_titleblocks'}
