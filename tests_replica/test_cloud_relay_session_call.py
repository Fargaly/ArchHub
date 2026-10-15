"""The installed app answers remote session MCP calls through the existing relay."""
from __future__ import annotations

import json
import secrets
from io import BytesIO
from pathlib import Path
from urllib.request import Request

import pytest

from nodelang.cloud_relay import ArchHubApplicationSessions, CloudRelay, RemoteSessionCaller, SESSION_CALL
from tests_replica.test_cloud_relay_host_read import _Cloud, cloud  # noqa: F401


def _relay(base, caller):
    return CloudRelay(base_url=base, token="t", respond=lambda _u: {}, execute=lambda _u: {},
                      hosts=lambda: [], session_caller=caller)


def test_the_relay_claims_session_calls_only_when_it_can_answer_them(cloud):  # noqa: F811
    _relay(cloud, None).poll_once()
    assert SESSION_CALL not in _Cloud.claims[-1]["kinds"]

    _relay(cloud, lambda *_a: {}).poll_once()
    assert SESSION_CALL in _Cloud.claims[-1]["kinds"]


def test_the_relay_answers_session_calls_through_the_session_caller_and_never_baboom(cloud):  # noqa: F811
    seen = []
    relay = CloudRelay(base_url=cloud, token="t",
                       respond=lambda u: (_ for _ in ()).throw(AssertionError(u)),
                       execute=lambda u: (_ for _ in ()).throw(AssertionError(u)),
                       hosts=lambda: [],
                       session_caller=lambda account, method, params, request_id:
                       seen.append((account, method, params, request_id))
                       or {"ok": True, "state": "idle", "tail": ["done"]})
    _Cloud.tasks[:] = [{"id": "s1", "kind": SESSION_CALL,
                        "directive": json.dumps({"account": "owner-a@example.com",
                                                 "method": "open_session",
                                                 "request_id": "cloud-request-1",
                                                 "params": {"id": "sess-a"}})}]

    answered = relay.poll_once()

    assert answered["ok"] is True
    assert seen == [("owner-a@example.com", "open_session", {"id": "sess-a"},
                     "cloud-request-1")]
    assert json.loads(_Cloud.results[-1]["result"])["tail"] == ["done"]


class _SessionTransport:
    def __init__(self):
        self.sent = []
        self.created = []

    def discover(self):
        recipients = [
            {"account": "owner-a@example.com", "app": "claude", "id": "sess-a",
             "title": "A", "state": "idle"},
            {"account": "owner-b@example.com", "app": "claude", "id": "sess-b",
             "title": "B", "state": "idle"},
            {"app": "claude", "id": "sess-unowned", "title": "Unowned", "state": "idle"},
        ]
        recipients.extend(self.created)
        return {"status": "ok", "recipients": recipients}

    def request(self, recipient, text, **kwargs):
        self.sent.append((recipient, text, kwargs))
        return {"status": "replied", "reply": {"text": "ok"}}

class _ApplicationSessions:
    def __init__(self):
        self.created = []
        self.sent = []

    def list(self, account):
        return [{"account": account, "app": "archhub", "id": row["id"],
                 "title": row["title"], "state": "idle",
                 "runtimeId": "application-conversation"} for row in self.created]

    def open(self, account, session_id, *, missing_ok=False):
        for row in self.list(account):
            if row["id"] == session_id:
                return {**row, "history": [{"text": "opened"}], "tail": ["opened"]}
        if missing_ok:
            return None
        raise PermissionError("session is not in this ArchHub account")

    def create(self, account, title, *, request_identity):
        row = {"account": account, "app": "archhub", "id": "sess-new",
               "title": title, "state": "idle", "runtimeId": "application-conversation",
               "history": [], "tail": [], "request_identity": request_identity}
        self.created.append(row)
        return row

    def send(self, account, session_id, text, *, request_identity):
        self.sent.append((account, session_id, text, request_identity))
        return {"session_id": session_id, "mode": "ask",
                "delivery": {"state": "replied", "reply_message_id": "reply-1"}}


