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

from nodelang import acp_client as _shipped_client
_SHIPPED_CHAT_ACTIONS = _shipped_client.CHAT_ACTIONS   # as the release has it, read before any test changes it

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
CODEX_ARGS = ['--disable', 'plugins', '--disable', 'apps',
              '-c', 'mcp_servers.archhub_agent_coordination.enabled=false', '-c', 'mcp_servers.rea.enabled=false', 'app-server']
# The user's Codex config as the tests' profile has it: two MCP servers, one of them remote.
CODEX_CONFIG = '''model = "gpt"
[mcp_servers.archhub_agent_coordination]
command = "python"
args = ["server.py"]
[mcp_servers.rea]
url = "https://example.invalid/mcp"
'''

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
stubborn = first = False
for line in sys.stdin:
    message = json.loads(line)
    request = message.get("request") or {}
    if message.get("type") == "control_request" and request.get("subtype") == "mcp_status":
        log.write(json.dumps({"asked": "mcp_status"}) + "\n"); log.flush()   # asked before any message, as the client must
        send({"type": "control_response", "response": {"subtype": "success", "request_id": message["request_id"],
              "response": json.loads(os.environ.get("FAKE_CLAUDE_MCP") or '{"mcpServers": []}')}})
        continue
    if message.get("type") != "user":
        continue
    if not first:   # like the real CLI: its init line comes after the first message is written, before any answer
        first = True
        log.write(json.dumps({"user": True}) + "\n"); log.flush()
        # like the real CLI: with --tools only those tools exist, and the init line lists exactly them
        tools = sys.argv[sys.argv.index("--tools") + 1].split(",") if "--tools" in sys.argv else ["Read", "Write", "Bash"]
        send({"type": "system", "subtype": "init", "session_id": "s1",
              **json.loads(os.environ.get("FAKE_CLAUDE_INIT") or json.dumps({"mcp_servers": [], "tools": tools}))})
    text = message["message"]["content"][0]["text"]
    if "hang" in text:
        grandchild()
        delta("Thinking")
        stubborn = True
        continue
    if "unknown" in text:   # a request kind the client has no answer for: it must be refused, never left waiting
        send({"type": "control_request", "request_id": "odd-1", "request": {"subtype": "hook_callback", "callback_id": "c1"}})
        answer = json.loads(sys.stdin.readline())
        said = "Refused." if answer["response"]["subtype"] == "error" else "Granted."
        delta(said)
        assistant({"type": "text", "text": said})
    elif "write" in text:
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
SERVERS, LEAK = ["archhub_agent_coordination", "rea"], os.environ.get("FAKE_CODEX_LEAK", "")
def server_list(params, off):
    # the user's own MCP servers: live with tools until a thread switches them off
    if LEAK == "list fails":
        return {"error": {"code": -32603, "message": "inventory unavailable"}}
    if "threadId" not in params:   # an inventory with no thread starts every configured server: it must never be asked
        log.write(json.dumps({"early_inventory": True}) + "\n"); log.flush()
    quiet = off and "threadId" in params
    # a real inventory is one long line (measured: 3.3 MB for 368 tools), longer than the old 1 MB bound
    rows = [{"name": name, "runtimeStatus": "disabled" if quiet else None,
             "tools": {} if quiet else {"t": {"description": "x" * 1200000}}} for name in SERVERS]
    if quiet and LEAK == "one stays on":
        rows[1] = {"name": "rea", "runtimeStatus": "ready", "tools": {"delete": {}}}
    if quiet and LEAK == "a new one appears":
        rows.append({"name": "project_local", "runtimeStatus": "ready", "tools": {"x": {}}})
    return {"result": {"data": rows, "nextCursor": "more" if LEAK == "more pages" else None}}
FEATURES = ["plugins", "apps", "shell_tool", "unified_exec", "code_mode_host", "code_mode", "multi_agent", "multi_agent_v2",
            "computer_use", "browser_use", "browser_use_external", "browser_use_full_cdp_access", "in_app_browser",
            "image_generation", "view_image", "goals", "sleep_tool", "in_app_local_automation", "skill_mcp_dependency_install",
            "hooks", "fast_mode"]
# switched off on the start line; like the real 0.163, unified_exec stays on whatever the start line says
DISABLED = {sys.argv[i + 1] for i, word in enumerate(sys.argv[:-1]) if word == "--disable"} - {"unified_exec"}
def feature_list(params):
    # the thread's own feature list, like the real one: every feature with its state, answered in pages
    if LEAK == "features fail":
        return {"error": {"code": -32603, "message": "features unavailable"}}
    if LEAK == "features are not a list":
        return {"result": {"data": "many"}}
    rows = [{"name": name, "enabled": name not in DISABLED, "defaultEnabled": True, "stage": "stable"} for name in FEATURES]
    if LEAK == "its shell stays on":
        rows[2]["enabled"] = True
    if LEAK == "a feature is not listed":
        rows = [row for row in rows if row["name"] != "goals"]
    half = len(rows) // 2
    return {"result": {"data": rows[:half], "nextCursor": "page-2"} if params.get("cursor") is None else
                      {"data": rows[half:], "nextCursor": None}}
