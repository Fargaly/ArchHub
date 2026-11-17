"""The one Agent Client Protocol (ACP) client: every installed agent answers in a session's thread through it.

Lifted from goose_adapter (its transport now lives here; Goose is one row of the table below). Behaviour taken
from ACP UI (MIT, read as reference): an agent table name -> {command, args}, a stdio pipe with no console window, and the agent's permission request turned into the user's decision.
From AionUi (Apache-2.0, as summarised by R&D res-051): an agent is offered only when its command is installed.
Nothing starts by itself: a session starts only because the user sent it a message.

Claude Code and Codex need no adapter: each installed CLI already has a structured stdio mode (`claude -p` with
stream-json in and out; `codex app-server`). A small dialect per CLI turns that mode's lines into the ACP messages
this client already reads, so the callbacks, the Approve card and the reply are the same for every agent.
The Claude mapping (which line is a text chunk, a tool call, a permission request, the end of a turn; tool titles
and kinds) follows @zed-industries/claude-agent-acp 0.23.1, Copyright 2022-2025 Zed Industries, Inc., Apache-2.0,
read as reference and rewritten here; that package is neither installed nor shipped. @zed-industries/codex-acp
0.16.0 (Apache-2.0) publishes only a launcher for a binary, so the Codex mapping follows Codex's own app-server schema.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .model_router import ModelRouteRefused

# The node of this client: how long an agent may take to start, and to finish one turn (an Approve card waits inside it).
ACP_NODE = {'id': 'agents.acp', 'params': {'start_seconds': 30, 'turn_seconds': 900, 'close_seconds': 2, 'card_poll_seconds': 0.2,
                                          'quiet_seconds': 10,     # no word for this long: the thread says "not responding"
                                          'inventory_rows': 500}}  # one page of an agent's own MCP servers; more is refused

# The start-command table, keyed by the agent registry's ids. First installed command wins; never a download.
# 'speaks' names the CLI's own stdio mode (a dialect below); a row without it speaks ACP itself.
# No row carries a flag that skips the agent's permission prompts: they come here and become the Approve card.
# Only this table starts an agent: an admitted command with a fixed ask policy. Settings cannot replace a row.
AGENTS = {
    'claude': {'commands': ('claude',), 'speaks': 'claude', 'args': (
        '-p', '--output-format', 'stream-json', '--input-format', 'stream-json', '--verbose',
        '--include-partial-messages', '--permission-prompt-tool', 'stdio', '--permission-mode', 'manual',
        '--strict-mcp-config')},   # with no --mcp-config: none of its own MCP servers
    'codex': {'commands': ('codex',), 'speaks': 'codex', 'args': ('app-server',)},
    'gemini': {'commands': ('gemini',), 'args': ('--acp',), 'fallback_args': ('--experimental-acp',)},
    'opencode': {'commands': ('opencode',), 'args': ('acp',)},
    'goose': {'commands': ('goose',), 'args': ('acp',)},
}


class AcpRefused(ModelRouteRefused):
    pass


class AcpResponseRefused(AcpRefused):
    """A complete remote refusal: the connection remains synchronised."""


def _refuse_permission(_permission, _request_params, _tool_calls):
    return {"outcome": "cancelled"}


def _update(session, **item):
    return {'method': 'session/update', 'params': {'sessionId': session, 'update': item}}


def _ask_permission(ident, session, call):
    return {'id': ident, 'method': 'session/request_permission', 'params': {'sessionId': session, 'toolCall': call,
            'options': [{'optionId': 'allow', 'name': 'Allow', 'kind': 'allow_once'},
                        {'optionId': 'reject', 'name': 'Reject', 'kind': 'reject_once'}]}}


def _allowed(message):
    return ((message.get('result') or {}).get('outcome') or {}).get('optionId') == 'allow'


class _ClaudeCode:
    """`claude -p --input-format stream-json --output-format stream-json`: its lines <-> ACP messages."""
    _KINDS = {'Bash': 'execute', 'PowerShell': 'execute', 'Read': 'read', 'Write': 'edit', 'Edit': 'edit',
              'NotebookEdit': 'edit', 'Glob': 'search', 'Grep': 'search', 'WebFetch': 'fetch', 'WebSearch': 'fetch',
              'Task': 'think', 'Agent': 'think'}

    _CONNECTORS = "Claude Code still has its own connectors (%s), so nothing was sent to it."

    def __init__(self, wire, hear):
        self.wire, self.hear, self.prompt, self.asked = wire, hear, None, {}
        self.checked = False   # its init line was read and names no MCP server and no mcp__ tool

    def _call(self, ident, name, data):
        data = data if isinstance(data, dict) else {}
        kind = self._KINDS.get(name, 'other')
        detail = next((str(data[key]) for key in ('command', 'description', 'file_path', 'pattern', 'url', 'query')
                       if data.get(key)), '')
        title = detail if detail and kind in ('execute', 'think') else ('%s %s' % (name, detail)).strip()
        return {'toolCallId': ident, 'title': title or 'Tool', 'kind': kind, 'rawInput': data}

    def say(self, message):
        method = message.get('method')
        if method in ('initialize', 'session/new'):   # the CLI is ready as started; it has one conversation per process
            self.hear({'id': message['id'], 'result': {'protocolVersion': 1, 'sessionId': 'claude'}})
        elif method == 'session/prompt':
            self.prompt = message['id']
            self.wire({'type': 'user', 'message': {'role': 'user', 'content': message['params']['prompt']},
                       'parent_tool_use_id': None, 'session_id': 'default'})
        elif message.get('id') in self.asked:         # the Approve card's decision on its permission request
            data = self.asked.pop(message['id'])
            self.wire({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': message['id'],
                       'response': {'behavior': 'allow', 'updatedInput': data} if _allowed(message) else
                                   {'behavior': 'deny', 'message': 'User refused permission to run tool'}}})

    def heard(self, line):
        kind, content = line.get('type'), (line.get('message') or {}).get('content')
        if kind == 'system' and line.get('subtype') == 'init':
            # Its own account of what it can use, plugin and managed connectors included (--strict-mcp-config is the
            # request; this is the proof). A key that is present must be a list; a connector ends the session.
            servers, tools = line.get('mcp_servers', []), line.get('tools', [])
            if type(servers) is not list or type(tools) is not list:
                self.hear({'refuse': self._CONNECTORS % 'its tool list could not be read'})
            else:
                named = [str(row.get('name') if isinstance(row, dict) else row) for row in servers] + [
                    str(tool) for tool in tools if str(tool).startswith('mcp__')]
                if named:
                    self.hear({'refuse': self._CONNECTORS % ', '.join(named)[:200]})
                else:
                    self.checked = True
        elif not self.checked and kind in ('stream_event', 'assistant', 'user', 'control_request', 'result'):
            self.hear({'refuse': self._CONNECTORS % 'it answered before saying what it can use'})
        elif kind == 'stream_event':
            delta = (line.get('event') or {}).get('delta') or {}
            if delta.get('type') == 'text_delta' and line.get('parent_tool_use_id') is None:
                self.hear(_update('claude', sessionUpdate='agent_message_chunk',
                                  content={'type': 'text', 'text': delta.get('text')}))
        elif kind in ('assistant', 'user') and isinstance(content, list):
            for block in content:   # the text of a whole assistant message was already streamed above
                block = block if isinstance(block, dict) else {}
                if kind == 'assistant' and block.get('type') in ('tool_use', 'server_tool_use', 'mcp_tool_use'):
                    self.hear(_update('claude', sessionUpdate='tool_call', status='pending',
                                      **self._call(block.get('id'), str(block.get('name')), block.get('input'))))
                elif kind == 'user' and str(block.get('type')).endswith('tool_result'):
                    self.hear(_update('claude', sessionUpdate='tool_call_update', toolCallId=block.get('tool_use_id'),
                                      status='failed' if block.get('is_error') else 'completed'))
        elif kind == 'control_request':
            request, ident = line.get('request') or {}, line.get('request_id')
            if request.get('subtype') == 'can_use_tool':
                self.asked[ident] = request.get('input')
                self.hear(_ask_permission(ident, 'claude', self._call(
                    request.get('tool_use_id'), str(request.get('tool_name')), request.get('input'))))
            else:
                self.wire({'type': 'control_response', 'response': {'subtype': 'error', 'request_id': ident,
                                                                    'error': 'Capability not admitted'}})
        elif kind == 'result' and self.prompt is not None:
            ident, self.prompt = self.prompt, None
            if line.get('subtype') == 'success' and not line.get('is_error'):
                self.hear({'id': ident, 'result': {
                    'stopReason': 'max_tokens' if line.get('stop_reason') == 'max_tokens' else 'end_turn'}})
            else:
                self.hear({'id': ident, 'error': {'code': -32603, 'message': str(line.get('result') or line.get('subtype'))}})


class _Codex:
    """`codex app-server` (its own JSON-RPC over stdio): threads, turns and items <-> ACP messages."""
    _STEPS = {'commandExecution': 'execute', 'fileChange': 'edit', 'mcpToolCall': 'other', 'dynamicToolCall': 'other',
              'webSearch': 'fetch', 'collabAgentToolCall': 'think'}

    # Measured on Codex 0.163 / Windows, policy untrusted + read-only: an approved shell command still runs inside the
    # read-only sandbox and writes nothing; an approved file change (apply_patch) is applied. So Codex is told to
    # change files with its file tool: the card comes before the write, Deny leaves nothing, Approve writes.
    _WRITES = ('Shell commands in this session run in a read-only sandbox and cannot write files. To create, change or '
               'delete a file, use the apply_patch file tool; the user is asked to approve each change.')

    # Measured on Codex 0.163: plugins and apps go off at start (start_command). Its own MCP servers cannot be removed
    # by a start flag, but thread/start config {mcp_servers: {name: {enabled: false}}} switches them off for the
    # thread, and mcpServerStatus/list with the threadId then reports each one 'disabled' with no tools.
    _INVENTORY = {'detail': 'toolsAndAuthOnly', 'limit': ACP_NODE['params']['inventory_rows']}
    _CONNECTORS = "Codex still has its own connectors in this thread (%s), so nothing was sent to it."

    def __init__(self, wire, hear):
        self.wire, self.hear, self.sent, self.prompt, self.asked = wire, hear, {}, None, set()
        self.opening, self.thread = None, None

    def _servers(self, line):
        """The server names of one complete inventory answer; None (and the session is refused) when it is not one."""
        result = line.get('result') or {}
        rows = result.get('data')
        if type(rows) is not list or result.get('nextCursor') or not all(
                isinstance(row, dict) and type(row.get('name')) is str for row in rows):
            self.hear({'refuse': self._CONNECTORS % 'the list was not complete'})
            return None
        return [row['name'] for row in rows]

    def say(self, message):
        method, ident, params = message.get('method'), message.get('id'), message.get('params') or {}
        if method == 'initialize':
            self.sent[ident] = method
            self.wire({'id': ident, 'method': 'initialize',
                       'params': {'clientInfo': {'name': 'archhub', 'title': 'ArchHub', 'version': '1'}}})
        elif method == 'session/new':   # first: which of its own MCP servers does this process have (same config, same cwd)
            self.opening = (ident, params)
            self.sent['servers'] = 'servers'
            self.wire({'id': 'servers', 'method': 'mcpServerStatus/list', 'params': dict(self._INVENTORY)})
        elif method == 'session/prompt':
            self.sent[ident], self.prompt = method, ident
            self.wire({'id': ident, 'method': 'turn/start', 'params': {'threadId': params.get('sessionId'), 'input': [
                {'type': 'text', 'text': part.get('text')} for part in params.get('prompt') or ()]}})
        elif ident in self.asked:       # the Approve card's decision on its approval request
            self.asked.discard(ident)
            self.wire({'id': ident, 'result': {'decision': 'accept' if _allowed(message) else 'decline'}})
        else:
            self.wire(message)          # this client's refusal of a request it does not admit

    def _step(self, thread, item, update):
        kind = self._STEPS.get(item.get('type'))
        if kind is None:
            return
        title = (item.get('command') or item.get('query') or ' '.join(filter(None, (item.get('server'), item.get('tool'))))
                 or ' '.join(['Edit'] + [str(change.get('path')) for change in item.get('changes') or ()
                                         if isinstance(change, dict)]))
        status = {'completed': 'completed', 'failed': 'failed', 'declined': 'failed'}.get(item.get('status'), 'in_progress')
        self.hear(_update(thread, sessionUpdate=update, toolCallId=item.get('id'), title=str(title), kind=kind, status=status))

    def heard(self, line):
        method, ident, params = line.get('method'), line.get('id'), line.get('params') or {}
        thread = params.get('threadId')
        if method is None:
            asked = self.sent.pop(ident, None)
            if 'error' in line and asked in ('servers', 'verify'):
                self.hear({'refuse': self._CONNECTORS % 'they could not be listed'})
            elif 'error' in line:
                self.prompt = None if asked == 'session/prompt' else self.prompt
                self.hear(line)
            elif asked == 'servers':   # never the user's ambient Codex config: it asks, it may only read, a person
                names = self._servers(line)   # decides; and every MCP server it has is off for this thread
                if names is not None:
                    ident, params = self.opening
                    self.sent[ident] = 'session/new'
                    self.wire({'id': ident, 'method': 'thread/start', 'params': {
                        'cwd': params.get('cwd'), 'approvalPolicy': 'untrusted', 'sandbox': 'read-only',
                        'approvalsReviewer': 'user', 'developerInstructions': self._WRITES,
                        'config': {'mcp_servers': {name: {'enabled': False} for name in names}}}})
            elif asked == 'verify':    # the thread's effective inventory, read back before any message is sent
                if self._servers(line) is not None:
                    live = [row['name'] for row in line['result']['data']
                            if row.get('runtimeStatus') != 'disabled' or row.get('tools')]
                    if live:
                        self.hear({'refuse': self._CONNECTORS % ', '.join(live)[:200]})
                    else:
                        self.hear({'id': self.opening[0], 'result': {'sessionId': self.thread}})
            elif asked == 'initialize':
                self.wire({'method': 'initialized'})
                self.hear({'id': ident, 'result': {'protocolVersion': 1}})
            elif asked == 'session/new':
                self.thread = ((line.get('result') or {}).get('thread') or {}).get('id')
                self.sent['verify'] = 'verify'
                self.wire({'id': 'verify', 'method': 'mcpServerStatus/list',
                           'params': {**self._INVENTORY, 'threadId': self.thread}})
            # the answer to turn/start only says the turn began; turn/completed settles the prompt
        elif method == 'item/agentMessage/delta':
            self.hear(_update(thread, sessionUpdate='agent_message_chunk', content={'type': 'text', 'text': params.get('delta')}))
        elif method in ('item/started', 'item/completed'):
            self._step(thread, params.get('item') or {}, 'tool_call' if method == 'item/started' else 'tool_call_update')
        elif method == 'turn/completed' and self.prompt is not None:
            ident, self.prompt = self.prompt, None
            turn = params.get('turn') or {}
            if turn.get('status') == 'completed':
                self.hear({'id': ident, 'result': {'stopReason': 'end_turn'}})
            else:
                self.hear({'id': ident, 'error': {'code': -32603, 'message': str((turn.get('error') or {}).get('message') or turn.get('status'))}})
        elif method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            self.asked.add(ident)
            command = method == 'item/commandExecution/requestApproval'
            self.hear(_ask_permission(ident, thread, {
                'toolCallId': params.get('itemId'), 'title': params.get('command') or params.get('reason'),
                'kind': 'execute' if command else 'edit',
                'rawInput': {key: params[key] for key in ('command', 'cwd', 'reason', 'grantRoot') if params.get(key)}}))
        elif method and 'id' in line:
            self.hear(line)             # any other request: the client answers "not admitted"


_DIALECTS = {'claude': _ClaudeCode, 'codex': _Codex}


class AcpTransport:
    """One bounded JSON-RPC connection to an owned stdio process."""

    def __init__(self, process, *, label="The agent", speaks=None, cancelled=lambda: False):
        self.process = process
        self.label = label
        self.cancelled = cancelled   # the owning session's stop flag: once true, not one more byte is written
        self.dialect = None   # set below, after the inbox it feeds exists
        self.inbox = queue.Queue(maxsize=256)
        self.outbox = queue.Queue(maxsize=16)
        self.sequence = 0
        self.closed = False
        self.ended = threading.Event()   # the agent's stream ended (exit, broken pipe, oversized or bad line)
        self.failure = None
        if speaks:
            self.dialect = _DIALECTS[speaks](self._wire, self.inbox.put_nowait)
        self.reader = threading.Thread(target=self._read, name="archhub-acp-read", daemon=True)
        self.reader.start()
        self.writer = threading.Thread(target=self._write, name="archhub-acp-write", daemon=True)
        self.writer.start()

    def _write(self):
        try:
            while not self.closed:
                value = self.outbox.get()
                if value is None or self.cancelled():   # the single write point: a stopped session writes nothing,
                    break                                # whoever queued the line (a request, a reply, the dialect)
                self.process.stdin.write(value)
                self.process.stdin.flush()
        except (OSError, ValueError) as error:
            self.failure = error
            self.ended.set()

    def _read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(1_048_577)
                if not line or len(line) > 1_048_576:
                    break
                value = json.loads(line)
                if self.dialect is None:
                    self.inbox.put_nowait(value)
                elif isinstance(value, dict):
                    self.dialect.heard(value)
        except (OSError, ValueError, queue.Full) as error:
            self.failure = error
        finally:
            self.ended.set()

    def _wire(self, value):
        if self.cancelled():
            raise AcpRefused("Stopped by you")
        try:
            self.outbox.put_nowait((json.dumps(value) + "\n").encode())
        except queue.Full:
            raise AcpRefused("The %s connection closed; the request was not replayed." % self.label) from None

    def send(self, value):
        if self.closed:
            raise AcpRefused("The %s connection is closed." % self.label)
        if self.dialect is None:
            self._wire({"jsonrpc": "2.0", **value})
        else:
            self.dialect.say(value)

    def request(self, method, params, *, deadline, update=lambda _: None, stopped=lambda: False,
                response_error=lambda _: None, permission=_refuse_permission):
        """permission(request, params, tool_calls) -> ACP outcome; it may block (an Approve card) while the agent waits."""
        self.sequence += 1
        request_id = self.sequence
        tool_calls = {}
        if stopped():
            raise AcpRefused("Stopped by you")
        self.send({"id": request_id, "method": method, "params": params})
        while not self.closed:
            if stopped():
                raise AcpRefused("Stopped by you")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpRefused("%s did not answer in time; the request was not replayed." % self.label)
            try:
                message = self.inbox.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                if self.ended.is_set() and self.inbox.empty():
                    raise AcpRefused("The %s connection closed; the request was not replayed." % self.label) from self.failure
                continue
            if not isinstance(message, dict):
                raise AcpRefused("The %s connection closed; the request was not replayed." % self.label)
            if "refuse" in message:   # the dialect found the agent in a state it must not be asked in; the session ends
                raise AcpRefused(str(message["refuse"]))
            if message.get("method"):
                if "id" in message:
                    if message["method"] == "session/request_permission":
                        outcome = permission(message.get("params") or {}, params, tool_calls)
                        if stopped():
                            raise AcpRefused("Stopped by you")
                        self.send({"id": message["id"], "result": {"outcome": outcome}})
                    else:
                        self.send({"id": message["id"], "error": {"code": -32601, "message": "Capability not admitted"}})
                elif message["method"] == "session/update":
                    notification = message.get("params") or {}
                    item = notification.get("update") or {}
                    if item.get("sessionUpdate") == "tool_call":
                        tool_calls[(notification.get("sessionId"), item.get("toolCallId"))] = item
                    update(notification)
                continue
            if message.get("id") != request_id:
                raise AcpRefused("%s returned an unexpected response identity." % self.label)
            if "error" in message:
                response_error(message["error"])
                # Provider diagnostics may contain credentials. Only the typed
                # failure crosses into the face, never the provider's raw text.
                raise AcpResponseRefused("%s could not complete this request. No action was approved." % self.label)
            result = message.get("result")
            if not isinstance(result, dict):
                raise AcpRefused("%s returned an invalid response." % self.label)
            return result
        raise AcpRefused("The %s connection is closed." % self.label)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=ACP_NODE['params']['close_seconds'])
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=ACP_NODE['params']['close_seconds'])
        self.reader.join(timeout=ACP_NODE['params']['close_seconds'])
        if not self.outbox.full():   # a full outbox means the writer is mid-write; it stops on `closed`
            self.outbox.put_nowait(None)
        self.writer.join(timeout=ACP_NODE['params']['close_seconds'])
        self.process.stdin.close()
        self.process.stdout.close()


# -- the agent table: who can be addressed, how each one starts -----------------------------------------
def label(agent):
    from .agent_runtime_registry import RUNTIMES
    return {'claude': 'Claude Code', 'goose': 'Goose'}.get(agent) or RUNTIMES.get(agent, {}).get('label', agent)


def agent_for(handle):
    """The table row an @handle names (its id or its label, e.g. @claude, @claude-code), else None."""
    handle = str(handle or '').casefold()
    for agent in AGENTS:
        if handle in (agent, re.sub(r'[^a-z0-9]+', '-', label(agent).casefold()).strip('-')):
            return agent
    return None


def child_environment():
    """The boundary: the agent is the user's own CLI, so it gets the user's environment (its login, PATH, proxy),
    minus what ArchHub put there for itself: every ARCHHUB_* name (state folders, the cloud token, test markers)
    and the launcher's two Qt switches. Nothing is added."""
    return {name: value for name, value in os.environ.items()
            if not name.upper().startswith('ARCHHUB_') and name.upper() not in ('QTWEBENGINE_CHROMIUM_FLAGS', 'QT_OPENGL')}


