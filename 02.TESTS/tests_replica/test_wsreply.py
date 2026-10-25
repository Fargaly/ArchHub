"""WSREPLY: stable recipient identity and send recovery, using isolated stores."""
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hashlib import sha256
import json
import socket
from statistics import median
import sqlite3
import threading
import time

import pytest

from nodelang import workshop_mailbox as mail
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_wsinject import NativeFixture, declare, send
from tests_replica.test_wsnoreply import message, start

pytest_plugins = ('tests_replica.test_wsinject',)


@pytest.mark.parametrize('malformed', ['refs', 'record'])
def test_index_admission_survives_malformed_legacy_json(room, malformed):
    _owner, history = room
    identity = mail._identity({'threadId': 'malformed-index'}, peer())[0]
    body = {'to': 'founder', 'text': 'Index court.', 'idempotency_key': 'malformed'}
    first = mail._queued_send(history, body, identity, None)
    for statement in mail.WORKSHOP_SEND_INDEXES:
        history._db.execute('DROP INDEX ' + statement.split()[2])
    history._db.execute('PRAGMA ignore_check_constraints=ON')
    if malformed == 'refs':
        history._db.execute("UPDATE messages SET refs='{' WHERE id=?", (first['message_id'],))
    else:
        history._db.execute("INSERT INTO workshop_send_queue VALUES('malformed','{')")
    history._db.execute('PRAGMA ignore_check_constraints=OFF')
    # Exercise the real admission owner, not a duplicate CREATE INDEX fixture.
    sent = mail._queued_send(history, {**body, 'idempotency_key': 'valid'}, identity, None)
    assert sent['message_id'] != first['message_id']
    history._validate_retention_source_schema(history._db.execute('PRAGMA user_version').fetchone()[0])


def test_committed_queue_rows_are_removed_and_retry_is_preserved(room):
    owner, history = room
    body = {'to': 'founder', 'text': 'Commit once.', 'idempotency_key': 'pruned-retry'}
    first = owner.shared_agent_mail('send', body, peer=peer(), account='owner@example.test')
    assert history._db.execute('SELECT count(*) FROM workshop_send_queue').fetchone()[0] == 0
    assert owner.shared_agent_mail('send', body, peer=peer())['message_id'] == first['message_id']


def test_pending_cap_is_global_across_sender_keys(room):
    _owner, history = room
    for number in range(128):
        identity = mail._identity({'threadId': f'pending-{number}'}, peer())[0]
        mail._queue_send(history, {'to': 'founder', 'text': 'Pending.',
            'idempotency_key': str(number)}, identity)
    identity = mail._identity({'threadId': 'another-caller'}, peer())[0]
    with pytest.raises(ValueError, match='WORKSHOP_PENDING_SEND_LIMIT'):
        mail._queue_send(history, {'to': 'founder', 'text': 'Over cap.', 'idempotency_key': 'over'}, identity)


def test_stale_worker_snapshot_reuses_committed_send(room, monkeypatch):
    _owner, history = room
    identity = mail._identity({'threadId': 'stale-worker'}, peer())[0]
    body = {'to': 'founder', 'text': 'One snapshot.', 'idempotency_key': 'stale'}
    queued = mail._queue_send(history, body, identity)
    first = mail._queued_send(history, body, identity, None)
    replay = mail._queued_send(history, body, identity, 'verified@example.test', queued=queued)
    assert first['message_id'] == replay['message_id']
    monkeypatch.setattr(mail, '_queue_account', lambda *_args: 'changed-session')
    with pytest.raises(ValueError, match='account session'):
        mail._queued_send(history, body, identity, None, queued=queued)


def test_long_metadata_and_terminal_refusals_leave_no_queue_rows(room):
    _owner, history = room
    identity = mail._identity({'threadId': 'long-metadata'}, peer())[0]
    body = {'to': 'founder', 'text': 'Long account.', 'idempotency_key': 'long'}
    first = mail._queued_send(history, body, identity, 'a' * 256)
    assert mail._queued_send(history, body, identity, None)['message_id'] == first['message_id']
    for number in range(129):
        pending = {**body, 'idempotency_key': str(number)}
        mail._queue_send(history, pending, identity)
        mail._fail_send(history, pending, identity, 'definitively refused')
    assert history._db.execute('SELECT count(*) FROM workshop_send_queue').fetchone()[0] == 0


