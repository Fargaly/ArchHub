# Billing alternatives — Stripe vs Polar.sh

**Why this doc exists:** Stripe direct requires you to be a real
business with KYC verification (10-30 min signup + multi-day waits).
For a solo founder pre-revenue, that's a wall. v1.3.0 ships **Polar.sh**
as a drop-in alternative — same checkout flow, same webhook DB pattern,
zero business-entity requirement.

## Quick decision

| You are... | Pick |
|---|---|
| Solo founder, no business entity yet | **Polar.sh** (~10 min signup) |
| Want lowest fees, willing to handle tax | **Stripe** (2.9% + $0.30) |
| Selling to EU customers, want VAT handled | **Polar.sh** (MoR) or **Paddle** (MoR) |
| Want to ship in next 60 minutes | **Polar.sh** |

## Cost comparison ($79 Studio subscription)

| Provider | Per-charge fee | Annual fee | Tax handling | Total cost on 100 Studio subs |
|---|---|---|---|---|
| **Stripe direct** | 2.9% + $0.30 = **$2.59** | $0 | YOU (Avalara ~$700/yr) | $3,290 |
| **Polar.sh** (MoR) | ~4% + $0.40 = **$3.56** | $0 | Polar handles all | $4,300 |
| **LemonSqueezy** (MoR, Stripe-owned) | 5% + $0.50 = **$4.45** | $0 | LSquid handles | $5,440 |
| **Paddle** (MoR) | 5% flat = **$3.95** | $0 | Paddle handles | $4,740 |

Stripe is **$1,000/yr cheaper** but you owe tax compliance work. Polar
costs $1,000/yr more but you do nothing on tax.

## Setup time

| Provider | Signup | First product | First charge possible |
|---|---|---|---|
| Stripe | 10-30 min KYC | 5 min | After Stripe verifies (minutes to days) |
| **Polar.sh** | **5 min** | **3 min** | **Same day** |
| LemonSqueezy | 30 min KYC | 5 min | Same day |
| Paddle | 30-60 min vendor onboarding | 10 min | After Paddle verifies (1-3 days) |

## Switching to Polar — what you do

### 1. Sign up at polar.sh (5 min)
- <https://polar.sh/dashboard/onboarding> → Create organization
- Connect bank account or Stripe-as-payout (your money lands in whichever)
- No business entity required for personal accounts

### 2. Create the 3 products (3 min total)
- Dashboard → Products → New product. Repeat 3x:

| Product name | Recurring | Price | Interval |
|---|---|---|---|
| ArchHub Solo | Yes | $19 USD | Monthly |
| ArchHub Studio | Yes | $79 USD | Monthly |
| ArchHub Firm | Yes | $299 USD | Monthly |

- After each save, copy the **Product UUID** (looks like `prod_01abc...`)

### 3. Get your API key (1 min)
- Dashboard → Settings → API → New token. Scope: full access.

### 4. Update Fly secrets
```powershell
flyctl secrets set `
  BILLING_PROVIDER=polar `
  POLAR_ACCESS_TOKEN=polar_at_... `
  POLAR_WEBHOOK_SECRET=polar_wh_... `
  POLAR_PRODUCT_SOLO=prod_... `
  POLAR_PRODUCT_STUDIO=prod_... `
  POLAR_PRODUCT_FIRM=prod_... `
  -a archhub-cloud
```

### 5. Register the webhook (3 min)
- Polar dashboard → Settings → Webhooks → New webhook
- URL: `https://archhub-cloud.fly.dev/v1/webhooks/polar`
- Events to subscribe:
  - `subscription.created`
  - `subscription.updated`
  - `subscription.canceled`
  - `subscription.revoked`
  - `order.paid`
- Copy the signing secret → paste as `POLAR_WEBHOOK_SECRET` in step 4 above

### 6. Test
Polar's checkout has a **test mode card**: `4242 4242 4242 4242`. Same
as Stripe. Run through the desktop signup → upgrade flow → verify the
DB row flips:

```bash
flyctl ssh console -a archhub-cloud
python -c "import db; print(db.get_user_by_email('your@email.com'))"
# → {..., 'plan': 'solo', 'stripe_id': 'polar_cus_...', 'msg_used': 0}
# 'stripe_id' column is reused — the Polar customer id lives there.
```

## Switching back to Stripe

Set `BILLING_PROVIDER=stripe` (default) — the existing Stripe path
takes over. Both providers can be configured at the same time; the
env var picks which one accepts checkouts at runtime.

## Architecture note

Both billing modules expose the same surface:

```python
create_checkout_url(*, user, tier) -> Optional[str]
create_portal_url(*, user) -> Optional[str]
handle_webhook(*, payload: bytes, signature: str) -> dict
```

`main.py` picks via `config.BILLING_PROVIDER`. Webhook URLs differ
(`/v1/webhooks/stripe` vs `/v1/webhooks/polar`) but both end with
`db.update_user_plan(...)` — DB stays provider-agnostic.

When you outgrow Polar (volume >$10k MRR → fees start hurting),
switch to Stripe with one env-var flip + 6 new Stripe-side secrets.
No code changes.

## What about LemonSqueezy / Paddle?

We can ship those as additional providers if needed. They use very
similar Merchant-of-Record patterns — adding LemonSqueezy = one new
`cloud_backend/lemonsqueezy.py` module that mirrors `polar.py`, plus a
new branch in `_billing_provider_module()`. ~2-3 hours of work each.
Defer until Polar isn't enough.

## Tax handling note

When Polar is your MoR:
- Polar charges + collects EU VAT, US sales tax, UK VAT
- Polar files all tax returns
- You get a **single** invoice from Polar (the MoR) for each payout
- You report Polar's payouts as **B2B revenue** to your country's tax
  authority — much simpler than 50+ tax jurisdictions

When Stripe is direct:
- YOU charge VAT/sales tax appropriately per-customer
- YOU register with tax authorities in every jurisdiction with nexus
- YOU file returns
- Most solo founders use a tool like Avalara ($700/yr+) for this
- Saves money only if you're already running a tax compliance function

## Recommendation

**Today:** start with Polar.sh. 10-min signup, no business, ship fast.
**Year 2:** if MRR >$10k/mo and fees hurt, evaluate Stripe direct + a tax tool.
**Always:** keep the env-var swap available so the choice is reversible.
