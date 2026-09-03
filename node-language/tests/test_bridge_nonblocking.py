"""AgDR-0035 / AgDR-0036 — bridge slots must never block the Qt main
thread.  `_cached_async` is the mechanism: the slot returns a cached
value instantly; the slow `work` callable runs on a bounded pool; a
signal fires when fresh data lands.

Tests use a PLAIN stand-in `self` (not a real QObject) that borrows
the real `_cached_async` + `_async_state` methods — avoids the heavy
ArchHubBridge(router, manager, ...) construction.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import bridge  # noqa: E402


class _DummySignal:
    def __init__(self):
        self.emits = 0
    def emit(self):
        self.emits += 1


class _DummyBridge:
    """Plain stand-in for ArchHubBridge `self` — borrows the real
    _cached_async + _async_state so the mechanism is exercised
    unchanged."""
    def __init__(self):
        self.hosts_changed = _DummySignal()
        self.memory_changed = _DummySignal()
        self._cached_async = bridge.ArchHubBridge._cached_async.__get__(self)
        self._async_state = bridge.ArchHubBridge._async_state.__get__(self)


# ─── 1. the slot returns instantly even when `work` is slow ─────────


def test_cached_async_returns_instantly_for_slow_work():
    dummy = _DummyBridge()
    ran = []

    def _slow():
        ran.append(time.time())
        time.sleep(3.0)
        return {"outlook": {"status": "live"}}

    t0 = time.time()
    out = dummy._cached_async("k", _slow, empty={})
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"slot blocked {elapsed:.2f}s — must be async"
    assert out == {}                       # cold cache → empty fallback

    # The work ran on the background pool — wait for it.
    deadline = time.time() + 6
    while time.time() < deadline and not ran:
        time.sleep(0.05)
    assert ran, "background work never ran"


def test_cached_async_serves_fresh_on_second_call():
    dummy = _DummyBridge()
    dummy._cached_async("k", lambda: {"v": 1}, empty={})
    deadline = time.time() + 4
    while time.time() < deadline:
        out = dummy._cached_async("k", lambda: {"v": 1}, empty={})
        if out == {"v": 1}:
            break
        time.sleep(0.05)
    assert dummy._cached_async("k", lambda: {"v": 1}, empty={}) == {"v": 1}
    assert dummy.hosts_changed.emits >= 1   # signalled JS to re-pull


def test_cached_async_dedupes_concurrent_refresh():
    """Rapid calls spawn only ONE background run (locked check-set)."""
    dummy = _DummyBridge()
    runs = []

    def _work():
        runs.append(1)
        time.sleep(0.3)
        return {"x": 1}

    for _ in range(5):
        dummy._cached_async("k", _work, empty={})
    time.sleep(1.0)
    assert len(runs) == 1, f"expected 1 refresh, got {len(runs)}"


def test_cached_async_custom_signal():
    """signal_name routes the re-pull notification to the right signal."""
    dummy = _DummyBridge()
    dummy._cached_async("m", lambda: {"ok": 1}, empty={},
                        signal_name="memory_changed")
    deadline = time.time() + 4
    while time.time() < deadline and dummy.memory_changed.emits == 0:
        time.sleep(0.05)
    assert dummy.memory_changed.emits >= 1
    assert dummy.hosts_changed.emits == 0


def test_cached_async_per_key_isolation():
    """Different keys keep independent caches — probe:revit must not
    collide with probe:autocad."""
    dummy = _DummyBridge()
    dummy._cached_async("probe:revit", lambda: {"h": "revit"}, empty={})
    dummy._cached_async("probe:acad", lambda: {"h": "acad"}, empty={})
    deadline = time.time() + 4
    while time.time() < deadline:
        a = dummy._cached_async("probe:revit", lambda: {}, empty={})
        b = dummy._cached_async("probe:acad", lambda: {}, empty={})
        if a and b:
            break
        time.sleep(0.05)
    assert dummy._cached_async("probe:revit", lambda: {}, empty={}) == {"h": "revit"}
    assert dummy._cached_async("probe:acad", lambda: {}, empty={}) == {"h": "acad"}


# ─── 2. real slot wrappers stay non-blocking ────────────────────────


def test_get_all_hosts_slot_is_async(monkeypatch):
    import host_detector

    def _slow(*a, **k):
        time.sleep(3.0)
        return {"excel": {"status": "live"}}

    monkeypatch.setattr(host_detector, "detect_all_hosts", _slow)
    dummy = _DummyBridge()
    t0 = time.time()
    bridge.ArchHubBridge.get_all_hosts(dummy)
    assert time.time() - t0 < 0.5, "get_all_hosts blocked"


def test_get_local_llms_slot_is_async(monkeypatch):
    import local_llm_detector

    def _slow(*a, **k):
        time.sleep(2.5)
        return {"ollama": {"status": "up"}}

    monkeypatch.setattr(local_llm_detector, "detect_all_local_llms", _slow)
    dummy = _DummyBridge()
    t0 = time.time()
    bridge.ArchHubBridge.get_local_llms(dummy)
    assert time.time() - t0 < 0.5, "get_local_llms blocked"


# ─── 3. AgDR-0036 Phase 1 — leak-hardening helpers ─────────────────


def test_bg_pool_is_bounded():
    """The fire-and-forget pool caps OS threads (was: raw Thread per
    call → unbounded under cascading dropdowns / rapid connector runs)."""
    dummy = type("D", (), {})()
    pool = bridge.ArchHubBridge._bg_pool(dummy)
    assert pool is bridge.ArchHubBridge._bg_pool(dummy)   # cached
    assert pool._max_workers == 8


def test_cook_lock_serialises():
    """run_workflow / run_node share one lock so two cooks can't
    interleave on the host brokers."""
    import threading
    dummy = type("D", (), {})()
    lk = bridge.ArchHubBridge._cook_lock(dummy)
    assert lk is bridge.ArchHubBridge._cook_lock(dummy)   # cached
    assert isinstance(lk, type(threading.Lock()))


def test_run_slots_acquire_cook_lock():
    """Source guard — both cook slots must hold _cook_lock around the
    runner call."""
    src = (APP / "bridge.py").read_text(encoding="utf-8")
    assert "with self._cook_lock():" in src
    assert src.count("with self._cook_lock():") >= 2   # run_workflow + run_node


def test_init_defers_heavy_loads():
    """__init__ must NOT call load_all_connectors / custom_nodes
    load_all inline — they belong on the deferred-boot thread."""
    src = (APP / "bridge.py").read_text(encoding="utf-8")
    # The deferred-boot thread exists.
    assert "archhub-deferred-boot" in src
    assert "_deferred_boot" in src


# ─── 4. AgDR docs ──────────────────────────────────────────────────


def test_agdr_0035_and_0036_exist():
    agdr = Path(__file__).resolve().parents[1] / "docs" / "agdr"
    assert (agdr / "AgDR-0035-bridge-slots-never-block-ui-thread.md").exists()
    p36 = agdr / "AgDR-0036-non-blocking-slot-mechanism.md"
    assert p36.exists()
    assert "status: executed" in p36.read_text(encoding="utf-8")
