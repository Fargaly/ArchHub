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
from dataclasses import dataclass
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


# ──────────────── BRV-12 reconcile accessors + outcome ──────────────────
#
# Sibling lineage rides inside ``Fragment.extra`` (decision B, no new table).
# These module-level helpers are the read API for it so callers don't reach
# into ``extra`` dict keys directly.

_SIBLINGS_KEY = "__siblings__"
_RECONCILE_KEY = "__reconcile__"


@dataclass
class ReconcileOutcome:
    """Result of :meth:`BrainStore.write_fragment_versioned`."""

    fragment_id: str
    conflict: bool = False        # True iff divergent siblings now coexist
    sibling_count: int = 0        # distinct live value-branches
    head_hlc: str = ""            # HLC the persisted head value carries
    noop: bool = False            # True iff an idempotent replay (nothing changed)


def fragment_siblings(fragment: Optional[Fragment]) -> list[dict]:
    """Every retained value-branch of a fragment (head + concurrent siblings),
    each a ``FragmentVersion`` dict. Empty for fragments never written through
    the reconcile-aware path."""
    if fragment is None:
        return []
    sibs = (fragment.extra or {}).get(_SIBLINGS_KEY)
    return list(sibs) if isinstance(sibs, list) else []


def fragment_reconcile_record(fragment: Optional[Fragment]) -> Optional[dict]:
    """The pending/resolved ``ReconcileRecord`` dict for a fragment, or None if
    it has no recorded conflict."""
    if fragment is None:
        return None
    rec = (fragment.extra or {}).get(_RECONCILE_KEY)
    return rec if isinstance(rec, dict) else None


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
    -- Brain #31 multimodal columns (2026-05-26 founder ask):
    perceptual_hash TEXT,          -- 64-bit pHash hex / geometry derived hash
    blob_path TEXT,                -- sidecar blob pointer (sha256-addressed)
    blob_mime TEXT,                -- 'application/octet-stream' / 'image/png' / etc
    blob_bytes INTEGER NOT NULL DEFAULT 0,
    -- AgDR-0054 per-trace schema (founder-signed 2026-06-10). A trace/session record carries the
    -- fields the dam needs to compute training/export tiers, poisoning provenance, and unlearning
    -- (which is export-gating, since weights-level erasure is impossible). Legacy-safe defaults:
    -- untagged rows are human_verified + firm_private_only so old data is never auto-trained.
    origin_kind TEXT NOT NULL DEFAULT 'human_verified',            -- human_verified | model_generated
    generating_model_id TEXT,                                      -- e.g. claude-* ; keys the ToS/legal tier
    training_rights_tier TEXT NOT NULL DEFAULT 'firm_private_only',-- collective_ok|firm_private_only|quarantine_never_trains
    format_shape_descriptor TEXT,                                  -- prompt->tool->result fingerprint (mix + per-format poison cap)
    content_hash_pre TEXT,                                         -- integrity (Carlini split-view) + dedup
    content_hash_post TEXT,                                        -- post-redaction; train<->eval decontamination scan
    action_payload TEXT,                                           -- JSON: tool-calls + structured outcomes (Tier-0, ALWAYS trainable, ArchHub-owned)
    language_payload TEXT,                                         -- JSON: prose (Tier-1 human / Tier-2 provider-prose, gated)
    quarantine_flag INTEGER NOT NULL DEFAULT 0,                    -- 1 = never trains, never recalls
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

