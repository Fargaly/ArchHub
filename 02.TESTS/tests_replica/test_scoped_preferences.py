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
    call('readPreferences')
    paths_before = {p: p.read_bytes() for p in (prefs.path, roots.path, path, other_path)}
    unchanged_after_refusal('setSettingsScope', 'Workspace', 'tower2', doc['id'])
    unchanged_after_refusal('setSettingsScope', 'Session', 'tower', other['id'])
    files.SessionFiles().dispatch({'action':'open','path':str(other_path)})
    unchanged_after_refusal('setAppearance', 'Appearance.Theme', 'Dark')
    assert all(p.read_bytes() == value for p, value in paths_before.items())
    files.SessionFiles().dispatch({'action':'open','path':str(path)})
    call('readPreferences')
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


def test_project_working_subfolder_reaches_session_and_handover(tmp_path, monkeypatch):
    import pytest
    from pathlib import Path
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR', 'WORKSHOP_STATE_DIR'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    from nodelang import session_files as files
    from nodelang.canvas_documents import run_thing
    from nodelang.nograph_server import JsonFile
    from nodelang.settings_owner import PreferenceScope
    from nodelang.user_paths import state_directory
    key = 'Projects.Working subfolder'
    prefs = JsonFile(state_directory() / 'settings/settings.json', {})
    roots = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []})
    work = tmp_path / 'project'
    work.mkdir()
    roots.write({'roots': [{'root_id': 'tower', 'label': 'Tower', 'path': str(work), 'settings': {}}]})
    document = files.new_document('Working folder consumer')
    document['properties']['project'] = 'tower'
    path = files.document_path(files.sessions_directory(), document)
    files.write_document(path, document)
    files.SessionFiles().dispatch({'action': 'open', 'path': str(path)})
    def owner():
        return PreferenceScope(prefs, roots, str(path))
    def folder(explicit=''):
        held = files.read_document(path)
        result, _ = run_thing('thing.session', {'project_folder': explicit}, {}, document=held)
        assert result['project folder'] == result['context']['project_folder']
        return result['context']['project_folder']
    assert folder() == str(work)
    from nodelang.nograph_server import r_settings_action
    server = SimpleNamespace(files={'settings': prefs, 'workspaces': roots, 'companion': JsonFile(tmp_path / 'companion.json', {})})
    read = r_settings_action(server, SimpleNamespace(body={'function': 'readPreferences', 'args': []}))['result']
    changed = r_settings_action(server, SimpleNamespace(body={'function': 'setAppearance', 'args': [key, 'route'], 'context': {'settingsDestination': read['settingsDestination']}}))['result']
    assert next(row for row in changed['appearanceSettings'] if row['id'] == key)['value'] == 'route'
    assert folder() == str(work / 'route')
    from nodelang.settings_owner import SettingsOwner
    bindings = SettingsOwner.exposeSettingsPage('Projects')['nodes']
    binding = next(node for node in bindings if node['params']['setting'] == key)
    assert binding['params'] == {'setting': key}
    from nodelang.node_params import socket_type
    from nodelang.canvas_documents import SESSION_PARAMS, thing_items
    parameter = next(row for row in SESSION_PARAMS if row['id'] == 'project_folder')
    card = next(row for row in thing_items() if row.get('params', {}).get('setting') == key)
    assert card['ports']['source'][0]['type'] == socket_type(parameter['type'])
    assert run_thing('thing.setting', binding['params'], {}, document=files.read_document(path))[0]['value'] == 'route'
    for scope, value in [('User', 'global'), ('Workspace', 'workspace'), ('Session', 'session')]:
        owner().select(scope, 'tower', document['id'])
        owner().change({key: value})
        assert folder() == str(work / value), 'the real Session engine must consume the selected scoped value'
        assert folder('explicit-node') == str(work / 'explicit-node')
        assert folder(str(work / 'explicit-absolute')) == str(work / 'explicit-absolute')
        assert files.resolve_project_folder(files.new_document(), '') == '', 'a default never selects a project implicitly'
    assert files.read_document(path)['properties']['settings'][key] == 'session'
    exported = owner().export('All')['scopes']
    assert [exported[scope][key] for scope in ('User', 'Workspace', 'Session')] == ['global', 'workspace', 'session']
    owner().change({key: None})
    assert folder() == str(work / 'workspace')
    owner().select('Workspace', 'tower', document['id'])
    owner().change({key: None})
    assert folder() == str(work / 'global')
    owner().select('User', 'tower', document['id'])
    owner().change({key: None})
    assert folder() == str(work)
    assert files.resolve_project_folder(files.new_document(), '') == '', 'no project never grants a folder'
    snapshots = {file: file.read_bytes() for file in (prefs.path, roots.path, path)}
    for bad in ('../outside', 'a/../outside', 'a\\..\\outside', '/absolute', 'C:/absolute', 'C:relative',
                '\\\\server\\share', 'a/.. /outside', 'a/../', 'bad.', 'NUL', 'https://outside'):
        with pytest.raises(ValueError):
            owner().change({key: bad})
        assert all(file.read_bytes() == before for file, before in snapshots.items())
    with pytest.raises(ValueError):
        owner().import_values({'format': 'archhub.settings', 'version': 1, 'scopes': {'User': {key: 'valid'}, 'Workspace': {key: '../outside'}}})
    assert all(file.read_bytes() == before for file, before in snapshots.items())
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create, handover, open_session
    with application_history() as history:
        task = create(history, 'Working folder handover', 'founder')['id']
        task_path = Path(open_session(history, task)['path'])
    files.set_session_fields(task_path, {'project': 'tower', 'settings': {key: 'joined'}})
    with application_history() as history:
        assert handover(history, task)['context']['project_folder'] == str(work / 'joined')
    files.set_session_fields(task_path, {'settings': {key: None}})
    files.SessionFiles().dispatch({'action': 'open', 'path': str(task_path)})
    def joined_owner():
        return PreferenceScope(prefs, roots, str(task_path))
    task_id = files.read_document(task_path)['id']
    joined_owner().select('User', 'tower', task_id)
    joined_owner().change({key: 'global-joined'})
    with application_history() as history:
        assert handover(history, task)['context']['project_folder'] == str(work / 'global-joined')
    joined_owner().select('Workspace', 'tower', task_id)
    unchanged_document = task_path.read_bytes()
    for value in ('workspace-joined', 'workspace-updated'):
        joined_owner().change({key: value})
        with application_history() as history:
            assert handover(history, task)['context']['project_folder'] == str(work / value)
        assert task_path.read_bytes() == unchanged_document, 'resolved defaults must not be copied into the task file'
    held = files.read_document(task_path)
    next(node for node in held['nodes'] if node['id'] == 'start')['params']['project_folder'] = 'explicit-session-node'
    files.write_document(task_path, held)
    with application_history() as history:
        assert handover(history, task)['context']['project_folder'] == str(work / 'explicit-session-node')
    assert key not in held['properties'].get('settings', {}), 'inherited values are not copied into the document'


