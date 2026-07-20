"""One-way, non-destructive migration from Brain control rows into Cell work.

The legacy Brain rows remain immutable evidence during migration. Active work
leaves and selected control-plane documents are re-expressed as Governed Work
assemblies plus openable value graphs; no JSON document becomes authority in
the Universal runtime.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from . import active_work as legacy
from . import compliance_report as cr
from . import hook_coverage as hc
from . import run_report as rr
from .universal_runtime import UniversalRuntimeBridge, UniversalRuntimeUnavailable


CONTROL_RECORDS = (
    {
        "key": "hook-coverage",
        "meta_key": hc.COVERAGE_META_KEY,
        "title": "Hook Coverage",
        "description": "Runtime hook audit and repair evidence.",
        "priority": 70,
    },
    {
        "key": "compliance-history",
        "meta_key": cr.HISTORY_META_KEY,
        "title": "Compliance History",
        "description": "Append-only governance and gate event evidence.",
        "priority": 65,
    },
    {
        "key": "run-report",
        "meta_key": rr.RUN_REPORT_META_KEY,
        "title": "Run Reports",
        "description": "Per-run report evidence required before closure.",
        "priority": 60,
    },
)


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_digest(store) -> str:
    raw = store.get_meta(legacy.LEDGER_META_KEY)
    return _digest(raw or "")


def _payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw, "encoding": "text"}


def _existing_external_keys(runtime_state: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in runtime_state.get("items") or ():
        if not isinstance(item, dict):
            continue
        value = item.get("external_key")
        root = item.get("root")
        if isinstance(value, str) and isinstance(root, str):
            out[value] = root
            continue
        interfaces = item.get("interfaces")
        if not isinstance(interfaces, dict):
            continue
        external = interfaces.get("external-key")
        if not isinstance(external, dict):
            continue
        value = external.get("value")
        root = item.get("root")
        if isinstance(value, str) and isinstance(root, str):
            out[value] = root
    return out


def _runtime_work_index(runtime) -> dict[str, Any]:
    work_index = getattr(runtime, "work_index", None)
    if callable(work_index):
        return work_index()
    return runtime.work_list()


def _work_create_with_recovery(
    runtime,
    *,
    external_key: str,
    recovery_attempts: int,
    recovery_sleep: float,
    **body: Any,
) -> dict[str, Any]:
    try:
        return runtime.work_create(external_key=external_key, **body)
    except UniversalRuntimeUnavailable as exc:
        last_error = exc
        for _attempt in range(max(0, int(recovery_attempts)) + 1):
            if recovery_sleep > 0:
                time.sleep(recovery_sleep)
            try:
                runtime_state = _runtime_work_index(runtime)
            except UniversalRuntimeUnavailable as retry_exc:
                last_error = retry_exc
                continue
            existing = _existing_external_keys(runtime_state)
            if external_key in existing:
                return {
                    "created_root": existing[external_key],
                    "membership_wire": "",
                    "revision": runtime_state.get("revision"),
                    "recovered_after_timeout": True,
                }
        raise last_error


def _source_records(store) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for spec in CONTROL_RECORDS:
        raw = store.get_meta(str(spec["meta_key"]))
        if raw is None:
            continue
        digest = _digest(raw)
        meta_key = str(spec["meta_key"])
        records.append({
            **spec,
            "raw": raw,
            "digest": digest,
            "external_key": "brain-control:%s" % meta_key,
            "legacy_external_prefix": "brain-control:%s:" % meta_key,
        })
    return records


def _existing_control_record_work_root(
    existing: Mapping[str, str],
    record: Mapping[str, Any],
) -> str | None:
    external_key = str(record["external_key"])
    if external_key in existing:
        return existing[external_key]
    legacy_prefix = str(record.get("legacy_external_prefix") or "")
    if legacy_prefix:
        for key, root in sorted(existing.items()):
            if key.startswith(legacy_prefix):
                return root
    return None


def migrate_active_work_to_cells(
    store,
    *,
    bridge: UniversalRuntimeBridge | None = None,
    owner_user: str | None = None,
    limit: int | None = None,
    leaf_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    recovery_attempts: int = 6,
    recovery_sleep: float = 5.0,
) -> dict[str, Any]:
    """Import every legacy leaf exactly once without changing the source row."""
    if limit is not None:
        limit = int(limit)
        if limit < 1:
            raise ValueError("active-work Cell migration limit must be positive")
    allowed_leaf_ids = (
        {str(item) for item in leaf_ids}
        if leaf_ids is not None else None
    )
    if allowed_leaf_ids is not None and not allowed_leaf_ids:
        raise ValueError("active-work Cell migration leaf_ids cannot be empty")
    runtime = bridge or UniversalRuntimeBridge()
    before_raw = store.get_meta(legacy.LEDGER_META_KEY)
    source_digest = _legacy_digest(store)
    runtime_state = _runtime_work_index(runtime)
    scope_root = runtime_state.get("brain_scope") or runtime_state.get("application")
    if not isinstance(scope_root, str) or not scope_root:
        raise RuntimeError("Universal runtime did not expose a Brain scope")
    existing = _existing_external_keys(runtime_state)
    imported = []
    skipped = []
    remaining = 0
    excluded = 0
    latest_revision = runtime_state.get("revision")
    owners = [owner_user] if owner_user else legacy.list_owners(store)
    position = len(existing)
    for owner_user in owners:
        ledger = legacy.get_ledger(store, owner_user=owner_user)
        if ledger is None:
            continue
        ledger_record = {
            "owner_user": ledger.owner_user,
            "iterations": ledger.iterations,
            "cap": ledger.cap,
            "created_at": ledger.created_at.isoformat(),
            "updated_at": ledger.updated_at.isoformat(),
        }
        for leaf in sorted(
            ledger.leaves.values(),
            key=lambda item: (item.created_at, item.leaf_id),
        ):
            if leaf.leaf_id in existing:
                skipped.append({
                    "leaf_id": leaf.leaf_id,
                    "work_root": existing[leaf.leaf_id],
                })
                continue
            if (
                allowed_leaf_ids is not None
                and leaf.leaf_id not in allowed_leaf_ids
            ):
                excluded += 1
                continue
            if limit is not None and len(imported) >= limit:
                remaining += 1
                continue
            leaf_record = leaf.model_dump(mode="json")
            created = _work_create_with_recovery(
                runtime,
                title=leaf.title,
                description=leaf.note,
                priority=leaf.priority,
                external_key=leaf.leaf_id,
                references={"scope": scope_root},
                structured_references={
                    "requirements": {
                        "gate": {
                            "kind": leaf.gate_kind,
                            "spec": leaf.gate_spec,
                        },
                    },
                    "cde-container": leaf.cde_container,
                    "required-capabilities": leaf.fit,
                    "applicable-policy": leaf.governance_context,
                    "inputs": {
                        "source": {
                            "system": "personal_brain.active_work_v1",
                            "meta_key": legacy.LEDGER_META_KEY,
                            "digest": source_digest,
                        },
                        "ledger": ledger_record,
                        "leaf": leaf_record,
                        "migration_state_policy": (
                            "legacy state is evidence; the Cell work starts OPEN "
                            "until its graph gates admit a new transition"
                        ),
                    },
                },
                x=720.0 + ((position % 3) * 420.0),
                y=420.0 + ((position // 3) * 280.0),
                compact_references=True,
                select_created=False,
                recovery_attempts=recovery_attempts,
                recovery_sleep=float(recovery_sleep),
            )
            position += 1
            existing[leaf.leaf_id] = created["created_root"]
            latest_revision = created.get("revision", latest_revision)
            imported.append({
                "leaf_id": leaf.leaf_id,
                "work_root": created["created_root"],
                "membership_wire": created["membership_wire"],
                "recovered_after_timeout": bool(
                    created.get("recovered_after_timeout")
                ),
            })
    after_raw = store.get_meta(legacy.LEDGER_META_KEY)
    if after_raw != before_raw:
        raise RuntimeError("legacy active-work evidence changed during migration")
    return {
        "source_key": legacy.LEDGER_META_KEY,
        "source_digest": source_digest,
        "source_preserved": True,
        "owners": owners,
        "imported": imported,
        "skipped": skipped,
        "excluded": excluded,
        "remaining": remaining,
        "complete": remaining == 0,
        "migration_limit": limit,
        "leaf_id_filter_count": (
            len(allowed_leaf_ids) if allowed_leaf_ids is not None else None
        ),
        "runtime_revision": latest_revision,
    }


def migrate_brain_control_records_to_cells(
    store,
    *,
    bridge: UniversalRuntimeBridge | None = None,
    owner_user: str = "founder",
) -> dict[str, Any]:
    """Import known Brain meta records without changing the Brain source rows."""
    runtime = bridge or UniversalRuntimeBridge()
    before = {str(spec["meta_key"]): store.get_meta(str(spec["meta_key"]))
              for spec in CONTROL_RECORDS}
    records = _source_records(store)
    runtime_state = _runtime_work_index(runtime)
    brain_scope = runtime_state["brain_scope"]
    existing = _existing_external_keys(runtime_state)
    imported: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    position = len(existing)
    latest_revision = runtime_state.get("revision")

    for record in records:
        external_key = str(record["external_key"])
        record_assembly = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": external_key,
                "scope": "founder/brain-control",
                "claims": "%s digest %s" % (
                    record["title"],
                    record["digest"],
                ),
                "provenance": "personal_brain.brain_meta:%s" % (
                    record["meta_key"],
                ),
            },
            idempotency_field="source",
            x=520.0 + ((position % 2) * 420.0),
            y=520.0 + ((position // 2) * 260.0),
        )
        record_root = str(record_assembly["created_root"])
        existing_root = _existing_control_record_work_root(existing, record)
        if existing_root is not None:
            skipped.append({
                "meta_key": str(record["meta_key"]),
                "digest": str(record["digest"]),
                "work_root": existing_root,
                "record_root": record_root,
            })
            continue

        created = runtime.work_create(
            title="Consume Brain control record: %s" % record["title"],
            description=str(record["description"]),
            priority=int(record["priority"]),
            external_key=external_key,
            references={"scope": brain_scope},
            structured_references={
                "plan": {
                    "record_root": record_root,
                    "record_definition": "knowledge-branch",
                    "record_source": external_key,
                },
                "requirements": {
                    "gate": {
                        "kind": "pytest",
                        "spec": {
                            "path": (
                                "personal-brain-mcp/tests/"
                                "test_brain_control_cell_migration.py"
                            ),
                            "args": ["-q"],
                        },
                    },
                },
                "applicable-policy": {
                    "authority": "10.PRODUCT/13.NODE-LANGUAGE",
                    "legacy_source": "personal_brain.brain_meta",
                    "legacy_migration_only": True,
                    "promotion_allowed": False,
                    "source_preserved": True,
                },
                "inputs": {
                    "source": {
                        "system": "personal_brain.brain_meta",
                        "meta_key": record["meta_key"],
                        "digest": record["digest"],
                        "owner_user": owner_user,
                        "record_root": record_root,
                    },
                    "record": {
                        "key": record["key"],
                        "title": record["title"],
                        "payload": _payload(str(record["raw"])),
                    },
                    "migration_state_policy": (
                        "legacy Brain meta row remains evidence; Universal "
                        "Cell work is the visible consumption path until the "
                        "record protocol is fully native"
                    ),
                },
            },
            x=940.0 + ((position % 2) * 420.0),
            y=520.0 + ((position // 2) * 260.0),
            compact_references=True,
            select_created=False,
        )
        position += 1
        existing[external_key] = created["created_root"]
        latest_revision = created.get("revision", latest_revision)
        imported.append({
            "meta_key": str(record["meta_key"]),
            "digest": str(record["digest"]),
            "record_root": record_root,
            "work_root": str(created["created_root"]),
            "membership_wire": str(created["membership_wire"]),
        })

    after = {str(spec["meta_key"]): store.get_meta(str(spec["meta_key"]))
             for spec in CONTROL_RECORDS}
    if after != before:
        raise RuntimeError(
            "legacy Brain control-plane evidence changed during migration"
        )
    return {
        "source": "personal_brain.brain_meta",
        "source_preserved": True,
        "owner_user": owner_user,
        "record_count": len(records),
        "imported": imported,
        "skipped": skipped,
        "missing": [
            str(spec["meta_key"])
            for spec in CONTROL_RECORDS
            if before[str(spec["meta_key"])] is None
        ],
        "runtime_revision": latest_revision,
    }


__all__ = [
    "CONTROL_RECORDS",
    "migrate_active_work_to_cells",
    "migrate_brain_control_records_to_cells",
]
