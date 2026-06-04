"""brain_unify — one-way importer that unifies ArchHub's two brain stores.

    ┌─────────────────────────────────────────────────────────────────┐
    │ RETIRED AS THE ONGOING BAND-AID (2026-05-28, ONE-SYSTEM mandate). │
    │ Use `python tools/brain_migrate.py` — the ONE-TIME migration that │
    │ folds graph.sqlite into the CANONICAL brain.db and writes a marker│
    │ so a fresh run is a no-op. The in-app brain view now reads the     │
    │ canonical store's counts via the daemon (bridge.memory_stats →    │
    │ brain.health), so nothing needs periodic graph→brain re-syncing.  │
    │ This module's `unify()` mapping is KEPT — brain_migrate imports it.│
    │ Design: docs/audits/brain-unify-design-2026-05-28.md              │
    └─────────────────────────────────────────────────────────────────┘

ArchHub grew TWO disjoint brains that never sync:

  (a) personal_brain `brain.db` — the MCP / enforcement spine the
      daemon serves on http://127.0.0.1:8473/mcp. Holds the fragments
      `brain.context` injects + `brain.health` counts. Small (a handful
      of bootstrap fragments).
  (b) the memory `graph.sqlite` — the populated knowledge graph the
      extractors (AgDR-0042) write to: 204 nodes today
      (153 capability · 48 decision · 3 skill) + typed edges. Rich, but
      INVISIBLE to the MCP brain because nothing copies it across.

This module reads the graph nodes and writes them into brain.db as
Fragments, so the MCP brain finally SEES the graph. It is **additive +
idempotent**: every node maps to a Fragment with a stable id
`graph:<node.id>`, `write_fragment` upserts by id, and a content
pre-check skips re-writing unchanged fragments. Re-running never
duplicates and never deletes anything already in brain.db.

Node-kind → FragmentKind mapping (FragmentKind has no CAPABILITY /
DECISION member, so we fold onto the existing kinds + keep the original
graph kind in `predicate`):

    capability  → FragmentKind.FACT      predicate="capability"
    decision    → FragmentKind.DOCUMENT  predicate="decision"
    skill       → FragmentKind.FACT      predicate="skill"
    <other>     → FragmentKind.FACT      predicate=<node.kind>

Edges are preserved minimally as a JSON sidecar on each fragment's
`extra["graph_edges"]` (the incident edges for that node) — the nodes
are the priority; the sidecar keeps the topology recoverable.

Run:  python tools/brain_unify.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── import paths ─────────────────────────────────────────────────────
# personal_brain lives under personal-brain-mcp/src; memory lives under
# app/. Neither is guaranteed on sys.path when this script runs from the
# repo root, so wire both explicitly (idempotent — skip if present).
_REPO = Path(__file__).resolve().parent.parent
_APP = _REPO / "app"
_PB_SRC = _REPO / "personal-brain-mcp" / "src"
for _p in (_APP, _PB_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from memory.graph import MemoryGraph, MemoryNode, default_graph_path  # noqa: E402
from personal_brain.models import (  # noqa: E402
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore, default_brain_path  # noqa: E402


# ── kind mapping ─────────────────────────────────────────────────────

# graph node.kind → (FragmentKind, predicate). Unmapped kinds fall back
# to FACT with the raw kind as predicate so nothing is ever dropped.
_KIND_MAP: dict[str, tuple[FragmentKind, str]] = {
    "capability": (FragmentKind.FACT, "capability"),
    "decision": (FragmentKind.DOCUMENT, "decision"),
    "skill": (FragmentKind.FACT, "skill"),
}

_FRAGMENT_ID_PREFIX = "graph:"
_CONTRIBUTING_AGENT = "brain_unify"

# Scope name → enum. The CLI / callers pass a lowercase scope string.
_SCOPE_BY_NAME = {s.value: s for s in Scope}


def _scope_from(scope: str | Scope) -> Scope:
    """Coerce a scope string ('project') or Scope enum to a Scope."""
    if isinstance(scope, Scope):
        return scope
    key = str(scope).strip().lower()
    if key not in _SCOPE_BY_NAME:
        raise ValueError(
            f"unknown scope {scope!r}; expected one of "
            f"{sorted(_SCOPE_BY_NAME)}"
        )
    return _SCOPE_BY_NAME[key]


def _serialize_props(props: dict[str, Any]) -> str:
    """Deterministic compact rendering of a node's props for the
    fragment `text`. sort_keys so re-runs produce byte-identical text
    (idempotency depends on this). Empty props → empty string."""
    if not props:
        return ""
    try:
        return json.dumps(props, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        # Non-JSON-serialisable prop value — fall back to repr so we
        # still capture something stable rather than crashing the import.
        return repr(sorted(props.items()))


def _fragment_text(node: MemoryNode) -> str:
    """`text` = node label + serialized key props (FTS-searchable)."""
    label = node.label or node.id
    props_blob = _serialize_props(node.props)
    return f"{label} {props_blob}".rstrip() if props_blob else label


def _edges_sidecar(node_id: str,
                    edges_by_node: dict[str, list[dict[str, Any]]]
                    ) -> list[dict[str, Any]]:
    """The incident edges for `node_id`, as plain dicts, sorted for
    determinism (idempotency)."""
    incident = edges_by_node.get(node_id, [])
    return sorted(
        incident,
        key=lambda e: (e.get("source", ""), e.get("target", ""),
                       e.get("relation", "")),
    )


def _build_fragment(node: MemoryNode, *, owner_user: str, scope: Scope,
                    edges_by_node: dict[str, list[dict[str, Any]]],
                    created_at: datetime) -> Fragment:
    """Map one MemoryNode → a Fragment with a stable id + edge sidecar."""
    kind, predicate = _KIND_MAP.get(node.kind, (FragmentKind.FACT, node.kind))
    extra = {
        "graph_node_id": node.id,
        "graph_kind": node.kind,
        "graph_edges": _edges_sidecar(node.id, edges_by_node),
    }
    if node.props:
        extra["graph_props"] = node.props
    return Fragment(
        id=f"{_FRAGMENT_ID_PREFIX}{node.id}",
        kind=kind,
        text=_fragment_text(node),
        subject=node.label or node.id,
        predicate=predicate,
        object=None,
        scope=scope,
        visibility=Visibility.PRIVATE,
        owner_user=owner_user,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent=_CONTRIBUTING_AGENT,
            contributing_user=owner_user,
            created_at=created_at,
        ),
        extra=extra,
    )


def _fragment_changed(existing: Fragment, candidate: Fragment) -> bool:
    """True if the candidate differs from the stored fragment in any
    field this importer owns. Provenance.created_at / timestamps are
    deliberately NOT compared so re-runs are idempotent even though a
    fresh `created_at` is generated each call."""
    return (
        existing.kind != candidate.kind
        or (existing.text or "") != (candidate.text or "")
        or (existing.subject or "") != (candidate.subject or "")
        or (existing.predicate or "") != (candidate.predicate or "")
        or (existing.object or "") != (candidate.object or "")
        or existing.scope != candidate.scope
        or existing.visibility != candidate.visibility
        or (existing.extra or {}) != (candidate.extra or {})
    )


def _write_with_retry(store: BrainStore, fragment: Fragment, *,
                      retries: int = 5, backoff: float = 0.5) -> int:
    """write_fragment with WAL lock-retry. The daemon holds brain.db
    open; WAL permits a concurrent writer, but a transient
    'database is locked' can still surface under contention. Retry up
    to `retries` times with linear `backoff`.

    Returns the number of lock-retry hits incurred (0 = clean write).
    Re-raises any non-lock error, and the lock error if it never clears.
    """
    import sqlite3

    hits = 0
    for attempt in range(retries + 1):
        try:
            store.write_fragment(fragment)
            return hits
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower() or attempt == retries:
                raise
            hits += 1
            time.sleep(backoff)
    return hits  # unreachable, but keeps type-checkers happy


def unify(graph: MemoryGraph, store: BrainStore, *,
          owner_user: str = "founder", scope: str | Scope = "project"
          ) -> dict[str, Any]:
    """Import every MemoryGraph node into the BrainStore as a Fragment.

    One-way, additive, idempotent. Each node becomes a Fragment with a
    stable id `graph:<node.id>`; unchanged fragments are skipped (no
    write). Graph edges incident to each node ride along in
    `extra["graph_edges"]`.

    Args:
        graph: the populated MemoryGraph (graph.sqlite).
        store: the destination BrainStore (brain.db).
        owner_user: owner stamped on every imported fragment +
            provenance.contributing_user.
        scope: target scope name ('project') or Scope enum.

    Returns:
        {"imported": n, "skipped": s, "by_kind": {...},
         "fragments_before": x, "fragments_after": y,
         "lock_retry_hits": k, "edges_total": e}
        where by_kind maps each graph node.kind to its
        {"imported": .., "skipped": ..} split.
    """
    scope_enum = _scope_from(scope)
    fragments_before = store.count_fragments()

    # Pre-index edges by the nodes they touch — one pass, so each node's
    # sidecar is O(degree) not O(E).
    edges_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    edges = graph.all_edges()
    for e in edges:
        d = e.to_dict()
        edges_by_node[e.source].append(d)
        if e.target != e.source:
            edges_by_node[e.target].append(d)

    now = datetime.now(timezone.utc)
    imported = 0
    skipped = 0
    lock_retry_hits = 0
    by_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"imported": 0, "skipped": 0}
    )

    for node in graph.all_nodes():
        candidate = _build_fragment(
            node, owner_user=owner_user, scope=scope_enum,
            edges_by_node=edges_by_node, created_at=now,
        )
        existing = store.get_fragment(candidate.id)
        if existing is not None and not _fragment_changed(existing, candidate):
            skipped += 1
            by_kind[node.kind]["skipped"] += 1
            continue
        lock_retry_hits += _write_with_retry(store, candidate)
        imported += 1
        by_kind[node.kind]["imported"] += 1

    fragments_after = store.count_fragments()
    return {
        "imported": imported,
        "skipped": skipped,
        "by_kind": {k: dict(v) for k, v in by_kind.items()},
        "fragments_before": fragments_before,
        "fragments_after": fragments_after,
        "lock_retry_hits": lock_retry_hits,
        "edges_total": len(edges),
    }


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: open the REAL graph.sqlite + REAL brain.db, run unify, print
    before/after fragment counts. Additive + idempotent — safe to re-run."""
    graph_path = default_graph_path()
    brain_path = default_brain_path()

    print("brain_unify -- graph.sqlite -> brain.db (one-way, idempotent)")
    print(f"  graph: {graph_path}  (exists={graph_path.exists()})")
    print(f"  brain: {brain_path}  (exists={brain_path.exists()})")

    if not graph_path.exists():
        print("ERROR: graph.sqlite not found — nothing to import.")
        return 1

    graph = MemoryGraph.open(graph_path)
    store = BrainStore.open(brain_path)
    try:
        result = unify(graph, store)
    finally:
        graph.close()
        store.close()

    nodes_seen = sum(
        v["imported"] + v["skipped"] for v in result["by_kind"].values()
    )
    kind_breakdown = ", ".join(
        f"{k}={v['imported'] + v['skipped']}"
        for k, v in sorted(result["by_kind"].items())
    )
    print(f"  graph nodes seen: {nodes_seen} ({kind_breakdown})")
    print(f"  fragments_before: {result['fragments_before']}")
    print(f"  imported: {result['imported']}   skipped: {result['skipped']}")
    print(f"  by_kind: {json.dumps(result['by_kind'], sort_keys=True)}")
    print(f"  edges preserved (sidecar): {result['edges_total']}")
    print(f"  lock_retry_hits: {result['lock_retry_hits']}")
    print(f"  fragments_after: {result['fragments_after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