def started_as(params):
    # its own account of how the thread was started, as the real thread/start answer gives it
    said = {"approvalPolicy": params.get("approvalPolicy"),
            "sandbox": {"type": "readOnly" if params.get("sandbox") == "read-only" else "dangerFullAccess"}}
    if LEAK == "it does not ask first":
        said["approvalPolicy"] = "never"
    if LEAK == "it may write":
        said["sandbox"] = {"type": "workspaceWrite"}
    if LEAK == "it has the network":
        said["sandbox"]["networkAccess"] = True
    return {} if LEAK == "it does not say how it started" else said
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
answers = []
off = all("mcp_servers.%s.enabled=false" % name in sys.argv for name in SERVERS)   # switched off on the start line
for line in sys.stdin:
    message = json.loads(line)
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        send({"id": ident, "result": {"userAgent": "fake"}})
    elif method == "initialized":
        ready = True
    elif method == "thread/start":
        asks = (params.get("approvalPolicy"), params.get("sandbox"), params.get("approvalsReviewer")) == ("untrusted", "read-only", "user")
        told = str(params.get("developerInstructions"))   # how an approved write can happen, or that none can
        asks = asks and ("apply_patch" in told or "answer and read only" in told)
        send({"id": ident, "result": {"thread": {"id": "thread-1"}, **started_as(params)}} if ready and params.get("cwd") and asks else
             {"id": ident, "error": {"code": -32600, "message": "Not initialized"}})
    elif method == "mcpServerStatus/list":
        send({"id": ident, **server_list(params, off)})
    elif method == "experimentalFeature/list":
        log.write(json.dumps({"features_asked": params.get("threadId")}) + "\n"); log.flush()
        send({"id": ident, **feature_list(params)})
    elif method == "turn/start":
        log.write(json.dumps({"turn": True}) + "\n"); log.flush()
        text = params["input"][0]["text"]
        send({"id": ident, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        if "hang" in text:
            grandchild()
            note("item/agentMessage/delta", itemId="m1", delta="Thinking")
            stubborn = True
            continue
        if "unknown" in text:
            for number, method in ((71, "item/permissions/requestApproval"), (72, "item/tool/requestUserInput"),
                                   (73, "mcpServer/elicitation/request"), (74, "execCommandApproval")):
                send({"id": number, "method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "t9"}})
                answers.append("error" in json.loads(sys.stdin.readline()))
            note("item/agentMessage/delta", itemId="m1", delta="Refused." if all(answers) else "Granted.")
        elif "write" in text:
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
    # This release ships answer and read only. The action path (cards, guards, permits) is kept behind the switch and
    # the tests written for it still run with it on; the tests of the shipped behaviour switch it off themselves.
    monkeypatch.setattr(_shipped_client, 'CHAT_ACTIONS', True)
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
    monkeypatch.setattr(acp_client, '_CODEX_CONFIG_TOP', tmp_path)   # the walk upward ends at the test's own folder
    for name, row in acp_client._NOT_YET.items():   # their ACP path is kept and tested here; the shipped table has no row for them
        monkeypatch.setitem(acp_client.AGENTS, name, row)
    monkeypatch.setenv('FAKE_AGENT_LOG', str(log))
    (tmp_path / 'USERPROFILE' / '.codex').mkdir()
    (tmp_path / 'USERPROFILE' / '.codex' / 'config.toml').write_text(CODEX_CONFIG, encoding='utf-8')
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
    pid = lines[1]['pid']
    grandchild = next(line['grandchild'] for line in lines if isinstance(line, dict) and 'grandchild' in line)
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
    assert [name for name in seen['archhub'] if not name.startswith('ARCHHUB_TEST_')] == ['ARCHHUB_CHAT_OWNED']
    assert seen['user'] is True                                          # the one name added says: started by ArchHub for chat


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


def _waiter(title='Write sheets.txt', kind='edit', session='s1', raw=None):
    """The agent's side of one Approve card, as approve_card runs it; returns (thread, outcome list)."""
    from nodelang import acp_client
    ask = acp_client.approve_card('Codex', time.monotonic() + 30)
    request = {'sessionId': session, 'toolCall': {'toolCallId': 't', 'title': title, 'kind': kind,
                                                  'rawInput': {'n': time.monotonic_ns(), **(raw or {})}},
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


@pytest.mark.parametrize('config', ['[mcp_servers."a & b"]\ncommand = "x"\n', 'mcp_servers = 3\n', '[mcp_servers\n', None])
def test_codex_is_not_started_when_its_config_cannot_be_read_for_server_names(installed, tmp_path, monkeypatch, config):
    from nodelang import acp_client
    install, log = installed
    install('codex')
    path = tmp_path / 'USERPROFILE' / '.codex' / 'config.toml'
    path.unlink()
    if config is None:
        path.mkdir()                                                     # there, but not readable as a file
    else:
        path.write_text(config, encoding='utf-8')
    started = []
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda *a, **kw: started.append(a))
    with pytest.raises(ValueError, match='own connectors could not be switched off'):
        acp_client.ask('codex', 'how many sheets?')
    assert not started and not log.exists() and not acp_client._SESSIONS


def test_codex_reads_server_names_from_codex_home_and_from_the_launch_folder(installed, tmp_path, monkeypatch):
    from nodelang import acp_client
    home, cwd = tmp_path / 'codex-home', tmp_path / 'work' / 'deep'
    (cwd / '.codex').mkdir(parents=True)
    (tmp_path / 'work' / '.codex').mkdir()
    (tmp_path / 'work' / '.codex' / 'config.toml').write_text('[mcp_servers.from_above]\ncommand = "y"\n', encoding='utf-8')
    home.mkdir()
    (home / 'config.toml').write_text('[mcp_servers.from_home]\ncommand = "x"\n', encoding='utf-8')
    (cwd / '.codex' / 'config.toml').write_text('[mcp_servers.from_project]\nurl = "http://127.0.0.1:1/mcp"\n', encoding='utf-8')
    monkeypatch.setenv('CODEX_HOME', str(home))
    words = acp_client._codex_servers_off(cwd)
    assert words == ['-c', 'mcp_servers.from_home.enabled=false', '-c', 'mcp_servers.from_project.enabled=false',
                     '-c', 'mcp_servers.from_above.enabled=false']        # every folder above the launch folder too


@pytest.mark.parametrize('leak', ['one stays on', 'a new one appears', 'more pages', 'list fails'])
def test_codex_gets_no_turn_while_one_of_its_own_connectors_is_live_in_the_thread(installed, monkeypatch, leak):
    """Codex's own MCP servers are outside the file and command cards. They are switched off for the thread and the
    thread's effective inventory is read back from the same process before any message is sent."""
    from nodelang import acp_client
    install, log = installed
    install('codex')
    monkeypatch.setenv('FAKE_CODEX_LEAK', leak)
    with pytest.raises(acp_client.AcpRefused, match='own connectors'):
        acp_client.ask('codex', 'how many sheets?')
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert {'turn': True} not in lines and not acp_client._SESSIONS      # nothing was sent to it
    pid = lines[1]['pid']
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_codex_connectors_are_found_and_switched_off_inside_its_own_process(installed, monkeypatch):
    from nodelang import acp_client
    install, log = installed
    install('codex')
    started = []
    real = acp_client.subprocess.Popen
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda argv, **kw: (started.append(list(argv)), real(argv, **kw))[1])
    assert acp_client.ask('codex', 'how many sheets?')['text'] == 'There are 12 sheets.'
    assert len(started) == 1 and started[0][2:] == CODEX_ARGS            # one process: no separate listing run
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert {'turn': True} in lines and {'early_inventory': True} not in lines   # no inventory before the thread exists


def test_claude_and_codex_start_without_their_own_connectors():
    from nodelang import acp_client
    assert '--strict-mcp-config' in acp_client.AGENTS['claude']['args'] and '--mcp-config' not in acp_client.AGENTS['claude']['args']
    assert acp_client.start_command.__doc__                               # Codex: see CODEX_ARGS and the thread check


@pytest.mark.parametrize('title, kind, session, raw', [
    ('canvas.run', 'execute', 's1', {'command': 'canvas.run'}),                       # a Bash command spelled like the Canvas replay
    ('write', 'edit', 's1', {'code': 'doc.Delete()', 'host': 'revit', 'path': 'a.rvt'}),   # the host-write replay's shape
    ('Write sheets.txt', 'edit', 'archhub-remote-relay', {}),                         # the reserved relay session id
    ('revit.delete', 'execute', 's1', {'connector': 'revit', 'arguments': {'ids': [1]}, 'node': {'params': {}}, 'feeds': {}}),
    ('canvas.run', 'edit', 'archhub-remote-relay', {'arguments': {}, 'code': 'x', 'host': 'acad'})])
def test_what_an_agent_calls_its_action_never_chooses_what_approve_does(monkeypatch, title, kind, session, raw):
    """An agent's title, command, input and session id are shown and digested. Approve only ever permits that one request."""
    from nodelang import acp_client, hook_decision
    assert acp_client._ClaudeCode(None, None)._call('t', 'Bash', {'command': 'canvas.run'})['title'] == 'canvas.run'
    replayed, written, real = [], [], hook_decision._write_holds
    monkeypatch.setattr(hook_decision, '_release_ask', lambda replay: replayed.append(replay))
    monkeypatch.setattr(hook_decision, '_write_holds', lambda path, data: (
        written.extend(row['status'] for row in data['holds'].values()), real(path, data))[1])
    worker, outcome = _waiter(title, kind, session, raw)
    card = _pending_card()
    row = json.loads(hook_decision._ask_path(os.environ).read_text(encoding='utf-8'))['holds'][card['id']]
    assert row['replay']['kind'] == 'permit' and card['who'] == 'Codex' and title in card['summary']
    assert hook_decision.ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    worker.join(10)
    assert outcome == [{'outcome': 'selected', 'optionId': 'yes'}]
    assert replayed == [] and 'releasing' not in written                 # nothing was run here; no half-way state
    assert hook_decision._take_permit(card['input_digest'], os.environ) is False   # the one grant went to the waiter


@pytest.mark.parametrize('init', [{'mcp_servers': [{'name': 'plugin:data:hex', 'status': 'connected'}], 'tools': ['Read', 'Write']},
                                  {'mcp_servers': [], 'tools': ['Read', 'mcp__claude_ai_Slack__send']},
                                  {'mcp_servers': 'unknown', 'tools': ['Read']}, {'tools': None, 'mcp_servers': []},
                                  {'tools': ['Read']}, {'mcp_servers': []}, {}])   # a missing key is unknown, not empty
def test_claude_gets_no_turn_when_its_start_line_names_a_connector(installed, monkeypatch, init):
    """Claude's own first line lists its tools and MCP servers: plugin and managed ones too. Any connector ends the session."""
    from nodelang import acp_client
    install, log = installed
    install('claude')
    monkeypatch.setenv('FAKE_CLAUDE_INIT', json.dumps(init))
    with pytest.raises(acp_client.AcpRefused, match='own connectors'):
        acp_client.ask('claude', 'how many sheets?')
    assert not acp_client._SESSIONS
    pid = json.loads(log.read_text(encoding='utf-8').splitlines()[1])['pid']
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_claude_with_only_its_built_in_tools_is_asked(installed, monkeypatch):
    from nodelang import acp_client
    install, _log = installed
    install('claude')
    monkeypatch.setenv('FAKE_CLAUDE_INIT', json.dumps({'mcp_servers': [], 'tools': ['Read', 'Write', 'Bash']}))
    assert acp_client.ask('claude', 'how many sheets?')['text'] == 'There are 12 sheets.'


@pytest.mark.parametrize('body', [{'prompt': '@gemini how many sheets?'}, {'prompt': '@opencode how many sheets?'},
                                  {'prompt': '@goose how many sheets?'}, {'prompt': 'how many sheets?', 'agent': 'gemini'},
                                  {'prompt': 'how many sheets?', 'agent': 'OpenCode'}, {'prompt': '@claude and @gemini: sheets?'},
                                  {'prompt': '@codex how many sheets?'}, {'prompt': 'how many sheets?', 'agent': 'codex'},
                                  {'prompt': 'how many sheets?', 'agent': 'Codex'}, {'prompt': '@claude and @codex: sheets?'}])
def test_only_claude_is_offered_in_chat_and_the_others_start_nothing(installed, monkeypatch, body):
    """Until 2026-11-17 this read "only claude and codex". An independent review found Codex is still given tools that
    act with no request (hosted web search, helper agents, a background memory job), so Codex is not admitted either."""
    from nodelang import acp_client, nograph_server
    install, log = installed
    for name in ('claude', 'codex', 'gemini', 'opencode', 'goose'):
        install(name)
    for name in acp_client._NOT_YET:
        monkeypatch.delitem(acp_client.AGENTS, name)                     # the table as it ships
    assert sorted(acp_client.AGENTS) == ['claude'] and 'codex' in acp_client._NOT_YET
    started = []
    monkeypatch.setattr(acp_client.subprocess, 'Popen', lambda *a, **kw: started.append(a))
    with pytest.raises(ValueError, match='is not available in chat yet') as refused:
        nograph_server._chat(body, lambda text: None)
    if 'codex' in json.dumps(body).lower():
        assert str(refused.value) == 'Codex is not available in chat yet.'   # one plain line, and nothing was started
    for name in acp_client._NOT_YET:
        with pytest.raises(ValueError, match='is not available in chat yet'):
            acp_client.ask(name, 'how many sheets?')
        with pytest.raises(ValueError, match='is not available in chat yet'):
            acp_client.start_command(name)
    assert not started and not log.exists() and not acp_client._SESSIONS


@pytest.mark.parametrize('answer', [{'mcpServers': [{'name': 'plugin:data:hex', 'status': 'connected'}]},
                                    {'mcpServers': None}, {}, {'servers': []}])
def test_claude_is_sent_no_message_until_it_has_said_it_has_no_connector(installed, monkeypatch, answer):
    from nodelang import acp_client
    install, log = installed
    install('claude')
    monkeypatch.setenv('FAKE_CLAUDE_MCP', json.dumps(answer))
    with pytest.raises(acp_client.AcpRefused, match='own connectors'):
        acp_client.ask('claude', 'how many sheets?')
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert {'asked': 'mcp_status'} in lines and {'user': True} not in lines   # the message never reached it
    assert not acp_client._SESSIONS


def test_claude_gets_the_message_only_after_its_connector_answer(installed):
    from nodelang import acp_client
    install, log = installed
    install('claude')
    assert acp_client.ask('claude', 'how many sheets?')['text'] == 'There are 12 sheets.'
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert lines.index({'asked': 'mcp_status'}) < lines.index({'user': True})


def test_a_chat_agent_keeps_the_users_guard_hooks_and_is_marked_as_started_for_chat():
    """The user's PreToolUse guards (scope, install, delete, ledger) must run for a chat agent as for any other session:
    hooks are never switched off. Only the session-lifecycle hook skips, on the one name set on the child."""
    from nodelang import acp_client
    words = list(acp_client.AGENTS['claude']['args']) + list(acp_client._CODEX_NO_PLUGINS)
    assert '--settings' not in words and 'disableAllHooks' not in ' '.join(words) and 'hooks' not in words and '--bare' not in words
    assert acp_client.child_environment()['ARCHHUB_CHAT_OWNED'] == '1'


@pytest.mark.parametrize('argv, stdin', [(['--session-start', '--vendor', 'claude'], b'{"session_id": "s1", "cwd": "C:/x"}'),
                                         (['--vendor', 'claude'], b'{"session_id": "s1", "hook_event_name": "Stop"}'),
                                         (['--vendor', 'codex'], b'{"session_id": "s1", "hook_event_name": "Stop"}')])
def test_the_session_hook_does_nothing_for_an_agent_started_for_chat(monkeypatch, capsys, argv, stdin):
    """SessionStart would declare the agent in the Workshop; Stop would ask the Workshop what it still owes. Neither for chat."""
    import io
    import types
    from nodelang import native_agent_hooks, native_stop_hook
    called = []
    monkeypatch.setattr(native_agent_hooks, 'declare_session', lambda *a, **kw: called.append('declare'))
    monkeypatch.setattr(native_stop_hook, 'query_stop', lambda *a, **kw: called.append('stop') or {})
    monkeypatch.setattr(sys, 'argv', ['native_stop_hook.py', *argv])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(stdin)))
    monkeypatch.setenv('ARCHHUB_CHAT_OWNED', '1')
    assert native_stop_hook.main() == 0
    assert called == [] and capsys.readouterr().out.strip() == '{}'


def test_codex_gets_no_turn_when_its_config_names_other_servers_after_it_started(installed, monkeypatch):
    from nodelang import acp_client
    install, log = installed
    install('codex')
    real, calls = acp_client._codex_servers_off, []

    def changing(cwd):
        calls.append(cwd)
        return real(cwd) + (['-c', 'mcp_servers.added_meanwhile.enabled=false'] if len(calls) > 1 else [])
    monkeypatch.setattr(acp_client, '_codex_servers_off', changing)
    with pytest.raises(acp_client.AcpRefused, match='config changed while it started'):
        acp_client.ask('codex', 'how many sheets?')
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert len(calls) == 2 and {'turn': True} not in lines and not acp_client._SESSIONS


_REAL_PATH = os.environ.get('PATH', '')   # as it was when this file was loaded, before any test replaced it
_CANARY = 'import pathlib, sys\npathlib.Path(sys.argv[1]).write_text("started")\nfor line in sys.stdin:\n    pass\n'


@pytest.fixture
def canaries(tmp_path, monkeypatch):
    """The REAL Codex with two real MCP servers in its config: a stdio program that writes a file when it is started,
    and a loopback HTTP listener that counts every connection. A temporary CODEX_HOME holds only that config."""
    import shutil
    import socket
    if not shutil.which('codex', path=_REAL_PATH):
        pytest.skip('Codex is not installed on this PC')
    from nodelang import acp_client
    monkeypatch.setitem(acp_client.AGENTS, 'codex', acp_client._NOT_YET['codex'])   # its row is kept and tested, not offered
    home, marker, script = tmp_path / 'codex-home', tmp_path / 'canary-started.txt', tmp_path / 'canary.py'
    home.mkdir()
    script.write_text(_CANARY, encoding='utf-8')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)
    listener.settimeout(0.2)
    hits, done = [], threading.Event()

    def accept():
        while not done.is_set():
            try:
                connection, _peer = listener.accept()
            except OSError:
                continue
            hits.append(time.monotonic())
            connection.close()
    threading.Thread(target=accept, daemon=True).start()
    (home / 'config.toml').write_text(
        '[mcp_servers.canary_stdio]\ncommand = %s\nargs = [%s, %s]\n[mcp_servers.canary_http]\nurl = "http://127.0.0.1:%d/mcp"\n'
        % (json.dumps(sys.executable), json.dumps(str(script)), json.dumps(str(marker)), listener.getsockname()[1]), encoding='utf-8')
    monkeypatch.setenv('CODEX_HOME', str(home))
    monkeypatch.setenv('PATH', _REAL_PATH)
    monkeypatch.setattr(acp_client, '_CODEX_CONFIG_TOP', tmp_path)   # not the real folders above the test's own
    yield marker, hits
    done.set()
    listener.close()


