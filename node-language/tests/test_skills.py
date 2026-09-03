"""Unit tests for the Skills package.

Covers metadata round-trip, the matcher's keyword scoring, the seeds
factory output, and library save/load with a temporary library root.

Run from the repo root:

    python -m pytest tests/

The tests do not need a live LLM, Revit, or any other external dependency.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `app/` importable as the top-level package (mirrors main.py's path).
APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_library(tmp_path, monkeypatch):
    """Redirect every library root to a temp directory for the test, and
    disable cloud sync so a real GitHub clone in %LOCALAPPDATA% never
    leaks into the test's view of `list_skills`."""
    user_root = tmp_path / "user"
    shared_root = tmp_path / "shared"
    user_root.mkdir()
    shared_root.mkdir()

    # workflows.library imports its WORKFLOWS_DIR at module-load time, so we
    # patch the references the skills package actually uses.
    from workflows import library as wf_library
    from skills import library as sk_library

    monkeypatch.setattr(wf_library, "WORKFLOWS_DIR", user_root)
    monkeypatch.setattr(sk_library, "USER_LIBRARY", user_root)
    monkeypatch.setattr(sk_library, "SHARED_LIBRARY", shared_root)

    # Force cloud sync off for tests — they should run hermetic, never
    # touching the user's real GitHub-backed cache.
    monkeypatch.setattr(sk_library, "_cloud_skills_dir", lambda: None)

    # Also redirect usage telemetry so tests don't write to the user's home.
    from skills import usage as sk_usage
    monkeypatch.setattr(sk_usage, "_PATH", tmp_path / "skill_usage.json")

    yield user_root, shared_root


# ---------------------------------------------------------------------------
class TestMetadata:
    def test_round_trip(self):
        from skills.metadata import SkillMeta

        original = SkillMeta(
            intent="Demo intent",
            keywords=["demo", "test"],
            when_to_use="When testing.",
            examples=[{"prompt": "demo", "expected_outcome": "ok"}],
            tags=["unit-test"],
            requires=["revit"],
            author="pytest",
            scope="user",
        )
        restored = SkillMeta.from_dict(original.to_dict())
        assert restored == original

    def test_attach_and_get(self):
        from workflows.graph import Workflow
        from skills.metadata import SkillMeta, attach_meta, get_meta, is_skill

        wf = Workflow.new(name="Test")
        assert not is_skill(wf)
        attach_meta(wf, SkillMeta(intent="something"))
        assert is_skill(wf)
        meta = get_meta(wf)
        assert meta is not None and meta.intent == "something"


# ---------------------------------------------------------------------------
class TestMatcher:
    def test_keyword_score_weights(self):
        from skills.matcher import _keyword_score, _tokens

        skill = {
            "name": "Dimension walls",
            "intent": "Add dimensions",
            "keywords": ["dimension", "wall"],
            "tags": ["revit"],
        }
        # keyword hits weighted higher than name/intent
        score, matched = _keyword_score(_tokens("dimension wall now"), skill)
        assert score > 0
        assert "dimension" in matched and "wall" in matched

        # Empty prompt → 0
        score, matched = _keyword_score(set(), skill)
        assert score == 0.0 and matched == []

    def test_usage_boost_promotes_reliable_skills(self, tmp_library):
        from workflows.graph import Workflow
        from skills.metadata import SkillMeta
        from skills.library import save_skill
        from skills.matcher import match_skills
        from skills.usage import record_run

        # Two Skills with identical keyword overlap; usage history differs.
        for name in ("reliable", "shaky"):
            wf = Workflow.new(name=name)
            save_skill(wf, SkillMeta(
                intent=f"do something with walls",
                keywords=["wall", "walls"],
            ))

        # Pull ids back so we can record usage against them.
        from skills.library import list_skills as _list
        skills_idx = {s["name"]: s["id"] for s in _list()}

        # "reliable" → 20 runs, 19 successes
        for _ in range(19):
            record_run(skills_idx["reliable"], success=True)
        record_run(skills_idx["reliable"], success=False)

        # "shaky" → 20 runs, 4 successes (very low success rate)
        for _ in range(4):
            record_run(skills_idx["shaky"], success=True)
        for _ in range(16):
            record_run(skills_idx["shaky"], success=False)

        matches = match_skills("walls", min_score=0.0)
        names = [m.name for m in matches]
        assert "reliable" in names and "shaky" in names
        assert names.index("reliable") < names.index("shaky"), (
            f"Reliable Skill should outrank shaky one; got order: {names}"
        )

    def test_match_filters_by_active_connectors(self, tmp_library):
        from workflows.graph import Workflow
        from skills.metadata import SkillMeta
        from skills.library import save_skill
        from skills.matcher import match_skills

        for fac_name in ("revit-skill", "blender-skill"):
            wf = Workflow.new(name=fac_name)
            requires = ["revit"] if "revit" in fac_name else ["blender"]
            save_skill(wf, SkillMeta(
                intent=f"do {fac_name}",
                keywords=["do"],
                requires=requires,
            ))

        # Only revit active → only revit skill considered
        matches = match_skills("do something", min_score=0.0,
                               active_connectors={"revit"})
        names = [m.name for m in matches]
        assert "revit-skill" in names
        assert "blender-skill" not in names


