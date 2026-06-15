"""MemoryGraph — core data model + SQLite-backed store.

AgDR-0042 slice 1/6 (D1·C, founder picked 2026-05-25).

The substrate the four extractors (slices 2 + 4) write to and the
`memory.query()` BFS (slice 3) reads from. Graphify-inspired shape:
nodes carry a `kind` (capability / skill / design / turn / decision /
…) and edges carry a `relation` + `confidence` (EXTRACTED for hard
facts, INFERRED for similarity-based links).

Storage choices:
- SQLite for ACID + fast indexed lookups by kind / relation. JSON props
  are stored as TEXT (json.dumps) so the schema doesn't need to grow
  per-kind.
- Two tables: `nodes(id, kind, label, props_json)` + `edges(source,
  target, relation, confidence, props_json, PRIMARY KEY)`.
- WAL journaling — concurrent reads while extractors write.

Performance budget (per AgDR-0042 §Consequences):
- ~12 MB per 10k nodes (measured on the graphify-on-ArchHub baseline).
- All inserts batched via `commit()`; per-call writes would crater
  extractor throughput.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional


# ── confidence levels ────────────────────────────────────────────────


class Confidence(str, Enum):
    """Edge provenance — drives ranking + opt-in LLM merge.

    EXTRACTED — derived from a deterministic source (registry walk,
                AST parse, frontmatter read). Trustworthy.
    INFERRED  — derived from similarity heuristics (port-shape match,
                token overlap, embedding cosine). Lower trust; the
                query layer filters these by a confidence threshold.
    """

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class MemoryNode:
    """One node in the shared-memory graph.

    `id`    — globally unique key. Convention: `<scope>:<kind>:<slug>`
              e.g. `lib:cap:revit.read_walls`, `turn:2026-05-25:14:22`.
              Stable across sessions so re-extraction is idempotent.
    `kind`  — type tag for queries. Stable enum-like string; not
              constrained at this layer (slice 2 extractors set
              capability / skill / design / turn / decision).
    `label` — human-readable display string. Optional; defaults to id.
    `props` — arbitrary JSON-serialisable dict for kind-specific
              metadata (cost, ts, file_path, etc.).
    """

    id: str
    kind: str
    label: str = ""
    props: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind,
                "label": self.label or self.id,
                "props": dict(self.props)}

    @staticmethod
    def from_dict(d: dict) -> "MemoryNode":
        return MemoryNode(
            id=d["id"], kind=d.get("kind", ""),
            label=d.get("label", "") or "",
            props=dict(d.get("props") or {}),
        )


@dataclass(frozen=True)
class MemoryEdge:
    """One typed edge in the shared-memory graph.

    `(source, target, relation)` is the natural key — duplicate inserts
    of the same triple no-op (props of the latest write win).
    `confidence` drives query-time filtering (EXTRACTED-only is the
    default; INFERRED is opt-in per query).
    """

    source: str
    target: str
    relation: str
    confidence: Confidence = Confidence.EXTRACTED
    props: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "relation": self.relation,
                "confidence": self.confidence.value,
                "props": dict(self.props)}

    @staticmethod
    def from_dict(d: dict) -> "MemoryEdge":
        conf_raw = d.get("confidence", "EXTRACTED")
        try:
            conf = Confidence(conf_raw)
        except ValueError:
            conf = Confidence.EXTRACTED
        return MemoryEdge(
            source=d["source"], target=d["target"],
            relation=d["relation"], confidence=conf,
            props=dict(d.get("props") or {}),
        )


# ── default disk path ────────────────────────────────────────────────


_APP_DIR = "ArchHub"
_MEMORY_SUBDIR = "memory"
_DB_FILENAME = "graph.sqlite"


def default_graph_path() -> Path:
    """Default on-disk location for the MemoryGraph SQLite store.

    Windows:  %LOCALAPPDATA%/ArchHub/memory/graph.sqlite
    POSIX:    $XDG_DATA_HOME/ArchHub/memory/graph.sqlite
              fallback ~/.local/share/ArchHub/memory/graph.sqlite

    Mirrors the layout used by library_persistence so the two stores
    sit side-by-side under one app dir.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / _APP_DIR / _MEMORY_SUBDIR / _DB_FILENAME
        return (
            Path.home() / "AppData" / "Local"
            / _APP_DIR / _MEMORY_SUBDIR / _DB_FILENAME
        )
    xdg = os.environ.get("XDG_DATA_HOME")
    base_path = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_path / _APP_DIR / _MEMORY_SUBDIR / _DB_FILENAME


