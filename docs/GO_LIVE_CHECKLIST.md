# ArchHub Cloud — Go-Live Checklist

**Goal:** first $1 lands in your Stripe account. Everything below is sequenced so you can pause at any step and resume later.

**Total time:** 90-120 min if no Stripe account exists. 30-45 min if one does.

---

## Phase 1 — Stripe (you, in stripe.com)

### 1.1 Create / sign in to Stripe account
- <https://dashboard.stripe.com/register>
- Fill in business info (sole proprietor is fine for now)
- **Country:** UAE (or wherever you bank)
- **Currency:** USD (universal — switch later if needed)
- Verify email + phone

### 1.2 Create the 3 subscription products
Dashboard → **Products** → **+ Add product**, do this three times:

| Product | Pricing model | Amount | Billing |
|---|---|---|---|
| **ArchHub Solo** | Recurring | $19 USD | Monthly |
| **ArchHub Studio** | Recurring | $79 USD | Monthly |
| **ArchHub Firm** | Recurring | $299 USD | Monthly |

After each save, copy the **Price ID** (looks like `price_1abc...`). You need three of them.

### 1.3 Get your secret key
Dashboard → **Developers → API keys** → reveal **Secret key** (starts `sk_test_...` for test mode, `sk_live_...` for live).

**Use TEST mode first.** Switch to LIVE once everything works end-to-end.

### 1.4 Stop here for now
The webhook URL needs the Fly app to exist before Stripe can validate it. We come back after Phase 2.

---

## Phase 2 — Deploy backend (mostly automated)

### 2.1 Install flyctl + sign in
The deploy script does this automatically, but if you want it manually:
```powershell
iwr https://fly.io/install.ps1 -useb | iex
flyctl auth signup        # OR `flyctl auth login` if you have an account
```

### 2.2 Run the one-command deploy
```powershell
.\cloud_backend\deploy.ps1
```
It will:
- Install flyctl if missing
- Create the `archhub-cloud` Fly app
- Create a 1GB persistent volume
- Prompt for each Stripe secret (you paste the values from Phase 1)
- Deploy
- Hit `/healthz` to confirm it booted

Required secret values when prompted:
- `STRIPE_SECRET_KEY` — from Phase 1.3
- `STRIPE_WEBHOOK_SECRET` — leave blank for now (we set it in Phase 3)
- `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_STUDIO`, `STRIPE_PRICE_FIRM` — from Phase 1.2
- `ANTHROPIC_API_KEY` — your Anthropic dashboard key (signs ArchHub Cloud LLM calls)
- `OPENAI_API_KEY` — optional, only needed if you want Cloud Solo to expose GPT
- `GOOGLE_API_KEY` — optional, only needed for Gemini in Cloud Solo
- `RESEND_API_KEY` — required for magic-link email (Resend.com free tier is fine)
- `JWT_SECRET` — generate with `openssl rand -hex 32` or paste 32+ random chars

### 2.3 Confirm the app is up
```powershell
curl https://archhub-cloud.fly.dev/healthz
# → {"status":"ok","db":"reachable","ts":...}
```

---

## Phase 3 — Stripe webhook (you, in stripe.com)

### 3.1 Add the webhook endpoint
Dashboard → **Developers → Webhooks → + Add endpoint**

| Field | Value |
|---|---|
| **Endpoint URL** | `https://archhub-cloud.fly.dev/v1/webhooks/stripe` |
| **Description** | "ArchHub Cloud production" |
| **Events to listen to** | (select 4 events below) |

Events:
- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

Click **Add endpoint**.

### 3.2 Copy the signing secret
On the new endpoint page → **Signing secret** → **Reveal**. Copy the `whsec_...` value.

### 3.3 Push the secret to Fly
```powershell
flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_... -a archhub-cloud
```
Fly auto-restarts the app to pick up the new secret. ~10s.

---

## Phase 4 — DNS (you, in your DNS provider)

If you want to publish under `cloud.archhub.app` instead of `archhub-cloud.fly.dev`:

```powershell
flyctl certs add cloud.archhub.app -a archhub-cloud
flyctl ips list -a archhub-cloud      # copy v4 + v6
```

Then in your DNS dashboard add:

| Type | Host | Value |
|---|---|---|
| A | cloud.archhub.app | <v4 from flyctl ips> |
| AAAA | cloud.archhub.app | <v6 from flyctl ips> |