def test_queue_lookup_plans_use_indexes(room):
    _owner, history = room
    identity = mail._identity({'threadId': 'query-plan'}, peer())[0]
    mail._queue_send(history, {'to': 'founder', 'text': 'Pending.', 'idempotency_key': 'plan'}, identity)
    queries = [
        ("SELECT record FROM workshop_send_queue WHERE json_valid(record) AND json_extract(record,'$.request_key')=? "
            "AND json_extract(record,'$.account_session') IS ?", ('key', None), 'workshop_send_request'),
        ("SELECT record FROM workshop_send_queue WHERE json_valid(record) AND json_extract(record,'$.result') IS NULL "
            "AND json_extract(record,'$.error') IS NULL LIMIT 32", (), 'workshop_send_pending'),
        ("SELECT refs FROM messages WHERE conversation_id=? AND json_valid(refs) AND json_extract(refs,'$[0]')=? "
            "AND json_extract(refs,'$[1]')=?", (mail.ROOM, 'key', 'session:'), 'workshop_send_committed'),
    ]
    for sql, args, expected in queries:
        assert any(expected in row[3] for row in history._db.execute('EXPLAIN QUERY PLAN ' + sql, args))
    history._validate_retention_source_schema(history._db.execute('PRAGMA user_version').fetchone()[0])


def test_queue_at_100000_historical_sends(room, capsys, monkeypatch, tmp_path):
    from contextlib import contextmanager
    from tests_replica.test_wsinject import room as room_fixture

    small = tmp_path / "SMALL"
    small.mkdir()
    with contextmanager(room_fixture.__wrapped__)(small) as small_room:
        histories = [(1000, small_room), (100000, room)]
        measurements = {}
        # This isolated store has no account session; keep live profile I/O out of the SQL benchmark.
        monkeypatch.setattr(mail, '_queue_account', lambda *_args: None)
        # Batch historical setup; time queue SQL separately from filesystem commit latency.
        for size, (owner, history) in histories:
            started = time.perf_counter()
            identity = mail._identity({'threadId': 'history-template'}, peer())[0]
            sent = mail._queued_send(history, {'to': 'founder', 'text': 'Historical send.',
                'idempotency_key': 'template'}, identity, None)
            assert history._db.execute('SELECT count(*) FROM workshop_send_queue').fetchone()[0] == 0
            template = history.get(mail.ROOM, sent['message_id'], principal=identity['sender'])
            history._db.execute('BEGIN IMMEDIATE')
            try:
                # Use the store's existing bulk insertion primitive, including search/count indexes.
                for number in range(history._head(mail.ROOM), size):
                    refs = list(template['refs'])
                    refs[0] = sha256(f'historical-{number}'.encode()).hexdigest()
                    history._insert_indexed({**template, 'refs': refs, 'idempotency_key': f'historical-{number}'},
                        f'historical-{number}', number + 1, template['created_at'])
                history._db.execute('UPDATE conversations SET last_sequence=? WHERE id=?', (size, mail.ROOM))
                history._db.execute('COMMIT')
            finally:
                if history._db.in_transaction:
                    history._db.execute('ROLLBACK')
            elapsed = time.perf_counter() - started
            retained = history._db.execute('SELECT count(*) FROM workshop_send_queue').fetchone()[0]
            sends, ticks, full_sends, full_ticks = [], [], [], []
            worker = mail.WorkshopInjection(owner, None)
            worker._cursor = history._db.execute('SELECT max(sequence) FROM messages').fetchone()[0]
            for _ in range(3):
                worker.tick()
            measurements[size] = {"fixture_seconds": elapsed, "retained": retained, "worker": worker,
                "sends": sends, "ticks": ticks, "full_sends": full_sends, "full_ticks": full_ticks}
        for round_number in range(8):
            # Alternate history sizes within each round to avoid comparing different load periods.
            for size, (owner, history) in (histories if round_number % 2 else list(reversed(histories))):
                row = measurements[size]
                sends, ticks, full_sends = row["sends"], row["ticks"], row["full_sends"]
                round_sends, round_ticks = [], []
                for number in range(30):
                    identity = mail._identity({'threadId': f'measure-{size}-{round_number}-{number}'}, peer())[0]
                    body = {'to': 'founder', 'text': 'Measured.', 'idempotency_key': str(number)}
                    with history._transaction(write=True):
                        start_time = time.perf_counter()
                        queued = mail._queue_send(history, body, identity)
                        round_sends.append((time.perf_counter() - start_time) * 1000)
                        mail._queued_send(history, body, identity, None, queued=queued)
                        full_sends.append((time.perf_counter() - start_time) * 1000)
                    start_time = time.perf_counter()
                    history._db.execute("SELECT record FROM workshop_send_queue "
                        "WHERE json_valid(record) AND json_extract(record,'$.result') IS NULL AND json_extract(record,'$.error') IS NULL LIMIT 32").fetchall()
                    round_ticks.append((time.perf_counter() - start_time) * 1000)
                if round_number:  # Discard one warm-up round before seven measured rounds.
                    sends.append(sum(round_sends) / len(round_sends))
                    ticks.append(sum(round_ticks) / len(round_ticks))
        medians = []
        for size, (owner, history) in histories:
            row = measurements[size]
            sends, ticks = row["sends"], row["ticks"]
            full_sends, full_ticks = row["full_sends"], row["full_ticks"]
            elapsed, retained, worker = row["fixture_seconds"], row["retained"], row["worker"]
            start_time = time.perf_counter()
            worker.tick()
            full_ticks.append((time.perf_counter() - start_time) * 1000)
            indexes = {row[1] for row in history._db.execute('PRAGMA index_list(workshop_send_queue)')}
            with capsys.disabled():
                print(json.dumps({'historical_sends': size, 'fixture_seconds': elapsed,
                    'committed_rows_retained': retained, 'queue_send_ms_median': median(sends), 'queue_send_round_means': sends,
                    'queue_tick_ms_median': median(ticks), 'queue_tick_round_means': ticks, 'queue_send_round_mean_ms_max': max(sends),
                    'queue_tick_round_mean_ms_max': max(ticks), 'full_send_sql_ms_mean': sum(full_sends)/len(full_sends),
                    'full_tick_ms_mean': sum(full_ticks)/len(full_ticks)}))
            assert retained == 0
            assert 'workshop_send_request' in indexes and 'workshop_send_pending' in indexes
            medians.append(median(sends))
            assert medians[-1] <= 25
            assert median(ticks) <= 5
        with capsys.disabled():
            print(json.dumps({"admission_100k_to_1k_ratio": medians[1]/medians[0]}))
        assert medians[1] <= 2.0 * medians[0]



