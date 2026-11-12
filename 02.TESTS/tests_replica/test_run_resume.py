"""F329: the existing file owner retains one run across approvals and reopen."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest


@pytest.fixture
def running(tmp_path, monkeypatch):
    from nodelang import canvas_documents, session_files
    from nodelang import enforce
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    counts = dict.fromkeys(('one', 'two', 'three'), 0)
    original = canvas_documents.run_thing
    def effect(engine, params, feeds):
        if engine != 'thing.agent':
            return original(engine, params, feeds)
        key = params['agent']
        counts[key] += 1
        return {'result': counts[key]}, key
    monkeypatch.setattr(canvas_documents, 'run_thing', effect)
    monkeypatch.setattr(enforce, 'guard_effect', lambda *args: None)
    document = session_files.new_document('Counting effects')
    document['nodes'] = [
        {'id': key, 'type': 'thing.agent', 'params': {'agent': key, 'task': ''},
         'position': {'x': i * 300, 'y': 0}, 'approvalRequired': key == 'two'}
        for i, key in enumerate(counts)]
    document['wires'] = [
        {'id': a + b, 'from': {'node': a, 'socket': 'result'}, 'to': {'node': b, 'socket': 'task'}}
        for a, b in (('one', 'two'), ('two', 'three'))]
    path = tmp_path / 'count.archhub'
    session_files.write_document(path, document)
    owner = session_files.SessionFiles(tmp_path / 'files')
    def run(**values):
        return owner.dispatch({'action': 'run', 'path': str(path),
                               'document': session_files.read_document(path), **values})
    return path, counts, run


def approve(result, decision='approve'):
    from nodelang.hook_decision import ask_apply, ask_reviews
    card = next(c for c in ask_reviews() if c['id'] == result['approvalId'])
    return ask_apply(card['id'], card['input_digest'], decision)


def test_resume_reopen_incremental_and_run_all_again(running):
    from nodelang import canvas_documents, session_files
    path, counts, run = running
    paused = run()
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    assert paused['results']['two']['status'] == 'Waiting for approval'
    assert paused['results']['three']['status'] == 'Waiting'
    reopened = session_files.SessionFiles(path.parent / 'files').dispatch({'action': 'open', 'path': str(path)})
    assert reopened['document']['nodes'][1]['result']['status'] == 'Waiting for approval'
    assert run()['approvalId'] == paused['approvalId']
    approve(paused)
    approve(paused)
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    assert run()['succeeded']
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    def change(document):
        document['nodes'][2]['params']['task'] = 'Changed third input'
        return ['three']
    canvas_documents.edit(path, 'test', 'change third', change)
    assert run()['succeeded']
    assert counts == {'one': 1, 'two': 1, 'three': 2}
    fresh = run(again=True)
    assert counts == {'one': 2, 'two': 1, 'three': 2}
    approve(fresh)
    assert counts == {'one': 2, 'two': 2, 'three': 3}


def test_reject_is_terminal_and_does_not_repeat(running):
    from nodelang.session_files import read_document
    path, counts, run = running
    approve(run(), 'deny')
    rejected = read_document(path)
    assert rejected['nodes'][1]['result']['status'] == 'Declined'  # legacy saved status
    assert rejected['nodes'][1]['result']['display'] == 'Rejected'
    assert rejected['nodes'][2]['result']['status'] == 'Blocked'
    assert not run()['succeeded']
    assert counts == {'one': 1, 'two': 0, 'three': 0}


def test_cycle_refused_before_effect_and_input_change_detected(running):
    from nodelang import session_files
    path, counts, run = running
    document = session_files.read_document(path)
    cycle = copy.deepcopy(document)
    cycle['wires'].append({'id': 'loop', 'from': {'node': 'three', 'socket': 'result'},
                           'to': {'node': 'one', 'socket': 'task'}})
    with pytest.raises(ValueError, match='Cycle'):
        session_files.run_document(cycle)
    assert counts == {'one': 0, 'two': 0, 'three': 0}
    approve(run())
    document = session_files.read_document(path)
    document['nodes'][2]['params']['task'] = 'changed without solve'
    session_files.write_document(path, document)
    run()
    assert counts == {'one': 1, 'two': 1, 'three': 2}


def test_process_restart_reads_pause_without_running(running):
    path, counts, run = running
    paused = run()
    script = """
