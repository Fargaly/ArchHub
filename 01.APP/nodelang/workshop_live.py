"""Workshop live delivery: push a message into each recipient's RUNNING session now.

Founder 2026-10-28: no pending state, no inbox, no queue. A Workshop message is
delivered live into the recipient session (it lands mid-turn, like Claude Code's
own cross-session messages) or it fails at once with the exact reason. The
Workshop store keeps the chat history and one delivery row per recipient.

One channel (founder 2026-10-28, "one Workshop, one channel"): every push goes through Session
Link (workshop/: worker inject -> native.mjs injectWorkshop). Workshop resolves the
recipient against its live catalog and uses that app's own door: Claude peer pipe, Codex Desktop
app bridge (`workshop resume --current` from a Codex Desktop task), OpenCode plugin,
Antigravity cascade API, Cursor Desktop Bridge, the app's BABOOM turn door, or the console seat of
a terminal session (workshop/console_seat.py, the Workshop's seat adapter). This module only records the rows.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

FOUNDER = 'Ahmed'
# Live delivery node: its typed parameters.
LIVE_NODE = {'id': 'workshop.live', 'params': {'discover_timeout_seconds': 10, 'list_cache_seconds': 30,
                                                 'sender_wait_seconds': 0.5}}
SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_live_deliveries (message_id TEXT NOT NULL, recipient TEXT NOT NULL, "
          "agent TEXT, app TEXT, native_session_id TEXT, channel TEXT, state TEXT NOT NULL, reason TEXT, "
          "at TEXT NOT NULL, ms INTEGER, PRIMARY KEY (message_id, recipient))")


def push(app, native_id, text, message_id, *, timeout=10.0, pids=()):
    """One live push, any agent, through Workshop (the one channel). Returns (state, channel, reason).

    Workshop resolves the recipient against its live catalog and uses that app's own door: Claude
    peer pipe, Codex Desktop app bridge, OpenCode plugin, Antigravity cascade API, Cursor Desktop Bridge,
    the app's BABOOM, or the console seat of a terminal session. Never waits for a reply.
    """
    import sys
    from .workshop_transport import public_delivery_reason
    from .workshop_mailbox import _local_transport
    env = {'WORKSHOP_PYTHON': sys.executable, 'WORKSHOP_PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    if app == 'goose' and native_id == 'baboom':
        app, pids = 'archhub', ()            # the app's own BABOOM: Workshop reaches its turn door
    if not native_id:
        return 'failed', 'none', 'This session has no live door; it reads the message in the Workshop.'
    recipient = {'app': app, 'id': str(native_id or ''), **({'pids': [int(p) for p in pids]} if pids and app not in ('claude', 'opencode') else {}),
                 **({'desktop': True} if app == 'codex' and codex_desktop_thread(native_id) else {})}
    transport = _local_transport(env)
    try:
        result = transport.inject(recipient, text, message_id=message_id, timeout_seconds=timeout)
    except Exception as error:  # noqa: BLE001 - the reason is the answer
        return 'failed', 'workshop', str(error)[:300]
    finally:
        getattr(transport, 'close', lambda: None)()
    if result.get('status') in ('injected', 'ok', 'delivered'):
        return 'delivered', 'workshop', result.get('note', '')
    return 'failed', 'workshop', public_delivery_reason(result.get('reason') or result.get('error') or result.get('status'))


def codex_desktop_thread(native_id):
    """True when this Codex thread belongs to Codex Desktop (its rollout's originator), not a terminal session."""
    import json as _json
    if not native_id:
        return False
    homes = [Path(os.environ.get('CODEX_HOME', '')), Path('C:/Users') / os.environ.get('USERNAME', '') / '.codex']
    for home in homes:
        sessions = home / 'sessions'
        if not sessions.is_dir():
            continue
        for rollout in sessions.rglob('rollout-*%s.jsonl' % native_id):
            try:
                with rollout.open(encoding='utf-8') as stream:
                    meta = _json.loads(stream.readline()).get('payload') or {}
            except (OSError, ValueError):
                continue
            return meta.get('originator') == 'Codex Desktop'
    return False


def envelope(message_id, sender, text):
    return ('[ArchHub Workshop message from %s · id %s]\n%s\n\n'
            'Reply in the Workshop now if it asks you something: send(to="%s", text=..., reply_to="%s"). '
            'Never reply to an acknowledgement.') % (sender, message_id, text, sender, message_id)


def deliver(history, message, recipients, sender, text):
    """Push to every recipient now; record one row each. Idempotent per (message, recipient)."""
    if not recipients:
        return []
    history._db.execute(SCHEMA)
    rows = []
    for row in recipients:
        key = row.get('session') or row.get('native_session_id')
        done = history._db.execute('SELECT state, channel, reason, at, ms FROM workshop_live_deliveries WHERE message_id=? AND recipient=?',
                                   (message, key)).fetchone()
        if done is not None:
            rows.append({'recipient': key, 'agent': row.get('agent'), 'state': done[0], 'channel': done[1], 'reason': done[2],
                         'at': done[3], 'ms': done[4], 'repeat': True})
            continue
        started = time.perf_counter()
        state, channel, reason = push(row.get('runtime') or row.get('app'), row.get('native_session_id'),
                                      envelope(message, sender, text), message, pids=_seat_pids(history, key))
        ms = int((time.perf_counter() - started) * 1000)
        at = datetime.now(timezone.utc).isoformat()
        history._db.execute('INSERT OR IGNORE INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (message, key, row.get('agent'), row.get('runtime') or row.get('app'), row.get('native_session_id'),
                             channel, state, reason, at, ms))
        rows.append({'recipient': key, 'agent': row.get('display_name') or row.get('agent'), 'state': state, 'channel': channel,
                     'reason': reason, 'at': at, 'ms': ms})
    return rows


