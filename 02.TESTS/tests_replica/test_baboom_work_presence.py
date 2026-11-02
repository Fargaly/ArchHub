"""BABOOM's desk role, mapped from real Workshop rows and saved skills."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

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
    def __init__(self):
        self._db = sqlite3.connect(":memory:")

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
        expired = workshop_tasks.rows(history)
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


def test_a_blocked_declaration_needs_the_founder(monkeypatch):
    monkeypatch.setattr(workshop_mailbox, "_session_alive", lambda row: True)
    history = _History()
    workshop_tasks.declared(
        history, "room:desk", "req-9", "Hold the sheet", "working", "agent", "Agent"
    )
    history._db.execute("CREATE TABLE workshop_declarations(root TEXT PRIMARY KEY, record TEXT)")
    history._db.execute(
        "INSERT INTO workshop_declarations VALUES(?,?)",
        ("room:desk", json.dumps({
            "root": "room:desk", "request_id": "req-9", "status": "blocked", "agent": "x",
        })),
    )
    shown = baboom_work_presence(workshop_tasks.column(history))
    assert shown.state == "needs-you"
    assert shown.badge is True
    assert shown.motion == "wave"
    assert shown.task_name == "Hold the sheet"


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