def test_the_real_codex_starts_none_of_its_configured_servers_before_or_after_the_thread(canaries, tmp_path):
    """Launch, initialize, thread/start and the thread inventory, exactly as chat does them. No model turn."""
    from nodelang import acp_client
    marker, hits = canaries
    session = acp_client.AgentSession('codex', tmp_path / 'launch')
    try:
        session.start()
        assert session.session_id                                        # the thread exists and its inventory was read
        time.sleep(4)
    finally:
        session.close()
    assert not marker.exists() and hits == []                            # the program never ran; nothing ever connected


def test_the_same_canaries_do_start_when_the_inventory_is_asked_before_they_are_off(canaries, tmp_path):
    """The old launch order, kept as the proof that the canaries are real: no per-server switch, inventory with no thread."""
    import subprocess
    from nodelang import acp_client, workshop_transport
    marker, hits = canaries
    (tmp_path / 'launch').mkdir()
    child = subprocess.Popen(acp_client.start_command('codex')[0], cwd=tmp_path / 'launch', stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=acp_client.child_environment(),
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    job = workshop_transport._OwnedProcessJob(child)
    try:
        for line in ({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'archhub', 'title': 'ArchHub', 'version': '1'}}},
                     {'method': 'initialized'},
                     {'id': 2, 'method': 'mcpServerStatus/list', 'params': {'detail': 'toolsAndAuthOnly'}}):
            child.stdin.write((json.dumps(line) + '\n').encode())
            child.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (marker.exists() and hits):
            time.sleep(0.2)
    finally:
        job.close()
        child.wait(10)
    assert marker.exists() and hits                                      # both were started by that one call


