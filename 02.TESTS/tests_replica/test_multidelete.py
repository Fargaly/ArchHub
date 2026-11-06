"""Selection deletion is one undoable edit in the compiled Studio."""
import json
import os
from pathlib import Path
import subprocess
import threading

import test_canvas_parametric as fixtures

profile = fixtures.profile
workflow = fixtures.workflow


def test_multidelete_one_rendered_undo(profile):
    from nodelang.nograph_server import NoGraphServer, _create_task
    from nodelang.workshop_tasks import open_session
    from nodelang.workshop_mailbox import application_history
    from nodelang.session_files import read_document, write_document
    path = profile / 'delete.archhub'
    write_document(path, workflow())
    server = NoGraphServer(profile / 'server')
    task = _create_task(server, 'Multi-delete test')
    with application_history() as history:
        opened = open_session(history, task['taskId'])
    path = Path(opened['path'])
    document = read_document(path)
    document.update({key: value for key, value in workflow().items() if key in ('nodes', 'wires')})
    write_document(path, document)
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).parents[1] / 'tests_js/multidelete.mjs')],
            input=json.dumps({'url': server.public_url+'/studio/?bootstrap='+server.browser_bootstrap_token, 'path': str(path)}),
            text=True, encoding='utf-8', capture_output=True, timeout=120, env=os.environ.copy(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stderr
    finally:
        server.close()