_CODEX_NO_PLUGINS = ['--disable', 'plugins', '--disable', 'apps']
_INTERPRETERS = {'.js': 'node'}        # what runs the script an npm shim points to
_UNSAFE_PATH = re.compile(r'[%^&|"\']')


def _launcher(agent, found):
    """The program behind an installed command, as an argv list for CreateProcess: cmd.exe never runs.
    npm installs a .cmd shim that only starts `node <script>` or an .exe beside it; that target is started directly.
    A shim that does not point to exactly one such program is refused, not handed to a shell."""
    refused = ValueError("%s's launcher (%s) could not be resolved to a program. Reinstall %s, then send again."
                         % (label(agent), Path(found).name, label(agent)))
    if found.lower().endswith(('.cmd', '.bat')):
        try:
            text = Path(found).read_text(encoding='utf-8', errors='replace')[:16384]
        except OSError:
            raise refused from None
        targets = re.findall(r'"%dp0%\\([^"%]+)"[ \t]+%\*', text)
        target = Path(found).parent / targets[0] if len(targets) == 1 else None
        if target is None or not target.is_file():
            raise refused
        runner = _INTERPRETERS.get(target.suffix.lower())
        if target.suffix.lower() == '.exe':
            argv = [str(target)]
        elif runner:
            beside = Path(found).parent / (runner + '.exe')
            program = str(beside) if beside.is_file() else runner if Path(runner).is_absolute() else shutil.which(runner)
            if not program or not program.lower().endswith('.exe'):
                raise refused
            argv = [program, str(target)]
        else:
            raise refused
    else:
        argv = [found]
    if any(_UNSAFE_PATH.search(part) for part in argv):
        raise ValueError('%s is installed in a folder whose name has %% ^ & | or a quote; it is not started from there.'
                         % label(agent))
    return argv


