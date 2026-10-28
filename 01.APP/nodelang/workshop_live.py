"""Workshop live delivery: push a message into each recipient's RUNNING session now.

Founder 2026-10-28: no pending state, no inbox, no queue. A Workshop message is
delivered live into the recipient session (it lands mid-turn, like Claude Code's
own cross-session messages) or it fails at once with the exact reason. The
Workshop store keeps the chat history and one delivery row per recipient.

Live channels (adopted, not invented):
  claude    Claude Code peer pipe (\\\\.\\pipe\\LOCAL\\cc-msg-*) via Session Link's vendored
            peer protocol (codex-mcp-bridge, MIT).
  codex     Codex Desktop app-tools pipe (\\\\.\\pipe\\codex-app-tools-*):
            send_message_to_thread into a loaded thread, via Session Link native.mjs.
  opencode  OpenCode server plugin (Session Link opencode-plugin) when it is loaded.
  any CLI   its console seat (console_seat.py, fitted from OpenRig seat delivery): typed only
            into an empty composer, re-checked before Enter.
  cursor, antigravity-ide, grok-bot  desktop apps: workshop_desktop.py (Cursor Desktop Bridge,
            ArchHub ide-live extension), tried before the CLI channels.
Desktop agents with no channel answer with the missing piece (NO_LIVE_CHANNEL / workshop_desktop).

Adapter interface (stable; other channel modules plug in here, e.g. desktop/IDE agents):
    register_adapter(app, adapter)
    adapter(native_id: str | None, text: str, message_id: str, pids: tuple[int, ...])
        -> (state, channel, reason)   state is 'delivered' or 'failed'; reason is shown to the sender.
A registered adapter is tried first for its app; on 'failed' the built-in IPC channel and the
console seat still run. An adapter must deliver now or fail now: no pending state, no queue.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

FOUNDER = 'Ahmed'
# Live delivery node: its typed parameters.
LIVE_NODE = {'id': 'workshop.live', 'params': {'discover_timeout_seconds': 10}}
# Desktop/IDE agents with neither an IPC channel nor a console seat: the exact missing piece.
NO_LIVE_CHANNEL = {
    'cursor': 'the Cursor app session has no console seat and no external input channel; cursor-agent sessions use their console',
    'antigravity': 'the Antigravity app session has no console seat and no external input channel',
    'antigravity-ide': 'the Antigravity IDE session has no console seat and no external input channel',
}
SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_live_deliveries (message_id TEXT NOT NULL, recipient TEXT NOT NULL, "
          "agent TEXT, app TEXT, native_session_id TEXT, channel TEXT, state TEXT NOT NULL, reason TEXT, "
          "at TEXT NOT NULL, ms INTEGER, PRIMARY KEY (message_id, recipient))")


def codex_app_pipes():
    try:
        return sorted(name for name in os.listdir('\\\\.\\pipe\\') if name.startswith('codex-app-tools-'))
    except OSError:
        return []


def codex_caller_thread():
    """The app tools answer only a caller thread they know: the newest recorded local Codex session."""
    import re
    homes = [Path(os.environ.get('CODEX_HOME', '')), Path('C:/Users') / os.environ.get('USERNAME', '') / '.codex']
    for home in homes:
        sessions = home / 'sessions'
        if not sessions.is_dir():
            continue
        newest = max(sessions.rglob('rollout-*.jsonl'), key=lambda p: p.stat().st_mtime, default=None)
        match = newest and re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$', newest.name)
        if match:
            return match.group(1)
    return ''


ADAPTERS = {}


def register_adapter(app, adapter):
    """Plug a live channel in for one agent app (see the interface in the module docstring)."""
    ADAPTERS[str(app)] = adapter


def push(app, native_id, text, message_id, *, timeout=10.0, pids=()):
    """One live push, any agent. Returns (state, channel, reason); never waits for a reply.

    The agent's own IPC channel first (Claude peer pipe, Codex Desktop app tools, OpenCode
    plugin); then its console seat (console_seat.py) for every terminal-hosted agent.
    """
    adapter = ADAPTERS.get(app)
    if adapter is not None:
        try:
            result = adapter(native_id, text, message_id, tuple(pids))
        except Exception as error:  # noqa: BLE001 - an adapter failure falls through to the built-in channels
            result = ('failed', app + '-adapter', str(error)[:200])
        if result[0] == 'delivered':
            return result
    # Desktop apps (Cursor app, Antigravity IDE, Grok Bot): their own channel. A cursor-agent CLI
    # session is also app 'cursor'; when the desktop channel cannot take it, its console seat does.
    from .workshop_desktop import push as desktop_push
    desktop = desktop_push(app, native_id, text, timeout)
    if desktop is not None and (desktop[0] == 'delivered' or not pids):
        return desktop
    from .console_seat import deliver as seat_deliver

    def seat():
        reason = 'no process of this session has a console'
        for pid in pids:
            state, reason = seat_deliver(pid, text)
            if state == 'delivered':
                return 'delivered', 'console-seat', ''
            if state != 'console_unavailable':
                return 'failed', 'console-seat', '%s: %s' % (state, reason)
        return 'failed', 'console-seat', reason
    # A terminal Codex session is reached through its own console at once; the Desktop app tools
    # only know Desktop threads and cost seconds to list.
    if app == 'codex' and pids:
        result = seat()
        if result[0] == 'delivered' or not result[2].startswith('no process'):
            return result
    state, channel, reason = _ipc(app, native_id, text, message_id, timeout)
    if state == 'delivered' or not pids or app == 'codex':
        return state, channel, reason
    result = seat()
    return result if channel == 'none' or result[0] == 'delivered' else (state, channel, reason + '; console seat: ' + result[2])


def _ipc(app, native_id, text, message_id, timeout):
    if app == 'goose' and native_id == 'baboom':
        from .baboom_nograph import deliver_remote
        return deliver_remote(text, message_id, timeout)
    if app in ('claude', 'opencode'):
        channel = 'claude-peer-pipe' if app == 'claude' else 'opencode-plugin'
        env = {}
    elif app == 'codex':
        pipes = codex_app_pipes()
        if not pipes:
            return 'failed', 'codex-app-tools', 'Codex Desktop is not running (no app-tools pipe)'
        channel = 'codex-app-tools'
        caller = codex_caller_thread()
        if not caller:
            return 'failed', channel, 'No Codex session is recorded on this PC to call the app tools from'
        env = {'CODEX_APP_TOOLS_PIPE_PATH': '\\\\.\\pipe\\' + pipes[0], 'CODEX_THREAD_ID': caller}
    else:
        return 'failed', 'none', NO_LIVE_CHANNEL.get(app, '%s has no IPC channel; only its console seat' % app)
    if not native_id or str(native_id).startswith('mcp:'):
        return 'failed', channel, 'The session did not report its native id; it cannot be addressed live'
    from .workshop_mailbox import _local_transport
    transport = _local_transport(env)
    try:
        result = transport.inject({'app': app, 'id': str(native_id)}, text, message_id=message_id, timeout_seconds=timeout)
    except Exception as error:  # noqa: BLE001 - the reason is the answer
        return 'failed', channel, str(error)[:300]
    finally:
        getattr(transport, 'close', lambda: None)()
    if result.get('status') in ('injected', 'ok', 'delivered'):
        return 'delivered', channel, ''
    from .session_link_transport import public_delivery_reason
    return 'failed', channel, public_delivery_reason(result.get('reason') or result.get('error') or result.get('status'))


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
        found = transport.discover(timeout_seconds=LIVE_NODE['params']['discover_timeout_seconds'], apps=['claude', 'codex', 'opencode'])
    except Exception:  # noqa: BLE001 - no discovery means no match, reported by the caller
        found = {}
    finally:
        getattr(transport, 'close', lambda: None)()
    wanted = target.strip().casefold()
    from .workshop_desktop import cursor_threads
    # Cursor agent threads open in the desktop app (Desktop Bridge), addressable by id or title.
    found = {'recipients': list(found.get('recipients', [])) +
             [dict(t, app='cursor', selector='cursor:' + t['id']) for t in cursor_threads()]}
    return [{'session': 'native:%s:%s' % (row['app'], row['id']), 'agent': row.get('title') or row['id'],
             'runtime': row['app'], 'native_session_id': row['id']}
            for row in found.get('recipients', [])
            if wanted in {str(row.get(k) or '').casefold() for k in ('id', 'title', 'selector')}]


def live_agents(with_status=False):
    """Every joined agent session (any provider) with a handle for @mentions, and its status if asked."""
    import re
    from .workshop_mailbox import application_history, read_declarations
    with application_history() as history:
        rows = read_declarations(history._db)
    from .baboom_nograph import own_session
    baboom = own_session()
    agents, seen = [], set()
    for row in rows:
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
        from .console_seat import peek_many
        seats = peek_many(sorted({pid for a in agents if a['app'] not in ('claude',) for pid in a['pids'][:4]}))
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
