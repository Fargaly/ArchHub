"""Typed node parameters: add, promote to a Parameter node (one value), re-solve, reopen, type rejection."""
import asyncio
import copy
import json

import pytest


def test_all_parameter_sockets_through_shared_api(profile):
    from nodelang import node_params
    from nodelang.native_agent_mcp import build_server
    server = build_server()
    path = str(profile / 'types.archhub')
    def tool(name, **args):
        result = asyncio.run(server.call_tool(name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get('result', content) if isinstance(content, dict) else json.loads(result[0].text)
    tool('canvas.new', path=path)
    for kind in node_params.TYPES:
        value = {'bool': True, 'integer': 7, 'number': 3.5, 'list': [1, 2], 'object': {'a': 1},
                 'json': {'a': 1}, 'color': '#112233', 'date': '2026-11-05'}.get(kind, 'typed value')
        a = tool('canvas.add_node', path=path, type='param.value', params={'type': kind, 'value': value})['node']
        b = tool('canvas.add_node', path=path, type='param.value', params={'type': kind, 'value': node_params.default({'type': kind, 'options': ['other', value]})})['node']
        if kind in ('choice', 'enum'):
            from nodelang.session_files import read_document, write_document
            doc = read_document(path)
            for n in doc['nodes']:
                if n['id'] in (a, b):
                    next(d for d in n['paramDefs'] if d['id'] == 'value')['options'] = ['other', value]
            write_document(path, doc)
        read = tool('canvas.read', path=path)
        node = next(n for n in read['nodes'] if n['id'] == b)
        socket = 'value:' + node_params.socket_type(kind)
        assert socket in node['sockets']['in'] and socket in node['sockets']['out'], (kind, node['sockets'])
        tool('canvas.set_param', path=path, node=a, key='value', value=json.dumps(value) if kind in ('list', 'object', 'json') else str(value))
        read = tool('canvas.wire', path=path, source=a+'.value', target=b+'.value')
        assert next(n for n in read['nodes'] if n['id'] == b)['output']['value'] == value
        if node_params.socket_type(kind) != 'any':
            wrong = 'text' if node_params.socket_type(kind) != 'string' else 'number'
            c = tool('canvas.add_node', path=path, type='param.value', params={'type': wrong})['node']
            with pytest.raises(Exception, match='Wrong type'):
                tool('canvas.wire', path=path, source=c+'.value', target=b+'.value')
        print('TYPEDPARAM shared API:', kind, socket, 'same-type accepted; mismatch policy retained')


def test_parameter_types_in_compiled_studio(profile):
    import os
    import subprocess
    import threading
    from pathlib import Path
    from nodelang import node_params
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import catalogue, new_document, write_document
    item = next(i for i in catalogue() if i['id'] == 'param.value')
    doc = new_document('Typed parameter chains')
    cases = []
    for index, kind in enumerate(node_params.TYPES):
        value = {'bool': True, 'integer': 7, 'number': 3.5, 'list': [1, 2], 'object': {'a': 1},
                 'json': {'a': 1}, 'color': '#112233', 'date': '2026-11-05'}.get(kind, 'typed value')
        defs = copy.deepcopy(item['paramDefs'])
        next(d for d in defs if d['id'] == 'value')['options'] = ['other', value] if kind in ('choice', 'enum') else []
        for suffix, held in [('a', value), ('b', node_params.default({'type': kind, 'options': ['other', value]}))]:
            doc['nodes'].append({'id': kind+'-'+suffix, 'type': 'param.value', 'item': item['id'],
                'title': kind+' '+suffix, 'params': {'type': kind, 'value': held},
                'paramDefs': defs, 'position': {'x': 0 if suffix == 'a' else 320, 'y': index*250}})
        cases.append({'kind': kind, 'socket': node_params.socket_type(kind), 'value': value})
    path = profile / 'typed.archhub'
    write_document(path, doc)
    server = NoGraphServer(profile / 'server')
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).parents[1] / 'tests_js/typedparam.mjs')],
            input=json.dumps({'url': server.public_url+'/studio/?bootstrap='+server.browser_bootstrap_token,
                              'path': str(path), 'cases': cases}),
            text=True, encoding='utf-8', capture_output=True, timeout=150, env=os.environ.copy())
        print(result.stdout)
        assert result.returncode == 0, result.stderr
    finally:
        server.close()


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    yield tmp_path


def workflow():
    from nodelang.session_files import catalogue, new_document
    items = {row['id']: row for row in catalogue()}
    doc = new_document('Typed parameters')
    for key, item, x in (('list', 'n_list', 0), ('slice', 's_slice', 300), ('count', 's_count', 600)):
        doc['nodes'].append({'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                             'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}})
    doc['nodes'][0]['params']['value'] = '[10, 20, 30, 40, 50]'
    doc['wires'] = [{'id': 'a', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'slice', 'socket': 'items'}},
                    {'id': 'b', 'from': {'node': 'slice', 'socket': 'items_out'}, 'to': {'node': 'count', 'socket': 'items'}}]
    return doc