# ── schema ───────────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    props_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    relation    TEXT NOT NULL,
    confidence  TEXT NOT NULL DEFAULT 'EXTRACTED',
    props_json  TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, target, relation)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SCHEMA_VERSION = "1"


# ── MemoryGraph ──────────────────────────────────────────────────────


class MemoryGraph:
    """SQLite-backed in-process knowledge graph.

    Open with `MemoryGraph.open()` for the default disk path or
    `MemoryGraph.open(path)` for a custom location. `:memory:` works
    too — used by every test for hermetic isolation.

    Writes are auto-committed by default. For batch extractor runs,
    use `with g.transaction(): …` to commit once at exit.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        # WAL = concurrent reads while extractors write. Skipped for
        # in-memory dbs (WAL not applicable).
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (_SCHEMA_VERSION,),
        )
        self._conn.commit()
        # Transaction depth — auto-commit when ==0, defer when >0.
        # Lets `with g.transaction():` group many writes into one commit
        # AND survive nested transaction() calls without confusion.
        self._tx_depth = 0

    def _autocommit(self) -> None:
        """Commit only when not inside a deferred transaction context."""
        if self._tx_depth == 0:
            self._conn.commit()

    # ── factory helpers ──

    @classmethod
    def open(
        cls,
        path: Optional[Path | str] = None,
        *,
        brain_store: Any = None,
    ) -> "MemoryGraph":
        """Open (creating if missing) the graph at `path`. None →
        default_graph_path(). Pass ':memory:' for an in-RAM graph.

        ONE-SYSTEM unify (ONE-SYSTEM-PLAN-BEFORE-BUILD mandate, 2026-05-28):
        pass ``brain_store=<BrainStore>`` to back this graph with the personal
        brain's ``brain.db`` instead of a separate ``graph.sqlite``. The app's
        knowledge graph and the daemon's brain then read/write ONE store — a
        node added here is the same Fragment row the brain serves, so the
        manual ``tools/brain_unify.py`` graph→brain copy is no longer needed.
        The returned object presents the full ``MemoryGraph`` API
        (``MemoryGraphStore`` from ``personal_brain.graph_adapter``), so every
        caller (extractors / query / sync / bridge) is unchanged.

        Without ``brain_store`` the standalone ``graph.sqlite`` behaviour is
        preserved exactly (back-compat for any path that hasn't been pointed at
        the unified store yet)."""
        if brain_store is not None:
            return cls._open_unified(brain_store)  # type: ignore[return-value]
        if path is None:
            path = default_graph_path()
        if str(path) != ":memory:":
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(p))
        else:
            conn = sqlite3.connect(":memory:")
        return cls(conn)

    @staticmethod
    def _open_unified(brain_store: Any) -> Any:
        """Return a MemoryGraphStore (MemoryGraph-compatible) backed by the
        given BrainStore. Imported lazily so app/memory keeps working even when
        personal-brain-mcp isn't on the path — but if a brain_store was passed,
        the adapter MUST be importable (the caller asked for unify)."""
        from personal_brain.graph_adapter import MemoryGraphStore
        return MemoryGraphStore(brain_store)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── write API ──

    def add_node(self, node: MemoryNode) -> None:
        """Upsert a node by id. Re-writing the same id replaces kind +
        label + props (extractors are idempotent on re-run)."""
        self._conn.execute(
            "INSERT INTO nodes(id, kind, label, props_json) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind, label=excluded.label, props_json=excluded.props_json",
            (node.id, node.kind, node.label or "",
             json.dumps(node.props, ensure_ascii=False)),
        )
        self._autocommit()

    def add_edge(self, edge: MemoryEdge) -> None:
        """Upsert an edge by (source, target, relation). Re-writing the
        same triple replaces confidence + props."""
        # Both endpoints must exist — keeps the graph consistent so a
        # BFS from any seed terminates cleanly. The extractor layer is
        # responsible for ordering adds; raising here surfaces the bug.
        if not self._node_exists(edge.source):
            raise ValueError(
                f"add_edge: source node {edge.source!r} not in graph")
        if not self._node_exists(edge.target):
            raise ValueError(
                f"add_edge: target node {edge.target!r} not in graph")
        self._conn.execute(
            "INSERT INTO edges(source, target, relation, confidence, props_json) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(source, target, relation) DO UPDATE SET "
            "confidence=excluded.confidence, props_json=excluded.props_json",
            (edge.source, edge.target, edge.relation, edge.confidence.value,
             json.dumps(edge.props, ensure_ascii=False)),
        )
        self._autocommit()

    def add_nodes(self, nodes: Iterable[MemoryNode]) -> int:
        """Batch upsert nodes. Single transaction — far cheaper than
        per-call add_node for extractor runs."""
        n = 0
        with self.transaction():
            for node in nodes:
                self._conn.execute(
                    "INSERT INTO nodes(id, kind, label, props_json) "
                    "VALUES (?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "kind=excluded.kind, label=excluded.label, "
                    "props_json=excluded.props_json",
                    (node.id, node.kind, node.label or "",
                     json.dumps(node.props, ensure_ascii=False)),
                )
                n += 1
        return n

    def add_edges(self, edges: Iterable[MemoryEdge]) -> int:
        """Batch upsert edges. Endpoints must already exist; missing
        endpoints raise ValueError mid-loop (transaction rolls back)."""
        n = 0
        with self.transaction():
            for edge in edges:
                if not self._node_exists(edge.source):
                    raise ValueError(
                        f"add_edges: source {edge.source!r} missing "
                        f"(processed {n} edges)")
                if not self._node_exists(edge.target):
                    raise ValueError(
                        f"add_edges: target {edge.target!r} missing "
                        f"(processed {n} edges)")
                self._conn.execute(
                    "INSERT INTO edges(source, target, relation, confidence, "
                    "props_json) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(source, target, relation) DO UPDATE SET "
                    "confidence=excluded.confidence, props_json=excluded.props_json",
                    (edge.source, edge.target, edge.relation,
                     edge.confidence.value,
                     json.dumps(edge.props, ensure_ascii=False)),
                )
                n += 1
        return n

    def remove_node(self, node_id: str) -> bool:
        """Delete a node + all incident edges. Returns False if no
        such node existed."""
        cur = self._conn.execute(
            "DELETE FROM edges WHERE source=? OR target=?",
            (node_id, node_id))
        cur = self._conn.execute(
            "DELETE FROM nodes WHERE id=?", (node_id,))
        self._autocommit()
        return cur.rowcount > 0

    def remove_edge(self, source: str, target: str, relation: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM edges WHERE source=? AND target=? AND relation=?",
            (source, target, relation))
        self._autocommit()
        return cur.rowcount > 0

    # ── read API ──

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        row = self._conn.execute(
            "SELECT id, kind, label, props_json FROM nodes WHERE id=?",
            (node_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def all_nodes(self, kind: Optional[str] = None) -> list[MemoryNode]:
        if kind is None:
            cur = self._conn.execute(
                "SELECT id, kind, label, props_json FROM nodes")
        else:
            cur = self._conn.execute(
                "SELECT id, kind, label, props_json FROM nodes WHERE kind=?",
                (kind,))
        return [self._row_to_node(r) for r in cur]

    def all_edges(self, relation: Optional[str] = None) -> list[MemoryEdge]:
        if relation is None:
            cur = self._conn.execute(
                "SELECT source, target, relation, confidence, props_json FROM edges")
        else:
            cur = self._conn.execute(
                "SELECT source, target, relation, confidence, props_json "
                "FROM edges WHERE relation=?", (relation,))
        return [self._row_to_edge(r) for r in cur]

    def neighbors(self, node_id: str, *,
                   direction: str = "out",
                   relation: Optional[str] = None) -> list[MemoryEdge]:
        """Edges incident to `node_id`.

        direction='out' → edges where source == node_id (downstream)
        direction='in'  → edges where target == node_id (upstream)
        direction='both' → union of the two
        relation filter applies to all three."""
        if direction == "out":
            sql = ("SELECT source, target, relation, confidence, props_json "
                   "FROM edges WHERE source=?")
            args: tuple = (node_id,)
        elif direction == "in":
            sql = ("SELECT source, target, relation, confidence, props_json "
                   "FROM edges WHERE target=?")
            args = (node_id,)
        elif direction == "both":
            sql = ("SELECT source, target, relation, confidence, props_json "
                   "FROM edges WHERE source=? OR target=?")
            args = (node_id, node_id)
        else:
            raise ValueError(
                f"neighbors: direction must be 'out'|'in'|'both', got {direction!r}")
        if relation is not None:
            sql += " AND relation=?"
            args = args + (relation,)
        return [self._row_to_edge(r) for r in self._conn.execute(sql, args)]

    def count_nodes(self, kind: Optional[str] = None) -> int:
        if kind is None:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM nodes").fetchone()[0])
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind=?", (kind,)).fetchone()[0])

    def count_edges(self, relation: Optional[str] = None) -> int:
        if relation is None:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM edges").fetchone()[0])
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE relation=?",
            (relation,)).fetchone()[0])

    # ── batch transactions ──

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes into one commit. Exceptions roll back the whole
        batch — partial writes do NOT persist.

        Nested transaction() calls are supported via a depth counter:
        only the outermost __exit__ commits / rolls back, so a batch
        extractor that internally calls add_nodes (which itself opens
        a transaction) still rolls back cleanly on error.
        """
        self._tx_depth += 1
        try:
            yield
        except Exception:
            self._tx_depth = 0
            self._conn.rollback()
            raise
        else:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._conn.commit()

    # ── serialisation ──

    def to_dict(self) -> dict:
        """Whole-graph snapshot — graphify-compatible shape. Useful
        for export / debug / round-trip tests."""
        return {
            "nodes": [n.to_dict() for n in self.all_nodes()],
            "edges": [e.to_dict() for e in self.all_edges()],
        }

    @classmethod
    def from_dict(cls, data: dict,
                   path: Optional[Path | str] = None) -> "MemoryGraph":
        """Build a fresh MemoryGraph from a snapshot dict. Default path
        is :memory: so this never clobbers an on-disk store by accident."""
        g = cls.open(path if path is not None else ":memory:")
        with g.transaction():
            for n in data.get("nodes") or []:
                g.add_node(MemoryNode.from_dict(n))
            for e in data.get("edges") or []:
                g.add_edge(MemoryEdge.from_dict(e))
        return g

    # ── meta ──

    def schema_version(self) -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return row[0] if row else _SCHEMA_VERSION

    # ── internal ──

    def _node_exists(self, node_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM nodes WHERE id=? LIMIT 1", (node_id,)).fetchone()
        return row is not None

    @staticmethod
    def _row_to_node(row: Any) -> MemoryNode:
        return MemoryNode(
            id=row["id"], kind=row["kind"], label=row["label"] or "",
            props=json.loads(row["props_json"] or "{}"),
        )

    @staticmethod
    def _row_to_edge(row: Any) -> MemoryEdge:
        try:
            conf = Confidence(row["confidence"])
        except (KeyError, ValueError):
            conf = Confidence.EXTRACTED
        return MemoryEdge(
            source=row["source"], target=row["target"],
            relation=row["relation"], confidence=conf,
            props=json.loads(row["props_json"] or "{}"),
        )
