"""APP-01 boot-hang gate — `get_models` must never block the Qt main thread.

Root cause (the boot-hang): `app-boot.jsx` prefetches `get_models`
synchronously during boot.  `get_models` called
`router.configured_providers()` + `lmstudio_models()`, both of which call
`llm_detector.probe_lmstudio`.  On a HALF-OPEN LM Studio port (TCP accepts
but the HTTP `/models` GET stalls) that probe pays the full ~1.5 s
`urlopen` timeout SYNCHRONOUSLY — on the Qt main thread — freezing the app
on launch.

Fix: `get_models` now routes its provider probing through `_cached_async`
(the same mechanism `get_local_llms` / `probe_connector` use), so the slow
probe runs on the background pool and the slot returns instantly.

This test mirrors `tests/test_bridge_nonblocking.py`:
`test_get_local_llms_slot_is_async` — a PLAIN stand-in `self` that borrows
the real `_cached_async` + `_async_state`, with `probe_lmstudio` stubbed to
sleep so a regression (re-introducing a synchronous probe in `get_models`)
fails the < 100 ms assertion.
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


class _DummyRouter:
    """Minimal router stand-in.  configured_providers() is the path that
    reaches probe_lmstudio in the real router — here it calls the (stubbed)
    probe so the slow probe is exercised through the same call shape."""

    def configured_providers(self):
        from llm_detector import probe_lmstudio
        res = probe_lmstudio() or {}
        return ["lmstudio"] if res.get("status") == "live" else []

    def blocked_providers(self):
        return {}


class _DummyBridge:
    """Plain stand-in for ArchHubBridge `self` — borrows the real
    _cached_async / _async_state / _static_models / get_models so the
    mechanism is exercised unchanged, without the heavy QObject build."""

    def __init__(self, router):
        self.router = router
        self.hosts_changed = _DummySignal()
        self._cached_async = bridge.ArchHubBridge._cached_async.__get__(self)
        self._async_state = bridge.ArchHubBridge._async_state.__get__(self)
        self._static_models = bridge.ArchHubBridge._static_models
        self.get_models = bridge.ArchHubBridge.get_models.__get__(self)


def _stub_probe_slow(monkeypatch, seconds=3.0, *, live=True):
    """Replace BOTH probe_lmstudio symbols (llm_detector + the name
    re-exported into llm_router) with a slow sleeper, so every path the
    real get_models takes hits the stall."""
    import llm_detector
    import llm_router

    def _slow():
        time.sleep(seconds)
        return {"status": "live" if live else "missing",
                "models": ["qwen2.5-coder-7b"] if live else []}

    monkeypatch.setattr(llm_detector, "probe_lmstudio", _slow)
    monkeypatch.setattr(llm_router, "probe_lmstudio", _slow, raising=False)
    return _slow


# ─── 1. THE gate — get_models returns < 100 ms with a 3 s probe ─────────


def test_get_models_returns_under_100ms_with_slow_probe(monkeypatch):
    _stub_probe_slow(monkeypatch, 3.0)
    dummy = _DummyBridge(_DummyRouter())

    t0 = time.perf_counter()
    raw = dummy.get_models()
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.1, (
        f"get_models blocked {elapsed*1000:.0f}ms on a slow LM Studio "
        f"probe — it must run the probe off the Qt main thread "
        f"(_cached_async).  The boot-hang has regressed."
    )
    # The cold call returns the static catalogue (never blank) so the
    # picker has something to render immediately.
    data = json.loads(raw)
    assert isinstance(data, list) and data, "cold call must return models"
    assert data[0]["id"] == "auto", "Auto row must lead the static list"
    ids = {m["id"] for m in data}
    assert "anthropic:claude-opus-4-7" in ids, "KNOWN_MODELS must be present"


# ─── 2. the slow probe actually lands on the background pool ─────────────


def test_get_models_fills_in_after_background_probe(monkeypatch):
    # Short sleep so the test is quick but the call is still async.
    _stub_probe_slow(monkeypatch, 0.3, live=True)
    dummy = _DummyBridge(_DummyRouter())

    dummy.get_models()                       # cold — kicks the bg probe
    deadline = time.time() + 5
    landed = None
    while time.time() < deadline:
        data = json.loads(dummy.get_models())
        if any(m.get("provider") == "lmstudio" for m in data):
            landed = data
            break
        time.sleep(0.05)

    assert landed is not None, "background probe never folded LM Studio in"
    assert dummy.hosts_changed.emits >= 1, "must signal JS to re-pull"
    # The lmstudio model the probe reported is now a real picker row.
    assert any(m["id"] == "lmstudio:qwen2.5-coder-7b" for m in landed)


# ─── 3. no-router safety (clean install) ────────────────────────────────


def test_get_models_no_router_returns_empty_list():
    dummy = _DummyBridge(router=None)
    assert json.loads(dummy.get_models()) == []
