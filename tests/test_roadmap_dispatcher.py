"""Tests for the autonomous roadmap loop.

Covers:
  * `roadmap_source.fetch_pending()` reads ROADMAP.md + dedups against
    the completed-ids state file.
  * Priority extraction (#P0 / #P1 / #P2) maps to high / med / low.
  * Department parsing — explicit `(dept)` annotation wins; keyword
    guesser falls back when the annotation is missing.
  * `roadmap_dispatcher.tick()` enqueues new items not in state.
  * Re-tick is idempotent (same items not re-enqueued).
  * Priority ordering honoured (#P0 items get a low priority int so the
    main dispatcher runs them first).
  * Lock prevents double-enqueue under concurrent ticks.
  * GitHub-issue source returns gracefully if `gh` isn't installed
    (no crash, empty list).
  * `mark_complete` writes the id and a re-fetch filters it out.
  * Throttling — back-to-back ticks short-circuit.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _force_top_level_agents() -> None:
    """Mirror the helper in test_agents_cloud — ensure `import agents`
    resolves to repo-root `agents/`, not `app/agents/`."""
    sys.path.insert(0, str(REPO_ROOT))
    for mod_name in list(sys.modules):
        if mod_name == "agents" or mod_name.startswith("agents."):
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _isolate_agents_package(monkeypatch, tmp_path):
    """Force-purge cached modules + redirect state/queue paths into
    tmp_path so tests never write to the real repo state."""
    _force_top_level_agents()
    from agents import queue as queue_mod
    from agents import roadmap_dispatcher
    from agents import roadmap_source

    # Redirect queue storage roots.
    monkeypatch.setattr(queue_mod, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(queue_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(queue_mod, "LOGS_DIR", tmp_path / "logs")
    # Redirect roadmap-dispatcher state paths.
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(roadmap_dispatcher, "STATE_DIR", state_dir)
    monkeypatch.setattr(roadmap_dispatcher, "COMPLETED_IDS_PATH",
                        state_dir / "completed_roadmap_ids.txt")
    monkeypatch.setattr(roadmap_dispatcher, "LOCK_PATH", state_dir / "lock.txt")
    monkeypatch.setattr(roadmap_dispatcher, "LAST_TICK_PATH",
                        state_dir / "last_tick.txt")
    yield


# ---------------------------------------------------------------------------
def _write_roadmap(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "ROADMAP.md"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
class TestRoadmapSource:
    def test_reads_pending_bullets(self, tmp_path, monkeypatch):
        from agents import roadmap_source
        md = (
            "# Roadmap\n\n"
            "## NEXT 7 DAYS\n\n"
            "- [ ] #P0 Frontend invite acceptance page (eng)\n"
            "- [ ] #P1 Trust center page (docs)\n"
            "- [x] #P2 Already-shipped item should be ignored\n\n"
            "## Done — last 7 days\n\n"
            "- [ ] #P0 Something completed (eng)\n"
        )
        p = _write_roadmap(tmp_path, md)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent_changelog.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        items = roadmap_source.fetch_pending(include_github=False)
        titles = [i.title for i in items]
        assert "Frontend invite acceptance page" in titles
        assert "Trust center page" in titles
        # Bullet in Done section is skipped
        assert "Something completed" not in titles
        # Checked bullet is skipped
        assert all("Already-shipped" not in t for t in titles)

    def test_priority_extraction(self, tmp_path, monkeypatch):
        from agents import roadmap_source
        md = (
            "## NEXT\n"
            "- [ ] #P0 High priority item (eng)\n"
            "- [ ] #P1 Medium priority item (eng)\n"
            "- [ ] #P2 Low priority item (eng)\n"
            "- [ ] Untagged item defaults to med (eng)\n"
        )
        p = _write_roadmap(tmp_path, md)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        items = {i.title: i for i in
                 roadmap_source.fetch_pending(include_github=False)}
        assert items["High priority item"].priority == "high"
        assert items["Medium priority item"].priority == "med"
        assert items["Low priority item"].priority == "low"
        assert items["Untagged item defaults to med"].priority == "med"

    def test_dept_annotation_wins_over_keyword(self, tmp_path, monkeypatch):
        from agents import roadmap_source
        md = (
            "## NEXT\n"
            # Has 'test' keyword (qa) but annotates eng — annotation wins
            "- [ ] #P1 Write end-to-end test fixture (eng)\n"
            # No annotation — keyword falls back to docs (no eng kw)
            "- [ ] #P1 Add trust center page\n"
        )
        p = _write_roadmap(tmp_path, md)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        items = {i.title: i for i in
                 roadmap_source.fetch_pending(include_github=False)}
        assert items["Write end-to-end test fixture"].suggested_dept == "eng"
        # 'trust center' / 'page' → docs
        assert items["Add trust center page"].suggested_dept == "docs"

    def test_dedup_against_completed_state(self, tmp_path, monkeypatch):
        from agents import roadmap_source
        md = (
            "## NEXT\n"
            "- [ ] #P0 Keep me (eng)\n"
            "- [ ] #P0 Hide me (eng)\n"
        )
        p = _write_roadmap(tmp_path, md)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        # Probe with no state — both visible
        items = roadmap_source.fetch_pending(include_github=False)
        titles = sorted(i.title for i in items)
        assert titles == ["Hide me", "Keep me"]

        # Write the "Hide me" id into the state file
        hide_id = next(i.id for i in items if i.title == "Hide me")
        state = tmp_path / "completed.txt"
        state.write_text(f"{hide_id}\n", encoding="utf-8")

        items2 = roadmap_source.fetch_pending(
            include_github=False, state_path=state)
        titles2 = [i.title for i in items2]
        assert titles2 == ["Keep me"]

    def test_priority_sort_ordering(self, tmp_path, monkeypatch):
        from agents import roadmap_source
        md = (
            "## NEXT\n"
            "- [ ] #P2 Low item (eng)\n"
            "- [ ] #P0 High item (eng)\n"
            "- [ ] #P1 Mid item (eng)\n"
        )
        p = _write_roadmap(tmp_path, md)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        items = roadmap_source.fetch_pending(include_github=False)
        order = [i.priority for i in items]
        # High → med → low
        assert order == ["high", "med", "low"]

    def test_github_source_graceful_without_gh(self, tmp_path, monkeypatch):
        """Sub-process call to `gh` must fail cleanly (no crash) when
        the binary isn't installed."""
        from agents import roadmap_source

        def _no_gh(*args, **kwargs):
            raise FileNotFoundError("gh not installed")

        monkeypatch.setattr(subprocess, "run", _no_gh)
        # Both helpers must return [] without raising.
        assert roadmap_source._read_github_issues() == []
        assert roadmap_source._read_github_prs() == []

    def test_github_source_handles_non_zero_exit(self, monkeypatch):
        """gh exits non-zero (e.g. unauthenticated). Source returns []."""
        from agents import roadmap_source

        class _FakeProc:
            returncode = 1
            stdout = ""
            stderr = "gh: not logged in"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
        assert roadmap_source._read_github_issues() == []
        assert roadmap_source._read_github_prs() == []

    def test_source_comment_pickup(self, tmp_path, monkeypatch):
        """`# ROADMAP:` prefix inside a tracked file shows up as an item."""
        from agents import roadmap_source
        # Create a fake source file inside tmp_path and point the
        # source-comment glob at it.
        src = tmp_path / "fake_main.py"
        src.write_text(
            "# Normal comment\n"
            "# ROADMAP: #P1 Wire up quota check in proxy (eng)\n"
            "x = 1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(roadmap_source, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS",
                            ["fake_main.py"])
        # Also disable the other two file sources to keep results clean.
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH",
                            tmp_path / "absent_roadmap.md")
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent_changelog.md")
        items = roadmap_source.fetch_pending(include_github=False)
        titles = [i.title for i in items]
        assert any("Wire up quota check" in t for t in titles)


