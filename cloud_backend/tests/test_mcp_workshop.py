"""Spark and Notion take part in the founder's Workshop through the one MCP door.

A client asks for mcp:workshop next to mcp:read; the consent page says what that
grants before Approve. Only then, and only for the founder's account, /mcp lists the
Workshop tools; each call is queued as a workshop-call task naming THAT client, so
the founder's running app answers it as the client's own agent
(nodelang/cloud_relay.py McpWorkshopAgents). These courts play the app's side over
the real queue.

Run: python -m pytest cloud_backend/tests/test_mcp_workshop.py -q
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the OAuth court's helpers
from test_mcp_oauth import (FOUNDER, REDIRECT, _continue, _google, _mcp, _pkce,  # noqa: F401
                            _register, _token, client)

STRANGER = "someone.else@studio.example"
WORKSHOP = {"workshop.lens", "workshop.agents", "workshop.read", "workshop.message",
            "workshop.post", "workshop.acknowledge", "work.claim"}


@pytest.fixture(autouse=True)
def _short_wait(monkeypatch):
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "6")


def _authorize(client, client_id, challenge, scope):
    r = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st-1",
        "scope": scope, "resource": "https://api.archhub.io/mcp"})
    return r


def _grant(client, monkeypatch, *, scope, email=FOUNDER, name="Spark"):
    r = client.post("/oauth/register", json={"redirect_uris": [REDIRECT], "client_name": name})
    assert r.status_code == 201, r.text
    client_id = r.json()["client_id"]
    verifier, challenge = _pkce()
    _google(monkeypatch, email)
    page = _authorize(client, client_id, challenge, scope)
    assert page.status_code == 200 and "Approve" in page.text, page.text
    pending = re.search(r'name=pending value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name=csrf value="([^"]+)"', page.text).group(1)
    r = client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"})
    assert r.status_code == 302, r.text
    back = _continue(client, pending)
    code = re.search(r"[?&]code=([^&]+)", back.headers["location"]).group(1)
    r = _token(client, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
               client_id=client_id, code_verifier=verifier, resource="https://api.archhub.io/mcp")
    assert r.status_code == 200, r.text
    return client_id, r.json(), page.text


def _listed(client, token):
    status, body = _mcp(client, token)
    assert status == 200, body
    return {tool["name"] for tool in body["result"]["tools"]}


def _play_the_app(answer, *, ok=True):
    """The founder's running app: claim the next Workshop step and answer it."""
    seen = {}

    def run():
        import config
        import db
        for _ in range(40):
            time.sleep(0.15)
            task = db.claim_next_agent_task(claimed_by="archhub-app", kinds=("workshop-call",),
                                            creators=config.founder_emails())
            if task:
                seen["task"] = task
                db.finish_agent_task(task["id"], ok=ok, result=json.dumps(answer) if ok else answer)
                return
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return seen, thread


def test_discovery_and_the_challenge_offer_the_workshop_scope(client):
    assert client.get("/.well-known/oauth-protected-resource").json()["scopes_supported"] == [
        "mcp:read", "mcp:workshop"]
    challenge = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "brain.health"}}).headers["www-authenticate"]
    assert 'scope="mcp:read mcp:workshop"' in challenge


def test_the_consent_page_names_the_workshop_only_when_it_is_asked_for(client, monkeypatch):
    client_id = _register(client)
    _verifier, challenge = _pkce()
    asked = _authorize(client, client_id, challenge, "mcp:read mcp:workshop")
    assert asked.status_code == 200 and "join the Workshop as its own agent" in asked.text
    plain = _authorize(client, client_id, challenge, "mcp:read")
    assert plain.status_code == 200 and "Workshop" not in plain.text
    wider = _authorize(client, client_id, challenge, "mcp:read mcp:admin")
    assert wider.status_code == 302 and "invalid_scope" in wider.headers["location"]


def test_only_the_founders_client_granted_the_workshop_lists_and_calls_it(client, monkeypatch):
    _, with_workshop, _ = _grant(client, monkeypatch, scope="mcp:read mcp:workshop")
    assert with_workshop["scope"] == "mcp:read mcp:workshop"
    assert WORKSHOP <= _listed(client, with_workshop["access_token"])
    _, read_only, _ = _grant(client, monkeypatch, scope="mcp:read")
    assert read_only["scope"] == "mcp:read"
    assert not WORKSHOP & _listed(client, read_only["access_token"])
    status, body = _mcp(client, read_only["access_token"], "tools/call",
                        {"name": "workshop.read", "arguments": {}})
    assert body["result"]["isError"] is True and "not granted the Workshop" in body["result"]["content"][0]["text"]
    _, stranger, _ = _grant(client, monkeypatch, scope="mcp:read mcp:workshop", email=STRANGER)
    assert not WORKSHOP & _listed(client, stranger["access_token"])
    status, body = _mcp(client, stranger["access_token"], "tools/call",
                        {"name": "workshop.post", "arguments": {"target": "x", "message": "m",
                                                                "idempotency_key": "stranger-1"}})
    assert body["error"]["message"] == "unknown tool"
    import db
    assert db.count_agent_tasks() == 0, "nothing was queued for a refused call"


