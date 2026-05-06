"""Per-department token + run accounting.

Each Agent run reports tokens-in/tokens-out + duration. Meter persists
to `agents/logs/token_meter.json` and serves two consumers:

  1. Dashboard (`agents/dashboard.html`) — green/amber/red status per
     dept based on weekly burn vs budget.
  2. TelemetryAgent (Sprint 2) — feeds rolling friction report so the
     Eng dept knows which path costs the most local compute.

Token counting is honest about which depts are local vs cloud:
  - Ollama runs (every default dept) → tokens are LOCAL CPU/GPU
    seconds, no $ cost. We track them anyway because slow runs hurt
    the founder's machine.
  - Future cloud dept (e.g. an Anthropic-backed reviewer) — tokens
    will be cloud spend; same meter file, different `kind` field.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .queue import LOGS_DIR


_METER_PATH = LOGS_DIR / "token_meter.json"

# Default weekly budgets — tweaked from telemetry over time. Local budgets
# are in CPU-seconds; cloud budgets are in tokens (we'll add $ later).
WEEKLY_BUDGET_LOCAL_SECONDS = {
    "docs": 60 * 60,        # 1 h / week  (llama3.1, fast)
    "qa":   3 * 60 * 60,    # 3 h / week  (deepseek-r1, slow chain-of-thought)
    "rnd":  2 * 60 * 60,    # 2 h / week
    "eng":  2 * 60 * 60,
    "ops":  30 * 60,        # 30 min / week
}


@dataclass
class MeterRow:
    dept: str
    runs: int = 0
    successes: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0
    last_run_at: str = ""
    kind: str = "local"   # "local" | "cloud"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not _METER_PATH.exists():
        return {}
    try:
        return json.loads(_METER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    _METER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _METER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record(dept: str, *, success: bool, prompt_tokens: int, completion_tokens: int,
           elapsed_ms: int, kind: str = "local") -> dict:
    data = _load()
    entry = data.get(dept) or asdict(MeterRow(dept=dept, kind=kind))
    entry["runs"] += 1
    if success:
        entry["successes"] += 1
    else:
        entry["failures"] += 1
    entry["prompt_tokens"] += int(prompt_tokens or 0)
    entry["completion_tokens"] += int(completion_tokens or 0)
    entry["elapsed_ms"] += int(elapsed_ms or 0)
    entry["last_run_at"] = _now_iso()
    entry["kind"] = kind
    data[dept] = entry
    _save(data)
    return entry


def snapshot() -> dict:
    """Read-only — used by the dashboard + TelemetryAgent."""
    return _load()


def status_for(dept: str) -> str:
    """Quick green/amber/red verdict for a dept based on weekly burn."""
    entry = _load().get(dept)
    if not entry:
        return "green"
    if entry.get("kind") == "local":
        budget = WEEKLY_BUDGET_LOCAL_SECONDS.get(dept, 60 * 60) * 1000
        used = entry.get("elapsed_ms", 0)
        if used > budget:        return "red"
        if used > budget * 0.8:  return "amber"
        return "green"
    # cloud — placeholder until we wire $-based budgets.
    return "green"
