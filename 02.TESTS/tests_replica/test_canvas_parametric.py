"""Parametric .archhub canvas: solve on edit, effects wait for Run, shared edits, agent tools."""
import asyncio
import copy
import json
import threading

import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    yield tmp_path


def workflow(count='3', with_agent=False):
    from nodelang.session_files import catalogue, new_document
    items = {row['id']: row for row in catalogue()}
    doc = new_document('Count first three')
    for key, item, x in (('list', 'n_list', 0), ('slice', 's_slice', 300), ('count', 's_count', 600)):
        doc['nodes'].append({'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                             'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}})
    doc['nodes'][0]['params']['value'] = '[10, 20, 30, 40, 50]'
    doc['nodes'][1]['params']['count'] = count
    doc['wires'] = [{'id': 'a', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'slice', 'socket': 'items'}},
                    {'id': 'b', 'from': {'node': 'slice', 'socket': 'items_out'}, 'to': {'node': 'count', 'socket': 'items'}}]
    if with_agent:
        agent = items['thing:agent:codex']
        doc['nodes'].append({'id': 'agent', 'item': agent['id'], 'type': 'thing.agent', 'title': 'Codex',
                             'params': copy.deepcopy(agent['params']), 'position': {'x': 900, 'y': 0}})
        doc['wires'].append({'id': 'c', 'from': {'node': 'count', 'socket': 'count'}, 'to': {'node': 'agent', 'socket': 'task'}})
    return doc


def test_solve_order_reuses_upstream_and_reaches_downstream():
    from nodelang.canvas_documents import solve
    doc = workflow()
    first = solve(doc, ['list'])
    assert first['solved'] == ['list', 'slice', 'count'] and doc['nodes'][2]['result']['output'] == {'count': 3}
    # Upstream output is reused, not recomputed: a sentinel List output proves it.
    doc['nodes'][0]['result']['output'] = {'value': [1, 2, 3, 4, 5, 6, 7]}
    doc['nodes'][1]['params']['count'] = '5'
    second = solve(doc, ['slice'])
    assert second['solved'] == ['slice', 'count'] and doc['nodes'][2]['result']['output'] == {'count': 5}
    assert second['ms'] >= 0


def test_effect_nodes_wait_for_run(profile):
    from nodelang.canvas_documents import solve
    doc = workflow(with_agent=True)
    result = solve(doc, ['list'])
    assert result['stale'] == ['agent'] and doc['nodes'][3]['result']['status'] == 'Out of date'
    assert not (profile / 'LOCALAPPDATA' / 'ArchHub' / 'workshop' / 'messages.sqlite3').exists()  # nothing was sent


def test_cycle_refused():
    from nodelang.session_files import run_document
    doc = workflow()
    doc['wires'].append({'id': 'loop', 'from': {'node': 'count', 'socket': 'count'}, 'to': {'node': 'list', 'socket': 'x'}})
    with pytest.raises(ValueError, match='Cycle'):
        run_document(doc)


def test_atomic_save_and_locked_concurrent_edits(profile):
    from nodelang import canvas_documents as docs
    from nodelang.session_files import read_document, write_document
    path = profile / 'shared.archhub'
    write_document(path, workflow())
    before = path.read_bytes()
    bad = workflow(); bad['nodes'][0]['position']['x'] = float('nan')
    with pytest.raises(ValueError):
        write_document(path, bad)
    assert path.read_bytes() == before
    def add(n, who):
        for i in range(n):
            docs.edit(path, who, 'add', lambda d, i=i: d['notes'].append({'text': who + str(i)}) or [])
    threads = [threading.Thread(target=add, args=(15, who)) for who in ('agent:claude', 'agent:codex')]
    [t.start() for t in threads]; [t.join() for t in threads]
    final = read_document(path)
    assert len(final['notes']) == 30 and final['properties']['revision'] == 30
    assert {h['by'] for h in final['properties']['history']} == {'agent:claude', 'agent:codex'}


def test_ui_save_merges_concurrent_agent_edit(profile):
    from nodelang import canvas_documents as docs
    from nodelang.session_files import read_document
    path = profile / 'live.archhub'
    ui = docs.commit_ui(path, workflow(), 0)                       # rev 1, the window's base
    base = copy.deepcopy(ui)
    docs.edit(path, 'agent:claude', 'set count', lambda d: (d['nodes'][1]['params'].update(count='2'), ['slice'])[1])
    mine = copy.deepcopy(base)
    mine['nodes'].append({'id': 'note', 'type': 'note', 'params': {}, 'position': {'x': 0, 'y': 300}, 'title': 'Mine'})
    merged = docs.commit_ui(path, mine, docs.revision(base))
    on_disk = read_document(path)
    assert on_disk == merged and {n['id'] for n in merged['nodes']} == {'list', 'slice', 'count', 'note'}
    assert merged['nodes'][1]['params']['count'] == '2'                                      # agent's edit survives
    assert [h['by'] for h in merged['properties']['history']] == ['You', 'agent:claude', 'You']
    undone, _ = docs.undo_last(path, 'You')
    assert {n['id'] for n in undone['nodes']} == {'list', 'slice', 'count'}


