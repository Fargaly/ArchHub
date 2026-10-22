"""Behavioral checks for the shared-profile mailbox, without a desktop runtime."""
import os
import sqlite3
import threading
import socket
from urllib.error import HTTPError
from types import SimpleNamespace

import psutil
import pytest

from nodelang.conversation_history import ConversationHistoryStore
from nodelang.application_machine_transport import MachinePipePeer
from nodelang.workshop_mailbox import call as external_call, _identity, read_declarations


def application_call(method, body, context, *, database, peer=None, account=None):
    from nodelang.persistence import application_content_path
    path = application_content_path(database) or database
    with ConversationHistoryStore(path, instance_id="mailbox-test", create=False) as history:
        return external_call(method, body, context, database=database, peer=peer, account=account, history=history)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "PROFILE.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    with ConversationHistoryStore(path, instance_id="mailbox-test", connection=connection) as history:
        history.ensure_conversation("app:workshop")
    connection.close()
    return path


def peer(pid=None):
    process = psutil.Process(pid or os.getpid())
    return MachinePipePeer(pid=process.pid, created_at=process.create_time(), cwd=os.getcwd())


def test_session_identity_survives_connector_restart():
    first, _, _ = _identity({"threadId": "same-session"}, peer())
    second, _, _ = _identity({"threadId": "same-session"}, peer(os.getppid()))
    other, _, _ = _identity({"threadId": "another-session"}, peer())
    assert first["sender_key"] == second["sender_key"]
    assert first["sender_key"] != other["sender_key"]


