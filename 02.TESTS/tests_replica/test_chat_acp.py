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


# Claude Code and Codex are started as the CLIs already installed, in the structured mode each one already has;
# these fakes speak those two modes (claude -p stream-json; codex app-server), not ACP.
CLAUDE_ARGS = ['-p', '--output-format', 'stream-json', '--input-format', 'stream-json', '--verbose',
               '--include-partial-messages', '--permission-prompt-tool', 'stdio']

FAKE_CLAUDE = r"""
import json, os, sys
log = open(sys.argv[1], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[2:]) + "\n"); log.write(json.dumps({"pid": os.getpid()}) + "\n"); log.flush()
def send(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def delta(text):
    send({"type": "stream_event", "parent_tool_use_id": None,
          "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}})
def assistant(*content):
    send({"type": "assistant", "parent_tool_use_id": None, "message": {"role": "assistant", "content": list(content)}})
def tool_result(ident, failed):
    send({"type": "user", "parent_tool_use_id": None, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": ident, "is_error": failed, "content": "done"}]}})
send({"type": "system", "subtype": "init", "session_id": "s1"})
for line in sys.stdin:
    message = json.loads(line)
    if message.get("type") != "user":
        continue
    text = message["message"]["content"][0]["text"]
    if "hang" in text:
        delta("Thinking")
        continue
    if "write" in text:
        call = {"file_path": "sheets.txt", "content": "A-101"}
        assistant({"type": "tool_use", "id": "t2", "name": "Write", "input": call})
        send({"type": "control_request", "request_id": "perm-1", "request": {"subtype": "can_use_tool",
              "tool_name": "Write", "input": call, "tool_use_id": "t2"}})
        answer = json.loads(sys.stdin.readline())
        reply = answer["response"]["response"] if answer["response"]["request_id"] == "perm-1" else {}
        allowed = reply.get("behavior") == "allow" and reply.get("updatedInput") == call
        tool_result("t2", not allowed)
        said = "File written." if allowed else "File not written."
        delta(said)
        assistant({"type": "text", "text": said})
    else:
        delta("There are ")
        assistant({"type": "text", "text": "There are "}, {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "sheets"}})
        tool_result("t1", False)
        delta("12 sheets.")
        assistant({"type": "text", "text": "12 sheets."})   # the whole message repeats what was streamed
    send({"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn", "result": "done"})
"""

FAKE_CODEX = r"""
import json, os, sys
log = open(sys.argv[1], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[2:]) + "\n"); log.write(json.dumps({"pid": os.getpid()}) + "\n"); log.flush()
def send(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def note(method, **params):
    send({"method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", **params}})
def command(ident, text, status):
    return {"type": "commandExecution", "id": ident, "command": text, "status": status}
ready = False
for line in sys.stdin:
    message = json.loads(line)
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        send({"id": ident, "result": {"userAgent": "fake"}})
    elif method == "initialized":
        ready = True
    elif method == "thread/start":
        send({"id": ident, "result": {"thread": {"id": "thread-1"}}} if ready and params.get("cwd") else
             {"id": ident, "error": {"code": -32600, "message": "Not initialized"}})
    elif method == "turn/start":
        text = params["input"][0]["text"]
        send({"id": ident, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        if "hang" in text:
            note("item/agentMessage/delta", itemId="m1", delta="Thinking")
            continue
        if "write" in text:
            note("item/started", item=command("t2", "Write sheets.txt", "inProgress"))
            send({"id": 70, "method": "item/commandExecution/requestApproval", "params": {"threadId": "thread-1",
                  "turnId": "turn-1", "itemId": "t2", "command": "Write sheets.txt", "cwd": "."}})
            answer = json.loads(sys.stdin.readline())
            allowed = answer.get("id") == 70 and (answer.get("result") or {}).get("decision") == "accept"
            note("item/completed", item=command("t2", "Write sheets.txt", "completed" if allowed else "declined"))
            note("item/agentMessage/delta", itemId="m1", delta="File written." if allowed else "File not written.")
        else:
            note("item/agentMessage/delta", itemId="m1", delta="There are ")
            note("item/started", item=command("t1", "Read sheets", "inProgress"))
            note("item/completed", item=command("t1", "Read sheets", "completed"))
            note("item/agentMessage/delta", itemId="m1", delta="12 sheets.")
            note("item/completed", item={"type": "agentMessage", "id": "m1", "text": "There are 12 sheets."})
        send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}}})
"""


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
    scripts = {'claude': 'fake_claude.py', 'codex': 'fake_codex.py'}   # these two speak their own CLI mode
    for name, source in (('fake_acp.py', FAKE_AGENT), ('fake_claude.py', FAKE_CLAUDE), ('fake_codex.py', FAKE_CODEX)):
        (bin_dir / name).write_text(source, encoding='utf-8')

    def install(command):
        (bin_dir / (command + '.cmd')).write_text(
            '@"%s" "%s" "%s" %%*\r\n' % (sys.executable, bin_dir / scripts.get(command, 'fake_acp.py'), log), encoding='utf-8')
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