@pytest.mark.parametrize('routed', [False, True])
@pytest.mark.parametrize('archived', [False, True])
def test_reply_from_reconnected_sender_closes_original_recipient(room, routed, archived):
    owner, history = room
    context = {'threadId': '01a084cd-fixture-native'}
    old = declare(owner, context)
    ask = send(owner, to='01a084cd', text='Can you confirm the patch SHA?')
    native = NativeFixture()
    if routed:
        _worker, now = start(owner, history, ask, native)
    else:
        now = datetime.fromisoformat(message(history, ask)['created_at']).timestamp()
    # Account binding creates a new connection key for the same native session.
    new = owner.shared_agent_mail('declare', {'task': 'WSREPLY', 'paths': [str(__file__)],
        'status': 'done' if archived else 'working', 'request_id': 'WSREPLY', 'context': context},
        peer=peer(), account='fixture@example.test')
    assert new['sender_key'] != old['sender_key']
    reply = owner.shared_agent_mail('send', {'to': 'claude', 'text': 'Final verdict: ACCEPT.',
        'reply_to': ask['message_id'], 'context': context}, peer=peer(), account='fixture@example.test')
    for offset in (1, 301, 601, 602):
        mail.WorkshopInjection(owner, native).tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))
    assert events[old['sender_key']]['answered']['reply_message_id'] == reply['message_id']
    assert all('reminder' not in value and 'escalated' not in value for value in events.values())
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? "
        "AND author='Workshop coordination'", (ask['message_id'],)).fetchone()[0] == 0


