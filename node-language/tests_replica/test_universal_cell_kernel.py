"""Forcing court for the parallel universal-cell physical kernel.

These tests deliberately do not import the legacy ``nodelang.core`` shape. The
old runtime remains migration authority while this court proves a smaller floor.
"""
from dataclasses import fields
import ast
import inspect
from collections.abc import Mapping

import pytest

from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    MatchBudgetExceeded,
)


def test_every_persisted_cell_has_one_nonsemantic_shape():
    assert [field.name for field in fields(Cell)] == [
        "id", "link0", "link1", "atom"
    ]
    forbidden = {
        "kind", "type", "role", "params", "body", "relations", "meta",
        "children", "ports", "operation", "source", "target",
    }
    assert not (forbidden & {field.name for field in fields(Cell)})


def test_null_and_ordinary_cells_use_the_exact_same_shape():
    store = CellStore()
    null = store.read(NULL_CELL_ID)
    root = Cell("root", NULL_CELL_ID, NULL_CELL_ID, b"opaque")
    store.commit(store.revision, create=[root])
    assert type(null) is Cell
    assert type(store.read("root")) is Cell


def test_atom_is_opaque_to_the_kernel_and_never_drives_dispatch():
    tree = ast.parse(inspect.getsource(__import__(
        "nodelang.universal_cell", fromlist=["*"]
    )))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"decode", "loads"}:
            violations.append((node.lineno, node.attr))
        if isinstance(node, ast.Compare):
            rendered = ast.unparse(node)
            if ".atom" in rendered or "atom[" in rendered:
                violations.append((node.lineno, rendered))
    assert violations == []


def test_commit_is_atomic_and_rejects_dangling_incidence():
    store = CellStore()
    before = store.snapshot()
    bad = Cell("bad", "missing", NULL_CELL_ID, b"")
    with pytest.raises(InvalidCell):
        store.commit(store.revision, create=[bad])
    assert store.snapshot() == before


def test_optimistic_revision_conflict_cannot_overwrite_concurrent_work():
    store = CellStore()
    observed = store.revision
    store.commit(observed, create=[
        Cell("a", NULL_CELL_ID, NULL_CELL_ID, b"a")
    ])
    with pytest.raises(Conflict):
        store.commit(observed, create=[
            Cell("b", NULL_CELL_ID, NULL_CELL_ID, b"b")
        ])
    assert "a" in store.snapshot().cells
    assert "b" not in store.snapshot().cells


def test_replace_preserves_identity_and_history_without_partial_state():
    store = CellStore()
    store.commit(store.revision, create=[
        Cell("root", NULL_CELL_ID, NULL_CELL_ID, b"before")
    ])
    first_revision = store.revision
    store.commit(first_revision, replace=[
        Cell("root", NULL_CELL_ID, NULL_CELL_ID, b"after")
    ])
    assert store.read("root").id == "root"
    assert store.read("root").atom == b"after"
    assert store.at(first_revision).cells["root"].atom == b"before"
    assert store.at(store.revision).cells["root"].atom == b"after"


def test_semantic_side_tables_are_forbidden():
    store = CellStore()
    forbidden = {
        "kinds", "roles", "relations", "edges", "groups", "ports",
        "parameters", "ui_bindings", "operations", "children",
    }
    assert not (forbidden & set(vars(store)))


def _relation_fixture():
    null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
    cells = {
        NULL_CELL_ID: null,
        "owner": Cell("owner", NULL_CELL_ID, NULL_CELL_ID, b"wall-panel"),
        "value": Cell("value", NULL_CELL_ID, NULL_CELL_ID, b"terracotta"),
        "owner-role": Cell(
            "owner-role", NULL_CELL_ID, NULL_CELL_ID, b"owner-role"
        ),
        "value-role": Cell(
            "value-role", NULL_CELL_ID, NULL_CELL_ID, b"value-role"
        ),
        "owner-incidence": Cell(
            "owner-incidence", "owner-role", "owner", b""
        ),
        "value-incidence": Cell(
            "value-incidence", "value-role", "value", b""
        ),
        "property-relation": Cell(
            "property-relation", "owner-incidence", "value-incidence", b""
        ),
    }
    return cells