def test_the_local_session_handler_refuses_sessions_owned_by_another_account():
    transport = _SessionTransport()
    caller = RemoteSessionCaller(account=lambda: "owner-a@example.com", transport=transport)

    listed = caller("owner-a@example.com", "list_sessions", {})
    opened = caller("owner-a@example.com", "open_session", {"id": "sess-a"})

    assert [row["id"] for row in listed["sessions"]] == ["sess-a"]
    assert opened["title"] == "A"
    with pytest.raises(PermissionError, match="not in this ArchHub account"):
        caller("owner-a@example.com", "open_session", {"id": "sess-unowned"})
    with pytest.raises(PermissionError, match="not in this ArchHub account"):
        caller("owner-a@example.com", "open_session", {"id": "sess-b"})
    with pytest.raises(PermissionError, match="another signed-in account"):
        caller("owner-b@example.com", "list_sessions", {})


def test_new_session_is_created_with_the_calling_account_and_then_listed():
    transport = _SessionTransport()
    application = _ApplicationSessions()
    caller = RemoteSessionCaller(account=lambda: "owner-a@example.com", transport=transport,
                                 application_sessions=application)

    created = caller("owner-a@example.com", "new_session",
                     {"title": "Remote plan", "mode": "ask"}, "task-create-1")
    listed = caller("owner-a@example.com", "list_sessions", {})

    assert created == {"app": "archhub", "id": "sess-new", "title": "Remote plan",
                       "state": "idle", "runtimeId": "application-conversation",
                       "tail": [], "history": []}
    assert [row["id"] for row in listed["sessions"]] == ["sess-new", "sess-a"]
    assert application.created[0]["account"] == "owner-a@example.com"
    assert application.created[0]["request_identity"] == "task-create-1"


def test_new_session_refuses_a_creation_without_a_proven_owner():
    class UnownedCreate(_ApplicationSessions):
        def create(self, account, title, *, request_identity):
            return {"app": "archhub", "id": "sess-new", "title": title, "state": "idle"}

    caller = RemoteSessionCaller(account=lambda: "owner-a@example.com", transport=_SessionTransport(),
                                 application_sessions=UnownedCreate())

    with pytest.raises(PermissionError, match="no proven ArchHub account owner"):
        caller("owner-a@example.com", "new_session",
               {"title": "Remote plan", "mode": "ask"}, "task-create-1")


