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
