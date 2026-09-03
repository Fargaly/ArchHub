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


# ── AgDR-0040 + AgDR-0041 — Skills build executors via the subgraph
# machinery. Smoke tests: the executor builds without raising AND its
# I/O lifting matches the inner_inputs / inner_outputs declarations.

from workflows.custom_nodes import _build_executor, _spec_from_dict  # noqa: E402


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_builds_executor(mod):
    """Each shipped Skill spec must produce a callable executor — the
    subgraph dispatch chain reaches the inner-graph runner. Raises a
    clear error here if a Skill spec drifts past what the substrate
    understands."""
    spec = mod._build_spec()
    fn = _build_executor(spec, _spec_from_dict(spec))
    assert callable(fn), f"{mod.__name__} did not produce an executor"


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_inner_outputs_lift_to_outer_ports(mod):
    """Every outer output port declared by the Skill MUST have a
    matching inner_outputs entry — otherwise cooking the composite
    would return a node whose declared output never fills."""
    spec = mod._build_spec()
    inner_out_ports = {o["port"] for o in
                       (spec["impl"].get("inner_outputs") or [])}
    outer_out_ports = {p["name"] for p in spec["outputs"]}
    missing = outer_out_ports - inner_out_ports
    assert not missing, (
        f"{mod.__name__} outer outputs {missing!r} have no inner_outputs lift")


@pytest.mark.parametrize("mod", SKILL_MODULES)
def test_skill_inner_inputs_target_real_ports(mod):
    """Every inner_inputs entry must target a port that exists on its
    inner node — silent typos here would mean the composite eats outer
    inputs and never delivers them downstream."""
    from workflows import registry as _reg
    spec = mod._build_spec()
    inner_node_by_id = {n["id"]: n for n in spec["impl"]["graph"]["nodes"]}
    for inp in (spec["impl"].get("inner_inputs") or []):
        nid = inp["inner_node"]
        port_name = inp["inner_port"]
        assert nid in inner_node_by_id, (
            f"{mod.__name__} inner_input refs unknown node {nid!r}")
        inner_type = inner_node_by_id[nid]["type"]
        ns = _reg.get(inner_type)
        assert ns, f"{mod.__name__} inner node type {inner_type!r} unregistered"
        node_spec = ns[0]
        port_names = {p.name for p in node_spec.inputs}
        assert port_name in port_names, (
            f"{mod.__name__} inner_input port {port_name!r} not on "
            f"{inner_type!r}; available: {sorted(port_names)}")