def test_redeclare_replaces_the_session_row(database):
    body = {"task": "Integration", "paths": [os.getcwd()], "status": "working", "request_id": "NEWAPP"}
    first = application_call("declare", body, {"threadId": "same-session"}, database=database, peer=peer())
    second = application_call("declare", body, {"threadId": "same-session"}, database=database, peer=peer(os.getppid()))
    assert first["declaration"]["root"] == second["declaration"]["root"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from workshop_declarations").fetchone()[0] == 1
    assert second["coordination_messages"] == []


def test_explicit_retry_key_is_exactly_once(database):
    body = {"to": "*", "text": "One deliberate message", "idempotency_key": "request-1"}
    first = application_call("send", body, {"threadId": "retry-session"}, database=database, peer=peer())
    second = application_call("send", body, {"threadId": "retry-session"}, database=database, peer=peer())
    assert first["message_id"] == second["message_id"]
    with pytest.raises(ValueError):
        application_call("send", {**body, "text": "Different effect"}, {"threadId": "retry-session"}, database=database, peer=peer())


def test_unqualified_callers_remain_distinct():
    assert _identity({}, peer())[0]["sender_key"] != _identity({}, peer(os.getppid()))[0]["sender_key"]


def test_derived_fields_are_not_parameter_sockets(database):
    application_call("declare", {"task": "Test", "paths": [os.getcwd()], "status": "working", "request_id": "NEWAPP"},
         {"threadId": "socket-session"}, database=database, peer=peer())
    with sqlite3.connect(database) as connection:
        row = read_declarations(connection)[0]
    assert "current" not in row["sockets"]
    assert "process_alive" not in row["sockets"]


def test_rate_budget_survives_connector_restart_and_allows_a_retry(database):
    context = {"threadId": "bounded-session"}
    for index in range(30):
        application_call("send", {"to": "*", "text": str(index), "idempotency_key": str(index)},
             context, database=database, peer=peer())
    with pytest.raises(ValueError, match="30 messages"):
        application_call("send", {"to": "*", "text": "31", "idempotency_key": "31"},
             context, database=database, peer=peer(os.getppid()))
    retry = application_call("send", {"to": "*", "text": "29", "idempotency_key": "29"},
                 context, database=database, peer=peer(os.getppid()))
    assert retry["sequence"] == 30


def test_pipe_metadata_cannot_select_a_session_identity(database):
    from nodelang.installed_workshop_coordination import dispatch_mailbox
    owner = SimpleNamespace(universal_store=SimpleNamespace(database_path=database))
    owner.shared_agent_mail = lambda method, body, **kw: application_call(method, body, {}, database=database, **kw)
    result = dispatch_mailbox(owner, {"method": "POST", "path": "/api/universal/agent-mail/send",
        "session": {}, "body": {"to": "*", "text": "Observed peer", "context": {"threadId": "spoofed"}}}, peer())
    assert result["sender_key"] == _identity({}, peer())[0]["sender_key"]
    assert result["sender_key"] != _identity({"threadId": "spoofed"}, peer())[0]["sender_key"]


def test_native_parent_keeps_a_short_lived_declaration_current(monkeypatch):
    from nodelang import workshop_mailbox as mailbox
    row = {"pid": 1, "created_at": 1, "native_session_id": "real-session", "runtime": "codex",
           "native_process": {"pid": 2, "created_at": 2, "runtime": "codex"},
           "process_lineage": [{"pid": 1, "created_at": 1}, {"pid": 2, "created_at": 2},
                               {"pid": 3, "created_at": 3}]}
    monkeypatch.setattr(mailbox, "_alive", lambda process: process["pid"] == 2)
    assert mailbox._session_alive(row)
    # A surviving desktop ancestor cannot keep the ended CLI session alive.
    monkeypatch.setattr(mailbox, "_alive", lambda process: process["pid"] == 3)
    assert not mailbox._session_alive(row)


def test_trusted_application_turns_keep_separate_session_rows(database):
    from nodelang.application_server import ApplicationServer
    with ConversationHistoryStore(database, instance_id="mailbox-test", create=False) as history:
        owner = SimpleNamespace(universal_store=SimpleNamespace(database_path=database),
            mutation_lock=threading.RLock(), conversation_content=SimpleNamespace(
                _history=history, _require_live_owner=lambda: None))
        for session in ("turn-A", "turn-B"):
            ApplicationServer.shared_agent_mail(owner, "declare", {"task": "Test", "paths": [os.getcwd()],
                "status": "working", "request_id": "NEWAPP", "context": {"archhub/sessionID": session}})
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from workshop_declarations").fetchone()[0] == 2


def test_graph_database_routes_to_its_conversation_store(tmp_path):
    """The installed app passes the graph file; messages live in the sibling conversation store."""
    graph = tmp_path / "archhub-test.universal.sqlite3"
    sqlite3.connect(graph).execute("CREATE TABLE cells(id INTEGER PRIMARY KEY)").connection.close()
    content = tmp_path / "archhub-test.universal.sqlite3.conversations.sqlite3"
    connection = sqlite3.connect(content, isolation_level=None)
    with ConversationHistoryStore(content, instance_id="mailbox-test", connection=connection) as history:
        history.ensure_conversation("app:workshop")
    connection.close()
    sent = application_call("send", {"to": "founder", "text": "hello"}, {"threadId": "graph-session"}, database=graph, peer=peer())
    assert external_call("read", {"since":0}, {}, database=graph, peer=peer())["messages"][0]["id"] == sent["message_id"]
    assert sent["message_id"]
    rows = sqlite3.connect(content).execute("SELECT content FROM messages").fetchall()
    assert rows == [("To founder:\nhello",)]


def test_account_attribution_scopes_mailbox_retries(database):
    body = {"to": "*", "text": "A deliberate message", "idempotency_key": "one-retry"}
    first = application_call("send", body, {}, database=database, peer=peer(), account="first@example.test")
    second = application_call("send", body, {}, database=database, peer=peer(), account="second@example.test")
    assert first['message_id'] != second['message_id']
    assert first['sender_key'] != second['sender_key']
    assert first['sender_label'].endswith(' / first@example.test')
    assert second['sender_label'].endswith(' / second@example.test')
    page = application_call('read', {'since': 0}, {}, database=database, peer=peer())
    assert {first['sender_label'], second['sender_label']} <= {row['label'] for row in page['peers']}


def test_closed_app_mailbox_uses_existing_profile_after_connection_refusal(database, monkeypatch):
    from nodelang import workshop_mailbox
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
        monkeypatch.setenv('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:%d/coordination' % port)
        monkeypatch.setattr(workshop_mailbox, 'profile_database', lambda: database)
        with pytest.raises(ValueError, match='application is unavailable'):
            external_call('send', {'to': '*', 'text': 'no listener fallback', 'idempotency_key': 'fallback'}, {})
        assert external_call('read', {'since':0}, {})['messages'] == []


def test_http_refusal_is_never_replayed_to_the_profile(monkeypatch):
    from nodelang import workshop_mailbox
    class RefusingOwner:
        def open(self, *_args, **_kwargs):
            raise HTTPError('http://127.0.0.1/coordination', 403, 'refused', {}, None)
    monkeypatch.setattr(workshop_mailbox, 'build_opener', lambda *_args: RefusingOwner())
    monkeypatch.setattr(workshop_mailbox, 'profile_database', lambda: pytest.fail('refused send was replayed'))
    with pytest.raises(HTTPError):
        external_call('send', {'to': '*', 'text': 'one attempt', 'idempotency_key': 'one-attempt'}, {})


def test_pending_to_verified_account_keeps_one_native_declaration(database):
    body = {'task': 'One current task', 'paths': [os.getcwd()], 'status': 'working', 'request_id': 'NOKEY'}
    pending = application_call('declare', body, {'threadId': 'same-native'}, database=database, peer=peer())
    verified = application_call('declare', body, {'threadId': 'same-native'}, database=database,
        peer=peer(), account='owner@example.test')
    assert pending['declaration']['root'] == verified['declaration']['root']
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM workshop_declarations').fetchone()[0] == 1

def test_a_fixture_profile_never_reaches_the_live_desktop(tmp_path, monkeypatch):
    """ARCHHUB_TEST_STATE_DIR selects a fixture profile; its mailbox must not post to 8474."""
    import nodelang.workshop_mailbox as mailbox
    content = tmp_path / "PROFILE.sqlite3"
    connection = sqlite3.connect(content, isolation_level=None)
    with ConversationHistoryStore(content, instance_id="mailbox-test", connection=connection) as history:
        history.ensure_conversation("app:workshop")
    connection.close()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_COORDINATION_ENDPOINT", raising=False)
    monkeypatch.setattr(mailbox, "profile_database", lambda: content)
    def never(*_args, **_kwargs):
        raise AssertionError("the fixture profile reached the live desktop")
    monkeypatch.setattr(mailbox, "build_opener", never)
    with pytest.raises(ValueError, match='application is unavailable'):
        external_call("send", {"to": "founder", "text": "fixture only"}, {"threadId": "fixture-session"}, peer=peer())
    assert external_call('read', {'since':0}, {}, peer=peer())['messages'] == []
