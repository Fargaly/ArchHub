"""User-profile fields — tests for the ALTER columns + DAO helpers.

Covers:
  1. Register endpoint stores profile fields when present
  2. update_user_profile only writes whitelisted fields (no SQL through
     unknown keys)
  3. get_user_with_profile returns the joined row including new cols
"""
from __future__ import annotations

import base64
import hashlib
import secrets

import pytest


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


class TestRegisterWithProfile:
    def test_register_writes_profile_fields(self, client, monkeypatch):
        async def fake_send(**kw):
            return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        _, challenge = _pkce_pair()
        r = client.post("/v1/auth/register", json={
            "email": "prof@studio.com",
            "code_challenge": challenge,
            "full_name": "Ada Architect",
            "firm_name": "Ada Studio",
            "aec_role": "Architect",
            "aec_discipline": "Architectural",
            "firm_size": "2-10",
            "country": "GB",
            "signup_source": "twitter",
            "landing_variant": "B",
        })
        assert r.status_code == 202
        u = db.get_user_by_email("prof@studio.com")
        assert u["full_name"] == "Ada Architect"
        assert u["firm_name"] == "Ada Studio"
        assert u["aec_role"] == "Architect"
        assert u["aec_discipline"] == "Architectural"
        assert u["firm_size"] == "2-10"
        assert u["country"] == "GB"
        assert u["signup_source"] == "twitter"
        assert u["landing_variant"] == "B"

    def test_register_without_profile_still_works(self, client, monkeypatch):
        """Magic-link sign-in must not require profile fields."""
        async def fake_send(**kw):
            return True
        import email_sender, db
        monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
        _, challenge = _pkce_pair()
        r = client.post("/v1/auth/register", json={
            "email": "bare@studio.com",
            "code_challenge": challenge,
        })
        assert r.status_code == 202
        u = db.get_user_by_email("bare@studio.com")
        assert u is not None
        assert u["full_name"] is None
        assert u["firm_name"] is None


class TestUpdateUserProfileWhitelist:
    def test_unknown_keys_silently_dropped(self):
        """The whitelist prevents an attacker setting is_admin=1 via the
        profile-update path."""
        import db
        u = db.get_or_create_user("wl@studio.com")
        # Try to flip is_admin via the profile updater — should be a no-op.
        db.update_user_profile(u["id"], is_admin=1)
        after = db.get_user(u["id"])
        assert int(after.get("is_admin") or 0) == 0

    def test_sql_keyword_in_key_does_not_inject(self):
        """An attacker-controlled key like "name; DROP TABLE users" must
        not reach the SQL builder — whitelist drops it before format."""
        import db
        u = db.get_or_create_user("inject@studio.com")
        # Without the whitelist, this would crash or worse. With it,
        # the key is silently dropped.
        db.update_user_profile(
            u["id"],
            **{"full_name; DROP TABLE users; --": "x"},
        )
        # Table still exists + row still readable.
        after = db.get_user(u["id"])
        assert after is not None
        assert after["email"] == "inject@studio.com"

    def test_none_values_skipped_not_blanking(self):
        """Passing key=None should NOT overwrite a previously-set value."""
        import db
        u = db.get_or_create_user("blank@studio.com")
        db.update_user_profile(u["id"], full_name="Alice")
        db.update_user_profile(u["id"], full_name=None,
                                firm_name="New Firm")
        after = db.get_user(u["id"])
        assert after["full_name"] == "Alice"
        assert after["firm_name"] == "New Firm"

    def test_whitelisted_keys_written(self):
        import db
        u = db.get_or_create_user("ok@studio.com")
        db.update_user_profile(u["id"],
                                full_name="Bob",
                                firm_name="Bob & Co",
                                country="US")
        after = db.get_user(u["id"])
        assert after["full_name"] == "Bob"
        assert after["firm_name"] == "Bob & Co"
        assert after["country"] == "US"


class TestGetUserWithProfile:
    def test_returns_joined_row(self):
        import db
        u = db.get_or_create_user("gw@studio.com")
        db.update_user_profile(u["id"], full_name="Joined",
                                aec_role="BIM Manager")
        out = db.get_user_with_profile(u["id"])
        assert out is not None
        assert out["email"] == "gw@studio.com"
        assert out["full_name"] == "Joined"
        assert out["aec_role"] == "BIM Manager"
        # Quota fields stay accessible — same row.
        assert "msg_limit" in out
        assert "plan" in out

    def test_unknown_user_returns_none(self):
        import db
        assert db.get_user_with_profile("u_does_not_exist") is None
