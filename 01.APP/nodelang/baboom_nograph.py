"""BABOOM without the graph: the packaged Goose brain (ACP) joined to the Workshop like any agent.

The old boot attached BABOOM through a signed session against the graph runtime
(baboom_attach) and then started goose_runtime. NOGRAPH keeps the brain and drops the graph:
  - goose_runtime.GooseRuntime runs the pinned goose.exe over ACP with the archhub-agent
    connector and the read-only host tools, exactly as before;
  - goose_adapter.GooseAdapter.ask runs one turn (tools and skills, not a bare router reply);
  - BABOOM declares itself in the Workshop, so @BABOOM and @everyone reach it, and its
    answer is posted back to the sender in the same thread;
  - the composer's "BABOOM chooses" route asks the same brain (nograph_server._router_chat);
  - the companion window (baboom_native_companion) runs on BaboomNativeHost over NoGraphTransport.
Startup follows settings/baboom.json {"startup": "on"|"off"}; it starts off the request path.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# A tool turn on a free model takes longer than a chat line; the Workshop turn has its own budget.
BABOOM_NODE = {'id': 'baboom', 'params': {'model': 'openrouter/free', 'turn_seconds': 120}}
# The companion window's frames are leases; the host renews them every few seconds.
COMPANION_NODE = {'id': 'baboom.companion', 'params': {'frame_seconds': 12}}
_STATE = {'runtime': None, 'brain': None, 'error': '', 'turns': 0}


def startup_choice(state_dir):
    try:
        return json.loads((Path(state_dir) / 'settings' / 'baboom.json').read_text(encoding='utf-8')).get('startup', 'on')
    except (OSError, ValueError):
        return 'on'


def shows_as_choice(state_dir):
    """Where the companion lives: "Screen" (the pet on the desktop, default), "Tray" or "Hidden"."""
    try:
        choice = json.loads((Path(state_dir) / 'settings' / 'baboom.json').read_text(encoding='utf-8')).get('shows_as')
    except (OSError, ValueError, TypeError, AttributeError):
        choice = None
    return choice if choice in ('Screen', 'Tray', 'Hidden') else 'Screen'


def start(state_dir, app_root, url=''):
    """Start the Goose brain and join the Workshop. Never raises into the app; the reason is kept."""
    _STATE['state_dir'] = state_dir
    if startup_choice(state_dir) == 'off':
        _STATE['error'] = 'BABOOM is turned off in Settings.'
        return None
    try:
        from .goose_adapter import GooseAdapter
        from .goose_runtime import GooseRuntime
        runtime = GooseRuntime(app_root=app_root, state_dir=state_dir, control=None).start()
        _STATE.update(runtime=runtime, brain=GooseAdapter(runtime), error='')
    except Exception as refused:  # noqa: BLE001 - the face stays honest about why it cannot answer
        _STATE['error'] = 'BABOOM brain unavailable: %s' % refused
        print('  BABOOM     : %s' % _STATE['error'], flush=True)
        return None
    _join_workshop(state_dir, url)
    print('  BABOOM     : Goose brain running (ACP) and joined the Workshop', flush=True)
    return _STATE['brain']


def brain():
    return _STATE['brain']


def reason():
    return _STATE['error'] or 'BABOOM is starting.'


def ask(prompt, context=''):
    """One BABOOM turn with its tools; returns {'text', 'steps', 'via', 'actions'}."""
    current = _STATE['brain']
    if current is None:
        raise RuntimeError(reason())
    result = current.ask(prompt, context, BABOOM_NODE['params']['model'], turn_seconds=BABOOM_NODE['params']['turn_seconds'])
    # BABOOM's instructions (agent_composer._SYSTEM) answer as {"answer": ..., "actions": [...]}.
    # A tool turn can stream more than one such object; the last answer is BABOOM's reply.
    decoder, text, index, shaped = json.JSONDecoder(), result['text'].strip(), 0, None
    while index < len(text):
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            break
        if isinstance(value, dict) and isinstance(value.get('answer'), str):
            shaped = value
        index = end
        while index < len(text) and text[index].isspace():
            index += 1
    if shaped is not None:
        result = {**result, 'text': shaped['answer'], 'actions': shaped.get('actions') or []}
    return result


def _join_workshop(state_dir, url):
    from .workshop_mailbox import call
    import os
    import psutil
    from .nograph_server import JsonFile
    declared = call('declare', {'task': 'BABOOM: answers with its tools and skills', 'paths': [str(Path(state_dir))],
                                'status': 'working', 'request_id': 'BABOOM'}, {'goose/sessionID': 'baboom'})
    # Which declaration is the app's own BABOOM: this process, recorded by the app (agents cannot claim the name).
    import secrets
    _STATE['token'] = secrets.token_urlsafe(32)
    # Any process (the app, an agent's connector) reaches this BABOOM through the app's local turn door.
    JsonFile(Path(state_dir) / 'settings' / 'baboom-session.json', {}).write(
        {'session': declared['declaration']['session'], 'pid': os.getpid(), 'created_at': psutil.Process().create_time(),
         'url': url, 'token': _STATE['token']})


def _record(state_dir=None):
    import os
    import psutil
    root = Path(state_dir) if state_dir else Path(os.environ['LOCALAPPDATA']) / 'ArchHub'
    try:
        held = json.loads((root / 'settings' / 'baboom-session.json').read_text(encoding='utf-8'))
        alive = abs(psutil.Process(held['pid']).create_time() - held['created_at']) < 0.01
    except (OSError, ValueError, KeyError, psutil.Error) as missing:
        _STATE['record_error'] = 'no running BABOOM session (%s)' % missing
        return None
    _STATE['record_error'] = '' if alive else 'the BABOOM session belongs to a closed app'
    return held if alive else None


def own_session(state_dir=None):
    """The Workshop session key of the app's BABOOM, if it is running now."""
    held = _record(state_dir)
    return held['session'] if held else None


