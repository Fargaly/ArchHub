"""Skill JSON split-view (StudioSkillJson) — consolidation gate.

CONSOLIDATION 2026-06-18 (lane SKILL-JSON). The design carried a "Skill
JSON" split-view (studio-suite.jsx → `StudioSkillJson` + the Studio
artboards in "ArchHub Redesign.html") that the APP had NO equivalent of
(grep `skill_json` / `split-view` in the app = 0). This ports it in,
honoring the LOCKED principle "skills are plain JSON files you own"
(PROTOTYPE-IS-CONTRACT — the left WHAT IT DOES / STAGES / EXPOSED
PARAMETERS / YOU OWN THIS panes + the right syntax-coloured skill.json
with line numbers + Copy JSON / Fork / Open-in-chat mirror the signed
prototype, rendered in the app's dark LM chrome).

This gate proves four things the task requires, and is a real RED->GREEN
check — `git stash` the studio-lm.jsx edit and PART 2/3/4 go RED because
the component, its wiring, and the compiled-bundle parity all vanish:

  1. The SkillJson view RENDERS A REAL SKILL — its name, derived STAGES,
     and EXPOSED PARAMETERS — and the data it consumes is REAL: it sources
     through the SAME async slot the panel's spawn path uses (`load_skill`
     → `_scan_canvas_skills`, the single store resolver), exercised here
     against the live ArchHubBridge with a real on-disk skill so the
     stage/param derivation runs on actual content, never the prototype's
     hard-coded sample.
  2. The JSON pane exists — line-numbered + syntax-coloured via the
     design's `colorJson` helper, fed by the REAL record (JSON.stringify
     of the actual envelope), not a canned string.
  3. The Copy JSON / Fork / Open-in-chat actions exist AND are wired to
     real receivers (clipboard, lm-spawn-skill, lm-composer-seed — the
     last has a live listener in the Composer, so it is not a dead event).
  4. It is REACHABLE from a visible affordance (the SkillsPanel row's
     "{ }" button) and MOUNTED at the StudioLM root — and the wiring is
     present in the COMPILED bundle the app actually boots.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
_COMPILED = (APP_ROOT / "web_ui" / "studio-lm.compiled.js").read_text(
    encoding="utf-8")
# Comment-stripped view so an assertion can't be satisfied by a comment, and
# whitespace-flat views so spacing / line-wrap differences never break a match
# (the compiled bundle strips inter-token spaces).
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)
_COMPILED_FLAT = re.sub(r"\s+", " ", _COMPILED)


def _jsx_window(anchor: str, size: int = 4200) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


# ════════════════════════════════════════════════════════════════════
# PART 1 — the data the view renders is REAL (live ArchHubBridge)
# ════════════════════════════════════════════════════════════════════
# load_skill is a plain synchronous Python method returning a JSON string;
# QWebChannel only makes the *transport* async. Call it directly on an
# instance built via __new__ (no event loop), mirroring the proven pattern
# in test_skills_search_panels_wiring.py.


@pytest.fixture
def isolated_skill_dirs(monkeypatch, tmp_path):
    """Point the canvas-skill store at tmp dirs and drop ONE real skill
    envelope in, so load_skill round-trips actual content the SkillJson
    view derives STAGES + EXPOSED PARAMETERS from."""
    import bridge
    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    user_dir.mkdir()
    shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    monkeypatch.setattr(bridge, "_load_skill_tombstones", lambda: set())
    # A REAL canvas-skill: a 3-stage graph carrying BOTH param shapes the
    # view derives EXPOSED PARAMETERS from — grammar params:[{k,v}] AND a
    # connector config:{key:value} object.
    envelope = {
        "kind": "archhub.skill",
        "name": "Sketch to production",
        "slug": "sketch_to_production",
        "graph": {
            "nodes": [
                {"id": "s1", "kind": "vision", "cat": "ai",
                 "title": "sketch parse",
                 "params": [{"k": "source", "v": "sketch.png"}]},
                {"id": "s2", "kind": "rhino.mass", "cat": "transform",
                 "title": "mass extract",
                 "params": [{"k": "mass_height", "v": 32},
                            {"k": "levels", "v": 9}]},
                {"id": "s3", "kind": "connector", "cat": "connector",
                 "host": "revit", "title": "wall build",
                 "config": {"host": "revit", "op": "create_walls",
                            "thickness": 200}},
            ],
            "wires": [{"from": ["s1", "out"], "to": ["s2", "in"]},
                      {"from": ["s2", "out"], "to": ["s3", "in"]}],
        },
        "meta": {"mode": "private",
                 "description": "Hand sketch to a production drawing set.",
                 "category": "aec"},
    }
    (user_dir / "sketch_to_production.archhub-skill.json").write_text(
        json.dumps(envelope), encoding="utf-8")
    return bridge


def test_load_skill_feeds_the_view_real_stages_and_params(isolated_skill_dirs):
    """The exact slot the SkillJson view calls on open returns the real
    record, and the STAGES + EXPOSED PARAMETERS the view derives from it
    are real (not the prototype's hard-coded sample)."""
    bridge = isolated_skill_dirs
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    blob = json.loads(inst.load_skill("sketch_to_production"))
    assert "error" not in blob, blob
    # The view's title + description come straight from the real record.
    assert blob["name"] == "Sketch to production"
    assert blob["meta"]["description"] == "Hand sketch to a production drawing set."
    # STAGES = the real graph nodes (one per node, in order).
    nodes = blob["nodes"]
    assert [n["kind"] for n in nodes] == ["vision", "rhino.mass", "connector"]
    # EXPOSED PARAMETERS = union of params[].k AND config{} keys — the two
    # shapes the JS `_skillNodeParams` helper merges. Prove both are present
    # in the real data the view reads.
    exposed = []
    for n in nodes:
        for p in (n.get("params") or []):
            exposed.append(p["k"])
        for k in (n.get("config") or {}):
            exposed.append(k)
    assert "mass_height" in exposed and "levels" in exposed  # grammar params
    assert "op" in exposed and "thickness" in exposed         # connector config


def test_view_source_is_not_the_prototype_sample(isolated_skill_dirs):
    """MAKE-IT-REAL / ANTI-LIE: the app's SkillJson must NOT ship the
    prototype's hard-coded sample skill — it reads the real record. The
    design embedded a literal `const json = "{...Sketch to production...}"`
    with `"type": "slider"` params; that canned blob must be absent."""
    # The prototype's tell-tale hard-coded slider-param sample.
    assert '"type": "slider"' not in _JSX_SRC, (
        "the app must source skill.json from the real record, not the "
        "prototype's hard-coded sample")
    # And the view must build its JSON from the real record via stringify.
    block = _jsx_window("const StudioSkillJsonInner", size=14000)
    assert "JSON.stringify(envelope" in block, (
        "skill.json text must be the REAL record serialised, not a literal")
    assert "bridgeAsync('load_skill'" in block, (
        "the view must resolve the skill through the real load_skill slot")


# ════════════════════════════════════════════════════════════════════
# PART 2 — the component renders the prototype's panes (source guards)
# ════════════════════════════════════════════════════════════════════


class TestSkillJsonComponent:
    def test_component_exists(self):
        assert "const StudioSkillJsonInner" in _JSX_CODE, (
            "the Skill JSON split-view component must exist (it was the one "
            "design surface the app had no equivalent of)")
        assert "const StudioSkillJson = React.memo(StudioSkillJsonInner)" \
            in _JSX_CODE

    def test_opens_on_real_event_with_skill_id(self):
        block = _jsx_window("const StudioSkillJsonInner", size=2400)
        assert "lm-skill-json-open" in block, (
            "the view must open on the lm-skill-json-open event")
        flat = re.sub(r"\s+", " ", block)
        assert "d.id || d.slug || d.name" in flat, (
            "the open handler must accept a skill id/slug/name from the event")

    def test_left_pane_has_all_four_prototype_sections(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        for label in ("WHAT IT DOES", "STAGES", "EXPOSED PARAMETERS",
                      "YOU OWN THIS"):
            assert label in block, (
                f"left pane must carry the prototype's '{label}' section")
        # The locked principle copy must be present verbatim-ish.
        assert "plain JSON files you own" in block, (
            "the YOU OWN THIS note must state the locked principle")

    def test_stages_and_params_are_derived_from_the_graph(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        # Stages come from nodes via the derivation helper; params via the
        # merge helper — proving they are not hard-coded lists.
        assert "_skillStageLabel" in block and "_skillNodeParams" in block
        assert 'data-testid="skill-json-stages"' in block
        assert 'data-testid="skill-json-params"' in block

    def test_derivation_helpers_exist(self):
        assert "const _skillStageLabel" in _JSX_CODE
        assert "const _skillNodeParams" in _JSX_CODE
        # _skillNodeParams must merge BOTH param shapes (params[].k + config).
        helper = _jsx_window("const _skillNodeParams", size=600)
        flat = re.sub(r"\s+", " ", helper)
        assert "n.params" in flat and "n.config" in flat, (
            "exposed-param derivation must read both params[] and config{}")

    def test_right_pane_is_line_numbered_colorjson(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        assert 'data-testid="skill-json-source"' in block
        assert "colorJson(line)" in block, (
            "the JSON pane must syntax-colour each line via colorJson")
        # Line numbers: i + 1 rendered per line.
        assert "jsonLines.map" in block and "{i + 1}" in block, (
            "the JSON pane must render line numbers")

    def test_colorjson_helper_reused_from_design(self):
        assert "const colorJson = (line)" in _JSX_CODE, (
            "the design's colorJson helper must be reused")


class TestSkillJsonActions:
    def test_copy_fork_open_actions_exist(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        for tid in ("skill-json-copy", "skill-json-fork",
                    "skill-json-open-chat"):
            assert f'data-testid="{tid}"' in block, (
                f"the {tid} action button must exist (prototype actions)")

    def test_actions_are_wired_to_real_receivers(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        # Copy → clipboard; Fork → real spawn path; Open → composer seed.
        assert "clipboard" in block and "writeText" in block, (
            "Copy JSON must write to the clipboard")
        assert "lm-spawn-skill" in block, (
            "Fork must route through the real spawn path (lm-spawn-skill)")
        assert "lm-composer-seed" in block, (
            "Open in chat must seed the composer (lm-composer-seed)")

    def test_open_in_chat_has_a_live_composer_receiver(self):
        # The lm-composer-seed event is only real if the Composer listens.
        assert "addEventListener('lm-composer-seed'" in _JSX_CODE, (
            "the Composer must subscribe to lm-composer-seed so Open-in-chat "
            "is not a dead dispatch (MAKE-IT-REAL / NO-OPEN-THREADS)")

    def test_honest_empty_and_error_states(self):
        block = _jsx_window("const StudioSkillJsonInner", size=14000)
        # No fabricated rows when the store has no such skill / bridge down.
        assert 'data-testid="skill-json-error"' in block, (
            "the view must show an honest error state, never invented data")


# ════════════════════════════════════════════════════════════════════
# PART 3 — reachable from a visible affordance + mounted at root
# ════════════════════════════════════════════════════════════════════


class TestSkillJsonReachable:
    def test_skills_panel_row_opens_the_view(self):
        block = _jsx_window("const SkillsPanel = (", size=5200)
        assert 'data-testid="skill-row-view-json"' in block, (
            "each SkillsPanel row must expose a '{ }' view-JSON affordance")
        assert "lm-skill-json-open" in block, (
            "the row affordance must dispatch lm-skill-json-open")
        # It must stop propagation so it opens JSON instead of spawning.
        flat = re.sub(r"\s+", " ", block)
        assert "e.stopPropagation(); viewJson(s)" in flat

    def test_modal_mounted_at_root(self):
        # Mounted alongside the other always-mounted modals.
        assert "<StudioSkillJson _themeBump={paletteBump}/>" in _JSX_CODE, (
            "StudioSkillJson must be mounted at the StudioLM root")


# ════════════════════════════════════════════════════════════════════
# PART 4 — the COMPILED bundle the app loads carries the wiring
# ════════════════════════════════════════════════════════════════════


class TestCompiledBundleParity:
    def test_component_present_in_bundle(self):
        assert "StudioSkillJson=React.memo(" in _COMPILED_FLAT or \
               "StudioSkillJsonInner" in _COMPILED_FLAT, (
            "StudioSkillJson must be in the compiled bundle the app boots")

    def test_open_event_and_real_slot_in_bundle(self):
        assert "lm-skill-json-open" in _COMPILED, (
            "the open event must be in the compiled bundle")
        assert "bridgeAsync('load_skill'" in _COMPILED_FLAT, (
            "the real load_skill wiring must be in the compiled bundle")

    def test_panes_and_actions_in_bundle(self):
        for needle in ("YOU OWN THIS", "skill-json-source",
                       "skill-json-copy", "skill-json-fork",
                       "skill-json-open-chat", "skill-row-view-json"):
            assert needle in _COMPILED, (
                f"{needle!r} must be in the compiled bundle")

    def test_composer_seed_receiver_in_bundle(self):
        assert "lm-composer-seed" in _COMPILED, (
            "the composer-seed receiver + dispatch must be in the bundle")
