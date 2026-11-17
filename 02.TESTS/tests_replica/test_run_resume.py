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


def test_retry_after_reject_requires_fresh_approval_without_repeating_upstream(running):
    from nodelang.hook_decision import ask_reviews
    from nodelang.session_files import read_document

    path, counts, run = running
    paused = run()
    approve(paused, 'deny')
    rejected = read_document(path)
    assert rejected['nodes'][1]['result']['status'] == 'Declined'  # legacy saved status
    assert rejected['nodes'][1]['result']['display'] == 'Rejected'
    assert rejected['nodes'][2]['result']['status'] == 'Blocked'
    assert counts == {'one': 1, 'two': 0, 'three': 0}

    retry = run()
    cards = {card['id']: card for card in ask_reviews()}
    assert not retry['succeeded']
    assert retry['run']['id'] == paused['run']['id']
    assert retry['results']['two']['status'] == 'Waiting for approval'
    assert retry['approvalId'] != paused['approvalId']
    assert cards[paused['approvalId']]['status'] == 'declined'
    assert cards[retry['approvalId']]['status'] == 'pending'
    assert counts == {'one': 1, 'two': 0, 'three': 0}

    approve(retry)
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    assert run()['succeeded']
    assert counts == {'one': 1, 'two': 1, 'three': 1}


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
    from nodelang import session_files
    path, counts, _run = running
    recovery_path = path.parent / 'recovery.archhub'
    target = path.parent / 'recovered.txt'
    target.write_text('Already written', encoding='utf-8')
    recovery = session_files.new_document('Unconfirmed write')
    recovery['nodes'] = [{'id': 'uncertain', 'type': 'thing.file.write', 'title': 'Unconfirmed write',
                          'params': {'path': str(target), 'content': 'Already written'}, 'position': {'x': 0, 'y': 0}}]
    session_files.validate(recovery)
    node = recovery['nodes'][0]
    recovery['properties']['canvasRun'] = {'id': 'crashed-run', 'inputs': {'uncertain': session_files.input_signature(node, [], recovery_path)}}
    session_files.begin_attempt({'document': recovery, 'path': recovery_path, 'completed': {}}, node, node['params'], {})
    server = NoGraphServer(path.parent / 'server')
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(['node', str(Path(__file__).resolve().parents[1] / 'tests_js' / 'run_resume.test.cjs')],
                                input=json.dumps({'url': server.public_url + '/studio/?bootstrap=' + server.browser_bootstrap_token,
                                                  'path': str(path), 'recovery_path': str(recovery_path)}), capture_output=True, text=True, timeout=120,
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


def test_relative_file_reject_ends_run(tmp_path):
    from nodelang.session_files import SessionFiles, new_document, read_document
    doc = new_document('Reject portable write')
    doc['nodes'] = [
        {'id': 'write', 'type': 'thing.file.write', 'params': {'path': 'output.txt', 'content': 'value'}, 'position': {'x': 0, 'y': 0}},
        {'id': 'read', 'type': 'thing.file', 'params': {'path': ''}, 'position': {'x': 300, 'y': 0}}]
    doc['wires'] = [{'id': 'next', 'from': {'node': 'write', 'socket': 'path'}, 'to': {'node': 'read', 'socket': 'path'}}]
    path = tmp_path / 'reject.archhub'
    owner = SessionFiles(tmp_path / 'files')
    saved = owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})['document']
    approve(owner.dispatch({'action': 'run', 'path': str(path), 'document': saved}), 'deny')
    held = read_document(path)
    assert held['nodes'][0]['result']['display'] == 'Rejected'
    assert held['nodes'][1]['result']['status'] == 'Blocked'
    assert held['properties']['canvasRun']['state'] == 'Ended'
    assert not (tmp_path / 'output.txt').exists()


