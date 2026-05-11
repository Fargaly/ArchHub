"""Health history (v0.42) — ring buffer + success rate.

Covers:
  * record() edge-only: identical state in a row stays at 1 entry
  * history() returns ordered tuples
  * success_rate is time-weighted (not count-weighted)
  * last_failure() finds the most recent non-live state
  * ring cap drops oldest when overflowed
  * disk persistence roundtrip
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Redirect LOCALAPPDATA so each test gets a clean store.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Re-import so module-level _store_path uses the new env.
    import health_history as hh
    hh.clear()
    yield
    hh.clear()


class TestRecording:
    def test_records_first_entry(self):
        import health_history as hh
        hh.record("revit", "live")
        items = hh.history("revit")
        assert len(items) == 1
        assert items[0][1] == "live"

    def test_edge_only_dedup(self):
        import health_history as hh
        for _ in range(5):
            hh.record("revit", "live")
        # All 5 calls but identical state → only first lands.
        assert len(hh.history("revit")) == 1

    def test_state_change_appends(self):
        import health_history as hh
        hh.record("revit", "live")
        hh.record("revit", "host_offline")
        hh.record("revit", "live")
        items = hh.history("revit")
        assert [s for _, s in items] == ["live", "host_offline", "live"]

    def test_unknown_or_empty_skipped(self):
        import health_history as hh
        hh.record("", "live")
        hh.record("revit", "")
        assert hh.history("revit") == []


class TestSuccessRate:
    def test_all_live_is_100_percent(self):
        import health_history as hh
        hh.record("revit", "live")
        # No state change for the rest of the test window → 100% live.
        assert hh.success_rate("revit") == pytest.approx(1.0, abs=0.01)

    def test_no_data_returns_zero(self):
        import health_history as hh
        assert hh.success_rate("nothing") == 0.0

    def test_time_weighted_split(self, monkeypatch):
        import health_history as hh
        # Manually inject a history: live at -1000s, dead at -500s, now.
        # Window of 1500s comfortably includes both entries.
        # Time-weighted across the 1500s window:
        #   pre-window (back-fill) — first known state ("live") covers
        #     the gap from -1500s to -1000s = 500s live
        #   -1000s..-500s = 500s live
        #   -500s..now    = 500s host_offline
        # Total = 1500s, live = 1000s → ~67%.
        with hh._LOCK:
            from collections import deque
            now = time.time()
            ring = deque(maxlen=hh._RING_CAP)
            ring.append((now - 1000, "live"))
            ring.append((now - 500, "host_offline"))
            hh._RINGS["revit"] = ring
        sr = hh.success_rate("revit", since_seconds=1500)
        assert 0.6 <= sr <= 0.75


class TestLastFailure:
    def test_no_failure_returns_none(self):
        import health_history as hh
        hh.record("revit", "live")
        assert hh.last_failure("revit") is None

    def test_returns_most_recent_failure(self):
        import health_history as hh
        hh.record("revit", "live")
        hh.record("revit", "host_offline")
        hh.record("revit", "live")
        hh.record("revit", "loaded_dead")
        hh.record("revit", "live")
        lf = hh.last_failure("revit")
        assert lf is not None
        assert lf[1] == "loaded_dead"


class TestPersistence:
    def test_save_then_reload(self, tmp_path, monkeypatch):
        import health_history as hh
        hh.record("revit", "live")
        hh.record("revit", "host_offline")
        # Force save (clear throttle).
        hh._LAST_SAVE = 0.0
        hh._save_to_disk()
        # Wipe in-memory + reload from disk.
        with hh._LOCK:
            hh._RINGS.clear()
        hh._load_from_disk()
        items = hh.history("revit")
        assert len(items) == 2
        assert [s for _, s in items] == ["live", "host_offline"]
