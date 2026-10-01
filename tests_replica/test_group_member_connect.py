"""A collapsed group's direct members stay wireable; nothing wider opens.

Collapsing cards into a group keeps each member's own interfaces. A wire
started or dropped on a member through the group joins that member's
interface; the group draws it at its edge and keeps its identity and place.
The group's derived boundary interfaces still refuse new connections, a
member of a group that is itself hidden stays outside, and a card on another
canvas level stays outside.
"""
from pathlib import Path

import pytest

from nodelang import universal_application as app
from nodelang.universal_cell import InvalidCell
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture
def application():
    public_map = Path(app.__file__).parent / "data" / "public_runtime_map.json"
    return app.build_universal_application(public_map)


def _node(projection, root):
    return next(node for node in projection["nodes"] if node["id"] == root)


def _port(projection, root, side):
    return next(
        port["id"] for port in _node(projection, root)["ports"]
        if port["side"] == side and port.get("mode") == "connection"
    )


def _cards(store, registry, *titles):
    return [
        create_engine_node(store, registry, title=title, engine="library.think")["root"]
        for title in titles
    ]


def _group(store, registry, roots):
    app.set_universal_selection(store, registry, list(roots))
    group, _ = app.group_universal_selection(
        store, registry,
        projected_canvas=app.project_universal_canvas(store, registry),
    )
    return group


def test_a_member_of_a_visible_collapsed_group_connects_and_the_group_keeps_its_place(application):
    store, registry = application
    member, other, outer = _cards(store, registry, "Member", "Other", "Outer")
    before = app.project_universal_canvas(store, registry)
    source, target = _port(before, member, "source"), _port(before, outer, "target")
    group = _group(store, registry, (member, other))
    grouped = app.project_universal_canvas(store, registry)
    place = (_node(grouped, group)["x"], _node(grouped, group)["y"])
    wires = len(grouped["wires"])

    relation, _ = app.connect_universal_roots(
        store, registry, member, outer, source_interface=source, target_interface=target,
    )

    after = app.project_universal_canvas(store, registry)
    assert len(after["wires"]) == wires + 1
    wire = next(item for item in after["wires"] if item["id"] == relation)
    boundary = {port["id"]: port for port in _node(after, group)["ports"] if port.get("derived")}
    assert (wire["source"], wire["target"]) == (group, outer), "the group draws the member's wire at its edge"
    assert wire["source_interface"] in boundary, "on a derived boundary port, like a wire that crossed when grouped"
    assert boundary[wire["source_interface"]]["connectable"] is False
    assert (_node(after, group)["x"], _node(after, group)["y"]) == place, "the group keeps its place"
    assert _node(after, group)["composition"] is True

    app.ungroup_universal_composition(store, registry, group)
    expanded = app.project_universal_canvas(store, registry)
    wire = next(item for item in expanded["wires"] if item["id"] == relation)
    assert (wire["source"], wire["source_interface"], wire["target"]) == (member, source, outer), \
        "expanding shows the wire on the member's own interface"


def test_two_members_of_one_group_are_not_wired_across_its_edge(application):
    store, registry = application
    first, second = _cards(store, registry, "First", "Second")
    before = app.project_universal_canvas(store, registry)
    source, target = _port(before, first, "source"), _port(before, second, "target")
    _group(store, registry, (first, second))
    with pytest.raises(InvalidCell, match="members of one group are wired inside it"):
        app.connect_universal_roots(
            store, registry, first, second, source_interface=source, target_interface=target,
        )


def test_a_member_of_a_hidden_group_stays_outside_the_canvas(application):
    store, registry = application
    member, other, loose, outer = _cards(store, registry, "Member", "Other", "Loose", "Outer")
    before = app.project_universal_canvas(store, registry)
    source, target = _port(before, member, "source"), _port(before, outer, "target")
    inner = _group(store, registry, (member, other))
    _group(store, registry, (inner, loose))
    with pytest.raises(InvalidCell, match="outside the active canvas"):
        app.connect_universal_roots(
            store, registry, member, outer, source_interface=source, target_interface=target,
        )


def test_a_card_on_another_canvas_level_stays_outside(application):
    store, registry = application
    member, other, outer = _cards(store, registry, "Member", "Other", "Outer")
    before = app.project_universal_canvas(store, registry)
    source, target = _port(before, member, "source"), _port(before, outer, "target")
    group = _group(store, registry, (member, other))
    app.set_universal_scope(store, registry, group)
    with pytest.raises(InvalidCell, match="outside the active canvas"):
        app.connect_universal_roots(
            store, registry, member, outer, source_interface=source, target_interface=target,
        )


def test_the_group_boundary_still_refuses_new_connections(application):
    store, registry = application
    member, other, outer, second = _cards(store, registry, "Member", "Other", "Outer", "Second")
    before = app.project_universal_canvas(store, registry)
    app.connect_universal_roots(
        store, registry, member, outer,
        source_interface=_port(before, member, "source"),
        target_interface=_port(before, outer, "target"),
    )
    group = _group(store, registry, (member, other))
    grouped = app.project_universal_canvas(store, registry)
    boundary = next(port for port in _node(grouped, group)["ports"] if port.get("derived"))
    assert boundary["connectable"] is False
    with pytest.raises(InvalidCell, match="derived composition boundaries"):
        app.connect_universal_roots(
            store, registry, group, second,
            source_interface=boundary["id"],
            target_interface=_port(grouped, second, "target"),
            leased_projection=grouped,
        )


