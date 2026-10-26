"""WSRECEIPTS: real store/HTTP concurrency, no founder profile or desktop."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import workshop_mailbox as mail
from nodelang.application_server import ApplicationServer
from nodelang.clean_coordination_host import CleanCoordinationHost
from nodelang.clean_coordination_service import build_bound_service
from nodelang.conversation_history import ConversationHistoryStore
from tests_replica.test_newapp_mailbox import peer


class MeasuredLock:
    def __init__(self):
        self.lock = threading.RLock()
        self.local = threading.local()
        self.holds = []

    def __enter__(self):
        self.lock.acquire()
        self.local.started = time.monotonic()
        return self

    def __exit__(self, *_):
        self.holds.append(time.monotonic() - self.local.started)
        self.lock.release()


@pytest.fixture
def receipt_room(tmp_path, monkeypatch):
    from nodelang import cloud_session
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda: None)
    path = tmp_path / 'ROOM.sqlite3'
    with ConversationHistoryStore(path, instance_id='wsreceipts') as history:
        history._db.execute('PRAGMA journal_mode=WAL')
        history.ensure_conversation(mail.ROOM)
        owner = SimpleNamespace(mutation_lock=MeasuredLock(),
            universal_store=SimpleNamespace(database_path=path, authority_identity='fixture', revision=0),
            universal_registry=SimpleNamespace(authorization=SimpleNamespace(subject_root='fixture')),
            conversation_content=SimpleNamespace(_history=history, _require_live_owner=lambda: None))
        owner.shared_agent_mail = lambda method, body, **kw: ApplicationServer.shared_agent_mail(owner, method, body, **kw)
        yield owner, history, path


def test_external_read_is_read_only_and_changes_zero_rows(receipt_room, monkeypatch):
    owner, history, path = receipt_room
    owner.shared_agent_mail('declare', {'task':'receipt court', 'paths':[str(path.parent)],
        'status':'working', 'request_id':'WSRECEIPTS', 'context':{'threadId':'reader'}}, peer=peer())
    owner.shared_agent_mail('send', {'to':'codex', 'text':'one note'}, peer=peer())
    before = history._db.execute('SELECT count(*) FROM messages').fetchone()[0]
    original = sqlite3.connect
    opened = []
    def connect(database, *args, **kw):
        opened.append(str(database))
        return original(database, *args, **kw)
    monkeypatch.setattr(mail.sqlite3, 'connect', connect)
    result = mail.call('read', {'since':0}, {'threadId':'reader'}, database=path, peer=peer())
    assert result['messages']
    assert opened and all('mode=ro' in value for value in opened), opened
    assert history._db.execute('SELECT count(*) FROM messages').fetchone()[0] == before


@pytest.mark.parametrize('value', [True, float('nan'), 3.0])
def test_store_wait_budget_cannot_exceed_two_seconds(receipt_room, value):
    with pytest.raises(ValueError, match='lock wait'):
        mail.call('read', {'since':0}, {}, database=receipt_room[2], store_busy_timeout_seconds=value)


def test_routing_metadata_does_not_become_visible_research_citations():
    from nodelang.research_owner import ResearchOwner
    owner = SimpleNamespace(api=SimpleNamespace(admit=lambda:SimpleNamespace(cells={})),
        _citation_root=lambda message:message)
    assert ResearchOwner.sources(owner, 'message', [mail.ROUTING_EVIDENCE, '{}'], [])['sources'] == []
    normal = ResearchOwner.sources(owner, 'message', ['https://source.example'], [])
    assert normal['sources'][0]['sourceId'] == 'https://source.example'


@pytest.mark.parametrize('method,body', [('send', {'to':'*','text':'offline'}),
    ('declare', {'task':'offline','paths':['C:/FIXTURE'],'status':'working','request_id':'WSRECEIPTS'})])
def test_external_mutation_without_application_refuses_and_changes_zero_rows(receipt_room, method, body):
    _owner, history, path = receipt_room
    before = history._db.total_changes
    with pytest.raises(ValueError, match='application.*unavailable|application.*required'):
        mail.call(method, body, {}, database=path, peer=peer())
    assert history._db.total_changes == before
    assert history._db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert history._db.execute("SELECT count(*) FROM sqlite_master WHERE name='workshop_declarations'").fetchone()[0] == 0


def test_worker_upserts_one_cursor_and_read_never_acknowledges_its_new_page(receipt_room):
    owner, history, path = receipt_room
    context = {'threadId':'cursor-reader'}
    owner.shared_agent_mail('declare', {'task':'cursor', 'paths':[str(path.parent)], 'status':'working',
        'request_id':'WSRECEIPTS', 'context':context}, peer=peer())
    worker = mail.WorkshopInjection(owner, None)
    owner.workshop_injection = worker
    first = owner.shared_agent_mail('send', {'to':'codex','text':'first'}, peer=peer())
    worker.tick()
    page = owner.shared_agent_mail('read', {'since':0, 'context':context}, peer=peer())
    assert [row['id'] for row in page['messages']] == [first['message_id']]
    assert all(row['author'] != mail.DELIVERY_AUTHOR for row in page['messages'])
    worker.tick()
    assert owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']
    owner.shared_agent_mail('read', {'since':page['next_since'], 'context':context}, peer=peer())
    worker.tick()
    assert not owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']
    from nodelang.conversation_archive import export_messages
    archive = path.parent / 'ARCHIVE.jsonl'
    def export():
        rows = [history._message(row) for row in history._db.execute('SELECT * FROM messages ORDER BY sequence')]
        return export_messages(archive, mail.ROOM, history.instance_id, rows)
    assert export()
    second = owner.shared_agent_mail('send', {'to':'codex','text':'second'}, peer=peer())
    worker.tick()
    page = owner.shared_agent_mail('read', {'since':first['sequence'], 'context':context}, peer=peer())
    assert next(row for row in page['messages'] if row['id']==second['message_id'])['state'] == 'pending'
    owner.shared_agent_mail('read', {'since':page['next_since'], 'context':context}, peer=peer())
    worker.tick()
    cursors = history._db.execute('SELECT record FROM workshop_delivery_cursors').fetchall()
    assert len(cursors) == 1 and json.loads(cursors[0][0])['since'] == second['sequence']
    assert second['sequence'] in export(), 'advancing a cursor must not alter any archived message'
    assert history._db.execute("SELECT count(*) FROM messages WHERE json_valid(content) "
        "AND json_extract(content,'$.event')='delivered'").fetchone()[0] == 0


def test_late_reply_is_recorded_by_worker(receipt_room):
    owner, history, path = receipt_room
    context = {'threadId':'late-reader'}
    declared = owner.shared_agent_mail('declare', {'task':'late reply','paths':[str(path.parent)],
        'status':'working','request_id':'WSRECEIPTS','context':context}, peer=peer())
    worker = mail.WorkshopInjection(owner, None)
    note = owner.shared_agent_mail('send', {'to':'codex','text':'answer eventually'}, peer=peer())
    started = time.time()
    for offset in (0,61,121):
        worker.tick(now=started+offset)
    assert 'attempt' in mail.delivery_events(history, {'id':note['message_id']})[declared['sender_key']]
    owner.shared_agent_mail('send', {'to':'*','text':'late answer','reply_to':note['message_id'],
        'context':context}, peer=peer())
    worker.tick(now=started+122)
    owner.shared_agent_mail('send', {'to':'*','text':'additional answer','reply_to':note['message_id'],
        'context':context}, peer=peer())
    worker.tick(now=started+123)
    assert 'answered' in mail.delivery_events(history, {'id':note['message_id']})[declared['sender_key']]


def test_authenticated_pipe_dispatch_uses_application_sink_outside_store_wait(receipt_room):
    from nodelang.installed_workshop_coordination import dispatch_mailbox
    owner, _history, _path = receipt_room
    result = dispatch_mailbox(owner, {'method':'POST','path':'/api/universal/agent-mail/send',
        'session':{}, 'body':{'to':'*','text':'pipe route','context':{'threadId':'spoofed'}}}, peer())
    assert result['sender_key'] == mail._identity({}, peer())[0]['sender_key']
    assert result['message_id']


def test_broadcast_snapshot_excludes_sender_and_retry_keeps_original_recipients(receipt_room):
    owner, history, path = receipt_room
    context = {'threadId':'broadcast-sender'}
    declared = owner.shared_agent_mail('declare', {'task':'broadcast','paths':[str(path.parent)],
        'status':'working','request_id':'WSRECEIPTS','context':context}, peer=peer())
    body = {'to':'*','text':'broadcast to others','idempotency_key':'one-broadcast','context':context}
    original = owner.shared_agent_mail('send', body, peer=peer())
    owner.shared_agent_mail('declare', {'task':'late reader','paths':[str(path.parent/'LATE')],
        'status':'working','request_id':'WSRECEIPTS','context':{'threadId':'late'}}, peer=peer())
    retry = owner.shared_agent_mail('send', body, peer=peer())
    assert retry['message_id'] == original['message_id']
    worker = mail.WorkshopInjection(owner, None)
    worker.tick()
    events = mail.delivery_events(history, {'id':original['message_id']})
    assert declared['sender_key'] not in events


@pytest.mark.parametrize('page_protection', [False, True])
def test_delivery_cursor_survives_retention_upgrade_and_normal_reopen(receipt_room, page_protection):
    owner, history, path = receipt_room
    worker = mail.WorkshopInjection(owner, None)
    owner.workshop_injection = worker
    note = owner.shared_agent_mail('send', {'to':'*','text':'reopen cursor'}, peer=peer())
    owner.shared_agent_mail('read', {'since':note['sequence'],'context':{'threadId':'reader'}}, peer=peer())
    worker.tick()
    history.initialize_retention()
    if page_protection:
        history.initialize_page_protection()
    with ConversationHistoryStore(path, instance_id=history.instance_id, create=False) as reopened:
        assert reopened._db.execute('SELECT count(*) FROM workshop_delivery_cursors').fetchone()[0] == 1
        assert reopened.conversation_head(mail.ROOM) >= note['sequence']


def _request(surface, method, body, *, timeout_seconds: float = 3.0):
    request = Request('http://127.0.0.1:%d/coordination' % surface.server_address[1],
        data=json.dumps({'method':'GET' if method=='read' else 'POST',
            'path':'/api/universal/agent-mail/'+method, 'body':body}).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def test_founder_scale_reads_during_blocking_transport(receipt_room, monkeypatch, *,
        poll_seconds: float = .1, block_seconds: float = 5.0,
        read_budget_seconds: float = 2.0, lock_budget_seconds: float = .2):
    owner, history, path = receipt_room
    from datetime import datetime, timezone
    for index in range(10):
        owner.shared_agent_mail('declare', {'task':'scale reader', 'paths':[str(path.parent/str(index))],
            'status':'working', 'request_id':'WSRECEIPTS', 'context':{'threadId':'poll-'+str(index)}}, peer=peer())
    stamp = datetime.now(timezone.utc).isoformat()
    history._db.execute('BEGIN IMMEDIATE')
    try:
        history._db.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ((str(i), mail.ROOM, i, 'Fixture sender', 'To codex:\n' + 'x'*1024,
                mail.CATEGORY, '[]','[]','[]',None,stamp,'fixture:'+str(i),1) for i in range(1,60001)))
        history._db.execute('UPDATE conversations SET last_sequence=60000 WHERE id=?', (mail.ROOM,))
        history._db.execute('COMMIT')
    except BaseException:
        history._db.execute('ROLLBACK')
        raise
    assert history._db.execute('SELECT count(*) FROM messages').fetchone()[0] == 60000
    owner.shared_agent_mail('declare', {'task':'scale', 'paths':[str(path.parent/'READER')], 'status':'working',
        'request_id':'WSRECEIPTS', 'context':{'threadId':'reader'}}, peer=peer())
    note = owner.shared_agent_mail('send', {'to':'codex','text':'blocking transport'}, peer=peer())
    entered = threading.Event()
    class BlockingTransport:
        def inject(self, *_args, **_kw):
            entered.set()
            time.sleep(block_seconds)
            return {'status':'injected'}
    delivery = mail.WorkshopInjection(owner, BlockingTransport())
    owner.workshop_injection = delivery
    surface = build_bound_service(CleanCoordinationHost(owner))
    server = threading.Thread(target=surface.serve_forever, daemon=True)
    completed_ticks = []
    def ticks():
        for _ in range(2):
            delivery.tick()
            completed_ticks.append(True)
    tick = threading.Thread(target=ticks)
    server.start()
    owner.mutation_lock.holds.clear()
    times = []
    errors = []
    def poll(index):
        since = 0
        while not entered.is_set():
            time.sleep(.01)
        until = time.monotonic() + 2*block_seconds + poll_seconds
        while time.monotonic() < until:
            started = time.monotonic()
            try:
                page = _request(surface, 'read', {'since':since,'context':{'threadId':'poll-'+str(index)}})
                since = page['next_since']
                assert page['messages'] or since >= note['sequence']
            except Exception as exc:
                errors.append(repr(exc))
            times.append(time.monotonic()-started)
            time.sleep(poll_seconds)
    try:
        tick.start()
        assert entered.wait(3)
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(poll, range(10)))
        tick.join(3)
        assert not tick.is_alive()
        assert len(completed_ticks) == 2
        delivery.tick()  # Flush observations from the final concurrent read round.
        assert not errors, errors
        assert times and max(times) < read_budget_seconds, max(times)
        assert owner.mutation_lock.holds and max(owner.mutation_lock.holds) < lock_budget_seconds
        owner.shared_agent_mail('read', {'since':60000, 'context':{'threadId':'poll-0'}}, peer=peer())
        with mail.application_history(history) as selected:
            delivery._flush_reads(selected)
        parsed = []
        original = ConversationHistoryStore._message
        def counted(self, raw):
            parsed.append(raw['id'])
            return original(self, raw)
        monkeypatch.setattr(ConversationHistoryStore, '_message', counted)
        pending = owner.shared_agent_mail('pending', {'context':{'threadId':'poll-0'}}, peer=peer())
        assert [row['id'] for row in pending['pending']] == [note['message_id']]
        assert len(parsed) <= 20, len(parsed)
        print('FOUNDER_SCALE rows=60000 readers=10 requests=%d max_read=%.6f max_lock=%.6f' %
            (len(times),max(times),max(owner.mutation_lock.holds)))
    finally:
        tick.join(block_seconds+3)
        surface.shutdown()
        server.join(3)
        surface.server_close()


@pytest.mark.parametrize('journal_mode', ['WAL', 'DELETE'])
def test_locked_store_fails_one_request_and_host_keeps_answering(receipt_room, journal_mode, *,
        lock_seconds: float = 10.0, request_budget_seconds: float = 2.5):
    owner, history, path = receipt_room
    history._db.execute('PRAGMA journal_mode='+journal_mode)
    surface = build_bound_service(CleanCoordinationHost(owner))
    server = threading.Thread(target=surface.serve_forever, daemon=True)
    server.start()
    locked = threading.Event()
    def hold():
        with closing(sqlite3.connect(path, isolation_level=None)) as other:
            other.execute('BEGIN IMMEDIATE')
            locked.set()
            time.sleep(lock_seconds)
            other.execute('ROLLBACK')
    writer = threading.Thread(target=hold)
    writer.start()
    try:
        assert locked.wait(2)
        started = time.monotonic()
        with pytest.raises(HTTPError) as refused:
            _request(surface, 'send', {'to':'*','text':'bounded lock failure'})
        elapsed = time.monotonic()-started
        detail = json.load(refused.value)
        assert elapsed < request_budget_seconds
        assert 'locked' in detail['error'].lower() or 'busy' in detail['error'].lower(), detail
        assert _request(surface, 'read', {'since':0})['messages'] == []
        with owner.mutation_lock:
            pass
        assert max(owner.mutation_lock.holds) < .2
        writer.join(lock_seconds+1)
        assert _request(surface, 'send', {'to':'*','text':'recovered'})['message_id']
        print('LOCKED_STORE elapsed=%.6f recovered=True' % elapsed)
    finally:
        writer.join(lock_seconds+1)
        surface.shutdown()
        server.join(3)
        surface.server_close()
