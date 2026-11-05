"""Settings nodes keep a binding, and read/write the real Settings owner."""
import json
import os
from pathlib import Path
import subprocess
import threading

import test_node_params as fixtures

profile = fixtures.profile


def test_settings_binding_after_reopen(profile):
    from nodelang.nograph_server import NoGraphServer, _create_task
    from nodelang.session_files import profile_directory, read_document
    server = NoGraphServer(profile_directory())
    task = _create_task(server, 'Settings bridge test')
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).parents[1] / 'tests_js/settings_node_bridge.mjs')],
            input=json.dumps({'url': server.public_url+'/studio/?bootstrap='+server.browser_bootstrap_token}),
            text=True, encoding='utf-8', capture_output=True, timeout=120, env=os.environ.copy(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        settings = json.loads((server.settings_dir / 'settings.json').read_text(encoding='utf-8'))
        assert settings['appearanceTextScale'] == 130
        from nodelang.workshop_mailbox import application_history
        from nodelang.workshop_tasks import open_session
        with application_history() as history:
            path = open_session(history, task['taskId'])['path']
        document = read_document(path)
        assert document['nodes']
        bindings = [n for n in document['nodes'] if n['type'] == 'thing.setting']
        assert bindings and all(set(n['params']) == {'setting'} for n in bindings)
    finally:
        server.close()


def test_shared_node_parameter_writes_same_settings_owner(profile):
    import pytest
    from nodelang.node_params import set_value
    from nodelang.settings_owner import SettingsOwner, appearance_settings
    nodes = SettingsOwner.exposeSettingsPage('Appearance')['nodes']
    node = next(n for n in nodes if n['params']['setting'] == 'Appearance.Text scale')
    document = {'nodes': nodes, 'wires': []}
    set_value(document, node['id'], 'value', '120')
    row = next(r for r in appearance_settings()['appearanceSettings'] if r['id'] == 'Appearance.Text scale')
    assert row['value'] == 120 and node['params'] == {'setting': 'Appearance.Text scale'}
    with pytest.raises(ValueError):
        set_value(document, node['id'], 'value', '120.5')
    with pytest.raises(ValueError, match='outside max 150'):
        set_value(document, node['id'], 'value', '999')


def test_settings_edit_has_no_empty_document_undo_and_stale_id_is_visible(profile):
    import pytest
    from nodelang import canvas_documents
    from nodelang.node_params import set_value
    from nodelang.session_files import new_document, read_document, write_document
    from nodelang.settings_owner import SettingsOwner
    document = new_document('Settings history')
    document['nodes'] = SettingsOwner.exposeSettingsPage('Appearance')['nodes']
    path = profile / 'settings.archhub'
    write_document(path, document)
    node = next(n for n in document['nodes'] if n['params']['setting'] == 'Appearance.Text scale')
    before = path.read_bytes()
    result, solved = canvas_documents.edit(path, 'agent', 'set setting', lambda d: set_value(d, node['id'], 'value', '120'))
    assert path.read_bytes() == before
    assert canvas_documents.revision(result) == canvas_documents.revision(read_document(path)) == 0
    assert solved['results'][node['id']]['output']['value'] == 120
    node['params']['setting'] = 'Appearance.Removed'
    with pytest.raises(ValueError, match='no longer exists'):
        set_value(document, node['id'], 'value', '130')
