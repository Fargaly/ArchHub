from __future__ import annotations

from nodelang.cell_evidence_floor_view import (
    CELL_FLOOR_PREFIX,
    CELL_FLOOR_TEMPLATE_MEMBER_ROOTS,
    CELL_FLOOR_TEMPLATE_ROOT,
    EVIDENCE_LIST_PREFIX,
    EVIDENCE_LIST_TEMPLATE_MEMBER_ROOTS,
    EVIDENCE_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_cell_floor_template,
    compose_evidence_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _descriptor(
    key: str,
    tag: str = "div",
    *,
    class_name: str = "",
    text: object | None = None,
    value: object | None = None,
    attributes: dict[str, object] | None = None,
    children: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "key": key,
        "tag": tag,
        "class": class_name,
        "attributes": attributes or {},
        "children": children or [],
    }
    if text is not None:
        result["text"] = str(text)
    if value is not None:
        result["value"] = str(value)
    return result


def _row(
    key: str,
    label: str,
    content: dict[str, object],
    *,
    tag: str = "div",
) -> dict[str, object]:
    return _descriptor(
        key,
        tag,
        class_name="property-row",
        children=[
            _descriptor(
                key + ":label",
                "span",
                class_name="property-label",
                text=label,
            ),
            content,
        ],
    )


def _composed_templates():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_evidence_list_template(batch, protocol) == (
        EVIDENCE_LIST_TEMPLATE_ROOT
    )
    assert compose_cell_floor_template(batch, protocol) == (
        CELL_FLOOR_TEMPLATE_ROOT
    )
    batch.commit()
    return store.snapshot(), protocol


def _assert_six_executable_members(snapshot, protocol, member_roots):
    assert len(member_roots) == 6
    assert len(set(member_roots)) == 6
    assert all(
        snapshot.cells[root].link0 != NULL_CELL_ID
        and is_view_template(snapshot, protocol, root)
        for root in member_roots
    )


def test_member_roots_preserve_the_six_presenter_incidences():
    assert EVIDENCE_LIST_TEMPLATE_MEMBER_ROOTS == tuple(
        EVIDENCE_LIST_PREFIX + ":" + name
        for name in ("section", "heading", "list", "row", "text", "details")
    )
    assert CELL_FLOOR_TEMPLATE_MEMBER_ROOTS == tuple(
        CELL_FLOOR_PREFIX + ":" + name
        for name in ("section", "heading", "row", "text", "control", "input")
    )


def test_evidence_list_is_graph_held_and_matches_representative_descriptor():
    snapshot, protocol = _composed_templates()

    assert is_view_template(
        snapshot, protocol, EVIDENCE_LIST_TEMPLATE_ROOT
    )
    _assert_six_executable_members(
        snapshot, protocol, EVIDENCE_LIST_TEMPLATE_MEMBER_ROOTS
    )

    projected = render_view_template(
        snapshot,
        protocol,
        EVIDENCE_LIST_TEMPLATE_ROOT,
        {
            "selected": "assembly-a",
            "selected_definition": {
                "id": "assembly-a",
                "name": "Assembly A",
                "version": "v7",
                "interfaces": 4,
                "parts": 19,
            },
        },
    )

    expected_rows = [
        _row(
            "release:assembly-a:version",
            "version",
            _descriptor(
                "release-value:assembly-a:version",
                class_name="connection-box",
                text="v7",
            ),
        ),
        _row(
            "release:assembly-a:interface-count",
            "interface count",
            _descriptor(
                "release-value:assembly-a:interface-count",
                class_name="connection-box",
                text=4,
            ),
        ),
        _row(
            "release:assembly-a:cell-count",
            "cell count",
            _descriptor(
                "release-value:assembly-a:cell-count",
                class_name="connection-box",
                text=19,
            ),
        ),
    ]
    assert projected == [
        _descriptor(
            "presenter:evidence-list:assembly-a",
            "section",
            class_name="inspector-section",
            children=[
                _descriptor(
                    "release:heading",
                    class_name="inspector-heading",
                    text="RELEASE",
                ),
                *expected_rows,
            ],
        )
    ]
    assert render_view_template(
        snapshot,
        protocol,
        EVIDENCE_LIST_TEMPLATE_ROOT,
        {"selected": "assembly-a", "selected_definition": None},
    ) == []


def test_cell_floor_is_graph_held_and_matches_editable_descriptor():
    snapshot, protocol = _composed_templates()

    assert is_view_template(snapshot, protocol, CELL_FLOOR_TEMPLATE_ROOT)
    _assert_six_executable_members(
        snapshot, protocol, CELL_FLOOR_TEMPLATE_MEMBER_ROOTS
    )

    projected = render_view_template(
        snapshot,
        protocol,
        CELL_FLOOR_TEMPLATE_ROOT,
        {
            "physical": {
                "identity": "cell-a",
                "link0": "left-a",
                "link1": "right-a",
                "atom": "payload",
                "editable": True,
                "control": "property-a",
                "event_fact_input": "event-fact-a",
            },
        },
    )

    assert projected == [_expected_floor(
        atom_content=_descriptor(
            "floor-atom-input:cell-a",
            "input",
            class_name="property-input",
            value="payload",
            attributes={
                "type": "text",
                "data-universal-control": "property-a",
                "data-universal-event-fact-input": "event-fact-a",
            },
        )
    )]


def test_cell_floor_matches_read_only_empty_atom_descriptor():
    snapshot, protocol = _composed_templates()
    projected = render_view_template(
        snapshot,
        protocol,
        CELL_FLOOR_TEMPLATE_ROOT,
        {
            "physical": {
                "identity": "cell-a",
                "link0": "left-a",
                "link1": "right-a",
                "atom": "",
                "editable": False,
            },
        },
    )

    assert projected == [_expected_floor(
        atom_content=_descriptor(
            "floor-atom-value:cell-a",
            class_name="connection-box",
            text="empty",
        )
    )]


def _expected_floor(*, atom_content: dict[str, object]) -> dict[str, object]:
    return _descriptor(
        "presenter:cell-floor:cell-a",
        "details",
        class_name="inspector-section",
        children=[
            _descriptor(
                "floor-summary:cell-a",
                "summary",
                class_name="inspector-heading",
                text="PHYSICAL FLOOR",
            ),
            _row(
                "floor:cell-a:identity",
                "identity",
                _descriptor(
                    "floor-value:cell-a:identity",
                    class_name="connection-box",
                    text="cell-a",
                ),
            ),
            _row(
                "floor:cell-a:link-0",
                "link 0",
                _descriptor(
                    "floor-value:cell-a:link-0",
                    class_name="connection-box",
                    text="left-a",
                ),
            ),
            _row(
                "floor:cell-a:link-1",
                "link 1",
                _descriptor(
                    "floor-value:cell-a:link-1",
                    class_name="connection-box",
                    text="right-a",
                ),
            ),
            _row(
                "floor-atom:cell-a",
                "atom",
                atom_content,
                tag="label",
            ),
        ],
    )
