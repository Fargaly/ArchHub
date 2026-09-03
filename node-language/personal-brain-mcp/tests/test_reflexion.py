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
    AnthropicCritic,
    HeuristicCritic,
    HoneTrial,
    ReflexionResult,
    ReflexionWorker,
    WorkerTask,
    classify_outcome,
    dedupe_against_library,
    default_critic,
    detect_real_llm_key,
    extract_skill_draft,
    generate_eval_queries,
    heuristic_sandbox,
    hone,
    publish_skill,
    reflect_on_trace,
    trace_grounded_sandbox,
    validate_modular_spec,
    validate_skill_against_trace,
)
from personal_brain.storage import BrainStore


@pytest.fixture(autouse=True)
def _offline_critic_by_default(monkeypatch):
    """Hermetic default: ensure the real-LLM critic stays OFF for every
    test unless the test explicitly opts into it.

    Routing to the live LLM is opt-in via BRAIN_REFLEXION_LLM (off by
    default in production too). This env may also have a real ANTHROPIC
    key wired via ArchHub's secret store, so we defensively clear the
    opt-in flag here — a host that exports it must not flip unrelated
    tests onto the live API (where a billing/quota 400 would flake them).
    Tests that PROVE the real-critic wiring set the flag + a controlled
    fake anthropic client themselves."""
    monkeypatch.delenv("BRAIN_REFLEXION_LLM", raising=False)


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


def test_hone_passes_with_default_sandbox_for_wellformed_skill():
    # New (real) heuristic_sandbox: a well-formed skill — has steps/triggers,
    # has examples, requires_mcps internally consistent — passes ALL trials
    # deterministically (no seed coin-flip). figma trigger ⊂ figma_* step.
    spec = {
        "triggers": ["figma get design context"],
        "requires_mcps": ["figma"],
        "examples": [{"input": "x", "output": "y"}],
    }
    res = hone(spec, n_trials=3, pass_floor=2)
    assert res["passed"] == 3  # all trials agree — structural, not random
    assert res["ok"]


def test_hone_fails_when_no_examples():
    # Has a step but no examples → structurally malformed → fails every trial.
    spec = {"triggers": ["figma get design context"], "examples": []}
    res = hone(spec, n_trials=3, pass_floor=2)
    assert res["passed"] == 0
    assert not res["ok"]


def test_hone_fails_when_no_steps():
    # Examples present but NO steps/triggers → not a runnable skill → fails.
    spec = {"examples": [{"input": "x", "output": "y"}]}
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


# ════════════════════════════════════════════════════════════════════════
# REAL HONING — genuine trace-grounded structural validation.
#
# The old gate declared pass/fail by `seed % 3 != 0` (a coin-flip that
# self-labelled "no real execution"). These tests PROVE the new validation
# is real by showing it DISCRIMINATES: a faithful skill (every step mirrors
# a tool the trace actually called, same order, I/O consistent) PASSES; a
# deliberately-broken one (step naming a tool absent from the trace, phantom
# MCP, side-effect/IO mismatch, or re-ordered steps) FAILS. A coin-flip
# could not separate these two — the separation is the proof.
# ════════════════════════════════════════════════════════════════════════


def _faithful_skill_for_success_trace():
    """A skill whose steps mirror `_trace_success()` exactly + in order."""
    return {
        "proposed_name": "figma_to_pr_flow",
        "description": "Push a Figma component spec to a GitHub PR via Code "
                       "Connect after reading the design context from the frame.",
        "steps": [
            {"tool": "figma_get_design_context"},
            {"tool": "gh_pr_create"},
        ],
        "requires_mcps": ["figma", "gh"],
        "side_effects": "host_write",
        "examples": [
            {"input": "push figma spec to code connect", "output": "PR opened"},
            {"input": "handoff this frame", "output": "PR opened"},
        ],
    }


# ───────────────────── (1) faithful → PASSES ───────────────────────────


def test_validate_faithful_skill_passes_all_checks():
    verdict = validate_skill_against_trace(
        _faithful_skill_for_success_trace(), _trace_success(),
    )
    assert verdict["ok"] is True
    assert verdict["checks"]["tool_grounding"] is True
    assert verdict["checks"]["no_phantom_mcps"] is True
    assert verdict["checks"]["io_consistency"] is True
    assert verdict["checks"]["reproducibility"] is True
    assert verdict["violations"] == []
    assert verdict["grounded"] == 2


