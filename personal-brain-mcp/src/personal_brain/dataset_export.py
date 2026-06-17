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
The privacy/legal layer is WIRED at export (no longer "pre-privacy"):
  - **Collective-scope routing (Q10).** Any COMMUNITY/GLOBAL scope routes
    through `privacy.privatize_for_collective` → differentially-private
    AGGREGATES only; raw rows never reach the collective pool (see
    `_export_collective_dp`).
  - **Training-rights dam (AgDR-0054 · BRV-04).** Raw-row exports are gated by
    `BrainStore.export_trainable_fragments`: quarantined
    (right-to-be-forgotten / poisoned) rows are ALWAYS excluded, and
    `training_target='collective'` additionally excludes `firm_private_only`
    rows. Export-gating is the only reliable unlearning, so the gate runs here.
  - The default `scope_filter=[USER]` still minimises accidental scope
    escalation; `respect_training_rights=True` is the default rights floor.
Still pending (genuinely separate slices, not silently skipped here): a
`payload_pii` USER-only split and per-row PII redaction before the
`content_hash_post` decontamination scan.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from . import privacy
from .models import Fragment, FragmentKind, Scope
from .storage import BrainStore as Store


_SCHEMA_VERSION = "1.0"

# Default differential-privacy budget for collective-scope exports. Smaller
# epsilon = more noise = stronger privacy. 1.0 is a conventional starting
# point (Apple iOS telemetry ships in this range); callers may override.
_DEFAULT_COLLECTIVE_EPSILON = 1.0


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
        # Quality signals for training-set filtering (added 2026-06-02 for
        # Brain #33 readiness): confidence tier + memory half-life let a
        # training run drop low-confidence / stale rows. Mirror the kind/scope
        # enum-or-str pattern above.
        "confidence":      (frag.confidence.value if hasattr(frag.confidence, "value") else str(frag.confidence)) if getattr(frag, "confidence", None) is not None else "",
        "half_life_days":  getattr(frag, "half_life_days", None),
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


# AgDR-0054 — the export-time legal/rights dam, wired INTO the exporter the
# founder named (closes BRV-04: the dam lived in storage.py but `export_fragments`
# never consulted it, so a quarantined / out-of-tier fragment landed verbatim in a
# training export). `BrainStore.export_trainable_fragments` is the single authority
# on which fragment ids are legally trainable for a given target:
#   - quarantine_flag = 1            -> NEVER exported (any target)
#   - target='collective'            -> only training_rights_tier='collective_ok'
#   - target='firm_private'          -> 'collective_ok' or 'firm_private_only'
# Export-gating is the ONLY reliable unlearning (weights-level erasure is
# impossible), so this gate runs HERE, at the export, not at recall.
_VALID_TRAINING_TARGETS = ("collective", "firm_private")


def _trainable_id_set(store: Store, training_target: str) -> set[str]:
    """Ask the legal/rights dam which fragment ids may leave for `training_target`.

    Returns the set of ids the dam clears. Raw rows whose id is NOT in this set
    (quarantined or out-of-tier) are excluded from the export. Raises
    ``ValueError`` for an unknown target (mirrors the dam's own contract) so a
    typo can never silently widen the export.
    """
    if training_target not in _VALID_TRAINING_TARGETS:
        raise ValueError(
            f"unknown training_target {training_target!r}; "
            f"expected one of {_VALID_TRAINING_TARGETS}"
        )
    cleared = store.export_trainable_fragments(target=training_target)
    return {row["id"] for row in cleared}