def start_command(agent):
    """(argv, fallback argv or None, the dialect it speaks or None) for an installed agent; refuses (names it) when it is not installed."""
    row = AGENTS[agent]
    found = next((path for path in map(shutil.which, row['commands']) if path), None)
    if found is None:
        raise ValueError('%s is not installed on this PC (looked for %s). Install it, then send again.'
                         % (label(agent), ' or '.join(row['commands'])))
    head = _launcher(agent, found)
    fallback = row.get('fallback_args')
    args = list(row['args'])
    if row.get('speaks') == 'codex':
        args[-1:-1] = _CODEX_NO_PLUGINS   # its own MCP servers are switched off per thread and checked: _Codex
    return head + args, (head + list(fallback)) if fallback else None, row.get('speaks')


# -- an Approve card for a permission request -------------------------------------------------------------
_ACTIONS = {'edit': 'write', 'delete': 'delete', 'move': 'write', 'execute': 'shell', 'fetch': 'send'}


def approve_card(agent_label, deadline, stopped=lambda: False):
    """The agent's permission request becomes the one Approve card (hook_decision); the agent waits for the decision."""
    from . import hook_decision

    def permission(request, _params, tool_calls):
        call = request.get('toolCall') or {}
        seen = tool_calls.get((request.get('sessionId'), call.get('toolCallId'))) or {}
        title = str(call.get('title') or seen.get('title') or 'Agent action')[:200]
        action = _ACTIONS.get(call.get('kind') or seen.get('kind'), 'write')
        # The owner's permit-only entry: what the agent calls its action is shown, never used to choose what Approve does.
        hold, digest = hook_decision.agent_permission(os.environ, agent_label, title, action, call.get('rawInput'),
                                                      request.get('sessionId'))
        options = {row.get('kind'): row.get('optionId') for row in request.get('options') or ()}
        if not hold:
            return {'outcome': 'cancelled'}
        while time.monotonic() < deadline and not stopped():
            try:
                status = hook_decision.approval_status(os.environ, hold)
            except OSError:   # the file could not be read just now: unknown, not a denial; read again
                time.sleep(ACP_NODE['params']['card_poll_seconds'])
                continue
            if status == 'approved' and hook_decision._take_permit(digest, os.environ) and options.get('allow_once'):
                return {'outcome': 'selected', 'optionId': options['allow_once']}
            if status not in ('pending', 'releasing', 'approved'):
                break
            time.sleep(ACP_NODE['params']['card_poll_seconds'])
        else:
            # out of time: nothing runs. An unreadable file here raises: the turn fails and its agent is closed.
            if hook_decision.approval_status(os.environ, hold) == 'pending':
                hook_decision.withdraw_approval(os.environ, hold, agent_label)
        rejected = options.get('reject_once')
        return {'outcome': 'selected', 'optionId': rejected} if rejected else {'outcome': 'cancelled'}
    return permission