def test_unrelated_native_session_cannot_close_an_ask(room):
    owner, history = room
    declare(owner, {'threadId': '01a084cd-original'})
    ask = send(owner, to='01a084cd', text='Can you confirm the SHA?')
    native = NativeFixture()
    worker, now = start(owner, history, ask, native)
    declare(owner, {'threadId': 'unrelated-native'})
    owner.shared_agent_mail('send', {'to': 'claude', 'text': 'Done.',
        'reply_to': ask['message_id'], 'context': {'threadId': 'unrelated-native'}}, peer=peer())
    for offset in (301, 601, 602):
        worker.tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))
    assert not any('answered' in row for row in events.values())
    assert sum('reminder' in row for row in events.values()) == 1
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? "
        "AND author='Workshop coordination'", (ask['message_id'],)).fetchone()[0] == 1


def test_reply_binding_survives_another_redeclare_and_a_busy_room(room):
    owner, history = room
    context = {'threadId': '01a084cd-native'}
    old = declare(owner, context)
    ask = send(owner, to='01a084cd', text='Can you confirm the SHA?')
    native = NativeFixture()
    _worker, now = start(owner, history, ask, native)
    for account in ('first@example.test', 'second@example.test'):
        owner.shared_agent_mail('declare', {'task': 'WSREPLY', 'paths': [str(__file__)],
            'status': 'working', 'request_id': 'WSREPLY', 'context': context}, peer=peer(), account=account)
        if account.startswith('first'):
            reply = owner.shared_agent_mail('send', {'to': 'claude', 'text': 'Done.',
                'reply_to': ask['message_id'], 'context': context}, peer=peer(), account=account)
    for index in range(140):
        history.append(mail.ROOM, author='fixture', category=mail.CATEGORY,
            content='Unrelated status.', idempotency_key=f'busy-{index}')
    for offset in (301, 601):
        mail.WorkshopInjection(owner, native).tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))[old['sender_key']]
    assert events['answered']['reply_message_id'] == reply['message_id']
    assert 'reminder' not in events and 'escalated' not in events


def test_replay_after_account_verification_becomes_pending_is_exactly_once(room):
    owner, _history = room
    body = {'to': 'founder', 'text': 'One send.', 'idempotency_key': 'account-transition',
        'context': {'threadId': 'account-fixture'}}
    first = owner.shared_agent_mail('send', body, peer=peer(), account='owner@example.test')
    replay = owner.shared_agent_mail('send', body, peer=peer(), account=None)
    assert replay['message_id'] == first['message_id']
    other = owner.shared_agent_mail('send', body, peer=peer(), account='other@example.test')
    assert other['message_id'] != first['message_id'], 'separate verified accounts retain separate retry scopes'


def test_replay_after_pending_account_is_verified_is_exactly_once(room):
    owner, _history = room
    body = {'to': 'founder', 'text': 'One pending send.', 'idempotency_key': 'pending-transition',
        'context': {'threadId': 'account-fixture'}}
    first = owner.shared_agent_mail('send', body, peer=peer(), account=None)
    replay = owner.shared_agent_mail('send', body, peer=peer(), account='owner@example.test')
    assert replay['message_id'] == first['message_id']
    other = owner.shared_agent_mail('send', body, peer=peer(), account='other@example.test')
    assert other['message_id'] != first['message_id']
    with pytest.raises(ValueError, match='ambiguous'):
        owner.shared_agent_mail('send', body, peer=peer(), account=None)


def test_ambiguous_account_does_not_cancel_pending_sends(room):
    owner, history = room
    identity = mail._identity({'threadId': 'pending-scope'}, peer())[0]
    body = {'to': 'founder', 'text': 'Pending account court.', 'idempotency_key': 'pending-scope'}
    for account in ('first@example.test', 'second@example.test'):
        mail._queue_send(history, body, identity, account)
    with pytest.raises(ValueError, match='ambiguous'):
        owner.shared_agent_mail('send', {**body, 'context': {'threadId': 'pending-scope'}}, peer=peer())
    assert history._db.execute("SELECT count(*) FROM workshop_send_queue "
        "WHERE json_extract(record,'$.error') IS NULL AND json_extract(record,'$.result') IS NULL").fetchone()[0] == 2


