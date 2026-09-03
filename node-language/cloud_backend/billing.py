"""Stripe billing — Checkout sessions + Customer Portal + webhook.

Model C (founder 2026-05-31). Three per-seat tiers (Solo / Studio /
Firm) map to monthly + annual (−20%) Stripe price ids set via env. A
subscription's `quantity` IS the seat count:

  • Solo   — exactly 1 seat (fixed).
  • Studio — quantity = seats, à la carte (min 1).
  • Firm   — quantity = seats, minimum 10 (volume per-seat).

Seats are added/removed by updating the subscription quantity
(`update_subscription_quantity`); Stripe prorates automatically.

Hosted-AI credit packs ($10 = 1,000 messages) are a SEPARATE one-time
Checkout (`create_credit_pack_checkout`, mode="payment"). On
`checkout.session.completed` with kind=credit_pack the webhook grants
the messages to the workspace (db.grant_credits, 60-day rollover).

The webhook is the source of truth — never trust client-side
"checkout finished" callbacks for plan upgrades or credit grants.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    import stripe  # type: ignore
except Exception:
    stripe = None  # noqa: N816

import config
import db


def _ensure_stripe() -> bool:
    if stripe is None:
        return False
    if not config.STRIPE_SECRET_KEY:
        return False
    stripe.api_key = config.STRIPE_SECRET_KEY
    return True


def create_checkout_url(*, user: dict, tier: str,
                        annual: bool = False) -> Optional[str]:
    """Build a Stripe Checkout session for the given plan tier and
    return its `url`. None on misconfig / invalid tier.

    This is the per-USER path — used by Solo (a fixed single seat).
    Studio/Firm bill per-seat through the company checkout. `annual`
    selects the −20% price id.
    """
    if not _ensure_stripe():
        return None
    price = config.stripe_price_id(tier, annual=annual)
    if not price:
        return None
    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=user.get("stripe_id") or None,
            customer_email=(None if user.get("stripe_id")
                            else user["email"]),
            # Solo = exactly 1 seat (config.clamp_seats enforces it).
            line_items=[{"price": price,
                         "quantity": config.clamp_seats(tier, 1)}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=user["id"],
            allow_promotion_codes=True,
            metadata={"user_id": user["id"], "tier": tier,
                      "cadence": "annual" if annual else "monthly"},
        )
    except Exception as ex:
        # Surface as None; the route returns 503.
        print(f"[stripe] checkout.create failed: {ex}", flush=True)
        return None
    return session.url


def create_company_checkout(*, company_id: str, plan: str,
                              billing_email: Optional[str] = None,
                              seats: Optional[int] = None,
                              annual: bool = False,
                              ) -> Optional[str]:
    """Stripe Checkout for a per-seat company plan (Model C).

    `quantity` = the seat count, clamped to the tier's floor/ceiling via
    config.clamp_seats — so a Firm checkout can never start below 10
    seats and the per-seat price the customer sees is honest. `annual`
    selects the −20% price id. Metadata carries `company_id` so the
    webhook routes the resulting subscription back to the correct row.
    """
    if not _ensure_stripe():
        return None
    price = config.stripe_price_id(plan, annual=annual)
    if not price:
        return None
    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"
    # Seat count: caller's request (or the tier minimum), clamped to the
    # tier's [min_seats, max_seats]. Firm's 10-seat floor lives in
    # config.clamp_seats — one rule, shared by checkout + seat changes.
    requested = seats if seats is not None else config.PLAN_SEATS.get(plan, 1)
    qty = config.clamp_seats(plan, int(requested))
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=billing_email or None,
            line_items=[{"price": price, "quantity": qty}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=company_id,
            allow_promotion_codes=True,
            metadata={"company_id": company_id, "tier": plan,
                      "kind": "company", "seats": str(qty),
                      "cadence": "annual" if annual else "monthly"},
        )
    except Exception as ex:
        print(f"[stripe] company checkout.create failed: {ex}",
              flush=True)
        return None
    return session.url


def update_subscription_quantity(*, subscription_id: str, plan: str,
                                  seats: int) -> dict:
    """À-la-carte seats — set a live subscription's seat quantity.

    Stripe prorates the change automatically (proration_behavior=
    'create_prorations'). `seats` is clamped to the tier's
    [min_seats, max_seats] (Firm can't drop below 10, Solo can't exceed
    1) so the floor is enforced on every seat change, not just checkout.

    Returns {ok, seats} on success, {ok: False, error} otherwise. The
    subscription's single line item is updated in place (we read its
    current item id, then set the new quantity on it).
    """
    if not _ensure_stripe():
        return {"ok": False, "error": "stripe_not_configured"}
    qty = config.clamp_seats(plan, int(seats))
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "quantity": qty}],
            proration_behavior="create_prorations",
        )
    except Exception as ex:
        print(f"[stripe] subscription.modify quantity failed: {ex}",
              flush=True)
        return {"ok": False, "error": "quantity_update_failed"}
    return {"ok": True, "seats": qty}


def create_credit_pack_checkout(*, company_id: Optional[str] = None,
                                 user_id: Optional[str] = None,
                                 billing_email: Optional[str] = None,
                                 ) -> Optional[str]:
    """One-time Stripe Checkout for a hosted-AI credit pack.

    mode="payment" (NOT subscription) — a single $10 charge that the
    webhook turns into 1,000 hosted messages via db.grant_credits. The
    metadata carries the owning workspace (company_id OR user_id) +
    kind=credit_pack so checkout.session.completed routes the grant. The
    actual message count + price live in config.CREDIT_PACK /
    STRIPE_PRICE_CREDIT_PACK — we never hardcode them here.
    """
    if not _ensure_stripe():
        return None
    price = config.STRIPE_PRICE_CREDIT_PACK
    if not price:
        return None
    success_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/success"
    cancel_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/cancel"
    ref = company_id or user_id or ""
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=billing_email or None,
            line_items=[{"price": price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=ref,
            metadata={
                "kind": "credit_pack",
                "company_id": company_id or "",
                "user_id": user_id or "",
                "messages": str(config.CREDIT_PACK["messages"]),
            },
        )
    except Exception as ex:
        print(f"[stripe] credit-pack checkout.create failed: {ex}",
              flush=True)
        return None
    return session.url


def create_portal_url(*, user: dict) -> Optional[str]:
    """Stripe Customer Portal for plan changes / cancel / card update."""
    if not _ensure_stripe():
        return None
    if not user.get("stripe_id"):
        return None
    return_url = f"{config.PUBLIC_URL.rstrip('/')}/billing/portal_return"
    try:
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_id"],
            return_url=return_url,
        )
    except Exception as ex:
        print(f"[stripe] portal.create failed: {ex}", flush=True)
        return None
    return session.url


# ---------------------------------------------------------------------------
def _tier_from_event(event: dict) -> Optional[str]:
    """Pull the tier label out of metadata / line items."""
    try:
        meta = (event["data"]["object"].get("metadata") or {})
        if meta.get("tier"):
            return meta["tier"]
    except Exception:
        pass
    return None


def _user_id_from_event(event: dict) -> Optional[str]:
    obj = event["data"]["object"]
    if obj.get("client_reference_id"):
        return obj["client_reference_id"]
    meta = obj.get("metadata") or {}
    if meta.get("user_id"):
        return meta["user_id"]
    customer = obj.get("customer") or ""
    if customer:
        u = db.get_user_by_stripe_id(customer)
        if u is not None:
            return u["id"]
    return None


def _company_from_subscription(obj: dict) -> Optional[dict]:
    """Resolve the company behind a `customer.subscription.*` event.

    The subscription object carries the Stripe customer id; the company
    row stores it (`stripe_customer_id`, stamped at checkout). A given
    Stripe customer is either a company or a single user — never both —
    so a hit here unambiguously means a company event. Returns None for
    per-user (Solo) subscriptions, which fall through to the user path.
    """
    customer = obj.get("customer") or ""
    if not customer:
        return None
    return db.get_company_by_stripe_customer(customer)


def _tier_from_subscription(obj: dict) -> Optional[str]:
    """Map a subscription's active price id back to a plan tier."""
    try:
        price_id = obj["items"]["data"][0]["price"]["id"]
    except Exception:
        return None
    if not price_id:
        return None
    # Match the monthly id (via the PLAN_PRICE_IDS shim — kept in sync
    # with PLANS, and the surface tests monkeypatch) OR the annual (−20%)
    # id (which lives only in PLANS, not the monthly shim).
    for tier, pid in config.PLAN_PRICE_IDS.items():
        if pid == price_id:
            return tier
    for tier, p in config.PLANS.items():
        if price_id == p.get("price_id_annual") and price_id:
            return tier
    return None


