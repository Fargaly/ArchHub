# ArchHub Cloud — Backend Spec

> **Reference — not the roadmap.** `docs/ROADMAP.md` is the single source of
> truth for plans and milestones. This file describes the backend as it
> runs **today** (audited live on 2026-06-18). Every endpoint and table
> below was checked against the deployed service, not derived from a plan.

The backend is **live and built**. It is a FastAPI service deployed on
Fly.io as the app `archhub-cloud`, reachable at
`https://archhub-cloud.fly.dev`. It is deployed from `cloud_backend/` in
this repository; the app entry point is `cloud_backend/main.py` and the
data model is the SQLite schema created by `cloud_backend/db.py`
(`init_schema()`).

## Where the data lives

- **App**: Fly.io app `archhub-cloud` (`cloud_backend/fly.toml`).
- **Database**: one SQLite file, `/data/archhub_cloud.db`, on a **1 GB
  encrypted Fly volume** mounted at `/data` (`[[mounts]] source = 'data'
  destination = '/data'`). Because the database sits on the volume and not
  inside the container image, **it survives every redeploy** — new code
  ships, the same data stays. Locally (dev and tests) the file defaults to
  `./archhub_cloud.db`; an explicit `DATABASE_URL` always overrides.
- **Per-user brain replicas**: stored under `REPLICAS_ROOT`, which resolves
  to `/data/replicas` on Fly (also on the persistent volume). Each signed-in
  account gets its own replica folder, so brain sync survives redeploys too.
- **Schema creation**: `init_schema()` runs on every startup. It creates the
  tables if missing and applies a set of idempotent `ALTER TABLE` migrations,
  so a redeploy can add a column without a manual migration step.

## Runtime

- **API**: Python FastAPI service (`cloud_backend/main.py`), with sub-routers
  for companies (`companies.py`), the chat proxy (`proxy.py`), the marketplace
  (`marketplace.py`), and billing (`billing.py` / `polar.py`).
- **Auth**: passwordless magic-link sign-in with optional PKCE, plus optional
  Google OAuth. Both converge on the same user / one-time-code / bearer-token
  flow.
- **Email**: Resend, via `cloud_backend/email_sender.py`.
- **Billing**: Stripe by default, Polar as an alternate provider.
- **Hosted AI**: OpenAI / Anthropic / Google keys stay server-side; hosted
  inference is metered through credit packs (`credit_grants`).
- **Provider keys never leave the backend.** The desktop never receives them.

## Auth model

ArchHub Cloud uses **passwordless** auth. There are two front doors and they
end at the same place.

1. **Magic link (PKCE).** The client calls `POST /v1/auth/register` with an
   email and an optional PKCE `code_challenge`. The backend records a one-time
   code in the `codes` table and emails a link. The client then calls
   `POST /v1/auth/exchange` with `{code, code_verifier}`. If the code was
   created with a challenge, the verifier must match — this is what stops a
   stolen code from being replayed.
2. **Google OAuth.** `GET /v1/auth/google/start` returns a Google consent URL;
   after the user picks an account, Google calls back to
   `GET /v1/auth/google/callback`, the backend verifies the signed state and
   Google ID-token, mints the same kind of one-time ArchHub code, and the
   client exchanges it on the same `/v1/auth/exchange` route. These two routes
   are only mounted when both Google client secrets are configured.

The exchange returns a **bearer token**. Every authenticated call sends it as
`Authorization: Bearer <token>`. Tokens:

- are minted as `ah_live_…` random strings (`db.issue_token`),
- carry **no scopes** — a token identifies exactly one user; permissions are
  derived from the user, the route, and company membership,
- **expire server-side after 90 days** (`TOKEN_TTL_SECONDS = 90 * 24 * 3600`,
  enforced in `db.user_for_token`, not merely promised on the client),
- can be revoked with `POST /v1/auth/logout` (this token, or every token for
  the user with `{"all_sessions": true}`).

## Endpoints (verified live 2026-06-18)

The status column shows what the live service returned during the audit.

### Health

| Method | Path | Auth | Purpose | Live |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | none | Liveness probe | `200 {"ok": true, "ts": <int>}` |

