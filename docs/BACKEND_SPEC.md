# ArchHub Cloud — Backend Spec

This document is the contract the desktop client (this repo) assumes
the `cloud.archhub.app` backend implements. The backend lives in a
**separate repo** (not yet built); this file is what the next person
to build it needs to ship.

## Stack recommendation

- **Cloudflare Workers + D1 (SQLite)** for the auth + billing routes (cheap, fast cold-start, no server to manage)
- **OR Fly.io + Postgres** if you prefer a long-running Python service
- **Stripe** for billing — Checkout for new sign-ups, Customer Portal for plan changes
- **Resend** for magic-link emails

Either stack works. Pick by familiarity. Total infra cost at <1000 users: ~$20-50/mo.

---

## Endpoints

### POST `/v1/auth/register`

Triggers a magic-link send. Idempotent — a second call within 5 min should rate-limit, not resend.

**Request**
```json
{ "email": "alice@studio.com" }
```

**Response**: `202 Accepted`, empty body.

**Errors**:
- `400` — invalid email
- `429` — rate-limited

---

### POST `/v1/auth/exchange`

Exchange a one-time code (from the magic-link redirect) for a long-lived bearer token. Uses PKCE so a stolen code can't be replayed.

**Request**
```json
{
  "code": "abc123...",
  "code_verifier": "verifier_from_pkce_pair"
}
```

**Response**: `200 OK`
```json
{
  "token": "ah_live_xxx",
  "expires_at": 1759999999,
  "plan": "trial"
}
```

**Errors**:
- `400` — bad code / verifier mismatch
- `401` — code expired (5 min TTL)

---

### GET `/v1/me`

Returns the signed-in user's plan + remaining quota. Cached client-side for 60s.

**Headers**: `Authorization: Bearer <token>`

**Response**: `200 OK`
```json
{
  "email": "alice@studio.com",
  "plan": "solo",
  "remaining_messages": 467,
  "period_end": 1762678400,
  "can_upgrade": true
}
```

Plan values: `"trial"` | `"solo"` | `"studio"` | `"firm"`.

---

### POST `/v1/chat/completions`

**OpenAI-compatible Chat Completions API.** Streams Server-Sent Events. Backend authenticates the bearer, picks a provider (Claude / GPT / Gemini) based on the requested model or routing rules, decrements quota by 1 message per completed conversation, returns `402 Payment Required` when exhausted.

Wire format identical to OpenAI's. The client already speaks this — see `app/llm_providers/archhub_cloud_client.py`. Pass through tool calls, reasoning content, image inputs unchanged.

**Headers**: `Authorization: Bearer <token>`, `Content-Type: application/json`

**Request**: standard OpenAI shape (`model`, `messages`, `tools`, `stream: true`, etc.).

**Response**: SSE stream.

**Errors**:
- `401` — bad / expired token
- `402` — quota exhausted; body `{ "error": "quota_exhausted", "upgrade_url": "..." }`
- `429` — fair-use rate limit
- `5xx` — provider unavailable (backend should retry across providers before surfacing)

---

### POST `/v1/billing/checkout`

Create a Stripe Checkout Session for the chosen tier. Returns the URL the client opens in the browser.

**Request**
```json
{ "tier": "solo" }
```

Valid tiers: `"solo"` | `"studio"` | `"firm"`.

**Response**: `200 OK`
```json
{ "url": "https://checkout.stripe.com/c/pay/..." }
```

---

### GET `/v1/billing/portal`

Stripe Customer Portal URL for the signed-in user (plan changes, cancel, update card).

**Response**: `200 OK`
```json
{ "url": "https://billing.stripe.com/p/session/..." }
```

---

### POST `/v1/webhooks/stripe`

Stripe webhook receiver. Updates the user's plan + quota when subscription events fire. Must verify the Stripe signature.

Events to handle:
- `checkout.session.completed` → upgrade plan, reset quota
- `customer.subscription.updated` → plan change
- `customer.subscription.deleted` → downgrade to trial / BYO
- `invoice.payment_failed` → flag account, email user

---

## Data model

```sql
-- users
CREATE TABLE users (
    id            TEXT PRIMARY KEY,           -- ulid
    email         TEXT UNIQUE NOT NULL,
    created_at    INTEGER NOT NULL,
    plan          TEXT NOT NULL DEFAULT 'trial',  -- trial|solo|studio|firm
    stripe_id     TEXT,                       -- customer_xxx
    period_end    INTEGER,                    -- unix ts of next bill
    msg_limit     INTEGER NOT NULL DEFAULT 30,
    msg_used      INTEGER NOT NULL DEFAULT 0
);

-- magic-link codes (5 min TTL)
CREATE TABLE codes (
    code            TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    code_challenge  TEXT NOT NULL,
    expires_at      INTEGER NOT NULL
);

-- bearer tokens
CREATE TABLE tokens (
    token         TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER
);

-- usage log (one row per chat turn, for billing audit + analytics)
CREATE TABLE usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    model       TEXT NOT NULL,                -- claude-sonnet-4-6 etc.
    input_toks  INTEGER NOT NULL,
    output_toks INTEGER NOT NULL,
    cost_micros INTEGER NOT NULL              -- $0.000001 units
);
```

## Quotas

| Plan | $/mo | msg_limit | Approx cost per msg | Margin |
|------|------|-----------|---------------------|--------|
| Trial | $0 | 30 | $0.02 | -$0.60 (acquisition) |
| Solo | $19 | 500 | $0.02 | ~$9 |
| Studio | $79 | 2000 | $0.02 | ~$39 |
| Firm | $299 + $39/seat | unlimited fair-use | $0.02 | varies |

A "message" = one completed conversation turn (user msg → final assistant msg incl. all tool calls). Multi-step skill runs count as 1 even if they fire 8 tool calls internally.

## Security

- All endpoints HTTPS only.
- Bearer tokens are 256-bit URL-safe random; never sent in URLs (Authorization header only).
- PKCE protects the exchange step against intercepted codes.
- Webhooks verify Stripe signature.
- Magic-link emails include `Reply-To: noreply@archhub.app` and a clear "didn't request this?" link that revokes any pending code for the address.
- No provider API keys ever leave the backend.

## Acceptance criteria

Backend ships when:

- [ ] `archhub_cloud` provider in the desktop client gets a streaming response from `/v1/chat/completions` and renders tokens in real time
- [ ] `/v1/me` returns the right remaining count after each chat turn
- [ ] Stripe Checkout completes → next `/v1/me` shows updated plan + new quota
- [ ] Quota exhaustion returns 402 with an `upgrade_url` the client surfaces as a paywall toast
- [ ] At least 3 days of usage_log entries reconcile against Stripe revenue within 1% margin (cost tracking sanity check)

## Out of scope for v1

- Team / multi-seat billing → v1.1
- SSO (SAML / OIDC) → Firm tier, post-launch
- Self-hosted on-prem deploy → AGPL grant covers it; we don't operate it
- Per-firm SLAs → handled by separate support contracts, not the billing system
