"""Polar.sh billing-provider tests — v1.3.0.

Polar is the Merchant-of-Record alternative to direct Stripe. Same
surface (create_checkout_url, create_portal_url, handle_webhook), same
DB-write outcome. These tests cover the static contract + the webhook
verification path. No real Polar API calls (mocked urlopen).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
class TestStaticSurface:
    def test_module_imports(self):
        import polar
        assert hasattr(polar, "create_checkout_url")
        assert hasattr(polar, "create_portal_url")
        assert hasattr(polar, "handle_webhook")

    def test_create_checkout_without_token_returns_none(self):
        import polar, config
        with patch.object(config, "POLAR_ACCESS_TOKEN", ""):
            assert polar.create_checkout_url(
                user={"id": "u1", "email": "x@y.z"}, tier="solo",
            ) is None

    def test_create_checkout_unknown_tier_returns_none(self):
        import polar, config
        with patch.object(config, "POLAR_ACCESS_TOKEN", "polar_at_test"), \
             patch.object(config, "POLAR_PRODUCT_IDS",
                            {"solo": "", "studio": "", "firm": ""}):
            assert polar.create_checkout_url(
                user={"id": "u1", "email": "x@y.z"}, tier="enterprise",
            ) is None


class TestCheckoutHappyPath:
    def test_posts_correct_body(self):
        import polar, config
        captured: dict = {}

        def _mock_request(method, path, *, body=None, timeout=30):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {"url": "https://polar.sh/checkout/abc123"}

        with patch.object(config, "POLAR_ACCESS_TOKEN", "polar_at_test"), \
             patch.object(config, "POLAR_PRODUCT_IDS",
                            {"solo": "prod-solo-uuid",
                             "studio": "prod-studio-uuid",
                             "firm": "prod-firm-uuid"}), \
             patch.object(config, "PUBLIC_URL", "https://archhub-cloud.fly.dev"), \
             patch.object(polar, "_request", side_effect=_mock_request):
            url = polar.create_checkout_url(
                user={"id": "u1", "email": "founder@example.com"},
                tier="studio",
            )
        assert url == "https://polar.sh/checkout/abc123"
        assert captured["method"] == "POST"
        assert captured["path"] == "/checkouts/"
        body = captured["body"]
        assert body["product_id"] == "prod-studio-uuid"
        assert body["customer_email"] == "founder@example.com"
        assert body["metadata"]["user_id"] == "u1"
        assert body["metadata"]["tier"] == "studio"
        assert "/billing/success" in body["success_url"]


class TestWebhookSignatureVerification:
    def test_missing_secret_rejects(self):
        import polar, config
        with patch.object(config, "POLAR_WEBHOOK_SECRET", ""):
            assert polar._verify_signature(b"{}", "sha256=anything") is False

    def test_correct_signature_accepts(self):
        import polar, config
        import hmac, hashlib
        secret = "whsec_test_polar"
        payload = b'{"type":"subscription.created"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        with patch.object(config, "POLAR_WEBHOOK_SECRET", secret):
            assert polar._verify_signature(payload, f"sha256={sig}") is True

    def test_tampered_payload_rejects(self):
        import polar, config
        import hmac, hashlib
        secret = "whsec_test_polar"
        payload = b'{"type":"subscription.created"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        with patch.object(config, "POLAR_WEBHOOK_SECRET", secret):
            # Tamper the payload — same signature must fail.
            assert polar._verify_signature(
                b'{"type":"subscription.canceled"}', f"sha256={sig}"
            ) is False


class TestWebhookDispatch:
    def _evt(self, etype, **data):
        return {"type": etype, "data": data}

    def _send(self, evt, secret="whsec_test_polar"):
        import polar, config
        import hmac, hashlib
        payload = json.dumps(evt).encode("utf-8")
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        with patch.object(config, "POLAR_ACCESS_TOKEN", "tok"), \
             patch.object(config, "POLAR_WEBHOOK_SECRET", secret):
            return polar.handle_webhook(
                payload=payload, signature=f"sha256={sig}",
            )

    def test_subscription_created_upgrades_plan(self):
        import db
        u = db.get_or_create_user("polar1@example.com")
        evt = self._evt("subscription.created",
                         metadata={"user_id": u["id"], "tier": "solo"},
                         customer_id="polar_cus_1",
                         current_period_end="2026-12-31T00:00:00Z")
        r = self._send(evt)
        assert r["ok"] is True
        assert r["handled"] == "subscription.created"
        row = db.get_user_by_email("polar1@example.com")
        assert row["plan"] == "solo"
        assert row["stripe_id"] == "polar_cus_1"   # column re-used for polar id
        assert row["msg_used"] == 0  # reset on plan change

    def test_subscription_canceled_downgrades(self):
        import db
        u = db.get_or_create_user("polar2@example.com")
        db.update_user_plan(u["id"], plan="studio")
        evt = self._evt("subscription.canceled",
                         metadata={"user_id": u["id"]},
                         customer_id="polar_cus_2")
        r = self._send(evt)
        assert r["handled"] == "subscription.canceled"
        row = db.get_user_by_email("polar2@example.com")
        assert row["plan"] == "trial"

    def test_unknown_event_ignored_cleanly(self):
        evt = self._evt("checkout.opened",
                         metadata={"user_id": "u1"})
        r = self._send(evt)
        assert r["ok"] is True
        assert r["ignored"] == "checkout.opened"

    def test_bad_signature_rejected(self):
        import polar, config
        payload = b'{"type":"subscription.created"}'
        with patch.object(config, "POLAR_ACCESS_TOKEN", "tok"), \
             patch.object(config, "POLAR_WEBHOOK_SECRET", "whsec_test"):
            r = polar.handle_webhook(
                payload=payload, signature="sha256=wrong",
            )
        assert r["ok"] is False
        assert r["error"] == "bad_signature"


class TestProviderRouting:
    """main.py picks the right provider module via BILLING_PROVIDER env."""

    def test_default_is_stripe(self):
        from main import _billing_provider_module
        import config
        with patch.object(config, "BILLING_PROVIDER", "stripe"):
            mod = _billing_provider_module()
        assert mod.__name__ == "billing"

    def test_polar_selected_when_env_set(self):
        from main import _billing_provider_module
        import config
        with patch.object(config, "BILLING_PROVIDER", "polar"):
            mod = _billing_provider_module()
        assert mod.__name__ == "polar"
