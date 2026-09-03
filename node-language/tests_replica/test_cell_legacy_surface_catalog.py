"""Legacy UI surface registry must be graph-held while it is consumed."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang.cell_legacy_surface_catalog import (  # noqa: E402
    DEFAULT_SUPERSEDED_BY,
    bootstrap_legacy_surface_catalog_protocol,
    build_legacy_surface_catalog,
    project_legacy_surface_catalog,
    surface_names_digest,
)
from nodelang.cell_protocols import read_relation  # noqa: E402
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID  # noqa: E402
import nodelang.cell_legacy_surface_catalog as catalog_module  # noqa: E402


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SURFACE_SOURCE = (
    PRODUCT_ROOT / "12.PRODUCTION" / "app" / "workflows" / "grand_map_ui.py"
)
EXPECTED_LEGACY_SURFACE_COUNT = 198
EXPECTED_LEGACY_SURFACE_DIGEST = (
    "b8be80ca1a2d34eb2873ab98d3847f4cbfa6e8aff61469f9accb5494b59cbda0"
)


def _legacy_surface_names_from_source() -> tuple[str, ...]:
    source = LEGACY_SURFACE_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "grand_map_ui_surface":
            for child in ast.walk(node):
                if not isinstance(child, ast.Assign) or not isinstance(child.value, ast.Dict):
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "builders"
                    for target in child.targets
                ):
                    continue
                return tuple(
                    key.value
                    for key in child.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
    raise AssertionError("legacy Grand Map UI builders registry not found")


def _catalog_world():
    names = _legacy_surface_names_from_source()
    store = CellStore()
    protocol = bootstrap_legacy_surface_catalog_protocol(store)
    built = build_legacy_surface_catalog(
        store,
        protocol,
        names,
        source_digest=EXPECTED_LEGACY_SURFACE_DIGEST,
    )
    return store, protocol, built, names


def test_legacy_surface_registry_is_mirrored_as_cells_with_frozen_digest():
    store, protocol, built, names = _catalog_world()
    projection = project_legacy_surface_catalog(store.snapshot(), protocol, built.root_id)

    assert len(names) == EXPECTED_LEGACY_SURFACE_COUNT
    assert surface_names_digest(names) == EXPECTED_LEGACY_SURFACE_DIGEST
    assert projection["surface_count"] == EXPECTED_LEGACY_SURFACE_COUNT
    assert projection["source_digest"] == EXPECTED_LEGACY_SURFACE_DIGEST
    assert projection["promotion_allowed"] is False
    assert projection["superseded_by"] == DEFAULT_SUPERSEDED_BY
    projected_names = tuple(item["name"] for item in projection["surfaces"])
    assert projected_names == names
    assert "rail-drawer-shell" in projected_names
    assert "canvas-node-card" in projected_names
    assert all(not name.startswith("universal-") for name in projected_names)
    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}


def test_catalog_relation_contains_one_item_per_legacy_surface():
    store, protocol, built, _names = _catalog_world()
    members = read_relation(store.snapshot(), built.root_id, budget=100_000)
    item_roots = [
        member.participant_id
        for member in members
        if member.role_id == protocol.role("item")
    ]

    assert tuple(item_roots) == built.surface_roots
    assert len(item_roots) == EXPECTED_LEGACY_SURFACE_COUNT
    for root in item_roots[:5]:
        surface = read_relation(store.snapshot(), root, budget=100)
        assert {
            member.role_id for member in surface
        } >= {
            protocol.role("name"),
            protocol.role("index"),
            protocol.role("source-digest"),
            protocol.role("lifecycle"),
            protocol.role("superseded-by"),
            protocol.role("promotion-allowed"),
        }


def test_catalog_rejects_drift_in_graph_held_surface_names():
    store, protocol, built, _names = _catalog_world()
    first_surface = built.surface_roots[0]
    name_root = first_surface + ":name"
    original = store.read(name_root)
    store.commit(store.revision, replace=(
        Cell(original.id, original.link0, original.link1, b"changed-surface-name"),
    ))

    with pytest.raises(InvalidCell, match="digest drifted"):
        project_legacy_surface_catalog(store.snapshot(), protocol, built.root_id)


def test_catalog_rejects_universal_surface_claims_and_digest_mismatches():
    store = CellStore()
    protocol = bootstrap_legacy_surface_catalog_protocol(store)
    with pytest.raises(InvalidCell, match="cannot claim universal"):
        build_legacy_surface_catalog(store, protocol, ("universal-canvas",))

    store = CellStore()
    protocol = bootstrap_legacy_surface_catalog_protocol(store)
    with pytest.raises(InvalidCell, match="digest does not match"):
        build_legacy_surface_catalog(
            store,
            protocol,
            ("home-top",),
            source_digest=EXPECTED_LEGACY_SURFACE_DIGEST,
        )


def test_catalog_bridge_does_not_import_legacy_or_execute_surfaces():
    source = inspect.getsource(catalog_module)
    for forbidden in (
        "grand_map_ui",
        "workflows.",
        "importlib",
        "exec(",
        "eval(",
        "subprocess",
        "open(",
    ):
        assert forbidden not in source
