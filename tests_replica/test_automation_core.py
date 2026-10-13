from __future__ import annotations

import nodelang.core as core
from nodelang.automation import (
    AutomationEngine,
    baboom_automation_candidates,
    create_automation,
    create_trigger_node,
    missing_host_event_paths,
    pause_automation,
    record_manual_run,
    run_history,
)


class FakeClock:
    def __init__(self, now=0):
        self.value = float(now)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeFs:
    def __init__(self):
        self.tokens = {}

    def snapshot(self, path):
        return self.tokens.get(path)

    def change(self, path, token):
        self.tokens[path] = token


class FakeAuth:
    def __init__(self, sessions=()):
        self.sessions = set(sessions)

    def is_browser_session(self, session):
        return session in self.sessions


def _runner(calls, result=None):
    def run(graph_id, payload):
        calls.append((graph_id, payload))
        return dict(result or {"outputs": {"ok": True}})
    return run


def test_schedule_fires_and_records_run():
    store = core.Store()
    clock = FakeClock(10)
    calls = []
    trig = create_trigger_node(store, "schedule", {"every_seconds": 60, "start_at": 10})
    auto = create_automation(store, graph_id="graph-a", trigger_ids=[trig])

    engine = AutomationEngine(store, runner=_runner(calls), clock=clock)
    engine.boot()
    fired = engine.tick()

    assert len(fired) == 1
    assert calls == [("graph-a", {})]
    assert run_history(store, auto)[0]["status"] == "ok"


def test_schedule_survives_restart_and_resumes():
    store = core.Store()
    clock = FakeClock(10)
    calls = []
    trig = create_trigger_node(store, "schedule", {"every_seconds": 30, "start_at": 10})
    auto = create_automation(store, graph_id="graph-a", trigger_ids=[trig])
    AutomationEngine(store, runner=_runner(calls), clock=clock).boot()
    flat = store.dump()

    restored = core.Store.load(flat)
    engine = AutomationEngine(restored, runner=_runner(calls), clock=clock)
    engine.boot()
    engine.tick()

    assert len(calls) == 1
    assert run_history(restored, auto)[0]["trigger"] == "schedule"


def test_missed_run_policy_skip_or_run_once():
    skipped = core.Store()
    skip_trig = create_trigger_node(skipped, "schedule", {"every_seconds": 30, "start_at": 10})
    create_automation(skipped, graph_id="skip", trigger_ids=[skip_trig], missed_policy="skip")
    skip_calls = []
    AutomationEngine(skipped, runner=_runner(skip_calls), clock=FakeClock(100)).boot()
    AutomationEngine(skipped, runner=_runner(skip_calls), clock=FakeClock(100)).tick()

    once = core.Store()
    once_trig = create_trigger_node(once, "schedule", {"every_seconds": 30, "start_at": 10})
    create_automation(once, graph_id="once", trigger_ids=[once_trig], missed_policy="run_once")
    once_calls = []
    engine = AutomationEngine(once, runner=_runner(once_calls), clock=FakeClock(100))
    engine.boot()
    engine.tick()

    assert skip_calls == []
    assert once_calls == [("once", {})]


def test_file_change_triggers_once_after_debounce():
    store = core.Store()
    clock = FakeClock(0)
    fs = FakeFs()
    fs.change("C:/watched", "v1")
    calls = []
    trig = create_trigger_node(store, "file_changed", {"path": "C:/watched", "debounce_seconds": 5})
    create_automation(store, graph_id="graph-a", trigger_ids=[trig])
    engine = AutomationEngine(store, runner=_runner(calls), clock=clock, fs=fs)

    engine.tick()
    fs.change("C:/watched", "v2")
    engine.tick()
    clock.advance(5)
    engine.tick()
    engine.tick()

    assert calls == [("graph-a", {"path": "C:/watched"})]


def test_batch_runs_each_item_and_collects_results():
    store = core.Store()
    clock = FakeClock(1)
    calls = []
    trig = create_trigger_node(store, "schedule", {"every_seconds": 60, "start_at": 1})
    auto = create_automation(
        store,
        graph_id="outer",
        trigger_ids=[trig],
        batch={"subgraph_id": "sub", "items": ["L1", "L2", "L3"], "concurrency": 2},
    )

    AutomationEngine(store, runner=_runner(calls), clock=clock).boot()
    AutomationEngine(store, runner=_runner(calls), clock=clock).tick()
    summary = run_history(store, auto)[0]["outputs_summary"]

    assert [call[1]["item"] for call in calls] == ["L1", "L2", "L3"]
    assert summary["count"] == 3
    assert summary["concurrency"] == 2


def test_pause_stops_next_fire():
    store = core.Store()
    calls = []
    trig = create_trigger_node(store, "schedule", {"every_seconds": 60, "start_at": 0})
    auto = create_automation(store, graph_id="graph-a", trigger_ids=[trig])
    pause_automation(store, auto)

    engine = AutomationEngine(store, runner=_runner(calls), clock=FakeClock(0))
    engine.boot()
    engine.tick()

    assert calls == []
    assert run_history(store, auto) == []


def test_automated_host_write_without_grant_is_refused():
    store = core.Store()
    trig = create_trigger_node(store, "schedule", {"every_seconds": 60, "start_at": 0})
    auto = create_automation(store, graph_id="graph-a", trigger_ids=[trig])
    result = {"would_write_host": True, "required_grant": "revit-write"}

    engine = AutomationEngine(store, runner=_runner([], result), clock=FakeClock(0))
    engine.boot()
    engine.tick()

    history = run_history(store, auto)
    assert history[0]["status"] == "refused"
    assert history[0]["outputs_summary"]["reason"] == "revit-write"


def test_host_event_and_approval_granted_triggers_are_real_nodes():
    store = core.Store()
    calls = []
    host = create_trigger_node(store, "host_event", {"event": "revit.document_saved"})
    approval = create_trigger_node(store, "approval_granted", {"grant_id": "write-ok"})
    create_automation(store, graph_id="graph-a", trigger_ids=[host, approval])

    engine = AutomationEngine(store, runner=_runner(calls), clock=FakeClock(0))
    engine.emit_host_event("revit.document_saved", {"document": "a.rvt"})
    engine.grant_approval("write-ok")

    assert [call[1]["event"] if "event" in call[1] else call[1]["grant_id"] for call in calls] == [
        "revit.document_saved",
        "write-ok",
    ]


def test_unauthenticated_webhook_is_refused():
    store = core.Store()
    trig = create_trigger_node(store, "webhook", {"auth": {"token": "secret"}})
    auto = create_automation(store, graph_id="graph-a", trigger_ids=[trig])
    calls = []

    result = AutomationEngine(store, runner=_runner(calls), clock=FakeClock(0)).handle_webhook(auto)

    assert result["accepted"] is False
    assert result["status"] == "refused"
    assert calls == []


def test_baboom_manual_repeat_data_and_missing_host_events_are_exposed():
    store = core.Store()
    record_manual_run(store, "graph-a", {"level": 1})
    record_manual_run(store, "graph-a", {"level": 1})

    assert baboom_automation_candidates(store) == [{
        "graph_id": "graph-a",
        "input_hash": baboom_automation_candidates(store)[0]["input_hash"],
        "inputs": {"level": 1},
        "manual_runs": 2,
    }]
    assert "revit.document_saved" in missing_host_event_paths()
