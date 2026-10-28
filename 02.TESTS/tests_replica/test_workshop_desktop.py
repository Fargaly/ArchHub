"""Desktop/IDE live delivery: Cursor Desktop Bridge and the ide-live extension; delivered now or failed now."""
import json
import os

import pytest


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv('CURSOR_DESKTOP_BRIDGE_DIR', str(tmp_path / 'bridge'))
    monkeypatch.setenv('ARCHHUB_IDE_LIVE_DIR', str(tmp_path / 'ide'))
    (tmp_path / 'bridge').mkdir()
    (tmp_path / 'ide').mkdir()
    return tmp_path


def record(folder, name, **row):
    row.setdefault('pid', os.getpid())
    (folder / name).write_text(json.dumps(row))


def http(status, body):
    data = json.dumps(body).encode()
    return b'HTTP/1.1 %d OK\r\ncontent-type: application/json\r\ncontent-length: %d\r\n\r\n' % (status, len(data)) + data


def test_closed_apps_fail_now_with_the_route(dirs):
    from nodelang.workshop_live import push
    assert push('cursor', 't1', 'hi', 'm')[2].startswith('Cursor Desktop Bridge is off')
    state, channel, reason = push('antigravity-ide', 'active', 'hi', 'm')
    assert state == 'failed' and channel == 'ide-live-extension' and 'ide-live' in reason
    assert 'cloud' in push('grok-bot', 'x', 'hi', 'm')[2]


def test_dead_process_records_are_ignored(dirs):
    from nodelang import workshop_desktop as d
    record(dirs / 'bridge', 'a.json', pid=999999, socketPath='p', token='t')
    assert d.cursor_records() == []


def test_cursor_bridge_submits_into_the_thread(dirs, monkeypatch):
    from nodelang import workshop_desktop as d
    record(dirs / 'bridge', 'a.json', socketPath='pipe-a', token='tok', createdAt=1)
    sent = []

    def exchange(pipe, payload, timeout):
        sent.append((pipe, payload))
        body = json.loads(payload.split(b'\r\n\r\n', 1)[1])
        return http(200, {'status': 'submitted', 'threadId': body['threadId'], 'windowId': 1, 'threadTitle': 'T'})
    monkeypatch.setattr(d, '_pipe_exchange', exchange)
    assert d.push('cursor', 'thread-1', 'hello', 5) == ('delivered', 'cursor-desktop-bridge', '')
    head, body = sent[0][1].split(b'\r\n\r\n', 1)
    assert sent[0][0] == 'pipe-a' and b'Authorization: Bearer tok' in head
    assert json.loads(body) == {'type': 'sendMessage', 'threadId': 'thread-1', 'text': 'hello'}


def test_cursor_unknown_thread_and_not_sendable_are_reasons(dirs, monkeypatch):
    from nodelang import workshop_desktop as d
    record(dirs / 'bridge', 'a.json', socketPath='pipe-a', token='tok')
    monkeypatch.setattr(d, '_pipe_exchange', lambda *a: http(200, {'status': 'unknown-thread'}))
    assert d.push('cursor', 'nope', 'hi')[2] == 'Cursor: unknown-thread'
    monkeypatch.setattr(d, '_pipe_exchange', lambda *a: http(200, {'status': 'not-sendable', 'reason': 'Draft threads cannot accept messages.'}))
    assert 'Draft' in d.push('cursor', 'draft', 'hi')[2]


def test_ide_extension_reply_and_fresh_flag(dirs, monkeypatch):
    from nodelang import workshop_desktop as d
    record(dirs / 'ide', 'antigravity-ide-1.json', pipe='pipe-ag', token='k')
    seen = []
    monkeypatch.setattr(d, '_pipe_exchange', lambda pipe, payload, t: seen.append(json.loads(payload)) or b'{"status":"injected"}\n')
    assert d.push('antigravity-ide', 'new', 'hi')[0] == 'delivered'
    assert seen[0] == {'token': 'k', 'text': 'hi', 'fresh': True}
    monkeypatch.setattr(d, '_pipe_exchange', lambda *a: b'{"status":"failed","reason":"unauthorized"}\n')
    assert d.push('antigravity-ide', 'active', 'hi') == ('failed', 'ide-live-extension', 'antigravity-ide: unauthorized')


def test_cursor_threads_are_addressable_by_title(dirs, monkeypatch):
    from nodelang import workshop_desktop as d, workshop_live, workshop_mailbox

    class Transport:
        def discover(self, **k):
            raise OSError('no session link')
    monkeypatch.setattr(workshop_mailbox, '_local_transport', lambda *a: Transport())
    monkeypatch.setattr(d, 'cursor_threads', lambda timeout=5.0: [{'id': 'th-9', 'title': 'Fix tests'}])
    assert workshop_live.discover_target('fix tests') == [
        {'session': 'native:cursor:th-9', 'agent': 'Fix tests', 'runtime': 'cursor', 'native_session_id': 'th-9'}]
