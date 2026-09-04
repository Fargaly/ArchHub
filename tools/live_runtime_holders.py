#!/usr/bin/env python
"""Audit live processes holding a legacy runtime copy.

This is intentionally read-only. It does not terminate or move anything. The
purpose is to make copied runtime directories visible to the governance layer
before any archive/drain action is attempted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA = "archhub-live-runtime-holders/v1"
LOCAL_APP_SERVER_SCHEMA = "archhub-local-application-server-processes/v1"
BRAIN_RESOURCE_HYGIENE_SCHEMA = "archhub-brain-resource-hygiene/v1"
FINGERPRINT_PATHS = ("/", "/api/state", "/api/universal/health", "/health")
FINGERPRINT_TIMEOUT_SECONDS = 1.5
FINGERPRINT_BODY_BYTES = 512
PROTECTED_LOCAL_PORTS = frozenset((8482, 8484, 8501))
PROTECTED_BRAIN_PORTS = frozenset((8473,))


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    name: str
    cwd: str
    cmdline: str
    parent_pid: int | None = None
    create_time: float | None = None
    status: str = ""
    cpu_user_seconds: float | None = None
    cpu_system_seconds: float | None = None
    working_set_bytes: int | None = None
    private_memory_bytes: int | None = None


def default_runtime_copy(root: Path) -> Path:
    return root / "node_runtime"


def _norm(path: str | Path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def _under(path: str, root: str) -> bool:
    # One separator on every runner: the records are Windows paths, the
    # runtime copy under test may be a POSIX tmp_path.
    path_norm = _norm(path).replace("\\", "/")
    root_norm = _norm(root).replace("\\", "/").rstrip("/")
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def iter_processes() -> list[ProcessRecord]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []

    records: list[ProcessRecord] = []
    for proc in psutil.process_iter([
        "pid",
        "name",
        "cwd",
        "cmdline",
        "ppid",
        "create_time",
        "status",
        "cpu_times",
        "memory_info",
    ]):
        try:
            info = proc.info
            cpu_times = info.get("cpu_times")
            memory_info = info.get("memory_info")
            records.append(
                ProcessRecord(
                    pid=int(info.get("pid") or 0),
                    name=str(info.get("name") or ""),
                    cwd=str(info.get("cwd") or ""),
                    cmdline=" ".join(info.get("cmdline") or []),
                    parent_pid=(
                        int(info["ppid"])
                        if info.get("ppid") is not None
                        else None
                    ),
                    create_time=(
                        float(info["create_time"])
                        if info.get("create_time") is not None
                        else None
                    ),
                    status=str(info.get("status") or ""),
                    cpu_user_seconds=(
                        float(getattr(cpu_times, "user"))
                        if cpu_times is not None and hasattr(cpu_times, "user")
                        else None
                    ),
                    cpu_system_seconds=(
                        float(getattr(cpu_times, "system"))
                        if cpu_times is not None and hasattr(cpu_times, "system")
                        else None
                    ),
                    working_set_bytes=(
                        int(getattr(memory_info, "rss"))
                        if memory_info is not None and hasattr(memory_info, "rss")
                        else None
                    ),
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return records


def find_holders(
    runtime_copy: Path,
    processes: Iterable[ProcessRecord] | None = None,
    observed_at: float | None = None,
) -> list[dict[str, Any]]:
    root = str(runtime_copy.resolve() if runtime_copy.exists() else runtime_copy)
    records = list(processes) if processes is not None else iter_processes()
    observed = observed_at if observed_at is not None else time.time()
    holders: list[dict[str, Any]] = []
    for record in records:
        cwd_matches = bool(record.cwd) and _under(record.cwd, root)
        cmd_matches = bool(record.cmdline) and _norm(root) in record.cmdline.lower()
        if not cwd_matches and not cmd_matches:
            continue
        age_seconds = (
            max(0.0, observed - record.create_time)
            if record.create_time is not None
            else None
        )
        cpu_total_seconds = None
        if record.cpu_user_seconds is not None or record.cpu_system_seconds is not None:
            cpu_total_seconds = (
                float(record.cpu_user_seconds or 0.0)
                + float(record.cpu_system_seconds or 0.0)
            )
        holders.append(
            {
                "pid": record.pid,
                "name": record.name,
                "cwd": record.cwd,
                "cmdline": record.cmdline,
                "match": "cwd" if cwd_matches else "cmdline",
                "create_time": record.create_time,
                "age_seconds": age_seconds,
                "status": record.status,
                "cpu_user_seconds": record.cpu_user_seconds,
                "cpu_system_seconds": record.cpu_system_seconds,
                "cpu_total_seconds": cpu_total_seconds,
            }
        )
    holders.sort(key=lambda item: (item["pid"], item["name"]))
    return holders


def audit(runtime_copy: Path) -> dict[str, Any]:
    observed_at = time.time()
    holders = find_holders(runtime_copy, observed_at=observed_at)
    exists = runtime_copy.exists()
    archive_safe = exists and not holders
    return {
        "schema": SCHEMA,
        "runtime_copy": str(runtime_copy),
        "exists": exists,
        "observed_at": observed_at,
        "holder_count": len(holders),
        "archive_safe_now": archive_safe,
        "required_action": (
            "archive is safe now"
            if archive_safe
            else "do not archive or move while holders exist; drain or relaunch from 10.PRODUCT/13.NODE-LANGUAGE first"
        ),
        "holders": holders,
    }


def audit_local_application_servers(
    workspace_root: Path,
    processes: Iterable[ProcessRecord] | None = None,
    observed_at: float | None = None,
) -> dict[str, Any]:
    """Classify local ArchHub app-server processes without interrupting them."""
    workspace = workspace_root.resolve()
    records = list(processes) if processes is not None else iter_processes()
    observed = observed_at if observed_at is not None else time.time()
    listener_map, established_connection_count = _process_tcp_maps()
    rows = [
        _local_application_server_row(
            record,
            workspace,
            observed,
            listener_map.get(record.pid, []),
            int(established_connection_count.get(record.pid, 0)),
        )
        for record in records
        if _is_archhub_runtime_process(record.cmdline)
    ]
    rows.sort(key=lambda item: (str(item["classification"]), int(item["pid"])))
    stop_candidates = [row for row in rows if row["safe_to_stop"] is True]
    protected = [row for row in rows if row["safe_to_stop"] is not True]
    return {
        "schema": LOCAL_APP_SERVER_SCHEMA,
        "observed_at": observed,
        "workspace_root": str(workspace),
        "process_count": len(rows),
        "safe_to_stop_count": len(stop_candidates),
        "protected_count": len(protected),
        "safe_to_stop_pids": [row["pid"] for row in stop_candidates],
        "protected_pids": [row["pid"] for row in protected],
        "rule": (
            "read-only classification; stop only safe_to_stop PIDs after an "
            "immediate exact PID and command-line recheck"
        ),
        "processes": rows,
    }


def audit_brain_resource_hygiene(
    processes: Iterable[ProcessRecord] | None = None,
    observed_at: float | None = None,
) -> dict[str, Any]:
    """Classify Brain server processes without interrupting them.

    The protected service is the HTTP Brain listener. Bare non-listening
    ``python -m personal_brain.server`` children can consume memory as duplicate
    MCP/stdio helpers, but this audit only reports candidates. A caller still
    has to recheck the exact PID/command/ports immediately before stopping one.
    """
    records = list(processes) if processes is not None else iter_processes()
    observed = observed_at if observed_at is not None else time.time()
    listener_map, established_connection_count = _process_tcp_maps()
    child_count = _child_count_by_parent(records)
    rows = [
        _brain_resource_row(
            record,
            observed,
            listener_map.get(record.pid, []),
            int(established_connection_count.get(record.pid, 0)),
            int(child_count.get(record.pid, 0)),
        )
        for record in records
        if _is_personal_brain_server_process(record.cmdline)
    ]
    rows.sort(key=lambda item: (str(item["classification"]), int(item["pid"])))
    release_candidates = [
        row for row in rows
        if row["classification"] == "candidate_duplicate_non_listening_brain"
    ]
    protected = [row for row in rows if row not in release_candidates]
    return {
        "schema": BRAIN_RESOURCE_HYGIENE_SCHEMA,
        "observed_at": observed,
        "process_count": len(rows),
        "release_candidate_count": len(release_candidates),
        "protected_count": len(protected),
        "release_candidate_pids": [row["pid"] for row in release_candidates],
        "protected_pids": [row["pid"] for row in protected],
        "total_release_candidate_working_set_bytes": sum(
            int(row.get("working_set_bytes") or 0) for row in release_candidates
        ),
        "rule": (
            "read-only classification; release only candidate PIDs after an "
            "immediate exact PID, command-line, child, and port recheck; never "
            "touch protected Brain listeners or supervisor processes"
        ),
        "processes": rows,
    }


def _child_count_by_parent(records: Iterable[ProcessRecord]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for record in records:
        if record.parent_pid is None:
            continue
        counts[int(record.parent_pid)] = counts.get(int(record.parent_pid), 0) + 1
    return counts


def _is_personal_brain_server_process(cmdline: str) -> bool:
    cmd = str(cmdline or "").lower()
    return "-m personal_brain.server" in cmd


def _brain_resource_row(
    record: ProcessRecord,
    observed_at: float,
    listening_ports: Iterable[int],
    established_connections: int,
    child_process_count: int,
) -> dict[str, Any]:
    cmdline = str(record.cmdline or "")
    ports = sorted(set(int(port) for port in listening_ports))
    age_seconds = (
        max(0.0, observed_at - record.create_time)
        if record.create_time is not None
        else None
    )
    cpu_total_seconds = None
    if record.cpu_user_seconds is not None or record.cpu_system_seconds is not None:
        cpu_total_seconds = (
            float(record.cpu_user_seconds or 0.0)
            + float(record.cpu_system_seconds or 0.0)
        )
    classification, posture, release_candidate = _classify_brain_server(
        cmdline,
        ports,
        established_connections,
        child_process_count,
    )
    return {
        "pid": int(record.pid),
        "parent_pid": record.parent_pid,
        "name": record.name,
        "cwd": record.cwd,
        "cmdline": cmdline,
        "classification": classification,
        "drain_posture": posture,
        "release_candidate": release_candidate,
        "listening_ports": ports,
        "established_connection_count": established_connections,
        "child_process_count": child_process_count,
        "create_time": record.create_time,
        "age_seconds": age_seconds,
        "status": record.status,
        "cpu_user_seconds": record.cpu_user_seconds,
        "cpu_system_seconds": record.cpu_system_seconds,
        "cpu_total_seconds": cpu_total_seconds,
        "working_set_bytes": record.working_set_bytes,
        "private_memory_bytes": record.private_memory_bytes,
        "allowed_action": (
            "inspect only; this audit never interrupts a process"
        ),
    }


def _classify_brain_server(
    cmdline: str,
    listening_ports: list[int],
    established_connections: int,
    child_process_count: int,
) -> tuple[str, str, bool]:
    cmd = str(cmdline or "").lower()
    ports = set(listening_ports)
    if "--http" in cmd or ports & PROTECTED_BRAIN_PORTS:
        return (
            "protected_brain_http_service",
            "supervised or listening Brain service; never stop as duplicate cleanup",
            False,
        )
    if ports:
        return (
            "protected_brain_listener",
            "Brain process owns a listener; identify service role before any handoff",
            False,
        )
    if established_connections > 0:
        return (
            "protected_brain_active_client",
            "Brain process has active TCP clients; do not interrupt mid-flight",
            False,
        )
    if child_process_count > 0:
        return (
            "protected_brain_parent",
            "Brain process owns child processes; inspect child tree first",
            False,
        )
    return (
        "candidate_duplicate_non_listening_brain",
        (
            "bare non-listening Brain server child; release only after exact "
            "PID/command/port recheck and machine-priority coordination"
        ),
        True,
    )


def _process_tcp_maps() -> tuple[dict[int, list[int]], dict[int, int]]:
    listener_map: dict[int, list[int]] = {}
    established_connection_count: dict[int, int] = {}
    try:
        import psutil  # type: ignore

        for conn in psutil.net_connections(kind="tcp"):
            try:
                if conn.pid is None:
                    continue
                pid = int(conn.pid)
                status = str(conn.status).upper()
                if status == "ESTABLISHED":
                    established_connection_count[pid] = (
                        established_connection_count.get(pid, 0) + 1
                    )
                if status != "LISTEN" or not conn.laddr:
                    continue
                listener_map.setdefault(pid, []).append(int(conn.laddr.port))
            except (AttributeError, TypeError, ValueError):
                continue
    except Exception:
        return {}, {}
    return (
        {pid: sorted(set(ports)) for pid, ports in listener_map.items()},
        established_connection_count,
    )


def _is_archhub_runtime_process(cmdline: str) -> bool:
    cmd = str(cmdline or "").lower()
    return (
        "nodelang.application_server" in cmd
        or "nodelang.authority_bridge" in cmd
        or "run_application_server.py" in cmd
    )


def _local_application_server_row(
    record: ProcessRecord,
    workspace: Path,
    observed_at: float,
    listening_ports: Iterable[int],
    established_connections: int,
) -> dict[str, Any]:
    cmdline = str(record.cmdline or "")
    cmd = cmdline.lower()
    ports = sorted(set(int(port) for port in listening_ports))
    declared_port = _flag_int(cmdline, "--port")
    declared_cloud_port = _flag_int(cmdline, "--cloud-port")
    state_path = _flag_value(cmdline, "--state-path")
    universal_state_path = _flag_value(cmdline, "--universal-state-path")
    fresh = _has_flag(cmdline, "--fresh")
    age_seconds = (
        max(0.0, observed_at - record.create_time)
        if record.create_time is not None
        else None
    )
    cpu_total_seconds = None
    if record.cpu_user_seconds is not None or record.cpu_system_seconds is not None:
        cpu_total_seconds = (
            float(record.cpu_user_seconds or 0.0)
            + float(record.cpu_system_seconds or 0.0)
        )
    classification, posture, safe_to_stop = _classify_local_application_server(
        cmd,
        workspace,
        ports,
        declared_port,
        state_path,
        universal_state_path,
        fresh,
        established_connections,
    )
    return {
        "pid": int(record.pid),
        "name": record.name,
        "cwd": record.cwd,
        "cmdline": cmdline,
        "classification": classification,
        "drain_posture": posture,
        "safe_to_stop": safe_to_stop,
        "fresh": fresh,
        "declared_port": declared_port,
        "declared_cloud_port": declared_cloud_port,
        "listening_ports": ports,
        "established_connection_count": established_connections,
        "state_path": state_path,
        "universal_state_path": universal_state_path,
        "create_time": record.create_time,
        "age_seconds": age_seconds,
        "status": record.status,
        "cpu_user_seconds": record.cpu_user_seconds,
        "cpu_system_seconds": record.cpu_system_seconds,
        "cpu_total_seconds": cpu_total_seconds,
    }


def _classify_local_application_server(
    cmd: str,
    workspace: Path,
    listening_ports: list[int],
    declared_port: int | None,
    state_path: str | None,
    universal_state_path: str | None,
    fresh: bool,
    established_connections: int,
) -> tuple[str, str, bool]:
    ports = set(listening_ports)
    if "nodelang.authority_bridge" in cmd:
        return (
            "protected_authority_bridge",
            "active authority bridge; never stop as QA cleanup",
            False,
        )
    if "run_application_server.py" in cmd:
        return (
            "protected_copied_runtime_endpoint",
            "copied runtime visible endpoint; drain through legacy runtime plan",
            False,
        )
    if declared_port in PROTECTED_LOCAL_PORTS or ports & PROTECTED_LOCAL_PORTS:
        return (
            "protected_visible_endpoint",
            "user-visible endpoint; preserve unless explicitly relaunched",
            False,
        )
    if established_connections > 0:
        return (
            "protected_active_connections",
            "has active TCP clients; do not interrupt mid-flight",
            False,
        )
    if not fresh:
        return (
            "protected_non_fresh_runtime",
            "not a disposable --fresh QA runtime; inspect before handoff",
            False,
        )
    if not _is_disposable_qa_state_path(workspace, state_path, universal_state_path):
        return (
            "protected_unknown_fresh_runtime",
            "fresh runtime but state path is not a recognized QA scratch path",
            False,
        )
    return (
        "disposable_fresh_qa_runtime",
        "fresh QA runtime with scratch state and no active clients",
        True,
    )


def _is_disposable_qa_state_path(
    workspace: Path,
    state_path: str | None,
    universal_state_path: str | None,
) -> bool:
    candidates = [path for path in (state_path, universal_state_path) if path]
    if not candidates:
        return False
    test_results = workspace / "10.PRODUCT" / "13.NODE-LANGUAGE" / "test-results"
    # Compare with one separator: the holders are Windows paths, the
    # workspace may be a POSIX tmp_path on a Linux runner.
    def _norm(path: object) -> str:
        return str(path).replace("\\", "/").lower()
    test_results_prefix = _norm(test_results) + "/qa-"
    for raw in candidates:
        lower = _norm(raw)
        if (
            "/appdata/local/temp/archhub-current-memory-qa-" in lower
            or "/appdata/local/temp/archhub-universal-qa-" in lower
            or lower.startswith(test_results_prefix)
        ):
            return True
    return False


def _flag_value(cmdline: str, flag: str) -> str | None:
    parts = cmdline.split()
    for index, part in enumerate(parts):
        if part == flag and index + 1 < len(parts):
            return parts[index + 1].strip('"')
    prefix = flag + "="
    for part in parts:
        if part.startswith(prefix):
            return part[len(prefix):].strip('"')
    return None


def _flag_int(cmdline: str, flag: str) -> int | None:
    value = _flag_value(cmdline, flag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _has_flag(cmdline: str, flag: str) -> bool:
    return flag in cmdline.split()


def inspect_pids(pids: Iterable[int]) -> dict[str, Any]:
    """Return read-only process details for handoff candidates."""
    inspected: list[dict[str, Any]] = []
    observed_at = time.time()
    try:
        import psutil  # type: ignore
    except Exception as exc:
        return {
            "schema": "archhub-live-runtime-pid-inspection/v1",
            "observed_at": observed_at,
            "available": False,
            "reason": f"psutil unavailable: {exc}",
            "processes": [],
        }

    listener_map, established_connection_count = _process_tcp_maps()

    for pid in sorted({int(pid) for pid in pids}):
        try:
            proc = psutil.Process(pid)
            create_time = proc.create_time()
            cpu_times = proc.cpu_times()
            parent = proc.parent()
            children = proc.children(recursive=False)
            cmdline_argv = list(_safe_proc_value(proc.cmdline, default=[]))
            cwd = _safe_proc_value(proc.cwd)
            script = _script_evidence(cmdline_argv, cwd)
            inspected.append({
                "pid": pid,
                "exists": True,
                "name": proc.name(),
                "status": proc.status(),
                "cwd": cwd,
                "cmdline": " ".join(cmdline_argv),
                "cmdline_argv": cmdline_argv,
                "create_time": create_time,
                "age_seconds": max(0.0, observed_at - create_time),
                "cpu_user_seconds": float(getattr(cpu_times, "user", 0.0)),
                "cpu_system_seconds": float(getattr(cpu_times, "system", 0.0)),
                "cpu_total_seconds": (
                    float(getattr(cpu_times, "user", 0.0))
                    + float(getattr(cpu_times, "system", 0.0))
                ),
                "parent_pid": parent.pid if parent is not None else None,
                "child_pids": [child.pid for child in children],
                "listening_ports": sorted(listener_map.get(pid, [])),
                "established_connection_count": int(
                    established_connection_count.get(pid, 0)
                ),
                "endpoint_fingerprints": _endpoint_fingerprints(
                    sorted(listener_map.get(pid, []))
                ),
                **script,
                **_process_risk_class(
                    cmdline_argv,
                    cwd,
                    [child.pid for child in children],
                    sorted(listener_map.get(pid, [])),
                    parent.pid if parent is not None else None,
                    script,
                ),
                "allowed_action": "inspect only; this function never interrupts a process",
            })
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            inspected.append({
                "pid": pid,
                "exists": False,
                "error": type(exc).__name__,
                "allowed_action": "treat as changed state; rerun drain gate before cleanup",
            })
    return {
        "schema": "archhub-live-runtime-pid-inspection/v1",
        "observed_at": observed_at,
        "available": True,
        "processes": inspected,
    }


def _endpoint_fingerprints(ports: Iterable[int]) -> list[dict[str, Any]]:
    """Fingerprint local listener ports with bounded read-only HTTP GETs."""
    fingerprints: list[dict[str, Any]] = []
    for port in sorted({int(port) for port in ports}):
        for path in FINGERPRINT_PATHS:
            url = f"http://127.0.0.1:{port}{path}"
            row: dict[str, Any] = {
                "port": port,
                "path": path,
                "url": url,
                "ok": False,
            }
            try:
                request = Request(
                    url,
                    method="GET",
                    headers={
                        "User-Agent": (
                            "ArchHub-readonly-runtime-fingerprint/1"
                        ),
                    },
                )
                with urlopen(
                    request, timeout=FINGERPRINT_TIMEOUT_SECONDS
                ) as response:
                    body = response.read(FINGERPRINT_BODY_BYTES)
                    row.update(_http_fingerprint_row(response, body))
            except HTTPError as exc:
                row.update(_http_fingerprint_row(exc, exc.read(FINGERPRINT_BODY_BYTES)))
            except (
                URLError,
                TimeoutError,
                socket.timeout,
                ConnectionError,
                OSError,
            ) as exc:
                row.update({
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:180],
                })
            fingerprints.append(row)
    return fingerprints


def _http_fingerprint_row(response, body: bytes) -> dict[str, Any]:
    status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
    headers = getattr(response, "headers", {})
    return {
        "ok": True,
        "status": status,
        "content_type": headers.get("Content-Type"),
        "server": headers.get("Server"),
        "body_prefix": body.decode("utf-8", errors="replace")[:180],
    }


def _script_evidence(argv: list[str], cwd: str) -> dict[str, Any]:
    """Return file evidence for Python script/module/stdin launches."""
    mode = "unknown"
    module = None
    script_path = None
    stdin_mode = False
    for index, arg in enumerate(argv[1:], start=1):
        if arg == "-m" and index + 1 < len(argv):
            mode = "python_module"
            module = argv[index + 1]
            break
        if arg == "-":
            mode = "python_stdin"
            stdin_mode = True
            break
        if arg.lower().endswith(".py"):
            mode = "python_script"
            candidate = Path(arg)
            if not candidate.is_absolute() and cwd:
                candidate = Path(cwd) / candidate
            script_path = str(candidate)
            break
    evidence: dict[str, Any] = {
        "launch_mode": mode,
        "module": module,
        "stdin_mode": stdin_mode,
        "script_path": script_path,
        "script_exists": False,
        "script_size_bytes": None,
        "script_mtime_utc": None,
        "script_sha256": None,
    }
    if not script_path:
        return evidence
    path = Path(script_path)
    if not path.is_file():
        return evidence
    try:
        stat = path.stat()
        evidence.update({
            "script_exists": True,
            "script_size_bytes": int(stat.st_size),
            "script_mtime_utc": stat.st_mtime,
            "script_sha256": _sha256(path),
        })
    except OSError:
        pass
    return evidence


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _process_risk_class(
    argv: list[str],
    cwd: str,
    child_pids: list[int],
    listening_ports: list[int],
    parent_pid: int | None,
    script: dict[str, Any],
) -> dict[str, str]:
    cmd = " ".join(argv).lower()
    cwd_lower = str(cwd or "").lower()
    script_path = str(script.get("script_path") or "").lower()
    # Holders are Windows processes; a POSIX runner must still read the
    # script name off a backslash path.
    script_name = PureWindowsPath(script_path).name.lower() if script_path else ""
    if (
        "run_application_server.py" in cmd
        and "--port 8482" in cmd
        and "--cloud-port 8484" in cmd
        and "node_runtime" in cwd_lower
    ):
        return {
            "process_risk_class": "visible_legacy_endpoint",
            "drain_posture": (
                "coordinate visible endpoint handoff; do not stop mid-flight"
            ),
        }
    if script_name == "archhub_nary_qa_server.py":
        return {
            "process_risk_class": (
                "qa_server_script" if script.get("script_exists")
                else "qa_server_script_missing"
            ),
            "drain_posture": (
                "script-backed QA holder; verify owner before any handoff"
                if script.get("script_exists")
                else "orphaned temp-script holder; inspect live process before any cleanup"
            ),
        }
    if script.get("stdin_mode") and listening_ports:
        return {
            "process_risk_class": "stdin_python_listener_child",
            "drain_posture": (
                "stdin-launched listener; identify parent/source before handoff"
            ),
        }
    if script.get("stdin_mode") and child_pids:
        return {
            "process_risk_class": "stdin_python_parent",
            "drain_posture": (
                "stdin-launched parent with child process; inspect child before handoff"
            ),
        }
    if "-m nodelang.application_server" in cmd and "13.node-language" in cwd_lower:
        return {
            "process_risk_class": "authority_sidecar_listener",
            "drain_posture": "authority-side listener; not a copied-runtime holder",
        }
    return {
        "process_risk_class": "unclassified_process_holder",
        "drain_posture": "inspect evidence before deciding any handoff",
    }


def _safe_proc_value(method, default: Any = "") -> Any:
    try:
        return method()
    except Exception:
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit live holders for a legacy runtime copy.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--runtime-copy", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--enforce-drained", action="store_true")
    parser.add_argument(
        "--inspect-pid",
        action="append",
        type=int,
        default=[],
        help="Inspect a PID read-only. May be supplied multiple times.",
    )
    parser.add_argument(
        "--audit-local-app-servers",
        action="store_true",
        help="Read-only audit of local ArchHub app-server/authority processes.",
    )
    parser.add_argument(
        "--audit-brain-resource-hygiene",
        action="store_true",
        help="Read-only audit of duplicate/non-listening Brain server children.",
    )
    parser.add_argument(
        "--enforce-no-brain-duplicates",
        action="store_true",
        help="Exit 2 when duplicate non-listening Brain candidates are present.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.audit_brain_resource_hygiene:
        report = audit_brain_resource_hygiene()
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        if args.enforce_no_brain_duplicates and report["release_candidate_count"]:
            return 2
        return 0

    if args.audit_local_app_servers:
        report = audit_local_application_servers(root.parents[1])
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0

    if args.inspect_pid:
        print(json.dumps(inspect_pids(args.inspect_pid), indent=2))
        return 0

    runtime_copy = Path(args.runtime_copy) if args.runtime_copy else default_runtime_copy(root)
    report = audit(runtime_copy)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.enforce_drained and report["holder_count"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
