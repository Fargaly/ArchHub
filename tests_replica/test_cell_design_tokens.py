"""Courts for the Cell-native DTCG design-system authority."""
from __future__ import annotations

import json

import pytest

from nodelang.cell_design_tokens import (
    COMPONENT_BINDINGS,
    DTCG_VERSION,
    ensure_archhub_design_token_system,
    import_dtcg_format,
    project_dtcg_format,
    project_dtcg_resolver,
    resolve_design_tokens,
)
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


THEME = {
    "bg": "#0e0e11",
    "bg_panel": "#15151a",
    "bg_soft": "#1c1c23",
    "bg_hover": "#22222a",
    "bg_deep": "#0a0a0d",
    "bg_canvas": "#101015",
    "ink": "#ece8e0",
    "ink_soft": "#9b938a",
    "ink_muted": "#5e574f",
    "line": "#26262e",
    "line_soft": "#1e1e24",
    "accent": "#d97757",
    "accent_soft": "#3a2018",
    "ok": "#7ec18e",
    "warn": "#e5b25a",
    "err": "#e6705f",
    "cyan": "#5fb3b3",
    "purple": "#a98cd6",
    "blue": "#7898d6",
}


def _system():
    store = CellStore()
    roots = {name: "test:theme:%s" % name for name in THEME}
    store.commit(store.revision, create=tuple(
        Cell(roots[name], NULL_CELL_ID, NULL_CELL_ID, value.encode("ascii"))
        for name, value in THEME.items()
    ))
    return store, ensure_archhub_design_token_system(store, roots)


def test_design_system_is_typed_graph_authority_without_json_atoms():
    store, built = _system()
    snapshot = store.snapshot()
    resolved = resolve_design_tokens(
        snapshot, built.protocol, built.token_set_root
    )
    assert len(resolved) == len(built.base_token_roots) + len(
        built.alias_token_roots
    )
    assert resolved[built.alias_token_roots["surface.canvas"]] == THEME[
        "bg_canvas"
    ]
    assert set(built.component_roots) == set(COMPONENT_BINDINGS)
    graph_atoms = tuple(
        cell.atom for root, cell in snapshot.cells.items()
        if root.startswith("app:design-token")
        or root.startswith("app:presentation-component")
    )
    assert graph_atoms
    assert not any(atom.lstrip().startswith((b"{", b"[")) for atom in graph_atoms)


def test_dtcg_projection_round_trips_through_a_new_cell_graph():
    store, built = _system()
    document = project_dtcg_format(
        store.snapshot(), built.protocol, built.token_set_root
    )
    assert document["color"]["accent"]["$type"] == "color"
    assert document["action"]["primary"]["$value"] == "{color.accent}"
    assert document["color"]["accent"]["$value"]["hex"] == THEME[
        "accent"
    ]
    imported = CellStore()
    protocol, token_set = import_dtcg_format(imported, document)
    projected = project_dtcg_format(
        imported.snapshot(), protocol, token_set
    )
    assert json.dumps(projected, sort_keys=True) == json.dumps(
        document, sort_keys=True
    )


def test_resolver_projects_the_released_dark_context_and_order():
    store, built = _system()
    resolver = project_dtcg_resolver(store.snapshot(), built)
    assert resolver["version"] == DTCG_VERSION
    assert resolver["modifiers"]["theme"]["default"] == "dark"
    assert resolver["resolutionOrder"] == [
        {"$ref": "#/sets/foundation"},
        {"$ref": "#/modifiers/theme"},
    ]


def test_alias_cycle_is_rejected_by_graph_resolution():
    store, built = _system()
    alias_root = built.alias_token_roots["surface.canvas"]
    members = read_relation(store.snapshot(), alias_root, budget=64)
    alias = next(
        member for member in members
        if member.role_id == built.protocol.role("alias")
    )
    incidence = store.read(alias.incidence_id)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, alias_root, incidence.atom
    ),))
    with pytest.raises(InvalidCell, match="cycle"):
        resolve_design_tokens(
            store.snapshot(), built.protocol, built.token_set_root
        )
