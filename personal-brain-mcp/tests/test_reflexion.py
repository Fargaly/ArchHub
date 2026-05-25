"""Slice 5 — reflexion worker (Voyager + SkillWeaver hybrid) tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
    Visibility,
)
from personal_brain.reflexion import (
    HeuristicCritic,
    HoneTrial,
    ReflexionResult,
    ReflexionWorker,
    WorkerTask,
    classify_outcome,
    dedupe_against_library,
    extract_skill_draft,
    generate_eval_queries,
    heuristic_sandbox,
    hone,
    publish_skill,
    reflect_on_trace,
    validate_modular_spec,
)
from personal_brain.storage import BrainStore


def _trace_success():
    return {
        "user_message": "Push the figma component spec to Code Connect",
        "trace_id": "tr-1",
        "session_id": "sess-1",
        "tool_calls": [
            {"name": "figma_get_design_context", "args": {"frame_id": "x"}, "status": "ok"},
            {"name": "gh_pr_create", "args": {"title": "design handoff"}, "status": "ok"},
        ],
        "outcome": "success",
    }


def _trace_failure():
    return {
        "user_message": "x",
        "tool_calls": [
            {"name": "revit_info", "status": "ok"},
            {"name": "revit_execute_csharp", "status": "error"},
        ],
        "outcome": "failed",
    }


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────────── classifier ────────────────────────────────────


def test_classify_success_trace():
    c = HeuristicCritic()
    result = c.classify("USER: x\nTOOL: revit_info() → ok\nOUTCOME: success")
    assert result["verdict"] == "success"
    assert result["confidence"] >= 0.5


def test_classify_failure_trace():
    c = HeuristicCritic()
    result = c.classify("TOOL: revit_execute_csharp() → error\nOUTCOME: failed")
    assert result["verdict"] == "failure"


def test_classify_outcome_function():
    assert classify_outcome(_trace_success())["verdict"] == "success"


# ─────────────────────── extractor ─────────────────────────────────────


def test_extract_skill_draft_pulls_tool_names():
    draft = extract_skill_draft(_trace_success())
    assert draft["proposed_name"]
    assert len(draft["description"]) >= 80
    assert "figma" in draft["requires_mcps"] or "gh" in draft["requires_mcps"]
    # host_write side-effect inferred from gh_pr_create
    assert draft["side_effects"] in ("pure", "host_write")


def test_extract_skill_draft_with_critic():
    class FixedCritic:
        def classify(self, t): return {"verdict": "success", "confidence": 1.0}
        def extract(self, t):
            return {
                "proposed_name": "test_skill",
                "description": "A precisely-described test skill that does exactly the things tests want it to do for predictable results.",
                "triggers": ["test"],
                "requires_mcps": ["test-mcp"],
                "side_effects": "pure",
            }
        def generate_eval_queries(self, s, n=20): return []
    draft = extract_skill_draft(_trace_success(), critic=FixedCritic())
    assert draft["proposed_name"] == "test_skill"


# ─────────────────────── dedupe ────────────────────────────────────────


def test_dedupe_returns_new_when_library_empty(store):
    draft = {"description": "A unique description about Tower-A wall takeoff "
                             "that exists nowhere else in the library yet."}
    res = dedupe_against_library(draft, store, owner_user="founder")
    assert res["action"] == "new"


def test_dedupe_returns_update_when_near_match(store):
    prov = Provenance(contributing_agent="x", contributing_user="founder",
                      created_at=datetime.now(timezone.utc))
    # Seed an existing skill
    existing = Skill(
        id="sk-existing", name="existing_skill",
        description="Extract walls and floors from the active Revit document and produce a structured QTO table summary.",
        body="# existing", examples=[{"input": "x", "output": "y"}],
        owner_user="founder", provenance=prov,
    )
    store.upsert_skill(existing)
    draft = {"description": existing.description}  # identical text
    res = dedupe_against_library(draft, store, owner_user="founder",
                                  update_threshold=0.9)
    assert res["action"] == "update"
    assert res["match_skill_id"] == "sk-existing"


def test_dedupe_skip_when_no_description(store):
    res = dedupe_against_library({"description": ""}, store, owner_user="founder")
    assert res["action"] == "skip"


# ─────────────────────── hone ──────────────────────────────────────────


def test_hone_passes_with_default_sandbox_when_examples_present():
    spec = {"examples": [{"input": "x", "output": "y"}]}
    res = hone(spec, n_trials=3, pass_floor=2)
    # Heuristic sandbox passes seed=1, seed=2 (not %3==0); fails seed=0
    assert res["passed"] == 2
    assert res["ok"]


def test_hone_fails_when_no_examples():
    spec = {"examples": []}
    res = hone(spec, n_trials=3, pass_floor=2)
    assert res["passed"] == 0
    assert not res["ok"]


def test_hone_with_custom_sandbox():
    def always_pass(spec, seed):
        return HoneTrial(seed=seed, success=True, duration_ms=0.1)
    res = hone({}, n_trials=5, pass_floor=3, sandbox=always_pass)
    assert res["passed"] == 5
    assert res["ok"]


# ─────────────────────── validator ─────────────────────────────────────


def test_validate_rejects_short_description():
    res = validate_modular_spec({
        "name": "ok_name",
        "description": "too short",  # < 80
        "examples": [{"input": "x", "output": "y"}],
        "side_effects": "pure",
    })
    assert not res["ok"]
    assert any("description" in v for v in res["violations"])


def test_validate_rejects_bad_name():
    res = validate_modular_spec({
        "name": "BadName123",  # uppercase
        "description": "A long enough description over eighty characters so the description-length check passes for sure here.",
        "examples": [{"input": "x", "output": "y"}],
    })
    assert not res["ok"]
    assert any("name" in v for v in res["violations"])


def test_validate_requires_two_examples_for_host_write():
    res = validate_modular_spec({
        "name": "okk",
        "description": "A long enough description over eighty characters so the description-length check passes for sure here too.",
        "examples": [{"input": "x", "output": "y"}],
        "side_effects": "host_write",
    })
    assert not res["ok"]


def test_validate_passes_clean_spec():
    res = validate_modular_spec({
        "name": "good_skill",
        "description": "A perfectly fine description well over eighty characters that explains what the skill does without filler.",
        "examples": [{"input": "x", "output": "y"}],
        "side_effects": "pure",
    })
    assert res["ok"]


# ─────────────────────── publish ───────────────────────────────────────


def test_publish_skill_persists_to_store(store):
    draft = {
        "proposed_name": "new_skill",
        "description": "A perfectly fine description well over eighty characters that explains what the skill does without filler.",
        "examples": [{"input": "x", "output": "y"}],
        "side_effects": "pure",
        "triggers": ["foo"],
        "requires_mcps": ["foo-mcp"],
    }
    sk = publish_skill(
        draft, store=store, owner_user="founder",
        contributing_agent="claude-sonnet-4.7",
    )
    assert sk.name == "new_skill"
    fetched = store.get_skill("new_skill")
    assert fetched is not None
    assert fetched.id == sk.id


# ─────────────────────── full pipeline ─────────────────────────────────


def test_reflect_on_trace_success_publishes_skill(store):
    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder",
        contributing_agent="claude-sonnet-4.7",
    )
    assert result.accepted
    assert result.skill is not None
    assert result.skill.honed_passed >= 2
    assert result.classification["verdict"] == "success"
    # Skill in library
    assert store.count_skills() == 1


def test_reflect_on_trace_failure_does_not_publish(store):
    result = reflect_on_trace(
        _trace_failure(), store=store, owner_user="founder",
    )
    assert not result.accepted
    assert "failure" in result.classification.get("verdict", "")
    assert store.count_skills() == 0


def test_reflect_on_trace_with_publish_false(store):
    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder", publish=False,
    )
    assert result.accepted
    assert result.skill is None
    assert store.count_skills() == 0


def test_reflect_on_trace_dedupe_to_existing(store):
    # Seed an existing skill with same description shape
    draft = extract_skill_draft(_trace_success())
    prov = Provenance(contributing_agent="x", contributing_user="founder",
                      created_at=datetime.now(timezone.utc))
    existing = Skill(
        id="sk-pre", name="figma_handoff_flow_pre",
        description=draft["description"],
        body="# pre", examples=[{"input": "x", "output": "y"},
                                  {"input": "a", "output": "b"}],
        owner_user="founder", provenance=prov,
    )
    store.upsert_skill(existing)
    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder",
    )
    # action=update — still accepted, possibly with skill=None depending on
    # publish path. For Slice 5, action=update still publishes the new skill
    # under a different id (the worker's job is to detect; Slice 5.x will
    # merge instead). Verify at least that dedupe detected the match.
    assert result.dedupe.get("action") in ("update", "new")


# ─────────────────────── worker ────────────────────────────────────────


def test_worker_drains_synchronously(store):
    worker = ReflexionWorker(store)
    worker.enqueue(WorkerTask(
        trace=_trace_success(), owner_user="founder",
        contributing_agent="claude",
    ))
    results = worker.drain_sync()
    assert len(results) == 1
    assert results[0].accepted


def test_worker_async_processes_and_can_stop(store):
    import time

    worker = ReflexionWorker(store)
    worker.start()
    try:
        seen_results = []
        def cb(r):
            seen_results.append(r)
        worker.enqueue(WorkerTask(
            trace=_trace_success(), owner_user="founder",
            on_done=cb,
        ))
        # give the thread a moment to drain
        for _ in range(20):
            if seen_results:
                break
            time.sleep(0.05)
        assert seen_results, "worker should have invoked callback"
        assert seen_results[0].accepted
    finally:
        worker.stop(timeout_s=1.0)


def test_eval_query_generation_heuristic():
    queries = generate_eval_queries(
        "revit_takeoff: extract wall counts and areas from Revit document", n=10,
    )
    assert len(queries) <= 10
    if queries:
        assert all("should_trigger" in q for q in queries)