_FAKE_GUARD = r"""
import json, os, sys
event = json.load(sys.stdin)
with open(os.environ["FAKE_GUARD_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), event.get("tool_name"), event.get("tool_input")]) + "\n")
text = json.dumps(event.get("tool_input")).replace("\\\\", "/")
name = os.path.basename(sys.argv[0])
if name == "agent_scope_gate.py" and ("20.CLIENTS" in text or "60.PERSONAL" in text):
    sys.stderr.write("SCOPE: this path is outside the lane")
    sys.exit(2)
if name == "install_guard.py" and "pip install" in text:
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "INSTALL: installs are not admitted here"}}))
if name == "delete_guard.py" and "Remove-Item" in text:
    print(json.dumps({"decision": "block", "reason": "DELETE: this would delete the user's data"}))
"""


@pytest.fixture
def guards(tmp_path, monkeypatch):
    """The user's own PreToolUse guards, as his Claude settings list them: here four small real scripts under those names."""
    folder, log = tmp_path / 'hooks', tmp_path / 'guards.log'
    folder.mkdir()
    groups = []
    for name, matcher in (('ledger_guard.py', 'Bash|PowerShell|Write|Edit'), ('install_guard.py', 'Bash|PowerShell|Write|Edit'),
                          ('agent_scope_gate.py', 'Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell'),
                          ('delete_guard.py', 'Bash|PowerShell'), ('delete_guard.py', 'Bash|PowerShell'),
                          ('hook_decision.py', ''), ('gen_register.py', 'Write')):
        (folder / name).write_text(_FAKE_GUARD, encoding='utf-8')
        groups.append({'matcher': matcher, 'hooks': [{'type': 'command', 'timeout': 30,
                                                      'command': '"%s" "%s" --vendor claude' % (sys.executable, folder / name)}]})
    (tmp_path / 'USERPROFILE' / '.claude').mkdir()
    (tmp_path / 'USERPROFILE' / '.claude' / 'settings.json').write_text(json.dumps({'hooks': {'PreToolUse': groups}}), encoding='utf-8')
    monkeypatch.setenv('FAKE_GUARD_LOG', str(log))
    return log


