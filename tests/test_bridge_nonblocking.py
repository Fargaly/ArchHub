"""AgDR-0035 — get_all_hosts / get_local_llms must never block the
Qt main thread.

The slot returns (near-)instantly from a cache; the slow detector
runs on a background thread.

Tests call the slot methods with a PLAIN stand-in `self` (not a real
QObject) — the methods only setattr/getattr cache fields + emit a
stubbed signal, so a plain object is enough and avoids the heavy
ArchHubBridge(router, manager, ...) construction.
"""
from __future__ import annotations

import json
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
    """Plain stand-in for ArchHubBridge `self` — holds cache attrs +
    a hosts_changed signal, and borrows the real `_cached_async`
    method so get_all_hosts / get_local_llms run unchanged."""
    def __init__(self):
        self.hosts_changed = _DummySignal()
        # Bind the real helper onto this plain instance.
        self._cached_async = bridge.ArchHubBridge._cached_async.__get__(self)


def _call(method, dummy, *args):
    """Invoke an ArchHubBridge method with a plain `self`."""
    return getattr(bridge.ArchHubBridge, method)(dummy, *args)


# ─── 1. the slot returns fast even when the detector is slow ────────


def test_get_all_hosts_returns_instantly(monkeypatch):
    import host_detector
    slow_calls = []

    def _slow_detect(*a, **kw):
        slow_calls.append(time.time())
        time.sleep(3.0)
        return {"outlook": {"status": "live"}}

    monkeypatch.setattr(host_detector, "detect_all_hosts", _slow_detect)

    dummy = _DummyBridge()
    t0 = time.time()
    raw = _call("get_all_hosts", dummy)
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"slot blocked {elapsed:.2f}s — must be async"
    assert isinstance(json.loads(raw), dict)

    deadline = time.time() + 6
    while time.time() < deadline and not slow_calls:
        time.sleep(0.05)
    assert slow_calls, "background detector never ran"


def test_get_all_hosts_serves_cache_on_second_call(monkeypatch):
    import host_detector
    monkeypatch.setattr(host_detector, "detect_all_hosts",
                        lambda *a, **k: {"excel": {"status": "live"}})
    dummy = _DummyBridge()
    _call("get_all_hosts", dummy)  # kicks the bg refresh
    deadline = time.time() + 4
    while time.time() < deadline:
        if getattr(dummy, "_hosts_cache_val", None):
            break
        time.sleep(0.05)
    parsed = json.loads(_call("get_all_hosts", dummy))
    assert parsed.get("excel", {}).get("status") == "live"
    # The refresh emitted hosts_changed so the JS side re-pulls.
    assert dummy.hosts_changed.emits >= 1


def test_get_local_llms_returns_instantly(monkeypatch):
    import local_llm_detector

    def _slow(*a, **kw):
        time.sleep(2.5)
        return {"ollama": {"status": "up"}}

    monkeypatch.setattr(local_llm_detector, "detect_all_local_llms", _slow)
    dummy = _DummyBridge()
    t0 = time.time()
    _call("get_local_llms", dummy)
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"get_local_llms blocked {elapsed:.2f}s"


# ─── 2. _cached_async contract ──────────────────────────────────────


def test_cached_async_dedupes_refresh(monkeypatch):
    """Two rapid calls spawn only ONE background detector run."""
    import host_detector
    runs = []

    def _detect(*a, **kw):
        runs.append(1)
        time.sleep(0.3)
        return {"x": 1}

    monkeypatch.setattr(host_detector, "detect_all_hosts", _detect)
    dummy = _DummyBridge()
    _call("get_all_hosts", dummy)
    _call("get_all_hosts", dummy)
    _call("get_all_hosts", dummy)
    time.sleep(1.0)
    assert len(runs) == 1, f"expected 1 refresh, got {len(runs)}"


def test_cached_async_empty_fallback_is_dict(monkeypatch):
    """First call (cache cold) returns the detector's real shape — a
    dict — never a list, so JS never sees a shape flip."""
    import host_detector
    monkeypatch.setattr(host_detector, "detect_all_hosts",
                        lambda *a, **k: {"x": 1})
    dummy = _DummyBridge()
    out = bridge.ArchHubBridge._cached_async(
        dummy, "_hosts", "detect_all_hosts", "host_detector")
    assert isinstance(out, dict)


# ─── 3. AgDR doc ────────────────────────────────────────────────────


def test_agdr_0035_exists():
    p = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
         / "AgDR-0035-bridge-slots-never-block-ui-thread.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: approved" in text
    assert "_cached_async" in text
