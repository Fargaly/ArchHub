"""Tests for agents.dispatcher — picks + runs the next pending task.

Live production module (archhub-agents) with ZERO prior coverage (TCI-02).
These drive the real Dispatcher logic with a FAKE department agent (so no
Ollama / network is touched): claim → execute → mark_done on success,
mark_failed on failure, swallow agent exceptions into a failed receipt, and
skip tasks whose department is unknown.
"""
from __future__ import annotations

import agents.dispatcher as dispatcher_mod
from agents.base import AgentResult
from agents.dispatcher import Dispatcher
from agents.queue import Task, TaskQueue


class _FakeAgent:
    """Stands in for a department Agent without touching Ollama."""

    def __init__(self, result=None, raises: bool = False):
        self._result = result
        self._raises = raises
        self.executed = []

    def execute(self, task: Task) -> AgentResult:
        self.executed.append(task.id)
        if self._raises:
            raise RuntimeError("agent blew up")
        return self._result


def _wire_department(monkeypatch, name: str, agent: _FakeAgent):
    """Register `name` as a known department resolving to `agent`."""
    monkeypatch.setattr(dispatcher_mod, "DEPARTMENTS", {name: object}, raising=True)
    monkeypatch.setattr(dispatcher_mod, "get_department",
                        lambda dept: agent, raising=True)


def _task(tid: str, dept: str, priority: int = 50, inputs=None) -> Task:
    return Task(id=tid, department=dept, title=f"t-{tid}",
                instructions="go", priority=priority, inputs=inputs or {})


def _queue(tmp_path) -> TaskQueue:
    return TaskQueue(root=tmp_path / "q")


def test_run_one_success_marks_done(monkeypatch, tmp_path):
    agent = _FakeAgent(result=AgentResult(True, "did it"))
    _wire_department(monkeypatch, "eng", agent)
    q = _queue(tmp_path)
    q.add(_task("ok1", "eng"))

    d = Dispatcher(queue=q)
    res = d.run_one(department="eng")

    assert res is not None and res.success is True
    assert agent.executed == ["ok1"]
    assert (q.root / "eng" / "ok1.done").exists(), "success must write a .done receipt"
    assert not (q.root / "eng" / "ok1.failed").exists()


def test_run_one_failure_marks_failed(monkeypatch, tmp_path):
    agent = _FakeAgent(result=AgentResult(False, "nope", error="bad input"))
    _wire_department(monkeypatch, "eng", agent)
    q = _queue(tmp_path)
    q.add(_task("bad1", "eng"))

    d = Dispatcher(queue=q)
    res = d.run_one(department="eng")

    assert res is not None and res.success is False
    failed = q.root / "eng" / "bad1.failed"
    assert failed.exists(), "a failed agent result must write a .failed receipt"
    assert "bad input" in failed.read_text(encoding="utf-8")


def test_run_one_agent_exception_becomes_failed_not_crash(monkeypatch, tmp_path):
    """An exception inside the agent must NOT crash the dispatcher daemon — it
    is caught and turned into a typed failed result + receipt."""
    agent = _FakeAgent(raises=True)
    _wire_department(monkeypatch, "eng", agent)
    q = _queue(tmp_path)
    q.add(_task("boom1", "eng"))

    d = Dispatcher(queue=q)
    res = d.run_one(department="eng")

    assert res is not None and res.success is False
    assert "agent blew up" in (res.error or "")
    assert (q.root / "eng" / "boom1.failed").exists()


def test_run_one_skips_unknown_department(monkeypatch, tmp_path):
    """A task for a department not in DEPARTMENTS is left untouched (no claim,
    no run) so a human can fix the task file."""
    agent = _FakeAgent(result=AgentResult(True, "should not run"))
    _wire_department(monkeypatch, "eng", agent)  # only 'eng' is known
    q = _queue(tmp_path)
    q.add(_task("ghost", "marketing"))  # unknown dept

    d = Dispatcher(queue=q)
    res = d.run_one()  # any department

    assert res is None, "unknown-department task must not run"
    assert agent.executed == []
    assert not (q.root / "marketing" / "ghost.lock").exists(), (
        "an unknown-department task must NOT be claimed"
    )
    # The task file survives for a human to fix.
    assert (q.root / "marketing" / "ghost.yaml").exists()


def test_run_one_returns_none_on_empty_queue(monkeypatch, tmp_path):
    agent = _FakeAgent(result=AgentResult(True, "x"))
    _wire_department(monkeypatch, "eng", agent)
    d = Dispatcher(queue=_queue(tmp_path))
    assert d.run_one(department="eng") is None


def test_run_one_flushes_roadmap_id_on_success(monkeypatch, tmp_path):
    """A roadmap-sourced task calls roadmap_dispatcher.mark_complete on success
    so it isn't re-enqueued next tick."""
    agent = _FakeAgent(result=AgentResult(True, "done"))
    _wire_department(monkeypatch, "eng", agent)
    q = _queue(tmp_path)
    q.add(_task("rm1", "eng", inputs={"roadmap_id": "R-42"}))

    marked = []
    import sys
    import types as _types
    fake_rd = _types.ModuleType("agents.roadmap_dispatcher")
    fake_rd.mark_complete = lambda rid: marked.append(rid)
    monkeypatch.setitem(sys.modules, "agents.roadmap_dispatcher", fake_rd)

    Dispatcher(queue=q).run_one(department="eng")
    assert marked == ["R-42"], "roadmap_id must be flushed via mark_complete on success"


def test_run_round_runs_each_known_department(monkeypatch, tmp_path):
    agent = _FakeAgent(result=AgentResult(True, "ok"))
    # Two known departments, both resolving to the same fake agent.
    monkeypatch.setattr(dispatcher_mod, "DEPARTMENTS",
                        {"eng": object, "rnd": object}, raising=True)
    monkeypatch.setattr(dispatcher_mod, "get_department",
                        lambda dept: agent, raising=True)
    q = _queue(tmp_path)
    q.add(_task("e1", "eng"))
    q.add(_task("r1", "rnd"))

    results = Dispatcher(queue=q).run_round()
    assert set(results.keys()) == {"eng", "rnd"}
    assert all(r.success for r in results.values())