@pytest.mark.parametrize('handle, command, argv', [('claude', 'claude', CLAUDE_ARGS), ('codex', 'codex', ['app-server']),
                                                   ('opencode', 'opencode', ['acp'])])
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


@pytest.mark.parametrize('agent, who', [('claude', 'Claude Code'), ('codex', 'Codex'), ('opencode', 'OpenCode')])
@pytest.mark.parametrize('decision, reply, status', [('approve', 'File written.', 'ok'), ('deny', 'File not written.', 'failed')])
def test_a_permission_request_becomes_the_approve_card_and_the_agent_waits(installed, decision, reply, status, agent, who):
    from nodelang import acp_client, hook_decision, nograph_server
    install, _log = installed
    install(agent)
    assert acp_client.label(agent) == who
    task = _task('Write sheets')
    done = {}
    worker = threading.Thread(target=lambda: done.update(result=nograph_server._chat(
        {'prompt': '@%s write the sheet list' % agent, 'task': task}, lambda text: None)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 20
    cards = []
    while time.monotonic() < deadline and not cards:
        cards = [c for c in hook_decision.ask_reviews() if c['status'] == 'pending']
        time.sleep(0.05)
    assert cards and cards[0]['who'] == who and 'Write sheets.txt' in cards[0]['summary']
    time.sleep(0.3)
    assert 'result' not in done                                          # the agent waits for the card
    hook_decision.ask_apply(cards[0]['id'], cards[0]['input_digest'], decision)
    worker.join(20)
    assert done['result']['text'] == reply
    assert [s['status'] for s in done['result']['steps'] if s['tool'] == 'Write sheets.txt'] == [status]


def _alive(pid):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259   # STILL_ACTIVE


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_stop_ends_the_agent_process(installed, agent):
    from nodelang import acp_client
    install, log = installed
    install(agent)
    seen, halted = [], threading.Event()
    with pytest.raises(acp_client.AcpRefused, match='Stopped by you'):
        acp_client.ask(agent, 'hang on this one', on_delta=lambda text: (seen.append(text), halted.set()),
                       stopped=halted.is_set)
    assert seen == ['Thinking']                                          # it was mid-answer when Stop was pressed
    pid = json.loads(log.read_text(encoding='utf-8').splitlines()[1])['pid']
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)                                               # the CLI itself, not only its .cmd shim


@pytest.mark.parametrize('quiet, states', [(10, ['starting…', 'answering']), (0, ['starting…', 'not responding', 'answering'])])
def test_one_state_row_says_starting_then_answering_and_says_when_the_agent_is_quiet(installed, monkeypatch, quiet, states):
    from nodelang import acp_client, nograph_server
    install, _log = installed
    install('codex')
    monkeypatch.setitem(acp_client.ACP_NODE['params'], 'quiet_seconds', quiet)
    events = []
    result = nograph_server._chat({'prompt': '@codex how many sheets?'}, events.append, on_step=events.append)
    assert events[0] == {'who': 'Codex'} and events[1] == {'id': 'agent-state', 'tool': 'Codex', 'status': 'starting…'}
    assert [e['status'] for e in events if isinstance(e, dict) and e.get('id') == 'agent-state'] == states
    assert events.index('There are ') > max(i for i, e in enumerate(events) if isinstance(e, dict) and e.get('id') == 'agent-state')
    assert result['text'] == 'There are 12 sheets.'                      # a quiet agent is told about, never stopped
    assert not [s for s in result['steps'] if s['id'] == 'agent-state']  # the state row is not part of the settled answer


def test_claude_and_codex_start_as_the_installed_cli_never_an_adapter_or_a_permission_skip():
    from nodelang import acp_client
    for agent in ('claude', 'codex'):
        row = acp_client.AGENTS[agent]
        assert row['commands'] == (agent,)                               # no claude-agent-acp / codex-acp dependency
        assert not [arg for arg in row['args'] if 'skip' in arg or 'bypass' in arg or 'dangerous' in arg]


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
