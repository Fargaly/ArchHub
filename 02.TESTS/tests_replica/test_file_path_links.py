"""Saved File-to-path wires reopen and are admitted again by API and Studio."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import threading

import test_node_params as fixtures

profile = fixtures.profile


def consultant(profile):
    from nodelang.session_files import catalogue, new_document
    items = {row['id']: row for row in catalogue()}
    document = new_document('Consultant path links')
    for i in range(2):
        source = profile / ('input-%d.txt' % i)
        source.write_text('consultant input %d' % i, encoding='utf-8')
        for key, item in [('file%d' % i, 'param.value'), ('read%d' % i, 'thing:file')]:
            row = items[item]
            params = {'type': 'file', 'value': str(source)} if item == 'param.value' else copy.deepcopy(row['params'])
            document['nodes'].append({'id': key, 'type': row['engine'], 'item': item, 'title': key,
                'params': params, 'paramDefs': copy.deepcopy(row['paramDefs']), 'position': {'x': i*300, 'y': 0}})
        document['wires'].append({'id': 'w0%d' % i, 'from': {'node': 'file%d' % i, 'socket': 'value'},
                                  'to': {'node': 'read%d' % i, 'socket': 'path'}})
    return document


def test_saved_links_reopen_and_shared_api_rewire(profile):
    from nodelang.native_agent_mcp import build_server
    from nodelang.node_params import compatible
    from nodelang.session_files import SessionFiles, read_document, write_document
    path = profile / 'Consultant path links.archhub'
    document = consultant(profile)
    write_document(path, document)
    opened = SessionFiles(profile / 'sessions').dispatch({'action': 'open', 'path': str(path)})['document']
    assert opened['wires'] == document['wires']
    for i in range(2):
        assert next(n for n in opened['nodes'] if n['id'] == 'read%d' % i)['result']['output']['text'] == 'consultant input %d' % i
    server = build_server()
    for i in range(2):
        asyncio.run(server.call_tool('canvas.wire', {'path': str(path), 'source': 'file%d.value' % i, 'target': 'read%d.path' % i}))
    assert len(read_document(path)['wires']) == 2
    assert compatible('file', 'string', 'path')
    assert compatible('file', 'path') and compatible('path', 'file')
    assert not compatible('file', 'string', 'prompt')
    assert not compatible('number', 'string', 'path')
    print('FILE->PATH shared API: saved w00/w01 reopen; both re-wire; unrelated mismatches refused')


def test_file_path_links_compiled_studio(profile):
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import write_document
    path = profile / 'Consultant path links.archhub'
    write_document(path, consultant(profile))
    server = NoGraphServer(profile / 'server')
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).parents[1] / 'tests_js/file_path_links.mjs')],
            input=json.dumps({'url': server.public_url+'/studio/?bootstrap='+server.browser_bootstrap_token, 'path': str(path)}),
            text=True, encoding='utf-8', capture_output=True, timeout=120, env=os.environ.copy(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stderr
    finally:
        server.close()