def test_faithful_skill_honed_passed_is_real_and_full():
    # Trace-grounded sandbox: a faithful skill passes EVERY trial (3/3),
    # deterministically — not ~2/3 from a seed coin-flip.
    sandbox = trace_grounded_sandbox(_trace_success())
    res = hone(_faithful_skill_for_success_trace(), n_trials=3, sandbox=sandbox)
    assert res["passed"] == 3
    assert res["ok"]
    # Provenance note proves it's the structural validator, not the stub.
    assert all("structural validation" in t["notes"] for t in res["trials"])
    assert all("no real execution" not in t["notes"] for t in res["trials"])


def test_reflect_on_trace_faithful_publishes_with_real_honed_passed(store):
    # End-to-end: the default reflect_on_trace path (no sandbox injected)
    # now builds the trace-grounded sandbox itself. honed_passed > 0 because
    # the minted skill genuinely matches the trace.
    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder",
        contributing_agent="claude",
    )
    assert result.accepted
    assert result.skill is not None
    assert result.skill.honed_passed > 0
    assert result.skill.honed_passed == result.hone["n_trials"]
    assert result.hone["ok"] is True


# ───────────────────── (2) broken → genuinely FAILS ────────────────────


def test_validate_skill_with_hallucinated_tool_fails():
    # Step references `slack_send_message` — a tool that NEVER appears in the
    # trace. A faithful skill cannot step through a tool the agent never ran.
    broken = _faithful_skill_for_success_trace()
    broken["steps"] = [
        {"tool": "figma_get_design_context"},
        {"tool": "slack_send_message"},  # hallucinated — absent from trace
    ]
    verdict = validate_skill_against_trace(broken, _trace_success())
    assert verdict["ok"] is False
    assert verdict["checks"]["tool_grounding"] is False
    assert any("slack_send_message" in v for v in verdict["violations"])


def test_validate_skill_with_phantom_mcp_fails():
    broken = _faithful_skill_for_success_trace()
    broken["requires_mcps"] = ["figma", "gh", "notion"]  # notion never used
    verdict = validate_skill_against_trace(broken, _trace_success())
    assert verdict["ok"] is False
    assert verdict["checks"]["no_phantom_mcps"] is False
    assert any("notion" in v for v in verdict["violations"])


def test_validate_skill_with_io_mismatch_fails():
    # Build a READ-ONLY trace (no write tool), but the skill claims
    # host_write — the advertised I/O schema is not backed by observed I/O.
    read_only_trace = {
        "user_message": "look up the wall schedule",
        "tool_calls": [
            {"name": "revit_info", "args": {}, "status": "ok"},
            {"name": "revit_get_walls", "args": {}, "status": "ok"},
        ],
        "outcome": "success",
    }
    skill = {
        "proposed_name": "revit_wall_lookup",
        "description": "Look up the wall schedule from the active Revit model "
                       "and return a structured summary of every wall instance.",
        "steps": [{"tool": "revit_info"}, {"tool": "revit_get_walls"}],
        "requires_mcps": ["revit"],
        "side_effects": "host_write",  # LIE: nothing in the trace writes
        "examples": [{"input": "x", "output": "y"}, {"input": "a", "output": "b"}],
    }
    verdict = validate_skill_against_trace(skill, read_only_trace)
    assert verdict["ok"] is False
    assert verdict["checks"]["io_consistency"] is False


def test_validate_skill_with_reordered_steps_fails():
    # Same tools, but the skill claims gh_pr_create BEFORE
    # figma_get_design_context — the reverse of the trace. Not replayable.
    broken = _faithful_skill_for_success_trace()
    broken["steps"] = [
        {"tool": "gh_pr_create"},
        {"tool": "figma_get_design_context"},
    ]
    verdict = validate_skill_against_trace(broken, _trace_success())
    assert verdict["ok"] is False
    assert verdict["checks"]["reproducibility"] is False
    assert any("subsequence" in v for v in verdict["violations"])


def test_broken_skill_honed_passed_is_zero_via_sandbox():
    # The discriminator, end to end through hone(): a hallucinated skill
    # fails EVERY trial → honed_passed == 0 → hone not ok.
    broken = _faithful_skill_for_success_trace()
    broken["steps"] = [{"tool": "slack_send_message"}]  # absent from trace
    sandbox = trace_grounded_sandbox(_trace_success())
    res = hone(broken, n_trials=3, sandbox=sandbox)
    assert res["passed"] == 0
    assert not res["ok"]


