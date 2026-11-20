"""The founder recovers the owner of an existing community that has none enrolled (COMMUNITYJOINTRUST left
such communities locked: their join-codes are refused). One audited Cockpit action binds the community to a
registered account whose Ed25519 key signed this exact community and account; an enrolled owner is never
replaced. Disposable databases and keys only (conftest)."""
from __future__ import annotations

import base64
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

FOUNDER = "founder.desktop@example.test"


@pytest.fixture
def client(tmp_path, monkeypatch):
    import brain_replica
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT", tmp_path / "replicas")
    import main
    with TestClient(main.app) as c:
        yield c


def _bearer(email):
    import db
    user = db.get_or_create_user(email)
    return user, {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _signature(priv, community_id, user_id):
    from community_join import enrol_statement
    from tests.join_signing import _sign
    return _sign(priv, enrol_statement(community_id, user_id))


def _invitation(community_id, priv, pub):
    from community_join import _payload_bytes
    from tests.join_signing import _sign
    now = time.time()
    data = {"community_id": community_id, "name": "Court", "owner_pub": pub, "role": "member", "transport": {},
            "issued_by": "owner-device", "issued_at": now, "expires_at": now + 3600, "nonce": uuid.uuid4().hex[:12]}
    payload = _payload_bytes(data)
    return base64.urlsafe_b64encode(payload).decode() + "." + _sign(priv, payload)


def _state():
    """Every owner and membership row: a refused recovery must leave this exactly as it was."""
    import db
    with db.connect() as con:
        return (sorted(tuple(r) for r in con.execute("SELECT * FROM community_owners").fetchall()),
                sorted(tuple(r) for r in con.execute("SELECT * FROM community_members").fetchall()))


def _audits(community_id):
    import db
    return [row for row in db.recent_founder_actions(1000) if row["target"] == community_id]


def _recover(client, community_id, body):
    _, founder = _bearer(FOUNDER)
    return client.post("/founder/api/community/%s/owner" % community_id, headers=founder,
                       json={"typed": "RECOVER", **body})


def test_a_recovered_community_takes_join_codes_signed_by_its_account_key(client):
    import db
    from tests.join_signing import _generate_keypair
    owner, _ = _bearer("legacy.owner@studio.example")
    priv, pub = _generate_keypair()
    _, h = _bearer("legacy.member@studio.example")
    invitation = _invitation("legacy-studio", priv, pub)  # issued before the cloud enrolled owners
    assert client.post("/v1/community/join", headers=h, json={"envelope": invitation}).status_code == 403
    answer = _recover(client, "legacy-studio", {"owner": owner["email"], "owner_pub": pub,
                                                "signature": _signature(priv, "legacy-studio", owner["id"])})
    assert answer.status_code == 200 and answer.json()["owner"] == owner["email"], answer.text
    assert db.community_owner("legacy-studio")["owner_user_id"] == owner["id"]
    [row] = _audits("legacy-studio")
    assert row["ok"] == 1 and row["action"] == "community.owner.recover" and row["actor"] == FOUNDER
    joined = client.post("/v1/community/join", headers=h, json={"envelope": invitation})
    assert joined.status_code == 200 and joined.json()["community_keys"] == ["legacy-studio"], joined.text
    view = {c["community_id"]: c for c in client.get("/founder/api/community/members",
                                                       headers=_bearer(FOUNDER)[1]).json()["communities"]}
    assert view["legacy-studio"]["owner"] == {"enrolled": True, "email": owner["email"], "platform": False}


@pytest.mark.parametrize("case", ["unsigned", "signed_for_another_account", "not_typed", "unknown_account"])
def test_a_refused_recovery_writes_nothing_but_its_audit_row(client, case):
    import db
    from tests.join_signing import _generate_keypair
    owner, _ = _bearer("claimant@studio.example")
    other, _ = _bearer("other@studio.example")
    priv, pub = _generate_keypair()
    body = {"owner": owner["email"], "owner_pub": pub, "signature": _signature(priv, "locked-studio", owner["id"])}
    if case == "unsigned":
        body.pop("signature")
    elif case == "signed_for_another_account":
        body["signature"] = _signature(priv, "locked-studio", other["id"])
    elif case == "unknown_account":
        body["owner"] = "nobody@studio.example"
    before = _state()
    answer = (client.post("/founder/api/community/locked-studio/owner", headers=_bearer(FOUNDER)[1], json=body)
              if case == "not_typed" else _recover(client, "locked-studio", body))
    assert answer.status_code in (400, 404) and answer.json()["ok"] is False, answer.text
    assert _state() == before and db.community_owner("locked-studio") is None
    [row] = _audits("locked-studio")
    assert row["ok"] == 0 and json.loads(row["result"])["refused"]


def test_a_competing_recovery_is_refused_and_the_enrolled_owner_stays(client):
    import db
    from tests.join_signing import _generate_keypair
    owner, _ = _bearer("first.owner@studio.example")
    rival, _ = _bearer("rival.owner@studio.example")
    priv, pub = _generate_keypair()
    rival_priv, rival_pub = _generate_keypair()
    assert _recover(client, "contested-studio", {"owner": owner["email"], "owner_pub": pub,
                                                 "signature": _signature(priv, "contested-studio", owner["id"])}).status_code == 200
    before = _state()
    answer = _recover(client, "contested-studio", {"owner": rival["email"], "owner_pub": rival_pub,
                                                   "signature": _signature(rival_priv, "contested-studio", rival["id"])})
    assert answer.status_code == 409 and answer.json()["ok"] is False
    assert _state() == before and db.community_owner("contested-studio")["owner_pub"] == pub
    assert [row["ok"] for row in _audits("contested-studio")] == [0, 1]  # newest first: the refusal, then the recovery


def test_only_the_founder_can_recover(client):
    from tests.join_signing import _generate_keypair
    owner, h = _bearer("not.founder@studio.example")
    priv, pub = _generate_keypair()
    before = _state()
    answer = client.post("/founder/api/community/locked-studio/owner", headers=h, json={
        "owner": owner["email"], "owner_pub": pub, "signature": _signature(priv, "locked-studio", owner["id"]),
        "typed": "RECOVER"})
    assert answer.status_code in (302, 303, 401, 403)
    assert _state() == before and _audits("locked-studio") == []


def test_an_audit_row_that_cannot_be_written_enrols_no_owner(client, monkeypatch):
    """Owner enrolment and its founder audit row are one transaction: if the audit row fails, nothing is enrolled."""
    import sqlite3
    import db
    from tests.join_signing import _generate_keypair
    owner, _ = _bearer("audit.fails@studio.example")
    priv, pub = _generate_keypair()

    def broken(con, **_row):
        raise sqlite3.OperationalError("audit log is not writable")

    monkeypatch.setattr(db, "_insert_founder_action", broken)
    before = _state()
    with pytest.raises(sqlite3.OperationalError):
        _recover(client, "unaudited-studio", {"owner": owner["email"], "owner_pub": pub,
                                               "signature": _signature(priv, "unaudited-studio", owner["id"])})
    assert _state() == before and db.community_owner("unaudited-studio") is None
    assert _audits("unaudited-studio") == []
    with pytest.raises(sqlite3.OperationalError):  # the same holds for the owner operation called directly
        db.recover_community_owner("unaudited-studio", owner_user_id=owner["id"], owner_pub=pub,
                                   signature=_signature(priv, "unaudited-studio", owner["id"]),
                                   audit={"actor": FOUNDER, "command": "court", "action": "community.owner.recover",
                                          "target": "unaudited-studio", "result": "{}", "ok": True})
    assert _state() == before and _audits("unaudited-studio") == []