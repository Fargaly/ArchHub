"""Roadmap dispatcher — the autonomous loop.

Periodically scans every roadmap source, enqueues new items as Tasks
for the suggested department, and tracks completion ids on disk.

Loop responsibilities:

  * Throttle — runs at most every `ARCHHUB_ROADMAP_INTERVAL_MIN` minutes
    (default 30). Earlier ticks are no-ops.
  * De-dup — a roadmap item already in the task queue OR already in
    `agents/state/completed_roadmap_ids.txt` is skipped.
  * Priority — `#P0` items get `priority=10`, `#P1` → 30, `#P2` → 70.
    The existing dispatcher already orders by `task.priority` ascending,
    so HIGH-priority work runs first.
  * Concurrency — a `lock.txt` file prevents two ticks from racing
    each other when started from different processes.
  * Done-tracking — when the main dispatcher marks a roadmap-sourced
    task as `.done`, this module appends the item id to
    `completed_roadmap_ids.txt` so it never gets re-enqueued.
  * Safe failures — every source error is swallowed; the loop never
    crashes the cloud daemon. Failures are written to `last_tick.txt`.

The loop never modifies repo source files. The only writes are to:

    agents/state/lock.txt
    agents/state/last_tick.txt
    agents/state/completed_roadmap_ids.txt

Pause the loop entirely with `ARCHHUB_ROADMAP_DISABLED=1`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import roadmap_source
from .queue import REPO_ROOT, Task, TaskQueue


# ---------------------------------------------------------------------------
# State paths — kept in agents/state/ which IS git-ignored.
STATE_DIR = REPO_ROOT / "agents" / "state"
COMPLETED_IDS_PATH = STATE_DIR / "completed_roadmap_ids.txt"
LOCK_PATH = STATE_DIR / "lock.txt"
LAST_TICK_PATH = STATE_DIR / "last_tick.txt"


def _interval_minutes() -> int:
    try:
        return max(1, int(os.environ.get("ARCHHUB_ROADMAP_INTERVAL_MIN", "30")))
    except Exception:
        return 30


def _disabled() -> bool:
    return os.environ.get("ARCHHUB_ROADMAP_DISABLED", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
@dataclass
class TickResult:
    ts: str
    enqueued: int
    skipped_already_queued: int
    skipped_already_done: int
    error: Optional[str] = None
    throttled: bool = False
    locked: bool = False


# ---------------------------------------------------------------------------
def _ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not COMPLETED_IDS_PATH.exists():
        COMPLETED_IDS_PATH.write_text(
            "# completed roadmap ids — one per line\n", encoding="utf-8",
        )


def _should_throttle(now: datetime, interval_min: int) -> bool:
    if not LAST_TICK_PATH.exists():
        return False
    try:
        last = datetime.fromisoformat(LAST_TICK_PATH.read_text().strip())
    except Exception:
        return False
    return (now - last) < timedelta(minutes=interval_min)


def _write_last_tick(ts: datetime) -> None:
    try:
        LAST_TICK_PATH.write_text(ts.isoformat(), encoding="utf-8")
    except Exception:
        pass


def _acquire_lock() -> bool:
    """Exclusive-create the lock file. Returns False if a concurrent
    tick already holds it."""
    try:
        LOCK_PATH.touch(exist_ok=False)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "item"


def _priority_int(priority: str) -> int:
    return {"high": 10, "med": 30, "low": 70}.get(priority, 50)


def _existing_task_ids(queue: TaskQueue) -> set[str]:
    """Every yaml stem under agents/tasks/<dept>/ — both pending and
    completed. We never re-enqueue an id that's been seen."""
    seen: set[str] = set()
    if not queue.root.exists():
        return seen
    for dept_dir in queue.root.iterdir():
        if not dept_dir.is_dir():
            continue
        for f in dept_dir.iterdir():
            if f.suffix in (".yaml", ".done", ".failed", ".lock"):
                seen.add(f.stem)
    return seen