def handle_webhook(*, payload: bytes, signature: str) -> dict:
    """Verify + dispatch a Stripe webhook. Returns a small status dict."""
    if not _ensure_stripe():
        return {"ok": False, "error": "stripe_not_configured"}
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, config.STRIPE_WEBHOOK_SECRET,
        )
    except Exception as ex:
        return {"ok": False, "error": f"bad_signature: {ex}"}

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        # Credit-pack purchase (one-time payment, Model C). Checked FIRST
        # because a pack bought by a company also carries company_id in
        # metadata — but it must grant credits, NOT change the plan. The
        # grant is idempotent on the Stripe session id so a webhook replay
        # can't double-credit.
        if meta.get("kind") == "credit_pack":
            messages = int(meta.get("messages")
                           or config.CREDIT_PACK["messages"])
            cid = meta.get("company_id") or None
            uid = meta.get("user_id") or None
            if not cid and not uid:
                # Fall back to client_reference_id (we stored the
                # workspace id there too). Prefer company resolution.
                ref = obj.get("client_reference_id") or ""
                if ref.startswith("co_"):
                    cid = ref
                elif ref:
                    uid = ref
            event_id = (event.get("id")
                        or obj.get("id")
                        or obj.get("payment_intent"))
            granted = {"granted": False}
            try:
                if cid:
                    granted = db.grant_credits(
                        messages=messages, company_id=cid,
                        stripe_event_id=event_id)
                elif uid:
                    granted = db.grant_credits(
                        messages=messages, user_id=uid,
                        stripe_event_id=event_id)
            except Exception as ex:
                print(f"[stripe] credit grant failed: {ex}", flush=True)
            return {"ok": True, "handled": etype, "kind": "credit_pack",
                    "company_id": cid, "user_id": uid,
                    "messages": messages,
                    "granted": granted.get("granted"),
                    "balance": granted.get("balance")}

        # Company-scoped checkout (multi-seat plans). The router stamps
        # `company_id` + `kind=company` into the session metadata so we
        # can route the subscription update to the right table.
        if meta.get("company_id") or meta.get("kind") == "company":
            cid = meta.get("company_id") or obj.get("client_reference_id")
            tier = meta.get("tier") or "studio"
            stripe_customer = obj.get("customer")
            sub_id = obj.get("subscription")
            period_end = None
            # Model C: seat_limit = the subscription's purchased quantity
            # (per-seat), clamped to the tier floor. Read it off the live
            # subscription line item; fall back to the metadata `seats`
            # the router stamped, then the tier minimum.
            sub_qty = None
            if sub_id:
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    period_end = int(sub.get("current_period_end") or 0)
                    sub_qty = int(sub["items"]["data"][0].get("quantity") or 0)
                except Exception:
                    period_end = None
            if not sub_qty:
                try:
                    sub_qty = int(meta.get("seats") or 0)
                except Exception:
                    sub_qty = 0
            if not sub_qty:
                sub_qty = config.PLAN_SEATS.get(tier, 1)
            seat_limit = config.clamp_seats(tier, sub_qty)
            if cid:
                db.update_company(
                    cid,
                    plan=tier,
                    seat_limit=seat_limit,
                    stripe_customer_id=stripe_customer,
                    stripe_subscription_id=sub_id,
                    period_end=period_end,
                )
            return {"ok": True, "handled": etype, "company_id": cid,
                    "tier": tier}

        # Legacy per-user flow (Solo plan).
        uid = _user_id_from_event(event)
        tier = _tier_from_event(event) or "solo"
        stripe_id = obj.get("customer")
        period_end = None
        sub_id = obj.get("subscription")
        if sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                period_end = int(sub.get("current_period_end") or 0)
            except Exception:
                period_end = None
        if uid:
            db.update_user_plan(uid, plan=tier, stripe_id=stripe_id,
                                  period_end=period_end)
        return {"ok": True, "handled": etype, "user_id": uid,
                "tier": tier}

    if etype in ("customer.subscription.created",
                  "customer.subscription.updated"):
        # subscription.created fires on first subscription (Stripe
        # Checkout completion OR programmatic Subscriptions.create).
        # subscription.updated fires on tier change, payment-method
        # change, metadata change, etc. Both upgrade the user's plan —
        # one handler covers both (idempotent: update_user_plan resets
        # msg_used only when plan actually changes).
        period_end = int(obj.get("current_period_end") or 0)
        # Company subscription? Route to the company row first — a
        # Stripe customer is either a company or a user, never both.
        # Without this branch a Studio->Firm upgrade (which arrives as
        # subscription.updated, not checkout.completed) never reaches
        # the company quota.
        company = _company_from_subscription(obj)
        if company is not None:
            tier = _tier_from_subscription(obj) or company["plan"]
            # Model C: seat_limit tracks the subscription's live quantity
            # (à-la-carte seat add/remove arrives here as a
            # subscription.updated), clamped to the tier floor. Fall back
            # to the company's existing seat_limit if the item carries no
            # quantity.
            try:
                qty = int(obj["items"]["data"][0].get("quantity") or 0)
            except Exception:
                qty = 0
            seat_limit = (config.clamp_seats(tier, qty) if qty
                          else company["seat_limit"])
            db.update_company(
                company["id"], plan=tier,
                seat_limit=seat_limit,
                period_end=period_end,
            )
            return {"ok": True, "handled": etype,
                    "company_id": company["id"], "tier": tier,
                    "seat_limit": seat_limit}
        uid = _user_id_from_event(event)
        tier = _tier_from_subscription(obj) or "solo"
        stripe_customer = obj.get("customer")
        if uid:
            db.update_user_plan(uid, plan=tier,
                                  stripe_id=stripe_customer,
                                  period_end=period_end)
        return {"ok": True, "handled": etype, "user_id": uid,
                "tier": tier}

    if etype == "customer.subscription.deleted":
        # Cancelled subscription — drop the actor back to trial quota.
        company = _company_from_subscription(obj)
        if company is not None:
            db.update_company(company["id"], plan="trial",
                              period_end=None)
            return {"ok": True, "handled": etype,
                    "company_id": company["id"]}
        uid = _user_id_from_event(event)
        if uid:
            db.update_user_plan(uid, plan="trial", period_end=None)
        return {"ok": True, "handled": etype, "user_id": uid}

    if etype == "invoice.payment_failed":
        # Don't downgrade immediately — Stripe retries. Just log.
        uid = _user_id_from_event(event)
        print(f"[billing] payment_failed for user {uid}", flush=True)
        return {"ok": True, "handled": etype, "user_id": uid}

    return {"ok": True, "ignored": etype}
