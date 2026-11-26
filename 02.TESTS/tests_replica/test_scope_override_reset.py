"""A session that holds its own Theme shows Reset even when that value is the factory default; Reset inherits the workspace.

Founder-verified defect on installed 75f10a3: workspace Theme Light, session Theme saved Dark, scope Session -> no Reset.
"""
from types import SimpleNamespace


def test_session_override_equal_to_default_is_owned_and_reset_inherits_the_workspace(tmp_path, monkeypatch):
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR', 'WORKSHOP_STATE_DIR'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    from nodelang import session_files as files
    from nodelang.nograph_server import JsonFile, r_settings_action
    from nodelang.user_paths import state_directory
    prefs = JsonFile(state_directory() / 'settings/settings.json', {})
    roots = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []})
    work = tmp_path / 'project'
    work.mkdir()
    roots.write({'roots': [{'root_id': 'tower', 'label': 'Tower', 'path': str(work), 'settings': {}}]})
    doc = files.new_document('Override probe')
    doc['properties']['project'] = 'tower'
    path = files.document_path(files.sessions_directory(), doc)
    files.write_document(path, doc)
    files.SessionFiles().dispatch({'action': 'open', 'path': str(path)})
    owner = SimpleNamespace(files={'settings': prefs, 'workspaces': roots, 'companion': JsonFile(tmp_path / 'companion.json', {})})
    view = {}

    def call(function, *args):
        result = r_settings_action(owner, SimpleNamespace(body={'function': function, 'args': list(args), 'context': {
            'session': doc['id'], 'settingsDestination': view.get('settingsDestination')}}))['result']
        if 'settingsDestination' in result:
            view.update(result)
        return result

    def theme(result):
        return next(row for row in result['appearanceSettings'] if row['id'] == 'Appearance.Theme')

    call('readPreferences')
    call('setSettingsScope', 'Workspace', 'tower', doc['id'])
    assert theme(call('setAppearance', 'Appearance.Theme', 'Light'))['value'] == 'Light'
    call('setSettingsScope', 'Session', 'tower', doc['id'])
    inherited = theme(call('readPreferences'))
    assert inherited['value'] == 'Light' and inherited['scopeOwned'] is False, 'an inherited value has no Reset'
    default = inherited['default']
    owned = theme(call('setAppearance', 'Appearance.Theme', default))
    assert owned['value'] == default and owned['scopeOwned'] is True, 'the session override equal to the default must show Reset'
    back = theme(call('resetAppearance', 'Appearance.Theme'))
    assert back['value'] == 'Light' and back['scopeOwned'] is False, 'Reset removes the override and inherits the workspace'
    assert 'Appearance.Theme' not in (files.read_document(path)['properties'].get('settings') or {})
