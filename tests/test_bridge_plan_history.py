"""Bridge slots for plan history — M4 phase-2 entry-points (AgDR-0021).

JSX Composer panel (next tick) reads the persisted `ai.plan`
records via these slots. Tests pin: list ordering, single load,
delete, default project_dir fallback, missing-record errors.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


@pytest.fixture
def bridge():
    from bridge import ArchHubBridge
    return ArchHubBridge()


@pytest.fixture
def plan_dir(tmp_path):
    """Pre-populate a tmp project dir with a handful of plan records
    so the bridge slots have something to surface."""
    import time
    from plan_history import PlanHistory
    h = PlanHistory(tmp_path)
    for i in range(3):
        h.save({
            "plan_id": f"{i:016d}",
            "prompt":  f"prompt {i}",
            "model":   "claude-4",
            "plan":    [{"tool": f"demo.{i}", "args": {}}],
            "result":  f"result {i}",
            "status":  "ok" if i % 2 == 0 else "error",
            "error":   None if i % 2 == 0 else "boom",
            "ts":      1700000000 + i,
        })
        time.sleep(0.01)  # mtime ordering on Windows
    return tmp_path


# ─── 1. get_plan_history ─────────────────────────────────────────────


def test_get_plan_history_returns_records(bridge, plan_dir):
    raw = bridge.get_plan_history(str(plan_dir), 50)
    result = json.loads(raw)
    assert "error" not in result, result
    assert result["count"] == 3
    assert len(result["records"]) == 3
    assert result["project_dir"] == str(plan_dir)
    # Most recent first (i=2 saved last).
    assert result["records"][0]["plan_id"] == "0000000000000002"


def test_get_plan_history_respects_limit(bridge, plan_dir):
    raw = bridge.get_plan_history(str(plan_dir), 2)
    result = json.loads(raw)
    assert result["count"] == 2
    # The 2 most recent — not the oldest.
    plan_ids = [r["plan_id"] for r in result["records"]]
    assert "0000000000000000" not in plan_ids  # oldest dropped


def test_get_plan_history_empty_dir_returns_empty_list(bridge, tmp_path):
    raw = bridge.get_plan_history(str(tmp_path), 50)
    result = json.loads(raw)
    assert result["count"] == 0
    assert result["records"] == []


def test_get_plan_history_uses_default_project_dir_when_empty(bridge,
                                                                  monkeypatch,
                                                                  tmp_path):
    """Empty project_dir → fall back to default_project_dir."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))
    # Pre-save a record at the fallback dir.
    from plan_history import PlanHistory
    PlanHistory(tmp_path).save({
        "plan_id": "f" * 16, "prompt": "fb", "model": "m",
        "plan": [], "result": "", "status": "ok",
        "error": None, "ts": 0,
    })
    raw = bridge.get_plan_history("", 50)
    result = json.loads(raw)
    assert result["count"] == 1
    assert result["records"][0]["plan_id"] == "f" * 16


def test_get_plan_history_limit_clamped_to_at_least_one(bridge, plan_dir):
    """limit=0 should not return 0 records — clamp to ≥1."""
    raw = bridge.get_plan_history(str(plan_dir), 0)
    result = json.loads(raw)
    # Returns ≥1; the exact value depends on the impl but it must
    # not be empty when records exist.
    assert result["count"] >= 1


# ─── 2. get_plan_record ──────────────────────────────────────────────


def test_get_plan_record_returns_record_by_id(bridge, plan_dir):
    raw = bridge.get_plan_record("0000000000000001", str(plan_dir))
    result = json.loads(raw)
    # Not "not_found" — the bridge-level error sentinel. The record
    # itself happens to carry status=error+error="boom" (test data),
    # so we check the bridge return shape not the record content.
    assert result.get("error") != "not_found", result
    assert result["plan_id"] == "0000000000000001"
    assert result["prompt"] == "prompt 1"
    assert result["status"] == "error"
    assert result["error"] == "boom"


def test_get_plan_record_returns_not_found(bridge, plan_dir):
    raw = bridge.get_plan_record("never-existed", str(plan_dir))
    result = json.loads(raw)
    assert result.get("error") == "not_found"


# ─── 3. delete_plan_record ───────────────────────────────────────────


def test_delete_plan_record_removes_file(bridge, plan_dir):
    raw = bridge.delete_plan_record("0000000000000001", str(plan_dir))
    result = json.loads(raw)
    assert result["ok"] is True
    # Subsequent list_history should NOT include the deleted id.
    list_raw = bridge.get_plan_history(str(plan_dir), 50)
    list_result = json.loads(list_raw)
    plan_ids = {r["plan_id"] for r in list_result["records"]}
    assert "0000000000000001" not in plan_ids


def test_delete_plan_record_missing_returns_false(bridge, plan_dir):
    raw = bridge.delete_plan_record("never-existed", str(plan_dir))
    result = json.loads(raw)
    assert result["ok"] is False
