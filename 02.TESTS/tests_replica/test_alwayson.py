"""ALWAYSON: real Qt callbacks, SQLite connections and provider HTTP fixtures."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from nodelang import model_router, workshop_mailbox as mail
from nodelang.model_router import default_composer_route
from nodelang.application_server import ApplicationServer
from nodelang.clean_coordination_host import CleanCoordinationHost
from nodelang.clean_coordination_service import build_bound_service
from nodelang.conversation_history import ConversationHistoryStore
from tests_replica.test_newapp_mailbox import peer


@pytest.fixture
def room(tmp_path, monkeypatch):
    from nodelang import cloud_session
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda: None)
    with ConversationHistoryStore(tmp_path / 'ROOM.sqlite3', instance_id='alwayson') as history:
        history.ensure_conversation(mail.ROOM)
        owner = SimpleNamespace(mutation_lock=threading.RLock(),
            universal_store=SimpleNamespace(database_path=history._database_uri),
            conversation_content=SimpleNamespace(_history=history, _require_live_owner=lambda: None))
        owner.shared_agent_mail = lambda method, body, **kw: ApplicationServer.shared_agent_mail(owner, method, body, **kw)
        yield owner, history


@pytest.mark.parametrize('operation', ['injection', 'read', 'send', 'reply', 'pending', 'declare'])
def test_injection_reader_and_two_sends_commit_within_busy_timeout(room, monkeypatch, operation):
    owner, history = room
    entered, release = threading.Event(), threading.Event()
    original = mail.read_declarations

    def delayed_probe(connection, **kwargs):
        if threading.current_thread().name == 'ALWAYSON-INJECTION' and operation != 'reply':
            entered.set()
            assert release.wait(5)
        return original(connection, **kwargs)

    monkeypatch.setattr(mail, 'read_declarations', delayed_probe)
    if operation == 'declare':
        for index in range(2):
            owner.shared_agent_mail('declare', {'task':'expired fixture', 'paths':[str(Path(history._database_uri))],
                'status':'working', 'request_id':'ALWAYSON',
                'context':{'threadId':'expired-' + str(index)}}, peer=peer())
        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.updated_at','2000-01-01')")
        session_alive = mail._session_alive
        def delayed_alive(row):
            if threading.current_thread().name == 'ALWAYSON-INJECTION':
                entered.set()
                assert release.wait(5)
                return False
            return session_alive(row)
        monkeypatch.setattr(mail, '_session_alive', delayed_alive)
    if operation in ('reply', 'pending'):
        declared = owner.shared_agent_mail('declare', {'task':'legacy recipient',
            'paths':[str(Path(history._database_uri))], 'status':'working',
            'request_id':'ALWAYSON', 'context':{'threadId':'legacy-recipient'}}, peer=peer())
        parent = history.append(mail.ROOM, author='legacy sender', category=mail.CATEGORY,
            content='To ' + declared['sender_label'] + ':\nlegacy ask', idempotency_key='legacy-parent')
    if operation == 'pending':
        history.append(mail.ROOM, author='legacy sender', category=mail.CATEGORY,
            content='To ' + declared['sender_label'] + ':\nsecond legacy ask', idempotency_key='legacy-second')
    if operation == 'reply':
        can_ack = mail._can_ack
        def delayed_ack(*args):
            entered.set()
            assert release.wait(5)
            return can_ack(*args)
        monkeypatch.setattr(mail, '_can_ack', delayed_ack)
        history.append(mail.ROOM, author=declared['sender'], category=mail.CATEGORY,
            content='To legacy sender:\nanswer', reply_to=parent['id'], idempotency_key='legacy-reply')
    worker = mail.WorkshopInjection(owner, None)
    errors = []

    def tick():
        try:
            if operation in ('injection', 'reply'):
                worker.tick()
            elif operation == 'read':
                owner.shared_agent_mail('read', {'since':0}, peer=peer())
            elif operation == 'pending':
                owner.shared_agent_mail('pending', {'context':{'threadId':'legacy-recipient'}}, peer=peer())
            elif operation == 'declare':
                owner.shared_agent_mail('declare', {'task':'new declaration',
                    'paths':[str(Path(history._database_uri))], 'status':'working',
                    'request_id':'ALWAYSON', 'context':{'threadId':'new-declaration'}}, peer=peer())
            else:
                owner.shared_agent_mail('send', {'to':'*', 'text':'delayed sender'}, peer=peer())
        except Exception as exc:
            errors.append(exc)

    tick_thread = threading.Thread(target=tick, name='ALWAYSON-INJECTION')
    tick_thread.start()
    try:
        assert entered.wait(3)
        def send(index):
            started = time.monotonic()
            result = owner.shared_agent_mail('send', {'to':'*', 'text':'concurrent ' + str(index),
                'context':{'threadId':'ALWAYSON-' + str(index)}}, peer=peer())
            return result, time.monotonic() - started
        with ThreadPoolExecutor(max_workers=2) as pool:
            sent = list(pool.map(send, range(2)))
        assert len({result['message_id'] for result, _ in sent}) == 2
        assert max(elapsed for _, elapsed in sent) < 1.0
        print('CONCURRENT_SEND_SECONDS', [round(elapsed, 6) for _, elapsed in sent])
    finally:
        release.set()
        tick_thread.join(5)
    assert not tick_thread.is_alive()
    assert not errors, errors
    assert history._db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'


def test_native_injection_wait_holds_no_transaction_and_two_sends_succeed(room, tmp_path):
    owner, _history = room
    declared = owner.shared_agent_mail('declare', {'task':'ALWAYSON recipient', 'paths':[str(tmp_path)],
        'status':'working', 'request_id':'ALWAYSON', 'context':{'threadId':'recipient'}}, peer=peer())
    owner.shared_agent_mail('send', {'to':declared['sender_label'], 'text':'fixture ask'}, peer=peer())
    entered, release = threading.Event(), threading.Event()
    class Transport:
        def inject(self, *_args, **_kwargs):
            entered.set()
            assert release.wait(5)
            return {'status':'injected'}
    worker = mail.WorkshopInjection(owner, Transport())
    thread = threading.Thread(target=worker.tick)
    thread.start()
    try:
        assert entered.wait(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(owner.shared_agent_mail, 'send', {'to':'*', 'text':str(i)}, peer=peer())
                for i in range(2)]
            assert all(future.result(timeout=2)['message_id'] for future in futures)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


def test_default_close_hides_window_and_coordination_still_answers(room, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtGui import QCloseEvent, QIcon, QPixmap
    from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon
    from nodelang import universal_application as app
    from nodelang.map_import import resolve_map_path
    qt = QApplication.instance() or QApplication([])
    store, registry = app.build_universal_application(resolve_map_path())
    owner, _history = room
    owner.universal_store, owner.universal_registry = store, registry
    source = ast.parse((Path(__file__).resolve().parents[2] / '01.APP/nodelang/launcher.py').read_text('utf-8'))
    nodes = [node for node in ast.walk(source) if
        isinstance(node, ast.FunctionDef) and node.name == '_hide_in_tray_if_enabled'
        or isinstance(node, ast.ClassDef) and node.name == '_ArchHubWindow']
    quits = []
    namespace = {'QMainWindow':QMainWindow, 'server':owner,
        '_quit_from_window':lambda widget:quits.append(widget)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'ALWAYSON-close', 'exec'), namespace)
    window = namespace['_ArchHubWindow']()
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    tray = QSystemTrayIcon(QIcon(pixmap))
    window._tray = tray
    surface = build_bound_service(CleanCoordinationHost(owner))
    service_thread = threading.Thread(target=surface.serve_forever)
    service_thread.start()
    try:
        window.show()
        tray.show()
        qt.processEvents()
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        assert not window.isVisible() and tray.isVisible() and not quits
        request = Request('http://127.0.0.1:%d/coordination' % surface.server_address[1],
            data=json.dumps({'method':'GET', 'path':'/api/universal/agent-mail/read',
                'body':{'since':0}}).encode(), headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=3) as response:
            assert json.load(response)['messages'] == []
        window.quitting = True
        quit_event = QCloseEvent()
        window.closeEvent(quit_event)
        assert quit_event.isAccepted() and quits == [window]
    finally:
        surface.shutdown()
        service_thread.join(3)
        surface.server_close()
        tray.hide()
        window.deleteLater()
        qt.processEvents()


def test_free_default_selects_available_model_and_fixture_provider_answers(monkeypatch):
    from tests_replica.test_openrouter_free_tool_routing import _Wire, _chat_payload, _tool_catalogue, _tool_schema
    model = 'dots-studio/dots-3-note-preview:free'
    model_router._reset_openrouter_free_tool_catalogue_cache()
    route, _source = default_composer_route(settings_loader=lambda _: '',
        readiness=lambda value: model_router.composer_readiness(value,
            environ={'OPENROUTER_API_KEY':'fixture'}, secrets_loader=lambda _: '', cloud_session={}))
    assert route == 'openrouter/free'
    wire = _Wire([_chat_payload('ALWAYSON answered', model=model)], catalogue_rows=_tool_catalogue(model))
    answer = model_router.route_chat(route, [{'role':'user', 'content':'fixture ping'}],
        opener=wire, environ={'OPENROUTER_API_KEY':'fixture'}, secrets_loader=lambda _: '',
        cloud_session={}, free_only=True, tools=_tool_schema())
    assert answer['text'] == 'ALWAYSON answered'
    assert wire.chat_body(0)['model'] == model
    assert wire.chat_body(0)['provider']['max_price']['completion'] == 0
    model_router._reset_openrouter_free_tool_catalogue_cache()
