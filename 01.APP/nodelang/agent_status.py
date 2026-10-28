"""Agent status for the Workshop list: working / resting / needs-you, from each CLI's own records.

Fitted from AgentTrail (github.com/sodiumsun/agenttrail, MIT, e4ba2da) connectors/logs.mjs:
Codex rollouts (~/.codex/sessions/**/rollout-*<id>.jsonl: task_started / task_complete /
turn_aborted) and Claude Code transcripts (~/.claude/projects/*/<id>.jsonl: an assistant row
with stop_reason end_turn ends a turn). Only the tail of one file is read, no prompt text is kept.
Agents without such a record (Gemini, Cursor, OpenCode, Copilot...) are read from their console
seat in workshop_live.live_agents (console_seat.peek_many): an open choice or dialog means needs-you.
"""
from __future__ import annotations

import json
import os
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


def _codex(native_id):
    root = _home() / '.codex' / 'sessions'
    found = sorted(root.rglob('rollout-*%s.jsonl' % native_id), key=lambda p: p.stat().st_mtime) if root.is_dir() else []
    if not found:
        return None
    for row in reversed(_tail_rows(found[-1])):
        kind = (row.get('payload') or {}).get('type')
        if kind in ('task_complete', 'turn_aborted'):
            return 'resting'
        if kind == 'task_started':
            return 'working'
    return None


def _claude(native_id):
    root = _home() / '.claude' / 'projects'
    found = list(root.glob('*/%s.jsonl' % native_id)) if root.is_dir() else []
    if not found:
        return None
    for row in reversed(_tail_rows(found[0])):
        if row.get('isSidechain'):
            continue
        message = row.get('message') or {}
        if row.get('type') == 'assistant':
            return 'resting' if message.get('stop_reason') == 'end_turn' else 'working'
        if row.get('type') == 'user':
            return 'working'
    return None
