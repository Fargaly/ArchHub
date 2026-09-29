"""The founder's read-only query view of the cloud database (Cockpit P8, 2026-09-29).

"Control the database from the Cockpit": one SELECT at a time, and SQLite
itself enforces the limits, not a parse of the text:
  * a separate mode=ro connection with PRAGMA query_only;
  * an authorizer that allows only SELECT, column reads and functions (no
    ATTACH, no PRAGMA, no write of any kind) and refuses to read credentials
    (session and code tables, any token/secret/password/digest column) and
    users' private content (cloud memory, training samples);
  * one statement, a row cap and a time limit.
The route audits every query. The cockpit agent still has no SQL tool.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import config

MAX_ROWS = 200
TIME_LIMIT_S = 3.0

# Whole tables no query may read: credentials, and users' private content.
DENIED_TABLES = frozenset({
    "tokens", "codes", "refund_confirmations", "company_invites",
    "memory_facts", "memory_fact_index", "memory_op_log", "memory_access_log",
    "training_samples", "collective_memory",
})
_DENIED_COLUMN_WORDS = ("token", "secret", "password", "digest", "code_challenge")

# SELECT, column reads, functions and a WITH RECURSIVE (33 on builds that do
# not name it); everything else -- writes, ATTACH, PRAGMA, DDL -- is denied.
_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
            getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


class QueryRefused(ValueError):
    """The query is not a single permitted read."""


def _authorizer(action, table, column, _db, _trigger):
    if action not in _ALLOWED:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ:
        name = (table or "").lower()
        col = (column or "").lower()
        if name in DENIED_TABLES or any(word in col for word in _DENIED_COLUMN_WORDS):
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def run(sql: str, *, max_rows: int = MAX_ROWS, time_limit_s: float = TIME_LIMIT_S) -> dict:
    """Run ONE read-only statement; QueryRefused for anything else."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise QueryRefused("an empty query")
    if ";" in text or not sqlite3.complete_statement(text + ";"):
        raise QueryRefused("one statement only")
    path = Path(config.DATABASE_URL).resolve()
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=time_limit_s)
    try:
        con.execute("PRAGMA query_only = ON")
        con.set_authorizer(_authorizer)
        deadline = time.monotonic() + time_limit_s
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        started = time.perf_counter()
        try:
            cursor = con.execute(text)
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if "interrupted" in message:
                message = "the query ran past %.0f s" % time_limit_s
            raise QueryRefused(message) from exc
        columns = [item[0] for item in cursor.description or ()]
        return {
            "columns": columns,
            "rows": [[value.hex() if isinstance(value, bytes) else value for value in row]
                     for row in rows[:max_rows]],
            "truncated": len(rows) > max_rows,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    finally:
        con.close()