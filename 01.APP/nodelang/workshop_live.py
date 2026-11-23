"""Workshop live delivery: push a message into each recipient's RUNNING session now.

Founder 2026-10-28: no pending state, no inbox, no queue. A Workshop message is
delivered live into the recipient session (it lands mid-turn, like Claude Code's
own cross-session messages) or it fails at once with the exact reason. The
Workshop store keeps the chat history and one delivery row per recipient.

One channel (founder 2026-10-28, "one Workshop, one channel"): every push goes through Session
Link (workshop/: worker inject -> native.mjs injectWorkshop). Workshop resolves the
recipient against its live catalog and uses that app's own door: Claude peer pipe, Codex Desktop
app bridge (`workshop resume --current` from a Codex Desktop task), OpenCode plugin,
Antigravity cascade API, the app's BABOOM turn door, or the console seat of
a terminal session (workshop/console_seat.py, the Workshop's seat adapter). Cursor has no console
and its Desktop Bridge stays off: a Cursor push is queued for the chat's stop hook, which injects
it as the next turn. This module only records the rows.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

FOUNDER = 'Ahmed'
# Live delivery node: its typed parameters.
LIVE_NODE = {'id': 'workshop.live', 'params': {'discover_timeout_seconds': 10, 'list_cache_seconds': 30,
                                                 'sender_wait_seconds': 0.5,
                                                 # a one-shot CLI send waits this long for its pushes (native.mjs gives it 35 s)
                                                 'one_shot_wait_seconds': 30}}
SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_live_deliveries (message_id TEXT NOT NULL, recipient TEXT NOT NULL, "
          "agent TEXT, app TEXT, native_session_id TEXT, channel TEXT, state TEXT NOT NULL, reason TEXT, "
          "at TEXT NOT NULL, ms INTEGER, PRIMARY KEY (message_id, recipient))")


def push(app, native_id, text, message_id, *, timeout=10.0, pids=(), permission_mode='prompting'):
    """One live push, any agent, through Workshop (the one channel). Returns (state, channel, reason).

    Workshop resolves the recipient against its live catalog and uses that app's own door: Claude
    peer pipe, Codex Desktop app bridge, OpenCode plugin, Antigravity cascade API,
    the app's BABOOM, or the console seat of a terminal session. Cursor is queued for its stop hook.
    Never waits for a reply.
    """
    import sys
    from .workshop_transport import public_delivery_reason
    from .workshop_mailbox import _local_transport
    env = {'WORKSHOP_PYTHON': sys.executable, 'WORKSHOP_PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    if app == 'goose' and native_id == 'baboom':
        app, pids = 'archhub', ()            # the app's own BABOOM: Workshop reaches its turn door
    # Cursor's agent process has no console. The Desktop Bridge flag stays off, so the stop hook
    # is the door: the message waits for that chat's next turn. Never attach a console.
    if app == 'cursor':
        return 'queued', 'hook', 'queued for next turn via hook'
    if not native_id:
        return 'failed', 'none', 'This session has no live door; it reads the message in the Workshop.'
    recipient = {'app': app, 'id': str(native_id or ''), **({'pids': [int(p) for p in pids]} if pids and app not in ('claude', 'opencode', 'cursor') else {}),
                 **({'desktop': True} if app == 'codex' and codex_desktop_thread(native_id) else {})}
    if app == 'codex' and not recipient.get('desktop') and codex_remote(pids):
        recipient['remote'] = codex_remote(pids)   # its TUI runs on this App Server (--remote), not the shared daemon
    transport = _local_transport(env)
    from .workshop_mailbox import delivery_outcome
    try:
        result = transport.inject(recipient, text, message_id=message_id, timeout_seconds=timeout, permission_mode=permission_mode)
    except Exception as error:  # noqa: BLE001 - the transport may have accepted it before failing: uncertain
        return 'uncertain', 'workshop', str(error)[:300]
    finally:
        getattr(transport, 'close', lambda: None)()
    outcome = delivery_outcome(result.get('status'), result.get('dispatch_attempted'))
    if outcome == 'delivered':
        return 'delivered', 'workshop', result.get('note', '')
    # 'failed' only when the door verified nothing was sent; anything else may have landed.
    return ('failed' if outcome == 'refused' else 'uncertain'), 'workshop', public_delivery_reason(
        result.get('reason') or result.get('error') or result.get('status'))


def opencode_session(pids):
    """The one OpenCode session in the declaring connector's own OpenCode process, from Workshop's live list (the
    plugin answers for its process, runtimeId = that process id). Several sessions there: '' (no guess)."""
    from .workshop_mailbox import _local_transport
    if not pids:
        return ''
    transport = _local_transport()
    try:
        found = transport.discover(timeout_seconds=LIVE_NODE['params']['discover_timeout_seconds'], apps=['opencode'])
    except Exception as error:  # noqa: BLE001 - no list means no door; the push reports it
        import sys
        sys.stderr.write('  workshop   : OpenCode live list unavailable (%s)\n' % str(error)[:160])
        return ''
    finally:
        getattr(transport, 'close', lambda: None)()
    rows = [r for r in found.get('recipients', []) if r.get('app') == 'opencode' and r.get('runtimeId') in set(pids)]
    return rows[0]['id'] if len(rows) == 1 else ''


def codex_remote(pids):
    """The loopback App Server a Codex session runs on, from its process line: the TUI's `--remote ws://...` or the
    serving app server's `--listen ws://...` (the connector that declared the session is that server's child)."""
    import psutil
    for pid in pids:
        try:
            argv = psutil.Process(pid).cmdline()
        except (psutil.Error, OSError):
            continue
        for flag, value in zip(argv, argv[1:]):
            if flag in ('--remote', '--listen') and value.startswith(('ws://127.0.0.1:', 'ws://localhost:')):
                return value
    return ''


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


def deliver(history, message, recipients, sender, text, permission_mode='prompting'):
    """Push to every recipient now; record one row each. Idempotent per (message, recipient).

    permission_mode is the sender's: the founder's own chat is 'bypass', so a session running in bypass takes it
    mid-turn instead of holding it for approval (Claude Code permission-mode parity)."""
    if not recipients:
        return []
    from .workshop_mailbox import DELIVERY_AUTHOR, ROOM, claim_delivery, delivery_outcome, recipient_identity
    history._db.execute(SCHEMA)
    stored = history.get(ROOM, message, principal=DELIVERY_AUTHOR)
    rows = []
    for row in recipients:
        key = row.get('session') or row.get('native_session_id')
        # F320: one receipt per addressee identity; a push recorded under an old declaration key of the same native
        # session (same runtime) is this recipient's push.
        identity = recipient_identity(row)
        seat = identity[1:] if identity[0] == 'native' else ('', '')
        done = history._db.execute('SELECT state, channel, reason, at, ms FROM workshop_live_deliveries WHERE message_id=? '
                                   "AND (recipient=? OR (app=? AND native_session_id=? AND native_session_id!='')) "
                                   "ORDER BY state='delivered' DESC LIMIT 1", (message, key, *seat)).fetchone()
        if done is not None:
            rows.append({'recipient': key, 'agent': row.get('agent'), 'state': done[0], 'channel': done[1], 'reason': done[2],
                         'at': done[3], 'ms': done[4], 'repeat': True})
            continue
        # Resolve the actual recipient first (OpenCode gives its MCP connector no session id), then claim under that
        # identity, dispatch to exactly it and settle under it: the one claim shared with the app's loop.
        runtime, native = row.get('runtime') or row.get('app'), row.get('native_session_id')
        if runtime == 'opencode' and not native:
            native = opencode_session(_seat_pids(history, key))
        target = {**row, 'runtime': runtime, 'native_session_id': native or None}
        try:
            won, claimed = claim_delivery(history, stored or {'id': message}, target, 'initial', 'sender')
        except sqlite3.OperationalError as error:
            # The message is saved and earlier recipients may already have it: restarting the whole send repeated
            # their pushes. This recipient stays unclaimed on the same message; the app's delivery loop (or the
            # recipient's own pending read) claims and delivers it once the store frees.
            if (getattr(error, 'sqlite_errorcode', 0) & 0xff) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            rows.append({'recipient': key, 'agent': row.get('display_name') or row.get('agent'), 'state': 'pending',
                         'channel': 'workshop', 'reason': 'Recorded; delivery continues when the Workshop store frees.',
                         'at': None, 'ms': 0})
            continue
        if not won:
            rows.append({'recipient': key, 'agent': row.get('agent'), 'state': claimed, 'channel': 'workshop',
                         'reason': 'claimed by another delivery path', 'at': None, 'ms': 0, 'repeat': True})
            continue
        started = time.perf_counter()
        state, channel, reason = push(runtime, native,
                                      envelope(message, sender, text), message + ':initial', pids=_seat_pids(history, key),
                                      permission_mode=permission_mode)
        ms = int((time.perf_counter() - started) * 1000)
        at = datetime.now(timezone.utc).isoformat()
        outcome = delivery_outcome(state)
        state = state if outcome == 'delivered' else outcome   # the live row says refused or uncertain, never 'failed'
        receipt = (message, key, row.get('agent'), runtime, native or None, channel, state, reason, at, ms)
        try:
            _record_push(history, receipt, target, outcome)
        except sqlite3.OperationalError as error:
            # The message is saved and the push happened: a busy store only delays its receipt. Raising here made the
            # composer send the same text again (a second message, a second push). The receipt is written once the
            # store frees; the push is never repeated.
            if (getattr(error, 'sqlite_errorcode', 0) & 0xff) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            _record_push_later(history, receipt, target, outcome)
        rows.append({'recipient': key, 'agent': row.get('display_name') or row.get('agent'), 'state': state, 'channel': channel,
                     'reason': reason, 'at': at, 'ms': ms})
    return rows


def _record_push(history, receipt, target, outcome):
    from .workshop_mailbox import record_claim_outcome
    history._db.execute(SCHEMA)
    history._db.execute('INSERT OR IGNORE INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)', receipt)
    record_claim_outcome(history, receipt[0], target, 'initial', outcome, receipt[7])


def _record_push_later(history, receipt, target, outcome, attempts=30, wait=2.0):
    """Write a delayed push receipt beside the caller, retrying while the store stays busy (about a minute)."""
    import threading
    from .workshop_mailbox import application_history
    database = history._db.execute('PRAGMA database_list').fetchone()[2]

    def retry():
        for _ in range(attempts):
            time.sleep(wait)
            try:
                with application_history(database=database) as later:
                    _record_push(later, receipt, target, outcome)
                return
            except sqlite3.OperationalError as error:
                if (getattr(error, 'sqlite_errorcode', 0) & 0xff) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    return  # shortcut: a non-busy failure leaves the claim to settle as uncertain (never re-pushed)
    threading.Thread(target=retry, name='archhub-workshop-receipt', daemon=True).start()


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
    # A claim whose winner never recorded an outcome reads uncertain: neither delivered nor failed.
    from .workshop_mailbox import claim_state
    if history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_claims'").fetchone():
        for row in history._db.execute('SELECT * FROM workshop_claims WHERE outcome IS NULL AND step=? '
                                       'AND message_id IN (%s)' % marks, ['initial', *message_ids]):
            if claim_state(row) == 'uncertain':
                out.setdefault(row['message_id'], []).append({'agent': row['label'], 'app': json.loads(row['recipient'])[1],
                    'channel': 'workshop', 'state': 'uncertain', 'reason': 'claimed at %s; no outcome was recorded'
                    % row['claimed_at'], 'at': row['claimed_at'], 'ms': 0})
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
    rows = found.get('recipients', [])
    hits = [row for row in rows if wanted in {str(row.get(k) or '').casefold() for k in ('id', 'title', 'selector')}]
    if not hits:
        # An app name addresses its session only when exactly one is live. Never the first of many.
        app = APP_NAMES.get(wanted)
        same = [row for row in rows if app and row.get('app') == app]
        hits = same if len(same) == 1 else []
    if len(hits) != 1:
        return []
    return [{'session': 'native:%s:%s' % (row['app'], row['id']), 'agent': row.get('title') or row['id'],
             'runtime': row['app'], 'native_session_id': row['id']} for row in hits]


# What people call each app in "to:" -> the discovery app id.
APP_NAMES = {'claude': 'claude', 'claude code': 'claude', 'codex': 'codex', 'opencode': 'opencode',
             'antigravity': 'antigravity', 'antigravity ide': 'antigravity-ide', 'cursor': 'cursor'}


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
    transport = None
    try:
        transport = _local_transport()
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
                       'model': row.get('model') if isinstance(row.get('model'), str) else '',
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


def send_as_founder(text, handles, *, reply_to=None, task=None, task_peer=False):
    """The composer's @mention path: one Workshop message from Ahmed, pushed live to each mentioned agent.
    Sent from a session's thread, the message is bound to that task (refs), so it and the replies show there."""
    from .workshop_mailbox import application_history, _send
    agents = live_agents()
    chosen = agents if 'everyone' in handles else [a for a in agents if a['handle'] in handles]
    unknown = [h for h in handles if h != 'everyone' and h not in {a['handle'] for a in agents}]
    if task_peer:
        from .workshop_tasks import get, _live
        with application_history() as history:
            row = get(history, task) if task else None
        if not row or row.get('archived') or row['status'] == 'done' or not row.get('session_path'):
            raise ValueError('The selected task has no open canvas to continue.')
        attached = [member for member in row['members'] if not member.get('left')]
        current = _live(attached)
        owners = {member['owner'] for member in current or attached}
        chosen = [agent for agent in agents if agent['session'] in owners]
        if len(chosen) != 1:
            raise ValueError('Several agents are attached. Choose one in the task thread.' if chosen else
                             'No attached agent is available. Choose a recipient in the task thread.')
    if not chosen:
        raise ValueError('No live agent matches %s. Mention one of: %s' % (
            ', '.join('@' + h for h in handles), ', '.join('@' + a['handle'] for a in agents) or 'none joined'))
    identity = {'sender_key': 'founder', 'sender_label': FOUNDER, 'sender': FOUNDER}
    # The agents chosen now are stored on the one message (explicit routing), for @everyone and for named groups: a
    # joined label header can pass the 512-byte limit, a bare room header reached nobody, and a later joiner must not
    # receive it. The header is only the display: full labels when they fit, else the @handles typed.
    labels = ', '.join(a['agent'] for a in chosen)
    target = ('Everyone' if 'everyone' in handles else labels if len(labels.encode('utf-8')) <= 512
              else ', '.join('@' + a['handle'] for a in chosen))
    picked = [{'session': a['session'], 'agent': a['name'], 'runtime': a['app'],
               'native_session_id': a['native_session_id']} for a in chosen]
    with application_history() as history:
        sent = _send(history, {'to': target, 'text': text, **({'reply_to': reply_to} if reply_to else {})}, identity,
                     queued=(task,) if task else (), sender_binding={'session': 'founder'}, explicit=picked)
        rows = deliver(history, sent['message_id'], picked, FOUNDER, text, permission_mode='bypass')
    return {'message_id': sent['message_id'], 'deliveries': rows, 'unknown': unknown}


def record_answer(question, answer, model, task=None, to='Router'):
    """A composer question and its settled answer (model or agent) join the one Workshop history (that task's thread if given)."""
    from .workshop_mailbox import application_history
    from .workshop_mailbox import ROOM, CATEGORY
    refs = (task,) if task else ()
    with application_history() as history:
        with history._transaction(write=True):
            asked = history.append(ROOM, author=FOUNDER, content='To %s:\n' % to + question, category=CATEGORY, refs=refs,
                                   recipients=(), reply_principal=FOUNDER, idempotency_key='composer:' + os.urandom(8).hex())
            history.append(ROOM, author=model, content='To Ahmed:\n' + answer, category=CATEGORY, recipients=(), refs=refs,
                           reply_to=asked['id'], reply_principal=model, idempotency_key='composer:' + os.urandom(8).hex())
