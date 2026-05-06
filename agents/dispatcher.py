"""Dispatcher — picks the next pending task per department, runs it,
writes outputs + updates queue state.

The dispatcher is the only thing that ever instantiates Agents. It
also enforces the safety contract:

  * Outputs go to `agents/outputs/<dept>/<task-id>/`. Period.
  * Branches are `auto/<dept>/<task-id>` if anything is committed.
  * Pushes are off unless ARCHHUB_AUTO_PUSH=1 (we deliberately keep
    the human in the loop).

The dispatcher does NOT itself commit. A separate, optional `commit`
step is left to a follow-up tool (see `commit_outputs.py`, future).
This commit lands the framework only.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from .base import AgentResult
from .departments import DEPARTMENTS, get as get_department
from .queue import TaskQueue, Task, TaskStatus


class Dispatcher:
    def __init__(self, queue: Optional[TaskQueue] = None):
        self.queue = queue or TaskQueue()

    def run_one(self, department: Optional[str] = None) -> Optional[AgentResult]:
        """Pick the highest-priority pending task in the given department
        (or any department if None) and run it. Returns the result, or
        None if the queue was empty."""
        for task in self.queue.list_pending(department):
            if task.department not in DEPARTMENTS:
                # Unknown department — skip; the task file lives on for
                # a human to fix.
                continue
            if not self.queue.claim(task):
                continue   # someone else got it
            agent = get_department(task.department)
            try:
                result = agent.execute(task)
            except Exception as ex:
                self.queue.mark_failed(task, f"dispatcher: {type(ex).__name__}: {ex}")
                return AgentResult(False, "dispatcher exception", error=str(ex))

            if result.success:
                self.queue.mark_done(task, result.summary)
            else:
                self.queue.mark_failed(task, result.error or result.summary)
            return result
        return None

    def run_round(self) -> dict[str, AgentResult]:
        """One run per department that has a pending task."""
        results: dict[str, AgentResult] = {}
        for dept in DEPARTMENTS.keys():
            r = self.run_one(department=dept)
            if r is not None:
                results[dept] = r
        return results
