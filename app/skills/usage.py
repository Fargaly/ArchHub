"""Skill usage tracking — runs, success rate, last used.

Stored in a single JSON sidecar file: %LOCALAPPDATA%/ArchHub/skill_usage.json.
Per-user stats. Shared library skills get their stats logged locally too,
so each architect's panel reflects their own use, while firm-wide rollup
is a future job (v0.8 Speckle telemetry channel).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "skill_usage.json"


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_run(skill_id: str, *, success: bool, elapsed_ms: int = 0,
               error: Optional[str] = None,
               retry_of: Optional[str] = None) -> dict:
    """Persist one run.

    `retry_of` is set by the chat layer when it detects the user just
    re-asked the same question within ~60s — strong signal that the
    previous run failed silently (low completion-token count, no
    follow-up). Drives the Telemetry agent's "what hurts" report.
    """
    data = _load()
    entry = data.get(skill_id) or {
        "runs": 0, "successes": 0, "failures": 0,
        "retries": 0, "retry_history": [],
        "last_used": "", "last_error": "",
        "total_elapsed_ms": 0,
    }
    entry["runs"] = entry.get("runs", 0) + 1
    if success:
        entry["successes"] = entry.get("successes", 0) + 1
        entry["last_error"] = ""
    else:
        entry["failures"] = entry.get("failures", 0) + 1
        if error:
            entry["last_error"] = error
    if retry_of:
        entry["retries"] = entry.get("retries", 0) + 1
        # Cap retry_history at 20 — bounded growth.
        history = entry.get("retry_history") or []
        history.append({"prev": retry_of, "at": _now_iso()})
        entry["retry_history"] = history[-20:]
    entry["last_used"] = _now_iso()
    entry["total_elapsed_ms"] = entry.get("total_elapsed_ms", 0) + max(0, elapsed_ms)
    data[skill_id] = entry
    _save(data)

    # Mirror to telemetry so the friction report has cloud signal too.
    try:
        from telemetry import track_event
        track_event(
            "skill_run",
            skill_id=skill_id,
            success=bool(success),
            elapsed_ms=int(elapsed_ms),
            is_retry=bool(retry_of),
            error_kind=(error[:40] if error else None),
        )
    except Exception:
        pass

    return entry


def get_usage(skill_id: str) -> dict:
    data = _load()
    return data.get(skill_id) or {}


def all_usage() -> dict:
    return _load()
