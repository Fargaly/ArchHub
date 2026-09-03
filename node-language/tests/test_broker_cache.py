"""AgDR-0034 deferred-audit fix — revit_broker.list_sessions short-TTL
cache. A burst of calls must cost ONE port scan (16 parallel probes),
not a fresh scan every call.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import revit_broker  # noqa: E402


def _reset_cache():
    revit_broker._list_cache["at"] = 0.0
    revit_broker._list_cache["result"] = None


@pytest.fixture
def _iso(tmp_path, monkeypatch):
    """Isolate the broker — empty sessions dir, all ports dead — so the
    only observable cost is the port-range scan, and no real session
    file is ever touched."""
    monkeypatch.setattr(revit_broker, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(revit_broker, "_probe_service", lambda *a, **k: False)
    _reset_cache()
    yield
    _reset_cache()


def test_burst_of_calls_costs_one_scan(_iso, monkeypatch):
    scans: list = []
    monkeypatch.setattr(revit_broker, "_discover_in_port_range",
                        lambda known, timeout=0.4: scans.append(1) or [])
    revit_broker.list_sessions()
    revit_broker.list_sessions()
    revit_broker.list_sessions()
    assert len(scans) == 1, f"expected 1 scan for 3 rapid calls, got {len(scans)}"


def test_cache_expires_after_ttl(_iso, monkeypatch):
    scans: list = []
    monkeypatch.setattr(revit_broker, "_discover_in_port_range",
                        lambda known, timeout=0.4: scans.append(1) or [])
    revit_broker.list_sessions()
    # Age the cache past its TTL.
    revit_broker._list_cache["at"] -= (revit_broker._LIST_TTL_S + 1.0)
    revit_broker.list_sessions()
    assert len(scans) == 2, "a call past the TTL must re-scan"


def test_cached_result_is_a_copy(_iso, monkeypatch):
    """A caller mutating the returned list must not corrupt the cache."""
    monkeypatch.setattr(revit_broker, "_discover_in_port_range",
                        lambda known, timeout=0.4: [])
    first = revit_broker.list_sessions()
    first.append("junk")
    second = revit_broker.list_sessions()
    assert "junk" not in second
