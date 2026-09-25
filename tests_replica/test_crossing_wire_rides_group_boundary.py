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


def _wires(canvas):
    return {
        wire["id"]: (
            wire["source"], wire["target"],
            wire["source_interface"], wire["target_interface"],
            wire["source_incidence"], wire["target_incidence"],
        )
        for wire in canvas["wires"]
    }


def _drawn(store, registry):
    revision = store.revision
    canvas = project_universal_canvas(store, registry)
    assert store.revision == revision, "a canvas read wrote the graph"
    return canvas


def test_a_wire_into_a_card_two_groups_deep_rides_the_outer_boundary():
    """Crossing-wire v2: a wire whose end sits inside a group inside a group
    is drawn on the OUTER group's boundary port; ungrouping the outer group
    commits once and the read after it writes nothing; each ungroup gives
    back the exact wires the canvas had before the matching group."""
    from nodelang.universal_application import ungroup_universal_composition

    store, registry = build_universal_application(resolve_map_path())
    domains = registry.map.domains
    inner_pair = (domains["brain"], domains["ui"])
    outer_extra = domains["canvas"]
    before = _wires(_drawn(store, registry))
    deep = set(inner_pair) | {outer_extra}
    crossing = {
        wire_id for wire_id, wire in before.items()
        if (wire[0] in deep) != (wire[1] in deep)
    }
    assert crossing, "the court needs a wire crossing the nested selection"
    set_universal_selection(
        store, registry, inner_pair, focus_root=inner_pair[-1]
    )
    inner, _ = group_universal_selection(store, registry, title="Inner")
    after_inner = _wires(_drawn(store, registry))
    set_universal_selection(
        store, registry, (inner, outer_extra), focus_root=outer_extra
    )
    outer, _ = group_universal_selection(store, registry, title="Outer")
    canvas = _drawn(store, registry)
    node = next(node for node in canvas["nodes"] if node["id"] == outer)
    boundary = {port["id"] for port in node["ports"] if port.get("derived")}
    drawn = _wires(canvas)
    missing = sorted(crossing - set(drawn))
    assert not missing, ("crossing-missing", missing)
    for wire_id in crossing:
        source, target, source_interface, target_interface = drawn[wire_id][:4]
        assert outer in (source, target), wire_id
        assert {source_interface, target_interface} & boundary, wire_id
    revision = store.revision
    ungroup_universal_composition(store, registry, outer)
    assert store.revision == revision + 1
    assert _wires(_drawn(store, registry)) == after_inner
    ungroup_universal_composition(store, registry, inner)
    assert _wires(_drawn(store, registry)) == before


def test_reading_after_ungrouping_the_outer_group_writes_nothing():
    """Crossing-wire v2 (also on base): after ungrouping the OUTER group of
    a nested pair the next canvas read committed the inner group's ports
    ("READ WROTE 938 -> 939"). The ungroup gesture publishes the whole
    index; the read after it writes nothing."""
    from nodelang.universal_application import ungroup_universal_composition

    store, registry = build_universal_application(resolve_map_path())
    domains = registry.map.domains
    set_universal_selection(
        store, registry, (domains["brain"], domains["ui"]),
        focus_root=domains["ui"],
    )
    inner, _ = group_universal_selection(store, registry, title="Inner")
    project_universal_canvas(store, registry)
    set_universal_selection(
        store, registry, (inner, domains["canvas"]),
        focus_root=domains["canvas"],
    )
    outer, _ = group_universal_selection(store, registry, title="Outer")
    project_universal_canvas(store, registry)
    ungroup_universal_composition(store, registry, outer)
    revision = store.revision
    project_universal_canvas(store, registry)
    assert store.revision == revision, "a canvas read wrote the graph"