def _asks(agent, tool, data):
    """The permission request each dialect hands the card for one native request, built by the dialect itself."""
    from nodelang import acp_client
    heard = []
    if agent == 'claude':
        dialect = acp_client._ClaudeCode(lambda value: None, heard.append)
        dialect.checked = True
        dialect.heard({'type': 'control_request', 'request_id': 'r1', 'request': {
            'subtype': 'can_use_tool', 'tool_name': tool, 'input': data, 'tool_use_id': 't1'}})
    else:
        dialect = acp_client._Codex(lambda value: None, heard.append)
        if tool == 'Bash':
            dialect.heard({'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': 'th', 'turnId': 'tu', 'itemId': 'i1', 'command': data['command'], 'cwd': 'C:/work'}})
        else:
            dialect.heard({'method': 'item/started', 'params': {'threadId': 'th', 'turnId': 'tu', 'item': {
                'type': 'fileChange', 'id': 'i1', 'status': 'inProgress', 'changes': [{'path': data['file_path'], 'kind': 'add'}]}}})
            dialect.heard({'id': 7, 'method': 'item/fileChange/requestApproval', 'params': {
                'threadId': 'th', 'turnId': 'tu', 'itemId': 'i1', 'startedAtMs': 1}})
    return [message for message in heard if message.get('method') == 'session/request_permission'][0]['params']


