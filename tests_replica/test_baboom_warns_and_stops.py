"""BABOOM watches and warns on real events; a Stop really ends an agent run.

Lane baboom-settings, 2026-09-24. On 35d3e8f BABOOM@Q@s directive had no path for
an agent session that stopped answering, a Run that failed or a host that
refused (the last-run record held only ran/answered/pending), and a native
agent that ignored interrupt and EOF kept running after Stop
(cooperative_stop_timeout, process alive). These courts hold the repair:

- warnings derive from the one presence source (graph presence leases) and the
  run itself, carry runtime and engine names only, and reach the directive;
- NativeWorkshopProcess.stop kills the owned tree once the cooperative budget
  is spent, and a new run can start afterwards (resume).
"""
from __future__ import annotations

import json
import sys
import time
import uuid

import pytest

from nodelang import universal_pipeline
from nodelang.cell_runtime_presence import (
    bootstrap_runtime_presence_protocol,
    renew_runtime_presence,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_baboom_companion_directive,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore
from nodelang.universal_pipeline import create_engine_node, run_universal_pipeline


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def test_a_failed_run_and_a_refusing_connector_become_baboom_warnings(graph):
    store, registry = graph
    context = registry.authorization.session.context()
    failing = create_engine_node(store, registry, title="Fails", engine="library.think")["root"]
    refusing = create_engine_node(store, registry, title="Refuses", engine="library.embed", x=640.0, y=420.0)["root"]

    def raises(params, feeds):
        raise RuntimeError("private detail that must not reach BABOOM")

    def refuses(params, feeds):
        return {"out": [], "ok": False, "reason": "C:/private/path refused"}, "C:/private/path refused"

    run_universal_pipeline(store, registry, effect_engines={"library.think": raises, "library.embed": refuses},
                           only_roots=[failing, refusing])
    held = universal_pipeline.last_pipeline_run()
    assert held["failed"] == ["library.think"] and held["refused"] == ["library.embed"]
    directive = project_universal_baboom_companion_directive(store, registry, authentication_context=context)
    assert directive["motion"] == "warning" and directive["action"] == "status", directive
    assert directive["compact_message"] == directive["message"], "the companion panel carries it"
    assert directive["message"] == "The last run failed in library.think. (+1 more)", directive
    text = json.dumps(directive, sort_keys=True)
    assert "private" not in text, "engine names only, never the refusal text"

    def answers(params, feeds):
        return {"out": "ok"}, "answered"

    run_universal_pipeline(store, registry, effect_engines={"library.think": answers, "library.embed": answers},
                           only_roots=[failing, refusing])
    calm = project_universal_baboom_companion_directive(store, registry, authentication_context=context)
    assert calm["motion"] != "warning" and "run failed" not in calm["message"], calm
    # A Workshop card refusing the ungated canvas Run is its designed answer, not a failure.
    from nodelang.workshop_workflow import approval_required
    run_universal_pipeline(store, registry, effect_engines={"library.think": approval_required},
                           only_roots=[failing])
    assert universal_pipeline.last_pipeline_run()["failed"] == []


def test_a_session_whose_graph_lease_lapsed_is_reported_gone():
    from nodelang.cell_runtime_presence import list_lapsed_runtime_presences
    store = CellStore()
    store.commit(store.revision, create=(
        Cell("app:agent-session:runtime:gone", NULL_CELL_ID, NULL_CELL_ID, b"runtime-session"),
        Cell("device-custody:sha256:gone", NULL_CELL_ID, NULL_CELL_ID, b"device-custody"),
    ))
    protocol = bootstrap_runtime_presence_protocol(store)
    renew_runtime_presence(store, protocol, agent_session_root="app:agent-session:runtime:gone",
        device_custody_root="device-custody:sha256:gone", runtime="claude", now=1000.0, lease_seconds=60.0)
    snapshot = store.snapshot()
    assert list_lapsed_runtime_presences(snapshot, protocol, now=1059.0) == ()
    lapsed = list_lapsed_runtime_presences(snapshot, protocol, now=1100.0)
    assert [presence.runtime for presence in lapsed] == ["claude"]
    assert list_lapsed_runtime_presences(snapshot, protocol, now=1100.0 + 3600) == (), "old lapses age out"


def test_the_directive_names_a_gone_session_from_the_context_lens():
    from nodelang.universal_application import _baboom_runtime_warnings
    assert _baboom_runtime_warnings({"agents": {"gone": ["claude"]}, "canvas": {}}) == [
        "A claude session stopped answering."]
    assert _baboom_runtime_warnings({"agents": {"working": []}, "canvas": {"ran": 2}}) == []


def _stubborn_launch(tmp_path):
    from nodelang.native_workshop_process import NativeWorkshopLaunch
    session = str(uuid.uuid4())
    # A child that ignores interrupt frames and stdin EOF: it reads nothing and sleeps.
    return NativeWorkshopLaunch(
        argv=(sys.executable, "-c", "import time; time.sleep(120)"),
        env=(("SYSTEMROOT", __import__("os").environ.get("SYSTEMROOT", "C:/Windows")),),
        cwd=str(tmp_path), runtime="claude", external_session_id=session,
        max_input_bytes=64 * 1024, max_output_bytes=64 * 1024, max_event_bytes=16 * 1024,
        max_events=16, max_process_bytes=512 * 1024 * 1024,
        startup_timeout_seconds=30.0, turn_timeout_seconds=30.0, lifetime_seconds=60.0,
        stop_timeout_seconds=2.0,
    )


def test_stop_ends_an_agent_that_ignores_interrupt_and_a_new_run_can_start(tmp_path):
    import psutil
    from nodelang.native_workshop_process import NativeWorkshopProcess
    launch = _stubborn_launch(tmp_path)
    first = NativeWorkshopProcess(launch)
    started = first.start()
    pid = started["pid"]
    try:
        assert started["process_alive"] is True
        stopped = first.stop(timeout_seconds=1.0)
        assert stopped["process_alive"] is False, stopped
        assert stopped["error_code"] == "forced_stop" and stopped["requires_reconciliation"] is True
        assert stopped["drained"] is True, stopped
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        # Resume: the same session identity starts again once the old run is gone.
        second = NativeWorkshopProcess(launch)
        again = second.start()
        assert again["process_alive"] is True and again["pid"] != pid
        assert second.stop(timeout_seconds=1.0)["process_alive"] is False
    finally:
        for candidate in (pid,):
            try:
                psutil.Process(candidate).kill()
            except psutil.NoSuchProcess:
                pass