@pytest.mark.parametrize('extra', [{'reply_to': []}, {'native_control': {'app': 'codex', 'id': 'wrong'}}])
def test_invalid_offline_send_is_not_queued(room, extra):
    owner, history = room
    identity = mail._identity({'threadId': 'invalid-queue'}, peer())[0]
    with pytest.raises(ValueError):
        mail._queue_send(history, {'to': 'founder', 'text': 'Invalid.', 'idempotency_key': 'invalid', **extra}, identity)
    assert history._db.execute("SELECT name FROM sqlite_master WHERE name='workshop_send_queue'").fetchone() is None
    with pytest.raises(ValueError):
        owner.shared_agent_mail('send', {'to': 'founder', 'text': 'Invalid.', **extra,
            'context': {'threadId': 'invalid-queue'}}, peer=peer())


def test_uncommitted_send_is_durable_after_caller_exits(room, monkeypatch):
    owner, history = room
    path = history._db.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(path))
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:18474/coordination')
    monkeypatch.setattr(mail, 'profile_database', lambda: __import__('pathlib').Path(path))
    class Offline:
        def open(self, *_args, **_kwargs):
            raise mail.URLError(ConnectionRefusedError(10061, 'fixture restart'))
    monkeypatch.setattr(mail, 'build_opener', lambda *_args: Offline())
    with pytest.raises((ValueError, mail.URLError)):
        mail.call('send', {'to': 'founder', 'text': 'Persist across boot.',
            'idempotency_key': 'durable-fixture'}, {'threadId': 'durable-native'},
            peer=peer(), timeout_seconds=0.01)
    assert history._db.execute('SELECT count(*) FROM messages WHERE category=?', (mail.CATEGORY,)).fetchone()[0] == 0
    # No client retry remains. A fresh application worker recovers the existing store.
    monkeypatch.setattr('nodelang.cloud_session.signed_in_cloud_account', lambda **_kw: None)
    mail.WorkshopInjection(owner, None).tick()
    mail.WorkshopInjection(owner, None).tick()
    rows = history._db.execute('SELECT id FROM messages WHERE category=? AND content=?',
        (mail.CATEGORY, 'To founder:\nPersist across boot.')).fetchall()
    assert len(rows) == 1


def test_pending_send_cannot_follow_a_different_signed_in_account(room, monkeypatch):
    _owner, history = room
    identity = mail._identity({'threadId': 'queued-account'}, peer())[0]
    body = {'to': 'founder', 'text': 'Account-bound queue.', 'idempotency_key': 'queue-account'}
    monkeypatch.setattr(mail, '_queue_account', lambda *_args: 'original-account-keyring-reference')
    queued = mail._queue_send(history, body, identity)
    monkeypatch.setattr(mail, '_queue_account', lambda *_args: 'different-account-keyring-reference')
    with pytest.raises(ValueError, match='account session'):
        mail._queued_send(history, body, identity, 'other@example.test', queued=queued)
    assert history._db.execute('SELECT count(*) FROM messages WHERE category=?', (mail.CATEGORY,)).fetchone()[0] == 0


def test_definitive_refusal_after_transient_failure_is_not_replayed(room, monkeypatch):
    owner, history = room
    path = history._db.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(path))
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:18474/coordination')
    monkeypatch.setattr(mail, 'profile_database', lambda: __import__('pathlib').Path(path))
    class Refused:
        attempts = 0
        def open(self, *_args, **_kwargs):
            self.attempts += 1
            raise mail.HTTPError('http://127.0.0.1:18474/coordination',
                503 if self.attempts == 1 else 403, 'fixture refusal', {}, None)
    transport = Refused()
    monkeypatch.setattr(mail, 'build_opener', lambda *_args: transport)
    with pytest.raises(mail.HTTPError) as failure:
        mail.call('send', {'to': 'founder', 'text': 'Must stay refused.', 'idempotency_key': 'refusal'},
            {'threadId': 'refused-native'}, peer=peer(), timeout_seconds=1)
    assert failure.value.code == 403
    monkeypatch.setattr('nodelang.cloud_session.signed_in_cloud_account', lambda **_kw: None)
    mail.WorkshopInjection(owner, None).tick()
    assert history._db.execute('SELECT count(*) FROM messages WHERE category=?', (mail.CATEGORY,)).fetchone()[0] == 0