`/health` is **not** a route — the health path is `/healthz` (a bare `/health`
returns `404`).

### Auth

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/auth/register` | none | Create or find a user, record a one-time code, send a magic link. Accepts `email`, optional `code_challenge`, optional `redirect`, and optional profile fields (`full_name`, `firm_name`, `aec_role`, `aec_discipline`, `firm_size`, `country`, `signup_source`, `landing_variant`). |
| POST | `/v1/auth/exchange` | none | Exchange `{code, code_verifier}` for a bearer token. PKCE enforced when the code carried a challenge. |
| POST | `/v1/auth/logout` | bearer | Revoke this token, or all of the user's tokens with `{"all_sessions": true}`. |
| GET | `/v1/auth/google/start` | none | Return a Google consent URL. Live: `200`. |
| GET | `/v1/auth/google/callback` | none | Google redirect target; mints an ArchHub code. |

### Account, billing, and hosted AI

| Method | Path | Auth | Purpose | Live (no token) |
| --- | --- | --- | --- | --- |
| GET | `/v1/me` | bearer | The signed-in user's identity, plan, quota, current company, AI mode, and credit state. | `401` |
| GET | `/v1/billing/plans` | none | Public pricing / plan metadata (Model C). | `200` |
| POST | `/v1/billing/checkout` | bearer | Start per-user checkout (`{tier, seats?, annual?}`). | — |
| GET | `/v1/billing/portal` | bearer | Open the customer billing portal. | — |
| POST | `/v1/billing/credits` | bearer | Buy a user-scoped hosted-AI credit pack. | — |
| GET / POST | `/v1/ai-mode` | bearer | Read or set the user's personal `ai_mode`. | — |
| POST | `/v1/chat/completions` | bearer | OpenAI-compatible chat. | `401` |

The public `/v1/billing/plans` response confirms the live pricing model:
provider `stripe`, model `C`, `default_ai_mode: byo_key`, a credit pack of
**$10 = 1,000 messages** rolling over **60 days**, a **30-message trial**, and
three tiers — Solo ($19/seat, 1 seat), Studio ($39/seat, default 5 seats),
Firm ($29/seat, minimum 10 seats, SSO).

**`/v1/chat/completions` behaviour** (handler in `cloud_backend/proxy.py`):

- No bearer → `401`.
- Valid bearer, **BYO-key mode** (the default `ai_mode`) → `402 byo_key_required`.
  The hosted proxy declines and spends no credit; the desktop falls back to the
  user's own provider key. This is the "bring your own key" path — AI cost to
  ArchHub is $0.
- Valid bearer, **hosted mode**, zero credits → `402 out_of_credits` prompting a
  top-up. Over the fair-use quota → `402 quota_exhausted`.

### Companies (multi-seat)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/companies` | bearer | Create a Studio or Firm company; the creator becomes `owner`. |
| GET | `/v1/companies/mine` | bearer | List companies the caller belongs to (with role). |
| GET | `/v1/companies/{id}` | bearer (member) | Company detail and member roster. |
| PATCH | `/v1/companies/{id}` | bearer (owner) | Update owner-only company fields. |
| POST | `/v1/companies/{id}/invites` | bearer (owner/admin) | Create an email-bound invite for `admin` or `member`. |
| POST | `/v1/companies/invites/accept` | bearer | Accept an invite (signed-in email must match the invite email). |
| DELETE | `/v1/companies/{id}/members/{user_id}` | bearer (owner) | Remove a member. |
| POST | `/v1/companies/{id}/transfer-ownership` | bearer (owner) | Hand owner role to an existing member; the previous owner becomes admin. |
| POST | `/v1/companies/{id}/switch` | bearer (member) | Set the caller's active company. |
| GET / POST | `/v1/companies/{id}/ai` and `/ai-mode` | bearer | Read / set the workspace AI mode. |
| POST | `/v1/companies/{id}/seats` | bearer (owner/admin) | Set the seat count (clamped to the tier floor). |
| POST | `/v1/companies/{id}/credits/checkout` | bearer (owner/admin) | Buy workspace hosted-AI credits. |

