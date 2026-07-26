"""Courts for graph-authored visible control presentation."""
from __future__ import annotations

import inspect

import nodelang.cell_control_presentations as control_presentations
from nodelang.cell_control_presentations import (
    CONTROL_SPECS,
    ensure_archhub_control_catalog,
    project_control_catalog,
)
from nodelang.cell_icons import (
    ensure_archhub_icon_catalog,
    project_icon_assignment,
)
from nodelang.universal_cell import CellStore


def _controls():
    store = CellStore()
    icons = ensure_archhub_icon_catalog(store)
    controls = ensure_archhub_control_catalog(store, icons)
    return store, icons, controls


def test_every_admitted_visible_control_is_a_graph_composition_with_an_icon_wire():
    store, icons, built = _controls()
    projected = project_control_catalog(
        store.snapshot(), built.protocol, icons.protocol, built.catalog_root
    )
    assert set(projected.controls) == {
        specification.owner_root for specification in CONTROL_SPECS
    }
    assert len(projected.controls) == len(CONTROL_SPECS) == 15
    for owner_root, control in projected.controls.items():
        assert control.owner_root == owner_root
        assert control.label
        assert control.title
        assert control.zone in {
            "application-rail",
            "library",
            "canvas-toolbar",
            "inspector-properties",
            "inspector-interfaces",
        }
        assignment = project_icon_assignment(
            store.snapshot(), icons.protocol, control.icon_assignment_root
        )
        assert assignment.owner_root == owner_root
        assert assignment.icon_root == control.icon_root
        assert control.icon_root in icons.icon_roots.values()


def test_control_order_is_explicit_and_unique_inside_each_graph_zone():
    store, icons, built = _controls()
    controls = project_control_catalog(
        store.snapshot(), built.protocol, icons.protocol, built.catalog_root
    ).controls.values()
    zones = {}
    for control in controls:
        zones.setdefault(control.zone, []).append(control.order)
    assert all(len(orders) == len(set(orders)) for orders in zones.values())
    assert all(orders == sorted(orders) for orders in zones.values())


def test_control_projection_has_no_icon_or_product_name_dispatch():
    source = "\n".join((
        inspect.getsource(ensure_archhub_control_catalog),
        inspect.getsource(project_control_catalog),
    )).lower()
    assert "if name ==" not in source
    assert "match name" not in source
    for product_name in ("brain", "cockpit", "grand map", "bim", "session"):
        assert product_name not in source


def test_control_catalog_restore_is_idempotent():
    store, icons, first = _controls()
    before = store.revision
    second = ensure_archhub_control_catalog(store, icons)
    assert store.revision == before
    assert second.catalog_root == first.catalog_root
    assert dict(second.control_roots) == dict(first.control_roots)


def test_control_catalog_old_release_appends_missing_controls(monkeypatch):
    store = CellStore()
    icons = ensure_archhub_icon_catalog(store)
    monkeypatch.setattr(
        control_presentations, "CONTROL_SPECS", CONTROL_SPECS[:13]
    )
    old = ensure_archhub_control_catalog(store, icons)
    old_snapshot = store.snapshot()
    old_tail = old_snapshot.cells[
        "app:control-presentation-catalog:v1:chain:12"
    ]
    assert old_tail.link1 == "00000000-0000-0000-0000-000000000000"

    monkeypatch.setattr(control_presentations, "CONTROL_SPECS", CONTROL_SPECS)
    migrated = ensure_archhub_control_catalog(store, icons)
    projected = project_control_catalog(
        store.snapshot(), migrated.protocol, icons.protocol, migrated.catalog_root
    )

    assert len(projected.controls) == len(CONTROL_SPECS) == 15
    assert dict(old.control_roots).items() <= dict(migrated.control_roots).items()
    assert (
        store.snapshot().cells["app:control-presentation-catalog:v1:chain:12"]
        .link1
        == "app:control-presentation-catalog:v1:chain:13"
    )
