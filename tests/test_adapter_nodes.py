"""Tests for ADAPTER category engine nodes.

adapter.cad_to_revit_wall · adapter.to_revit_directshape ·
adapter.max_to_revit_family

Each node annotates the wired value with target-host metadata
(`revit_target_category`, `revit_*`). Receive-side Speckle Revit
connector reads those to create native walls/families/directshapes.
Tests verify the annotations land + structure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes import adapter  # noqa: F401, E402
from workflows.registry import get as registry_get  # noqa: E402


# ---------------------------------------------------------------------------
# adapter.cad_to_revit_wall


@pytest.fixture
def cad_wall_ex():
    _, ex = registry_get("adapter.cad_to_revit_wall")
    return ex


def test_cad_to_revit_wall_annotates_single_polyline(cad_wall_ex):
    src = {"type": "Polyline", "points": [[0, 0], [5000, 0], [5000, 3000], [0, 3000]]}
    r = cad_wall_ex({"level": "L1", "wall_type": "Generic - 200mm",
                      "height": 3000, "top_offset": 100,
                      "structural": True},
                     {"value": src}, None)
    assert r["status"]["ok"] is True
    assert r["status"]["count"] == 1
    out = r["value"]
    assert out["revit_target_category"] == "Walls"
    assert out["revit_level"] == "L1"
    assert out["revit_wall_type"] == "Generic - 200mm"
    assert out["revit_height_mm"] == 3000
    assert out["revit_top_offset_mm"] == 100
    assert out["revit_structural"] is True
    # Source geometry preserved.
    assert out["type"] == "Polyline"
    assert out["points"] == [[0, 0], [5000, 0], [5000, 3000], [0, 3000]]


def test_cad_to_revit_wall_annotates_list(cad_wall_ex):
    src = [
        {"type": "Polyline", "id": "w1"},
        {"type": "Polyline", "id": "w2"},
        {"type": "Polyline", "id": "w3"},
    ]
    r = cad_wall_ex({"level": "Level 1"}, {"value": src}, None)
    assert r["status"]["ok"] is True
    assert r["status"]["count"] == 3
    for out in r["value"]:
        assert out["revit_target_category"] == "Walls"
        assert out["revit_level"] == "Level 1"
        assert out["id"] in {"w1", "w2", "w3"}


def test_cad_to_revit_wall_defaults_when_config_empty(cad_wall_ex):
    r = cad_wall_ex({}, {"value": {"type": "Polyline"}}, None)
    out = r["value"]
    assert out["revit_level"] == "Level 1"
    assert out["revit_wall_type"] == "Generic - 200mm"
    assert out["revit_height_mm"] == 3000
    assert out["revit_top_offset_mm"] == 0
    assert out["revit_structural"] is False


def test_cad_to_revit_wall_handles_none_value(cad_wall_ex):
    r = cad_wall_ex({"level": "L1"}, {"value": None}, None)
    out = r["value"]
    assert out["revit_target_category"] == "Walls"
    assert out["revit_level"] == "L1"


def test_cad_to_revit_wall_includes_adapter_marker(cad_wall_ex):
    r = cad_wall_ex({}, {"value": {"id": "x"}}, None)
    assert r["value"]["_archhub_adapter"] == "cad_to_revit_wall"


# ---------------------------------------------------------------------------
# adapter.to_revit_directshape


@pytest.fixture
def directshape_ex():
    _, ex = registry_get("adapter.to_revit_directshape")
    return ex


def test_directshape_annotates_generic(directshape_ex):
    src = {"speckle_type": "Objects.Geometry.Mesh", "vertex_count": 1024}
    r = directshape_ex({}, {"value": src}, None)
    out = r["value"]
    assert out["revit_target_category"] == "DirectShape"
    assert out["revit_directshape_category"] == "Generic Models"
    assert out["revit_builtin_category"] == "OST_GenericModel"
    assert out["speckle_type"] == "Objects.Geometry.Mesh"  # preserved


def test_directshape_custom_category(directshape_ex):
    r = directshape_ex({
        "target_category": "Site",
        "category_name": "Sites",
        "builtin_category": "OST_Site",
    }, {"value": {"id": "x"}}, None)
    out = r["value"]
    assert out["revit_directshape_category"] == "Site"
    assert out["revit_builtin_category"] == "OST_Site"


def test_directshape_handles_list(directshape_ex):
    src = [{"id": i} for i in range(4)]
    r = directshape_ex({}, {"value": src}, None)
    assert r["status"]["count"] == 4
    assert all(item["revit_target_category"] == "DirectShape"
                for item in r["value"])


# ---------------------------------------------------------------------------
# adapter.max_to_revit_family


@pytest.fixture
def max_family_ex():
    _, ex = registry_get("adapter.max_to_revit_family")
    return ex


def test_max_to_revit_family_annotates_with_params(max_family_ex):
    src = {"speckle_type": "Objects.Geometry.Mesh",
            "bbox": {"min": [0, 0, 0], "max": [5000, 5000, 12000]}}
    r = max_family_ex({
        "target_category": "Mass",
        "family_name": "RoofPavilion",
        "family_template": "Metric Mass.rft",
        "parameters": {"Height": 12000, "Material": "Concrete"},
    }, {"value": src}, None)
    out = r["value"]
    assert out["revit_target_category"] == "Mass"
    assert out["revit_family_name"] == "RoofPavilion"
    assert out["revit_family_template"] == "Metric Mass.rft"
    assert out["revit_parameters"] == {"Height": 12000, "Material": "Concrete"}


def test_max_to_revit_family_default_category_is_mass(max_family_ex):
    r = max_family_ex({}, {"value": {"id": "x"}}, None)
    out = r["value"]
    assert out["revit_target_category"] == "Mass"
    assert out["revit_family_name"] == "ArchHubMass"


def test_max_to_revit_family_list(max_family_ex):
    r = max_family_ex({"family_name": "Block"},
                       {"value": [{"id": 1}, {"id": 2}]}, None)
    assert r["status"]["count"] == 2
    for out in r["value"]:
        assert out["revit_family_name"] == "Block"


def test_max_to_revit_family_invalid_parameters_become_empty_dict(max_family_ex):
    """If user passes non-dict parameters, fall back to empty {} instead
    of letting bad config crash the cook."""
    r = max_family_ex({"parameters": "not a dict"},
                       {"value": {"id": "x"}}, None)
    assert r["value"]["revit_parameters"] == {}


# ---------------------------------------------------------------------------
# Registry shape


@pytest.mark.parametrize("type_name", [
    "adapter.cad_to_revit_wall",
    "adapter.to_revit_directshape",
    "adapter.max_to_revit_family",
    # Batch 2 (AgDR-0018):
    "adapter.cad_to_revit_detail_line",
    "adapter.rhino_to_revit_beam",
    "adapter.excel_to_revit_params",
])
def test_adapter_registered_with_right_shape(type_name):
    spec, ex = registry_get(type_name)
    assert callable(ex)
    assert spec.category == "adapter"
    assert {p.name for p in spec.inputs} == {"value"}
    assert {p.name for p in spec.outputs} == {"value", "status"}


# ---------------------------------------------------------------------------
# AgDR-0018 Batch 2 — three new adapters


def test_cad_to_revit_detail_line_stamps_annotations():
    _, ex = registry_get("adapter.cad_to_revit_detail_line")
    src = {"type": "Polyline", "points": [[0, 0], [1000, 0]]}
    r = ex({"view_id": 7, "line_style": "Wide Lines"},
            {"value": src}, None)
    out = r["value"]
    assert out["revit_target_category"] == "DetailLines"
    assert out["revit_view_id"] == 7
    assert out["revit_line_style"] == "Wide Lines"
    assert r["status"]["count"] == 1


def test_cad_to_revit_detail_line_default_view_zero():
    _, ex = registry_get("adapter.cad_to_revit_detail_line")
    r = ex({}, {"value": {"foo": "bar"}}, None)
    # Defaults: view_id=0 means "active view".
    assert r["value"]["revit_view_id"] == 0
    assert r["value"]["revit_line_style"] == "Thin Lines"


def test_cad_to_revit_detail_line_list_input():
    _, ex = registry_get("adapter.cad_to_revit_detail_line")
    rows = [{"i": i} for i in range(4)]
    r = ex({"line_style": "Hidden Lines"},
            {"value": rows}, None)
    assert isinstance(r["value"], list)
    assert len(r["value"]) == 4
    for item in r["value"]:
        assert item["revit_target_category"] == "DetailLines"
        assert item["revit_line_style"] == "Hidden Lines"


def test_rhino_to_revit_beam_stamps_annotations():
    _, ex = registry_get("adapter.rhino_to_revit_beam")
    curve = {"type": "Curve", "points": [[0, 0, 0], [5000, 0, 0]]}
    r = ex({"beam_family": "MyBeams", "beam_type": "B-450",
             "level": "Level 2"},
            {"value": curve}, None)
    out = r["value"]
    assert out["revit_target_category"] == "StructuralFraming"
    assert out["revit_beam_family"] == "MyBeams"
    assert out["revit_beam_type"] == "B-450"
    assert out["revit_level"] == "Level 2"
    assert out["revit_structural"] is True


def test_rhino_to_revit_beam_list_input():
    _, ex = registry_get("adapter.rhino_to_revit_beam")
    curves = [{"i": i} for i in range(3)]
    r = ex({}, {"value": curves}, None)
    assert len(r["value"]) == 3
    assert all(item["revit_target_category"] == "StructuralFraming"
               for item in r["value"])


def test_excel_to_revit_params_folds_rows():
    _, ex = registry_get("adapter.excel_to_revit_params")
    rows = [
        {"ElementId": 100, "Width": 500, "Comments": "row1"},
        {"ElementId": 101, "Width": 700, "Comments": "row2"},
    ]
    r = ex({"element_id_column": "ElementId"}, {"value": rows}, None)
    out = r["value"]
    assert isinstance(out, list) and len(out) == 2
    assert out[0]["revit_element_id"] == 100
    assert out[0]["revit_parameters"] == {"Width": 500, "Comments": "row1"}
    assert out[1]["revit_element_id"] == 101
    assert out[1]["revit_parameters"]["Width"] == 700
    # Original row preserved for debugging.
    assert out[0]["_source_row"]["ElementId"] == 100


def test_excel_to_revit_params_ignores_listed_columns():
    _, ex = registry_get("adapter.excel_to_revit_params")
    rows = [{"ElementId": 200, "Width": 1000,
             "Notes": "skip", "Date": "2026-01-01"}]
    r = ex({"element_id_column": "ElementId",
             "ignore_columns": "Notes, Date"},
            {"value": rows}, None)
    out = r["value"][0]
    assert "Notes" not in out["revit_parameters"]
    assert "Date" not in out["revit_parameters"]
    assert out["revit_parameters"] == {"Width": 1000}


def test_excel_to_revit_params_bad_element_id_zero_falls_through():
    """Non-numeric ElementId folds to 0 — the C# generator will
    surface 'Element not found' honestly."""
    _, ex = registry_get("adapter.excel_to_revit_params")
    rows = [{"ElementId": "not-a-number", "Width": 500}]
    r = ex({"element_id_column": "ElementId"}, {"value": rows}, None)
    assert r["value"][0]["revit_element_id"] == 0


def test_excel_to_revit_params_filters_none_values():
    """A column with a None value (empty cell) is excluded from
    `revit_parameters` — don't push Nones."""
    _, ex = registry_get("adapter.excel_to_revit_params")
    rows = [{"ElementId": 1, "A": 10, "B": None, "C": 0}]
    r = ex({"element_id_column": "ElementId"}, {"value": rows}, None)
    params = r["value"][0]["revit_parameters"]
    assert "A" in params and params["A"] == 10
    assert "B" not in params  # None filtered.
    assert "C" in params  # 0 is a real value, not None.


