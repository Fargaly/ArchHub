"""Legacy Brain governance/compliance projection surface."""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from . import active_work as aw
from . import hook_coverage as hc
from . import runtime_holders as rh
from . import run_report as rr

if TYPE_CHECKING:
    from .storage import BrainStore


HISTORY_META_KEY = "compliance_history_v1"
HISTORY_LIMIT = 500


def _active_cde_state_path() -> Path:
    raw = os.environ.get("ARCHHUB_ACTIVE_CDE_STATE", "").strip()
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "active_cde_container.json"
    return Path.home() / ".archhub" / "active_cde_container.json"


def _last_gate_decision_path() -> Path:
    raw = os.environ.get("ARCHHUB_LAST_GATE_DECISION", "").strip()
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "last_gate_decision.json"
    return Path.home() / ".archhub" / "last_gate_decision.json"


def _read_json_file(path: Path) -> Optional[dict[str, Any]]:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _claimed_leaves(store: "BrainStore", owner_user: str) -> list[dict[str, Any]]:
    ledger = aw.get_ledger(store, owner_user=owner_user)
    if ledger is None:
        return []
    out: list[dict[str, Any]] = []
    for leaf in ledger.leaves.values():
        if leaf.state == aw.LeafState.CLAIMED:
            out.append(leaf.model_dump(mode="json"))
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except Exception:
        return {"unserializable": str(value)}


