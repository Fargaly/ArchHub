"""Tests for app/library.py — the in-process library module.

Covers:
- register / inspect / delete round-trip
- search ranking + threshold + category filter + limit
- list_node_types filters by category
- Seed bootstrap (library_seeds.PRIMITIVE_SEEDS all validate + register)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import library  # noqa: E402
from library import (  # noqa: E402
    DuplicateTypeError,
    MATCH_THRESHOLD,
    RegistrationError,
    UnknownTypeError,
    create_node_type,
    delete_node_type,
    inspect,
    list_node_types,
    registry_size,
    reset_registry,
    search,
)
from library_seeds import PRIMITIVE_SEEDS, seed_library  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Reset the in-process library before EACH test so test order is free."""
    reset_registry()
    yield
    reset_registry()


def _spec(type_name: str = "demo.example", **overrides) -> dict:
    base = {
        "type": type_name,
        "display_name": "Demo Example",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A demo node used in the library tests. Has a single output "
            "called `value`. Useful for proving the library mechanics "
            "end-to-end."
        ),
        "examples": [
            {"input": {}, "output": {"value": "x"}, "note": "happy"},
        ],
        "side_effects": "pure",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# register (= create_node_type)


def test_register_modular_spec_succeeds():
    r = create_node_type(_spec())
    assert r == {"id": "demo.example", "registered": True, "type": "demo.example"}
    assert registry_size() == 1


def test_register_non_modular_spec_raises():
    bad = {"type": "demo.bad"}  # missing nearly everything
    with pytest.raises(RegistrationError) as ei:
        create_node_type(bad)
    # violations enumerate every gap — for the one-pass-fix design.
    assert len(ei.value.violations) >= 3


def test_register_duplicate_raises():
    create_node_type(_spec())
    with pytest.raises(DuplicateTypeError):
        create_node_type(_spec())


def test_register_does_not_mutate_caller_dict():
    spec = _spec()
    create_node_type(spec)
    assert "status" not in spec  # caller's dict unchanged
    # but stored copy has defaults filled.
    stored = inspect("demo.example")
    assert stored["status"] == "registered"


# ---------------------------------------------------------------------------
# inspect


def test_inspect_unknown_type_raises():
    with pytest.raises(UnknownTypeError):
        inspect("nope.unknown")


def test_inspect_returns_shallow_copy():
    create_node_type(_spec())
    a = inspect("demo.example")
    b = inspect("demo.example")
    a["display_name"] = "TAMPERED"
    assert b["display_name"] == "Demo Example"  # not aliased


# ---------------------------------------------------------------------------
# delete


def test_delete_known_type_succeeds():
    create_node_type(_spec())
    r = delete_node_type("demo.example")
    assert r == {"id": "demo.example", "ok": True}
    assert registry_size() == 0


def test_delete_unknown_type_raises():
    with pytest.raises(UnknownTypeError):
        delete_node_type("never.registered")


def test_delete_then_re_register_works():
    create_node_type(_spec())
    delete_node_type("demo.example")
    create_node_type(_spec())  # should succeed — not a duplicate now
    assert registry_size() == 1


# ---------------------------------------------------------------------------
# list_node_types


def test_list_empty():
    assert list_node_types() == []


def test_list_returns_summaries_sorted():
    create_node_type(_spec("a.alpha", display_name="Alpha"))
    create_node_type(_spec("b.bravo", display_name="Bravo", category="input"))
    items = list_node_types()
    assert len(items) == 2
    # Sorted by category then display_name.
    assert items[0]["type"] == "b.bravo"  # input < shape
    assert items[1]["type"] == "a.alpha"


def test_list_filtered_by_category():
    create_node_type(_spec("a.x", category="input"))
    create_node_type(_spec("b.y", category="shape"))
    create_node_type(_spec("c.z", category="input"))
    items = list_node_types(category="input")
    assert len(items) == 2
    assert all(s["category"] == "input" for s in items)


# ---------------------------------------------------------------------------
# search — scoring + threshold


def test_search_empty_intent_returns_empty():
    create_node_type(_spec())
    assert search("") == []
    assert search("   ") == []


def test_search_no_match_returns_empty():
    create_node_type(_spec(display_name="Watch Preview"))
    # "octopus" appears nowhere → below threshold.
    assert search("octopus") == []


def test_search_display_name_hit_dominates():
    create_node_type(_spec("a.x", display_name="Tag Walls"))
    create_node_type(_spec("b.y", display_name="Tag Doors"))
    out = search("tag walls")
    assert len(out) >= 1
    assert out[0]["type"] == "a.x"
    # And the score is well above threshold (display hit = +50).
    assert out[0]["score"] >= 50


def test_search_description_hit():
    create_node_type(_spec(
        "a.x",
        display_name="Unrelated",
        description=(
            "Generates a Speckle send-receive wire payload for a Revit "
            "view. Use it before any cross-host transformation."
        ),
    ))
    out = search("speckle")
    assert len(out) == 1
    assert out[0]["type"] == "a.x"