@pytest.mark.parametrize('committed', [False, True])
def test_send_started_before_quit_survives_restart_exactly_once(room, monkeypatch, committed):
    owner, history = room
    monkeypatch.setattr(mail, 'profile_database', lambda: __import__('pathlib').Path(
        history._db.execute('PRAGMA database_list').fetchone()[2]))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(history._database_uri))
    entered, quit_requested, restarted = threading.Event(), threading.Event(), threading.Event()
    bodies, errors, results = [], [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            bodies.append(payload['body'])
            if len(bodies) == 1:
                entered.set()
                assert quit_requested.wait(5)
                if committed:
                    owner.shared_agent_mail('send', payload['body'], peer=peer())
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            assert restarted.wait(5)
            result = owner.shared_agent_mail('send', payload['body'], peer=peer())
            raw = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    address = server.server_address
    monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', f'http://127.0.0.1:{address[1]}/coordination')
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    def sending():
        try:
            results.append(mail.call('send', {'to': 'founder', 'text': 'Restart court.'},
                {'threadId': 'restart-fixture'}, peer=peer(), timeout_seconds=5))
        except Exception as error:
            errors.append(error)
    caller = threading.Thread(target=sending)
    caller.start()
    try:
        assert entered.wait(5), 'send must begin before quit-request'
        quit_requested.set()
        server.shutdown()
        server.server_close()
        serving.join(5)
        # A new HTTP owner, using the same existing durable conversation store.
        server = ThreadingHTTPServer(address, Handler)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        restarted.set()
        caller.join(8)
        assert not caller.is_alive()
        assert not errors, repr(errors)
        assert len(results) == 1
        assert len(bodies) >= 2
        assert len({body['idempotency_key'] for body in bodies}) == 1
        path = history._db.execute('PRAGMA database_list').fetchone()[2]
        with closing(sqlite3.connect(path)) as fresh:
            rows = fresh.execute('SELECT id FROM messages WHERE category=? AND content=?',
                (mail.CATEGORY, 'To founder:\nRestart court.')).fetchall()
        assert rows == [(results[0]['message_id'],)]
    finally:
        restarted.set()
        quit_requested.set()
        caller.join(8)
        server.shutdown()
        server.server_close()
        serving.join(5)


@pytest.mark.parametrize('reply_count', [1, 2])
@pytest.mark.parametrize('before_first_tick', [False, True])
def test_undeclared_codex_same_address_reply_closes_ask(room, monkeypatch, reply_count, before_first_tick):
    from dataclasses import replace

    owner, history = room
    address = '01a084cd-0000-4000-8000-000000000001'
    # Match build 57: OS connection keys, no declarations or native session metadata.
    monkeypatch.setattr(mail, 'mailbox_label', lambda *_: ('Codex', None))
    asker = replace(peer(), pid=90744)
    ask = owner.shared_agent_mail('send', {'to': address, 'text': 'Can you confirm the patch SHA?'}, peer=asker)
    worker = mail.WorkshopInjection(owner, None, backfill_minutes=30.0)
    now = datetime.fromisoformat(message(history, ask)['created_at']).timestamp()
    if not before_first_tick:
        worker.tick(now=now)
    replies = []
    for pid in (155620, 170276)[:reply_count]:
        replies.append(owner.shared_agent_mail('send', {'to': address, 'text': 'Final verdict: ACCEPT.',
            'reply_to': ask['message_id']}, peer=replace(peer(), pid=pid)))
        routing = mail._routing(message(history, replies[-1]))
        assert routing['sender'] == {'runtime': None, 'session': replies[-1]['sender_key']}
        assert not routing['recipients']
    # Restart at timer boundaries so receipt closure must be durable.
    for offset in (1, 301, 601, 602):
        mail.WorkshopInjection(owner, None, backfill_minutes=30.0).tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))
    assert events['address:' + address]['answered']['reply_message_id'] in {r['message_id'] for r in replies}
    assert all('reminder' not in row and 'escalated' not in row for row in events.values())
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'",
        (ask['message_id'],)).fetchone()[0] == 0


