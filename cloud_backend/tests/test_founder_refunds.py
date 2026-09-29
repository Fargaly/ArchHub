"""The founder refunds a payment by clicking twice (Cockpit P4b, 2026-09-29).

A preview returns a single-use confirmation (five minutes, bound to the
founder, the payment and the amount); the confirmation issues exactly one
Stripe refund under an idempotency key derived from it, and both steps are
audited. The cockpit agent can never refund (cockpit_agent withholds it).
Stripe is stubbed here.
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"
OTHER_FOUNDER = "founder@example.test"
PI = "pi_court_1"


class _Stripe:
    api_key = None
    refunds: list = []
    fail = False

    class PaymentIntent:
        @staticmethod
        def retrieve(intent):
            return {"id": intent, "amount_received": 3900, "currency": "usd", "status": "succeeded"}

    class Refund:
        @staticmethod
        def create(**kwargs):
            if _Stripe.fail:
                raise RuntimeError("court: stripe is down")
            _Stripe.refunds.append(kwargs)
            return {"id": "re_%d" % len(_Stripe.refunds), "status": "succeeded",
                    "amount": kwargs["amount"], "currency": "usd"}


@pytest.fixture
def client(monkeypatch):
    import billing
    import config
    from fastapi.testclient import TestClient
    import main
    _Stripe.refunds = []
    _Stripe.fail = False
    monkeypatch.setattr(billing, "stripe", _Stripe)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_court")
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _refund(client, body, who=FOUNDER):
    return client.post("/founder/api/stripe/refund", headers=_auth(who), json=body)


def test_a_preview_then_one_confirmed_refund(client):
    import db
    preview = _refund(client, {"payment_intent": PI, "amount": 1900})
    assert preview.status_code == 200 and preview.json()["needs_confirm"] is True
    assert _Stripe.refunds == []                          # nothing moved yet
    token = preview.json()["confirm_token"]
    done = _refund(client, {"confirm_token": token})
    assert done.status_code == 200 and done.json()["refund"]["amount"] == 1900
    (call,) = _Stripe.refunds
    assert call["payment_intent"] == PI and call["amount"] == 1900
    assert call["idempotency_key"].startswith("archhub-refund-") and token not in call["idempotency_key"]
    again = _refund(client, {"confirm_token": token})
    assert again.status_code == 409 and len(_Stripe.refunds) == 1
    actions = [a["action"] for a in db.recent_founder_actions(50) if a["target"] == PI]
    assert actions[:2] == ["stripe.refund", "stripe.refund.preview"]


def test_a_confirmation_is_bound_to_its_founder_and_expires(client):
    import db
    token = _refund(client, {"payment_intent": PI}).json()["confirm_token"]
    assert _refund(client, {"confirm_token": token}, who=OTHER_FOUNDER).status_code == 409
    with db.connect() as con:
        con.execute("UPDATE refund_confirmations SET expires_at = 0")
    assert _refund(client, {"confirm_token": token}).status_code == 409
    assert _Stripe.refunds == []


def test_the_amount_must_be_real(client):
    assert _refund(client, {"payment_intent": PI, "amount": 0}).status_code == 400
    assert _refund(client, {"payment_intent": PI, "amount": 99999}).status_code == 400
    assert _refund(client, {"payment_intent": "ch_not_an_intent"}).status_code == 400


def test_a_stripe_failure_can_be_retried_once_with_the_same_key(client):
    token = _refund(client, {"payment_intent": PI}).json()["confirm_token"]
    _Stripe.fail = True
    assert _refund(client, {"confirm_token": token}).status_code == 502
    _Stripe.fail = False
    assert _refund(client, {"confirm_token": token}).status_code == 200
    assert len(_Stripe.refunds) == 1 and _Stripe.refunds[0]["amount"] == 3900


def test_the_cockpit_agent_still_cannot_refund():
    import cockpit_agent
    assert not any("refund" in name for name in cockpit_agent.TOOLS)