DNS propagates in 5-30 min. Fly's TLS cert auto-issues once propagation completes.

You can ship the desktop app pointing at `archhub-cloud.fly.dev` directly today and add the custom domain later.

---

## Phase 5 — Smoke test with a real card

### 5.1 Test mode
Stay in Stripe test mode. Use test card `4242 4242 4242 4242`, any future expiry, any CVC.

```bash
# From the ArchHub desktop app:
# 1. Settings → Sign-ins → ArchHub Cloud → Sign up (enter your real email)
# 2. Check your inbox for the magic link — click it
# 3. Settings → Plans & pricing → Solo → Subscribe
# 4. Pay with 4242 4242 4242 4242
# 5. Should redirect to /billing/success
```

Check Stripe dashboard → **Events** → you should see:
- `checkout.session.completed` event delivered to your webhook URL with **HTTP 200**
- The customer card now shows the Solo subscription active

Check the DB (one-off):
```bash
flyctl ssh console -a archhub-cloud
cd /app && python -c "import db; print(db.get_user_by_email('your@email.com'))"
# → {..., 'plan': 'solo', 'stripe_id': 'cus_...', 'msg_used': 0, ...}
```

### 5.2 If webhook fails to deliver
Stripe dashboard → **Webhooks → your endpoint → recent attempts** shows the last 50 requests + responses. Common issues:
- 400 "bad_signature" → `STRIPE_WEBHOOK_SECRET` doesn't match. Re-copy + re-set.
- 503 / no response → app is sleeping. Hit `/healthz` to wake it; Fly auto-starts on traffic.
- 404 → URL wrong. Should be `/v1/webhooks/stripe` (with the `/v1/` prefix).

### 5.3 Flip to LIVE mode
Once test mode end-to-end works:
1. Stripe dashboard top-right → toggle from **Test** → **Live**
2. **Recreate** the 3 prices in live mode (test prices don't carry over)
3. **Recreate** the webhook endpoint in live mode (test webhooks don't carry over)
4. Update Fly secrets with live values:
   ```powershell
   flyctl secrets set `
     STRIPE_SECRET_KEY=sk_live_... `
     STRIPE_WEBHOOK_SECRET=whsec_... `
     STRIPE_PRICE_SOLO=price_... `
     STRIPE_PRICE_STUDIO=price_... `
     STRIPE_PRICE_FIRM=price_... `
     -a archhub-cloud
   ```
5. Do one real $19 self-purchase to verify. Refund yourself after via Stripe dashboard.

---

## After go-live

| Watch daily | Where |
|---|---|
| New signups | `flyctl ssh console -a archhub-cloud` + `python -c "import db; print([u['email'] for u in db.list_users()])"` |
| Failed webhook deliveries | Stripe dashboard → Webhooks → endpoint → attempts |
| Sentry crashes | <https://archhub-2y.sentry.io> |
| Cloud usage / token spend | Anthropic dashboard + OpenAI dashboard |

| Watch weekly | Action |
|---|---|
| MRR growth | Stripe → Reports → MRR |
| Churn | Stripe → Reports → Churn |
| Token cost vs subscription revenue | Anthropic billing vs Stripe Reports |

---

## Troubleshooting

**`flyctl deploy` fails with "Dockerfile not found"**
The script passes `--dockerfile cloud_backend/Dockerfile`. Verify the file exists:
```powershell
Get-Item cloud_backend/Dockerfile
```

**`/healthz` returns 503 right after deploy**
First boot needs ~30s for the SQLite migration + the FastAPI app to start. Wait + retry. If still 503 after 60s:
```powershell
flyctl logs -a archhub-cloud
```

**Stripe webhook keeps failing with HTTP 400 bad_signature**
The signing secret in Fly doesn't match the one Stripe dashboard shows. Re-reveal in dashboard, re-set the secret, restart app.

**Magic-link email never arrives**
- Check the Resend API key is valid (Resend dashboard → API Keys)
- Check the "from" address is verified in Resend (you need to add + verify your sending domain)
- Inspect Fly logs for `[email_sender]` lines around the signup time

**Anthropic / OpenAI calls fail in production**
Verify Fly secrets are actually set:
```powershell
flyctl secrets list -a archhub-cloud
```
A missing secret here is the most common cause of "the chat works locally but errors on Cloud."