See `docs/PERMISSIONS.md` for the full roles model.

### Brain, memory, training, marketplace

| Method | Path | Auth | Purpose | Live (no token) |
| --- | --- | --- | --- | --- |
| POST | `/v1/brain/sync` | bearer | Merge the caller's personal brain replica plus any firm/community replicas resolved from membership. | — |
| DELETE | `/v1/brain/sync` | bearer | Delete the caller's cloud replica. | — |
| GET | `/v1/memory/stats` | bearer | Training / memory counters. | `401` |
| GET | `/v1/memory/facts` | bearer | List or search the caller's memory facts (`?q=`, `?limit=`). | — |
| POST / PUT / DELETE | `/v1/memory/facts[/{id}]` | bearer | Add, update, soft-delete a fact owned by the caller. | — |
| GET | `/v1/memory/collective` | bearer | List shared collective facts. | — |
| GET | `/v1/memory/ops` | bearer | The caller's memory-operation audit log. | — |
| `*` | `/marketplace/*` | mixed | Signed skill-pack metadata, blobs, downloads, reviews, abuse reports. | — |
| POST | `/v1/webhooks/stripe` and the Polar webhook | provider-signed | Update plan, seat, subscription, and credit-grant state from billing events. | — |

## Data model — 19 application tables + 1 search index

Source of truth: `cloud_backend/db.py`. The schema declares **19
application-owned tables** plus the application-owned full-text search virtual
table `memory_facts_fts`. (SQLite also creates internal FTS shadow tables; those
are an implementation detail and are not listed here.) Column notation:
`name TYPE [PK] [NOT NULL] [DEFAULT value]`.

The tables, grouped by what they hold:

**Accounts and sessions**

- **`users`** — one row per signed-in account. Solo and trial billing live here;
  a company workspace is selected through `current_company_id`.
  Columns: `id TEXT PK`, `email TEXT NOT NULL UNIQUE`, `created_at INTEGER NOT NULL`,
  `plan TEXT NOT NULL DEFAULT 'trial'`, `stripe_id TEXT`, `period_end INTEGER`,
  `msg_limit INTEGER NOT NULL DEFAULT 30`, `msg_used INTEGER NOT NULL DEFAULT 0`,
  `is_admin INTEGER NOT NULL DEFAULT 0`, `current_company_id TEXT`,
  `full_name TEXT`, `firm_name TEXT`, `aec_role TEXT`, `aec_discipline TEXT`,
  `firm_size TEXT`, `country TEXT`, `signup_source TEXT`, `landing_variant TEXT`,
  `ai_mode TEXT NOT NULL DEFAULT 'byo_key'`, `credit_balance INTEGER NOT NULL DEFAULT 0`,
  `brain_id TEXT` (backfilled to `users.id`).
- **`codes`** — magic-link one-time codes; the PKCE challenge is stored here and
  enforced at exchange. Columns: `code TEXT PK`, `user_id TEXT NOT NULL`,
  `code_challenge TEXT NOT NULL`, `expires_at INTEGER NOT NULL`.
- **`tokens`** — bearer session tokens (no scopes). Columns: `token TEXT PK`,
  `user_id TEXT NOT NULL`, `created_at INTEGER NOT NULL`, `last_used_at INTEGER`,
  `expires_at INTEGER` (created_at + 90 days).
- **`usage_log`** — billing/analytics audit for completed hosted chat turns.
  Columns: `id INTEGER PK`, `user_id TEXT NOT NULL`, `ts INTEGER NOT NULL`,
  `model TEXT NOT NULL`, `input_toks INTEGER NOT NULL`, `output_toks INTEGER NOT NULL`,
  `cost_micros INTEGER NOT NULL`.

**Companies and seats**

- **`companies`** — the billing + membership unit for Studio and Firm plans.
  Columns include `id TEXT PK`, `name`, `slug UNIQUE`, `owner_user_id NOT NULL`,
  `plan DEFAULT 'studio'`, `seat_limit DEFAULT 5`, `billing_email`,
  `stripe_customer_id`, `stripe_subscription_id`, `period_end`, `created_at`,
  `msg_limit DEFAULT 2000`, `msg_used`, `ai_mode DEFAULT 'byo_key'`,
  `credit_balance`.
