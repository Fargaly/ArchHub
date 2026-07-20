"""Brain-owned hook coverage audit and repair.

The installer is the migration wiring plan for supported client hooks until the
Universal Cell graph owns the released capability policy. This module makes
that wiring visible to the Brain itself:

* audit actual client config/hook files against installer.COVERAGE_MATRIX;
* persist the latest report in brain_meta under hook_coverage_v1;
* repair by delegating to installer.install_all; and
* expose a small gate that write-capable work assignment can call before a
  runtime claims a leaf.

This is deliberately a control-plane record, not a replacement for vendor
hooks and not product authority. Hooks still run in each client; Brain records
whether those hooks are present enough for the client to be trusted with write
work while the capability policy is consumed into Cell protocols and courts.
"""
from __future__ import annotations

import json
import os
import hashlib
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

from . import installer

if TYPE_CHECKING:
    from .storage import BrainStore


COVERAGE_META_KEY = "hook_coverage_v1"
LEGACY_MIGRATION_ONLY = True
MIGRATION_CONTROL_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

GREEN = "green"
RED = "red"
NOT_DETECTED = "not_detected"
_OFF_VALUES = {"0", "off", "false", "no", "disabled"}
_MONITORS: dict[int, "HookCoverageMonitor"] = {}
_MONITORS_LOCK = threading.Lock()


class TouchpointCoverage(BaseModel):
    touchpoint: str
    state: str
    required: bool = True
    installed: bool = False
    evidence: list[str] = Field(default_factory=list)
    issue: str = ""


class ClientCoverage(BaseModel):
    client: str
    supported: bool = True
    detected: bool = False
    installed: bool = False
    status: str = NOT_DETECTED
    touchpoints: dict[str, TouchpointCoverage] = Field(default_factory=dict)
    config_paths: list[str] = Field(default_factory=list)
    config_hashes: dict[str, str] = Field(default_factory=dict)
    schema_valid: bool = False
    schema_evidence: list[str] = Field(default_factory=list)
    docs_url: Optional[str] = None
    issues: list[str] = Field(default_factory=list)
    last_audited_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HookCoverageReport(BaseModel):
    owner_user: str = "founder"
    status: str = GREEN
    clients: dict[str, ClientCoverage] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    last_audited_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    cell_first: bool = False
    cell_record_root: str = ""
    cell_record_source: str = ""
    audit_id: str = ""
    repair_id: str = ""
    repair_request_cell_record_root: str = ""
    repair_request_cell_record_source: str = ""
    repair_outcome_cell_record_root: str = ""
    repair_outcome_cell_record_source: str = ""


