"""Tests for `personal_brain.reflexion.extract_tutorial_draft`.

Sister tests to `test_reflexion.py::test_extract_skill_draft_*`. Per
content-ecosystem 2026-05-26 §3: every successful trace produces a
tutorial draft alongside the skill draft, and the tutorial inherits the
skill's scope.
"""
from __future__ import annotations

import pytest

from personal_brain.reflexion import (
    HeuristicCritic,
    extract_skill_draft,
    extract_tutorial_draft,
)


def _trace_revit_success() -> dict:
    return {
        "user_message": "Annotate this view in Revit.",
        "trace_id": "tr-revit-1",
        "session_id": "sess-revit-1",
        "tool_calls": [
            {
                "name": "revit_info",
                "args": {},
                "status": "ok",
            },
            {
                "name": "revit_annotate_view",
                "args": {"view_id": "abc"},
                "status": "ok",
            },
        ],
        "outcome": "success",
    }


def test_empty_trace_returns_none():
    """Per the extractor contract: a trace with no tool_calls returns
    None — there's nothing to teach, and a None signal lets the
    orchestrator skip the publish step."""
    assert extract_tutorial_draft({}) is None
    assert extract_tutorial_draft({"tool_calls": []}) is None
    # Even a populated trace WITHOUT tool_calls is treated as empty.
    assert extract_tutorial_draft({
        "user_message": "do a thing",
        "outcome": "success",
    }) is None


def test_valid_trace_returns_draft_with_all_fields():
    """A populated trace returns a dict matching the template
    frontmatter contract: slug, title, prerequisites, steps, outcome,
    scope, replay_skill_id."""
    trace = _trace_revit_success()
    draft = extract_tutorial_draft(trace)

    assert draft is not None
    # Required keys per the docs/_templates/tutorial.md frontmatter.
    for key in (
        "slug", "title", "prerequisites", "steps",
        "outcome", "scope", "replay_skill_id",
    ):
        assert key in draft, f"missing key: {key}"

    # Slug is lowercase, kebab-case.
    assert draft["slug"]
    assert draft["slug"] == draft["slug"].lower()
    assert " " not in draft["slug"]

    # Title is plain English — at least one capital letter, no underscores
    # (the slug uses dashes, the title uses spaces).
    assert draft["title"]
    assert "_" not in draft["title"]

    # Prerequisites is a non-empty list of strings.
    assert isinstance(draft["prerequisites"], list)
    assert draft["prerequisites"]
    assert all(isinstance(p, str) for p in draft["prerequisites"])

    # Steps mirror the tool_calls 1:1, each with n/tool/intent/observation.
    assert isinstance(draft["steps"], list)
    assert len(draft["steps"]) == len(trace["tool_calls"])
    for i, step in enumerate(draft["steps"], start=1):
        assert step["n"] == i
        assert step["tool"] == trace["tool_calls"][i - 1]["name"]
        assert isinstance(step["intent"], str) and step["intent"]
        assert isinstance(step["observation"], str) and step["observation"]

    # Outcome is a single string.
    assert isinstance(draft["outcome"], str) and draft["outcome"]

    # Scope defaults to "user" when neither the skill nor the trace
    # specifies otherwise.
    assert draft["scope"] == "user"


def test_scope_inheritance_from_skill():
    """Per Content-Ecosystem §3: tutorials carry the same scope as the
    skill they mirror. When the skill draft is firm-scoped, the tutorial
    draft inherits firm scope."""
    trace = _trace_revit_success()
    # Pre-compute a firm-scoped skill draft + pass it in so the tutorial
    # extractor sees the scope hint without re-running the critic.
    base_skill = extract_skill_draft(trace)
    base_skill["scope"] = "firm"
    base_skill["skill_id"] = "sk-revit-annotate-firm"

    draft = extract_tutorial_draft(trace, skill_draft=base_skill)
    assert draft is not None
    assert draft["scope"] == "firm"
    # replay_skill_id propagates so the rendered tutorial's Replay button
    # can target the right skill.
    assert draft["replay_skill_id"] == "sk-revit-annotate-firm"

    # Also verify inheritance through the trace itself (the worker may
    # not pre-extract the skill in all code paths).
    trace_with_scope = dict(trace)
    trace_with_scope["scope"] = "community"
    trace_with_scope["replay_skill_id"] = "sk-public"
    draft2 = extract_tutorial_draft(trace_with_scope)
    assert draft2 is not None
    # The skill draft (auto-extracted) has no scope, so the trace's
    # scope wins.
    assert draft2["scope"] == "community"
    assert draft2["replay_skill_id"] == "sk-public"