def test_model_node_param_writes_router_json(profile):
    from nodelang.settings_owner import read_router_settings
    from nodelang.session_files import SessionFiles, catalogue
    model = next(i for i in catalogue() if i['id'] == 'thing:model:default')
    doc = workflow()
    doc['nodes'].append({'id': 'm', 'item': model['id'], 'type': 'thing.model', 'title': 'Model',
                         'params': dict(model['params'], default_model='openrouter/openrouter/free'), 'position': {'x': 0, 'y': 300}})
    out = SessionFiles().dispatch({'action': 'solve', 'document': doc, 'changed': ['m'],
                                   'params': [{'node': 'm', 'key': 'default_model', 'value': 'openrouter/openrouter/free'}]})
    assert out['written'] == ['default_model'] and out['stale'] == ['m']
    assert read_router_settings()['default_model'] == 'openrouter/openrouter/free'
    stored = json.loads((profile / 'LOCALAPPDATA' / 'ArchHub' / 'settings' / 'router.json').read_text())
    assert stored['default_model'] == 'openrouter/openrouter/free'
    # Generation parameters (temperature, top-p, max tokens) are the Model node's own parameters.
    assert {'temperature', 'top_p', 'max_tokens'} <= set(model['params'])
    out = SessionFiles().dispatch({'action': 'solve', 'document': doc, 'changed': ['m'],
                                   'params': [{'node': 'm', 'key': 'top_p', 'value': '0.9'}]})
    assert out['written'] == ['top_p'] and read_router_settings()['generation']['top_p'] == 0.9


def test_library_has_a_node_for_every_app_thing():
    from nodelang.session_files import catalogue
    cats = {i['cat'] for i in catalogue()}
    assert {'agents', 'models', 'connectors', 'files', 'workshop', 'settings'} <= cats


def test_agent_canvas_tools_build_run_and_refuse_cycles(profile):
    from nodelang.native_agent_mcp import build_server
    server = build_server()
    path = str(profile / 'agent.archhub')
    def tool(name, **args):
        result = asyncio.run(server.call_tool(name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get('result', content) if isinstance(content, dict) else json.loads(result[0].text)
    tool('canvas.new', path=path, title='Agent built')
    a = tool('canvas.add_node', path=path, type='n_list', params={'value': '[1, 2, 3, 4]'})['node']
    b = tool('canvas.add_node', path=path, type='s_slice', params={'count': '3'}, x=300)['node']
    c = tool('canvas.add_node', path=path, type='s_count', x=600)['node']
    tool('canvas.wire', path=path, source=a + '.value', target=b + '.items')
    read = tool('canvas.wire', path=path, source=b + '.items_out', target=c + '.items')
    assert next(n for n in read['nodes'] if n['id'] == c)['output'] == {'count': 3}           # solved on wire
    read = tool('canvas.set_param', path=path, node=b, key='count', value='2')
    assert next(n for n in read['nodes'] if n['id'] == c)['output'] == {'count': 2}
    with pytest.raises(Exception, match='Cycle'):
        asyncio.run(server.call_tool('canvas.wire', {'path': path, 'source': c + '.count', 'target': b + '.items'}))
    ran = tool('canvas.run', path=path)
    assert all(n['status'] == 'Done' for n in ran['nodes']) and ran['last_edits'][-1]['op'] == 'run'
    assert tool('library.search', query='revit')['count'] >= 1


def test_skill_has_typed_sockets_from_its_inner_workflow(profile):
    from nodelang.session_files import catalogue, new_document, run_document, skills_directory, write_document
    items = {row['id']: row for row in catalogue()}
    skill = new_document('Count items')
    skill['id'] = 'count_items'
    skill['nodes'] = [
        {'id': 'items', 'item': 'param.value', 'type': 'param.value', 'title': 'Items', 'params': {'type': 'list', 'value': []}, 'position': {'x': 0, 'y': 0}},
        {'id': 'count', 'item': 's_count', 'type': items['s_count']['engine'], 'title': 'Count', 'params': copy.deepcopy(items['s_count']['params']), 'position': {'x': 300, 'y': 0}}]
    skill['wires'] = [{'id': 'w', 'from': {'node': 'items', 'socket': 'value'}, 'to': {'node': 'count', 'socket': 'items'}}]
    write_document(str(skills_directory() / 'count_items.archhub'), skill)
    entry = {row['id']: row for row in catalogue()}['skill:count_items']
    assert entry['ports']['target'] == [{'id': 'in:items', 'type': 'list', 'label': 'Items'}]
    assert {'id': 'out:count:count', 'type': 'number', 'label': 'Count · count'} in entry['ports']['source']
    outer = new_document('Uses the skill')
    outer['nodes'] = [
        {'id': 'list', 'item': 'n_list', 'type': items['n_list']['engine'], 'title': 'List', 'params': {**copy.deepcopy(items['n_list']['params']), 'value': '[4, 5, 6, 7]'}, 'position': {'x': 0, 'y': 0}},
        {'id': 'skill', 'item': 'skill:count_items', 'type': 'skill', 'title': 'Count items', 'params': {'skill': 'count_items'}, 'position': {'x': 300, 'y': 0}}]
    outer['wires'] = [{'id': 'a', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'skill', 'socket': 'in:items'}}]
    ran = run_document(outer)
    assert ran['succeeded'] and ran['results']['skill']['output']['out:count:count'] == 4
