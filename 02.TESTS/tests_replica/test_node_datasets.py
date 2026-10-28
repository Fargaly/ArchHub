"""Datasets on the canvas: +Field, +Record, typed cells; a field node is the column (door.width -> Number[])."""
import asyncio
import json

import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    yield tmp_path


def doors():
    from nodelang import node_datasets as ds
    from nodelang.session_files import new_document
    doc = new_document('Doors')
    dataset = ds.new_dataset(doc, 'door')[0]
    ds.add_field(doc, 'door', 'Width', 'number', unit='mm', min=0)
    ds.add_field(doc, 'door', 'Mark', 'text')
    for width, mark in ((800, 'D1'), (900, 'D2'), (1000, 'D3')):
        ds.add_record(doc, 'door', {'width': width, 'mark': mark})
    field = ds.expose_field(doc, 'door', 'width')[0]
    doc['nodes'].append({'id': 'filter', 'item': 's_filter', 'type': 'shape.filter', 'title': 'Wide doors',
                         'params': {'predicate': 'item > 850', 'mode': 'keep'}, 'position': {'x': 800, 'y': 0}})
    doc['wires'].append({'id': 'w', 'from': {'node': field, 'socket': 'values'}, 'to': {'node': 'filter', 'socket': 'items'}})
    return doc, dataset, field


def test_field_node_is_the_typed_column_and_holds_no_values():
    from nodelang.node_params import ports
    doc, dataset, field = doors()
    node = next(n for n in doc['nodes'] if n['id'] == field)
    assert node['title'] == 'door.width' and 'values' not in node['params'] and 'records' not in node
    assert ports(node, {})['source'] == [{'id': 'values', 'type': 'list', 'label': 'Number[]', 'of': 'number'}]
    owner = next(n for n in doc['nodes'] if n['id'] == dataset)
    assert owner['params'] == {} and [r['cells']['width'] for r in owner['records']] == [800, 900, 1000]
    # The binding is a visible wire from the dataset's typed field socket.
    assert [p['label'] for p in ports(owner, {})['source']] == ['Record[]', 'Width · Number[]', 'Mark · Text[]']
    assert any(w['from'] == {'node': dataset, 'socket': 'field:width'} and w['to'] == {'node': field, 'socket': 'column'}
               for w in doc['wires'])


def test_deleting_the_wire_unbinds_and_rewiring_rebinds():
    from nodelang.canvas_documents import solve
    doc, dataset, field = doors()
    doc['wires'] = [w for w in doc['wires'] if w['to'] != {'node': field, 'socket': 'column'}]
    assert 'Unbound' in solve(doc, [dataset, field])['results'][field]['error']
    doc['wires'].append({'id': 'r', 'from': {'node': dataset, 'socket': 'field:mark'}, 'to': {'node': field, 'socket': 'column'}})
    assert solve(doc, [dataset])['results'][field]['output'] == {'values': ['D1', 'D2', 'D3']}


def test_cell_edit_resolves_field_node_and_filter_downstream():
    from nodelang import node_datasets as ds
    from nodelang.canvas_documents import solve
    doc, dataset, field = doors()
    first = solve(doc, [dataset])
    assert first['results']['filter']['output'] == {'items_out': [900, 1000]}
    changed = ds.set_cell(doc, 'door', 0, 'width', '1200')
    assert changed == [dataset, field]
    again = solve(doc, changed)
    assert again['results'][field]['output'] == {'values': [1200, 900, 1000]}
    assert again['results']['filter']['output'] == {'items_out': [1200, 900, 1000]}
    ds.add_record(doc, 'door', {'width': 700, 'mark': 'D4'})
    assert solve(doc, [dataset])['results']['filter']['output'] == {'items_out': [1200, 900, 1000]}


def test_cells_are_typed_by_their_field():
    from nodelang import node_datasets as ds
    doc, _, _ = doors()
    with pytest.raises(ValueError, match='Enter a number'):
        ds.set_cell(doc, 'door', 1, 'width', 'wide')
    with pytest.raises(ValueError, match='outside min'):
        ds.set_cell(doc, 'door', 1, 'width', -5)
    with pytest.raises(ValueError, match='Unknown fields'):
        ds.add_record(doc, 'door', {'height': 2100})


def test_save_and_reopen_keeps_fields_records_and_the_binding(profile):
    from nodelang.canvas_documents import solve
    from nodelang.session_files import read_document, write_document
    doc, dataset, _ = doors()
    path = write_document(str(profile / 'doors.archhub'), doc)
    reopened = read_document(path)
    assert next(n for n in reopened['nodes'] if n['id'] == dataset)['records'] == next(n for n in doc['nodes'] if n['id'] == dataset)['records']
    assert solve(reopened, [dataset])['results']['filter']['output'] == {'items_out': [900, 1000]}


def test_agent_tools_add_field_add_record_set_cell(profile):
    from nodelang.native_agent_mcp import build_server
    server = build_server()
    path = str(profile / 'agent-doors.archhub')

    def tool(tool_name, **args):
        result = asyncio.run(server.call_tool(tool_name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get('result', content) if isinstance(content, dict) else json.loads(result[0].text)
    tool('canvas.new', path=path, title='Doors by agent')
    read = tool('canvas.add_field', path=path, dataset='door', name='Width', type='number', show_as_node=True)
    field = next(n['id'] for n in read['nodes'] if n['type'] == 'data.field')
    for width in (800, 950):
        tool('canvas.add_record', path=path, dataset='door', cells={'width': width})
    flt = tool('canvas.add_node', path=path, type='s_filter', params={'predicate': 'item > 900'}, x=800)['node']
    read = tool('canvas.wire', path=path, source=field + '.values', target=flt + '.items')
    assert next(n for n in read['nodes'] if n['id'] == flt)['output'] == {'items_out': [950]}
    read = tool('canvas.set_cell', path=path, dataset='door', record='0', field='width', value='1100')
    assert next(n for n in read['nodes'] if n['id'] == flt)['output'] == {'items_out': [1100, 950]}
    assert read['last_edits'][-1]['op'] == 'set door[0].width'