@pytest.mark.parametrize('agent', ['claude', 'codex'])
@pytest.mark.parametrize('tool, data, reason', [
    ('Write', {'file_path': 'C:\\Users\\x\\00.ARCHUB\\20.CLIENTS\\a\\notes.txt', 'content': 'hi'}, 'SCOPE: this path is outside the lane'),
    ('Write', {'file_path': 'C:/Users/x/00.ARCHUB/60.PERSONAL/cv.txt', 'content': 'hi'}, 'SCOPE: this path is outside the lane'),
    ('Bash', {'command': 'pip install requests'}, 'INSTALL: installs are not admitted here'),
    ('Bash', {'command': 'Remove-Item -Recurse C:/Users/x/Documents'}, "DELETE: this would delete the user's data")])
def test_a_guarded_action_is_refused_with_the_guards_reason_before_any_card(guards, agent, tool, data, reason):
    from nodelang import acp_client, hook_decision
    request = _asks(agent, tool, data)
    request['options'] = [{'optionId': 'yes', 'kind': 'allow_once'}, {'optionId': 'no', 'kind': 'reject_once'}]
    shown = []
    outcome = acp_client.approve_card('Codex', time.monotonic() + 20, cwd='C:/work', refused=shown.append)(request, {}, {})
    assert outcome == {'outcome': 'selected', 'optionId': 'no', 'reason': reason}
    assert hook_decision.ask_reviews() == [] and shown == [reason]       # no card exists that could grant it
    ran = [json.loads(line)[0] for line in guards.read_text(encoding='utf-8').splitlines()]
    assert 'hook_decision.py' not in ran and 'gen_register.py' not in ran and ran.count('delete_guard.py') <= 1


@pytest.mark.parametrize('agent, who', [('claude', 'Claude Code'), ('codex', 'Codex')])
def test_a_normal_write_passes_the_guards_and_raises_exactly_one_card(installed, guards, agent, who):
    from nodelang import hook_decision, nograph_server
    install, _log = installed
    install(agent)
    done = {}
    worker = threading.Thread(target=lambda: done.update(result=nograph_server._chat(
        {'prompt': '@%s write the sheet list' % agent}, lambda text: None)), daemon=True)
    worker.start()
    card = _pending_card()
    time.sleep(0.5)
    assert len(hook_decision.ask_reviews()) == 1 and card['who'] == who   # one card, the agent's
    hook_decision.ask_apply(card['id'], card['input_digest'], 'approve')
    worker.join(20)
    assert done['result']['text'] == 'File written.'
    assert 'agent_scope_gate.py' in [json.loads(line)[0] for line in guards.read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_a_guard_refusal_reaches_the_agent_and_the_thread_and_no_card_is_shown(installed, guards, monkeypatch, agent):
    from nodelang import hook_decision, nograph_server
    install, _log = installed
    install(agent)
    source = (guards.parent / 'hooks' / 'agent_scope_gate.py')
    source.write_text(source.read_text(encoding='utf-8').replace('"20.CLIENTS" in text', '"sheets" in text.lower()'), encoding='utf-8')
    result = nograph_server._chat({'prompt': '@%s write the sheet list' % agent}, lambda text: None)
    assert result['text'] == 'File not written.' and hook_decision.ask_reviews() == []
    step = next(s for s in result['steps'] if 'sheets.txt' in s['tool'])
    assert step['status'] == 'failed' and 'refused: SCOPE: this path is outside the lane' in step['tool']


def test_no_guard_list_and_a_guard_that_cannot_run_do_not_refuse(tmp_path, guards):
    from nodelang import acp_client
    assert acp_client._guards_refuse([('Write', {'file_path': 'C:/work/a.txt'})], 'C:/work', 's1') == ''
    settings = tmp_path / 'USERPROFILE' / '.claude' / 'settings.json'
    settings.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': '', 'hooks': [
        {'type': 'command', 'command': '"%s" "%s"' % (tmp_path / 'missing.exe', tmp_path / 'hooks' / 'install_guard.py')}]}]}}),
        encoding='utf-8')
    assert acp_client._guards_refuse([('Bash', {'command': 'pip install x'})], 'C:/work', 's1') == ''   # as the CLI itself treats it
    settings.unlink()
    assert acp_client._guards_refuse([('Bash', {'command': 'pip install x'})], 'C:/work', 's1') == ''


def test_this_release_ships_answer_and_read_only():
    assert _SHIPPED_CHAT_ACTIONS is False


