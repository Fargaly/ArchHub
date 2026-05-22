# ArchHub Cloud — Backend

FastAPI service that powers the **Solo / Studio / Firm** paid tiers
of ArchHub. The desktop client (in `../app/cloud_client.py`) talks
to this; this talks to Anthropic / OpenAI / Google + Stripe + Resend.

Open question for the maintainer: **proprietary vs open-source.** This
folder ships as part of the public repo today (under the parent
LICENSE = MIT) because it makes deployment trivially reproducible.
If you want to keep the cloud backend closed, move this folder to a
private repo and reference it via `docs/BACKEND_SPEC.md`.

---

## What it does

7 endpoints (mirrors `docs/BACKEND_SPEC.md`):

```
POST /v1/auth/register      magic-link send
POST /v1/auth/exchange      PKCE code → bearer token
GET  /v1/me                 plan + remaining quota
POST /v1/chat/completions   OpenAI-compatible proxy with quota
POST /v1/billing/checkout   Stripe Checkout URL
GET  /v1/billing/portal     Stripe Customer Portal URL
POST /v1/webhooks/stripe    subscription lifecycle events
```

Plus three convenience routes:

```
GET  /signin                browser landing page for desktop PKCE
GET  /auth/return           magic-link click → desktop loopback redirect
GET  /healthz               liveness for Fly.io / Cloud Run
```

---

## Local dev

```bash
cd cloud_backend
python -m venv .venv
.venv\Scripts\activate     # or: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill at minimum: ANTHROPIC_API_KEY / OPENAI_API_KEY
uvicorn main:app --reload --port 8000
# → http://localhost:8000/healthz
```

With no Stripe / Resend keys the billing endpoints return 503 and
the magic-link logs to stdout instead of emailing — that's fine for
end-to-end smoke testing the desktop client's sign-in flow against
a local backend (override `ARCHHUB_CLOUD_BASE_URL=http://localhost:8000`
in the client's env to point it here).

---

## Deploy to Fly.io

One-time setup (~10 min):

```bash
flyctl launch --no-deploy --copy-config --name archhub-cloud
flyctl volumes create archhub_data --size 1 --region ord
flyctl secrets set \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_PRICE_SOLO=price_... \
  STRIPE_PRICE_STUDIO=price_... \
  STRIPE_PRICE_FIRM=price_... \
  ANTHROPIC_API_KEY=sk-ant-... \
  OPENAI_API_KEY=sk-proj-... \
  GOOGLE_API_KEY=AIza... \
  RESEND_API_KEY=re_...
flyctl deploy
```

After deploy:

```bash
# Point the production domain at the Fly IP
flyctl ips list
# (Add an A record at your DNS for cloud.archhub.io pointing to the v4)

# Add the Stripe webhook destination in the Stripe dashboard:
#   https://cloud.archhub.io/v1/webhooks/stripe
# Copy the signing secret back into Fly via:
flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_...
```

Cost at <1000 users: **~$5/mo** (Fly.io shared-cpu-1x + 1 GB volume).

---

## Deploy to Cloudflare Workers / Cloud Run

The app is plain FastAPI — anything that runs a Python ASGI server
works:

- **Cloud Run** — `gcloud run deploy archhub-cloud --source .`
- **Render** — connect the repo, point the start command at
  `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Railway** — same as Render

Cloudflare Workers itself is JavaScript-native; if you want to move
there, port `db.py` to D1 + the route handlers to itty-router. The
shape is small enough that it's ~1 day of work.

---

## Schema migrations

There aren't any — this is v1.0. Just delete the SQLite file and
restart for a fresh DB. Add Alembic later if/when you outgrow that.

---

## What's NOT included

- Email templates beyond plain magic-link.
- Per-firm SSO (Firm tier promises SAML/OIDC — wire it via [WorkOS]
  in v1.1).
- A dashboard page. Subscribers manage their plan via the Stripe
  Customer Portal that `/v1/billing/portal` issues.
- Multi-region replication. The volume is per-machine; for HA add a
  Postgres backend.

---

## Cost flow

The desktop bills you when a user paid. **You** pay the upstream
providers (Anthropic / OpenAI / Google) from the API key in env. Set
plan quotas in `config.PLAN_QUOTAS` aggressively enough that even
heavy use stays under your budget.

Per-message gross margin at the v1.0 quotas:

| Plan | Price | Msgs | Avg cost/msg | Margin/mo |
|------|-------|------|--------------|-----------|
| Trial | $0 | 30 | $0.02 | -$0.60 (acquisition) |
| Solo | $19 | 500 | $0.02 | ~$9 |
| Studio | $79 | 2000 | $0.02 | ~$39 |
| Firm | $299 + $39/seat | unlimited fair-use | $0.02 | varies |

Reconcile monthly: sum `usage_log.cost_micros` per user, compare to
Stripe revenue.

---

## Security notes

- All API endpoints HTTPS-only (Fly.io enforces).
- Bearer tokens are 256-bit URL-safe random; never in URLs.
- PKCE protects against intercepted magic-link codes.
- Webhooks verify Stripe signatures via `stripe.Webhook.construct_event`.
- No user-supplied provider keys ever stored — keys live in env on
  the server.
- No PII in logs beyond email; usage_log has user_id only.
