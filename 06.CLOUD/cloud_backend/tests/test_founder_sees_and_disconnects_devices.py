"""The founder sees every signed-in device and can disconnect one (Cockpit P6b, 2026-09-29).

A device reports a heartbeat on its account session (POST /v1/devices/heartbeat).
The registry keeps the device's id, label, the digest of that session (never
the bearer) and the last heartbeat. Disconnect revokes that one session; the
account's other devices keep theirs, and signing in again reconnects it.
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"
USER = "device.owner@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _beat(client, session, device, name=""):
    return client.post("/v1/devices/heartbeat", headers=session,
                       json={"device_id": device, "name": name})


def test_devices_are_listed_and_one_is_disconnected_alone(client):
    import db
    laptop, desk = _auth(USER), _auth(USER)
    assert _beat(client, laptop, "laptop-1", "Studio laptop").status_code == 200
    assert _beat(client, desk, "desk-2", "Office desktop").status_code == 200
    listed = client.get("/founder/api/devices", params={"user": USER}, headers=_auth(FOUNDER))
    rows = {row["device_id"]: row for row in listed.json()["devices"]}
    assert set(rows) == {"laptop-1", "desk-2"}
    assert rows["laptop-1"]["name"] == "Studio laptop" and rows["laptop-1"]["online"] is True
    with db.connect() as con:
        digests = [row[0] for row in con.execute("SELECT token FROM tokens")]
    assert not any(digest in listed.text for digest in digests)
    assert laptop["Authorization"].split()[1] not in listed.text
    r = client.post("/founder/api/devices/%s/laptop-1/disconnect" % USER, headers=_auth(FOUNDER))
    assert r.status_code == 200 and r.json()["sessions_revoked"] == 1
    assert client.get("/v1/me", headers=laptop).status_code == 401    # this device only
    assert client.get("/v1/me", headers=desk).status_code == 200
    detail = client.get("/founder/api/users/%s" % USER, headers=_auth(FOUNDER)).json()["user"]
    by_id = {row["device_id"]: row for row in detail["devices"]}
    assert by_id["laptop-1"]["disconnected_at"] and by_id["laptop-1"]["online"] is False
    (row,) = [a for a in db.recent_founder_actions(50) if a["action"] == "device.disconnect"]
    assert row["target"] == "%s/laptop-1" % USER


def test_signing_in_again_reconnects_the_device(client):
    _beat(client, _auth(USER), "laptop-1")
    client.post("/founder/api/devices/%s/laptop-1/disconnect" % USER, headers=_auth(FOUNDER))
    assert _beat(client, _auth(USER), "laptop-1").status_code == 200      # a new session
    rows = client.get("/founder/api/devices", params={"user": USER},
                      headers=_auth(FOUNDER)).json()["devices"]
    assert rows[0]["disconnected_at"] is None and rows[0]["online"] is True


def test_the_heartbeat_needs_a_session_and_a_plain_device_id(client):
    assert _beat(client, {}, "laptop-1").status_code == 401
    assert _beat(client, _auth(USER), "bad id with spaces").status_code == 422


def test_an_unknown_device_or_account_is_404(client):
    headers = _auth(FOUNDER)
    assert client.post("/founder/api/devices/%s/none/disconnect" % USER,
                       headers=headers).status_code == 404
    assert client.get("/founder/api/devices", params={"user": "nobody@nowhere.example"},
                      headers=headers).status_code == 404