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


def _home():
    return Path(os.environ.get('ARCHHUB_AGENT_PROFILE') or Path.home())


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


def transcript_path(runtime, native_id):
    """Resolve only this provider's named transcript under the existing profile."""
    if not isinstance(native_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', native_id):
        return None
    if runtime == 'codex':
        root = _home() / '.codex' / 'sessions'
        found = list(root.rglob('rollout-*%s.jsonl' % native_id)) if root.is_dir() else []
    elif runtime == 'claude':
        root = _home() / '.claude' / 'projects'
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
    messages = []
    for row in _tail_rows(path):
        if not isinstance(row, dict):
            continue
        message = row.get('payload', {}) if runtime == 'codex' else row.get('message', {})
        if not isinstance(message, dict):
            continue
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
    return {'messages': messages[-200:], 'limited': path.stat().st_size > 65536 or len(messages) > 200}


def _codex(native_id):
    path = transcript_path('codex', native_id)
    if path is None:
        return None
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
    for row in reversed(_tail_rows(path)):
        if row.get('isSidechain'):
            continue
        message = row.get('message') or {}
        if row.get('type') == 'assistant':
            return 'resting' if message.get('stop_reason') == 'end_turn' else 'working'
        if row.get('type') == 'user':
            return 'working'
    return None
