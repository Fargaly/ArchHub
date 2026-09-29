"""The founder sees the money: live Stripe and every failed payment or refund (Cockpit P4a, 2026-09-29).

MRR used to be an estimate from stored plans times list prices, invoices were
not shown, a failed payment was one server log line and a refund was ignored.
Now: active subscriptions and MRR from their real prices, recent invoices, and
the failures and refunds the webhook records. The Stripe key never leaves the
server. Stripe itself is stubbed here.
"""
from __future__ import annotations

import json

import pytest

FOUNDER = "founder.desktop@example.test"
KEY = "sk_test_court_secret"


class _Stripe:
    api_key = None

    class Subscription:
        @staticmethod
        def list(**_kwargs):
            return {"has_more": False, "data": [
                {"currency": "usd", "items": {"data": [{"quantity": 1, "price": {
                    "unit_amount": 1900, "recurring": {"interval": "month", "interval_count": 1}}}]}},
                {"currency": "usd", "items": {"data": [{"quantity": 2, "price": {
                    "unit_amount": 39000, "recurring": {"interval": "year", "interval_count": 1}}}]}},
            ]}

    class Invoice:
        @staticmethod
        def list(**_kwargs):
            return {"data": [{"id": "in_1", "customer_email": "payer@studio.example",
                              "amount_paid": 1900, "amount_due": 1900, "currency": "usd",
                              "status": "paid", "created": 1790000000,
                              "hosted_invoice_url": "https://pay.example/in_1"}]}

    class Webhook:
        @staticmethod
        def construct_event(payload, _signature, _secret):
            return json.loads(payload)


@pytest.fixture
def client(monkeypatch):
    import billing
    import config
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(billing, "stripe", _Stripe)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", KEY)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_court")
    getattr(billing, "_STRIPE_VIEW", {}).clear()
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _payments(client):
    answer = client.get("/founder/api/stripe", headers=_auth(FOUNDER))
    assert answer.status_code == 200, answer.text
    return answer


def test_live_subscriptions_mrr_and_invoices(client):
    answer = _payments(client)
    live = answer.json()["live"]
    assert live["available"] is True and live["active_subscriptions"] == 2
    assert live["mrr_minor"] == {"usd": 1900 + 6500}        # 2 x 390.00/yr = 65.00/mo
    assert [invoice["id"] for invoice in live["invoices"]] == ["in_1"]
    assert "hosted_invoice_url" not in live["invoices"][0]
    assert KEY not in answer.text


def test_without_stripe_it_says_so(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "")
    assert _payments(client).json()["live"] == {
        "available": False, "reason": "Stripe is not configured on this server"}


def test_failed_payments_and_refunds_are_recorded_and_shown(client):
    import db
    payer = db.get_or_create_user("payer@studio.example")
    for event in (
        {"type": "invoice.payment_failed", "data": {"object": {
            "id": "in_9", "amount_due": 3900, "currency": "usd", "attempt_count": 2,
            "metadata": {"user_id": payer["id"]}}}},
        {"type": "charge.refunded", "data": {"object": {
            "id": "ch_1", "amount_refunded": 1900, "currency": "usd", "payment_intent": "pi_1",
            "metadata": {"user_id": payer["id"]}}}},
    ):
        r = client.post("/v1/webhooks/stripe", content=json.dumps(event),
                        headers={"stripe-signature": "court"})
        assert r.status_code == 200, r.text
    body = _payments(client).json()
    (failed,) = body["failed_payments"]
    assert (failed["email"], failed["stripe_object"], failed["amount"], failed["detail"]) == (
        "payer@studio.example", "in_9", 3900, "attempt 2")
    (refund,) = body["refunds"]
    assert (refund["stripe_object"], refund["amount"], refund["detail"]) == ("ch_1", 1900, "pi_1")