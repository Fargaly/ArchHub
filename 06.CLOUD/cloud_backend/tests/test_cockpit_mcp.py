"""The Cockpit over MCP: the founder's agents and automations reach the Cockpit's own tools.

One door (/mcp), the tools are cockpit_agent.TOOLS themselves, only the founder's account sees or calls them. A read
runs and is audited. A write returns its preview and an approval id and changes nothing until the founder approves it in
the Cockpit; approve runs the existing executor once, reject runs nothing. Refunds, erasure and impersonation have no tool.

Run: python -m pytest cloud_backend/tests/test_cockpit_mcp.py -q
"""
from __future__ import annotations

import json

import pytest

FOUNDER = "founder.desktop@example.test"
STRANGER = "someone.else@studio.example"
PERSON = "architect.two@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _token(email: str) -> str:
    import db
    return db.issue_token(db.get_or_create_user(email)["id"])


def _rpc(client, method, params=None, token=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    data = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    return r.status_code, (json.loads(data[0]) if data else {})


def _call(client, token, name, arguments=None):
    status, body = _rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, token)
    assert status == 200
    return body


def _payload(body):
    return json.loads(body["result"]["content"][0]["text"])


def _logged(command: str) -> list:
    import db
    return [row for row in db.recent_founder_actions(100) if row["command"] == command]


def _listed(client, token):
    _, body = _rpc(client, "tools/list", token=token)
    return {tool["name"]: tool for tool in body["result"]["tools"]}


def test_the_listing_is_the_registry_and_only_the_founder_has_it(client):
    import cockpit_agent
    mine = {n for n in _listed(client, _token(FOUNDER)) if n.startswith("cockpit_")}
    assert mine == {"cockpit_" + n for n, s in cockpit_agent.TOOLS.items() if s["kind"] in ("read", "write")} | {"cockpit_approval_status"}
    assert not any(n.startswith("cockpit_") for n in _listed(client, _token(STRANGER)))
    assert not any(n.startswith("cockpit_") for n in _listed(client, None))
    for word in ("refund", "erase", "impersonat"):
        assert not any(word in n for n in mine)


def test_reads_are_marked_read_only_and_writes_are_not(client):
    tools = _listed(client, _token(FOUNDER))
    assert tools["cockpit_users_find"]["annotations"]["readOnlyHint"] is True
    assert tools["cockpit_users_set_plan"]["annotations"]["readOnlyHint"] is False


def test_a_stranger_cannot_call_a_cockpit_tool(client):
    body = _call(client, _token(STRANGER), "cockpit_users_find", {"query": "a"})
    assert body["error"]["message"] == "unknown tool"


def test_a_read_runs_and_is_audited(client):
    import db
    db.get_or_create_user(PERSON)
    body = _call(client, _token(FOUNDER), "cockpit_users_find", {"query": "architect.two"})
    assert any(u["email"] == PERSON for u in _payload(body)["users"])
    assert _logged("mcp:cockpit_users_find")


def test_app_command_from_here_never_executes(client, monkeypatch):
    import app_relay
    seen = {}
    monkeypatch.setattr(app_relay, "relay", lambda text, *, actor, execute=False: seen.update(execute=execute) or {"ok": True})
    _call(client, _token(FOUNDER), "cockpit_app_command", {"utterance": "what is blocked?", "execute": True})
    assert seen == {"execute": False}


