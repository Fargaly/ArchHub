"""Agent events projected through the ONE Workshop activity log; no prompt/tool content."""
from datetime import datetime
from contextlib import closing
import hashlib
import json
import logging
import re
import sqlite3
import time

from .baboom_persona import speech
from .user_paths import state_directory

REACTIONS = {'thinking': ('think', 'Thinking.'), 'editing': ('cast', 'Editing.'),
             'testing': ('ponder', 'Testing.'), 'waiting': ('ponder', 'Waiting for your decision.'),
             'success': ('cast', 'The agent turn ended.'), 'error': ('ponder', 'The agent reported a failure.')}
_EVENTS = {'UserPromptSubmit': 'thinking', 'beforeSubmitPrompt': 'thinking', 'task_started': 'thinking',
           'PermissionRequest': 'waiting', 'Stop': 'success', 'stop': 'success', 'task_complete': 'success',
           'StopFailure': 'error', 'PostToolUseFailure': 'error', 'failure': 'error', 'turn_aborted': 'error'}
_LOG = logging.getLogger(__name__)
REACTION_NODE = {'id': 'baboom.reactions', 'params': {'sqlite_seconds': .05, 'cooldown_seconds': 10,
                                                   'poll_ms': 100, 'active_seconds': 10}}


def reaction_kind(payload, verdict=''):
    if verdict in ('ask', 'refuse'):
        return 'waiting' if verdict == 'ask' else 'error'
    event = payload.get('hook_event_name') or payload.get('type')
    item = payload.get('item')
    if isinstance(item, dict) and item.get('status') in ('failed', 'error', 'denied', 'rejected'):
        return 'error'
    response = payload.get('tool_response')
    if payload.get('is_error') is True or isinstance(response, dict) and (
            response.get('is_error') is True or response.get('isError') is True or response.get('ok') is False):
        return 'error'
    if event in _EVENTS:
        return _EVENTS[event]
    tool = str(payload.get('tool_name') or payload.get('tool') or payload.get('name') or '').casefold()
    if re.search(r'edit|write|apply_patch|replace|create_file', tool):
        return 'editing'
    args = payload.get('tool_input') or payload.get('input') or payload.get('arguments') or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    command = str(args.get('command') or args.get('cmd') or '') if isinstance(args, dict) else ''
    if re.search(r'\b(Set-Content|Add-Content|Out-File|write_text|write_bytes)\b', command, re.I):
        return 'editing'
    return 'testing' if re.search(r'\b(pytest|test|vitest|jest|unittest)\b', command) else None


def emit(payload, vendor, *, verdict='', environment=None, event_id='', now=None):
    """Best-effort feedback cannot change a tool decision. Throttle per session and reaction."""
    from .workshop_mailbox import ACTIVITY_SCHEMA, record_activity
    from types import SimpleNamespace
    kind = reaction_kind(payload, verdict)
    session = payload.get('session_id') or payload.get('sessionId')
    if not kind or not isinstance(session, str) or not session:
        return False
    vendor = {'claude-code': 'claude', 'codex-cli': 'codex', 'gemini-cli': 'gemini'}.get(vendor, vendor)
    actor = hashlib.sha256((vendor + ':' + session).encode()).hexdigest()
    path = state_directory(environment) / 'workshop' / 'messages.sqlite3'
    now = time.time() if now is None else now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=REACTION_NODE['params']['sqlite_seconds'])) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(ACTIVITY_SCHEMA)
            previous = db.execute("SELECT at,detail FROM workshop_activity WHERE actor=? AND action='baboom.reaction' ORDER BY sequence DESC LIMIT 64", (actor,)).fetchall()
            for at, detail in previous:
                value = json.loads(detail)
                if event_id and value.get('event_id') == event_id:
                    return False
                if value.get('reaction') == kind and now - datetime.fromisoformat(at).timestamp() < REACTION_NODE['params']['cooldown_seconds']:
                    return False
            record_activity(SimpleNamespace(_db=db), actor, 'baboom.reaction', reaction=kind, event_id=event_id)
        return True
    except (OSError, ValueError, sqlite3.Error):
        _LOG.warning('BABOOM reaction unavailable; agent work continues')
        return False


def latest(*, environment=None, now=None):
    """Project declared native events into this profile's Workshop, then read its latest reaction."""
    from .baboom_work_presence import BaboomWorkPresence
    path = state_directory(environment) / 'workshop' / 'messages.sqlite3'
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=REACTION_NODE['params']['sqlite_seconds'])) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone():
                declarations = db.execute('SELECT record FROM workshop_declarations LIMIT 64').fetchall()
                from .agent_status import project_baboom_reaction
                for record, in declarations:
                    agent = json.loads(record)
                    if agent.get('runtime') in ('claude', 'codex') and agent.get('native_session_id'):
                        project_baboom_reaction(agent['runtime'], agent['native_session_id'], environment=environment)
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_activity'").fetchone():
                return None
            row = db.execute("SELECT at,detail FROM workshop_activity WHERE action='baboom.reaction' ORDER BY sequence DESC LIMIT 1").fetchone()
        if not row:
            return None
        age = (time.time() if now is None else now) - datetime.fromisoformat(row[0]).timestamp()
        kind = json.loads(row[1])['reaction']
        if kind not in REACTIONS or not -5 <= age <= REACTION_NODE['params']['active_seconds']:
            return None
        motion, text = REACTIONS[kind]
        return BaboomWorkPresence(kind, '', motion, kind == 'waiting', speech(text))
    except (OSError, ValueError, KeyError, sqlite3.Error):
        _LOG.warning('BABOOM reaction read unavailable; open Workshop to inspect its activity')
        return None
