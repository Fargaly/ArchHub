"""Tests for the active-work ledger producer (tools/active_work.py) — AgDR-0054.

ONE-SYSTEM: the producer now writes THROUGH the brain ledger (the single store),
not a forked JSON file. These tests prove:
  * register() enqueues into the BRAIN ledger (read back via brain_ledger),
  * status()/bump() read/write the BRAIN ledger,
  * the legacy file helpers (register_file/status_file) still work for the
    OFFLINE degraded path only (not a parallel store).

Runs under pytest. Uses an isolated temp brain.db via $ARCHHUB_BRAIN_DB with no
daemon (the in-process transport answers — still the ONE brain store).
"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO / "tools"), str(_REPO / "personal-brain-mcp" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def brain_producer(monkeypatch):
    """Fresh temp brain.db + fresh brain_ledger/active_work imports, no daemon."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("ARCHHUB_BRAIN_DB", str(Path(d) / "brain.db"))
        monkeypatch.setenv("BRAIN_OWNER_USER", "founder")
        import brain_ledger as bl
        bl = importlib.reload(bl)
        monkeypatch.setattr(bl, "_call_daemon", lambda *a, **k: None)
        bl._daemon_up = False
        bl._store = None
        bl._store_tried = False
        import active_work as aw
        aw = importlib.reload(aw)
        try:
            yield aw, bl
        finally:
            try:
                if getattr(bl, "_store", None) is not None:
                    bl._store.close()
            except Exception:
                pass
            bl._store = None
            bl._store_tried = False


def test_register_routes_to_brain_ledger(brain_producer):
    aw, bl = brain_producer
    res = aw.register([{"name": "a", "kind": "manual", "machine_resolvable": False}],
                      scope="demo", cap=5)
    assert res["ok"] and res["transport"] == "inproc"
    # the leaf is in the BRAIN ledger (one store), not a forked file.
    led = bl.get_ledger()
    assert led is not None
    assert any(lf["title"] == "a" for lf in led["leaves"].values())


def test_status_reads_brain_ledger(brain_producer):
    aw, _ = brain_producer
    aw.register([{"name": "artifact", "kind": "file_exists", "arg": "x.py"}])
    s = aw.status()
    assert s is not None
    assert s["exists"] is True
    assert s["counts"]["open"] == 1


def test_bump_increments_brain_ledger(brain_producer):
    aw, _ = brain_producer
    aw.register([{"name": "x", "kind": "manual", "machine_resolvable": False}])
    assert aw.bump() == 1
    assert aw.bump() == 2
    assert aw.status()["iterations"] == 2


# ─────────────────── legacy file helpers (offline degraded path) ─────────


def test_legacy_file_helpers_roundtrip():
    """register_file/status_file keep the legacy JSON shape for the OFFLINE
    fallback path (used only when the brain is unreachable)."""
    import active_work as aw
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "aw.json"
        aw.register_file([{"name": "a", "kind": "manual",
                           "machine_resolvable": False}], scope="demo", cap=5, path=p)
        s = aw.status_file(p)
        assert s["scope"] == "demo" and s["cap"] == 5
        assert s["gates"][0]["name"] == "a" and s["iterations"] == 0


def test_clear_removes_offline_cache():
    import active_work as aw
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "aw.json"
        aw.register_file([], path=p)
        assert aw.clear(p) is True
        assert aw.status_file(p) is None
        assert aw.clear(p) is False  # already gone
