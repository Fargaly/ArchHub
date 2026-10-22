"""WSINJECT: executable delivery boundaries; every profile lives in the lane fixture."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import threading
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from nodelang import workshop_mailbox as mail
from nodelang.application_server import ApplicationServer
from nodelang.conversation_history import ConversationHistoryStore
from tests_replica.test_newapp_mailbox import peer
from tests_replica.test_nokey import _post

pytest_plugins = ("tests_replica.test_nokey",)


@pytest.fixture
def room(tmp_path):
    path = tmp_path / 'ROOM.sqlite3'
    with closing(sqlite3.connect(path, isolation_level=None, check_same_thread=False)) as db:
        with ConversationHistoryStore(path, instance_id='wsinject', connection=db) as history:
            history.ensure_conversation(mail.ROOM)
            owner = SimpleNamespace(mutation_lock=threading.RLock(),
                universal_store=SimpleNamespace(database_path=path),
                conversation_content=SimpleNamespace(_history=history, _require_live_owner=lambda: None))
            owner.shared_agent_mail = lambda method, body, **kw: ApplicationServer.shared_agent_mail(owner, method, body, **kw)
            yield owner, history


def declare(owner, context):
    return owner.shared_agent_mail('declare', {'task':'WSINJECT court', 'paths':[str(Path.cwd() / next(iter(context.values())))],
        'status':'working', 'request_id':'WSINJECT', 'context':context}, peer=peer())


def send(owner, to='codex', text='Please reply here', **kw):
    return owner.shared_agent_mail('send', {'to':to, 'text':text,
        'context':{'claude/sessionID':'claude-fixture'}, **kw}, peer=peer())


class NativeFixture:
    def __init__(self):
        self.turns = []

    def inject(self, recipient, text, **kw):
        self.turns.append((recipient, text, kw))
        return {'status':'injected'}


def test_app_send_injects_existing_public_message_without_recipient_polling(room):
    owner, _history = room
    declare(owner, {'threadId':'codex-fixture'})
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native)
    owner.workshop_injection = delivery
    note = send(owner, text='A message inside the Codex session')
    delivery.tick()
    assert len(native.turns) == 1
    target, text, kw = native.turns[0]
    assert target == {'app':'codex', 'id':'codex-fixture'}
    assert kw['message_id'] == note['message_id'] + ':initial'
    assert 'A message inside the Codex session' in text and note['message_id'] in text
    assert 'not authorization' in text
    delivery.tick()
    assert len(native.turns) == 1, 'ordinary ticks must not replay injection'
    pending = owner.shared_agent_mail('pending', {'context':{'threadId':'codex-fixture'}}, peer=peer())
    assert pending['pending'][0]['id'] == note['message_id'], 'submission is not acknowledgement'
    owner.shared_agent_mail('read', {'since':note['sequence'],
        'context':{'threadId':'codex-fixture'}}, peer=peer())
    delivery.tick()
    assert not owner.shared_agent_mail('pending', {'context':{'threadId':'codex-fixture'}}, peer=peer())['pending']


def test_next_unrelated_mcp_result_carries_pending_and_notification(room, monkeypatch):
    from mcp import types
    from mcp.server.lowlevel.server import request_ctx
    from mcp.shared.context import RequestContext
    from nodelang.native_agent_mcp import build_server
    owner, _history = room
    context = {'gemini/sessionID':'mcp-fixture'}
    recipient = declare(owner, context)
    note = send(owner, to=recipient['sender_label'])
    emitted = []

    async def notify(**kw):
        emitted.append(kw)

    def call(method, body, supplied):
        return owner.shared_agent_mail(method, {**body, 'context':supplied}, peer=peer())

    server = build_server(mailbox_call=call)
    def unrelated() -> dict[str, object]:
        return {'ok':True, 'value':7}
    server.add_tool(unrelated, name='unrelated')
    server.add_tool(lambda: (_ for _ in ()).throw(ValueError('expected failure')), name='broken')

    async def run(name):
        token = request_ctx.set(RequestContext(request_id=1, meta=types.RequestParams.Meta(**context),
            session=SimpleNamespace(send_log_message=notify), lifespan_context={}))
        try:
            return (await server._mcp_server.request_handlers[types.CallToolRequest](
                types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(name=name, arguments={})))).root
        finally:
            request_ctx.reset(token)

    result = asyncio.run(run('unrelated'))
    blocks = [json.loads(item.text) for item in result.content if item.type == 'text']
    assert any(block.get('pending', [{}])[0].get('id') == note['message_id'] for block in blocks if block.get('pending'))
    assert result.structuredContent == {'ok':True, 'value':7}
    assert emitted and emitted[0]['logger'] == 'workshop' and emitted[0]['data']['pending'][0]['id'] == note['message_id']
    assert asyncio.run(run('broken')).isError, 'pending content must preserve tool failure'
    assert not owner.shared_agent_mail('pending', {'context':context}, peer=peer()).get('acknowledged')


def test_unanswered_reinjects_once_then_escalates_and_survives_restart(room):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native, reminder_minutes=1.0, escalation_minutes=2.0)
    owner.workshop_injection = delivery
    note = send(owner)
    original = history.get(mail.ROOM, note['message_id'], principal='court')
    from datetime import datetime
    sent_at = datetime.fromisoformat(original['created_at']).timestamp()
    delivery.tick(now=sent_at)
    delivery.tick(now=sent_at + 60)
    delivery.tick(now=sent_at + 90)
    assert len(native.turns) == 2
    assert 'Reminder' in native.turns[1][1] and 'repeat' in native.turns[1][1]
    delivery = mail.WorkshopInjection(owner, native, reminder_minutes=1.0, escalation_minutes=2.0)
    delivery.tick(now=sent_at + 121)
    delivery.tick(now=sent_at + 180)
    assert len(native.turns) == 2
    notices = history._db.execute("SELECT content FROM messages WHERE author='Workshop coordination' AND reply_to=?",
        (note['message_id'],)).fetchall()
    assert len(notices) == 1 and notices[0][0].startswith('To 717:')


def test_only_addressed_recipient_read_or_reply_confirms_delivery(room):
    owner, _history = room
    declare(owner, {'threadId':'codex-fixture'})
    declare(owner, {'gemini/sessionID':'other-fixture'})
    note = send(owner)
    owner.shared_agent_mail('read', {'since':0, 'context':{'gemini/sessionID':'other-fixture'}}, peer=peer())
    pending = owner.shared_agent_mail('pending', {'context':{'threadId':'codex-fixture'}}, peer=peer())
    assert [row['id'] for row in pending['pending']] == [note['message_id']]
    owner.shared_agent_mail('send', {'to':'claude', 'text':'Received and answering', 'reply_to':note['message_id'],
        'context':{'threadId':'codex-fixture'}}, peer=peer())
    mail.WorkshopInjection(owner, None).tick()
    assert not owner.shared_agent_mail('pending', {'context':{'threadId':'codex-fixture'}}, peer=peer())['pending']
    page = owner.shared_agent_mail('read', {'since':0, 'context':{'gemini/sessionID':'other-fixture'}}, peer=peer())
    assert next(row for row in page['messages'] if row['id']==note['message_id'])['state'] == 'answered'


@pytest.mark.parametrize('kwargs', [{'reminder_minutes':0}, {'reminder_minutes':True},
    {'escalation_minutes':float('nan')}, {'reminder_minutes':3, 'escalation_minutes':2}])
def test_invalid_timing_defaults_refuse(room, kwargs):
    with pytest.raises(ValueError):
        mail.WorkshopInjection(room[0], NativeFixture(), **kwargs)


@pytest.mark.parametrize('runtime,context', [('codex', {'threadId':'codex-fixture'}),
    ('claude', {'claude/sessionID':'71700000-0000-4000-8000-000000000001'}),
    ('opencode', {'ai.opencode/sessionID':'opencode-fixture'})])
def test_real_session_link_worker_reaches_fixture_native_socket(room, tmp_path, runtime, context):
    from nodelang.session_link_transport import SessionLinkTransport
    owner, history = room
    root = Path(__file__).resolve().parents[2]
    node = shutil.which('node')
    session = next(iter(context.values()))
    environment = {**os.environ, 'HOME':str(tmp_path), 'USERPROFILE':str(tmp_path),
        'SESSION_LINK_STATE_DIR':str(tmp_path), 'CODEX_APP_TOOLS_PIPE_PATH':'', 'CODEX_THREAD_ID':''}
    process = subprocess.Popen([node, str(root / '02.TESTS/tests/session_link_wsinject.mjs'),
        str(tmp_path), runtime, session], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=environment)
    delivery = None
    try:
        assert process.stdout.readline().strip() == b'READY'
        declare(owner, context)
        transport = SessionLinkTransport(node_executable=Path(node), state_dir=tmp_path, env=environment)
        delivery = mail.WorkshopInjection(owner, transport)
        owner.workshop_injection = delivery
        delivery.start()
        started = time.monotonic()
        note = owner.shared_agent_mail('send', {'to':runtime, 'text':'Visible native exchange',
            'context':{'gemini/sessionID':'sender-fixture'}}, peer=peer())
        turns = tmp_path / 'TURNS.jsonl'
        while not turns.exists() and time.monotonic() - started < 12:
            time.sleep(.05)
        assert turns.exists(), delivery.last_error
        records = [json.loads(line) for line in turns.read_text(encoding='utf-8').splitlines()]
        assert len(records) == 1
        assert 'Visible native exchange' in records[0]['text'] and note['message_id'] in records[0]['text']
        assert time.monotonic() - started < 12
        assert {path.name for path in tmp_path.glob('*.sqlite3')} == {'ROOM.sqlite3'}, 'only the existing Workshop database may exist'
        while delivery_events_status(owner, history, note['message_id']) is None and time.monotonic() - started < 12:
            time.sleep(.05)
        assert delivery_events_status(owner, history, note['message_id']) == ('queued' if runtime=='opencode' else 'injected')
        print('native_socket', runtime, 'received_in_seconds', round(time.monotonic()-started, 3))
    finally:
        if delivery:
            delivery.close()
            transport.close()
        process.stdin.close()
        process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            stream.close()


def delivery_events_status(owner, history, message_id):
    with owner.mutation_lock:
        events = mail.delivery_events(history, {'id':message_id})
    return next((event['initial-outcome']['status'] for event in events.values() if 'initial-outcome' in event), None)


def test_mcp_wire_emits_notifications_message_and_preserves_unrelated_result(room):
    from mcp.shared.memory import create_connected_server_and_client_session
    from nodelang.native_agent_mcp import build_server
    owner, _history = room
    context = {'gemini/sessionID':'wire-fixture'}
    recipient = declare(owner, context)
    note = send(owner, to=recipient['sender_label'])
    server = build_server(mailbox_call=lambda method, body, supplied:
        owner.shared_agent_mail(method, {**body, 'context':supplied}, peer=peer()))
    def unrelated() -> dict[str, object]:
        return {'unrelated':True}
    server.add_tool(unrelated, name='unrelated')
    received = []
    async def logged(params):
        received.append(params)
    async def run():
        async with create_connected_server_and_client_session(server, logging_callback=logged) as client:
            result = await client.call_tool('unrelated', {}, meta=context)
            assert result.structuredContent == {'unrelated':True}
            assert any('pending' in item.text and note['message_id'] in item.text for item in result.content)
    asyncio.run(run())
    assert received and received[0].logger == 'workshop' and received[0].data['pending'][0]['id'] == note['message_id']


def test_coordinator_escalation_is_itself_injected_without_recursive_followup(room):
    owner, _history = room
    declare(owner, {'threadId':'codex-fixture'})
    declare(owner, {'claude/sessionID':'71700000-0000-4000-8000-000000000001'})
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native, reminder_minutes=1, escalation_minutes=2)
    send(owner)
    started = time.time()
    for offset in (0, 61, 121, 122, 400, 401):
        delivery.tick(now=started + offset)
    coordinator = [turn for turn in native.turns if turn[0]['id'].startswith('717')]
    assert len(coordinator) == 1 and 'No reply from' in coordinator[0][1]


def test_coordinator_title_resolves_717_when_native_uuid_does_not_start_with_717(room):
    owner, _history = room
    native_id = 'b1b1b1b1-0000-4000-8000-000000000001'
    context = {'claude/sessionID':native_id}
    declare(owner, context)
    native = NativeFixture()
    native.discover = lambda **kw: {'status':'ok','recipients':[{'app':'claude','id':native_id,'title':'717 coordinator (live)'}]}
    delivery = mail.WorkshopInjection(owner, native)
    owner.workshop_injection = delivery
    note = send(owner, to='717', text='Coordinator must see this')
    delivery.tick()
    assert len(native.turns)==1 and native.turns[0][0]['id']==native_id
    assert note['message_id'] in [row['id'] for row in owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']]
    owner.shared_agent_mail('read', {'since':note['sequence'],'context':context}, peer=peer())
    delivery.tick()
    assert not owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']


def test_late_broadcast_recipient_cannot_ack_or_receive_old_message(room):
    owner, _history = room
    declare(owner, {'threadId':'codex-fixture'})
    note = send(owner, to='*')
    declare(owner, {'gemini/sessionID':'late-fixture'})
    page = owner.shared_agent_mail('pending', {'context':{'gemini/sessionID':'late-fixture'}}, peer=peer())
    assert note['message_id'] not in [row['id'] for row in page['pending']]


@pytest.mark.parametrize('vendor,label', [('cursor','Cursor'), ('copilot','VS Code Copilot'), ('grok','Grok Bot')])
def test_mcp_only_vendor_uses_its_connector_identity(room, monkeypatch, vendor, label):
    from nodelang.native_agent_mcp import _default_context
    monkeypatch.setenv('ARCHHUB_COORDINATION_VENDOR', vendor)
    monkeypatch.setenv('ARCHHUB_EXTERNAL_SESSION_ID', 'vendor-fixture')
    context = _default_context()
    recipient = declare(room[0], context)
    assert recipient['sender_label'].startswith(label + ' / ')
    note = send(room[0], to=vendor)
    page = room[0].shared_agent_mail('pending', {'context':context}, peer=peer())
    assert note['message_id'] in [row['id'] for row in page['pending']]


def test_public_room_projection_contains_unattached_mailbox_notes_and_real_states(room):
    from nodelang.workshop_api import WorkshopAPI
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    note = send(owner)
    api = SimpleNamespace(root=mail.ROOM, history=lambda:history)
    page = WorkshopAPI.listWorkshopMessages(api)
    assert next(row for row in page['messages'] if row['id']==note['message_id'])['state'] == 'pending'
    owner.workshop_injection = mail.WorkshopInjection(owner, None)
    owner.shared_agent_mail('read', {'since':note['sequence'],'context':{'threadId':'codex-fixture'}}, peer=peer())
    owner.workshop_injection.tick()
    page = WorkshopAPI.listWorkshopMessages(api)
    assert next(row for row in page['messages'] if row['id']==note['message_id'])['state'] == 'delivered'
    pending = send(owner, to='gemini', text='Pending message in the shared room')
    answered = send(owner, text='Answered message in the shared room')
    owner.shared_agent_mail('send', {'to':'claude', 'text':'Visible reply from Codex',
        'reply_to':answered['message_id'], 'context':{'threadId':'codex-fixture'}}, peer=peer())
    owner.workshop_injection.tick()
    page = WorkshopAPI.listWorkshopMessages(api)
    assert next(row for row in page['messages'] if row['id']==pending['message_id'])['state'] == 'pending'
    assert next(row for row in page['messages'] if row['id']==answered['message_id'])['state'] == 'answered'
    if os.environ.get('WSINJECT_UI_DATA'):
        Path(os.environ['WSINJECT_UI_DATA']).write_text(json.dumps(page), encoding='utf-8')


def test_reminder_to_a_read_but_unanswered_message_returns_on_next_tool(room):
    owner, _history = room
    context = {'gemini/sessionID':'recipient-fixture'}
    declare(owner, context)
    note = send(owner, to='gemini')
    delivery = mail.WorkshopInjection(owner, None, reminder_minutes=1, escalation_minutes=2)
    owner.workshop_injection = delivery
    started = time.time()
    delivery.tick(now=started)
    owner.shared_agent_mail('read', {'since':note['sequence'],'context':context}, peer=peer())
    delivery.tick(now=started)
    assert not owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']
    delivery.tick(now=started + 61)
    assert note['message_id'] in [row['id'] for row in owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']]
    reminder = owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending'][0]
    owner.shared_agent_mail('read', {'since':reminder['delivery_sequence'],'context':context}, peer=peer())
    delivery.tick(now=started+61)
    assert not owner.shared_agent_mail('pending', {'context':context}, peer=peer())['pending']


def test_late_declared_target_gets_native_injection_from_unresolved_address(room):
    owner, _history = room
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native)
    send(owner)
    delivery.tick()
    assert native.turns == []
    declare(owner, {'threadId':'late-codex'})
    delivery.tick()
    assert len(native.turns) == 1 and native.turns[0][0]['id'] == 'late-codex'


def test_unrelated_history_is_not_materialized_into_every_tool_result(room, monkeypatch):
    owner, history = room
    context = {'threadId':'codex-fixture'}
    declare(owner, context)
    with history._transaction(write=True):
        for index in range(2000):
            history.append(mail.ROOM, author='Fixture sender', category=mail.CATEGORY,
                content='To unrelated-agent:\nUnrelated history', idempotency_key='history:'+str(index))
    note = send(owner)
    parsed = []
    original = ConversationHistoryStore._message
    def counted(self, row):
        parsed.append(row['id'])
        return original(self, row)
    monkeypatch.setattr(ConversationHistoryStore, '_message', counted)
    page = owner.shared_agent_mail('pending', {'context':context}, peer=peer())
    assert [row['id'] for row in page['pending']] == [note['message_id']]
    assert len(parsed) <= 20, 'unrelated history must be filtered before payload materialization'


def test_new_message_reaches_native_target_before_historical_backfill(room):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    with history._transaction(write=True):
        for index in range(300):
            history.append(mail.ROOM, author='Fixture sender', category=mail.CATEGORY,
                content='To someone-else:\nOlder note', idempotency_key='older:'+str(index))
    note = send(owner)
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native)
    delivery.tick()
    assert len(native.turns)==1 and note['message_id'] in native.turns[0][1]


def test_explicit_native_controller_is_not_replayed_and_model_survives_reminder(room):
    owner, _history = room
    declare(owner, {'ai.opencode/sessionID':'selected-target'})
    native = NativeFixture()
    model = {'providerID':'openrouter','modelID':'qwen/qwen3.8-27b:free'}
    delivery = mail.WorkshopInjection(owner, native, reminder_minutes=1, escalation_minutes=2)
    owner.shared_agent_mail('send', {'to':'selected-target','text':'Explicitly selected free model',
        'native_control':{'app':'opencode','id':'selected-target','model':model},
        'context':{'claude/sessionID':'source'}}, peer=peer())
    started = time.time()
    delivery.tick(now=started)
    assert native.turns==[], 'Session Link ask already owns the original model-selected native call'
    delivery.tick(now=started + 61)
    assert len(native.turns)==1 and native.turns[0][2]['model']==model


def test_unicode_native_excerpt_respects_session_link_utf16_envelope(room):
    owner, _history = room
    declare(owner, {'threadId':'codex-fixture'})
    native = NativeFixture()
    send(owner, text='\U0001f431' * 16000)
    mail.WorkshopInjection(owner,native).tick()
    text = native.turns[0][1]
    assert len(text.encode('utf-16-le')) // 2 <= 32000 and '[Excerpt;' in text


def test_escalation_append_failure_does_not_mark_it_escalated(room, monkeypatch):
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native, reminder_minutes=1, escalation_minutes=2)
    note = send(owner)
    started = time.time()
    delivery.tick(now=started)
    delivery.tick(now=started + 61)
    append = ConversationHistoryStore.append
    def refused(self, *args, **kw):
        if kw.get('author') == 'Workshop coordination':
            raise OSError('fixture append interrupted')
        return append(self, *args, **kw)
    monkeypatch.setattr(ConversationHistoryStore, 'append', refused)
    with pytest.raises(OSError, match='fixture append interrupted'):
        delivery.tick(now=started + 121)
    assert all('escalated' not in event for event in mail.delivery_events(history, {'id':note['message_id']}).values())
    monkeypatch.setattr(ConversationHistoryStore, 'append', append)
    delivery.tick(now=started + 122)
    assert history._db.execute("SELECT count(*) FROM messages WHERE author='Workshop coordination' AND reply_to=?",
        (note['message_id'],)).fetchone()[0] == 1


def test_running_application_http_send_reaches_codex_bridge_without_read(owner, tmp_path):
    from nodelang import desktop
    from nodelang.session_link_transport import SessionLinkTransport
    server, _root = owner
    node = shutil.which('node')
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ,'HOME':str(tmp_path),'USERPROFILE':str(tmp_path),
        'SESSION_LINK_STATE_DIR':str(tmp_path),'CODEX_APP_TOOLS_PIPE_PATH':'','CODEX_THREAD_ID':''}
    process = subprocess.Popen([node,str(root/'02.TESTS/tests/session_link_wsinject.mjs'),
        str(tmp_path),'codex','http-codex'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment)
    transport = SessionLinkTransport(node_executable=Path(node), state_dir=tmp_path, env=environment)
    try:
        assert process.stdout.readline().strip() == b'READY'
        server.workshop_injection.close()
        server.workshop_injection = mail.WorkshopInjection(server, transport)
        server.workshop_injection.start()
        surface = desktop.bind_coordination_surface(server,tmp_path)
        _post(surface,{'method':'POST','path':'/api/universal/agent-mail/declare','body':{
            'task':'HTTP injection court','paths':[str(tmp_path)],'request_id':'WSINJECT','status':'working',
            'context':{'threadId':'http-codex'}}})
        started = time.monotonic()
        note = _post(surface,{'method':'POST','path':'/api/universal/agent-mail/send','body':{
            'to':'codex','text':'Claude reaches Codex through the application','context':{'claude/sessionID':'http-claude'}}})
        transcript = tmp_path/'TURNS.jsonl'
        while not transcript.exists() and time.monotonic()-started < 12:
            time.sleep(.05)
        assert transcript.exists()
        turn = json.loads(transcript.read_text(encoding='utf-8').splitlines()[0])
        assert turn['threadId']=='http-codex' and note['message_id'] in turn['text']
        print('application_http_native_injection_seconds',round(time.monotonic()-started,3))
    finally:
        server.workshop_injection.close()
        transport.close()
        process.stdin.close()
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_old_room_notes_are_readable_but_never_injected(room):
    """Build 31 replayed hours of room backlog, with reminders, into every live session."""
    from datetime import datetime, timedelta, timezone
    owner, history = room
    declare(owner, {'threadId':'codex-fixture'})
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    declared = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    with history._transaction(write=True):
        # The live agents had declared hours before the backlog notes were written.
        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.updated_at',?)", (declared,))
        history.append(mail.ROOM, author='Fixture sender', category=mail.CATEGORY,
            content='To codex:\nTwo hours old', idempotency_key='stale-note', created_at=old)
    native = NativeFixture()
    delivery = mail.WorkshopInjection(owner, native)
    delivery.tick()
    assert native.turns == []
    note = send(owner)
    delivery.tick()
    assert len(native.turns) == 1 and note['message_id'] in native.turns[0][1]



def test_a_broadcast_is_never_injected_back_into_its_sender():
    """717's 'To *' status came back into 717's own session with Follow-up reminders."""
    sender = {"agent":"Claude Code / ArchHub / session-a", "session":"agent:session:a", "current":True}
    other = {"agent":"Codex / lane / session-b", "session":"agent:session:b", "current":True}
    note = {"category":mail.CATEGORY, "author":"Claude Code / ArchHub / session-a / ahmed [agent:session:a]", "content":"To *:\nBuild installed"}
    sessions = [row["session"] for row in mail._recipient_rows(note, [sender, other])]
    assert "agent:session:a" not in sessions and "agent:session:b" in sessions



def test_a_broadcast_is_delivered_once_never_reminded():
    """Each 'To *' status produced a reminder per agent and an escalation per agent to 717."""
    assert mail._is_broadcast({"content":"To *:\nBuild installed"})
    assert mail._is_broadcast({"content":"To 717, *:\nBoth"})
    assert not mail._is_broadcast({"content":"To codex:\nPlease reply"})
