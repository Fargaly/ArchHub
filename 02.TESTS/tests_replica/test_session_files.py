"""Portable sessions: real engines, atomic save and shareable file contracts."""
import copy
import pytest
from nodelang.session_files import SessionFiles, catalogue, new_document, read_document, run_document, write_document


def definition():
    items={row['id']:row for row in catalogue()}
    doc=new_document('File court')
    for index,item in enumerate([items['n_text'],items['data.convert'],items['w_watch']]):
        doc['nodes'].append({'id':str(index),'item':item['id'],'type':item['engine'],'title':item['title'],
                             'params':copy.deepcopy(item['params']),'position':{'x':80+index*300,'y':100}})
    doc['nodes'][0]['params']['value']='hello'
    doc['wires']=[{'id':'a','from':{'node':'0','socket':'value'},'to':{'node':'1','socket':'in'}},
                  {'id':'b','from':{'node':'1','socket':'out'},'to':{'node':'2','socket':'in'}}]
    return doc


def test_real_engines_and_second_profile(tmp_path):
    from nodelang.enforce import guard_effect
    doc=definition()
    result=run_document(doc,invoke=lambda n,f,p,v:guard_effect(n,f,p,v))
    assert result['succeeded'] and result['order']==['0','1','2']
    assert result['results']['2']['output']['out']=='hello'
    for node in doc['nodes']:
        node['result']=result['results'][node['id']]
    path=tmp_path/'test.archhub';write_document(path,doc)
    second=SessionFiles(tmp_path/'SECOND')
    reopened = second.dispatch({'action':'open','path':str(path)})['document']
    assert reopened['nodes'][1]['result']['output'] == {'out': 'hello'}
    assert reopened['nodes'][2]['result']['status'] == 'Done'
    for node in reopened['nodes']:
        node['result'] = doc['nodes'][int(node['id'])]['result']
    assert reopened == doc


def test_bad_file_preserves_previous_bytes(tmp_path):
    path=tmp_path/'test.archhub';doc=definition();write_document(path,doc);before=path.read_bytes()
    for bad in [{'children':{}},{'params':{'api_key':'secret'}},{'position':{'x':float('nan'),'y':0}},{'result':{'status':99}}]:
        changed=copy.deepcopy(doc);changed['nodes'][0].update(bad)
        with pytest.raises(ValueError):write_document(path,changed)
        assert path.read_bytes()==before


def test_cycles_and_missing_sockets_refuse_before_effect():
    doc=definition();doc['wires'].append({'id':'cycle','from':{'node':'2','socket':'out'},'to':{'node':'0','socket':'value'}})
    with pytest.raises(ValueError,match='Cycle'):run_document(doc)
    doc=definition();doc['wires'][0]['from']['socket']='missing'
    with pytest.raises(ValueError,match='socket'):run_document(doc)


def test_errors_and_rules_preserve_per_node_results():
    doc=definition();doc['nodes'][1]['params']['target_type']='number'
    from nodelang.enforce import guard_effect
    result=run_document(doc,invoke=lambda n,f,p,v:guard_effect(n,f,p,v))
    assert result['ok'] and not result['succeeded']
    assert result['results']['0']['status']=='Done'
    assert result['results']['1']['status']=='Error'
    assert result['results']['2']['status']=='Blocked'
    doc=definition();doc['wires'][0]['rule']='false'
    result=run_document(doc,invoke=lambda n,f,p,v:guard_effect(n,f,p,v))
    assert not result['succeeded']


def test_recovery_is_per_session(tmp_path):
    owner=SessionFiles(tmp_path);first=definition();second=new_document('Second')
    owner.dispatch({'action':'autosave','document':first})
    owner.dispatch({'action':'autosave','document':second})
    assert read_document(tmp_path/(first['title']+'.archhub'))==first
    assert owner.dispatch({'action':'initial'})['document']==second


