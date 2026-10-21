"""Aggregate SQLite store shape without opening a writable journal or content output.

dbstat bytes are allocated B-tree bytes (including overflow); logical payload bytes
are measured separately. A live WAL store is read in one read transaction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sqlite3
import time


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def validate_output(stores: list[Path], output: Path) -> None:
    target = output.resolve()
    for store in stores:
        source = store.resolve()
        target_name, source_name = os.path.normcase(str(target)), os.path.normcase(str(source))
        if target == source or target_name.startswith(source_name + ".") or target_name in (source_name + "-wal", source_name + "-shm", source_name + "-journal"):
            raise ValueError("aggregate output cannot overwrite a source store or its sidecars")


def measure(path: Path, prior: dict | None = None, *, resume_history: bool = False) -> dict:
    started = time.perf_counter()
    database = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    database.execute("PRAGMA query_only=ON")
    database.execute("PRAGMA cache_size=-8192")
    database.execute("BEGIN")
    try:
        report = {
            "file_bytes": path.stat().st_size,
            "wal_bytes": Path(str(path) + "-wal").stat().st_size if Path(str(path) + "-wal").exists() else 0,
            "page_size": database.execute("PRAGMA page_size").fetchone()[0],
            "page_count": database.execute("PRAGMA page_count").fetchone()[0],
            "freelist_pages": database.execute("PRAGMA freelist_count").fetchone()[0],
            "tables": {},
            "indexes": {},
        }
        try:
            allocations = {row[0]: {"allocated_bytes": row[1], "payload_bytes": row[2], "unused_bytes": row[3]}
                           for row in database.execute("SELECT name,sum(pgsize),sum(payload),sum(unused) FROM dbstat GROUP BY name")}
            report["allocation_source"] = "dbstat"
        except sqlite3.OperationalError as error:
            if "no such table: dbstat" not in str(error):
                raise
            allocations = {}
            report["allocation_source"] = "dbstat unavailable in this SQLite build; exact logical column bytes reported"
        for name, kind, owner in database.execute("SELECT name,type,tbl_name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name").fetchall():
            item = dict(allocations.get(name, {}))
            if kind == "table":
                old = (prior or {}).get("tables", {}).get(name)
                if old:
                    item.update(old)
                    item["byte_snapshot"] = "previous completed read-only table-byte transaction"
                else:
                    item["rows"] = database.execute("SELECT count(*) FROM " + quote(name)).fetchone()[0]
                    columns = database.execute("PRAGMA table_info(" + quote(name) + ")").fetchall()
                    expression = "+".join("coalesce(length(CAST(" + quote(column[1]) + " AS BLOB)),0)" for column in columns)
                    item["logical_column_bytes"] = database.execute("SELECT coalesce(sum(" + expression + "),0) FROM " + quote(name)).fetchone()[0]
                report["tables"][name] = item
                print("measured table " + name + ": " + json.dumps(item), flush=True)
            else:
                item["table"] = owner
                report["indexes"][name] = item
        if "revisions" in report["tables"]:
            report["revision"] = database.execute("SELECT max(revision) FROM revisions").fetchone()[0]
            report["observed_revision_rows"] = database.execute("SELECT count(*) FROM revisions").fetchone()[0]
        if "current_cells" in report["tables"]:
            # One streaming sweep bounds RAM and avoids SQLite sorting millions
            # of rows into temporary files. Prefixes are diagnostics, not kinds;
            # role participation overlaps and must not be summed as Cell kinds.
            families, categories, roles = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
            structure = dict.fromkeys(("cells", "empty_atoms", "atom_bytes", "identifier_bytes", "revision_column_bytes", "logical_column_bytes", "non_null_link0", "non_null_link1", "relation_chain_cells"), 0)
            for identifier, link0, link1, atom_bytes, revision in database.execute("SELECT cell_id,link0,link1,length(atom),revision FROM current_cells"):
                identifier_bytes = sum(len(value.encode("utf-8")) for value in (identifier, link0, link1))
                revision_bytes = len(str(revision).encode("utf-8"))
                logical_bytes = identifier_bytes + atom_bytes + revision_bytes
                parts = identifier.split(":", 2)
                family = parts[0] if len(parts) > 1 else "[no-prefix]"
                category = ":".join(parts[:2]) if len(parts) > 1 else "[no-prefix]"
                if len(parts) > 1 and (len(parts[1]) > 40 or len(parts[1]) == 36 and parts[1].count("-") == 4
                                      or len(parts[1]) == 32 and all(character in "0123456789abcdefABCDEF" for character in parts[1])):
                    category = family + ":[id]"
                for bucket, key in ((families, family), (categories, category)):
                    if key not in bucket and len(bucket) >= 4096:
                        key = "[other-namespaces]"
                    bucket[key][0] += 1
                    bucket[key][1] += atom_bytes
                    bucket[key][2] += logical_bytes
                if ":role:" in link0:
                    role_family = link0.split(":role:", 1)[0]
                    if role_family not in roles and len(roles) >= 4096:
                        role_family = "[other-role-prefixes]"
                    roles[role_family][0] += 1
                    roles[role_family][1] += atom_bytes
                    roles[role_family][2] += logical_bytes
                structure["cells"] += 1
                structure["empty_atoms"] += atom_bytes == 0
                structure["atom_bytes"] += atom_bytes
                structure["identifier_bytes"] += identifier_bytes
                structure["revision_column_bytes"] += revision_bytes
                structure["logical_column_bytes"] += logical_bytes
                structure["non_null_link0"] += link0 != "00000000-0000-0000-0000-000000000000"
                structure["non_null_link1"] += link1 != "00000000-0000-0000-0000-000000000000"
                structure["relation_chain_cells"] += ":incidence:" in link0
                if structure["cells"] % 1_000_000 == 0:
                    print("current aggregate stream: " + str(structure["cells"]) + " rows", flush=True)
            def groups(values, count_name):
                return [{"family": key, count_name: counts[0], "atom_bytes": counts[1], "logical_column_bytes": counts[2]}
                        for key, counts in sorted(values.items(), key=lambda pair: (-pair[1][0], pair[0]))]
            report["current_id_families"] = groups(families, "cells")
            report["current_id_categories"] = groups(categories, "cells")
            report["current_structure"] = structure
            report["role_families"] = groups(roles, "incidences")
            report["tables"]["current_cells"].update(rows=structure["cells"], logical_column_bytes=structure["logical_column_bytes"], byte_snapshot="current bounded aggregate stream transaction")
            print("measured current Cell role/category stream", flush=True)
            if resume_history and prior and "history" in prior:
                version_rows = database.execute("SELECT count(*) FROM cell_versions").fetchone()[0]
                report["history"] = {"version_rows": version_rows, "current_cell_ids": structure["cells"],
                                     "superseded_rows": version_rows - structure["cells"],
                                     "method": "current and version row counts from the same pinned read transaction",
                                     "previous_atom_byte_snapshot": prior["history"]}
                report["elapsed_seconds"] = round(time.perf_counter() - started, 6)
                return report
            version_rows, version_atom_bytes = database.execute("SELECT count(*),sum(length(atom)) FROM cell_versions").fetchone()
            head = report["current_structure"]
            # CellStore is append-only and never deletes Cell identities. One
            # current row per ID equals each latest version; subtraction avoids
            # millions of random head-index probes on the working computer.
            report["history"] = {"version_rows": version_rows, "current_cell_ids": head["cells"],
                                 "version_atom_bytes": version_atom_bytes,
                                 "superseded_rows": version_rows - head["cells"],
                                 "superseded_atom_bytes": version_atom_bytes - head["atom_bytes"],
                                 "method": "append-only kernel: version totals minus current totals"}
            if prior:
                report["resumed_byte_snapshot_row_counts_unchanged"] = (version_rows == report["tables"]["cell_versions"]["rows"]
                    and head["cells"] == report["tables"]["current_cells"]["rows"]
                    and report["observed_revision_rows"] == report["tables"]["revisions"]["rows"])
        if "messages" in report["tables"]:
            report["conversation_content"] = dict(zip(("messages", "content_bytes", "recipient_bytes", "refs_bytes", "evidence_bytes"), database.execute(
                "SELECT count(*),sum(length(CAST(content AS BLOB))),sum(length(CAST(recipients AS BLOB))),sum(length(CAST(refs AS BLOB))),sum(length(CAST(evidence AS BLOB))) FROM messages").fetchone()))
        report["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        return report
    finally:
        database.rollback()
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume-from", type=Path, help="reuse completed table-byte aggregates; record the separate snapshot provenance")
    parser.add_argument("--resume-history", action="store_true", help="reuse completed history aggregates when refreshing namespace/role bytes")
    args = parser.parse_args()
    validate_output(args.stores, args.output)
    prior = json.loads(args.resume_from.read_text(encoding="utf-8")) if args.resume_from else {}
    result = {"measurement": "SQLite URI mode=ro; query_only=ON; aggregate-only read transactions; resumed table byte snapshot labeled explicitly" if prior else "SQLite URI mode=ro; query_only=ON; aggregate-only read transaction",
              "stores": {path.name: measure(path, prior.get("stores", {}).get(path.name), resume_history=args.resume_history) for path in args.stores}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