def test_a_post_is_queued_as_this_clients_own_agent_and_answered_by_the_app(client, monkeypatch, caplog):
    client_id, granted, _ = _grant(client, monkeypatch, scope="mcp:read mcp:workshop", name="Gemini Spark")
    answer = {"ok": True, "actor": "app:agent-session:runtime:" + "a" * 32, "message_id": "m-1",
              "agent_runtime": "mcp-gemini-spark"}
    seen, thread = _play_the_app(answer)
    status, body = _mcp(client, granted["access_token"], "tools/call", {"name": "workshop.post", "arguments": {
        "target": "app:agent-session:runtime:" + "b" * 32, "message": "Spark here",
        "idempotency_key": "spark-post-0001", "extra": "dropped"}})
    thread.join(timeout=10)
    assert status == 200 and "error" not in body, body
    assert json.loads(body["result"]["content"][0]["text"]) == answer
    task = seen["task"]
    assert task["kind"] == "workshop-call" and task["created_by"] == FOUNDER
    assert json.loads(task["directive"]) == {
        "agent": {"client_id": client_id, "client_name": "Gemini Spark"}, "method": "send_message",
        "params": {"target": "app:agent-session:runtime:" + "b" * 32, "message": "Spark here",
                   "idempotency_key": "spark-post-0001"}}
    import db
    with db.connect() as con:
        stored = json.dumps([dict(r) for r in con.execute("SELECT * FROM agent_tasks")])
    assert granted["access_token"] not in stored and granted["access_token"] not in caplog.text


def test_an_offline_app_is_reported_and_the_step_is_never_delivered_later(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "1")
    _, granted, _ = _grant(client, monkeypatch, scope="mcp:read mcp:workshop")
    status, body = _mcp(client, granted["access_token"], "tools/call",
                        {"name": "workshop.read", "arguments": {"limit": 5}})
    assert body["result"]["isError"] is True and "device_offline" in body["result"]["content"][0]["text"]
    import config
    import db
    assert db.claim_next_agent_task(claimed_by="archhub-app", kinds=("workshop-call",),
                                    creators=config.founder_emails()) is None


def test_bad_arguments_and_overlong_posts_are_refused_before_anything_is_queued(client, monkeypatch):
    _, granted, _ = _grant(client, monkeypatch, scope="mcp:read mcp:workshop")
    for arguments in ({"target": "x", "message": "m" * 1501, "idempotency_key": "long-post-01"},
                      {"target": "x", "message": "m"},
                      {"target": "", "message": "m", "idempotency_key": "empty-target"},
                      # Every field at its own limit: longer than one task row carries,
                      # refused rather than cut into JSON the app cannot read.
                      {"target": "t" * 256, "message": "m" * 1500, "idempotency_key": "k" * 128,
                       "reply_to": "r" * 256}):
        _status, body = _mcp(client, granted["access_token"], "tools/call",
                             {"name": "workshop.post", "arguments": arguments})
        assert body["result"]["isError"] is True, arguments
    _status, body = _mcp(client, granted["access_token"], "tools/call",
                         {"name": "workshop.message", "arguments": {"message_id": "m", "sequence": 0}})
    assert body["result"]["isError"] is True
    import db
    assert db.count_agent_tasks() == 0


def test_an_app_that_names_no_kinds_never_claims_a_workshop_step(client, monkeypatch):
    """An app from before this change sends no workshop-call kind; its default claim
    must not hand it a JSON step it would read as a BABOOM instruction."""
    import app_relay
    import db
    db.enqueue_agent_task(directive='{"method":"send_message"}', created_by=FOUNDER, kind=app_relay.WORKSHOP_CALL)
    import founder_cockpit
    kinds = tuple(k for k in app_relay.APP_KINDS if k != app_relay.WORKSHOP_CALL)
    assert "workshop-call" not in kinds and set(kinds) == {"app", "app-execute", "host-read"}
    body = founder_cockpit.AgentTaskClaimReq(kinds=[])
    response = founder_cockpit.api_agent_task_claim(body, founder={"email": FOUNDER})
    assert json.loads(response.body)["task"] is None
