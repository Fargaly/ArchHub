"""R28: the Session card's Parameters, Tools and Context are the session node's own typed values, with sockets.

Design: archhub-directions app.js ensurePins (Parameters / Tools / Context panels, each a typed parameter list with
output sockets) and sessTabHTML (the Inspector's Session group). One owner each: the values live on the session
node in the .archhub file; Permissions stays the Settings permissions owner.
"""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_a_new_session_carries_its_panel_values_and_their_sockets(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import canvas_documents
    from nodelang.session_files import read_document
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create, open_session

    with application_history() as history:
        task = create(history, 'Sheet set review', 'founder')['id']
        opened = open_session(history, task)
    document = read_document(opened['path'])
    session = next(node for node in document['nodes'] if node['id'] == 'start')
    groups = {d['id']: d['group'] for d in session['paramDefs']}
    assert groups == {'run_budget': 'Parameters', 'prefer_no_agent': 'Parameters', 'reply_in': 'Parameters',
                      'tools_off': 'Tools', 'brief': 'Context', 'project_folder': 'Context', 'standard': 'Context',
                      'read_only_agents': 'Session'}
    assert session['params']['run_budget'] == 'Node budgets' and session['params']['prefer_no_agent'] is True
    outs = {port['id'] for port in session['ports']['source']}
    assert {'parameters', 'tools', 'context', 'project folder', 'standard'} <= outs
    # Every value is a parameter, so every value is also an input socket (param:<id>), typed by its parameter.
    assert all(d['type'] in ('choice', 'bool', 'list', 'text', 'folder') for d in session['paramDefs'])
    assert not any('token' in d['id'].split('_') for d in session['paramDefs'])  # session_files refuses credential-like keys
    assert canvas_documents.THING_ENGINES['thing.session']['pure'] is True


def test_the_session_engine_puts_each_panel_on_its_socket():
    from nodelang.canvas_documents import _run_session
    produced, _display = _run_session({'value': 'Sheet set review', 'workspace': 'Demo Block', 'run_budget': '5 minutes',
                                       'tools_off': ['Bluebeam'], 'brief': 'Issue for tender', 'project_folder': r'C:\\work\\demo',
                                       'read_only_agents': ['Codex']}, {})
    assert produced['parameters'] == {'run_budget': '5 minutes', 'prefer_no_agent': True, 'reply_in': 'English',
                                      'workspace': 'Demo Block', 'read_only_agents': ['Codex']}
    assert produced['tools'] == {'off': ['Bluebeam']}
    assert produced['context'] == {'brief': 'Issue for tender', 'project_folder': r'C:\\work\\demo',
                                   'standard': 'Office standard, current'}
    assert produced['project folder'] == r'C:\\work\\demo' and produced['standard'] == 'Office standard, current'
    # A file from before these values runs with their defaults.
    older, _ = _run_session({'value': 'Old task', 'workspace': ''}, {})
    assert older['parameters']['run_budget'] == 'Node budgets' and older['tools'] == {'off': []}


def test_the_library_session_card_declares_the_values_a_file_gets_at_its_first_edit():
    from nodelang.canvas_documents import session_param_defs, thing_items
    card = next(item for item in thing_items() if item['id'] == 'thing:session')
    assert card['paramDefs'] == session_param_defs()
    assert {d['id'] for d in card['paramDefs']} <= set(card['params'])


def test_an_agent_joining_the_session_gets_its_context_and_reply_language(tmp_path, monkeypatch):
    """Session card > Parameters > Reply in acts: the join handover every agent gets says which language to reply in."""
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.session_files import read_document, write_document
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create, handover, open_session

    with application_history() as history:
        task = create(history, 'Tender drawings', 'founder')['id']
        path = open_session(history, task)['path']
    document = read_document(path)
    next(n for n in document['nodes'] if n['id'] == 'start')['params'].update(
        reply_in='Arabic', brief='Issue for tender', standard='Office standard, previous')
    write_document(path, document)
    with application_history() as history:
        joined = handover(history, task)
    assert joined['context'] == {'brief': 'Issue for tender', 'project_folder': '', 'standard': 'Office standard, previous',
                                 'reply_in': 'Arabic'}
    assert joined['instructions'] == 'Reply in Arabic in this session.'


def test_the_session_card_and_inspector_rendered_with_real_edits_that_act(tmp_path, monkeypatch):
    """Rendered: every async panel shows waiting, error -> Retry, empty and loaded; the card's edits reach the file and
    survive a reload; Permissions reads back from its owner; the Revit tool turned off on the card is refused for that
    session's agent; the 1 minute run budget set on the card stops a run."""
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '') or subprocess.check_output(
        ['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import hook_decision, session_files
    from nodelang.nograph_server import NoGraphServer
    from nodelang.workshop_mailbox import application_history

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: [
        {'id': 'revit', 'name': 'Revit', 'state': 'connected', 'drive': True, 'detail': ''}]))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        task = client.workshop('createTask', 'Tender drawings')['taskId']
        view = client.workshop('openTaskGraph', task)
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/session_properties_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'file': view['path']}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=300,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout, result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.split('SESSIONPROPS ', 1)[1])
        assert report['permissions'] == ['error', 'waiting', 'loaded', 'empty'], report
        assert report['session'] == ['error', 'waiting', 'loaded', 'empty'], report
        assert report['permissionOwner'] == 'Accept edits'
        assert hook_decision.read_permissions()['runMode'] == 'Accept edits', 'the card wrote the Settings owner'
        edited = {'run_budget': '1 minute', 'brief': 'Issue for tender', 'tools_off': ['revit']}
        assert {key: report['edits'][key] for key in edited} == edited and report['edits']['defs'] >= 7, report['edits']
        assert {key: report['reopened'][key] for key in edited} == edited, 'the values did not survive a reload'
        assert {'session.socket.parameters', 'session.socket.tools', 'session.socket.context'} <= set(report['sockets'])
        document = session_files.read_document(view['path'])
        start = next(n for n in document['nodes'] if n['id'] == 'start')
        assert {key: start['params'][key] for key in edited} == edited, 'the file does not hold the card values'

        # Tools > Revit off acts: this session's agent may not call Revit; the same call outside the session may.
        record = {'root': 'root-live', 'session': 'identity-live', 'native_session_id': 'native-live', 'runtime': 'codex',
                  'work': task, 'status': 'working', 'display_name': 'Codex', 'agent': 'Codex', 'request_id': 'r1',
                  'pid': 999999, 'created_at': 0}
        with application_history() as history:
            with history._transaction(write=True):
                history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                                    "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
                history._db.execute("INSERT INTO workshop_declarations VALUES(?,?)", (record['root'], json.dumps(record)))
        call = {'tool_name': 'revit_execute_csharp', 'tool_input': {'code': 'return 1;'}}
        refused = hook_decision.decide({**call, 'session_id': 'native-live'})
        assert refused['verdict'] == 'refuse' and 'session-setting' in refused['rules'], refused
        assert 'session-setting' not in hook_decision.decide({**call, 'session_id': 'someone-else'})['rules']

        # Run budget 1 minute acts: a run of this file stops at 60 s with the reason on each step it did not reach.
        ticks = iter(range(10000))
        monkeypatch.setattr(session_files.time, 'monotonic', lambda: next(ticks) * 100.0)
        answer = session_files.run_document(document)
        stopped = [row for row in answer['results'].values() if row['status'] == 'Stopped']
        assert stopped and all(row['error'] == 'Run budget of 60 s reached before this step.' for row in stopped), answer['results']
    finally:
        client.close()
        server.close()
