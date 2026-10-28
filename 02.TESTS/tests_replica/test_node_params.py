"""Typed node parameters: add, promote to a Parameter node (one value), re-solve, reopen, type rejection."""
import asyncio
import copy
import json

import pytest


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