# ---------------------------------------------------------------------------
# AgDR-0018 — classifier + C# emitter extensions


def test_classify_beam_annotation():
    from connectors.revit_speckle_ops import _classify_item
    item = {"revit_target_category": "StructuralFraming",
            "revit_beam_family": "MyBeams"}
    assert _classify_item(item) == "beam"


def test_classify_detail_line_annotation():
    from connectors.revit_speckle_ops import _classify_item
    item = {"revit_target_category": "DetailLines",
            "revit_view_id": 0,
            "revit_polyline": [[0, 0, 0], [1, 0, 0]]}
    assert _classify_item(item) == "detail_line"


def test_classify_parameter_set_annotation():
    """Excel-param items classify as parameter_set, NOT one of the
    create kinds — they belong to revit.batch_set_parameters."""
    from connectors.revit_speckle_ops import _classify_item
    item = {"revit_element_id": 42,
            "revit_parameters": {"Width": 500}}
    assert _classify_item(item) == "parameter_set"


def test_build_create_script_beam_emits_curve_familyinstance():
    from connectors.revit_speckle_ops import build_create_script
    items = [{
        "revit_target_category": "StructuralFraming",
        "revit_beam_family": "WideFlange",
        "revit_beam_type": "W12X26",
        "revit_level": "Level 1",
        "revit_polyline": [[0, 0, 0], [5000, 0, 0]],
    }]
    script = build_create_script(items)
    assert "WideFlange" in script
    assert "W12X26" in script
    assert "StructuralType.Beam" in script
    assert "Line.CreateBound" in script
    # Per-item try/catch.
    assert "try {" in script
    assert "catch (Exception ex)" in script


