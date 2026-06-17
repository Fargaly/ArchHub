"""Trigger framework.

A Trigger fires a workflow run. Phase 1 supports four trigger types:

  manual           — user clicks "Run". Always available.
  cron             — schedule expression. Two syntaxes, both real:
                     interval ("every 10m" / "every 1h" / "every 1d") and
                     a standard 5-field cron string ("*/5 * * * *",
                     "0 9 * * 1-5", …). Parsed in-process, no external dep.
  speckle_webhook  — fires when the configured Speckle model gets a new
                     version. Polls the latest version/commit at the tick
                     interval and fires on a version-id change; a future
                     phase can additionally listen to a registered webhook
                     on a public endpoint.
  file_watch       — fires when a file/folder changes (uses polling, no
                     external dependency).

The TriggerScheduler is started by the chat window at app boot. It owns a
background QThread that ticks every N seconds and dispatches workflows whose
triggers have fired.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional

from ..graph import Workflow, Trigger
from ..library import list_workflows, load_workflow


@dataclass
class TriggerEvent:
    workflow_id: str
    trigger_id: str
    trigger_type: str
    fired_at: float = field(default_factory=time.time)
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
class TriggerScheduler:
    """Polls all stored workflows and fires their triggers when due."""

    def __init__(self, on_fire: Callable[[Workflow, Trigger], None],
                 tick_seconds: float = 15.0,
                 speckle_client: object | None = None):
        self.on_fire = on_fire
        self.tick_seconds = tick_seconds
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._last_runs: dict[str, float] = {}      # trigger.id -> last fired epoch
        self._file_signatures: dict[str, str] = {}  # trigger.id -> last seen mtime/digest
        self._speckle_versions: dict[str, str] = {} # trigger.id -> last seen version id
        self._last_cron_minute: dict[str, int] = {} # trigger.id -> last cron minute that fired
        # The Speckle client used to poll latest versions. Injectable so a
        # test can drive _speckle_changed without a live server; defaults to
        # the real SpeckleClient (lazy import — the scheduler module must load
        # without app/speckle_client's secrets_store import succeeding).
        self._speckle_client = speckle_client

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="ArchHubTriggers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                # Trigger loop must never crash; swallow and continue.
                pass
            self._stop.wait(self.tick_seconds)

    def _tick(self) -> None:
        now = time.time()
        for item in list_workflows():
            workflow = load_workflow(Path(item["path"]))
            for trig in workflow.triggers:
                if not trig.enabled or trig.type == "manual":
                    continue
                if self._should_fire(workflow, trig, now):
                    self._last_runs[trig.id] = now
                    self.on_fire(workflow, trig)

    def _should_fire(self, workflow: Workflow, trig: Trigger, now: float) -> bool:
        if trig.type == "cron":
            return self._cron_due(trig, now)
        if trig.type == "file_watch":
            return self._file_changed(trig)
        if trig.type == "speckle_webhook":
            # Phase 1: poll the latest commit on a model. Phase 2: real webhook receiver.
            return self._speckle_changed(trig, now)
        return False

    def _cron_due(self, trig: Trigger, now: float) -> bool:
        # The expression lives under config["expression"] OR config["cron"]
        # (the `schedule` grammar primitive writes `cron`). Accept both.
        raw = (trig.config.get("expression")
               or trig.config.get("cron") or "")
        spec = raw.strip()
        if not spec:
            return False
        last = self._last_runs.get(trig.id, 0.0)

        # Interval syntax — "every 10m" / "every 1h" / "every 1d".
        low = spec.lower()
        if low.startswith("every "):
            try:
                num = int("".join(c for c in low if c.isdigit()))
                unit = low.rstrip()[-1]
                seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 60) * num
                if seconds <= 0:
                    return False
                return (now - last) >= seconds
            except Exception:
                return False

        # Standard 5-field cron string — "*/5 * * * *", "0 9 * * 1-5", …
        # Parsed in-process (no external dependency). Fire once per matching
        # minute: a tick whose minute matches AND differs from the last minute
        # we fired for this trigger.
        try:
            dt = datetime.fromtimestamp(now)
        except (OverflowError, OSError, ValueError):
            return False
        if not _cron_matches(spec, dt):
            return False
        minute_stamp = int(now // 60)
        if self._last_cron_minute.get(trig.id) == minute_stamp:
            return False
        self._last_cron_minute[trig.id] = minute_stamp
        return True

    def _file_changed(self, trig: Trigger) -> bool:
        path = Path(trig.config.get("path") or "")
        if not path.exists():
            return False
        sig = f"{path.stat().st_mtime}:{path.stat().st_size}"
        prev = self._file_signatures.get(trig.id)
        self._file_signatures[trig.id] = sig
        return prev is not None and prev != sig

    def _speckle_changed(self, trig: Trigger, now: float) -> bool:
        """Fire when the configured Speckle model has a NEW version.

        Polls the latest version id for the trigger's project (+ branch /
        model) and compares it to the id seen on the previous poll. The
        FIRST poll records the baseline and does NOT fire (so wiring a
        trigger doesn't immediately replay the existing latest version);
        every subsequent poll fires iff the latest id changed.

        Honest-degrade contract: no token / no project / unreachable server /
        empty model → returns False (no fire), never raises. The version
        baseline is only advanced on a successful poll, so a transient error
        cannot make us miss the next real change.
        """
        cfg = trig.config or {}
        project_id = (cfg.get("project_id") or cfg.get("stream_id")
                      or cfg.get("project") or "").strip()
        if not project_id:
            return False
        branch = (cfg.get("branch") or cfg.get("model")
                  or DEFAULT_SPECKLE_BRANCH)

        latest = self._latest_speckle_version(project_id, branch)
        if not latest:
            # No reachable latest version (no token / offline / empty model /
            # error). Do not fire, do not move the baseline.
            return False

        prev = self._speckle_versions.get(trig.id)
        self._speckle_versions[trig.id] = latest
        if prev is None:
            # First successful poll establishes the baseline silently.
            return False
        return latest != prev

    def _latest_speckle_version(self, project_id: str,
                                branch: str) -> Optional[str]:
        """Return the latest version/commit id for (project, branch), or
        None when it can't be determined. Total-tolerant — any failure
        (no token, HTTP error, malformed payload) maps to None."""
        client = self._get_speckle_client()
        if client is None:
            return None
        try:
            res = client.pull_parameters(project_id, branch)
        except Exception:
            return None
        if not isinstance(res, dict):
            return None
        if res.get("status") != "ok":
            return None
        # pull_parameters returns the resolved commit_id (the version id on
        # the branch); object_id is the content hash fallback.
        return res.get("commit_id") or res.get("object_id") or None

    def _get_speckle_client(self):
        """Lazily build the real SpeckleClient on first use. Kept lazy so
        importing this module never requires app/speckle_client's
        secrets_store dependency to be importable (it pulls in the app
        package). An injected client (tests) short-circuits this."""
        if self._speckle_client is not None:
            return self._speckle_client
        try:
            from speckle_client import SpeckleClient
        except Exception:
            try:
                from app.speckle_client import SpeckleClient  # type: ignore
            except Exception:
                return None
        try:
            self._speckle_client = SpeckleClient()
        except Exception:
            return None
        return self._speckle_client


# ---------------------------------------------------------------------------
# Standard cron parsing — 5 fields (minute hour day-of-month month
# day-of-week), no external dependency. Supports `*`, `*/step`, ranges
# (`1-5`), `a,b,c` lists, and `a-b/step`. Day-of-week: 0 and 7 are Sunday.
# A datetime matches iff every field matches; day-of-month and day-of-week
# follow cron's OR semantics when BOTH are restricted.
# ---------------------------------------------------------------------------

DEFAULT_SPECKLE_BRANCH = "archhub/main"

_CRON_BOUNDS = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week (0/7 = Sunday, normalised below)
)


def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field into the set of integers it matches. Raises
    ValueError on malformed input so the caller can treat it as no-match."""
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field part")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError("cron step must be positive")
        else:
            base = part
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(base)
        if start > end or start < lo or end > hi:
            raise ValueError(f"cron value {base!r} out of range {lo}-{hi}")
        out.update(range(start, end + 1, step))
    return out


def _cron_matches(expr: str, dt: datetime) -> bool:
    """True iff `dt` satisfies the standard 5-field cron `expr`. Returns
    False (never raises) on a malformed expression."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    try:
        minute_s, hour_s, dom_s, month_s, dow_s = fields
        minutes = _parse_cron_field(minute_s, *_CRON_BOUNDS[0])
        hours = _parse_cron_field(hour_s, *_CRON_BOUNDS[1])
        doms = _parse_cron_field(dom_s, *_CRON_BOUNDS[2])
        months = _parse_cron_field(month_s, *_CRON_BOUNDS[3])
        # Normalise day-of-week 7 -> 0 (Sunday) before/after expansion.
        dows_raw = _parse_cron_field(dow_s.replace("7", "0")
                                     if dow_s.strip() in ("7", "*/7")
                                     else dow_s, *_CRON_BOUNDS[4])
        dows = {0 if d == 7 else d for d in dows_raw}
    except ValueError:
        return False

    if dt.minute not in minutes:
        return False
    if dt.hour not in hours:
        return False
    if dt.month not in months:
        return False

    # cron weekday: Monday=1..Sunday=0/7. Python weekday(): Monday=0..Sunday=6.
    py_dow = dt.weekday()          # Mon=0 .. Sun=6
    cron_dow = (py_dow + 1) % 7    # Mon=1 .. Sat=6 .. Sun=0

    dom_restricted = dom_s.strip() != "*"
    dow_restricted = dow_s.strip() != "*"
    dom_hit = dt.day in doms
    dow_hit = cron_dow in dows

    if dom_restricted and dow_restricted:
        # cron OR-semantics: match if EITHER constraint is satisfied.
        return dom_hit or dow_hit
    if dom_restricted:
        return dom_hit
    if dow_restricted:
        return dow_hit
    return True
