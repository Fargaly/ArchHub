"""Bridge plan-history SESSION threading — IA fix
(ia-critique-ai-stemcells-2026-06-03 §2). The composer already receives
`session_id` upstream (send_chat_history) but DROPPED it; now it threads
through `_persist_chat_plan` and the read/delete slots.

Pins, all ADDITIVE / back-compat:
  * `_persist_chat_plan(session_id=...)` writes into the session's pool;
    `get_plan_history(project_dir, limit, session_id=...)` reads it back.
  * The historical no-session path (`_persist_chat_plan` without a
    session, `get_plan_history("", N)`) STILL works — old global plans.
  * A session pool and the global pool are isolated.
  * The persisted record carries its `session_id`.
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
def use_tmp_project(monkeypatch, tmp_path):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                        lambda: str(tmp_path))
    return tmp_path


# ─── 1. session-scoped persist + read-back round trip ────────────────


def test_persist_with_session_reads_back_with_session(bridge, use_tmp_project):
    bridge._persist_chat_plan(
        prompt="hi", model="auto", result="hello",
        reasoning=[], tool_calls=[], routing_note="", session_id="sess-1",
    )
    # Read WITH the same session → 1 record.
    raw = bridge.get_plan_history(str(use_tmp_project), 10, "sess-1")
    out = json.loads(raw)
    assert out["count"] == 1, out
    assert out["records"][0]["prompt"] == "hi"
    assert out["records"][0]["session_id"] == "sess-1"
    assert out["session_id"] == "sess-1"


def test_session_record_not_in_global_pool(bridge, use_tmp_project):
    """A session-keyed plan must NOT appear in the global pool read."""
    bridge._persist_chat_plan(
        prompt="scoped", model="auto", result="r",
        reasoning=[], tool_calls=[], routing_note="", session_id="sess-9",
    )
    # Global read (no session) → empty.
    out = json.loads(bridge.get_plan_history(str(use_tmp_project), 10))
    assert out["count"] == 0, out
    # Wrong session → empty.
    out2 = json.loads(bridge.get_plan_history(str(use_tmp_project), 10, "other"))
    assert out2["count"] == 0


def test_two_sessions_isolated(bridge, use_tmp_project):
    bridge._persist_chat_plan(prompt="A", model="auto", result="ra",
                              reasoning=[], tool_calls=[], routing_note="",
                              session_id="sess-A")
    bridge._persist_chat_plan(prompt="B", model="auto", result="rb",
                              reasoning=[], tool_calls=[], routing_note="",
                              session_id="sess-B")
    a = json.loads(bridge.get_plan_history(str(use_tmp_project), 10, "sess-A"))
    b = json.loads(bridge.get_plan_history(str(use_tmp_project), 10, "sess-B"))
    assert a["count"] == 1 and a["records"][0]["prompt"] == "A"
    assert b["count"] == 1 and b["records"][0]["prompt"] == "B"


# ─── 2. back-compat: no-session path is unchanged (global pool) ──────


def test_no_session_persist_lands_in_global_pool(bridge, use_tmp_project):
    """The historical call (no session_id) still writes to + reads from
    the global pool — old plans don't move."""
    bridge._persist_chat_plan(
        prompt="legacy turn", model="auto", result="ok",
        reasoning=[], tool_calls=[], routing_note="",
    )
    out = json.loads(bridge.get_plan_history("", 10))
    assert out["count"] == 1
    assert out["records"][0]["prompt"] == "legacy turn"
    assert out["records"][0]["session_id"] == ""


def test_old_global_record_still_readable_after_session_feature(bridge,
                                                                use_tmp_project):
    """A record written directly to the global pool (as the pre-session
    code did) is still surfaced by the no-session bridge read."""
    from plan_history import PlanHistory
    PlanHistory(use_tmp_project).save({
        "plan_id": "d" * 16, "prompt": "older-global", "model": "m",
        "plan": [], "result": "", "status": "ok", "error": None, "ts": 0,
    })
    out = json.loads(bridge.get_plan_history("", 50))
    ids = {r["plan_id"] for r in out["records"]}
    assert "d" * 16 in ids


# ─── 3. session-scoped get_plan_record + delete_plan_record ──────────


def test_get_and_delete_plan_record_session_scoped(bridge, use_tmp_project):
    bridge._persist_chat_plan(prompt="del me", model="auto", result="r",
                              reasoning=[], tool_calls=[], routing_note="",
                              session_id="sess-D")
    out = json.loads(bridge.get_plan_history(str(use_tmp_project), 10, "sess-D"))
    pid = out["records"][0]["plan_id"]

    # Record is fetchable WITH the session.
    rec = json.loads(bridge.get_plan_record(pid, str(use_tmp_project), "sess-D"))
    assert rec.get("error") != "not_found"
    assert rec["prompt"] == "del me"

    # ...but NOT from the global pool (wrong root).
    miss = json.loads(bridge.get_plan_record(pid, str(use_tmp_project)))
    assert miss.get("error") == "not_found"

    # Delete WITH the session removes it.
    d = json.loads(bridge.delete_plan_record(pid, str(use_tmp_project), "sess-D"))
    assert d["ok"] is True
    after = json.loads(bridge.get_plan_history(str(use_tmp_project), 10, "sess-D"))
    assert after["count"] == 0