def test_build_create_script_detail_line_emits_detailcurve():
    from connectors.revit_speckle_ops import build_create_script
    items = [{
        "revit_target_category": "DetailLines",
        "revit_view_id": 0,
        "revit_line_style": "Thin Lines",
        "revit_polyline": [[0, 0, 0], [1000, 0, 0]],
    }]
    script = build_create_script(items)
    assert "NewDetailCurve" in script
    assert "doc.ActiveView" in script  # view_id=0 → active view
    assert "Thin Lines" in script


def test_build_create_script_parameter_set_items_show_in_skipped():
    """An excel-param item routed through build_create_script lands
    in the `skipped` list (handled by batch_set_parameters instead)."""
    from connectors.revit_speckle_ops import build_create_script
    items = [
        {"revit_element_id": 1, "revit_parameters": {"X": 1}},
        # Sandwich with a real creatable item to confirm only the
        # param-set is skipped.
        {"revit_directshape_category": "OST_GenericModel"},
    ]
    script = build_create_script(items)
    assert "skipped = new System.Collections.Generic.List<int> { 0 }" in script
    assert "DirectShape.CreateElement" in script


def test_build_create_script_beam_degenerate_polyline_errors_cleanly():
    """A beam with only 1 point should emit a try-catch that throws
    a clear error — no half-baked Line.CreateBound."""
    from connectors.revit_speckle_ops import build_create_script
    items = [{
        "revit_target_category": "StructuralFraming",
        "revit_beam_family": "MyBeams",
        "revit_beam_type": "X",
        "revit_polyline": [[0, 0, 0]],
    }]
    script = build_create_script(items)
    assert "at least a start and end point" in script
    # No Line.CreateBound emitted for the degenerate case.
    assert "Line.CreateBound" not in script


