"""Founder-cockpit honesty (2026-06-22) — test/seed account exclusion + purge.

The production users table was polluted by scripts/reality_smoke.py, which
registered `reality+smoketest<ts>@archhub.io` against the LIVE backend on a
30-min cron. The cockpit counted those rows honestly, so users/MRR/signups were
junk. This suite locks the three pieces of the fix:

  (a) the test-account predicate matches the synthetic probe emails but NOT a
      genuine user / founder / staff mailbox;
  (b) the cockpit's REAL counts exclude test accounts AND report the test count
      separately (nothing hidden);
  (c) the purge endpoint is founder-gated, requires an explicit confirm, and
      deletes ONLY the test rows.

Every test runs against the per-test isolated temp DB from conftest._isolate_db
(DATABASE_URL → tmp_path/test.db). The production DB is NEVER touched.
"""
from __future__ import annotations

import base64
import hashlib
import time

import pytest


FOUNDER_EMAIL = "founder@archhub-cockpit-test.com"


# ---------------------------------------------------------------------------
# (a) The predicate
# ---------------------------------------------------------------------------
class TestPredicate:
    def test_matches_the_real_smoke_probe_email(self):
        import db
        # The exact shape scripts/reality_smoke.py used to POST.
        salt = str(int(time.time()))
        assert db.is_test_account_email(
            f"reality+smoketest{salt}@archhub.io") is True
        assert db.is_test_account_email(
            "reality+smoketest1750000000@archhub.io") is True

    @pytest.mark.parametrize("email", [
        "reality+smoketest1@archhub.io",
        "reality+foo@archhub.io",
        "reality+anything@example.com",     # +tag prefix on any domain
        "someone+test@gmail.com",           # +test sub-address
        "user+smoketest@studio.com",        # +smoketest sub-address
        "smoketest42@archhub.io",           # smoketest prefix
        "test+probe@archhub.io",            # test+ prefix
        "REALITY+SmokeTest9@ARCHHUB.IO",    # case-insensitive
    ])
    def test_synthetic_emails_match(self, email):
        import db
        assert db.is_test_account_email(email) is True

    @pytest.mark.parametrize("email", [
        "ahmedfargale@gmail.com",           # the founder — must NOT match
        "ahmed.fargaly98@gmail.com",
        "jane.doe@studio.com",              # a normal customer
        "ahmed@archhub.io",                 # genuine staff @ internal domain
        "support@archhub.io",               # genuine staff
        "info@archhub.io",
        "tester@gmail.com",                 # 'test' substring, no +tag, not internal
        "contest@gmail.com",                # contains 'test' but not a marker
        "",                                 # empty
        None,                               # None
        "no-at-sign",                       # malformed
    ])
    def test_genuine_emails_do_not_match(self, email):
        import db
        assert db.is_test_account_email(email) is False

    def test_sql_fragment_agrees_with_python_predicate(self):
        """The WHERE-clause SQL must classify the SAME rows as the Python
        function — otherwise the cockpit count and the purge would disagree."""
        import db
        sample = [
            "reality+smoketest1@archhub.io",
            "reality+foo@example.com",
            "someone+test@gmail.com",
            "smoketest9@archhub.io",
            "test+x@archhub.io",
            "ahmedfargale@gmail.com",
            "ahmed@archhub.io",
            "support@archhub.io",
            "jane@studio.com",
            "tester@gmail.com",
        ]
        # Seed each as a real user row, then ask SQL which ones are test rows.
        for e in sample:
            db.get_or_create_user(e)
        frag, params = db._test_account_sql()
        with db.connect() as con:
            rows = con.execute(
                f"SELECT email FROM users WHERE {frag}", params).fetchall()
        sql_hits = {r["email"] for r in rows}
        py_hits = {e for e in sample if db.is_test_account_email(e)}
        assert sql_hits == py_hits


