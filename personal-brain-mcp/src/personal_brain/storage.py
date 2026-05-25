"""BrainStore — SQLite-backed persistence for fragments + skills.

Slice 1 (this file): pure SQLite + FTS5 + JSON columns. Standalone — does
NOT yet import ArchHub's app.memory.graph.MemoryGraph (slice 2 will wire
that as a backend adapter so the brain works inside ArchHub AND as a
self-contained Python package).

Schema:
    fragments        — every memory unit (facts, traces, spatial refs, etc.)
    skills           — minted procedures (separate table for richer fields)
    wiring           — registered MCPs / CLIs per device
    secret_refs      — references to secrets (never values)
    access_log       — arXiv 2505.18279 retrospective audit
    fragments_fts    — FTS5 virtual table mirroring fragment.text
    skills_fts       — FTS5 virtual table mirroring skill.description

Concurrency model: single writer thread, many reader connections.
Each MCP tool call opens its own connection in WAL mode.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import (
    Confidence,
    ContextResponse,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    SecretRef,
    Skill,
    Visibility,
    WiringEntry,
    WriteOp,
    WriteOpType,
    WriteResponse,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    scope TEXT NOT NULL DEFAULT 'user',
    visibility TEXT NOT NULL DEFAULT 'private',
    owner_user TEXT NOT NULL,
    project_id TEXT,
    firm_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'extracted',
    provenance_json TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    embedding_blob BLOB,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    half_life_days REAL NOT NULL DEFAULT 30.0,
    extra_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_fragments_scope ON fragments(scope, owner_user);
CREATE INDEX IF NOT EXISTS idx_fragments_kind ON fragments(kind, scope);
CREATE INDEX IF NOT EXISTS idx_fragments_project ON fragments(project_id);
CREATE INDEX IF NOT EXISTS idx_fragments_last_used ON fragments(last_used_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS fragments_fts USING fts5(
    id UNINDEXED, text, subject, object,
    content='fragments', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS fragments_ai AFTER INSERT ON fragments BEGIN
    INSERT INTO fragments_fts(rowid, id, text, subject, object)
    VALUES (new.rowid, new.id, new.text, new.subject, new.object);
END;
CREATE TRIGGER IF NOT EXISTS fragments_ad AFTER DELETE ON fragments BEGIN
    INSERT INTO fragments_fts(fragments_fts, rowid, id, text, subject, object)
    VALUES ('delete', old.rowid, old.id, old.text, old.subject, old.object);
END;
CREATE TRIGGER IF NOT EXISTS fragments_au AFTER UPDATE ON fragments BEGIN
    INSERT INTO fragments_fts(fragments_fts, rowid, id, text, subject, object)
    VALUES ('delete', old.rowid, old.id, old.text, old.subject, old.object);
    INSERT INTO fragments_fts(rowid, id, text, subject, object)
    VALUES (new.rowid, new.id, new.text, new.subject, new.object);
END;

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    triggers_json TEXT NOT NULL DEFAULT '[]',
    requires_mcps_json TEXT NOT NULL DEFAULT '[]',
    requires_secrets_json TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL,
    examples_json TEXT NOT NULL DEFAULT '[]',
    eval_queries_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'user',
    visibility TEXT NOT NULL DEFAULT 'private',
    owner_user TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    minted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    honed_trials INTEGER NOT NULL DEFAULT 0,
    honed_passed INTEGER NOT NULL DEFAULT 0,
    side_effects TEXT NOT NULL DEFAULT 'pure',
    embedding_blob BLOB
);

CREATE INDEX IF NOT EXISTS idx_skills_scope ON skills(scope, owner_user);
CREATE INDEX IF NOT EXISTS idx_skills_last_used ON skills(last_used_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    id UNINDEXED, name, description, body,
    content='skills', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS skills_ai AFTER INSERT ON skills BEGIN
    INSERT INTO skills_fts(rowid, id, name, description, body)
    VALUES (new.rowid, new.id, new.name, new.description, new.body);
END;
CREATE TRIGGER IF NOT EXISTS skills_ad AFTER DELETE ON skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, id, name, description, body)
    VALUES ('delete', old.rowid, old.id, old.name, old.description, old.body);
END;
CREATE TRIGGER IF NOT EXISTS skills_au AFTER UPDATE ON skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, id, name, description, body)
    VALUES ('delete', old.rowid, old.id, old.name, old.description, old.body);
    INSERT INTO skills_fts(rowid, id, name, description, body)
    VALUES (new.rowid, new.id, new.name, new.description, new.body);
END;

CREATE TABLE IF NOT EXISTS wiring (
    name TEXT NOT NULL,
    device_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    endpoint TEXT,
    auth_method TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    last_seen TEXT NOT NULL,
    PRIMARY KEY (name, device_id)
);

CREATE TABLE IF NOT EXISTS secret_refs (
    ref TEXT NOT NULL,
    owner_user TEXT NOT NULL,
    resolver TEXT NOT NULL,
    description TEXT,
    scope TEXT NOT NULL DEFAULT 'user',
    last_used_at TEXT,
    PRIMARY KEY (ref, owner_user)
);

CREATE TABLE IF NOT EXISTS access_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    reader_user TEXT NOT NULL,
    fragment_id TEXT NOT NULL,
    purpose TEXT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_access_log_fragment ON access_log(fragment_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_access_log_reader ON access_log(reader_user, ts DESC);

CREATE TABLE IF NOT EXISTS brain_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_brain_path() -> Path:
    """Default SQLite location — %APPDATA%/ArchHub/brain/brain.db on Windows,
    ~/.local/share/archhub/brain/brain.db on Linux/macOS."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        return base / "ArchHub" / "brain" / "brain.db"
    base = Path(os.environ.get("XDG_DATA_HOME",
                                str(Path.home() / ".local" / "share")))
    return base / "archhub" / "brain" / "brain.db"


