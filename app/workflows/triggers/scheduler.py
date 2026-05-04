"""Trigger framework.

A Trigger fires a workflow run. Phase 1 supports four trigger types:

  manual           — user clicks "Run". Always available.
  cron             — schedule expression (cron-like or "every Nm/h/d").
  speckle_webhook  — fires when Speckle emits an event.
                     Phase 1 = poll Speckle's commits at an interval; phase 2
                     listens to a registered webhook on a public endpoint.
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

from .graph import Workflow, Trigger
from .library import list_workflows, load_workflow


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
                 tick_seconds: float = 15.0):
        self.on_fire = on_fire
        self.tick_seconds = tick_seconds
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._last_runs: dict[str, float] = {}      # trigger.id -> last fired epoch
        self._file_signatures: dict[str, str] = {}  # trigger.id -> last seen mtime/digest

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
        last = self._last_runs.get(trig.id, 0.0)
        # Phase 1: simple interval syntax — "every 10m" / "every 1h" / "every 1d"
        spec = (trig.config.get("expression") or "").strip().lower()
        if spec.startswith("every "):
            try:
                num = int("".join(c for c in spec if c.isdigit()))
                unit = spec.rstrip()[-1]
                seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 60) * num
                return (now - last) >= seconds
            except Exception:
                return False
        # Standard cron strings would land here in phase 2 (croniter dependency).
        return False

    def _file_changed(self, trig: Trigger) -> bool:
        path = Path(trig.config.get("path") or "")
        if not path.exists():
            return False
        sig = f"{path.stat().st_mtime}:{path.stat().st_size}"
        prev = self._file_signatures.get(trig.id)
        self._file_signatures[trig.id] = sig
        return prev is not None and prev != sig

    def _speckle_changed(self, trig: Trigger, now: float) -> bool:
        # Phase 1 stub: always returns False. Phase 2 implements polling via
        # SpeckleClient.list_versions on the configured project/model.
        return False
