"""F10 in the live app: Rerun and Fork are one click from the node's Properties (the Inspector reached through
Node > Open properties) and from the node menu, through the same command owner (window.UI.nodeCommand).

Rendered in the compiled Studio over a seeded isolated server, with real clicks: Rerun posts again=true and the node
shows its result; Fork adds the fork, and it is still there after a reload.
"""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_properties_rerun_and_fork_are_real_clicks_on_the_rendered_inspector(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '') or subprocess.check_output(
        ['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        task = client.workshop('createTask', 'Rerun and fork')['taskId']
        view = client.workshop('openTaskGraph', task)
        opened = client.files('read', path=view['path'], id=view['id'])
        opened['document']['nodes'] = [*opened['document']['nodes'], *[
            {'id': node, 'type': 'data.convert', 'item': 'data.convert', 'title': node, 'params': {'target_type': 'text'},
             'position': {'x': 600 + i * 300, 'y': 40}} for i, node in enumerate(('source', 'end'))],
            {'id': 'middle', 'type': 'data.constant', 'item': 'n_number', 'title': 'middle', 'params': {'value': 31},
             'position': {'x': 750, 'y': 300}}]
        opened['document']['wires'] = []
        client.files('save', path=view['path'], document=opened['document'])
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/properties_rerun_fork_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'file': view['path']}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout, result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.split('RERUNFORK ', 1)[1])
        assert [row['again'] for row in report['reruns']] == [True, True], report  # node menu, then Properties
        assert all(row['root'] == 'middle' and row['status'] in ('Done', 'Solved') for row in report['reruns']), report
        assert report['forked'] and report['forked'] not in report['before'], report
        assert report['forked'] in report['reopened'], 'the fork did not survive a reload'
        saved = {n['id'] for n in client.files('read', path=view['path'], id=view['id'])['document']['nodes']}
        assert report['forked'] in saved, 'the fork is not in the file'
    finally:
        client.close()
        server.close()