# ---------------------------------------------------------------------------
# (b) DAO-level exclusion
# ---------------------------------------------------------------------------
class TestCountHelpersExcludeTest:
    def _seed(self):
        import db
        # 2 real users, 3 synthetic.
        db.get_or_create_user("real.one@studio.com")
        db.get_or_create_user("real.two@studio.com")
        db.get_or_create_user("reality+smoketest1@archhub.io")
        db.get_or_create_user("reality+smoketest2@archhub.io")
        db.get_or_create_user("someone+test@gmail.com")
        return db

    def test_count_users_excludes_test(self):
        db = self._seed()
        assert db.count_users() == 5                  # default: counts all
        assert db.count_users(exclude_test=True) == 2  # real only
        assert db.count_test_users() == 3

    def test_by_plan_excludes_test(self):
        db = self._seed()
        all_bp = db.count_users_by_plan()
        real_bp = db.count_users_by_plan(exclude_test=True)
        # All five are 'trial' on creation.
        assert all_bp.get("trial") == 5
        assert real_bp.get("trial") == 2

    def test_count_since_excludes_test(self):
        db = self._seed()
        # Everything was created "just now"; window = last hour.
        since = int(time.time()) - 3600
        assert db.count_users_since(since) == 5
        assert db.count_users_since(since, exclude_test=True) == 2

    def test_recent_users_excludes_test(self):
        db = self._seed()
        recent = db.recent_users(50, exclude_test=True)
        emails = {u["email"] for u in recent}
        assert emails == {"real.one@studio.com", "real.two@studio.com"}
        assert not any("smoketest" in e for e in emails)

    def test_paid_users_excludes_test(self):
        import config
        db = self._seed()
        # Upgrade one real + (pathologically) one test user to solo.
        real = db.get_user_by_email("real.one@studio.com")
        testu = db.get_user_by_email("reality+smoketest1@archhub.io")
        db.update_user_plan(real["id"], plan="solo")
        db.update_user_plan(testu["id"], plan="solo")
        # Default counts both paid; exclude_test counts only the real one.
        assert db.count_paid_users() == 2
        assert db.count_paid_users(exclude_test=True) == 1

    def test_usage_totals_excludes_test(self):
        db = self._seed()
        real = db.get_user_by_email("real.one@studio.com")
        testu = db.get_user_by_email("reality+smoketest1@archhub.io")
        db.log_usage(real["id"], model="m", input_toks=10, output_toks=5,
                     cost_micros=100)
        db.log_usage(testu["id"], model="m", input_toks=99, output_toks=99,
                     cost_micros=9999)
        all_u = db.usage_totals()
        real_u = db.usage_totals(exclude_test=True)
        assert all_u["chat_completions"] == 2
        assert real_u["chat_completions"] == 1
        assert real_u["cost_micros"] == 100   # the test row's 9999 dropped


# ---------------------------------------------------------------------------
# (b) cockpit panel level
# ---------------------------------------------------------------------------
class TestCockpitPanelExcludesTest:
    def test_users_panel_reports_real_and_test_separately(self):
        import db, founder_cockpit
        db.get_or_create_user("real.one@studio.com")
        db.get_or_create_user("real.two@studio.com")
        for i in range(4):
            db.get_or_create_user(f"reality+smoketest{i}@archhub.io")
        panel = founder_cockpit._users_panel()
        # Headline numbers are REAL (test excluded).
        assert panel["total"] == 2
        assert sum(panel["by_plan"].values()) == 2
        # Test count surfaced separately — nothing hidden.
        assert panel["test_seed"]["count"] == 4
        assert panel["total_incl_test"] == 6
        # Recent list has only real people.
        assert all("smoketest" not in u["email"] for u in panel["recent"])

    def test_overview_total_is_real(self):
        import db, founder_cockpit
        db.get_or_create_user("real@studio.com")
        for i in range(5):
            db.get_or_create_user(f"reality+smoketest{i}@archhub.io")
        ov = founder_cockpit.build_overview()
        assert ov["users"]["total"] == 1
        assert ov["users"]["test_seed"]["count"] == 5


