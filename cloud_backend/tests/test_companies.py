"""Companies / multi-seat — end-to-end HTTP tests via FastAPI TestClient.

Mirrors the pattern in test_endpoints.py: get a bearer token via the
magic-link/PKCE flow (with the email send stubbed), then exercise the
/v1/companies/* endpoints.

Covers the eight contract points called out in the spec:
  1. Authed user creates a company → 200, owner membership row exists
  2. Unauth create → 401
  3. /mine returns the membership list with the role
  4. Owner invites → invite row exists, email_sender called
  5. Non-owner invites → 403
  6. Accept invite → membership row created
  7. Accept twice → 400
  8. Delete member as owner works; deleting self → 400
  9. Switch company sets current_company_id
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


@pytest.fixture
def owner_token():
    """Issue a token for an owner user without going through PKCE."""
    import db
    u = db.get_or_create_user("owner@studio.com")
    return u, db.issue_token(u["id"])


@pytest.fixture
def other_token():
    import db
    u = db.get_or_create_user("teammate@studio.com")
    return u, db.issue_token(u["id"])


@pytest.fixture
def third_token():
    import db
    u = db.get_or_create_user("guest@studio.com")
    return u, db.issue_token(u["id"])


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Create
# ---------------------------------------------------------------------------
class TestCreateCompany:
    def test_unauthenticated_create_rejected(self, client):
        r = client.post("/v1/companies",
                          json={"name": "Foo Studio", "plan": "studio"})
        assert r.status_code == 401

    def test_owner_create_succeeds_and_owner_membership_exists(
            self, client, owner_token):
        import db
        _, token = owner_token
        r = client.post("/v1/companies",
                          json={"name": "Foo Studio", "plan": "studio"},
                          headers=_hdr(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Foo Studio"
        assert body["plan"] == "studio"
        assert body["seat_limit"] == 5
        cid = body["id"]
        # Owner row exists with role=owner.
        owner_user = db.get_user_by_email("owner@studio.com")
        m = db.get_membership(cid, owner_user["id"])
        assert m is not None
        assert m["role"] == "owner"

    def test_create_with_firm_plan_sets_25_seats(self, client, owner_token):
        _, token = owner_token
        r = client.post("/v1/companies",
                          json={"name": "Big Firm", "plan": "firm"},
                          headers=_hdr(token))
        assert r.status_code == 200
        assert r.json()["seat_limit"] == 25

    def test_unsupported_plan_rejected(self, client, owner_token):
        _, token = owner_token
        r = client.post("/v1/companies",
                          json={"name": "Solo Shop", "plan": "solo"},
                          headers=_hdr(token))
        assert r.status_code == 400

    def test_slug_collision_auto_increments(self, client, owner_token,
                                              other_token):
        _, t1 = owner_token
        _, t2 = other_token
        r1 = client.post("/v1/companies",
                           json={"name": "Studio X", "plan": "studio"},
                           headers=_hdr(t1))
        r2 = client.post("/v1/companies",
                           json={"name": "Studio X", "plan": "studio"},
                           headers=_hdr(t2))
        assert r1.json()["slug"] != r2.json()["slug"]


# ---------------------------------------------------------------------------
# 2. /mine
# ---------------------------------------------------------------------------
class TestListMine:
    def test_returns_companies_with_role(self, client, owner_token):
        _, token = owner_token
        client.post("/v1/companies",
                      json={"name": "Bar Studio", "plan": "studio"},
                      headers=_hdr(token))
        r = client.get("/v1/companies/mine", headers=_hdr(token))
        assert r.status_code == 200
        cos = r.json()["companies"]
        assert len(cos) == 1
        assert cos[0]["role"] == "owner"
        assert cos[0]["name"] == "Bar Studio"

    def test_mine_empty_for_user_with_no_companies(self, client, other_token):
        _, t = other_token
        r = client.get("/v1/companies/mine", headers=_hdr(t))
        assert r.status_code == 200
        assert r.json()["companies"] == []


# ---------------------------------------------------------------------------
# 3. Invites
# ---------------------------------------------------------------------------
def _send_calls_recorder(monkeypatch):
    """Patch email_sender.send_magic_link and return a list that gets
    populated with each call's kwargs."""
    calls: list[dict] = []
    async def fake_send(**kw):
        calls.append(kw)
        return True
    import email_sender
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    return calls


