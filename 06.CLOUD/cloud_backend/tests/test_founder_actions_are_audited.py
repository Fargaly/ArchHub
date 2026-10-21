"""Every cockpit route that acts writes one founder_action_log row (Cockpit P9, 2026-09-29).

The command path always audited; four routes that act outside it did not:
the purge-test-users route, the browser sign-in code, and the application's
task claim and result. A minted sign-in code is never written to the log.
(POST /founder/map-state is the founder's desktop publishing its map, a sync
stamped by its own pushed-at record, not an action.)
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _actions(action: str) -> list[dict]:
    import db
    return [row for row in db.recent_founder_actions(200) if row["action"] == action]


def test_the_purge_route_audits_its_preview_and_its_effect(client):
    import db
    db.get_or_create_user("seed-user-1@example.com")
    preview = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER), json={})
    assert preview.status_code == 200 and preview.json()["dry_run"] is True
    assert [row["actor"] for row in _actions("purge_test_users.preview")] == [FOUNDER]
    done = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER),
                       json={"confirm": True})
    assert done.status_code == 200 and done.json()["dry_run"] is False
    (row,) = _actions("purge_test_users")
    assert row["actor"] == FOUNDER and '"deleted": %d' % done.json()["deleted"] in row["result"]


def test_the_browser_code_is_audited_and_the_code_is_never_logged(client):
    r = client.post("/founder/api/browser-code", headers=_auth(FOUNDER))
    assert r.status_code == 200
    code = r.json()["claim_url"].split("code=", 1)[1]
    (row,) = _actions("browser_code")
    assert row["actor"] == FOUNDER
    import db
    assert not any(code in (entry["result"] + entry["command"] + (entry["target"] or ""))
                   for entry in db.recent_founder_actions(200))


def test_a_claimed_task_and_its_result_are_audited_an_idle_poll_is_not(client):
    import db
    idle = client.post("/founder/api/agent-tasks/claim", headers=_auth(FOUNDER), json={})
    assert idle.status_code == 200 and idle.json()["task"] is None
    assert _actions("agent_task.claim") == []
    task = db.enqueue_agent_task(directive="court: say hello", created_by=FOUNDER, kind="app")
    claimed = client.post("/founder/api/agent-tasks/claim", headers=_auth(FOUNDER), json={})
    assert claimed.json()["task"]["id"] == task["id"]
    (claim,) = _actions("agent_task.claim")
    assert claim["target"] == task["id"] and claim["actor"] == FOUNDER
    done = client.post("/founder/api/agent-tasks/%s/result" % task["id"],
                       headers=_auth(FOUNDER), json={"ok": True, "result": "hello"})
    assert done.status_code == 200
    (result,) = _actions("agent_task.result")
    assert result["target"] == task["id"] and result["ok"] == 1