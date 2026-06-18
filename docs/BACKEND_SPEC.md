# ArchHub Cloud - Backend Spec

This document is the contract the desktop client assumes for ArchHub
Cloud. The backend is live at `https://archhub-cloud.fly.dev` and is
deployed from `cloud_backend/` in this repository. The FastAPI app entry
point is `cloud_backend/main.py`; the production data model is the
SQLite schema created by `cloud_backend/db.py:init_schema()`.

The default persistence target is a SQLite database on the Fly.io
persistent volume (`/data/archhub_cloud.db` on Fly, unless
`DATABASE_URL` overrides it). Per-user brain replicas live under
`REPLICAS_ROOT` (`/data/replicas` on Fly by default).

## Runtime

- **Hosting**: Fly.io app `archhub-cloud` (`cloud_backend/fly.toml`).
- **API**: Python FastAPI service in `cloud_backend/main.py`.
- **Database**: SQLite through `cloud_backend/db.py`.
- **Auth**: magic-link sign-in with optional PKCE; optional Google OAuth
  converges onto the same user/code/token flow when configured.
- **Email**: Resend, via `cloud_backend/email_sender.py`.
- **Billing**: Stripe by default, Polar as an alternate provider.
- **Hosted AI**: OpenAI, Anthropic, and Google keys remain server-side;
  hosted mode is metered through `credit_grants`.

## Endpoints

### Auth

- `POST /v1/auth/register` creates or finds a user, records a one-time
  code in `codes`, and sends a magic link.
  Request fields: `email`, optional `code_challenge`, optional
  `redirect`, and optional profile fields
  `full_name`, `firm_name`, `aec_role`, `aec_discipline`, `firm_size`,
  `country`, `signup_source`, `landing_variant`.
- `POST /v1/auth/exchange` exchanges `{code, code_verifier}` for a
  bearer token. Codes with a non-empty challenge require a matching
  verifier.
- `POST /v1/auth/logout` revokes the caller's token by default, or all
  of that user's tokens with `{"all_sessions": true}`.
- `GET /v1/auth/google/start` and `GET /v1/auth/google/callback` are
  available only when both Google OAuth client secrets are configured.

### Account, billing, and hosted AI

- `GET /v1/me` returns the signed-in user's plan, quota, current company,
  AI mode, and credit state.
- `POST /v1/billing/checkout` starts per-user checkout. Body:
  `{tier, seats?, annual?}`.
- `GET /v1/billing/portal` opens the customer billing portal.
- `POST /v1/billing/credits` buys a user-scoped hosted-AI credit pack.
- `GET /v1/ai-mode` and `POST /v1/ai-mode` read or update the user's
  personal `ai_mode`.
- `POST /v1/chat/completions` is OpenAI-compatible and requires a valid
  bearer token. It bills the current actor: the active company when
  `users.current_company_id` is set, otherwise the user row.

### Companies

- `POST /v1/companies` creates a Studio or Firm company and inserts the
  creator as `company_members.role = 'owner'`.
- `GET /v1/companies/mine` lists companies the caller belongs to.
- `GET /v1/companies/{company_id}` returns company detail and members.
- `PATCH /v1/companies/{company_id}` updates owner-only fields.
- `POST /v1/companies/{company_id}/invites` creates an email-bound
  invite for role `admin` or `member`.
- `POST /v1/companies/invites/accept` accepts a valid invite only when
  the signed-in email matches the invite email.
- `DELETE /v1/companies/{company_id}/members/{user_id}` removes a
  member; live code requires the actor to be owner.
- `POST /v1/companies/{company_id}/transfer-ownership` transfers owner
  role to an existing member and demotes the previous owner to admin.
- `POST /v1/companies/{company_id}/switch` sets the caller's
  `current_company_id` after verifying membership.
- `GET /v1/companies/{company_id}/ai`, `POST /v1/companies/{company_id}/ai`,
  `POST /v1/companies/{company_id}/seats`, and
  `POST /v1/companies/{company_id}/credits` manage workspace AI mode,
  seat limit, and hosted-AI credit checkout.

### Brain, memory, training, and marketplace

- `POST /v1/brain/sync` merges the caller's personal brain replica and
  any shared firm/community replicas the server resolves from membership.