@pytest.mark.parametrize('change', ['run', 'upstream'])
def test_stale_approval_refused(running, change):
    from nodelang.session_files import read_document, write_document
    from nodelang import agent_work, hook_decision
    path, counts, run = running
    paused = run()
    # Retain the issued replay payload even if the one-shot owner withdraws its card.
    captured = []
    original = agent_work.request_approval
    def capture(*args, **kwargs):
        captured.append(copy.deepcopy(kwargs['continuation']))
        return original(*args, **kwargs)
    from unittest.mock import patch
    with patch.object(agent_work, 'request_approval', capture):
        run(again=True)
    continuation = captured[0]
    issued = read_document(path)
    payload = {'node': copy.deepcopy(issued['nodes'][1]), 'feeds': {}, 'continuation': continuation}
    if change == 'run':
        run(again=True)
    else:
        issued['nodes'][0]['params']['task'] = 'changed upstream'
        write_document(path, issued)
    token = hook_decision._RELEASING.set(True)
    try:
        with pytest.raises(ValueError, match='changed after this approval'):
            agent_work.release(payload)
    finally:
        hook_decision._RELEASING.reset(token)
    assert counts['two'] == 0
    assert paused['approvalId']


def test_crash_after_effect_before_outcome_is_unconfirmed(running):
    from nodelang.session_files import read_document
    path, counts, _run = running
    counter = path.parent / 'effect-count.txt'
    script = r'''
import sys, os, json
sys.path.insert(0, sys.argv[3])
from pathlib import Path
from nodelang import canvas_documents, session_files
counter = Path(sys.argv[2])
def effect(engine, params, feeds):
    counter.write_text(counter.read_text() + '1' if counter.exists() else '1')
    os._exit(91)
canvas_documents.run_thing = effect
owner = session_files.SessionFiles(Path(sys.argv[1]).parent / 'files')
opened = owner.dispatch({'action': 'open', 'path': sys.argv[1]})['document']
result = owner.dispatch({'action': 'run', 'path': sys.argv[1], 'document': opened})
print(json.dumps(result))
'''
    command = [sys.executable, '-c', script, str(path), str(counter), str(Path(__file__).resolve().parents[2] / '01.APP')]
    crashed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert crashed.returncode == 91, crashed.stderr
    assert counter.read_text() == '1'
    restarted = subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
    result = json.loads(restarted.stdout)
    assert counter.read_text() == '1'
    assert result['results']['one']['status'] == 'Unconfirmed'
    assert result['results']['two']['status'] == 'Blocked'
    assert result['results']['three']['status'] == 'Blocked'
    attempt = read_document(path)['properties']['canvasRun']['attempts']['one']
    assert attempt['nodeId'] == 'one' and attempt['inputSignature'] and attempt['runId']
    assert 'outcome' not in attempt
    assert counts == {'one': 0, 'two': 0, 'three': 0}


