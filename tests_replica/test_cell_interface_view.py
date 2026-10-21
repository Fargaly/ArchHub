from __future__ import annotations

import pytest

from nodelang.cell_interface_view import (
    INTERFACE_LIST_PREFIX,
    INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    INTERFACE_LIST_TEMPLATE_ROOT,
    LEGACY_INTERFACE_LIST_PREFIX,
    LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    VIEW_TEMPLATE_PREFIX,
    compose_interface_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _interfaces
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    edit_universal_interface_collection,
    edit_universal_lifecycle_content,
    instantiate_universal_definition,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _interface_template():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_interface_list_template(batch, protocol) == (
        INTERFACE_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _render(projection):
    store, protocol = _interface_template()
    try:
        return render_view_template(
            store.snapshot(),
            protocol,
            INTERFACE_LIST_TEMPLATE_ROOT,
            projection,
            budget=500_000,
        )
    finally:
        store.close()


def _assert_exact_parity(projection):
    assert _render(projection) == _interfaces(projection)


EMPTY_PROJECTION = {
    "selected": "node:none",
    "nodes": [],
    "selected_assembly": None,
}

ORDINARY_PROJECTION = {
    "selected": "assembly:ordinary",
    "nodes": [
        {"id": "node:source", "label": "Source Node"},
    ],
    "selected_assembly": {
        "interfaces": [
            {
                "id": "interface:editable",
                "name": "title",
                "mode": "connection",
                "editable": True,
                "value": "Editable value",
                "control": "control:interface:editable",
                "event_fact_input": "event:submitted-value",
            },
            {
                "id": "interface:target",
                "name": "source",
                "mode": "connection",
                "editable": False,
                "target": "node:source",
                "value": "",
            },
            {
                "id": "interface:state",
                "name": "status",
                "mode": "state",
                "editable": False,
                "value": "",
            },
            {
                "id": "interface:unwired",
                "name": "destination",
                "mode": "connection",
                "editable": False,
                "value": "",
            },
        ],
        "lifecycle": None,
    },
}

COLLECTION_PROJECTION = {
    "selected": "assembly:list",
    "nodes": [],
    "selected_assembly": {
        "interfaces": [
            {
                "id": "interface:items",
                "name": "items",
                "mode": "collection",
            "editable": True,
            "append_control": "control:collection:append",
            "append_event_fact_input": "event:submitted-value",
            "items": [
                    {
                        "incidence": "incidence:alpha",
                        "value": "Alpha",
                        "control": "control:collection:alpha",
                    "event_fact_input": "event:submitted-value",
                    "up_control": "control:alpha:up",
                    "down_control": "control:alpha:down",
                    "remove_control": "control:alpha:remove",
                    },
                    {
                        "incidence": "incidence:beta",
                        "value": "Beta",
                        "control": "control:collection:beta",
                    "event_fact_input": "event:submitted-value",
                    "up_control": "control:beta:up",
                    "down_control": "control:beta:down",
                    "remove_control": "control:beta:remove",
                    },
                ],
            },
        ],
        "lifecycle": None,
    },
}

LIFECYCLE_PROJECTION = {
    "selected": "assembly:asset",
    "nodes": [],
    "selected_assembly": {
        "interfaces": [
            {
                "id": "interface:content",
                "name": "content",
                "mode": "connection",
                "editable": True,
                "value": "owner draft",
            },
        ],
        "lifecycle": {
            "content_interface": "interface:content",
            "release_scoped": False,
            "states": [
                {
                    "name": "WIP",
                    "head_count": 1,
                    "revision": "revision:wip",
                    "heads": [{"revision": "revision:wip"}],
                },
                {
                    "name": "SHARED",
                    "head_count": 0,
                    "revision": None,
                    "heads": [],
                },
            ],
        },
    },
}

DIVERGED_LIFECYCLE_PROJECTION = {
    "selected": "assembly:asset",
    "nodes": [],
    "selected_assembly": {
        "interfaces": [
            {
                "id": "interface:content",
                "name": "content",
                "mode": "connection",
                "editable": True,
                "value": "conflicting drafts",
            },
        ],
        "lifecycle": {
            "content_interface": "interface:content",
            "release_scoped": False,
            "states": [
                {
                    "name": "WIP",
                    "head_count": 2,
                    "revision": None,
                    "heads": [
                        {"revision": "revision:wip-a"},
                        {"revision": "revision:wip-b"},
                    ],
                },
            ],
        },
    },
}

INTERFACE_AUTHORING_PROJECTION = {
    "selected": "node:owner",
    "nodes": [],
    "selected_assembly": None,
    "selected_interfaces": [],
    "authoring": {
        "add_interface": True,
        "owner": "node:owner",
        "interface_form": {
            "root": "form:interface",
            "control": "control:add-interface",
            "control_label": "Add interface",
            "control_title": "Add interface",
            "control_binding": "binding:add-interface",
            "control_capability": "capability:relation-form",
            "control_icon": "icon:plus",
            "operation": "operation:interface-create",
            "operation_path": "/api/universal/interaction",
            "inputs": {
                "name": "form:interface:input:name",
                "presentation": "form:interface:input:presentation",
                "contract": "form:interface:input:contract",
            },
        },
        "interface_presentations": [
            {"id": "presentation:input", "label": "Input"},
            {"id": "presentation:output", "label": "Output"},
        ],
        "interface_contracts": [
            {"id": "contract:cell", "label": "Universal Cell"},
        ],
    },
}


def test_interface_list_preserves_legacy_prefix_and_authors_interface_form():
    store, protocol = _interface_template()
    try:
        snapshot = store.snapshot()
        legacy_v2_roots = (
            INTERFACE_LIST_PREFIX + ":section",
            INTERFACE_LIST_PREFIX + ":heading",
            INTERFACE_LIST_PREFIX + ":collection-row",
            INTERFACE_LIST_PREFIX + ":interface-row",
            INTERFACE_LIST_PREFIX + ":interface-value",
            INTERFACE_LIST_PREFIX + ":interface-input",
            INTERFACE_LIST_PREFIX + ":lifecycle-action",
            INTERFACE_LIST_PREFIX + ":lifecycle-controls",
            INTERFACE_LIST_PREFIX + ":lifecycle-action",
        )
        assert INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS[:9] == legacy_v2_roots
        assert LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS == tuple(
            root.replace(INTERFACE_LIST_PREFIX, LEGACY_INTERFACE_LIST_PREFIX)
            for root in legacy_v2_roots
        )
        assert len(INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS) == 16
        assert len(LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS) == 9
        assert len(set(INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS)) == 15
        assert INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS[6] == (
            INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS[8]
        )
        assert all(
            is_view_template(snapshot, protocol, root)
            for root in set(INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS)
        )
        assert all(
            snapshot.cells[root].link0 != NULL_CELL_ID
            for root in set(INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS)
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "projection",
    (
        EMPTY_PROJECTION,
        ORDINARY_PROJECTION,
        COLLECTION_PROJECTION,
        LIFECYCLE_PROJECTION,
        DIVERGED_LIFECYCLE_PROJECTION,
    ),
    ids=(
        "no-selected-assembly",
        "ordinary-interfaces",
        "collection-controls",
        "lifecycle-save",
        "lifecycle-merge",
    ),
)
def test_raw_interface_projections_have_exact_legacy_parity(projection):
    _assert_exact_parity(projection)


def test_diverged_wip_heads_are_mapped_and_json_serialized_from_raw_state():
    section = _render(DIVERGED_LIFECYCLE_PROJECTION)[0]
    action = section["children"][1]["children"][1]["children"][1]

    assert action["text"] == "MERGE 2 WIP HEADS"
    assert action["attributes"]["data-parents"] == (
        '["revision:wip-a", "revision:wip-b"]'
    )
    assert "data-universal-lifecycle-save" not in action["attributes"]
    _assert_exact_parity(DIVERGED_LIFECYCLE_PROJECTION)


def test_interface_authoring_form_is_graph_projected_with_exact_bindings():
    rendered = _render(INTERFACE_AUTHORING_PROJECTION)
    _assert_exact_parity(INTERFACE_AUTHORING_PROJECTION)

    section = rendered[0]
    form = section["children"][-1]
    assert form["key"] == "interface-create:node:owner"
    assert form["class"] == "interface-create"
    assert form["attributes"] == {
        "data-universal-relation-form": "form:interface",
        "data-universal-relation-form-operation": (
            "operation:interface-create"
        ),
        "data-universal-relation-form-path": (
            "/api/universal/interaction"
        ),
    }
    name, presentation, contract, action = form["children"]
    assert name["attributes"] == {
        "type": "text",
        "placeholder": "Interface name",
        "maxlength": "512",
        "data-universal-relation-form-field": "name",
        "data-universal-relation-form-input": "form:interface:input:name",
    }
    assert [item["value"] for item in presentation["children"]] == [
        "presentation:input", "presentation:output"
    ]
    assert presentation["attributes"] == {
        "data-universal-relation-form-field": "presentation",
        "data-universal-relation-form-input": (
            "form:interface:input:presentation"
        ),
    }
    assert [item["value"] for item in contract["children"]] == [
        "contract:cell"
    ]
    assert contract["attributes"] == {
        "data-universal-relation-form-field": "contract",
        "data-universal-relation-form-input": "form:interface:input:contract",
    }
    assert action["attributes"] == {
        "type": "button",
        "data-universal-relation-form-submit": "form:interface",
        "data-universal-control": "control:add-interface",
        "data-control-binding": "binding:add-interface",
        "data-control-capability": "capability:relation-form",
        "data-control-icon": "icon:plus",
        "title": "Add interface",
        "aria-label": "Add interface",
    }


def test_live_universal_application_projection_states_have_exact_parity():
    store, registry = build_universal_application(resolve_map_path())
    try:
        _assert_exact_parity(project_universal_canvas(store, registry))

        list_root, _ = instantiate_universal_definition(
            store,
            registry,
            registry.standard_library.definition_roots[0],
            x=320,
            y=180,
        )
        collection = project_universal_canvas(store, registry)
        assert collection["selected"] == list_root
        _assert_exact_parity(collection)
        collection_interface = collection["selected_assembly"][
            "interfaces"
        ][0]
        edit_universal_interface_collection(
            store,
            registry,
            list_root,
            collection_interface["id"],
            "append",
            value="Alpha",
        )
        edit_universal_interface_collection(
            store,
            registry,
            list_root,
            collection_interface["id"],
            "append",
            value="Beta",
        )
        populated_collection = project_universal_canvas(store, registry)
        assert len(
            populated_collection["selected_assembly"]["interfaces"][0][
                "items"
            ]
        ) == 2
        _assert_exact_parity(populated_collection)

        connection_root, _ = instantiate_universal_definition(
            store,
            registry,
            registry.standard_library.definition_roots[1],
            x=560,
            y=180,
        )
        connection = project_universal_canvas(store, registry)
        assert connection["selected"] == connection_root
        _assert_exact_parity(connection)

        asset_root, _ = instantiate_universal_definition(
            store,
            registry,
            registry.standard_library.definition_roots[2],
            x=800,
            y=180,
        )
        lifecycle = project_universal_canvas(store, registry)
        assert lifecycle["selected"] == asset_root
        _assert_exact_parity(lifecycle)
        lifecycle_state = lifecycle["selected_assembly"]["lifecycle"]
        content_interface = lifecycle_state["content_interface"]
        initial_wip = next(
            state for state in lifecycle_state["states"]
            if state["name"] == "WIP"
        )["revision"]
        edit_universal_lifecycle_content(
            store,
            registry,
            asset_root,
            content_interface,
            "owner draft one",
            base_revision_root=initial_wip,
        )
        edit_universal_lifecycle_content(
            store,
            registry,
            asset_root,
            content_interface,
            "owner concurrent draft",
            base_revision_root=initial_wip,
        )
        diverged = project_universal_canvas(store, registry)
        wip = next(
            state for state in diverged["selected_assembly"]["lifecycle"][
                "states"
            ]
            if state["name"] == "WIP"
        )
        assert wip["head_count"] == 2
        _assert_exact_parity(diverged)
    finally:
        store.close()
