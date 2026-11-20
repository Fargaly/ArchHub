"""Scoped preferences use the real file owners and leave invalid imports unwritten."""
import json
from types import SimpleNamespace
from unittest.mock import patch


def test_scoped_preferences_round_trip_node_binding_and_atomic_import(tmp_path, monkeypatch):
    root = tmp_path
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR', 'WORKSHOP_STATE_DIR'):
        directory = root / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    from nodelang import session_files as files
    from nodelang.nograph_server import JsonFile, Refused, r_settings_action
    from nodelang.user_paths import state_directory
    prefs=JsonFile(state_directory()/'settings/settings.json',{})
    roots=JsonFile(state_directory()/'settings/workspaces.json',{'roots':[]})
    work=root/'project';work.mkdir()
    roots.write({'roots':[{'root_id':'tower','label':'Tower','path':str(work),'settings':{'Appearance.Text scale':125}}]})
    prefs.write({'appearanceTheme':'Dark','keybindings':{'menu.copy':'Ctrl Alt C'},'unrelated':42})
    doc=files.new_document('Scope probe');doc['properties']['project']='tower'
    path=files.document_path(files.sessions_directory(),doc);files.write_document(path,doc)
    files.SessionFiles().dispatch({'action':'open','path':str(path)})
    owner=SimpleNamespace(files={'settings':prefs,'workspaces':roots,'companion':JsonFile(root/'companion.json',{})})
    view={}
    def call(function,*args):
        result=r_settings_action(owner,SimpleNamespace(body={'function':function,'args':list(args),'context':{'session':doc['id'],'settingsDestination':view.get('settingsDestination')}}))['result']
        if 'settingsDestination' in result:view.update(result)
        return result
    def theme(result):
        return next(row['value'] for row in result['appearanceSettings'] if row['id']=='Appearance.Theme')
    call('readPreferences')
    call('setSettingsScope','Workspace','tower',doc['id'])
    global_before=prefs.path.read_bytes()
    assert theme(call('setAppearance','Appearance.Theme','Light'))=='Light'
    assert prefs.path.read_bytes()==global_before,'workspace edit changed global file'
    assert roots.read()['roots'][0]['settings']['Appearance.Theme']=='Light'
    with patch('nodelang.nograph_server._secrets',return_value=[]),patch('nodelang.settings_owner.read_router_settings',return_value={'providerPreferences':{}}):
        assert theme(call('readControls'))=='Light','real route did not read back workspace value'
    assert files.resolve_setting(files.read_document(path),'Appearance.Theme')=={'value':'Light','scope':'workspace'}
    from nodelang.canvas_documents import run_thing, edit
    from nodelang.node_params import set_value
    binding={'id':'theme-setting','item':'thing:setting:Appearance.Theme','type':'thing.setting','title':'Theme','params':{'setting':'Appearance.Theme'},'position':{'x':0,'y':0}}
    edit(path,'Probe','place setting',lambda document:document['nodes'].append(binding),solve_changed=False)
    node_document=files.read_document(path)
    assert run_thing('thing.setting',binding['params'],{},document=node_document)[0]['value']=='Light'
    edit(path,'Probe','edit scoped setting',lambda document:set_value(document,'theme-setting','value','System'),solve_changed=False)
    assert theme(call('readPreferences'))=='System','node write and Settings disagree'
    files.set_session_fields(path,{'settings':{'Appearance.Theme':'System'}})
    assert files.resolve_setting(files.read_document(path),'Appearance.Theme')=={'value':'System','scope':'session'}
    files.set_session_fields(path,{'settings':{'Appearance.Theme':None}})
    assert files.resolve_setting(files.read_document(path),'Appearance.Theme')['value']=='System'
    assert theme(call('resetAppearance','Appearance.Theme'))=='Dark','reset did not inherit global'
    exported=call('exportPreferences','All')['settingsExport']
    assert exported['scopes']['User']['Keyboard.menu.copy']=='Ctrl Alt C'
    paths=[prefs.path,roots.path,path]
    snapshots={str(file):file.read_bytes() for file in paths}
    bad=[{'format':'archhub.settings','version':1,'scopes':{'Workspace':{'Appearance.Theme':'Light','Appearance.Text scale':900}}},
         {'format':'archhub.settings','version':1,'scopes':{'User':{'Appearance.Theme':'Light'},'Workspace':{'Keyboard.menu.copy':'Ctrl Z'}}},
         {'format':'archhub.settings','version':1,'scopes':{'Session':{'unrecognized':'value'}}}]
    for value in bad:
        try:call('importPreferences',value)
        except Refused:pass
        else:raise AssertionError('invalid import accepted')
        assert all(file.read_bytes()==snapshots[str(file)] for file in paths),'invalid import wrote a file'
    imported={'format':'archhub.settings','version':1,'scopes':{'Workspace':{'Appearance.Theme':'Light','Keyboard.menu.copy':'Ctrl Shift C'}}}
    assert theme(call('importPreferences',imported))=='Light'
    call('setSettingsScope','Session','tower',doc['id'])
    call('setAppearance','Appearance.Theme','Light')
    assert run_thing('thing.setting',binding['params'],{},document=files.read_document(path))[0]['value']=='Light'
    edit(path,'Probe','edit session setting',lambda document:set_value(document,'theme-setting','value','Dark'),solve_changed=False)
    assert theme(call('readPreferences'))=='Dark','session node write and Settings disagree'
    call('setKeybinding','menu.copy','Ctrl Alt X')
    assert files.resolve_setting(files.read_document(path),'Keyboard.menu.copy')=={'value':'Ctrl Alt X','scope':'session'}
    call('resetPreferences')
    assert files.resolve_setting(files.read_document(path),'Keyboard.menu.copy')=={'value':'Ctrl Shift C','scope':'workspace'}
    from nodelang.settings_owner import preference_scope
    stale=preference_scope()
    edit(path,'Probe','concurrent title',lambda document:document.update(title='Changed concurrently'),solve_changed=False)
    before=path.read_bytes()
    try:stale.change({'Appearance.Theme':'System'})
    except ValueError as error:assert 'session changed' in str(error).lower()
    else:raise AssertionError('stale session update was accepted')
    assert path.read_bytes()==before
    call('setSettingsScope','Workspace','tower',doc['id'])
    before=prefs.path.read_bytes()
    call('importPreferences',{'format':'archhub.settings','version':1,'scopes':{'User':{'Appearance.Theme':'Light'},'Workspace':{'Appearance.Theme':'System'}}})
    assert prefs.path.read_bytes()==before,'import changed a scope other than its selected destination'
    call('setSettingsScope','User','tower',doc['id'])
    prefs.update({'keybindings':{'retired-command':'broken'}})
    call('setAppearance','Appearance.Theme','Light')
    assert prefs.read()['keybindings']=={'retired-command':'broken'},'appearance edit repaired keyboard data without a reset'
    call('resetKeybindings')
    assert prefs.read()['keybindings']=={}
    call('readPreferences')
    call('setSettingsScope','Workspace','tower',doc['id'])
    call('readPreferences')
    direct=preference_scope();direct.read()
    saved_roots=roots.read()
    roots.write({**saved_roots,'roots':[]})
    def unchanged_after_refusal(function,*args):
        expected={str(file):file.read_bytes() for file in paths}
        try:call(function,*args)
        except Refused as error:assert error.code=='settings_destination_changed'
        else:raise AssertionError('stale destination was accepted: '+function)
        assert all(file.read_bytes()==expected[str(file)] for file in paths),'refused destination changed an owner file'
    unchanged_after_refusal('setAppearance','Appearance.Theme','Dark')
    try:direct.change({'Appearance.Theme':'Dark'})
    except ValueError:pass
    else:raise AssertionError('direct owner silently fell back to global')
    with patch('nodelang.nograph_server._secrets',return_value=[]),patch('nodelang.settings_owner.read_router_settings',return_value={'providerPreferences':{}}):
        unavailable=call('readControls')
    assert unavailable['settingsScope']=='Workspace' and unavailable['settingsScopeNotice'] and unavailable['appearanceSettings']
    call('setSettingsScope','User','',doc['id'])
    roots.write(saved_roots)
    call('readPreferences')
    call('setSettingsScope','Workspace','tower',doc['id'])
    work2=root/'project2';work2.mkdir()
    roots.write({'roots':[*roots.read()['roots'],{'root_id':'tower2','label':'Tower2','path':str(work2)}]})
    call('readPreferences')
    files.set_session_fields(path,{'project':'tower2'})
    unchanged_after_refusal('setAppearance','Appearance.Theme','Dark')
    files.set_session_fields(path,{'project':'tower'})
    call('readPreferences')
    prefs.update({'settingsScope':'User'})
    unchanged_after_refusal('setAppearance','Appearance.Theme','Dark')
    unchanged_after_refusal('resetPreferences')
    unchanged_after_refusal('importPreferences',{'format':'archhub.settings','version':1,'scopes':{'User':{'Appearance.Theme':'Dark'},'Workspace':{'Appearance.Theme':'Dark'}}})
    call('readPreferences')
    call('setSettingsScope','Workspace','tower',doc['id'])
    root_rows=roots.read()
    roots.write({'roots':[{**row,'path':str(work2)} if row['root_id']=='tower' else row for row in root_rows['roots']]})
    unchanged_after_refusal('setAppearance','Appearance.Theme','Dark')
    roots.write(root_rows)
    call('readPreferences')
    from nodelang.settings_owner import PreferenceScope
    validate=PreferenceScope.validate
    during={}
    def switch_during_validation(context,scope,values,maps):
        validate(context,scope,values,maps)
        files.set_session_fields(path,{'project':'tower2'})
        during['session']=path.read_bytes()
    before={str(file):file.read_bytes() for file in (prefs.path,roots.path)}
    with patch.object(PreferenceScope,'validate',switch_during_validation):
        try:call('setAppearance','Appearance.Theme','Dark')
        except Refused as error:assert error.code=='settings_destination_changed'
        else:raise AssertionError('mid-request destination switch was accepted')
    assert all(file.read_bytes()==before[str(file)] for file in (prefs.path,roots.path))
    assert path.read_bytes()==during['session'],'refused edit changed the independently updated session'
    files.set_session_fields(path,{'project':'tower'})
    call('readPreferences')
    other=files.new_document('Other session');other['properties']['project']='tower2'
    other_path=files.document_path(files.sessions_directory(),other);files.write_document(other_path,other)
    def open_during_validation(context,scope,values,maps):
        validate(context,scope,values,maps)
        files.SessionFiles().dispatch({'action':'open','path':str(other_path)})
    before={str(file):file.read_bytes() for file in (prefs.path,roots.path,path,other_path)}
    with patch.object(PreferenceScope,'validate',open_during_validation):
        try:call('setAppearance','Appearance.Theme','Dark')
        except Refused as error:assert error.code=='settings_destination_changed'
        else:raise AssertionError('mid-request session switch was accepted')
    assert all(file.read_bytes()==before[str(file)] for file in (prefs.path,roots.path,path,other_path))
    assert prefs.read()['unrelated']==42
    print(json.dumps({'result':'PASS','workspace_edit_global_bytes_unchanged':True,'readback':'real r_settings_action readControls',
                      'precedence':'session then workspace then global','reset':'inherits','keyboard':'export/import/session/reset','nodes':'Settings-to-node and node-to-Settings agree in workspace and session scopes',
                      'invalid_imports_zero_writes':len(bad),'import_destination':'only selected owner','stale_session':'refused without writes','destination_refusals':'removed workspace, same document changed project, other window User, same-id root path switch; all three files unchanged','unavailable_read':'usable, explicit notice, scope selection recovers','malformed_keyboard':'preserved by appearance edit; explicit reset recovers','owners':'existing JSON + .archhub files','boundary':'temporary owner/route, not browser or installed'}))
