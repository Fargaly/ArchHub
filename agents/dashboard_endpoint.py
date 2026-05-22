"""Tiny FastAPI app served alongside the cloud daemon on port 8080.

The cloud_backend (or anyone with the Fly URL) can hit this to see
that the agents container is alive and what it's been producing.

Endpoints:
  GET /healthz                       — liveness + last heartbeat
  GET /status                        — queue + recent outputs summary
  GET /outputs/{department}/{task}   — file listing for one task
  GET /outputs/{department}/{task}/{filename} — single file content
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse


def _read_heartbeat(path: Path) -> dict:
    """Return {ts, cycles, age_seconds, fresh} from the heartbeat file.

    The file format is two lines: ISO timestamp, then cycle count. If
    the file doesn't exist (cold-start, volume not mounted) the
    dashboard still answers — it just reports the daemon as 'unknown'.
    """
    if not path.exists():
        return {"ts": None, "cycles": None, "age_seconds": None, "fresh": False}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        ts_str = lines[0].strip() if lines else ""
        cycles = int(lines[1].strip()) if len(lines) > 1 else 0
        ts = datetime.fromisoformat(ts_str)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return {
            "ts": ts_str,
            "cycles": cycles,
            "age_seconds": int(age),
            # "fresh" = last heartbeat within 3 cycles (default 180s) —
            # the cloud_backend uses this to flag a stalled daemon.
            "fresh": age < 180,
        }
    except Exception:
        return {"ts": None, "cycles": None, "age_seconds": None, "fresh": False}


def _scan_outputs(outputs_root: Path, limit: int = 20) -> list[dict]:
    """Return the N most-recent task outputs across all departments."""
    if not outputs_root.exists():
        return []
    items: list[dict] = []
    for dept_dir in outputs_root.iterdir():
        if not dept_dir.is_dir():
            continue
        for task_dir in dept_dir.iterdir():
            if not task_dir.is_dir():
                continue
            try:
                mtime = task_dir.stat().st_mtime
            except OSError:
                continue
            items.append({
                "department": dept_dir.name,
                "task_id": task_dir.name,
                "modified": datetime.fromtimestamp(mtime, tz=timezone.utc)
                                    .isoformat(),
                "modified_epoch": mtime,
            })
    items.sort(key=lambda d: d["modified_epoch"], reverse=True)
    for it in items:
        it.pop("modified_epoch", None)
    return items[:limit]


def _count_pending(tasks_root: Path) -> int:
    if not tasks_root.exists():
        return 0
    n = 0
    for dept_dir in tasks_root.iterdir():
        if not dept_dir.is_dir():
            continue
        for yaml_file in dept_dir.glob("*.yaml"):
            stem = yaml_file.stem
            if (dept_dir / f"{stem}.lock").exists():
                continue
            if (dept_dir / f"{stem}.done").exists():
                continue
            if (dept_dir / f"{stem}.failed").exists():
                continue
            n += 1
    return n


def _count_completed_today(tasks_root: Path) -> int:
    if not tasks_root.exists():
        return 0
    today = datetime.now(timezone.utc).date()
    n = 0
    for dept_dir in tasks_root.iterdir():
        if not dept_dir.is_dir():
            continue
        for done_file in dept_dir.glob("*.done"):
            try:
                mtime = datetime.fromtimestamp(
                    done_file.stat().st_mtime, tz=timezone.utc,
                )
            except OSError:
                continue
            if mtime.date() == today:
                n += 1
    return n


def build_app(
    *,
    heartbeat_path: Path,
    data_root: Path,
) -> FastAPI:
    """Construct the FastAPI app. Factory so tests can point it at tmp dirs."""
    app = FastAPI(title="archhub-agents", version="1.0.0")
    tasks_root = data_root / "tasks"
    outputs_root = data_root / "outputs"

    @app.get("/healthz")
    def healthz():
        hb = _read_heartbeat(heartbeat_path)
        return {
            "status": "ok" if hb["fresh"] else "stale",
            "last_heartbeat": hb["ts"],
            "cycles": hb["cycles"],
            "age_seconds": hb["age_seconds"],
        }

    @app.get("/status")
    def status():
        # Departments come from the registry — keeps the dashboard
        # in sync if a dept is added/removed in departments.py.
        from .departments import DEPARTMENTS
        return {
            "departments": sorted(DEPARTMENTS.keys()),
            "pending_tasks": _count_pending(tasks_root),
            "completed_today": _count_completed_today(tasks_root),
            "last_outputs": _scan_outputs(outputs_root, limit=10),
            "heartbeat": _read_heartbeat(heartbeat_path),
        }

    @app.get("/outputs/{department}/{task_id}")
    def list_output(department: str, task_id: str):
        out_dir = outputs_root / department / task_id
        if not out_dir.is_dir():
            raise HTTPException(status_code=404, detail="output not found")
        files = []
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                files.append({"name": f.name, "size": f.stat().st_size})
        return {"department": department, "task_id": task_id, "files": files}

    @app.get("/outputs/{department}/{task_id}/{filename}",
             response_class=PlainTextResponse)
    def get_output_file(department: str, task_id: str, filename: str):
        # Reject any traversal attempt — filename must not contain '/' or '..'
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="bad filename")
        f = outputs_root / department / task_id / filename
        if not f.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        try:
            return f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="binary file")

    return app


# Convenience: a module-level `app` reading from /data, used by uvicorn
# when launched as `uvicorn agents.dashboard_endpoint:app` (e.g. in a
# debug shell on the Fly machine).
_default_data = Path(os.environ.get("ARCHHUB_AGENTS_DATA_ROOT", "/data/agents"))
app = build_app(
    heartbeat_path=_default_data / "heartbeat.txt",
    data_root=_default_data,
)