def test_the_group_lists_its_members_ports_and_wires_through_them_both_ways(application):
    store, registry = application
    member, other, outer = _cards(store, registry, "Member", "Other", "Outer")
    group = _group(store, registry, (member, other))
    grouped = app.project_universal_canvas(store, registry)
    listed = _node(grouped, group)["member_ports"]
    assert {(port["owner_label"], port["side"]) for port in listed} == {
        ("Member", "source"), ("Member", "target"), ("Other", "source"), ("Other", "target"),
    }, "the group lists each member's own ports, not its derived boundary"
    assert all(not port.get("derived") for port in listed)
    member_out = next(port for port in listed if port["owner"] == member and port["side"] == "source")
    assert member_out["connect_control"] and any(
        choice["owner"] == outer for choice in member_out["connect_choices"]
    ), "a member output offers the outer card's input"
    assert all(choice["owner"] not in (member, other) for choice in member_out["connect_choices"]), \
        "wiring between members of the same group happens inside it"
    outer_out = next(
        port for port in _node(grouped, outer)["ports"]
        if port["side"] == "source" and port.get("mode") == "connection"
    )
    member_in = next(port for port in listed if port["owner"] == member and port["side"] == "target")
    assert any(
        choice["owner"] == member and choice["id"] == member_in["id"]
        for choice in outer_out["connect_choices"]
    ), "an outer output offers the member's input through the group"

    first, _ = app.connect_universal_roots(
        store, registry, member, outer,
        source_interface=member_out["id"],
        target_interface=next(
            port["id"] for port in _node(grouped, outer)["ports"]
            if port["side"] == "target" and port.get("mode") == "connection"
        ),
        leased_projection=grouped,
    )
    again = app.project_universal_canvas(store, registry)
    second, _ = app.connect_universal_roots(
        store, registry, outer, member,
        source_interface=outer_out["id"], target_interface=member_in["id"],
        leased_projection=again,
    )
    after = app.project_universal_canvas(store, registry)
    drawn = {item["id"]: (item["source"], item["target"]) for item in after["wires"]}
    assert drawn[first] == (group, outer) and drawn[second] == (outer, group)


def _boundary_shape(store, registry, boundary_root, composition_root, relation_root, seed_root):
    """One derived boundary with its identities replaced by their roles in the story."""
    snapshot = store.snapshot()
    roles = {value: name for name, value in registry.roles.items()}
    for name in ("interface-target", "name", "interface-contract", "interface-presentation"):
        roles[registry.assembly_protocol.role(name)] = name
    names = {composition_root: "<group>", relation_root: "<wire>", seed_root: "<member-interface>",
             registry.roles["read-only"]: "<read-only>"}
    members = []
    for member in app.read_relation(snapshot, boundary_root, budget=64):
        participant = member.participant_id
        if participant.startswith(boundary_root + ":"):
            participant = "<boundary>" + participant[len(boundary_root):] + "=" + snapshot.cells[participant].atom.decode("ascii")
        elif member.role_id == registry.roles["authority"]:
            participant = "<wire-incidence>" if snapshot.cells[participant].link0 == relation_root or participant in {
                item.incidence_id for item in app.read_relation(snapshot, relation_root, budget=16)} else participant
        members.append((roles.get(member.role_id, member.role_id), names.get(participant, participant)))
    return members


def test_a_boundary_derived_at_connect_has_the_exact_shape_grouping_derives_and_stays_read_only(application):
    store, registry = application
    # Grouping derives a boundary for a wire that already crosses.
    early, early_other, early_outer = _cards(store, registry, "Early", "Early other", "Early outer")
    before = app.project_universal_canvas(store, registry)
    early_source = _port(before, early, "source")
    early_wire, _ = app.connect_universal_roots(
        store, registry, early, early_outer,
        source_interface=early_source, target_interface=_port(before, early_outer, "target"),
    )
    early_group = _group(store, registry, (early, early_other))
    grouped = app.project_universal_canvas(store, registry)
    [grouping_port] = [port for port in _node(grouped, early_group)["ports"] if port.get("derived")]

    # Connecting to a member of a collapsed group derives one for the new wire.
    late, late_other, late_outer = _cards(store, registry, "Late", "Late other", "Late outer")
    fresh = app.project_universal_canvas(store, registry)
    late_source = _port(fresh, late, "source")
    late_target = _port(fresh, late_outer, "target")
    late_group = _group(store, registry, (late, late_other))
    late_wire, _ = app.connect_universal_roots(
        store, registry, late, late_outer, source_interface=late_source, target_interface=late_target,
    )
    after = app.project_universal_canvas(store, registry)
    [connect_port] = [port for port in _node(after, late_group)["ports"] if port.get("derived")]

    assert _boundary_shape(store, registry, connect_port["id"], late_group, late_wire, late_source) == \
        _boundary_shape(store, registry, grouping_port["id"], early_group, early_wire, early_source), \
        "the connect-time boundary is the grouping boundary, cell for cell"
    for port in (grouping_port, connect_port):
        assert port["derived"] is True and port["connectable"] is False, "read-only, never wireable"
    keys = ("name", "side", "mode", "connectable", "derived")
    assert {key: connect_port.get(key) for key in keys} == {key: grouping_port.get(key) for key in keys}