# ---------------------------------------------------------------------------
# (c) the founder-gated purge endpoint
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    import founder_cockpit
    founder_cockpit.clear_errors()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _pkce_pair():
    import secrets
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _sign_in(client, monkeypatch, email) -> str:
    async def fake_send(**kw):
        return True
    import email_sender, db
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    verifier, challenge = _pkce_pair()
    r = client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
    assert r.status_code == 202, r.text
    u = db.get_user_by_email(email)
    with db.connect() as con:
        row = con.execute(
            "SELECT code FROM codes WHERE user_id = ?", (u["id"],)).fetchone()
    r2 = client.post("/v1/auth/exchange",
                     json={"code": row["code"], "code_verifier": verifier})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


PURGE = "/founder/api/purge-test-users"


class TestPurgeEndpointGate:
    def test_unauthenticated_is_403(self, client):
        r = client.post(PURGE, json={"confirm": True})
        assert r.status_code == 403

    def test_garbage_token_is_403(self, client):
        r = client.post(PURGE, json={"confirm": True},
                        headers=_auth("ah_live_not_real"))
        assert r.status_code == 403

    def test_non_founder_is_403_and_deletes_nothing(self, client, monkeypatch):
        import db
        # Seed a test row that must SURVIVE an unauthorised purge attempt.
        db.get_or_create_user("reality+smoketest1@archhub.io")
        token = _sign_in(client, monkeypatch, "someone.else@studio.com")
        # Sanity: token works on a normal route.
        assert client.get("/v1/me", headers=_auth(token)).status_code == 200
        r = client.post(PURGE, json={"confirm": True}, headers=_auth(token))
        assert r.status_code == 403
        # Row still there.
        assert db.count_test_users() == 1


class TestPurgeEndpointConfirm:
    def test_founder_without_confirm_is_dry_run(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        for i in range(3):
            db.get_or_create_user(f"reality+smoketest{i}@archhub.io")
        # No confirm → dry run, deletes nothing.
        r = client.post(PURGE, json={}, headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["would_purge"] == 3
        assert body["purged"] == 0
        assert db.count_test_users() == 3   # untouched

    def test_confirm_false_is_dry_run(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        db.get_or_create_user("reality+smoketest1@archhub.io")
        r = client.post(PURGE, json={"confirm": False}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["dry_run"] is True
        assert db.count_test_users() == 1


class TestPurgeEndpointDeletesOnlyTest:
    def test_confirm_true_deletes_only_test_rows(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        # Real users (incl. the founder who just signed in) must SURVIVE.
        db.get_or_create_user("real.one@studio.com")
        db.get_or_create_user("real.two@studio.com")
        # Synthetic users to be purged.
        for i in range(5):
            db.get_or_create_user(f"reality+smoketest{i}@archhub.io")
        db.get_or_create_user("someone+test@gmail.com")  # 6 total test

        before_real = db.count_users(exclude_test=True)
        assert db.count_test_users() == 6

        r = client.post(PURGE, json={"confirm": True}, headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is False
        assert body["purged"] == 6
        assert body["remaining_test"] == 0

        # Real users untouched (founder + the two studio users).
        assert db.count_test_users() == 0
        assert db.count_users(exclude_test=True) == before_real
        assert db.get_user_by_email("real.one@studio.com") is not None
        assert db.get_user_by_email(FOUNDER_EMAIL) is not None
        # The synthetic ones are gone.
        assert db.get_user_by_email("reality+smoketest0@archhub.io") is None

    def test_purge_also_clears_dependent_rows(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        testu = db.get_or_create_user("reality+smoketest1@archhub.io")
        db.log_usage(testu["id"], model="m", input_toks=1, output_toks=1,
                     cost_micros=1)
        # Give it a token too, to prove dependent cleanup.
        db.issue_token(testu["id"])
        r = client.post(PURGE, json={"confirm": True}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["purged"] == 1
        with db.connect() as con:
            usage = con.execute(
                "SELECT COUNT(*) AS n FROM usage_log WHERE user_id = ?",
                (testu["id"],)).fetchone()["n"]
            toks = con.execute(
                "SELECT COUNT(*) AS n FROM tokens WHERE user_id = ?",
                (testu["id"],)).fetchone()["n"]
        assert usage == 0
        assert toks == 0

    def test_purge_on_clean_db_returns_zero(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        db.get_or_create_user("real.only@studio.com")
        r = client.post(PURGE, json={"confirm": True}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["purged"] == 0