def _history_doc(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {"schema": "archhub-compliance-history/v1", "owners": {}}
    try:
        data = json.loads(raw)
    except Exception:
        return {"schema": "archhub-compliance-history/v1", "owners": {}}
    if not isinstance(data, dict):
        return {"schema": "archhub-compliance-history/v1", "owners": {}}
    owners = data.get("owners")
    if not isinstance(owners, dict):
        data["owners"] = {}
    data.setdefault("schema", "archhub-compliance-history/v1")
    return data


def append_compliance_event(
    store: "BrainStore",
    *,
    event: dict[str, Any],
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> dict[str, Any]:
    payload = _prepare_event_payload(event, owner_user=owner_user)
    result = _append_prepared_event(store, owner_user=owner_user, payload=payload)
    result["cell_sync"] = _sync_control_records_to_cells(
        store,
        owner_user=owner_user,
        cell_bridge=cell_bridge,
    )
    return result


def append_compliance_event_cell_first(
    store: "BrainStore",
    *,
    event: dict[str, Any],
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> dict[str, Any]:
    payload = _prepare_event_payload(event, owner_user=owner_user)
    source = "brain-control:compliance-event:%s" % payload["event_id"]
    try:
        runtime = cell_bridge
        if runtime is None:
            from .universal_runtime import UniversalRuntimeBridge

            runtime = UniversalRuntimeBridge()
        created = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": source,
                "scope": "founder/brain-control/compliance-history",
                "claims": json.dumps(
                    {
                        "event_type": payload.get("event_type"),
                        "decision": payload.get("decision"),
                        "code": payload.get("code"),
                    },
                    sort_keys=True,
                ),
                "provenance": "personal_brain.compliance_report:cell_first",
            },
            idempotency_field="source",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    payload["cell_record_root"] = str(created["created_root"])
    payload["cell_record_source"] = source
    result = _append_prepared_event(
        store,
        owner_user=owner_user,
        payload=payload,
    )
    result["cell_first"] = True
    result["brain_written"] = True
    result["cell_record"] = created
    result["cell_sync"] = _sync_control_records_to_cells(
        store,
        owner_user=owner_user,
        cell_bridge=runtime,
    )
    return result


def _prepare_event_payload(
    event: dict[str, Any],
    *,
    owner_user: str,
) -> dict[str, Any]:
    payload = _jsonable(event)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    recorded_at = _utc_now()
    payload.setdefault("event_type", "event")
    payload.setdefault("source", "brain")
    payload["owner_user"] = owner_user
    payload["recorded_at"] = recorded_at
    digest = hashlib.sha256(
        json.dumps(
            {
                "owner_user": owner_user,
                "recorded_at": recorded_at,
                "event": payload,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    payload["event_id"] = digest
    return payload


def _append_prepared_event(
    store: "BrainStore",
    *,
    owner_user: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    def mutate(raw: Optional[str]) -> tuple[str, dict[str, Any]]:
        doc = _history_doc(raw)
        owners = doc.setdefault("owners", {})
        owner = owners.setdefault(owner_user, {"owner_user": owner_user, "events": []})
        events = owner.setdefault("events", [])
        if not isinstance(events, list):
            events = []
        events.append(payload)
        owner["events"] = events[-HISTORY_LIMIT:]
        owner["total"] = len(owner["events"])
        result = {"ok": True, "event": payload, "total": len(owner["events"])}
        return json.dumps(doc, sort_keys=True), result

    return store.update_meta(HISTORY_META_KEY, mutate)


def _sync_control_records_to_cells(
    store: "BrainStore",
    *,
    owner_user: str,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    if cell_bridge is None and str(getattr(store, "path", "")) == ":memory:":
        return {
            "ok": False,
            "status": "skipped",
            "reason": "in-memory Brain store has no implicit runtime sync",
        }
    try:
        from .active_work_cell_migration import (
            migrate_brain_control_records_to_cells,
        )

        result = migrate_brain_control_records_to_cells(
            store,
            bridge=cell_bridge,
            owner_user=owner_user,
        )
        return {"ok": True, "status": "synced", **result}
    except Exception as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def get_compliance_history(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    limit: int = 50,
) -> dict[str, Any]:
    try:
        limit_int = max(0, min(int(limit), HISTORY_LIMIT))
    except Exception:
        limit_int = 50
    doc = _history_doc(store.get_meta(HISTORY_META_KEY))
    owner = doc.get("owners", {}).get(owner_user, {})
    events = owner.get("events", []) if isinstance(owner, dict) else []
    if not isinstance(events, list):
        events = []
    latest = list(reversed(events))[:limit_int]
    return {
        "ok": True,
        "owner_user": owner_user,
        "total": len(events),
        "events": latest,
    }


def _markdown(report: dict[str, Any]) -> str:
    hook = report["hook_coverage"]
    work = report["work"]
    cde = report["active_cde"]
    gate = report["last_gate_decision"]
    history = report.get("history", {})
    run_reports = report.get("run_reports", {})
    runtime_holders = report.get("legacy_runtime_holders", {})

    cde_container = cde.get("container") if isinstance(cde, dict) else None
    cde_id = (
        cde_container.get("container_id")
        if isinstance(cde_container, dict)
        else "none"
    )
    gate_decision = gate.get("decision", "none") if isinstance(gate, dict) else "none"
    gate_code = gate.get("code", "") if isinstance(gate, dict) else ""
    lines = [
        "# Brain Compliance Report",
        "",
        f"Hook coverage: {hook.get('status', 'missing')}",
        f"Active work: open={work['counts'].get('open', 0)} "
        f"claimed={work['counts'].get('claimed', 0)} "
        f"blocked={work['counts'].get('blocked', 0)}",
        f"Active CDE: {cde_id}",
        f"Last gate: {gate_decision}" + (f" ({gate_code})" if gate_code else ""),
        f"Compliance events: {history.get('total', 0)}",
        f"Run reports: {run_reports.get('total', 0)}",
        f"Legacy runtime holders: {runtime_holders.get('holder_count', 0)}",
    ]
    clients = hook.get("clients") if isinstance(hook, dict) else {}
    if isinstance(clients, dict) and clients:
        lines.append("")
        lines.append("Clients:")
        for name in sorted(clients):
            status = clients[name].get("status", "unknown")
            lines.append(f"- {name}: {status}")
    return "\n".join(lines)


def build_compliance_report(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
) -> dict[str, Any]:
    coverage = hc.get_report(store, owner_user=owner_user)
    coverage_data = (
        coverage.model_dump(mode="json")
        if coverage is not None
        else {"status": "missing", "clients": {}, "issues": []}
    )
    work_status = aw.status(store, owner_user=owner_user)
    claimed_leaves = _claimed_leaves(store, owner_user)
    active_cde_file = _read_json_file(_active_cde_state_path()) or {}
    claimed_by_id = {str(leaf.get("leaf_id")): leaf for leaf in claimed_leaves}
    file_leaf_id = str(active_cde_file.get("leaf_id") or "")
    if not claimed_leaves:
        active_cde = {}
    elif file_leaf_id in claimed_by_id:
        active_cde = active_cde_file
    else:
        leaf = claimed_leaves[0]
        active_cde = {
            "schema": "archhub-active-cde/v1",
            "runtime": leaf.get("runtime"),
            "agent_id": leaf.get("claimed_by"),
            "leaf_id": leaf.get("leaf_id"),
            "title": leaf.get("title"),
            "container": leaf.get("cde_container") or {},
            "updated_at": leaf.get("updated_at"),
            "source": "brain-active-work-ledger",
        }
    last_gate = _read_json_file(_last_gate_decision_path()) or {}
    history = get_compliance_history(store, owner_user=owner_user, limit=10)
    run_reports = rr.get_run_reports(store, owner_user=owner_user, limit=5)
    legacy_runtime_holders = rh.audit()
    report = {
        "ok": True,
        "owner_user": owner_user,
        "hook_coverage": coverage_data,
        "work": work_status,
        "claimed_leaves": claimed_leaves,
        "active_cde": active_cde,
        "last_gate_decision": last_gate,
        "history": history,
        "run_reports": run_reports,
        "legacy_runtime_holders": legacy_runtime_holders,
    }
    report["markdown"] = _markdown(report)
    return report


def register_compliance_report_tools(mcp: "Any", store: "BrainStore") -> "Any":
    def _resolve_owner() -> str:
        try:
            getter = getattr(mcp, "_brain_resolve_owner", None)
            if callable(getter):
                val = getter()
                if val:
                    return str(val)
        except Exception:
            pass
        return "founder"

    def _retired_legacy_append(owner: str) -> dict[str, Any]:
        replacement = "brain.compliance_event_append_cell_first"
        return {
            "ok": False,
            "owner_user": owner,
            "universal": True,
            "migration_only": True,
            "deprecated": True,
            "code": "legacy_governance_route_retired",
            "error": (
                "Legacy compliance event append is retired. Use %s so the "
                "event is committed to the Universal Cell graph first."
            ) % replacement,
            "replacement": replacement,
            "cell_first_alternative": replacement,
            "brain_written": False,
        }

    @mcp.tool(
        name="brain.compliance_report",
        description=(
            "Return one Brain governance status report: hook coverage, active "
            "work, active CDE container, and the last pre-tool gate decision."
        ),
    )
    def brain_compliance_report(
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return build_compliance_report(store, owner_user=owner)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.compliance_event_append",
        description=(
            "RETIRED compatibility route. It never appends legacy Brain "
            "history; use brain.compliance_event_append_cell_first."
        ),
    )
    def brain_compliance_event_append(
        event: dict[str, Any],
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_append(owner)

    @mcp.tool(
        name="brain.compliance_event_append_cell_first",
        description=(
            "Create the compliance event as a Universal Cell record first, "
            "then append Brain's migration receipt only if that succeeds."
        ),
    )
    def brain_compliance_event_append_cell_first(
        event: dict[str, Any],
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return append_compliance_event_cell_first(
                store,
                owner_user=owner,
                event=event,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.compliance_history_get",
        description="Return recent Brain governance/compliance events.",
    )
    def brain_compliance_history_get(
        owner_user: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return get_compliance_history(store, owner_user=owner, limit=limit)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    return mcp
