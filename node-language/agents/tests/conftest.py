"""Shared fixtures for the agents/ test suite.

The agents package modules (`queue`, `scheduler`, `ceo_routine`, `base`)
compute their on-disk roots ONCE at import time from `REPO_ROOT`
(`agents/tasks/`, `agents/.last_run/`, `agents/outputs/_ceo/`, …). A naive
test would therefore read+write the developer's REAL repo dirs — polluting
the live queue and making tests order/host dependent.

`_isolate_agent_filesystem` redirects every such module-global at the start
of EVERY test to per-test tmp dirs (monkeypatch auto-reverts on teardown),
so the suite is hermetic: it exercises the real code paths against a clean,
throwaway filesystem and never touches `agents/tasks/` or `agents/outputs/`.
This is the same structural-isolation philosophy as the brain suite's
conftest — the guarantee is in config, not per-test discipline.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_agent_filesystem(monkeypatch, tmp_path):
    """Point all agents module-global on-disk roots at a per-test tmp tree so
    no test reads or writes the real repo's agents/ directories."""
    tasks_dir = tmp_path / "tasks"
    outputs_dir = tmp_path / "outputs"
    logs_dir = tmp_path / "logs"
    last_run_dir = tmp_path / "last_run"
    ceo_out = outputs_dir / "_ceo"
    for d in (tasks_dir, outputs_dir, logs_dir, last_run_dir, ceo_out):
        d.mkdir(parents=True, exist_ok=True)

    # queue.py — TaskQueue() defaults to TASKS_DIR; Agent uses OUTPUTS_DIR/LOGS_DIR.
    from agents import queue as _queue
    monkeypatch.setattr(_queue, "TASKS_DIR", tasks_dir, raising=True)
    monkeypatch.setattr(_queue, "OUTPUTS_DIR", outputs_dir, raising=True)
    monkeypatch.setattr(_queue, "LOGS_DIR", logs_dir, raising=True)

    # scheduler.py — recurring config + last-run timestamps.
    from agents import scheduler as _scheduler
    monkeypatch.setattr(_scheduler, "RECURRING_PATH", tasks_dir / "recurring.yaml",
                        raising=True)
    monkeypatch.setattr(_scheduler, "LAST_RUN_DIR", last_run_dir, raising=True)

    # ceo_routine.py — task root + CEO output log dir, AND the REPO anchor it
    # uses for `fp.relative_to(REPO)` when logging a filed task's path. tasks_dir
    # lives under tmp_path, so REPO must be tmp_path for relative_to to resolve.
    from agents import ceo_routine as _ceo
    monkeypatch.setattr(_ceo, "REPO", tmp_path, raising=True)
    monkeypatch.setattr(_ceo, "TASKS_ROOT", tasks_dir, raising=True)
    monkeypatch.setattr(_ceo, "CEO_OUT", ceo_out, raising=True)

    yield


@pytest.fixture
def tmp_queue(monkeypatch, tmp_path):
    """A real TaskQueue rooted in an isolated tmp dir (separate from the
    autouse default so a test can hold its own handle)."""
    from agents.queue import TaskQueue
    root = tmp_path / "q"
    return TaskQueue(root=root)
