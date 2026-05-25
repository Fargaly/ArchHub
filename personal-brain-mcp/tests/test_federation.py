"""Slice 8 — community federation tests."""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from personal_brain.federation import (
    ActivityRecord,
    ContributorReputation,
    FederationDriver,
    ImportDecision,
    Outbox,
    Pattern,
    add_dp_noise,
    derive_skill_usage_patterns,
    derive_tool_sequence_patterns,
    evaluate_incoming_pattern,
    noise_pattern_statistics,
    pattern_to_activity,
)
from personal_brain.models import Provenance, Skill


def _skill(name, success=10, fail=1, body="UNIQUE_BODY_TOKEN_FOR_LEAK_DETECTION", mcps=("foo-mcp",), triggers=("trigger",)):
    return Skill(
        id=f"sk-{name}", name=name,
        description="A perfectly fine description well over eighty characters that explains what the skill does without filler.",
        triggers=list(triggers),
        requires_mcps=list(mcps),
        body=body,
        examples=[{"input": "x", "output": "y"}],
        owner_user="founder",
        provenance=Provenance(
            contributing_agent="claude", contributing_user="founder",
            created_at=datetime.now(timezone.utc),
        ),
        success_count=success, fail_count=fail,
        honed_trials=3, honed_passed=2,
    )


# ─────────────────────── compendium derivation ─────────────────────────


def test_derive_skill_usage_patterns_filters_by_min_success():
    skills = [_skill("alpha", success=10), _skill("beta", success=1)]
    patterns = derive_skill_usage_patterns(skills, firm_id="archhub-inc",
                                            min_success_count=3)
    names = {p.statistics["name_prefix"] for p in patterns}
    assert "alpha" in names
    assert "beta" not in names


def test_derived_pattern_carries_no_raw_skill_body():
    """Verify pattern statistics never contain skill.body text."""
    sk = _skill("alpha", success=5, body="SECRET_INSIDE")
    patterns = derive_skill_usage_patterns([sk], firm_id="x", min_success_count=3)
    assert patterns
    stats_str = str(patterns[0].statistics)
    assert "SECRET_INSIDE" not in stats_str


def test_derive_tool_sequence_patterns():
    traces = [
        {"tool_calls": [
            {"name": "revit_info", "status": "ok"},
            {"name": "revit_execute_csharp", "status": "ok"},
        ]},
        {"tool_calls": [
            {"name": "revit_info", "status": "ok"},
            {"name": "revit_execute_csharp", "status": "ok"},
        ]},
        {"tool_calls": [
            {"name": "revit_info", "status": "ok"},
            {"name": "revit_execute_csharp", "status": "ok"},
        ]},
    ]
    patterns = derive_tool_sequence_patterns(
        traces, firm_id="x", min_occurrences=3,
    )
    assert patterns
    p = patterns[0]
    assert p.statistics["a"] == "revit_info"
    assert p.statistics["b"] == "revit_execute_csharp"
    assert p.statistics["count"] == 3


def test_pattern_id_is_content_addressed():
    skills = [_skill("alpha", success=10)]
    p1 = derive_skill_usage_patterns(skills, firm_id="x", min_success_count=3)[0]
    p2 = derive_skill_usage_patterns(skills, firm_id="x", min_success_count=3)[0]
    assert p1.pattern_id == p2.pattern_id


# ─────────────────────── DP noise ──────────────────────────────────────


def test_add_dp_noise_zero_epsilon_raises():
    with pytest.raises(ValueError):
        add_dp_noise(1.0, epsilon=0.0)


def test_add_dp_noise_changes_value():
    random.seed(1)
    noised = add_dp_noise(100.0, sensitivity=1.0, epsilon=1.0)
    # With ε=1, expect non-negligible noise
    assert noised != 100.0


def test_noise_pattern_statistics_preserves_keys():
    p = Pattern(
        pattern_id="x", kind="skill_usage", summary="x",
        statistics={"success_count": 10, "success_rate": 0.9,
                     "name_prefix": "alpha"},
        contributor_firm="x",
    )
    noised = noise_pattern_statistics(p, epsilon=1.0, seed=42)
    # Same set of keys
    assert set(noised.statistics.keys()) == set(p.statistics.keys())
    # Non-numeric keys unchanged
    assert noised.statistics["name_prefix"] == "alpha"
    # numeric keys probably changed
    assert noised.pattern_id != p.pattern_id


def test_noise_with_gaussian_mechanism():
    random.seed(7)
    noised = add_dp_noise(50.0, sensitivity=1.0, epsilon=0.5,
                           mechanism="gaussian")
    assert noised != 50.0


# ─────────────────────── ActivityPub shapes ────────────────────────────


