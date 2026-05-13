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
        ):
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                # Column already exists — idempotent re-run.
                pass


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


def update_company_quota(company_id: str, *, plan: str) -> None:
    """Seed company.msg_limit from plan + reset msg_used.

    Called by the Stripe webhook on `checkout.session.completed` /
    `customer.subscription.updated` when `metadata.kind == "company"`.
    Mirrors `update_user_plan` shape so the per-plan quotas are kept
    in one source of truth (config.PLAN_QUOTAS).
    """
    msg_limit = config.PLAN_QUOTAS.get(plan, config.PLAN_QUOTAS["trial"])
    with connect() as con:
        con.execute(
            "UPDATE companies SET plan = ?, msg_limit = ?, msg_used = 0"
            " WHERE id = ?",
            (plan, msg_limit, company_id),
        )


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
    Returns None when code is missing / expired / verifier mismatched."""
    import base64
    import hashlib
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
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
        if r["code_challenge"] != expected:
            con.execute("DELETE FROM codes WHERE code = ?", (code,))
            return None
        user_id = r["user_id"]
        con.execute("DELETE FROM codes WHERE code = ?", (code,))
        return user_id


def issue_token(user_id: str) -> str:
    token = "ah_live_" + secrets.token_urlsafe(32)
    now = int(time.time())
    with connect() as con:
        con.execute(
            "INSERT INTO tokens (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now),
        )
    return token


def user_for_token(token: str) -> Optional[dict]:
    with connect() as con:
        r = con.execute(
            "SELECT u.* FROM tokens t JOIN users u ON t.user_id = u.id"
            " WHERE t.token = ?",
            (token,),
        ).fetchone()
        if r is None:
            return None
        # Touch last_used_at for token-rotation analytics.
        con.execute(
            "UPDATE tokens SET last_used_at = ? WHERE token = ?",
            (int(time.time()), token),
        )
        return dict(r)


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
    # Default seat counts mirror config.PLAN_SEATS — but config imports db
    # via the router, so we don't reach back here. Caller passes the
    # explicit number when they have one.
    if seat_limit is None:
        seat_limit = {"studio": 5, "firm": 25}.get(plan, 5)
    with connect() as con:
        con.execute(
            "INSERT INTO companies (id, name, slug, owner_user_id, plan,"
            " seat_limit, billing_email, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, name, final_slug, owner_user_id, plan,
             seat_limit, billing_email, now),
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
    """Whitelisted update for company rows."""
    allowed = {
        "name", "billing_email", "plan", "seat_limit",
        "stripe_customer_id", "stripe_subscription_id", "period_end",
    }
    sets: list[str] = []
    vals: list = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
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