# ─────────────────────────────────────────────────────────────────────────


class BrainStore:
    """Thread-safe SQLite store with FTS5 search.

    Slice-1 surface:
        store = BrainStore.open(path)
        store.write_fragment(fragment) → bool
        store.search_fragments(query, scope_filter, k=10) → list[Fragment]
        store.upsert_skill(skill) → bool
        store.search_skills(query, scope_filter, k=5) → list[Skill]
        store.upsert_wiring(entry) → bool
        store.list_wiring(device_id?) → list[WiringEntry]
        store.upsert_secret_ref(ref) → bool
        store.list_secret_refs(owner_user, scope_filter?) → list[SecretRef]
        store.log_access(reader, fragment_id, purpose) → None
        store.close() → None
    """

    def __init__(self, conn: sqlite3.Connection, path: Path):
        self._conn = conn
        self._path = path
        self._lock = threading.RLock()

    # ── lifecycle ────────────────────────────────────────────────────────

    @classmethod
    def open(cls, path: str | Path | None = None) -> "BrainStore":
        """Open / create a brain store at `path`. Default = OS-appropriate
        per-user location. Special value ':memory:' for ephemeral test stores."""
        if path is None:
            path = default_brain_path()
        if str(path) != ":memory:":
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(path), isolation_level=None, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        return cls(conn, Path(str(path)))

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    @property
    def path(self) -> Path:
        return self._path

    # ── fragments ────────────────────────────────────────────────────────

    def write_fragment(self, fragment: Fragment) -> bool:
        """Upsert a fragment. Returns True on insert, False on update."""
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM fragments WHERE id = ?", (fragment.id,)
            ).fetchone() is not None
            self._conn.execute(
                """INSERT INTO fragments(
                    id, kind, text, subject, predicate, object,
                    scope, visibility, owner_user, project_id, firm_id,
                    confidence, provenance_json, valid_from, valid_until,
                    success_count, fail_count, last_used_at, half_life_days,
                    extra_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    text=excluded.text,
                    subject=excluded.subject,
                    predicate=excluded.predicate,
                    object=excluded.object,
                    scope=excluded.scope,
                    visibility=excluded.visibility,
                    provenance_json=excluded.provenance_json,
                    valid_until=excluded.valid_until,
                    success_count=excluded.success_count,
                    fail_count=excluded.fail_count,
                    last_used_at=excluded.last_used_at,
                    half_life_days=excluded.half_life_days,
                    extra_json=excluded.extra_json,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    fragment.id, fragment.kind.value, fragment.text,
                    fragment.subject, fragment.predicate, fragment.object,
                    fragment.scope.value, fragment.visibility.value,
                    fragment.owner_user, fragment.project_id, fragment.firm_id,
                    fragment.confidence.value,
                    fragment.provenance.model_dump_json(),
                    _iso(fragment.valid_from), _iso(fragment.valid_until),
                    fragment.success_count, fragment.fail_count,
                    _iso(fragment.last_used_at), fragment.half_life_days,
                    json.dumps(fragment.extra or {}),
                ),
            )
            return not existed

    def search_fragments(
        self,
        query: str,
        *,
        scope_filter: Optional[Iterable[Scope]] = None,
        owner_user: Optional[str] = None,
        kinds: Optional[Iterable[FragmentKind]] = None,
        k: int = 10,
    ) -> list[Fragment]:
        """FTS5 search over fragment text + subject + object.
        Slice 2 will add vector similarity ranking on top. Slice 7 will add
        bipartite ACL pre-filter."""
        clauses = []
        params: list[Any] = []
        # FTS5 match clause
        clauses.append(
            "fragments.rowid IN (SELECT rowid FROM fragments_fts WHERE fragments_fts MATCH ?)"
        )
        params.append(_fts_escape(query))
        if scope_filter is not None:
            scope_list = list(scope_filter)
            placeholders = ",".join("?" * len(scope_list))
            clauses.append(f"scope IN ({placeholders})")
            params.extend(s.value for s in scope_list)
        if owner_user is not None:
            clauses.append("(scope != 'user' OR owner_user = ?)")
            params.append(owner_user)
        if kinds is not None:
            kind_list = list(kinds)
            placeholders = ",".join("?" * len(kind_list))
            clauses.append(f"kind IN ({placeholders})")
            params.extend(k_.value for k_ in kind_list)
        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"""
            SELECT * FROM fragments
            WHERE {where}
            ORDER BY
              CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END DESC,
              last_used_at DESC,
              success_count DESC
            LIMIT ?
        """
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_fragment(r) for r in rows]

    def get_fragment(self, fragment_id: str) -> Optional[Fragment]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fragments WHERE id = ?", (fragment_id,)
            ).fetchone()
        return _row_to_fragment(row) if row else None

    def delete_fragment(self, fragment_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM fragments WHERE id = ?", (fragment_id,)
            )
            return cur.rowcount > 0

    def touch_fragment(self, fragment_id: str, *, success: bool = True) -> None:
        """Reinforcement — bumps last_used_at + success/fail counts. Per Nader
        reconsolidation: every read is an implicit edit signal."""
        with self._lock:
            if success:
                self._conn.execute(
                    """UPDATE fragments
                       SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           success_count = success_count + 1
                       WHERE id = ?""",
                    (fragment_id,),
                )
            else:
                self._conn.execute(
                    """UPDATE fragments
                       SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           fail_count = fail_count + 1
                       WHERE id = ?""",
                    (fragment_id,),
                )

    def count_fragments(self, scope: Optional[Scope] = None) -> int:
        with self._lock:
            if scope is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM fragments"
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM fragments WHERE scope = ?",
                    (scope.value,),
                ).fetchone()
        return int(row["n"]) if row else 0

    # ── skills ───────────────────────────────────────────────────────────

    def upsert_skill(self, skill: Skill) -> bool:
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM skills WHERE id = ?", (skill.id,)
            ).fetchone() is not None
            self._conn.execute(
                """INSERT INTO skills(
                    id, name, description, triggers_json, requires_mcps_json,
                    requires_secrets_json, body, examples_json, eval_queries_json,
                    scope, visibility, owner_user, provenance_json,
                    success_count, fail_count, last_used_at, minted_at,
                    honed_trials, honed_passed, side_effects
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    description=excluded.description,
                    triggers_json=excluded.triggers_json,
                    requires_mcps_json=excluded.requires_mcps_json,
                    requires_secrets_json=excluded.requires_secrets_json,
                    body=excluded.body,
                    examples_json=excluded.examples_json,
                    eval_queries_json=excluded.eval_queries_json,
                    success_count=excluded.success_count,
                    fail_count=excluded.fail_count,
                    last_used_at=excluded.last_used_at,
                    honed_trials=excluded.honed_trials,
                    honed_passed=excluded.honed_passed,
                    side_effects=excluded.side_effects
                """,
                (
                    skill.id, skill.name, skill.description,
                    json.dumps(skill.triggers),
                    json.dumps(skill.requires_mcps),
                    json.dumps(skill.requires_secrets),
                    skill.body,
                    json.dumps(skill.examples),
                    json.dumps(skill.eval_queries),
                    skill.scope.value, skill.visibility.value, skill.owner_user,
                    skill.provenance.model_dump_json(),
                    skill.success_count, skill.fail_count,
                    _iso(skill.last_used_at), _iso(skill.minted_at),
                    skill.honed_trials, skill.honed_passed,
                    skill.side_effects,
                ),
            )
            return not existed

    def search_skills(
        self,
        query: str,
        *,
        scope_filter: Optional[Iterable[Scope]] = None,
        owner_user: Optional[str] = None,
        k: int = 5,
    ) -> list[Skill]:
        clauses = [
            "skills.rowid IN (SELECT rowid FROM skills_fts WHERE skills_fts MATCH ?)"
        ]
        params: list[Any] = [_fts_escape(query)]
        if scope_filter is not None:
            scope_list = list(scope_filter)
            placeholders = ",".join("?" * len(scope_list))
            clauses.append(f"scope IN ({placeholders})")
            params.extend(s.value for s in scope_list)
        if owner_user is not None:
            clauses.append("(scope != 'user' OR owner_user = ?)")
            params.append(owner_user)
        where = " AND ".join(clauses)
        sql = f"""
            SELECT * FROM skills
            WHERE {where}
            ORDER BY
              success_count DESC,
              CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END DESC,
              last_used_at DESC
            LIMIT ?
        """
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_skill(self, skill_id_or_name: str) -> Optional[Skill]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skills WHERE id = ? OR name = ?",
                (skill_id_or_name, skill_id_or_name),
            ).fetchone()
        return _row_to_skill(row) if row else None

    def list_skills(
        self,
        *,
        scope_filter: Optional[Iterable[Scope]] = None,
        owner_user: Optional[str] = None,
        limit: int = 100,
    ) -> list[Skill]:
        clauses = []
        params: list[Any] = []
        if scope_filter is not None:
            scope_list = list(scope_filter)
            placeholders = ",".join("?" * len(scope_list))
            clauses.append(f"scope IN ({placeholders})")
            params.extend(s.value for s in scope_list)
        if owner_user is not None:
            clauses.append("(scope != 'user' OR owner_user = ?)")
            params.append(owner_user)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM skills{where} ORDER BY last_used_at DESC NULLS LAST LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_skill(r) for r in rows]

    def count_skills(self, scope: Optional[Scope] = None) -> int:
        with self._lock:
            if scope is None:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM skills WHERE scope = ?",
                    (scope.value,),
                ).fetchone()
        return int(row["n"]) if row else 0

    # ── wiring + secrets ─────────────────────────────────────────────────

    def upsert_wiring(self, entry: WiringEntry) -> bool:
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM wiring WHERE name=? AND device_id=?",
                (entry.name, entry.device_id),
            ).fetchone() is not None
            self._conn.execute(
                """INSERT INTO wiring(
                    name, device_id, kind, endpoint, auth_method,
                    capabilities_json, status, last_seen
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(name, device_id) DO UPDATE SET
                    kind=excluded.kind,
                    endpoint=excluded.endpoint,
                    auth_method=excluded.auth_method,
                    capabilities_json=excluded.capabilities_json,
                    status=excluded.status,
                    last_seen=excluded.last_seen
                """,
                (
                    entry.name, entry.device_id, entry.kind,
                    entry.endpoint, entry.auth_method,
                    json.dumps(entry.capabilities), entry.status,
                    _iso(entry.last_seen),
                ),
            )
            return not existed

    def list_wiring(
        self, *, device_id: Optional[str] = None, status: str = "active"
    ) -> list[WiringEntry]:
        sql = "SELECT * FROM wiring WHERE status = ?"
        params: list[Any] = [status]
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY name ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_wiring(r) for r in rows]

    def upsert_secret_ref(self, ref: SecretRef) -> bool:
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM secret_refs WHERE ref=? AND owner_user=?",
                (ref.ref, ref.owner_user),
            ).fetchone() is not None
            self._conn.execute(
                """INSERT INTO secret_refs(
                    ref, owner_user, resolver, description, scope, last_used_at
                ) VALUES (?,?,?,?,?,?)
                ON CONFLICT(ref, owner_user) DO UPDATE SET
                    resolver=excluded.resolver,
                    description=excluded.description,
                    scope=excluded.scope,
                    last_used_at=excluded.last_used_at
                """,
                (
                    ref.ref, ref.owner_user, ref.resolver, ref.description,
                    ref.scope.value, _iso(ref.last_used_at),
                ),
            )
            return not existed

    def list_secret_refs(
        self, owner_user: str, *, scope_filter: Optional[Iterable[Scope]] = None
    ) -> list[SecretRef]:
        sql = "SELECT * FROM secret_refs WHERE owner_user = ?"
        params: list[Any] = [owner_user]
        if scope_filter is not None:
            scope_list = list(scope_filter)
            placeholders = ",".join("?" * len(scope_list))
            sql += f" AND scope IN ({placeholders})"
            params.extend(s.value for s in scope_list)
        sql += " ORDER BY ref ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_secret(r) for r in rows]

    # ── audit ────────────────────────────────────────────────────────────

    def log_access(
        self, reader_user: str, fragment_id: str, purpose: Optional[str] = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO access_log(reader_user, fragment_id, purpose) VALUES (?,?,?)",
                (reader_user, fragment_id, purpose),
            )

    def access_log_for(self, fragment_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT reader_user, purpose, ts FROM access_log "
                "WHERE fragment_id = ? ORDER BY ts DESC LIMIT ?",
                (fragment_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── meta ─────────────────────────────────────────────────────────────

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO brain_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM brain_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    # ── batch write (Mem0-style ops) ────────────────────────────────────

    def apply_write_ops(self, ops: list[WriteOp]) -> WriteResponse:
        import time as _t

        t0 = _t.perf_counter()
        resp = WriteResponse()
        for op in ops:
            try:
                if op.op == WriteOpType.ADD or op.op == WriteOpType.UPDATE:
                    if op.fragment is None:
                        resp.errors.append(f"{op.op.value} op missing fragment")
                        continue
                    inserted = self.write_fragment(op.fragment)
                    resp.ops_applied += 1
                    if inserted:
                        resp.fragments_added += 1
                    else:
                        resp.fragments_updated += 1
                elif op.op == WriteOpType.DELETE:
                    if not op.fragment_id:
                        resp.errors.append("delete op missing fragment_id")
                        continue
                    if self.delete_fragment(op.fragment_id):
                        resp.fragments_deleted += 1
                    resp.ops_applied += 1
                elif op.op == WriteOpType.NOOP:
                    resp.fragments_noop += 1
                    resp.ops_applied += 1
            except Exception as ex:
                resp.errors.append(f"{op.op.value} failed: {ex}")
        resp.write_ms = (_t.perf_counter() - t0) * 1000.0
        return resp


# ─────────────────────────── helpers ────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%fZ")[:23] + "Z" if False else dt.isoformat()


def _fts_escape(query: str) -> str:
    """FTS5 query escaping. Strip operators that confuse the parser; wrap
    individual terms in double-quotes for safety. Trim to 200 chars."""
    if not query:
        return '""'
    safe = "".join(c if c.isalnum() or c.isspace() else " " for c in query[:200])
    tokens = [t for t in safe.split() if t]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)


def _row_to_fragment(row: sqlite3.Row) -> Fragment:
    prov_dict = json.loads(row["provenance_json"])
    prov = Provenance(**prov_dict)
    extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    return Fragment(
        id=row["id"],
        kind=FragmentKind(row["kind"]),
        text=row["text"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        scope=Scope(row["scope"]),
        visibility=Visibility(row["visibility"]),
        owner_user=row["owner_user"],
        project_id=row["project_id"],
        firm_id=row["firm_id"],
        confidence=Confidence(row["confidence"]),
        provenance=prov,
        valid_from=_parse_iso(row["valid_from"]),
        valid_until=_parse_iso(row["valid_until"]),
        success_count=row["success_count"],
        fail_count=row["fail_count"],
        last_used_at=_parse_iso(row["last_used_at"]),
        half_life_days=row["half_life_days"],
        extra=extra,
    )


def _row_to_skill(row: sqlite3.Row) -> Skill:
    prov = Provenance(**json.loads(row["provenance_json"]))
    return Skill(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        triggers=json.loads(row["triggers_json"]),
        requires_mcps=json.loads(row["requires_mcps_json"]),
        requires_secrets=json.loads(row["requires_secrets_json"]),
        body=row["body"],
        examples=json.loads(row["examples_json"]),
        eval_queries=json.loads(row["eval_queries_json"]),
        scope=Scope(row["scope"]),
        visibility=Visibility(row["visibility"]),
        owner_user=row["owner_user"],
        provenance=prov,
        success_count=row["success_count"],
        fail_count=row["fail_count"],
        last_used_at=_parse_iso(row["last_used_at"]),
        minted_at=_parse_iso(row["minted_at"]) or datetime.now(timezone.utc),
        honed_trials=row["honed_trials"],
        honed_passed=row["honed_passed"],
        side_effects=row["side_effects"],
    )


def _row_to_wiring(row: sqlite3.Row) -> WiringEntry:
    return WiringEntry(
        name=row["name"],
        device_id=row["device_id"],
        kind=row["kind"],
        endpoint=row["endpoint"],
        auth_method=row["auth_method"],
        capabilities=json.loads(row["capabilities_json"]),
        status=row["status"],
        last_seen=_parse_iso(row["last_seen"]) or datetime.now(timezone.utc),
    )


def _row_to_secret(row: sqlite3.Row) -> SecretRef:
    return SecretRef(
        ref=row["ref"],
        owner_user=row["owner_user"],
        resolver=row["resolver"],
        description=row["description"],
        scope=Scope(row["scope"]),
        last_used_at=_parse_iso(row["last_used_at"]),
    )


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # SQLite emits naive iso strings; coerce to UTC.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
