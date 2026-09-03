"""Courts for Cell-native icon geometry, provenance, and assignment."""
from __future__ import annotations

import inspect

import pytest

from nodelang.cell_icons import (
    LUCIDE_VERSION,
    assign_icon,
    ensure_archhub_icon_catalog,
    project_icon,
    project_icon_assignment,
    project_icon_catalog,
)
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _catalog():
    store = CellStore()
    built = ensure_archhub_icon_catalog(store)
    return store, built


def test_lucide_source_is_imported_as_cells_without_markup_or_json_atoms():
    store, built = _catalog()
    snapshot = store.snapshot()
    catalog = project_icon_catalog(snapshot, built.protocol, built.catalog_root)
    assert catalog.source.package == "lucide-static"
    assert catalog.source.version == LUCIDE_VERSION == "1.25.0"
    assert catalog.source.license == "ISC"
    assert len(catalog.source.source_sha256) == 64
    assert len(catalog.source.selected_geometry_sha256) == 64
    assert set(catalog.icons) == set(built.icon_roots)
    assert {icon.name for icon in catalog.icons.values()} == set(
        built.icon_roots
    )

    atoms = tuple(
        cell.atom for root, cell in snapshot.cells.items()
        if root.startswith("app:icon")
    )
    assert atoms
    assert not any(atom.lstrip().startswith((b"{", b"[", b"<")) for atom in atoms)
    assert not any(b"javascript:" in atom.lower() for atom in atoms)
    assert all(len(cell) == 4 for cell in (
        tuple((item.id, item.link0, item.link1, item.atom) for item in snapshot.cells.values())
    ))


def test_icon_geometry_projects_exact_ordered_safe_primitives():
    store, built = _catalog()
    icon = project_icon(
        store.snapshot(), built.protocol, built.icon_roots["plus"]
    )
    assert icon.name == "plus"
    assert icon.view_box == "0 0 24 24"
    assert [(primitive.tag, dict(primitive.attributes)) for primitive in icon.primitives] == [
        ("path", {"d": "M5 12h14"}),
        ("path", {"d": "M12 5v14"}),
    ]


def test_icon_assignment_is_an_editable_relation_between_control_and_icon():
    store, built = _catalog()
    owner = "test:control:zoom-in"
    store.commit(store.revision, create=(
        Cell(owner, NULL_CELL_ID, NULL_CELL_ID, b"Zoom in"),
    ))
    assignment = assign_icon(
        store,
        built.protocol,
        owner_root=owner,
        icon_root=built.icon_roots["zoom-in"],
        assignment_root="test:control:zoom-in:icon",
    )
    projected = project_icon_assignment(
        store.snapshot(), built.protocol, assignment
    )
    assert projected.owner_root == owner
    assert projected.icon_root == built.icon_roots["zoom-in"]


def test_icon_projection_rejects_an_executable_attribute_even_after_store_write():
    store, built = _catalog()
    snapshot = store.snapshot()
    icon_root = built.icon_roots["plus"]
    icon_members = read_relation(snapshot, icon_root, budget=128)
    primitive_root = next(
        member.participant_id for member in icon_members
        if member.role_id == built.protocol.role("primitive")
    )
    primitive_members = read_relation(snapshot, primitive_root, budget=64)
    attribute_root = next(
        member.participant_id for member in primitive_members
        if member.role_id == built.protocol.role("attribute")
    )
    attribute_members = read_relation(snapshot, attribute_root, budget=32)
    name_root = next(
        member.participant_id for member in attribute_members
        if member.role_id == built.protocol.role("attribute-name")
    )
    name = snapshot.cells[name_root]
    store.commit(snapshot.revision, replace=(
        Cell(name.id, name.link0, name.link1, b"onclick"),
    ))
    with pytest.raises(InvalidCell, match="attribute"):
        project_icon(store.snapshot(), built.protocol, icon_root)


def test_icon_import_and_projection_have_no_product_name_dispatch():
    source = "\n".join((
        inspect.getsource(ensure_archhub_icon_catalog),
        inspect.getsource(project_icon),
    )).lower()
    assert "if name ==" not in source
    assert "match name" not in source
    for product_name in ("brain", "cockpit", "grand map", "bim", "session"):
        assert product_name not in source


def test_icon_catalog_restore_is_idempotent():
    store, first = _catalog()
    before = store.revision
    second = ensure_archhub_icon_catalog(store)
    assert store.revision == before
    assert second.catalog_root == first.catalog_root
    assert dict(second.icon_roots) == dict(first.icon_roots)
