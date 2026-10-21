"""The founder reads the Community Brain: its members and what was admitted (Cockpit P5, 2026-09-29).

Read-only views beside the one review surface (/founder/api/community/pending
and /judge, ADGR-0004). The facts view shows the exact text the founder
admitted, from community_reviews; the shared replica only labels each version
current, superseded (a newer version exists) or withdrawn, and its text is
never printed: after an edit the replica row is the new, still-pending text.
Nothing pending and nothing from a private replica appears.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


def _facts(client):
    answer = client.get("/founder/api/community/facts", headers=_founder())
    assert answer.status_code == 200, answer.text
    return answer


def test_members_are_listed_and_who_left_is_counted(client):
    import db
    stay, _ = _member("comm-stay@studio.test")
    leave, _ = _member("comm-leave@studio.test")
    for user in (stay, leave):
        db.add_community_member(CID, user["id"], role="member", owner_pub="court-key")
    db.remove_community_member(CID, leave["id"])
    db.record_community_optout(CID, leave["id"])
    answer = client.get("/founder/api/community/members", headers=_founder())
    assert answer.status_code == 200, answer.text
    (community,) = [c for c in answer.json()["communities"] if c["community_id"] == CID]
    emails = {member["email"] for member in community["members"]}
    assert "comm-stay@studio.test" in emails and "comm-leave@studio.test" not in emails
    assert community["left"] == 1


def test_only_admitted_text_is_shown_and_an_edit_marks_it_superseded(client):
    _, author = _member("comm-author@studio.test")
    _share(client, author, SKILL, "0000000000000100.aaaa")
    assert _facts(client).json()["facts"] == []            # pending is never shown here
    judged = client.post("/founder/api/community/judge", headers=_founder(), json={
        "community_id": CID, "id": "skill-1", "hlc": "0000000000000100.aaaa", "admit": True})
    assert judged.status_code == 200
    facts = _facts(client).json()["facts"]
    assert [(f["fragment_id"], f["text"], f["state"], f["contributor"]) for f in facts] == [
        ("skill-1", SKILL, "current", "comm-author@studio.test")]
    _share(client, author, SKILL + " (edited)", "0000000000000200.aaaa")
    answer = _facts(client)
    assert [(f["text"], f["state"]) for f in answer.json()["facts"]] == [(SKILL, "superseded")]
    assert "(edited)" not in answer.text                   # the pending edit never leaks