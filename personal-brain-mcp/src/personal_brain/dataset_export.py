"""Brain #32 · dataset export.

Per founder ask 2026-05-26: *"this brain should be able to produce training
data sets for models and used to produce our own hosted models in the future
after multiple users form a collective memory enough to do that."*

This module exports brain fragments + skills as HuggingFace-style on-disk
datasets — the foundation for Brain #33 (collective hosted model training).

Format
------
- **JSONL primary** (no extra deps; works on every install). Each line is
  one fragment serialized as JSON.
- **Parquet optional** (when `pyarrow` is importable). Single .parquet file
  per dataset; faster + smaller for downstream HF training.
- **Manifest file** (`manifest.json`) alongside every dataset: schema,
  filter used, row count, byte size, scope distribution, created_at.

Output layout::

    <out_dir>/<dataset_name>/
        manifest.json
        fragments.jsonl                  (always)
        fragments.parquet                (when pyarrow available)

Filters
-------
- scope: which scopes to include (default: user only — never leaks
  higher-scope data without explicit caller opt-in)
- kinds: fragment kinds (fact / skill / wire_version / ...)
- since: ISO8601 timestamp; only fragments at or after
- limit: cap row count (default 10_000)

Privacy
-------
This is the PRE-PRIVACY-LAYER export. The Q10 privacy slice (separate)
adds:
  - `payload_pii` split kept at USER-scope only
  - `redacted=true` requirement for COLLECTIVE-scope export
  - differential privacy noise on aggregates
Until Q10 lands, callers MUST be conscious of which scope they're
exporting from. The default `scope_filter=[USER]` minimises accidental
escalation.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Fragment, FragmentKind, Scope
from .storage import BrainStore as Store


_SCHEMA_VERSION = "1.0"


def _fragment_to_row(frag: Fragment) -> dict[str, Any]:
    """Flatten a Fragment to a JSON-serialisable training-data row."""
    prov = frag.provenance
    created_at = prov.created_at.isoformat() if prov and prov.created_at else ""
    return {
        "id":              frag.id,
        "kind":            frag.kind.value if hasattr(frag.kind, "value") else str(frag.kind),
        "scope":           frag.scope.value if hasattr(frag.scope, "value") else str(frag.scope),
        "subject":         frag.subject or "",
        "predicate":       frag.predicate or "",
        "object":          frag.object or "",
        "text":            frag.text or "",
        "owner_user":      frag.owner_user or "",
        "firm_id":         frag.firm_id or "",
        "project_id":      frag.project_id or "",
        "created_at":      created_at,
        "success_count":   frag.success_count or 0,
        "fail_count":      frag.fail_count or 0,
        "contributing_agent": (prov.contributing_agent if prov else ""),
        # `extra` serialised to JSON string so parquet can write it
        # (pyarrow can't handle struct types with empty schemas).
        "extra":           json.dumps(dict(frag.extra or {}), ensure_ascii=False),
    }


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> int:
    """Write rows as newline-delimited JSON. Returns bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            line = json.dumps(r, ensure_ascii=False) + "\n"
            f.write(line)
            n += len(line.encode("utf-8"))
    return n


def _write_parquet_if_possible(
    rows: list[dict[str, Any]],
    path: Path,
) -> Optional[int]:
    """Best-effort parquet emit. Returns bytes written or None if pyarrow
    isn't installed. Importing inside the function so the module loads
    on minimal installs."""
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except Exception:
        return None
    if not rows:
        # Parquet wants a schema; empty rows = empty file
        path.parent.mkdir(parents=True, exist_ok=True)
        empty = pa.table({})
        pq.write_table(empty, str(path))
        return path.stat().st_size if path.exists() else 0
    table = pa.Table.from_pylist(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))
    return path.stat().st_size if path.exists() else 0


def _scope_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        s = r.get("scope", "unknown")
        out[s] = out.get(s, 0) + 1
    return out


def export_fragments(
    store: Store,
    out_dir: Path,
    *,
    dataset_name: str,
    scope_filter: Optional[Iterable[Scope]] = None,
    kinds: Optional[Iterable[FragmentKind]] = None,
    since: Optional[str] = None,
    limit: int = 10_000,
    owner_user: Optional[str] = None,
) -> dict[str, Any]:
    """Export fragments matching the filter to <out_dir>/<dataset_name>/.

    Returns a manifest dict with row count + file paths + byte sizes.
    Caller is responsible for any post-processing (cloud upload, etc).
    """
    if scope_filter is None:
        # Privacy default — USER-scope only.
        scope_filter = [Scope.USER]
    frags = store.list_fragments(
        scope_filter=scope_filter,
        kinds=kinds,
        owner_user=owner_user,
        since=since,
        limit=limit,
    )
    rows = [_fragment_to_row(f) for f in frags]

    target = Path(out_dir) / dataset_name
    target.mkdir(parents=True, exist_ok=True)

    jsonl_path = target / "fragments.jsonl"
    jsonl_bytes = _write_jsonl(rows, jsonl_path)

    parquet_path = target / "fragments.parquet"
    parquet_bytes = _write_parquet_if_possible(rows, parquet_path)

    manifest = {
        "ok": True,
        "schema_version": _SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "row_count": len(rows),
        "scope_distribution": _scope_distribution(rows),
        "filter": {
            "scopes": [s.value for s in scope_filter],
            "kinds":  ([k.value for k in (kinds or [])] if kinds else None),
            "since":  since,
            "limit":  limit,
            "owner_user": owner_user,
        },
        "files": {
            "jsonl":   {"path": str(jsonl_path),   "bytes": jsonl_bytes},
            "parquet": ({"path": str(parquet_path), "bytes": parquet_bytes}
                        if parquet_bytes is not None
                        else {"path": None, "bytes": 0,
                              "note": "pyarrow not installed"}),
        },
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest
