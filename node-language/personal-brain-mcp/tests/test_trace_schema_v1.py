"""AgDR-0054 slice 1 — per-trace schema lock (acceptance gate).

Proves: the per-trace schema columns exist on fresh DBs AND are added to legacy
DBs by the additive migration WITHOUT data loss, with legacy-safe defaults
(untagged old rows are human_verified + firm_private_only → never auto-train the
collective), and the export/legal tier is computable by a single WHERE.
"""
from __future__ import annotations
import sqlite3

from personal_brain.storage import BrainStore

NEW_COLS = {
    "origin_kind", "generating_model_id", "training_rights_tier",
    "format_shape_descriptor", "content_hash_pre", "content_hash_post",
    "action_payload", "language_payload", "quarantine_flag",
}


def _cols(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(fragments)").fetchall()}


def test_fresh_db_has_trace_schema(tmp_path):
    s = BrainStore.open(tmp_path / "fresh.db")
    try:
        missing = NEW_COLS - _cols(s._conn)
        assert not missing, f"fresh DB missing per-trace columns: {missing}"
    finally:
        s.close()


def test_legacy_db_migrates_without_data_loss(tmp_path):
    # Build a pre-AgDR-0054 fragments table (no new columns) + a legacy row.
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(p)
    c.execute(
        """CREATE TABLE fragments(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL,
            subject TEXT, predicate TEXT, object TEXT,
            scope TEXT NOT NULL DEFAULT 'user', visibility TEXT NOT NULL DEFAULT 'private',
            owner_user TEXT NOT NULL, project_id TEXT, firm_id TEXT,
            confidence TEXT NOT NULL DEFAULT 'extracted', provenance_json TEXT NOT NULL,
            valid_from TEXT, valid_until TEXT, embedding_blob BLOB,
            success_count INTEGER NOT NULL DEFAULT 0, fail_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT, half_life_days REAL NOT NULL DEFAULT 30.0, extra_json TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )"""
    )
    c.execute(
        "INSERT INTO fragments(id,kind,text,owner_user,provenance_json) "
        "VALUES('legacy1','fact','old knowledge','Fargaly','{}')"
    )
    c.commit(); c.close()

    # Open via BrainStore → the additive ALTER migration runs.
    s = BrainStore.open(p)
    try:
        missing = NEW_COLS - _cols(s._conn)
        assert not missing, f"legacy DB not migrated: {missing}"
        row = s._conn.execute(
            "SELECT text, origin_kind, training_rights_tier, quarantine_flag "
            "FROM fragments WHERE id='legacy1'"
        ).fetchone()
        assert row[0] == "old knowledge", "data loss on migration"
        # The privacy-critical defaults: legacy/untagged data must NOT auto-train the collective.
        assert row[1] == "human_verified"
        assert row[2] == "firm_private_only"
        assert row[3] == 0
    finally:
        s.close()


def test_export_tier_filter_is_computable(tmp_path):
    # The export filter selects the trainable set by a single WHERE over the new
    # columns — assert the query is valid (columns exist + indexed).
    s = BrainStore.open(tmp_path / "t.db")
    try:
        n = s._conn.execute(
            "SELECT count(*) FROM fragments "
            "WHERE quarantine_flag=0 AND training_rights_tier='collective_ok'"
        ).fetchone()[0]
        assert n == 0  # empty db; the point is the query runs against real columns
    finally:
        s.close()
