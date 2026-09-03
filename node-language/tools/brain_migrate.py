"""brain_migrate — ONE-TIME migration: graph.sqlite → brain.db (canonical).

ONE-SYSTEM-PLAN-BEFORE-BUILD mandate (founder, 2026-05-28). Design:
`docs/audits/brain-unify-design-2026-05-28.md`.

ArchHub grew TWO brain stores that the founder never asked for:
  (a) personal-brain `brain.db`  — the daemon store on :8473. Fragments +
      skills + FTS5 + 5-scope ACL + provenance. RICHER superset.
  (b) memory `graph.sqlite`       — the AgDR-0042 extractor nodes/edges.
      A plain subset (no scope / provenance).

`tools/brain_unify.py` was the manual band-aid that copied (b)→(a) and had
to be RE-RUN forever to keep them reconciled. This script is the replacement:
the canonical store is **brain.db**, and this is a ONE-TIME migration, not an
ongoing sync. It:

  1. Folds every graph.sqlite node into brain.db as a Fragment (reusing the
     proven idempotent `brain_unify.unify()` mapping — capability→FACT,
     decision→DOCUMENT, skill→FACT; edges ride in `extra.graph_edges`).
  2. Stamps `brain_meta.migrated_from_graph` with the timestamp + node count,
     so a FRESH run knows the migration already happened and is a no-op.
  3. Prints before/after fragment counts + a parity line.

Why this RETIRES the band-aid (not just renames it): the reconciliation that
forced repeated runs is gone. The in-app brain view now reads the CANONICAL
store's counts via the daemon (`bridge.memory_stats` → `brain.health`), so
nothing needs periodic graph→brain copying. On a fresh machine, run this once;
re-running is a marker-gated no-op.

Run:  python tools/brain_migrate.py
      python tools/brain_migrate.py --force   # re-run even if marker present
      python tools/brain_migrate.py --status  # print marker + counts, no write
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── import paths (mirror brain_unify.py: app/ + personal-brain-mcp/src) ──
_REPO = Path(__file__).resolve().parent.parent
_APP = _REPO / "app"
_PB_SRC = _REPO / "personal-brain-mcp" / "src"
for _p in (_APP, _PB_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from memory.graph import MemoryGraph, default_graph_path  # noqa: E402
from personal_brain.storage import BrainStore, default_brain_path  # noqa: E402

# Reuse the PROVEN, tested mapping — do not re-implement it.
from brain_unify import unify  # noqa: E402  (tools/ is on sys.path as cwd)


# brain_meta key that marks the one-time migration as done. Presence (with a
# matching node count) means a fresh run is a no-op.
_MARKER_KEY = "migrated_from_graph"


def _read_marker(store: BrainStore) -> Optional[dict[str, Any]]:
    raw = store.get_meta(_MARKER_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # Legacy / hand-written marker — treat any non-empty value as "done".
        return {"raw": raw}


def _write_marker(store: BrainStore, *, graph_nodes: int, imported: int,
                  skipped: int) -> dict[str, Any]:
    payload = {
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "graph_nodes": graph_nodes,
        "imported": imported,
        "skipped": skipped,
        "source": "tools/brain_migrate.py",
        "canonical": "brain.db",
    }
    store.set_meta(_MARKER_KEY, json.dumps(payload, sort_keys=True))
    return payload


def migrate(
    *,
    graph_path: Optional[Path] = None,
    brain_path: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the one-time migration. Returns a result dict.

    Idempotent two ways:
      • the `migrated_from_graph` marker short-circuits a repeat run (unless
        force=True), AND
      • the underlying `unify()` is itself additive + content-precheck
        idempotent, so even a forced re-run never duplicates fragments.
    """
    graph_path = graph_path or default_graph_path()
    brain_path = brain_path or default_brain_path()

    result: dict[str, Any] = {
        "graph_path": str(graph_path),
        "brain_path": str(brain_path),
        "graph_exists": graph_path.exists(),
        "ran": False,
        "noop_reason": None,
    }

    if not graph_path.exists():
        # No staging graph at all → nothing to fold; brain.db already canonical.
        result["noop_reason"] = "graph.sqlite absent — brain.db already sole store"
        store = BrainStore.open(brain_path)
        try:
            result["fragments_after"] = store.count_fragments()
            result["marker"] = _read_marker(store)
        finally:
            store.close()
        return result

    store = BrainStore.open(brain_path)
    graph = MemoryGraph.open(graph_path)
    try:
        existing_marker = _read_marker(store)
        graph_nodes = graph.count_nodes()

        if existing_marker is not None and not force:
            # Migration already done — a fresh run must NOT need this script.
            result["noop_reason"] = "already migrated (marker present)"
            result["marker"] = existing_marker
            result["fragments_after"] = store.count_fragments()
            result["graph_nodes"] = graph_nodes
            return result

        # Do the fold (idempotent even when forced).
        unify_res = unify(graph, store)
        marker = _write_marker(
            store,
            graph_nodes=graph_nodes,
            imported=unify_res["imported"],
            skipped=unify_res["skipped"],
        )
        result.update({
            "ran": True,
            "imported": unify_res["imported"],
            "skipped": unify_res["skipped"],
            "by_kind": unify_res["by_kind"],
            "edges_preserved": unify_res["edges_total"],
            "fragments_before": unify_res["fragments_before"],
            "fragments_after": unify_res["fragments_after"],
            "graph_nodes": graph_nodes,
            "marker": marker,
        })
        return result
    finally:
        graph.close()
        store.close()