def test_pattern_to_activity_returns_jsonld_compatible_shape():
    p = Pattern(pattern_id="abc", kind="skill_usage", summary="x",
                 contributor_firm="archhub")
    act = pattern_to_activity(
        p, actor_url="https://archhub.brain/actor",
        base_url="https://archhub.brain",
    )
    assert act.id.endswith("/patterns/abc")
    assert act.actor == "https://archhub.brain/actor"
    jsonld = act.to_jsonld()
    assert jsonld["@context"] == "https://www.w3.org/ns/activitystreams"
    assert jsonld["type"] == "Create"


def test_outbox_collects_activities():
    outbox = Outbox(actor_url="https://x/actor", base_url="https://x")
    outbox.publish(Pattern(pattern_id="a", kind="skill_usage", summary="A"))
    outbox.publish(Pattern(pattern_id="b", kind="tool_sequence", summary="B"))
    assert len(outbox.activities) == 2
    jsonld = outbox.to_jsonld()
    assert jsonld["totalItems"] == 2
    assert len(jsonld["orderedItems"]) == 2


# ─────────────────────── reputation gating ─────────────────────────────


def test_high_reputation_auto_accepts():
    rep = ContributorReputation(
        contributor_id="x", accepted_count=50, rejected_count=2,
        avg_quality_score=0.9,
    )
    pat = Pattern(pattern_id="p", kind="skill_usage", summary="x")
    decision = evaluate_incoming_pattern(pat, contributor_rep=rep)
    assert decision.accept
    assert not decision.quarantine


def test_medium_reputation_quarantines():
    rep = ContributorReputation(
        contributor_id="x", accepted_count=5, rejected_count=5,
        avg_quality_score=0.5,
    )
    pat = Pattern(pattern_id="p", kind="skill_usage", summary="x")
    decision = evaluate_incoming_pattern(pat, contributor_rep=rep)
    assert not decision.accept
    assert decision.quarantine


def test_low_reputation_rejects():
    rep = ContributorReputation(
        contributor_id="x", accepted_count=1, rejected_count=50,
        avg_quality_score=0.1,
    )
    pat = Pattern(pattern_id="p", kind="skill_usage", summary="x")
    decision = evaluate_incoming_pattern(pat, contributor_rep=rep)
    assert not decision.accept
    assert not decision.quarantine
    assert "rejected" in decision.reason


def test_reputation_score_in_zero_to_one():
    rep = ContributorReputation(contributor_id="x", accepted_count=100,
                                  rejected_count=0, avg_quality_score=1.0)
    assert 0.0 <= rep.score <= 1.0
    rep2 = ContributorReputation(contributor_id="x", accepted_count=0,
                                   rejected_count=0)
    assert 0.0 <= rep2.score <= 1.0


# ─────────────────────── federation driver ─────────────────────────────


def test_federation_driver_end_to_end():
    driver = FederationDriver(
        firm_id="archhub-inc",
        actor_url="https://brain.archhub.io/actor",
        base_url="https://brain.archhub.io",
        epsilon=1.0,
    )
    skills = [
        _skill("alpha", success=10, fail=1, mcps=["revit-mcp"]),
        _skill("beta", success=7, fail=0, mcps=["notion-mcp"]),
        _skill("low", success=1),  # filtered out
    ]
    traces = [
        {"tool_calls": [{"name": "a", "status": "ok"},
                         {"name": "b", "status": "ok"}]},
        {"tool_calls": [{"name": "a", "status": "ok"},
                         {"name": "b", "status": "ok"}]},
        {"tool_calls": [{"name": "a", "status": "ok"},
                         {"name": "b", "status": "ok"}]},
    ]
    outbox = driver.derive_and_publish(skills, traces=traces)
    assert outbox.activities, "outbox should contain activities"
    # No raw skill body leaks into any activity
    jsonld = outbox.to_jsonld()
    flat = str(jsonld)
    for sk in skills:
        assert sk.body not in flat
        for ex in sk.examples:
            assert str(ex) not in flat


def test_driver_receive_incoming():
    driver = FederationDriver(
        firm_id="archhub-inc",
        actor_url="https://brain.archhub.io/actor",
        base_url="https://brain.archhub.io",
    )
    incoming = {
        "object": {
            "pattern_id": "remote-p",
            "kind": "skill_usage",
            "summary": "skill 'foo' used 30× (90% success)",
            "statistics": {"success_count": 30, "success_rate": 0.9},
            "contributor_firm_hash": "abcd1234",
        }
    }
    high_rep = ContributorReputation(
        contributor_id="abcd1234", accepted_count=20, rejected_count=1,
    )
    d = driver.receive(incoming, reputation=high_rep)
    assert d.accept

    low_rep = ContributorReputation(
        contributor_id="abcd1234", accepted_count=1, rejected_count=50,
    )
    d2 = driver.receive(incoming, reputation=low_rep)
    assert not d2.accept
