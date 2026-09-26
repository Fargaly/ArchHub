"""Per-company quota enforcement — v1.3.3.

Solo + trial users have an individual quota on `users.msg_limit`. When
a user joins a company + switches into it (`current_company_id` set),
they share the company-level quota bucket on `companies.msg_limit`.

Tests:
  - quota_remaining_for_actor returns user quota when no company_id
  - quota_remaining_for_actor returns company quota when company_id set
  - increment_usage_for_actor bumps the right bucket
  - Stale company_id falls back to user quota (no lock-out)
  - a plan change re-derives company msg_limit (create + update)
  - billing.py routes company subscription events to the company row
  - Proxy 402 includes `actor` field
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


def _make_company(name: str = "Acme") -> dict:
    """Create a company row directly via db helpers. Returns the row."""
    import db
    u = db.get_or_create_user(f"owner+{uuid.uuid4().hex[:6]}@example.com")
    return db.create_company(
        name=name, owner_user_id=u["id"], plan="studio",
        billing_email=u["email"],
    )


class TestActorResolution:
    def test_remaining_uses_user_quota_when_no_company(self):
        import db
        u = db.get_or_create_user("solo@example.com")
        # Eat 5 messages from the user bucket.
        db.increment_usage(u["id"], 5)
        u = db.get_user_by_email("solo@example.com")
        # actor-aware path should match the raw user path.
        a = db.quota_remaining_for_actor(u)
        b = db.quota_remaining(u["id"])
        assert a == b
        assert a < db.config.PLAN_QUOTAS["trial"]

    def test_remaining_uses_company_quota_when_company_id_set(self):
        import db
        c = _make_company("CompanyA")
        u = db.get_or_create_user("member-a@example.com")
        # Switch the user into the company.
        db.set_current_company(u["id"], c["id"])
        u = db.get_user_by_email("member-a@example.com")
        # Burn some company quota.
        db.increment_usage_for_actor(u, 7)
        remaining = db.quota_remaining_for_actor(u)
        # Studio company shares one bucket = config.PLAN_QUOTAS["studio"].
        # (Model C: this legacy msg bucket is now the fair-use ceiling;
        # hosted billing flows through credit packs. The shared-bucket
        # decrement mechanism is what this guards — read the live number
        # rather than hardcode it so it can't drift from config.)
        assert remaining == db.config.PLAN_QUOTAS["studio"] - 7

    def test_stale_company_id_falls_back_to_user_quota(self):
        import db
        u = db.get_or_create_user("orphan@example.com")
        # Point at a company id that doesn't exist.
        db.set_current_company(u["id"], "company-does-not-exist")
        u = db.get_user_by_email("orphan@example.com")
        # Should NOT lock the user out — fall through to user quota.
        remaining = db.quota_remaining_for_actor(u)
        assert remaining == db.config.PLAN_QUOTAS["trial"]


class TestIncrementUsage:
    def test_increment_company_does_not_touch_user_row(self):
        import db
        c = _make_company("CompanyB")
        u = db.get_or_create_user("member-b@example.com")
        db.set_current_company(u["id"], c["id"])
        u = db.get_user_by_email("member-b@example.com")
        # Bump 10 via actor — should hit company, not user.
        db.increment_usage_for_actor(u, 10)
        u_after = db.get_user_by_email("member-b@example.com")
        assert u_after["msg_used"] == 0   # user bucket untouched
        # Company bucket reflects the bump.
        c_row = db.get_company(c["id"])
        assert c_row["msg_used"] == 10

    def test_increment_user_when_no_company(self):
        import db
        u = db.get_or_create_user("solo-bump@example.com")
        db.increment_usage_for_actor(u, 3)
        u_after = db.get_user_by_email("solo-bump@example.com")
        assert u_after["msg_used"] == 3


class TestCompanyPlanQuotaInvariant:
    """A company's plan ALWAYS implies its msg_limit (config.PLAN_QUOTAS).
    Regression guard for the Firm-tier revenue bug: a Firm company was
    stuck at the 2000 `msg_limit` column default — 99.8% of quota lost —
    because nothing re-derived msg_limit when the plan was set. The
    invariant now lives in db.create_company + db.update_company, so the
    Stripe webhook (which calls update_company) can't leave it stale."""

    def test_create_firm_company_seeds_firm_quota(self):
        import db, config
        u = db.get_or_create_user("firm-create@example.com")
        c = db.create_company(name="FirmCo", owner_user_id=u["id"],
                              plan="firm", billing_email=u["email"])
        assert c["plan"] == "firm"
        assert c["msg_limit"] == config.PLAN_QUOTAS["firm"]   # 1_000_000
        assert c["seat_limit"] == config.PLAN_SEATS["firm"]   # 25

    def test_create_studio_company_seeds_studio_quota(self):
        import db, config
        u = db.get_or_create_user("studio-create@example.com")
        c = db.create_company(name="StudioCo", owner_user_id=u["id"],
                              plan="studio", billing_email=u["email"])
        assert c["msg_limit"] == config.PLAN_QUOTAS["studio"]
        assert c["seat_limit"] == config.PLAN_SEATS["studio"]

    def test_update_to_firm_re_derives_msg_limit(self):
        import db, config
        c = _make_company("UpgradeCo")            # created as studio
        assert c["msg_limit"] == config.PLAN_QUOTAS["studio"]
        # The Studio->Firm upgrade path — billing.py webhook calls this.
        db.update_company(c["id"], plan="firm")
        c_row = db.get_company(c["id"])
        assert c_row["plan"] == "firm"
        assert c_row["msg_limit"] == config.PLAN_QUOTAS["firm"]
        assert c_row["msg_used"] == 0

    def test_update_plan_resets_msg_used(self):
        import db
        c = _make_company("BurnCo")
        with db.connect() as con:
            con.execute("UPDATE companies SET msg_used = 1234 WHERE id = ?",
                        (c["id"],))
        db.update_company(c["id"], plan="firm")
        assert db.get_company(c["id"])["msg_used"] == 0

    def test_update_unknown_plan_falls_back_to_trial(self):
        import db, config
        c = _make_company("WeirdCo")
        db.update_company(c["id"], plan="enterprise")  # not in PLAN_QUOTAS
        row = db.get_company(c["id"])
        assert row["msg_limit"] == config.PLAN_QUOTAS["trial"]

    def test_update_without_plan_leaves_msg_limit_untouched(self):
        import db
        c = _make_company("RenameCo")
        before = db.get_company(c["id"])["msg_limit"]
        db.update_company(c["id"], name="RenameCo v2")
        after = db.get_company(c["id"])
        assert after["name"] == "RenameCo v2"
        assert after["msg_limit"] == before    # no plan change -> untouched