def test_add_typed_parameter_checks_type_and_bounds():
    from nodelang import node_params
    doc = workflow()
    node_params.add_param(doc, 'count', 'Limit', 'integer', '4', min=0, max=10)
    assert doc['nodes'][2]['params']['limit'] == 4 and doc['nodes'][2]['paramDefs'][0]['type'] == 'integer'
    for bad in ('4.5', '11', 'x'):
        with pytest.raises(ValueError):
            node_params.set_value(doc, 'count', 'limit', bad)
    node_params.add_param(doc, 'count', 'Tint', 'color', '#112233')
    node_params.add_param(doc, 'count', 'Mode', 'enum', 'b', options=['a', 'b'])
    with pytest.raises(ValueError):
        node_params.set_value(doc, 'count', 'mode', 'c')


def test_promoted_parameter_is_one_value_and_re_solves_downstream():
    from nodelang import node_params
    from nodelang.canvas_documents import solve
    doc = workflow()
    solve(doc, ['list'])
    assert doc['nodes'][2]['result']['output'] == {'count': 5}
    param = node_params.promote(doc, 'slice', 'count')[0]
    changed = node_params.set_value(doc, param, 'value', 2)          # edit from the Parameter node
    assert doc['nodes'][1]['params']['count'] == 2 and 'value' not in doc['nodes'][3]['params']
    result = solve(doc, changed)
    assert doc['nodes'][2]['result']['output'] == {'count': 2} and param in result['solved']
    node_params.set_value(doc, 'slice', 'count', 3)                   # edit inline: same value
    assert node_params.bound_value(doc, doc['nodes'][3]) == 3


def test_save_and_reopen_keep_the_identity(profile):
    from nodelang import node_params
    from nodelang.session_files import read_document, write_document
    doc = workflow()
    param = node_params.promote(doc, 'slice', 'count')[0]
    path = profile / 'typed.archhub'
    write_document(path, doc)
    again = read_document(path)
    node_params.set_value(again, param, 'value', 1)
    assert again['nodes'][1]['params']['count'] == 1
    assert next(n for n in again['nodes'] if n['id'] == param)['bind'] == {'node': 'slice', 'param': 'count'}
    node_params.demote(again, 'slice', 'count')
    assert all(n['type'] != 'param.value' for n in again['nodes']) and 'promoted' not in again['nodes'][1]['paramDefs'][0]


@pytest.mark.parametrize('socket', ['count', 'param:count'])
def test_promotion_preserves_an_existing_parameter_input(socket):
    from nodelang import node_params
    from nodelang.session_files import validate

    doc = workflow()
    doc['nodes'].append({'id': 'source', 'item': 'n_number', 'type': 'data.constant',
                         'title': 'Count source', 'params': {'value': 3}, 'position': {'x': 0, 'y': 200}})
    if socket.startswith('param:'):
        doc['nodes'][1]['paramDefs'] = [{'id': 'count', 'name': 'Count', 'type': 'integer'}]
    doc['wires'].append({'id': 'input', 'from': {'node': 'source', 'socket': 'value'},
                         'to': {'node': 'slice', 'socket': socket}})
    validate(doc)
    before = copy.deepcopy(doc)

    with pytest.raises(ValueError, match='Disconnect the existing input wire first'):
        node_params.promote(doc, 'slice', 'count')

    assert doc == before


@pytest.mark.parametrize('value', [2, 2.5])
def test_legacy_number_promotes_with_its_declared_type(profile, value):
    from nodelang import node_params
    from nodelang.session_files import catalogue, new_document, read_document, write_document

    item = next(row for row in catalogue() if row['id'] == 'n_number')
    doc = new_document('Legacy Number')
    doc['nodes'].append({
        'id': 'number', 'item': item['id'], 'type': item['engine'], 'title': item['title'],
        'params': {'value': value}, 'position': {'x': 0, 'y': 0},
    })
    param = node_params.promote(doc, 'number', 'value')[0]
    node_params.set_value(doc, param, 'value', 7.25)
    path = profile / 'legacy-number.archhub'
    write_document(path, doc)
    reopened = read_document(path)
    binding = next(node for node in reopened['nodes'] if node['id'] == param)
    assert binding['params']['type'] == 'number'
    assert node_params.bound_value(reopened, binding) == 7.25
    node_params.demote(reopened, 'number', 'value')
    write_document(path, reopened)
    restored = read_document(path)
    assert len(restored['nodes']) == 1 and not restored['wires']
    assert restored['nodes'][0]['params']['value'] == 7.25


def test_agent_tools_add_promote_set_and_reject_wrong_type(profile):
    from nodelang.native_agent_mcp import build_server
    from nodelang.session_files import write_document
    server = build_server()
    path = str(profile / 'agent.archhub')
    write_document(path, workflow())

    def tool(tool_name, **args):
        result = asyncio.run(server.call_tool(tool_name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get('result', content) if isinstance(content, dict) else json.loads(result[0].text)
    tool('canvas.add_param', path=path, node='count', name='Label', type='text', value='total')
    read = tool('canvas.promote_param', path=path, node='slice', param='count')
    param = next(n for n in read['nodes'] if n['type'] == 'param.value')
    assert param['sockets']['out'] == ['value:number']
    read = tool('canvas.set_param', path=path, node=param['id'], key='value', value='2')
    assert next(n for n in read['nodes'] if n['id'] == 'count')['output'] == {'count': 2}
    with pytest.raises(Exception, match='Wrong type'):
        asyncio.run(server.call_tool('canvas.wire', {'path': path, 'source': param['id'] + '.value', 'target': 'count.param:label'}))