def _relation_pattern():
    return {
        NULL_CELL_ID: Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b""),
        "p-owner-role": Cell(
            "p-owner-role", NULL_CELL_ID, NULL_CELL_ID, b"owner-role"
        ),
        "p-value-role": Cell(
            "p-value-role", NULL_CELL_ID, NULL_CELL_ID, b"value-role"
        ),
        "owner-var": Cell("owner-var", NULL_CELL_ID, NULL_CELL_ID, b""),
        "value-var": Cell("value-var", NULL_CELL_ID, NULL_CELL_ID, b""),
        "p-owner-incidence": Cell(
            "p-owner-incidence", "p-owner-role", "owner-var", b""
        ),
        "p-value-incidence": Cell(
            "p-value-incidence", "p-value-role", "value-var", b""
        ),
        "p-relation": Cell(
            "p-relation", "p-owner-incidence", "p-value-incidence", b""
        ),
    }


def test_generic_matcher_recognizes_protocol_shape_without_semantic_dispatch():
    store = CellStore()
    fixture = _relation_fixture()
    store.commit(
        store.revision,
        create=[cell for key, cell in fixture.items() if key != NULL_CELL_ID],
    )
    bindings = store.match(
        _relation_pattern(),
        pattern_root="p-relation",
        target_root="property-relation",
        variables={"owner-var", "value-var"},
        budget=64,
    )
    assert bindings == {"owner-var": "owner", "value-var": "value"}


def test_relation_can_target_another_relation_without_a_new_record_type():
    store = CellStore()
    fixture = _relation_fixture()
    extra = {
        "subject-role": Cell(
            "subject-role", NULL_CELL_ID, NULL_CELL_ID, b"subject-role"
        ),
        "policy-role": Cell(
            "policy-role", NULL_CELL_ID, NULL_CELL_ID, b"policy-role"
        ),
        "policy": Cell("policy", NULL_CELL_ID, NULL_CELL_ID, b"founder-only"),
        "subject-incidence": Cell(
            "subject-incidence", "subject-role", "property-relation", b""
        ),
        "policy-incidence": Cell(
            "policy-incidence", "policy-role", "policy", b""
        ),
        "policy-relation": Cell(
            "policy-relation", "subject-incidence", "policy-incidence", b""
        ),
    }
    store.commit(
        store.revision,
        create=[
            cell
            for key, cell in (fixture | extra).items()
            if key != NULL_CELL_ID
        ],
    )
    pattern = _relation_pattern()
    pattern["p-owner-role"] = Cell(
        "p-owner-role", NULL_CELL_ID, NULL_CELL_ID, b"subject-role"
    )
    pattern["p-value-role"] = Cell(
        "p-value-role", NULL_CELL_ID, NULL_CELL_ID, b"policy-role"
    )
    bindings = store.match(
        pattern,
        pattern_root="p-relation",
        target_root="policy-relation",
        variables={"owner-var", "value-var"},
        budget=64,
    )
    assert bindings["owner-var"] == "property-relation"
    assert type(store.read(bindings["owner-var"])) is Cell


def test_match_budget_is_enforced_instead_of_hanging_on_graphs():
    store = CellStore()
    fixture = _relation_fixture()
    store.commit(
        store.revision,
        create=[cell for key, cell in fixture.items() if key != NULL_CELL_ID],
    )
    with pytest.raises(MatchBudgetExceeded):
        store.match(
            _relation_pattern(),
            pattern_root="p-relation",
            target_root="property-relation",
            variables={"owner-var", "value-var"},
            budget=1,
        )


def test_stored_rewrite_walks_its_rule_region_without_scanning_the_host():
    class NoIterationMapping(Mapping):
        def __init__(self, source):
            self._source = source

        def __getitem__(self, key):
            return self._source[key]

        def __len__(self):
            return len(self._source)

        def __iter__(self):
            raise AssertionError("stored rewrite scanned the complete host graph")

    store = CellStore()
    store.commit(
        store.revision,
        create=[
            Cell("p-left", NULL_CELL_ID, NULL_CELL_ID, b""),
            Cell("p-right", NULL_CELL_ID, NULL_CELL_ID, b""),
            Cell("p-pair", "p-left", "p-right", b"pair"),
            Cell("r-left", NULL_CELL_ID, NULL_CELL_ID, b""),
            Cell("r-right", NULL_CELL_ID, NULL_CELL_ID, b""),
            Cell("r-pair", "r-right", "r-left", b"pair"),
            Cell("left", NULL_CELL_ID, NULL_CELL_ID, b"A"),
            Cell("right", NULL_CELL_ID, NULL_CELL_ID, b"B"),
            Cell("target", "left", "right", b"pair"),
        ],
    )
    store._cells = NoIterationMapping(store._cells)

    prepared = store.prepare_rewrite(
        expected_revision=store.revision,
        pattern_root="p-pair",
        target_root="target",
        pattern_variables={"p-left", "p-right"},
        replacement_root="r-pair",
        replacement_variables={
            "r-left": "p-left",
            "r-right": "p-right",
        },
        budget=64,
    )

    assert prepared.replace == (Cell(
        "target", "right", "left", b"pair"
    ),)


