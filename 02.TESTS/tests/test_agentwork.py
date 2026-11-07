"""F296: native transcript -> editable nodes -> ordinary Run/Approve, isolated files only."""
import json
import inspect

import pytest

import test_agentcanvas


@pytest.fixture
def history(tmp_path, monkeypatch):
    yield from inspect.unwrap(test_agentcanvas.history)(tmp_path, monkeypatch)


def native(root, vendor, name, calls):
    path = root / ('.claude/projects/fixture/' + name + '.jsonl' if vendor == 'claude' else '.codex/sessions/fixture/rollout-date-' + name + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (tool, args, output) in enumerate(calls):
        identity = 'call-' + str(index)
        if vendor == 'claude':
            rows.extend([{'type': 'assistant', 'message': {'role': 'assistant', 'model': 'fixture-model', 'content': [
                {'type': 'tool_use', 'id': identity, 'name': tool, 'input': args}]}},
                {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': identity, 'content': output}]}}])
        else:
            rows.extend([{'type': 'turn_context', 'payload': {'model': 'fixture-model', 'turn_id': 'turn-' + str(index)}},
                {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': identity, 'name': tool, 'arguments': json.dumps(args)}},
                {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': identity, 'output': output}}])
    path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    return path


def fixture_document(root, vendor, monkeypatch):
    from nodelang.agent_status import read_transcript
    from nodelang.agent_work import project
    from nodelang.session_files import new_document, validate
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(root))
    first, second = root / 'INDEX.csv', root / 'EDITED.csv'
    first.write_text('original', encoding='utf-8')
    second.write_text('edited', encoding='utf-8')
    calls = [('declare', {'task': 'Read details index'}, '{}'), ('Read', {'file_path': str(first)}, str(first)),
             ('declare', {'task': 'Write reviewed details'}, '{}'), ('Write', {'file_path': str(root / 'output.txt'), 'content': 'reviewed'}, 'written'),
             ('declare', {'task': 'Inspect native commands'}, '{}'), ('Bash', {'command': 'echo safe', 'cwd': str(root)}, 'safe')]
    native(root, vendor, vendor, calls)
    document = new_document('BA details fixture')
    agent = {'id': 'agent', 'type': 'thing.agent', 'title': 'BA details', 'params': {'agent': vendor}, 'position': {'x': 0, 'y': 0}}
    document['nodes'] = [agent]
    project(document, agent, {'runtime': vendor, 'native_session_id': vendor}, read_transcript(vendor, vendor))
    validate(document)
    return document, first, second


@pytest.mark.parametrize('vendor', ['claude', 'codex'])
def test_native_nodes_edit_run_approve_history_and_fork(tmp_path, monkeypatch, vendor):
    from nodelang.agent_work import history as read_history, fork, project
    from nodelang.agent_status import read_transcript
    from nodelang.session_files import run_document, write_document
    from nodelang.hook_decision import ask_apply, ask_reviews
    document, first, second = fixture_document(tmp_path, vendor, monkeypatch)
    agent, read, write, shell = document['nodes']
    assert agent['params']['model'] == 'fixture-model'
    assert read['paramDefs'] == [{'id': 'path', 'name': 'Path', 'type': 'file'}]
    assert len(document['nodes']) == 4
    read['params']['path'] = str(second)
    result = run_document(document, roots=[read['id']])
    assert result['results'][read['id']]['output']['text'] == 'edited'
    assert len(read_history(read)['calls']) == 1
    assert read_history(read)['calls'][0]['output'] == str(first)
    result = run_document(document, roots=[write['id']])
    assert result['approvalId']
    assert not (tmp_path / 'output.txt').exists()
    card = next(c for c in ask_reviews() if c['id'] == result['approvalId'])
    assert ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    assert (tmp_path / 'output.txt').read_text(encoding='utf-8') == 'reviewed'
    assert ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    result = run_document(document, roots=[shell['id']])
    assert 'escape hatch' in result['results'][shell['id']]['error']
    assert not shell['agentWork']['runnable']
    project(document, agent, {'runtime': vendor, 'native_session_id': vendor}, read_transcript(vendor, vendor))
    assert read['params']['path'] == str(second)
    ids = fork(document, 'agent')
    assert len(ids) == 3
    assert all('agentWork' not in n for n in document['nodes'] if n['id'] in ids)
    write_document(tmp_path / 'proof.archhub', document)


def test_secrets_do_not_enter_document_or_history(tmp_path, monkeypatch):
    from nodelang.agent_status import read_transcript
    from nodelang.agent_work import project
    from nodelang.session_files import new_document, write_document, run_document
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(tmp_path))
    private_label = ' '.join(('PRIVATE', 'KEY'))
    pem = '-----BEGIN ' + private_label + '-----\nfixture-key\n-----END ' + private_label + '-----'
    payload = json.dumps({'api_key': 'fixture-json-key', 'password': 'fixture password with spaces'}) + '\n' + pem
    secret_file = tmp_path / 'input.txt'
    secret_file.write_text(payload, encoding='utf-8')
    native(tmp_path, 'claude', 'secret', [('Read', {'path': str(secret_file), 'api_key': 'fixture-secret',
        'headers': {'Authorization': 'Bearer fixture-auth', 'Cookie': 'fixture-cookie'}},
        'Bearer fixture-bearer password=fixture-password\n' + payload)])
    transcript = read_transcript('claude', 'secret')
    secrets = ('fixture-secret', 'fixture-bearer', 'fixture-password', 'fixture-json-key',
               'fixture password with spaces', 'fixture-key', 'fixture-auth', 'fixture-cookie')
    assert not any(s in json.dumps(transcript) for s in secrets)
    doc = new_document()
    agent = {'id': 'a', 'title': 'Work', 'type': 'thing.agent', 'params': {}, 'position': {'x': 0, 'y': 0}}
    doc['nodes'] = [agent]
    project(doc, agent, {'runtime': 'claude', 'native_session_id': 'secret'}, transcript)
    step = doc['nodes'][-1]
    step['result'] = run_document(doc, roots=[step['id']])['results'][step['id']]
    path = tmp_path / 'proof.archhub'
    write_document(path, doc)
    assert not any(s in path.read_text(encoding='utf-8') for s in secrets)


def test_inferred_wires_never_override_edited_parameters(tmp_path, monkeypatch):
    from nodelang.agent_work import project
    from nodelang.agent_status import read_transcript
    from nodelang.session_files import run_document, validate
    document, first, second = fixture_document(tmp_path, 'codex', monkeypatch)
    native(tmp_path, 'codex', 'codex', [('declare', {'task': 'Read'}, '{}'), ('Read', {'path': str(first)}, json.dumps({'path': str(second)})),
                                      ('declare', {'task': 'Read output'}, '{}'), ('Read', {'path': str(second) + '.bak'}, 'edited')])
    document['nodes'] = document['nodes'][:1]
    project(document, document['nodes'][0], {'runtime': 'codex', 'native_session_id': 'codex'}, read_transcript('codex', 'codex'))
    validate(document)
    assert len(document['wires']) == 1 and document['wires'][0]['inferred']
    later = document['nodes'][-1]
    later['params']['path'] = str(first)
    result = run_document(document, roots=[later['id']])
    assert result['results'][later['id']]['output']['text'] == 'original'


def test_no_declare_groups_by_turn(tmp_path, monkeypatch):
    from nodelang.agent_status import read_transcript
    from nodelang.agent_work import steps
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(tmp_path))
    native(tmp_path, 'codex', 'turns', [('Read', {'path': 'a'}, 'a'), ('Bash', {'command': 'b'}, 'b')])
    assert len(steps(read_transcript('codex', 'turns'))) == 2


def test_empty_declare_appears_without_fabricated_tool(tmp_path, monkeypatch):
    from nodelang.agent_status import read_transcript
    from nodelang.agent_work import project
    from nodelang.session_files import new_document
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(tmp_path))
    native(tmp_path, 'claude', 'empty', [('declare', {'task': 'Review details'}, '{}')])
    document = new_document()
    agent = {'id': 'a', 'title': 'Review', 'type': 'thing.agent', 'params': {}, 'position': {'x': 0, 'y': 0}}
    document['nodes'] = [agent]
    project(document, agent, {'runtime': 'claude', 'native_session_id': 'empty'}, read_transcript('claude', 'empty'))
    step = document['nodes'][-1]
    assert step['title'] == 'Review details'
    assert step['agentWork']['tool'] == 'detail not available'
    assert not step['agentWork']['runnable']
    project(document, agent, {'runtime': 'claude', 'native_session_id': 'empty', 'model': 'declared-model'}, {})
    assert agent['params']['model'] == 'declared-model'
    assert agent['params']['detail'] == 'detail not available'


def test_forked_write_still_needs_approval_and_deny_writes_nothing(tmp_path, monkeypatch):
    from nodelang.agent_work import fork
    from nodelang.session_files import run_document
    from nodelang.hook_decision import ask_apply, ask_reviews
    document, _, _ = fixture_document(tmp_path, 'claude', monkeypatch)
    write = document['nodes'][2]
    ids = fork(document, write['id'])
    assert len(ids) == 2
    result = run_document(document, roots=[ids[0]])
    card = next(c for c in ask_reviews() if c['id'] == result['approvalId'])
    assert ask_apply(card['id'], card['input_digest'], 'deny')['status'] == 'declined'
    assert not (tmp_path / 'output.txt').exists()


def test_structural_ids_and_paths_survive_redaction():
    from nodelang.agent_work import redact
    identity = 'c91092311b7c4ee3aafe9763bc0d12fe'
    assert redact({'id': identity, 'path': 'C:/fixture/' + identity + '/INDEX.csv'}) == {
        'id': identity, 'path': 'C:/fixture/' + identity + '/INDEX.csv'}


def test_current_pointer_retries_windows_sharing_violation(tmp_path, monkeypatch):
    import os
    from nodelang.session_files import SessionFiles
    owner = SessionFiles(tmp_path)
    old, new = tmp_path / 'old.archhub', tmp_path / 'new.archhub'
    owner._current('old', str(old))
    replace = os.replace
    attempts = []
    def sharing_once(source, target):
        attempts.append(str(target))
        if len(attempts) == 1:
            assert json.loads((tmp_path / 'current.json').read_text(encoding='utf-8'))['id'] == 'old'
            error = PermissionError('Simulated Windows read handle')
            error.winerror = 32
            raise error
        return replace(source, target)
    monkeypatch.setattr(os, 'replace', sharing_once)
    owner._current('new', str(new))
    assert len(attempts) == 2
    assert json.loads((tmp_path / 'current.json').read_text(encoding='utf-8'))['id'] == 'new'


def test_noop_autosave_move_allows_open_readers():
    from nodelang.session_files import sessions_directory, write_document, new_document, move_session
    path = sessions_directory() / 'Readers.archhub'
    write_document(path, new_document('Readers'))
    before = path.read_bytes()
    with path.open('rb') as reader:
        assert reader.read() == before
        assert move_session(path, path.parent) == str(path)
    assert path.read_bytes() == before
    assert list(path.parent.glob('*.archhub')) == [path]


@pytest.mark.parametrize('winerror', [32, 2])
def test_document_read_retries_only_windows_sharing_errors(tmp_path, monkeypatch, winerror):
    from pathlib import Path
    from nodelang.session_files import new_document, write_document, read_document
    path = tmp_path / 'Readers.archhub'
    document = new_document('Readers')
    write_document(path, document)
    original = Path.open
    attempts = []
    def sharing_once(target, *args, **kwargs):
        if target == path:
            attempts.append(target)
            if len(attempts) == 1:
                error = PermissionError('Simulated Windows read handle')
                error.winerror = winerror
                raise error
        return original(target, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', sharing_once)
    if winerror == 32:
        assert read_document(path) == document
        assert len(attempts) == 2
    else:
        with pytest.raises(PermissionError):
            read_document(path)
        assert len(attempts) == 1


def test_home_fold_only_changes_archive_flag(history):
    from nodelang import workshop_tasks as tasks
    current = tasks._declared_id('agent')
    declarations = [{'root': 'root', 'request_id': 'FIRST', 'session': 'agent'}]
    legacy = tasks._declaration_task_id(declarations[0])
    for identity in (current, legacy):
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,owner,created_by,created_at,updated_at,result) VALUES(?,'Work','open','agent','Agent','then','then','retained')", (identity,))
    before = tasks.get(history, legacy)
    tasks.fold_declarations(history, declarations)
    after = tasks.get(history, legacy)
    assert after == {**before, 'archived': 1, 'revision': before['revision'] + 1}
    assert len(tasks.rows(history, include_archived=False)) == 1
    tasks._write(history, 'UPDATE workshop_tasks SET archived=0 WHERE id=?', (legacy,))
    assert len(tasks.rows(history, include_archived=False)) == 2
    for identity in ('declared-old-a', 'declared-old-b'):
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,owner,created_by,created_at,updated_at,result) VALUES(?,'Legacy work','open','old-agent','Agent','then','then','retained')", (identity,))
    tasks.fold_declarations(history, [{'root': 'old-root', 'request_id': 'OLD', 'session': 'old-agent'}])
    assert len([r for r in tasks.rows(history, include_archived=False) if r['owner'] == 'old-agent']) == 1
    assert all(r['title'] == 'Legacy work' and r['result'] == 'retained' for r in tasks.rows(history) if r['owner'] == 'old-agent')


def test_rendered_agentwork():
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or subprocess.check_output(
        ['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    for command in (['node', '--max-old-space-size=512', '03.TOOLS/packaging/compile_studio.cjs'],
                    ['node', '02.TESTS/tests_js/agentwork.cjs']):
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=240,
                                env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': cache, 'ARCHHUB_COURT_PYTHON': sys.executable},
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