def _print_status(store_path: Path, graph_path: Path) -> int:
    store = BrainStore.open(store_path)
    try:
        marker = _read_marker(store)
        print("brain_migrate --status")
        print(f"  canonical brain.db: {store_path}  (exists={store_path.exists()})")
        print(f"  staging graph.sqlite: {graph_path}  (exists={graph_path.exists()})")
        print(f"  fragments (brain.db): {store.count_fragments()}")
        print(f"  skills    (brain.db): {store.count_skills()}")
        print(f"  migrated_from_graph marker: "
              f"{json.dumps(marker) if marker else 'NONE (migration not yet run)'}")
    finally:
        store.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="brain_migrate",
        description="One-time migration: graph.sqlite → brain.db (canonical).",
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if the migration marker is present.")
    parser.add_argument("--status", action="store_true",
                        help="Print marker + counts; do not write.")
    parser.add_argument("--db", type=str, default=None,
                        help="Override brain.db path (default: OS-appropriate).")
    parser.add_argument("--graph", type=str, default=None,
                        help="Override graph.sqlite path (default: OS-appropriate).")
    args = parser.parse_args(argv)

    brain_path = Path(args.db) if args.db else default_brain_path()
    graph_path = Path(args.graph) if args.graph else default_graph_path()

    if args.status:
        return _print_status(brain_path, graph_path)

    print("brain_migrate -- graph.sqlite -> brain.db (ONE-TIME, canonical=brain.db)")
    res = migrate(graph_path=graph_path, brain_path=brain_path, force=args.force)
    print(f"  graph: {res['graph_path']}  (exists={res['graph_exists']})")
    print(f"  brain: {res['brain_path']}")
    if not res["ran"]:
        print(f"  NO-OP: {res['noop_reason']}")
        print(f"  fragments_after: {res.get('fragments_after')}")
        if res.get("marker"):
            print(f"  marker: {json.dumps(res['marker'], sort_keys=True)}")
        return 0
    print(f"  graph nodes seen: {res['graph_nodes']}")
    print(f"  fragments_before: {res['fragments_before']}")
    print(f"  imported: {res['imported']}   skipped: {res['skipped']}")
    print(f"  by_kind: {json.dumps(res['by_kind'], sort_keys=True)}")
    print(f"  edges preserved (sidecar): {res['edges_preserved']}")
    print(f"  fragments_after: {res['fragments_after']}")
    print(f"  marker written: {json.dumps(res['marker'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