def _seat_pids(history, session):
    """The declared session's live processes, agent first (OpenRig's seat = the agent's own console)."""
    import psutil
    from .workshop_mailbox import read_declarations
    row = next((r for r in read_declarations(history._db, include_archived=True) if r['session'] == session), None)
    if row is None:
        return ()
    pids = []
    for entry in ([row.get('native_process')] if row.get('native_process') else []) + list(row.get('process_lineage') or []):
        try:
            if psutil.Process(entry['pid']).create_time() == entry['created_at'] or abs(psutil.Process(entry['pid']).create_time() - entry['created_at']) < 0.01:
                pids.append(entry['pid'])
        except (psutil.Error, KeyError, TypeError):
            continue
    return tuple(dict.fromkeys(pids))


def deliveries(history, message_ids):
    try:
        history._db.execute(SCHEMA)
    except Exception:  # noqa: BLE001 - a read-only handle shows no rows
        return {}
    out = {}
    marks = ','.join('?' * len(message_ids)) or "''"
    for row in history._db.execute('SELECT message_id, agent, app, channel, state, reason, at, ms FROM workshop_live_deliveries '
                                   'WHERE message_id IN (%s)' % marks, list(message_ids)):
        out.setdefault(row[0], []).append({'agent': row[1], 'app': row[2], 'channel': row[3], 'state': row[4],
                                           'reason': row[5], 'at': row[6], 'ms': row[7]})
    return out


def discover_target(target):
    """A live session that has not joined yet is still addressable by its exact id, title or selector."""
    from .workshop_mailbox import _local_transport
    transport = _local_transport()
    try:
        found = transport.discover(timeout_seconds=LIVE_NODE['params']['discover_timeout_seconds'],
                                   apps=['claude', 'codex', 'opencode', 'antigravity', 'antigravity-ide', 'cursor'])
    except Exception:  # noqa: BLE001 - no discovery means no match, reported by the caller
        found = {}
    finally:
        getattr(transport, 'close', lambda: None)()
    wanted = target.strip().casefold()
    return [{'session': 'native:%s:%s' % (row['app'], row['id']), 'agent': row.get('title') or row['id'],
             'runtime': row['app'], 'native_session_id': row['id']}
            for row in found.get('recipients', [])
            if wanted in {str(row.get(k) or '').casefold() for k in ('id', 'title', 'selector')}]


_LIVE = {'at': 0.0, 'ids': {}}


def live_ids():
    """{app: {native ids}} from the Workshop's own live list, for apps whose discovery answered (cached briefly)."""
    # Never waited on: the list refreshes beside the caller; until it answers nothing is dropped.
    if time.monotonic() - _LIVE['at'] >= LIVE_NODE['params']['list_cache_seconds'] and not _LIVE.get('running'):
        import threading
        _LIVE['running'] = True
        threading.Thread(target=_refresh_live_ids, name='archhub-workshop-list', daemon=True).start()
    return _LIVE['ids']


def _refresh_live_ids():
    from .workshop_mailbox import _local_transport
    transport = _local_transport()
    try:
        found = transport.discover(timeout_seconds=LIVE_NODE['params']['discover_timeout_seconds'],
                                   apps=['claude', 'codex', 'opencode', 'antigravity', 'antigravity-ide'])
    except Exception as error:  # noqa: BLE001 - no list means nothing is dropped; the reason is logged
        import sys   # stdout is an MCP connector's protocol stream; diagnostics go to stderr
        sys.stderr.write('  workshop   : live list unavailable (%s)\n' % str(error)[:160])
        found = {}
    finally:
        getattr(transport, 'close', lambda: None)()
    ids = {}
    for row in found.get('recipients', []):
        ids.setdefault(row['app'], set()).add(row['id'])
    _LIVE.update(at=time.monotonic(), ids=ids, running=False)