def test_external_pattern_still_validates_unreachable_cells_exhaustively():
    store = CellStore()
    store.commit(store.revision, create=(Cell(
        "target", NULL_CELL_ID, NULL_CELL_ID, b"target"
    ),))
    external = {
        NULL_CELL_ID: Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b""),
        "pattern": Cell("pattern", NULL_CELL_ID, NULL_CELL_ID, b"target"),
        "unreachable": Cell("unreachable", "missing", NULL_CELL_ID, b""),
    }

    with pytest.raises(InvalidCell, match="dangling link"):
        store.match(
            external,
            pattern_root="pattern",
            target_root="target",
            budget=16,
        )


def _swap_rule_cells():
    return {
        "p-left": Cell("p-left", NULL_CELL_ID, NULL_CELL_ID, b""),
        "p-right": Cell("p-right", NULL_CELL_ID, NULL_CELL_ID, b""),
        "p-swap": Cell("p-swap", "p-left", "p-right", b"pair"),
        "r-left": Cell("r-left", NULL_CELL_ID, NULL_CELL_ID, b""),
        "r-right": Cell("r-right", NULL_CELL_ID, NULL_CELL_ID, b""),
        "r-swap": Cell("r-swap", "r-right", "r-left", b"pair"),
    }


def test_rewrite_rule_is_stored_as_cells_and_changes_graph_atomically():
    store = CellStore()
    target = [
        Cell("left", NULL_CELL_ID, NULL_CELL_ID, b"A"),
        Cell("right", NULL_CELL_ID, NULL_CELL_ID, b"B"),
        Cell("target", "left", "right", b"pair"),
    ]
    rules = list(_swap_rule_cells().values())
    store.commit(store.revision, create=target + rules)
    result = store.rewrite(
        expected_revision=store.revision,
        pattern_root="p-swap",
        target_root="target",
        pattern_variables={"p-left", "p-right"},
        replacement_root="r-swap",
        replacement_variables={"r-left": "p-left", "r-right": "p-right"},
        budget=64,
    )
    assert result.root_id == "target"
    assert store.read("target") == Cell("target", "right", "left", b"pair")
    assert store.at(result.revision - 1).cells["target"].link0 == "left"


def test_editing_the_rule_cells_changes_later_execution():
    store = CellStore()
    targets = [
        Cell("a1", NULL_CELL_ID, NULL_CELL_ID, b"A"),
        Cell("b1", NULL_CELL_ID, NULL_CELL_ID, b"B"),
        Cell("target1", "a1", "b1", b"pair"),
        Cell("a2", NULL_CELL_ID, NULL_CELL_ID, b"A"),
        Cell("b2", NULL_CELL_ID, NULL_CELL_ID, b"B"),
        Cell("target2", "a2", "b2", b"pair"),
    ]
    store.commit(
        store.revision,
        create=targets + list(_swap_rule_cells().values()),
    )
    store.rewrite(
        expected_revision=store.revision,
        pattern_root="p-swap",
        target_root="target1",
        pattern_variables={"p-left", "p-right"},
        replacement_root="r-swap",
        replacement_variables={"r-left": "p-left", "r-right": "p-right"},
        budget=64,
    )
    assert store.read("target1").link0 == "b1"

    store.commit(
        store.revision,
        replace=[Cell("r-swap", "r-left", "r-right", b"pair")],
    )
    store.rewrite(
        expected_revision=store.revision,
        pattern_root="p-swap",
        target_root="target2",
        pattern_variables={"p-left", "p-right"},
        replacement_root="r-swap",
        replacement_variables={"r-left": "p-left", "r-right": "p-right"},
        budget=64,
    )
    assert store.read("target2").link0 == "a2"
    assert store.read("target2").link1 == "b2"