# ---------------------------------------------------------------------------
# AgDR-0018 — batch_set_parameters generator


def test_build_set_parameters_script_emits_per_param_setters():
    from connectors.revit_speckle_ops import build_set_parameters_script
    items = [{
        "revit_element_id": 42,
        "revit_parameters": {"Width": 500, "Comments": "from-excel"},
    }]
    script = build_set_parameters_script(items)
    # Element lookup by id.
    assert "doc.GetElement(new ElementId(42))" in script
    # Each parameter has a try/LookupParameter/Set chain.
    assert "LookupParameter(\"Width\")" in script
    assert "p.Set(500)" in script
    assert "LookupParameter(\"Comments\")" in script
    assert "p.Set(\"from-excel\")" in script
    # ctx.result block with updated/error/skipped.
    assert "updated_count" in script
    assert "error_count" in script
    assert "skipped_count" in script


def test_build_set_parameters_script_skips_items_without_id():
    from connectors.revit_speckle_ops import build_set_parameters_script
    items = [
        {"revit_element_id": 1, "revit_parameters": {"X": 1}},
        {"revit_parameters": {"Y": 2}},  # no element_id → skipped
        {"revit_element_id": 3, "revit_parameters": "not a dict"},  # bad shape → skipped
    ]
    script = build_set_parameters_script(items)
    # idx 1 + 2 in skipped list.
    assert "skipped = new System.Collections.Generic.List<int> { 1, 2 }" in script


