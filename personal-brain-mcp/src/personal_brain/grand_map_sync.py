"""Grand Map -> CDE container -> Brain active-work sync."""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from . import active_work as aw
from . import compliance_report as cr

if TYPE_CHECKING:
    from .storage import BrainStore


def _workspace_root() -> Path:
    configured = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "00.GOVERNANCE" / "hooks" / "cde_gate.py").exists():
            return parent
    raise RuntimeError("ArchHub workspace root is unavailable")


def _cde_gate():
    hooks = _workspace_root() / "00.GOVERNANCE" / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import cde_gate  # type: ignore

    return cde_gate


_MANAGED_FIELDS = ("gate_kind", "gate_spec", "cde_container", "fit", "priority")


def _resolve_overlay_path(
    grand_map_path: str | Path,
    overlay_path: str | Path | None,
) -> Path | None:
    """Resolve the governed overlay, including the canonical sibling layout."""
    if overlay_path:
        resolved = Path(overlay_path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Grand Map CDE overlay not found: {resolved}")
        return resolved

    grand_map = Path(grand_map_path).resolve()
    candidate = grand_map.parent.parent / "cde_overlay_node_native.json"
    return candidate if candidate.is_file() else None


def _overlay_contract(overlay_path: Path | None) -> dict[str, Any]:
    if overlay_path is None:
        return {"target_runtime": ""}
    payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Grand Map CDE overlay must be an object: {overlay_path}")
    target = str(payload.get("target_runtime") or "").replace("\\", "/").strip("/")
    return {"target_runtime": target}


def _route_problem(value: str, target_runtime: str) -> str:
    route = str(value or "").replace("\\", "/").strip()
    if not route:
        return "empty route"
    if route.startswith("/") or re.match(r"^[A-Za-z]:/", route):
        return "absolute route is not allowed"
    parts = [part for part in route.split("/") if part not in ("", ".")]
    if ".." in parts:
        return "parent traversal is not allowed"
    normalized = "/".join(parts).rstrip("/")
    if normalized != target_runtime and not normalized.startswith(target_runtime + "/"):
        return f"route is outside declared target_runtime '{target_runtime}'"
    return ""


def _route_issues(leaves: list[dict[str, Any]], target_runtime: str) -> list[dict[str, str]]:
    if not target_runtime:
        return []
    issues: list[dict[str, str]] = []
    for leaf in leaves:
        cde = leaf.get("cde_container") or {}
        container_id = str(cde.get("container_id") or leaf.get("title") or "unknown")
        candidates: list[tuple[str, str]] = []
        for index, route in enumerate(cde.get("allowed_paths") or []):
            candidates.append((f"cde_container.allowed_paths[{index}]", str(route)))
        gate_spec = leaf.get("gate_spec") or {}
        for field in ("path", "cwd"):
            if gate_spec.get(field):
                candidates.append((f"gate_spec.{field}", str(gate_spec[field])))
        evidence_ref = str(cde.get("evidence_ref") or leaf.get("evidence_ref") or "")
        if evidence_ref.startswith("file:"):
            candidates.append(("evidence_ref", evidence_ref[5:]))
        for field, value in candidates:
            reason = _route_problem(value, target_runtime)
            if reason:
                issues.append({
                    "container_id": container_id,
                    "field": field,
                    "value": value,
                    "target_runtime": target_runtime,
                    "reason": reason,
                })
    return issues


def _is_generated_leaf(leaf: "aw.WorkLeaf") -> bool:
    cde = leaf.cde_container or {}
    return bool(cde.get("node_id")) and str(cde.get("container_id") or "").startswith("GM.")


def _managed_values(leaf: "aw.WorkLeaf") -> dict[str, Any]:
    dumped = leaf.model_dump(mode="json")
    return {field: dumped.get(field) for field in _MANAGED_FIELDS}


def _desired_values(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate_kind": spec.get("gate_kind") or "manual",
        "gate_spec": spec.get("gate_spec") or {},
        "cde_container": spec.get("cde_container") or {},
        "fit": list(spec.get("fit") or []),
        "priority": int(spec.get("priority") or 0),
    }


def _reconcile_ledger(
    ledger: "aw.ActiveWork",
    *,
    owner_user: str,
    leaves: list[dict[str, Any]],
    mutate: bool,
) -> dict[str, int]:
    """Reconcile Grand Map-owned leaves while preserving all other ownership."""
    desired = {
        aw._leaf_id(owner_user, str(spec.get("title") or "")): spec
        for spec in leaves
    }
    result = {
        "added": 0,
        "updated_open": 0,
        "preserved_in_flight": 0,
        "preserved_external": 0,
    }
    now = datetime.now(timezone.utc)
    for leaf_id, spec in desired.items():
        current = ledger.leaves.get(leaf_id)
        values = _desired_values(spec)
        if current is None:
            result["added"] += 1
            if mutate:
                ledger.leaves[leaf_id] = aw.WorkLeaf(
                    leaf_id=leaf_id,
                    title=str(spec.get("title") or "").strip(),
                    state=aw.LeafState.OPEN,
                    created_at=now,
                    updated_at=now,
                    **values,
                )
            continue
        if not _is_generated_leaf(current):
            result["preserved_external"] += 1
            continue
        if current.state != aw.LeafState.OPEN:
            result["preserved_in_flight"] += 1
            continue
        if _managed_values(current) != values:
            result["updated_open"] += 1
            if mutate:
                for field, value in values.items():
                    setattr(current, field, value)
                current.updated_at = now
    result["preserved_external"] += sum(
        1 for leaf_id in ledger.leaves if leaf_id not in desired
    )
    return result


def preview_grand_map_work_leaves(
    *,
    grand_map_path: str | Path,
    overlay_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_overlay = _resolve_overlay_path(grand_map_path, overlay_path)
    contract = _overlay_contract(resolved_overlay)
    cde_gate = _cde_gate()
    payload = cde_gate.work_leaf_payload_from_grand_map(
        grand_map_path,
        overlay_path=resolved_overlay,
    )
    leaves = list(payload.get("leaves") or [])
    issues = _route_issues(leaves, contract["target_runtime"])
    return {
        "ok": not issues,
        "code": "invalid_cde_routes" if issues else "ok",
        **payload,
        "resolved_overlay_path": str(resolved_overlay or ""),
        "target_runtime": contract["target_runtime"],
        "route_issues": issues,
    }


def sync_grand_map_work_leaves(
    store: "BrainStore",
    *,
    grand_map_path: str | Path,
    overlay_path: str | Path | None = None,
    owner_user: str = "founder",
    dry_run: bool = False,
) -> dict[str, Any]:
    preview = preview_grand_map_work_leaves(
        grand_map_path=grand_map_path,
        overlay_path=overlay_path,
    )
    leaves = list(preview.get("leaves") or [])
    route_issues = list(preview.get("route_issues") or [])
    if route_issues:
        if not dry_run:
            cr.append_compliance_event(
                store,
                owner_user=owner_user,
                event={
                    "event_type": "grand_map_work_sync_rejected",
                    "source": "grand_map_sync",
                    "grand_map_path": str(grand_map_path),
                    "overlay_path": str(preview.get("resolved_overlay_path") or ""),
                    "target_runtime": str(preview.get("target_runtime") or ""),
                    "route_issue_count": len(route_issues),
                    "route_issues": route_issues[:50],
                },
            )
        return {
            **preview,
            "ok": False,
            "code": "invalid_cde_routes",
            "dry_run": dry_run,
            "owner_user": owner_user,
            "status": None,
        }

    if dry_run:
        ledger = aw.get_ledger(store, owner_user=owner_user) or aw.ActiveWork(
            owner_user=owner_user
        )
        reconciliation = _reconcile_ledger(
            ledger,
            owner_user=owner_user,
            leaves=leaves,
            mutate=False,
        )
    else:
        reconciliation = aw.ActiveWorkStore(store).mutate_owner(
            owner_user,
            lambda ledger: _reconcile_ledger(
                ledger,
                owner_user=owner_user,
                leaves=leaves,
                mutate=True,
            ),
        )
    event = {
        "event_type": "grand_map_work_sync",
        "source": "grand_map_sync",
        "dry_run": dry_run,
        "grand_map_path": str(grand_map_path),
        "overlay_path": str(preview.get("resolved_overlay_path") or ""),
        "target_runtime": str(preview.get("target_runtime") or ""),
        "leaf_count": int(preview.get("leaf_count") or 0),
        "skipped_count": int(preview.get("skipped_count") or 0),
        "reconciliation": reconciliation,
        "container_ids": [
            leaf.get("cde_container", {}).get("container_id", "")
            for leaf in leaves
            if isinstance(leaf, dict)
        ],
    }
    if not dry_run:
        cr.append_compliance_event(store, owner_user=owner_user, event=event)
    return {
        "ok": True,
        "dry_run": dry_run,
        "owner_user": owner_user,
        "leaf_count": int(preview.get("leaf_count") or 0),
        "skipped_count": int(preview.get("skipped_count") or 0),
        "leaves": leaves,
        "skipped": list(preview.get("skipped") or []),
        "resolved_overlay_path": str(preview.get("resolved_overlay_path") or ""),
        "target_runtime": str(preview.get("target_runtime") or ""),
        "route_issues": [],
        "reconciliation": reconciliation,
        "status": aw.status(store, owner_user=owner_user) if not dry_run else None,
    }


def preview_grand_map_work_leaves_cell_first(
    *,
    limit: int = 50,
    include_live: bool = False,
    bridge: Any = None,
) -> dict[str, Any]:
    """Preview Grand Map Work through the application-owned Cell runtime."""
    try:
        runtime = bridge
        if runtime is None:
            from .universal_runtime import UniversalRuntimeBridge
            runtime = UniversalRuntimeBridge()
        return runtime.grand_map_work_preview(
            limit=int(limit),
            include_live=bool(include_live),
        )
    except Exception as ex:
        return {
            "ok": False,
            "code": "universal_runtime_unavailable",
            "error": f"{type(ex).__name__}: {ex}",
        }


def sync_grand_map_work_leaves_cell_first(
    *,
    limit: int = 25,
    include_live: bool = False,
    bridge: Any = None,
) -> dict[str, Any]:
    """Sync Grand Map Work through the application-owned Cell runtime."""
    try:
        runtime = bridge
        if runtime is None:
            from .universal_runtime import UniversalRuntimeBridge
            runtime = UniversalRuntimeBridge()
        return runtime.grand_map_work_sync(
            limit=int(limit),
            include_live=bool(include_live),
        )
    except Exception as ex:
        return {
            "ok": False,
            "code": "universal_runtime_unavailable",
            "error": f"{type(ex).__name__}: {ex}",
        }


def register_grand_map_sync_tools(mcp: "Any", store: "BrainStore") -> "Any":
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

    def _retired_legacy_route(
        owner: str,
        operation: str,
        replacement: str,
    ) -> dict[str, Any]:
        """Refuse the old Brain-led route without touching its work ledger."""
        return {
            "ok": False,
            "owner_user": owner,
            "universal": True,
            "migration_only": True,
            "deprecated": True,
            "code": "legacy_governance_route_retired",
            "error": (
                "Legacy Grand Map work %s is retired. Use %s so requirements "
                "and work are read from the Universal Cell graph."
            ) % (operation, replacement),
            "replacement": replacement,
            "cell_first_alternative": replacement,
            "brain_written": False,
            "side_effect_executed": False,
        }

    @mcp.tool(
        name="brain.grand_map_work_preview",
        description=(
            "RETIRED compatibility route. It does not read an external Grand "
            "Map or the legacy Brain work ledger; use "
            "brain.grand_map_work_preview_cell_first."
        ),
    )
    def brain_grand_map_work_preview(
        grand_map_path: str,
        overlay_path: str = "",
    ) -> dict[str, Any]:
        del grand_map_path, overlay_path
        return _retired_legacy_route(
            _resolve_owner(),
            "preview",
            "brain.grand_map_work_preview_cell_first",
        )

    @mcp.tool(
        name="brain.grand_map_work_sync",
        description=(
            "RETIRED compatibility route. It never creates legacy "
            "active_work_v1 leaves or compliance history; use "
            "brain.grand_map_work_sync_cell_first."
        ),
    )
    def brain_grand_map_work_sync(
        grand_map_path: str,
        overlay_path: str = "",
        owner_user: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del grand_map_path, overlay_path, dry_run
        return _retired_legacy_route(
            owner_user or _resolve_owner(),
            "sync",
            "brain.grand_map_work_sync_cell_first",
        )

    @mcp.tool(
        name="brain.grand_map_work_preview_cell_first",
        description=(
            "Preview Grand Map requirements from the application-owned "
            "Universal Cell graph. This does not read an external Grand Map "
            "path or mutate Brain active_work_v1."
        ),
    )
    def brain_grand_map_work_preview_cell_first(
        limit: int = 50,
        include_live: bool = False,
    ) -> dict[str, Any]:
        return preview_grand_map_work_leaves_cell_first(
            limit=limit,
            include_live=include_live,
        )

    @mcp.tool(
        name="brain.grand_map_work_sync_cell_first",
        description=(
            "Create missing Governed Work directly in the application-owned "
            "Universal Cell graph. This does not write Brain active_work_v1."
        ),
    )
    def brain_grand_map_work_sync_cell_first(
        limit: int = 25,
        include_live: bool = False,
    ) -> dict[str, Any]:
        return sync_grand_map_work_leaves_cell_first(
            limit=limit,
            include_live=include_live,
        )

    return mcp
