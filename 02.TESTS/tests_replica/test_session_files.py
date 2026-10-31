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
    assert second.dispatch({'action':'open','path':str(path)})['document']==doc


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
    assert read_document(tmp_path/(first['id']+'.archhub'))==first
    assert owner.dispatch({'action':'initial'})['document']==second


def test_file_route_does_not_read_or_write_graph(tmp_path, monkeypatch):
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from nodelang.application_server import ApplicationServer
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    server=ApplicationServer(enable_machine_transport=False, enable_machine_projection_prewarm=False, live_watch=False).start()
    snapshot=server.universal_store.snapshot
    def forbidden(*args,**kwargs):
        raise AssertionError('File operation touched the universal graph')
    try:
        monkeypatch.setattr(server.universal_store,'snapshot',forbidden)
        def post(body,token=None,csrf=None):
            request=Request(server.url+'/api/session-files',data=json.dumps(body).encode(),headers={
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
        monkeypatch.setattr(server.universal_store,'snapshot',snapshot)
        server.close()


def test_clean_file_route_uses_existing_frame_admission_without_graph(tmp_path, monkeypatch):
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from tests_replica.test_clean_server_admission import _provision_clean_runtime, _start_clean_server
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    from nodelang.application_server import _CleanAuthorityHttpServer
    monkeypatch.setattr(_CleanAuthorityHttpServer,'_warm_clean_runtime',lambda self:self._boot_ready.set())
    built,provider=_provision_clean_runtime(tmp_path,root_name='CLEAN')
    server=_start_clean_server(built,provider,scope_root=built.location.authority.manifest.application_root)
    snapshot=built.location.authority.store.snapshot
    def forbidden(*args,**kwargs):
        raise AssertionError('File route read the clean graph')
    try:
        monkeypatch.setattr(built.location.authority.store,'snapshot',forbidden)
        def post(key):
            request=Request(server.url+'/api/session-files',data=json.dumps({'action':'validate','document':definition()}).encode(),headers={'Content-Type':'application/json','X-ArchHub-Canvas-Key':key})
            try:
                with urlopen(request,timeout=15) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        assert post('unknown')[0]==403
        status,answer=post(server.clean_canvas_key)
        assert status==200,answer
        assert answer['document']['nodes'][0]['params']['value']=='hello'
    finally:
        monkeypatch.setattr(built.location.authority.store,'snapshot',snapshot)
        server.close()
        built.location.authority.store.close()


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
