"""Model C pricing — the founder-approved hybrid (2026-05-31).

Spec: docs/prototypes/pricing-model-C-hybrid-2026-05-31.html

Each test below proves ONE rule of Model C so a regression names exactly
which rule broke:

  • tier prices — Solo $19, Studio $39/seat, Firm $29/seat
  • per-seat checkout quantity = seat count
  • Firm minimum 10 seats (clamped at checkout + seat change)
  • annual billing = −20% on every tier
  • hosted metering: each message decrements a credit; 402 honest
    "out of credits" at zero
  • byo_key mode = NO hosted limit (the user's key carries it)
  • à-la-carte seats = subscription quantity update (Stripe prorates)
  • credit pack = $10 → 1,000 messages, granted on payment, rolling
    over 60 days then expiring

Stripe is mocked everywhere — we never hit the network. The mocks
assert the SHAPE we send Stripe (quantity, price id, mode, metadata).
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user(email: str | None = None, plan: str = "trial"):
    import db
    email = email or f"u+{uuid.uuid4().hex[:8]}@example.com"
    u = db.get_or_create_user(email)
    if plan != "trial":
        db.update_user_plan(u["id"], plan=plan)
        u = db.get_user_by_email(email)
    return u


def _company(plan: str = "studio"):
    import db
    owner = _user()
    return db.create_company(name=f"Co-{uuid.uuid4().hex[:6]}",
                             owner_user_id=owner["id"], plan=plan,
                             billing_email=owner["email"])


# ═══════════════════════════════════════════════════════════════════════
#  Rule 1 — tier prices
# ═══════════════════════════════════════════════════════════════════════
class TestTierPrices:
    def test_solo_is_19_one_seat(self):
        import config
        p = config.PLANS["solo"]
        assert p["price_per_seat"] == 19
        assert p["min_seats"] == 1 and p["max_seats"] == 1

    def test_studio_is_39_per_seat(self):
        import config
        p = config.PLANS["studio"]
        assert p["price_per_seat"] == 39
        assert p["is_company"] is True

    def test_firm_is_29_per_seat(self):
        import config
        assert config.PLANS["firm"]["price_per_seat"] == 29

    def test_public_pricing_carries_model_c_numbers(self):
        import config
        pp = config.public_pricing()
        assert pp["model"] == "C"
        by = {t["id"]: t for t in pp["tiers"]}
        assert by["solo"]["price_per_seat"] == 19
        assert by["studio"]["price_per_seat"] == 39
        assert by["firm"]["price_per_seat"] == 29


# ═══════════════════════════════════════════════════════════════════════
#  Rule 2 — annual billing = −20% on every tier
# ═══════════════════════════════════════════════════════════════════════
class TestAnnualDiscount:
    def test_discount_is_20pct(self):
        import config
        assert config.ANNUAL_DISCOUNT == 0.20

    def test_annual_per_seat_is_80pct_of_monthly(self):
        import config
        for tier in ("solo", "studio", "firm"):
            monthly = config.PLANS[tier]["price_per_seat"]
            assert config.annual_price_per_seat(tier) == round(monthly * 0.8, 2)
        # Concrete: Studio $39 → $31.20/seat/mo on annual.
        assert config.annual_price_per_seat("studio") == 31.20
        assert config.annual_price_per_seat("firm") == 23.20
        assert config.annual_price_per_seat("solo") == 15.20

    def test_annual_total_is_twelve_months(self):
        import config
        # Studio annual = $31.20 × 12 = $374.40 per seat per year.
        assert config.annual_total_per_seat("studio") == 374.40


# ═══════════════════════════════════════════════════════════════════════
#  Rule 3 — seat floors: per-seat quantity, Firm min 10, Solo pinned at 1
# ═══════════════════════════════════════════════════════════════════════
class TestSeatClamping:
    def test_firm_clamps_up_to_10(self):
        import config
        assert config.clamp_seats("firm", 1) == 10
        assert config.clamp_seats("firm", 9) == 10
        assert config.clamp_seats("firm", 25) == 25   # above min stays

    def test_solo_pinned_to_one(self):
        import config
        assert config.clamp_seats("solo", 5) == 1
        assert config.clamp_seats("solo", 1) == 1

    def test_studio_is_a_la_carte_min_one(self):
        import config
        assert config.clamp_seats("studio", 1) == 1
        assert config.clamp_seats("studio", 7) == 7


class TestCheckoutQuantity:
    """Per-seat subscription: quantity = seat count, clamped to the tier
    floor. Mocked Stripe asserts the quantity we send."""

    def _capture_session(self):
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            s = MagicMock()
            s.url = "https://checkout.stripe.test/session"
            return s

        return captured, fake_create

    def test_studio_checkout_sends_quantity(self):
        import billing, config
        c = _company("studio")
        captured, fake = self._capture_session()
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch.object(config, "STRIPE_PRICE_STUDIO", "price_studio_m"), \
             patch.dict(config.PLANS["studio"], {"price_id": "price_studio_m"}), \
             patch("billing.stripe.checkout.Session.create", side_effect=fake):
            url = billing.create_company_checkout(
                company_id=c["id"], plan="studio", seats=4)
        assert url
        item = captured["line_items"][0]
        assert item["price"] == "price_studio_m"
        assert item["quantity"] == 4          # à-la-carte seat count
        assert captured["mode"] == "subscription"

    def test_firm_checkout_clamps_quantity_to_10(self):
        import billing, config
        c = _company("firm")
        captured, fake = self._capture_session()
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch.dict(config.PLANS["firm"], {"price_id": "price_firm_m"}), \
             patch("billing.stripe.checkout.Session.create", side_effect=fake):
            # Ask for 3 — Firm floor is 10, so Stripe must see 10.
            billing.create_company_checkout(
                company_id=c["id"], plan="firm", seats=3)
        assert captured["line_items"][0]["quantity"] == 10

    def test_solo_checkout_quantity_is_one(self):
        import billing, config
        u = _user(plan="trial")
        captured, fake = self._capture_session()
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch.dict(config.PLANS["solo"], {"price_id": "price_solo_m"}), \
             patch("billing.stripe.checkout.Session.create", side_effect=fake):
            billing.create_checkout_url(user=u, tier="solo")
        assert captured["line_items"][0]["quantity"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Rule 4 — annual checkout selects the −20% price id
# ═══════════════════════════════════════════════════════════════════════
class TestAnnualCheckoutPriceId:
    def test_annual_uses_annual_price_id(self):
        import billing, config
        c = _company("studio")
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            s = MagicMock(); s.url = "u"; return s

        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch.dict(config.PLANS["studio"],
                        {"price_id": "price_m", "price_id_annual": "price_a"}), \
             patch("billing.stripe.checkout.Session.create", side_effect=fake_create):
            billing.create_company_checkout(company_id=c["id"], plan="studio",
                                            seats=2, annual=True)
        assert captured["line_items"][0]["price"] == "price_a"
        assert captured["metadata"]["cadence"] == "annual"

    def test_monthly_uses_monthly_price_id(self):
        import config
        assert config.stripe_price_id("studio", annual=False) == config.PLANS["studio"]["price_id"]
        assert config.stripe_price_id("studio", annual=True) == config.PLANS["studio"]["price_id_annual"]


# ═══════════════════════════════════════════════════════════════════════
#  Rule 5 — à-la-carte seats = subscription quantity update (prorated)
# ═══════════════════════════════════════════════════════════════════════
class TestSeatProration:
    def test_update_quantity_calls_stripe_modify_with_proration(self):
        import billing, config
        modify_args = {}

        sub = {"items": {"data": [{"id": "si_123",
                                   "price": {"id": "price_studio_m"},
                                   "quantity": 5}]}}

        def fake_modify(sub_id, **kwargs):
            modify_args["sub_id"] = sub_id
            modify_args.update(kwargs)
            return MagicMock()

        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Subscription.retrieve", return_value=sub), \
             patch("billing.stripe.Subscription.modify", side_effect=fake_modify):
            res = billing.update_subscription_quantity(
                subscription_id="sub_x", plan="studio", seats=8)
        assert res["ok"] is True
        assert res["seats"] == 8
        # The proration is what makes "add/remove anytime" honest.
        assert modify_args["proration_behavior"] == "create_prorations"
        assert modify_args["items"][0]["id"] == "si_123"
        assert modify_args["items"][0]["quantity"] == 8

    def test_firm_seat_change_clamps_to_10(self):
        import billing
        modify_args = {}
        sub = {"items": {"data": [{"id": "si_f", "quantity": 12}]}}

        def fake_modify(sub_id, **kwargs):
            modify_args.update(kwargs)
            return MagicMock()

        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Subscription.retrieve", return_value=sub), \
             patch("billing.stripe.Subscription.modify", side_effect=fake_modify):
            res = billing.update_subscription_quantity(
                subscription_id="sub_f", plan="firm", seats=4)
        # Firm can't drop below 10 even via à-la-carte removal.
        assert res["seats"] == 10
        assert modify_args["items"][0]["quantity"] == 10

    def test_seats_endpoint_updates_company_and_subscription(self):
        """The /v1/companies/{id}/seats endpoint, end to end (mocked
        Stripe): clamps, updates the subscription quantity, and writes
        the company seat_limit."""
        import db, companies
        from fastapi import Header
        c = _company("studio")
        db.update_company(c["id"], stripe_subscription_id="sub_live")
        owner_id = c["owner_user_id"]
        token = db.issue_token(owner_id)

        with patch("companies.billing.update_subscription_quantity",
                   return_value={"ok": True, "seats": 9}) as m:
            from companies import set_company_seats, SeatsReq
            res = set_company_seats(c["id"], SeatsReq(seats=9),
                                    authorization=f"Bearer {token}")
        assert res["seat_limit"] == 9
        m.assert_called_once()
        assert db.get_company(c["id"])["seat_limit"] == 9


# ═══════════════════════════════════════════════════════════════════════
#  Rule 6 — hosted credit packs: $10 = 1,000 msgs, grant + 60-day rollover
# ═══════════════════════════════════════════════════════════════════════
class TestCreditPackTerms:
    def test_pack_is_10_dollars_1000_messages_60_days(self):
        import config
        assert config.CREDIT_PACK["price_usd"] == 10
        assert config.CREDIT_PACK["messages"] == 1000
        assert config.CREDIT_PACK["rollover_days"] == 60


class TestCreditGrant:
    def test_grant_credits_sets_balance(self):
        import db
        u = _user()
        r = db.grant_credits(messages=1000, user_id=u["id"])
        assert r["granted"] is True
        assert r["balance"] == 1000
        assert db.credit_balance(user_id=u["id"]) == 1000

    def test_grant_expires_after_rollover_days(self):
        import db, config
        u = _user()
        now = 1_000_000
        db.grant_credits(messages=1000, user_id=u["id"], now=now)
        # Just before expiry: still counted.
        almost = now + config.CREDIT_PACK["rollover_days"] * 86400 - 1
        assert db.credit_balance(user_id=u["id"], now=almost) == 1000
        # One second after the 60-day window: lapsed to 0.
        after = now + config.CREDIT_PACK["rollover_days"] * 86400 + 1
        assert db.credit_balance(user_id=u["id"], now=after) == 0

    def test_grant_is_idempotent_on_event_id(self):
        import db
        u = _user()
        db.grant_credits(messages=1000, user_id=u["id"], stripe_event_id="evt_1")
        dup = db.grant_credits(messages=1000, user_id=u["id"], stripe_event_id="evt_1")
        assert dup["granted"] is False           # replay didn't double-credit
        assert db.credit_balance(user_id=u["id"]) == 1000

    def test_rollover_two_packs_stack(self):
        import db
        u = _user()
        db.grant_credits(messages=1000, user_id=u["id"])
        db.grant_credits(messages=1000, user_id=u["id"])
        assert db.credit_balance(user_id=u["id"]) == 2000


class TestCreditPackCheckout:
    def test_checkout_is_one_time_payment_with_metadata(self):
        import billing, config
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            s = MagicMock(); s.url = "https://pay.test"; return s

        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch.object(config, "STRIPE_PRICE_CREDIT_PACK", "price_pack"), \
             patch("billing.stripe.checkout.Session.create", side_effect=fake_create):
            url = billing.create_credit_pack_checkout(company_id="co_abc")
        assert url == "https://pay.test"
        assert captured["mode"] == "payment"            # NOT subscription
        assert captured["line_items"][0]["price"] == "price_pack"
        assert captured["metadata"]["kind"] == "credit_pack"
        assert captured["metadata"]["company_id"] == "co_abc"

    def test_webhook_credit_pack_grants_messages(self):
        import db, billing, config
        c = _company("studio")
        evt = {
            "id": "evt_pack_1",
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_1",
                "metadata": {"kind": "credit_pack",
                             "company_id": c["id"],
                             "messages": str(config.CREDIT_PACK["messages"])},
            }},
        }
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        assert r["handled"] == "checkout.session.completed"
        assert r["kind"] == "credit_pack"
        assert r["granted"] is True
        assert db.credit_balance(company_id=c["id"]) == 1000
        # Plan/seat are untouched — a pack is not a subscription change.
        assert db.get_company(c["id"])["plan"] == "studio"

    def test_webhook_credit_pack_idempotent_on_replay(self):
        import db, billing, config
        c = _company("studio")
        evt = {
            "id": "evt_pack_dup",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_2", "metadata": {
                "kind": "credit_pack", "company_id": c["id"],
                "messages": "1000"}}},
        }
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            billing.handle_webhook(payload=b"{}", signature="sig")
            billing.handle_webhook(payload=b"{}", signature="sig")   # replay
        assert db.credit_balance(company_id=c["id"]) == 1000   # not 2000


# ═══════════════════════════════════════════════════════════════════════
#  Rule 7 — AI mode + hosted metering (the key flexibility)
# ═══════════════════════════════════════════════════════════════════════
class TestAiMode:
    def test_default_is_byo_key(self):
        import config
        assert config.DEFAULT_AI_MODE == "byo_key"
        assert set(config.AI_MODES) == {"byo_key", "hosted"}

    def test_company_starts_byo_key(self):
        import db
        c = _company("studio")
        assert db.ai_mode_for_actor(_member_in(c)) == "byo_key"

    def test_toggle_to_hosted(self):
        import db
        c = _company("studio")
        db.set_company_ai_mode(c["id"], "hosted")
        assert db.ai_mode_for_actor(_member_in(c)) == "hosted"


def _member_in(company):
    """A user operating under `company` (current_company_id set)."""
    import db
    u = _user()
    db.set_current_company(u["id"], company["id"])
    return db.get_user(u["id"])


class TestHostedMetering:
    """hosted mode: each delivered turn decrements a credit; at 0 the
    proxy returns an honest 402 out_of_credits."""

    def _run(self, user):
        import asyncio, proxy
        return asyncio.run(proxy.chat_completions(user=user, body={"model": "auto"}))

    def test_byo_key_never_hits_credit_limit(self, monkeypatch):
        """byo_key workspace with ZERO credits is NOT blocked by credits —
        it's told to use its own key (byo_key_required), never
        out_of_credits. The user's key carries inference."""
        import db, proxy
        from fastapi import HTTPException
        monkeypatch.setattr("config.PROXY_LIVE", True)
        # Isolate the byo branch from the zero-config FREE DEFAULT (#64), which
        # legitimately supersedes byo_key_required when a free-provider key is
        # present in the runner's env. Free-default behaviour is covered
        # elsewhere (test_free_default.py).
        monkeypatch.setattr("config.free_default_available", lambda: False)
        u = _user(plan="studio")            # byo_key by default, 0 credits
        assert db.credit_balance(user_id=u["id"]) == 0
        with pytest.raises(HTTPException) as exc:
            self._run(u)
        assert exc.value.status_code == 402
        assert exc.value.detail["error"] == "byo_key_required"
        assert exc.value.detail["ai_mode"] == "byo_key"

    def test_hosted_zero_credits_returns_402_out_of_credits(self, monkeypatch):
        import db, proxy
        from fastapi import HTTPException
        monkeypatch.setattr("config.PROXY_LIVE", True)
        u = _user(plan="studio")
        db.set_user_ai_mode(u["id"], "hosted")     # switch to hosted, still 0
        u = db.get_user(u["id"])
        with pytest.raises(HTTPException) as exc:
            self._run(u)
        assert exc.value.status_code == 402
        assert exc.value.detail["error"] == "out_of_credits"
        assert exc.value.detail["credit_balance"] == 0
        # The 402 prompts a top-up with the real pack terms.
        assert exc.value.detail["credit_pack"]["messages"] == 1000

    def test_hosted_with_credits_decrements_one_per_message(self, monkeypatch):
        """A full streamed turn in hosted mode spends exactly one credit.
        We stub the upstream generator so no network is touched."""
        import db, proxy
        monkeypatch.setattr("config.PROXY_LIVE", True)
        monkeypatch.setattr("config.ANTHROPIC_API_KEY", "sk-test")
        u = _user(plan="studio")
        db.set_user_ai_mode(u["id"], "hosted")
        db.grant_credits(messages=1000, user_id=u["id"])
        u = db.get_user(u["id"])

        async def fake_stream(model, body):
            yield b"data: {\"choices\":[]}\n\n"
            yield b"data: [DONE]\n\n"

        import asyncio
        async def drive():
            with patch.object(proxy, "_stream_anthropic", side_effect=fake_stream):
                resp = await proxy.chat_completions(
                    user=u, body={"model": "claude-sonnet-4-6"})
                # Consume the streaming body so the end-of-stream meter runs.
                async for _ in resp.body_iterator:
                    pass
        asyncio.run(drive())
        # One message delivered → one credit gone.
        assert db.credit_balance(user_id=u["id"]) == 999

    def test_hosted_blocked_when_proxy_off(self, monkeypatch):
        """Dev-budget guard: hosted mode + credits but PROXY_LIVE=0 → the
        proxy refuses (hosted_unavailable) so accidental traffic can't
        burn the founder's prepaid balance before launch."""
        import db, proxy
        from fastapi import HTTPException
        monkeypatch.setattr("config.PROXY_LIVE", False)
        u = _user(plan="studio")
        db.set_user_ai_mode(u["id"], "hosted")
        db.grant_credits(messages=1000, user_id=u["id"])
        u = db.get_user(u["id"])
        with pytest.raises(HTTPException) as exc:
            self._run(u)
        assert exc.value.detail["error"] == "hosted_unavailable"