def test_build_set_parameters_script_bool_to_int():
    """Bool values become 0/1 for Revit Yes/No parameters."""
    from connectors.revit_speckle_ops import build_set_parameters_script
    items = [{
        "revit_element_id": 1,
        "revit_parameters": {"IsExternal": True, "IsBearing": False},
    }]
    script = build_set_parameters_script(items)
    assert "p.Set(1)" in script  # True
    assert "p.Set(0)" in script  # False


def test_batch_set_parameters_missing_url():
    from connectors.revit_speckle_ops import batch_set_parameters
    result = batch_set_parameters(source_url="")
    assert result["status"] == "error"
    assert "source_url" in result["error"].lower()


def test_batch_set_parameters_remote_url_not_supported():
    from connectors.revit_speckle_ops import batch_set_parameters
    result = batch_set_parameters(
        source_url="https://app.speckle.systems/streams/X/objects/Y")
    assert result["status"] == "error"
    assert "remote" in result["error"].lower()


# ---------------------------------------------------------------------------
# AgDR-0018 — grammar count after Batch 2


def test_grammar_count_includes_batch_2_adapters():
    """Grammar grew by 3 (rhino_to_revit_beam +
    cad_to_revit_detail_line + excel_to_revit_params). Cap is 75."""
    from workflows import node_grammar as ng
    adapter_kinds = {p.kind for p in ng.PRIMITIVES if p.cat == "adapter"}
    assert "cad_to_revit_wall" in adapter_kinds
    assert "to_revit_directshape" in adapter_kinds
    assert "max_to_revit_family" in adapter_kinds
    assert "cad_to_revit_detail_line" in adapter_kinds
    assert "rhino_to_revit_beam" in adapter_kinds
    assert "excel_to_revit_params" in adapter_kinds
    assert len(adapter_kinds) == 6
    # Cap from test_node_grammar.test_grammar_is_small (≤80 post
    # AgDR-0019 typed AI split + AgDR-0021 ai_plan + code typed split;
    # +1 → 81 for stem-rebuild Phase-0 `verify.assert`).
    # +1 → 82: stem-rebuild Phase-0 `fs.list` (READ-ONLY IO read cell).
    # +3 -> 85: stem-rebuild Phase-0 batch-2 cells (fs.read + data.dedupe
    # + data.json) — cap bumped in lockstep with their node_grammar entries.
    # +2 -> 87: stem-rebuild Phase-0 IO-write cells fs.write + fs.move.
    # +4 -> 91: text.op regex primitives (regex_findall / regex_match /
    # regex_replace / regex_split) exposed by name in the library; the
    # executor was pre-existing. Cap raised 87 -> 91.
    assert len(ng.PRIMITIVES) <= 91