@pytest.mark.parametrize('agent', ['claude', 'codex'])
@pytest.mark.parametrize('tool, data', [('Write', {'file_path': 'C:/work/a.txt', 'content': 'hi'}), ('Edit', {'file_path': 'C:/work/a.txt'}),
                                        ('Bash', {'command': 'pip install requests'}), ('Bash', {'command': 'dir'}),
                                        ('PowerShell', {'command': 'cmd /c rmdir /s /q C:/work'}), ('WebFetch', {'url': 'https://example.com'}),
                                        ('mcp__x__send', {'text': 'hi'}), ('SomethingNew', {})])
def test_every_request_from_a_chat_agent_is_denied_and_nothing_else_happens(guards, tmp_path, monkeypatch, agent, tool, data):
    """No card, no guard process, no permit, nothing in the approval store: the answer is ours and immediate."""
    from nodelang import acp_client, hook_decision
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    reached = []
    monkeypatch.setattr(hook_decision, 'agent_permission', lambda *a, **kw: reached.append('permit') or ('', ''))
    monkeypatch.setattr(acp_client, '_guards_refuse', lambda *a, **kw: reached.append('guards') or '')
    if agent == 'codex':   # Codex asks in two shapes only: a command, or a file change
        tool, data = ('Write', data) if 'file_path' in data else ('Bash', {'command': data.get('command', 'x')})
    request = _asks(agent, tool, data)
    request['options'] = [{'optionId': 'yes', 'kind': 'allow_once'}, {'optionId': 'no', 'kind': 'reject_once'}]
    began = time.monotonic()
    outcome = acp_client.approve_card('Codex', time.monotonic() + 20, cwd=str(tmp_path))(request, {}, {})
    assert outcome == {'outcome': 'selected', 'optionId': 'no', 'reason': 'Actions are not available in chat yet. I can read and answer.'}
    assert time.monotonic() - began < 1 and reached == []
    assert not hook_decision._ask_path(os.environ).exists() and not guards.exists()   # no store write, no guard process


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_a_chat_agent_that_asks_to_act_is_told_no_and_finishes_its_turn(installed, guards, tmp_path, monkeypatch, agent):
    from nodelang import acp_client, hook_decision, nograph_server
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    install, log = installed
    install(agent)
    result = nograph_server._chat({'prompt': '@%s write the sheet list' % agent}, lambda text: None)
    assert result['text'] == 'File not written.'                         # the agent was told no and finished its turn
    step = next(s for s in result['steps'] if 'sheets.txt' in s['tool'])
    assert step['status'] == 'failed' and step['tool'].endswith('refused: Actions are not available in chat yet. I can read and answer.')
    assert hook_decision.ask_reviews() == [] and not hook_decision._ask_path(os.environ).exists() and not guards.exists()
    folder = tmp_path / 'LOCALAPPDATA' / 'ArchHub' / 'agents' / agent
    assert not folder.exists() or list(folder.iterdir()) == []           # no file changed
    assert nograph_server._chat({'prompt': '@%s how many sheets?' % agent}, lambda text: None)['text'] == 'There are 12 sheets.'
    assert len([line for line in log.read_text(encoding='utf-8').splitlines() if line.startswith('[')]) == 1   # the same session


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_a_request_kind_the_client_does_not_know_is_refused_not_left_waiting(installed, monkeypatch, agent):
    from nodelang import acp_client, hook_decision
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    install, _log = installed
    install(agent)
    assert acp_client.ask(agent, 'try an unknown request')['text'] == 'Refused.'
    assert not hook_decision._ask_path(os.environ).exists()


def test_codex_is_told_that_chat_is_answer_and_read_only(monkeypatch):
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    sent = []
    dialect = acp_client._Codex(sent.append, lambda value: None)
    dialect.say({'id': 2, 'method': 'session/new', 'params': {'cwd': 'C:/work'}})
    start = sent[0]['params']
    assert 'answer and read only' in start['developerInstructions'] and 'apply_patch' not in start['developerInstructions']
    assert (start['approvalPolicy'], start['sandbox'], start['approvalsReviewer']) == ('untrusted', 'read-only', 'user')


def test_claude_is_started_with_only_its_reading_tools_while_chat_grants_no_action(installed, monkeypatch):
    """Answering every request with No is not enough: a CLI has tools that never ask. Measured on Claude Code 2.1.325
    with every request denied: CronCreate scheduled a task, and Bash ran a command the user's own allow rule names."""
    from nodelang import acp_client
    install, log = installed
    install('claude')
    assert acp_client.start_command('claude')[0][2:] == CLAUDE_ARGS      # with actions on: the CLI as it is
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    words = acp_client.start_command('claude')[0][2:]
    assert words[:-1] == CLAUDE_ARGS + ['--tools', 'Read,Glob,Grep', '--append-system-prompt']
    assert 'answer and read only' in words[-1]
    assert acp_client.ask('claude', 'how many sheets?')['text'] == 'There are 12 sheets.'
    assert json.loads(log.read_text(encoding='utf-8').splitlines()[0]) == words   # the CLI was started with exactly these


@pytest.mark.parametrize('tools', [['Read', 'Write', 'Bash'], ['Read', 'Glob', 'Grep', 'CronCreate'],
                                   ['Glob', 'Grep', 'Read', 'SomethingNew'], ['Read', {'name': 'Bash'}]])
