"""Acceptance court: a wire crossing a group's edge rides its boundary."""
from __future__ import annotations

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    group_universal_selection,
    project_universal_canvas,
    set_universal_selection,
)


def test_a_wire_crossing_a_group_edge_rides_its_boundary_and_returns():
    """Pre-existing on 6e167b6 (test_group_and_ungroup_are_lossless...):
    grouping gm:domain:ui with gm:domain:canvas dropped the wire
    core-values -> ui from the top view index, so nothing reached the
    group's derived boundary port. A crossing wire stays drawn, attached
    to the group, and ungroup gives back the exact original wire."""
    from nodelang.universal_application import ungroup_universal_composition

    store, registry = build_universal_application(resolve_map_path())

    def wires(canvas):
        return {
            wire["id"]: (
                wire["source"], wire["target"],
                wire["source_interface"], wire["target_interface"],
                wire["source_incidence"], wire["target_incidence"],
            )
            for wire in canvas["wires"]
        }

    domains = registry.map.domains
    selected = (domains["ui"], domains["canvas"])
    before = wires(project_universal_canvas(store, registry))
    crossing = {
        wire_id for wire_id, wire in before.items()
        if (wire[0] in selected) != (wire[1] in selected)
    }
    assert crossing, "the court needs a wire crossing the selection"
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    group, _ = group_universal_selection(store, registry, title="Edge")
    grouped = project_universal_canvas(store, registry)
    node = next(node for node in grouped["nodes"] if node["id"] == group)
    boundary = {port["id"] for port in node["ports"] if port.get("derived")}
    drawn = wires(grouped)
    assert crossing <= set(drawn)
    for wire_id in crossing:
        source, target, source_interface, target_interface = drawn[wire_id][:4]
        assert group in (source, target)
        assert {source_interface, target_interface} & boundary
    ungroup_universal_composition(store, registry, group)
    assert wires(project_universal_canvas(store, registry)) == before