# ---------------------------------------------------------------------------
class TestSeeds:
    def test_seeds_validate(self):
        from skills.seeds import (
            _seed_dimension_walls, _seed_room_tags, _seed_push_to_speckle,
        )
        for factory in (_seed_dimension_walls, _seed_room_tags, _seed_push_to_speckle):
            wf, meta = factory()
            assert wf.validate() == []
            assert meta.intent
            assert meta.keywords
            assert meta.requires

    def test_ensure_starter_skills_idempotent(self, tmp_library):
        from skills.seeds import ensure_starter_skills
        from skills.library import list_skills

        first = ensure_starter_skills()
        assert len(first) == 3

        # Second call should add nothing.
        second = ensure_starter_skills()
        assert second == []
        assert len(list_skills()) == 3

    def test_production_seeds_validate(self):
        from skills.production_seeds import SEED_FACTORIES
        # Walk every registered factory — adding a new seed automatically
        # extends the validation surface, no need to edit this test.
        for factory in SEED_FACTORIES:
            wf, meta = factory()
            assert wf.validate() == [], f"{factory.__name__}: {wf.validate()}"
            assert meta.intent, f"{factory.__name__}: missing intent"
            assert meta.keywords, f"{factory.__name__}: missing keywords"
            assert meta.tags, f"{factory.__name__}: missing tags"

    def test_sketch_to_production_chains_six_stages(self):
        from skills.production_seeds import _seed_sketch_to_production
        wf, meta = _seed_sketch_to_production()
        # 1 input + 6 (template, llm) pairs + 1 output = 14 nodes
        assert len(wf.nodes) == 14
        # 1 input→tmpl + 6 tmpl→llm + 5 llm→tmpl + 1 llm→output = 13 edges
        assert len(wf.edges) == 13
        # Six stages = six llm nodes
        llm_nodes = [n for n in wf.nodes if n.type == "llm.complete_with_tools"]
        assert len(llm_nodes) == 6

    def test_ensure_production_skills_idempotent(self, tmp_library):
        from skills.production_seeds import ensure_production_skills, SEED_FACTORIES
        from skills.library import list_skills

        expected = len(SEED_FACTORIES)
        first = ensure_production_skills()
        assert len(first) == expected
        second = ensure_production_skills()
        assert second == []
        assert len(list_skills()) == expected


# ---------------------------------------------------------------------------
class TestShare:
    def test_export_then_import_round_trips(self, tmp_library):
        from skills.seeds import _seed_dimension_walls
        from skills.library import save_skill, list_skills
        from skills.share import (
            export_skill_to_string, import_skill_from_string,
            looks_like_skill_json,
        )

        wf, meta = _seed_dimension_walls()
        save_skill(wf, meta)

        text = export_skill_to_string(wf.id)
        assert looks_like_skill_json(text)
        assert "Dimension walls" in text

        # Import gives a fresh id by default so it doesn't clobber the source.
        imported = import_skill_from_string(text)
        assert imported.id != wf.id
        assert imported.name == wf.name
        assert len(list_skills()) == 2

    def test_import_rejects_non_skill_workflow(self, tmp_library):
        from workflows.graph import Workflow
        from skills.share import import_skill_from_string, SkillImportError

        plain = Workflow.new(name="Plain workflow")
        # No metadata.skill — not a Skill.
        with pytest.raises(SkillImportError):
            import_skill_from_string(plain.to_json())

    def test_import_rejects_garbage(self, tmp_library):
        from skills.share import import_skill_from_string, SkillImportError

        with pytest.raises(SkillImportError):
            import_skill_from_string("")
        with pytest.raises(SkillImportError):
            import_skill_from_string("not json at all")
        with pytest.raises(SkillImportError):
            import_skill_from_string('{"not": "a workflow"}')

    def test_looks_like_skill_json_sniff(self):
        from skills.share import looks_like_skill_json
        from skills.seeds import _seed_room_tags
        from skills.metadata import attach_meta

        wf, meta = _seed_room_tags()
        attach_meta(wf, meta)
        assert looks_like_skill_json(wf.to_json())
        assert not looks_like_skill_json("hello world")
        assert not looks_like_skill_json("{}")


# ---------------------------------------------------------------------------
class TestUsage:
    def test_record_run_accumulates(self, tmp_library):
        from skills.usage import record_run, get_usage

        record_run("demo", success=True, elapsed_ms=100)
        record_run("demo", success=True, elapsed_ms=200)
        record_run("demo", success=False, elapsed_ms=50, error="boom")

        u = get_usage("demo")
        assert u["runs"] == 3
        assert u["successes"] == 2
        assert u["failures"] == 1
        assert u["last_error"] == "boom"
        assert u["total_elapsed_ms"] == 350
