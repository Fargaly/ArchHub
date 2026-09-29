"""Court: members never pull a community version the founder review has not admitted.

Review of ADGR-0004 (2026-09-29): the cloud merged every member's community
fragment straight into the replica every member pulls. Now each contributed
version waits for the founder review (founder-only /founder/api/community,
the one surface the Cockpit uses). Every member read -- /v1/brain/sync, /facts,
/search, /stats -- holds unreviewed versions back; the contributor sees their own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

CID = "archhub-community"
SKILL = "Dimension stairs riser-first"


@pytest.fixture
def client(tmp_path):
    import main
    with TestClient(main.app) as c:
        yield c


def _member(email):
    import auth
    import db
    user = db.get_or_create_user(email)
    auth.provision_brain(user["id"])
    return user, {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _founder():
    import db
    user = db.get_or_create_user("founder@example.test")
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _share(client, headers, text, hlc, fid="skill-1"):
    answer = client.post("/v1/brain/sync", headers=headers, json={"delta": {"fragments": [
        {"id": fid, "kind": "practice", "text": text, "scope": "community", "hlc": hlc,
         "extra": {"community_id": CID}}]}})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _pulled(client, headers):
    answer = client.post("/v1/brain/sync", headers=headers, json={"delta": {"fragments": []}})
    assert answer.status_code == 200, answer.text
    return {f["id"]: f for f in answer.json()["merged"]["fragments"] if f.get("scope") == "community"}


def test_an_unreviewed_version_is_not_pulled_by_another_member(client):
    _, a = _member("gate-a@studio.test")
    _, b = _member("gate-b@studio.test")
    mine = _share(client, a, SKILL, "0000000000000100.aaaa")
    assert "skill-1" in {f["id"] for f in mine["merged"]["fragments"]}, "the contributor sees their own"
    assert "skill-1" not in _pulled(client, b)
    for path in ("/v1/brain/facts", "/v1/brain/search?q=stairs", "/v1/brain/stats"):
        body = client.get(path, headers=b)
        assert SKILL not in body.text, path


def test_the_founder_review_admits_and_then_members_pull(client):
    _, a = _member("gate-a2@studio.test")
    _, b = _member("gate-b2@studio.test")
    _share(client, a, SKILL, "0000000000000100.aaaa")
    pending = client.get("/founder/api/community/pending", headers=_founder()).json()["pending"]
    assert [(p["fragment_id"], p["text"]) for p in pending] == [("skill-1", SKILL)]
    judged = client.post("/founder/api/community/judge", headers=_founder(), json={
        "community_id": CID, "id": "skill-1", "hlc": "0000000000000100.aaaa", "admit": True})
    assert judged.status_code == 200 and judged.json()["status"] == "admitted"
    assert _pulled(client, b)["skill-1"]["text"] == SKILL
    # A new version is reviewed again before members see it.
    _share(client, a, SKILL + " (edited)", "0000000000000200.aaaa")
    assert "skill-1" not in _pulled(client, b)


def test_a_rejected_version_is_never_pulled_and_is_not_judged_twice(client):
    _, a = _member("gate-a3@studio.test")
    _, b = _member("gate-b3@studio.test")
    _share(client, a, SKILL, "0000000000000100.aaaa")
    body = {"community_id": CID, "id": "skill-1", "hlc": "0000000000000100.aaaa", "admit": False}
    assert client.post("/founder/api/community/judge", headers=_founder(), json=body).status_code == 200
    assert "skill-1" not in _pulled(client, b)
    assert client.post("/founder/api/community/judge", headers=_founder(), json=dict(body, admit=True)).status_code == 409


def test_only_the_founder_moderates(client):
    _, a = _member("gate-a4@studio.test")
    _share(client, a, SKILL, "0000000000000100.aaaa")
    assert client.get("/founder/api/community/pending", headers=a).status_code == 403
    assert client.post("/founder/api/community/judge", headers=a, json={
        "community_id": CID, "id": "skill-1", "hlc": "0000000000000100.aaaa", "admit": True}).status_code == 403

def test_a_future_expiry_is_not_a_withdrawal(client):
    """Review v2 (3): a row with text and a far-future valid_until passed as a
    'withdrawal' and reached every member unreviewed."""
    _, a = _member("gate-a5@studio.test")
    _, b = _member("gate-b5@studio.test")
    answer = client.post("/v1/brain/sync", headers=a, json={"delta": {"fragments": [
        {"id": "sneak", "kind": "practice", "text": "unreviewed text", "scope": "community",
         "hlc": "0000000000000100.aaaa", "valid_until": "2099-01-01T00:00:00Z",
         "extra": {"community_id": CID}}]}})
    assert answer.status_code == 200, answer.text
    assert "sneak" not in _pulled(client, b)


def test_a_forged_owner_does_not_unlock_a_version_for_its_target(client):
    """Review v2 (4): the reader's own rows are the ones the cloud recorded them
    pushing, never a row's owner_user."""
    import db
    b_user, b = _member("gate-b6@studio.test")
    _, a = _member("gate-a6@studio.test")
    answer = client.post("/v1/brain/sync", headers=a, json={"delta": {"fragments": [
        {"id": "forged", "kind": "practice", "text": "aimed at b", "scope": "community",
         "hlc": "0000000000000100.aaaa", "owner_user": b_user["id"], "extra": {"community_id": CID}}]}})
    assert answer.status_code == 200, answer.text
    assert "forged" not in _pulled(client, b)
    assert all(p["contributor"] != b_user["id"] for p in db.pending_community_versions())


def test_every_judgement_is_in_the_founder_action_log(client):
    import db
    _, a = _member("gate-a7@studio.test")
    _share(client, a, SKILL, "0000000000000100.aaaa")
    body = {"community_id": CID, "id": "skill-1", "hlc": "0000000000000100.aaaa", "admit": True}
    assert client.post("/founder/api/community/judge", headers=_founder(), json=body).status_code == 200
    assert client.post("/founder/api/community/judge", headers=_founder(), json=body).status_code == 409
    logged = [row for row in db.recent_founder_actions(50) if row.get("action") == "community.judge"]
    assert len(logged) == 2, logged
    assert sorted(bool(row.get("ok")) for row in logged) == [False, True]
