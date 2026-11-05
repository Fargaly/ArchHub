"""BABOOM's desk role, mapped from real Workshop rows and saved skills."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from mcp import types

from nodelang import workshop_mailbox, workshop_tasks
from nodelang.baboom_work_presence import (
    baboom_pose_motion,
    baboom_reduced_motion,
    baboom_shown_tick,
    baboom_work_presence,
    execute_saved_skill,
    load_saved_skills,
    match_saved_skill,
    read_workshop_task_rows,
)
from nodelang.session_files import new_document, write_document
from nodelang.workshop_mailbox import application_history


class _History:
    def __init__(self, database=":memory:"):
        self._db = sqlite3.connect(database)

    @contextmanager
    def _transaction(self, write=False):
        with self._db:
            yield


def _skill(folder, filename, title, skill_id, note, spoken):
    document = new_document(title)
    document["id"] = skill_id
    document["notes"] = [{"text": note}]
    document["nodes"] = [
        {
            "id": "file",
            "type": "param.value",
            "title": "File",
            "params": {"type": "text", "value": ""},
            "position": {"x": 0, "y": 0},
        },
        {
            "id": "said",
            "type": "note",
            "title": spoken,
            "params": {},
            "position": {"x": 40, "y": 0},
        },
    ]
    write_document(folder / filename, document)


def test_workshop_rows_map_to_baboom_states(tmp_path, monkeypatch):
    """Idle, thinking, needs-you, done, and error come from Workshop rows, not a second store."""
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    with application_history() as history:
        created = workshop_tasks.create(history, "Quiet index", "founder")
        assert baboom_work_presence(workshop_tasks.rows(history)).state == "idle"
        assert baboom_work_presence(workshop_tasks.column(history)).state == "idle"

        assert workshop_tasks.claim(history, created["id"], "agent", "Agent")
        thinking = baboom_work_presence(workshop_tasks.rows(history))
        assert thinking.state == "thinking"
        assert thinking.task_name == "Quiet index"
        assert thinking.motion == "think"
        assert thinking.bubble == "Quiet index"

        monkeypatch.setenv("ARCHHUB_BABOOM_READ_WORKSHOP", "1")
        read_back = read_workshop_task_rows()
        assert read_back and read_back[0]["status"] == "WIP"
        assert baboom_work_presence(read_back).state == "thinking"

        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (created["id"],))
        expired = workshop_tasks.rows(history, settle=False)
        assert expired[0]["lease_expired"]
        assert baboom_work_presence(expired).state == "idle"

        assert workshop_tasks.claim(history, created["id"], "agent", "Agent")
        assert workshop_tasks.complete(history, created["id"], "agent", "shipped")
        done = baboom_work_presence(workshop_tasks.rows(history), now=now)
        assert done.state == "done" and done.motion == "talk"
        assert "shipped" in done.bubble
        later = baboom_work_presence(
            workshop_tasks.rows(history), now=now + timedelta(hours=1)
        )
        assert later.state == "idle"

        failed = workshop_tasks.create(history, "Check the sheet", "founder")
        assert workshop_tasks.claim(history, failed["id"], "agent", "Agent")
        assert workshop_tasks.complete(history, failed["id"], "agent", "failed: the sheet")
        error = baboom_work_presence(workshop_tasks.rows(history), now=datetime.now(timezone.utc))
        assert error.state == "error" and error.motion == "crouch"
        assert "failed: the sheet" in error.bubble

        review = dict(workshop_tasks.rows(history)[0])
        review["status"] = "IN REVIEW"
        review["title"] = "Need a decision"
        assert baboom_work_presence([error_row(history), review]).state == "needs-you"


def error_row(history):
    return next(row for row in workshop_tasks.rows(history) if str(row.get("result") or "").startswith("failed"))


@pytest.mark.parametrize("legacy", [False, True], ids=["agent-id", "legacy-root-id"])
def test_a_blocked_declaration_needs_the_founder(tmp_path, monkeypatch, legacy):
    from nodelang import native_agent_mcp

    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_BABOOM_READ_WORKSHOP", "1")
    server = native_agent_mcp.build_server()
    # Only the explicit declare call is under test, not the connector's background refresh.
    server._mailbox_stop()
    declare = server._tool_manager.get_tool("declare").fn
    context = SimpleNamespace(request_context=SimpleNamespace(
        meta=types.RequestParams.Meta(**{"threadId": "baboom-declaration-fixture"})))
    result = declare("Hold the sheet", [str(tmp_path)], "blocked", "req-9", context)
    declaration = result["declaration"]
    with application_history() as history:
        if legacy:
            with history._transaction(write=True):
                history._db.execute("UPDATE workshop_tasks SET id=?", (
                    workshop_tasks._declaration_task_id(declaration),))
                declaration.pop("session")
                history._db.execute("UPDATE workshop_declarations SET record=?", (json.dumps(declaration),))
        column = workshop_tasks.column(history)
    assert column[0]["status"] == "IN REVIEW"
    assert column[0]["declarations"]
    shown = baboom_work_presence(read_workshop_task_rows())
    assert shown.state == "needs-you"
    assert shown.badge is True
    assert shown.motion == "wave"
    assert shown.task_name == "Hold the sheet"

    if not legacy:
        with application_history() as history:
            with history._transaction(write=True):
                history._db.execute("UPDATE workshop_tasks SET purpose='another-request'")
        assert baboom_work_presence(read_workshop_task_rows()).state == "thinking"


def test_reduced_motion_holds_the_first_frame():
    assert baboom_reduced_motion(parameter=None, show_animations=False) is True
    assert baboom_reduced_motion(parameter=False, show_animations=False) is True
    assert baboom_reduced_motion(parameter=True, show_animations=True) is True
    assert baboom_reduced_motion(parameter=None, show_animations=True) is False
    assert baboom_pose_motion("thinking", 3, reduced_motion=True) == "think"
    assert baboom_pose_motion("thinking", 3, reduced_motion=False) == "cast"
    assert baboom_pose_motion("thinking", 2, reduced_motion=False) == "think"
    assert baboom_pose_motion("needs-you", 1, reduced_motion=False) == "wave"
    assert baboom_pose_motion("error", 1, reduced_motion=False) == "crouch"
    assert baboom_pose_motion("done", 1, reduced_motion=False) == "talk"
    assert baboom_pose_motion("thinking", 3, reduced_motion=False, transitioning=True) == "walk"
    assert baboom_shown_tick(4, reduced_motion=True) == 0
    assert baboom_shown_tick(4, reduced_motion=False) == 4


def test_bad_timestamp_does_not_hide_other_running_work():
    rows = [
        {"id": "broken", "status": "DONE", "title": "Old result", "updated_at": "2026-99-99T12:00:00+00:00"},
        {"id": "running", "status": "WIP", "title": "Index the sheets"},
    ]
    shown = baboom_work_presence(rows)
    assert shown.state == "thinking"
    assert shown.task_id == "running"


def test_compact_result_keeps_its_full_report_and_task_reference():
    now = datetime.now(timezone.utc)
    report = "Checked each drawing. " * 20
    shown = baboom_work_presence([{
        "id": "task-123", "status": "DONE", "title": "Check the drawings",
        "result": report, "updated_at": now.isoformat(),
    }], now=now)
    assert len(shown.bubble) <= 72
    assert shown.task_id == "task-123"
    assert shown.report == report


def test_far_future_completion_is_not_a_current_success():
    shown = baboom_work_presence([{
        "status": "DONE", "title": "Future result", "updated_at": "2099-01-01T00:00:00+00:00",
    }], now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert shown.state == "idle"


def test_structured_failure_keeps_the_reason_and_safe_outcome():
    now = datetime.now(timezone.utc)
    shown = baboom_work_presence([{
        "id": "publish-pdf", "status": "DONE", "title": "Publish PDF", "updated_at": now.isoformat(),
        "result": {"ok": False, "status": "failed", "error": "Destination is read-only", "details": "No files written"},
    }], now=now)
    assert shown.state == "error"
    assert "Destination is read-only" in shown.bubble
    assert shown.report == "Destination is read-only\nNo files written"
    assert shown.task_id == "publish-pdf"


def test_dead_declaration_does_not_resurrect_work_and_done_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_BABOOM_READ_WORKSHOP", "1")
    monkeypatch.setattr(workshop_mailbox, "_session_alive", lambda row: False)
    database = tmp_path / "workshop" / "messages.sqlite3"
    database.parent.mkdir()
    history = _History()
    history._db.close()
    history._db = sqlite3.connect(database)
    try:
        workshop_tasks.declared(history, "room:old", "old", "Old work", "working", "old-agent", "Old agent")
        task = workshop_tasks.rows(history)[0]["id"]
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (task,))
        history._db.execute("CREATE TABLE workshop_declarations(root TEXT PRIMARY KEY, record TEXT)")
        history._db.execute("INSERT INTO workshop_declarations VALUES(?,?)", ("room:old", json.dumps({
            "root": "room:old", "request_id": "old", "session": "old-agent", "status": "working", "agent": "Old agent",
        })))
        history._db.commit()
        assert baboom_work_presence(read_workshop_task_rows()).state == "idle"
        monkeypatch.setattr(workshop_mailbox, "_session_alive", lambda row: True)
        assert workshop_tasks.claim(history, task, "old-agent", "Old agent")
        assert workshop_tasks.complete(history, task, "old-agent", "Checked the real result")
        assert baboom_work_presence(read_workshop_task_rows()).state == "done"
    finally:
        history._db.close()


def test_verified_baboom_availability_is_not_a_running_task(tmp_path, monkeypatch):
    from nodelang import baboom_nograph

    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_BABOOM_READ_WORKSHOP", "1")
    monkeypatch.setattr(workshop_mailbox, "_session_alive", lambda row: True)
    monkeypatch.setattr(baboom_nograph, "own_session", lambda state_dir=None: "app-baboom")
    database = tmp_path / "workshop" / "messages.sqlite3"
    database.parent.mkdir()
    history = _History(database)
    try:
        workshop_tasks.declared(history, "room:baboom", "BABOOM", "BABOOM is available", "working", "app-baboom", "BABOOM")
        history._db.execute("CREATE TABLE workshop_declarations(root TEXT PRIMARY KEY, record TEXT)")
        history._db.execute("INSERT INTO workshop_declarations VALUES(?,?)", ("room:baboom", json.dumps({
            "root": "room:baboom", "request_id": "BABOOM", "session": "app-baboom", "status": "working", "agent": "BABOOM",
        })))
        history._db.commit()
        assert baboom_work_presence(read_workshop_task_rows()).state == "idle"
        task = workshop_tasks.create(history, "Tag the doors", "founder")
        assert workshop_tasks.claim(history, task["id"], "app-baboom", "BABOOM")
        shown = baboom_work_presence(read_workshop_task_rows())
        assert shown.state == "thinking" and shown.task_id == task["id"]
        monkeypatch.setattr(baboom_nograph, "own_session", lambda state_dir=None: None)
        assert len(read_workshop_task_rows()) == 2
    finally:
        history._db.close()


def test_owner_read_only_rows_do_not_settle_but_default_read_does(tmp_path):
    database = tmp_path / "workshop.sqlite3"
    history = _History(database)
    try:
        task = workshop_tasks.create(history, "Expired task", "founder")
        assert workshop_tasks.claim(history, task["id"], "agent", "Agent")
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (task["id"],))
        history._db.commit()
        before = workshop_tasks.rows(history, settle=False)
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            shown = workshop_tasks.rows(SimpleNamespace(_db=connection), settle=False)
            assert shown == before
            assert shown[0]["status"] == "claimed" and shown[0]["lease_expired"]
            assert connection.total_changes == 0
        finally:
            connection.close()
        settled = workshop_tasks.rows(history)
        assert settled[0]["status"] == "open"
        assert settled[0]["outcome"] == "interrupted"
    finally:
        history._db.close()


def test_a_dropped_file_matches_one_saved_skill_and_runs_it(tmp_path):
    folder = tmp_path / "skills"
    folder.mkdir()
    _skill(folder, "read-pdf.archhub", "Read PDF", "read-pdf", "pdf drawings", "Read the sheet")
    _skill(folder, "walls.archhub", "Walls", "walls", "masonry", "Lay the course")
    skills = load_saved_skills(folder)
    chosen = match_saved_skill(tmp_path / "plan.pdf", skills)
    assert chosen is not None and chosen["title"] == "Read PDF"
    assert match_saved_skill(tmp_path / "zzzz.bin", skills) is None
    assert execute_saved_skill(chosen["path"], tmp_path / "plan.pdf") == "Read the sheet"
