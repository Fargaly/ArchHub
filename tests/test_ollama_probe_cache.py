"""GUI-idle-stall residual fix (2026-06-02) — `list_local_models()` is cached
AND refreshes off-thread, so the synchronous Ollama probe never runs on the Qt
GUI thread.

The Qt MainThread was caught (py-spy) parked in `create_connection` under
`list_local_models` (Ollama `/api/tags`, 2 s timeout, no cache), reached on the
GUI thread from `llm_router.configured_providers` / `ollama_models` /
`has_credentials` via the `get_providers` @pyqtSlot, the model-picker, and
timer-driven status refreshes. With Ollama down, several of those fire in one UI
refresh and each paid the full cold socket cost, stacking toward ~7 s and
flipping the window to "Not Responding" periodically.

The fix (a) caches the result for a short TTL so a burst of calls shares one
value, and (b) refreshes BEHIND on a daemon thread so the urlopen never runs on
the caller's GUI thread. These tests guard that the default path is
non-blocking, the background refresher coalesces, repeated calls don't re-probe,
`pass_through=True` forces a synchronous refresh, and the TTL still expires.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import llm_providers.ollama_client as oc  # noqa: E402


def _join_refreshers(timeout=3.0):
    for t in list(threading.enumerate()):
        if t.name == "ollama-models-refresh":
            t.join(timeout)


def _reset_cache():
    # Drain any refresher a prior test left running (daemon threads + module
    # globals bleed across tests otherwise), THEN clear state.
    _join_refreshers()
    with oc._cache_lock:
        oc._cache_val = None
        oc._cache_at = 0.0
        oc._refresh_inflight = False


def test_default_path_never_blocks_on_a_slow_probe(monkeypatch):
    """THE stall guard: even if the underlying probe takes seconds, the
    default GUI-thread call must return effectively instantly (it serves the
    cache and refreshes behind). If this regresses, the Ollama probe is back on
    the Qt thread."""
    _reset_cache()

    def slow_probe():
        time.sleep(1.5)
        return ["qwen3"]

    monkeypatch.setattr(oc, "_probe_local_models", slow_probe)
    t0 = time.perf_counter()
    val = oc.list_local_models()           # cold cache -> [] immediately
    dt = time.perf_counter() - t0
    assert dt < 0.2, f"default path blocked {dt*1000:.0f}ms — probe is on the caller thread"
    assert val == []                        # nothing cached yet
    _join_refreshers()
    # bg fill landed; the next call serves it instantly (poll briefly to avoid
    # any thread-handoff timing flake).
    deadline = time.time() + 2.0
    while oc.list_local_models() != ["qwen3"] and time.time() < deadline:
        _join_refreshers(0.5)
    assert oc.list_local_models() == ["qwen3"]


def test_background_refresher_coalesces(monkeypatch):
    """A burst of stale reads (several hot paths in one UI refresh) must spawn
    exactly ONE background probe, not N."""
    _reset_cache()
    calls = {"n": 0}
    gate = threading.Event()

    def gated_probe():
        calls["n"] += 1
        gate.wait(2.0)            # hold the worker so the burst overlaps it
        return ["m"]

    monkeypatch.setattr(oc, "_probe_local_models", gated_probe)
    for _ in range(15):
        oc.list_local_models()    # all stale, all non-blocking
    assert calls["n"] == 1, f"expected 1 coalesced refresh, got {calls['n']}"
    gate.set()
    _join_refreshers()


def test_fresh_cache_is_served_without_reprobe(monkeypatch):
    """Within the TTL, calls return the cached value and never re-probe."""
    _reset_cache()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return ["llama3.1", "qwen3"]

    monkeypatch.setattr(oc, "_probe_local_models", probe)
    monkeypatch.setattr(oc, "_TTL_S", 100.0)
    oc.list_local_models(); _join_refreshers()   # fill cache (1 probe)
    first = oc.list_local_models()
    for _ in range(25):
        assert oc.list_local_models() == first
    assert calls["n"] == 1, f"cache not holding — {calls['n']} probes"


def test_pass_through_forces_a_synchronous_probe(monkeypatch):
    """An explicit refresh probes synchronously on the caller's thread (only
    ever a user-initiated refresh path, never the GUI timer)."""
    _reset_cache()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return [f"m{calls['n']}"]

    monkeypatch.setattr(oc, "_probe_local_models", probe)
    monkeypatch.setattr(oc, "_TTL_S", 100.0)
    got = oc.list_local_models(pass_through=True)
    assert calls["n"] == 1 and got == ["m1"]
    oc.list_local_models(pass_through=True)
    assert calls["n"] == 2


def test_cache_expires_after_ttl(monkeypatch):
    """Liveness preserved: once the TTL lapses the next call refreshes (behind),
    so a newly-started Ollama is picked up within ~_TTL_S."""
    _reset_cache()
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return ["x"]

    fake_now = {"t": 1000.0}
    monkeypatch.setattr(oc, "_probe_local_models", probe)
    monkeypatch.setattr(oc, "_TTL_S", 4.0)
    monkeypatch.setattr(oc.time, "monotonic", lambda: fake_now["t"])

    oc.list_local_models(); _join_refreshers()   # probe #1 at t=1000
    fake_now["t"] = 1003.0
    oc.list_local_models(); _join_refreshers()    # within TTL -> cached
    assert calls["n"] == 1
    fake_now["t"] = 1005.0                          # TTL lapsed
    oc.list_local_models(); _join_refreshers()    # refresh-behind -> probe #2
    assert calls["n"] == 2


def test_default_call_signature_unchanged(monkeypatch):
    """Existing callers call `list_local_models()` with no args — must still
    work and (after the bg fill) return the model-name list."""
    _reset_cache()
    monkeypatch.setattr(oc, "_probe_local_models", lambda: ["a", "b"])
    oc.list_local_models(); _join_refreshers()
    assert oc.list_local_models() == ["a", "b"]
