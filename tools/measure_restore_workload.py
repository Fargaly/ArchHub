"""Measure source-defined restore relation discovery against a live read-only DB.

This is a graph traversal diagnostic subset, not full boot or authority admission.
It never opens CellStore, a writable journal, signing keys, or accelerators.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang.cell_protocols import read_relation, with_restore_relation_projection_scope
from nodelang.universal_cell import InvalidCell, Snapshot, _HeadRowReader, _LazyHeadCellMap


class CountingReader(_HeadRowReader):
    MAX_CACHE_BYTES = 32 * 1024 * 1024
    MAX_CACHE_ENTRIES = 32768
    MAX_MISSING_ENTRIES = 4096
    MAX_MISSING_BYTES = 1024 * 1024

    def __init__(self, *args, **kwargs):
        self.physical_rows = 0
        super().__init__(*args, **kwargs)

    def _remember(self, key, cell):
        if key not in self._cache:
            self.physical_rows += 1
        return super()._remember(key, cell)


def measure_workload(path: Path) -> dict:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-8192")
    connection.execute("BEGIN")
    reader = CountingReader(connection)
    count = connection.execute("SELECT count(*) FROM current_cells").fetchone()[0]
    snapshot = Snapshot(reader._base_revision, _LazyHeadCellMap(reader, base_count=count))
    report = {"scope": "source-defined graph relation discovery subset; excludes signed authority verification, migrations, callbacks and Home rendering",
              "mode": "SQLite URI mode=ro; query_only=ON; pinned read transaction; verified read_relation traversal",
              "revision": snapshot.revision, "current_cells": count, "reader_cache_limit_bytes": reader.MAX_CACHE_BYTES,
              "stages": {}}
    try:
        @with_restore_relation_projection_scope
        def traverse():
            stage_roots = set()
            def stage(name, roots, budget=100_000):
                before = reader.physical_rows
                started = time.perf_counter()
                stats = {"relation_attempts": 0, "valid_relations": 0, "invalid_relations": 0,
                         "members_walked": 0, "chain_and_incidence_cells_walked": 0}
                results = []
                for root in roots:
                    stats["relation_attempts"] += 1
                    stage_roots.add(root)
                    try:
                        members = read_relation(snapshot, root, budget=budget, retain_projection=False)
                    except InvalidCell:
                        stats["invalid_relations"] += 1
                        continue
                    stats["valid_relations"] += 1
                    stats["members_walked"] += len(members)
                    stats["chain_and_incidence_cells_walked"] += 2 * len(members) if members else 1
                    if name in ("application_members", "canvas_members", "brain_members"):
                        results.extend(members)
                    if stats["relation_attempts"] % 1000 == 0:
                        print(name + ": " + str(stats["relation_attempts"]) + " roots", flush=True)
                stats["physical_rows_read_including_refetch"] = reader.physical_rows - before
                stats["elapsed_seconds"] = round(time.perf_counter() - started, 6)
                report["stages"][name] = stats
                print("completed " + name + ": " + json.dumps(stats), flush=True)
                return results

            application = stage("application_members", ("app:archhub",))
            candidate_roots = tuple(member.participant_id for member in application if member.role_id == "gm:role:member")
            # These are the exact blind candidate loops on the original
            # restore path. No migration writes or authority claims are replayed.
            stage("canvas_migration_original_candidate_probe", candidate_roots)
            stage("restore_original_session_candidate_probe", candidate_roots)
            canvas = stage("canvas_members", ("app:canvas",))
            brain = stage("brain_members", ("gm:domain:brain",))
            brain_candidates = tuple(dict.fromkeys(member.participant_id for member in (*canvas, *brain) if member.role_id == "gm:role:member"))
            stage("brain_receipt_migration_original_candidate_probe", brain_candidates)
            # Home structural need is the already-listed top-level canvas and
            # its property relations; this does not assert full render admission.
            stage("home_canvas_properties_structural_subset", (member.participant_id for member in canvas if member.role_id == "app:role:property"), budget=32)
            lazy_candidates = tuple(root for root in candidate_roots if root.startswith("app:view-session:") or root == "app:session:founder-desktop")
            stage("lazy_namespaced_view_candidate_subset", lazy_candidates)
            report["distinct_relation_roots_attempted"] = len(stage_roots)
            report["physical_rows_read_including_refetch"] = reader.physical_rows
        traverse()
        return report
    finally:
        connection.rollback()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.measure_store import validate_output
    validate_output([args.store], args.output)
    result = measure_workload(args.store)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
