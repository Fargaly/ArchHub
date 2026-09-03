"""Grammar synthesis — Tier 1 host_typed + Tier 2 typed primitives +
shipped Skills must appear in `grammar_payload()` AND resolve via
`engine_type()` so the canvas can place + cook them.

AgDR-0041 (2026-05-24) — without this, the previous loop's whole
ship-list (4 typed host nodes + 7 Tier 2 primitives + 3 shipped Skills)
landed in the registry/library but was invisible in the palette.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows  # noqa: F401  triggers nodes + skills auto-import
from workflows import node_grammar as ng  # noqa: E402


# ── Tier 1 host_typed primitives (AgDR-0041 P1) ─────────────────────


@pytest.mark.parametrize("kind", [
    "host.import_mesh",
    "host.read_walls",
    "host.export_viewport",
    "host.run_script",
])
def test_tier1_host_typed_in_payload(kind):
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    assert kind in by_kind, f"{kind} missing from grammar payload"
    assert by_kind[kind]["cat"] == "connector"
    assert by_kind[kind]["status"] == ng.READY


@pytest.mark.parametrize("kind", [
    "host.import_mesh",
    "host.read_walls",
    "host.export_viewport",
    "host.run_script",
])
def test_tier1_host_typed_engine_type_identity(kind):
    """A placed typed-host node must resolve back to its own type so
    the runner has an executor."""
    assert ng.engine_type(kind) == kind


# ── Tier 2 typed primitives (render / vision / mesh / anim / llm) ───


@pytest.mark.parametrize("kind", [
    "render.comfyui",
    "render.image_edit",
    "render.task_poll",
    "vision.describe",
    "mesh.from_image",
    "anim.wan_i2v",
    "llm.qwen",
])
def test_tier2_typed_primitives_in_payload(kind):
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    assert kind in by_kind, f"{kind} missing from grammar payload"
    assert by_kind[kind]["cat"] == "ai"


@pytest.mark.parametrize("kind", [
    "render.comfyui",
    "render.image_edit",
    "render.task_poll",
    "vision.describe",
    "mesh.from_image",
    "anim.wan_i2v",
    "llm.qwen",
])
def test_tier2_typed_engine_type_identity(kind):
    assert ng.engine_type(kind) == kind


# ── Shipped Skills (3 composite Capability Nodes) ───────────────────


@pytest.mark.parametrize("kind", [
    "skill.revit_hero_render",
    "skill.photo_to_rhino_mass",
    "skill.drone_to_revit_walls",
])
def test_skills_in_payload(kind):
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    assert kind in by_kind, f"{kind} missing from grammar payload"
    assert by_kind[kind]["cat"] == "skill"
    assert by_kind[kind]["status"] == ng.READY


@pytest.mark.parametrize("kind", [
    "skill.revit_hero_render",
    "skill.photo_to_rhino_mass",
    "skill.drone_to_revit_walls",
])
def test_skill_engine_type_identity(kind):
    assert ng.engine_type(kind) == kind


# ── No regression: existing Primitives still resolve ────────────────


def test_existing_primitives_still_present():
    """Hardcoded PRIMITIVES (number / text / connector / ai / output …)
    must still appear — synthesis is additive, not replacement."""
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    for k in ("number", "text", "connector", "result", "filter"):
        assert k in by_kind, f"hardcoded primitive {k} disappeared"


def test_unknown_kind_still_returns_none():
    """The identity fallback only fires for REGISTERED types — random
    strings stay None so the runner can surface 'no executor'."""
    assert ng.engine_type("definitely.not.a.type") is None


# ── Synthesized entries carry sane palette metadata ─────────────────


def test_synthesized_blurbs_are_short_and_clean():
    """Synthesized entries hit the same palette-UX bar as PRIMITIVES:
    blurb ≤ 48 chars + no dev jargon."""
    for e in ng.grammar_payload():
        if not e.get("_source"):
            continue
        assert e["blurb"], f"{e['kind']} has no blurb"
        assert len(e["blurb"]) <= 48, (e["kind"], e["blurb"])
        low = e["blurb"].lower()
        for jargon in ("executor", "run_op", "subgraph", "slice",
                       "registry"):
            assert jargon not in low, (e["kind"], e["blurb"])


def test_synthesized_entries_have_engine_ports():
    """Tier 1 + Tier 2 entries source ports from the registry — so
    the canvas can draw + wire them without inventing port names."""
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    # render.comfyui has a workflow input + value output per its spec.
    e = by_kind["render.comfyui"]
    in_ids = [p["id"] for p in e["ports"]["in"]]
    out_ids = [p["id"] for p in e["ports"]["out"]]
    assert "workflow" in in_ids
    assert "value" in out_ids


def test_synthesized_skill_ports_from_library_spec():
    """Skills source their ports from the library spec's inputs /
    outputs (not from a registry executor — Skills are composite specs)."""
    by_kind = {e["kind"]: e for e in ng.grammar_payload()}
    e = by_kind["skill.revit_hero_render"]
    in_ids = [p["id"] for p in e["ports"]["in"]]
    out_ids = [p["id"] for p in e["ports"]["out"]]
    assert "view_name" in in_ids
    assert "style_prompt" in in_ids
    assert "image_path" in out_ids