def test_remote_archhub_session_uses_real_application_conversation_store(tmp_path, monkeypatch):
    from nodelang import agent_composer, commit_intent, model_router, universal_application as app
    from nodelang import workshop_session_start
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.workshop_conversation_catalog import create_workshop_conversation

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    calls = []
    discovery_calls = []
    created_deliveries = []
    fixture_model = "nvidia/nemotron-3.5-lightning:free"
    # Discover and prove the fake route through the same free/tool metadata contract.
    # Isolate the process cache so this court never depends on another court's discovery.
    monkeypatch.setattr(model_router, "_OPENROUTER_FREE_TOOL_CATALOGUE_FETCHED", False)
    monkeypatch.setattr(model_router, "_OPENROUTER_FREE_TOOL_CATALOGUE_CACHE_AT", 0.0)
    monkeypatch.setattr(model_router, "_OPENROUTER_FREE_TOOL_CATALOGUE_CACHE_MODELS", ())
    real_start = workshop_session_start.start_workshop_session

    def captured_start(*args, **kwargs):
        result = real_start(*args, **kwargs)
        created_deliveries.append(dict(result["delivery"]))
        return result

    monkeypatch.setattr(workshop_session_start, "start_workshop_session", captured_start)

    def provider(request: Request, timeout):
        if request.get_method() == "GET" and request.full_url.endswith("/models"):
            discovery_calls.append(request.full_url)
            return BytesIO(json.dumps({"data": [{
                "id": fixture_model, "name": "Fixture free tool model", "context_length": 32768,
                "pricing": {"prompt": "0", "completion": "0", "request": "0", "image": "0"},
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                "supported_parameters": ["tools", "tool_choice"],
            }]}).encode())
        assert request.get_method() == "POST", request.full_url
        payload = json.loads(request.data)
        assert payload["model"] == fixture_model
        prompt = payload["messages"][-1]["content"].rsplit("FOUNDER: ", 1)[1]
        calls.append(prompt)
        answer = json.dumps({"actions": [], "answer": "fake model reply: " + prompt})
        return BytesIO(json.dumps({"model": fixture_model, "choices": [{"message": {"content": answer}}]}).encode())

    def routed(*args, **kwargs):
        return model_router.route_chat(*args, **kwargs, opener=provider, environ={},
            secrets_loader=lambda _name: "synthetic-fixture-key", cloud_session=None)

    monkeypatch.setattr(agent_composer, "route_chat", routed)
    server = ApplicationServer(universal_state_path=tmp_path / "remote.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        server._read_agent_model = lambda: "openrouter/free"
        active_account = {"email": "owner-a@example.com"}
        application_sessions = ArchHubApplicationSessions(
            server, cloud_account=lambda: active_account["email"])
        caller = RemoteSessionCaller(account=lambda: active_account["email"],
            transport=_SessionTransport(), application_sessions=application_sessions)
        binding = server._resolve_browser_session(server.browser_session_token,
            csrf_token=server.browser_csrf_token, require_csrf=True)
        with commit_intent.declare(commit_intent.USER_ACTION, actor=binding.subject_root,
                reason="remote session legacy unowned court setup"):
            legacy = create_workshop_conversation(server,
                authentication_context=binding.context,
                expected_revision=server.universal_store.revision,
                title="Legacy unowned", participant_roots=(binding.subject_root,),
                idempotency_key="legacy-unowned")

        created = caller("owner-a@example.com", "new_session",
                         {"title": "Remote hello", "mode": "ask"}, "task-create-1")
        assert created_deliveries and created_deliveries[0]["state"] == "replied", created_deliveries
        assert discovery_calls, "the fake free tool model was proven by catalogue discovery"
        created_retry = caller("owner-a@example.com", "new_session",
                               {"title": "Remote hello", "mode": "ask"}, "task-create-1")
        listed = caller("owner-a@example.com", "list_sessions", {})
        opened = caller("owner-a@example.com", "open_session", {"id": created["id"]})
        sent = caller("owner-a@example.com", "send_to_session",
                      {"id": created["id"], "text": "Remote follow-up", "mode": "ask"},
                      "task-send-1")
        sent_retry = caller("owner-a@example.com", "send_to_session",
                            {"id": created["id"], "text": "Remote follow-up", "mode": "ask"},
                            "task-send-1")
        second_sent = caller("owner-a@example.com", "send_to_session",
                             {"id": created["id"], "text": "Remote follow-up", "mode": "ask"},
                             "task-send-2")
        reopened = caller("owner-a@example.com", "open_session", {"id": created["id"]})
        with pytest.raises(PermissionError, match="not in this ArchHub account"):
            caller("owner-a@example.com", "open_session", {"id": legacy["root"]})
        active_account["email"] = "owner-b@example.com"
        b_listed = caller("owner-b@example.com", "list_sessions", {})
        with pytest.raises(PermissionError, match="not in this ArchHub account"):
            caller("owner-b@example.com", "open_session", {"id": created["id"]})
        with pytest.raises(PermissionError, match="not in this ArchHub account"):
            caller("owner-b@example.com", "send_to_session",
                   {"id": created["id"], "text": "stolen", "mode": "ask"},
                   "task-send-b")
        with pytest.raises(PermissionError, match="not in this ArchHub account"):
            caller("owner-b@example.com", "open_session", {"id": legacy["root"]})

        assert created["app"] == "archhub" and created["runtimeId"] == "application-conversation"
        assert created_retry["id"] == created["id"]
        assert created["id"] in [row["id"] for row in listed["sessions"]]
        assert legacy["root"] not in [row["id"] for row in listed["sessions"]]
        assert "Remote hello" in "\n".join(opened["tail"])
        assert "fake model reply: Remote hello" in "\n".join(opened["tail"])
        assert sent["delivery"]["state"] == "replied" and sent["reply_persisted"] is True
        assert sent_retry["message_id"] == sent["message_id"]
        assert second_sent["delivery"]["state"] == "replied"
        assert "Remote follow-up" in "\n".join(reopened["tail"])
        assert "fake model reply: Remote follow-up" in "\n".join(reopened["tail"])
        assert created["id"] not in [row["id"] for row in b_listed["sessions"]]
        assert legacy["root"] not in [row["id"] for row in b_listed["sessions"]]
        assert calls == ["Remote hello", "Remote follow-up", "Remote follow-up"]
    finally:
        server.close()


def test_start_cloud_relay_wires_the_real_session_caller_and_lists_sessions(
    tmp_path, monkeypatch, cloud  # noqa: F811
):
    from nodelang import cloud_publish_consent
    from nodelang.cloud_relay import start_cloud_relay

    appdata = tmp_path / "appdata"
    state = tmp_path / "state"
    cloud_json = appdata / "ArchHub" / "brain" / "cloud.json"
    cloud_json.parent.mkdir(parents=True)
    cloud_json.write_text(json.dumps({
        "email": "owner-a@example.com",
        "token": "t",
        "cloud_base_url": cloud,
    }), encoding="utf-8")
    monkeypatch.setattr(cloud_publish_consent, "cloud_publish_allowed",
                        lambda _state, _account=None: True)
    monkeypatch.setattr("nodelang.cloud_relay.PINNED_BASES", (cloud,))
    monkeypatch.setattr(CloudRelay, "start", lambda self: self)

    relay = start_cloud_relay(appdata=appdata, state_dir=state,
                              respond=lambda _text: {}, execute=lambda _text: {},
                              session_transport=_SessionTransport())
    _Cloud.tasks[:] = [{"id": "s2", "kind": SESSION_CALL,
                        "directive": json.dumps({"account": "owner-a@example.com",
                                                 "method": "list_sessions",
                                                 "params": {}})}]

    answered = relay.poll_once()
    result = json.loads(_Cloud.results[-1]["result"])

    assert answered["ok"] is True
    assert [row["id"] for row in result["sessions"]] == ["sess-a"]


def test_application_relay_lifecycle_starts_after_consent_and_rebinds_on_account_switch(
    tmp_path, monkeypatch, cloud  # noqa: F811
):
    from nodelang import cloud_publish_consent
    from nodelang.application_server import ApplicationServer

    monkeypatch.setattr("nodelang.cloud_relay.PINNED_BASES", (cloud,))
    monkeypatch.setattr(CloudRelay, "start", lambda self: self)
    owner = object.__new__(ApplicationServer)
    owner._cloud_relay_enabled = True
    owner._cloud_relay_transport = _SessionTransport()
    owner._cloud_relay_appdata = tmp_path / "appdata"
    owner._cloud_relay_state_dir = tmp_path / "state"
    owner._cloud_relay_state_dir.mkdir()
    owner.cloud_relay = None
    cloud_json = owner._cloud_relay_appdata / "ArchHub" / "brain" / "cloud.json"
    cloud_json.parent.mkdir(parents=True)

    assert owner._restart_cloud_relay() is None
    assert owner.cloud_relay is None

    cloud_json.write_text(json.dumps({
        "email": "owner-a@example.com", "token": "t", "cloud_base_url": cloud,
    }), encoding="utf-8")
    cloud_publish_consent.record_cloud_publish_consent(
        owner._cloud_relay_state_dir, account="owner-a@example.com")
    first = owner._restart_cloud_relay()

    assert first is owner.cloud_relay
    assert [row["id"] for row in first.session_caller(
        "owner-a@example.com", "list_sessions", {})["sessions"]] == ["sess-a"]

    cloud_json.write_text(json.dumps({
        "email": "owner-b@example.com", "token": "t2", "cloud_base_url": cloud,
    }), encoding="utf-8")
    cloud_publish_consent.record_cloud_publish_consent(
        owner._cloud_relay_state_dir, account="owner-b@example.com")
    second = owner._restart_cloud_relay()

    assert second is owner.cloud_relay and second is not first
    assert first._stop.is_set()
    assert [row["id"] for row in second.session_caller(
        "owner-b@example.com", "list_sessions", {})["sessions"]] == ["sess-b"]
    with pytest.raises(PermissionError, match="another signed-in account"):
        second.session_caller("owner-a@example.com", "list_sessions", {})


def test_cloud_signin_success_event_calls_relay_restart_without_app_restart(tmp_path):
    import time
    import urllib.request
    from urllib.parse import parse_qs, urlparse
    from nodelang.cloud_signin import SignIn

    completed = []

    def http(method, url, **kwargs):
        if method == "GET" and url.endswith("/v1/me"):
            return 200, {"email": "owner-a@example.com"}
        if method == "GET":
            query = parse_qs(urlparse(url).query)
            return 200, {"auth_url": (
                query["redirect"][0] + "?code=code-a&state=" + query["state"][0])}
        if method == "POST":
            return 200, {"token": "t", "expires_at": int(time.time()) + 3600,
                         "email": "owner-a@example.com"}
        raise AssertionError(method)

    def opener(url):
        with urllib.request.urlopen(url, timeout=5) as response:
            response.read()

    attempt = SignIn("google", path=tmp_path / "cloud.json", opener=opener,
                     http=http, on_complete=completed.append, wait_seconds=5).start()
    attempt.thread.join(timeout=10)

    assert attempt.status()["phase"] == "done"
    assert completed == ["owner-a@example.com"]

