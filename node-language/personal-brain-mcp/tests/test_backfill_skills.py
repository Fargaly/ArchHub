"""Tests for tools/backfill_skills.py — skill backfill from real traces.

The backfill tool lives under ``ArchHub/tools/`` (outside the
``personal-brain-mcp`` package), so we add the repo's ``tools/`` dir to
``sys.path`` to import it. ``personal_brain`` itself is already importable
from the package ``src`` on the pytest path.

Coverage:
  1. synth-trace path: 2 fake commits -> >= 1 skill minted, after > before.
  2. idempotent-ish: re-running doesn't duplicate identically-named skills.
  3. a trace with < 2 ok calls is skipped by the gate / floor.
  4. promote path: a minted skill promoted to COMMUNITY is retrievable at
     community scope (i.e. what ``brain.skill_export(scope=community)`` reads).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── import the tool under test (ArchHub/tools/backfill_skills.py) ──
_REPO = Path(__file__).resolve().parents[2]          # .../ArchHub
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import backfill_skills as bf  # noqa: E402

from personal_brain.models import Scope, Visibility  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


# ───────────────────────── fixtures / helpers ──────────────────────────


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _commit_trace(trace_id: str, subject: str, n_files: int) -> dict:
    """A synth-style trace mirroring what _synth_traces_from_git emits:
    N files -> N ok tool_calls, outcome=success. The first tool name is
    derived from the commit type (as the real synth does) so distinct
    commit types yield distinct skill names."""
    ctype = subject.split("(")[0].split(":")[0].strip() or "feat"
    tool_calls = [{"name": f"{ctype}_apply", "status": "ok"}]
    for i in range(1, n_files):
        tool_calls.append({"name": f"{ctype}_step_{i}", "status": "ok"})
    return {
        "trace_id": trace_id,
        "tool_calls": tool_calls,
        "outcome": "success",
        "summary": subject,
        "user_message": subject,
    }


# ───────────────────────── 1. synth-trace path ─────────────────────────


def test_synth_traces_mint_at_least_one_skill(store):
    """Two fake commits -> >= 1 skill minted, skills_after > before."""
    traces = [
        _commit_trace("git:aaa", "feat(cloud): wire sync round-trip", 3),
        _commit_trace("git:bbb", "docs(viz): document the brain graph", 4),
    ]
    before = store.count_skills()
    result = bf.backfill(store, traces, owner_user="founder")

    assert result["skills_before"] == before
    assert result["minted"] >= 1, result
    assert result["skills_after"] > result["skills_before"], result
    # Every minted skill went through a known path.
    assert result["by_path"]["gate"] + result["by_path"]["direct"] >= 1
    # The store actually grew.
    assert store.count_skills() == result["skills_after"]
    assert store.count_skills() > before


def test_synth_from_git_helper_shapes_traces():
    """_synth_traces_from_git produces floor-clearing traces from real
    commits in THIS repo (every trace has >= 2 ok calls + success)."""
    traces = bf._synth_traces_from_git(_REPO, n=15)
    assert traces, "expected at least one conventional commit in git log"
    for t in traces:
        ok = [tc for tc in t["tool_calls"] if tc.get("status") == "ok"]
        assert len(ok) >= 2, t
        assert t["outcome"] == "success"


# ───────────────────────── 2. idempotency ──────────────────────────────


def test_rerun_does_not_duplicate_skills(store):
    """Re-running the same traces does not create duplicate skills.

    upsert is keyed by id (deterministic from name+description+owner) and
    name is UNIQUE, so an identical trace re-mints to the SAME row.
    """
    traces = [
        _commit_trace("git:aaa", "feat(cloud): wire sync round-trip", 3),
        _commit_trace("git:bbb", "docs(viz): document the brain graph", 4),
    ]
    bf.backfill(store, traces, owner_user="founder")
    count_after_first = store.count_skills()

    # Re-run with the exact same traces.
    result2 = bf.backfill(store, traces, owner_user="founder")
    count_after_second = store.count_skills()

    assert count_after_second == count_after_first, (
        f"second run changed skill count {count_after_first} -> "
        f"{count_after_second}"
    )
    # Names are unique — no two skills share a name.
    names = [s.name for s in store.list_skills(owner_user="founder", limit=500)]
    assert len(names) == len(set(names)), f"duplicate names: {names}"


# ───────────────────────── 3. sub-floor trace skipped ──────────────────


def test_trace_with_one_ok_call_is_skipped(store):
    """A trace with < 2 ok tool_calls never mints (mirrors the >= 2 floor)."""
    bad = {
        "trace_id": "git:short",
        "tool_calls": [{"name": "feat_apply", "status": "ok"}],
        "outcome": "success",
        "user_message": "feat: one-liner",
    }
    before = store.count_skills()
    result = bf.backfill(store, [bad], owner_user="founder")

    assert result["minted"] == 0, result
    assert result["skipped"] == 1, result
    # No PROJECT/USER skill landed from the bad trace (community count is 0).
    assert store.count_skills() == before


def test_failed_outcome_trace_is_skipped(store):
    """A trace whose outcome != success is skipped even with >= 2 ok calls."""
    failed = {
        "trace_id": "git:failed",
        "tool_calls": [
            {"name": "feat_apply", "status": "ok"},
            {"name": "feat_step_1", "status": "ok"},
        ],
        "outcome": "failure",
        "user_message": "feat: aborted",
    }
    result = bf.backfill(store, [failed], owner_user="founder")
    assert result["minted"] == 0, result
    assert result["skipped"] == 1, result


# ───────────────────────── 4. promote path ─────────────────────────────


def test_promoted_skill_retrievable_at_community_scope(store):
    """A minted generic skill, once promoted, is retrievable at COMMUNITY
    scope — exactly what brain.skill_export(scope=community) reads."""
    traces = [
        _commit_trace("git:aaa", "feat(cloud): wire sync round-trip", 3),
        _commit_trace("git:bbb", "docs(brain): index the library", 2),
    ]
    assert store.count_skills(scope=Scope.COMMUNITY) == 0

    result = bf.backfill(store, traces, owner_user="founder")

    # Promotion happened and community export is now non-empty.
    assert result["promoted"] >= 1, result
    community = store.list_skills(scope=Scope.COMMUNITY, limit=50)
    assert len(community) >= 1, "expected >= 1 community skill"
    # Every community skill is public + correctly scoped.
    for sk in community:
        assert sk.scope == Scope.COMMUNITY
        assert sk.visibility == Visibility.SHARED_PUBLIC
    # count_skills(scope=COMMUNITY) agrees with the export list.
    assert store.count_skills(scope=Scope.COMMUNITY) == len(community)


def test_promotion_is_idempotent(store):
    """Re-running backfill doesn't keep stacking community copies."""
    traces = [_commit_trace("git:aaa", "feat(cloud): wire sync", 3)]
    bf.backfill(store, traces, owner_user="founder")
    comm_first = store.count_skills(scope=Scope.COMMUNITY)
    bf.backfill(store, traces, owner_user="founder")
    comm_second = store.count_skills(scope=Scope.COMMUNITY)
    assert comm_first == comm_second, (comm_first, comm_second)


def test_promote_helper_directly(store):
    """_promote_to_community returns the live community count and tags
    skills SHARED_PUBLIC."""
    # Mint one generic skill first via the direct path.
    trace = _commit_trace("git:ccc", "test(brain): cover the gate", 3)
    res = bf._mint_one(store, trace, owner_user="founder")
    assert res["minted"], res

    n = bf._promote_to_community(store, owner_user="founder")
    assert n >= 1
    assert store.count_skills(scope=Scope.COMMUNITY) == n


# ───────────────────────── return-shape contract ───────────────────────


def test_backfill_return_shape(store):
    traces = [_commit_trace("git:aaa", "feat(x): y", 3)]
    result = bf.backfill(store, traces, owner_user="founder")
    assert set(result) == {
        "minted", "promoted", "skipped",
        "skills_before", "skills_after", "by_path",
    }
    assert set(result["by_path"]) == {"gate", "direct"}
    assert all(isinstance(result[k], int)
               for k in ("minted", "promoted", "skipped",
                         "skills_before", "skills_after"))
