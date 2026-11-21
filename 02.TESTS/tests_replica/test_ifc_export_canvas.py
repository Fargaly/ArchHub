import copy,json,re,hashlib
import pytest

@pytest.fixture
def project(tmp_path,monkeypatch):
    import socket
    from nodelang import clean_revit_adapter as adapter
    def no_network(*args,**kwargs):
        pytest.fail('This disposable court must not connect to a real host.')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    monkeypatch.setattr(adapter,'_call',no_network)
    for key in ('USERPROFILE','HOME','LOCALAPPDATA','APPDATA'):
        folder=tmp_path/key;folder.mkdir();monkeypatch.setenv(key,str(folder))
    state=tmp_path/'state';monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR',str(state));monkeypatch.setenv('WORKSHOP_STATE_DIR',str(tmp_path/'workshop'))
    root=tmp_path/'private-project';root.mkdir();source=root/'Model.rvt';source.write_bytes(b'disposable source-path fixture; no real Revit model')
    from nodelang.nograph_server import JsonFile
    JsonFile(state/'settings/workspaces.json',{'roots':[]}).write({'roots':[{'root_id':'court','path':str(root),'privacy':'private','name':'Court'}]})
    return root,source

def start(project,folder='Issued',version='From Projects',properties=None, node_params=None, wired=False):
    from nodelang import session_files as files
    root,source=project;out=root/folder;out.mkdir();target=out/'Reviewed.ifc'
    item=next(row for row in files.catalogue() if row['id']=='file_export_ifc')
    document=files.new_document('IFC approval');document['properties'].update(properties or {})
    document['nodes']=[{'id':'export','item':item['id'],'type':item['engine'],'params':{**copy.deepcopy(item['params']),'project_id':'court','document':str(source),'path':str(target),'session':'48884','version':version},'paramDefs':copy.deepcopy(item.get('paramDefs',[])),'position':{'x':0,'y':0}}]
    if node_params is not None:
        document['nodes'][0]['params'] = {**node_params, 'project_id':'court', 'document':str(source),
                                         'path':str(target), 'session':'48884', 'version':version}
    if wired:
        document['nodes'].append({'id':'setting','type':'thing.setting','params':{'setting':'Projects.Working subfolder'},'position':{'x':0,'y':120}})
        document['wires'] = [{'id':'setup-wire','from':{'node':'setting','socket':'value'},'to':{'node':'export','socket':'setup'}}]
    path=root/'export.archhub';files.write_document(path,document);owner=files.SessionFiles(root/'sessions')
    result=owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    from nodelang.hook_decision import ask_reviews
    card=next(row for row in ask_reviews() if row['id']==result['approvalId'])
    assert card['text'].count(str(source))==1 and card['text'].count(str(target))==1
    assert all(word not in card['text'] for word in ('pending_write','project_id','input_digest','_ifc_effect'))
    assert all(label in card['text'] for label in ('Source:', 'Destination:', 'Format:', 'Setup:', 'Views:'))
    assert not target.exists()
    return path,target,card

def transport(monkeypatch,target,*,malformed=False,expected_setup=None):
    from nodelang import clean_revit_adapter as adapter
    calls=[]
    monkeypatch.setattr(adapter,'live_sessions',lambda:[{'port':48884,'pid':7,'revit_version':'2027','document':'Disposable fixture'}])
    def broker(port,route,body,*,timeout):
        assert (port,route,body['transaction_name'],body['transaction'])==(48884,'/exec','ArchHub IFC export',False)
        version=json.loads(re.search(r'requestedVersion = ("[^"]+")',body['code']).group(1));calls.append(version)
        if expected_setup is not None:
            assert json.loads(re.search(r'setup = ("[^"]*")',body['code']).group(1)) == expected_setup
        schema=adapter._IFC_SCHEMAS[version].decode('ascii')
        data=("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\nFILE_NAME('Reviewed.ifc','2026-11-20T14:30:00',(''),(''),'Revit','Revit','');\nFILE_SCHEMA(('%s'));\nENDSEC;\nDATA;\n#42=IFCCARTESIANPOINT((0.,0.,0.));\nENDSEC;\nEND-ISO-10303-21;\n"%schema).encode()
        if malformed:data=data.replace(b'DATA;',b'/* DATA; */')
        staged,=target.parent.glob('.archhub-ifc-*')
        name=json.loads(re.search(r'name = ("[^"]+")',body['code']).group(1))
        (staged/name).write_bytes(data)
        return {'status':'ok','result':version}
    monkeypatch.setattr(adapter,'_call',broker)
    assert adapter._call is broker
    return calls

