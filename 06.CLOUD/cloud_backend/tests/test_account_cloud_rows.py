"""Settings > Account rows served by the cloud (D-055): invite access period and the office policy lock."""
from __future__ import annotations

from datetime import date, timedelta

import pytest


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import email_sender
    import main

    async def no_mail(**_kwargs):
        return None
    monkeypatch.setattr(email_sender, "send_company_invite", no_mail)
    return TestClient(main.app)


def _user(email):
    import db
    user = db.get_or_create_user(email)
    return user, {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _office(client, headers):
    r = client.post("/v1/companies", json={"name": "Rows Studio", "plan": "studio"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _join(client, cid, owner, email, **invite):
    r = client.post(f"/v1/companies/{cid}/invites", json={"email": email, **invite}, headers=owner)
    assert r.status_code == 200, r.text
    user, headers = _user(email)
    accepted = client.post("/v1/companies/invites/accept", json={"invite_token": r.json()["token"]}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    return user, headers, accepted.json()


def test_invite_access_days_end_the_membership_after_that_many_days(client):
    import db
    _owner, owner = _user("owner@rows.example")
    cid = _office(client, owner)
    member, _headers, answer = _join(client, cid, owner, "temp@rows.example", access_days=30)
    expected = (date.today() + timedelta(days=30)).isoformat()
    assert answer["access_until"] == expected
    assert db.get_membership(cid, member["id"])["access_until"] == expected
    with db.connect() as con:  # once the date passes, the membership reads as gone
        con.execute("UPDATE company_members SET access_until=? WHERE user_id=?",
                    ((date.today() - timedelta(days=1)).isoformat(), member["id"]))
    assert db.get_membership(cid, member["id"]) is None


def test_invite_without_access_days_never_ends(client):
    import db
    _owner, owner = _user("owner2@rows.example")
    cid = _office(client, owner)
    member, _headers, answer = _join(client, cid, owner, "staff@rows.example")
    assert answer["access_until"] is None
    assert not db.get_membership(cid, member["id"]).get("access_until")


def test_invite_refuses_an_out_of_range_access_period(client):
    _owner, owner = _user("owner3@rows.example")
    cid = _office(client, owner)
    r = client.post(f"/v1/companies/{cid}/invites", json={"email": "x@rows.example", "access_days": 0}, headers=owner)
    assert r.status_code == 422


def test_admin_locks_the_office_policy_and_every_member_reads_it(client):
    _owner, owner = _user("owner4@rows.example")
    cid = _office(client, owner)
    _member, member, _answer = _join(client, cid, owner, "m@rows.example")
    assert client.get(f"/v1/companies/{cid}/policy", headers=member).json()["locked"] is False
    put = client.put(f"/v1/companies/{cid}/policy", json={"locked": True, "values": {"lenUnit": "Metres", "nameCheck": True}},
                     headers=owner)
    assert put.status_code == 200, put.text
    read = client.get(f"/v1/companies/{cid}/policy", headers=member).json()
    assert read["locked"] is True and read["values"] == {"lenUnit": "Metres", "nameCheck": True}
    assert read["your_role"] == "member"


def test_a_member_cannot_change_the_office_policy(client):
    _owner, owner = _user("owner5@rows.example")
    cid = _office(client, owner)
    _member, member, _answer = _join(client, cid, owner, "m5@rows.example")
    r = client.put(f"/v1/companies/{cid}/policy", json={"locked": False, "values": {}}, headers=member)
    assert r.status_code == 403


def test_policy_refuses_nested_or_unknown_shaped_values(client):
    _owner, owner = _user("owner6@rows.example")
    cid = _office(client, owner)
    r = client.put(f"/v1/companies/{cid}/policy", json={"locked": True, "values": {"x": {"nested": 1}}}, headers=owner)
    assert r.status_code == 400


def test_a_stranger_cannot_read_an_office_policy(client):
    _owner, owner = _user("owner7@rows.example")
    cid = _office(client, owner)
    _stranger, stranger = _user("stranger@rows.example")
    assert client.get(f"/v1/companies/{cid}/policy", headers=stranger).status_code == 403
