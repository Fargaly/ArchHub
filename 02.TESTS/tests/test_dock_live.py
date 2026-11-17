"""The Canvas dock: its layout owner over the real route, and the compiled Studio on a seeded temporary Workshop."""
import json

from test_task_session_roundtrip import _isolate, _Studio, _post

LAYOUT = {
    'left': {'w': 268, 'c': False, 'st': [
        {'p': ['workshop'], 'a': 'workshop', 'h': 1.15, 'c': False},
        {'p': ['library'], 'a': 'library', 'h': 1, 'c': True}]},
    'right': {'c': False, 'st': [
        {'p': ['map'], 'a': 'map', 'h': 1, 'c': False},
        {'p': ['insp'], 'a': 'insp', 'h': 1, 'c': False}]},
}


def test_dock_layout_owner_over_the_settings_route(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    owner = state / 'settings' / 'settings.json'
    try:
        def setting(function, *args):
            return _post(client.connection, '/api/universal/settings-action', {'function': function, 'args': list(args)}, client.headers)
        status, body = setting('readDockLayout')
        assert status == 200 and body['result']['dockLayout'] == {'sessions': {}, 'projects': {}}
        status, body = setting('setDockLayout', 'task-a', 'studio', LAYOUT)
        assert status == 200 and body['ok']
        assert body['result']['dockLayout'] == {'sessions': {'task-a': LAYOUT}, 'projects': {'studio': LAYOUT}}
        assert json.loads(owner.read_text(encoding='utf8'))['dockLayout']['sessions']['task-a'] == LAYOUT
        # A second session of the same project starts from the project's last layout; a session without a project keeps its own.
        other = {**LAYOUT, 'left': {**LAYOUT['left'], 'w': 300}}
        assert setting('setDockLayout', 'task-b', '', other)[1]['result']['dockLayout']['projects'] == {'studio': LAYOUT}
        # The boot read carries the same record, so a reload restores the layout.
        assert setting('readControls')[1]['result']['dockLayout']['sessions'] == {'task-a': LAYOUT, 'task-b': other}
        before = owner.read_bytes()
        slot = LAYOUT['right']['st'][0]
        for bad in (
                {'left': LAYOUT['left']},
                {**LAYOUT, 'left': {**LAYOUT['left'], 'w': 199}},
                {**LAYOUT, 'left': {**LAYOUT['left'], 'w': True}},
                {**LAYOUT, 'right': {**LAYOUT['right'], 'w': 320}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'p': ['map', 'workshop']}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'p': ['chat'], 'a': 'chat'}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'a': 'insp'}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'h': 0}]}},
                {**LAYOUT, 'right': {'c': 'yes', 'st': []}}):
            status, body = setting('setDockLayout', 'task-a', 'studio', bad)
            assert status >= 400 or body.get('ok') is False, bad
            assert owner.read_bytes() == before
        status, body = setting('setDockLayout', '../outside', '', LAYOUT)
        assert (status >= 400 or body.get('ok') is False) and owner.read_bytes() == before
        # Reset: the session and its project go back to the default (no stored record).
        status, body = setting('setDockLayout', 'task-a', 'studio', None)
        assert status == 200 and body['result']['dockLayout'] == {'sessions': {'task-b': other}, 'projects': {}}
    finally:
        client.close()
        server.close()