class TestBillingCompanyRouting:
    """billing.py must route company subscription events to the company
    row. Before the fix, customer.subscription.updated / .deleted only
    ever resolved a user — a company's Studio->Firm upgrade or its
    cancellation silently never reached the company quota."""

    def test_company_resolves_from_stripe_customer(self):
        import db, billing
        c = _make_company("StripeCo")
        db.update_company(c["id"], stripe_customer_id="cus_test123")
        resolved = billing._company_from_subscription(
            {"customer": "cus_test123"})
        assert resolved is not None
        assert resolved["id"] == c["id"]

    def test_unknown_customer_resolves_to_none(self):
        import billing
        assert billing._company_from_subscription(
            {"customer": "cus_nope"}) is None
        assert billing._company_from_subscription({}) is None

    def test_tier_from_subscription_maps_price_id(self, monkeypatch):
        import billing, config
        monkeypatch.setitem(config.PLAN_PRICE_IDS, "firm", "price_firm_x")
        obj = {"items": {"data": [{"price": {"id": "price_firm_x"}}]}}
        assert billing._tier_from_subscription(obj) == "firm"

    def test_tier_from_subscription_unknown_price_is_none(self):
        import billing
        obj = {"items": {"data": [{"price": {"id": "price_unknown"}}]}}
        assert billing._tier_from_subscription(obj) is None


class TestProxyActorReporting:
    """402 response should include the actor (user/company) so the
    desktop client can show the right upgrade path."""

    def test_402_envelope_includes_actor_company(self, monkeypatch):
        import db, proxy
        c = _make_company("CompanyE")
        # Force company to zero remaining.
        with db.connect() as con:
            con.execute(
                "UPDATE companies SET msg_limit = 1, msg_used = 1 WHERE id = ?",
                (c["id"],),
            )
        u = db.get_or_create_user("member-e@example.com")
        db.set_current_company(u["id"], c["id"])
        u = db.get_user_by_email("member-e@example.com")

        # Build a tiny async harness — proxy.chat_completions is async.
        import asyncio
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(proxy.chat_completions(user=u, body={"model": "auto"}))
        detail = excinfo.value.detail
        assert detail["error"] == "quota_exhausted"
        assert detail["actor"] == "company"

    def test_402_envelope_includes_actor_user(self, monkeypatch):
        import db, proxy
        u = db.get_or_create_user("burnt@example.com")
        # Burn all trial messages.
        with db.connect() as con:
            con.execute(
                "UPDATE users SET msg_used = msg_limit WHERE id = ?",
                (u["id"],),
            )
        u = db.get_user_by_email("burnt@example.com")
        import asyncio
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(proxy.chat_completions(user=u, body={"model": "auto"}))
        detail = excinfo.value.detail
        assert detail["error"] == "quota_exhausted"
        assert detail["actor"] == "user"