def test_working_subfolder_uses_the_session_typed_parameter_source(monkeypatch):
    from nodelang import canvas_documents as canvas
    from nodelang.settings_owner import preference_settings, _PreferenceValues
    parameters = tuple({**row, 'value': 'parameter-default'} if row['id'] == 'project_folder' else dict(row)
                       for row in canvas.SESSION_PARAMS)
    monkeypatch.setattr(canvas, 'SESSION_PARAMS', parameters)
    parameter = next(row for row in parameters if row['id'] == 'project_folder')
    control = next(row for row in preference_settings(settings=_PreferenceValues({}))['appearanceSettings']
                   if row['id'] == 'Projects.Working subfolder')
    output, _ = canvas.run_thing('thing.session', {}, {})
    assert control['type'] == parameter['type']
    assert control['default'] == control['value'] == output['context']['project_folder'] == parameter['value']


def test_project_register_restores_inheritance_without_modifying_session_files(tmp_path, monkeypatch):
    import pytest
    from nodelang import session_files
    from nodelang.nograph_server import JsonFile, Refused, r_workspace_roots
    from nodelang.settings_owner import PreferenceScope
    from nodelang.user_paths import state_directory

    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    prefs = JsonFile(state_directory() / 'settings/settings.json', {})
    roots = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []})
    rows = []
    for key in ('first', 'second'):
        path = tmp_path / key
        path.mkdir()
        rows.append({'root_id': key, 'path': str(path), 'label': key, 'settings': {'Projects.Length': 'Metres'}})
    roots.write({'roots': rows, 'imported_legacy': True})
    server = SimpleNamespace(files={'settings': prefs, 'workspaces': roots}, workspace_built_in=lambda: '')
    def call(action, **body):
        return r_workspace_roots(server, SimpleNamespace(body={'action': action, **body}))

    doc = session_files.new_document('Existing session')
    doc['properties']['project'] = 'first'
    path = tmp_path / 'existing.archhub'
    session_files.write_document(path, doc)
    original = path.read_bytes()
    call('select', id='first')
    legacy = call('list')['roots'][0]['register']
    assert legacy == {'number': '', 'override': True}
    edited = call('update-register', id='first', expected=legacy, number='TEST-01', override=False)['register']
    assert session_files.resolve_setting(doc, 'Projects.Length')['value'] == 'Millimetres'
    scoped = PreferenceScope(prefs, roots, str(path), current_path=lambda: str(path))
    assert scoped.effective('Session').get('Projects.Length') is None
    assert scoped.effective('Workspace')['Projects.Length'] == 'Metres'
    with pytest.raises(Refused):
        call('update-register', id='first', expected=legacy, number='Stale', override=True)
    call('select', id='second')
    with pytest.raises(Refused):
        call('update-register', id='first', expected=edited, number='Wrong root', override=False)
    assert call('list')['roots'][1]['register'] == legacy
    call('select', id='first')
    assert call('update-register', id='first', expected=edited, number='', override=True)['register'] == legacy
    assert session_files.resolve_setting(session_files.read_document(path), 'Projects.Length')['value'] == 'Metres'
    assert original == path.read_bytes()