def test_linked_skill_concurrent_runs_execute_child_once(running, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from nodelang import session_files
    path, counts, _run = running
    child = session_files.read_document(path)
    child['nodes'][1]['approvalRequired'] = False
    session_files.write_document(path, child)
    parents = []
    for index in range(2):
        doc = session_files.new_document('Parent')
        canvas_documents_path = path.parent / ('parent%d.archhub' % index)
        session_files.insert_session(doc, str(path))
        session_files.write_document(canvas_documents_path, doc)
        parents.append(canvas_documents_path)
    def run(parent):
        owner = session_files.SessionFiles(parent.parent / 'files')
        return owner.dispatch({'action': 'run', 'path': str(parent), 'document': session_files.read_document(parent)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, parents))
    assert all(result['succeeded'] for result in results), results
    assert counts == {'one': 1, 'two': 1, 'three': 1}


def test_rejected_body_slow_trickle_has_total_deadline(running, monkeypatch):
    from email.message import Message
    from io import BytesIO
    from types import SimpleNamespace
    from nodelang import nograph_server
    path, _counts, _run = running
    server = nograph_server.NoGraphServer(path.parent / 'trickle-server')
    elapsed, budgets = [0.0], []
    class Trickle:
        def read1(self, length):
            elapsed[0] += 0.01
            return b'x'
    monkeypatch.setattr(nograph_server.time, 'monotonic', lambda: elapsed[0])
    try:
        handler = object.__new__(server._handler())
        handler.headers = Message()
        handler.headers['Content-Length'] = '1000000'
        handler.headers['Host'] = '127.0.0.1:' + str(server.port)
        handler.headers['X-ArchHub-Session'] = 'unknown'
        handler.path, handler.command = '/api/session-files', 'POST'
        handler.request_version, handler.requestline = 'HTTP/1.1', 'POST /api/session-files HTTP/1.1'
        handler.rfile, handler.wfile = Trickle(), BytesIO()
        handler.connection = SimpleNamespace(settimeout=budgets.append)
        handler.dispatch('POST')
        from nodelang.library_engines import LIBRARY_ITEM_ENGINES
        deadline = LIBRARY_ITEM_ENGINES['tool_workshop']['params']['worker_join_ms'] / 1000
        assert elapsed[0] <= deadline + 0.011
        assert budgets[-1] < budgets[0]
        assert handler.wfile.getvalue().startswith(b'HTTP/1.1 403')
    finally:
        server.httpd.server_close()


@pytest.mark.parametrize('decision', ['check', 'retry'])
def test_unconfirmed_file_requires_explicit_recovery(tmp_path, monkeypatch, decision):
    from nodelang import canvas_documents, session_files
    owner = session_files.SessionFiles(tmp_path / 'files')
    path, target = tmp_path / 'recover.archhub', tmp_path / 'output.txt'
    doc = session_files.new_document('Recover write')
    doc['nodes'] = [{'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(target), 'content': 'one\r\ntwo'}, 'position': {'x': 0, 'y': 0}}]
    saved = owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})['document']
    paused = owner.dispatch({'action': 'run', 'path': str(path), 'document': saved})
    effect, calls = canvas_documents.run_thing, []
    def crash(engine, params, feeds):
        calls.append(engine)
        effect(engine, params, feeds)
        raise SystemExit('crash before outcome')
    with monkeypatch.context() as fault:
        fault.setattr(canvas_documents, 'run_thing', crash)
        with pytest.raises(SystemExit, match='crash before outcome'):
            approve(paused)
    reopened = owner.dispatch({'action': 'open', 'path': str(path)})['document']
    assert reopened['nodes'][0]['result']['status'] == 'Unconfirmed'
    resumed = owner.dispatch({'action': 'run', 'path': str(path), 'document': reopened, 'again': True})
    assert resumed['results']['write']['status'] == 'Unconfirmed'
    assert calls == ['thing.file.write']
    if decision == 'check':
        target.write_text('different', encoding='utf-8')
        with pytest.raises(ValueError, match='does not match'):
            owner.dispatch({'action': 'recover-run', 'path': str(path), 'node': 'write', 'decision': decision})
        target.write_bytes(b'one\r\ntwo')
    recovered = owner.dispatch({'action': 'recover-run', 'path': str(path), 'node': 'write', 'decision': decision})
    ran = owner.dispatch({'action': 'run', 'path': str(path), 'document': recovered['document']})
    if decision == 'retry':
        assert ran['results']['write']['status'] == 'Waiting for approval'
        approve(ran)
    else:
        assert ran['succeeded']
    assert target.read_bytes() == b'one\r\ntwo'
    assert session_files.read_document(path)['nodes'][0]['result']['status'] == 'Done'


def test_retry_from_failed_node_reuses_upstream(running, monkeypatch):
    from nodelang import canvas_documents, session_files
    path, counts, run = running
    effect = canvas_documents.run_thing
    failing = {'three': True}
    def flaky(engine, params, feeds):
        if failing.get(params.get('agent')):
            raise ValueError('Third effect refused once')
        return effect(engine, params, feeds)
    monkeypatch.setattr(canvas_documents, 'run_thing', flaky)
    approve(run())
    held = session_files.read_document(path)
    assert held['nodes'][2]['result']['status'] == 'Error'
    assert counts == {'one': 1, 'two': 1, 'three': 0}
    failing['three'] = False
    retried = run()
    assert retried['succeeded']
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    assert retried['run']['id'] == held['properties']['canvasRun']['id']


def test_one_engine_for_run_button_agent_tool_and_trigger(running, monkeypatch):
    import asyncio
    from nodelang import session_files
    from nodelang.native_agent_mcp import build_server
    from nodelang.canvas_triggers import TriggerService
    path, counts, run = running
    callers = []
    engine = session_files.run_document
    def spy(*args, **kwargs):
        callers.append(sys._getframe(1).f_code.co_filename.rsplit(os.sep, 1)[-1])
        return engine(*args, **kwargs)
    monkeypatch.setattr(session_files, 'run_document', spy)
    server = build_server()
    paused = asyncio.run(server.call_tool('canvas.run', {'path': str(path)}))
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    waiting = session_files.read_document(path)['nodes'][1]['result']
    assert waiting['status'] == 'Waiting for approval'
    button = run()
    assert button['approvalId'] == waiting['output']['approvalId']
    approve(button)
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    asyncio.run(server.call_tool('canvas.run', {'path': str(path)}))
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    trigger = path.parent / 'triggered.archhub'
    items = {row['id']: row for row in session_files.catalogue()}
    doc = session_files.new_document('Triggered')
    doc['nodes'] = [
        {'id': 't', 'item': 'tr_schedule', 'type': items['tr_schedule']['engine'], 'title': 'Trigger',
             # Exercise immediate execution explicitly; default-on approval has its own regression.
             'params': {**copy.deepcopy(items['tr_schedule']['params']), 'every_seconds': '600', 'ask_before_running': False}, 'position': {'x': 0, 'y': 0}},
        {'id': 'c', 'item': 'data.convert', 'type': 'data.convert', 'title': 'Convert',
         'params': {'target_type': 'text'}, 'position': {'x': 300, 'y': 0}}]
    doc['wires'] = [{'id': 'w', 'from': {'node': 't', 'socket': 'payload'}, 'to': {'node': 'c', 'socket': 'in'}}]
    session_files.write_document(trigger, doc)
    service = TriggerService()
    try:
        assert service.fire((str(trigger), 't'), 'trigger.schedule')['outcome'] == 'ran'
    finally:
        service.close()
    assert set(callers) == {'canvas_tools.py', 'session_files.py', 'agent_work.py', 'canvas_triggers.py'}
    assert paused is not None


def test_run_budget_stops_deterministically_and_nothing_polls(running, monkeypatch):
    import threading
    import time
    from nodelang import canvas_documents, session_files
    path, counts, run = running
    effect = canvas_documents.run_thing
    def slow(engine, params, feeds):
        if params.get('agent') == 'one':
            time.sleep(0.2)
        return effect(engine, params, feeds)
    monkeypatch.setattr(canvas_documents, 'run_thing', slow)
    stopped = run(budget_s=0.05)
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    assert stopped['run']['budget_s'] == 0.05
    for key in ('two', 'three'):
        assert stopped['results'][key] == {'status': 'Stopped', 'output': {}, 'error': 'Run budget of 0.05 s reached before this step.'}
    held = session_files.read_document(path)
    assert held['properties']['canvasRun']['state'] == 'Ended'
    before = {thread.ident for thread in threading.enumerate()}
    paused = run()
    assert paused['run']['budget_s'] == sum(canvas_documents.BUDGET_DEFAULT['seconds'] for _ in range(3))
    assert {thread.ident for thread in threading.enumerate()} <= before
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    approve(paused)
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    with pytest.raises(ValueError, match='budget'):
        run(budget_s=-1)


def test_canvas_run_history_keeps_one_id_through_approval_and_reopen(running):
    from nodelang.session_files import read_document, read_runs, runs_path
    path, counts, run = running
    waiting = run()
    identity = read_document(path)['properties']['canvasRun']['id']
    history = read_runs(path)
    assert len(history) == 1 and history[0]['id'] == identity
    assert history[0]['state'] == 'waiting-for-approval'
    assert history[0]['approvalId'] == waiting['approvalId']
    assert counts == {'one': 1, 'two': 0, 'three': 0}
    approve(waiting)
    history = read_runs(path)
    assert len(history) == 1 and history[0]['id'] == identity
    assert history[0]['state'] == 'succeeded' and history[0]['trigger'] == 'manual'
    assert history[0].get('approvalId') is None and not history[0].get('error')
    assert counts == {'one': 1, 'two': 1, 'three': 1}
    lines = runs_path(path).read_bytes()
    read_document(path)
    assert runs_path(path).read_bytes() == lines
    for line in lines.decode('utf-8').splitlines():
        assert not {'results', 'outputs', 'attempts', 'document'} & json.loads(line).keys()


@pytest.mark.parametrize('decision, terminal, move', [
    ('approve', 'succeeded', False), ('deny', 'declined', False), ('approve', 'succeeded', True),
])
def test_automation_history_follows_effect_approval_on_the_same_run(tmp_path, monkeypatch, decision, terminal, move):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from nodelang import canvas_documents, session_files
    from nodelang.canvas_triggers import TriggerService
    from nodelang.hook_decision import ask_apply, ask_reviews

    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    path, output = tmp_path / 'scheduled-write.archhub', tmp_path / 'output.txt'
    document = session_files.new_document('Scheduled approval')
    document['nodes'] = [
        {'id': 't', 'type': 'trigger.schedule', 'item': 'tr_schedule',
         'params': {'every_seconds': '600', 'ask_before_running': False}, 'position': {'x': 0, 'y': 0}},
        {'id': 'c', 'type': 'data.convert', 'item': 'data.convert',
         'params': {'target_type': 'text'}, 'position': {'x': 300, 'y': 0}},
    ]
    document['wires'] = [{'id': 'convert', 'from': {'node': 't', 'socket': 'payload'},
                          'to': {'node': 'c', 'socket': 'in'}}]
    document['nodes'] += [
        {'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(output), 'content': 'approved'},
         'ports': {'source': [{'id': 'path', 'type': 'file'}], 'target': [{'id': 'content', 'type': 'string'}]},
         'position': {'x': 600, 'y': 0}},
        {'id': 'unused', 'type': 'trigger.schedule', 'params': {'armed': False}, 'position': {'x': 0, 'y': 200}},
    ]
    document['wires'].append({'id': 'writer', 'from': {'node': 'c', 'socket': 'out'},
                              'to': {'node': 'write', 'socket': 'content'}})
    session_files.write_document(path, document)
    service = TriggerService()
    monkeypatch.setattr(service, '_post', lambda *args: {})
    ready, release = Event(), Event()
    history = service._history
    pending = {}

    def hold_history(key, entry):
        if entry['state'] == 'waiting-for-approval':
            pending.update(entry)
            ready.set()
            assert release.wait(5)
        history(key, entry)

    monkeypatch.setattr(service, '_history', hold_history)
    try:
        with ThreadPoolExecutor(max_workers=2) as jobs:
            scheduled = jobs.submit(service.fire, (str(path), 't'), 'trigger.schedule')
            try:
                assert ready.wait(5) and not output.exists()
                key = str(canvas_documents._lock_path(path))
                assert canvas_documents._THREAD_LOCKS[key].locked()
                card = next(row for row in ask_reviews() if row['id'] == pending['approvalId'])
                if not move:
                    effect = jobs.submit(ask_apply, card['id'], card['input_digest'], decision)
            finally:
                release.set()
            assert scheduled.result(timeout=5)['outcome'] == 'ran'
            if move:
                def rearrange(document):
                    document['nodes'][0]['position'] = {'x': 96, 'y': 24}
                    return []
                canvas_documents.edit(path, 'Canvas', 'arrange', rearrange, solve_changed=False)
                ask_apply(card['id'], card['input_digest'], decision)
            else:
                effect.result(timeout=5)
        saved = session_files.read_document(path)
        if move:
            assert saved['nodes'][0]['position'] == {'x': 96, 'y': 24}
        finished = session_files.last_automation_runs(path, saved['id'])['t']
        assert finished['id'] == pending['id'] and finished['kind'] == 'trigger.schedule'
        assert finished['state'] == terminal and finished['end'] >= pending['start']
        assert output.is_file() == (decision == 'approve')
        assert session_files.read_runs(path)[-1] == finished
    finally:
        service.close()
