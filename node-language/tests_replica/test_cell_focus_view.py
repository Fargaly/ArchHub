from __future__ import annotations

import pytest

from nodelang.cell_focus_view import (
    FOCUS_LIST_TEMPLATE_MEMBER_ROOTS,
    FOCUS_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_focus_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _focus
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _project(projection):
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    root = compose_focus_list_template(batch, protocol)
    batch.commit()
    return (
        store,
        protocol,
        root,
        render_view_template(
            store.snapshot(), protocol, root, projection
        ),
    )


def _descriptor(items, key):
    for item in items:
        if item["key"] == key:
            return item
        found = _descriptor(item.get("children", ()), key)
        if found is not None:
            return found
    return None


def test_focus_list_is_a_persisted_executable_graph_assembly():
    projection = {
        "focus": {
            "root": "focus:current",
            "origin": "user",
            "state": "active",
            "created_at": "2026-07-16T08:30:00+00:00",
            "reasons": [],
        },
        "obligations": [],
    }
    store, protocol, root, projected = _project(projection)
    snapshot = store.snapshot()

    assert root == FOCUS_LIST_TEMPLATE_ROOT
    assert len(FOCUS_LIST_TEMPLATE_MEMBER_ROOTS) == 6
    assert len(set(FOCUS_LIST_TEMPLATE_MEMBER_ROOTS)) == 6
    assert is_view_template(snapshot, protocol, root)
    assert all(
        is_view_template(snapshot, protocol, member_root)
        for member_root in FOCUS_LIST_TEMPLATE_MEMBER_ROOTS
    )
    assert all(
        snapshot.cells[member_root].link0 != NULL_CELL_ID
        for member_root in FOCUS_LIST_TEMPLATE_MEMBER_ROOTS
    )
    assert projected[0]["key"] == "presenter:focus-list:focus:current"


@pytest.mark.parametrize(
    "projection",
    (
        {
            "focus": {
                "root": "focus:initial",
                "origin": "bootstrap",
                "state": "active",
                "created_at": "2026-07-16T08:30:00+00:00",
                "reasons": [],
            },
            "obligations": [],
        },
        {
            "focus": {
                "root": "focus:current",
                "origin": "user",
                "state": "interrupted",
                "created_at": "2026-07-16T09:15:00+00:00",
                "reasons": [
                    {"root": "reason:selection", "label": "User selection"},
                    {"root": "reason:court", "label": "Failed active court"},
                ],
                "previous": "focus:previous",
            },
            "obligations": [],
        },
    ),
)
def test_focus_list_matches_legacy_behavior_where_protocol_is_expressive(
    projection,
):
    _store, _protocol, _root, projected = _project(projection)

    assert projected == _focus(projection)


def test_obligation_projection_matches_legacy_filtered_count_exactly():
    projection = {
        "focus": {
            "root": "focus:current",
            "origin": "user",
            "state": "active",
            "created_at": "2026-07-16T09:15:00+00:00",
            "reasons": [
                {"root": "reason:selection", "label": "User selection"},
            ],
            "previous": "focus:previous",
        },
        "obligations": [
            {
                "root": "obligation:open",
                "label": "Repair failed court",
                "priority_label": "blocking",
                "state": "open",
            },
            {
                "root": "obligation:resolved",
                "label": "Record authority",
                "priority_label": "normal",
                "state": "resolved",
            },
        ],
    }
    _store, _protocol, _root, projected = _project(projection)
    assert projected == _focus(projection)
    heading = _descriptor(
        projected, "focus:obligations-summary:focus:current"
    )
    assert heading is not None
    assert heading["text"] == "OPEN OBLIGATIONS / 1"
