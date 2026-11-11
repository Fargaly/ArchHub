"""Render compiled Studio against real task files in a temporary profile."""
import json
import os
from pathlib import Path
import subprocess
import pytest

from test_task_session_roundtrip import _isolate, _Studio, _post


@pytest.mark.parametrize("board", ["home", "workshop", "canvas", "settings", "canvas_fit", "fluid_shell", "resume", "zero_home"])
def test_designbuild_board(tmp_path, monkeypatch, board):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer

    monkeypatch.setattr(NoGraphServer, "_probe_hosts", staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        if board != 'zero_home':
            task = client.workshop('createTask', 'Drawing set review')
            client.workshop('setTaskSession', task['taskId'], {
                'scope': 'Review and export the drawing set', 'rules': ['Review before export'],
                'agents': ['Drawing coordinator'], 'folders': ['Dated issue folder'],
                'references': ['Drawing index'], 'plan': ['Read sheet index', 'Review drawings', 'Export PDF'],
                'progress': {'Read sheet index': 'done', 'Review drawings': 'done'},
                'messages': [{'id':'review-complete','who':'Drawing coordinator','text':'Review is complete. The drawing index matches the reviewed set.'},{'id':'ask-export','who':'You','text':'What is holding up the export?'}],
            })
            if board in ('canvas', 'canvas_fit'):
                import copy
                from nodelang.session_files import catalogue
                items = {row['id']: row for row in catalogue()}
                nodes = [{'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                          'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}}
                         for key, item, x in [('list','n_list',0),('slice','s_slice',340),('count','s_count',680),('pdf','o_pdf_handoff',1020)]]
                if board == 'canvas_fit':
                    nodes = nodes[:2]
                nodes[0]['params']['value'] = '[10, 20, 30, 40, 50]'
                nodes[1]['params']['count'] = '3'
                view = client.workshop('openTaskGraph', task['taskId'])
                opened = client.files('read', path=view['path'], id=view['id'])
                opened['document']['nodes'] = nodes
                opened['document']['wires'] = [
                    {'id':'first','from':{'node':'list','socket':'value'},'to':{'node':'slice','socket':'items'}},
                    {'id':'second','from':{'node':'slice','socket':'items_out'},'to':{'node':'count','socket':'items'}}]
                if board == 'canvas_fit':
                    opened['document']['wires'] = opened['document']['wires'][:1]
                client.files('save', path=view['path'], document=opened['document'])
            for title in ['Sheet index check', 'Export issue package', 'Update drawing references', 'Model view audit']:
                client.workshop('createTask', title)
            client.workshop('openTaskGraph', task['taskId'])
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/designbuild.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token,
                              'browserCache': browser_cache, 'board': board,
                              'polish': os.environ.get('ARCHHUB_DESIGNPOLISH_PHASE', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
            encoding='utf-8', timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        if board in ('canvas_fit', 'fluid_shell', 'resume', 'zero_home') or os.environ.get('ARCHHUB_DESIGNPOLISH_PHASE'):
            return
        reopened = client.workshop('openTaskGraph', task['taskId'])
        assert reopened['scope'] == 'Review the current issue'
        assert reopened['rules'] == ['Review every sheet before export']
        assert reopened['references'] == ['Current drawing index']
        assert reopened['folders'] == ['Dated issue folder renamed']

    finally:
        client.close()
        server.close()


def test_designbuild_appearance_owner(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    (state / 'settings').mkdir(parents=True)
    owner = state / 'settings' / 'settings.json'
    owner.write_text(json.dumps({'homeLayout': {'inner': {'params': 30, 'main': 70}}}), encoding='utf8')
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        def setting(function, *args):
            return _post(client.connection, '/api/universal/settings-action', {'function': function, 'args': list(args)}, client.headers)
        status, body = setting('readControls')
        assert status == 200 and body['ok']
        rows = {row['id']: row for row in body['result']['appearanceSettings']}
        assert rows['Appearance.Inspector width']['value'] == 320
        assert rows['Appearance.Inspector width']['tokenId'] == 'layout.inspectorWidth'
        assert rows['Appearance.Row spacing']['value'] == 4
        status, body = setting('setAppearance', 'Appearance.Inspector width', 400)
        assert status == 200 and body['ok']
        saved = json.loads(owner.read_text(encoding='utf8'))
        assert saved['appearanceInspectorWidth'] == 400 and 'homeLayout' not in saved
        before = owner.read_bytes()
        for name, value in [('Inspector width', 481), ('Inspector width', True), ('Row spacing', -1), ('Node radius', 25), ('Node header colour', 'red')]:
            status, body = setting('setAppearance', 'Appearance.' + name, value)
            assert status >= 400 or body.get('ok') is False
            assert owner.read_bytes() == before
        layout = {'width': 300, 'collapsed': False, 'resume': 'kept-task', 'order': ['kept-task'], 'hidden': []}
        status, body = setting('setHomeLayout', layout)
        assert status == 200 and body['ok']
        status, body = setting('setAppearance', 'Appearance.Inspector width', 360)
        assert status == 200 and body['ok']
        assert json.loads(owner.read_text(encoding='utf8'))['homeLayout'] == layout
        before = owner.read_bytes()
        for patch in ({'width': True}, {'width': 239}, {'collapsed': 'yes'}, {'resume': '../outside'}, {'order': ['same', 'same']}, {'hidden': [7]}):
            status, body = setting('setHomeLayout', {**layout, **patch})
            assert status >= 400 or body.get('ok') is False
            assert owner.read_bytes() == before
        from concurrent.futures import ThreadPoolExecutor
        def edit_many(spec):
            name, start = spec
            peer = _Studio(server)
            try:
                for offset in range(16):
                    status, reply = _post(peer.connection, '/api/universal/settings-action',
                                          {'function':'setAppearance','args':['Appearance.'+name,start+offset]},peer.headers)
                    assert status == 200 and reply['ok']
            finally:
                peer.close()
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(edit_many,[('Inspector width',350),('Row spacing',0),('Node radius',0),('Text scale',100),('Default zoom',100)]))
        saved = json.loads(owner.read_text(encoding='utf8'))
        for key, value in [('appearanceInspectorWidth',365),('appearanceRowSpacing',15),('appearanceNodeRadius',15),('appearanceTextScale',115),('appearanceDefaultZoom',115)]:
            assert saved[key] == value
    finally:
        client.close()
        server.close()
