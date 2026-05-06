# Cloud Relay v0 — Hand-off

## What I built

A Vercel-deployable, OpenAI-shape proxy that authenticates ArchHub Studio architects
against Supabase, looks up their firm's upstream API key, routes by model name to
Anthropic / OpenAI / Google / OpenRouter, streams the response back without
buffering, and logs usage out-of-band for monthly-cap enforcement. The desktop
app's existing `CustomOpenAICompatibleClient(api_key, base_url)` works unchanged
against this endpoint.

## Files created

| Path                                          | Role                                                          |
|-----------------------------------------------|---------------------------------------------------------------|
| `relay/api/v1/chat/completions.ts`            | POST proxy, SSE passthrough, async usage logging              |
| `relay/api/v1/me.ts`                          | GET identity + `usage_this_month` snapshot                    |
| `relay/lib/supabase.ts`                       | `getUserFromToken`, `getFirmKey`, `recordUsage`, `getMonthlyUsage`, `checkRateLimit` |
| `relay/lib/upstream.ts`                       | `routeModel` + `maybeRewriteModel` — model-prefix → upstream  |
| `relay/sql/schema.sql`                        | `firms`, `users`, partitioned `usage`, `monthly_usage_per_firm` view, RLS policies |
| `relay/scripts/seed-test-firm.ts`             | Local-dev seed: firm + JWT for pasting into ArchHub Settings  |
| `relay/package.json`                          | Deps: `@vercel/node`, `@supabase/supabase-js`, `openai`, `@anthropic-ai/sdk`, `@google/generative-ai` |
| `relay/vercel.json`                           | Node 20 runtime + `/v1/*` → `/api/v1/*` rewrite               |
| `relay/tsconfig.json`                         | Strict TS for `npm run typecheck`                             |
| `relay/.env.example`                          | Required env vars, no secrets                                 |
| `relay/README.md`                             | Deploy guide, free-tier sizing, cost ladder, architecture     |

## What's left for you

1. **Deploy to Vercel.** From `relay/`: `vercel link` → `vercel deploy --prod`.
   Set the three Supabase env vars in the Vercel project's Environment Variables
   panel (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`).
2. **Provision Supabase.** New project → SQL editor → paste `sql/schema.sql` → Run.
   Confirm RLS is on for `firms`, `users`, `usage` (it is in the schema, but worth
   eyeballing in the Auth → Policies UI).
3. **Point a domain at it.** Add `archhub-relay.vercel.app` (or
   `relay.archhub.app` via custom domain) and update the README's deploy URL.
4. **Wire the desktop app's "Firm Relay" Settings field.** Add a new section to
   the Settings dialog:
   - Two text fields: **Relay URL** (default `https://archhub-relay.vercel.app/v1`)
     and **Token**.
   - Helper text: *"Studio plan customers: paste the URL and token your firm admin
     gave you. Self-hosted? See <https://github.com/Fargaly/ArchHub/tree/main/relay>."*
   - On save, instantiate `CustomOpenAICompatibleClient(token, url)` and store the
     pair in the existing config under a new `firm_relay` key.
   - Optional polish: hit `GET /v1/me` with the entered token and show
     "Connected as <email> · <usage>/<cap> tokens this month" inline.
5. **Onboarding flow for paying firms.** Some thin admin UI (or a one-off script
   per firm for v0) that:
   - inserts a row into `firms` with the firm's name and plan,
   - drops their provider key into `*_key_encrypted` (Vault recommended before
     the second firm — for the first, plain text in the column is acceptable),
   - creates Supabase auth users for each architect and inserts their `users` row.
6. **Pick a partition-rotation cadence.** The schema bootstraps 12 months of
   `usage` partitions. Either a Supabase scheduled SQL function or `pg_partman`
   to add the next month each month — easy, but unowned right now.

## Open questions

1. **Direct Anthropic / Gemini paths.** v0 routes everything non-OpenAI through
   OpenRouter so we only speak one wire format. A firm asking for direct
   Anthropic billing means writing a body translator. Worth doing? My read: not
   for v0 — the OpenRouter markup is small and the firm gets unified billing.
2. **Token cap unit.** I used `prompt_tokens + completion_tokens` for the cap.
   Is that what you want to bill against, or do you want a *cost* cap (USD,
   computed via per-model rate cards)? The latter is more honest for mixed-model
   workflows but needs a price table.
3. **Bearer token model.** I assumed Supabase JWTs (one per architect, refreshed
   by the desktop app). Alternative: a per-firm long-lived API token + a header
   identifying the architect. JWT path is simpler today; long-lived token is
   nicer if architects work offline-then-sync.
4. **Edge vs Node runtime.** I picked Node so `@supabase/supabase-js` works
   without polyfills. If the streaming-cold-start latency bothers paying firms,
   we can move the chat handler to Edge and inline a minimal Supabase JWT
   verifier (~30 lines) — usage logging would move to a fire-and-forget Edge
   `waitUntil` call.
5. **Where does the firm's bill go?** If ArchHub pays OpenRouter and re-bills the
   firm, that's a per-firm Stripe subscription tied to a `seat_count` field on
   `firms`. Not in v0; flagging because it changes the `users.role` model
   slightly (need an `owner` who is the billing contact — schema already has it).
6. **Vault vs plain TEXT for `*_key_encrypted`.** Schema treats them as opaque
   strings the relay reads verbatim. Acceptable for the first paying firm;
   needs to migrate to Supabase Vault before the second. Want me to write that
   migration now or wait?