- `DELETE /v1/brain/sync` deletes the caller's cloud replica.
- `/v1/memory/*` and `/v1/training/*` persist memory facts, memory
  operations, access logs, and training samples.
- `/marketplace/*` stores signed skill packs, review state, pack blobs,
  downloads, and abuse reports.
- `POST /v1/webhooks/stripe` and the Polar webhook path update plan,
  seat, subscription, and credit-grant state from billing events.

## Data Model

Source of truth: `cloud_backend/db.py`. This section was regenerated
from a temporary database created by `db.init_schema()`, so it includes
the declarative `SCHEMA` plus the idempotent `ALTER TABLE` migrations.
SQLite's internal FTS shadow tables are intentionally omitted; the
application-owned virtual table `memory_facts_fts` is included.

Column notation: `name TYPE [PK] [NOT NULL] [DEFAULT value]`.

### `users`

One row per signed-in account. Solo and trial billing live here; company
workspaces are selected through `current_company_id`.

Columns:

- `id TEXT PK`
- `email TEXT NOT NULL UNIQUE`
- `created_at INTEGER NOT NULL`
- `plan TEXT NOT NULL DEFAULT 'trial'`
- `stripe_id TEXT`
- `period_end INTEGER`
- `msg_limit INTEGER NOT NULL DEFAULT 30`
- `msg_used INTEGER NOT NULL DEFAULT 0`
- `is_admin INTEGER NOT NULL DEFAULT 0`
- `current_company_id TEXT`
- `full_name TEXT`
- `firm_name TEXT`
- `aec_role TEXT`
- `aec_discipline TEXT`
- `firm_size TEXT`
- `country TEXT`
- `signup_source TEXT`
- `landing_variant TEXT`
- `ai_mode TEXT NOT NULL DEFAULT 'byo_key'`
- `credit_balance INTEGER NOT NULL DEFAULT 0`
- `brain_id TEXT`

Migration-added columns: `is_admin`, `current_company_id`, profile
fields, `ai_mode`, `credit_balance`, and `brain_id`. `brain_id` is
backfilled to `users.id`.

### `codes`

Magic-link one-time codes. PKCE challenge is stored here and enforced at
exchange time when non-empty.

Columns:

- `code TEXT PK`
- `user_id TEXT NOT NULL`
- `code_challenge TEXT NOT NULL`
- `expires_at INTEGER NOT NULL`

Index: `idx_codes_user(user_id)`.

### `tokens`

Bearer session tokens. Tokens do not carry scopes; they identify a user
and expire server-side.

Columns:

- `token TEXT PK`
- `user_id TEXT NOT NULL`
- `created_at INTEGER NOT NULL`
- `last_used_at INTEGER`
- `expires_at INTEGER`

Index: `idx_tokens_user(user_id)`. `expires_at` is migration-added and
backfilled to `created_at + TOKEN_TTL_SECONDS` for old rows.

### `usage_log`

Billing and analytics audit for completed hosted chat turns.

Columns:

- `id INTEGER PK`
- `user_id TEXT NOT NULL`
- `ts INTEGER NOT NULL`
- `model TEXT NOT NULL`
- `input_toks INTEGER NOT NULL`
- `output_toks INTEGER NOT NULL`
- `cost_micros INTEGER NOT NULL`

Index: `idx_usage_user_ts(user_id, ts)`.

### `companies`

Billing and membership unit for Studio and Firm plans. Solo users do not
need a company row.

Columns:

- `id TEXT PK`
- `name TEXT NOT NULL`
- `slug TEXT UNIQUE`
- `owner_user_id TEXT NOT NULL`
- `plan TEXT NOT NULL DEFAULT 'studio'`
- `seat_limit INTEGER NOT NULL DEFAULT 5`
- `billing_email TEXT`
- `stripe_customer_id TEXT`
- `stripe_subscription_id TEXT`
- `period_end INTEGER`
- `created_at INTEGER NOT NULL`
- `msg_limit INTEGER NOT NULL DEFAULT 2000`
- `msg_used INTEGER NOT NULL DEFAULT 0`
- `ai_mode TEXT NOT NULL DEFAULT 'byo_key'`
- `credit_balance INTEGER NOT NULL DEFAULT 0`

Index: `idx_companies_owner(owner_user_id)`. Migration-added columns:
`msg_limit`, `msg_used`, `ai_mode`, and `credit_balance`.

