"""The one Agent Client Protocol (ACP) client: every installed agent answers in a session's thread through it.

Lifted from goose_adapter (its transport now lives here; Goose is one row of the table below). Behaviour taken
from ACP UI (MIT, read as reference): an agent table name -> {command, args}, a stdio pipe started through
`cmd /C` with no console window, and the agent's permission request turned into the user's decision.
From AionUi (Apache-2.0, as summarised by R&D res-051): an agent is offered only when its command is installed.
Nothing starts by itself: a session starts only because the user sent it a message.
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
ACP_NODE = {'id': 'agents.acp', 'params': {'start_seconds': 30, 'turn_seconds': 900, 'close_seconds': 2, 'card_poll_seconds': 0.2}}

# The start-command table, keyed by the agent registry's ids. First installed command wins; never a download.
# A Settings override (router.json agents.<id>.acp = {command, args}) replaces a row; see start_command().
AGENTS = {
    'claude': {'commands': ('claude-agent-acp', 'claude-code-acp'), 'args': ()},
    'codex': {'commands': ('codex-acp',), 'args': ()},
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


class AcpTransport:
    """One bounded JSON-RPC connection to an owned stdio process."""

    def __init__(self, process, *, label="The agent"):
        self.process = process
        self.label = label
        self.inbox = queue.Queue(maxsize=256)
        self.outbox = queue.Queue(maxsize=16)
        self.sequence = 0
        self.closed = False
        self.ended = threading.Event()   # the agent's stream ended (exit, broken pipe, oversized or bad line)
        self.failure = None
        self.reader = threading.Thread(target=self._read, name="archhub-acp-read", daemon=True)
        self.reader.start()
        self.writer = threading.Thread(target=self._write, name="archhub-acp-write", daemon=True)
        self.writer.start()

    def _write(self):
        try:
            while not self.closed:
                value = self.outbox.get()
                if value is None:
                    break
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
                self.inbox.put_nowait(value)
        except (OSError, ValueError, queue.Full) as error:
            self.failure = error
        finally:
            self.ended.set()

    def send(self, value):
        if self.closed:
            raise AcpRefused("The %s connection is closed." % self.label)
        try:
            self.outbox.put_nowait((json.dumps({"jsonrpc": "2.0", **value}) + "\n").encode())
        except queue.Full:
            raise AcpRefused("The %s connection closed; the request was not replayed." % self.label) from None

    def request(self, method, params, *, deadline, update=lambda _: None, stopped=lambda: False,
                response_error=lambda _: None, permission=_refuse_permission):
        """permission(request, params, tool_calls) -> ACP outcome; it may block (an Approve card) while the agent waits."""
        self.sequence += 1
        request_id = self.sequence
        tool_calls = {}
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
            if message.get("method"):
                if "id" in message:
                    if message["method"] == "session/request_permission":
                        outcome = permission(message.get("params") or {}, params, tool_calls)
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


def start_command(agent):
    """[argv, fallback argv or None] for an installed agent; refuses (names it) when it is not installed."""
    row = dict(AGENTS[agent])
    try:
        from .settings_owner import read_router_settings
        chosen = (read_router_settings()['agents'].get(agent) or {}).get('acp')
    except ValueError:
        chosen = None
    if chosen:
        row = {'commands': (chosen['command'],), 'args': tuple(chosen.get('args') or ())}
    found = next((path for path in map(shutil.which, row['commands']) if path), None)
    if found is None:
        raise ValueError('%s is not installed on this PC (looked for %s). Install it, then send again.'
                         % (label(agent), ' or '.join(row['commands'])))
    # npm installs agents as .cmd shims: run them through cmd /C like ACP UI; args come from this table only.
    head = [os.environ.get('COMSPEC') or 'cmd.exe', '/C', found] if found.lower().endswith(('.cmd', '.bat')) else [found]
    fallback = row.get('fallback_args')
    return head + list(row['args']), (head + list(fallback)) if fallback else None


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
        # 'connector' names the asking agent on the card (hook_decision._ask_who); no 'arguments' key, so Approve only permits.
        event = {'tool': title, 'input': {'connector': agent_label, 'input': call.get('rawInput')},
                 'vendor': agent_label, 'session': str(request.get('sessionId') or '')}
        digest = hook_decision._call_digest(event, action, 'agent')
        hold = hook_decision._remember(event, action, 'agent', digest, agent_label + ': ' + title, os.environ)
        options = {row.get('kind'): row.get('optionId') for row in request.get('options') or ()}
        if not hold:
            return {'outcome': 'cancelled'}
        path = hook_decision._ask_path(os.environ)
        while time.monotonic() < deadline and not stopped():
            status = (hook_decision._read_holds(path)['holds'].get(hold) or {}).get('status')
            if status == 'approved' and hook_decision._take_permit(digest, os.environ) and options.get('allow_once'):
                return {'outcome': 'selected', 'optionId': options['allow_once']}
            if status not in ('pending', 'releasing', 'approved'):
                break
            time.sleep(ACP_NODE['params']['card_poll_seconds'])
        else:
            if (hook_decision._read_holds(path)['holds'].get(hold) or {}).get('status') == 'pending':
                hook_decision.withdraw_approval(os.environ, hold, agent_label)   # out of time: nothing runs
        rejected = options.get('reject_once')
        return {'outcome': 'selected', 'optionId': rejected} if rejected else {'outcome': 'cancelled'}
    return permission


# -- one session per (agent, thread) ------------------------------------------------------------------------
class AgentSession:
    def __init__(self, agent, cwd):
        self.agent, self.label, self.cwd = agent, label(agent), str(cwd)
        self.transport, self.job, self.session_id = None, None, None
        self.lock = threading.Lock()

    def start(self):
        argv, fallback = start_command(self.agent)
        try:
            self._open(argv)
        except AcpRefused:
            if fallback is None:
                raise
            self._open(fallback)   # Gemini: --acp on newer builds, --experimental-acp on older ones
        return self

    def _open(self, command):
        try:
            self._connect(command)
        except BaseException:
            self.close()
            raise

    def _connect(self, command):
        Path(self.cwd).mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.transport = AcpTransport(process, label=self.label)
        from .workshop_transport import _OwnedProcessJob
        self.job = _OwnedProcessJob(process)   # the agent closes with the app
        deadline = time.monotonic() + ACP_NODE['params']['start_seconds']
        init = self.transport.request('initialize', {'protocolVersion': 1,
            'clientInfo': {'name': 'ArchHub', 'version': '1'},
            'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}},
            deadline=deadline)
        if init.get('protocolVersion') != 1:
            raise AcpRefused('%s speaks a different ACP version.' % self.label)
        # shortcut: no mcpServers are handed over; the agent keeps the ArchHub connector it is already registered with.
        session = self.transport.request('session/new', {'cwd': self.cwd, 'mcpServers': []}, deadline=deadline)
        if not isinstance(session.get('sessionId'), str) or not session['sessionId']:
            raise AcpRefused('%s did not open a session.' % self.label)
        self.session_id = session['sessionId']

    def ask(self, prompt, *, on_delta=lambda _t: None, on_step=lambda _s: None, stopped=lambda: False):
        if not self.lock.acquire(blocking=False):
            raise AcpRefused('%s is answering another message in this session. Wait for its answer.' % self.label)
        try:
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
            final = self.transport.request('session/prompt', {'sessionId': self.session_id,
                'prompt': [{'type': 'text', 'text': prompt}]}, deadline=deadline, update=update, stopped=stopped,
                permission=approve_card(self.label, deadline, lambda: stopped() or self.transport is None or self.transport.closed))
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
        try:
            if self.transport is not None:
                self.transport.close()
        finally:
            if self.job is not None:
                self.job.close()
            self.transport, self.job = None, None


_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


def ask(agent, prompt, *, task=None, on_delta=lambda _t: None, on_step=lambda _s: None, stopped=lambda: False):
    """One message to an installed agent; started for this thread on first use (only because the user sent it)."""
    from .user_paths import state_directory
    key = (agent, task or '')
    with _SESSIONS_LOCK:
        current = _SESSIONS.get(key)
        if current is None or current.transport is None or current.transport.closed:
            current = _SESSIONS[key] = AgentSession(agent, state_directory() / 'agents' / agent)
            fresh = True
        else:
            fresh = False
    if fresh:
        current.start()
    return {**current.ask(prompt, on_delta=on_delta, on_step=on_step, stopped=stopped), 'label': current.label}


def close_all():
    with _SESSIONS_LOCK:
        held = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in held:
        session.close()