def test_claude_gets_no_turn_when_its_start_line_lists_a_tool_that_acts(installed, monkeypatch, tools):
    """--tools is the request; Claude's own first line is the proof. Any tool beyond the three that read ends the session."""
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    install, log = installed
    install('claude')
    monkeypatch.setenv('FAKE_CLAUDE_INIT', json.dumps({'mcp_servers': [], 'tools': tools}))
    with pytest.raises(acp_client.AcpRefused, match='tools that act'):
        acp_client.ask('claude', 'how many sheets?')
    assert not acp_client._SESSIONS
    pid = json.loads(log.read_text(encoding='utf-8').splitlines()[1])['pid']
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_codex_is_started_with_no_shell_and_nothing_that_acts_while_chat_grants_no_action(installed, monkeypatch):
    """Codex's shell is its only way to read, run or write outside a file change, so chat with Codex is answer only."""
    from nodelang import acp_client
    install, log = installed
    install('codex')
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    words = acp_client.start_command('codex')[0][2:]
    off = [words[at + 1] for at, word in enumerate(words[:-1]) if word == '--disable']
    assert off[:2] == ['plugins', 'apps'] and words[-1] == 'app-server'
    assert {'shell_tool', 'code_mode_host', 'multi_agent', 'computer_use', 'browser_use', 'image_generation', 'view_image',
            'goals', 'sleep_tool', 'in_app_local_automation'} <= set(off)
    assert 'hooks' not in off                                            # the user's hooks stay on
    assert acp_client.ask('codex', 'how many sheets?')['text'] == 'There are 12 sheets.'
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert lines.index({'features_asked': 'thread-1'}) < lines.index({'turn': True})   # the thread's own list, read first


@pytest.mark.parametrize('leak, said', [
    ('its shell stays on', 'shell_tool'), ('a feature is not listed', 'goals'),
    ('features fail', 'could not be listed'), ('features are not a list', 'could not be listed'),
    ('it does not ask first', 'did not start as asked'), ('it may write', 'did not start as asked'),
    ('it has the network', 'did not start as asked'), ('it does not say how it started', 'did not start as asked')])
def test_codex_gets_no_turn_unless_its_own_answers_prove_it_cannot_act(installed, monkeypatch, leak, said):
    """The start words are the request. Codex's own answers are the proof: thread/start says it asks first and may only
    read, and the thread's feature list says every feature that acts is off. Anything else: nothing is sent to it."""
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    install, log = installed
    install('codex')
    monkeypatch.setenv('FAKE_CODEX_LEAK', leak)
    with pytest.raises(acp_client.AcpRefused, match=said):
        acp_client.ask('codex', 'how many sheets?')
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert {'turn': True} not in lines and not acp_client._SESSIONS      # nothing was sent to it
    pid = lines[1]['pid']
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_codex_is_told_to_say_that_it_cannot_read_files_in_chat(monkeypatch):
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    sent = []
    acp_client._Codex(sent.append, lambda value: None).say({'id': 2, 'method': 'session/new', 'params': {'cwd': 'C:/work'}})
    assert 'Codex cannot read files in chat yet' in sent[0]['params']['developerInstructions']


def test_the_real_codex_proves_it_cannot_act_before_it_is_asked_anything(canaries, tmp_path, monkeypatch):
    """Launch, thread/start, inventory and feature list against the REAL Codex, as answer-only chat does them. No model turn."""
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    session = acp_client.AgentSession('codex', tmp_path / 'launch')
    try:
        session.start()
        assert session.session_id                                        # every gate passed on Codex's own answers
        said = session.transport.dialect.features
        assert [name for name in ('plugins', 'apps', *acp_client._CODEX_ACTING) if said[name] is not False] == []
        assert said['hooks'] is True                                     # the user's hooks stay on
    finally:
        session.close()


def test_the_real_codex_is_refused_when_its_shell_was_left_on(canaries, tmp_path, monkeypatch):
    """The proof is real: started without the word that switches its shell off, Codex's own list says so."""
    from nodelang import acp_client
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)
    real = acp_client.start_command

    def shell_left_on(agent):
        argv, fallback, speaks = real(agent)
        at = argv.index('shell_tool')
        return argv[:at - 1] + argv[at + 1:], fallback, speaks
    monkeypatch.setattr(acp_client, 'start_command', shell_left_on)
    session = acp_client.AgentSession('codex', tmp_path / 'launch')
    try:
        with pytest.raises(acp_client.AcpRefused, match='shell_tool'):
            session.start()
    finally:
        session.close()


def test_the_users_own_hook_makes_no_card_for_an_agent_started_for_chat(monkeypatch):
    """ArchHub's decision hook runs inside a chat agent as one of the user's hooks. With Ask first on, a call outside
    his folders becomes an Approve card there. For an agent started for chat it must not: chat grants no action."""
    from nodelang import hook_decision
    hook_decision.write_permissions({'runMode': 'Ask first'})
    call = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'session_id': 's1', 'cwd': 'C:/elsewhere',
            'tool_input': {'file_path': 'C:/elsewhere/notes.txt', 'content': 'one'}}
    asked = hook_decision.decide(call, 'claude')
    assert asked['verdict'] == 'ask' and asked.get('hold') and len(hook_decision.ask_reviews()) == 1   # any other session: a card
    monkeypatch.setenv('ARCHHUB_CHAT_OWNED', '1')
    owned = hook_decision.decide({**call, 'tool_input': {'file_path': 'C:/elsewhere/notes.txt', 'content': 'two'}}, 'claude')
    assert owned['verdict'] == 'ask' and 'hold' not in owned             # still asked: the chat client answers No
    assert len(hook_decision.ask_reviews()) == 1                         # and no card was made for it
    assert hook_decision.render(owned, 'claude')['hookSpecificOutput']['permissionDecision'] == 'ask'


def test_claude_and_codex_start_as_the_installed_cli_never_an_adapter_or_a_permission_skip():
    from nodelang import acp_client
    for agent in ('claude', 'codex'):
        row = {**acp_client._NOT_YET, **acp_client.AGENTS}[agent]        # Codex's row is kept, not offered
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
    assert argv[2:] == ([w for w in CODEX_ARGS if not w.startswith(('-c', 'mcp_servers.'))] if agent == 'codex'
                        else list(acp_client.AGENTS[agent]['args']))   # the per-server words are added at start
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
