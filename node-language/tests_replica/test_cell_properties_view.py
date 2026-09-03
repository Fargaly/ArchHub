from __future__ import annotations

from nodelang.cell_properties_view import (
    FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    FIELD_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_field_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import project_presenter
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def test_field_list_is_an_executable_graph_assembly_not_a_named_dispatch():
    assert project_presenter("field-list", {}) is None
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_field_list_template(batch, protocol) == (
        FIELD_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    snapshot = store.snapshot()

    assert is_view_template(snapshot, protocol, FIELD_LIST_TEMPLATE_ROOT)
    assert all(
        snapshot.cells[root].link0 != NULL_CELL_ID
        for root in FIELD_LIST_TEMPLATE_MEMBER_ROOTS
    )

    projected = render_view_template(
        snapshot,
        protocol,
        FIELD_LIST_TEMPLATE_ROOT,
        {
            "selected": "node-a",
            "properties": [
                {
                    "relation": "property:color",
                    "label": "color",
                    "value": "#d97757",
                    "editable": True,
                    "control": "property:color",
                    "event_fact_input": "event:submitted-value",
                },
                {
                    "relation": "property:x",
                    "label": "position_x",
                    "value": 12.5,
                    "editable": True,
                    "control": "property:x",
                    "event_fact_input": "event:submitted-value",
                },
                {
                    "relation": "property:id",
                    "label": "identity",
                    "value": "node-a",
                    "editable": False,
                },
            ],
        },
    )

    assert len(projected) == 1
    section = projected[0]
    assert section["key"] == "presenter:field-list:node-a"
    assert section["tag"] == "section"
    assert section["children"][0]["text"] == "PROPERTIES"
    rows = section["children"][1:]
    assert [row["key"] for row in rows] == [
        "property-row:property:color",
        "property-row:property:x",
        "property-row:property:id",
    ]
    assert [row["children"][0]["text"] for row in rows] == [
        "color", "position x", "identity",
    ]
    assert rows[0]["children"][1]["attributes"] == {
        "type": "color",
        "data-universal-control": "property:color",
        "data-universal-event-fact-input": "event:submitted-value",
    }
    assert rows[1]["children"][1]["attributes"] == {
        "type": "number",
        "data-universal-control": "property:x",
        "data-universal-event-fact-input": "event:submitted-value",
        "step": "any",
    }
    assert rows[2]["children"][1]["class"] == "connection-box"
    assert rows[2]["children"][1]["text"] == "node-a"

    authored = render_view_template(
        snapshot,
        protocol,
        FIELD_LIST_TEMPLATE_ROOT,
        {
            "selected": "node-a",
            "properties": [],
            "authoring": {
                "add_property": True,
                "owner": "node-a",
                "property_form": {
                    "root": "form:property",
                    "control": "control:add-property",
                    "control_label": "Add parameter",
                    "control_title": "Add parameter",
                    "control_binding": "binding:add-property",
                    "control_capability": "capability:relation-form",
                    "control_icon": "icon:plus",
                    "operation": "operation:property-create",
                    "operation_path": "/api/universal/interaction",
                    "inputs": {
                        "label": "form:property:input:label",
                        "value": "form:property:input:value",
                    },
                },
            },
        },
    )[0]
    form = authored["children"][-1]
    assert form["key"] == "property-create:node-a"
    assert form["attributes"] == {
        "data-universal-relation-form": "form:property",
        "data-universal-relation-form-operation": (
            "operation:property-create"
        ),
        "data-universal-relation-form-path": (
            "/api/universal/interaction"
        ),
    }
    assert [child["tag"] for child in form["children"]] == [
        "input", "input", "button",
    ]
    assert form["children"][0]["attributes"] == {
        "type": "text",
        "placeholder": "Parameter name",
        "aria-label": "Parameter name",
        "data-universal-relation-form-field": "label",
        "data-universal-relation-form-input": "form:property:input:label",
    }
    assert form["children"][1]["attributes"] == {
        "type": "text",
        "placeholder": "Initial value",
        "aria-label": "Initial value",
        "data-universal-relation-form-field": "value",
        "data-universal-relation-form-input": "form:property:input:value",
    }
    assert form["children"][2]["attributes"] == {
        "type": "button",
        "data-universal-relation-form-submit": "form:property",
        "data-universal-control": "control:add-property",
        "data-control-binding": "binding:add-property",
        "data-control-capability": "capability:relation-form",
        "data-control-icon": "icon:plus",
        "title": "Add parameter",
        "aria-label": "Add parameter",
    }
    assert form["children"][2]["text"] == "Add parameter"
