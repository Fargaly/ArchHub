"""Optional DBSTAT physical-byte reader (temporary APSW dependency only).

Primary references: https://www.sqlite.org/dbstat.html and
https://rogerbinns.github.io/apsw/connection.html . Production has no APSW dependency.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def measure_allocations(path: Path, apsw_path: Path) -> dict:
    sys.path.insert(0, str(apsw_path.resolve()))
    import apsw
    started = time.perf_counter()
    db = apsw.Connection(path.resolve().as_uri() + "?mode=ro", flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA cache_size=-8192")
    db.execute("BEGIN")
    try:
        if not db.readonly("main"):
            raise RuntimeError("physical allocation reader must be read-only")
        metadata = {row[0]: (row[1], row[2]) for row in db.execute("SELECT name,type,tbl_name FROM sqlite_master WHERE type IN ('table','index')")}
        allocations = {}
        # Aggregate mode emits one row per B-tree and avoids a sorter over
        # millions of page rows. Payload/unused include overflow pages.
        for name, pages, cells, payload, unused, allocated in db.execute("SELECT name,pageno,ncell,payload,unused,pgsize FROM dbstat WHERE aggregate=TRUE"):
            kind, owner = metadata.get(name, ("table", name))
            allocations[name] = {"kind": kind, "table": owner, "pages": pages, "btree_cells": cells,
                                 "payload_bytes": payload, "unused_bytes": unused, "allocated_bytes": allocated}
            print("allocated " + name + ": " + str(allocated) + " bytes", flush=True)
        page_size = next(db.execute("PRAGMA page_size"))[0]
        page_count = next(db.execute("PRAGMA page_count"))[0]
        free = next(db.execute("PRAGMA freelist_count"))[0] * page_size
        total = sum(item["allocated_bytes"] for item in allocations.values())
        return {"measurement": "APSW READONLY|URI; mode=ro; query_only=ON; dbstat aggregate=TRUE; independent pinned allocation snapshot",
                "sqlite_version": apsw.sqlitelibversion(), "page_size": page_size, "page_count": page_count,
                "snapshot_allocated_file_bytes": page_size * page_count, "file_bytes_at_observation": path.stat().st_size,
                "revision": next(db.execute("SELECT max(revision) FROM revisions"))[0] if "revisions" in metadata else None,
                "freelist_bytes": free, "btree_allocated_bytes": total,
                "non_btree_non_free_bytes": page_size * page_count - total - free,
                "table_allocated_bytes": sum(item["allocated_bytes"] for item in allocations.values() if item["kind"] == "table"),
                "index_allocated_bytes": sum(item["allocated_bytes"] for item in allocations.values() if item["kind"] == "index"),
                "allocations": allocations, "elapsed_seconds": round(time.perf_counter() - started, 6)}
    finally:
        db.execute("ROLLBACK")
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", nargs="+", type=Path)
    parser.add_argument("--apsw-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.measure_store import validate_output
    validate_output(args.stores, args.output)
    result = {"stores": {path.name: measure_allocations(path, args.apsw_path) for path in args.stores}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
