"""Courts for graph-held control activation and applicability."""
from __future__ import annotations

import inspect

import pytest

import nodelang.cell_control_bindings as control_bindings
import nodelang.cell_control_presentations as control_presentations
from nodelang.cell_control_bindings import (
    CONTROL_BINDING_SPECS,
    CAPABILITY_RELATION_FORM,
    FACT_FOCUS_COMPOSITION,
    FACT_SCOPE_PARENT,
    FACT_SELECTION_COUNT,
    ensure_archhub_control_binding_catalog,
    evaluate_control_condition,
    project_control_binding_catalog,
)
from nodelang.cell_control_presentations import (
    CONTROL_SPECS as CONTROL_PRESENTATION_SPECS,
    ensure_archhub_control_catalog,
)
from nodelang.cell_icons import ensure_archhub_icon_catalog
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _bindings():
    store = CellStore()
    icons = ensure_archhub_icon_catalog(store)
    controls = ensure_archhub_control_catalog(store, icons)
    bindings = ensure_archhub_control_binding_catalog(store, controls)
    projected = project_control_binding_catalog(
        store.snapshot(), bindings.protocol, bindings.catalog_root
    )
    return store, controls, bindings, projected


def test_every_visible_control_has_one_openable_activation_and_condition():
    store, controls, _built, projected = _bindings()
    assert set(projected.bindings) == set(controls.control_roots)
    assert len(projected.bindings) == len(CONTROL_BINDING_SPECS) == 15
    for owner_root, binding in projected.bindings.items():
        assert binding.control_root == owner_root
        assert binding.capability_root in store.snapshot().cells
        assert binding.condition_root in store.snapshot().cells
        assert binding.activation_root in store.snapshot().cells
        assert all(key and value for key, value in binding.arguments.items())


@pytest.mark.parametrize(
    ("owner", "facts", "expected"),
    (
        ("app:control:canvas:scope-up", {
            FACT_SCOPE_PARENT: False,
            FACT_SELECTION_COUNT: 1,
            FACT_FOCUS_COMPOSITION: False,
        }, False),
        ("app:control:canvas:scope-up", {
            FACT_SCOPE_PARENT: True,
            FACT_SELECTION_COUNT: 1,
            FACT_FOCUS_COMPOSITION: False,
        }, True),
        ("app:control:canvas:group", {
            FACT_SCOPE_PARENT: False,
            FACT_SELECTION_COUNT: 2,
            FACT_FOCUS_COMPOSITION: False,
        }, True),
        ("app:control:canvas:ungroup", {
            FACT_SCOPE_PARENT: False,
            FACT_SELECTION_COUNT: 1,
            FACT_FOCUS_COMPOSITION: True,
        }, True),
        ("app:control:canvas:ungroup", {
            FACT_SCOPE_PARENT: False,
            FACT_SELECTION_COUNT: 2,
            FACT_FOCUS_COMPOSITION: True,
        }, False),
    ),
)
def test_applicability_is_evaluated_from_generic_graph_expression(
    owner, facts, expected
):
    store, _controls, built, projected = _bindings()
    assert evaluate_control_condition(
        store.snapshot(), built.protocol,
        projected.bindings[owner].condition_root, facts,
    ) is expected


def test_unknown_capability_and_missing_fact_fail_closed():
    store, _controls, built, projected = _bindings()
    condition = projected.bindings["app:control:canvas:scope-up"].condition_root
    with pytest.raises(InvalidCell, match="fact"):
        evaluate_control_condition(store.snapshot(), built.protocol, condition, {})


def test_binding_projection_has_no_control_or_product_name_dispatch():
    source = "\n".join((
        inspect.getsource(project_control_binding_catalog),
        inspect.getsource(evaluate_control_condition),
    )).lower()
    assert "app:control:" not in source
    assert "if owner" not in source
    assert "match owner" not in source
    for product_name in ("brain", "cockpit", "grand map", "bim", "session"):
        assert product_name not in source


def test_binding_catalog_restore_is_idempotent():
    store, controls, first, _projected = _bindings()
    before = store.revision
    second = ensure_archhub_control_binding_catalog(store, controls)
    assert store.revision == before
    assert second.catalog_root == first.catalog_root
    assert dict(second.binding_roots) == dict(first.binding_roots)


def test_binding_catalog_old_release_appends_protocol_and_bindings(monkeypatch):
    store = CellStore()
    icons = ensure_archhub_icon_catalog(store)
    monkeypatch.setattr(
        control_presentations,
        "CONTROL_SPECS",
        CONTROL_PRESENTATION_SPECS[:13],
    )
    controls = ensure_archhub_control_catalog(store, icons)
    monkeypatch.setattr(
        control_bindings, "CONTROL_BINDING_SPECS", CONTROL_BINDING_SPECS[:13]
    )
    monkeypatch.setattr(
        control_bindings, "PROTOCOL_ADDED_CAPABILITY_ORDER", ()
    )
    old = ensure_archhub_control_binding_catalog(store, controls)
    old_snapshot = store.snapshot()
    assert len(read_relation(old_snapshot, old.catalog_root, budget=128)) == 13
    assert all(
        member.participant_id != CAPABILITY_RELATION_FORM
        for member in read_relation(
            old_snapshot, old.protocol.root_id, budget=128
        )
    )

    monkeypatch.setattr(
        control_presentations,
        "CONTROL_SPECS",
        CONTROL_PRESENTATION_SPECS,
    )
    controls = ensure_archhub_control_catalog(store, icons)
    monkeypatch.setattr(
        control_bindings, "CONTROL_BINDING_SPECS", CONTROL_BINDING_SPECS
    )
    monkeypatch.setattr(
        control_bindings, "PROTOCOL_ADDED_CAPABILITY_ORDER",
        ("relation-form",),
    )
    migrated = ensure_archhub_control_binding_catalog(store, controls)
    projected = project_control_binding_catalog(
        store.snapshot(), migrated.protocol, migrated.catalog_root
    )

    assert len(projected.bindings) == len(CONTROL_BINDING_SPECS) == 15
    assert dict(old.binding_roots).items() <= dict(migrated.binding_roots).items()
    assert any(
        member.participant_id == CAPABILITY_RELATION_FORM
        for member in read_relation(
            store.snapshot(), migrated.protocol.root_id, budget=128
        )
    )


def test_binding_catalog_upgrades_relation_form_targets_to_v3():
    store, controls, _first, _projected = _bindings()
    downgraded = (
        (
            "app:control-binding:inspector:add-property:activation:argument:0:value",
            b"app:relation-form:property:v1",
        ),
        (
            "app:control-binding:inspector:add-interface:activation:argument:0:value",
            b"app:relation-form:interface:v1",
        ),
    )
    store.commit(
        store.revision,
        replace=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
            for root, atom in downgraded
        ),
    )

    ensure_archhub_control_binding_catalog(store, controls)

    assert store.snapshot().cells[
        "app:control-binding:inspector:add-property:activation:argument:0:value"
    ].atom == b"app:relation-form:property:v3"
    assert store.snapshot().cells[
        "app:control-binding:inspector:add-interface:activation:argument:0:value"
    ].atom == b"app:relation-form:interface:v3"