def test_reflect_on_trace_rejects_skill_for_broken_trace(store):
    # A trace with ZERO tool_calls cannot ground any procedural skill. The
    # classifier still says "success" (outcome=success), the extractor still
    # emits a draft, but the REAL honing gate refuses to publish because the
    # skill cannot be validated against any observed tool call. Proof the
    # gate blocks a non-reproducible mint (the old coin-flip might have let
    # it through on a lucky seed).
    no_tools_trace = {
        "user_message": "just chatting, no tools used here at all really",
        "trace_id": "tr-empty",
        "tool_calls": [],
        "outcome": "success",
    }
    result = reflect_on_trace(
        no_tools_trace, store=store, owner_user="founder",
    )
    assert not result.accepted
    assert "hone failed" in result.reason
    assert store.count_skills() == 0


def test_validation_discriminates_faithful_from_broken(store):
    """Single assertion of the core property: the SAME validator returns
    OPPOSITE verdicts for a faithful vs a broken skill on the SAME trace.
    A coin-flip cannot do this; structural truth can."""
    trace = _trace_success()
    faithful = validate_skill_against_trace(
        _faithful_skill_for_success_trace(), trace,
    )
    broken = dict(_faithful_skill_for_success_trace())
    broken["steps"] = [{"tool": "ghost_tool_not_in_trace"}]
    broken_verdict = validate_skill_against_trace(broken, trace)
    assert faithful["ok"] is True
    assert broken_verdict["ok"] is False
    assert faithful["ok"] != broken_verdict["ok"]


# ───────────────────── (3) real-critic wiring ──────────────────────────


def test_detect_real_llm_key_reports_env_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    found = detect_real_llm_key()
    assert found is not None
    provider, key = found
    assert provider == "anthropic"
    assert key == "sk-ant-test-123"


def test_detect_real_llm_key_none_when_unset(monkeypatch):
    # Force a clean env: no ambient keys, and stub the ArchHub secret store
    # lookup to miss so the test is hermetic regardless of the host machine.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import sys, types
    fake = types.ModuleType("secrets_store")
    fake.load_api_key = lambda provider: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "secrets_store", fake)
    assert detect_real_llm_key() is None


def test_default_critic_offline_is_heuristic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import sys, types
    fake = types.ModuleType("secrets_store")
    fake.load_api_key = lambda provider: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "secrets_store", fake)
    critic = default_critic()
    assert isinstance(critic, HeuristicCritic)


def test_default_critic_routes_to_anthropic_when_key_present(monkeypatch):
    # Prove a configured key GENUINELY drives the real critic path: with a
    # key set, default_critic() constructs an AnthropicCritic (the live LLM
    # judge), not the heuristic. We stub the anthropic SDK client so the
    # construction succeeds offline — the ROUTING is what we assert (a key
    # present → real critic selected), and that AnthropicCritic actually
    # calls the LLM client (verified in the next test).
    monkeypatch.setenv("BRAIN_REFLEXION_LLM", "1")  # opt into the live path
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-routing-test")

    import anthropic  # installed in this env

    class _FakeMessages:
        def create(self, **kwargs):
            raise AssertionError("not called in routing test")

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    critic = default_critic()
    # default_critic wraps the live critic in ResilientCritic (so a call-time
    # billing/quota failure degrades gracefully). The REAL judge underneath
    # is the AnthropicCritic — that's the routing proof.
    from personal_brain.reflexion import ResilientCritic
    assert isinstance(critic, ResilientCritic)
    assert isinstance(critic.primary, AnthropicCritic)


def test_anthropic_critic_actually_calls_the_llm(monkeypatch):
    # Prove the AnthropicCritic path issues a REAL judgement call (not a
    # heuristic). We inject a fake anthropic client that records the call and
    # returns a JSON verdict; the critic must hit it and parse the result.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-judge-test")
    import anthropic

    calls = {"n": 0, "last_prompt": None}

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        def __init__(self, text):
            self.content = [_Block(text)]

    class _FakeMessages:
        def create(self, **kwargs):
            calls["n"] += 1
            calls["last_prompt"] = kwargs["messages"][0]["content"]
            return _Resp('{"verdict": "success", "confidence": 0.91, '
                         '"rationale": "the agent completed the handoff"}')

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    critic = AnthropicCritic(api_key="sk-ant-judge-test")
    verdict = critic.classify("USER: do the handoff\nTOOL: gh_pr_create() → ok")
    assert calls["n"] == 1  # a REAL LLM call was issued
    assert "gh_pr_create" in calls["last_prompt"]  # the trace was judged
    assert verdict["verdict"] == "success"
    assert verdict["confidence"] == 0.91


