"""READ-ONLY inventory of the brain DB (fragments + skills).

Opens brain.db in IMMUTABLE/read-only mode together with its live WAL so the
inventory reflects exactly what the running daemon sees. ZERO writes. Dumps a
JSON file the sort step consumes, plus a compact stdout summary.

Why read-only sqlite (not the daemon) for READS: the daemon holds the single
writer connection; a second *reader* in WAL mode is safe and standard
("single writer, many readers"). We never open a second WRITER here.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import sys
from collections import Counter
from pathlib import Path

DB = Path(r"C:\Users\fargaly\AppData\Roaming\ArchHub\brain\brain.db")
OUT = Path(__file__).resolve().parent / "brain_sort_inventory.json"


def _unpack_embedding(blob):
    if not blob:
        return None
    try:
        n = len(blob) // 8
        if n == 0:
            return None
        return list(struct.unpack(f"<{n}d", blob))
    except Exception:
        return None


def main() -> int:
    # mode=ro = read-only but still reads the live -wal. Do NOT use immutable
    # (that would ignore the WAL and miss the 3.1MB uncommitted data).
    uri = f"file:{DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    frags = []
    for row in conn.execute("SELECT * FROM fragments ORDER BY created_at, id"):
        prov = json.loads(row["provenance_json"]) if row["provenance_json"] else {}
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        emb = _unpack_embedding(row["embedding_blob"])
        frags.append({
            "id": row["id"],
            "kind": row["kind"],
            "text": row["text"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "scope": row["scope"],
            "visibility": row["visibility"],
            "owner_user": row["owner_user"],
            "project_id": row["project_id"],
            "firm_id": row["firm_id"],
            "confidence": row["confidence"],
            "provenance": prov,
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "success_count": row["success_count"],
            "fail_count": row["fail_count"],
            "last_used_at": row["last_used_at"],
            "half_life_days": row["half_life_days"],
            "extra": extra,
            "perceptual_hash": row["perceptual_hash"],
            "blob_path": row["blob_path"],
            "blob_mime": row["blob_mime"],
            "blob_bytes": row["blob_bytes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "has_embedding": emb is not None,
            "embedding_dim": (len(emb) if emb else 0),
            "embedding": emb,
        })

    skills = []
    for row in conn.execute("SELECT id, name, scope, side_effects, owner_user, "
                            "success_count, fail_count, honed_trials, honed_passed, "
                            "minted_at FROM skills ORDER BY name"):
        skills.append({k: row[k] for k in row.keys()})

    # table counts
    tables = {}
    for t in ("fragments", "skills", "wiring", "secret_refs", "access_log",
              "brain_meta", "reputation"):
        try:
            tables[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception as ex:
            tables[t] = f"ERR:{ex}"

    conn.close()

    OUT.write_text(json.dumps({"fragments": frags, "skills": skills,
                               "tables": tables}, indent=2), encoding="utf-8")

    # ── stdout summary (no embeddings dumped) ──
    print(f"DB: {DB}")
    print(f"TABLE COUNTS: {tables}")
    print(f"FRAGMENTS: {len(frags)}   SKILLS: {len(skills)}")
    by_agent = Counter(f["provenance"].get("contributing_agent", "?") for f in frags)
    by_kind = Counter(f["kind"] for f in frags)
    by_scope = Counter(f["scope"] for f in frags)
    by_vis = Counter(f["visibility"] for f in frags)
    by_owner = Counter(f["owner_user"] for f in frags)
    with_emb = sum(1 for f in frags if f["has_embedding"])
    print(f"BY AGENT: {dict(by_agent)}")
    print(f"BY KIND : {dict(by_kind)}")
    print(f"BY SCOPE: {dict(by_scope)}")
    print(f"BY VIS  : {dict(by_vis)}")
    print(f"BY OWNER: {dict(by_owner)}")
    print(f"WITH EMBEDDING: {with_emb}/{len(frags)}  (dims seen: "
          f"{sorted({f['embedding_dim'] for f in frags if f['has_embedding']})})")
    already_tagged = sum(1 for f in frags if isinstance(f['extra'], dict)
                         and ('brain_sort' in f['extra'] or 'category' in f['extra']))
    print(f"ALREADY-CATEGORIZED (extra.category/brain_sort present): {already_tagged}")
    print(f"\nWROTE: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
