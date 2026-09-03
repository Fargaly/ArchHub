from __future__ import annotations

import pytest

from nodelang.cell_event_facts import (
    bootstrap_event_fact_protocol,
    build_event_fact_spec,
    read_event_fact_spec,
    validate_event_fact_values,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell


def _released_xy_contract():
    store = CellStore()
    protocol = bootstrap_event_fact_protocol(
        store, prefix="test:event-fact-protocol"
    )
    x = build_event_fact_spec(
        store,
        protocol,
        spec_id="test:event-fact:x",
        key="x",
        source="canvas-point-x",
        minimum=0,
        maximum=1_000_000,
    )
    y = build_event_fact_spec(
        store,
        protocol,
        spec_id="test:event-fact:y",
        key="y",
        source="canvas-point-y",
        minimum=0,
        maximum=1_000_000,
    )
    return store, protocol, x, y


def test_released_event_facts_admit_only_exact_bounded_numeric_inputs():
    store, protocol, x, y = _released_xy_contract()
    values = validate_event_fact_values(
        store.snapshot(),
        protocol,
        (x.root_id, y.root_id),
        [
            {"input": y.root_id, "value": 245.5},
            {"input": x.root_id, "value": 120},
        ],
    )
    assert dict(values) == {"x": 120.0, "y": 245.5}

    rejected = (
        [{"input": x.root_id, "value": 1}],
        [
            {"input": x.root_id, "value": 1},
            {"input": x.root_id, "value": 2},
            {"input": y.root_id, "value": 3},
        ],
        [
            {"input": x.root_id, "value": float("nan")},
            {"input": y.root_id, "value": 3},
        ],
        [
            {"input": x.root_id, "value": -1},
            {"input": y.root_id, "value": 3},
        ],
        [
            {"input": x.root_id, "value": "1"},
            {"input": y.root_id, "value": 3},
        ],
    )
    for payload in rejected:
        with pytest.raises(InvalidCell):
            validate_event_fact_values(
                store.snapshot(), protocol, (x.root_id, y.root_id), payload
            )


def test_optional_event_fact_may_be_absent_but_is_bounded_when_present():
    store, protocol, x, y = _released_xy_contract()
    zoom = build_event_fact_spec(
        store,
        protocol,
        spec_id="test:event-fact:zoom",
        key="zoom",
        source="canvas-viewport-zoom",
        minimum=0.1,
        maximum=4.0,
        required=False,
    )
    required_only = validate_event_fact_values(
        store.snapshot(),
        protocol,
        (x.root_id, y.root_id, zoom.root_id),
        [
            {"input": x.root_id, "value": 1},
            {"input": y.root_id, "value": 2},
        ],
    )
    assert dict(required_only) == {"x": 1.0, "y": 2.0}
    with pytest.raises(InvalidCell, match="outside its released bounds"):
        validate_event_fact_values(
            store.snapshot(),
            protocol,
            (x.root_id, y.root_id, zoom.root_id),
            [
                {"input": x.root_id, "value": 1},
                {"input": y.root_id, "value": 2},
                {"input": zoom.root_id, "value": 5},
            ],
        )


def test_released_event_fact_digest_rejects_graph_rewiring():
    store, protocol, x, _y = _released_xy_contract()
    before = store.snapshot()
    minimum = before.cells[x.root_id + ":minimum"]
    store.commit(before.revision, replace=(Cell(
        minimum.id, minimum.link0, minimum.link1, b"-100"
    ),))
    with pytest.raises(InvalidCell, match="digest drifted"):
        read_event_fact_spec(store.snapshot(), protocol, x.root_id)


def test_released_submitted_text_is_utf8_byte_bounded_and_typed():
    store = CellStore()
    protocol = bootstrap_event_fact_protocol(
        store, prefix="test:submitted-event-fact-protocol"
    )
    submitted = build_event_fact_spec(
        store,
        protocol,
        spec_id="test:event-fact:submitted-label",
        key="value",
        source="submitted",
        value_kind="text",
        maximum_bytes=8,
    )
    values = validate_event_fact_values(
        store.snapshot(),
        protocol,
        (submitted.root_id,),
        [{"input": submitted.root_id, "value": "Room A"}],
    )
    assert dict(values) == {"value": "Room A"}

    rejected = (
        [{"input": submitted.root_id, "value": ""}],
        [{"input": submitted.root_id, "value": "123456789"}],
        [{"input": submitted.root_id, "value": 7}],
    )
    for payload in rejected:
        with pytest.raises(InvalidCell):
            validate_event_fact_values(
                store.snapshot(), protocol, (submitted.root_id,), payload
            )


def test_optional_submitted_text_may_be_empty_but_not_oversized():
    store = CellStore()
    protocol = bootstrap_event_fact_protocol(
        store, prefix="test:optional-submitted-event-fact-protocol"
    )
    submitted = build_event_fact_spec(
        store,
        protocol,
        spec_id="test:event-fact:optional-text",
        key="value",
        source="submitted",
        value_kind="text",
        maximum_bytes=4,
        required=False,
    )
    values = validate_event_fact_values(
        store.snapshot(),
        protocol,
        (submitted.root_id,),
        [{"input": submitted.root_id, "value": ""}],
    )
    assert dict(values) == {"value": ""}
    with pytest.raises(InvalidCell, match="exceeds its released bound"):
        validate_event_fact_values(
            store.snapshot(),
            protocol,
            (submitted.root_id,),
            [{"input": submitted.root_id, "value": "abcde"}],
        )