import json, sys
sys.path.insert(0, sys.argv[3])
from nodelang.session_files import SessionFiles
owner = SessionFiles(sys.argv[2])
opened = owner.dispatch({'action': 'open', 'path': sys.argv[1]})['document']
assert opened['nodes'][1]['result']['status'] == 'Waiting for approval'
result = owner.dispatch({'action': 'run', 'path': sys.argv[1], 'document': opened})
print(json.dumps({'approvalId': result['approvalId'], 'results': result['results']}))
"""
    child = subprocess.run([sys.executable, '-c', script, str(path), str(path.parent / 'files'),
                            str(Path(__file__).resolve().parents[2] / '01.APP')],
                           capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(child.stdout)['approvalId'] == paused['approvalId']
    assert counts == {'one': 1, 'two': 0, 'three': 0}


def test_failure_keeps_error_and_blocks_downstream(running, monkeypatch):
    from nodelang import canvas_documents, session_files
    path, counts, run = running
    effect = canvas_documents.run_thing
    def failed(engine, params, feeds):
        if params.get('agent') == 'two':
            raise ValueError('Counting effect refused')
        return effect(engine, params, feeds)
    monkeypatch.setattr(canvas_documents, 'run_thing', failed)
    approve(run())
    document = session_files.read_document(path)
    assert document['nodes'][1]['result']['status'] == 'Error'
    assert document['nodes'][1]['result']['error'] == 'Counting effect refused'
    assert document['nodes'][2]['result']['status'] == 'Blocked'
    run()
    assert counts == {'one': 1, 'two': 0, 'three': 0}


def test_edit_while_waiting_replaces_card_without_repeating_success(running):
    from nodelang.session_files import read_document, write_document
    path, counts, run = running
    paused = run()
    changed = read_document(path)
    changed['nodes'][2]['params']['task'] = 'new tail'
    write_document(path, changed)
    resumed = run()
    assert resumed['approvalId'] != paused['approvalId']
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    approve(resumed)
    assert counts == {'one': 1, 'two': 1, 'three': 1}


def test_upstream_parameter_only_invalidates_third_effect(running):
    from nodelang import canvas_documents, session_files
    path, counts, run = running
    document = session_files.read_document(path)
    document['nodes'].append({'id': 'tail-input', 'type': 'param.value',
                              'params': {'type': 'integer', 'value': 1}, 'position': {'x': 300, 'y': 300}})
    document['nodes'][2]['paramDefs'] = [{'id': 'tail', 'name': 'Tail', 'type': 'integer'}]
    document['nodes'][2]['params']['tail'] = 0
    document['wires'].append({'id': 'tail-wire', 'from': {'node': 'tail-input', 'socket': 'value'},
                              'to': {'node': 'three', 'socket': 'param:tail'}})
    session_files.write_document(path, document)
    approve(run())
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    def change(document):
        document['nodes'][3]['params']['value'] = 2
        return ['tail-input']
    changed, _ = canvas_documents.edit(path, 'test', 'change upstream tail parameter', change)
    assert [n['result']['status'] for n in changed['nodes'][:3]] == ['Done', 'Done', 'Out of date']
    assert run()['succeeded']
    assert counts == {'one': 1, 'two': 1, 'three': 2}


def test_compiled_browser_uses_same_run_and_existing_approve_card(running):
    from nodelang.nograph_server import NoGraphServer
    path, counts, _run = running
    server = NoGraphServer(path.parent / 'server')
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).resolve().parents[1] / 'tests_js' / 'run_resume.test.cjs')],
                                input=json.dumps({'url': server.public_url + '/studio/?bootstrap=' + server.browser_bootstrap_token,
                                                  'path': str(path)}), capture_output=True, text=True, timeout=120,
                                env=os.environ.copy(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        assert counts == {'one': 2, 'two': 2, 'three': 3}
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
        thread.join(5)


@pytest.mark.parametrize('length, consumed', [(22, 22), (9 * 1024 * 1024 + 1, 0), (-1, 0), ('invalid', 0)])
def test_rejected_post_consumes_bounded_body_before_closing(running, length, consumed):
    from email.message import Message
    from io import BytesIO
    from types import SimpleNamespace
    from nodelang.nograph_server import NoGraphServer
    path, _counts, _run = running
    server = NoGraphServer(path.parent / 'refused-server')
    try:
        handler = object.__new__(server._handler())
        raw = b'{"action":"catalogue"}'
        handler.headers = Message()
        handler.headers['Host'] = '127.0.0.1:' + str(server.port)
        handler.headers['Content-Length'] = str(length)
        handler.headers['X-ArchHub-Session'] = 'unknown'
        handler.path = '/api/session-files'
        handler.command = 'POST'
        handler.request_version = 'HTTP/1.1'
        handler.requestline = 'POST /api/session-files HTTP/1.1'
        handler.rfile, handler.wfile = BytesIO(raw), BytesIO()
        handler.connection = SimpleNamespace(settimeout=lambda seconds: None)
        handler.close_connection = False
        handler.dispatch('POST')
        assert handler.wfile.getvalue().startswith(b'HTTP/1.1 403')
        assert handler.rfile.tell() == consumed
        assert handler.close_connection
    finally:
        server.httpd.server_close()
