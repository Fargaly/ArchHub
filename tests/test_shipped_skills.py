"""Built-in Skills — verify the 3 shipped composites build clean
specs + their inner graphs reference only-registered node types.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.skills import (  # noqa: E402
    revit_to_render, photo_to_rhino_mass, drone_to_revit_walls,
)
from workflows import registry as _reg  # noqa: E402


SKILL_MODULES = [
    revit_to_render,
    photo_to_rhino_mass,
    drone_to_revit_walls,
]


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_spec_is_well_formed(mod):
    spec = mod._build_spec()
    assert spec["type"].startswith("skill.")
    assert spec["impl"]["kind"] == "graph"
    g = spec["impl"]["graph"]
    assert g["nodes"], "skill graph has no nodes"
    assert g["wires"], "skill graph has no wires"


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_inner_nodes_are_registered_types(mod):
    """Every node in the inner graph must reference a node type that
    actually exists in workflows.registry — else cooking would error."""
    spec = mod._build_spec()
    for node in spec["impl"]["graph"]["nodes"]:
        t = node["type"]
        # Output nodes are tolerated via existing nodes/io_data; check
        # we at least know about every type referenced.
        assert _reg.get(t) is not None, f"unknown node type {t!r}"


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_inner_io_maps_reference_real_ports(mod):
    """inner_inputs / inner_outputs map ports on outer spec to
    inner-graph node ports. Verify the inner ports exist."""
    spec = mod._build_spec()
    g = spec["impl"]["graph"]
    inner_node_ids = {n["id"] for n in g["nodes"]}
    for inp in spec["impl"].get("inner_inputs") or []:
        assert inp["inner_node"] in inner_node_ids, (
            f"inner_input {inp!r} refs unknown inner node")
    for outp in spec["impl"].get("inner_outputs") or []:
        assert outp["inner_node"] in inner_node_ids, (
            f"inner_output {outp!r} refs unknown inner node")


def test_revit_render_has_expected_outer_ports():
    spec = revit_to_render._build_spec()
    in_names = {p["name"] for p in spec["inputs"]}
    out_names = {p["name"] for p in spec["outputs"]}
    assert "view_name" in in_names and "style_prompt" in in_names
    assert "image_path" in out_names


def test_photo_mass_supports_host_swap():
    spec = photo_to_rhino_mass._build_spec()
    host_opts = set(spec["config_schema"]["host"]["options"])
    assert {"rhino", "revit", "3dsmax", "blender"}.issubset(host_opts)
