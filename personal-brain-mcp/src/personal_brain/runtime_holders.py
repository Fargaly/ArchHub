"""Read-only process evidence for live-held legacy runtime copies."""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "archhub-live-runtime-holders/v1"


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    name: str
    cwd: str
    cmdline: str


def product_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_runtime_copy(root: Path | None = None) -> Path:
    return (root or product_root()) / "node_runtime"


def _norm(path: str | Path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def _under(path: str, root: str | Path) -> bool:
    path_norm = _norm(path)
    root_norm = _norm(root)
    return path_norm == root_norm or path_norm.startswith(root_norm + "\\")


def iter_processes() -> list[ProcessRecord]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []

    records: list[ProcessRecord] = []
    for proc in psutil.process_iter(["pid", "name", "cwd", "cmdline"]):
        try:
            info = proc.info
            records.append(
                ProcessRecord(
                    pid=int(info.get("pid") or 0),
                    name=str(info.get("name") or ""),
                    cwd=str(info.get("cwd") or ""),
                    cmdline=" ".join(info.get("cmdline") or []),
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return records


def find_holders(
    runtime_copy: Path,
    processes: Iterable[ProcessRecord] | None = None,
) -> list[dict[str, Any]]:
    root = runtime_copy.resolve() if runtime_copy.exists() else runtime_copy
    holders: list[dict[str, Any]] = []
    for record in list(processes) if processes is not None else iter_processes():
        cwd_matches = bool(record.cwd) and _under(record.cwd, root)
        cmd_matches = bool(record.cmdline) and _norm(root) in record.cmdline.lower()
        if not cwd_matches and not cmd_matches:
            continue
        holders.append(
            {
                "pid": record.pid,
                "name": record.name,
                "cwd": record.cwd,
                "cmdline": record.cmdline,
                "match": "cwd" if cwd_matches else "cmdline",
            }
        )
    holders.sort(key=lambda item: (item["pid"], item["name"]))
    return holders


def audit(runtime_copy: Path | None = None) -> dict[str, Any]:
    target = runtime_copy or default_runtime_copy()
    holders = find_holders(target)
    exists = target.exists()
    archive_safe = exists and not holders
    return {
        "schema": SCHEMA,
        "runtime_copy": str(target),
        "exists": exists,
        "holder_count": len(holders),
        "archive_safe_now": archive_safe,
        "required_action": (
            "archive is safe now"
            if archive_safe
            else "do not archive or move while holders exist; drain or relaunch from 10.PRODUCT/13.NODE-LANGUAGE first"
        ),
        "holders": holders,
    }
