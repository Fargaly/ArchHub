"""Scheduler — keeps the queue topped up.

Every cycle:
  1. Reads `agents/recurring.yaml` (a small list of recurring jobs).
  2. For each, checks the last-run timestamp file under
     `agents/.last_run/<job-id>` and re-creates a fresh Task in the
     queue if the cadence has elapsed.
  3. Calls Dispatcher.run_round() to drain the queue.
  4. Sleeps until the next cycle.

The recurring YAML lets the user add or remove ongoing work without
touching code. Sample entries shipped in `agents/recurring.yaml`.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .dispatcher import Dispatcher
from .queue import Task, TaskQueue, REPO_ROOT


RECURRING_PATH = REPO_ROOT / "agents" / "recurring.yaml"
LAST_RUN_DIR = REPO_ROOT / "agents" / ".last_run"


class Scheduler:
    def __init__(self, dispatcher: Optional[Dispatcher] = None):
        self.dispatcher = dispatcher or Dispatcher()
        self.queue = self.dispatcher.queue
        LAST_RUN_DIR.mkdir(parents=True, exist_ok=True)

    def _enqueue_recurring(self) -> int:
        """Re-create any recurring task whose interval has elapsed.
        Returns the number of new tasks enqueued."""
        if not RECURRING_PATH.exists():
            return 0
        try:
            jobs = json.loads(RECURRING_PATH.read_text(encoding="utf-8"))
        except Exception:
            return 0

        added = 0
        now = datetime.now(timezone.utc)
        for job in jobs.get("jobs", []):
            jid = job.get("id")
            if not jid:
                continue
            last_path = LAST_RUN_DIR / f"{jid}.txt"
            interval = int(job.get("interval_minutes", 60))

            if last_path.exists():
                try:
                    last = datetime.fromisoformat(last_path.read_text().strip())
                except Exception:
                    last = now - timedelta(minutes=interval + 1)
            else:
                last = now - timedelta(minutes=interval + 1)

            if (now - last) < timedelta(minutes=interval):
                continue

            task = Task(
                id=f"{jid}-{uuid.uuid4().hex[:8]}",
                department=job["department"],
                title=job["title"],
                instructions=job["instructions"],
                priority=int(job.get("priority", 50)),
                inputs=dict(job.get("inputs") or {}),
            )
            self.queue.add(task)
            last_path.write_text(now.isoformat(), encoding="utf-8")
            added += 1
        return added

    def tick(self) -> dict:
        """One scheduler cycle. Returns a small summary dict.

        Also regenerates the Skill index used by Telemetry / Backlog
        depts. Cheap (filesystem walk + 1 JSON write) so it's safe
        to run every cycle.
        """
        try:
            from skills.exporter import export_skills_index
            export_skills_index()
        except Exception:
            # Index is best-effort; depts will fall back to whatever's
            # on disk from the previous successful export.
            pass
        added = self._enqueue_recurring()
        results = self.dispatcher.run_round()
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "added": added,
            "ran": {k: r.success for k, r in results.items()},
        }

    def run_forever(self, cycle_seconds: int = 300) -> None:
        """Daemon mode — call from agents/run.py."""
        print(f"[scheduler] starting; cycle = {cycle_seconds}s")
        while True:
            try:
                summary = self.tick()
                print(f"[scheduler] {summary}")
            except KeyboardInterrupt:
                print("[scheduler] interrupted, exiting")
                return
            except Exception as ex:
                print(f"[scheduler] error: {type(ex).__name__}: {ex}")
            time.sleep(cycle_seconds)
