"""The founder sees and steers the cloud relay (Cockpit P6a, 2026-09-29).

The relay is the agent_tasks queue the founder's application drains. The
cockpit shows each status's count, the oldest wait, whether the application
is publishing, and the latest failures; it retries one failed task or drains
the queue. Both actions are audited; non-founders are refused by the route
walk (test_every_founder_route_is_gated.py).
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


def _seed():
    import db
    queued = [db.enqueue_agent_task(directive="court: read %d" % i, created_by=FOUNDER, kind="app")
              for i in range(2)]
    claimed = db.enqueue_agent_task(directive="court: running", created_by=FOUNDER, kind="app")
    db.claim_agent_task(claimed["id"], "court-app")
    failed = db.enqueue_agent_task(directive="court: gave up", created_by=FOUNDER, kind="app")
    db.expire_agent_task(failed["id"], "device_offline: court")
    return queued, claimed, failed


def test_the_relay_shows_its_queue_and_its_failures(client):
    queued, claimed, failed = _seed()
    body = client.get("/founder/api/relay", headers=_auth(FOUNDER)).json()
    assert body["counts"] == {"queued": 2, "claimed": 1, "failed": 1}
    assert body["oldest_queued_age_s"] is not None and body["oldest_queued_age_s"] >= 0
    assert [task["id"] for task in body["failed"]] == [failed["id"]]
    assert body["failed"][0]["result"].startswith("device_offline")
    assert set(body["application"]) == {"pushed_at", "live"}


def test_a_failed_task_is_retried_once_and_audited(client):
    import db
    queued, claimed, failed = _seed()
    r = client.post("/founder/api/relay/tasks/%s/retry" % failed["id"], headers=_auth(FOUNDER))
    assert r.status_code == 200 and r.json()["task"]["status"] == "queued"
    assert db.get_agent_task(failed["id"])["result"] == ""
    again = client.post("/founder/api/relay/tasks/%s/retry" % failed["id"], headers=_auth(FOUNDER))
    assert again.status_code == 404                        # it is queued now, not failed
    running = client.post("/founder/api/relay/tasks/%s/retry" % claimed["id"],
                          headers=_auth(FOUNDER))
    assert running.status_code == 404
    audited = [a for a in db.recent_founder_actions(50) if a["action"] == "relay.retry"]
    assert [a["target"] for a in audited] == [failed["id"]]


def test_draining_closes_every_queued_task_and_nothing_else(client):
    import db
    queued, claimed, failed = _seed()
    r = client.post("/founder/api/relay/drain", headers=_auth(FOUNDER),
                    json={"reason": "court: app reinstalled"})
    assert r.status_code == 200 and r.json()["drained"] == 2
    assert sorted(r.json()["ids"]) == sorted(task["id"] for task in queued)
    for task in queued:
        row = db.get_agent_task(task["id"])
        assert row["status"] == "failed" and "court: app reinstalled" in row["result"]
    assert db.get_agent_task(claimed["id"])["status"] == "claimed"
    (row,) = [a for a in db.recent_founder_actions(50) if a["action"] == "relay.drain"]
    assert '"drained": 2' in row["result"]