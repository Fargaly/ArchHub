"""SQLite DAO for the ArchHub Cloud backend.

Schema matches docs/BACKEND_SPEC.md:
  users     — one row per signed-up email
  codes     — magic-link one-time codes (5 min TTL)
  tokens    — bearer tokens issued after exchange
  usage_log — one row per chat turn for billing audit

Single-file SQLite is the right call at <10K users. Migrating to
Postgres later is a sed-style schema lift; the DAO surface stays
identical.

NOT thread-safe by default — every coroutine that wants the
connection grabs it via `connect()` which returns a fresh one
(SQLite handles per-conn locking). Concurrency is fine at hundreds
of req/sec on a single instance.
"""
from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Iterable, Optional

import config


# Bearer-token lifetime. Single source of truth — auth.exchange_code
# returns this same value to the client as `expires_at`, and
# issue_token stamps `tokens.expires_at = created_at + TOKEN_TTL_SECONDS`
# so the client's expiry and the server's enforced expiry AGREE.
# A token past this is rejected by user_for_token (server-side enforced).
TOKEN_TTL_SECONDS = 90 * 24 * 3600   # 90 days


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    created_at    INTEGER NOT NULL,
    plan          TEXT NOT NULL DEFAULT 'trial',
    stripe_id     TEXT,
    period_end    INTEGER,
    msg_limit     INTEGER NOT NULL DEFAULT 30,
    msg_used      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS codes (
    code            TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    code_challenge  TEXT NOT NULL,
    expires_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS tokens (
    token         TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER,
    -- Absolute server-side expiry (epoch seconds). A token whose
    -- expires_at is in the past fails auth in user_for_token — the
    -- 90-day lifetime is enforced HERE, not just promised client-side.
    expires_at    INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    model       TEXT NOT NULL,
    input_toks  INTEGER NOT NULL,
    output_toks INTEGER NOT NULL,
    cost_micros INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_codes_user ON codes(user_id);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage_log(user_id, ts);

-- Companies / multi-seat -------------------------------------------------
-- A "company" is a billing + membership unit. The Studio ($79) and Firm
-- ($299) plans pay per company and ship N seats. Solo users continue to
-- bill on the legacy `users.plan` column — they don't need a company row.
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE,
    owner_user_id   TEXT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'studio',
    seat_limit      INTEGER NOT NULL DEFAULT 5,
    billing_email   TEXT,
    stripe_customer_id  TEXT,
    stripe_subscription_id TEXT,
    period_end      INTEGER,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS company_members (
    company_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    joined_at       INTEGER NOT NULL,
    invited_by_user_id  TEXT,
    PRIMARY KEY (company_id, user_id),
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS company_invites (
    token           TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    email           TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    invited_by_user_id TEXT NOT NULL,
    expires_at      INTEGER NOT NULL,
    accepted_at     INTEGER,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_companies_owner ON companies(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_company_members_user ON company_members(user_id);
CREATE INDEX IF NOT EXISTS idx_company_invites_company ON company_invites(company_id);
CREATE INDEX IF NOT EXISTS idx_company_invites_email ON company_invites(email);

-- Hosted-AI credit grants (Model C, founder 2026-05-31) -----------------
-- Each purchased credit pack ($10 = 1,000 messages) inserts ONE row.
-- `remaining` decrements one-per-message while the workspace is in
-- `hosted` AI mode; `expires_at` is granted_at + CREDIT_PACK.rollover_days
-- (60 days) so unused credits roll over then lapse. The live balance is
-- SUM(remaining) over rows with expires_at > now (see credit_balance()).
-- Exactly one of (user_id, company_id) identifies the owning workspace:
-- solo/trial actors grant on user_id; company workspaces on company_id —
-- mirroring the msg_used billing-actor split.
CREATE TABLE IF NOT EXISTS credit_grants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT,
    company_id  TEXT,
    messages    INTEGER NOT NULL,       -- size of the pack as purchased
    remaining   INTEGER NOT NULL,       -- decremented per hosted message
    source      TEXT NOT NULL DEFAULT 'credit_pack',
    stripe_event_id TEXT,               -- idempotency for webhook replays
    granted_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,       -- granted_at + rollover_days
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_credit_grants_user ON credit_grants(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_credit_grants_company ON credit_grants(company_id, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_grants_event ON credit_grants(stripe_event_id);

-- Marketplace v1 ----------------------------------------------------------
-- Architects upload signed skill packs (zip + Ed25519 signature). Packs
-- start as 'pending_review'; an admin approves before they appear in the
-- public listing. The signed zip is stored as a blob in
-- marketplace_pack_files so we don't depend on external object storage
-- for v1. (S3/R2 migration is Phase 2 — the column shape stays the same;
-- swap the BLOB for an `object_url TEXT`.)
CREATE TABLE IF NOT EXISTS marketplace_packs (
    id              TEXT PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    version         TEXT NOT NULL DEFAULT '0.1.0',
    category        TEXT NOT NULL DEFAULT '',
    author_user_id  TEXT NOT NULL,
    manifest_json   TEXT NOT NULL,
    signature       TEXT NOT NULL,
    pubkey          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending_review',
    download_count  INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    approved_at     INTEGER,
    approved_by     TEXT,
    rejected_reason TEXT,
    FOREIGN KEY (author_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS marketplace_pack_files (
    pack_id     TEXT PRIMARY KEY,
    content     BLOB NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (pack_id) REFERENCES marketplace_packs(id)
);

CREATE TABLE IF NOT EXISTS marketplace_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id           TEXT NOT NULL,
    reporter_user_id  TEXT NOT NULL,
    reason            TEXT NOT NULL,
    created_at        INTEGER NOT NULL,
    FOREIGN KEY (pack_id) REFERENCES marketplace_packs(id),
    FOREIGN KEY (reporter_user_id) REFERENCES users(id)
);

-- ── Memory architecture (ADR-002, v1.3.4+) ──────────────────────────
--
-- Five tiers; this DB layer implements three of them:
--
--   EPISODIC   = training_samples (already above)
--   SEMANTIC   = memory_facts + memory_facts_fts (below)
--   COLLECTIVE = collective_memory (below)
--
-- HOT lives in-process on the desktop; PROCEDURAL is the LoRA-trained
-- apprentice that ships when ADR-001 Stack A pivot point hits.
--
-- Every write to memory_facts is logged in memory_op_log so the user
-- can audit "why does ArchHub remember X?" and rewind.

CREATE TABLE IF NOT EXISTS memory_facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT NOT NULL,
    company_id          TEXT,
    project_id          TEXT,
    -- 'user' | 'project' | 'company' | 'global'
    scope               TEXT NOT NULL DEFAULT 'user',
    -- 'private' | 'shared_company' | 'shared_public'
    visibility          TEXT NOT NULL DEFAULT 'private',
    -- Triple form (sparse — text is the canonical form)
    subject             TEXT NOT NULL DEFAULT '',
    predicate           TEXT NOT NULL DEFAULT '',
    object              TEXT NOT NULL DEFAULT '',
    -- Canonical denormalised form for FTS5 + display
    text                TEXT NOT NULL,
    -- 0.0 - 1.0, raised by reinforce
    confidence          REAL NOT NULL DEFAULT 0.7,
    -- Provenance: which approved sample this came from (NULL when manual)
    source_sample_id    INTEGER,
    -- Temporal validity. valid_until=NULL means current.
    valid_from          INTEGER NOT NULL,
    valid_until         INTEGER,
    created_at          INTEGER NOT NULL,
    last_reinforced_at  INTEGER NOT NULL,
    reinforce_count     INTEGER NOT NULL DEFAULT 1,
    -- Optional sentence-transformer embedding (384-dim MiniLM) as BLOB
    embedding           BLOB,
    embedding_model     TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (source_sample_id) REFERENCES training_samples(id)
);

-- ── Unified per-user brain (cloud-brain-unify 2026-05-31) ────────────
-- ONE canonical per-user store: the replica `fragments` table
-- (brain_replica.py → data/replicas/<user_id>/brain.db). A "memory fact"
-- IS a fragment. `memory_facts` above is RETAINED for audit + as the
-- one-time migration source, but the /v1/memory DAO no longer reads/writes
-- it — it reads/writes the user's replica fragments so a fact added via
-- /v1/memory and a fragment synced via /v1/brain/sync share one table.
--
-- `memory_fact_index` is the DERIVED index over those fragments (NOT a
-- second source of truth): it mints the global-unique INTEGER fact-id the
-- /v1/memory/facts/{id} API has always exposed, maps it to the per-user
-- replica fragment (user_id, frag_id), and carries the optional embedding.
-- The canonical CONTENT (text/scope/visibility/confidence/valid_until/…)
-- lives in the fragment; this table is the lookup + search spine only.
CREATE TABLE IF NOT EXISTS memory_fact_index (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    frag_id         TEXT NOT NULL,      -- fragment id in the user's replica
    embedding       BLOB,
    embedding_model TEXT,
    created_at      INTEGER NOT NULL,
    UNIQUE (user_id, frag_id)
);
CREATE INDEX IF NOT EXISTS idx_mfi_user ON memory_fact_index(user_id);

-- Migration / schema markers (mirrors the per-replica meta table). One row
-- per one-time migration so a re-run is a guarded no-op.
CREATE TABLE IF NOT EXISTS schema_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- FTS5 index over the canonical fragment text, keyed on the index id (the
-- public fact-id). Contentless external-content table — we own the rows
-- explicitly from the DAO (insert/update/delete), so no triggers on the
-- legacy memory_facts table. Keeps search fast on pure-SQLite deploys
-- until pgvector lands (ADR-002 §"revisit").
CREATE VIRTUAL TABLE IF NOT EXISTS memory_facts_fts USING fts5(
    text,
    content='',
    content_rowid='id'
);

-- Per arXiv 2505.18279 Collaborative Memory. Anonymised + redacted
-- patterns promoted from private memory_facts. Searchable by everyone
-- subject to access_policy.
CREATE TABLE IF NOT EXISTS collective_memory (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    text                    TEXT NOT NULL,
    domain                  TEXT NOT NULL DEFAULT 'aec.general',
    -- Provenance audit. user_id kept on contributor side, NOT exposed in queries.
    contributing_user_id    TEXT NOT NULL,
    contributing_company_id TEXT,
    source_fact_id          INTEGER,
    redaction_policy        TEXT NOT NULL DEFAULT 'transform',
    -- 'public' | 'architects_only' | 'studio_tier+'
    access_policy           TEXT NOT NULL DEFAULT 'public',
    confidence              REAL NOT NULL DEFAULT 0.7,
    upvotes                 INTEGER NOT NULL DEFAULT 0,
    downvotes               INTEGER NOT NULL DEFAULT 0,
    promoted_at             INTEGER NOT NULL,
    embedding               BLOB,
    FOREIGN KEY (contributing_user_id) REFERENCES users(id),
    FOREIGN KEY (source_fact_id) REFERENCES memory_facts(id)
);

-- Mem0-style op log. Every write to memory_facts (ADD/UPDATE/DELETE/NOOP)
-- gets one row here. Lets the user audit "what did ArchHub learn from
-- session X" and rewind.
CREATE TABLE IF NOT EXISTS memory_op_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    fact_id         INTEGER,
    op              TEXT NOT NULL,         -- 'ADD' | 'UPDATE' | 'DELETE' | 'NOOP'
    source_sample_id INTEGER,
    rationale       TEXT NOT NULL DEFAULT '',
    before_text     TEXT,
    after_text      TEXT,
    ts              INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Per arXiv 2505.18279 audit log. Every READ of a non-private fact
-- gets recorded so reviews can trace which user pulled which fact.
CREATE TABLE IF NOT EXISTS memory_access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reader_user_id TEXT NOT NULL,
    fact_id     INTEGER,                   -- NULL for collective_memory reads
    collective_id INTEGER,                 -- NULL for memory_facts reads
    purpose     TEXT NOT NULL DEFAULT 'retrieve',
    ts          INTEGER NOT NULL,
    FOREIGN KEY (reader_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS training_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    company_id      TEXT,                  -- NULL for solo / pre-team capture
    role            TEXT NOT NULL,         -- 'user' | 'assistant' | 'tool'
    content         TEXT NOT NULL,
    tool_trace      TEXT NOT NULL DEFAULT '[]',
                                            -- JSON array of {name, args, result}
    intent          TEXT NOT NULL DEFAULT '',
    stage           TEXT NOT NULL DEFAULT 'captured',
                                            -- captured | redacted | judged | rejected | approved
    judge_score     REAL,                  -- 0..1 from instructor model
    redacted_at     INTEGER,
    judged_at       INTEGER,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_packs_status ON marketplace_packs(status);
CREATE INDEX IF NOT EXISTS idx_packs_author ON marketplace_packs(author_user_id);
CREATE INDEX IF NOT EXISTS idx_reports_pack ON marketplace_reports(pack_id);
CREATE INDEX IF NOT EXISTS idx_training_user_stage ON training_samples(user_id, stage);
CREATE INDEX IF NOT EXISTS idx_training_created ON training_samples(created_at);
CREATE INDEX IF NOT EXISTS idx_memory_user_scope ON memory_facts(user_id, scope, valid_until);
CREATE INDEX IF NOT EXISTS idx_memory_visibility ON memory_facts(visibility);
CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_facts(project_id);
CREATE INDEX IF NOT EXISTS idx_memory_op_user ON memory_op_log(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_memory_access_reader ON memory_access_log(reader_user_id, ts);
CREATE INDEX IF NOT EXISTS idx_collective_domain ON collective_memory(domain);
"""


@contextmanager
def connect():
    """Yield a SQLite connection. Caller MUST use a context manager:
        with connect() as con: ..."""
    con = sqlite3.connect(config.DATABASE_URL,
                           detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_schema() -> None:
    """Apply schema. Idempotent — safe to call on every startup."""
    with connect() as con:
        con.executescript(SCHEMA)
        # is_admin was added in v0.40 for marketplace review. ALTER TABLE
        # is wrapped in try/except so the SCHEMA above stays declarative
        # for fresh databases while existing deployments self-migrate.
        try:
            con.execute(
                "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            # Column already exists — idempotent re-run.
            pass
        # Multi-seat: which company is the user operating under in the
        # desktop app right now? NULL for solo users.
        for ddl in (
            "ALTER TABLE users ADD COLUMN current_company_id TEXT",
            # Customer-profile fields captured at signup / dashboard edit.
            "ALTER TABLE users ADD COLUMN full_name TEXT",
            "ALTER TABLE users ADD COLUMN firm_name TEXT",
            "ALTER TABLE users ADD COLUMN aec_role TEXT",
            "ALTER TABLE users ADD COLUMN aec_discipline TEXT",
            "ALTER TABLE users ADD COLUMN firm_size TEXT",
            "ALTER TABLE users ADD COLUMN country TEXT",
            "ALTER TABLE users ADD COLUMN signup_source TEXT",
            "ALTER TABLE users ADD COLUMN landing_variant TEXT",
            # v1.3.3: per-company quota tracking. Studio plan seeds 2000,
            # Firm plan seeds 1_000_000 (fair-use, throttled by per-min
            # rate limit). Webhook + create_company set the right value.
            "ALTER TABLE companies ADD COLUMN msg_limit INTEGER NOT NULL DEFAULT 2000",
            "ALTER TABLE companies ADD COLUMN msg_used INTEGER NOT NULL DEFAULT 0",
            # Server-side token expiry. Pre-expiry deploys created the
            # tokens table without this column; add it here for them.
            # (Fresh DBs already have it from SCHEMA above — the
            # try/except makes the duplicate add a no-op.)
            "ALTER TABLE tokens ADD COLUMN expires_at INTEGER",
            # Model C (founder 2026-05-31): AI mode + hosted credit
            # balance per workspace. `ai_mode` is 'byo_key' (default,
            # launch-cheap — user's own key, no hosted limit) or
            # 'hosted' (we run the LLM, metered against credit_grants).
            # `credit_balance` is a denormalised cache of the live
            # SUM(remaining) over non-expired credit_grants — kept in
            # sync by grant_credits / consume_credit so a hot read
            # (the per-message gate) avoids the aggregate query.
            "ALTER TABLE companies ADD COLUMN ai_mode TEXT NOT NULL DEFAULT 'byo_key'",
            "ALTER TABLE companies ADD COLUMN credit_balance INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN ai_mode TEXT NOT NULL DEFAULT 'byo_key'",
            "ALTER TABLE users ADD COLUMN credit_balance INTEGER NOT NULL DEFAULT 0",
            # MAKE-IT-REAL (founder 2026-05-31): every account gets a brain
            # slot. `brain_id` is the explicit, queryable link from a users
            # row to its per-user cloud brain replica (brain_replica.py →
            # <replicas_root>/<brain_id>/brain.db). It equals users.id (the
            # replica dir is keyed on the user id) so the mapping is 1:1 and
            # derivable, but storing it turns "does this account have a
            # brain?" into a column lookup. Fresh DBs get it from the
            # backfill below; existing deployments self-migrate via this
            # ALTER. Nullable because ALTER can't add a NOT NULL column with
            # a per-row default — the backfill fills it immediately after.
            "ALTER TABLE users ADD COLUMN brain_id TEXT",
        ):
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                # Column already exists — idempotent re-run.
                pass
        # Backfill: any existing token row with a NULL expires_at (rows
        # issued before this migration, when tokens were immortal) gets
        # a real expiry of created_at + the 90-day TTL. After this runs
        # once, every token has an enforced expiry — no immortal tokens
        # survive the upgrade. Idempotent: only touches NULL rows.
        con.execute(
            "UPDATE tokens SET expires_at = created_at + ? "
            "WHERE expires_at IS NULL",
            (TOKEN_TTL_SECONDS,),
        )
        # Model C backfill: re-derive each workspace's cached
        # credit_balance from the live (non-expired) credit_grants so the
        # denormalised column can never disagree with the grant ledger
        # after an upgrade. Same idempotent shape as the token backfill —
        # safe on every boot. Workspaces with no grants settle to 0.
        now = int(time.time())
        con.execute(
            "UPDATE users SET credit_balance = COALESCE("
            "  (SELECT SUM(remaining) FROM credit_grants g"
            "   WHERE g.user_id = users.id AND g.expires_at > ?), 0)",
            (now,),
        )
        con.execute(
            "UPDATE companies SET credit_balance = COALESCE("
            "  (SELECT SUM(remaining) FROM credit_grants g"
            "   WHERE g.company_id = companies.id AND g.expires_at > ?), 0)",
            (now,),
        )
        # brain_id backfill: every EXISTING user gets their brain link set to
        # their own id (the replica is keyed on users.id). Pre-MAKE-IT-REAL
        # rows had brain_id NULL; after this runs once every account has a
        # populated brain slot — no account is left without a brain link on
        # upgrade. Idempotent: only touches NULL rows, so a returning user is
        # never re-stamped. (provision_brain at exchange time also sets this
        # for new sign-ins; this backfill covers users who never re-login.)
        con.execute(
            "UPDATE users SET brain_id = id WHERE brain_id IS NULL")
        # cloud-brain-unify (2026-05-31): the FTS index is now a CONTENTLESS
        # external table owned explicitly by the DAO (keyed on the public
        # fact-id), not auto-synced from the legacy memory_facts table.
        # Existing DBs created the old `content='memory_facts'` FTS + its
        # three triggers — drop them and rebuild the contentless table so
        # search runs against the unified store. A fresh DB already has the
        # right shape from SCHEMA; these statements are then no-ops.
        for legacy_trigger in (
            "memory_facts_ai", "memory_facts_ad", "memory_facts_au",
        ):
            try:
                con.execute(f"DROP TRIGGER IF EXISTS {legacy_trigger}")
            except sqlite3.OperationalError:
                pass
        # If the FTS table was created with external content (old shape), its
        # schema string names content='memory_facts'. Rebuild only then.
        try:
            ddl = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table'"
                " AND name='memory_facts_fts'"
            ).fetchone()
            if ddl and ddl["sql"] and "content='memory_facts'" in ddl["sql"]:
                con.execute("DROP TABLE IF EXISTS memory_facts_fts")
                con.execute(
                    "CREATE VIRTUAL TABLE memory_facts_fts USING fts5("
                    " text, content='', content_rowid='id')")
        except sqlite3.OperationalError:
            pass
    # One-time data migration: fold legacy memory_facts rows into the
    # canonical per-user replica fragments. Runs AFTER the schema connection
    # closes (it opens its own replica connections) and is marker-guarded +
    # idempotent, so it's safe on every boot.
    try:
        migrate_memory_facts_to_fragments()
    except Exception:
        # A migration failure must not block boot / break /healthz. The
        # marker isn't written on failure, so the next boot retries.
        import sys as _sys
        print("migrate_memory_facts_to_fragments deferred (will retry next "
              "boot)", file=_sys.stderr)


# ---------------------------------------------------------------------------
# Customer profile
# ---------------------------------------------------------------------------
# Whitelist for update_user_profile. Anything not in this set is silently
# ignored — prevents an attacker from setting `is_admin = 1` or smuggling
# raw SQL through unknown keys.
PROFILE_FIELDS = frozenset({
    "full_name",
    "firm_name",
    "aec_role",
    "aec_discipline",
    "firm_size",
    "country",
    "signup_source",
    "landing_variant",
})


def update_user_profile(user_id: str, **fields) -> None:
    """Write whitelisted profile fields onto the users row.

    Unknown keys are dropped (no error). Empty / None values are skipped
    so partial updates don't blank a previously-set value.
    """
    sets: list[str] = []
    vals: list = []
    for k, v in fields.items():
        if k not in PROFILE_FIELDS:
            continue
        if v is None:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    vals.append(user_id)
    with connect() as con:
        con.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ?",
            vals,
        )


def get_user_with_profile(user_id: str) -> Optional[dict]:
    """Return the user row including every profile column."""
    return get_user(user_id)


# ---------------------------------------------------------------------------
def _ulid() -> str:
    """Lexicographic-sortable id without external dep."""
    return f"u_{int(time.time()*1000):x}_{uuid.uuid4().hex[:12]}"


def get_or_create_user(email: str) -> dict:
    """Return user row by email; insert with default trial plan if absent."""
    email = email.strip().lower()
    with connect() as con:
        r = con.execute("SELECT * FROM users WHERE email = ?",
                         (email,)).fetchone()
        if r is not None:
            return dict(r)
        uid = _ulid()
        now = int(time.time())
        con.execute(
            "INSERT INTO users (id, email, created_at, plan, msg_limit, msg_used)"
            " VALUES (?, ?, ?, 'trial', ?, 0)",
            (uid, email, now, config.PLAN_QUOTAS["trial"]),
        )
        return {
            "id": uid, "email": email, "created_at": now,
            "plan": "trial", "stripe_id": None, "period_end": None,
            "msg_limit": config.PLAN_QUOTAS["trial"], "msg_used": 0,
        }


def get_user(user_id: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute("SELECT * FROM users WHERE id = ?",
                         (user_id,)).fetchone()
        return dict(r) if r else None


def get_user_by_email(email: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute("SELECT * FROM users WHERE email = ?",
                         (email.strip().lower(),)).fetchone()
        return dict(r) if r else None


def get_user_by_stripe_id(stripe_id: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute("SELECT * FROM users WHERE stripe_id = ?",
                         (stripe_id,)).fetchone()
        return dict(r) if r else None


def set_user_brain_id(user_id: str, brain_id: str) -> None:
    """Record the user's brain replica identity on the users row.

    Called from auth.provision_brain at first login so `users.brain_id`
    is the explicit, queryable link to the per-user cloud brain replica.
    Idempotent + write-once-stable: only writes when the stored value
    differs (a returning user whose brain_id already equals brain_id is a
    no-op), so re-provisioning on every sign-in never churns the row.
    """
    if not user_id or not brain_id:
        return
    with connect() as con:
        con.execute(
            "UPDATE users SET brain_id = ? WHERE id = ? "
            "AND (brain_id IS NULL OR brain_id != ?)",
            (brain_id, user_id, brain_id),
        )


def update_user_plan(user_id: str, *, plan: str,
                      stripe_id: Optional[str] = None,
                      period_end: Optional[int] = None) -> None:
    msg_limit = config.PLAN_QUOTAS.get(plan, config.PLAN_QUOTAS["trial"])
    with connect() as con:
        # Reset msg_used when plan changes (new billing period).
        con.execute(
            "UPDATE users SET plan = ?, stripe_id = COALESCE(?, stripe_id),"
            " period_end = ?, msg_limit = ?, msg_used = 0 WHERE id = ?",
            (plan, stripe_id, period_end, msg_limit, user_id),
        )


def increment_usage(user_id: str, n: int = 1) -> int:
    """Decrement remaining quota by `n`. Returns the NEW remaining
    count. Atomic — uses a single UPDATE."""
    with connect() as con:
        con.execute(
            "UPDATE users SET msg_used = msg_used + ? WHERE id = ?",
            (n, user_id),
        )
        r = con.execute(
            "SELECT msg_limit, msg_used FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if r is None:
        return 0
    return max(0, int(r["msg_limit"]) - int(r["msg_used"]))


def quota_remaining_for_actor(user: dict) -> int:
    """Resolve quota for the right billing actor: company if the user
    is operating under a company context, user otherwise.

    Studio + Firm plan seats share one company-level quota bucket.
    Solo + trial users have their own user-level bucket.
    """
    if not isinstance(user, dict):
        return 0
    cid = user.get("current_company_id") or None
    if cid:
        with connect() as con:
            r = con.execute(
                "SELECT msg_limit, msg_used FROM companies WHERE id = ?",
                (cid,),
            ).fetchone()
        if r is not None:
            return max(0, int(r["msg_limit"]) - int(r["msg_used"]))
        # Company row missing — fall through to user quota so the user
        # isn't locked out by a stale current_company_id pointer.
    return quota_remaining(user["id"])


def increment_usage_for_actor(user: dict, n: int = 1) -> int:
    """Bump usage on the right billing actor. Returns NEW remaining."""
    if not isinstance(user, dict):
        return 0
    cid = user.get("current_company_id") or None
    if cid:
        with connect() as con:
            con.execute(
                "UPDATE companies SET msg_used = msg_used + ? WHERE id = ?",
                (n, cid),
            )
            r = con.execute(
                "SELECT msg_limit, msg_used FROM companies WHERE id = ?",
                (cid,),
            ).fetchone()
        if r is not None:
            return max(0, int(r["msg_limit"]) - int(r["msg_used"]))
        # Company row missing — fall through to user-level.
    return increment_usage(user["id"], n)


def quota_remaining(user_id: str) -> int:
    with connect() as con:
        r = con.execute(
            "SELECT msg_limit, msg_used FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if r is None:
        return 0
    return max(0, int(r["msg_limit"]) - int(r["msg_used"]))


# ---------------------------------------------------------------------------
# Model C — AI mode + hosted credit packs (founder 2026-05-31)
# ---------------------------------------------------------------------------
# Two concerns, both keyed on the same billing-actor split as msg_used:
#   • ai_mode — 'byo_key' (default) or 'hosted', per workspace. In
#     byo_key the user's own LLM key carries inference → no hosted limit.
#     In hosted, we run the LLM and decrement credits per message.
#   • credit packs — credit_grants ledger rows ($10 = 1,000 messages),
#     each expiring 60 days after purchase (rollover). The live balance
#     is SUM(remaining) over non-expired rows; companies/users also cache
#     it in credit_balance for a cheap hot read on the metering path.
#
# "Actor" resolution: a user operating under current_company_id bills on
# the COMPANY workspace (shared pool); solo/trial users bill on their own
# user row. ai_mode_for_actor / credit_balance_for_actor / consume_credit
# all follow that rule so the per-message gate is workspace-correct.


def _ai_mode_norm(mode: str | None) -> str:
    m = (mode or "").strip().lower()
    return m if m in config.AI_MODES else config.DEFAULT_AI_MODE


def set_company_ai_mode(company_id: str, mode: str) -> str:
    """Set a company workspace's AI mode. Returns the stored value.
    Invalid values fall back to the default (never raises)."""
    mode = _ai_mode_norm(mode)
    with connect() as con:
        con.execute("UPDATE companies SET ai_mode = ? WHERE id = ?",
                    (mode, company_id))
    return mode


def set_user_ai_mode(user_id: str, mode: str) -> str:
    """Set a solo user's AI mode. Returns the stored value."""
    mode = _ai_mode_norm(mode)
    with connect() as con:
        con.execute("UPDATE users SET ai_mode = ? WHERE id = ?",
                    (mode, user_id))
    return mode


def ai_mode_for_actor(user: dict) -> str:
    """Resolve the active AI mode for the billing actor (company if the
    user is operating under one, else the user)."""
    if not isinstance(user, dict):
        return config.DEFAULT_AI_MODE
    cid = user.get("current_company_id") or None
    if cid:
        c = get_company(cid)
        if c is not None:
            return _ai_mode_norm(c.get("ai_mode"))
    return _ai_mode_norm(user.get("ai_mode"))


def _recache_balance(con, *, user_id: str | None,
                     company_id: str | None, now: int) -> int:
    """Recompute SUM(remaining) over non-expired grants for one actor and
    write it back to the actor's credit_balance cache. Returns the value.
    Runs inside an existing connection/transaction."""
    if company_id:
        row = con.execute(
            "SELECT COALESCE(SUM(remaining),0) AS bal FROM credit_grants"
            " WHERE company_id = ? AND expires_at > ?",
            (company_id, now),
        ).fetchone()
        bal = int(row["bal"]) if row else 0
        con.execute("UPDATE companies SET credit_balance = ? WHERE id = ?",
                    (bal, company_id))
        return bal
    row = con.execute(
        "SELECT COALESCE(SUM(remaining),0) AS bal FROM credit_grants"
        " WHERE user_id = ? AND expires_at > ?",
        (user_id, now),
    ).fetchone()
    bal = int(row["bal"]) if row else 0
    con.execute("UPDATE users SET credit_balance = ? WHERE id = ?",
                (bal, user_id))
    return bal


def grant_credits(*, messages: int,
                  user_id: str | None = None,
                  company_id: str | None = None,
                  rollover_days: int | None = None,
                  source: str = "credit_pack",
                  stripe_event_id: str | None = None,
                  now: int | None = None) -> dict:
    """Credit a workspace with `messages` hosted-AI messages.

    Inserts one credit_grants row expiring `rollover_days` (default
    CREDIT_PACK.rollover_days = 60) after now, then refreshes the cached
    balance. Exactly one of user_id / company_id must be given.

    Idempotent on stripe_event_id: a replayed webhook with the same event
    id is a no-op (the UNIQUE index would otherwise raise) — returns the
    existing balance with granted=False so double-delivery can't
    double-credit.
    """
    if bool(user_id) == bool(company_id):
        raise ValueError("grant_credits needs exactly one of user_id/company_id")
    messages = int(messages)
    if messages <= 0:
        raise ValueError("messages must be positive")
    if rollover_days is None:
        rollover_days = int(config.CREDIT_PACK["rollover_days"])
    now = int(now if now is not None else time.time())
    expires_at = now + int(rollover_days) * 86400
    with connect() as con:
        if stripe_event_id:
            dup = con.execute(
                "SELECT 1 FROM credit_grants WHERE stripe_event_id = ?",
                (stripe_event_id,),
            ).fetchone()
            if dup is not None:
                bal = _recache_balance(con, user_id=user_id,
                                       company_id=company_id, now=now)
                return {"granted": False, "balance": bal,
                        "reason": "duplicate_event"}
        con.execute(
            "INSERT INTO credit_grants (user_id, company_id, messages,"
            " remaining, source, stripe_event_id, granted_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, company_id, messages, messages, source,
             stripe_event_id, now, expires_at),
        )
        bal = _recache_balance(con, user_id=user_id,
                               company_id=company_id, now=now)
    return {"granted": True, "balance": bal, "expires_at": expires_at,
            "messages": messages}


def credit_balance(*, user_id: str | None = None,
                   company_id: str | None = None,
                   now: int | None = None) -> int:
    """Live hosted-credit balance = SUM(remaining) over non-expired
    grants for one actor. Computed from the ledger (not the cache) so it
    is always honest even if a cache write was missed."""
    now = int(now if now is not None else time.time())
    if bool(user_id) == bool(company_id):
        raise ValueError("credit_balance needs exactly one of user_id/company_id")
    col = "company_id" if company_id else "user_id"
    val = company_id or user_id
    with connect() as con:
        r = con.execute(
            f"SELECT COALESCE(SUM(remaining),0) AS bal FROM credit_grants"
            f" WHERE {col} = ? AND expires_at > ?",
            (val, now),
        ).fetchone()
    return int(r["bal"]) if r else 0


def credit_balance_for_actor(user: dict, *, now: int | None = None) -> int:
    """Hosted-credit balance for the billing actor (company if set)."""
    if not isinstance(user, dict):
        return 0
    cid = user.get("current_company_id") or None
    if cid:
        return credit_balance(company_id=cid, now=now)
    return credit_balance(user_id=user["id"], now=now)


def consume_credit(*, n: int = 1,
                   user_id: str | None = None,
                   company_id: str | None = None,
                   now: int | None = None) -> dict:
    """Spend `n` hosted-AI credits from the oldest-expiring non-expired
    grants first (so credits closest to lapsing are used up before they
    roll off — minimises waste). Returns {consumed, balance, exhausted}.

    `consumed` is how many credits were actually deducted (may be < n if
    the balance ran out mid-spend). `exhausted` is True when the balance
    hit 0. The caller's gate decides the 402 — this just does the maths
    atomically within one transaction.
    """
    if bool(user_id) == bool(company_id):
        raise ValueError("consume_credit needs exactly one of user_id/company_id")
    n = int(n)
    now = int(now if now is not None else time.time())
    col = "company_id" if company_id else "user_id"
    val = company_id or user_id
    consumed = 0
    with connect() as con:
        # Oldest-expiring first (FIFO on expiry) among live grants.
        rows = con.execute(
            f"SELECT id, remaining FROM credit_grants"
            f" WHERE {col} = ? AND expires_at > ? AND remaining > 0"
            f" ORDER BY expires_at ASC, id ASC",
            (val, now),
        ).fetchall()
        need = n
        for row in rows:
            if need <= 0:
                break
            take = min(int(row["remaining"]), need)
            con.execute(
                "UPDATE credit_grants SET remaining = remaining - ?"
                " WHERE id = ?",
                (take, row["id"]),
            )
            need -= take
            consumed += take
        bal = _recache_balance(con, user_id=user_id,
                               company_id=company_id, now=now)
    return {"consumed": consumed, "balance": bal, "exhausted": bal <= 0}


def consume_credit_for_actor(user: dict, n: int = 1, *,
                             now: int | None = None) -> dict:
    """Spend hosted credits on the right billing actor (company if set)."""
    cid = user.get("current_company_id") or None
    if cid:
        return consume_credit(n=n, company_id=cid, now=now)
    return consume_credit(n=n, user_id=user["id"], now=now)


# ---------------------------------------------------------------------------
def issue_code(user_id: str, code_challenge: str,
                *, ttl_seconds: int = 300) -> str:
    code = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    with connect() as con:
        con.execute(
            "INSERT INTO codes (code, user_id, code_challenge, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (code, user_id, code_challenge, expires_at),
        )
    return code


def consume_code(code: str, code_verifier: str) -> Optional[str]:
    """Verify code + PKCE verifier; if valid, delete + return user_id.
    Returns None when code is missing / expired / verifier mismatched.

    TWO deliberate paths, gated on whether the code was issued with a
    `code_challenge`:

    1. PKCE flow (DESKTOP) — `code_challenge` is NON-EMPTY. The desktop
       client generated a PKCE pair and bound the challenge to the code
       at /register time. The exchange MUST present a verifier whose
       SHA-256/base64url digest equals the stored challenge. A missing,
       empty, or mismatched verifier is REJECTED (the code is burned).
       This closes the bypass: a code that was challenged can never be
       redeemed without proving possession of the matching verifier.

    2. Browser-direct flow — `code_challenge` is EMPTY. The user signs in
       from a browser with no desktop client to hold a PKCE secret. Here
       the magic-link code itself is the only secret: one-time-use,
       5-min TTL, delivered only to the email owner's inbox. This is the
       classic magic-link security floor and is intentionally preserved;
       an empty verifier is expected and accepted ONLY because no
       challenge was ever issued for this code.
    """
    with connect() as con:
        r = con.execute(
            "SELECT user_id, code_challenge, expires_at FROM codes"
            " WHERE code = ?",
            (code,),
        ).fetchone()
        if r is None:
            return None
        if int(r["expires_at"]) < int(time.time()):
            con.execute("DELETE FROM codes WHERE code = ?", (code,))
            return None
        stored_challenge = r["code_challenge"] or ""
        if stored_challenge:
            # PKCE flow — desktop client must present a matching verifier.
            # Reject an absent/blank verifier up front: a challenged code
            # exchanged with no proof of the verifier is the bypass we are
            # closing. (Burn the code so it can't be retried.)
            verifier = (code_verifier or "").strip()
            if not verifier:
                con.execute("DELETE FROM codes WHERE code = ?", (code,))
                return None
            import base64
            import hashlib
            expected = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            # Constant-time compare — challenge/verifier are secrets.
            if not secrets.compare_digest(stored_challenge, expected):
                con.execute("DELETE FROM codes WHERE code = ?", (code,))
                return None
        # else: browser-direct flow — code alone is the secret.
        user_id = r["user_id"]
        con.execute("DELETE FROM codes WHERE code = ?", (code,))
        return user_id


def issue_token(user_id: str, *,
                 ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    token = "ah_live_" + secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + int(ttl_seconds)
    with connect() as con:
        con.execute(
            "INSERT INTO tokens (token, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token, user_id, now, expires_at),
        )
    return token


def user_for_token(token: str) -> Optional[dict]:
    """Resolve a bearer token to its user, enforcing server-side expiry.

    A token whose `expires_at` is in the past (or, defensively, NULL —
    which only happens if a row dodged the backfill) does NOT
    authenticate: the JOIN's `expires_at > now` clause returns no row
    and the caller gets None → 401. This is the real teeth behind the
    90-day lifetime; the client-side expiry is now a convenience, not
    the only gate.
    """
    now = int(time.time())
    with connect() as con:
        r = con.execute(
            "SELECT u.* FROM tokens t JOIN users u ON t.user_id = u.id"
            " WHERE t.token = ?"
            "   AND t.expires_at IS NOT NULL AND t.expires_at > ?",
            (token, now),
        ).fetchone()
        if r is None:
            return None
        # Touch last_used_at for token-rotation analytics.
        con.execute(
            "UPDATE tokens SET last_used_at = ? WHERE token = ?",
            (now, token),
        )
        return dict(r)


def delete_token(token: str) -> bool:
    """Revoke a single bearer token (logout of the current session).

    Returns True when a row was actually removed. After this, a call to
    user_for_token(token) returns None → the token is dead.
    """
    with connect() as con:
        cur = con.execute("DELETE FROM tokens WHERE token = ?", (token,))
        return int(cur.rowcount or 0) > 0


def delete_tokens_for_user(user_id: str) -> int:
    """Revoke ALL of a user's bearer tokens (logout everywhere / GDPR
    erasure / "sign out of all devices").

    Returns the number of tokens removed. Referenced by
    brain_replica.py's erasure note — now actually implemented.
    """
    with connect() as con:
        cur = con.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
def log_usage(user_id: str, *, model: str, input_toks: int,
               output_toks: int, cost_micros: int) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO usage_log (user_id, ts, model, input_toks,"
            " output_toks, cost_micros) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, int(time.time()), model,
             int(input_toks), int(output_toks), int(cost_micros)),
        )


# ---------------------------------------------------------------------------
# Memory / training samples (v1.3.3)
# ---------------------------------------------------------------------------
#
# Stages a sample moves through:
#   captured  → just inserted from desktop client (raw approved turn)
#   redacted  → PII scrubbed (client names, file paths, addresses)
#   judged    → instructor model scored quality + alignment
#   rejected  → judge flagged hallucination / off-domain — never trained
#   approved  → ready for the next training batch
#
# train_ready threshold lives in cloud_backend/config (default 100).
import json as _json


def insert_training_sample(*, user_id: str, role: str, content: str,
                            tool_trace: list | None = None,
                            intent: str = "",
                            company_id: Optional[str] = None) -> int:
    """Persist one approved turn. Returns the new row id.

    `tool_trace` is JSON-serialised before storage so the SQLite column
    stays TEXT. Loose typing on the way in (list[dict] expected) lets
    the desktop forward whatever the tool engine produced without
    re-shaping it.
    """
    payload = _json.dumps(tool_trace or [], separators=(",", ":"))
    with connect() as con:
        cur = con.execute(
            "INSERT INTO training_samples ("
            " user_id, company_id, role, content, tool_trace, intent,"
            " stage, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'captured', ?)",
            (user_id, company_id, role, content, payload, intent,
             int(time.time())),
        )
        return int(cur.lastrowid or 0)


def get_training_sample(sample_id: int) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM training_samples WHERE id = ?",
            (sample_id,),
        ).fetchone()
    return dict(r) if r else None


def memory_stats(user_id: str) -> dict:
    """Counters for the 4 pipeline stages, scoped to one user.

    `capture_today` = rows captured in the trailing 24h.
    `redact_clean` = lifetime rows that have been redacted but not yet judged.
    `judge_queued` = rows waiting on the instructor model.
    `train_ready` = True once approved samples >= TRAIN_THRESHOLD.
    """
    threshold = getattr(config, "TRAIN_READY_THRESHOLD", 100)
    day_ago = int(time.time()) - 86400
    with connect() as con:
        cap = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples "
            "WHERE user_id = ? AND created_at >= ?",
            (user_id, day_ago),
        ).fetchone()
        red = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples "
            "WHERE user_id = ? AND stage = 'redacted'",
            (user_id,),
        ).fetchone()
        jud = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples "
            "WHERE user_id = ? AND stage = 'judged'",
            (user_id,),
        ).fetchone()
        app = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples "
            "WHERE user_id = ? AND stage = 'approved'",
            (user_id,),
        ).fetchone()
    approved_count = int(app["n"]) if app else 0
    return {
        "capture_today": int(cap["n"]) if cap else 0,
        "redact_clean":  int(red["n"]) if red else 0,
        "judge_queued":  int(jud["n"]) if jud else 0,
        "approved":      approved_count,
        "train_ready":   approved_count >= int(threshold),
        "threshold":     int(threshold),
    }


# ---------------------------------------------------------------------------
# Semantic memory facts (ADR-002) — UNIFIED on the per-user brain replica
# ---------------------------------------------------------------------------
#
# cloud-brain-unify (2026-05-31): a "memory fact" IS a fragment in the user's
# replica (brain_replica.py → data/replicas/<user_id>/brain.db). The DAO
# below reads/writes THAT canonical store so a fact added via /v1/memory and
# a fragment synced via /v1/brain/sync share ONE table — the two-brains
# duplicate is gone. `memory_fact_index` mints the global-unique INTEGER
# fact-id the /v1/memory/facts/{id} API exposes and maps it to the replica
# fragment (+ holds the FTS/embedding index). The canonical CONTENT lives in
# the fragment, never in a second per-user table.
#
# Mem0-style ADD/UPDATE/DELETE/NOOP operations apply through memory_writer.
# Search uses FTS5 over the fragment text; vector search is best-effort via
# the index embedding BLOB (populated by an async embedding worker later).

VALID_SCOPES = ("user", "project", "company", "global")
VALID_VISIBILITY = ("private", "shared_company", "shared_public")
VALID_OPS = ("ADD", "UPDATE", "DELETE", "NOOP")

# Numeric-confidence (REAL) → fragment text-confidence label. The replica
# `fragments.confidence` column is a TEXT enum ('extracted'/'stated'/…); the
# precise 0..1 score memory facts use rides in extra_json.mf_confidence so no
# precision is lost while the fragment still carries a sensible brain label.
def _conf_label(score: float) -> str:
    s = float(score)
    if s >= 0.9:
        return "confirmed"
    if s >= 0.7:
        return "stated"
    return "extracted"


def _open_replica(user_id: str):
    """Open (creating if needed) the user's brain replica — the canonical
    per-user store. Imported lazily so db.py stays importable standalone.

    Passes NO explicit root, so it resolves through the SAME
    brain_replica.DEFAULT_REPLICAS_ROOT that main.py's /v1/brain/sync uses —
    guaranteeing the /v1/memory DAO and the /v1/brain/sync endpoint open the
    EXACT same per-user brain.db file (one store, both APIs agree). Operator
    override flows through config.REPLICAS_ROOT → DEFAULT_REPLICAS_ROOT at
    import; test isolation repoints DEFAULT_REPLICAS_ROOT."""
    import brain_replica
    return brain_replica.BrainReplica.open(user_id=user_id)


def _fragment_to_fact_row(user_id: str, fact_id: int, frag: dict) -> dict:
    """Project a replica fragment back into the memory_facts row shape every
    caller (main.py, memory_writer, memory_extractor, tests) expects. The
    integer `id` is the public fact-id from memory_fact_index; the rest is
    reconstructed from fragment columns + extra_json (mf_* keys)."""
    extra = frag.get("extra") or {}
    return {
        "id": int(fact_id),
        "user_id": user_id,
        "company_id": extra.get("mf_company_id"),
        "project_id": frag.get("project_id"),
        "scope": frag.get("scope") or "user",
        "visibility": frag.get("visibility") or "private",
        "subject": frag.get("subject") or "",
        "predicate": frag.get("predicate") or "",
        "object": frag.get("object") or "",
        "text": frag.get("text") or "",
        "confidence": float(extra.get("mf_confidence", 0.7)),
        "source_sample_id": extra.get("mf_source_sample_id"),
        "valid_from": extra.get("mf_valid_from"),
        "valid_until": frag.get("valid_until"),
        "created_at": extra.get("mf_created_at"),
        "last_reinforced_at": extra.get("mf_last_reinforced_at"),
        "reinforce_count": int(extra.get("mf_reinforce_count", 1)),
        # The underlying fragment id — internal, lets callers that already
        # have the row find the canonical fragment without a re-lookup.
        "frag_id": frag.get("id"),
    }


def _fts_insert(con, fact_id: int, text: str) -> None:
    """Add a NEW fact's text to the contentless FTS index. Must only be
    called for a rowid not already present (a 'delete' directive against an
    absent rowid corrupts a contentless fts5 table)."""
    con.execute("INSERT INTO memory_facts_fts(rowid, text) VALUES (?, ?)",
                (fact_id, text))


def _fts_delete(con, fact_id: int, old_text: str) -> None:
    """Drop a fact's text from the contentless FTS index. `old_text` MUST be
    the exact text currently indexed for this rowid (contentless fts5 needs
    the stored value to reverse the posting)."""
    con.execute("INSERT INTO memory_facts_fts(memory_facts_fts, rowid, text)"
                " VALUES('delete', ?, ?)", (fact_id, old_text))


def _fts_replace(con, fact_id: int, old_text: str, new_text: str) -> None:
    """Re-index a fact whose text changed: remove the old posting, add new."""
    _fts_delete(con, fact_id, old_text)
    _fts_insert(con, fact_id, new_text)


def _index_lookup(fact_id: int) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT id, user_id, frag_id FROM memory_fact_index WHERE id = ?",
            (fact_id,),
        ).fetchone()
    return dict(r) if r else None


def _index_for_fragment(user_id: str, frag: dict) -> int:
    """Return the public fact-id for a fact fragment, MINTING the index row
    (+ FTS posting) on first sight.

    This is what makes the index a true *derived* view over the canonical
    fragments: a fact that arrives via /v1/brain/sync (a fragment, never
    routed through insert_memory_fact) is auto-indexed the first time
    /v1/memory lists or searches — so both APIs surface the SAME facts with
    no separate write path. Idempotent: an already-indexed fragment just
    returns its id."""
    frag_id = frag.get("id")
    created = int((frag.get("extra") or {}).get("mf_created_at")
                  or time.time())
    with connect() as con:
        row = con.execute(
            "SELECT id FROM memory_fact_index WHERE user_id = ? AND frag_id = ?",
            (user_id, frag_id),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        cur = con.execute(
            "INSERT INTO memory_fact_index (user_id, frag_id, created_at)"
            " VALUES (?, ?, ?)",
            (user_id, frag_id, created),
        )
        fact_id = int(cur.lastrowid or 0)
        text = frag.get("text") or ""
        if text:
            _fts_insert(con, fact_id, text)
    return fact_id


def insert_memory_fact(*, user_id: str, text: str,
                        subject: str = "", predicate: str = "",
                        object: str = "",
                        scope: str = "user",
                        visibility: str = "private",
                        confidence: float = 0.7,
                        company_id: Optional[str] = None,
                        project_id: Optional[str] = None,
                        source_sample_id: Optional[int] = None,
                        ) -> int:
    """Insert a new fact AS A FRAGMENT in the user's replica. Returns the
    global-unique integer fact-id.

    Caller is responsible for asserting non-private writes have gone
    through the redaction policy (memory_writer.promote_to_shared).
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}")
    if visibility not in VALID_VISIBILITY:
        raise ValueError(f"visibility must be one of {VALID_VISIBILITY}")
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    now = int(time.time())
    replica = _open_replica(user_id)
    # Write the fact as a fragment (the canonical store). The replica's
    # secret-leak gate runs here too — /v1/memory can't smuggle a bare
    # credential past the BRAIN-FIRST contract any more than /v1/brain/sync.
    res = replica.upsert_fragment({
        "kind": "fact",
        "text": text,
        "subject": subject or None,
        "predicate": predicate or None,
        "object": object or None,
        "scope": scope,
        "visibility": visibility,
        "project_id": project_id,
        "valid_from": None,
        "valid_until": None,
        "confidence": _conf_label(confidence),
        "provenance": {"via": "v1/memory"},
        "extra": {
            "mf_confidence": float(confidence),
            "mf_company_id": company_id,
            "mf_source_sample_id": source_sample_id,
            "mf_created_at": now,
            "mf_last_reinforced_at": now,
            "mf_valid_from": now,
            "mf_reinforce_count": 1,
        },
    })
    frag_id = res["id"]
    # Mint / fetch the public integer fact-id, then index the text for FTS.
    with connect() as con:
        cur = con.execute(
            "INSERT INTO memory_fact_index (user_id, frag_id, created_at)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, frag_id) DO UPDATE SET frag_id = excluded.frag_id",
            (user_id, frag_id, now),
        )
        fact_id = int(cur.lastrowid or 0)
        if not fact_id:
            row = con.execute(
                "SELECT id FROM memory_fact_index WHERE user_id = ? AND frag_id = ?",
                (user_id, frag_id),
            ).fetchone()
            fact_id = int(row["id"]) if row else 0
        # New index row → plain FTS insert. If this (user,frag) was already
        # indexed (re-add of a fragment id), refresh by delete+insert.
        if int(cur.lastrowid or 0):
            _fts_insert(con, fact_id, text)
        else:
            try:
                _fts_delete(con, fact_id, text)
            except sqlite3.DatabaseError:
                pass
            _fts_insert(con, fact_id, text)
    return fact_id


def get_memory_fact(fact_id: int) -> Optional[dict]:
    """Resolve a fact-id to its row by reading the canonical fragment."""
    idx = _index_lookup(int(fact_id))
    if idx is None:
        return None
    frag = _open_replica(idx["user_id"]).get_fragment(idx["frag_id"])
    if frag is None:
        return None
    return _fragment_to_fact_row(idx["user_id"], int(fact_id), frag)


def list_memory_facts(*, user_id: str, scope: Optional[str] = None,
                       include_expired: bool = False,
                       limit: int = 50) -> list[dict]:
    """List a user's facts from their replica fragments (newest first),
    excluding tombstoned (valid_until set) rows unless include_expired."""
    replica = _open_replica(user_id)
    frags = replica.list_fragments(
        kind="fact", include_invalid=include_expired, limit=max(int(limit), 1))
    out: list[dict] = []
    for f in frags:
        if scope and (f.get("scope") or "user") != scope:
            continue
        # Lazily mint the public fact-id for ANY fact fragment — including
        # ones that arrived via /v1/brain/sync — so the unified store
        # presents the same facts through both APIs.
        fid = _index_for_fragment(user_id, f)
        out.append(_fragment_to_fact_row(user_id, fid, f))
        if len(out) >= int(limit):
            break
    return out


def search_memory_facts(*, user_id: str, query: str,
                         include_shared: bool = True,
                         limit: int = 10) -> list[dict]:
    """FTS5 search over the unified fragment text. When include_shared=True
    the user also sees shared facts (visibility shared_company/shared_public).
    Results are reconstructed from the canonical fragments."""
    query = (query or "").strip()
    if not query:
        return []
    # Ensure the caller's own fact fragments are indexed before searching —
    # a fact that arrived via /v1/brain/sync is otherwise absent from the
    # FTS index until first listed. This lazy backfill keeps search honest
    # across both write paths (one store, both APIs agree). Cheap: facts
    # churn slowly and _index_for_fragment is a no-op once indexed.
    try:
        own = _open_replica(user_id).list_fragments(kind="fact", limit=500)
        for f in own:
            _index_for_fragment(user_id, f)
    except Exception:
        pass
    safe = query.replace('"', '""')
    # FTS index is keyed on the public fact-id; join back to the index to
    # get (user_id, frag_id), then read the canonical fragment.
    with connect() as con:
        hits = con.execute(
            "SELECT i.id AS id, i.user_id AS user_id, i.frag_id AS frag_id,"
            " bm25(memory_facts_fts) AS rank"
            " FROM memory_facts_fts"
            " JOIN memory_fact_index i ON i.id = memory_facts_fts.rowid"
            " WHERE memory_facts_fts MATCH ?"
            " ORDER BY rank LIMIT ?",
            (f'"{safe}"', int(limit) * 4),
        ).fetchall()
    out: list[dict] = []
    # Cache replicas per owner so a multi-user shared search opens each once.
    replicas: dict[str, object] = {}
    for h in hits:
        owner = h["user_id"]
        rep = replicas.get(owner)
        if rep is None:
            rep = _open_replica(owner)
            replicas[owner] = rep
        frag = rep.get_fragment(h["frag_id"])
        if frag is None or frag.get("valid_until") is not None:
            continue
        vis = frag.get("visibility") or "private"
        # Own facts always visible; others only if shared + caller opted in.
        if owner == user_id:
            pass
        elif include_shared and vis in ("shared_company", "shared_public"):
            pass
        else:
            continue
        row = _fragment_to_fact_row(owner, int(h["id"]), frag)
        row["rank"] = h["rank"]
        out.append(row)
        if len(out) >= int(limit):
            break
    return out


def update_memory_fact(fact_id: int, *,
                        text: Optional[str] = None,
                        confidence: Optional[float] = None,
                        reinforce: bool = True) -> None:
    """Refine a fact's underlying fragment. `reinforce=True` bumps the
    reinforce_count + last_reinforced_at carried in the fragment extra."""
    idx = _index_lookup(int(fact_id))
    if idx is None:
        return
    replica = _open_replica(idx["user_id"])
    frag = replica.get_fragment(idx["frag_id"])
    if frag is None:
        return
    now = int(time.time())
    old_text = frag.get("text") or ""
    extra = dict(frag.get("extra") or {})
    patch: dict = {}
    new_text = None
    if text is not None and text.strip():
        new_text = text.strip()
        patch["text"] = new_text
    fcol = None
    if confidence is not None:
        extra["mf_confidence"] = float(confidence)
        fcol = _conf_label(confidence)
    if reinforce:
        extra["mf_reinforce_count"] = int(extra.get("mf_reinforce_count", 1)) + 1
        extra["mf_last_reinforced_at"] = now
    if not patch and confidence is None and not reinforce:
        return
    patch["extra"] = extra
    if fcol is not None:
        patch["confidence"] = fcol
    replica.patch_fragment(idx["frag_id"], **patch)
    if new_text is not None and new_text != old_text:
        with connect() as con:
            _fts_replace(con, int(fact_id), old_text, new_text)


def delete_memory_fact(fact_id: int) -> None:
    """Soft-delete: tombstone the underlying fragment (valid_until=now) so
    BOTH /v1/memory and the /v1/brain/sync export agree it's gone. The
    fragment + index row stay for audit; FTS row is dropped so it no longer
    surfaces in search."""
    idx = _index_lookup(int(fact_id))
    if idx is None:
        return
    replica = _open_replica(idx["user_id"])
    frag = replica.get_fragment(idx["frag_id"])
    if frag is None or frag.get("valid_until") is not None:
        return
    now = int(time.time())
    replica.patch_fragment(idx["frag_id"], valid_until=now)
    with connect() as con:
        try:
            _fts_delete(con, int(fact_id), frag.get("text") or "")
        except sqlite3.DatabaseError:
            pass


# ── One-time migration: legacy memory_facts rows → replica fragments ────
def migrate_memory_facts_to_fragments() -> dict:
    """Fold every LIVE legacy `memory_facts` row into its owner's replica
    `fragments` (the canonical per-user store). Idempotent + marker-guarded
    — mirrors the token/credit/brain_id backfills:

      * a per-row stable fragment id `legacy-mf-<original_id>` makes a re-run
        a no-op (upsert on the same id, never a dup),
      * a global `schema_meta.migrated_memory_facts` marker short-circuits
        the whole pass once it has run.

    Legacy rows are NOT deleted (audit), they're just no longer the source
    the DAO reads — so nothing is lost. Returns a small summary dict.
    """
    with connect() as con:
        done = con.execute(
            "SELECT value FROM schema_meta WHERE key = 'migrated_memory_facts'"
        ).fetchone()
        if done is not None:
            return {"migrated": 0, "skipped": True, "reason": "already_done"}
        # Pull every legacy row that still has live content. (We migrate all
        # rows incl. tombstoned so the audit trail's validity carries over.)
        try:
            rows = con.execute(
                "SELECT id, user_id, company_id, project_id, scope,"
                " visibility, subject, predicate, object, text, confidence,"
                " source_sample_id, valid_from, valid_until, created_at,"
                " last_reinforced_at, reinforce_count"
                " FROM memory_facts ORDER BY id ASC"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    migrated = 0
    for r in rows:
        user_id = r["user_id"]
        if not user_id:
            continue
        legacy_id = int(r["id"])
        frag_id = f"legacy-mf-{legacy_id}"
        replica = _open_replica(user_id)
        # Skip if this legacy row was already folded in a prior partial run.
        if replica.get_fragment(frag_id) is not None:
            # Ensure it's indexed, then move on (idempotent).
            _ensure_indexed(user_id, frag_id, r["text"] or "",
                            int(r["created_at"] or time.time()))
            continue
        conf = float(r["confidence"] if r["confidence"] is not None else 0.7)
        try:
            replica.upsert_fragment({
                "id": frag_id,
                "kind": "fact",
                "text": r["text"] or "",
                "subject": r["subject"] or None,
                "predicate": r["predicate"] or None,
                "object": r["object"] or None,
                "scope": r["scope"] or "user",
                "visibility": r["visibility"] or "private",
                "project_id": r["project_id"],
                "valid_from": None,
                "valid_until": r["valid_until"],
                "confidence": _conf_label(conf),
                "provenance": {"via": "migrate:memory_facts",
                               "legacy_id": legacy_id},
                "extra": {
                    "mf_confidence": conf,
                    "mf_company_id": r["company_id"],
                    "mf_source_sample_id": r["source_sample_id"],
                    "mf_created_at": int(r["created_at"] or time.time()),
                    "mf_last_reinforced_at": int(
                        r["last_reinforced_at"] or time.time()),
                    "mf_valid_from": int(r["valid_from"] or time.time()),
                    "mf_reinforce_count": int(r["reinforce_count"] or 1),
                },
            })
        except ValueError:
            # A legacy row carrying a bare secret-like value is rejected by
            # the replica gate — skip it (don't leak it into the brain), it
            # stays in the legacy table for audit.
            continue
        _ensure_indexed(user_id, frag_id, r["text"] or "",
                        int(r["created_at"] or time.time()),
                        live=(r["valid_until"] is None))
        migrated += 1

    with connect() as con:
        con.execute(
            "INSERT INTO schema_meta (key, value) VALUES"
            " ('migrated_memory_facts', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(int(time.time())),),
        )
    return {"migrated": migrated, "skipped": False}


def _ensure_indexed(user_id: str, frag_id: str, text: str,
                    created_at: int, *, live: bool = True) -> int:
    """Idempotently map (user_id, frag_id) → a public fact-id and (re)index
    its text for FTS. Returns the fact-id. Used by the migration so a
    re-run never double-indexes."""
    with connect() as con:
        cur = con.execute(
            "INSERT INTO memory_fact_index (user_id, frag_id, created_at)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, frag_id) DO NOTHING",
            (user_id, frag_id, created_at),
        )
        newly_indexed = int(cur.lastrowid or 0) and (cur.rowcount or 0) > 0
        row = con.execute(
            "SELECT id FROM memory_fact_index WHERE user_id = ? AND frag_id = ?",
            (user_id, frag_id),
        ).fetchone()
        fact_id = int(row["id"]) if row else int(cur.lastrowid or 0)
        # Only insert the FTS posting when the index row is brand-new — a
        # re-run (row already present) must NOT re-post (idempotent, and a
        # blind 'delete' on contentless fts5 would corrupt the index).
        if live and text and newly_indexed:
            _fts_insert(con, fact_id, text)
    return fact_id


def log_memory_op(*, user_id: str, op: str,
                   fact_id: Optional[int] = None,
                   source_sample_id: Optional[int] = None,
                   rationale: str = "",
                   before_text: Optional[str] = None,
                   after_text: Optional[str] = None) -> int:
    if op not in VALID_OPS:
        raise ValueError(f"op must be one of {VALID_OPS}")
    now = int(time.time())
    with connect() as con:
        cur = con.execute(
            "INSERT INTO memory_op_log (user_id, fact_id, op,"
            " source_sample_id, rationale, before_text, after_text, ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, fact_id, op, source_sample_id, rationale,
             before_text, after_text, now),
        )
        return int(cur.lastrowid or 0)


def list_memory_ops(*, user_id: str, limit: int = 50) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM memory_op_log WHERE user_id = ?"
            " ORDER BY ts DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Collective memory (community-shared, redacted) ──────────────────
def promote_to_collective(*, fact_id: int, contributing_user_id: str,
                            redaction_policy: str = "transform",
                            access_policy: str = "public",
                            domain: str = "aec.general",
                            redacted_text: Optional[str] = None,
                            ) -> int:
    """Promote a private fact into the community store.

    Per ADR-002: any non-private write must apply the `transform`
    redaction policy. Caller passes the already-redacted text (from
    memory_writer.redact_text); we just persist + audit."""
    src = get_memory_fact(fact_id)
    if not src:
        raise ValueError(f"fact {fact_id} not found")
    text = (redacted_text or src["text"]).strip()
    company_id = src.get("company_id")
    now = int(time.time())
    with connect() as con:
        cur = con.execute(
            "INSERT INTO collective_memory ("
            " text, domain, contributing_user_id, contributing_company_id,"
            " source_fact_id, redaction_policy, access_policy,"
            " confidence, promoted_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text, domain, contributing_user_id, company_id,
             fact_id, redaction_policy, access_policy,
             float(src.get("confidence") or 0.7), now),
        )
        return int(cur.lastrowid or 0)


def list_collective_memory(*, domain: Optional[str] = None,
                              limit: int = 50) -> list[dict]:
    where = []
    params: list = []
    if domain:
        where.append("domain = ?")
        params.append(domain)
    sql = "SELECT id, text, domain, redaction_policy, access_policy," \
          " confidence, upvotes, downvotes, promoted_at" \
          " FROM collective_memory"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY promoted_at DESC LIMIT ?"
    params.append(int(limit))
    with connect() as con:
        rows = con.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def log_memory_access(*, reader_user_id: str,
                       fact_id: Optional[int] = None,
                       collective_id: Optional[int] = None,
                       purpose: str = "retrieve") -> None:
    """Per arXiv 2505.18279: record every read of a non-private fact."""
    with connect() as con:
        con.execute(
            "INSERT INTO memory_access_log ("
            " reader_user_id, fact_id, collective_id, purpose, ts)"
            " VALUES (?, ?, ?, ?, ?)",
            (reader_user_id, fact_id, collective_id, purpose,
             int(time.time())),
        )


def advance_training_sample(sample_id: int, *, stage: str,
                             judge_score: Optional[float] = None) -> None:
    """Move a sample to the next pipeline stage.

    Valid stages: 'redacted' / 'judged' / 'rejected' / 'approved'.
    The redact + judge worker jobs call this once each phase completes.
    """
    now = int(time.time())
    field_updates = ["stage = ?"]
    params: list = [stage]
    if stage == "redacted":
        field_updates.append("redacted_at = ?")
        params.append(now)
    elif stage in ("judged", "approved", "rejected"):
        field_updates.append("judged_at = ?")
        params.append(now)
        if judge_score is not None:
            field_updates.append("judge_score = ?")
            params.append(float(judge_score))
    params.append(sample_id)
    with connect() as con:
        con.execute(
            f"UPDATE training_samples SET {', '.join(field_updates)} "
            f"WHERE id = ?",
            tuple(params),
        )


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
import re as _re


def _company_id() -> str:
    return f"co_{int(time.time()*1000):x}_{uuid.uuid4().hex[:12]}"


def _slugify(name: str) -> str:
    s = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "company"


def _unique_slug(base: str) -> str:
    """Find a slug not yet taken — appends -2, -3, … on collision."""
    with connect() as con:
        if not con.execute(
            "SELECT 1 FROM companies WHERE slug = ?", (base,)
        ).fetchone():
            return base
        n = 2
        while True:
            candidate = f"{base}-{n}"
            if not con.execute(
                "SELECT 1 FROM companies WHERE slug = ?", (candidate,)
            ).fetchone():
                return candidate
            n += 1


def create_company(*, name: str, owner_user_id: str,
                    plan: str = "studio",
                    seat_limit: Optional[int] = None,
                    billing_email: Optional[str] = None,
                    slug: Optional[str] = None) -> dict:
    """Insert a company + the owner row in `company_members`. Returns the
    new company dict."""
    cid = _company_id()
    now = int(time.time())
    raw_slug = slug.strip() if slug else _slugify(name)
    final_slug = _unique_slug(_slugify(raw_slug))
    # Seat + message limits both DERIVE from the plan. config is the
    # single source of truth (config.PLAN_SEATS / config.PLAN_QUOTAS) —
    # never hardcode a mirror here, it drifts. config imports only
    # os+pathlib, so there is no circular import (db imports config).
    if seat_limit is None:
        seat_limit = config.PLAN_SEATS.get(plan, 5)
    msg_limit = config.PLAN_QUOTAS.get(plan, config.PLAN_QUOTAS["trial"])
    with connect() as con:
        con.execute(
            "INSERT INTO companies (id, name, slug, owner_user_id, plan,"
            " seat_limit, msg_limit, billing_email, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, name, final_slug, owner_user_id, plan,
             seat_limit, msg_limit, billing_email, now),
        )
        con.execute(
            "INSERT INTO company_members (company_id, user_id, role,"
            " joined_at) VALUES (?, ?, 'owner', ?)",
            (cid, owner_user_id, now),
        )
    return get_company(cid)


def get_company(company_id: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,),
        ).fetchone()
        return dict(r) if r else None


def get_company_by_slug(slug: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM companies WHERE slug = ?", (slug,),
        ).fetchone()
        return dict(r) if r else None


def get_company_by_stripe_customer(customer_id: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM companies WHERE stripe_customer_id = ?",
            (customer_id,),
        ).fetchone()
        return dict(r) if r else None


def update_company(company_id: str, **fields) -> None:
    """Whitelisted update for company rows.

    Invariant: a company's `plan` always implies its `msg_limit` (from
    config.PLAN_QUOTAS). Whenever `plan` is updated — the Stripe / Polar
    webhook on a tier change is the live caller — `msg_limit` is
    re-derived and `msg_used` reset for the new billing period. A caller
    CANNOT set a new plan and leave a stale quota: the two move
    together, always. (Mirrors `update_user_plan` for the per-seat
    path. This is why the Firm tier's 1,000,000-message quota actually
    reaches the customer instead of being stuck at the 2000 default.)
    """
    allowed = {
        "name", "billing_email", "plan", "seat_limit",
        "stripe_customer_id", "stripe_subscription_id", "period_end",
        "ai_mode",
    }
    sets: list[str] = []
    vals: list = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if "plan" in fields:
        # msg_limit is DERIVED from plan, never passed in by the caller.
        # msg_used resets to 0: a tier change opens a fresh billing
        # period (same rule as update_user_plan).
        plan = fields["plan"]
        sets.append("msg_limit = ?")
        vals.append(config.PLAN_QUOTAS.get(plan, config.PLAN_QUOTAS["trial"]))
        sets.append("msg_used = 0")
    if not sets:
        return
    vals.append(company_id)
    with connect() as con:
        con.execute(
            f"UPDATE companies SET {', '.join(sets)} WHERE id = ?",
            vals,
        )


def list_companies_for_user(user_id: str) -> list[dict]:
    """Companies the user belongs to (with their role)."""
    with connect() as con:
        rows = con.execute(
            "SELECT c.*, m.role AS member_role"
            " FROM companies c JOIN company_members m"
            " ON c.id = m.company_id"
            " WHERE m.user_id = ? ORDER BY c.created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_membership(company_id: str, user_id: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM company_members"
            " WHERE company_id = ? AND user_id = ?",
            (company_id, user_id),
        ).fetchone()
        return dict(r) if r else None


def list_company_members(company_id: str) -> list[dict]:
    """Members joined to users so callers can show email + role."""
    with connect() as con:
        rows = con.execute(
            "SELECT m.company_id, m.user_id, m.role, m.joined_at,"
            " m.invited_by_user_id, u.email, u.full_name"
            " FROM company_members m JOIN users u ON m.user_id = u.id"
            " WHERE m.company_id = ? ORDER BY m.joined_at ASC",
            (company_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_company_members(company_id: str) -> int:
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS n FROM company_members WHERE company_id = ?",
            (company_id,),
        ).fetchone()
    return int(r["n"]) if r else 0


def count_outstanding_invites(company_id: str) -> int:
    """Distinct invited emails with an un-accepted, un-expired invite.

    Each outstanding invite reserves a seat. The seat-limit check counts
    these alongside accepted members so a company can't over-invite past
    `seat_limit` — the failure mode where 3 members + N pending invites
    all pass the check, then all accept and blow the cap. DISTINCT email
    so a double-click re-invite of the same address reserves one seat,
    not two; expired invites free their reservation automatically.
    """
    now = int(time.time())
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(DISTINCT email) AS n FROM company_invites"
            " WHERE company_id = ? AND accepted_at IS NULL"
            "   AND expires_at > ?",
            (company_id, now),
        ).fetchone()
    return int(r["n"]) if r else 0


def add_company_member(*, company_id: str, user_id: str,
                        role: str = "member",
                        invited_by_user_id: Optional[str] = None) -> None:
    now = int(time.time())
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO company_members"
            " (company_id, user_id, role, joined_at, invited_by_user_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (company_id, user_id, role, now, invited_by_user_id),
        )


def remove_company_member(company_id: str, user_id: str) -> None:
    with connect() as con:
        con.execute(
            "DELETE FROM company_members"
            " WHERE company_id = ? AND user_id = ?",
            (company_id, user_id),
        )


def transfer_company_ownership(company_id: str, old_owner_id: str,
                                new_owner_id: str) -> None:
    """Atomically hand a company to a new owner. Roadmap #P1.

    Three writes in one transaction: point `companies.owner_user_id`
    at the new owner, promote the new owner's membership row to
    'owner', and demote the previous owner to 'admin' — kept as a
    member, never orphaned, so they can still manage the team or be
    removed normally afterward."""
    with connect() as con:
        con.execute(
            "UPDATE companies SET owner_user_id = ? WHERE id = ?",
            (new_owner_id, company_id),
        )
        con.execute(
            "UPDATE company_members SET role = 'owner'"
            " WHERE company_id = ? AND user_id = ?",
            (company_id, new_owner_id),
        )
        con.execute(
            "UPDATE company_members SET role = 'admin'"
            " WHERE company_id = ? AND user_id = ?",
            (company_id, old_owner_id),
        )


def set_current_company(user_id: str, company_id: Optional[str]) -> None:
    with connect() as con:
        con.execute(
            "UPDATE users SET current_company_id = ? WHERE id = ?",
            (company_id, user_id),
        )


# ---------------------------------------------------------------------------
# Company invites
# ---------------------------------------------------------------------------
def create_company_invite(*, company_id: str, email: str, role: str,
                           invited_by_user_id: str,
                           ttl_seconds: int = 7 * 24 * 3600) -> dict:
    """Issue an invite token (32-char urlsafe, 7-day expiry by default)."""
    token = secrets.token_urlsafe(24)   # 24 bytes ≈ 32 char base64
    expires_at = int(time.time()) + ttl_seconds
    with connect() as con:
        con.execute(
            "INSERT INTO company_invites (token, company_id, email, role,"
            " invited_by_user_id, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (token, company_id, email.strip().lower(), role,
             invited_by_user_id, expires_at),
        )
    return {
        "token": token, "company_id": company_id,
        "email": email.strip().lower(), "role": role,
        "invited_by_user_id": invited_by_user_id,
        "expires_at": expires_at, "accepted_at": None,
    }


def get_company_invite(token: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT * FROM company_invites WHERE token = ?", (token,),
        ).fetchone()
        return dict(r) if r else None


def mark_invite_accepted(token: str) -> None:
    with connect() as con:
        con.execute(
            "UPDATE company_invites SET accepted_at = ? WHERE token = ?",
            (int(time.time()), token),
        )


# ---------------------------------------------------------------------------
# Founder cockpit aggregates (PHASE 5)
# ---------------------------------------------------------------------------
# Read-only roll-ups over the LIVE tables for the founder-only admin
# dashboard (cloud_backend/founder_cockpit.py). These are pure SELECT
# aggregates — they never write — so they are safe to call on every
# dashboard refresh. They read the same `users`, `companies`,
# `usage_log` and `training_samples` rows the rest of the backend writes,
# so the numbers are the real business state, never placeholders.

def count_users() -> int:
    """Total registered users (every row in `users`)."""
    with connect() as con:
        r = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(r["n"]) if r else 0


def count_users_by_plan() -> dict:
    """{plan: count} over all users, e.g. {'trial': 12, 'solo': 3}."""
    with connect() as con:
        rows = con.execute(
            "SELECT plan, COUNT(*) AS n FROM users GROUP BY plan"
        ).fetchall()
    return {r["plan"]: int(r["n"]) for r in rows}


def count_users_since(epoch: int) -> int:
    """Users created at/after `epoch` (e.g. signups in the last 24h/7d)."""
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE created_at >= ?",
            (int(epoch),),
        ).fetchone()
    return int(r["n"]) if r else 0


def recent_users(limit: int = 10) -> list[dict]:
    """Most-recent signups, newest first. Returns id/email/plan/created_at."""
    with connect() as con:
        rows = con.execute(
            "SELECT id, email, plan, created_at, msg_used, msg_limit "
            "FROM users ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def count_paid_users() -> int:
    """Users on a paid individual tier (not trial)."""
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE plan != 'trial'"
        ).fetchone()
    return int(r["n"]) if r else 0


def list_companies_billing() -> list[dict]:
    """Every company row with its plan + seat_limit — the basis for
    company-tier MRR. Read-only."""
    with connect() as con:
        rows = con.execute(
            "SELECT id, name, plan, seat_limit, stripe_subscription_id, "
            "period_end, created_at FROM companies ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def count_companies() -> int:
    with connect() as con:
        r = con.execute("SELECT COUNT(*) AS n FROM companies").fetchone()
    return int(r["n"]) if r else 0


def usage_totals() -> dict:
    """Lifetime proxy-usage roll-up from `usage_log`:
    chat completions (one row per proxied completion), total tokens, and
    total spend in micro-dollars. Real counters — every /v1/chat/completions
    that hits the hosted proxy writes a usage_log row via db.log_usage."""
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS calls, "
            "COALESCE(SUM(input_toks), 0) AS in_toks, "
            "COALESCE(SUM(output_toks), 0) AS out_toks, "
            "COALESCE(SUM(cost_micros), 0) AS cost_micros FROM usage_log"
        ).fetchone()
    return {
        "chat_completions": int(r["calls"]) if r else 0,
        "input_tokens":     int(r["in_toks"]) if r else 0,
        "output_tokens":    int(r["out_toks"]) if r else 0,
        "cost_micros":      int(r["cost_micros"]) if r else 0,
    }


def usage_calls_since(epoch: int) -> int:
    """Proxied chat completions at/after `epoch` (trailing-window activity)."""
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS n FROM usage_log WHERE ts >= ?",
            (int(epoch),),
        ).fetchone()
    return int(r["n"]) if r else 0


def training_totals() -> dict:
    """Memory-capture roll-up from `training_samples`: total captured turns
    + a per-stage breakdown (captured/redacted/judged/rejected/approved).
    Every /v1/memory/capture writes one row, so `total` is the real count
    of memory captures across all users."""
    with connect() as con:
        total = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples"
        ).fetchone()
        by_stage = con.execute(
            "SELECT stage, COUNT(*) AS n FROM training_samples GROUP BY stage"
        ).fetchall()
        day_ago = int(time.time()) - 86400
        today = con.execute(
            "SELECT COUNT(*) AS n FROM training_samples WHERE created_at >= ?",
            (day_ago,),
        ).fetchone()
    return {
        "total":      int(total["n"]) if total else 0,
        "today":      int(today["n"]) if today else 0,
        "by_stage":   {r["stage"]: int(r["n"]) for r in by_stage},
    }


def count_marketplace_packs() -> int:
    with connect() as con:
        r = con.execute(
            "SELECT COUNT(*) AS n FROM marketplace_packs"
        ).fetchone()
    return int(r["n"]) if r else 0