@pytest.mark.parametrize('variant', ['different-address', 'asker', 'no-parent', 'quoted-address', 'broadcast'])
def test_address_reply_spoof_keeps_one_reminder_and_escalation(room, monkeypatch, variant):
    from dataclasses import replace

    owner, history = room
    address = '01a084cd-0000-4000-8000-000000000001'
    monkeypatch.setattr(mail, 'mailbox_label', lambda *_: ('Codex', None))
    asker = replace(peer(), pid=90744)
    ask = owner.shared_agent_mail('send', {'to': address, 'text': 'Can you confirm the SHA?'}, peer=asker)
    worker = mail.WorkshopInjection(owner, None, backfill_minutes=30.0)
    now = datetime.fromisoformat(message(history, ask)['created_at']).timestamp()
    worker.tick(now=now)
    target = ('other-task' if variant in ('different-address', 'quoted-address') else
        '*' if variant == 'broadcast' else address)
    body = {'to': target, 'text': 'Final verdict: ACCEPT.'}
    if variant != 'no-parent':
        body['reply_to'] = ask['message_id']
    if variant == 'quoted-address':
        body['text'] += '\n> To ' + address + ': '
    owner.shared_agent_mail('send', body, peer=asker if variant == 'asker' else replace(peer(), pid=155620))
    for offset in (1, 301, 601, 602, 1200):
        mail.WorkshopInjection(owner, None, backfill_minutes=30.0).tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))
    assert not any('answered' in row for row in events.values())
    assert sum('reminder' in row for row in events.values()) == 1
    assert sum('escalated' in row for row in events.values()) == 1
    assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to=? AND author='Workshop coordination'",
        (ask['message_id'],)).fetchone()[0] == 1



def test_address_reply_does_not_grant_ack_authority(room, monkeypatch):
    from dataclasses import replace

    owner, history = room
    monkeypatch.setattr(mail, 'mailbox_label', lambda *_: ('Codex', None))
    address = '01a084cd-0000-4000-8000-000000000001'
    ask = send(owner, to=address, text='Can you confirm the SHA?')
    reply = owner.shared_agent_mail('send', {'to': address, 'text': 'Done.',
        'reply_to': ask['message_id']}, peer=replace(peer(), pid=155620))
    identity = {key: reply[key] for key in ('sender', 'sender_key', 'sender_label')}
    assert not mail._can_ack(history, message(history, ask), identity, mail._declaration(history, identity), [])


def test_same_address_reply_cannot_claim_a_declared_native_session(room):
    owner, history = room
    context = {'threadId': '01a084cd-original'}
    declare(owner, context)
    ask = send(owner, to=context['threadId'], text='Can you confirm the SHA?')
    worker, now = start(owner, history, ask, NativeFixture())
    owner.shared_agent_mail('send', {'to': context['threadId'], 'text': 'Done.',
        'reply_to': ask['message_id'], 'context': {'threadId': 'unrelated-native'}}, peer=peer())
    for offset in (1, 301, 601, 602):
        worker.tick(now=now + offset)
    events = mail.delivery_events(history, message(history, ask))
    assert not any('answered' in row for row in events.values())
    assert sum('reminder' in row for row in events.values()) == 1
    assert sum('escalated' in row for row in events.values()) == 1


def test_address_reply_parent_lookup_beyond_recent_tail(room, monkeypatch):
    from dataclasses import replace

    owner, history = room
    monkeypatch.setattr(mail, 'mailbox_label', lambda *_: ('Codex', None))
    address = '01a084cd-0000-4000-8000-000000000001'
    ask = send(owner, to=address, text='Can you confirm the SHA?')
    worker, now = start(owner, history, ask, None)
    reply = owner.shared_agent_mail('send', {'to': address, 'text': 'Done.',
        'reply_to': ask['message_id']}, peer=replace(peer(), pid=155620))
    for number in range(130):
        history.append(mail.ROOM, author='fixture', content='To founder:\nProgress.', category=mail.CATEGORY,
            idempotency_key='busy-room-' + str(number))
    # Force recovery via the parent's indexed reply lookup, independently of the tail pass.
    worker._cursor = history._head(mail.ROOM)
    worker.tick(now=now + 1)
    events = mail.delivery_events(history, message(history, ask))
    assert events['address:' + address]['answered']['reply_message_id'] == reply['message_id']
