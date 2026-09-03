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
from nodelang.cell_theme_sets import DEFAULT_THEME, THEMES
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


# The application's own palette IS the fixture: a hand-copy here silently
# drifted from production (it still carried the failing #5e574f ink_muted
# after the app moved on). The court must judge the palette the app ships.
from nodelang.universal_presentation_seed import THEME


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


def test_resolver_projects_the_released_theme_contexts_and_order():
    """The resolver used to print one context, `dark`, as a literal. The
    themes are graph-held now, so it names every installed one and the
    active one -- see `test_cell_theme_sets` for the switching court."""
    store, built = _system()
    resolver = project_dtcg_resolver(store.snapshot(), built)
    assert resolver["version"] == DTCG_VERSION
    assert set(resolver["modifiers"]["theme"]["contexts"]) == set(THEMES)
    assert resolver["modifiers"]["theme"]["default"] == DEFAULT_THEME
    assert resolver["resolutionOrder"] == [
        {"$ref": "#/sets/foundation"},
        {"$ref": "#/modifiers/theme"},
        {"$ref": "#/modifiers/a11y"},
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
