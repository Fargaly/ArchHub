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
