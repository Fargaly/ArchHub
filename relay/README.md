# ArchHub Cloud Relay

> **Audience:** This directory is the closed-source paid-tier component of ArchHub.
> The code is shipped here for transparency and self-hosting, but the operated
> instance that ArchHub Studio customers connect to (`archhub-relay.vercel.app`) is
> run by the company. The desktop app at <https://github.com/Fargaly/ArchHub> remains
> open source under MIT.

## What it does

The relay is a thin Vercel serverless function that exposes an **OpenAI-compatible
`/v1/chat/completions` endpoint** for ArchHub Studio firms. Architects on a firm's
plan sign in once and their LLM traffic is routed to Anthropic, OpenAI, Google, or
OpenRouter using a single key the firm's IT manages — instead of pasting raw
provider keys into every laptop.

Why this exists:

- **For IT**: API keys live on the relay (in Supabase Vault), not on every laptop.
  Revoke a departing architect's bearer token, not a shared key.
- **For architects**: One sign-in. One bill. The desktop app's existing
  `CustomOpenAICompatibleClient` (in `app/llm_providers/openrouter_client.py`)
  already speaks this shape — they paste the relay URL + their token in
  Settings → Firm Relay and it works.
- **For ArchHub the company**: A simple paid-tier moat. $79/seat/mo, billed to the
  firm, no per-architect billing pain.

## Architecture

```
   ArchHub Desktop                     Cloud Relay (this repo)               Upstream
  ----------------                  ---------------------------          ------------------
   Architect's laptop                Vercel serverless function           Anthropic / OpenAI
       |                                     |                            Google / OpenRouter
       |  POST /v1/chat/completions          |                                    ^
       |  Authorization: Bearer <jwt>        |                                    |
       +------------------------------------>+                                    |
                                             |  (1) verify JWT via Supabase anon  |
                                             |  (2) load firm row + provider key  |
                                             |  (3) check rate-limit + monthly cap|
                                             |  (4) route by model name --------->+
                                             |                                    |
                                             |  (5) tee SSE stream <--------------+
                                             |  (6) pipe to client (no buffer)
                                             |  (7) async usage row -> Supabase
       <-------------------------------------+

  Supabase Postgres (free tier)
    firms ............ (id, plan, monthly_cap, *_key_encrypted)
    users ............ (id -> auth.users, firm_id, role)
    usage ............ (partitioned monthly, RLS firm-scoped)
    monthly_usage_per_firm  (view, used for cap enforcement)
```

## Deploy in 10 minutes

### 1. One-click Vercel

Click **Deploy** → choose a Vercel scope → Vercel imports this repo. *(Replace the
URL below with the live archhub-cloud-relay template once published.)*

```
https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FFargaly%2FArchHub&root-directory=relay
```

### 2. Supabase

1. Create a new project at <https://supabase.com/dashboard> (free tier is fine).
2. SQL editor → paste `relay/sql/schema.sql` → Run.
3. Project Settings → API → copy the **URL**, the **anon** key, and the
   **service_role** key.

### 3. Wire the env vars

In the Vercel project's Environment Variables panel set:

| Var                          | Where to find it                       |
|------------------------------|----------------------------------------|
| `SUPABASE_URL`               | Supabase → Settings → API              |
| `SUPABASE_ANON_KEY`          | Supabase → Settings → API → `anon`     |
| `SUPABASE_SERVICE_ROLE_KEY`  | Supabase → Settings → API → `service_role` (secret) |
| `RELAY_RATE_PER_MIN`         | Optional, defaults to `60`             |

Per-firm provider keys go into the `firms.*_key_encrypted` columns in Supabase,
not env vars — that's the whole point of the multi-tenant model.

### 4. Hand the URL to the firm

The firm pastes two values into ArchHub Desktop → Settings → Firm Relay:

- **Relay URL:** `https://archhub-relay.vercel.app/v1` (or your own deploy)
- **Token:** their per-architect Supabase JWT, issued by the ArchHub Studio
  onboarding flow.

ArchHub uses its existing `CustomOpenAICompatibleClient(api_key, base_url)`
(see `app/llm_providers/openrouter_client.py`) — no client-side changes.

## Local dev

```bash
cd relay
cp .env.example .env.local
# fill in SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
npm install
npm run seed       # creates Test Studio firm + a test JWT, prints it
npm run dev        # vercel dev on :3000
```

Then in another terminal:

```bash
curl -N -X POST http://localhost:3000/v1/chat/completions \
  -H "Authorization: Bearer <token-printed-by-seed>" \
  -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

## Free-tier sizing

| Layer       | Free-tier limit                           | Comfortable for             |
|-------------|-------------------------------------------|-----------------------------|
| Vercel Free | ~100k function invocations / month        | First 5–10 paying firms     |
| Supabase    | 500 MB Postgres + 50k auth users          | Same                        |
| OpenRouter  | Pay-as-you-go on the firm's own balance   | (firm pays upstream costs)  |

Cap-enforcement aggregate query is one indexed read against
`monthly_usage_per_firm`; it stays sub-millisecond even with millions of
`usage` rows because the table is partitioned monthly.

## Cost ladder

| Stage                                  | Spend                                    |
|----------------------------------------|------------------------------------------|
| 0 firms (you're testing)               | $0                                       |
| 1–10 firms (~50–500 architects)        | $0 — fits in Vercel + Supabase free      |
| 10–50 firms (~500–2.5k architects)     | $20/mo Vercel Pro                        |
| 50+ firms                              | $20 Vercel + ~$25/mo managed Postgres    |
| Enterprise / dedicated                 | self-hosted on the firm's own VPC        |

The relay's incremental compute is negligible — almost all per-request latency is
upstream LLM time, which Vercel doesn't charge for during streaming idle (the
function counts as one invocation regardless of how long the stream stays open,
within Vercel's 300s function timeout on Pro).

## Files

| Path                                  | Role                                      |
|---------------------------------------|-------------------------------------------|
| `api/v1/chat/completions.ts`          | OpenAI-shape proxy + SSE passthrough      |
| `api/v1/me.ts`                        | Identity + monthly usage snapshot         |
| `lib/supabase.ts`                     | Auth + firm-key + usage helpers           |
| `lib/upstream.ts`                     | Model-name → provider router              |
| `sql/schema.sql`                      | Tables, partitions, RLS, view             |
| `scripts/seed-test-firm.ts`           | Local dev: test firm + bearer token       |
| `vercel.json`                         | Node 20 runtime + `/v1/*` rewrite         |
| `.env.example`                        | Required env vars (no secrets)            |

## License

The relay code is **not** MIT-licensed. See LICENSE in the repo root for terms — in
short, you may read and audit; commercial operation of an instance for paying
customers is reserved to ArchHub the company. Self-hosting for your own firm's
internal use is permitted.
