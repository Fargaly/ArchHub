"""Live delivery into desktop/IDE agent sessions (adopted channels, no UI automation).

cursor           Cursor's own Desktop Bridge: the main process serves HTTP on a local pipe and lists /
                 sends messages to agent threads open in the app (the `cursor desktop` CLI path).
                 Discovery: ~/.cursor/desktop-bridge/<hash>.json {socketPath, token}. It runs only when
                 Settings > Beta > "Allow CLI to access desktop agents" is on and Cursor's desktop_bridge
                 rollout covers the account.
antigravity-ide  ArchHub's ide-live extension (01.APP/bridges/ide-live) inside Antigravity IDE: a local pipe
                 whose message is submitted with the IDE's own antigravity.sendPromptToAgentPanel command.
                 Discovery: ~/.archhub-live/antigravity-ide-<pid>.json {pipe, token}.
Every function returns (state, channel, reason) like workshop_live.push.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CURSOR_CHANNEL = 'cursor-desktop-bridge'
IDE_CHANNEL = 'ide-live-extension'
# Desktop delivery node: its typed parameters (wait between tries while every pipe instance is busy).
DESKTOP_NODE = {'id': 'workshop.desktop', 'params': {'pipe_retry_seconds': 0.02}}
CURSOR_OFF = ('Cursor Desktop Bridge is off: turn on Settings > Beta > "Allow CLI to access desktop agents" and restart '
              'Cursor (needs Cursor\'s desktop_bridge rollout on this account)')
GROK_BOT_GAP = ('Grok Bot runs its agent sessions in the cloud and exposes no local live-input channel '
                '(no bridge, no extension host; grokbot:// links only open pages)')


def _home():
    return Path(os.environ.get('USERPROFILE') or os.environ.get('HOME') or Path.home())


def _alive(pid):
    import ctypes
    if os.name != 'nt':
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return bool(handle)


def _discovery(folder, pattern):
    """Newest-first live discovery records; files of dead processes are skipped."""
    rows = []
    for path in Path(folder).glob(pattern):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if row.get('pid') and _alive(row['pid']):
            rows.append(row)
    return sorted(rows, key=lambda r: r.get('createdAt', 0), reverse=True)


def _pipe_exchange(pipe, payload, timeout):
    """One request/response over a Windows named pipe (or a unix socket elsewhere)."""
    import socket
    import time
    deadline = time.monotonic() + timeout
    if os.name == 'nt':
        while True:
            try:
                handle = open(pipe, 'r+b', buffering=0)
                break
            except OSError as error:
                if getattr(error, 'winerror', None) != 231 or time.monotonic() > deadline:  # 231 = all pipe instances busy
                    raise
                time.sleep(DESKTOP_NODE['params']['pipe_retry_seconds'])
        with handle:
            handle.write(payload)
            chunks = []
            while True:
                try:
                    chunk = handle.read(65536)
                except OSError as error:
                    if getattr(error, 'winerror', None) == 109:  # broken pipe = server closed after replying
                        break
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
            return b''.join(chunks)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(timeout)
        sock.connect(pipe)
        sock.sendall(payload)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
        return b''.join(chunks)


def _cursor_post(record, body, timeout):
    data = json.dumps(body).encode('utf-8')
    head = ('POST / HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer %s\r\nContent-Type: application/json\r\n'
            'Content-Length: %d\r\nConnection: close\r\n\r\n' % (record['token'], len(data))).encode('ascii')
    raw = _pipe_exchange(record['socketPath'], head + data, timeout)
    status_line, _, rest = raw.partition(b'\r\n')
    payload = rest.partition(b'\r\n\r\n')[2]
    if b'transfer-encoding: chunked' in rest.partition(b'\r\n\r\n')[0].lower():
        out, buf = b'', payload
        while buf:
            size, _, buf = buf.partition(b'\r\n')
            n = int(size.split(b';')[0] or b'0', 16)
            if n == 0:
                break
            out, buf = out + buf[:n], buf[n + 2:]
        payload = out
    code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0
    return code, json.loads(payload or b'{}')


def cursor_records():
    folder = os.environ.get('CURSOR_DESKTOP_BRIDGE_DIR') or str(_home() / '.cursor' / 'desktop-bridge')
    return _discovery(folder, '*.json')


def cursor_threads(timeout=5.0):
    out = []
    for record in cursor_records():
        try:
            code, body = _cursor_post(record, {'type': 'listThreads'}, timeout)
        except (OSError, ValueError):
            continue
        if code == 200:
            out += [dict(t, userDataDir=record.get('userDataDir')) for t in body.get('threads', [])]
    return out


def push_cursor(thread_id, text, timeout=10.0):
    records = cursor_records()
    if not records:
        return 'failed', CURSOR_CHANNEL, CURSOR_OFF
    if not thread_id or str(thread_id).startswith('mcp:'):
        return 'failed', CURSOR_CHANNEL, 'No Cursor agent thread id; list them with cursor_threads()'
    last = 'unknown-thread'
    for record in records:
        try:
            code, body = _cursor_post(record, {'type': 'sendMessage', 'threadId': str(thread_id), 'text': text}, timeout)
        except (OSError, ValueError) as error:
            last = 'Cursor Desktop Bridge did not answer: %s' % str(error)[:200]
            continue
        status = body.get('status')
        if code == 200 and status == 'submitted':
            return 'delivered', CURSOR_CHANNEL, ''
        if code == 200 and status == 'queued':
            # Cursor's own behaviour for a thread that is mid-turn: the message joins that running turn's queue.
            return 'delivered', CURSOR_CHANNEL, 'joined the running turn (Cursor queued it behind the current step)'
        if status == 'unknown-thread':
            continue
        last = body.get('reason') or body.get('message') or body.get('error') or status or ('HTTP %s' % code)
    return 'failed', CURSOR_CHANNEL, 'Cursor: %s' % last


def ide_records(app):
    folder = os.environ.get('ARCHHUB_IDE_LIVE_DIR') or str(_home() / '.archhub-live')
    return _discovery(folder, '%s-*.json' % app)


def push_ide(app, native_id, text, timeout=10.0, fresh=False):
    records = ide_records(app)
    if native_id and str(native_id) not in ('', 'active', 'new') and not str(native_id).startswith('mcp:'):
        records = [r for r in records if str(r.get('pid')) == str(native_id)] or records
    if not records:
        return 'failed', IDE_CHANNEL, ('%s is not running with the ArchHub ide-live extension '
                                       '(install 01.APP/bridges/ide-live into it)' % app)
    record = records[0]
    try:
        raw = _pipe_exchange(record['pipe'], (json.dumps({'token': record['token'], 'text': text, 'fresh': fresh}) + '\n').encode('utf-8'), timeout)
        reply = json.loads(raw or b'{}')
    except (OSError, ValueError) as error:
        return 'failed', IDE_CHANNEL, '%s extension did not answer: %s' % (app, str(error)[:200])
    if reply.get('status') == 'injected':
        return 'delivered', IDE_CHANNEL, ''
    return 'failed', IDE_CHANNEL, '%s: %s' % (app, reply.get('reason') or 'no reply')


def push(app, native_id, text, timeout=10.0):
    if app == 'cursor':
        return push_cursor(native_id, text, timeout)
    if app == 'antigravity-ide':
        # native id 'new' opens a fresh conversation first; anything else goes to the open one (or a pid).
        return push_ide('antigravity-ide', native_id, text, timeout, fresh=str(native_id) == 'new')
    if app in ('grok-bot', 'grokbot'):
        return 'failed', 'none', GROK_BOT_GAP
    return None
