"""Court: the desktop's heartbeat is what the founder Cockpit lists (real cloud).

brain_cloud_runner.heartbeat_now, posted to the real /v1/devices/heartbeat on
the signed-in account's session, puts this install's stable id and machine
label (never its hostname) in the device registry the founder reads -- the same\nrow on every beat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nodelang import brain_cloud_runner as runner  # noqa: E402

FOUNDER = "founder.desktop@example.test"
USER = "heartbeat.owner@studio.example"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email):
    import db
    return {"Authorization": "Bearer " + db.issue_token(db.get_or_create_user(email)["id"])}


def test_the_desktop_heartbeat_appears_in_the_founder_device_list(client, tmp_path, monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "ACME-LT-1234")
    session = _auth(USER)
    (tmp_path / "ArchHub" / "brain").mkdir(parents=True)
    (tmp_path / "ArchHub" / "brain" / "cloud.json").write_text(
        json.dumps({"email": USER, "token": "court"}), encoding="utf-8")

    def post(body):
        answer = client.post("/v1/devices/heartbeat", headers=session, json=body)
        assert answer.status_code == 200, answer.text
        return answer.json()
    assert runner.heartbeat_now(appdata=tmp_path, post=post) == {"ok": True}
    assert runner.heartbeat_now(appdata=tmp_path, post=post) == {"ok": True}
    listed = client.get("/founder/api/devices", params={"user": USER}, headers=_auth(FOUNDER)).json()
    rows = listed["devices"]
    assert len(rows) == 1, rows
    assert rows[0]["device_id"] == runner.device_id(tmp_path)
    assert rows[0]["name"].endswith(" desktop") and rows[0]["online"] is True
    assert "ACME" not in json.dumps(listed), "the hostname reached the founder's list"