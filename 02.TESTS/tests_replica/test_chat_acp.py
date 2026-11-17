"""CHAT-WORKS part 2: type in the app -> any installed agent answers in the session's thread, over the one ACP client.

Founder 2026-11-16: "even its chat does not work"; take what exists (ACP, our goose_adapter client) and fit it.
Every agent here is a FAKE that speaks ACP over stdio, started through the same start-command table as a real one
(a .cmd shim on PATH, as npm installs them; the client starts what the shim points to, never cmd.exe).
No real agent, no paid model, no live Workshop.
"""
import json
import os
import sys
import threading
import time

import pytest

FAKE_AGENT = r'''
import json, os, sys
log = open(os.environ["FAKE_AGENT_LOG"], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[1:]) + "\n"); log.flush()
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
               '--include-partial-messages', '--permission-prompt-tool', 'stdio', '--permission-mode', 'manual',
               '--strict-mcp-config']
# Codex is started with its plugins, apps and every MCP server it lists switched off (the fake lists two).
CODEX_ARGS = ['--disable', 'plugins', '--disable', 'apps', '-c', 'mcp_servers.archhub_agent_coordination.enabled=false',
              '-c', 'mcp_servers.rea.enabled=false', 'app-server']

FAKE_CLAUDE = r"""
import json, os, sys
log = open(os.environ["FAKE_AGENT_LOG"], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[1:]) + "\n"); log.write(json.dumps({"pid": os.getpid(), "user": "USERPROFILE" in os.environ,
    "archhub": sorted(k for k in os.environ if k.upper().startswith("ARCHHUB_") or k.upper() in ("QTWEBENGINE_CHROMIUM_FLAGS", "QT_OPENGL"))}) + "\n"); log.flush()
def grandchild():
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.write(json.dumps({"grandchild": child.pid}) + "\n"); log.flush()
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
stubborn = False
for line in sys.stdin:
    message = json.loads(line)
    if message.get("type") != "user":
        continue
    text = message["message"]["content"][0]["text"]
    if "hang" in text:
        grandchild()
        delta("Thinking")
        stubborn = True
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
if stubborn:
    import time
    time.sleep(600)   # like a real CLI behind its .cmd shim: it does not leave because its input closed
"""

FAKE_CODEX = r"""
import json, os, sys
if "mcp" in sys.argv:   # `codex --disable plugins --disable apps mcp list --json`: what the client asks before it starts
    if os.environ.get("FAKE_MCP_LIST") == "fails" or sys.argv[1:5] != ["--disable", "plugins", "--disable", "apps"]:
        sys.exit(3)
    print(os.environ.get("FAKE_MCP_LIST") or json.dumps([{"name": "archhub_agent_coordination", "enabled": True},
                                                          {"name": "rea", "enabled": True}]))
    sys.exit(0)
log = open(os.environ["FAKE_AGENT_LOG"], "a", encoding="utf-8")
log.write(json.dumps(sys.argv[1:]) + "\n"); log.write(json.dumps({"pid": os.getpid(), "user": "USERPROFILE" in os.environ,
    "archhub": sorted(k for k in os.environ if k.upper().startswith("ARCHHUB_") or k.upper() in ("QTWEBENGINE_CHROMIUM_FLAGS", "QT_OPENGL"))}) + "\n"); log.flush()
def grandchild():
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.write(json.dumps({"grandchild": child.pid}) + "\n"); log.flush()
def send(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def note(method, **params):
    send({"method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", **params}})
def command(ident, text, status):
    return {"type": "commandExecution", "id": ident, "command": text, "status": status}
ready = stubborn = False
for line in sys.stdin:
    message = json.loads(line)
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        send({"id": ident, "result": {"userAgent": "fake"}})
    elif method == "initialized":
        ready = True
    elif method == "thread/start":
        asks = (params.get("approvalPolicy"), params.get("sandbox"), params.get("approvalsReviewer")) == ("untrusted", "read-only", "user")
        asks = asks and "apply_patch" in str(params.get("developerInstructions"))   # told how an approved write can happen
        send({"id": ident, "result": {"thread": {"id": "thread-1"}}} if ready and params.get("cwd") and asks else
             {"id": ident, "error": {"code": -32600, "message": "Not initialized"}})
    elif method == "turn/start":
        text = params["input"][0]["text"]
        send({"id": ident, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        if "hang" in text:
            grandchild()
            note("item/agentMessage/delta", itemId="m1", delta="Thinking")
            stubborn = True
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
if stubborn:
    import time
    time.sleep(600)   # like a real CLI behind its .cmd shim: it does not leave because its input closed
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
    scripts = {'claude': 'fake_claude.py', 'codex': 'fake_codex.py', 'gemini': 'fake_mute.py'}   # their own CLI mode; one never answers
    mute = 'import sys\nfor line in sys.stdin:\n    pass\n'
    for name, source in (('fake_acp.py', FAKE_AGENT), ('fake_claude.py', FAKE_CLAUDE), ('fake_codex.py', FAKE_CODEX),
                         ('fake_mute.py', mute)):
        (bin_dir / name).write_text(source, encoding='utf-8')

    def install(command, folder=bin_dir):
        # the shim npm writes: it only starts an interpreter on a script beside it (node on .js; here Python on .py)
        folder.mkdir(parents=True, exist_ok=True)
        script = scripts.get(command, 'fake_acp.py')
        (folder / script).write_text((bin_dir / script).read_text(encoding='utf-8'), encoding='utf-8')
        (folder / (command + '.cmd')).write_text(
            '@ECHO off\r\nSETLOCAL\r\n"%%_prog%%"  "%%dp0%%\\%s" %%*\r\n' % script, encoding='utf-8')
    from nodelang import acp_client
    monkeypatch.setitem(acp_client._INTERPRETERS, '.py', sys.executable)
    monkeypatch.setenv('FAKE_AGENT_LOG', str(log))
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


@pytest.mark.parametrize('handle, command, argv', [('claude', 'claude', CLAUDE_ARGS), ('codex', 'codex', CODEX_ARGS),
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


def _server(tmp_path):
    """The server's stop state without its HTTP side: what halt_all, resume_all, close and admit_chat use."""
    import types
    quiet = types.SimpleNamespace(shutdown=lambda: None, server_close=lambda: None)
    return types.SimpleNamespace(_halted=threading.Event(), _closing=threading.Event(), _stop_epoch=0, triggers=None,
                                 cloud_relay=None, httpd=quiet, state_dir=tmp_path)


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
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    pid, grandchild = lines[1]['pid'], lines[2]['grandchild']
    deadline = time.monotonic() + 10
    while (_alive(pid) or _alive(grandchild)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)                                               # the CLI itself, not only its .cmd shim
    assert not _alive(grandchild)                                        # and whatever the CLI started


def test_a_start_that_never_answers_ends_on_stop_not_on_its_timeout(installed):
    from nodelang import acp_client
    install, _log = installed
    install('gemini')
    began = time.monotonic()
    with pytest.raises(acp_client.AcpRefused, match='Stopped by you'):
        acp_client.ask('gemini', 'how many sheets?', stopped=lambda: time.monotonic() - began > 1)
    assert time.monotonic() - began < acp_client.ACP_NODE['params']['start_seconds'] / 2


@pytest.mark.parametrize('ending', ['halt_all', 'close'])
def test_stop_everything_and_closing_the_app_end_every_agent(installed, tmp_path, ending):
    from nodelang import acp_client, nograph_server
    install, log = installed
    install('codex')
    assert acp_client.ask('codex', 'how many sheets?')['text'] == 'There are 12 sheets.'
    pid = json.loads(log.read_text(encoding='utf-8').splitlines()[1])['pid']
    assert _alive(pid)                                                   # the session is kept for the next message
    server = _server(tmp_path)
    getattr(nograph_server.NoGraphServer, ending)(server)
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid) and not acp_client._SESSIONS


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_the_agent_gets_the_users_environment_without_archhubs_own_variables(installed, monkeypatch, agent):
    from nodelang import acp_client
    install, log = installed
    install(agent)
    monkeypatch.setenv('ARCHHUB_CLOUD_TOKEN', 'not-for-the-agent')
    monkeypatch.setenv('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    assert acp_client.ask(agent, 'how many sheets?')['text'] == 'There are 12 sheets.'
    seen = json.loads(log.read_text(encoding='utf-8').splitlines()[1])
    # the test Python's own start-up stamps ARCHHUB_TEST_* markers into every Python it starts, the fake included
    assert [name for name in seen['archhub'] if not name.startswith('ARCHHUB_TEST_')] == [] and seen['user'] is True


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


def _held_start(monkeypatch, point):
    """Hold a start at a point where its session is registered but not yet usable; returns (entered, release, seen)."""
    from nodelang import acp_client, workshop_transport
    entered, release, seen = threading.Event(), threading.Event(), []

    def hold(real):
        def held(*args, **kwargs):
            seen.extend(args)
            entered.set()
            assert release.wait(20)
            return real(*args, **kwargs)
        return held
    if point == 'before the launch':
        monkeypatch.setattr(acp_client, 'start_command', hold(acp_client.start_command))
    else:   # the process exists, suspended; it is not yet in its job and not resumed
        monkeypatch.setattr(workshop_transport, '_OwnedProcessJob', hold(workshop_transport._OwnedProcessJob))
    return entered, release, seen


def test_two_sends_on_one_thread_while_its_agent_starts_start_exactly_one_agent(installed, monkeypatch):
    from nodelang import acp_client
    install, log = installed
    install('codex')
    entered, release, _seen = _held_start(monkeypatch, 'before the launch')
    results = []

    def send():
        try:
            results.append(acp_client.ask('codex', 'how many sheets?', task='one')['text'])
        except acp_client.AcpRefused as refused:
            results.append(str(refused))
    workers = [threading.Thread(target=send, daemon=True) for _ in range(2)]
    workers[0].start()
    assert entered.wait(10)
    workers[1].start()
    time.sleep(0.5)                                                      # the second send is now at the same start
    release.set()
    for worker in workers:
        worker.join(20)
    starts = [line for line in map(json.loads, log.read_text(encoding='utf-8').splitlines()) if isinstance(line, list)]
    assert starts == [CODEX_ARGS]                                        # one child, not two
    assert 'There are 12 sheets.' in results and len(results) == 2
    assert len(acp_client._SESSIONS) == 1


@pytest.mark.parametrize('point', ['before the launch', 'before the resume'])
@pytest.mark.parametrize('ending', ['close_all', 'stop_then_resume', 'app_close'])
def test_stop_during_a_start_leaves_no_agent_and_a_later_resume_does_not_revive_it(installed, monkeypatch, tmp_path, point, ending):
    from nodelang import acp_client, nograph_server
    install, log = installed
    install('codex')
    entered, release, seen = _held_start(monkeypatch, point)
    outcome = []

    def send():
        try:
            outcome.append(acp_client.ask('codex', 'how many sheets?')['text'])
        except BaseException as refused:  # noqa: BLE001 - the test reads what the send returned
            outcome.append(refused)
    worker = threading.Thread(target=send, daemon=True)
    worker.start()
    assert entered.wait(10)
    server = _server(tmp_path)
    if ending == 'close_all':
        acp_client.close_all()
    elif ending == 'app_close':
        nograph_server.NoGraphServer.close(server)
    else:
        nograph_server.NoGraphServer.halt_all(server)
        nograph_server.NoGraphServer.resume_all(server)                  # Resume does not bring the stopped start back
    release.set()
    worker.join(20)
    assert len(outcome) == 1 and isinstance(outcome[0], acp_client.AcpRefused) and str(outcome[0]) == 'Stopped by you'
    assert not log.exists()                                              # the agent never ran one instruction
    assert not acp_client._SESSIONS
    if point == 'before the resume':
        process = seen[0]
        process.wait(10)
        assert process.poll() is not None                                # the suspended child was ended, not left behind


def test_nothing_is_sent_to_an_agent_after_its_session_is_stopped(installed):
    from nodelang import acp_client
    install, _log = installed
    install('codex')
    assert acp_client.ask('codex', 'how many sheets?', task='t')['text'] == 'There are 12 sheets.'
    session = acp_client._SESSIONS[('codex', 't')]
    sent = []
    session.transport.dialect.wire = sent.append
    session.cancelled.set()
    with pytest.raises(acp_client.AcpRefused, match='Stopped by you'):
        session.ask('how many sheets?')
    assert sent == []
    acp_client.ask('codex', 'how many sheets?', task='t')                # the next send starts a new session
    assert acp_client._SESSIONS[('codex', 't')] is not session


@pytest.mark.parametrize('ending', ['stop_then_resume', 'app_close'])
def test_a_send_admitted_before_stop_never_starts_an_agent_after_it(installed, monkeypatch, tmp_path, ending):
    """The send is past admission but has no agent session yet when Stop (then Resume) or app close happens."""
    from nodelang import acp_client, nograph_server
    install, log = installed
    install('codex')
    server = _server(tmp_path)
    cancelled = nograph_server.NoGraphServer.admit_chat(server)
    entered, release, real, outcome = threading.Event(), threading.Event(), acp_client.ask, []

    def held(*args, **kwargs):          # the admitted request, just before it registers a session
        entered.set()
        assert release.wait(20)
        return real(*args, **kwargs)
    monkeypatch.setattr(acp_client, 'ask', held)

    def send():
        try:
            outcome.append(nograph_server._chat({'prompt': '@codex how many sheets?'}, lambda text: None, cancelled=cancelled))
        except BaseException as refused:  # noqa: BLE001 - the test reads what the send returned
            outcome.append(refused)
    worker = threading.Thread(target=send, daemon=True)
    worker.start()
    assert entered.wait(10)
    if ending == 'app_close':
        nograph_server.NoGraphServer.close(server)
    else:
        nograph_server.NoGraphServer.halt_all(server)
        nograph_server.NoGraphServer.resume_all(server)
    release.set()
    worker.join(20)
    assert len(outcome) == 1 and isinstance(outcome[0], acp_client.AcpRefused) and str(outcome[0]) == 'Stopped by you'
    assert not log.exists() and not acp_client._SESSIONS                 # no child, no session
    if ending == 'app_close':
        nograph_server.NoGraphServer.resume_all(server)
        with pytest.raises(nograph_server.Refused):                      # admission stays closed for good
            nograph_server.NoGraphServer.admit_chat(server)
    else:
        assert nograph_server.NoGraphServer.admit_chat(server)() is False   # after Resume a new send is admitted
        nograph_server.NoGraphServer.halt_all(server)
        with pytest.raises(nograph_server.Refused):
            nograph_server.NoGraphServer.admit_chat(server)


def test_close_all_marks_every_session_stopped_before_it_cleans_up_the_first(installed, monkeypatch):
    from nodelang import acp_client
    install, _log = installed
    install('codex')
    for task in ('a', 'b', 'c'):
        acp_client.ask('codex', 'how many sheets?', task=task)
    sessions, seen, real = list(acp_client._SESSIONS.values()), [], acp_client.AgentSession._release

    def release(session):
        seen.append([one.cancelled.is_set() for one in sessions])
        real(session)
    monkeypatch.setattr(acp_client.AgentSession, '_release', release)
    acp_client.close_all()
    assert len(sessions) == 3 and seen[0] == [True, True, True]


def test_nothing_is_written_to_an_agent_after_its_session_is_stopped_whatever_queued_it(installed):
    from nodelang import acp_client
    install, _log = installed
    install('codex')
    acp_client.ask('codex', 'how many sheets?', task='t')
    session = acp_client._SESSIONS[('codex', 't')]
    transport, written = session.transport, []

    class Spy:
        write = staticmethod(written.append)
        flush = close = staticmethod(lambda: None)
    real, transport.process.stdin = transport.process.stdin, Spy()
    try:
        session.cancelled.set()
        transport.outbox.put_nowait(b'{"method": "queued-before-stop"}\n')   # a line already in the writer's queue
        with pytest.raises(acp_client.AcpRefused, match='Stopped by you'):  # Codex's read-side `initialized`, and any other
            transport.dialect.wire({'method': 'initialized'})
        time.sleep(0.5)
        assert written == []
    finally:
        transport.process.stdin = real


def _waiter():
    """The agent's side of one Approve card, as approve_card runs it; returns (thread, outcome list)."""
    from nodelang import acp_client
    ask = acp_client.approve_card('Codex', time.monotonic() + 30)
    request = {'sessionId': 's1', 'toolCall': {'toolCallId': 't', 'title': 'Write sheets.txt', 'kind': 'edit',
                                               'rawInput': {'n': time.monotonic_ns()}},
               'options': [{'optionId': 'yes', 'kind': 'allow_once'}, {'optionId': 'no', 'kind': 'reject_once'}]}
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(ask(request, {}, {})), daemon=True)
    worker.start()
    return worker, outcome


def _pending_card():
    from nodelang import hook_decision
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        cards = [c for c in hook_decision.ask_reviews() if c['status'] == 'pending']
        if cards:
            return cards[0]
        time.sleep(0.01)
    raise AssertionError('no pending card')


def test_a_waiting_agent_never_takes_an_unreadable_approval_file_for_a_denial(monkeypatch):
    from nodelang import acp_client, hook_decision
    monkeypatch.setitem(acp_client.ACP_NODE['params'], 'card_poll_seconds', 0.01)
    real, failed = hook_decision.approval_status, []

    def unreadable(environment, hold):
        if len(failed) < 5:
            failed.append(hold)
            raise PermissionError(13, 'Access is denied')
        return real(environment, hold)
    monkeypatch.setattr(hook_decision, 'approval_status', unreadable)
    worker, outcome = _waiter()
    card = _pending_card()
    while len(failed) < 5:
        time.sleep(0.01)
    assert outcome == []                                                 # five failed reads: still waiting, not denied
    hook_decision.ask_apply(card['id'], card['input_digest'], 'approve')
    worker.join(10)
    assert outcome == [{'outcome': 'selected', 'optionId': 'yes'}]


def test_approve_and_deny_under_a_polling_agent_give_exactly_one_decision_each_time(monkeypatch):
    """The live race: the waiting agent reads the file as fast as it can while the click replaces it."""
    from nodelang import acp_client, hook_decision
    monkeypatch.setitem(acp_client.ACP_NODE['params'], 'card_poll_seconds', 0.0)
    for turn in range(30):
        decision = 'approve' if turn % 2 else 'deny'
        worker, outcome = _waiter()
        card = _pending_card()
        saved = hook_decision.ask_apply(card['id'], card['input_digest'], decision)   # one click, no retry
        worker.join(10)
        assert saved['status'] == ('approved' if decision == 'approve' else 'declined')
        assert outcome == [{'outcome': 'selected', 'optionId': 'yes' if decision == 'approve' else 'no'}], turn
        assert hook_decision._take_permit(card['input_digest'], os.environ) is False   # taken once, by the waiter
    rows = json.loads(hook_decision._ask_path(os.environ).read_text(encoding='utf-8'))['holds'].values()
    assert len(rows) == 30 and not [row for row in rows if row['status'] in ('releasing', 'pending')]


@pytest.mark.parametrize('listing', ['fails', 'not json', json.dumps([{'name': 'rea & calc'}]), json.dumps({'servers': []})])
def test_codex_is_not_started_when_its_connectors_cannot_be_switched_off(installed, monkeypatch, listing):
    """Codex's own MCP servers, plugins and apps are outside the file and command cards: it starts without them or not at all."""
    from nodelang import acp_client
    install, log = installed
    install('codex')
    monkeypatch.setenv('FAKE_MCP_LIST', listing)
    with pytest.raises(ValueError, match='connectors could not be switched off'):
        acp_client.ask('codex', 'how many sheets?')
    assert not log.exists() and not acp_client._SESSIONS


def test_claude_and_codex_start_without_their_own_connectors():
    from nodelang import acp_client
    assert '--strict-mcp-config' in acp_client.AGENTS['claude']['args'] and '--mcp-config' not in acp_client.AGENTS['claude']['args']
    assert acp_client._codex_connectors_off.__doc__                       # Codex: its start words are built there, see CODEX_ARGS


def test_claude_and_codex_start_as_the_installed_cli_never_an_adapter_or_a_permission_skip():
    from nodelang import acp_client
    for agent in ('claude', 'codex'):
        row = acp_client.AGENTS[agent]
        assert row['commands'] == (agent,)                               # no claude-agent-acp / codex-acp dependency
        assert not [arg for arg in row['args'] if 'skip' in arg or 'bypass' in arg or 'dangerous' in arg]


def test_settings_cannot_replace_an_agent_start_command(installed):
    """Only the built-in table starts an agent: a start command in Settings is refused and never run."""
    from nodelang import nograph_server
    from nodelang.settings_owner import read_router_settings, router_settings_path
    install, log = installed
    install('opencode')
    install('my-opencode')
    router_settings_path().parent.mkdir(parents=True, exist_ok=True)
    router_settings_path().write_text(json.dumps({'agents': {'opencode': {'acp': {'command': 'my-opencode', 'args': ['acp', '--quiet']}}}}),
                                      encoding='utf-8')
    with pytest.raises(ValueError):
        read_router_settings()
    assert nograph_server._chat({'prompt': '@opencode how many sheets?'}, lambda text: None)['text'] == 'There are 12 sheets.'
    assert [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] == [['acp']]   # the table row, nothing else


@pytest.mark.parametrize('agent', ['claude', 'codex', 'gemini', 'opencode', 'goose'])
def test_an_agent_starts_as_the_program_its_shim_points_to_and_cmd_never_runs(installed, monkeypatch, agent):
    from nodelang import acp_client
    install, _log = installed
    install(agent)
    started = []
    real = acp_client.subprocess.Popen
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda argv, **kw: (started.append(list(argv)), real(argv, **kw))[1])
    argv = acp_client.start_command(agent)[0]
    assert argv[0] == sys.executable and argv[1].endswith('.py')
    assert argv[2:] == (CODEX_ARGS if agent == 'codex' else list(acp_client.AGENTS[agent]['args']))
    if agent != 'gemini':   # the mute fake never answers
        acp_client.ask(agent, 'how many sheets?')
        assert started and all(line[0] == sys.executable and 'cmd' not in os.path.basename(line[0]).lower() and '/C' not in line
                               for line in started)


@pytest.mark.parametrize('folder', ['%COMSPEC%', 'a&b', 'a^b'])
def test_a_shim_in_a_folder_with_a_shell_character_is_refused_and_nothing_starts(installed, tmp_path, monkeypatch, folder):
    from nodelang import acp_client
    install, log = installed
    install('opencode', tmp_path / folder / 'bin')
    monkeypatch.setenv('PATH', str(tmp_path / folder / 'bin'))
    started = []
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda *a, **kw: started.append(a))
    with pytest.raises(ValueError, match='is not started from there'):
        acp_client.ask('opencode', 'how many sheets?')
    assert not started and not log.exists()


@pytest.mark.parametrize('shim', ['@python "%dp0%\\fake_acp.py" & calc.exe %*\r\n', '@echo nothing here\r\n',
                                  '"%_prog%"  "%dp0%\\missing.py" %*\r\n', '"%_prog%"  "%dp0%\\fake_acp.txt" %*\r\n'])
def test_a_shim_that_does_not_point_to_one_program_is_refused_with_a_plain_message(installed, tmp_path, monkeypatch, shim):
    from nodelang import acp_client
    install, log = installed
    install('opencode')
    (tmp_path / 'bin' / 'fake_acp.txt').write_text('x', encoding='utf-8')
    (tmp_path / 'bin' / 'opencode.cmd').write_text(shim, encoding='utf-8')
    started = []
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda *a, **kw: started.append(a))
    with pytest.raises(ValueError, match='could not be resolved to a program'):
        acp_client.ask('opencode', 'how many sheets?')
    assert not started and not log.exists()


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
    process = subprocess.Popen(acp_client.start_command('goose')[0], env=acp_client.child_environment(),
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