# ---------------------------------------------------------------------------
class TestRoadmapDispatcher:
    def _setup_roadmap(self, tmp_path, monkeypatch, body):
        from agents import roadmap_source
        p = _write_roadmap(tmp_path, body)
        monkeypatch.setattr(roadmap_source, "ROADMAP_PATH", p)
        monkeypatch.setattr(roadmap_source, "CHANGELOG_PATH",
                            tmp_path / "absent_changelog.md")
        monkeypatch.setattr(roadmap_source, "SOURCE_COMMENT_GLOBS", [])
        # Block external network sources for deterministic tests.
        monkeypatch.setattr(roadmap_source, "_read_github_issues", lambda: [])
        monkeypatch.setattr(roadmap_source, "_read_github_prs", lambda: [])

    def test_tick_enqueues_new_items(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P0 First item (eng)\n"
            "- [ ] #P1 Second item (docs)\n"
        ))
        q = TaskQueue(root=tmp_path / "tasks")
        result = roadmap_dispatcher.tick(queue=q, force=True)
        assert result.enqueued == 2
        assert result.error is None
        # Both task yamls exist on disk
        eng_files = list((tmp_path / "tasks" / "eng").glob("*.yaml"))
        docs_files = list((tmp_path / "tasks" / "docs").glob("*.yaml"))
        assert len(eng_files) == 1
        assert len(docs_files) == 1

    def test_tick_is_idempotent(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P0 An item (eng)\n"
        ))
        q = TaskQueue(root=tmp_path / "tasks")
        first = roadmap_dispatcher.tick(queue=q, force=True)
        second = roadmap_dispatcher.tick(queue=q, force=True)
        third = roadmap_dispatcher.tick(queue=q, force=True)
        assert first.enqueued == 1
        assert second.enqueued == 0
        assert third.enqueued == 0
        assert second.skipped_already_queued == 1
        # Still only one yaml file
        eng_files = list((tmp_path / "tasks" / "eng").glob("*.yaml"))
        assert len(eng_files) == 1

    def test_priority_ordering_in_queue(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P2 Low one (eng)\n"
            "- [ ] #P0 High one (eng)\n"
            "- [ ] #P1 Mid one (eng)\n"
        ))
        q = TaskQueue(root=tmp_path / "tasks")
        roadmap_dispatcher.tick(queue=q, force=True)
        pending = q.list_pending()
        # list_pending sorts by priority ascending → high (10) first
        priorities = [t.priority for t in pending]
        assert priorities == sorted(priorities)
        assert pending[0].priority == 10   # #P0 -> 10
        assert "High one" in pending[0].title

    def test_lock_prevents_double_enqueue(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P0 Locked item (eng)\n"
        ))
        q = TaskQueue(root=tmp_path / "tasks")
        # Pre-create the lock file → simulate concurrent tick already
        # in flight.
        roadmap_dispatcher._ensure_state()
        roadmap_dispatcher.LOCK_PATH.touch(exist_ok=False)
        try:
            result = roadmap_dispatcher.tick(queue=q, force=True)
            assert result.locked is True
            assert result.enqueued == 0
            # Nothing on disk under tasks/
            assert not (tmp_path / "tasks" / "eng").exists() or not list(
                (tmp_path / "tasks" / "eng").glob("*.yaml"))
        finally:
            roadmap_dispatcher.LOCK_PATH.unlink(missing_ok=True)

    def test_mark_complete_blocks_re_enqueue(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher, roadmap_source
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P0 Done already (eng)\n"
        ))
        q = TaskQueue(root=tmp_path / "tasks")
        # Pre-mark the item complete so a tick should skip it.
        items = roadmap_source.fetch_pending(include_github=False)
        roadmap_dispatcher.mark_complete(items[0].id)
        result = roadmap_dispatcher.tick(queue=q, force=True)
        assert result.enqueued == 0
        assert result.skipped_already_done == 1

    def test_disabled_env_var_short_circuits(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n- [ ] #P0 Item (eng)\n"
        ))
        monkeypatch.setenv("ARCHHUB_ROADMAP_DISABLED", "1")
        q = TaskQueue(root=tmp_path / "tasks")
        result = roadmap_dispatcher.tick(queue=q, force=True)
        assert result.enqueued == 0
        assert "disabled" in (result.error or "").lower()

    def test_throttle_short_circuits_second_tick(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n- [ ] #P0 Item (eng)\n"
        ))
        # Default interval 30 min. First tick (force=False) runs because
        # last_tick.txt is absent. Second tick (force=False) must be
        # throttled.
        q = TaskQueue(root=tmp_path / "tasks")
        first = roadmap_dispatcher.tick(queue=q, force=False)
        second = roadmap_dispatcher.tick(queue=q, force=False)
        assert first.enqueued == 1
        assert second.throttled is True
        assert second.enqueued == 0

    def test_pending_completed_counts(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n"
            "- [ ] #P0 First (eng)\n"
            "- [ ] #P1 Second (eng)\n"
        ))
        assert roadmap_dispatcher.pending_count() == 2
        assert roadmap_dispatcher.completed_count() == 0
        # Mark one complete
        from agents import roadmap_source
        items = roadmap_source.fetch_pending(include_github=False)
        roadmap_dispatcher.mark_complete(items[0].id)
        assert roadmap_dispatcher.pending_count() == 1
        assert roadmap_dispatcher.completed_count() == 1

    def test_force_bypasses_throttle(self, tmp_path, monkeypatch):
        from agents import roadmap_dispatcher
        from agents.queue import TaskQueue
        self._setup_roadmap(tmp_path, monkeypatch, (
            "## NEXT\n- [ ] #P0 Item (eng)\n"
        ))
        # Pre-write a fresh last_tick so non-force would throttle.
        now = datetime.now(timezone.utc).isoformat()
        roadmap_dispatcher.LAST_TICK_PATH.parent.mkdir(parents=True, exist_ok=True)
        roadmap_dispatcher.LAST_TICK_PATH.write_text(now, encoding="utf-8")
        q = TaskQueue(root=tmp_path / "tasks")
        # force=True ignores the throttle
        result = roadmap_dispatcher.tick(queue=q, force=True)
        assert result.throttled is False
        assert result.enqueued == 1
