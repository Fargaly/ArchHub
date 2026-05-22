"""Tests for app/library_validator.py — Layer 4 of the LIBRARY-FIRST +
MODULARITY enforcement model.

Design-system tokens (locked by AgDR-0014) the validator enforces:

- Category enum (11) aligned with engine `cat` + glue + adapter
- Description floor: 80 chars (one full sentence; empirical from Speckle /
  ComfyUI norms)
- Examples count tiered by side_effects: pure ≥1, host_write ≥2, network ≥2
- Status lifecycle: registered | proposed | superseded | deprecated
- Port-type taxonomy resolver (speckle / legacy / free) — warnings only

These tests prove the contract — both the floor (rejects bad specs) and the
tier (accepts well-formed specs).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `app/` importable without depending on the runtime sys.path layout.
_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from library_validator import (  # noqa: E402
    DESCRIPTION_MIN_LENGTH,
    EXAMPLES_MIN_BY_SIDE_EFFECTS,
    ExampleSpec,
    ModularNodeSpec,
    PortSpec,
    ResolvedPortType,
    ValidationResult,
    resolve_port_type,
    schema_json,
    validate,
)


# ---------------------------------------------------------------------------
# Fixtures — one modular spec we mutate per-test
#
# Default fixture: category=`shape`, side_effects=`host_write` (≥2 examples).


def _modular_spec() -> dict:
    return {
        "type": "revit.tag_by_room",
        "display_name": "Tag Walls By Room",
        "category": "shape",
        "inputs": [
            {
                "name": "walls",
                "port_type": "Objects.BuiltElements.Wall",
                "required": True,
                "description": "Walls to tag",
            },
            {
                "name": "rooms",
                "port_type": "Objects.BuiltElements.Room",
                "required": True,
            },
        ],
        "outputs": [
            {
                "name": "tags",
                "port_type": "Objects.BuiltElements.Revit.RevitTag",
                "description": "Created room tags",
            },
        ],
        "config_schema": {
            "properties": {
                "view_id": {"type": "string"},
                "tag_family": {"type": "string", "default": "M_Room Tag"},
            }
        },
        "description": (
            "Tags every wall in the input list with the room it belongs to. "
            "Uses the configured tag family. Skips walls that already have "
            "a tag."
        ),
        "examples": [
            {
                "input": {"walls": "<10 Wall objects>", "rooms": "<3 Room objects>"},
                "output": {"tags": "<10 RoomTag objects>"},
                "note": "Standard happy path.",
            },
            {
                "input": {"walls": "<offline Revit>", "rooms": "<unused>"},
                "output": {"error": "host not reachable"},
                "note": "Offline-host approval-gated failure.",
            },
        ],
        "side_effects": "host_write",
    }


def _pure_spec() -> dict:
    """A pure-side-effects spec — examples ≥1 suffices."""
    s = _modular_spec()
    s["type"] = "data.constant"
    s["side_effects"] = "pure"
    s["examples"] = s["examples"][:1]  # only happy path
    return s


# ---------------------------------------------------------------------------
# PortSpec


def test_port_spec_valid():
    p = PortSpec(name="walls", port_type="Objects.BuiltElements.Wall")
    assert p.name == "walls"
    assert p.required is False  # default


def test_port_spec_name_with_underscores():
    PortSpec(name="tag_family", port_type="string")


def test_port_spec_name_with_digits():
    PortSpec(name="port_2", port_type="string")


def test_port_spec_name_starts_with_digit_rejected():
    with pytest.raises(Exception):
        PortSpec(name="2_walls", port_type="string")


def test_port_spec_name_with_spaces_rejected():
    with pytest.raises(Exception):
        PortSpec(name="my walls", port_type="string")


def test_port_spec_name_with_dash_rejected():
    with pytest.raises(Exception):
        PortSpec(name="my-walls", port_type="string")


def test_port_spec_name_too_long_rejected():
    long_name = "a" * 41
    with pytest.raises(Exception):
        PortSpec(name=long_name, port_type="string")


def test_port_spec_name_empty_rejected():
    with pytest.raises(Exception):
        PortSpec(name="", port_type="string")


def test_port_spec_port_type_required():
    with pytest.raises(Exception):
        PortSpec(name="walls")  # type: ignore[call-arg]


def test_port_spec_description_too_long_rejected():
    with pytest.raises(Exception):
        PortSpec(
            name="walls",
            port_type="string",
            description="x" * 201,
        )


# ---------------------------------------------------------------------------
# ExampleSpec


def test_example_spec_valid():
    e = ExampleSpec(input={"x": 1}, output={"y": 2})
    assert e.input == {"x": 1}
    assert e.note is None


def test_example_spec_empty_dicts_allowed():
    # Edge: an example with empty input + output is technically allowed —
    # used for nodes with no inputs (a constant generator).
    ExampleSpec(input={}, output={})


def test_example_spec_note_too_long_rejected():
    with pytest.raises(Exception):
        ExampleSpec(input={}, output={}, note="x" * 201)


# ---------------------------------------------------------------------------
# ModularNodeSpec — accept


def test_modular_spec_full_accepts():
    spec = _modular_spec()
    m = ModularNodeSpec.model_validate(spec)
    assert m.type == "revit.tag_by_room"
    assert len(m.outputs) == 1
    assert m.side_effects == "host_write"
    assert m.status == "registered"  # default


def test_modular_spec_inputs_empty_accepted():
    # A pure-generator node has no inputs.
    spec = _pure_spec()
    spec["inputs"] = []
    ModularNodeSpec.model_validate(spec)


def test_modular_spec_side_effects_defaults_to_pure():
    spec = _pure_spec()
    del spec["side_effects"]
    m = ModularNodeSpec.model_validate(spec)
    assert m.side_effects == "pure"


def test_modular_spec_config_schema_flat_shorthand_accepted():
    spec = _modular_spec()
    spec["config_schema"] = {"view_id": {"type": "string"}}
    ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# ModularNodeSpec — reject (type pattern)


@pytest.mark.parametrize("bad_type", [
    "revit",                # no dot
    "revit.",               # nothing after dot
    ".tag",                 # nothing before dot
    "Revit.tag",            # capital
    "revit.Tag",            # capital on right side
    "revit.123tag",         # right side starts with digit
    "1revit.tag",           # left starts with digit
    "revit-host.tag",       # dash
    "revit.tag-by-room",    # dash in body
    "revit.tag by room",    # space
    "revit..tag",           # double dot
    "",                     # empty
])
def test_modular_spec_type_pattern_rejects(bad_type: str):
    spec = _modular_spec()
    spec["type"] = bad_type
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


@pytest.mark.parametrize("good_type", [
    "revit.tag_by_room",
    "autocad.send_to_speckle",
    "ai.plan",
    "data.constant",
    "revit.tag_by_room_2",
])
def test_modular_spec_type_pattern_accepts(good_type: str):
    spec = _modular_spec()
    spec["type"] = good_type
    ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# ModularNodeSpec — category enum (AgDR-0014 token 1: 11 values)


@pytest.mark.parametrize("good_category", [
    "input", "connector", "ai", "logic", "output",
    "skill", "shape", "watch", "note", "glue", "adapter",
])
def test_modular_spec_category_all_11_accepted(good_category: str):
    spec = _modular_spec()
    spec["category"] = good_category
    ModularNodeSpec.model_validate(spec)


@pytest.mark.parametrize("bad_category", [
    "primitive",   # removed in AgDR-0014 (axis collision with `kind`)
    "transform",   # collapsed into `shape`
    "filter",      # collapsed into `shape`
    "decoration",
    "junk",
    "",
    "shapes",      # plural
    "Shape",       # capital
])
def test_modular_spec_category_old_or_invalid_rejected(bad_category: str):
    spec = _modular_spec()
    spec["category"] = bad_category
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# ModularNodeSpec — reject (field-level)


def test_modular_spec_display_name_too_short():
    spec = _modular_spec()
    spec["display_name"] = "x"
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_display_name_too_long():
    spec = _modular_spec()
    spec["display_name"] = "x" * 61
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_outputs_required():
    spec = _modular_spec()
    spec["outputs"] = []
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_config_schema_empty_rejected():
    spec = _modular_spec()
    spec["config_schema"] = {}
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_config_schema_empty_properties_rejected():
    spec = _modular_spec()
    spec["config_schema"] = {"properties": {}}
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# AgDR-0014 token 2 — description floor = 80 chars


def test_description_floor_is_80():
    # Sanity: the constant matches AgDR-0014.
    assert DESCRIPTION_MIN_LENGTH == 80


def test_modular_spec_description_too_short_60_chars():
    # 60 chars used to pass (AgDR-0013 picked it). AgDR-0014 bumped it.
    spec = _pure_spec()
    spec["description"] = "x" * 60
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_description_79_chars_rejected():
    spec = _pure_spec()
    spec["description"] = "x" * 79
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_modular_spec_description_80_chars_accepted():
    spec = _pure_spec()
    spec["description"] = "x" * 80
    ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# AgDR-0014 token 3 — examples count tiered by side_effects


def test_examples_tier_constants_match_agdr_0014():
    # Sanity: lock the tier values in the test layer so any future drift
    # surfaces immediately.
    assert EXAMPLES_MIN_BY_SIDE_EFFECTS == {
        "pure": 1, "host_write": 2, "network": 2,
    }


def test_pure_one_example_accepted():
    spec = _pure_spec()
    assert spec["side_effects"] == "pure"
    assert len(spec["examples"]) == 1
    ModularNodeSpec.model_validate(spec)


def test_pure_zero_examples_rejected():
    spec = _pure_spec()
    spec["examples"] = []
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_host_write_one_example_rejected():
    # Host-write needs ≥2 examples — happy + failure / approval-gated edge.
    spec = _modular_spec()
    assert spec["side_effects"] == "host_write"
    spec["examples"] = spec["examples"][:1]
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_host_write_two_examples_accepted():
    spec = _modular_spec()  # already has 2 examples
    assert spec["side_effects"] == "host_write"
    assert len(spec["examples"]) == 2
    ModularNodeSpec.model_validate(spec)


def test_network_one_example_rejected():
    spec = _pure_spec()
    spec["side_effects"] = "network"  # bumps tier to 2
    spec["examples"] = spec["examples"][:1]
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


def test_network_two_examples_accepted():
    spec = _pure_spec()
    spec["side_effects"] = "network"
    spec["examples"] = [
        {"input": {"url": "ok"}, "output": {"data": "..."}},
        {"input": {"url": "bad"}, "output": {"error": "timeout"}},
    ]
    ModularNodeSpec.model_validate(spec)


def test_host_write_violation_message_mentions_tier():
    spec = _modular_spec()
    spec["examples"] = spec["examples"][:1]  # 1 example, host_write
    r = validate(spec)
    assert r.ok is False
    # The violation message must explain the tier so the LLM can fix in
    # one retry — not just emit "list too short" and force a guess.
    joined = " ".join(r.violations).lower()
    assert "host_write" in joined or "2" in joined
    assert "example" in joined


# ---------------------------------------------------------------------------
# AgDR-0014 token 6 — status lifecycle


def test_status_defaults_to_registered():
    spec = _modular_spec()
    m = ModularNodeSpec.model_validate(spec)
    assert m.status == "registered"


@pytest.mark.parametrize("good_status", [
    "registered", "proposed", "superseded", "deprecated",
])
def test_status_enum_values_accepted(good_status: str):
    spec = _modular_spec()
    spec["status"] = good_status
    ModularNodeSpec.model_validate(spec)


@pytest.mark.parametrize("bad_status", [
    "active", "live", "archived", "draft", "",
])
def test_status_invalid_rejected(bad_status: str):
    spec = _modular_spec()
    spec["status"] = bad_status
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# Side-effects enum


def test_modular_spec_side_effects_invalid():
    spec = _modular_spec()
    spec["side_effects"] = "destructive"  # not in enum
    with pytest.raises(Exception):
        ModularNodeSpec.model_validate(spec)


# ---------------------------------------------------------------------------
# validate() — the public API


def test_validate_returns_validation_result():
    r = validate(_modular_spec())
    assert isinstance(r, ValidationResult)
    assert r.ok is True, r.violations
    assert r.violations == []


def test_validate_empty_dict_rejects_with_many_violations():
    r = validate({})
    assert r.ok is False
    assert len(r.violations) >= 5
    joined = " ".join(r.violations).lower()
    for needle in ("type", "display_name", "category", "outputs", "description"):
        assert needle in joined, f"missing violation for {needle}: {r.violations}"


def test_validate_non_dict_input_rejects():
    r = validate("not a dict")  # type: ignore[arg-type]
    assert r.ok is False
    assert any("object" in v.lower() for v in r.violations)


def test_validate_violations_are_strings():
    r = validate({})
    assert r.ok is False
    for v in r.violations:
        assert isinstance(v, str)
        assert v  # not empty


def test_validate_violations_include_field_paths():
    spec = _pure_spec()
    spec["examples"] = []
    r = validate(spec)
    assert r.ok is False
    joined = " ".join(r.violations).lower()
    assert "example" in joined


def test_validate_nested_port_error_surfaces_with_path():
    spec = _modular_spec()
    spec["outputs"] = [{"port_type": "string"}]  # missing name
    r = validate(spec)
    assert r.ok is False
    assert any("outputs" in v and "name" in v for v in r.violations)


def test_validate_modular_spec_with_zero_inputs_accepted():
    spec = _pure_spec()
    spec["inputs"] = []
    r = validate(spec)
    assert r.ok is True, r.violations


def test_validate_each_field_failure_produces_at_least_one_violation():
    """The validator's job is to surface EVERY missing piece in one pass —
    not stop at the first. The LLM must see them all to fix in one retry.
    """
    spec = {
        "type": "BAD",                         # pattern fail
        "display_name": "x",                   # too short
        "category": "junk",                    # not in enum
        "outputs": [],                          # empty
        "config_schema": {},                    # empty
        "description": "short",                 # too short
        "examples": [],                         # empty
    }
    r = validate(spec)
    assert r.ok is False
    joined = " ".join(r.violations)
    for needle in ("type", "display_name", "category", "outputs",
                    "config_schema", "description"):
        assert needle in joined, f"missing violation for {needle}: {r.violations}"


# ---------------------------------------------------------------------------
# schema_json() — JSON Schema emit


def test_schema_json_returns_dict():
    s = schema_json()
    assert isinstance(s, dict)


def test_schema_json_has_properties():
    s = schema_json()
    assert "properties" in s
    for key in ("type", "display_name", "category", "outputs",
                 "description", "examples", "status"):
        assert key in s["properties"], f"missing {key} in schema_json properties"


def test_schema_json_required_fields_listed():
    s = schema_json()
    assert "required" in s
    required = set(s["required"])
    for key in ("type", "display_name", "category", "outputs", "description"):
        assert key in required, f"{key} should be required in JSON Schema"


# ---------------------------------------------------------------------------
# AgDR-0014 token 8 — resolve_port_type taxonomy resolver


def test_resolve_port_type_speckle():
    r = resolve_port_type("Objects.BuiltElements.Wall")
    assert r == ResolvedPortType("speckle", "Objects.BuiltElements.Wall")


def test_resolve_port_type_speckle_nested():
    r = resolve_port_type("Objects.Geometry.Line")
    assert r.kind == "speckle"


def test_resolve_port_type_legacy_walls():
    r = resolve_port_type("walls")
    assert r == ResolvedPortType("legacy", "walls")


def test_resolve_port_type_legacy_capital_normalised():
    r = resolve_port_type("Walls")
    assert r.kind == "legacy"
    assert r.canonical == "walls"


def test_resolve_port_type_free_string():
    r = resolve_port_type("unknown_special_type")
    assert r.kind == "free"
    assert r.canonical == "unknown_special_type"


def test_resolve_port_type_empty_string():
    r = resolve_port_type("")
    assert r.kind == "free"
    assert r.canonical == ""


def test_resolve_port_type_strips_whitespace():
    r = resolve_port_type("  walls  ")
    assert r.kind == "legacy"
    assert r.canonical == "walls"


def test_resolve_port_type_returns_named_tuple():
    # The NamedTuple shape lets callers do tuple-unpack or attr access.
    r = resolve_port_type("walls")
    kind, canonical = r
    assert kind == "legacy"
    assert canonical == "walls"
    assert r.kind == "legacy"
    assert r.canonical == "walls"
