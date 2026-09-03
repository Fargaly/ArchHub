"""Court for structured values made only from openable Cell relations."""
import math

import pytest

from nodelang.cell_protocols import read_relation
from nodelang.cell_value_graph import (
    MAX_SCALAR_BYTES,
    bootstrap_value_graph_protocol,
    build_value_graph,
    build_value_graphs,
    prepare_value_graph,
    project_value_graph_protocol,
    read_value_graph,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


def _value():
    return {
        "gate": {
            "kind": "pytest",
            "spec": {"path": "tests/test_work.py", "args": ["-q", 3]},
        },
        "fit": ["python", "governance"],
        "enabled": True,
        "attempts": 2,
        "ratio": 0.5,
        "note": None,
        "digest": b"abc",
    }


def test_value_graph_roundtrips_without_hiding_structure_in_json(tmp_path):
    path = tmp_path / "values.sqlite3"
    store = CellStore(path)
    protocol = bootstrap_value_graph_protocol(
        store, prefix="test:value-graph"
    )
    root, revision = build_value_graph(
        store, protocol, _value(), root_id="test:work:requirements"
    )
    assert revision == store.revision
    assert read_value_graph(store.snapshot(), protocol, root) == _value()

    snapshot = store.snapshot()
    root_members = read_relation(snapshot, root, budget=10_000)
    assert any(
        member.participant_id == protocol.variant("object")
        for member in root_members
    )
    assert not any(
        cell.atom.startswith(b"{") or cell.atom.startswith(b"[")
        for cell in snapshot.cells.values()
    )
    kind_content = snapshot.cells[
        "test:work:requirements:entry:gate:value:entry:kind:value:content"
    ]
    assert kind_content.atom == b"pytest"

    store.close()
    reopened = CellStore(path)
    restored = project_value_graph_protocol(
        reopened.snapshot(), prefix="test:value-graph"
    )
    assert read_value_graph(reopened.snapshot(), restored, root) == _value()

    content_root = (
        "test:work:requirements:entry:attempts:value:content"
    )
    old = reopened.read(content_root)
    reopened.commit(
        reopened.revision,
        replace=(Cell(old.id, NULL_CELL_ID, NULL_CELL_ID, b"4"),),
    )
    changed = read_value_graph(reopened.snapshot(), restored, root)
    assert changed["attempts"] == 4
    reopened.close()


def test_value_graph_batch_registers_many_values_in_one_revision():
    store = CellStore()
    protocol = bootstrap_value_graph_protocol(store)
    before = store.revision
    roots, revision = build_value_graphs(
        store,
        protocol,
        {
            "batch:one": {"name": "one", "rank": 1},
            "batch:two": {"name": "two", "rank": 2},
            "batch:three": ["visible", "cells"],
        },
    )
    assert revision == before + 1 == store.revision
    assert roots == ("batch:one", "batch:two", "batch:three")
    assert read_value_graph(store.snapshot(), protocol, "batch:one") == {
        "name": "one",
        "rank": 1,
    }
    assert read_value_graph(store.snapshot(), protocol, "batch:two") == {
        "name": "two",
        "rank": 2,
    }
    assert read_value_graph(store.snapshot(), protocol, "batch:three") == [
        "visible",
        "cells",
    ]


def test_prepared_value_graph_joins_its_referencing_graph_in_one_commit():
    store = CellStore()
    protocol = bootstrap_value_graph_protocol(store)
    snapshot = store.snapshot()
    payload_root = "test:prepared:payload"
    prepared = prepare_value_graph(
        snapshot,
        protocol,
        {"research": "verified", "priority": 1},
        root_id=payload_root,
    )

    assert payload_root not in snapshot.cells
    revision = store.commit(
        snapshot.revision,
        create=(*prepared.create, Cell(
            "test:prepared:ledger-entry", NULL_CELL_ID, NULL_CELL_ID, b""
        )),
        replace=prepared.replace,
    )

    assert revision == snapshot.revision + 1
    assert "test:prepared:ledger-entry" in store.snapshot().cells
    assert read_value_graph(store.snapshot(), protocol, payload_root) == {
        "research": "verified", "priority": 1,
    }


def test_value_graph_rejects_opaque_or_unbounded_payloads():
    store = CellStore()
    protocol = bootstrap_value_graph_protocol(store)
    with pytest.raises(InvalidCell, match="finite"):
        build_value_graph(store, protocol, math.inf, root_id="bad:number")
    with pytest.raises(InvalidCell, match="blob reference"):
        build_value_graph(
            store,
            protocol,
            b"x" * (MAX_SCALAR_BYTES + 1),
            root_id="bad:blob",
        )
    with pytest.raises(InvalidCell, match="keys must be text"):
        build_value_graph(store, protocol, {1: "hidden"}, root_id="bad:key")
    with pytest.raises(InvalidCell, match="not admitted"):
        build_value_graph(store, protocol, {"bad": object()}, root_id="bad:type")
