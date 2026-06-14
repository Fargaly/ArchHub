"""Regression guard — the ConnectorHealth poll-thread leak (2026-06-01).

Root cause (the 229-error teardown regression):
    `connector_health._probe_revit_multi()` called
    `revit_broker.list_sessions(prune=True)`, which runs a parallel 16-port
    range scan (`_discover_in_port_range`, a ThreadPoolExecutor whose __exit__
    joins every worker) where each worker probes `http://localhost:<port>` —
    dual-stack on Windows (::1 THEN 127.0.0.1), so a dead port costs 2× the
    timeout. Cold, that call measured ~2.4s. Run inside the 5s health poll
    thread's tick, it blocked the tick un-interruptibly for >2s, so
    `ConnectorHealth.stop()`'s 2s join timed out and the daemon survived test
    teardown — every later test that constructs a UI surface re-tripped the
    conftest `_stop_leaked_background_threads` assertion (225–229 errors).

    c98fd35 had added the join, but couldn't have known a single tick could
    outlast it. The mechanism fix bounds every probe to one
    PROBE_TIMEOUT_SECONDS so a tick always returns to its stop-event check
    well inside the join window.

These tests lock in the mechanism so the class cannot silently regress again:
  1. the poll thread's revit probe takes the bounded `live_session_count()`
     path and NEVER calls the unbounded `list_sessions(prune=True)` scan;
  2. `_probe_revit_multi()` returns within the bounded budget even when every
     port is dead and the broker scan would be slow;
  3. a started monitor is provably stopped + joined by `shutdown()` — the
     unit-level twin of the conftest guard;
  4. a tick's dead-listener diagnosis costs AT MOST ONE process enumeration
     (the shared proc_utils TTL snapshot) — never one `tasklist /FI` spawn
     per family, which at ~0.6s each loaded made ticks flake near 3s.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import connector_health  # noqa: E402
import proc_utils  # noqa: E402
import revit_broker  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_monitor():
    """Never let these tests leak their own monitor into later tests."""
    yield
    connector_health.shutdown()


def test_revit_probe_uses_bounded_path_not_port_range_scan(monkeypatch):
    """The poll thread's revit probe must call the bounded
    `live_session_count()` helper, never `list_sessions(prune=True)` — the
    latter is the unbounded 16-port dual-stack scan that wedged the tick."""
    calls = {"live": 0, "list": 0}

    def _fake_live(*a, **k):
        calls["live"] += 1
        return 0

    def _boom_list(*a, **k):  # pragma: no cover - must never run on poll thread
        calls["list"] += 1
        raise AssertionError(
            "connector_health probed revit via the unbounded "
            "list_sessions(prune=True) port scan — the leak path. It must use "
            "the bounded revit_broker.live_session_count() helper instead."
        )

    monkeypatch.setattr(revit_broker, "live_session_count", _fake_live)
    monkeypatch.setattr(revit_broker, "list_sessions", _boom_list)
    # No live session + bounded single-port fallback that says 'down'.
    monkeypatch.setattr(connector_health, "_probe_listener",
                        lambda family: (False, "closed"))

    ok, _err, sessions = connector_health._probe_revit_multi()

    assert calls["live"] == 1, "the bounded live_session_count path was not taken"
    assert calls["list"] == 0, "the unbounded port-range scan was taken (leak path)"
    assert ok is False and sessions == 0


def test_full_tick_is_bounded_when_all_ports_dead(monkeypatch):
    """A single poll tick with every port dead must finish fast — the
    invariant that lets stop()'s join win. We pin each probe to a tiny budget
    and assert the whole tick stays inside a few probe-widths, proving no
    unbounded dual-stack scan sneaks in."""
    monkeypatch.setattr(connector_health, "PROBE_TIMEOUT_SECONDS", 0.05)
    # Empty sessions dir → live_session_count returns 0 with ~no cost.
    monkeypatch.setattr(revit_broker, "SESSIONS_DIR",
                        Path("does-not-exist-zzz"))
    # Make the BOUNDED primitives instant so the measurement reflects only
    # control flow — never real-socket connect/teardown jitter (which made a
    # wall-clock ceiling flaky under full-suite load). Process listing is one
    # of those bounded primitives: un-stubbed, the dead-listener diagnosis
    # path (state() → _process_running per family + the autocad self-heal
    # check) spawned one tasklist per family — ~0.6s each on a loaded box,
    # five per tick = the ~2.4–3.2s flake this test showed on loaded Windows.
    # That cost is bounded (each spawn has its own 2s timeout), so it is NOT
    # the regression this test guards; test_tick_costs_at_most_one_process_
    # enumeration below guards it instead. The regression we DO guard does
    # not go through these instant stubs: it goes through
    # revit_broker.list_sessions(prune=True) → _discover_in_port_range, a real
    # 16-port dual-stack scan (~2.4s) that this test leaves un-stubbed. So a
    # regressed _probe_revit_multi still blows seconds past the 2.0s
    # tripwire, while the fixed bounded path returns in ~0.
    monkeypatch.setattr(connector_health, "_port_open",
                        lambda host, port, timeout: False)
    monkeypatch.setattr(revit_broker, "_probe", lambda port, **k: False)
    monkeypatch.setattr(connector_health, "_process_running",
                        lambda name: False)
    ch = connector_health.ConnectorHealth()
    t0 = time.perf_counter()
    ch._tick_once()
    elapsed = time.perf_counter() - t0
    # Generous tripwire: fails hard on the multi-second port-range scan that
    # regressed, immune to sub-second scheduler jitter on a loaded CI box.
    assert elapsed < 2.0, (
        f"a tick with all ports dead took {elapsed:.2f}s — an unbounded probe "
        f"(dual-stack localhost / port-range scan) regressed"
    )


def test_tick_costs_at_most_one_process_enumeration(monkeypatch):
    """Mechanism guard for the shared process snapshot: a full tick must cost
    AT MOST ONE process enumeration. Before proc_utils' TTL snapshot, every
    dead family's diagnosis (state() → _process_running) plus the autocad
    self-heal check each spawned its own `tasklist /FI` — five spawns/tick at
    ~0.6s each loaded was the ~2.4–3.2s flake in
    test_full_tick_is_bounded_when_all_ports_dead. Sockets are stubbed
    instant exactly as there, but `_process_running` is deliberately NOT
    stubbed: the real delegation chain (connector_health._process_running →
    proc_utils.any_process_running → process_names) is what gets counted."""
    monkeypatch.setattr(connector_health, "PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(revit_broker, "SESSIONS_DIR",
                        Path("does-not-exist-zzz"))
    monkeypatch.setattr(connector_health, "_port_open",
                        lambda host, port, timeout: False)
    monkeypatch.setattr(revit_broker, "_probe", lambda port, **k: False)

    counter = {"n": 0}

    def _counting_enumeration(*a, **k):
        counter["n"] += 1
        return frozenset()   # nothing running → every family 'host_offline'

    monkeypatch.setattr(proc_utils, "_enumerate_process_names",
                        _counting_enumeration)
    # Cold cache so the tick's FIRST check is the one allowed enumeration.
    proc_utils._reset_process_snapshot_for_tests()
    try:
        connector_health.ConnectorHealth()._tick_once()
        assert counter["n"] <= 1, (
            f"a single tick performed {counter['n']} process enumerations — "
            f"per-call process enumeration regressed (one tasklist spawn per "
            f"_process_running call, 5/tick at ~0.6s each, was the "
            f"loaded-Windows flake)"
        )
    finally:
        # Drop the poisoned empty snapshot — inside the TTL a later test
        # would otherwise see every host process as not-running.
        proc_utils._reset_process_snapshot_for_tests()


def test_shutdown_stops_and_joins_the_poll_thread(monkeypatch):
    """`shutdown()` must leave NO live ConnectorHealth thread — the unit twin
    of the conftest leak guard. Make every probe instant so the loop spins
    quickly, then assert the daemon is gone right after shutdown()."""
    monkeypatch.setattr(connector_health, "PROBE_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(connector_health, "_probe_listener",
                        lambda family: (False, "closed"))
    monkeypatch.setattr(connector_health, "_probe_revit_multi",
                        lambda: (False, "closed", 0))

    inst = connector_health.instance()  # starts the poll thread
    # Give the loop a moment to actually enter a tick.
    time.sleep(0.05)
    assert any(t.name == "ConnectorHealth" and t.is_alive()
               for t in threading.enumerate()), "monitor never started"

    connector_health.shutdown()

    survivors = [t for t in threading.enumerate()
                 if t.name == "ConnectorHealth" and t.is_alive()]
    assert not survivors, (
        f"shutdown() did not stop+join the poll thread: {survivors} — the leak "
        f"that produced the 229 teardown errors"
    )
    assert connector_health._INSTANCE is None, "shutdown() did not drop the singleton"
