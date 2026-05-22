"""Stripe webhook end-to-end tests.

The webhook is the source of truth for plan upgrades — client-side
"checkout finished" callbacks are never trusted. These tests verify
each event type the handler claims to support actually flips the DB
the way it should.

We don't hit Stripe; the `stripe.Webhook.construct_event` call is
mocked so we can craft fake events without computing real signatures.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
def _event(etype: str, *, user_id: str = "u-test", tier: str = "solo",
            customer: str = "cus_test", subscription: str = "sub_test",
            period_end: int = 1900000000) -> dict:
    """Build a fake stripe event dict matching the shape the handler reads."""
    return {
        "type": etype,
        "data": {
            "object": {
                "id":            "evt_test_" + etype.replace(".", "_"),
                "client_reference_id": user_id,
                "customer":      customer,
                "subscription":  subscription,
                "metadata":      {"user_id": user_id, "tier": tier},
                "current_period_end": period_end,
                "items": {"data": [{"price": {"id": "price_test_solo"}}]},
            }
        }
    }


# ---------------------------------------------------------------------------
class TestCheckoutSessionCompleted:
    def test_flips_plan_and_resets_usage(self):
        import db, billing
        # Seed a trial user.
        u = db.get_or_create_user("test@example.com")
        # Eat some quota so we can verify the reset.
        db.increment_usage(u["id"], 5)
        assert db.quota_remaining(u["id"]) < 30

        evt = _event("checkout.session.completed",
                     user_id=u["id"], tier="solo")
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt), \
             patch("billing.stripe.Subscription.retrieve",
                    return_value={"current_period_end": 1900000000}):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        assert r["ok"] is True
        assert r["handled"] == "checkout.session.completed"

        # Plan upgraded; msg_used reset; stripe_id stored.
        row = db.get_user_by_email("test@example.com")
        assert row["plan"] == "solo"
        assert row["msg_used"] == 0
        assert row["stripe_id"] == "cus_test"
        assert row["msg_limit"] > 30   # solo quota > trial


class TestSubscriptionUpdated:
    def test_recognises_studio_via_price_id(self):
        import db, billing, config
        u = db.get_or_create_user("studio@example.com")
        # Tag a known studio price id so the handler can lookup the tier.
        config.PLAN_PRICE_IDS["studio"] = "price_studio_real"
        evt = _event("customer.subscription.updated", user_id=u["id"])
        evt["data"]["object"]["items"]["data"][0]["price"]["id"] = "price_studio_real"
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        assert r["handled"] == "customer.subscription.updated"
        row = db.get_user_by_email("studio@example.com")
        assert row["plan"] == "studio"


class TestSubscriptionDeleted:
    def test_downgrades_to_trial(self):
        import db, billing
        u = db.get_or_create_user("cancel@example.com")
        db.update_user_plan(u["id"], plan="solo")
        evt = _event("customer.subscription.deleted", user_id=u["id"])
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        assert r["handled"] == "customer.subscription.deleted"
        row = db.get_user_by_email("cancel@example.com")
        assert row["plan"] == "trial"


class TestPaymentFailed:
    def test_logs_no_downgrade(self):
        import db, billing
        u = db.get_or_create_user("late@example.com")
        db.update_user_plan(u["id"], plan="solo")
        evt = _event("invoice.payment_failed", user_id=u["id"])
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        # Plan stays on solo — Stripe retries.
        row = db.get_user_by_email("late@example.com")
        assert row["plan"] == "solo"
        assert r["handled"] == "invoice.payment_failed"


class TestSignatureVerification:
    def test_bad_signature_returns_error(self):
        import billing
        # Don't patch construct_event so the real verify path runs +
        # fails on a fake signature.
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event",
                    side_effect=Exception("Invalid signature")):
            r = billing.handle_webhook(payload=b"{}", signature="wrong")
        assert r["ok"] is False
        assert "bad_signature" in r["error"]

    def test_stripe_not_configured_returns_error(self):
        import billing
        # _ensure_stripe returns False when STRIPE_SECRET_KEY is empty.
        with patch.object(billing, "_ensure_stripe", return_value=False):
            r = billing.handle_webhook(payload=b"{}", signature="any")
        assert r["ok"] is False
        assert r["error"] == "stripe_not_configured"


class TestUnknownEventType:
    def test_unknown_event_returns_ignored(self):
        import billing
        evt = _event("charge.refunded")
        with patch.object(billing, "_ensure_stripe", return_value=True), \
             patch("billing.stripe.Webhook.construct_event", return_value=evt):
            r = billing.handle_webhook(payload=b"{}", signature="sig")
        assert r["ok"] is True
        assert r["ignored"] == "charge.refunded"
