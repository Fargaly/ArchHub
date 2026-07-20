"""Verified Brain projection of the universal Core Values authority.

The universal Cell graph remains the authority. Brain stores only a verified
projection of its identity, revision, digest, lifecycle, coverage, and the
explicit Core Values-to-Brain wire. No caller can upload replacement prose or
declare its own authority manifest through MCP.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import hashlib
import importlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .storage import BrainStore


AUTHORITY_META_KEY = "core_values_authority_v1"
AUTHORITY_ROOT = "app:core-values:v1"
AUTHORITY_WIRE_ROOT = "app:canvas-relation:core-values:brain"
AUTHORITY_SCHEMA = "archhub-core-values-authority/v1"
VALUE_KEYS = (
    "security",
    "truth",
    "ownership",
    "respect-time",
    "architect-review",
    "real-pain",
    "simplicity",
    "test-ship",
    "iterate",
    "root-cause",
)
HARD_GATE_VALUES = frozenset({"security", "truth", "ownership", "test-ship"})
RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
GREEN = "green"
RED = "red"


class CoreValuesAuthorityReport(BaseModel):
    schema_name: str = AUTHORITY_SCHEMA
    owner_user: str = "founder"
    status: str = RED
    authority_root: str = AUTHORITY_ROOT
    authority_wire_root: str = AUTHORITY_WIRE_ROOT
    source_digest: str = ""
    translation_digest: str = ""
    lifecycle: str = "unknown"
    graph_revision: int = -1
    revision_chain_digest: str = ""
    coverage: dict[str, str] = Field(default_factory=dict)
    database_identity: str = ""
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    issues: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_root() -> Path:
    configured = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "00.GOVERNANCE").is_dir():
            return candidate
    raise FileNotFoundError("ArchHub workspace root is unavailable")


def _node_language_root() -> Path:
    configured = os.environ.get("ARCHHUB_NODE_LANGUAGE_ROOT", "").strip()
    root = (
        Path(configured).expanduser().resolve()
        if configured
        else _workspace_root() / "10.PRODUCT" / "13.NODE-LANGUAGE"
    )
    if not (root / "nodelang" / "universal_cell.py").is_file():
        raise FileNotFoundError("universal Cell runtime is unavailable")
    return root


def _runtime_descriptor_path() -> Path:
    configured = os.environ.get("ARCHHUB_UNIVERSAL_RUNTIME_STATE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "ArchHub" / "active-universal-runtime.json"


def _database_path() -> Path:
    configured = os.environ.get("ARCHHUB_UNIVERSAL_DB", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        descriptor = _runtime_descriptor_path()
        path: Path | None = None
        if descriptor.is_file():
            try:
                payload = json.loads(descriptor.read_text(encoding="utf-8"))
                raw = payload.get("database") if isinstance(payload, dict) else ""
                if raw:
                    path = Path(str(raw)).expanduser().resolve()
            except (OSError, ValueError):
                path = None
        if path is None:
            local = Path(
                os.environ.get("LOCALAPPDATA")
                or Path.home() / "AppData" / "Local"
            )
            path = (
                local
                / "ArchHub"
                / "node-native-wip.json.gz.universal.sqlite3"
            )
    if path.suffix.lower() != ".sqlite3" or not path.is_file():
        raise FileNotFoundError("active universal Cell database is unavailable")
    return path


@contextmanager
def _import_root(root: Path) -> Iterator[None]:
    value = str(root)
    inserted = value not in sys.path
    if inserted:
        sys.path.insert(0, value)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(value)
            except ValueError:
                pass


def _one_for_role(members: Any, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise ValueError("Core Values Brain wire requires one %s" % label)
    return values[0]


def _load_live_authority() -> dict[str, Any]:
    """Read and validate the authority directly from the live Cell journal."""
    root = _node_language_root()
    database = _database_path()
    with _import_root(root):
        universal = importlib.import_module("nodelang.universal_cell")
        core_values = importlib.import_module("nodelang.cell_core_values")
        protocols = importlib.import_module("nodelang.cell_protocols")

    store = universal.CellStore(database)
    try:
        snapshot = store.snapshot()
        base_roles = {
            name: "gm:role:%s" % name
            for name in (
                "owner", "value", "label", "member", "scope",
                "source", "target", "why",
            )
        }
        authority = core_values.project_core_values_authority(
            snapshot, base_roles, prefix=AUTHORITY_ROOT
        )
        core_values.validate_core_values_authority(snapshot, authority)

        root_members = protocols.read_relation(snapshot, AUTHORITY_ROOT, budget=256)
        lifecycle_root = _one_for_role(
            root_members, authority.roles["lifecycle"], "lifecycle"
        )
        lifecycle = snapshot.cells[lifecycle_root].atom.decode("utf-8").upper()
        if lifecycle not in {"WIP", "SHARED", "PUBLISHED", "PRODUCTION"}:
            raise ValueError("Core Values lifecycle is invalid")

        wire_members = protocols.read_relation(
            snapshot, AUTHORITY_WIRE_ROOT, budget=64
        )
        if _one_for_role(wire_members, base_roles["source"], "source") != AUTHORITY_ROOT:
            raise ValueError("Core Values Brain wire source drifted")
        if _one_for_role(wire_members, base_roles["target"], "target") != "gm:domain:brain":
            raise ValueError("Core Values Brain wire target drifted")
        wire_authorities = {
            member.participant_id
            for member in wire_members
            if member.role_id == authority.roles["authority"]
        }
        expected_wire_authorities = {
            authority.control_binding_roots[key]
            for key in ("truth", "ownership", "iterate")
        }
        if wire_authorities != expected_wire_authorities:
            raise ValueError("Core Values Brain wire authority bindings drifted")

        coverage = {
            key: authority.coverage[key].status for key in VALUE_KEYS
        }
        if set(coverage) != set(VALUE_KEYS):
            raise ValueError("Core Values coverage is incomplete")
        database_identity = hashlib.sha256(
            str(database).casefold().encode("utf-8")
        ).hexdigest()
        return {
            "authority_root": authority.root_id,
            "authority_wire_root": AUTHORITY_WIRE_ROOT,
            "source_digest": authority.source_digest,
            "translation_digest": authority.translation_digest,
            "lifecycle": lifecycle,
            "graph_revision": snapshot.revision,
            "revision_chain_digest": store.revision_chain_digest(),
            "coverage": coverage,
            "database_identity": database_identity,
        }
    finally:
        store.close()


def _persist_report(
    store: "BrainStore", report: CoreValuesAuthorityReport
) -> CoreValuesAuthorityReport:
    store.set_meta(AUTHORITY_META_KEY, report.model_dump_json())
    try:
        from . import compliance_report as cr

        cr.append_compliance_event(
            store,
            owner_user=report.owner_user,
            event={
                "event_type": "core_values_authority_audit",
                "source": "universal-cell-graph",
                "status": report.status,
                "authority_root": report.authority_root,
                "authority_wire_root": report.authority_wire_root,
                "lifecycle": report.lifecycle,
                "graph_revision": report.graph_revision,
                "revision_chain_digest": report.revision_chain_digest,
                "translation_digest": report.translation_digest,
                "coverage": report.coverage,
                "issues": report.issues,
            },
        )
    except Exception:
        pass
    return report


def audit(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    loader: Callable[[], dict[str, Any]] | None = None,
) -> CoreValuesAuthorityReport:
    """Verify the live graph and persist its bounded Brain projection."""
    try:
        payload = (loader or _load_live_authority)()
        report = CoreValuesAuthorityReport(
            owner_user=owner_user,
            status=GREEN,
            checked_at=_utc_now(),
            **payload,
        )
    except Exception as exc:
        report = CoreValuesAuthorityReport(
            owner_user=owner_user,
            status=RED,
            checked_at=_utc_now(),
            issues=["%s: %s" % (type(exc).__name__, exc)],
        )
    return _persist_report(store, report)


def get_report(
    store: "BrainStore", *, owner_user: str = "founder"
) -> Optional[CoreValuesAuthorityReport]:
    raw = store.get_meta(AUTHORITY_META_KEY)
    if not raw:
        return None
    try:
        report = CoreValuesAuthorityReport.model_validate_json(raw)
    except Exception:
        return None
    return report if report.owner_user == owner_user else None


def ensure_current(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    max_age_seconds: float = 30.0,
) -> CoreValuesAuthorityReport:
    """Return a recent audit, refreshing it from the live graph when stale."""
    report = get_report(store, owner_user=owner_user)
    if report is not None:
        try:
            checked = datetime.fromisoformat(report.checked_at)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            if 0 <= age <= max(0.0, float(max_age_seconds)):
                return report
        except (TypeError, ValueError):
            pass
    return audit(store, owner_user=owner_user)


def validate_work_context(
    report: CoreValuesAuthorityReport | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate a work leaf against the exact verified authority revision."""
    if report is None or report.status != GREEN:
        return {
            "allowed": False,
            "reason": "Core Values authority is not verified in Brain",
            "code": "core_values_authority_unverified",
        }
    value = context if isinstance(context, dict) else {}
    if value.get("authority_root") != report.authority_root:
        return {
            "allowed": False,
            "reason": "work leaf does not reference the verified Core Values root",
            "code": "core_values_trace_missing",
        }
    if value.get("translation_digest") != report.translation_digest:
        return {
            "allowed": False,
            "reason": "work leaf Core Values translation revision is stale",
            "code": "core_values_trace_stale",
        }
    applicable = tuple(dict.fromkeys(value.get("applicable_values") or ()))
    if not applicable or set(applicable) - set(VALUE_KEYS):
        return {
            "allowed": False,
            "reason": "work leaf has no valid Core Values applicability trace",
            "code": "core_values_trace_invalid",
        }
    risk = str(value.get("risk") or "").lower()
    if risk not in RISK_LEVELS:
        return {
            "allowed": False,
            "reason": "work leaf has no valid Core Values risk classification",
            "code": "core_values_risk_invalid",
        }
    required_evidence = tuple(value.get("required_evidence") or ())
    if HARD_GATE_VALUES.intersection(applicable) and not required_evidence:
        return {
            "allowed": False,
            "reason": "hard-gate Core Values require explicit evidence criteria",
            "code": "core_values_evidence_missing",
        }
    reviewer = str(value.get("reviewer") or "").strip()
    if risk in {"high", "critical"} and not reviewer:
        return {
            "allowed": False,
            "reason": "high-impact work requires an accountable reviewer",
            "code": "core_values_reviewer_missing",
        }
    return {
        "allowed": True,
        "reason": "",
        "code": "ok",
        "authority": report.model_dump(mode="json"),
        "applicable_values": list(applicable),
        "risk": risk,
        "required_evidence": list(required_evidence),
        "reviewer": reviewer,
    }