CREATE TABLE IF NOT EXISTS reputation (
    contributor_id TEXT PRIMARY KEY,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    quarantine_count INTEGER NOT NULL DEFAULT 0,
    avg_quality_score REAL NOT NULL DEFAULT 0.5,
    sybil_risk REAL NOT NULL DEFAULT 0.0,
    domains_json TEXT NOT NULL DEFAULT '{}',
    identity_json TEXT NOT NULL DEFAULT '{}',
    vouches_json TEXT NOT NULL DEFAULT '[]',
    stake_json TEXT NOT NULL DEFAULT '{}',
    first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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
        # busy_timeout is load-bearing for CROSS-PROCESS atomicity: update_meta's
        # critical section opens a BEGIN IMMEDIATE (RESERVED lock). When a SECOND
        # process is mid-claim and holds that lock, this connection's BEGIN
        # IMMEDIATE would otherwise fail instantly with "database is locked";
        # busy_timeout makes it WAIT (and retry) for the lock instead, so the two
        # claims serialise rather than one erroring out. Without it the
        # serialization degrades to a noisy error under contention.
        conn.execute("PRAGMA busy_timeout=10000")  # 10s
        conn.executescript(_SCHEMA)
        # Brain #31 multimodal — add columns to pre-existing DBs that
        # were created before the schema gained them. Idempotent;
        # ignores `duplicate column name` errors.
        for col_sql in (
            "ALTER TABLE fragments ADD COLUMN perceptual_hash TEXT",
            "ALTER TABLE fragments ADD COLUMN blob_path TEXT",
            "ALTER TABLE fragments ADD COLUMN blob_mime TEXT",
            "ALTER TABLE fragments ADD COLUMN blob_bytes INTEGER NOT NULL DEFAULT 0",
            # AgDR-0054 per-trace schema (founder-signed 2026-06-10) — additive, legacy-safe.
            "ALTER TABLE fragments ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'human_verified'",
            "ALTER TABLE fragments ADD COLUMN generating_model_id TEXT",
            "ALTER TABLE fragments ADD COLUMN training_rights_tier TEXT NOT NULL DEFAULT 'firm_private_only'",
            "ALTER TABLE fragments ADD COLUMN format_shape_descriptor TEXT",
            "ALTER TABLE fragments ADD COLUMN content_hash_pre TEXT",
            "ALTER TABLE fragments ADD COLUMN content_hash_post TEXT",
            "ALTER TABLE fragments ADD COLUMN action_payload TEXT",
            "ALTER TABLE fragments ADD COLUMN language_payload TEXT",
            "ALTER TABLE fragments ADD COLUMN quarantine_flag INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass  # column already present
        # Index for cheap perceptual-hash lookup (Brain #31 slice 2
        # similarity query rides this).
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fragments_phash "
                "ON fragments(perceptual_hash) "
                "WHERE perceptual_hash IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass
        # AgDR-0054 — indexes the export/dam filters ride (training tier + quarantine).
        for ix_sql in (
            "CREATE INDEX IF NOT EXISTS idx_fragments_rights ON fragments(training_rights_tier)",
            "CREATE INDEX IF NOT EXISTS idx_fragments_quarantine ON fragments(quarantine_flag)",
        ):
            try:
                conn.execute(ix_sql)
            except sqlite3.OperationalError:
                pass
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

    # ── AgDR-0054 training export — the legal/privacy dam at export time ──────
    def export_trainable_fragments(
        self, target: str = "collective", allow_provider_prose: bool = False
    ) -> list[dict]:
        """Select the trainable corpus per the AgDR-0054 tiers.

        Export-gating is the ONLY reliable unlearning (weights-level erasure is
        impossible — TOFU/quantization), so rights + quarantine are enforced HERE,
        not at recall.
          - quarantine_flag=1            -> NEVER trainable (any target).
          - target='collective'          -> only training_rights_tier='collective_ok'.
          - target='firm_private'        -> 'collective_ok' or 'firm_private_only'.
        Per row: action_payload (Tier-0, ArchHub-owned) is ALWAYS included;
        language_payload only for human-authored traces (Tier-1) unless
        allow_provider_prose (Tier-2 provider-prose gate — needs founder ToS ruling §7a).
        """
        if target == "collective":
            rights = ("collective_ok",)
        elif target == "firm_private":
            rights = ("collective_ok", "firm_private_only")
        else:
            raise ValueError(f"unknown export target: {target!r}")
        placeholders = ",".join("?" for _ in rights)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT id, origin_kind, training_rights_tier, action_payload,
                           language_payload, content_hash_post
                    FROM fragments
                    WHERE quarantine_flag = 0
                      AND training_rights_tier IN ({placeholders})""",
                rights,
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            lang = r["language_payload"]
            if (
                lang is not None
                and r["origin_kind"] != "human_verified"
                and not allow_provider_prose
            ):
                lang = None  # Tier-2 provider-prose gated out of the competing-model corpus
            out.append(
                {
                    "id": r["id"],
                    "action_payload": r["action_payload"],  # Tier-0 — always
                    "language_payload": lang,               # Tier-1 human / Tier-2 gated
                    "content_hash_post": r["content_hash_post"],
                }
            )
        return out

    # ── fragments ────────────────────────────────────────────────────────

    def write_fragment(self, fragment: Fragment) -> bool:
        """Upsert a fragment. Returns True on insert, False on update."""
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM fragments WHERE id = ?", (fragment.id,)
            ).fetchone() is not None
            # Serialise embedding to a tightly-packed BLOB so the SQLite
            # column stays compact. struct.pack(<N>d) gives 8 bytes per
            # float — a 512-dim CLIP vector = 4096 bytes.
            embedding_blob = None
            if fragment.embedding:
                import struct as _struct
                embedding_blob = _struct.pack(
                    f"<{len(fragment.embedding)}d",
                    *fragment.embedding,
                )

            self._conn.execute(
                """INSERT INTO fragments(
                    id, kind, text, subject, predicate, object,
                    scope, visibility, owner_user, project_id, firm_id,
                    confidence, provenance_json, valid_from, valid_until,
                    embedding_blob,
                    success_count, fail_count, last_used_at, half_life_days,
                    extra_json,
                    perceptual_hash, blob_path, blob_mime, blob_bytes,
                    origin_kind, generating_model_id, training_rights_tier,
                    format_shape_descriptor, content_hash_pre, content_hash_post,
                    action_payload, language_payload, quarantine_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    perceptual_hash=excluded.perceptual_hash,
                    blob_path=excluded.blob_path,
                    blob_mime=excluded.blob_mime,
                    blob_bytes=excluded.blob_bytes,
                    embedding_blob=excluded.embedding_blob,
                    origin_kind=excluded.origin_kind,
                    generating_model_id=excluded.generating_model_id,
                    training_rights_tier=excluded.training_rights_tier,
                    format_shape_descriptor=excluded.format_shape_descriptor,
                    content_hash_pre=excluded.content_hash_pre,
                    content_hash_post=excluded.content_hash_post,
                    action_payload=excluded.action_payload,
                    language_payload=excluded.language_payload,
                    quarantine_flag=excluded.quarantine_flag,
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
                    embedding_blob,
                    fragment.success_count, fragment.fail_count,
                    _iso(fragment.last_used_at), fragment.half_life_days,
                    json.dumps(fragment.extra or {}),
                    fragment.perceptual_hash,
                    fragment.blob_path,
                    fragment.blob_mime,
                    int(fragment.blob_bytes or 0),
                    # AgDR-0054 per-trace fields — persisted so the export dam can
                    # tier them. None-safe: NULL columns fall back to SQL defaults
                    # only on a fresh row; here we always pass the model's value
                    # (whose defaults already match the column defaults).
                    fragment.origin_kind,
                    fragment.generating_model_id,
                    fragment.training_rights_tier,
                    fragment.format_shape_descriptor,
                    fragment.content_hash_pre,
                    fragment.content_hash_post,
                    fragment.action_payload,
                    fragment.language_payload,
                    int(bool(fragment.quarantine_flag)),
                ),
            )
            return not existed

    # ── BRV-12: reconcile-aware write (decision B — siblings, not LWW) ────

    def write_fragment_versioned(
        self,
        fragment: Fragment,
        *,
        hlc: str,
        source: str = "",
        parent_hlc: Optional[str] = None,
    ) -> "ReconcileOutcome":
        """Write a fragment with concurrent-edit reconciliation.

        Unlike :meth:`write_fragment` (a plain last-writer-wins upsert), this
        path treats a DIVERGENT concurrent write — a different value whose HLC
        is NOT a causal descendant of the stored head — as a CONFLICT: it
        retains BOTH values as sibling ``FragmentVersion`` branches and attaches
        a pending ``ReconcileRecord`` instead of silently overwriting (decision
        B, AgDR-0044 acceptance #5). The head row keeps the highest-HLC value so
        every existing reader/search path is unchanged.

        Lineage (``__siblings__`` + ``__reconcile__`` + the head ``hlc``) rides
        inside ``Fragment.extra`` — ONE-SYSTEM, no new table. The single SQL
        upsert is reused by delegating the row write to ``write_fragment``.

        Cases:
          • new id                 → head version, no conflict.
          • idempotent replay      → identical (hlc,value) already present → noop.
          • linear successor       → ``parent_hlc`` == stored head hlc (or same
                                     value) → advance head, no pending conflict.
          • concurrent divergent   → different value, non-descendant hlc → BOTH
                                     retained as siblings + pending reconcile.
        """
        from .models import FragmentVersion, ReconcileRecord

        with self._lock:
            existing = self.get_fragment(fragment.id)
            incoming_value = fragment.text or ""

            # ── first write — just a head, no lineage conflict ───────────
            if existing is None:
                head_ver = FragmentVersion(
                    value=incoming_value, hlc=hlc, source=source,
                    verdict="head", parent_hlc=parent_hlc,
                )
                fragment.extra = dict(fragment.extra or {})
                fragment.extra["hlc"] = hlc
                fragment.extra["__siblings__"] = [head_ver.model_dump(mode="json")]
                self.write_fragment(fragment)
                return ReconcileOutcome(
                    fragment_id=fragment.id, conflict=False, sibling_count=1,
                    head_hlc=hlc,
                )

            # ── reconstruct the existing lineage ─────────────────────────
            prev_extra = dict(existing.extra or {})
            head_hlc = str(prev_extra.get("hlc") or "")
            versions: list[dict] = list(prev_extra.get("__siblings__") or [])
            if not versions:
                # Legacy row written via plain write_fragment — seed its
                # current value as the head branch so nothing is lost.
                versions = [FragmentVersion(
                    value=existing.text or "", hlc=head_hlc or "",
                    source="", verdict="head",
                ).model_dump(mode="json")]

            def _has(v_hlc: str, v_val: str) -> bool:
                return any(
                    (x.get("hlc") == v_hlc and (x.get("value") or "") == v_val)
                    for x in versions
                )

            # ── idempotent replay — identical (hlc,value) already present ──
            if _has(hlc, incoming_value):
                return ReconcileOutcome(
                    fragment_id=fragment.id, conflict=False,
                    sibling_count=len(versions), head_hlc=head_hlc,
                    noop=True,
                )

            same_value = incoming_value == (existing.text or "")
            # Linear successor iff the writer declares the current head as its
            # parent, OR it merely re-states the same value (no divergence).
            is_linear = bool(parent_hlc and parent_hlc == head_hlc) or same_value

            # Record the incoming branch.
            incoming_ver = FragmentVersion(
                value=incoming_value, hlc=hlc, source=source,
                verdict="sibling", parent_hlc=parent_hlc,
            ).model_dump(mode="json")
            versions.append(incoming_ver)

            # ── decide the head: highest HLC wins (deterministic) ────────
            def _hlc_key(v: dict) -> str:
                return str(v.get("hlc") or "")

            winner = max(versions, key=_hlc_key)
            winner_hlc = str(winner.get("hlc") or "")
            for v in versions:
                v["verdict"] = "head" if v is winner else "sibling"

            # Distinct concurrent VALUE branches still live (dedup by value).
            distinct_values = {
                (v.get("value") or "") for v in versions
                if v.get("verdict") != "discarded"
            }
            conflict = (not is_linear) and len(distinct_values) >= 2

            new_extra = dict(fragment.extra or {})
            # preserve any non-lineage keys the caller didn't carry over
            for k, val in prev_extra.items():
                if k not in ("hlc", "__siblings__", "__reconcile__"):
                    new_extra.setdefault(k, val)
            new_extra["hlc"] = winner_hlc
            new_extra["__siblings__"] = versions
            if conflict:
                new_extra["__reconcile__"] = ReconcileRecord(
                    state="pending", sibling_count=len(distinct_values),
                ).model_dump(mode="json")
            else:
                # linear/idempotent path clears any stale pending marker
                new_extra.pop("__reconcile__", None)

            # The persisted row serves the WINNER's value (head), not
            # necessarily the incoming write — so an older concurrent write
            # never clobbers a newer head.
            fragment.text = winner.get("value") or ""
            fragment.extra = new_extra
            self.write_fragment(fragment)
            return ReconcileOutcome(
                fragment_id=fragment.id, conflict=conflict,
                sibling_count=len(distinct_values), head_hlc=winner_hlc,
            )

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

    def list_fragments(
        self,
        *,
        scope_filter: Optional[Iterable[Scope]] = None,
        kinds: Optional[Iterable[FragmentKind]] = None,
        owner_user: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 1000,
    ) -> list[Fragment]:
        """Enumerate fragments by filter — NO FTS query.

        Used by Brain #32 dataset export (HuggingFace-style training-data
        dump) — needs full enumeration, not text-relevance ranking. The
        FTS-based `search_fragments` requires a text query and ranks by
        FTS relevance; this method walks the table by filter only.

        Filters:
          - scope_filter: only fragments in these scopes
          - kinds: only fragments of these kinds (fact/skill/etc)
          - owner_user: USER-scope rows must match this owner (other
            scopes pass through — ACL gating happens upstream)
          - since: ISO8601 timestamp; only fragments created at or after
          - limit: cap (default 1000; pass a large number for full dump)

        Ordered by created_at DESC so the most-recent first if you want
        only the last N.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if scope_filter is not None:
            scope_list = list(scope_filter)
            if scope_list:
                placeholders = ",".join("?" * len(scope_list))
                clauses.append(f"scope IN ({placeholders})")
                params.extend(s.value for s in scope_list)
        if kinds is not None:
            kind_list = list(kinds)
            if kind_list:
                placeholders = ",".join("?" * len(kind_list))
                clauses.append(f"kind IN ({placeholders})")
                params.extend(k_.value for k_ in kind_list)
        if owner_user is not None:
            clauses.append("(scope != 'user' OR owner_user = ?)")
            params.append(owner_user)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"""
            SELECT * FROM fragments
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_fragment(r) for r in rows]

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

    def touch_skill(self, skill_id: str, *, success: bool = True) -> None:
        """Reinforcement — bumps last_used_at + success/fail counts on a
        skill. Mirror of `touch_fragment` for the skills table. This is the
        counter the federation sharing gate reads (`derive_skill_usage_patterns`
        requires success_count >= 3): without it, no skill ever becomes
        shareable no matter how often it is retrieved and used."""
        with self._lock:
            if success:
                self._conn.execute(
                    """UPDATE skills
                       SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           success_count = success_count + 1
                       WHERE id = ?""",
                    (skill_id,),
                )
            else:
                self._conn.execute(
                    """UPDATE skills
                       SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           fail_count = fail_count + 1
                       WHERE id = ?""",
                    (skill_id,),
                )

    def list_skills(
        self,
        scope: Optional[Scope] = None,
        limit: int = 100,
        *,
        scope_filter: Optional[Iterable[Scope]] = None,
        owner_user: Optional[str] = None,
    ) -> list[Skill]:
        """List skills, optionally filtered by scope.

        Two call styles:
          • `list_skills(scope=Scope.COMMUNITY, limit=100)` — content-ecosystem
            export path (CONTENT-ECOSYSTEM-2026-05-26.md §2). Used by
            `brain.skill_export` MCP tool for static-site builds.
          • `list_skills(scope_filter=[...], owner_user="x", limit=100)` —
            multi-scope ACL-aware path. Preserved for prior callers.

        Ordering: most-recently-used first; ties broken by NULL-last so newly
        minted unused skills still surface for the website export.
        """
        clauses = []
        params: list[Any] = []
        # Build effective scope filter — `scope` positional wins if both given.
        effective_scopes: Optional[list[Scope]] = None
        if scope is not None:
            effective_scopes = [scope]
        elif scope_filter is not None:
            effective_scopes = list(scope_filter)
        if effective_scopes:
            placeholders = ",".join("?" * len(effective_scopes))
            clauses.append(f"scope IN ({placeholders})")
            params.extend(s.value for s in effective_scopes)
        if owner_user is not None:
            clauses.append("(scope != 'user' OR owner_user = ?)")
            params.append(owner_user)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            f"SELECT * FROM skills{where} "
            "ORDER BY last_used_at IS NULL, last_used_at DESC, minted_at DESC "
            "LIMIT ?"
        )
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

    # ── reputation (Slice 15) ───────────────────────────────────────────

    def upsert_reputation(self, peer_dict: dict[str, Any]) -> bool:
        """Upsert a PeerV2-shaped reputation row. `peer_dict` should
        contain: contributor_id, accepted_count, rejected_count,
        quarantine_count, avg_quality_score, sybil_risk, domains,
        identity, vouches, stake, first_seen."""
        cid = peer_dict["contributor_id"]
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM reputation WHERE contributor_id = ?", (cid,),
            ).fetchone() is not None
            self._conn.execute(
                """INSERT INTO reputation (
                    contributor_id, accepted_count, rejected_count,
                    quarantine_count, avg_quality_score, sybil_risk,
                    domains_json, identity_json, vouches_json, stake_json,
                    first_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(contributor_id) DO UPDATE SET
                    accepted_count = excluded.accepted_count,
                    rejected_count = excluded.rejected_count,
                    quarantine_count = excluded.quarantine_count,
                    avg_quality_score = excluded.avg_quality_score,
                    sybil_risk = excluded.sybil_risk,
                    domains_json = excluded.domains_json,
                    identity_json = excluded.identity_json,
                    vouches_json = excluded.vouches_json,
                    stake_json = excluded.stake_json,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    cid,
                    int(peer_dict.get("accepted_count", 0)),
                    int(peer_dict.get("rejected_count", 0)),
                    int(peer_dict.get("quarantine_count", 0)),
                    float(peer_dict.get("avg_quality_score", 0.5)),
                    float(peer_dict.get("sybil_risk", 0.0)),
                    json.dumps(peer_dict.get("domains", {})),
                    json.dumps(peer_dict.get("identity", {})),
                    json.dumps(peer_dict.get("vouches", [])),
                    json.dumps(peer_dict.get("stake", {})),
                    peer_dict.get("first_seen") or "",
                ),
            )
            return not existed

    def get_reputation(self, contributor_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reputation WHERE contributor_id = ?",
                (contributor_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "contributor_id": row["contributor_id"],
            "accepted_count": row["accepted_count"],
            "rejected_count": row["rejected_count"],
            "quarantine_count": row["quarantine_count"],
            "avg_quality_score": row["avg_quality_score"],
            "sybil_risk": row["sybil_risk"],
            "domains": json.loads(row["domains_json"]),
            "identity": json.loads(row["identity_json"]),
            "vouches": json.loads(row["vouches_json"]),
            "stake": json.loads(row["stake_json"]),
            "first_seen": row["first_seen"],
            "updated_at": row["updated_at"],
        }

    def list_reputations(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM reputation ORDER BY updated_at DESC",
            ).fetchall()
        return [
            {
                "contributor_id": r["contributor_id"],
                "accepted_count": r["accepted_count"],
                "rejected_count": r["rejected_count"],
                "quarantine_count": r["quarantine_count"],
                "avg_quality_score": r["avg_quality_score"],
                "sybil_risk": r["sybil_risk"],
                "domains": json.loads(r["domains_json"]),
                "identity": json.loads(r["identity_json"]),
                "vouches": json.loads(r["vouches_json"]),
                "stake": json.loads(r["stake_json"]),
                "first_seen": r["first_seen"],
                "updated_at": r["updated_at"],
            } for r in rows
        ]

    # ── doc backlink graph (Track C, AgDR-0042 docs extractor) ─────────

    def doc_links(self, file: str) -> dict[str, Any]:
        """Backlink graph for a documentation file.

        Honest scope (per ANTI-LIE): scaffolded + tests green. Backlink
        mining IS NOT production-grade — it walks fragments of
        kind=document and looks for forward references in
        Fragment.text / extra.deps / extra.artifacts using simple
        substring matching on the doc slug + path.

        Real graph backlinks would query a dedicated edge table
        (`memory_edges` per AgDR-0042) that this slice does not yet
        populate from the docs extractor. Production version SQL hint:

            SELECT source FROM memory_edges
            WHERE target = ? AND relation IN
                ('cites','depends_on','references','linked_from');

        Returns:
            {ok, file, backlinks: [doc_slug, ...],
             forward_links: [doc_slug, ...],
             freshness_score: 0.0..1.0,
             note: "scaffolded"}
        """
        # Normalise: support both 'docs/X.md' and bare 'X' slug.
        slug = file.replace("\\", "/").rsplit("/", 1)[-1]
        if slug.endswith(".md"):
            slug = slug[:-3]
        path_token = file.replace("\\", "/")

        backlinks: list[str] = []
        forward_links: list[str] = []
        my_extra: dict[str, Any] = {}
        my_freshness: Optional[float] = None

        with self._lock:
            # All document fragments — scan O(n_docs); fine for n<10k.
            rows = self._conn.execute(
                "SELECT id, text, subject, object, extra_json "
                "FROM fragments WHERE kind = ?",
                (FragmentKind.DOCUMENT.value,),
            ).fetchall()

        for r in rows:
            rid = r["id"]
            text = r["text"] or ""
            subj = r["subject"] or ""
            obj = r["object"] or ""
            try:
                extra = json.loads(r["extra_json"]) if r["extra_json"] else {}
            except Exception:
                extra = {}
            # The doc itself
            if rid == f"doc:{slug}" or subj == path_token or subj == slug:
                my_extra = extra
                fs = extra.get("freshness_score")
                if isinstance(fs, (int, float)):
                    my_freshness = float(fs)
                # forward_links come from this fragment's extra.deps
                deps = extra.get("deps") or []
                if isinstance(deps, list):
                    forward_links.extend(str(d) for d in deps if d)
                continue
            # Backlink heuristic: some OTHER doc text mentions our path/slug.
            haystack = f"{text} {obj}"
            if path_token in haystack or f"docs/{slug}.md" in haystack:
                # Pull the other doc's slug from its subject if available.
                other_slug = subj.rsplit("/", 1)[-1]
                if other_slug.endswith(".md"):
                    other_slug = other_slug[:-3]
                backlinks.append(other_slug or rid)

        # Default freshness if doc not yet indexed: 0.5 (unknown).
        score = my_freshness if my_freshness is not None else 0.5
        score = max(0.0, min(1.0, score))
        return {
            "ok": True,
            "file": file,
            "backlinks": sorted(set(backlinks)),
            "forward_links": sorted(set(forward_links)),
            "freshness_score": score,
            "note": "scaffolded — substring backlink mining; not full graph",
        }

    # ── a11y prefs (Track E, accessibility audit 2026-05-26) ────────────

    DEFAULT_A11Y_PREFS = {
        "font_size": "medium",          # small | medium | large | xlarge
        "contrast": "normal",           # normal | high
        "reduce_motion": False,
        "screen_reader_optimised": False,
    }

    def a11y_prefs(
        self,
        mode: str,
        prefs: Optional[dict[str, Any]] = None,
        owner_user: str = "founder",
    ) -> dict[str, Any]:
        """Get / set per-user accessibility preferences.

        Stored as a single `Fragment(kind=SETUP, predicate="a11y",
        scope=USER, owner_user=<owner>)` whose ``object`` is the JSON-
        encoded prefs payload. One fragment per user; ``set`` overwrites.

        Args:
            mode: ``"get"`` or ``"set"``.
            prefs: required for ``set`` — dict with any subset of
                ``font_size``, ``contrast``, ``reduce_motion``,
                ``screen_reader_optimised``. Unknown keys are kept (no
                schema enforcement at the storage layer); missing keys
                fall back to the defaults on subsequent ``get``.
            owner_user: per-user scope. Defaults to ``"founder"``.

        Returns:
            ``{"ok": True, "prefs": <dict>, "mode": <mode>}`` on success.
            ``{"ok": False, "error": "..."}`` on bad input.

        Raises:
            ValueError: when ``mode`` is not ``"get"`` or ``"set"``.
        """
        if mode not in ("get", "set"):
            raise ValueError(
                f"a11y_prefs mode must be 'get' or 'set', got {mode!r}"
            )

        fragment_id = f"a11y:{owner_user}"

        if mode == "set":
            if not isinstance(prefs, dict):
                return {
                    "ok": False,
                    "error": "set mode requires a prefs dict",
                }
            # Merge against current (so partial updates don't drop keys).
            current = self._a11y_load(owner_user)
            merged = {**current, **prefs}

            now = datetime.now(timezone.utc)
            frag = Fragment(
                id=fragment_id,
                kind=FragmentKind.SETUP,
                text=f"a11y prefs for {owner_user}: "
                     f"font={merged.get('font_size','?')} "
                     f"contrast={merged.get('contrast','?')} "
                     f"motion={'reduced' if merged.get('reduce_motion') else 'normal'} "
                     f"sr={'on' if merged.get('screen_reader_optimised') else 'off'}",
                subject=owner_user,
                predicate="a11y",
                object=json.dumps(merged, sort_keys=True),
                scope=Scope.USER,
                visibility=Visibility.PRIVATE,
                owner_user=owner_user,
                confidence=Confidence.EXTRACTED,
                provenance=Provenance(
                    contributing_agent="settings-dialog",
                    contributing_user=owner_user,
                    created_at=now,
                ),
                last_used_at=now,
            )
            self.write_fragment(frag)
            return {"ok": True, "mode": "set", "prefs": merged}

        # mode == "get"
        loaded = self._a11y_load(owner_user)
        return {"ok": True, "mode": "get", "prefs": loaded}

    def _a11y_load(self, owner_user: str) -> dict[str, Any]:
        """Return the current a11y prefs for ``owner_user`` merged on
        top of :pyattr:`DEFAULT_A11Y_PREFS`. Empty store → defaults."""
        fragment_id = f"a11y:{owner_user}"
        with self._lock:
            row = self._conn.execute(
                "SELECT object FROM fragments "
                "WHERE id = ? AND predicate = ? AND owner_user = ?",
                (fragment_id, "a11y", owner_user),
            ).fetchone()
        merged = dict(self.DEFAULT_A11Y_PREFS)
        if not row or not row["object"]:
            return merged
        try:
            stored = json.loads(row["object"])
            if isinstance(stored, dict):
                merged.update(stored)
        except Exception:
            pass
        return merged

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

    def update_meta(self, key: str, fn: "Any") -> "Any":
        """Atomic read-modify-write of a single brain_meta key — IN-PROCESS *and*
        CROSS-PROCESS safe.

        The RLock alone closes the in-PROCESS TOCTOU window (two THREADS sharing
        this connection can't split the get→decide→set). But the RLock gives ZERO
        protection across PROCESSES: a second daemon / an in-process hook has its
        own connection and its own RLock. On the autocommit path
        (``isolation_level=None``) the ``SELECT`` below holds no database lock, so
        process A and process B could BOTH read the old value, BOTH decide, and
        BOTH write — the cross-process double-claim the court reproduced.

        The fix wraps the whole critical section in ``BEGIN IMMEDIATE … COMMIT``.
        ``BEGIN IMMEDIATE`` takes a RESERVED lock on the database AT ONCE (not
        deferred to the first write), and SQLite permits only one RESERVED lock
        at a time — so a concurrent process's ``BEGIN IMMEDIATE`` blocks (and,
        thanks to ``busy_timeout``, WAITS) until this COMMIT. The read-decide-
        write therefore serialises across connections/processes, not just
        threads. On error we ROLL BACK so a failed decide never half-writes.

        ``fn(old_value: Optional[str]) -> (new_value: Optional[str], result)``:
        receives the current raw string (or None), returns the new raw string to
        persist plus an arbitrary result handed back to the caller. Returning
        ``new_value is None`` leaves the key untouched (a pure read — the
        transaction still COMMITs, releasing the lock). Because the RLock is
        re-entrant AND a re-entrant call detects the already-open transaction
        (``in_transaction``) and does NOT start a nested ``BEGIN``, ``fn`` may
        itself call ``get_meta`` / ``set_meta`` (or recover via the durable load)
        without deadlocking or "cannot start a transaction within a transaction"
        — the inner statements simply join the outer transaction. This is what
        lets the JSON-doc stores route their read-modify-write through one
        serialised critical section. BOTH such stores do so for real:
        ``active_work.ActiveWorkStore._mutate`` AND
        ``requirement_tree.TreeStore._mutate`` (the latter wired here so its
        ``claim_leaf`` is a genuine cross-process CAS — exactly one winner per
        contested leaf across processes, no TOCTOU double-claim).
        """
        with self._lock:
            # Re-entrancy guard: if we're ALREADY inside a transaction (a nested
            # update_meta under the same re-entrant RLock), don't open a second
            # one — let the outermost call own the BEGIN/COMMIT so the inner work
            # joins it. Only the outer transaction-owner commits/rolls back.
            owns_txn = not self._conn.in_transaction
            if owns_txn:
                # IMMEDIATE = grab the RESERVED write-lock now, so the SELECT that
                # follows is already inside the serialised critical section (no
                # other process can read-then-claim concurrently).
                self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT value FROM brain_meta WHERE key = ?", (key,)
                ).fetchone()
                old = row["value"] if row else None
                new_value, result = fn(old)
                if new_value is not None:
                    self._conn.execute(
                        "INSERT INTO brain_meta(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, new_value),
                    )
                if owns_txn:
                    self._conn.execute("COMMIT")
                return result
            except BaseException:
                if owns_txn and self._conn.in_transaction:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise

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

    # ── MemoryGraph absorb (ONE-SYSTEM unify — AgDR-0042 ⇄ AgDR-0044) ──────
    #
    # The app's knowledge-graph store (app/memory/graph.py MemoryGraph,
    # graph.sqlite) and this brain store (brain.db) used to be TWO disjoint
    # SQLite files reconciled only by the manual band-aid tools/brain_unify.py
    # (the ONE-SYSTEM-PLAN-BEFORE-BUILD debt the founder flagged 2026-05-28).
    # These primitives let the brain store BE the graph: a MemoryGraph node is
    # persisted as ONE Fragment row in brain.db using the EXACT id + kind
    # convention brain_unify.unify() established (`graph:<node.id>`,
    # capability→FACT/predicate="capability", decision→DOCUMENT/predicate=
    # "decision", skill→FACT/predicate=<kind>), so a fact written through
    # either surface is the SAME row. graph_adapter.MemoryGraphStore wraps
    # these to present the full MemoryGraph API over this one store — no second
    # store, no sync, no schema migration (edges are kept BOTH as first-class
    # edge fragments AND as the legacy extra["graph_edges"] sidecar so prior
    # readers and the topology queries both keep working).

    GRAPH_NODE_ID_PREFIX = "graph:"
    GRAPH_EDGE_ID_PREFIX = "graphedge:"
    # graph node.kind → (FragmentKind, predicate). Mirrors brain_unify._KIND_MAP
    # exactly so both surfaces encode identically. Unmapped kinds fall back to
    # FACT with the raw kind as predicate (nothing is ever dropped).
    _GRAPH_KIND_MAP: dict[str, "tuple[FragmentKind, str]"] = {
        "capability": (FragmentKind.FACT, "capability"),
        "decision": (FragmentKind.DOCUMENT, "decision"),
        "skill": (FragmentKind.FACT, "skill"),
    }

    def write_graph_node(
        self,
        node: "Any",
        *,
        owner_user: str = "founder",
        scope: "Scope" = Scope.PROJECT,
        visibility: "Visibility" = Visibility.PRIVATE,
        contributing_agent: str = "memory_graph",
    ) -> bool:
        """Persist a MemoryGraph-shaped node as a Fragment in THIS brain.db.

        `node` is duck-typed to app.memory.graph.MemoryNode — it must expose
        ``id``, ``kind``, ``label``, ``props``. The row id is the canonical
        ``graph:<node.id>`` so it is byte-for-byte the same fragment
        brain_unify.unify() would have written; the original graph kind +
        props ride in ``extra`` so the reverse decode is lossless. Returns
        True on insert, False on update (mirrors write_fragment)."""
        kind, predicate = self._GRAPH_KIND_MAP.get(
            node.kind, (FragmentKind.FACT, node.kind)
        )
        label = node.label or node.id
        props = dict(node.props or {})
        # Deterministic props blob so re-writes of an unchanged node are
        # idempotent (matches brain_unify._serialize_props).
        if props:
            try:
                props_blob = json.dumps(props, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                props_blob = repr(sorted(props.items()))
        else:
            props_blob = ""
        text = f"{label} {props_blob}".rstrip() if props_blob else label
        extra: dict[str, Any] = {
            "graph_node_id": node.id,
            "graph_kind": node.kind,
        }
        if props:
            extra["graph_props"] = props
        # Preserve the legacy edge sidecar (incident edges) so prior readers
        # (and the brain_unify tests) keep seeing extra["graph_edges"].
        extra["graph_edges"] = self._incident_edge_dicts(node.id)
        frag = Fragment(
            id=f"{self.GRAPH_NODE_ID_PREFIX}{node.id}",
            kind=kind,
            text=text,
            subject=label,
            predicate=predicate,
            object=None,
            scope=scope,
            visibility=visibility,
            owner_user=owner_user,
            confidence=Confidence.EXTRACTED,
            provenance=Provenance(
                contributing_agent=contributing_agent,
                contributing_user=owner_user,
                created_at=datetime.now(timezone.utc),
            ),
            extra=extra,
        )
        return self.write_fragment(frag)

    def get_graph_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """Read a graph node back as a plain dict ``{id, kind, label, props}``
        (the MemoryNode shape) from its Fragment row. None if absent.

        The original graph kind is recovered from ``extra.graph_kind``
        (authoritative — survives the lossy decision→DOCUMENT fold); props
        from ``extra.graph_props``. This is the reverse of write_graph_node,
        so a node written via the MemoryGraph surface round-trips exactly."""
        frag = self.get_fragment(f"{self.GRAPH_NODE_ID_PREFIX}{node_id}")
        if frag is None:
            return None
        return self._fragment_to_graph_node(frag)

    def all_graph_nodes(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        """Every graph node (optionally filtered by ORIGINAL graph kind),
        as MemoryNode-shaped dicts. Walks the fragment rows whose id carries
        the ``graph:`` prefix."""
        like = f"{self.GRAPH_NODE_ID_PREFIX}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fragments WHERE id LIKE ? ESCAPE '\\'",
                (like.replace("_", r"\_"),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            frag = _row_to_fragment(r)
            node = self._fragment_to_graph_node(frag)
            if kind is not None and node["kind"] != kind:
                continue
            out.append(node)
        return out

    def count_graph_nodes(self, kind: Optional[str] = None) -> int:
        """Count graph nodes (optionally by original graph kind)."""
        if kind is None:
            like = f"{self.GRAPH_NODE_ID_PREFIX}%".replace("_", r"\_")
            with self._lock:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM fragments "
                    "WHERE id LIKE ? ESCAPE '\\'",
                    (like,),
                ).fetchone()
            return int(row["n"]) if row else 0
        # kind-filtered: decode is needed (graph kind lives in extra), so
        # fall back to the python filter.
        return len(self.all_graph_nodes(kind=kind))

    def remove_graph_node(self, node_id: str) -> bool:
        """Delete a graph node fragment AND every edge fragment incident to
        it (keeps the unified graph consistent, mirroring
        MemoryGraph.remove_node). Returns False if the node didn't exist."""
        with self._lock:
            # Drop incident edge fragments first.
            for ed in self._incident_edge_dicts(node_id):
                eid = self._edge_fragment_id(
                    ed["source"], ed["target"], ed["relation"]
                )
                self._conn.execute("DELETE FROM fragments WHERE id = ?", (eid,))
            cur = self._conn.execute(
                "DELETE FROM fragments WHERE id = ?",
                (f"{self.GRAPH_NODE_ID_PREFIX}{node_id}",),
            )
            return cur.rowcount > 0

    # ── graph edges (first-class edge fragments) ──────────────────────────

    # Edge-id encoding (court defect, BRV-01 re-fix — data loss).
    #
    # The OLD scheme joined (source, target, relation) with a literal "||"
    # separator and ASSERTED in a comment that node ids "never contain '|'".
    # That invariant was FALSE: the extractor slug builders interpolate
    # UN-sanitised names (app/memory/extractors: _tool_id → "tool:<name>",
    # _cap_id → "lib:cap:<type>", _doc_id → "doc:<file-stem>"), so a doc
    # literally named "a||x.md" — or any tool/type carrying a '|' — produces a
    # node id containing the separator. Two DISTINCT edges then forged the SAME
    # id and silently overwrote each other (the court repro:
    # (a||x -> y) and (a -> x||y) BOTH mapped to graphedge:a||x||y), a
    # regression vs the standalone store's composite (source,target,relation)
    # PRIMARY KEY.
    #
    # FIX: the edge identity is now a SHA-256 over the LENGTH-PREFIXED triple.
    # Length-prefixing each component ("<len>:<value>") makes the byte stream
    # injective — no component value can ever forge a boundary, because the
    # decoder (conceptually) reads exactly <len> bytes — so distinct triples
    # map to distinct digests (collisions are cryptographically impossible, not
    # merely "unlikely given an assumed-absent separator"). The id is
    # OPAQUE: the (source,target,relation) triple is NEVER recovered FROM the id
    # (it rides verbatim in the fragment's ``extra``; see write_graph_edge /
    # _fragment_to_graph_edge), so id-shape no longer constrains node ids at all.
    GRAPH_EDGE_ID_HASH_LEN = 40  # hex chars of the sha256 kept in the id

    @staticmethod
    def _edge_identity_payload(source: str, target: str, relation: str) -> bytes:
        """Injective byte-encoding of the edge triple — length-prefixed
        components so NO value can forge a component boundary (the ambiguity
        the literal-separator scheme had). ``str(len)`` is itself unambiguous
        because it is followed by a literal ':' and then EXACTLY that many
        UTF-8 bytes."""
        parts = []
        for comp in (source, target, relation):
            raw = str(comp).encode("utf-8")
            parts.append(f"{len(raw)}:".encode("ascii") + raw)
        return b"\x1f".join(parts)  # 0x1f unit-sep, belt-and-braces between fields

    def _edge_fragment_id(self, source: str, target: str, relation: str) -> str:
        import hashlib as _hashlib
        digest = _hashlib.sha256(
            self._edge_identity_payload(source, target, relation)
        ).hexdigest()[: self.GRAPH_EDGE_ID_HASH_LEN]
        return f"{self.GRAPH_EDGE_ID_PREFIX}{digest}"

    def write_graph_edge(
        self,
        source: str,
        target: str,
        relation: str,
        *,
        confidence: str = "EXTRACTED",
        props: Optional[dict[str, Any]] = None,
        owner_user: str = "founder",
        scope: "Scope" = Scope.PROJECT,
        contributing_agent: str = "memory_graph",
    ) -> bool:
        """Persist a graph edge as a dedicated Fragment (kind=TRACE,
        predicate='graph_edge'). The (source,target,relation) triple is the
        natural key; its fragment id is the SHA-256 of the length-prefixed
        triple (``_edge_fragment_id``), so re-writing the SAME triple upserts
        (matches MemoryGraph.add_edge semantics) while DISTINCT triples can
        never collide — even when a node id contains the old '||' separator.
        The triple itself is stored verbatim in ``extra`` (the id is opaque and
        is never parsed back), and ENFORCED below to be losslessly recoverable.
        Endpoint existence is the caller's responsibility (the adapter enforces
        it, exactly like MemoryGraph.add_edge)."""
        props = dict(props or {})
        try:
            props_blob = json.dumps(props, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            props_blob = "{}"
        extra = {
            "graph_edge": True,
            "source": source,
            "target": target,
            "relation": relation,
            "confidence": confidence,
            "props": props,
            "props_blob": props_blob,
        }
        # ENFORCED identity guard (replaces the old comment-asserted, UNENFORCED
        # "node ids never contain '|'" invariant). Because the id is now an
        # opaque hash, the triple is recovered ONLY from ``extra`` — so the real
        # invariant that must hold is: the triple round-trips out of extra. Check
        # the exact keys ``_fragment_to_graph_edge`` reads, so a future change
        # that drops/mangles an extra field fails LOUD at write time, not
        # silently at read. (Cheap: inspects the dict we just built — no
        # throwaway Fragment constructed per write.)
        if (
            extra.get("source"), extra.get("target"), extra.get("relation")
        ) != (source, target, relation):  # pragma: no cover - defensive
            raise ValueError(
                "edge identity not recoverable from extra — refusing to write a "
                f"graph edge whose triple would be lost "
                f"(({source!r},{target!r},{relation!r}))"
            )
        frag = Fragment(
            id=self._edge_fragment_id(source, target, relation),
            kind=FragmentKind.TRACE,
            text=f"{source} -{relation}-> {target}",
            subject=source,
            predicate="graph_edge",
            object=target,
            scope=scope,
            visibility=Visibility.PRIVATE,
            owner_user=owner_user,
            confidence=Confidence.EXTRACTED,
            provenance=Provenance(
                contributing_agent=contributing_agent,
                contributing_user=owner_user,
                created_at=datetime.now(timezone.utc),
            ),
            extra=extra,
        )
        return self.write_fragment(frag)

    def all_graph_edges(
        self, relation: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Every graph edge as a plain dict
        ``{source, target, relation, confidence, props}``."""
        like = f"{self.GRAPH_EDGE_ID_PREFIX}%".replace("_", r"\_")
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fragments WHERE id LIKE ? ESCAPE '\\'",
                (like,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            frag = _row_to_fragment(r)
            ed = self._fragment_to_graph_edge(frag)
            if relation is not None and ed["relation"] != relation:
                continue
            out.append(ed)
        return out

    def graph_edges_incident(
        self, node_id: str, *, direction: str = "out",
        relation: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Edges incident to ``node_id`` — mirrors MemoryGraph.neighbors.
        direction in {'out','in','both'}; relation filters all three."""
        if direction not in ("out", "in", "both"):
            raise ValueError(
                f"graph_edges_incident: direction must be 'out'|'in'|'both', "
                f"got {direction!r}"
            )
        out: list[dict[str, Any]] = []
        for ed in self.all_graph_edges(relation=relation):
            if direction == "out" and ed["source"] == node_id:
                out.append(ed)
            elif direction == "in" and ed["target"] == node_id:
                out.append(ed)
            elif direction == "both" and (
                ed["source"] == node_id or ed["target"] == node_id
            ):
                out.append(ed)
        return out

    def count_graph_edges(self, relation: Optional[str] = None) -> int:
        if relation is None:
            like = f"{self.GRAPH_EDGE_ID_PREFIX}%".replace("_", r"\_")
            with self._lock:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM fragments "
                    "WHERE id LIKE ? ESCAPE '\\'",
                    (like,),
                ).fetchone()
            return int(row["n"]) if row else 0
        return len(self.all_graph_edges(relation=relation))

    def remove_graph_edge(self, source: str, target: str, relation: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM fragments WHERE id = ?",
                (self._edge_fragment_id(source, target, relation),),
            )
            return cur.rowcount > 0

    def _incident_edge_dicts(self, node_id: str) -> list[dict[str, Any]]:
        """The incident edges of ``node_id`` as the legacy sidecar shape
        (sorted for determinism). Used to keep extra['graph_edges'] populated
        on node fragments so brain_unify-era readers keep working."""
        incident = self.graph_edges_incident(node_id, direction="both")
        sidecar = [
            {
                "source": e["source"],
                "target": e["target"],
                "relation": e["relation"],
                "confidence": e["confidence"],
                "props": e["props"],
            }
            for e in incident
        ]
        return sorted(
            sidecar,
            key=lambda e: (e["source"], e["target"], e["relation"]),
        )

    @staticmethod
    def _fragment_to_graph_node(frag: "Fragment") -> dict[str, Any]:
        extra = frag.extra or {}
        node_id = extra.get("graph_node_id")
        if not node_id and frag.id.startswith(BrainStore.GRAPH_NODE_ID_PREFIX):
            node_id = frag.id[len(BrainStore.GRAPH_NODE_ID_PREFIX):]
        # Original graph kind is authoritative in extra; fall back to the
        # predicate (which brain_unify set to the graph kind), then "".
        kind = extra.get("graph_kind") or frag.predicate or ""
        props = extra.get("graph_props")
        if not isinstance(props, dict):
            props = {}
        return {
            "id": node_id,
            "kind": kind,
            "label": frag.subject or node_id or "",
            "props": dict(props),
        }

    @staticmethod
    def _fragment_to_graph_edge(frag: "Fragment") -> dict[str, Any]:
        extra = frag.extra or {}
        props = extra.get("props")
        if not isinstance(props, dict):
            props = {}
        return {
            "source": extra.get("source") or frag.subject or "",
            "target": extra.get("target") or frag.object or "",
            "relation": extra.get("relation") or "",
            "confidence": extra.get("confidence") or "EXTRACTED",
            "props": dict(props),
        }


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
        # Brain #31 multimodal columns (optional · None for older rows
        # before the schema migration ran).
        perceptual_hash=_safe_row_get(row, "perceptual_hash"),
        blob_path=_safe_row_get(row, "blob_path"),
        blob_mime=_safe_row_get(row, "blob_mime"),
        blob_bytes=_safe_row_get(row, "blob_bytes", default=0) or 0,
        embedding=_unpack_embedding(_safe_row_get(row, "embedding_blob")),
        # AgDR-0054 per-trace fields (legacy-tolerant — pre-migration rows /
        # column-less SELECTs fall back to the same defaults the model + SQL use).
        origin_kind=_safe_row_get(row, "origin_kind", default="human_verified")
        or "human_verified",
        generating_model_id=_safe_row_get(row, "generating_model_id"),
        training_rights_tier=_safe_row_get(
            row, "training_rights_tier", default="firm_private_only"
        )
        or "firm_private_only",
        format_shape_descriptor=_safe_row_get(row, "format_shape_descriptor"),
        content_hash_pre=_safe_row_get(row, "content_hash_pre"),
        content_hash_post=_safe_row_get(row, "content_hash_post"),
        action_payload=_safe_row_get(row, "action_payload"),
        language_payload=_safe_row_get(row, "language_payload"),
        quarantine_flag=bool(_safe_row_get(row, "quarantine_flag", default=0)),
    )


def _unpack_embedding(blob) -> Optional[list[float]]:
    """Reverse of the struct.pack in write_fragment.

    `blob` is either None / b'' / a packed sequence of doubles. The
    length tells us the dimensionality (bytes / 8). Returns None
    when the blob is empty or unparseable."""
    if not blob:
        return None
    try:
        import struct as _struct
        n = len(blob) // 8
        if n == 0:
            return None
        return list(_struct.unpack(f"<{n}d", blob))
    except Exception:
        return None


def _safe_row_get(row: sqlite3.Row, key: str, *, default=None):
    """Tolerant column getter — returns `default` when the column
    isn't present on the row (e.g. pre-migration DB queried before
    ALTER TABLE ran or against a fts/select that didn't include it)."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


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


def _max_dt(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    """Later of two optional datetimes (naive coerced to UTC). Used by the
    sync apply paths to merge last_used_at so a remote row never rewinds
    local reinforcement evidence."""
    if a is None:
        return b
    if b is None:
        return a
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a if a >= b else b