def live_agents(with_status=False):
    """Every joined agent session (any provider) with a handle for @mentions, and its status if asked."""
    import re
    from .workshop_mailbox import application_history, read_declarations
    with application_history() as history:
        rows = read_declarations(history._db)
    from .baboom_nograph import own_session
    baboom = own_session()
    live = live_ids()
    agents, seen = [], set()
    for row in rows:
        app = row.get('runtime') or row.get('app')
        if app in live and row.get('native_session_id') and row['native_session_id'] not in live[app]:
            continue   # its native id is not a session the Workshop's own list returns: a stale row, never addressed
        name = 'BABOOM' if row['session'] == baboom else row.get('display_name') or row['agent']
        handle = re.sub(r'[^a-z0-9]+', '-', name.split(' (')[0].casefold()).strip('-')[:40] or row['session'][-8:]
        while handle in seen:
            handle += '-' + row['session'][-4:]
        seen.add(handle)
        from .workshop_gateway import read_states
        governance = read_states().get(row.get('runtime') or row.get('app'), {}).get('state', 'not checked')
        agents.append({'handle': handle, 'name': name, 'agent': row['agent'], 'app': row.get('runtime') or row.get('app'), 'governance': governance,
                       'session': row['session'], 'native_session_id': row.get('native_session_id'), 'task': row.get('task'),
                       'pids': [entry['pid'] for entry in ([row['native_process']] if row.get('native_process') else [])
                                + list(row.get('process_lineage') or [])]})
    if with_status:
        from .agent_status import _claude, _codex
        from .workshop import console_seat
        seats = console_seat.peek_many(sorted({pid for a in agents if a['app'] not in ('claude',) for pid in a['pids'][:4]}))
        for agent in agents:
            state = None
            if agent['native_session_id'] and agent['app'] == 'codex':
                state, source = _codex(agent['native_session_id']), 'codex rollout'
            elif agent['native_session_id'] and agent['app'] == 'claude':
                state, source = _claude(agent['native_session_id']), 'claude transcript'
            if not state:
                seat = next((seats[pid] for pid in agent['pids'][:4] if pid in seats), None)
                state = {'selection_open': 'needs-you', 'empty': 'resting', 'draft': 'resting'}.get(seat, 'working' if seat else None)
                source = 'console seat'
            agent['status'], agent['status_source'] = state or 'unknown', source if state else 'no record'
    return agents


def send_as_founder(text, handles, *, reply_to=None):
    """The composer's @mention path: one Workshop message from Ahmed, pushed live to each mentioned agent."""
    from .workshop_mailbox import application_history, _send
    agents = live_agents()
    chosen = agents if 'everyone' in handles else [a for a in agents if a['handle'] in handles]
    unknown = [h for h in handles if h != 'everyone' and h not in {a['handle'] for a in agents}]
    if not chosen:
        raise ValueError('No live agent matches %s. Mention one of: %s' % (
            ', '.join('@' + h for h in handles), ', '.join('@' + a['handle'] for a in agents) or 'none joined'))
    identity = {'sender_key': 'founder', 'sender_label': FOUNDER, 'sender': FOUNDER}
    target = 'Everyone' if 'everyone' in handles else ', '.join(a['agent'] for a in chosen)
    with application_history() as history:
        sent = _send(history, {'to': target, 'text': text, **({'reply_to': reply_to} if reply_to else {})}, identity,
                     sender_binding={'session': 'founder'})
        rows = deliver(history, sent['message_id'], [{'session': a['session'], 'agent': a['name'], 'runtime': a['app'],
                                                       'native_session_id': a['native_session_id']} for a in chosen],
                       FOUNDER, text)
    return {'message_id': sent['message_id'], 'deliveries': rows, 'unknown': unknown}


def record_answer(question, answer, model):
    """A plain composer question and the model's answer join the one Workshop history."""
    from .workshop_mailbox import application_history
    from .workshop_mailbox import ROOM, CATEGORY
    with application_history() as history:
        with history._transaction(write=True):
            asked = history.append(ROOM, author=FOUNDER, content='To Router:\n' + question, category=CATEGORY,
                                   recipients=(), reply_principal=FOUNDER, idempotency_key='composer:' + os.urandom(8).hex())
            history.append(ROOM, author=model, content='To Ahmed:\n' + answer, category=CATEGORY, recipients=(),
                           reply_to=asked['id'], reply_principal=model, idempotency_key='composer:' + os.urandom(8).hex())