@pytest.mark.parametrize('version,native,folder',[('IFC4','IFC4RV','90% Design'),('IFC2x3','IFC2x3CV2','RFI #42'),('IFC4.3','IFC4x3RV','تنسيق')])
def test_normal_approve_releases_once_and_reads_exact_output(project,monkeypatch,version,native,folder):
    from nodelang import settings_owner,session_files as files,nodeslib_v2_engines as nodes
    from nodelang.hook_decision import ask_apply
    assert nodes._WRITE_GRANT_VERIFIER is None
    settings_owner.preference_settings('setAppearance',['Projects.IFC version',version])
    path,target,card=start(project,folder);calls=transport(monkeypatch,target)
    waiting=files.SessionFiles(project[0]/'sessions').dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    assert waiting['approvalId']==card['id'] and calls==[]
    decided=ask_apply(card['id'],card['input_digest'],'approve');assert decided['status']=='approved'
    result=files.read_document(path)['nodes'][0]['result'];assert result['status']=='Done',result
    assert calls==[native] and target.is_file()
    assert result['output']['files']==[str(target)]
    assert result['output']['receipt']['ifc_sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    ask_apply(card['id'],card['input_digest'],'approve');assert calls==[native]
    assert not list(target.parent.glob('.archhub-ifc-*'))

@pytest.mark.parametrize('change',['deny','node','setting','session setting','workspace','existing','malformed'])
def test_normal_refusal_preserves_output_and_uses_no_unapproved_host(project,monkeypatch,change):
    from types import SimpleNamespace
    from nodelang.nograph_server import JsonFile,r_settings_action
    from nodelang.user_paths import state_directory
    from nodelang import settings_owner,session_files as files
    from nodelang.hook_decision import ask_apply
    path,target,card=start(project);calls=transport(monkeypatch,target,malformed=change=='malformed')
    if change=='deny':
        assert ask_apply(card['id'],card['input_digest'],'deny')['status']=='declined'
        with pytest.raises(ValueError):ask_apply(card['id'],card['input_digest'],'approve')
    else:
        if change=='node':
            doc=files.read_document(path);doc['nodes'][0]['params']['views']=[99];files.write_document(path,doc)
        if change=='setting':settings_owner.preference_settings('setAppearance',['Projects.IFC version','IFC2x3'])
        if change=='session setting':
            files.SessionFiles().dispatch({'action':'open','path':str(path)})
            service=SimpleNamespace(files={'settings':JsonFile(state_directory()/'settings/settings.json',{}),'workspaces':JsonFile(state_directory()/'settings/workspaces.json',{'roots':[]}), 'companion':JsonFile(state_directory()/'companion.json',{})})
            view={}
            def call(function,*args):
                result=r_settings_action(service,SimpleNamespace(body={'function':function,'args':list(args),'context':{'settingsDestination':view.get('settingsDestination')}}))['result'];view.update(result);return result
            call('readPreferences');call('setSettingsScope','Session','court',files.read_document(path)['id']);call('setAppearance','Projects.IFC version','IFC2x3')
        if change=='workspace':
            owner=JsonFile(state_directory()/'settings/workspaces.json',{});held=owner.read();held['roots'][0]['name']='Changed';owner.write(held)
        if change=='existing':target.write_bytes(b'Keep existing issue')
        try:
            ask_apply(card['id'],card['input_digest'],'approve')
        except ValueError:
            pass
        else:
            assert files.read_document(path)['nodes'][0]['result']['status']=='Error'
    assert calls==(['IFC4RV'] if change=='malformed' else [])
    if change=='existing':assert target.read_bytes()==b'Keep existing issue'
    else:assert not target.exists()
    if change=='session setting':
        from nodelang.hook_decision import ask_reviews,approval_record
        failed=next(row for row in ask_reviews() if row['id']==card['id']);assert failed['status']=='failed'
        assert approval_record(None,card['id'])['decided']['outcome']=='approved'
        owner=files.SessionFiles(project[0]/'sessions')
        retried=owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
        fresh=next(row for row in ask_reviews() if row['id']==retried['approvalId'])
        assert fresh['id']!=card['id'] and fresh['status']=='pending'
        assert 'IFC2x3 (Coordination View 2)' in fresh['text']
        assert ask_apply(fresh['id'],fresh['input_digest'],'approve')['status']=='approved'
        assert calls==['IFC2x3CV2'] and target.exists()
        ask_apply(fresh['id'],fresh['input_digest'],'approve');assert calls==['IFC2x3CV2']

def test_boolean_release_and_forged_grant_are_not_approval(project,monkeypatch):
    from nodelang import nodeslib_v2_engines as nodes,clean_revit_adapter as adapter
    from nodelang.hook_decision import _RELEASING
    root,source=project;effect=nodes.ifc_export_request({'project_id':'court','document':str(source),'path':str(root/'out.ifc'),'session':'48884','version':'IFC4','setup':'','views':[]},{},{'id':'fixture'})
    monkeypatch.setattr(adapter,'live_sessions',lambda:pytest.fail('unapproved native discovery'))
    forged={'caller':'archhub','session':'canvas','work':'export','action':'revit.export_ifc','scope':'revit.write','input_digest':nodes._digest_payload(effect),'digest':'fake','approval_id':'fake'}
    token=_RELEASING.set(True)
    try:
        with pytest.raises(ValueError,match='one-shot'):adapter.invoke('revit.export_ifc',{**effect,'grant':forged})
    finally:_RELEASING.reset(token)
    assert not (root/'out.ifc').exists()

def test_scoped_default_and_wired_override_share_existing_owner(project):
    from nodelang import nodeslib_v2_engines as nodes,settings_owner
    root,source=project
    params={'project_id':'court','document':str(source),'path':str(root/'out.ifc'),'session':'48884','version':'From Projects','setup':'','views':[]}
    settings_owner.preference_settings('setAppearance',['Projects.IFC version','IFC2x3'])
    doc={'id':'scope-fixture','properties':{'settings':{'Projects.IFC version':'IFC4.3'}}}
    assert nodes.ifc_export_request(params,{},doc)['version']=='IFC4x3RV'
    assert nodes.ifc_export_request(params,{'version':'IFC4'},doc)['version']=='IFC4RV'
    assert nodes.ifc_export_request(params,{}, {'id':'global','properties':{}})['version']=='IFC2x3CV2'

def test_catalogue_declares_real_file_and_list_parameters(project):
    from nodelang import session_files as files,canvas_documents as canvas
    item=next(row for row in files.catalogue() if row['id']=='file_export_ifc')
    assert not item.get('noEngine') and not canvas.is_pure(item['engine'],item['params'])
    definitions={row['id']:row for row in item['paramDefs']}
    assert definitions['document']['type']=='file' and definitions['path']['type']=='file'
    assert definitions['views']['type']=='list' and definitions['version']['type']=='choice'
    assert {'files','receipt','out'}<={port['id'] for port in item['ports']['source']}

@pytest.mark.parametrize('later_error',[False,True])
def test_two_exports_report_each_approved_node_independently(project,monkeypatch,later_error):
    from nodelang import session_files as files
    from nodelang.hook_decision import ask_apply,ask_reviews
    root,source=project;folder=root/'Issued';folder.mkdir();first,second=folder/'Coordination.ifc',folder/'Issue.ifc'
    if later_error:second.write_bytes(b'Preserve the existing issue')
    item=next(row for row in files.catalogue() if row['id']=='file_export_ifc');document=files.new_document('Two IFC exports')
    for identity,target in [('coordination',first),('issue',second)]:
        document['nodes'].append({'id':identity,'item':item['id'],'type':item['engine'],'params':{**copy.deepcopy(item['params']),'project_id':'court','document':str(source),'path':str(target),'session':'48884','version':'IFC4'},'paramDefs':copy.deepcopy(item.get('paramDefs',[])),'position':{'x':0,'y':0}})
    path=root/'two.archhub';files.write_document(path,document);owner=files.SessionFiles(root/'sessions');calls=transport(monkeypatch,first)
    run=owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    card=next(row for row in ask_reviews() if row['id']==run['approvalId'])
    assert ask_apply(card['id'],card['input_digest'],'approve')['status']=='approved'
    assert first.is_file() and calls==['IFC4RV']
    held=files.read_document(path);assert held['nodes'][0]['result']['status']=='Done'
    if later_error:
        assert held['nodes'][1]['result']['status']=='Error' and second.read_bytes()==b'Preserve the existing issue'
        ask_apply(card['id'],card['input_digest'],'approve');assert calls==['IFC4RV']
        return
    assert not second.exists() and held['nodes'][1]['result']['status']=='Waiting for approval'
    next_card=next(row for row in ask_reviews() if row['status']=='pending' and row['nodeId']=='issue')
    assert ask_apply(next_card['id'],next_card['input_digest'],'approve')['status']=='approved'
    assert calls==['IFC4RV','IFC4RV'] and second.is_file()
    for node,target in zip(files.read_document(path)['nodes'],(first,second)):
        assert node['result']['status']=='Done'
        assert node['result']['output']['receipt']['ifc_sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    ask_apply(card['id'],card['input_digest'],'approve');ask_apply(next_card['id'],next_card['input_digest'],'approve')
    assert calls==['IFC4RV','IFC4RV']

@pytest.mark.parametrize('identity,default,global_value,workspace_value,session_value,invalid', [
    ('Projects.DWG version','2018','2013','2018','2013','2010'),
    ('Projects.DWG export setup','Office DWG export','Revit default','Office DWG export','Revit default','Unknown'),
    ('Projects.Sheet size','Use Sheet Size','A0','A1','A3','A2'),
    ('Projects.Title block','Not set','Office A1 title block','Office A0 title block','Office A3 title block','missing'),
    ('Projects.IFC version','IFC4','IFC2x3','IFC4.3','IFC4','IFC9'),
    ('Projects.IFC export setup','','Global exchange','Workspace exchange','Session exchange','invalid\nname'),
])
def test_settings_three_scope_roundtrip_import_reset_and_node_binding(project, identity, default, global_value, workspace_value, session_value, invalid):
    from types import SimpleNamespace
    from nodelang import session_files as files,canvas_documents as canvas
    from nodelang.nograph_server import JsonFile,Refused,r_settings_action
    from nodelang.user_paths import state_directory
    root,_source=project;prefs=JsonFile(state_directory()/'settings/settings.json',{});roots=JsonFile(state_directory()/'settings/workspaces.json',{'roots':[]})
    doc=files.new_document('IFC scopes');doc['properties']['project']='court';path=files.document_path(files.sessions_directory(),doc);files.write_document(path,doc)
    files.SessionFiles().dispatch({'action':'open','path':str(path)})
    owner=SimpleNamespace(files={'settings':prefs,'workspaces':roots,'companion':JsonFile(root/'companion.json',{})});view={}
    def call(function,*args):
        result=r_settings_action(owner,SimpleNamespace(body={'function':function,'args':list(args),'context':{'session':doc['id'],'settingsDestination':view.get('settingsDestination')}}))['result']
        if 'settingsDestination' in result:view.update(result)
        return result
    def value(result):return next(row['value'] for row in result['appearanceSettings'] if row['id']==identity)
    assert value(call('readPreferences'))==default;call('setAppearance',identity,global_value)
    call('setSettingsScope','Workspace','court',doc['id']);before=prefs.path.read_bytes();assert value(call('setAppearance',identity,workspace_value))==workspace_value;assert prefs.path.read_bytes()==before
    call('setSettingsScope','Session','court',doc['id']);before=roots.path.read_bytes();assert value(call('setAppearance',identity,session_value))==session_value;assert roots.path.read_bytes()==before
    node={'id':'ifc-setting','type':'thing.setting','params':{'setting':identity}}
    assert canvas.run_thing('thing.setting',node['params'],{},files.read_document(path))[0]['value']==session_value
    def edit(document):canvas.write_through(node,'value',global_value,document=document);return []
    canvas.edit(path,'Court','IFC setting edit',edit,solve_changed=False);assert value(call('readPreferences'))==global_value
    snapshot={p:p.read_bytes() for p in (prefs.path,roots.path,path)}
    with pytest.raises(Refused):call('setAppearance',identity,invalid)
    with pytest.raises(Refused):call('importPreferences',{'format':'archhub.settings','version':1,'scopes':{'Session':{identity:invalid}}})
    assert all(p.read_bytes()==data for p,data in snapshot.items())
    assert value(call('resetAppearance',identity))==workspace_value
    exported=call('exportPreferences','All')['settingsExport'];assert exported['scopes']['Workspace'][identity]==workspace_value
    call('importPreferences',{'format':'archhub.settings','version':1,'scopes':{'Session':{identity:session_value}}});assert value(call('readPreferences'))==session_value


def test_setup_settings_run_ask_and_stale_approval(project, monkeypatch):
    from nodelang import settings_owner, session_files as files
    from nodelang.hook_decision import ask_apply
    identity = 'Projects.IFC export setup'
    settings_owner.preference_settings('setAppearance', [identity, 'From Projects'])
    path, target, card = start(project)
    assert 'Setup: Named: From Projects' in card['text']
    calls = transport(monkeypatch, target)
    settings_owner.preference_settings('resetAppearance', [identity])
    try:
        ask_apply(card['id'], card['input_digest'], 'approve')
    except ValueError:
        pass
    assert not calls and not target.exists()
    assert files.read_document(path)['nodes'][0]['result']['status'] != 'Done'
    owner = files.SessionFiles(project[0]/'sessions')
    result = owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    from nodelang.hook_decision import ask_reviews
    fresh = next(row for row in ask_reviews() if row['id'] == result['approvalId'])
    assert 'Setup: Revit default' in fresh['text'] and fresh['input_digest'] != card['input_digest']
    assert ask_apply(fresh['id'],fresh['input_digest'],'approve')['status'] == 'approved'
    assert calls == ['IFC4RV'] and target.is_file()


def test_ifc_setup_old_and_new_values_and_wire(project):
    from nodelang import nodeslib_v2_engines as nodes
    root, source = project
    base = {'project_id':'court','session':'48884','document':str(source),'path':str(root/'out.ifc')}
    doc = {'properties':{'settings':{'Projects.IFC export setup':'Scoped exchange'}}}
    def setup(params, wires=None):
        return nodes.ifc_export_request({**base,**params}, wires or {}, doc)['pending_write']['content']['setup']
    inherit = {'setup_source':'From Projects'}
    assert setup(inherit) == 'Scoped exchange'
    assert setup({}) == setup({'setup':''}) == setup({'setup_source':'Revit default'}) == ''
    for literal in ('From Projects','Revit default','Named setup','Office exchange'):
        assert setup({'setup':literal}) == setup({'setup_source':'Named setup','setup_name':literal}) == literal
        assert setup(inherit, {'setup':literal}) == literal
    assert setup(inherit, {'setup':''}) == ''
    assert setup(inherit, {'setup_source':'Named setup','setup_name':'Wire name'}) == 'Wire name'
    with pytest.raises(ValueError): setup({'setup_source':'Named setup','setup_name':''})


@pytest.mark.parametrize('stored,wired,expected', [
    ({},False,'Revit default'), ({'setup':''},False,'Revit default'),
    ({'setup':'From Projects'},False,'Named: From Projects'),
    ({'setup':'Revit default'},False,'Named: Revit default'),
    ({'setup_source':'From Projects'},True,'Named: Wire exchange'),
])
def test_saved_node_and_wired_setup_reach_ask(project, stored, wired, expected):
    from nodelang import settings_owner
    settings_owner.preference_settings('setAppearance',['Projects.Working subfolder','Wire exchange'])
    _,_,card = start(project,properties={'settings':{'Projects.IFC export setup':'Different scoped setup'}},
                     node_params=stored,wired=wired)
    assert 'Setup: '+expected in card['text']


@pytest.mark.parametrize('setup,label',[('Revit default','Named: Revit default'),('','Revit default')])
def test_inherited_setup_approved_to_adapter(project,monkeypatch,setup,label):
    from nodelang.hook_decision import ask_apply
    _,target,card=start(project,properties={'settings':{'Projects.IFC export setup':setup}})
    assert 'Setup: '+label in card['text']
    calls=transport(monkeypatch,target,expected_setup=setup)
    assert ask_apply(card['id'],card['input_digest'],'approve')['status']=='approved'
    assert calls==['IFC4RV'] and target.is_file()

@pytest.mark.parametrize('entry', ['canvas', 'agent', 'revoked', 'wire', 'stale', 'host-refusal', 'canvas-refuse', 'agent-refuse'])
def test_sheet_creation_uses_reviewed_model_and_title_block(project, monkeypatch, entry):
    from nodelang import clean_revit_adapter as adapter, settings_owner, session_files as files
    from nodelang.hook_decision import ask_apply, ask_reviews
    root, source = project
    settings_owner.preference_settings('setAppearance', ['Projects.Title block', 'Office A1 title block'])
    from nodelang import enforce
    from nodelang.hook_decision import _CLAIMED_ASK
    calls, decisions = [], []
    inspect = enforce.inspect_pending
    def observe(pending, *args, **kwargs):
        held = _CLAIMED_ASK.get()['row']['replay']['payload']
        reviewed = held['node']['params']['_sheet_effect']['pending_write']
        assert pending == reviewed and not calls
        result = inspect(pending, *args, **kwargs)
        decisions.append((pending['operation'], result['ok']))
        return result
    monkeypatch.setattr(enforce, 'inspect_pending', observe)
    monkeypatch.setattr(adapter, 'live_sessions', lambda: [{'port': 48884, 'pid': 7, 'revit_version': '2027', 'document': 'Model'}])
    def broker(port, route, body):
        if body.get('transaction') is False:
            return {'status': 'ok', 'result': ['Model', str(source), 'fixture-project']}
        assert decisions == [('revit.create_sheets', True)]
        calls.append(body)
        if entry == 'host-refusal':
            return {'status': 'error', 'error': 'Title block is not loaded in the disposable model.'}
        return {'status': 'ok', 'result': [{'id': 5, 'number': 'A101', 'name': 'Plan', 'title_block_type_id': 9}]}
    monkeypatch.setattr(adapter, '_call', broker)
    params = {'rows': [{'number': 'A101', 'name': 'Plan'}]}
    if entry.endswith('-refuse'):
        params['rows'][0]['unsupported'] = 'The sheet compiler rejects extra fields.'
    if entry not in ('agent', 'revoked', 'agent-refuse'):
        document = files.new_document('Sheets')
        document['nodes'] = [{'id': 'sheets', 'item': 'b_create_sheets', 'type': 'revit.create_sheets',
                              'params': params, 'position': {'x': 0, 'y': 0}}]
        if entry == 'wire':
            settings_owner.preference_settings('setAppearance', ['Projects.IFC export setup', 'A3 frame'])
            document['nodes'][0]['params']['title_block'] = 'Explicit A2'
            document['nodes'].append({'id':'setting','type':'thing.setting','params':{'setting':'Projects.IFC export setup'},'position':{'x':0,'y':120}})
            document['wires'] = [{'id':'title-wire','from':{'node':'setting','socket':'value'},'to':{'node':'sheets','socket':'title_block'}}]
        path = root / 'sheets.archhub'
        files.write_document(path, document)
        result = files.SessionFiles(root/'sessions').dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    else:
        from nodelang import native_host_tools
        from nodelang.user_paths import state_directory
        class Server:
            def tool(self, name, **options):
                def register(fn):
                    setattr(self, name, fn)
                    return fn
                return register
        server = Server()
        native_host_tools.register_host_tools(server)
        settings = state_directory() / 'settings.json'
        settings.write_text(json.dumps({'host_effects': {'revit': True}}))
        result = server.revit_run('b_create_sheets', params)
        assert result['confirmed'] is False, result
    card = next(row for row in ask_reviews() if row['id'] == result['approvalId'])
    assert ('A3 frame' if entry == 'wire' else 'Office A1 title block') in card['text'] and 'A101' in card['text'] and not calls
    assert not decisions
    if entry.endswith('-refuse'):
        with pytest.raises(ValueError, match='E0009'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert decisions == [('revit.create_sheets', False)] and not calls
        return
    if entry == 'revoked':
        settings.write_text(json.dumps({'host_effects': {'revit': False}}))
        with pytest.raises(ValueError, match='permission is disabled'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert not calls
        return
    if entry == 'stale':
        settings_owner.preference_settings('setAppearance', ['Projects.Title block', 'Office A3 title block'])
        with pytest.raises(ValueError, match='changed'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert not calls
        return
    if entry == 'host-refusal':
        with pytest.raises(ValueError, match='not loaded'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert len(calls) == 1
        return
    assert ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    ask_apply(card['id'], card['input_digest'], 'approve')
    assert len(calls) == 1 and decisions == [('revit.create_sheets', True)]
    if entry not in ('agent', 'revoked', 'agent-refuse'):
        result = files.read_document(path)['nodes'][0]['result']
        assert result['output']['sheets'][0]['title_block_type_id'] == 9
        assert result['output']['receipt']['operation'] == 'revit.create_sheets'

@pytest.mark.parametrize('change', ['target', 'operation', 'rows', 'extra argument', 'project id', 'title block'])
def test_sheet_compiler_refuses_invalid_pending_request(project, change):
    from nodelang.enforce import inspect_pending
    from nodelang.nodeslib_v2_engines import sheet_effect
    target = {'port': 48884, 'pid': 7, 'project_id': 'fixture-project', 'document': 'Model', 'path': str(project[1])}
    pending = sheet_effect({'rows': [{'number': 'A101'}], 'title_block': 'Office A1 title block'}, target)['pending_write']
    if change == 'target':
        pending['target'] = 'revit://sheet-create/another-project'
    elif change == 'operation':
        pending['operation'] = 'revit.set_parameter_by_name'
    elif change == 'rows':
        pending['content']['rows'] = [{}]
    elif change == 'extra argument':
        pending['content']['unexpected'] = True
    elif change == 'project id':
        target['project_id'] = '../other'
    else:
        pending['content']['title_block'] = ['Office A1 title block']
    checked = inspect_pending(pending)
    assert not checked['ok']
    assert any(row['code'] == 'E0009' for row in checked['diagnostics'])

def test_sheet_catalogue_and_saved_node_default(project):
    from nodelang import nodeslib_v2_engines as nodes, session_files as files
    items = {item['id']: item for item in files.catalogue()}
    for key in ('b_create_sheets', 'd_place_sheet'):
        item = items[key]
        assert item['params']['title_block'] == 'From Projects'
        port = next(port for port in item['ports']['target'] if port['id'] == 'title_block')
        assert port['type'] in ('string', 'text')
    rows = [{'number': 'A101'}]
    assert nodes.sheet_request({}, {'rows': rows}) == {'rows': rows}
    assert nodes.sheet_request({'title_block': 'Node type'}, {'rows': rows, 'title_block': ''}) == {'rows': rows}

@pytest.mark.parametrize('feeds,expected', [
    ({'sheet':'W1','views':['North','South'],'title_block':'Wired family','in':['Legacy']},
     ('W1',['North','South'],'Wired family')),
    ({'in':['Legacy']}, ('L1',['Legacy'],'Literal family')),
    ({}, ('L1',['Ground','Roof'],'Literal family')),
])
def test_place_on_sheet_named_inputs(project, monkeypatch, feeds, expected):
    from nodelang import clean_revit_adapter as adapter, session_files as files
    from nodelang.enforce import guard_effect
    seen = []
    def broker(script, transaction, params):
        sheet, names, family = expected
        assert transaction == 'ArchHub place on sheet'
        assert 'var number = ' + json.dumps(sheet) + ';' in script
        assert 'new List<string>{' + ', '.join(map(json.dumps, names)) + '}' in script
        assert 'string wanted = ' + json.dumps(family) + ';' in script
        seen.append(sheet)
        return {'port': 48884}, {'sheet': sheet, 'placed': names, 'skipped': []}
    monkeypatch.setattr(adapter, 'authoring', broker)
    item = next(row for row in files.catalogue() if row['id'] == 'd_place_sheet')
    assert {'in', 'sheet', 'views', 'title_block'} <= {row['id'] for row in item['ports']['target']}
    params = {**item['params'], 'sheet':'L1', 'views':'Ground, Roof', 'title_block':'Literal family'}
    node = {'id':'place', 'item':item['id'], 'type':item['engine'], 'params':params}
    output, _ = files._dispatch_node(files.new_document('Placement'), node, item['engine'], params, feeds,
                                     invoke=guard_effect, stopped=None, depth=0)
    assert seen == [expected[0]] and output['placed'] == expected[1]

@pytest.mark.parametrize('global_size,session_size,node_size,wire_size,expected', [
    (None, None, None, None, 'Default'),
    ('A3', None, None, None, 'ISO_A3'),
    ('A3', 'A1', None, None, 'ISO_A1'),
    ('A3', 'A1', 'A0', None, 'ISO_A0'),
    ('A1', None, 'A0', 'Use Sheet Size', 'Default'),
    ('A1', None, 'A0', 'A2', 'refused'),
])
def test_pdf_paper_format_at_export_transport(project, monkeypatch, global_size, session_size, node_size, wire_size, expected):
    from nodelang import clean_revit_adapter as adapter, settings_owner, session_files as files
    from nodelang.enforce import guard_effect
    if global_size:
        settings_owner.preference_settings('setAppearance', ['Projects.Sheet size', global_size])
    document = files.new_document('PDF set')
    if session_size:
        document['properties']['settings'] = {'Projects.Sheet size': session_size}
    params = {'sheets': 'A101, A102', 'folder': 'Print'}
    if node_size:
        params['sheet_size'] = node_size
    feeds = {} if wire_size is None else {'sheet_size': wire_size}
    item = next(row for row in files.catalogue() if row['id'] == 'o_pdf_handoff')
    choice = next(row for row in item['paramDefs'] if row['id'] == 'sheet_size')
    assert choice['type'] == 'enum' and 'Use Sheet Size' in choice['options']
    node = {'id':'pdf','type':item['engine'],'params':params}
    monkeypatch.setattr(adapter, 'sole_session', lambda: ({'port':48884, 'document':'Mixed paper set'}, ''))
    native_formats = {'A101':'ISO_A1', 'A102':'ISO_A3'}
    submitted = []
    def broker(port, route, body, *, timeout):
        assert (port, route, body['transaction_name']) == (48884, '/exec', 'ArchHub publish pdf')
        code = body['code']
        paper = re.search(r'options.PaperFormat = ExportPaperFormat\.(\w+);', code)[1]
        numbers = json.loads('[' + re.search(r'var wanted = new List<string>\{(.*?)\};', code)[1] + ']')
        effective = [native_formats[number] if paper == 'Default' else paper for number in numbers]
        submitted.append((numbers, paper, effective))
        return {'status':'ok', 'result':{'files':[number + '.pdf' for number in numbers]}}
    monkeypatch.setattr(adapter, '_call', broker)
    def export():
        return files._dispatch_node(document, node, item['engine'], params, feeds, invoke=guard_effect, stopped=None, depth=0)
    if expected == 'refused':
        with pytest.raises(ValueError, match='PDF export'):
            export()
        assert not submitted
    else:
        output, _ = export()
        expected_pages = ['ISO_A1','ISO_A3'] if expected == 'Default' else [expected, expected]
        assert submitted == [(['A101','A102'], expected, expected_pages)]
        assert output['out'] == ['A101.pdf','A102.pdf']

@pytest.mark.parametrize('mode', ['settings', 'wired', 'legacy', 'stale', 'wrong-header', 'header-only', 'truncated', 'extra-file', 'missing-file', 'collision', 'host-refusal', 'duplicate-view', 'unexpected-sidecar', 'existing', 'reject', 'compiler-refusal', 'changed-view'])
def test_registered_dwg_export_review_and_file_set(project, monkeypatch, mode):
    from pathlib import Path
    from nodelang import clean_revit_adapter as adapter, session_files as files, settings_owner
    from nodelang.hook_decision import ask_apply, ask_reviews
    root, source = project
    import os
    import ezdwg
    fixture2013 = os.environ.get('ARCHHUB_QA_DWG_2013')
    default_version = '2013' if fixture2013 else '2018'
    destination = root / 'CAD package'
    settings_owner.preference_settings('setAppearance', ['Projects.DWG version', default_version])
    settings_owner.preference_settings('setAppearance', ['Projects.DWG export setup', 'Office DWG export'])
    item = next(row for row in files.catalogue() if row['id'] == 'file_export_dwg')
    document = files.new_document('Issue DWG set')
    params = {**item['params'], 'project_id':'court', 'session':'48884', 'document':str(source),
              'path':str(destination), 'views':[41, 52]}
    if mode == 'legacy':
        params.pop('setup_source')
        params.pop('project_id')
        params.pop('document')
        document['properties']['project'] = 'court'
        params.update(setup='Legacy CAD', version='2018', views=[{'id':41}, {'id':52}])
    if mode == 'duplicate-view':
        params['views'] = [41, 41]
    document['nodes'] = [{'id':'dwg','item':item['id'],'type':item['engine'],'paramDefs':item['paramDefs'],
                          'params':params,'position':{'x':0,'y':0}}]
    path = root/'dwg.archhub'
    if mode == 'wired':
        from nodelang import canvas_tools
        api = {}
        class Registry:
            def tool(self, name):
                def register(fn):
                    api[name] = fn
                    return fn
                return register
        canvas_tools.register_canvas_tools(Registry())
        document['nodes'] = []
        files.write_document(path, document)
        held = api['canvas.add_node'](str(path), item['id'], None, params={'project_id':'court',
                                   'session':'48884', 'document':str(source), 'views':['41', '52']})
        node = held['node']
        defs = next(n['param_types'] for n in held['nodes'] if n['id'] == node)
        assert defs['path'] == defs['setup_name'] == 'text'
        for key, value in [('path', str(destination)), ('setup_source', 'Named setup'), ('setup_name', 'Literal setup')]:
            api['canvas.set_param'](str(path), node, key, value, None)
        upstream = api['canvas.add_node'](str(path), 'thing.setting', None, params={'value':'Office DWG export'})
        api['canvas.wire'](str(path), upstream['node']+'.value', node+'.setup_name', None)
    else:
        files.write_document(path, document)
    owner = files.SessionFiles(root/'sessions')
    calls = []
    expected_setup = {'legacy':'Legacy CAD'}.get(mode,'Office DWG export')
    expected_version = '2018' if mode == 'legacy' else default_version
    monkeypatch.setattr(adapter, 'live_sessions', lambda:[{'port':48884,'pid':8,'document':'Model','revit_version':'2025'}])
    def broker(port, route, body, *, timeout=None):
        if body['transaction_name'] == 'ArchHub read':
            assert mode == 'legacy' and body['transaction'] is False
            return {'status':'ok', 'result':['Model',str(source),'fixture-project']}
        assert (port,route,body['transaction_name'],body['transaction']) == (48884,'/exec','ArchHub DWG export',False)
        script = body['code']
        assert 'new long[] { 41L, 52L }' in script
        assert 'string setup = ' + json.dumps(expected_setup) in script
        assert 'FileVersion = ACADVersion.R' + expected_version in script
        stage = Path(json.loads(re.search(r'string folder = (.*?);',script)[1]))
        assert stage.is_dir() and not list(stage.iterdir()) and not destination.exists()
        calls.append(stage)
        if mode == 'host-refusal':
            return {'status':'error', 'error':'Unknown named DWG setup'}
        (stage/'XRefs').mkdir()
        if expected_version == '2013':
            data = Path(fixture2013).read_bytes()
            # LibreDWG test/test-data/2013/Polyline.dwg, Git blob 82e97619b17e2c325875054d88e90c4d966ee379.
            assert hashlib.sha256(data).hexdigest() == '9dd9152a053fceca8b339c2a6a892cef22505a4fbd3bf312dbbdd75f2f766f0f'
        elif os.environ.get('ARCHHUB_QA_DWG_2018'):
            data = Path(os.environ['ARCHHUB_QA_DWG_2018']).read_bytes()
        else:
            drawing = ezdwg.new('AC1032')
            drawing.modelspace().add_line((0, 0), (2, 1))
            drawing.save(str(root/'fixture.dwg'))
            data = (root/'fixture.dwg').read_bytes()
        (stage/'sheet.dwg').write_bytes(data)
        (stage/'XRefs/detail.dwg').write_bytes({'wrong-header': b'broken', 'header-only': data[:6],
                                                 'truncated': data[:len(data)//2]}.get(mode, data))
        (stage/'layers.pcp').write_bytes(b'pen table')
        if mode == 'collision':
            destination.mkdir()
            (destination/'personal.txt').write_text('preserve')
        listing = ['sheet.dwg','XRefs/detail.dwg','layers.pcp']
        if mode == 'unexpected-sidecar':
            (stage/'unrelated.bin').write_bytes(b'unexpected')
            listing.append('unrelated.bin')
        if mode == 'extra-file':
            (stage/'extra.pcp').write_bytes(b'extra')
        if mode == 'missing-file':
            listing.append('absent.dwg')
        return {'status':'ok','result':listing}
    monkeypatch.setattr(adapter,'_call',broker)
    if mode == 'existing':
        destination.mkdir()
        (destination/'existing.dwg').write_bytes(b'original')
    run = owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    if mode == 'existing':
        assert not run.get('approvalId') and not calls and (destination/'existing.dwg').read_bytes() == b'original'
        return
    if mode == 'duplicate-view':
        assert not run.get('approvalId') and not calls and not destination.exists()
        return
    assert run.get('approvalId'), [n.get('result', {}).get('error') for n in run['document']['nodes']]
    card = next(row for row in ask_reviews() if row['id'] == run['approvalId'])
    assert all(term in card['text'] for term in (str(source),str(destination),expected_setup,expected_version,'41, 52'))
    assert not calls and not destination.exists()
    if mode == 'reject':
        assert ask_apply(card['id'], card['input_digest'], 'deny')['status'] == 'declined'
        assert not calls and not destination.exists()
    elif mode == 'compiler-refusal':
        from nodelang import enforce
        rules = json.loads(enforce.defaults()['rules'])
        rules.pop('dwg-export')
        monkeypatch.setattr(enforce, 'graph_parameters', lambda store: {'rules': rules})
        with pytest.raises(ValueError, match='E0010'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert not calls and not destination.exists()
    elif mode == 'changed-view':
        changed = files.read_document(path)
        changed['nodes'][0]['params']['views'] = [99]
        files.write_document(path, changed)
        with pytest.raises(ValueError, match='changed'):
            ask_apply(card['id'], card['input_digest'], 'approve')
        assert not calls and not destination.exists()
    elif mode == 'stale':
        settings_owner.preference_settings('setAppearance',['Projects.DWG version','2018' if default_version == '2013' else '2013'])
        with pytest.raises(ValueError,match='changed'):
            ask_apply(card['id'],card['input_digest'],'approve')
        assert not calls and not destination.exists()
    elif mode in ('wrong-header','header-only','truncated','extra-file','missing-file','collision','host-refusal','unexpected-sidecar'):
        with pytest.raises(ValueError):
            ask_apply(card['id'],card['input_digest'],'approve')
        assert len(calls) == 1
        if mode == 'collision':
            assert [p.name for p in destination.iterdir()] == ['personal.txt']
            assert (destination/'personal.txt').read_text() == 'preserve'
        else:
            assert not destination.exists()
    else:
        assert ask_apply(card['id'],card['input_digest'],'approve')['status'] == 'approved'
        ask_apply(card['id'],card['input_digest'],'approve')
        assert len(calls) == 1
        result = files.read_document(path)['nodes'][0]['result']['output']
        expected = {p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in destination.rglob('*') if p.is_file()}
        assert set(expected) == {'sheet.dwg','XRefs/detail.dwg','layers.pcp'}
        assert result['receipt']['dwg_manifest'] == expected
        assert result['files'] == [str(destination / name) for name in sorted(expected)]
    assert not list(root.glob('.archhub-dwg-*'))

@pytest.mark.parametrize('reference,reason', [
    ('../assets/panel.png', None), ('../assets/absent.png', 'missing'),
    ('../../external.png', 'outside'), ('C:/staging/panel.png', 'relative'),
    ('/staging/panel.png', 'relative'), ('', 'relative'),
])
def test_dwg_package_reference(reference, reason):
    from pathlib import Path
    from nodelang.clean_revit_adapter import _check_dwg_reference, RevitUnreachable
    args = (Path('sheets/drawing.dwg'), reference, {Path('assets/panel.png')})
    if reason:
        with pytest.raises(RevitUnreachable, match=reason):
            _check_dwg_reference(*args)
    else:
        _check_dwg_reference(*args)


@pytest.mark.parametrize('kind', ['IMAGE', 'BLOCK_HEADER'])
def test_dwg_unread_reference_inventory_is_refused(tmp_path, kind):
    from types import SimpleNamespace
    from nodelang.clean_revit_adapter import _dwg_references, RevitUnreachable
    reader = SimpleNamespace(list_object_headers_with_type=lambda _: [(41, 0, 0, 0, kind, '')],
                             decode_image_entities=lambda _: [], decode_write_blocks=lambda _: [])
    with pytest.raises(RevitUnreachable, match='Could not verify'):
        _dwg_references(reader, tmp_path/'drawing.dwg')


# ACadSharp 3.8.35 (MIT), lib/net8.0/ACadSharp.dll; QA writer independent of the product reader.
_DWG_LINK_FIXTURE = r'''
$ErrorActionPreference = 'Stop'
Add-Type -Path $env:ARCHHUB_QA_ACADSHARP_DLL
$version = [ACadSharp.ACadVersion]$env:QA_DWG_VERSION
$drawing = [ACadSharp.CadDocument]::new($version)
$config = [ACadSharp.IO.DwgWriterConfiguration]::new()
if ($env:QA_DWG_KIND -eq 'block') {
    $block = [ACadSharp.Tables.BlockRecord]::new('Linked detail')
    $drawing.BlockRecords.Add($block)
    $block.BlockEntity.Flags = 'XRef, XRefResolved'
    $block.BlockEntity.XRefPath = $env:QA_DWG_REFERENCE
    $drawing.ModelSpace.Entities.Add([ACadSharp.Entities.Insert]::new($block))
    [ACadSharp.IO.DwgWriter]::Write($env:QA_DWG_TARGET, [ACadSharp.CadDocument]::new($version), $config, $null)
} else {
    $sample = Join-Path $env:ARCHHUB_QA_DWG_SAMPLES ('sample_' + $env:QA_DWG_VERSION + '.dwg')
    $drawing = [ACadSharp.IO.DwgReader]::Read([string]$sample, [ACadSharp.IO.DwgReaderConfiguration]::new(),
                                             [ACadSharp.IO.NotificationEventHandler]$null)
    $defs = @($drawing.ImageDefinitions)
    if ($defs.Count -ne 1) { throw 'Expected one bound raster definition' }
    $defs[0].FileName = $env:QA_DWG_REFERENCE
}
[ACadSharp.IO.DwgWriter]::Write($env:QA_DWG_SHEET, $drawing, $config, $null)
'''


@pytest.mark.parametrize('version,signature', [('2013','AC1027'), ('2018','AC1032')])
@pytest.mark.parametrize('kind', ['block', 'raster'])
@pytest.mark.parametrize('mode', ['relative', 'staged-absolute', 'missing', 'outside'])
def test_reviewed_dwg_references(project, monkeypatch, version, signature, kind, mode):
    import os, subprocess
    from pathlib import Path
    import ezdwg
    from nodelang import clean_revit_adapter as adapter, session_files as files
    from nodelang.hook_decision import ask_apply, ask_reviews
    if not os.environ.get('ARCHHUB_QA_ACADSHARP_DLL'):
        pytest.skip('Independent linked-DWG writer requires the ACadSharp QA DLL.')
    # DomCR/ACadSharp samples/sample_AC1027.dwg, sample_AC1032.dwg and image.JPG.
    if kind == 'raster' and not os.environ.get('ARCHHUB_QA_DWG_SAMPLES'):
        pytest.skip('Set ARCHHUB_QA_DWG_SAMPLES to the ACadSharp sample directory.')
    root, source = project
    sentinel = root/'unrelated.txt'
    sentinel.write_text('preserve')
    destination = root/'Issued CAD'
    item = next(row for row in files.catalogue() if row['id'] == 'file_export_dwg')
    doc = files.new_document('Reference review')
    doc['nodes'] = [{'id':'export', 'item':item['id'], 'type':item['engine'], 'paramDefs':item['paramDefs'],
                     'params':{**item['params'], 'project_id':'court', 'session':'48884', 'document':str(source),
                               'path':str(destination), 'views':[41], 'version':version, 'setup_source':'Revit default'},
                     'position':{'x':0,'y':0}}]
    path = root/'export.archhub'
    files.write_document(path, doc)
    owner = files.SessionFiles(root/'sessions')
    monkeypatch.setattr(adapter, 'live_sessions', lambda:[{'port':48884,'pid':8,'document':'Model','revit_version':'2025'}])
    asset_name = 'detail.dwg' if kind == 'block' else 'image.JPG'
    before = {}
    def export(port, route, body, *, timeout=None):
        assert route == '/exec' and body['transaction'] is False
        stage = Path(json.loads(re.search(r'string folder = (.*?);', body['code'])[1]))
        (stage/'sheets').mkdir()
        (stage/'assets').mkdir()
        sheet, target = stage/'sheets/plan.dwg', stage/'assets'/asset_name
        reference = {'relative': '../assets/'+asset_name, 'missing':'../assets/missing'+target.suffix,
                     'outside':'../../outside'+target.suffix, 'staged-absolute':str(target)}[mode]
        if kind == 'raster':
            image = (Path(os.environ['ARCHHUB_QA_DWG_SAMPLES'])/'image.JPG').read_bytes()
            assert hashlib.sha256(image).hexdigest() == '55e9a686d51f82692ca6bbfb2be367f899fa0f16d3c408e80d7930ddae72d4ff'
            target.write_bytes(image)
        env = dict(os.environ, QA_DWG_VERSION=signature, QA_DWG_KIND=kind, QA_DWG_REFERENCE=reference,
                   QA_DWG_SHEET=str(sheet), QA_DWG_TARGET=str(target))
        subprocess.run(['pwsh.exe','-NoProfile','-NonInteractive','-Command',_DWG_LINK_FIXTURE],
                       env=env, check=True, capture_output=True, timeout=30)
        assert adapter._dwg_references(ezdwg.raw, sheet) == [reference]
        before.update({f.relative_to(stage).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in (sheet,target)})
        return {'status':'ok','result':list(before)}
    monkeypatch.setattr(adapter,'_call',export)
    run = owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    card = next(row for row in ask_reviews() if row['id'] == run['approvalId'])
    assert str(destination) in card['text'] and not before and not destination.exists()
    if mode == 'relative':
        assert ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
        published = destination/'sheets/plan.dwg'
        ref, = adapter._dwg_references(ezdwg.raw, published)
        assert hashlib.sha256((published.parent/ref).read_bytes()).hexdigest() == before['assets/'+asset_name]
        result = files.read_document(path)['nodes'][0]['result']['output']
        assert result['receipt']['dwg_manifest'] == before
    else:
        reason = {'staged-absolute':'relative','missing':'missing','outside':'outside'}[mode]
        with pytest.raises(ValueError, match=reason):
            ask_apply(card['id'], card['input_digest'], 'approve')
        failed = next(row for row in ask_reviews() if row['id'] == card['id'])
        assert failed['status'] == 'failed' and reason in failed['error']
        assert before and not destination.exists()
    assert sentinel.read_text() == 'preserve' and not list(root.glob('.archhub-dwg-*'))


@pytest.mark.parametrize('views', [['41', 41], ['0'], ['-1'], ['1.5'], ['2e3'], ['9223372036854775808'],
                                   [''], ['041'], [' 41 '], [True], ['1' * 100]])
def test_dwg_inspector_rejects_invalid_view_ids(views):
    from nodelang.nodeslib_v2_engines import dwg_export_request
    with pytest.raises(ValueError, match='distinct positive Revit view IDs'):
        dwg_export_request({'views':views,'version':'2018','setup_source':'Revit default','session':'48884'}, {}, {})
