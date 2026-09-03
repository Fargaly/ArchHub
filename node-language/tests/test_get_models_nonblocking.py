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
fails well before the slow probe could complete.
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


SLOW_PROBE_SECONDS = 3.0


def _assert_not_waiting_for_probe(elapsed, probe_seconds, label, detail):
    """Allow scheduler jitter, but fail if the slow probe runs inline."""
    budget = probe_seconds / 2
    assert elapsed < budget, (
        f"{label} blocked {elapsed*1000:.0f}ms with a "
        f"{probe_seconds:.1f}s slow probe (budget {budget:.1f}s) - "
        f"{detail}"
    )


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
    _cached_async / _async_state / _static_models / get_models AND the
    provider slots (get_providers / get_provider_stats / get_runtime_info)
    so the mechanism is exercised unchanged, without the heavy QObject
    build."""

    def __init__(self, router):
        self.router = router
        self.hosts_changed = _DummySignal()
        self._cached_async = bridge.ArchHubBridge._cached_async.__get__(self)
        self._async_state = bridge.ArchHubBridge._async_state.__get__(self)
        self._static_models = bridge.ArchHubBridge._static_models
        self.get_models = bridge.ArchHubBridge.get_models.__get__(self)
        # APP-01 (court-root) — the provider slots that used to block boot.
        self._PROVIDERS_META = bridge.ArchHubBridge._PROVIDERS_META
        self._providers_payload = \
            bridge.ArchHubBridge._providers_payload.__get__(self)
        self._provider_counts = \
            bridge.ArchHubBridge._provider_counts.__get__(self)
        self.get_providers = bridge.ArchHubBridge.get_providers.__get__(self)
        self.get_provider_stats = \
            bridge.ArchHubBridge.get_provider_stats.__get__(self)
        self._BRAIN_PORT = bridge.ArchHubBridge._BRAIN_PORT
        self._runtime_probe = \
            bridge.ArchHubBridge._runtime_probe.__get__(self)
        self.get_runtime_info = \
            bridge.ArchHubBridge.get_runtime_info.__get__(self)


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


# ─── 1. THE gate — get_models returns well before a 3 s probe ───────────


def test_get_models_returns_without_waiting_for_slow_probe(monkeypatch):
    probe_seconds = SLOW_PROBE_SECONDS
    _stub_probe_slow(monkeypatch, probe_seconds)
    dummy = _DummyBridge(_DummyRouter())

    t0 = time.perf_counter()
    raw = dummy.get_models()
    elapsed = time.perf_counter() - t0

    _assert_not_waiting_for_probe(
        elapsed,
        probe_seconds,
        "get_models",
        "it must run the probe off the Qt main thread (_cached_async). "
        "The boot-hang has regressed.",
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


# ─── 4. APP-01 court-root — the OTHER boot-path slots must not block ─────
#
# `get_providers` is in the boot `pullAll` batch (app-boot.jsx) right
# alongside `get_models`.  It (and get_provider_stats / get_runtime_info)
# reached `probe_lmstudio` through `router.configured_providers()` and
# paid the full timeout on the Qt main thread — the boot-hang the court
# refuted as still-present. Same gate as get_models: return well before the
# slow probe could complete.


def test_get_providers_returns_without_waiting_for_slow_probe(monkeypatch):
    probe_seconds = SLOW_PROBE_SECONDS
    _stub_probe_slow(monkeypatch, probe_seconds)
    dummy = _DummyBridge(_DummyRouter())

    t0 = time.perf_counter()
    raw = dummy.get_providers()
    elapsed = time.perf_counter() - t0

    _assert_not_waiting_for_probe(
        elapsed,
        probe_seconds,
        "get_providers",
        "it is in the boot pullAll batch and MUST run the probe off "
        "the Qt main thread (_cached_async). The boot-hang has regressed.",
    )
    # The cold call returns the static provider list (never blank) so the
    # Settings → Providers tab renders immediately.
    data = json.loads(raw)
    assert isinstance(data, list) and data, "cold call must return providers"
    ids = {p["id"] for p in data}
    assert {"anthropic", "openai", "lmstudio"} <= ids, \
        "static provider rows must be present on the cold call"


def test_get_provider_stats_returns_without_waiting_for_slow_probe(
        monkeypatch):
    probe_seconds = SLOW_PROBE_SECONDS
    _stub_probe_slow(monkeypatch, probe_seconds)
    dummy = _DummyBridge(_DummyRouter())

    t0 = time.perf_counter()
    raw = dummy.get_provider_stats()
    elapsed = time.perf_counter() - t0

    _assert_not_waiting_for_probe(
        elapsed,
        probe_seconds,
        "get_provider_stats",
        "route it through _cached_async.",
    )
    data = json.loads(raw)
    assert "configured" in data and "blocked" in data


def test_get_runtime_info_returns_without_waiting_for_slow_probe(monkeypatch):
    probe_seconds = SLOW_PROBE_SECONDS
    _stub_probe_slow(monkeypatch, probe_seconds)
    dummy = _DummyBridge(_DummyRouter())

    t0 = time.perf_counter()
    raw = dummy.get_runtime_info()
    elapsed = time.perf_counter() - t0

    _assert_not_waiting_for_probe(
        elapsed,
        probe_seconds,
        "get_runtime_info",
        "the provider-count read must come from the _cached_async pool.",
    )
    data = json.loads(raw)
    assert "providers_configured" in data and "providers_blocked" in data


def test_get_providers_fills_in_after_background_probe(monkeypatch):
    # A live probe → lmstudio becomes a "connected" provider once the
    # background refresh lands and hosts_changed fires.
    _stub_probe_slow(monkeypatch, 0.3, live=True)
    dummy = _DummyBridge(_DummyRouter())

    dummy.get_providers()                    # cold — kicks the bg probe
    deadline = time.time() + 5
    landed = None
    while time.time() < deadline:
        data = json.loads(dummy.get_providers())
        lm = next((p for p in data if p["id"] == "lmstudio"), None)
        if lm and lm["state"] == "connected":
            landed = data
            break
        time.sleep(0.05)

    assert landed is not None, \
        "background probe never marked LM Studio connected"
    assert dummy.hosts_changed.emits >= 1, "must signal JS to re-pull"


def test_provider_slots_share_one_background_probe(monkeypatch):
    """get_provider_stats + get_runtime_info share the `provider_counts`
    cache key, AND the in-flight de-dupe in llm_detector._cached collapses
    concurrent sibling probes — so a boot batch hitting all of them fires
    the slow probe ONCE, not once per slot."""
    calls = {"n": 0}
    import llm_detector
    import llm_router
    probe_seconds = SLOW_PROBE_SECONDS

    def _slow():
        calls["n"] += 1
        time.sleep(probe_seconds)
        return {"status": "live", "models": ["qwen2.5-coder-7b"]}

    # Route configured_providers through the REAL llm_detector cache so the
    # in-flight de-dupe (defect #3) is exercised, not bypassed.
    llm_detector._CACHE.clear()
    monkeypatch.setattr(llm_detector, "probe_lmstudio",
                        llm_detector._cached("lmstudio")(_slow))

    class _RealishRouter:
        def configured_providers(self):
            res = llm_detector.probe_lmstudio() or {}
            return ["lmstudio"] if res.get("status") == "live" else []

        def blocked_providers(self):
            return {}

    dummy = _DummyBridge(_RealishRouter())

    # Fire all three provider slots "at once" (cold) — each returns instantly.
    t0 = time.perf_counter()
    dummy.get_providers()
    dummy.get_provider_stats()
    dummy.get_runtime_info()
    elapsed = time.perf_counter() - t0
    _assert_not_waiting_for_probe(
        elapsed,
        probe_seconds,
        "cold fan-out",
        "provider slots must not synchronously wait for the shared probe.",
    )

    # Let the background probes settle.
    deadline = time.time() + 5
    while time.time() < deadline and calls["n"] == 0:
        time.sleep(0.05)
    # Allow any (wrongly) un-deduped sibling probe to also run.
    time.sleep(probe_seconds + 0.2)

    # The 25s llm_detector TTL + per-key in-flight lock mean the underlying
    # probe ran a SMALL number of times, never once-per-slot-per-call.
    assert calls["n"] <= 2, (
        f"probe ran {calls['n']}x — the in-flight de-dupe / shared cache "
        f"key is not collapsing sibling boot probes"
    )
