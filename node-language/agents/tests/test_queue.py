"""Tests for agents.queue — the file-backed task queue.

This is a live production module (deployed as archhub-agents on Fly) with ZERO
prior test coverage (TCI-02). These exercise the real on-disk queue mechanics:
add → list_pending (priority order, lock/done/failed filtering) → atomic claim
→ mark_done / mark_failed, plus the Task (de)serialisation round-trip.
"""
from __future__ import annotations

from agents.queue import Task, TaskQueue, TaskStatus


def _task(tid: str, dept: str = "eng", priority: int = 50) -> Task:
    return Task(
        id=tid, department=dept, title=f"title-{tid}",
        instructions="do the thing", priority=priority,
    )


def test_task_roundtrip_to_from_dict():
    """Task survives the dict round-trip the queue uses to persist to YAML."""
    t = _task("t1", dept="rnd", priority=10)
    t.inputs = {"roadmap_id": "R-7"}
    back = Task.from_dict(t.to_dict())
    assert back.id == "t1"
    assert back.department == "rnd"
    assert back.priority == 10
    assert back.inputs == {"roadmap_id": "R-7"}
    assert back.status == TaskStatus.PENDING


def test_add_writes_yaml_and_lists_pending(tmp_queue):
    path = tmp_queue.add(_task("a1"))
    assert path.exists(), "add() must persist the task file to disk"
    pending = tmp_queue.list_pending()
    assert [t.id for t in pending] == ["a1"]


def test_list_pending_is_priority_ordered(tmp_queue):
    tmp_queue.add(_task("low", priority=90))
    tmp_queue.add(_task("high", priority=5))
    tmp_queue.add(_task("mid", priority=50))
    assert [t.id for t in tmp_queue.list_pending()] == ["high", "mid", "low"]


def test_claim_is_atomic_second_claim_fails(tmp_queue):
    t = _task("c1")
    tmp_queue.add(t)
    assert tmp_queue.claim(t) is True, "first claim should win"
    # Second claim of the same task must fail — the lock file already exists.
    assert tmp_queue.claim(t) is False, (
        "second claim must fail (atomic exclusive-create lock) — otherwise two "
        "dispatchers could run the same task"
    )


def test_claimed_task_drops_out_of_pending(tmp_queue):
    t = _task("c2")
    tmp_queue.add(t)
    tmp_queue.claim(t)
    assert "c2" not in [p.id for p in tmp_queue.list_pending()], (
        "a locked (claimed) task must not show up as pending"
    )


def test_mark_done_writes_receipt_and_clears_lock(tmp_queue):
    t = _task("d1")
    tmp_queue.add(t)
    tmp_queue.claim(t)
    tmp_queue.mark_done(t, "all good")
    dept_dir = tmp_queue.root / t.department
    assert (dept_dir / f"{t.id}.done").exists(), "mark_done must write a .done receipt"
    assert not (dept_dir / f"{t.id}.lock").exists(), "mark_done must release the lock"
    assert "d1" not in [p.id for p in tmp_queue.list_pending()]


def test_mark_failed_writes_receipt_and_excludes_from_pending(tmp_queue):
    t = _task("f1")
    tmp_queue.add(t)
    tmp_queue.claim(t)
    tmp_queue.mark_failed(t, "boom")
    dept_dir = tmp_queue.root / t.department
    failed = dept_dir / f"{t.id}.failed"
    assert failed.exists(), "mark_failed must write a .failed receipt"
    assert "boom" in failed.read_text(encoding="utf-8")
    assert "f1" not in [p.id for p in tmp_queue.list_pending()], (
        "a failed task must not be re-listed as pending"
    )


def test_list_pending_department_filter(tmp_queue):
    tmp_queue.add(_task("e1", dept="eng"))
    tmp_queue.add(_task("r1", dept="rnd"))
    assert [t.id for t in tmp_queue.list_pending(department="rnd")] == ["r1"]
