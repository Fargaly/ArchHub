from __future__ import annotations

import pytest

from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.cell_relations_view import (
    RELATION_LIST_TEMPLATE_MEMBER_ROOTS,
    RELATION_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_relation_list_template,
)
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    select_universal_root,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _relation_template():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_relation_list_template(batch, protocol) == (
        RELATION_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _render(projection):
    store, protocol = _relation_template()
    return render_view_template(
        store.snapshot(),
        protocol,
        RELATION_LIST_TEMPLATE_ROOT,
        projection,
        budget=500_000,
    )


def _walk(descriptors):
    for item in descriptors:
        yield item
        yield from _walk(item.get("children", ()))


RELATION_PROJECTION = {
    "selected": "relation:r1",
    "selected_relation": {
        "id": "relation:r1",
        "source": {"participant_label": "Alpha"},
        "target": {"participant_label": "Beta"},
        "gates": [
            {
                "participant": "gate:policy",
                "participant_label": "Policy gate",
                "role": "authority",
                "navigable": True,
            },
            {
                "participant": "gate:transform",
                "participant_label": "Transform gate",
                "role": "transform",
                "navigable": False,
            },
        ],
        "observed_revision": 8,
    },
    "connections": [
        {
            "incidence": "inc:source",
            "role": "source",
            "participant": "interface:a",
            "participant_label": "Alpha output",
            "participant_owner": "node:a",
            "editable": True,
            "navigable": True,
        },
        {
            "incidence": "inc:target",
            "role": "target",
            "participant": "interface:b",
            "participant_label": "Beta input",
            "participant_owner": "node:b",
            "editable": False,
            "navigable": True,
        },
        {
            "incidence": "inc:authority",
            "role": "authority",
            "participant": "gate:policy",
            "participant_label": "Policy gate",
            "editable": False,
            "navigable": True,
        },
    ],
    "wires": [],
    "nodes": [
        {"id": "node:a", "label": "Alpha"},
        {"id": "node:b", "label": "Beta"},
        {"id": "node:c", "label": "Gamma"},
    ],
}

ATTACHED_WIRES_PROJECTION = {
    "selected": "node:a",
    "selected_relation": None,
    "connections": [],
    "wires": [
        {"id": "relation:r1", "source": "node:a", "target": "node:b"},
        {"id": "relation:r2", "source": "node:c", "target": "node:a"},
        {"id": "relation:r3", "source": "node:b", "target": "node:c"},
    ],
    "nodes": [
        {"id": "node:a", "label": "Alpha"},
        {"id": "node:b", "label": "Beta"},
        {"id": "node:c", "label": "Gamma"},
    ],
}

EMPTY_WITH_UNRELATED_WIRE_PROJECTION = {
    **ATTACHED_WIRES_PROJECTION,
    "selected": "node:isolated",
}

NON_RELATION_MEMBERS_PROJECTION = {
    "selected": "composition:one",
    "selected_relation": None,
    "connections": [
        {
            "incidence": "inc:source",
            "role": "source",
            "participant": "node:a",
            "participant_label": "Alpha",
            "participant_owner": "node:a",
            "navigable": True,
        },
        {
            "incidence": "inc:member",
            "role": "member",
            "participant": "node:b",
            "participant_label": "Beta",
            "editable": False,
            "navigable": False,
        },
        {
            "incidence": "inc:authority",
            "role": "authority",
            "participant": "node:c",
            "participant_label": "Gamma",
            "editable": False,
            "navigable": True,
        },
    ],
    "wires": [
        {
            "id": "relation:ignored",
            "source": "composition:one",
            "target": "node:a",
        }
    ],
    "nodes": [
        {"id": "node:a", "label": "Alpha"},
        {"id": "node:b", "label": "Beta"},
        {"id": "node:c", "label": "Gamma"},
    ],
}

CONTAINMENT_PROJECTION = {
    "selected": "node:child",
    "selected_relation": None,
    "connections": [
        {
            "incidence": "inc:member",
            "role": "member",
            "direction": "inbound",
            "relation": "scope:archhub",
            "participant": "scope:archhub",
            "participant_label": "ArchHub",
            "editable": False,
            "navigable": True,
        },
    ],
    "wires": [],
    "nodes": [{"id": "node:child", "label": "Ordered List"}],
}

INTERFACE_PROJECTION = {
    "selected": "interface:incoming",
    "selected_relation": None,
    "connections": [
        {
            "incidence": "inc:owner",
            "role": "interface-target",
            "participant": "node:ui",
            "participant_label": "UI & Design System",
            "editable": False,
            "navigable": True,
        },
        {
            "incidence": "inc:name",
            "role": "name",
            "participant": "literal:incoming",
            "participant_label": "Incoming relations",
            "editable": False,
            "navigable": False,
        },
        {
            "incidence": "inc:contract",
            "role": "interface-contract",
            "participant": "protocol:assembly",
            "participant_label": "Assembly protocol",
            "editable": False,
            "navigable": True,
        },
        {
            "incidence": "inc:presentation",
            "role": "interface-presentation",
            "participant": "literal:target",
            "participant_label": "target",
            "editable": False,
            "navigable": False,
        },
        {
            "incidence": "inc:wire-a",
            "role": "seed",
            "participant": "relation:a-ui",
            "participant_label": "Canvas to UI & Design System",
            "editable": False,
            "navigable": True,
        },
        {
            "incidence": "inc:authority",
            "role": "authority",
            "participant": "protocol:assembly",
            "participant_label": "Assembly protocol",
            "editable": False,
            "navigable": True,
        },
        {
            "incidence": "inc:previous",
            "role": "previous",
            "participant": "interface:incoming:v1",
            "participant_label": "Exact target endpoint / Canvas to UI",
            "editable": False,
            "navigable": True,
        },
    ],
    "wires": [],
    "nodes": [
        {"id": "node:ui", "label": "UI & Design System"},
    ],
}


def test_relation_list_has_exactly_nine_stable_executable_presenter_members():
    store, protocol = _relation_template()
    snapshot = store.snapshot()

    assert len(RELATION_LIST_TEMPLATE_MEMBER_ROOTS) == 9
    assert len(set(RELATION_LIST_TEMPLATE_MEMBER_ROOTS)) == 9
    assert RELATION_LIST_TEMPLATE_MEMBER_ROOTS[0] == (
        RELATION_LIST_TEMPLATE_ROOT
    )
    assert is_view_template(snapshot, protocol, RELATION_LIST_TEMPLATE_ROOT)
    assert all(
        is_view_template(snapshot, protocol, root)
        for root in RELATION_LIST_TEMPLATE_MEMBER_ROOTS
    )
    assert all(
        snapshot.cells[root].link0 != NULL_CELL_ID
        for root in RELATION_LIST_TEMPLATE_MEMBER_ROOTS
    )


@pytest.mark.parametrize(
    "projection",
    (
        RELATION_PROJECTION,
        ATTACHED_WIRES_PROJECTION,
        EMPTY_WITH_UNRELATED_WIRE_PROJECTION,
        NON_RELATION_MEMBERS_PROJECTION,
        CONTAINMENT_PROJECTION,
    ),
    ids=(
        "selected-relation",
        "attached-wires",
        "empty-with-unrelated-wire",
        "non-relation-members",
        "containment",
    ),
)
def test_representative_relation_descriptors_are_keyed_and_cell_authored(
    projection,
):
    rendered = _render(projection)
    assert len(rendered) == 1
    assert rendered[0]["key"].startswith("presenter:relation-list:")
    keys = [item["key"] for item in _walk(rendered)]
    assert len(keys) == len(set(keys))


def test_gate_indices_and_nested_option_identity_remain_exact():
    section = _render(RELATION_PROJECTION)[0]
    authority = section["children"][1]
    first_gate, second_gate = authority["children"][2:]
    connection_group = next(
        child for child in section["children"]
        if child["key"].startswith("relation-group:connections:")
    )
    source_row = connection_group["children"][1]
    select = source_row["children"][1]

    assert first_gate["children"][0]["text"] == "authority 1 / protected"
    assert second_gate["children"][0]["text"] == "transform 2 / protected"
    assert [option["key"] for option in select["children"]] == [
        "relation-option:inc:source:node:a",
        "relation-option:inc:source:node:b",
        "relation-option:inc:source:node:c",
    ]
    assert [
        option["attributes"]["data-selected"]
        for option in select["children"]
    ] == [True, False, False]


def test_interface_relations_are_layered_and_readable_without_losing_ids():
    section = _render(INTERFACE_PROJECTION)[0]
    groups = {
        child["class"].split("relation-group-")[1]: child
        for child in section["children"]
        if "relation-group-" in child.get("class", "")
    }

    assert set(groups) == {"overview", "connections", "governance", "history"}
    assert groups["overview"]["attributes"]["open"] is True
    assert groups["connections"]["attributes"] == {}
    assert groups["overview"]["children"][0]["text"] == "Overview / 4"
    assert groups["connections"]["children"][0]["text"] == "Connections / 1"
    assert groups["governance"]["children"][0]["text"] == "Governance / 1"
    assert groups["history"]["children"][0]["text"] == "History / 1"

    overview_rows = groups["overview"]["children"][1:]
    assert [row["children"][0]["text"] for row in overview_rows] == [
        "Owner", "Name", "Contract", "Direction",
    ]
    assert overview_rows[-1]["children"][1]["text"] == "Input"
    connection = groups["connections"]["children"][1]["children"][1]
    assert connection["text"] == "Canvas to UI & Design System"
    assert connection["attributes"]["title"] == "relation:a-ui"


def test_containment_is_a_real_structural_relation_not_a_data_flow_wire():
    section = _render(CONTAINMENT_PROJECTION)[0]
    groups = {
        child["class"].split("relation-group-")[1]: child
        for child in section["children"]
        if "relation-group-" in child.get("class", "")
    }

    assert set(groups) == {"parent"}
    assert groups["parent"]["attributes"]["open"] is True
    assert groups["parent"]["children"][0]["text"] == "Parent / 1"
    row = groups["parent"]["children"][1]
    assert row["children"][0]["text"] == "Contained in"
    assert any(child.get("text") == "ArchHub" for child in row["children"])


def test_container_contents_are_present_but_collapsed_by_default():
    section = _render(NON_RELATION_MEMBERS_PROJECTION)[0]
    contents = next(
        child for child in section["children"]
        if child.get("class") == "relation-group relation-group-contents"
    )

    assert contents["attributes"] == {}
    assert contents["children"][0]["text"] == "Contents / 1"


def test_live_application_projections_render_through_the_v3_graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        initial = project_universal_canvas(store, registry)
        assert _render(initial)[0]["key"].startswith(
            "presenter:relation-list:"
        )
        select_universal_root(store, registry, initial["nodes"][0]["id"])
        selected_node = project_universal_canvas(store, registry)
        parent = selected_node["scope"]["current"]
        containment = next(
            item for item in selected_node["connections"]
            if item.get("direction") == "inbound"
        )
        assert containment["participant"] == parent
        assert containment["relation"] == parent
        assert any(
            member.incidence_id == containment["incidence"]
            and member.participant_id == selected_node["selected"]
            for member in read_relation(store.snapshot(), parent)
        )

        wire = initial["wires"][0]
        select_universal_root(store, registry, wire["id"])
        selected_relation = project_universal_canvas(store, registry)
        assert selected_relation["selected_relation"]["id"] == wire["id"]
        assert any(
            item.get("class") == "relation-group relation-group-connections"
            for item in _walk(_render(selected_relation))
        )

        select_universal_root(store, registry, wire["source"])
        selected_endpoint = project_universal_canvas(store, registry)
        assert any(
            item["source"] == wire["source"]
            or item["target"] == wire["source"]
            for item in selected_endpoint["wires"]
        )
        assert _render(selected_endpoint)
    finally:
        store.close()