def test_native_client_is_private_to_one_registered_project(tmp_path, monkeypatch):
    import os
    import pytest
    if os.name != 'nt':
        pytest.skip('the native client editor uses Windows user-bound encryption')
    from nodelang import baboom_nograph, session_files
    from nodelang.nograph_server import JsonFile, Refused, r_workspace_roots
    from nodelang.settings_owner import PreferenceScope
    from nodelang.user_paths import state_directory
    from nodelang.workspace_roots_catalogue import read_registered_roots, root_bound_registration

    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    surface = 'settings/Projects'
    monkeypatch.setattr(baboom_nograph, 'studio_surface', lambda: surface)
    settings = JsonFile(state_directory() / 'settings/settings.json', {})
    store = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []})
    rows = []
    for key in ('north', 'south'):
        folder = tmp_path / key
        folder.mkdir()
        rows.append({'root_id': key, 'path': str(folder), 'label': key, 'privacy':'private'})
    store.write({'roots':rows, 'imported_legacy':True})
    sentinel = 'Synthetic private client 4318'
    dialogs = []
    answer = sentinel
    def edit(identity, name, current):
        dialogs.append((identity, current))
        return answer
    server = SimpleNamespace(files={'settings':settings, 'workspaces':store}, workspace_built_in=lambda:'',
                             ensure_current_desktop_access=lambda admission:None, native_project_client_editor=edit)
    def call(action, **body):
        return r_workspace_roots(server, SimpleNamespace(method='POST', body={'action':action, **body}))

    call('select', id='north')
    assert call('edit-local-client', id='north') == {'ok': True}
    assert dialogs[-1] == ('north','')
    raw = store.path.read_bytes()
    assert sentinel.encode() not in raw
    doc = session_files.new_document('Local test')
    doc['properties']['project'] = 'north'
    path = tmp_path / 'portable.archhub'
    session_files.write_document(path, doc)
    scope = PreferenceScope(settings, store, str(path), current_path=lambda:str(path))
    public = [call('list'), call('select',id='north'), call('register',path=rows[0]['path']),
              read_registered_roots()[0], root_bound_registration('workspace-roots/north/drawing.txt'),
              scope.export('All'), session_files.read_document(path)]
    assert sentinel not in json.dumps(public) and 'local_clients' not in json.dumps(public)
    assert sentinel.encode() not in path.read_bytes()
    surface = 'canvas'
    with pytest.raises(Refused):
        call('edit-local-client', id='north')
    surface = 'settings/Projects'
    with pytest.raises(Refused):
        call('edit-local-client', id='north', value='browser supplied')
    call('select', id='south')
    answer = None
    assert call('edit-local-client', id='south') == {'ok':True}
    assert dialogs[-1] == ('south','')
    call('select', id='north')
    call('edit-local-client', id='north')
    assert dialogs[-1] == ('north',sentinel) and store.path.read_bytes() == raw
    def switch_while_editing(*args):
        call('select', id='south')
        return 'Changed too late'
    server.native_project_client_editor = switch_while_editing
    with pytest.raises(Refused):
        call('edit-local-client', id='north')
    assert store.path.read_bytes() == raw
    call('unregister', id='north')
    assert 'local_clients' not in store.read()