class TestInvites:
    def _new_company(self, client, token):
        return client.post("/v1/companies",
                              json={"name": "Inv Co", "plan": "studio"},
                              headers=_hdr(token)).json()["id"]

    def test_owner_invite_creates_row_and_sends_email(
            self, client, owner_token, monkeypatch):
        import db
        calls = _send_calls_recorder(monkeypatch)
        _, token = owner_token
        cid = self._new_company(client, token)
        r = client.post(f"/v1/companies/{cid}/invites",
                          json={"email": "newhire@studio.com",
                                "role": "member"},
                          headers=_hdr(token))
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        assert tok
        inv = db.get_company_invite(tok)
        assert inv is not None
        assert inv["email"] == "newhire@studio.com"
        assert inv["role"] == "member"
        assert len(calls) == 1
        assert calls[0]["to"] == "newhire@studio.com"

    def test_non_member_invite_rejected(
            self, client, owner_token, other_token, monkeypatch):
        _send_calls_recorder(monkeypatch)
        _, t1 = owner_token
        _, t2 = other_token
        cid = self._new_company(client, t1)
        r = client.post(f"/v1/companies/{cid}/invites",
                          json={"email": "x@studio.com", "role": "member"},
                          headers=_hdr(t2))
        assert r.status_code == 403

    def test_member_cannot_invite(self, client, owner_token, other_token,
                                    third_token, monkeypatch):
        """A plain member (not owner/admin) inviting → 403."""
        import db
        _send_calls_recorder(monkeypatch)
        _, t_owner = owner_token
        other_user, t_other = other_token
        _, t_third = third_token
        cid = self._new_company(client, t_owner)
        # Add `other` as a plain member directly via DAO so we don't
        # depend on the accept-flow for this assertion.
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        r = client.post(f"/v1/companies/{cid}/invites",
                          json={"email": "another@studio.com",
                                "role": "member"},
                          headers=_hdr(t_other))
        assert r.status_code == 403

    def test_invalid_role_rejected(self, client, owner_token, monkeypatch):
        _send_calls_recorder(monkeypatch)
        _, token = owner_token
        cid = self._new_company(client, token)
        r = client.post(f"/v1/companies/{cid}/invites",
                          json={"email": "x@studio.com", "role": "owner"},
                          headers=_hdr(token))
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4. Accept
# ---------------------------------------------------------------------------
class TestAcceptInvite:
    def _new_company_with_invite(self, client, owner_token, monkeypatch,
                                   invite_email="invitee@studio.com"):
        _send_calls_recorder(monkeypatch)
        _, t = owner_token
        cid = client.post("/v1/companies",
                            json={"name": "Acc Co", "plan": "studio"},
                            headers=_hdr(t)).json()["id"]
        tok = client.post(f"/v1/companies/{cid}/invites",
                            json={"email": invite_email, "role": "member"},
                            headers=_hdr(t)).json()["token"]
        return cid, tok

    def test_accept_creates_membership(
            self, client, owner_token, other_token, monkeypatch):
        import db
        # The invite must be addressed to the accepting user — email
        # match is enforced (roadmap #P2). other_token = teammate@.
        cid, tok = self._new_company_with_invite(
            client, owner_token, monkeypatch,
            invite_email="teammate@studio.com")
        other_user, t_other = other_token
        r = client.post("/v1/companies/invites/accept",
                          json={"invite_token": tok},
                          headers=_hdr(t_other))
        assert r.status_code == 200
        m = db.get_membership(cid, other_user["id"])
        assert m is not None
        assert m["role"] == "member"

    def test_accept_already_used_rejected(
            self, client, owner_token, other_token, monkeypatch):
        cid, tok = self._new_company_with_invite(
            client, owner_token, monkeypatch,
            invite_email="teammate@studio.com")
        _, t_other = other_token
        client.post("/v1/companies/invites/accept",
                      json={"invite_token": tok}, headers=_hdr(t_other))
        r = client.post("/v1/companies/invites/accept",
                          json={"invite_token": tok}, headers=_hdr(t_other))
        assert r.status_code == 400

    def test_accept_with_unknown_token(self, client, other_token):
        _, t = other_token
        r = client.post("/v1/companies/invites/accept",
                          json={"invite_token": "x" * 30},
                          headers=_hdr(t))
        assert r.status_code == 404

    def test_accept_email_mismatch_rejected(
            self, client, owner_token, other_token, monkeypatch):
        """Invite bound to one address, accepted by a user signed in
        with a different address → 403, NO membership, invite stays
        unused. Token possession alone must not buy a seat (#P2)."""
        import db
        cid, tok = self._new_company_with_invite(
            client, owner_token, monkeypatch,
            invite_email="someone-else@studio.com")
        other_user, t_other = other_token   # teammate@studio.com
        r = client.post("/v1/companies/invites/accept",
                          json={"invite_token": tok},
                          headers=_hdr(t_other))
        assert r.status_code == 403
        assert r.json()["detail"] == "invite_email_mismatch"
        # The seat must NOT have been granted...
        assert db.get_membership(cid, other_user["id"]) is None
        # ...and the invite stays open for the right person to accept.
        assert db.get_company_invite(tok)["accepted_at"] is None

    def test_accept_email_match_is_case_insensitive(
            self, client, owner_token, other_token, monkeypatch):
        """Invite typed with mixed-case capitals still matches a user
        whose address is stored lower-cased — both sides normalise."""
        import db
        cid, tok = self._new_company_with_invite(
            client, owner_token, monkeypatch,
            invite_email="TeamMate@Studio.com")
        other_user, t_other = other_token
        r = client.post("/v1/companies/invites/accept",
                          json={"invite_token": tok},
                          headers=_hdr(t_other))
        assert r.status_code == 200, r.text
        assert db.get_membership(cid, other_user["id"]) is not None


