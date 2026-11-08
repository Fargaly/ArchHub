"""Agent status for the Workshop list: working / resting / needs-you, from each CLI's own records.

Fitted from AgentTrail (github.com/sodiumsun/agenttrail, MIT, e4ba2da) connectors/logs.mjs:
Codex rollouts (~/.codex/sessions/**/rollout-*<id>.jsonl: task_started / task_complete /
turn_aborted) and Claude Code transcripts (~/.claude/projects/*/<id>.jsonl: an assistant row
with stop_reason end_turn ends a turn). Only the tail of one file is read, no prompt text is kept.
Agents without such a record (Gemini, Cursor, OpenCode, Copilot...) are read from their console
seat in workshop_live.live_agents (workshop/console_seat.peek_many): an open choice or dialog means needs-you.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _home(environment=None):
    env = os.environ if environment is None else environment
    return Path(env.get('ARCHHUB_AGENT_PROFILE') or env.get('USERPROFILE') or env.get('HOME') or Path.home())


def _tail_rows(path, limit=65536):
    with open(path, 'rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        lines = stream.read().decode('utf-8', 'replace').splitlines()[1 if size > limit else 0:]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def transcript_path(runtime, native_id, environment=None):
    """Resolve only this provider's named transcript under the existing profile."""
    if not isinstance(native_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', native_id):
        return None
    if runtime == 'codex':
        root = _home(environment) / '.codex' / 'sessions'
        found = list(root.rglob('rollout-*%s.jsonl' % native_id)) if root.is_dir() else []
    elif runtime == 'claude':
        root = _home(environment) / '.claude' / 'projects'
        found = list(root.glob('*/%s.jsonl' % native_id)) if root.is_dir() else []
    else:
        return None
    return max((p for p in found if p.is_file() and p.resolve().is_relative_to(root.resolve())),
               key=lambda p: p.stat().st_mtime, default=None)


def read_transcript(runtime, native_id):
    """Read recent user/assistant text using the same bounded native-log reader as status."""
    path = transcript_path(runtime, native_id)
    if path is None:
        raise ValueError('No native transcript is available for this session.')
    messages, calls, by_id = [], [], {}
    turn, model = '', ''
    from .agent_work import redact
    for index, row in enumerate(_tail_rows(path, 2 * 1024 * 1024)):
        if not isinstance(row, dict):
            continue
        message = row.get('payload', {}) if runtime == 'codex' else row.get('message', {})
        if not isinstance(message, dict):
            continue
        if runtime == 'codex' and row.get('type') == 'turn_context':
            turn = str(message.get('turn_id') or index)
            model = str(message.get('model') or model)
        model = str(message.get('model') or model)
        if runtime == 'claude' and row.get('type') == 'user' and (isinstance(message.get('content'), str) or
                (isinstance(message.get('content'), list) and any(isinstance(p, dict) and p.get('type') == 'text' for p in message['content']))):
            turn = str(row.get('uuid') or index)
        blocks = message.get('content', []) if runtime == 'claude' else [message] if row.get('type') == 'response_item' else []
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind in ('tool_use', 'function_call'):
                identity = block.get('id') if kind == 'tool_use' else block.get('call_id')
                arguments = block.get('input', {}) if kind == 'tool_use' else block.get('arguments', '{}')
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {'unparsed': arguments}
                call = {'id': str(identity or index), 'tool': str(block.get('name') or ''),
                        'input': arguments, 'turn': turn or 'tail', 'at': row.get('timestamp', ''), 'model': model}
                calls.append(call)
                by_id[identity] = call
            elif kind in ('tool_result', 'function_call_output'):
                identity = block.get('tool_use_id') if kind == 'tool_result' else block.get('call_id')
                if identity in by_id:
                    by_id[identity]['output'] = block.get('content') if kind == 'tool_result' else block.get('output')
        if runtime == 'codex' and (row.get('type') != 'response_item' or message.get('type') != 'message'):
            continue
        if runtime == 'claude' and (row.get('type') not in ('user', 'assistant') or row.get('isSidechain')):
            continue
        role, content = message.get('role'), message.get('content', [])
        if role not in ('user', 'assistant'):
            continue
        text = ''
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = '\n'.join(part['text'] for part in content if isinstance(part, dict)
                             and part.get('type') in ('text', 'input_text', 'output_text') and isinstance(part.get('text'), str))
        if text:
            messages.append({'role': role, 'text': text, 'at': row.get('timestamp', '')})
    return redact({'messages': messages[-200:], 'calls': calls[-500:], 'model': model,
                   'limited': path.stat().st_size > 2 * 1024 * 1024 or len(messages) > 200 or len(calls) > 500})


def _codex(native_id):
    path = transcript_path('codex', native_id)
    if path is None:
        return None
    project_baboom_reaction('codex', native_id, path)
    for row in reversed(_tail_rows(path)):
        kind = (row.get('payload') or {}).get('type')
        if kind in ('task_complete', 'turn_aborted'):
            return 'resting'
        if kind == 'task_started':
            return 'working'
    return None


def _claude(native_id):
    path = transcript_path('claude', native_id)
    if path is None:
        return None
    project_baboom_reaction('claude', native_id, path)
    for row in reversed(_tail_rows(path)):
        if row.get('isSidechain'):
            continue
        message = row.get('message') or {}
        if row.get('type') == 'assistant':
            return 'resting' if message.get('stop_reason') == 'end_turn' else 'working'
        if row.get('type') == 'user':
            return 'working'
    return None


_REACTION_FILES = {}


def project_baboom_reaction(runtime, native_id, path=None, *, environment=None):
    """Project the latest native event only; retain no prompt, path or code in Workshop."""
    import hashlib
    import time
    from .baboom_reactions import emit, reaction_kind
    from .user_paths import state_directory
    key = (runtime, native_id, str(state_directory(environment)))
    cached = _REACTION_FILES.get(key)
    path = path or (cached[0] if cached else (transcript_path(runtime, native_id) if environment is None
                                           else transcript_path(runtime, native_id, environment=environment)))
    if path is None:
        return
    try:
        stat = path.stat()
        # Windows can keep an open writer's mtime unchanged while its log grows.
        stamp = (stat.st_mtime_ns, stat.st_size)
        if cached and cached[1] == stamp:
            return
        if len(_REACTION_FILES) >= 64:
            _REACTION_FILES.clear()
        _REACTION_FILES[key] = (path, stamp)
        for row in reversed(_tail_rows(path)):
            if not isinstance(row, dict) or row.get('isSidechain'):
                continue
            payload = row.get('payload') if runtime == 'codex' else row.get('message')
            if not isinstance(payload, dict):
                continue
            event = dict(payload)
            if runtime == 'claude':
                blocks = payload.get('content')
                tools = [b for b in blocks if isinstance(b, dict) and b.get('type') == 'tool_use'] if isinstance(blocks, list) else []
                if tools:
                    event = {**tools[-1], 'tool_name': tools[-1].get('name'), 'tool_input': tools[-1].get('input')}
                elif payload.get('stop_reason') == 'end_turn':
                    event = {'type': 'task_complete'}
                elif row.get('type') == 'user':
                    failed = isinstance(blocks, list) and any(isinstance(b, dict) and b.get('is_error') for b in blocks)
                    event = {'type': 'failure' if failed else 'task_started'}
            if reaction_kind(event):
                from .baboom_work_presence import _parsed_time
                recorded = _parsed_time(row.get('timestamp'))
                if time.time() - (recorded.timestamp() if recorded else stat.st_mtime) > 10:
                    return
                identity = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                emit({**event, 'session_id': native_id}, runtime, event_id=identity, environment=environment)
                return
    except (OSError, ValueError):
        return