### `company_members`

Membership and authorization role per user per company.

Columns:

- `company_id TEXT PK NOT NULL`
- `user_id TEXT PK NOT NULL`
- `role TEXT NOT NULL DEFAULT 'member'`
- `joined_at INTEGER NOT NULL`
- `invited_by_user_id TEXT`

Composite primary key: `(company_id, user_id)`. Index:
`idx_company_members_user(user_id)`.

### `company_invites`

Pending and accepted company invitations. Tokens are email-bound and
single-use.

Columns:

- `token TEXT PK`
- `company_id TEXT NOT NULL`
- `email TEXT NOT NULL`
- `role TEXT NOT NULL DEFAULT 'member'`
- `invited_by_user_id TEXT NOT NULL`
- `expires_at INTEGER NOT NULL`
- `accepted_at INTEGER`

Indexes: `idx_company_invites_company(company_id)`,
`idx_company_invites_email(email)`.

### `credit_grants`

Hosted-AI credit-pack ledger. Each grant belongs to exactly one actor in
normal operation: either a `user_id` or a `company_id`. Live balances are
the sum of unexpired `remaining` credits and are cached on the owning
`users` or `companies` row.

Columns:

- `id INTEGER PK`
- `user_id TEXT`
- `company_id TEXT`
- `messages INTEGER NOT NULL`
- `remaining INTEGER NOT NULL`
- `source TEXT NOT NULL DEFAULT 'credit_pack'`
- `stripe_event_id TEXT`
- `granted_at INTEGER NOT NULL`
- `expires_at INTEGER NOT NULL`

Indexes: unique `idx_credit_grants_event(stripe_event_id)`,
`idx_credit_grants_user(user_id, expires_at)`,
`idx_credit_grants_company(company_id, expires_at)`.

### `marketplace_packs`

Signed skill-pack metadata and review state.

Columns:

- `id TEXT PK`
- `slug TEXT NOT NULL UNIQUE`
- `title TEXT NOT NULL`
- `description TEXT NOT NULL DEFAULT ''`
- `version TEXT NOT NULL DEFAULT '0.1.0'`
- `category TEXT NOT NULL DEFAULT ''`
- `author_user_id TEXT NOT NULL`
- `manifest_json TEXT NOT NULL`
- `signature TEXT NOT NULL`
- `pubkey TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'pending_review'`
- `download_count INTEGER NOT NULL DEFAULT 0`
- `created_at INTEGER NOT NULL`
- `updated_at INTEGER NOT NULL`
- `approved_at INTEGER`
- `approved_by TEXT`
- `rejected_reason TEXT`

Indexes: `idx_packs_status(status)`, `idx_packs_author(author_user_id)`.

### `marketplace_pack_files`

The signed pack zip blob for a marketplace pack.

Columns:

- `pack_id TEXT PK`
- `content BLOB NOT NULL`
- `sha256 TEXT NOT NULL`
- `size_bytes INTEGER NOT NULL`
- `created_at INTEGER NOT NULL`

### `marketplace_reports`

Abuse or takedown reports from signed-in users.

Columns:

- `id INTEGER PK`
- `pack_id TEXT NOT NULL`
- `reporter_user_id TEXT NOT NULL`
- `reason TEXT NOT NULL`
- `created_at INTEGER NOT NULL`

Index: `idx_reports_pack(pack_id)`.

### `training_samples`

Captured user, assistant, and tool messages that may become approved
training data.

Columns:

- `id INTEGER PK`
- `user_id TEXT NOT NULL`
- `company_id TEXT`
- `role TEXT NOT NULL`
- `content TEXT NOT NULL`
- `tool_trace TEXT NOT NULL DEFAULT '[]'`
- `intent TEXT NOT NULL DEFAULT ''`
- `stage TEXT NOT NULL DEFAULT 'captured'`
- `judge_score REAL`
- `redacted_at INTEGER`
- `judged_at INTEGER`
- `created_at INTEGER NOT NULL`

Indexes: `idx_training_user_stage(user_id, stage)`,
`idx_training_created(created_at)`.

### `memory_facts`

Legacy/audit memory fact table. The unified cloud brain reads and writes
per-user replica fragments; this table remains as an audit and migration
source.

Columns:

- `id INTEGER PK`
- `user_id TEXT NOT NULL`
- `company_id TEXT`
- `project_id TEXT`
- `scope TEXT NOT NULL DEFAULT 'user'`
- `visibility TEXT NOT NULL DEFAULT 'private'`
- `subject TEXT NOT NULL DEFAULT ''`
- `predicate TEXT NOT NULL DEFAULT ''`
- `object TEXT NOT NULL DEFAULT ''`
- `text TEXT NOT NULL`
- `confidence REAL NOT NULL DEFAULT 0.7`
- `source_sample_id INTEGER`
- `valid_from INTEGER NOT NULL`
- `valid_until INTEGER`
- `created_at INTEGER NOT NULL`
- `last_reinforced_at INTEGER NOT NULL`
- `reinforce_count INTEGER NOT NULL DEFAULT 1`
- `embedding BLOB`
- `embedding_model TEXT`

Indexes: `idx_memory_user_scope(user_id, scope, valid_until)`,
`idx_memory_visibility(visibility)`, `idx_memory_project(project_id)`.

### `memory_fact_index`

Derived lookup from public integer fact IDs to canonical per-user
replica fragment IDs.

Columns:

- `id INTEGER PK`
- `user_id TEXT NOT NULL`
- `frag_id TEXT NOT NULL`
- `embedding BLOB`
- `embedding_model TEXT`
- `created_at INTEGER NOT NULL`

Unique constraint: `(user_id, frag_id)`. Index: `idx_mfi_user(user_id)`.

### `memory_facts_fts`

Contentless FTS5 table over canonical fragment text, keyed by
`memory_fact_index.id`.

Columns:

- `text ANY`

Old deployments with external-content FTS triggers are migrated by
dropping the legacy triggers and rebuilding this contentless shape.

### `collective_memory`

Redacted shared memory patterns promoted from private facts.

Columns:

- `id INTEGER PK`
- `text TEXT NOT NULL`
- `domain TEXT NOT NULL DEFAULT 'aec.general'`
- `contributing_user_id TEXT NOT NULL`
- `contributing_company_id TEXT`
- `source_fact_id INTEGER`
- `redaction_policy TEXT NOT NULL DEFAULT 'transform'`
- `access_policy TEXT NOT NULL DEFAULT 'public'`
- `confidence REAL NOT NULL DEFAULT 0.7`
- `upvotes INTEGER NOT NULL DEFAULT 0`
- `downvotes INTEGER NOT NULL DEFAULT 0`
- `promoted_at INTEGER NOT NULL`
- `embedding BLOB`

Index: `idx_collective_domain(domain)`.

### `memory_op_log`

Audit log for memory write operations.

Columns:

- `id INTEGER PK`
- `user_id TEXT NOT NULL`
- `fact_id INTEGER`
- `op TEXT NOT NULL`
- `source_sample_id INTEGER`
- `rationale TEXT NOT NULL DEFAULT ''`
- `before_text TEXT`
- `after_text TEXT`
- `ts INTEGER NOT NULL`

Index: `idx_memory_op_user(user_id, ts)`.

### `memory_access_log`

Audit log for reads of non-private facts or collective memory.

Columns:

- `id INTEGER PK`
- `reader_user_id TEXT NOT NULL`
- `fact_id INTEGER`
- `collective_id INTEGER`
- `purpose TEXT NOT NULL DEFAULT 'retrieve'`
- `ts INTEGER NOT NULL`

Index: `idx_memory_access_reader(reader_user_id, ts)`.

### `schema_meta`

One-time migration marker table.

Columns:

- `key TEXT PK`
- `value TEXT NOT NULL`

## Permissions and Roles

### Bearer tokens

All authenticated API calls use `Authorization: Bearer <token>`. The
token is looked up in `tokens`, checked for expiry by `db.user_for_token`,
and resolves to exactly one row in `users`.

There is no production token-scope table or `tokens.scope` column.
Bearer tokens are user session credentials, not OAuth-style scoped
grants. Effective permissions are derived from the authenticated user,
the current route, company membership rows, marketplace admin state, and
memory/brain scope checks.

Token lifecycle:

- `db.issue_token()` mints a random `ah_live_...` token and sets
  `expires_at = created_at + TOKEN_TTL_SECONDS` (90 days).
- `POST /v1/auth/logout` deletes the current token, or all of the
  user's tokens when `all_sessions` is true.
