"""The founder reads any account: search, then one account's detail (Cockpit P1, 2026-09-29).

Cloud-side data only: plan and quota, the profile the user gave, active
sign-in sessions and metered usage. No session token or its digest ever
leaves the database; a user's local graph never reaches the cloud at all.
Non-founders are refused by test_every_founder_route_is_gated.py, which
walks these routes with every other.
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"
USER = "architect.one@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def test_the_founder_finds_an_account_and_reads_its_detail(client):
    import db
    user = db.get_or_create_user(USER)
    db.update_user_profile(user["id"], full_name="Court Architect", firm_name="Court Studio",
                           country="AE")
    bearer = _auth(USER)["Authorization"].split()[1]           # one live session
    db.log_usage(user["id"], model="court-model", input_toks=100, output_toks=40,
                 cost_micros=1234)
    found = client.get("/founder/api/users/find", params={"q": "architect.one"},
                       headers=_auth(FOUNDER))
    assert found.status_code == 200
    assert [row["email"] for row in found.json()["users"]] == [USER]
    detail = client.get("/founder/api/users/%s" % USER, headers=_auth(FOUNDER))
    assert detail.status_code == 200, detail.text
    body = detail.json()["user"]
    assert body["email"] == USER and body["plan"] == "trial"
    assert body["profile"]["full_name"] == "Court Architect"
    assert body["profile"]["firm_name"] == "Court Studio" and body["profile"]["country"] == "AE"
    assert body["sessions_active"] == 1
    assert body["usage"]["calls"] == 1 and body["usage"]["cost_micros"] == 1234
    assert body["usage"]["calls_last_30d"] == 1
    by_id = client.get("/founder/api/users/%s" % user["id"], headers=_auth(FOUNDER))
    assert by_id.json()["user"]["email"] == USER
    with db.connect() as con:
        digests = [row[0] for row in con.execute("SELECT token FROM tokens")]
    assert bearer not in detail.text
    assert not any(digest in detail.text for digest in digests)


def test_an_unknown_account_is_404(client):
    r = client.get("/founder/api/users/nobody@nowhere.example", headers=_auth(FOUNDER))
    assert r.status_code == 404