class HookCoverageMonitor:
    """Periodic hook coverage auditor for the daemon.

    `start()` runs one audit immediately so daemon startup records a compliance
    baseline, then a daemon thread keeps it fresh. The monitor is intentionally
    small and fail-soft: a bad audit increments error_count but never kills the
    Brain server.
    """

    def __init__(
        self,
        store: "BrainStore",
        *,
        owner_user: str = "founder",
        only: Optional[list[str]] = None,
        interval_s: float = 300.0,
        auto_repair: bool = False,
        cell_bridge: Any = None,
    ):
        self.store = store
        self.owner_user = owner_user or "founder"
        self.only = list(only) if only else None
        self.interval_s = max(0.01, float(interval_s))
        self.auto_repair = auto_repair
        self.cell_bridge = cell_bridge
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._cycle_count = 0
        self._error_count = 0
        self._repair_count = 0
        self._last_report: Optional[dict[str, Any]] = None
        self._last_repair: Optional[dict[str, Any]] = None
        self._last_error = ""
        self._last_tick_at: Optional[str] = None

    def start(self) -> None:
        if self.is_alive():
            return
        self._stop.clear()
        self.tick()
        self._thread = threading.Thread(
            target=self._loop,
            name="brain-hook-coverage-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def tick(self) -> dict[str, Any]:
        with self._lock:
            try:
                audit_result = audit_cell_first(
                    self.store,
                    only=self.only,
                    owner_user=self.owner_user,
                    cell_bridge=self.cell_bridge,
                )
                if not audit_result.get("ok"):
                    raise RuntimeError(
                        str(audit_result.get("error") or "Cell-first audit failed")
                    )
                report = get_report(self.store, owner_user=self.owner_user)
                if report is None:
                    raise RuntimeError("Cell-first audit did not persist receipt")
                if self.auto_repair:
                    red_detected = [
                        name for name, coverage in report.clients.items()
                        if coverage.detected and coverage.status == RED
                    ]
                    if red_detected:
                        repair_result = repair_cell_first(
                            self.store,
                            only=red_detected,
                            owner_user=self.owner_user,
                            dry_run=False,
                            cell_bridge=self.cell_bridge,
                        )
                        if not repair_result.get("ok"):
                            raise RuntimeError(
                                str(
                                    repair_result.get("error")
                                    or "Cell-first repair failed"
                                )
                            )
                        self._repair_count += 1
                        self._last_repair = repair_result
                        report = get_report(
                            self.store, owner_user=self.owner_user
                        ) or report
                try:
                    self._last_report = json.loads(
                        self.store.get_meta(COVERAGE_META_KEY) or "{}"
                    )
                except Exception:
                    self._last_report = report.model_dump(mode="json")
                self._last_error = ""
                ok = True
            except Exception as ex:  # pragma: no cover - defensive
                self._error_count += 1
                self._last_error = f"{type(ex).__name__}: {ex}"
                ok = False
            self._cycle_count += 1
            self._last_tick_at = datetime.now(timezone.utc).isoformat()
            return self.status() | {"ok": ok}

    def _loop(self) -> None:
        while not self._stop.is_set():
            slept = 0.0
            while slept < self.interval_s and not self._stop.is_set():
                step = min(0.25, self.interval_s - slept)
                time.sleep(step)
                slept += step
            if self._stop.is_set():
                break
            self.tick()

    def status(self) -> dict[str, Any]:
        return {
            "alive": self.is_alive(),
            "owner_user": self.owner_user,
            "only": self.only,
            "interval_s": self.interval_s,
            "auto_repair": self.auto_repair,
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "repair_count": self._repair_count,
            "last_error": self._last_error,
            "last_tick_at": self._last_tick_at,
            "last_report": self._last_report,
            "last_repair": self._last_repair,
        }


def _read_json(path: Path) -> tuple[Optional[dict[str, Any]], str]:
    if not path.exists():
        return None, f"missing {path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        return None, f"{path.name} is not valid JSON: {type(ex).__name__}: {ex}"
    if not isinstance(data, dict):
        return None, f"{path.name} is not a JSON object"
    return data, ""


def _tokens(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for key in ("command", "tool", "name", "statusMessage"):
            val = obj.get(key)
            if val is not None:
                out.append(str(val))
        for val in obj.values():
            out.extend(_tokens(val))
    elif isinstance(obj, list):
        for val in obj:
            out.extend(_tokens(val))
    elif isinstance(obj, str):
        out.append(obj)
    return out


def _has_all_markers(tokens: list[str], markers: tuple[str, ...]) -> bool:
    lowered = [t.lower() for t in tokens]
    wanted = [m.lower() for m in markers]
    return any(all(m in token for m in wanted) for token in lowered)


def _json_event_has(
    path: Path,
    event: str,
    *markers: str,
) -> tuple[bool, str]:
    data, err = _read_json(path)
    if data is None:
        return False, f"{path.name}: {err}"
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False, f"{path.name}: missing hooks object"
    if event not in hooks:
        return False, f"{path.name}: missing hooks.{event}"
    event_tokens = _tokens(hooks[event])
    if not _has_all_markers(event_tokens, tuple(markers)):
        marker_text = " + ".join(markers)
        return False, f"{path.name}: hooks.{event} missing {marker_text}"
    return True, f"{path}:{event}"


def _json_has_brain_mcp(path: Path) -> tuple[bool, str]:
    data, err = _read_json(path)
    if data is None:
        return False, f"{path.name}: {err}"
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and "brain" in servers:
        return True, f"{path}:mcpServers.brain"
    return False, f"{path.name}: missing mcpServers.brain"


def _grouped_hook_schema(
    path: Path,
    *,
    client: str,
    command_only: bool,
) -> tuple[bool, str]:
    data, err = _read_json(path)
    if data is None:
        return False, f"{path.name}: {err}"
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False, f"{path.name}: missing hooks object"

    issues: list[str] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            issues.append(f"hooks.{event} must be an array")
            continue
        for group_index, group in enumerate(groups):
            where = f"hooks.{event}[{group_index}]"
            if not isinstance(group, dict):
                issues.append(f"{where} must be an object")
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                issues.append(f"{where}.hooks must be an array")
                continue
            if not handlers:
                issues.append(f"{where}.hooks must not be empty")
            for handler_index, handler in enumerate(handlers):
                handler_where = f"{where}.hooks[{handler_index}]"
                if not isinstance(handler, dict):
                    issues.append(f"{handler_where} must be an object")
                    continue
                kind = handler.get("type")
                if not isinstance(kind, str) or not kind:
                    issues.append(f"{handler_where}.type is required")
                    continue
                if command_only and kind != "command":
                    issues.append(f"{handler_where}.type must be command")
                if kind == "command" and not isinstance(
                    handler.get("command"), str
                ):
                    issues.append(f"{handler_where}.command is required")
                if client == "claude-code" and kind == "mcp_tool":
                    for field in ("server", "tool"):
                        if not isinstance(handler.get(field), str):
                            issues.append(f"{handler_where}.{field} is required")
                    if not isinstance(handler.get("input"), dict):
                        issues.append(f"{handler_where}.input must be an object")
                    if "arguments" in handler:
                        issues.append(
                            f"{handler_where}.arguments is obsolete; use input"
                        )

    if client == "gemini-cli":
        hooks_config = data.get("hooksConfig")
        if isinstance(hooks_config, dict) and hooks_config.get("enabled") is False:
            issues.append("hooksConfig.enabled is false")

    if issues:
        return False, f"{path.name}: " + "; ".join(issues)
    return True, f"{path}: grouped hook schema valid for {client}"


def _cursor_hook_schema(path: Path) -> tuple[bool, str]:
    data, err = _read_json(path)
    if data is None:
        return False, f"{path.name}: {err}"
    if data.get("version") != 1:
        return False, f"{path.name}: version must be 1"
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False, f"{path.name}: missing hooks object"
    issues: list[str] = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            issues.append(f"hooks.{event} must be an array")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(
                entry.get("command"), str
            ):
                issues.append(f"hooks.{event}[{index}].command is required")
    if issues:
        return False, f"{path.name}: " + "; ".join(issues)
    return True, f"{path}: Cursor version 1 hook schema valid"


def _codex_activation_schema(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing {path.name}"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        return False, f"{path.name}: invalid TOML: {type(ex).__name__}: {ex}"
    features = data.get("features")
    if isinstance(features, dict):
        if features.get("hooks") is False or features.get("codex_hooks") is False:
            return False, f"{path.name}: hooks feature is explicitly disabled"
    return True, f"{path}: Codex hook feature not disabled"


def _schema_checks_for(client: str) -> list[tuple[bool, str]]:
    if client == "claude-code":
        return [_grouped_hook_schema(
            installer._claude_code_path(),
            client=client,
            command_only=False,
        )]
    if client == "cursor":
        return [_cursor_hook_schema(installer._cursor_hooks_path())]
    if client == "codex":
        return [
            _grouped_hook_schema(
                installer._codex_hooks_path(),
                client=client,
                command_only=True,
            ),
            _codex_activation_schema(installer._codex_path()),
        ]
    if client == "gemini-cli":
        return [_grouped_hook_schema(
            installer._gemini_path(),
            client=client,
            command_only=True,
        )]
    return [(False, f"no schema check for {client}")]


def _config_hashes(paths: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        hashes[str(path)] = digest
    return hashes


def _text_has(path: Path, *markers: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing {path.name}"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as ex:
        return False, f"{path.name}: {type(ex).__name__}: {ex}"
    lower = text.lower()
    if all(marker.lower() in lower for marker in markers):
        return True, f"{path}:{' + '.join(markers)}"
    return False, f"{path.name}: missing {' + '.join(markers)}"


def _client_paths(client: str) -> list[Path]:
    if client == "claude-code":
        return [installer._claude_code_path()]
    if client == "cursor":
        return [installer._cursor_path(), installer._cursor_hooks_path()]
    if client == "codex":
        return [installer._codex_path(), installer._codex_hooks_path()]
    if client == "gemini-cli":
        return [installer._gemini_path()]
    return []


def _checks_for(client: str) -> tuple[list[tuple[bool, str]], dict[str, tuple[bool, str]]]:
    if client == "claude-code":
        path = installer._claude_code_path()
        return (
            [_json_has_brain_mcp(path)],
            {
                "scope_gate": _json_event_has(
                    path, "PreToolUse", "agent_scope_gate.py", "--vendor claude"
                ),
                "pre_prompt_inject": _json_event_has(path, "UserPromptSubmit", "brain.hook_context"),
                "workshop_authority": _json_event_has(path, "UserPromptSubmit", "brain.hook_context"),
                "drive_inject": _json_event_has(path, "UserPromptSubmit", "brain.work_assigned_block"),
                "post_tool_write": _json_event_has(path, "PostToolUse", "brain.observe"),
                "stop_gate": _json_event_has(
                    path, "Stop", "brainwrap", "stop", "claude-code"
                ),
            },
        )
    if client == "cursor":
        mcp_path = installer._cursor_path()
        hooks_path = installer._cursor_hooks_path()
        return (
            [_json_has_brain_mcp(mcp_path)],
            {
                "scope_gate": _json_event_has(hooks_path, "preToolUse", "agent_scope_gate.py"),
                "pre_prompt_inject": _json_event_has(hooks_path, "beforeSubmitPrompt", "brainwrap", "context"),
                "workshop_authority": _json_event_has(hooks_path, "beforeSubmitPrompt", "brainwrap", "context"),
                "drive_inject": _json_event_has(hooks_path, "beforeSubmitPrompt", "brainwrap", "context"),
                "post_tool_write": _json_event_has(hooks_path, "stop", "brainwrap", "stop"),
                "stop_gate": _json_event_has(hooks_path, "stop", "brainwrap", "stop"),
            },
        )
    if client == "codex":
        cfg_path = installer._codex_path()
        hooks_path = installer._codex_hooks_path()
        return (
            [_text_has(cfg_path, "mcp_servers.brain", "personal-brain-mcp")],
            {
                "scope_gate": _json_event_has(
                    hooks_path, "PreToolUse", "agent_scope_gate.py", "--vendor codex"
                ),
                "pre_prompt_inject": _json_event_has(hooks_path, "UserPromptSubmit", "brainwrap", "context"),
                "workshop_authority": _json_event_has(hooks_path, "UserPromptSubmit", "brainwrap", "context"),
                "drive_inject": _json_event_has(hooks_path, "UserPromptSubmit", "brainwrap", "context"),
                "post_tool_write": _json_event_has(hooks_path, "Stop", "brainwrap", "stop"),
                "stop_gate": _json_event_has(hooks_path, "Stop", "brainwrap", "stop"),
            },
        )
    if client == "gemini-cli":
        path = installer._gemini_path()
        return (
            [_json_has_brain_mcp(path)],
            {
                "scope_gate": _json_event_has(path, "BeforeTool", "agent_scope_gate.py"),
                "pre_prompt_inject": _json_event_has(path, "BeforeAgent", "brainwrap", "context"),
                "workshop_authority": _json_event_has(path, "BeforeAgent", "brainwrap", "context"),
                "drive_inject": _json_event_has(path, "BeforeAgent", "brainwrap", "context"),
                "post_tool_write": _json_event_has(path, "AfterAgent", "brainwrap", "stop"),
                "stop_gate": _json_event_has(path, "AfterAgent", "brainwrap", "stop"),
            },
        )
    return ([], {})


def _audit_client(client: str, now: datetime) -> ClientCoverage:
    plan = installer.ALL_PLANS.get(client)
    matrix = installer.coverage_matrix([client]).get(client)
    if plan is None or matrix is None:
        return ClientCoverage(
            client=client,
            supported=False,
            detected=False,
            installed=False,
            status=RED,
            issues=[f"unsupported client: {client}"],
            last_audited_at=now,
        )

    detected = bool(plan.detect())
    client_paths = _client_paths(client)
    config_paths = [str(p) for p in client_paths]
    mcp_checks, touchpoint_checks = _checks_for(client)
    issues: list[str] = []

    schema_checks = _schema_checks_for(client)
    schema_evidence = [note for ok, note in schema_checks if ok]
    schema_valid = all(ok for ok, _ in schema_checks)
    if not schema_valid:
        issues.extend(note for ok, note in schema_checks if not ok)

    mcp_ok = True
    for ok, note in mcp_checks:
        if not ok:
            mcp_ok = False
            issues.append(note)

    touchpoints: dict[str, TouchpointCoverage] = {}
    for tp in installer.TOUCHPOINTS:
        ok, note = touchpoint_checks.get(tp, (False, f"no audit check for {tp}"))
        if not ok:
            issues.append(f"{tp}: {note}")
        touchpoints[tp] = TouchpointCoverage(
            touchpoint=tp,
            state=matrix[tp],
            required=True,
            installed=ok,
            evidence=[note] if ok else [],
            issue="" if ok else note,
        )

    installed = (
        schema_valid
        and mcp_ok
        and all(t.installed for t in touchpoints.values())
    )
    if not detected:
        status = NOT_DETECTED
    else:
        status = GREEN if installed else RED
    return ClientCoverage(
        client=client,
        supported=True,
        detected=detected,
        installed=installed,
        status=status,
        touchpoints=touchpoints,
        config_paths=config_paths,
        config_hashes=_config_hashes(client_paths),
        schema_valid=schema_valid,
        schema_evidence=schema_evidence,
        docs_url=installer.HOOK_DOC_URLS.get(client),
        issues=issues,
        last_audited_at=now,
    )


def _persist(store: "BrainStore", report: HookCoverageReport) -> None:
    payload = report.model_dump(mode="json")
    store.set_meta(COVERAGE_META_KEY, json.dumps(payload, sort_keys=True))


def _persist_receipt(
    store: "BrainStore",
    report: HookCoverageReport,
    *,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    payload = report.model_dump(mode="json")
    payload.update(_jsonable(receipt))
    store.set_meta(COVERAGE_META_KEY, json.dumps(payload, sort_keys=True))
    return payload


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except Exception:
        return {"unserializable": str(value)}


def _client_statuses(report: HookCoverageReport) -> dict[str, str]:
    return {
        name: coverage.status
        for name, coverage in sorted(report.clients.items())
    }


def _append_history_event(
    store: "BrainStore",
    *,
    owner_user: str,
    event: dict[str, Any],
    cell_bridge: Any = None,
) -> None:
    try:
        from . import compliance_report as cr

        cr.append_compliance_event(
            store,
            owner_user=owner_user,
            event=event,
            cell_bridge=cell_bridge,
        )
    except Exception:
        pass


def _build_report(
    *,
    only: Optional[list[str]] = None,
    owner_user: str = "founder",
) -> HookCoverageReport:
    names = only or list(installer.ALL_PLANS.keys())
    now = datetime.now(timezone.utc)
    clients = {name: _audit_client(name, now) for name in names}
    issues = [
        f"{client}: {issue}"
        for client, coverage in clients.items()
        if coverage.status == RED
        for issue in coverage.issues
    ]
    status = RED if any(c.status == RED for c in clients.values()) else GREEN
    report = HookCoverageReport(
        owner_user=owner_user,
        status=status,
        clients=clients,
        issues=issues,
        last_audited_at=now,
    )
    return report


def audit(
    store: "BrainStore",
    *,
    only: Optional[list[str]] = None,
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> HookCoverageReport:
    report = _build_report(only=only, owner_user=owner_user)
    _persist(store, report)
    _append_history_event(
        store,
        owner_user=owner_user,
        cell_bridge=cell_bridge,
        event={
            "event_type": "hook_coverage_audit",
            "source": "hook_coverage",
            "status": report.status,
            "clients": _client_statuses(report),
            "issue_count": len(report.issues),
            "only": list(only or []),
        },
    )
    return report


def audit_cell_first(
    store: "BrainStore",
    *,
    only: Optional[list[str]] = None,
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> dict[str, Any]:
    report = _build_report(only=only, owner_user=owner_user)
    report_payload = report.model_dump(mode="json")
    audit_id = hashlib.sha256(
        json.dumps(
            {
                "owner_user": owner_user,
                "only": list(only or []),
                "report": report_payload,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]
    source = f"brain-control:hook-coverage-audit:{audit_id}"
    try:
        runtime = cell_bridge
        if runtime is None:
            from .universal_runtime import UniversalRuntimeBridge

            runtime = UniversalRuntimeBridge()
        created = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": source,
                "scope": "founder/brain-control/hook-coverage",
                "claims": json.dumps(
                    {
                        "status": report.status,
                        "clients": _client_statuses(report),
                        "issue_count": len(report.issues),
                        "only": list(only or []),
                    },
                    sort_keys=True,
                ),
                "provenance": "personal_brain.hook_coverage:audit_cell_first",
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

    receipt = {
        "cell_first": True,
        "cell_record_root": str(created["created_root"]),
        "cell_record_source": source,
        "audit_id": audit_id,
    }
    persisted = _persist_receipt(store, report, receipt=receipt)
    result: dict[str, Any] = {
        "ok": True,
        "cell_first": True,
        "brain_written": True,
        "report": persisted,
        "cell_record": created,
    }
    try:
        from . import compliance_report as cr

        compliance = cr.append_compliance_event_cell_first(
            store,
            owner_user=owner_user,
            cell_bridge=runtime,
            event={
                "event_type": "hook_coverage_audit",
                "source": "hook_coverage_cell_first",
                "status": report.status,
                "clients": _client_statuses(report),
                "issue_count": len(report.issues),
                "only": list(only or []),
                "hook_coverage_cell_record_root": receipt["cell_record_root"],
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


def get_report(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
) -> Optional[HookCoverageReport]:
    raw = store.get_meta(COVERAGE_META_KEY)
    if not raw:
        return None
    try:
        report = HookCoverageReport.model_validate(json.loads(raw))
    except Exception:
        return None
    if owner_user and report.owner_user != owner_user:
        return None
    return report


def repair(
    store: "BrainStore",
    *,
    only: Optional[list[str]] = None,
    owner_user: str = "founder",
    dry_run: bool = False,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    before = audit(
        store,
        only=only,
        owner_user=owner_user,
        cell_bridge=cell_bridge,
    )
    install_results = installer.install_all(only=only, dry_run=dry_run)
    after = audit(
        store,
        only=only,
        owner_user=owner_user,
        cell_bridge=cell_bridge,
    )
    result = {
        "ok": True,
        "dry_run": dry_run,
        "install_results": install_results,
        "before": before.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
    }
    _append_history_event(
        store,
        owner_user=owner_user,
        cell_bridge=cell_bridge,
        event={
            "event_type": "hook_coverage_repair",
            "source": "hook_coverage",
            "dry_run": dry_run,
            "before_status": before.status,
            "after_status": after.status,
            "clients": _client_statuses(after),
            "only": list(only or []),
        },
    )
    return result


def repair_cell_first(
    store: "BrainStore",
    *,
    only: Optional[list[str]] = None,
    owner_user: str = "founder",
    dry_run: bool = False,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    before = _build_report(only=only, owner_user=owner_user)
    requested_at = datetime.now(timezone.utc).isoformat()
    repair_id = hashlib.sha256(
        json.dumps(
            {
                "owner_user": owner_user,
                "only": list(only or []),
                "dry_run": dry_run,
                "requested_at": requested_at,
                "before": before.model_dump(mode="json"),
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]
    request_source = f"brain-control:hook-coverage-repair-request:{repair_id}"
    try:
        runtime = cell_bridge
        if runtime is None:
            from .universal_runtime import UniversalRuntimeBridge

            runtime = UniversalRuntimeBridge()
        request_record = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": request_source,
                "scope": "founder/brain-control/hook-coverage/repair",
                "claims": json.dumps(
                    {
                        "repair_id": repair_id,
                        "only": list(only or []),
                        "dry_run": dry_run,
                        "requested_at": requested_at,
                        "before_status": before.status,
                        "before_clients": _client_statuses(before),
                    },
                    sort_keys=True,
                ),
                "provenance": "personal_brain.hook_coverage:repair_request",
            },
            idempotency_field="source",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    install_results = installer.install_all(only=only, dry_run=dry_run)
    after = _build_report(only=only, owner_user=owner_user)
    outcome_source = f"brain-control:hook-coverage-repair-outcome:{repair_id}"
    try:
        outcome_record = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": outcome_source,
                "scope": "founder/brain-control/hook-coverage/repair",
                "claims": json.dumps(
                    {
                        "repair_id": repair_id,
                        "request_root": str(request_record["created_root"]),
                        "dry_run": dry_run,
                        "before_status": before.status,
                        "after_status": after.status,
                        "after_clients": _client_statuses(after),
                        "install_results": _jsonable(install_results),
                    },
                    sort_keys=True,
                ),
                "provenance": "personal_brain.hook_coverage:repair_outcome",
            },
            idempotency_field="source",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": True,
            "error": f"{type(exc).__name__}: {exc}",
            "request_cell_record": request_record,
            "install_results": _jsonable(install_results),
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
        }

    receipt = {
        "cell_first": True,
        "cell_record_root": str(outcome_record["created_root"]),
        "cell_record_source": outcome_source,
        "repair_id": repair_id,
        "repair_request_cell_record_root": str(request_record["created_root"]),
        "repair_request_cell_record_source": request_source,
        "repair_outcome_cell_record_root": str(outcome_record["created_root"]),
        "repair_outcome_cell_record_source": outcome_source,
    }
    persisted = _persist_receipt(store, after, receipt=receipt)
    result: dict[str, Any] = {
        "ok": True,
        "cell_first": True,
        "brain_written": True,
        "side_effect_executed": True,
        "dry_run": dry_run,
        "install_results": _jsonable(install_results),
        "before": before.model_dump(mode="json"),
        "after": persisted,
        "request_cell_record": request_record,
        "outcome_cell_record": outcome_record,
    }
    try:
        from . import compliance_report as cr

        compliance = cr.append_compliance_event_cell_first(
            store,
            owner_user=owner_user,
            cell_bridge=runtime,
            event={
                "event_type": "hook_coverage_repair",
                "source": "hook_coverage_repair_cell_first",
                "dry_run": dry_run,
                "before_status": before.status,
                "after_status": after.status,
                "clients": _client_statuses(after),
                "only": list(only or []),
                "repair_request_cell_record_root": receipt[
                    "repair_request_cell_record_root"
                ],
                "repair_outcome_cell_record_root": receipt[
                    "repair_outcome_cell_record_root"
                ],
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


def hook_coverage_monitor_enabled() -> bool:
    raw = os.environ.get("BRAIN_HOOK_COVERAGE_MONITOR", "1").strip().lower()
    return raw not in _OFF_VALUES


def _monitor_interval_from_env() -> float:
    raw = os.environ.get("BRAIN_HOOK_COVERAGE_INTERVAL_SECONDS", "").strip()
    if not raw:
        return 300.0
    try:
        return max(0.01, float(raw))
    except ValueError:
        return 300.0


def _monitor_only_from_env() -> Optional[list[str]]:
    raw = os.environ.get("BRAIN_HOOK_COVERAGE_ONLY", "").strip()
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def hook_coverage_auto_repair_enabled() -> bool:
    # A running client may hot-reload its settings file. Background repair can
    # therefore interrupt active work even when the rewritten JSON is valid.
    # Keep the monitor observational by default; repair is an explicit action.
    raw = os.environ.get("BRAIN_HOOK_COVERAGE_AUTO_REPAIR", "0").strip().lower()
    return raw not in _OFF_VALUES


def start_hook_coverage_monitor(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    only: Optional[list[str]] = None,
    interval_s: Optional[float] = None,
    auto_repair: bool = False,
    cell_bridge: Any = None,
) -> Optional[HookCoverageMonitor]:
    if not hook_coverage_monitor_enabled():
        return None
    key = id(store)
    with _MONITORS_LOCK:
        existing = _MONITORS.get(key)
        if existing is not None and existing.is_alive():
            return existing
        monitor = HookCoverageMonitor(
            store,
            owner_user=owner_user,
            only=only if only is not None else _monitor_only_from_env(),
            interval_s=(
                interval_s
                if interval_s is not None
                else _monitor_interval_from_env()
            ),
            auto_repair=auto_repair,
            cell_bridge=cell_bridge,
        )
        _MONITORS[key] = monitor
    monitor.start()
    return monitor


def runtime_client(runtime: str) -> str:
    key = (runtime or "").strip().lower().replace("_", "-")
    aliases = {
        "claude": "claude-code",
        "claude-code": "claude-code",
        "cursor": "cursor",
        "codex": "codex",
        "gemini": "gemini-cli",
        "gemini-cli": "gemini-cli",
    }
    return aliases.get(key, key)


def observe_runtime_compliance(runtime: str) -> dict[str, Any]:
    """Read physical client wiring without creating a Brain authority record.

    The Universal Cell runtime admits this read-only scanner as a physical
    court adapter.  The signed court attestation and its Cell compliance
    relation are the decision evidence; this legacy module never grants Work.
    """
    client = runtime_client(runtime)
    now = datetime.now(timezone.utc)
    coverage = _audit_client(client, now)
    mcp_checks, _touchpoint_checks = _checks_for(client)
    touchpoints = coverage.touchpoints
    required_hooks = bool(touchpoints) and all(
        touchpoint.installed for touchpoint in touchpoints.values()
    )

    def installed(name: str) -> bool:
        touchpoint = touchpoints.get(name)
        return bool(touchpoint is not None and touchpoint.installed)

    checks = {
        "runtime-detected": bool(coverage.supported and coverage.detected),
        "required-hooks": required_hooks,
        "schema-valid": bool(coverage.schema_valid),
        "brain-connected": bool(mcp_checks and all(ok for ok, _ in mcp_checks)),
        "scope-gate": installed("scope_gate"),
        "workshop-authority": installed("workshop_authority"),
    }
    return {
        "client": client,
        "status": GREEN if all(checks.values()) else RED,
        "checks": checks,
        "issue_count": len(coverage.issues),
    }


def _has_cell_first_receipt(report: HookCoverageReport) -> bool:
    return bool(
        report.cell_first is True
        and (
            report.cell_record_root
            or report.repair_outcome_cell_record_root
            or report.repair_request_cell_record_root
        )
    )


def runtime_write_gate(
    store: "BrainStore",
    *,
    runtime: str,
    owner_user: str = "founder",
    write: bool = False,
) -> dict[str, Any]:
    client = runtime_client(runtime)
    if not write:
        return {"allowed": True, "client": client, "reason": ""}
    report = get_report(store, owner_user=owner_user)
    if report is None:
        return {
            "allowed": False,
            "client": client,
            "status": RED,
            "reason": f"hook coverage has not been audited for {client}",
            "action_tool": "brain.hook_coverage_audit_cell_first",
        }
    coverage = report.clients.get(client)
    if coverage is None:
        return {
            "allowed": False,
            "client": client,
            "status": RED,
            "reason": f"hook coverage has no report for {client}",
            "action_tool": "brain.hook_coverage_audit_cell_first",
        }
    workshop = coverage.touchpoints.get("workshop_authority")
    if workshop is None or not workshop.installed:
        reason = (
            "workshop authority coverage missing"
            if workshop is None
            else workshop.issue or "workshop authority hook is not installed"
        )
        return {
            "allowed": False,
            "client": client,
            "status": RED,
            "coverage": coverage.model_dump(mode="json"),
            "reason": f"hook coverage red for {client}: {reason}",
            "action_tool": "brain.hook_coverage_repair_cell_first",
        }
    if coverage.status == GREEN:
        if not _has_cell_first_receipt(report):
            return {
                "allowed": False,
                "client": client,
                "status": RED,
                "coverage": coverage.model_dump(mode="json"),
                "reason": (
                    f"hook coverage green for {client} is legacy-only; "
                    "Cell-first receipt is required before write work"
                ),
                "action_tool": "brain.hook_coverage_audit_cell_first",
            }
        return {
            "allowed": True,
            "client": client,
            "status": GREEN,
            "coverage": coverage.model_dump(mode="json"),
            "cell_record_root": report.cell_record_root,
            "reason": "",
        }
    issue = coverage.issues[0] if coverage.issues else coverage.status
    return {
        "allowed": False,
        "client": client,
        "status": coverage.status,
        "coverage": coverage.model_dump(mode="json"),
        "reason": f"hook coverage {coverage.status} for {client}: {issue}",
        "action_tool": "brain.hook_coverage_repair_cell_first",
    }


def format_gate_block(gate: dict[str, Any]) -> str:
    reason = str(gate.get("reason") or "hook coverage is not green")
    client = str(gate.get("client") or "unknown")
    action_tool = str(
        gate.get("action_tool") or "brain.hook_coverage_repair_cell_first"
    )
    lines = [
        '<hook_coverage status="red">',
        f"Client: {client}",
        f"Decision: refuse write-capable assigned work before claim.",
        f"Reason: {reason}",
        f"Action: run {action_tool}.",
        "</hook_coverage>",
    ]
    return "\n".join(lines)


def register_hook_coverage_tools(mcp: "Any", store: "BrainStore") -> "Any":
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
        return {
            "ok": False,
            "owner_user": owner,
            "universal": True,
            "migration_only": True,
            "deprecated": True,
            "code": "legacy_governance_route_retired",
            "error": (
                "Legacy hook coverage %s is retired. Use %s so the request "
                "and outcome are committed to the Universal Cell graph."
            ) % (operation, replacement),
            "replacement": replacement,
            "cell_first_alternative": replacement,
            "brain_written": False,
            "side_effect_executed": False,
        }

    @mcp.tool(
        name="brain.hook_coverage_audit",
        description=(
            "RETIRED compatibility route. It never audits or writes the Brain "
            "receipt; use brain.hook_coverage_audit_cell_first."
        ),
    )
    def brain_hook_coverage_audit(
        only: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_route(
            owner,
            "audit",
            "brain.hook_coverage_audit_cell_first",
        )

    @mcp.tool(
        name="brain.hook_coverage_audit_cell_first",
        description=(
            "Create a Universal Cell hook-coverage audit record before "
            "persisting the Brain hook_coverage_v1 receipt."
        ),
    )
    def brain_hook_coverage_audit_cell_first(
        only: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return audit_cell_first(store, only=only, owner_user=owner)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.hook_coverage_get",
        description="Return the latest persisted hook_coverage_v1 report.",
    )
    def brain_hook_coverage_get(
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        report = get_report(store, owner_user=owner)
        if report is None:
            return {"ok": False, "error": "no hook coverage report"}
        return {"ok": True, "report": report.model_dump(mode="json")}

    @mcp.tool(
        name="brain.hook_coverage_repair",
        description=(
            "RETIRED compatibility route. It never repairs client files or "
            "writes the Brain receipt; use "
            "brain.hook_coverage_repair_cell_first."
        ),
    )
    def brain_hook_coverage_repair(
        only: Optional[list[str]] = None,
        dry_run: bool = False,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_route(
            owner,
            "repair",
            "brain.hook_coverage_repair_cell_first",
        )

    @mcp.tool(
        name="brain.hook_coverage_repair_cell_first",
        description=(
            "Create Universal Cell repair request/outcome records around "
            "installer hook repair before writing the Brain receipt."
        ),
    )
    def brain_hook_coverage_repair_cell_first(
        only: Optional[list[str]] = None,
        dry_run: bool = False,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return repair_cell_first(
                store,
                only=only,
                owner_user=owner,
                dry_run=dry_run,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    return mcp
