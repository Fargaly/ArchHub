"""The cockpit's backend health is measured, kept and complete (Cockpit P7, 2026-09-29).

healthz used to be a constant {"ok": true}; errors lived in a ring lost on
every deploy; the Fly block showed only the machine answering the request.
Now: the database round trip and size, the replica store, the data volume;
errors kept across restarts; this app's machines read with a read-only
token that never leaves the server.
"""
from __future__ import annotations

import json

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


def _system(client) -> dict:
    r = client.get("/founder/api/system", headers=_auth(FOUNDER))
    assert r.status_code == 200, r.text
    return r.json()


def test_health_is_measured_not_asserted(client):
    health = _system(client)["healthz"]
    assert set(health["checks"]) == {"database", "replicas_root", "data_volume"}
    database = health["checks"]["database"]
    assert database["ok"] is True and database["bytes"] > 0 and database["round_trip_ms"] >= 0
    assert health["checks"]["data_volume"]["total_bytes"] > 0
    assert health["ok"] is all(check["ok"] for check in health["checks"].values())


def test_a_database_that_fails_turns_health_red_and_says_why(client, monkeypatch):
    import db

    def refuse():
        raise RuntimeError("court: the database is gone")
    monkeypatch.setattr(db, "database_health", refuse)
    health = _system(client)["healthz"]
    assert health["ok"] is False
    assert health["checks"]["database"] == {"ok": False, "reason": "RuntimeError"}


def test_errors_are_kept_across_a_restart(client):
    import founder_cockpit
    founder_cockpit.record_error(where="court", kind="Boom", message="kept across restarts")
    founder_cockpit._ERROR_RING.clear()                     # the process restarted
    r = client.get("/founder/api/errors", headers=_auth(FOUNDER))
    assert "kept across restarts" in r.text


def test_the_machine_list_says_why_it_is_unavailable(monkeypatch):
    import config
    import founder_cockpit
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert founder_cockpit._fly_machines() == {"available": False, "reason": "not running on Fly"}
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(config, "FLY_MACHINES_READ_TOKEN", "")
    assert founder_cockpit._fly_machines()["reason"] == (
        "no read-only Fly token (secret FLY_MACHINES_READ_TOKEN)")


def test_the_machines_are_listed_and_the_token_never_returned(monkeypatch):
    import config
    import founder_cockpit
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(config, "FLY_MACHINES_READ_TOKEN", "FlyV1 fm2_court_secret")
    founder_cockpit._FLY_CACHE.clear()
    seen = {}

    def fetch(app, token):
        seen["call"] = (app, token)
        return [{"id": "m1", "name": "archhub-cloud-1", "state": "started", "region": "fra",
                 "updated_at": "2026-09-29T12:00:00Z", "config": {"image": "registry/img:1"}}]
    answer = founder_cockpit._fly_machines(fetch)
    assert seen["call"] == ("archhub-cloud", "FlyV1 fm2_court_secret")
    assert answer == {"available": True, "machines": [{
        "id": "m1", "name": "archhub-cloud-1", "state": "started", "region": "fra",
        "updated_at": "2026-09-29T12:00:00Z", "image": "registry/img:1"}]}
    assert "fm2_court_secret" not in json.dumps(answer)