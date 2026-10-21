from __future__ import annotations

import pytest

from nodelang.cell_control_view import (
    CONTROL_LIST_TEMPLATE_MEMBER_ROOTS,
    CONTROL_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_control_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    OPERATION_NAMES,
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _controls
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    instantiate_universal_definition,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _control_template():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_control_list_template(batch, protocol) == (
        CONTROL_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _render(projection):
    store, protocol = _control_template()
    try:
        return render_view_template(
            store.snapshot(),
            protocol,
            CONTROL_LIST_TEMPLATE_ROOT,
            projection,
            budget=750_000,
        )
    finally:
        store.close()


def _assert_exact_parity(projection):
    assert _render(projection) == _controls(projection)


REPRESENTATIVE_PROJECTION = {
    "selected": "assembly:controlled",
    "selected_assembly": {
        "status": [
            {"id": "status:ready", "label": "status", "value": "READY"},
            {"id": "status:false", "label": "flag", "value": False},
        ],
        "errors": [
            {"id": "error:count", "label": "error", "value": 0},
        ],
        "operational": {
            "current_state": "state:pending",
            "current_state_label": "PENDING",
            "admitted_transitions": [
                {
                    "event": "event:approve",
                    "event_label": "approve",
                    "to_state_label": "APPROVED",
                    "required_evidence_types": [
                        {"root": "evidence:decision", "label": "user decision"},
                    ],
                    "user_decision": True,
                    "adapter_execute": False,
                    "control": "control:approve",
                },
                {
                    "event": "event:execute",
                    "event_label": "execute",
                    "to_state_label": "RUNNING",
                    "required_evidence_types": [
                        {
                            "root": "evidence:admission",
                            "label": "execution admission",
                        },
                    ],
                    "user_decision": False,
                    "adapter_execute": True,
                },
                {
                    "event": "event:confirm",
                    "event_label": "confirm",
                    "to_state_label": "SETTLED",
                    "required_evidence_types": [
                        {
                            "root": "evidence:receipt",
                            "label": "provider \"receipt\"",
                        },
                        {
                            "root": "evidence:reconciliation",
                            "label": "reconciliation\nproof \u0394",
                        },
                    ],
                    "user_decision": False,
                    "adapter_execute": False,
                },
                {
                    "event": "event:cancel",
                    "event_label": "cancel",
                    "to_state_label": "CANCELLED",
                    "required_evidence_types": [],
                    "user_decision": False,
                    "adapter_execute": False,
                    "control": "control:cancel",
                },
            ],
            "history": [
                {
                    "event_label": "submit",
                    "from_state_label": "DRAFT",
                    "to_state_label": "PENDING",
                    "evidence": ["evidence:submission"],
                },
                {
                    "event_label": "retry",
                    "from_state_label": "FAILED",
                    "to_state_label": "PENDING",
                },
            ],
        },
    },
}


def test_control_list_uses_the_required_generic_bounded_join_operation():
    assert "join" in OPERATION_NAMES, (
        "exact control-list parity requires generic join(collection, separator); "
        "JSON formatting or presenter preprocessing is not equivalent"
    )


def test_control_list_has_nine_ordered_incidences_and_eight_roots():
    store, protocol = _control_template()
    try:
        snapshot = store.snapshot()
        assert len(CONTROL_LIST_TEMPLATE_MEMBER_ROOTS) == 9
        assert len(set(CONTROL_LIST_TEMPLATE_MEMBER_ROOTS)) == 8
        assert CONTROL_LIST_TEMPLATE_MEMBER_ROOTS[0] == (
            CONTROL_LIST_TEMPLATE_ROOT
        )
        assert CONTROL_LIST_TEMPLATE_MEMBER_ROOTS[5] == (
            CONTROL_LIST_TEMPLATE_MEMBER_ROOTS[8]
        )
        assert all(
            is_view_template(snapshot, protocol, root)
            for root in set(CONTROL_LIST_TEMPLATE_MEMBER_ROOTS)
        )
        assert all(
            snapshot.cells[root].link0 != NULL_CELL_ID
            for root in set(CONTROL_LIST_TEMPLATE_MEMBER_ROOTS)
        )
    finally:
        store.close()


def test_control_list_has_exact_representative_legacy_parity():
    _assert_exact_parity(REPRESENTATIVE_PROJECTION)


@pytest.mark.parametrize(
    "projection",
    (
        {"selected": "none", "selected_assembly": None},
        {"selected": "empty", "selected_assembly": {}},
        {
            "selected": "state-only",
            "selected_assembly": {
                "status": [
                    {"id": "status:one", "label": "status", "value": "OK"}
                ],
                "errors": [],
                "operational": None,
            },
        },
        {
            "selected": "operational-only",
            "selected_assembly": {
                "status": [],
                "errors": [],
                "operational": {
                    "current_state": "state:idle",
                    "current_state_label": "IDLE",
                },
            },
        },
    ),
    ids=("absent", "empty", "state-only", "operational-only"),
)
def test_control_list_empty_and_partial_raw_projections_have_exact_parity(
    projection,
):
    _assert_exact_parity(projection)


def test_live_universal_application_states_have_exact_legacy_parity():
    store, registry = build_universal_application(resolve_map_path())
    try:
        initial = project_universal_canvas(store, registry)
        _assert_exact_parity(initial)

        definition = next(
            item["id"] for item in initial["catalog"]
            if item["name"] == "Permission Request"
        )
        instantiate_universal_definition(
            store, registry, definition, x=420, y=180
        )
        selected = project_universal_canvas(store, registry)
        assert selected["selected_assembly"]["operational"] is not None
        assert selected["selected_assembly"]["operational"][
            "admitted_transitions"
        ]
        _assert_exact_parity(selected)
    finally:
        store.close()
