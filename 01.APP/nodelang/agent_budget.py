"""Per-agent token accounting in the router's one usage file, and the cap that pauses only that agent.

Design adopted from Paperclip budgets (cost events + a policy whose hard stop pauses its scope); the
store stays the existing router.sqlite ``requests`` table the composer already writes. Kept free of
heavy imports so the per-turn Stop hook can record native usage cheaply.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import time

# Node parameters: the cap is a parameter; None means no cap. ``caps`` overrides it per agent key
# (composer agent name, or "<runtime>:<native session id>" for a native session).
BUDGET_NODE = {'id': 'agent.budget', 'params': {'window_seconds': 86400, 'token_cap': None, 'caps': {},
                                                       'busy_timeout_seconds': 2}}
SCHEMA = ('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, ts REAL, agent TEXT, model TEXT, '
          'provider TEXT, tokens INTEGER, ms INTEGER, outcome TEXT)')


def router_database():
    return Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'settings' / 'router.sqlite'


def connect():
    path = router_database()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=BUDGET_NODE['params']['busy_timeout_seconds'])
    db.execute(SCHEMA)
    db.execute('CREATE INDEX IF NOT EXISTS requests_agent_ts ON requests(agent, ts)')
    return db


def cap_for(agent, cap=None):
    params = BUDGET_NODE['params']
    return cap if cap is not None else params['caps'].get(agent, params['token_cap'])


def used(agent, *, now=None):
    now = time.time() if now is None else now
    with closing(connect()) as db, db:
        return db.execute('SELECT coalesce(sum(tokens),0) FROM requests WHERE agent=? AND ts>=?',
                          (agent, now - BUDGET_NODE['params']['window_seconds'])).fetchone()[0]


def paused(agent, cap=None, *, now=None):
    """True once this agent's tokens in the window reach its cap; other agents are untouched."""
    limit = cap_for(agent, cap)
    return limit is not None and used(agent, now=now) >= limit


def record_entries(entries, agent, provider='claude-code'):
    """Record each assistant turn of a native transcript once (its message id is the row id)."""
    rows = {}
    for entry in entries:
        message = entry.get('message') if entry.get('type') == 'assistant' else None
        usage = message.get('usage') if type(message) is dict else None
        if type(usage) is not dict or type(message.get('id')) is not str:
            continue
        # shortcut: cache reads are not counted (billed far below fresh input); add them if quotas count them.
        tokens = sum(value for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens')
                     if type(value := usage.get(key)) is int and value >= 0)
        try:
            ts = datetime.fromisoformat(str(entry.get('timestamp')).replace('Z', '+00:00')).timestamp()
        except ValueError:
            ts = time.time()
        rows['native:' + message['id']] = (ts, agent, str(message.get('model') or ''), provider, tokens)
    if rows:
        with closing(connect()) as db, db:
            db.executemany("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?,0,'native-turn')",
                           [(key, *value) for key, value in rows.items()])
    return len(rows)
