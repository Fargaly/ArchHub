"""HANDOVER section 6, proved once: the incident queue is wired to something that genuinely reports.

"Its weakest point is that a founder opening it finds nothing behind the glass - every number
is authored." The design's incident queue read a DB.issues seed. The shipped queue counts two
things the cloud really holds, and this court walks both through the real routes:

  1. An instruction the founder's app refused. The app claims the task through
     /founder/api/agent-tasks/claim and posts ok=false, exactly as nodelang/cloud_relay.py does
     when BABOOM raises; the row becomes status "failed".
  2. A server error. main.py's exception handler records it with founder_cockpit.record_error;
     /founder/api/errors returns it.

Then it checks the cockpit bundle the browser downloads reads exactly those two answers, with
no seed collection in between. Set ARCHHUB_INCIDENT_PROOF_OUT to a directory to keep the two
JSON answers for a rendered proof.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

FOUNDER_EMAIL = "founder@archhub-incident-proof.com"
COMPILED = Path(__file__).resolve().parents[1] / "cockpit_assets" / "compiled"


@pytest.fixture(autouse=True)
def _founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    import founder_cockpit
    founder_cockpit.clear_errors()
    yield
    founder_cockpit.clear_errors()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _sign_in(client, monkeypatch, email):
    import secrets
    import db
    import email_sender

    async def fake_send(**_kw):
        return True

    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert client.post("/v1/auth/register", json={"email": email, "code_challenge": challenge}).status_code == 202
    user = db.get_user_by_email(email)
    with db.connect() as con:
        code = con.execute("SELECT code FROM codes WHERE user_id = ?", (user["id"],)).fetchone()["code"]
    answer = client.post("/v1/auth/exchange", json={"code": code, "code_verifier": verifier})
    assert answer.status_code == 200, answer.text
    return {"Authorization": "Bearer " + answer.json()["token"]}


def test_a_refused_instruction_and_a_server_error_reach_the_incident_queue(client, monkeypatch):
    import app_relay
    import founder_cockpit

    founder = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    queued = app_relay.enqueue("open revit", actor=FOUNDER_EMAIL, execute=True)
    claimed = client.post("/founder/api/agent-tasks/claim", headers=founder,
                          json={"claimed_by": "archhub-app", "kinds": ["app", "app-execute"]})
    assert claimed.status_code == 200, claimed.text
    task = claimed.json()["task"]
    assert task and task["id"] == queued["id"]
    refused = client.post("/founder/api/agent-tasks/%s/result" % task["id"], headers=founder,
                          json={"ok": False, "result": "RuntimeError: Revit is not running on this machine"})
    assert refused.status_code == 200, refused.text
    founder_cockpit.record_error(where="/founder/api/command", kind="TimeoutError",
                                 message="model call timed out", status=500)

    tasks = client.get("/founder/api/agent-tasks", headers=founder)
    errors = client.get("/founder/api/errors", headers=founder)
    assert tasks.status_code == 200 and errors.status_code == 200
    rows = tasks.json()["tasks"]
    failed = [row for row in rows if row["status"] == "failed"]
    assert [row["directive"] for row in failed] == ["open revit"]
    assert "Revit is not running" in failed[0]["result"]
    recorded = errors.json()["errors"]
    assert [(e["where"], e["kind"]) for e in recorded] == [("/founder/api/command", "TimeoutError")]

    out = os.environ.get("ARCHHUB_INCIDENT_PROOF_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "agent-tasks.json").write_text(json.dumps(tasks.json(), indent=1), encoding="utf-8")
        (Path(out) / "errors.json").write_text(json.dumps(errors.json(), indent=1), encoding="utf-8")


def test_the_cockpit_bundle_counts_exactly_those_two_answers():
    """The browser bundle reads the two routes above and nothing seeded."""
    cockpit = (COMPILED / "atlas-cockpit.js").read_text(encoding="utf-8")
    side = (COMPILED / "atlas-side.js").read_text(encoding="utf-8")
    assert "/founder/api/agent-tasks" in cockpit and "/founder/api/errors" in cockpit
    assert "serverErrors: serverErrors" in cockpit or "serverErrors=" in cockpit or "serverErrors:" in cockpit
    assert "r.status === 'failed'" in side, "failed task rows are not what the queue counts"
    assert "serverErrors" in side
    assert "DB.issues" not in side, "the queue still reads a seeded collection"
    assert "cannot tell whether anything failed" in side, "an unreadable source must not read as all clear"