# ---------------------------------------------------------------------------
# 5. Remove member
# ---------------------------------------------------------------------------
class TestRemoveMember:
    def test_owner_can_remove_member(
            self, client, owner_token, other_token, monkeypatch):
        import db
        _send_calls_recorder(monkeypatch)
        _, t_owner = owner_token
        other_user, _ = other_token
        cid = client.post("/v1/companies",
                            json={"name": "Rem Co", "plan": "studio"},
                            headers=_hdr(t_owner)).json()["id"]
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        assert db.get_membership(cid, other_user["id"]) is not None
        r = client.delete(f"/v1/companies/{cid}/members/{other_user['id']}",
                            headers=_hdr(t_owner))
        assert r.status_code == 200
        assert db.get_membership(cid, other_user["id"]) is None

    def test_owner_cannot_remove_self(self, client, owner_token):
        owner_user, t = owner_token
        cid = client.post("/v1/companies",
                            json={"name": "Self Co", "plan": "studio"},
                            headers=_hdr(t)).json()["id"]
        r = client.delete(f"/v1/companies/{cid}/members/{owner_user['id']}",
                            headers=_hdr(t))
        assert r.status_code == 400

    def test_non_owner_cannot_remove(
            self, client, owner_token, other_token, monkeypatch):
        import db
        _send_calls_recorder(monkeypatch)
        _, t_owner = owner_token
        other_user, t_other = other_token
        cid = client.post("/v1/companies",
                            json={"name": "X Co", "plan": "studio"},
                            headers=_hdr(t_owner)).json()["id"]
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        r = client.delete(f"/v1/companies/{cid}/members/{other_user['id']}",
                            headers=_hdr(t_other))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 6. Switch
# ---------------------------------------------------------------------------
class TestSwitchCompany:
    def test_switch_sets_current_company_id(self, client, owner_token):
        import db
        owner_user, t = owner_token
        cid = client.post("/v1/companies",
                            json={"name": "Sw Co", "plan": "studio"},
                            headers=_hdr(t)).json()["id"]
        r = client.post(f"/v1/companies/{cid}/switch", headers=_hdr(t))
        assert r.status_code == 200
        u = db.get_user(owner_user["id"])
        assert u["current_company_id"] == cid

    def test_switch_to_non_member_company_rejected(
            self, client, owner_token, other_token):
        _, t_owner = owner_token
        _, t_other = other_token
        cid = client.post("/v1/companies",
                            json={"name": "NM Co", "plan": "studio"},
                            headers=_hdr(t_owner)).json()["id"]
        r = client.post(f"/v1/companies/{cid}/switch",
                          headers=_hdr(t_other))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 7. Detail + patch
