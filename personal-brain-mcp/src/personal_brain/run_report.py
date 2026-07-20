"""Legacy Brain run-report projection ledger.

Each meaningful agent run is recorded as a first-class Brain node under one
brain_meta document: run_report_v1. Active work completion can then require a
report for the leaf before closing it.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .storage import BrainStore


RUN_REPORT_META_KEY = "run_report_v1"
RUN_REPORT_LIMIT = 500
REQUIRED_SECTIONS = (
    "what_i_did",
    "where_we_are",
    "evidence",
    "problems_risks",
    "whats_next",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except Exception:
        return {"unserializable": str(value)}


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _doc(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {"schema": "archhub-run-report-ledger/v1", "owners": {}}
    try:
        data = json.loads(raw)
    except Exception:
        return {"schema": "archhub-run-report-ledger/v1", "owners": {}}
    if not isinstance(data, dict):
        return {"schema": "archhub-run-report-ledger/v1", "owners": {}}
    owners = data.get("owners")
    if not isinstance(owners, dict):
        data["owners"] = {}
    data.setdefault("schema", "archhub-run-report-ledger/v1")
    return data


def _sections(report: dict[str, Any]) -> dict[str, list[str]]:
    source = report.get("sections")
    source = source if isinstance(source, dict) else {}
    sections = {
        key: _coerce_list(report.get(key, source.get(key)))
        for key in REQUIRED_SECTIONS
    }
    for key in ("what_i_did", "where_we_are", "evidence", "whats_next"):
        if not sections[key]:
            raise ValueError(f"run report requires section '{key}'")
    return sections


def _new_report_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"rr_{digest}"


def append_run_report(
    store: "BrainStore",
    *,
    report: dict[str, Any],
    owner_user: str = "founder",
    leaf_id: str = "",
    runtime: str = "",
    agent_id: str = "",
    changed_nodes: Optional[list[str]] = None,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    payload = _prepare_run_report_payload(
        report=report,
        owner_user=owner_user,
        leaf_id=leaf_id,
        runtime=runtime,
        agent_id=agent_id,
        changed_nodes=changed_nodes,
    )
    result = _append_prepared_run_report(
        store,
        owner_user=owner_user,
        payload=payload,
    )
    try:
        from . import compliance_report as cr

        compliance = cr.append_compliance_event(
            store,
            owner_user=owner_user,
            cell_bridge=cell_bridge,
            event={
                "event_type": "run_report_append",
                "source": "run_report",
                "report_id": payload["report_id"],
                "leaf_id": payload["leaf_id"],
                "runtime": payload["runtime"],
                "agent_id": payload["agent_id"],
                "changed_nodes": payload["changed_nodes"],
            },
        )
        if isinstance(compliance, dict) and "cell_sync" in compliance:
            result["cell_sync"] = compliance["cell_sync"]
    except Exception:
        pass
    return result


def append_run_report_cell_first(
    store: "BrainStore",
    *,
    report: dict[str, Any],
    owner_user: str = "founder",
    leaf_id: str = "",
    runtime: str = "",
    agent_id: str = "",
    changed_nodes: Optional[list[str]] = None,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    payload = _prepare_run_report_payload(
        report=report,
        owner_user=owner_user,
        leaf_id=leaf_id,
        runtime=runtime,
        agent_id=agent_id,
        changed_nodes=changed_nodes,
    )
    source = "brain-control:run-report:%s" % payload["report_id"]
    try:
        runtime_bridge = cell_bridge
        if runtime_bridge is None:
            from .universal_runtime import UniversalRuntimeBridge

            runtime_bridge = UniversalRuntimeBridge()
        created = runtime_bridge.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": source,
                "scope": "founder/brain-control/run-reports",
                "claims": json.dumps(
                    {
                        "report_id": payload["report_id"],
                        "leaf_id": payload["leaf_id"],
                        "runtime": payload["runtime"],
                        "agent_id": payload["agent_id"],
                    },
                    sort_keys=True,
                ),
                "provenance": "personal_brain.run_report:cell_first",
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
    result = _append_prepared_run_report(
        store,
        owner_user=owner_user,
        payload=payload,
    )
    result["cell_first"] = True
    result["brain_written"] = True
    result["cell_record"] = created
    try:
        from . import compliance_report as cr

        compliance = cr.append_compliance_event_cell_first(
            store,
            owner_user=owner_user,
            cell_bridge=runtime_bridge,
            event={
                "event_type": "run_report_append",
                "source": "run_report_cell_first",
                "report_id": payload["report_id"],
                "leaf_id": payload["leaf_id"],
                "runtime": payload["runtime"],
                "agent_id": payload["agent_id"],
                "changed_nodes": payload["changed_nodes"],
                "cell_record_root": payload["cell_record_root"],
            },
        )
        result["compliance_event"] = compliance
        if isinstance(compliance, dict) and "cell_sync" in compliance:
            result["cell_sync"] = compliance["cell_sync"]
    except Exception as exc:
        result["compliance_event"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result


def _prepare_run_report_payload(
    *,
    report: dict[str, Any],
    owner_user: str,
    leaf_id: str = "",
    runtime: str = "",
    agent_id: str = "",
    changed_nodes: Optional[list[str]] = None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("run report must be a dict")
    payload = {
        "schema": "archhub-run-report/v1",
        "owner_user": owner_user,
        "leaf_id": str(leaf_id or ""),
        "runtime": str(runtime or ""),
        "agent_id": str(agent_id or ""),
        "recorded_at": _utc_now(),
        "sections": _sections(report),
        "changed_nodes": _coerce_list(changed_nodes),
    }
    payload["report_id"] = _new_report_id(payload)
    return _jsonable(payload)


def _append_prepared_run_report(
    store: "BrainStore",
    *,
    owner_user: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    def mutate(raw: Optional[str]) -> tuple[str, dict[str, Any]]:
        doc = _doc(raw)
        owners = doc.setdefault("owners", {})
        owner = owners.setdefault(owner_user, {"owner_user": owner_user, "reports": []})
        reports = owner.setdefault("reports", [])
        if not isinstance(reports, list):
            reports = []
        reports.append(payload)
        owner["reports"] = reports[-RUN_REPORT_LIMIT:]
        owner["total"] = len(owner["reports"])
        result = {"ok": True, "report": payload, "total": len(owner["reports"])}
        return json.dumps(doc, sort_keys=True), result

    return store.update_meta(RUN_REPORT_META_KEY, mutate)


def get_run_reports(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    limit: int = 20,
    leaf_id: str = "",
) -> dict[str, Any]:
    try:
        limit_int = max(0, min(int(limit), RUN_REPORT_LIMIT))
    except Exception:
        limit_int = 20
    doc = _doc(store.get_meta(RUN_REPORT_META_KEY))
    owner = doc.get("owners", {}).get(owner_user, {})
    reports = owner.get("reports", []) if isinstance(owner, dict) else []
    if not isinstance(reports, list):
        reports = []
    if leaf_id:
        reports = [r for r in reports if isinstance(r, dict) and r.get("leaf_id") == leaf_id]
    latest = list(reversed(reports))[:limit_int]
    return {
        "ok": True,
        "owner_user": owner_user,
        "total": len(reports),
        "reports": latest,
    }


def has_run_report_for_leaf(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    leaf_id: str,
) -> bool:
    if not (leaf_id or "").strip():
        return False
    reports = get_run_reports(
        store,
        owner_user=owner_user,
        leaf_id=leaf_id,
        limit=1,
    )
    return bool(reports.get("reports"))


def register_run_report_tools(mcp: "Any", store: "BrainStore") -> "Any":
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
        replacement = "brain.run_report_append_cell_first"
        return {
            "ok": False,
            "owner_user": owner,
            "universal": True,
            "migration_only": True,
            "deprecated": True,
            "code": "legacy_governance_route_retired",
            "error": (
                "Legacy run-report append is retired. Use %s so the report "
                "is committed to the Universal Cell graph first."
            ) % replacement,
            "replacement": replacement,
            "cell_first_alternative": replacement,
            "brain_written": False,
        }

    @mcp.tool(
        name="brain.run_report_append",
        description=(
            "RETIRED compatibility route. It never appends run_report_v1; use "
            "brain.run_report_append_cell_first."
        ),
    )
    def brain_run_report_append(
        report: dict[str, Any],
        owner_user: Optional[str] = None,
        leaf_id: str = "",
        runtime: str = "",
        agent_id: str = "",
        changed_nodes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_append(owner)

    @mcp.tool(
        name="brain.run_report_append_cell_first",
        description=(
            "Create the run report as a Universal Cell record first, then "
            "append Brain's migration receipt only if that succeeds."
        ),
    )
    def brain_run_report_append_cell_first(
        report: dict[str, Any],
        owner_user: Optional[str] = None,
        leaf_id: str = "",
        runtime: str = "",
        agent_id: str = "",
        changed_nodes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return append_run_report_cell_first(
                store,
                owner_user=owner,
                leaf_id=leaf_id,
                runtime=runtime,
                agent_id=agent_id,
                report=report,
                changed_nodes=changed_nodes,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.run_report_get",
        description="Return recent run_report_v1 nodes, optionally filtered by leaf_id.",
    )
    def brain_run_report_get(
        owner_user: Optional[str] = None,
        limit: int = 20,
        leaf_id: str = "",
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return get_run_reports(
                store,
                owner_user=owner,
                limit=limit,
                leaf_id=leaf_id,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    return mcp