def _export_collective_dp(
    store: Store,
    out_dir: Path,
    *,
    dataset_name: str,
    scope_filter: list[Scope],
    kinds: Optional[Iterable[FragmentKind]] = None,
    since: Optional[str] = None,
    limit: int = 10_000,
    owner_user: Optional[str] = None,
    epsilon: float = _DEFAULT_COLLECTIVE_EPSILON,
) -> dict[str, Any]:
    """Collective-scope export — differentially-private AGGREGATES only.

    Never writes ``fragments.jsonl``/``.parquet`` (raw rows). Writes
    ``aggregates.json`` (DP counts) + ``manifest.json``. This is the only
    path by which the brain emits anything toward the collective pool, per
    docs/research/privacy-respecting-knowledge-sharing-2026-05-26.md §D.
    """
    frags = store.list_fragments(
        scope_filter=scope_filter,
        kinds=kinds,
        owner_user=owner_user,
        since=since,
        limit=limit,
    )
    aggregates = privacy.privatize_for_collective(frags, epsilon=epsilon)

    target = Path(out_dir) / dataset_name
    target.mkdir(parents=True, exist_ok=True)

    agg_path = target / "aggregates.json"
    agg_path.write_text(
        json.dumps(aggregates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "ok": True,
        "schema_version": _SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "mode": "collective_dp",          # signals: DP aggregates, no raw rows
        "row_count": 0,                    # raw rows intentionally not emitted
        "differential_privacy": True,
        "epsilon": epsilon,
        "mechanism": aggregates.get("mechanism"),
        "filter": {
            "scopes": [s.value for s in scope_filter],
            "kinds":  ([k.value for k in (kinds or [])] if kinds else None),
            "since":  since,
            "limit":  limit,
            "owner_user": owner_user,
        },
        "files": {
            "aggregates": {"path": str(agg_path),
                           "bytes": agg_path.stat().st_size},
        },
        "guarantee": aggregates.get("guarantee"),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    manifest["aggregates"] = aggregates
    return manifest


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
    epsilon: float = _DEFAULT_COLLECTIVE_EPSILON,
    respect_training_rights: bool = True,
    training_target: str = "firm_private",
) -> dict[str, Any]:
    """Export fragments matching the filter to <out_dir>/<dataset_name>/.

    Returns a manifest dict with row count + file paths + byte sizes.
    Caller is responsible for any post-processing (cloud upload, etc).

    **Privacy routing (Q10 layer).** If ``scope_filter`` includes a
    collective-class scope (COMMUNITY / GLOBAL — the ArchHub-wide pool that
    feeds Brain #33 model training), raw rows are NEVER written. Instead the
    export routes through ``privacy.privatize_for_collective`` and emits a
    differentially-private aggregate (counts by kind/scope, noised) under
    ``aggregates.json``. This is the runtime that enforces the research-doc
    guarantee: raw user fragments never reach the collective scope — only DP
    aggregates do. ``epsilon`` tunes the noise (smaller = stronger privacy).
    Non-collective exports (USER / PROJECT / FIRM) are unchanged.

    **Legal/training-rights dam (AgDR-0054 · BRV-04).** Raw-row exports are
    gated by ``BrainStore.export_trainable_fragments`` — the single authority on
    which fragments may legally leave for training. With
    ``respect_training_rights=True`` (default), any fragment that is
    ``quarantine_flag=1`` (poisoned / right-to-be-forgotten) or out-of-tier for
    ``training_target`` is EXCLUDED from the written dataset. This is the
    export-time enforcement of the rights tiers; recall-time gating cannot
    substitute because export-gating is the only reliable unlearning (weights
    can't be surgically erased).

    ``training_target`` matches the dam's own contract:
      - ``'firm_private'`` (default) — the minimal legal floor: clears
        ``collective_ok`` + ``firm_private_only`` and drops ONLY quarantined /
        ``quarantine_never_trains`` rows. This is the floor EVERY raw export must
        respect — right-to-be-forgotten / poisoned data never leaves, whatever
        the destination.
      - ``'collective'`` — the stricter pool gate: clears only ``collective_ok``,
        so ``firm_private_only`` rows are also excluded. Pass this when the
        dataset feeds the cross-firm collective training pool.

    Set ``respect_training_rights=False`` ONLY for a same-scope operational dump
    that never feeds training; the manifest records which gate ran so the choice
    is auditable.
    """
    if scope_filter is None:
        # Privacy default — USER-scope only.
        scope_filter = [Scope.USER]
    scope_filter = list(scope_filter)

    # Q10 privacy gate: a collective-class target never emits raw rows.
    if any(privacy.is_collective_scope(s) for s in scope_filter):
        return _export_collective_dp(
            store,
            out_dir,
            dataset_name=dataset_name,
            scope_filter=scope_filter,
            kinds=kinds,
            since=since,
            limit=limit,
            owner_user=owner_user,
            epsilon=epsilon,
        )

    frags = store.list_fragments(
        scope_filter=scope_filter,
        kinds=kinds,
        owner_user=owner_user,
        since=since,
        limit=limit,
    )

    # AgDR-0054 legal/rights dam (BRV-04): exclude quarantined / out-of-tier
    # fragments from the raw export by intersecting with the ids the dam clears.
    # `training_rights_excluded` is the count dropped here — surfaced in the
    # manifest so the gate is auditable and a regression (dam dead-wired again)
    # is visible. Validating `training_target` up-front means a typo raises
    # rather than silently widening the export.
    if respect_training_rights:
        if training_target not in _VALID_TRAINING_TARGETS:
            raise ValueError(
                f"unknown training_target {training_target!r}; "
                f"expected one of {_VALID_TRAINING_TARGETS}"
            )
        cleared_ids = _trainable_id_set(store, training_target)
        before = len(frags)
        frags = [f for f in frags if f.id in cleared_ids]
        training_rights_excluded = before - len(frags)
    else:
        training_rights_excluded = 0

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
        # AgDR-0054 legal/rights dam audit (BRV-04): names which gate ran + how
        # many rows it dropped, so the dam is provably wired (not dead) and any
        # regression is visible in the dataset's own manifest.
        "training_rights": {
            "enforced": respect_training_rights,
            "target": training_target if respect_training_rights else None,
            "excluded_count": training_rights_excluded,
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