def test_file_route_does_not_read_or_write_graph(tmp_path, monkeypatch):
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from nodelang.nograph_server import NoGraphServer
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    server=NoGraphServer(tmp_path/'ArchHub')
    server.thread=__import__('threading').Thread(target=server.httpd.serve_forever,daemon=True)
    server.thread.start()
    try:
        def post(body,token=None,csrf=None):
            request=Request(server.public_url+'/api/session-files',data=json.dumps(body).encode(),headers={
                'Content-Type':'application/json','X-ArchHub-Session':server.browser_session_token if token is None else token,
                'X-ArchHub-CSRF':server.browser_csrf_token if csrf is None else csrf})
            try:
                with urlopen(request,timeout=15) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        assert post({'action':'catalogue'},token='unknown')[0]==403
        assert post({'action':'catalogue'},csrf='wrong')[0]==403
        assert post({'action':'catalogue'})[0]==200
        doc=definition();path=str(tmp_path/'test.archhub')
        assert post({'action':'save','path':path,'document':doc})[0]==200
        assert post({'action':'open','path':path})[1]['document']==doc
        assert post({'action':'run','document':doc})[1]['succeeded']
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
        server.thread.join(timeout=5)


def test_file_health_uses_http_and_real_workshop_database(tmp_path, monkeypatch):
    import sqlite3
    import threading
    from nodelang.nograph_server import NoGraphServer
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    state=tmp_path/'ArchHub'
    server=NoGraphServer(state)
    server.thread=threading.Thread(target=server.httpd.serve_forever,daemon=True)
    server.thread.start()
    database=state/'workshop/messages.sqlite3'
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE saved(value TEXT)')
        connection.execute("INSERT INTO saved VALUES ('untouched')")
    try:
        assert server.health_check()
        server.files['settings'].write({'sessionsFolder':str(tmp_path/'Documents/ArchHub')})
        assert server.health_check()
        server.files['settings'].path.write_text('invalid json',encoding='utf-8')
        with pytest.raises(ValueError):
            server.health_check()
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
        server.thread.join(timeout=5)


def test_stop_prevents_the_next_engine_effect():
    calls=[]
    def invoke(name,effect,params,feeds):
        calls.append(name)
        return effect(params,feeds)
    result=run_document(definition(),invoke=invoke,stopped=lambda:bool(calls))
    assert calls==['data.convert']
    assert result['results']['2']['status']=='Stopped'
    assert not result['succeeded']


def test_node_contract_pure_budget_loop_are_engine_owned():
    """C2: pure comes from the engine (a file cannot claim it), budget and loop are typed, catalogue carries defaults."""
    from nodelang.session_files import validate
    items = {row['id']: row for row in catalogue()}
    assert items['thing:model:default']['pure'] is False and items['thing:setting:temperature']['pure'] is True
    assert items['thing:setting:temperature']['ports']['source'] == [{'id': 'value', 'type': 'number'}]
    assert {'id': 'temperature', 'type': 'number'} in items['thing:model:default']['ports']['target']
    from nodelang.canvas_documents import BUDGET_DEFAULT, THING_ENGINES, node_contract
    assert all(set(node_contract(e)['loop']) == {'trigger', 'stop', 'evaluator', 'cap'} for e in ('library.loop', 'control.foreach'))
    assert node_contract('imported.unknown') == {'pure': False, 'budget': {'seconds': 60, 'calls': 1, 'cost_usd': 0.0}, 'loop': None}
    for row in items.values():
        if not row.get('engine'):
            continue
        expected = dict((THING_ENGINES.get(row['engine']) or {}).get('budget') or BUDGET_DEFAULT)
        assert row['budget'] == expected, row['id']
    doc = new_document('Contract')
    doc['nodes'].append({'id': 'm', 'type': 'thing.model', 'params': {}, 'position': {'x': 0, 'y': 0}, 'pure': True,
                         'budget': {'seconds': 30, 'calls': 2}})
    assert validate(doc)['nodes'][0]['pure'] is False
    for bad in ({'budget': {'seconds': -1}}, {'budget': {'tokens': 5}}, {'loop': {'trigger': 'Run', 'stop': '', 'evaluator': '', 'cap': 0}},
                {'loop': {'trigger': 'Run'}}):
        broken = copy.deepcopy(doc); broken['nodes'][0].update(bad)
        with pytest.raises(ValueError):
            validate(broken)


def _list_node(node_id, value, x):
    return {'id': node_id, 'type': 'param.value', 'item': 'param.value', 'title': 'List',
            'params': {'type': 'list', 'value': value}, 'position': {'x': x, 'y': 0}}


def test_wire_connection_parameters_round_trip_and_old_file(tmp_path):
    """A wire is the connection node: its parameters save in the .archhub file, and an old file still loads."""
    from nodelang.enforce import guard_effect
    from nodelang.session_files import wire_choice
    doc = definition()
    wire = doc['wires'][0]
    chosen = {'matching': 'Longest', 'order': 'Reverse', 'missing': 'Drop', 'units': 'From target', 'conversion': 'Text'}
    for name, value in chosen.items():
        wire[name] = value
    wire['route'] = 'Step'
    path = tmp_path / 'connection.archhub'
    write_document(path, doc)
    saved = read_document(path)['wires'][0]
    for name, value in chosen.items():
        assert saved[name] == value
    assert saved['route'] == 'Step'
    old_path = tmp_path / 'old.archhub'
    write_document(old_path, definition())
    opened = read_document(old_path)
    bare = opened['wires'][0]
    assert set(bare) == {'id', 'from', 'to'}
    for name, expected in (
        ('matching', 'By index'), ('order', 'Source order'), ('missing', 'Preserve'),
        ('units', 'From source'), ('conversion', 'None'),
    ):
        assert name not in bare and wire_choice(bare, name) == expected
    assert wire_choice(bare, 'route') == 'Bezier'
    ran = run_document(opened, invoke=lambda n, f, p, v: guard_effect(n, f, p, v))
    assert ran['succeeded'] and ran['results']['2']['output']['out'] == 'hello'
    refused = definition()
    refused['wires'][0]['matching'] = 'sideways'
    with pytest.raises(ValueError):
        write_document(tmp_path / 'bad.archhub', refused)
    carry = new_document('Carry')
    carry['nodes'] = [_list_node('0', [1, None, 3], 0),
                      {'id': '1', 'type': 'watch.preview', 'item': 'w_watch', 'title': 'Watch', 'params': {'as': 'list'}, 'position': {'x': 320, 'y': 0}}]
    carry['wires'] = [{'id': 'a', 'from': {'node': '0', 'socket': 'value'}, 'to': {'node': '1', 'socket': 'in'},
                       'order': 'Reverse', 'missing': 'Drop', 'conversion': 'Text'}]
    carried = run_document(carry)
    assert carried['succeeded'], carried
    assert carried['results']['1']['output']['out'] == ['3', '1']
    join = new_document('Match')
    join['nodes'] = [_list_node('0', [1, 2, 3], 0), _list_node('1', [4, 5], 40),
                     {'id': '2', 'type': 'shape.concat', 'item': 's_join', 'title': 'Join', 'params': {}, 'position': {'x': 320, 'y': 0}}]
    join['wires'] = [{'id': 'a', 'from': {'node': '0', 'socket': 'value'}, 'to': {'node': '2', 'socket': 'a'}, 'matching': 'Shortest'},
                      {'id': 'b', 'from': {'node': '1', 'socket': 'value'}, 'to': {'node': '2', 'socket': 'b'}, 'matching': 'Shortest'}]
    matched = run_document(join)
    assert matched['succeeded'], matched
    assert matched['results']['2']['output']['items_out'] == [1, 2, 4, 5]
    cross = new_document('Cross')
    cross['nodes'] = [_list_node('0', [1, 2], 0), _list_node('1', [3, 4], 40),
                      {'id': '2', 'type': 'shape.concat', 'item': 's_join', 'title': 'Join', 'params': {}, 'position': {'x': 320, 'y': 0}}]
    cross['wires'] = [{'id': 'a', 'from': {'node': '0', 'socket': 'value'}, 'to': {'node': '2', 'socket': 'a'}, 'matching': 'Cross'},
                       {'id': 'b', 'from': {'node': '1', 'socket': 'value'}, 'to': {'node': '2', 'socket': 'b'}, 'matching': 'Cross'}]
    crossed = run_document(cross)
    assert crossed['succeeded'], crossed
    assert crossed['results']['2']['output']['items_out'] == [1, 1, 2, 2, 3, 3, 4, 4]