- `last_used_at` is updated on successful use.

### Company roles

Company roles live in `company_members.role`. Live accepted values are:

- `owner`: created automatically when a company is created. The owner
  can update company metadata, invite admins or members, remove members
  except themselves, transfer ownership, set seat count, set workspace
  AI mode, buy workspace credits, read company detail, and switch into
  the company.
- `admin`: can invite admins or members, set workspace AI mode, set seat
  count, buy workspace credits, read company detail, and switch into the
  company. Live removal, metadata patch, and ownership transfer routes
  require `owner`.
- `member`: can read company detail, list their memberships, switch into
  the company, read workspace AI status, and use company billing/quota
  while `users.current_company_id` points to that company.

Invite rules:

- Only `owner` or `admin` can create invites.
- Invite role must be `admin` or `member`; invites cannot mint a new
  owner.
- Outstanding unaccepted, unexpired invites reserve seats. Seat-limit
  checks count accepted members plus those outstanding invite emails.
- Accepting an invite requires a valid bearer token whose user email
  matches the invite email after normalization.
- Invites are single-use (`accepted_at`) and expire at `expires_at`.

Ownership rules:

- `companies.owner_user_id` is the owner pointer.
- Transferring ownership requires current owner role and a target user
  who is already a company member.
- Transfer promotes the target membership to `owner` and demotes the
  previous owner to `admin`.
- Owners cannot remove themselves; transfer first, then remove.

### Billing actor and hosted-AI mode

`users.current_company_id` selects the active company workspace. The
switch route verifies `company_members` membership before setting it.

When `current_company_id` is set, chat quota, `ai_mode`, and hosted-AI
credits are resolved against the company row and company
`credit_grants`. Otherwise they are resolved against the user row and
user `credit_grants`.

`ai_mode` is `byo_key` by default. Hosted inference requires `hosted`
mode plus unexpired credit grants. Credit packs grant 1,000 messages and
roll over for 60 days per `config.CREDIT_PACK`.

### Marketplace admin

Marketplace review uses `users.is_admin`, not company role.

- Anonymous users can browse and download approved packs only.
- Signed-in authors can see their own pending or rejected packs.
- Admin users can list the full review pipeline and approve or reject
  packs.
- Any signed-in user can report a pack.

### Memory and brain scopes

Memory fact scope values are `user`, `project`, `company`, and `global`.
Visibility values are `private`, `shared_company`, and `shared_public`.
Memory write ops are `ADD`, `UPDATE`, `DELETE`, and `NOOP`.

Brain sync has its own replica-level sharing:

- User-scope brain data stays private to the bearer-token user.
- Firm/company fanout is resolved server-side from company membership;
  clients do not get to choose arbitrary firm replicas.
- Firm and community fragment `owner_user` is stamped server-side from
  the authenticated user so a client cannot impersonate another owner.

## Quotas and Pricing Model C

Pricing and seat numbers are source-of-truth in `cloud_backend/config.py`.

- Solo: per-user plan, one seat, billed on `users`.
- Studio: company plan, default 5 seats, seats can change a la carte.
- Firm: company plan, minimum 10 seats, SSO flag in pricing metadata.
- Hosted AI is decoupled from base plan. `byo_key` mode has no hosted
  AI charge to ArchHub. `hosted` mode spends credit grants.
- Legacy `msg_limit` and `msg_used` remain as fair-use quota fields and
  are actor-aware (`users` or `companies`).

## Security

- All production traffic is HTTPS.
- Bearer tokens are sent only in `Authorization` headers.
- Magic-link codes expire and are deleted when exchanged.
- PKCE is enforced for codes created with a challenge.
- Webhooks verify provider signatures before mutating billing state.
- Provider API keys never leave the backend.
- Profile updates are whitelisted; callers cannot set `is_admin` through
  profile fields.
- Company invites require email match, not just token possession.
- Brain sync stamps shared-scope owners server-side.

## Production Readiness

`config.assert_production_ready()` fails startup when `ENV=production`
and required auth, email, billing, or provider keys are unset. Fly's
deployment leaves `ENV` unset until secrets are provisioned so `/healthz`
can stay reachable during setup.

Before changing this contract, update `cloud_backend/db.py`, tests, and
this document in the same branch. Schema-altering changes must be
idempotent because `init_schema()` runs on every startup.
