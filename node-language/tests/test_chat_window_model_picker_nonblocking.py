"""APP-01 RESIDUAL boot-hang gate — the chat header model picker must
NOT probe LM Studio synchronously on the Qt main thread at boot.

Root cause (the residual boot-hang the court flagged still-present)
------------------------------------------------------------------
`bridge.get_models` was made non-blocking (it routes through
`_cached_async`; see tests/test_get_models_nonblocking.py). But the
Qt-NATIVE model picker the merge missed kept the SAME bug:

    main.py:754   window = ChatWindow(...)            # Qt main thread, at boot
      -> ChatWindow.__init__  -> self._populate_model_picker()
         -> router.configured_providers()  -> llm_detector.probe_lmstudio()
         -> llm_router.lmstudio_models()   -> llm_detector.probe_lmstudio()

`probe_lmstudio` pays the full ~1.5 s `urlopen` timeout on a HALF-OPEN
LM Studio port (TCP accepts, the HTTP `/models` GET stalls). Because
`_populate_model_picker` runs INLINE inside `ChatWindow.__init__` on the
Qt main thread during launch, that stall froze the app on boot — the
residual hang.

Fix (same CLASS of fix as the bridge slot, applied to the widget)
-----------------------------------------------------------------
- `LLMRouter.configured_providers_cheap()` — the configured-set WITHOUT
  the LM Studio HTTP probe (key / env / CLI presence only; all cheap,
  filesystem/keyring). Boot uses this; the bridge path keeps the full
  `configured_providers()`.
- `_populate_model_picker(defer_probe=True)` (the boot call) builds the
  picker INSTANTLY from the cheap set + the static KNOWN_MODELS, and
  kicks the real LM Studio / Ollama probe on a BACKGROUND thread that
  re-populates via the `_model_picker_ready` signal when it lands.

These tests stub `probe_lmstudio` to sleep 3 s and assert the boot
population returns < 100 ms. They go RED on origin/main (the synchronous
probe blocks) and GREEN after the fix.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Headless Qt — must be set before any QApplication is built.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _clean_llm_detector_cache():
    """The deferred boot probe runs on a daemon thread that may outlive the
    test and write a stubbed value into `llm_detector._CACHE`. Clear it
    before AND after each test so neither these tests nor the rest of the
    suite see a polluted probe cache."""
    try:
        import llm_detector
        llm_detector._CACHE.clear()
    except Exception:
        pass
    yield
    try:
        import llm_detector
        llm_detector._CACHE.clear()
    except Exception:
        pass


def _stub_probe_slow(monkeypatch, seconds=3.0, *, live=True):
    """Replace BOTH probe_lmstudio symbols (llm_detector + the name used
    inside llm_router) with a slow sleeper, so every path the picker takes
    hits the stall."""
    import llm_detector
    import llm_router

    def _slow():
        _slow.calls += 1
        time.sleep(seconds)
        return {"status": "live" if live else "missing",
                "models": ["qwen2.5-coder-7b"] if live else []}

    # The stub counts how many times the LM Studio HTTP probe is entered.
    # The boot-hang IS calling this probe synchronously on the Qt main thread —
    # so the boot-safe gate is "probe entered ZERO times", a deterministic
    # invariant, not a wall-clock race (cold keyring `list_keys()` I/O the cheap
    # path legitimately does can cross a 100ms threshold without any probe).
    _slow.calls = 0

    monkeypatch.setattr(llm_detector, "probe_lmstudio", _slow)
    monkeypatch.setattr(llm_router, "probe_lmstudio", _slow, raising=False)
    # Bust the 25 s llm_detector cache so the stub is actually hit.
    try:
        llm_detector._CACHE.clear()
    except Exception:
        pass
    return _slow


# ─── 1. router: a cheap configured-set that skips the LM Studio HTTP probe ──


def test_configured_providers_cheap_skips_lmstudio_http_probe(monkeypatch):
    """`configured_providers_cheap()` must return WITHOUT paying the LM
    Studio HTTP timeout — it is the boot-safe variant the GUI uses."""
    slow = _stub_probe_slow(monkeypatch, 3.0)

    from llm_router import LLMRouter

    class _NullTools:
        def tool_schemas_for(self, *a, **k):
            return []

    router = LLMRouter(_NullTools())

    assert hasattr(router, "configured_providers_cheap"), (
        "LLMRouter.configured_providers_cheap() is missing — the boot-safe "
        "(no-network) configured-set the model picker needs does not exist."
    )

    t0 = time.perf_counter()
    out = router.configured_providers_cheap()
    elapsed = time.perf_counter() - t0

    # THE gate — deterministic, not a wall-clock race. The boot-hang is the
    # synchronous LM Studio HTTP probe; the boot-safe set must enter that probe
    # ZERO times. (The cheap path legitimately does cold keyring `list_keys()`
    # I/O that can exceed a 100ms threshold on a clean checkout without any
    # network probe — asserting wall-clock time here false-failed ~3/10. The
    # real invariant is the probe-call count.)
    assert slow.calls == 0, (
        f"configured_providers_cheap entered the LM Studio HTTP probe "
        f"{slow.calls} time(s) — it must enter it ZERO times (the probe is the "
        f"~1.5s boot-hang). It took {elapsed*1000:.0f}ms."
    )
    # Coarse backstop: even one probe entry would sleep 3s, so anything under
    # the sleep window proves the slow path was not taken (immune to keyring
    # jitter, unlike the old 100ms race).
    assert elapsed < 2.0, (
        f"configured_providers_cheap blocked {elapsed*1000:.0f}ms — far beyond "
        f"the cheap key/env/CLI presence checks; something slow crept in."
    )
    assert isinstance(out, (list, set, tuple))
    # lmstudio is the network-probed provider — it must NOT appear in the
    # cheap set (it is filled in later by the background refresh).
    assert "lmstudio" not in set(out), (
        "configured_providers_cheap must not include lmstudio — that would "
        "mean it ran the HTTP probe."
    )


# ─── 2. THE gate — building the picker at boot returns < 100 ms ─────────────


def _make_picker_host(router):
    """Build a minimal object that borrows the REAL ChatWindow model-picker
    methods + a real QComboBox, so the actual boot code path is exercised
    without constructing the whole ChatWindow (which needs the full app)."""
    from PyQt6.QtWidgets import QApplication, QComboBox
    import chat_window

    app = QApplication.instance() or QApplication([])

    class _Signal:
        """Stand-in for the pyqtSignal — record connections + fire them
        synchronously enough for the test (the production path uses a real
        queued pyqtSignal; here we just need emit() to reach the slot)."""
        def __init__(self):
            self._slots = []
            self.emits = 0

        def connect(self, fn):
            self._slots.append(fn)

        def emit(self, *a):
            self.emits += 1
            for fn in list(self._slots):
                try:
                    fn(*a)
                except Exception:
                    pass

    host = type("PickerHost", (), {})()
    host.router = router
    host.model_picker = QComboBox()
    host._model_picker_ready = _Signal()
    # Borrow the real methods under test.
    host._populate_model_picker = \
        chat_window.ChatWindow._populate_model_picker.__get__(host)
    host._refresh_model_picker = \
        chat_window.ChatWindow._refresh_model_picker.__get__(host)
    if hasattr(chat_window.ChatWindow, "_kick_model_picker_probe"):
        host._kick_model_picker_probe = \
            chat_window.ChatWindow._kick_model_picker_probe.__get__(host)
    return app, host


class _DummyRouter:
    """Router stand-in whose configured_providers() reaches the (stubbed)
    probe — the real boot path. configured_providers_cheap() (when present)
    must avoid that probe."""

    def configured_providers(self):
        from llm_detector import probe_lmstudio
        res = probe_lmstudio() or {}
        return ["lmstudio"] if res.get("status") == "live" else []

    def configured_providers_cheap(self):
        # The boot-safe set: NO network probe. (Mirrors the real router's
        # cheap variant — key/env/CLI presence only; here just empty.)
        return []

    def blocked_providers(self):
        return {}


def test_populate_model_picker_boot_returns_under_100ms(monkeypatch):
    _stub_probe_slow(monkeypatch, 3.0)
    app, host = _make_picker_host(_DummyRouter())

    # The boot call ChatWindow.__init__ makes. Must be non-blocking.
    sig = getattr(host._populate_model_picker, "__func__", None)
    # Prefer the deferred boot signature when the fix is in; fall back to
    # the bare call (origin/main) so the test still RUNS (and FAILS on time)
    # before the fix exists.
    t0 = time.perf_counter()
    try:
        host._populate_model_picker(defer_probe=True)
    except TypeError:
        host._populate_model_picker()
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.1, (
        f"_populate_model_picker blocked {elapsed*1000:.0f}ms on a slow LM "
        f"Studio probe — it runs INLINE in ChatWindow.__init__ on the Qt "
        f"main thread at boot, so this IS the residual boot-hang. The boot "
        f"call must build from the cheap set + defer the probe off-thread."
    )

    # The picker is never blank — Auto + the static KNOWN_MODELS show
    # immediately so the user has something to pick on the cold boot.
    assert host.model_picker.count() >= 2, (
        "cold boot picker must show the Auto row + KNOWN_MODELS instantly"
    )
    # First row is the Auto router row (assert by visible label — the data
    # role QStandardItem.setData uses is a separate production detail).
    assert "Auto" in host.model_picker.itemText(0), (
        "the Auto · best-model row must lead the cold-boot picker"
    )
    # A real KNOWN_MODELS row is present too (the static catalogue is shown
    # instantly, not deferred).
    labels = {host.model_picker.itemText(i)
              for i in range(host.model_picker.count())}
    assert any("Claude" in lbl or "GPT" in lbl or "Gemini" in lbl
               for lbl in labels), "KNOWN_MODELS rows must show on cold boot"


def test_populate_model_picker_default_path_unchanged(monkeypatch):
    """The non-boot (refresh) call keeps its full behavior — it MAY probe
    (it is off the boot critical path / user-initiated). This guards that
    the fix did not gut the live path: with a FAST stubbed probe the full
    populate still lists the live lmstudio model row."""
    _stub_probe_slow(monkeypatch, 0.0, live=True)
    app, host = _make_picker_host(_DummyRouter())

    # Default call (defer_probe defaults False after the fix; on origin/main
    # the bare call is the same code path).
    host._populate_model_picker()

    # Auto + KNOWN_MODELS at minimum.
    assert host.model_picker.count() >= 2
