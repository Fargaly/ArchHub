"""Tests for agents.ceo_routine — the no-LLM hourly CEO loop.

Live production module (archhub-agents, runs via Task Scheduler) with ZERO
prior coverage (TCI-02). Exercises the real pure-logic units against an
isolated tmp filesystem (see conftest): the weekly idempotency of `_pick_move`,
`_file_task` writing a dispatcher-shaped YAML, `hourly_tick` filing a move +
appending to the CEO log, and `daily_brief` rolling the log into Markdown.
No git, no network, no real repo writes.
"""
from __future__ import annotations

import json

import agents.ceo_routine as ceo


def test_pick_move_returns_backlog_entry_when_none_recent():
    move = ceo._pick_move(pulse={}, recent=set())
    assert move is not None
    assert {"dept", "title", "instructions"} <= set(move.keys())


def test_pick_move_skips_titles_filed_this_week():
    """A title already filed within the week is excluded — the cheap
    idempotency that stops the CEO re-queuing the same move every hour."""
    all_titles = {b["title"] for b in ceo.BACKLOG}
    # Mark every backlog title as recent except one; that one must be chosen.
    keep = next(iter(all_titles))
    recent = all_titles - {keep}
    move = ceo._pick_move(pulse={}, recent=recent)
    assert move is not None
    assert move["title"] == keep


def test_pick_move_returns_none_when_all_recent():
    recent = {b["title"] for b in ceo.BACKLOG}
    assert ceo._pick_move(pulse={}, recent=recent) is None


def test_file_task_writes_dispatcher_shaped_yaml():
    fp = ceo._file_task("eng", "Audit the thing", "read X, propose patch")
    assert fp.exists()
    # Must live under the (isolated) tasks root, in the dept subdir.
    assert fp.parent == ceo.TASKS_ROOT / "eng"
    data = json.loads(fp.read_text(encoding="utf-8"))
    assert data["department"] == "eng"
    assert data["title"] == "Audit the thing"
    assert data["instructions"] == "read X, propose patch"
    assert "id" in data and data["id"].startswith("eng-")


def test_recent_titles_reads_back_filed_tasks():
    ceo._file_task("docs", "Daily standup brief", "do it")
    recent = ceo._recent_titles(hours=24 * 7)
    assert "Daily standup brief" in recent


def test_hourly_tick_files_move_and_appends_log():
    out = ceo.hourly_tick()
    assert "ts" in out and "pulse" in out
    # With a clean (empty) recent set, a move is filed.
    assert out["filed"] is not None
    assert "title" in out["filed"]

    # The per-day CEO log got the line appended.
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    log = ceo.CEO_OUT / f"{today}.log"
    assert log.exists()
    lines = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["filed"]["title"] == out["filed"]["title"]


def test_hourly_tick_files_nothing_when_backlog_exhausted(monkeypatch):
    """When every backlog title was already filed this week, the tick logs a
    no-op (filed is None) instead of duplicating work."""
    monkeypatch.setattr(ceo, "_recent_titles",
                        lambda hours=0: {b["title"] for b in ceo.BACKLOG},
                        raising=True)
    out = ceo.hourly_tick()
    assert out["filed"] is None


def test_daily_brief_renders_markdown_with_filed_tasks():
    # Seed a tick so the daily log has a filed entry to roll up.
    ceo.hourly_tick()
    md = ceo.daily_brief()
    assert md.startswith("# ArchHub — daily CEO brief")
    assert "## Department state" in md
    assert "## Tasks I auto-filed last 24h" in md
    assert "## Next 24h move" in md