# ---------------------------------------------------------------------------
class TestDetailAndPatch:
    def test_get_detail_returns_members_and_role(self, client, owner_token):
        _, t = owner_token
        cid = client.post("/v1/companies",
                            json={"name": "Det Co", "plan": "studio"},
                            headers=_hdr(t)).json()["id"]
        r = client.get(f"/v1/companies/{cid}", headers=_hdr(t))
        assert r.status_code == 200
        body = r.json()
        assert body["your_role"] == "owner"
        assert any(m["email"] == "owner@studio.com" for m in body["members"])

    def test_patch_owner_updates_name(self, client, owner_token):
        import db
        _, t = owner_token
        cid = client.post("/v1/companies",
                            json={"name": "Old Name", "plan": "studio"},
                            headers=_hdr(t)).json()["id"]
        r = client.patch(f"/v1/companies/{cid}",
                           json={"name": "New Name"},
                           headers=_hdr(t))
        assert r.status_code == 200
        assert db.get_company(cid)["name"] == "New Name"

    def test_patch_by_non_owner_rejected(
            self, client, owner_token, other_token, monkeypatch):
        import db
        _send_calls_recorder(monkeypatch)
        _, t_owner = owner_token
        other_user, t_other = other_token
        cid = client.post("/v1/companies",
                            json={"name": "P Co", "plan": "studio"},
                            headers=_hdr(t_owner)).json()["id"]
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        r = client.patch(f"/v1/companies/{cid}",
                           json={"name": "Hijacked"}, headers=_hdr(t_other))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Invite acceptance page — GET /invite (roadmap #P0)
# ---------------------------------------------------------------------------
class TestInvitePage:
    def test_invite_page_renders_with_token(self, client):
        r = client.get("/invite?token=abc123XYZ")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # The invite token is injected into the page JS.
        assert 'INVITE = "abc123XYZ"' in r.text
        # The page drives the existing accept API.
        assert "/v1/companies/invites/accept" in r.text

    def test_invite_page_sanitizes_token(self, client):
        # A token carrying HTML/JS metacharacters must not break out of
        # the JS string — only [A-Za-z0-9_-] survive.
        r = client.get('/invite?token=x"><script>alert(1)</script>')
        assert r.status_code == 200
        assert "<script>alert(1)" not in r.text
        assert 'INVITE = "xscriptalert1script"' in r.text

    def test_invite_page_without_token_still_renders(self, client):
        r = client.get("/invite")
        assert r.status_code == 200
        assert 'INVITE = ""' in r.text


# ---------------------------------------------------------------------------
# Owner-transfer flow — POST /v1/companies/{cid}/transfer-ownership (#P1)
# ---------------------------------------------------------------------------
class TestTransferOwnership:
    def _company(self, client, token, name):
        return client.post("/v1/companies",
                            json={"name": name, "plan": "studio"},
                            headers=_hdr(token)).json()["id"]

    def test_owner_transfers_to_member(self, client, owner_token,
                                        other_token):
        import db
        owner_user, t_owner = owner_token
        other_user, _ = other_token
        cid = self._company(client, t_owner, "Transfer Co")
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        r = client.post(f"/v1/companies/{cid}/transfer-ownership",
                         json={"new_owner_user_id": other_user["id"]},
                         headers=_hdr(t_owner))
        assert r.status_code == 200, r.text
        assert r.json()["owner_user_id"] == other_user["id"]
        # New owner promoted; previous owner demoted to admin (not orphaned).
        assert db.get_membership(cid, other_user["id"])["role"] == "owner"
        assert db.get_membership(cid, owner_user["id"])["role"] == "admin"
        # The company row's owner pointer moved too.
        assert db.get_company(cid)["owner_user_id"] == other_user["id"]

    def test_non_owner_cannot_transfer(self, client, owner_token,
                                        other_token):
        import db
        owner_user, t_owner = owner_token
        other_user, t_other = other_token
        cid = self._company(client, t_owner, "Transfer Co 2")
        db.add_company_member(company_id=cid, user_id=other_user["id"],
                              role="member")
        r = client.post(f"/v1/companies/{cid}/transfer-ownership",
                         json={"new_owner_user_id": owner_user["id"]},
                         headers=_hdr(t_other))
        assert r.status_code == 403

    def test_transfer_to_non_member_rejected(self, client, owner_token,
                                              third_token):
        _, t_owner = owner_token
        third_user, _ = third_token
        cid = self._company(client, t_owner, "Transfer Co 3")
        r = client.post(f"/v1/companies/{cid}/transfer-ownership",
                         json={"new_owner_user_id": third_user["id"]},
                         headers=_hdr(t_owner))
        assert r.status_code == 404

    def test_transfer_to_self_rejected(self, client, owner_token):
        owner_user, t_owner = owner_token
        cid = self._company(client, t_owner, "Transfer Co 4")
        r = client.post(f"/v1/companies/{cid}/transfer-ownership",
                         json={"new_owner_user_id": owner_user["id"]},
                         headers=_hdr(t_owner))
        assert r.status_code == 400
