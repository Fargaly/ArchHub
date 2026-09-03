"""Plan-history persistence — M4 foundation (AgDR-0021).

Pins: deterministic plan_id, save/load round-trip, list ordering,
delete, prune, atomic-write resilience.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from plan_history import PlanHistory  # noqa: E402


# ─── 1. id determinism ───────────────────────────────────────────────


def test_id_for_same_inputs_returns_same_id():
    a = PlanHistory.id_for(prompt="hello", model="claude-4")
    b = PlanHistory.id_for(prompt="hello", model="claude-4")
    assert a == b


def test_id_for_differs_on_prompt_change():
    a = PlanHistory.id_for(prompt="hello", model="claude-4")
    b = PlanHistory.id_for(prompt="goodbye", model="claude-4")
    assert a != b


def test_id_for_differs_on_model_change():
    a = PlanHistory.id_for(prompt="hello", model="claude-4")
    b = PlanHistory.id_for(prompt="hello", model="gpt-4")
    assert a != b


def test_id_for_differs_on_extra_change():
    a = PlanHistory.id_for(prompt="x", model="m", extra="aA")
    b = PlanHistory.id_for(prompt="x", model="m", extra="bB")
    assert a != b


def test_id_for_is_16_hex():
    pid = PlanHistory.id_for(prompt="x", model="m")
    assert len(pid) == 16
    assert all(c in "0123456789abcdef" for c in pid)


# ─── 2. save / load ──────────────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path):
    h = PlanHistory(tmp_path)
    record = {
        "plan_id": "abc1234567890def",
        "prompt":  "list walls",
        "model":   "auto",
        "plan":    [{"tool": "revit.list_walls", "args": {}}],
        "result":  "12 walls found",
        "status":  "ok",
        "error":   None,
        "ts":      1700000000,
    }
    assert h.save(record) is True
    loaded = h.load("abc1234567890def")
    assert loaded == record


def test_load_unknown_id_returns_none(tmp_path):
    h = PlanHistory(tmp_path)
    assert h.load("nonexistent") is None


def test_save_creates_archhub_plans_subdir(tmp_path):
    h = PlanHistory(tmp_path)
    h.save({"plan_id": "x" * 16, "prompt": "p", "model": "m",
             "plan": [], "result": "", "status": "ok",
             "error": None, "ts": 0})
    assert (tmp_path / ".archhub" / "plans" / "xxxxxxxxxxxxxxxx.json").exists()


def test_save_rejects_record_without_plan_id(tmp_path):
    h = PlanHistory(tmp_path)
    assert h.save({"prompt": "p"}) is False


def test_save_non_dict_record_returns_false(tmp_path):
    h = PlanHistory(tmp_path)
    assert h.save("not a dict") is False
    assert h.save(None) is False


# ─── 3. list / delete / prune ────────────────────────────────────────


def test_list_ids_empty_when_no_records(tmp_path):
    h = PlanHistory(tmp_path)
    assert h.list_ids() == []


def test_list_ids_returns_saved_ids(tmp_path):
    h = PlanHistory(tmp_path)
    for i in range(3):
        h.save({"plan_id": f"{i:016d}", "prompt": f"p{i}", "model": "m",
                 "plan": [], "result": "", "status": "ok",
                 "error": None, "ts": i})
    ids = set(h.list_ids())
    assert ids == {"0000000000000000", "0000000000000001", "0000000000000002"}


def test_delete_removes_file(tmp_path):
    h = PlanHistory(tmp_path)
    h.save({"plan_id": "x" * 16, "prompt": "p", "model": "m",
             "plan": [], "result": "", "status": "ok",
             "error": None, "ts": 0})
    assert h.delete("x" * 16) is True
    assert h.load("x" * 16) is None


def test_delete_returns_false_for_missing(tmp_path):
    h = PlanHistory(tmp_path)
    assert h.delete("never-existed") is False


def test_list_records_returns_most_recent_first(tmp_path):
    import time
    h = PlanHistory(tmp_path)
    h.save({"plan_id": "older" + "0" * 11, "prompt": "old", "model": "m",
             "plan": [], "result": "", "status": "ok",
             "error": None, "ts": 1})
    time.sleep(0.01)  # ensure mtime ordering on Windows
    h.save({"plan_id": "newer" + "0" * 11, "prompt": "new", "model": "m",
             "plan": [], "result": "", "status": "ok",
             "error": None, "ts": 2})
    records = h.list_records()
    assert len(records) == 2
    assert records[0]["plan_id"] == "newer" + "0" * 11


def test_prune_keeps_only_last_n(tmp_path):
    import time
    h = PlanHistory(tmp_path)
    for i in range(5):
        h.save({"plan_id": f"{i:016d}", "prompt": "p", "model": "m",
                 "plan": [], "result": "", "status": "ok",
                 "error": None, "ts": i})
        time.sleep(0.01)
    dropped = h.prune(keep_last=3)
    assert dropped == 2
    assert len(h.list_ids()) == 3


def test_prune_no_op_when_under_cap(tmp_path):
    h = PlanHistory(tmp_path)
    h.save({"plan_id": "x" * 16, "prompt": "p", "model": "m",
             "plan": [], "result": "", "status": "ok",
             "error": None, "ts": 0})
    assert h.prune(keep_last=10) == 0


# ─── 4. corruption resilience ────────────────────────────────────────


def test_load_corrupted_record_returns_none(tmp_path):
    """A truncated/malformed JSON should return None, not raise."""
    h = PlanHistory(tmp_path)
    pid = "c" * 16
    path = tmp_path / ".archhub" / "plans" / f"{pid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json{{{", encoding="utf-8")
    assert h.load(pid) is None