def register_core_values_authority_tools(
    mcp: Any, store: "BrainStore"
) -> Any:
    def _resolve_owner() -> str:
        getter = getattr(mcp, "_brain_resolve_owner", None)
        if callable(getter):
            value = getter()
            if value:
                return str(value)
        return "founder"

    @mcp.tool(
        name="brain.core_values_authority_audit",
        description=(
            "Verify the live universal Cell Core Values authority and its "
            "explicit Brain wire, then persist a bounded reference in Brain."
        ),
    )
    def brain_core_values_authority_audit(
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return audit(store, owner_user=owner).model_dump(mode="json")

    @mcp.tool(
        name="brain.core_values_authority_get",
        description=(
            "Return Brain's latest verified Core Values authority projection."
        ),
    )
    def brain_core_values_authority_get(
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        report = get_report(store, owner_user=owner)
        if report is None:
            return {"ok": False, "owner_user": owner, "status": "missing"}
        return {"ok": report.status == GREEN, **report.model_dump(mode="json")}

    return mcp


__all__ = [
    "AUTHORITY_META_KEY",
    "AUTHORITY_ROOT",
    "AUTHORITY_WIRE_ROOT",
    "AUTHORITY_SCHEMA",
    "VALUE_KEYS",
    "HARD_GATE_VALUES",
    "CoreValuesAuthorityReport",
    "audit",
    "get_report",
    "ensure_current",
    "validate_work_context",
    "register_core_values_authority_tools",
]