# -- one session per (agent, thread) ------------------------------------------------------------------------
class AgentSession:
    def __init__(self, agent, cwd):
        self.agent, self.label, self.cwd = agent, label(agent), str(cwd)
        self.transport, self.job, self.session_id = None, None, None
        self.lock = threading.Lock()
        self.starting = threading.Lock()     # one start per session: a second send on the same key waits here
        self.ready = False
        self.cancelled = threading.Event()   # set by close/Stop/app close and never cleared: Resume cannot revive it

    def _stopped(self, stopped):
        return lambda: self.cancelled.is_set() or stopped()

    def _check(self, stopped=lambda: False):
        if self.cancelled.is_set() or stopped():
            raise AcpRefused('Stopped by you')

    def start(self, stopped=lambda: False):
        stopped = self._stopped(stopped)
        argv, fallback, self.speaks = start_command(self.agent)
        try:
            self._open(argv, stopped)
        except AcpRefused:
            if fallback is None or stopped():
                raise
            self._open(fallback, stopped)   # Gemini: --acp on newer builds, --experimental-acp on older ones
        self.ready = True
        return self

    def _open(self, command, stopped):
        try:
            self._connect(command, stopped)
        except BaseException:
            self._release()   # not close(): Gemini's second start command may still be tried
            raise

    def _connect(self, command, stopped):
        self._check(stopped)                 # before the launch
        Path(self.cwd).mkdir(parents=True, exist_ok=True)
        windows = os.name == 'nt'
        # Started suspended, put in its job, then resumed: nothing it starts can be outside the job that ends it.
        process = subprocess.Popen(command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=child_environment(),
                                   creationflags=(subprocess.CREATE_NO_WINDOW | 0x4) if windows else 0)   # 0x4 CREATE_SUSPENDED
        try:
            from .workshop_transport import _OwnedProcessJob
            self.job = _OwnedProcessJob(process)   # the agent and everything under it close with the session and the app
            self._check(stopped)             # before the resume: a start stopped meanwhile never runs one instruction
            if windows:
                import ctypes
                resume = ctypes.WinDLL('ntdll').NtResumeProcess
                resume.argtypes = [ctypes.c_void_p]
                if resume(int(process._handle)):
                    raise AcpRefused('%s could not be started.' % self.label)
            self.transport = AcpTransport(process, label=self.label, speaks=self.speaks, cancelled=self.cancelled.is_set)
            self._check(stopped)             # close() may have run between the two lines above and seen no transport
        except BaseException:
            process.kill()   # no orphan on any way out; _open then closes the job
            raise
        deadline = time.monotonic() + ACP_NODE['params']['start_seconds']
        init = self.transport.request('initialize', {'protocolVersion': 1,
            'clientInfo': {'name': 'ArchHub', 'version': '1'},
            'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}},
            deadline=deadline, stopped=stopped)
        if init.get('protocolVersion') != 1:
            raise AcpRefused('%s speaks a different ACP version.' % self.label)
        # shortcut: no mcpServers are handed over; the agent keeps the ArchHub connector it is already registered with.
        session = self.transport.request('session/new', {'cwd': self.cwd, 'mcpServers': []}, deadline=deadline, stopped=stopped)
        if not isinstance(session.get('sessionId'), str) or not session['sessionId']:
            raise AcpRefused('%s did not open a session.' % self.label)
        self.session_id = session['sessionId']

    def ask(self, prompt, *, on_delta=lambda _t: None, on_step=lambda _s: None, stopped=lambda: False):
        if not self.lock.acquire(blocking=False):
            raise AcpRefused('%s is answering another message in this session. Wait for its answer.' % self.label)
        try:
            stopped, transport = self._stopped(stopped), self.transport
            if transport is None:
                self.cancelled.set()
            self._check()
            deadline = time.monotonic() + ACP_NODE['params']['turn_seconds']
            chunks, steps = [], {}

            def update(params):
                if params.get('sessionId') != self.session_id:
                    return
                item = params.get('update') or {}
                kind = item.get('sessionUpdate')
                if kind == 'agent_message_chunk' and (item.get('content') or {}).get('type') == 'text':
                    text = str(item['content'].get('text') or '')
                    chunks.append(text)
                    if sum(map(len, chunks)) > 256_000:
                        raise AcpRefused("%s's answer exceeded its display limit." % self.label)
                    on_delta(text)
                elif kind in ('tool_call', 'tool_call_update'):
                    row = steps.setdefault(item.get('toolCallId'), {'id': str(item.get('toolCallId') or ''),
                                                                    'tool': str(item.get('title') or 'Tool')[:4000]})
                    if item.get('title'):
                        row['tool'] = str(item['title'])[:4000]
                    row['status'] = {'completed': 'ok', 'failed': 'failed'}.get(item.get('status'), 'running')
                    on_step(dict(row))
            final = transport.request('session/prompt', {'sessionId': self.session_id,
                'prompt': [{'type': 'text', 'text': prompt}]}, deadline=deadline, update=update, stopped=stopped,
                permission=approve_card(self.label, deadline, lambda: stopped() or transport.closed))
            text = ''.join(chunks).strip()
            if final.get('stopReason') not in ('end_turn', 'max_tokens') or not text:
                raise AcpResponseRefused('%s stopped before it answered. No action was approved.' % self.label)
            return {'text': text, 'steps': list(steps.values())}
        except AcpResponseRefused:
            raise
        except BaseException:
            self.close()   # a broken stream cannot carry the next message; the next send starts it again
            raise
        finally:
            self.lock.release()

    def close(self):
        self.cancelled.set()   # first, and for good: a start still under way sees it at its next step
        self._release()

    def _release(self):
        try:   # the job first: a CLI behind its .cmd shim outlives the shim and would hold the pipe (and this close) open
            if self.job is not None:
                self.job.close()
        finally:
            try:
                if self.transport is not None:
                    self.transport.close()
            finally:
                self.transport, self.job = None, None


_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


def ask(agent, prompt, *, task=None, on_delta=lambda _t: None, on_step=lambda _s: None, stopped=lambda: False,
        cancelled=lambda: False):
    """One message to an installed agent; started for this thread on first use (only because the user sent it).
    `cancelled` is the caller's irreversible stop for this one request (the server: Stop or app close since the
    request was admitted). When true, no session is registered, launched or resumed, and nothing is sent."""
    from .user_paths import state_directory
    key = (agent, task or '')
    halted = lambda: cancelled() or stopped()
    with _SESSIONS_LOCK:   # registration: one session object per key; a stopped one is never used again
        if cancelled():
            raise AcpRefused('Stopped by you')
        current = _SESSIONS.get(key)
        if current is None or current.cancelled.is_set():
            current = _SESSIONS[key] = AgentSession(agent, state_directory() / 'agents' / agent)
    try:
        with current.starting:   # start and publication: a second send on this key waits, then finds it ready
            if not current.ready:
                current.start(halted)
    except BaseException:
        current.close()
        with _SESSIONS_LOCK:
            if _SESSIONS.get(key) is current:
                del _SESSIONS[key]
        raise
    return {**current.ask(prompt, on_delta=on_delta, on_step=on_step, stopped=halted), 'label': current.label}


def close_all():
    with _SESSIONS_LOCK:
        held = list(_SESSIONS.values())
        _SESSIONS.clear()
        for session in held:   # every one is stopped before the first is cleaned up: a slow close frees no start
            session.cancelled.set()
    for session in held:
        session.close()