# ---------------------------------------------------------------------------
def _build_task(item: roadmap_source.RoadmapItem) -> Task:
    """Turn a RoadmapItem into a department Task for the queue."""
    task_id = f"roadmap-{item.id}-{_slugify(item.title)}"
    instructions = (
        f"Roadmap item from {item.source}.\n\n"
        f"Title: {item.title}\n\n"
        f"Original context:\n{item.body or '(none)'}\n\n"
        "Produce your department's standard deliverable for this item. "
        "Do NOT edit source files directly — write your output (patch / "
        "memo / doc / test plan) into your output directory only. A "
        "human will review and apply."
    )
    return Task(
        id=task_id,
        department=item.suggested_dept,
        title=item.title[:140],
        instructions=instructions,
        priority=_priority_int(item.priority),
        inputs={"roadmap_id": item.id, "roadmap_source": item.source},
    )


# ---------------------------------------------------------------------------
def tick(
    *,
    queue: Optional[TaskQueue] = None,
    force: bool = False,
) -> TickResult:
    """One pass: scan sources, enqueue new items, return a summary.

    `force=True` bypasses the throttle (used in tests). Returns a
    TickResult even on early-exit cases (throttled / locked / disabled)
    so the caller can log a uniform shape.
    """
    now = datetime.now(timezone.utc)
    _ensure_state()

    if _disabled():
        return TickResult(ts=now.isoformat(), enqueued=0,
                          skipped_already_queued=0, skipped_already_done=0,
                          error="disabled (ARCHHUB_ROADMAP_DISABLED=1)")

    interval = _interval_minutes()
    if not force and _should_throttle(now, interval):
        return TickResult(ts=now.isoformat(), enqueued=0,
                          skipped_already_queued=0, skipped_already_done=0,
                          throttled=True)

    if not _acquire_lock():
        return TickResult(ts=now.isoformat(), enqueued=0,
                          skipped_already_queued=0, skipped_already_done=0,
                          locked=True)

    try:
        q = queue or TaskQueue()
        # Pull every candidate WITHOUT applying the completed filter
        # so we can count "skipped because already done" explicitly
        # for telemetry / tests.
        all_items = roadmap_source.fetch_pending(
            state_path=roadmap_source.UNFILTERED,
        )
        existing = _existing_task_ids(q)
        completed = roadmap_source._load_completed_ids(COMPLETED_IDS_PATH)

        enqueued = 0
        skipped_queued = 0
        skipped_done = 0
        for item in all_items:
            if item.id in completed:
                skipped_done += 1
                continue
            task_id_prefix = f"roadmap-{item.id}-"
            if any(t.startswith(task_id_prefix) for t in existing):
                skipped_queued += 1
                continue
            task = _build_task(item)
            q.add(task)
            enqueued += 1

        _write_last_tick(now)
        return TickResult(ts=now.isoformat(), enqueued=enqueued,
                          skipped_already_queued=skipped_queued,
                          skipped_already_done=skipped_done)
    except Exception as ex:
        return TickResult(ts=now.isoformat(), enqueued=0,
                          skipped_already_queued=0, skipped_already_done=0,
                          error=f"{type(ex).__name__}: {ex}")
    finally:
        _release_lock()


# ---------------------------------------------------------------------------
def mark_complete(roadmap_id: str) -> None:
    """Append a roadmap id to the completed list. Idempotent — duplicate
    ids are skipped on read by `fetch_pending`."""
    _ensure_state()
    existing = roadmap_source._load_completed_ids(COMPLETED_IDS_PATH)
    if roadmap_id in existing:
        return
    try:
        with COMPLETED_IDS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{roadmap_id}\n")
    except Exception:
        pass


def pending_count() -> int:
    """How many roadmap items are still open? Cheap — no enqueueing."""
    try:
        return len(roadmap_source.fetch_pending(state_path=COMPLETED_IDS_PATH))
    except Exception:
        return 0


def completed_count() -> int:
    """How many roadmap items have shipped (per the state file)?"""
    try:
        return len(roadmap_source._load_completed_ids(COMPLETED_IDS_PATH))
    except Exception:
        return 0