def test_local_client_dialog_expires_and_cancel_is_distinct(monkeypatch):
    import pytest
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PyQt6.QtWidgets')
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QInputDialog
    from nodelang.nograph_launcher import edit_project_client
    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'offscreen':
        pytest.skip('use an isolated offscreen Qt process')
    opened = []
    def type_without_accepting():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue('Synthetic unsaved value')
        opened.append(True)
    QTimer.singleShot(0, type_without_accepting)
    with pytest.raises(ValueError, match='expired'):
        edit_project_client(None, 'Fixture', '', timeout_ms=100)
    assert opened and app.activeModalWidget() is None
    QTimer.singleShot(0, lambda: app.activeModalWidget().reject())
    assert edit_project_client(None, 'Fixture', 'Existing value') is None




def test_project_register_keeps_adopted_register_references_inside_the_selected_project(tmp_path, monkeypatch):
    import os
    import pytest
    from nodelang.nograph_server import JsonFile, Refused, r_workspace_roots
    from nodelang.user_paths import state_directory
    from nodelang.workspace_roots_catalogue import register_paths

    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    prefs = JsonFile(state_directory() / 'settings/settings.json', {})
    roots = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []})
    rows = []
    for key in ('first', 'second'):
        (tmp_path / key).mkdir()
        rows.append({'root_id': key, 'path': str(tmp_path / key), 'label': key})
    roots.write({'roots': rows, 'imported_legacy': True})
    server = SimpleNamespace(files={'settings': prefs, 'workspaces': roots}, workspace_built_in=lambda: '')
    def call(action, **body):
        return r_workspace_roots(server, SimpleNamespace(body={'action': action, **body}))

    call('select', id='first')
    legacy = call('list')['roots'][0]['register']
    assert legacy == {'number': '', 'override': False}  # unchanged shape while no reference is set
    saved = call('update-register', id='first', expected=legacy, number='P-1', override=False,
                 namingRegister='Registers/P001-naming-register.xlsx', issuedRegister='Issue/ISSUED.md')['register']
    assert saved == {'number': 'P-1', 'override': False, 'namingRegister': 'Registers\\P001-naming-register.xlsx', 'issuedRegister': 'Issue\\ISSUED.md'}
    assert register_paths(roots.read()['roots'][0]) == {'namingRegister': tmp_path / 'first' / 'Registers' / 'P001-naming-register.xlsx',
                                                        'issuedRegister': tmp_path / 'first' / 'Issue' / 'ISSUED.md'}
    kept = call('update-register', id='first', expected=saved, number='P-2', override=False)['register']  # legacy caller
    assert kept['namingRegister'] == 'Registers\\P001-naming-register.xlsx' and kept['issuedRegister'] == 'Issue\\ISSUED.md'
    for bad in ('..\\second\\naming.xlsx', 'C:\\naming.xlsx', '\\\\server\\share\\naming.xlsx', '\\naming.xlsx', 'REGISTER.md', 'a/../../x.xlsx', 'naming.pdf', None, False, 0):
        with pytest.raises(Refused):  # a folder inventory is not the naming register; only '' clears
            call('update-register', id='first', expected=kept, number='P-2', override=False, namingRegister=bad)
    for bad in ('ISSUED.txt', None, False):
        with pytest.raises(Refused):
            call('update-register', id='first', expected=kept, number='P-2', override=False, issuedRegister=bad)
    assert call('list')['roots'][0]['register'] == kept
    try:
        os.symlink(tmp_path / 'second', tmp_path / 'first' / 'linked', target_is_directory=True)
    except OSError:
        pass  # no symlink privilege on this machine; the other refusals still cover escape
    else:
        with pytest.raises(Refused):
            call('update-register', id='first', expected=kept, number='P-2', override=False, issuedRegister='linked\\ISSUED.md')
    call('select', id='second')
    with pytest.raises(Refused):  # a switched project never takes the edit
        call('update-register', id='first', expected=kept, number='P-2', override=False, namingRegister='naming.xlsx')
    call('select', id='first')
    from nodelang.workspace_roots_catalogue import register_files
    row = next(r for r in call('list')['roots'] if r['root_id'] == 'first')
    assert row['registerFiles'] == {'namingRegister': 'missing', 'issuedRegister': 'missing'}
    (tmp_path / 'first' / 'Registers').mkdir()
    (tmp_path / 'first' / 'Registers' / 'P001-naming-register.xlsx').write_bytes(b'register')
    assert register_files(roots.read()['roots'][0]) == {'namingRegister': 'usable', 'issuedRegister': 'missing'}
    chosen = str(tmp_path / 'first' / 'Registers' / 'P001-naming-register.xlsx')  # a picked absolute path
    picked = call('update-register', id='first', expected=kept, number='P-2', override=False, namingRegister=chosen)['register']
    assert picked['namingRegister'] == 'Registers\\P001-naming-register.xlsx'
    with pytest.raises(Refused):  # a picked file in another project
        elsewhere = str(tmp_path / 'second' / 'n.xlsx')
        call('update-register', id='first', expected=picked, number='P-2', override=False, namingRegister=elsewhere)
    kept = picked
    cleared = call('update-register', id='first', expected=kept, number='', override=False, namingRegister='', issuedRegister='')['register']
    assert cleared == legacy
    assert call('list')['roots'][1]['register'] == {'number': '', 'override': False}

