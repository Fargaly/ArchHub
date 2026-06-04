"""Plan-history SESSION keying — IA fix (ia-critique-ai-stemcells-2026-06-03
§2: "Key plans by session"). Plans belong to a SESSION, not a global pool.

Pins, all ADDITIVE / back-compat:
  * `id_for(..., session_id=...)` folds the session into the id; an
    omitted session_id reproduces the historical (pre-session) id EXACTLY.
  * Two sessions asking the same prompt get DISTINCT ids + DISTINCT roots.
  * A session-scoped `PlanHistory` roots under
    `<proj>/.archhub/sessions/<sid>/plans/`; an empty session keeps the
    historical global root `<proj>/.archhub/plans/`.
  * OLD GLOBAL PLANS STILL LOAD: a record written to the global pool
    (empty session) is read back by an empty-session PlanHistory — the
    back-compat guarantee.
  * Session ids are sanitised so a stray `/` / `..` can't escape the dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from plan_history import PlanHistory  # noqa: E402


# ─── 1. id_for back-compat (omitted session == historical id) ────────


def test_id_for_omitted_session_matches_historical_payload():
    """The pre-session id was sha256('prompt|model|extra')[:16]. Omitting
    session_id must reproduce that EXACT id (no churn for old plans)."""
    import hashlib
    legacy = hashlib.sha256("hello|claude-4|".encode("utf-8")).hexdigest()[:16]
    assert PlanHistory.id_for(prompt="hello", model="claude-4") == legacy


def test_id_for_empty_session_equals_omitted_session():
    a = PlanHistory.id_for(prompt="p", model="m", extra="e")
    b = PlanHistory.id_for(prompt="p", model="m", extra="e", session_id="")
    assert a == b


# ─── 2. session folds into the id ────────────────────────────────────


def test_id_for_session_changes_the_id():
    base = PlanHistory.id_for(prompt="p", model="m")
    sess = PlanHistory.id_for(prompt="p", model="m", session_id="sess-1")
    assert sess != base


def test_id_for_two_sessions_same_prompt_distinct_ids():
    a = PlanHistory.id_for(prompt="p", model="m", session_id="sess-A")
    b = PlanHistory.id_for(prompt="p", model="m", session_id="sess-B")
    assert a != b


def test_id_for_same_session_same_prompt_is_stable():
    a = PlanHistory.id_for(prompt="p", model="m", session_id="sess-A")
    b = PlanHistory.id_for(prompt="p", model="m", session_id="sess-A")
    assert a == b


def test_id_for_session_still_16_hex():
    pid = PlanHistory.id_for(prompt="p", model="m", session_id="sess-A")
    assert len(pid) == 16
    assert all(c in "0123456789abcdef" for c in pid)


# ─── 3. session-scoped root vs global root ───────────────────────────


def test_session_history_roots_under_sessions_dir(tmp_path):
    h = PlanHistory(tmp_path, session_id="sess-42")
    h.save({"plan_id": "a" * 16, "prompt": "p", "model": "m",
            "plan": [], "result": "", "status": "ok", "error": None, "ts": 0})
    expected = tmp_path / ".archhub" / "sessions" / "sess-42" / "plans" / ("a" * 16 + ".json")
    assert expected.exists()


def test_empty_session_roots_at_historical_global_dir(tmp_path):
    """Empty session → the SAME global root as before session-keying."""
    h = PlanHistory(tmp_path, session_id="")
    h.save({"plan_id": "b" * 16, "prompt": "p", "model": "m",
            "plan": [], "result": "", "status": "ok", "error": None, "ts": 0})
    assert (tmp_path / ".archhub" / "plans" / ("b" * 16 + ".json")).exists()


def test_none_session_is_global_pool(tmp_path):
    """Constructing without a session_id at all keeps the global root."""
    h = PlanHistory(tmp_path)
    assert h.root == tmp_path / ".archhub" / "plans"


# ─── 4. sessions are isolated from each other + from the global pool ──


def test_two_sessions_do_not_see_each_others_plans(tmp_path):
    a = PlanHistory(tmp_path, session_id="sess-A")
    b = PlanHistory(tmp_path, session_id="sess-B")
    a.save({"plan_id": "a" * 16, "prompt": "pa", "model": "m",
            "plan": [], "result": "", "status": "ok", "error": None, "ts": 0})
    # B's pool is empty; B cannot load A's record.
    assert b.list_ids() == []
    assert b.load("a" * 16) is None
    # A still sees its own.
    assert a.load("a" * 16) is not None


def test_session_pool_excludes_global_plans(tmp_path):
    """A session pool must not surface the old global plans (they live in
    a different dir) — but the global pool itself still has them."""
    glob = PlanHistory(tmp_path)            # global
    sess = PlanHistory(tmp_path, "sess-A")  # session-scoped
    glob.save({"plan_id": "g" * 16, "prompt": "pg", "model": "m",
               "plan": [], "result": "", "status": "ok", "error": None, "ts": 0})
    assert sess.list_ids() == []
    assert glob.load("g" * 16) is not None


# ─── 5. OLD-PLAN BACK-COMPAT (the load-bearing guarantee) ────────────


def test_old_global_plan_still_loads_after_session_keying(tmp_path):
    """A record written to the historical global pool (empty session) is
    still readable by an empty-session PlanHistory — old plans don't
    vanish when session-keying lands."""
    # Simulate a plan written by the PRE-session code: global root.
    writer = PlanHistory(tmp_path)
    writer.save({"plan_id": "0" * 16, "prompt": "legacy", "model": "auto",
                 "plan": [{"tool": "revit.list_walls", "args": {}}],
                 "result": "ok", "status": "ok", "error": None, "ts": 1})
    # A fresh empty-session reader (today's code) finds it unchanged.
    reader = PlanHistory(tmp_path)
    rec = reader.load("0" * 16)
    assert rec is not None
    assert rec["prompt"] == "legacy"
    assert "0" * 16 in reader.list_ids()


# ─── 6. session-id sanitisation (no path escape) ─────────────────────


def test_session_id_with_path_separators_is_sanitised(tmp_path):
    """A malicious / sloppy session id can't escape the sessions dir."""
    h = PlanHistory(tmp_path, session_id="../../etc/evil")
    # The root must stay UNDER <tmp>/.archhub/sessions/.
    sessions_root = (tmp_path / ".archhub" / "sessions").resolve()
    assert sessions_root in h.root.resolve().parents
    h.save({"plan_id": "c" * 16, "prompt": "p", "model": "m",
            "plan": [], "result": "", "status": "ok", "error": None, "ts": 0})
    assert h.load("c" * 16) is not None


def test_blank_session_after_sanitise_is_global(tmp_path):
    """A whitespace-only session id is treated as "no session" (global),
    not an empty path segment."""
    h = PlanHistory(tmp_path, session_id="   ")
    assert h.root == tmp_path / ".archhub" / "plans"
