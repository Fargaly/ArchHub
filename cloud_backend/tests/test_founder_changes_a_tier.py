"""The founder changes an account's tier (Cockpit P3, 2026-09-29).

A direct route over the same set_plan the cockpit command runs: the quota
moves with the tier, errors use that path's fixed codes, and the change is
one founder_action_log row. Non-founders are refused by the route walk
(test_every_founder_route_is_gated.py).
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"
USER = "tier.change@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def test_the_founder_moves_an_account_to_another_tier_with_its_quota(client):
    import config
    import db
    user = db.get_or_create_user(USER)
    r = client.post("/founder/api/users/%s/plan" % USER, headers=_auth(FOUNDER),
                    json={"plan": "studio"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "studio" and r.json()["ok"] is True
    row = db.get_user(user["id"])
    assert row["plan"] == "studio" and row["msg_limit"] == config.PLAN_QUOTAS["studio"]
    audited = [a for a in db.recent_founder_actions(50) if a["action"] == "set_plan"]
    assert audited and audited[0]["target"] == USER and audited[0]["actor"] == FOUNDER


def test_an_unknown_tier_changes_nothing(client):
    import db
    user = db.get_or_create_user(USER)
    r = client.post("/founder/api/users/%s/plan" % user["id"], headers=_auth(FOUNDER),
                    json={"plan": "platinum"})
    assert r.status_code == 400 and r.json()["error"] == "unknown_plan"
    assert db.get_user(user["id"])["plan"] == "trial"


def test_an_unknown_account_is_404(client):
    r = client.post("/founder/api/users/nobody@nowhere.example/plan", headers=_auth(FOUNDER),
                    json={"plan": "studio"})
    assert r.status_code == 404