def test_account_language_controls_inherit_and_drive_the_reply(tmp_path, monkeypatch):
    import pytest
    from nodelang import settings_owner as owner, session_files
    from nodelang.nograph_server import JsonFile
    settings = JsonFile(tmp_path / "settings.json", {})
    roots = JsonFile(tmp_path / "roots.json", {"roots":[]})
    document = session_files.new_document("Owner's English task name")
    scope = owner.PreferenceScope(settings, roots, document=document)
    monkeypatch.setattr(owner, "preference_scope", lambda document=None: scope)
    for label, value in (("App language", "Arabic"), ("Right-to-left layout", "Never"), ("Agents reply in", "Both")):
        identity = "Account." + label
        owner.preference_settings("setAppearance", [identity, value], settings)
        actual = next(row for row in owner.preference_settings(settings=settings)["appearanceSettings"] if row["id"] == identity)
        assert actual["value"] == value
    assert owner.agent_reply_language(document) == "Both"
    document["properties"]["settings"] = {"Account.Agents reply in":"Arabic"}
    assert owner.agent_reply_language(document) == "Arabic"
    assert document["title"] == "Owner's English task name"
    with pytest.raises(ValueError):
        owner.preference_settings("setAppearance", ["Account.Right-to-left layout", "bad"], settings)