- **`company_members`** — membership + role per user per company. Columns:
  `company_id TEXT`, `user_id TEXT` (composite PK), `role TEXT DEFAULT 'member'`,
  `joined_at INTEGER NOT NULL`, `invited_by_user_id TEXT`.
- **`company_invites`** — pending/accepted invites; email-bound and single-use.
  Columns: `token TEXT PK`, `company_id`, `email`, `role DEFAULT 'member'`,
  `invited_by_user_id`, `expires_at`, `accepted_at`.
- **`credit_grants`** — the hosted-AI credit-pack ledger. Each grant belongs to
  exactly one actor — a `user_id` or a `company_id`. The live balance is the sum
  of unexpired `remaining` credits, cached on the owning row. Columns:
  `id INTEGER PK`, `user_id`, `company_id`, `messages NOT NULL`,
  `remaining NOT NULL`, `source DEFAULT 'credit_pack'`, `stripe_event_id`,
  `granted_at`, `expires_at`.

**Marketplace**

- **`marketplace_packs`** — signed skill-pack metadata + review state
  (`status DEFAULT 'pending_review'`, `download_count`, signature, pubkey, …).
- **`marketplace_pack_files`** — the signed pack zip blob (`content BLOB`,
  `sha256`, `size_bytes`).
- **`marketplace_reports`** — abuse / takedown reports from signed-in users.

**Brain memory and training**

- **`memory_facts`** — legacy/audit memory-fact table. The live `/v1/memory`
  routes read and write per-user replica fragments; this table remains as the
  audit and migration source, and as the minter of global integer fact IDs.
- **`memory_fact_index`** — maps public integer fact IDs to per-user replica
  fragment IDs.
- **`memory_facts_fts`** — contentless FTS5 search index over fragment text.
- **`collective_memory`** — redacted shared patterns promoted from private facts.
- **`memory_op_log`** — audit log of memory write operations
  (`ADD` / `UPDATE` / `DELETE` / `NOOP`).
- **`memory_access_log`** — audit log of reads of non-private or collective facts.
- **`training_samples`** — captured user / assistant / tool messages that may
  become approved training data (`stage` moves `captured → … → approved`).

**Bookkeeping**

- **`schema_meta`** — one-time migration marker table (`key TEXT PK`,
  `value TEXT NOT NULL`).

## Permissions, roles, and scopes

Full detail lives in `docs/PERMISSIONS.md`. In brief:

- **Company roles** (`company_members.role`): `owner` > `admin` > `member`.
  Owner is created automatically and is the only role that can remove members,
  patch company metadata, or transfer ownership. Owner and admin can invite and
  set seats. Members get read access plus full quota while their active company
  points at that company.
- **Invites** are email-bound and single-use; accepting requires the signed-in
  email to match. Outstanding invites reserve seats against the seat limit.
- **Billing actor**: when `users.current_company_id` is set, chat quota,
  `ai_mode`, and credits resolve against the company; otherwise against the user.
- **Marketplace** review uses `users.is_admin`, not company role.
- **Memory scopes** are `user` / `project` / `company` / `global`; visibility is
  `private` / `shared_company` / `shared_public`. Shared-scope owners are stamped
  server-side so a client cannot impersonate another owner.

## Security

- All production traffic is HTTPS; bearer tokens travel only in `Authorization`.
- Magic-link codes expire and are deleted on exchange; PKCE is enforced when a
  challenge was set.
- Billing webhooks verify provider signatures before mutating state.
- Provider API keys never leave the backend.
- Profile updates are whitelisted — callers cannot set `is_admin` through them.
- Company invites require an email match, not just possession of the token.
- `config.assert_production_ready()` fails startup when `ENV=production` and any
  required auth / email / billing / provider secret is unset.

## Inspecting it yourself

The plain-English, founder-facing guide to the database — including the exact
`fly ssh console` one-liner — is `docs/USER_DATABASE.md`. The desktop-to-cloud
endpoint reference is `docs/CLOUD_API.md`.