def test_search_word_overlap_alone_below_threshold():
    # Two intent words both appear in the spec as WORDS (not as a
    # contiguous substring of the description / display). Word-overlap
    # alone scores 2 × 5 = 10, below the threshold (30). Verifies that
    # the threshold is enforced — word overlap is a SIGNAL, not a sufficient
    # match on its own.
    create_node_type(_spec(
        "a.x",
        display_name="Unrelated Name",
        description=(
            "A revit walls tagging op for room boundaries. Takes a list "
            "of walls and emits one tag per wall."
        ),
    ))
    # "boundaries tagging" is NOT a contiguous substring of the description
    # ("...for room boundaries. Takes..." has "boundaries." separator;
    # "tagging" appears earlier in "walls tagging op"). Words overlap = 2.
    out = search("boundaries tagging")
    # 2 × 5 = 10 → below threshold (30) → empty.
    assert out == []


def test_search_substring_in_type():
    create_node_type(_spec(
        "speckle.send",
        display_name="Generic Send",
        description=(
            "Sends data through. Generic op used by every host's "
            "speckle-based wire for cross-host streaming."
        ),
    ))
    # "speckle" appears in type (+10), description (+30) = ≥ threshold.
    out = search("speckle")
    assert len(out) == 1


def test_search_threshold_applied():
    # A spec whose ONLY hit is word-overlap (= 5) is below threshold (30).
    create_node_type(_spec(
        "a.x",
        display_name="Unrelated Display",
        description=(
            "Generic node for nothing in particular. Definitely not a "
            "wall, room, view, or model. Documentation filler."
        ),
    ))
    # No substring match, minimal word overlap, far below 30.
    assert search("walls") == [] or all(
        r["score"] >= MATCH_THRESHOLD for r in search("walls")
    )


def test_search_limit_caps_results():
    for i in range(15):
        create_node_type(_spec(
            f"x.n{i}", display_name=f"Demo Display {i}"
        ))
    # All match "demo" via display.
    out = search("demo", limit=5)
    assert len(out) == 5


def test_search_category_filter_boost():
    create_node_type(_spec(
        "a.x",
        display_name="Tag Walls",
        category="shape",
    ))
    create_node_type(_spec(
        "b.y",
        display_name="Tag Walls",
        category="input",
    ))
    # Both display-hit (+50). Category filter boosts one.
    out = search("tag walls", category="input")
    assert out[0]["type"] == "b.y"  # boosted +25 wins the tie


def test_search_sort_tiebreak_alphabetical():
    create_node_type(_spec("a.x", display_name="Zulu Display"))
    create_node_type(_spec("b.y", display_name="Alpha Display"))
    # Both hit via "display" word overlap + substring; same score.
    out = search("display")
    # Tie-break: display_name alphabetical ascending.
    assert out[0]["name"] == "Alpha Display"


def test_search_example_note_boost():
    create_node_type(_spec(
        "a.x",
        display_name="Unrelated",
        description="x" * 80,  # 80-char placeholder, no relevant words
        examples=[
            {
                "input": {},
                "output": {"value": "x"},
                "note": "Used to tag rooms in Revit when boundaries are open.",
            },
        ],
    ))
    out = search("tag rooms")
    # "tag rooms" appears in example.note → +20 → above threshold (with
    # additional word-overlap bonus).
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# Seed bootstrap (library_seeds)


def test_all_primitive_seeds_validate():
    """Every PRIMITIVE_SEED must satisfy the ModularNodeSpec contract.

    If this fails, the seed file drifted from AgDR-0014 design tokens.
    """
    from library_validator import validate

    for spec in PRIMITIVE_SEEDS:
        result = validate(spec)
        assert result.ok, (
            f"seed {spec.get('type', '?')} failed validation: "
            f"{result.violations}"
        )


def test_seed_library_registers_all_seeds():
    r = seed_library()
    assert r["registered"] == len(PRIMITIVE_SEEDS)
    assert r["skipped"] == 0
    assert registry_size() == len(PRIMITIVE_SEEDS)


def test_seed_library_is_idempotent():
    seed_library()  # first call: all registered
    r = seed_library()  # second call: all skipped (already there)
    assert r["registered"] == 0
    assert r["skipped"] == len(PRIMITIVE_SEEDS)
    assert registry_size() == len(PRIMITIVE_SEEDS)


def test_seeded_library_search_finds_connector():
    seed_library()
    out = search("connector")
    assert any(r["type"] == "connector.run" for r in out)


def test_seeded_library_search_finds_constant():
    seed_library()
    out = search("constant")
    assert any(r["type"] == "data.constant" for r in out)


def test_seeded_library_search_finds_watch_via_preview():
    seed_library()
    out = search("preview")
    # watch.preview's description mentions "preview" → display + description hit.
    assert any(r["type"] == "watch.preview" for r in out)


def test_seeded_library_list_filters_by_category():
    seed_library()
    inputs = list_node_types(category="input")
    types = {s["type"] for s in inputs}
    # Seed includes data.constant + input.parameter in category=input.
    assert "data.constant" in types
    assert "input.parameter" in types
    # connector.run is category=connector, must NOT be in input list.
    assert "connector.run" not in types


def test_seeded_library_inspect_returns_full_spec():
    seed_library()
    spec = inspect("connector.run")
    assert spec["type"] == "connector.run"
    assert spec["side_effects"] == "host_write"
    # Validates host_write tier — 2 examples required + present.
    assert len(spec["examples"]) >= 2