def accept_turn(token, text, message_id):
    """The app side of the turn door, which Workshop calls (workshop-apps.mjs): token-checked, answered in the thread."""
    import hmac
    if not _STATE.get('token') or not hmac.compare_digest(str(token or ''), _STATE['token']):
        return {'ok': False, 'error': 'BABOOM turn refused: wrong token.'}
    state, _channel, why = _adapter(None, text, message_id, ())
    return {'ok': state == 'delivered', 'error': why}


def _adapter(native_id, text, message_id, pids):
    """Workshop delivery to BABOOM: accepted now, answered in the thread when its turn ends."""
    if _STATE['brain'] is None:
        return 'failed', 'goose-acp', reason()
    threading.Thread(target=_answer, args=(text, message_id), name='archhub-baboom-turn', daemon=True).start()
    return 'delivered', 'goose-acp', ''


def _answer(text, message_id):
    import re
    from .workshop_mailbox import call
    sender = re.search(r'\[ArchHub Workshop message from (.+?) · id', text)
    to = sender.group(1) if sender else 'Ahmed'
    try:
        result = _turn(text)
        reply = result['text'] + ''.join('\n• %s: %s' % (s.get('tool'), s.get('status')) for s in result.get('steps', []))
    except Exception as refused:  # noqa: BLE001 - the sender sees why BABOOM could not answer
        reply = 'BABOOM could not answer: %s' % refused
    call('send', {'to': to, 'text': reply[:60000], 'reply_to': message_id}, {'goose/sessionID': 'baboom'})


class NoGraphTransport:
    """The companion's transport, answered from the running app instead of the graph.

    Frames are quiet (motion only): BABOOM looks busy while a turn runs, its orb lights when
    the Goose brain is up; asks and acts go to the same Goose brain as @BABOOM in the Workshop.
    """

    def __init__(self):
        self.agent_session_root = ''
        self.revision = 0

    def bind_agent_session(self, *, runtime, external_session_id, device_credential_provider):
        self.agent_session_root = own_session() or 'app:baboom'
        return {'agent_session': self.agent_session_root}

    def renew_runtime_presence(self):
        return {'agent_session': self.agent_session_root, 'runtime': 'baboom',
                'expires_at': time.time() + COMPANION_NODE['params']['frame_seconds']}

    def baboom_native_frame(self, *, response_timeout_seconds=None):
        from .application_machine_transport import BABOOM_NATIVE_FRAME_PROJECTION
        self.revision += 1
        ttl, now, up = COMPANION_NODE['params']['frame_seconds'], time.time(), _STATE['brain'] is not None
        context = {'revision': self.revision, 'brain': {'ok': up, 'facts': 1 if up else 0},
                   'work': {'blocked': 0, 'review': 0}, 'attention': {'blocked_obligations': 0},
                   'workshop': {'entry_count': 0}, 'meeting_notes': {'active_sessions': 0},
                   # Without it the companion falls back to "Tray" and hides the on-screen pet every frame.
                   'shows_as': shows_as_choice(_STATE.get('state_dir'))}
        directive = {'revision': self.revision, 'motion': 'working' if _STATE.get('turns') else 'idle',
                     'persona_form': 'baboom', 'message': '', 'compact_message': '', 'action': '',
                     'action_label': '', 'fingerprint': '', 'ttl_seconds': ttl}
        return {'projection': BABOOM_NATIVE_FRAME_PROJECTION, 'revision': self.revision, 'issued_at': now,
                'expires_at': now + ttl, 'context': context, 'directive': directive, 'report': None}

    def respond_baboom_command(self, *, utterance, on_progress=None):
        answer = _turn(utterance)
        return {'command': {'intent': 'ask', 'catalog': 'app:baboom-command-catalog:v1'},
                'response': {'kind': 'answer', 'summary': answer['text'], 'data': {'steps': answer.get('steps', [])}}}

    def execute_baboom_command(self, *, utterance):
        answer = _turn(utterance)
        return {'command': {'intent': 'ask', 'catalog': 'app:baboom-command-catalog:v1'},
                'kind': 'answer', 'summary': answer['text'] or 'BABOOM had nothing to add.'}

    def resolve_baboom_command(self, *, utterance):
        return {'catalog': 'app:baboom-command-catalog:v1', 'intent': 'ask', 'payload': utterance, 'revision': self.revision}

    def read_hosts_state(self):
        from .nograph_server import _SERVER
        return {'ok': True, 'hosts': (_SERVER._hosts.get() if _SERVER is not None else None) or []}

    def record_baboom_activity(self, *, app):
        return {'app': app, 'agent_session': self.agent_session_root, 'activity': 'app:baboom-activity:' + app,
                'expires_at': time.time() + 60.0, 'revision': self.revision}

    def record_baboom_steward_signal(self, *, fingerprint, source, summary):
        return {'signal': 'app:baboom-signal:' + fingerprint}


def _turn(utterance):
    _STATE['turns'] = _STATE.get('turns', 0) + 1
    try:
        return ask(utterance)
    finally:
        _STATE['turns'] -= 1


def companion_host():
    """The existing BaboomNativeHost over the no-graph transport; connected, not yet started."""
    from .baboom_native_companion import foreground_application_windows
    from .baboom_native_host import BaboomNativeHost
    host = BaboomNativeHost(NoGraphTransport(), external_session_id='founder-desktop-baboom',
                            device_credential_provider=lambda _request: {}, emit_steward_signals=False,
                            activity_provider=foreground_application_windows)
    host.connect()
    return host