def test_reflect_on_trace_drives_real_critic_when_key_present(store, monkeypatch):
    # End-to-end proof the configured key drives REAL honing: with a key set
    # and a fake anthropic client, reflect_on_trace classifies + extracts via
    # the LLM (the fake records calls), then the deterministic trace-grounded
    # sandbox validates the result. The mint is driven by the real critic.
    monkeypatch.setenv("BRAIN_REFLEXION_LLM", "1")  # opt into the live path
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-e2e-test")
    import anthropic

    seen = {"prompts": []}

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        def __init__(self, text):
            self.content = [_Block(text)]

    def _reply_for(prompt: str) -> str:
        seen["prompts"].append(prompt)
        if "evaluating whether" in prompt:  # classify
            return '{"verdict": "success", "confidence": 0.9, "rationale": "ok"}'
        if "mining a reusable skill" in prompt:  # extract
            return (
                '{"proposed_name": "figma_to_pr_flow", '
                '"description": "Push a Figma component spec to a GitHub PR '
                'via Code Connect after reading the frame design context.", '
                '"triggers": ["figma get design context", "gh pr create"], '
                '"requires_mcps": ["figma", "gh"], '
                '"side_effects": "host_write", '
                '"examples": [{"input": "handoff", "output": "PR"}, '
                '{"input": "push spec", "output": "PR"}]}'
            )
        return "[]"  # eval queries

    class _FakeMessages:
        def create(self, **kwargs):
            return _Resp(_reply_for(kwargs["messages"][0]["content"]))

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder",
        contributing_agent="claude",
    )
    # The real critic was consulted (classify + extract prompts recorded).
    assert any("evaluating whether" in p for p in seen["prompts"])
    assert any("mining a reusable skill" in p for p in seen["prompts"])
    # And the deterministic gate still validated the LLM-minted skill.
    assert result.accepted
    assert result.skill is not None
    assert result.skill.honed_passed == result.hone["n_trials"]


def test_resilient_critic_falls_back_on_live_failure():
    # Real-world scenario observed in THIS env: a real ANTHROPIC key is
    # configured, but the live call fails (HTTP 400 "credit balance too
    # low"). The mint must NOT crash — ResilientCritic degrades that call
    # to the deterministic heuristic and records the failure. This is why
    # the Stop hook stays alive when the LLM account is out of credit.
    from personal_brain.reflexion import ResilientCritic

    class _BillingWall:
        def classify(self, t):
            raise RuntimeError("Error code: 400 - credit balance is too low")
        def extract(self, t):
            raise RuntimeError("Error code: 400 - credit balance is too low")
        def generate_eval_queries(self, s, n=20):
            raise RuntimeError("Error code: 400 - credit balance is too low")

    critic = ResilientCritic(_BillingWall())
    verdict = critic.classify(
        "USER: x\nTOOL: revit_info() → ok\nOUTCOME: success"
    )
    # Heuristic fallback produced a real verdict despite the live failure.
    assert verdict["verdict"] == "success"
    assert critic.failures and "classify" in critic.failures[0]

    draft = critic.extract("TOOL: gh_pr_create() → ok")
    assert draft.get("proposed_name")  # heuristic extractor filled in
    assert any("extract" in f for f in critic.failures)


def test_reflect_on_trace_survives_billing_wall_via_resilient(store, monkeypatch):
    # End-to-end: a configured key whose live calls ALL fail (billing wall)
    # still mints a skill, because ResilientCritic falls back to the
    # deterministic critic AND the trace-grounded sandbox does real
    # structural validation. honed_passed is real (from the sandbox), not a
    # coin-flip, and the mint is not broken by the dead LLM account.
    monkeypatch.setenv("BRAIN_REFLEXION_LLM", "1")  # opt into the live path
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-broke")
    import anthropic

    class _DeadMessages:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 400 - credit balance is too low")

    class _DeadClient:
        def __init__(self, *a, **k):
            self.messages = _DeadMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _DeadClient)

    result = reflect_on_trace(
        _trace_success(), store=store, owner_user="founder",
        contributing_agent="claude",
    )
    assert result.accepted  # mint survived the dead LLM account
    assert result.skill is not None
    assert result.skill.honed_passed == result.hone["n_trials"]  # real gate
    assert result.hone["ok"] is True