def test_a_write_holds_a_preview_and_changes_nothing(client):
    import db
    db.get_or_create_user(PERSON)
    before = db.get_user_by_email(PERSON)["plan"]
    held = _payload(_call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": PERSON, "plan": "firm"}))
    assert held["state"] == "pending" and held["approval_id"].startswith("ap_") and "firm" in held["preview"]["summary"]
    assert db.get_user_by_email(PERSON)["plan"] == before
    status = _payload(_call(client, _token(FOUNDER), "cockpit_approval_status", {"approval_id": held["approval_id"]}))
    assert status["state"] == "pending"
    assert _logged("mcp:cockpit_users_set_plan")


def test_approve_runs_it_once_and_the_agent_can_see_the_outcome(client):
    import db
    db.get_or_create_user(PERSON)
    held = _payload(_call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": PERSON, "plan": "studio"}))
    inbox = client.get("/founder/api/inbox", headers={"Authorization": "Bearer " + _token(FOUNDER)}).json()["items"]
    row = next(i for i in inbox if i["kind"] == "agent_write")
    assert row["id"] == held["approval_id"] and "studio" in row["title"]
    url = "/founder/api/agent-approvals/%s/decide" % held["approval_id"]
    auth = {"Authorization": "Bearer " + _token(FOUNDER)}
    done = client.post(url, headers=auth, json={"approve": True})
    assert done.status_code == 200 and done.json()["state"] == "approved"
    assert db.get_user_by_email(PERSON)["plan"] == "studio"
    again = client.post(url, headers=auth, json={"approve": True})
    assert again.status_code == 409                                    # never a second run
    status = _payload(_call(client, _token(FOUNDER), "cockpit_approval_status", {"approval_id": held["approval_id"]}))
    assert status["state"] == "approved" and status["result"]["ok"] is True
    assert _logged("approved agent request " + held["approval_id"])    # the executor's own audit row


def test_reject_runs_nothing(client):
    import db
    db.get_or_create_user(PERSON)
    before = db.get_user_by_email(PERSON)["plan"]
    held = _payload(_call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": PERSON, "plan": "firm"}))
    auth = {"Authorization": "Bearer " + _token(FOUNDER)}
    out = client.post("/founder/api/agent-approvals/%s/decide" % held["approval_id"], headers=auth, json={"approve": False})
    assert out.status_code == 200 and out.json()["state"] == "rejected"
    assert db.get_user_by_email(PERSON)["plan"] == before
    assert client.post("/founder/api/agent-approvals/%s/decide" % held["approval_id"], headers=auth, json={"approve": True}).status_code == 409


def test_a_stranger_cannot_decide_and_an_expired_request_cannot_run(client):
    import db
    db.get_or_create_user(PERSON)
    held = _payload(_call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": PERSON, "plan": "firm"}))
    url = "/founder/api/agent-approvals/%s/decide" % held["approval_id"]
    assert client.post(url, headers={"Authorization": "Bearer " + _token(STRANGER)}, json={"approve": True}).status_code == 403
    with db.connect() as con:
        con.execute("UPDATE founder_agent_approvals SET created_at = created_at - ? WHERE id = ?", (db.AGENT_APPROVAL_TTL_S + 5, held["approval_id"]))
    out = client.post(url, headers={"Authorization": "Bearer " + _token(FOUNDER)}, json={"approve": True})
    assert out.status_code == 409 and db.get_user_by_email(PERSON)["plan"] != "firm"


def test_an_executor_that_raises_leaves_a_recorded_failure_not_an_empty_approval(client, monkeypatch):
    import cockpit_agent
    import db
    db.get_or_create_user(PERSON)
    held = _payload(_call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": PERSON, "plan": "firm"}))
    monkeypatch.setattr(cockpit_agent, "confirm_pending", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = client.post("/founder/api/agent-approvals/%s/decide" % held["approval_id"],
                      headers={"Authorization": "Bearer " + _token(FOUNDER)}, json={"approve": True})
    assert out.status_code == 409 and out.json()["ok"] is False
    status = _payload(_call(client, _token(FOUNDER), "cockpit_approval_status", {"approval_id": held["approval_id"]}))
    assert status["result"]["ok"] is False and status["result"]["error"] == "RuntimeError"
    assert "boom" not in json.dumps(status)
    assert any(not row["ok"] for row in _logged("mcp:cockpit_approval"))


def test_the_cockpit_cookie_decides_only_from_the_cockpits_own_origin(client):
    import db
    db.get_or_create_user(PERSON)
    token = _token(FOUNDER)
    held = _payload(_call(client, token, "cockpit_users_set_plan", {"email": PERSON, "plan": "firm"}))
    url = "/founder/api/agent-approvals/%s/decide" % held["approval_id"]
    client.cookies.set("founder_session", token)
    assert client.post(url, json={"approve": True}).status_code == 403                                   # no Origin
    assert client.post(url, json={"approve": True}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert db.get_user_by_email(PERSON)["plan"] != "firm"
    ok = client.post(url, json={"approve": True}, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200 and db.get_user_by_email(PERSON)["plan"] == "firm"


def test_a_bad_write_is_refused_before_anything_is_held(client):
    import db
    body = _call(client, _token(FOUNDER), "cockpit_users_set_plan", {"email": "nobody@studio.example", "plan": "firm"})
    assert body["result"]["isError"] is True
    assert db.pending_agent_approvals() == []
