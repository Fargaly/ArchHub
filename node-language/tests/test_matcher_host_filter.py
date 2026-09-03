"""Skill matcher host-context filter test.

Live regression: user said 'categorize all my emails by project'.
Matcher fired a Revit 'Construction doc sprint pack' skill because
both shared weak token 'all'. Wrong host. Now the matcher drops
skills whose `requires` targets only an UNRELATED host family
when the user prompt clearly mentions another family.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestPromptHostSignal:
    def test_outlook_words_detected(self):
        from skills.matcher import _prompt_host_signal
        for q in (
            "categorise all my emails by project",
            "forward newsletters to bob",
            "read the latest mail",
            "list my inbox",
        ):
            hosts = _prompt_host_signal(q)
            assert "outlook" in hosts, q

    def test_revit_words_detected(self):
        from skills.matcher import _prompt_host_signal
        hosts = _prompt_host_signal("add walls to level 2")
        assert "revit" in hosts

    def test_host_neutral_returns_empty(self):
        from skills.matcher import _prompt_host_signal
        for q in ("hello", "thanks", "what time is it"):
            hosts = _prompt_host_signal(q)
            assert hosts == set(), q


class TestMatcherDropsCrossHostSkills:
    @pytest.fixture
    def fake_skills(self):
        return [
            {
                "id": "construction-sprint",
                "name": "Construction doc sprint pack",
                "intent": "Revit production sheets + schedules",
                "keywords": ["all", "production", "sheets"],
                "tags": ["revit"],
                "requires": ["revit"],
                "examples": [],
            },
            {
                "id": "outlook-categorise",
                "name": "Sort inbox by project",
                "intent": "Categorise emails into project tags",
                "keywords": ["categorize", "categorise", "emails"],
                "tags": ["outlook"],
                "requires": ["outlook"],
                "examples": [],
            },
            {
                "id": "host-neutral",
                "name": "Daily summary",
                "intent": "Summarise the day across all hosts",
                "keywords": ["summary", "daily"],
                "tags": [],
                "requires": [],
                "examples": [],
            },
        ]

    def test_outlook_query_skips_revit_only_skill(self, fake_skills):
        from skills import matcher
        with patch.object(matcher, "list_skills",
                           return_value=fake_skills):
            results = matcher.match_skills(
                "categorise all my emails by project",
                active_connectors={"revit", "outlook"},
            )
        ids = [r.skill_id for r in results]
        assert "construction-sprint" not in ids
        assert "outlook-categorise" in ids

    def test_revit_query_skips_outlook_only_skill(self, fake_skills):
        from skills import matcher
        with patch.object(matcher, "list_skills",
                           return_value=fake_skills):
            results = matcher.match_skills(
                "add walls to level 2",
                active_connectors={"revit", "outlook"},
            )
        ids = [r.skill_id for r in results]
        assert "outlook-categorise" not in ids

    def test_host_neutral_skill_always_visible(self, fake_skills):
        # A skill with no `requires` must match regardless of host
        # context.
        from skills import matcher
        with patch.object(matcher, "list_skills",
                           return_value=fake_skills):
            results = matcher.match_skills(
                "daily summary",
                active_connectors={"revit", "outlook"},
            )
        ids = [r.skill_id for r in results]
        assert "host-neutral" in ids

    def test_no_host_keyword_falls_through_normally(self, fake_skills):
        # If the prompt mentions NO host family, the filter doesn't
        # apply and normal keyword scoring decides.
        from skills import matcher
        with patch.object(matcher, "list_skills",
                           return_value=fake_skills):
            results = matcher.match_skills(
                "daily summary",
                active_connectors={"revit", "outlook"},
            )
        # Should at least include the host-neutral skill.
        assert any(r.skill_id == "host-neutral" for r in results)
