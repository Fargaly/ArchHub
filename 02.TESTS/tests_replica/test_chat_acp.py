"""CHAT-WORKS part 2: type in the app -> any installed agent answers in the session's thread, over the one ACP client.

Founder 2026-11-16: "even its chat does not work"; take what exists (ACP, our goose_adapter client) and fit it.
Every agent here is a FAKE that speaks ACP over stdio, started through the same start-command table as a real one
(a .cmd shim on PATH, as npm installs them). No real agent, no paid model, no live Workshop.
"""
import json
import os
import sys
import threading
import time

import pytest

FAKE_AGENT = r'''
import json, sys
log = open(sys.argv[1], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[2:]) + "\n"); log.flush()
def send(value):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **value}) + "\n"); sys.stdout.flush()
def update(session, item):
    send({"method": "session/update", "params": {"sessionId": session, "update": item}})
for line in sys.stdin:
    message = json.loads(line)
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        send({"id": ident, "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    elif method == "session/new":
        send({"id": ident, "result": {"sessionId": "fake-session-1"}})
    elif method == "session/prompt":
        session = params["sessionId"]
        text = params["prompt"][0]["text"]
        if "write" in text:
            update(session, {"sessionUpdate": "tool_call", "toolCallId": "t2", "title": "Write sheets.txt", "kind": "edit",
                             "status": "pending", "rawInput": {"path": "sheets.txt"}})
            send({"id": "perm-1", "method": "session/request_permission", "params": {"sessionId": session,
                  "toolCall": {"toolCallId": "t2", "title": "Write sheets.txt", "kind": "edit", "rawInput": {"path": "sheets.txt"}},
                  "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                              {"optionId": "no", "name": "Reject", "kind": "reject_once"}]}})
            answer = json.loads(sys.stdin.readline())
            chosen = (answer.get("result") or {}).get("outcome") or {}
            allowed = chosen.get("outcome") == "selected" and chosen.get("optionId") == "yes"
            update(session, {"sessionUpdate": "tool_call_update", "toolCallId": "t2",
                             "status": "completed" if allowed else "failed"})
            update(session, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text",
                             "text": "File written." if allowed else "File not written."}})
        else:
            update(session, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "There are "}})
            update(session, {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Read sheets", "kind": "read",
                             "status": "in_progress"})
            update(session, {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"})
            update(session, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "12 sheets."}})
        send({"id": ident, "result": {"stopReason": "end_turn"}})
'''


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    from nodelang import workshop_live
    monkeypatch.setattr(workshop_live, 'live_agents', lambda with_status=False: [])  # no live session is reachable
    yield tmp_path
    from nodelang import acp_client
    acp_client.close_all()


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Put fake agents on PATH under their real start commands; returns the argv log."""
    bin_dir, log = tmp_path / 'bin', tmp_path / 'argv.log'
    bin_dir.mkdir()
    (bin_dir / 'fake_acp.py').write_text(FAKE_AGENT, encoding='utf-8')

    def install(command):
        (bin_dir / (command + '.cmd')).write_text(
            '@"%s" "%s" "%s" %%*\r\n' % (sys.executable, bin_dir / 'fake_acp.py', log), encoding='utf-8')
    monkeypatch.setenv('PATH', str(bin_dir))
    return install, log


def _task(title):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        return workshop_tasks.create_session(history, title, 'founder', select=False)['taskId']


def _thread(task):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        row = next(r for r in workshop_tasks.column(history) if r['id'] == task)
    return [m['text'] for m in row['agentLog'] + row['fileMessages']]


@pytest.mark.parametrize('handle, command, argv', [('claude', 'claude-agent-acp', []), ('opencode', 'opencode', ['acp'])])
def test_an_agent_that_is_not_running_is_started_and_its_reply_streams_into_the_thread(installed, handle, command, argv):
    from nodelang import nograph_server
    install, log = installed
    install(command)
    task = _task('Review sheets')
    events = []
    result = nograph_server._chat({'prompt': '@%s how many sheets?' % handle, 'task': task}, events.append,
                                  on_step=lambda step: events.append(step))
    deltas = [e for e in events if isinstance(e, str)]
    assert deltas == ['There are ', '12 sheets.']                      # streamed as written
    assert result['text'] == 'There are 12 sheets.' and result['answer'].startswith('There are 12 sheets.\n')
    assert {'tool': 'Read sheets', 'status': 'ok'} in [{k: s[k] for k in ('tool', 'status')} for s in result['steps']]
    assert any(isinstance(e, dict) and e.get('status') == 'running' for e in events)  # a step shows while it runs
    assert json.loads(log.read_text(encoding='utf-8').splitlines()[0]) == argv
    thread = _thread(task)
    assert 'how many sheets?' in thread and 'There are 12 sheets.\n\u2022 Read sheets: ok' in thread    # one settled message, no chunks
    assert not any(text in ('There are ', '12 sheets.') for text in thread)


def test_the_same_thread_reuses_its_agent_session(installed):
    from nodelang import nograph_server
    install, log = installed
    install('opencode')
    task = _task('Review sheets')
    for _ in range(2):
        nograph_server._chat({'prompt': '@opencode how many sheets?', 'task': task}, lambda text: None)
    assert len(log.read_text(encoding='utf-8').splitlines()) == 1         # started once, asked twice


@pytest.mark.parametrize('decision, reply, status', [('approve', 'File written.', 'ok'), ('deny', 'File not written.', 'failed')])
def test_a_permission_request_becomes_the_approve_card_and_the_agent_waits(installed, decision, reply, status):
    from nodelang import hook_decision, nograph_server
    install, _log = installed
    install('claude-agent-acp')
    task = _task('Write sheets')
    done = {}
    worker = threading.Thread(target=lambda: done.update(result=nograph_server._chat(
        {'prompt': '@claude write the sheet list', 'task': task}, lambda text: None)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 20
    cards = []
    while time.monotonic() < deadline and not cards:
        cards = [c for c in hook_decision.ask_reviews() if c['status'] == 'pending']
        time.sleep(0.05)
    assert cards and cards[0]['who'] == 'Claude Code' and 'Write sheets.txt' in cards[0]['summary']
    time.sleep(0.3)
    assert 'result' not in done                                          # the agent waits for the card
    hook_decision.ask_apply(cards[0]['id'], cards[0]['input_digest'], decision)
    worker.join(20)
    assert done['result']['text'] == reply
    assert [s['status'] for s in done['result']['steps'] if s['tool'] == 'Write sheets.txt'] == [status]


def test_a_settings_start_command_replaces_the_table_row(installed):
    from nodelang import nograph_server
    from nodelang.settings_owner import router_settings_path
    install, log = installed
    install('my-opencode')
    router_settings_path().parent.mkdir(parents=True, exist_ok=True)
    router_settings_path().write_text(json.dumps({'agents': {'opencode': {'acp': {'command': 'my-opencode', 'args': ['acp', '--quiet']}}}}),
                                      encoding='utf-8')
    result = nograph_server._chat({'prompt': '@opencode how many sheets?'}, lambda text: None)
    assert result['text'] == 'There are 12 sheets.'
    assert json.loads(log.read_text(encoding='utf-8').splitlines()[0]) == ['acp', '--quiet']


def test_an_agent_that_is_not_installed_is_named_and_nothing_is_downloaded(installed):
    from nodelang import nograph_server
    with pytest.raises(ValueError, match='Gemini is not installed'):
        nograph_server._chat({'prompt': '@gemini how many sheets?'}, lambda text: None)


def test_thread_rows_carry_no_routing_header():
    from nodelang.workshop_live import record_answer
    task = _task('Review sheets')
    record_answer('how many sheets?', 'There are 12 sheets.', 'Claude Code', task=task, to='Claude Code')
    thread = _thread(task)
    assert thread == ['how many sheets?', 'There are 12 sheets.']


def test_home_task_title_keeps_the_words_after_a_colon():
    from nodelang.workshop_tasks import short_title
    assert short_title('Check the doors: level 2 and 3') == 'Check the doors: level 2 and 3'
    assert short_title('WSFIX: check the doors') == 'check the doors'


def test_baboom_answers_through_the_same_acp_client(installed, tmp_path):
    """BABOOM (Goose) is one row on the one client: its turn runs over acp_client.AcpTransport."""
    import subprocess
    from nodelang import acp_client
    from nodelang.goose_adapter import GooseAdapter
    install, _log = installed
    install('goose')
    process = subprocess.Popen([os.environ['COMSPEC'], '/C', str(tmp_path / 'bin' / 'goose.cmd'), 'acp'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    class Runtime:
        transport = acp_client.AcpTransport(process, label='Goose')
        work_dir, host_extension = tmp_path, {'type': 'http', 'name': 'archhub-hosts', 'url': 'http://127.0.0.1:9/mcp', 'headers': []}

        def close(self):
            self.transport.close()
    runtime = Runtime()
    try:
        runtime.transport.request('initialize', {'protocolVersion': 1}, deadline=time.monotonic() + 10)
        answer = GooseAdapter(runtime).ask('how many sheets?', '', 'openrouter/free', turn_seconds=10)
    finally:
        runtime.close()
    assert answer['text'] == 'There are 12 sheets.'
