"""The founder suspends and restores an account (Cockpit P2, 2026-09-29).

A suspended account authenticates nowhere: db.user_for_token is the one path
every route turns a bearer token into a user, and it refuses a suspended
account. Its sessions are kept, so restoring brings the same sessions back.
A founder account can never be suspended (it would lock the cockpit). The
same chokepoint refuses the account's brain sync and every MCP tool call,
which is also the only way anything reaches the cloud relay (host reads).
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"
OTHER_FOUNDER = "founder@example.test"
USER = "suspend.me@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _reach(client, session) -> dict:
    """What a signed-in desktop does with its account: read, sync, call tools."""
    return {
        "me": client.get("/v1/me", headers=session).status_code,
        "brain_sync": client.post("/v1/brain/sync", headers=session,
                                  json={"delta": {"fragments": []}}).status_code,
        "mcp_tool": client.post("/mcp", headers=session, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "brain.list_facts", "arguments": {"limit": 5}}}).status_code,
    }


def test_a_suspended_account_is_refused_and_restore_brings_the_same_session_back(client):
    import db
    session = _auth(USER)
    assert _reach(client, session) == {"me": 200, "brain_sync": 200, "mcp_tool": 200}
    r = client.post("/founder/api/users/%s/suspend" % USER, headers=_auth(FOUNDER),
                    json={"reason": "court: unpaid"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["suspended_reason"] == "court: unpaid"
    assert _reach(client, session) == {"me": 401, "brain_sync": 401, "mcp_tool": 401}
    detail = client.get("/founder/api/users/%s" % USER, headers=_auth(FOUNDER)).json()["user"]
    assert detail["suspended_at"] and detail["suspended_reason"] == "court: unpaid"
    assert detail["sessions_active"] == 1                 # kept, not deleted
    r = client.post("/founder/api/users/%s/restore" % USER, headers=_auth(FOUNDER))
    assert r.status_code == 200 and r.json()["user"]["suspended_at"] is None
    assert _reach(client, session) == {"me": 200, "brain_sync": 200, "mcp_tool": 200}
    audited = [row["action"] for row in db.recent_founder_actions(50) if row["target"] == USER]
    assert audited[:2] == ["user.restore", "user.suspend"]


def test_a_founder_account_cannot_be_suspended(client):
    founder_session = _auth(OTHER_FOUNDER)                  # the account exists
    r = client.post("/founder/api/users/%s/suspend" % OTHER_FOUNDER, headers=_auth(FOUNDER),
                    json={"reason": "court"})
    assert r.status_code == 409
    assert client.get("/founder/api/overview", headers=founder_session).status_code == 200


def test_an_unknown_account_is_404(client):
    for verb in ("suspend", "restore"):
        r = client.post("/founder/api/users/nobody@nowhere.example/%s" % verb,
                        headers=_auth(FOUNDER), json={})
        assert r.status_code == 404