"""Live governance probes for the node-language floor.

These functions are the "meat" behind floor {'op':'probe','kind':'governance'}.
They intentionally return bounded summaries, not raw process command lines or
hook config bodies, so pulling a governance node does not leak secrets into the
graph value/history/UI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


NODE_LANG_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MCP_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
WATCHDOG_TASK_NAME = "ArchHub-Governed-Agent-Watchdog"


def _hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _result(check: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    out = {
        "ok": bool(ok),
        "kind": "governance",
        "check": check,
        "detail": str(detail),
    }
    out.update(extra)
    return out


def _parse_mcp_body(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except Exception:
            continue
        res = obj.get("result") or {}
        sc = res.get("structuredContent")
        if isinstance(sc, dict):
            return sc
        for item in res.get("content") or []:
            if item.get("type") == "text":
                try:
                    parsed = json.loads(item.get("text") or "{}")
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict):
                    return parsed
    try:
        obj = json.loads(text)
    except Exception:
        return {}
    res = obj.get("result") if isinstance(obj, dict) else None
    if isinstance(res, dict):
        return res.get("structuredContent") or res
    return obj if isinstance(obj, dict) else {}


def _mcp_tool(name: str, args: dict[str, Any], *, url: str, timeout: float) -> dict[str, Any]:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _parse_mcp_body(resp.read())


def _brain_report(spec: dict[str, Any]) -> dict[str, Any]:
    url = str(spec.get("mcp_url") or DEFAULT_MCP_URL)
    owner = spec.get("owner_user") or "founder"
    args = {"owner_user": owner} if owner else {}
    return _mcp_tool(
        str(spec.get("tool") or "brain.compliance_report"),
        args,
        url=url,
        timeout=float(spec.get("timeout", 3.0)),
    )


def _probe_brain_health(check: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Probe the daemon's actual MCP health operation.

    ``brain.compliance_report`` is useful governance evidence but is not a
    liveness contract: it can fail while the daemon is serving normally.  The
    Brain HTTP transport deliberately exposes only ``POST /mcp``; it has no
    ``GET /healthz`` endpoint.  Use the same bounded operation the supervisor
    uses so this projection cannot report a healthy Brain as down.
    """
    url = str(spec.get("mcp_url") or DEFAULT_MCP_URL)
    try:
        health = _mcp_tool(
            str(spec.get("tool") or "brain.health"),
            {},
            url=url,
            timeout=float(spec.get("timeout", 3.0)),
        )
    except Exception as ex:
        return _result(check, False, "brain health unavailable: %s: %s" % (type(ex).__name__, ex))
    return _result(
        check,
        bool(health.get("ok", True)),
        "brain.health reachable",
        source="brain.health",
        owner_user=health.get("owner_user", ""),
    )


def _hook_clients(report: dict[str, Any]) -> dict[str, str]:
    hook = report.get("hook_coverage")
    if not isinstance(hook, dict):
        return {}
    clients = hook.get("clients")
    if not isinstance(clients, dict):
        return {}
    return {
        str(name): str((coverage or {}).get("status") or "unknown")
        for name, coverage in sorted(clients.items())
        if isinstance(coverage, dict)
    }


def _probe_hook_coverage(check: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        report = _brain_report(spec)
    except Exception as ex:
        return _result(check, False, "hook coverage unreadable: %s: %s" % (type(ex).__name__, ex))
    hook = report.get("hook_coverage") if isinstance(report, dict) else {}
    status = str((hook or {}).get("status") or "missing").lower()
    clients = _hook_clients(report)
    return _result(
        check,
        status == "green",
        "hook coverage status: %s" % status,
        status=status,
        clients=clients,
    )


def _read_status_report(spec: dict[str, Any]) -> dict[str, Any]:
    status_json = spec.get("status_json")
    if status_json:
        with open(status_json, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("status_json is not an object")
        return data

    status_script = spec.get("status_script")
    if not status_script:
        raise ValueError("process-ancestry probe requires an explicit node-owned status source")
    script = Path(status_script)
    cmd = [sys.executable, str(script), "status", "--json"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=float(spec.get("timeout", 30.0)),
        **_hidden_subprocess_kwargs(),
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "status command failed").strip())
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise ValueError("status command did not return an object")
    return data


def _probe_process_ancestry(check: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        report = _read_status_report(spec)
    except Exception as ex:
        return _result(check, False, "session status unreadable: %s: %s" % (type(ex).__name__, ex))
    total = int(report.get("current_sessions_total") or 0)
    governed = int(report.get("current_sessions_governed") or 0)
    need_restart = int(report.get("current_sessions_need_restart") or 0)
    counts = {
        "total": total,
        "governed": governed,
        "need_restart": need_restart,
    }
    by_status: dict[str, int] = {}
    for session in report.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        status = str(session.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    ok = bool(report.get("ok", True)) and need_restart == 0 and governed == total
    return _result(
        check,
        ok,
        "%d/%d governed; %d need restart" % (governed, total, need_restart),
        counts=counts,
        sessions_by_status=by_status,
    )


def _startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _watchdog_file(spec: dict[str, Any]) -> Path:
    if spec.get("startup_path"):
        return Path(str(spec["startup_path"]))
    return _startup_folder() / (WATCHDOG_TASK_NAME + ".vbs")


def _scheduled_task_exists(spec: dict[str, Any]) -> bool:
    if os.name != "nt":
        return False
    task = str(spec.get("task_name") or WATCHDOG_TASK_NAME)
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task],
            capture_output=True,
            text=True,
            timeout=float(spec.get("timeout", 5.0)),
            **_hidden_subprocess_kwargs(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    return proc.returncode == 0


def _probe_watchdog(check: str, spec: dict[str, Any]) -> dict[str, Any]:
    path = _watchdog_file(spec)
    file_ok = path.exists()
    task_ok = _scheduled_task_exists(spec)
    ok = file_ok or task_ok
    pieces = []
    if file_ok:
        pieces.append("startup launcher present")
    if task_ok:
        pieces.append("scheduled task present")
    if not pieces:
        pieces.append("no startup launcher or scheduled task found")
    return _result(
        check,
        ok,
        "; ".join(pieces),
        startup_launcher=str(path),
        scheduled_task=bool(task_ok),
    )


def run_governance_probe(spec: dict[str, Any]) -> dict[str, Any]:
    check = str(spec.get("check") or "")
    if check == "brain-health":
        return _probe_brain_health(check, spec)
    if check == "hook-coverage":
        return _probe_hook_coverage(check, spec)
    if check == "process-ancestry-governed":
        return _probe_process_ancestry(check, spec)
    if check == "normal-app-watchdog":
        return _probe_watchdog(check, spec)
    return _result(check or "unknown", False, "unknown governance check: %s" % (check or "missing"))
