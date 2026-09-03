"""Tests for agents.scheduler — keeps the queue topped up from recurring.yaml.

Live production module (archhub-agents) with ZERO prior coverage (TCI-02).
Drives the real `_enqueue_recurring` cadence logic + `tick` summary against an
isolated tmp filesystem (see conftest) and a fake dispatcher (no departments
run). Verifies: a fresh recurring job is enqueued, the last-run stamp is
written, a not-yet-due job is skipped on the next pass, and a missing
recurring.yaml is a clean no-op.
"""
from __future__ import annotations

import json

import agents.scheduler as scheduler_mod
from agents.queue import TaskQueue
from agents.scheduler import Scheduler


class _FakeDispatcher:
    """Stands in for the real Dispatcher: owns a queue, run_round is a no-op."""

    def __init__(self, queue: TaskQueue):
        self.queue = queue
        self.rounds = 0

    def run_round(self) -> dict:
        self.rounds += 1
        return {}


def _make_scheduler(tmp_path) -> tuple[Scheduler, TaskQueue]:
    q = TaskQueue(root=tmp_path / "sched_q")
    sched = Scheduler(dispatcher=_FakeDispatcher(q))
    return sched, q


def _write_recurring(jobs: list[dict]) -> None:
    scheduler_mod.RECURRING_PATH.parent.mkdir(parents=True, exist_ok=True)
    scheduler_mod.RECURRING_PATH.write_text(
        json.dumps({"jobs": jobs}), encoding="utf-8"
    )


def test_enqueue_recurring_no_file_is_noop(tmp_path):
    sched, q = _make_scheduler(tmp_path)
    # conftest points RECURRING_PATH at a non-existent file.
    assert sched._enqueue_recurring() == 0
    assert q.list_pending() == []


def test_enqueue_recurring_creates_due_task(tmp_path):
    _write_recurring([{
        "id": "nightly-digest",
        "department": "docs",
        "title": "Nightly digest",
        "instructions": "summarise the day",
        "interval_minutes": 60,
        "priority": 30,
    }])
    sched, q = _make_scheduler(tmp_path)

    added = sched._enqueue_recurring()
    assert added == 1, "a never-run recurring job must be enqueued"
    pending = q.list_pending()
    assert len(pending) == 1
    t = pending[0]
    assert t.department == "docs"
    assert t.title == "Nightly digest"
    assert t.priority == 30
    # The last-run stamp must be written so the next pass can compute cadence.
    assert (scheduler_mod.LAST_RUN_DIR / "nightly-digest.txt").exists()


def test_enqueue_recurring_skips_when_not_due(tmp_path):
    _write_recurring([{
        "id": "hourly-job",
        "department": "eng",
        "title": "Hourly job",
        "instructions": "do it",
        "interval_minutes": 60,
    }])
    sched, q = _make_scheduler(tmp_path)

    assert sched._enqueue_recurring() == 1   # first pass: due (never run)
    # Second pass immediately after: the stamp is fresh → NOT due → skipped.
    assert sched._enqueue_recurring() == 0, (
        "a job that just ran must not be re-enqueued before its interval elapses"
    )
    assert len(q.list_pending()) == 1


def test_enqueue_recurring_ignores_jobs_without_id(tmp_path):
    _write_recurring([{"department": "eng", "title": "no id", "instructions": "x"}])
    sched, q = _make_scheduler(tmp_path)
    assert sched._enqueue_recurring() == 0
    assert q.list_pending() == []


def test_tick_returns_summary_and_runs_round(tmp_path):
    _write_recurring([{
        "id": "tick-job",
        "department": "ops",
        "title": "Tick job",
        "instructions": "tick",
        "interval_minutes": 60,
    }])
    sched, q = _make_scheduler(tmp_path)

    summary = sched.tick()
    assert summary["added"] == 1
    assert "ts" in summary and "ran" in summary
    assert sched.dispatcher.rounds == 1, "tick must call dispatcher.run_round()"
