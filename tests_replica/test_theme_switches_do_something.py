"""Court: a theme or overlay switch is offered only when it changes something.

Frontend brief task 9. The graph held blueprint, vellum and high-contrast as
contexts with no values: choosing one changed nothing on screen. A context is
offered, and can be made active, only when it carries a value for every
foundation key it would repaint; the authority names stay installed so an
existing graph never reads as drifted.
"""
from __future__ import annotations

import pytest

from nodelang.cell_accessibility import (
    ACTIVE_OVERLAY_ROOT,
    DEFAULT_OVERLAY,
    OVERLAYS,
    offered_overlays,
    set_active_overlay,
)
from nodelang.cell_design_tokens import (
    PROTOCOL_PREFIX,
    ensure_archhub_design_token_system,
    project_dtcg_resolver,
)
from nodelang.cell_theme_sets import (
    ACTIVE_THEME_ROOT,
    DEFAULT_THEME,
    THEMES,
    offered_themes,
    resolve_theme,
    set_active_theme,
    theme_context_root,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell
from nodelang.universal_presentation_seed import THEME as FOUNDATION

CONTEXT_ROLE = PROTOCOL_PREFIX + ":role:context"


def _system():
    store = CellStore()
    roots = {name: "test:theme:%s" % name for name in FOUNDATION}
    store.commit(store.revision, create=tuple(
        Cell(roots[name], NULL_CELL_ID, NULL_CELL_ID, value.encode("ascii"))
        for name, value in FOUNDATION.items()
    ))
    build = ensure_archhub_design_token_system(store, roots)
    return store, build


def test_every_offered_theme_repaints_every_foundation_key_it_names():
    for name in offered_themes():
        resolved = resolve_theme(FOUNDATION, name)
        assert set(resolved) == set(FOUNDATION)
        if name != DEFAULT_THEME:
            assert resolved != dict(FOUNDATION), name


def test_a_theme_without_values_is_not_offered_and_cannot_be_chosen():
    store, build = _system()
    modifier = build.resolver_root + ":modifier:theme"
    silent = [name for name in THEMES if name not in offered_themes()]
    assert silent, "every theme has values now: tighten this court"
    before = store.snapshot().revision
    for name in silent:
        assert theme_context_root(modifier, name) in store.snapshot().cells
        with pytest.raises(InvalidCell):
            set_active_theme(store, modifier, name)
    assert store.snapshot().revision == before


def test_the_projection_offers_only_themes_with_values():
    store, build = _system()
    resolver = project_dtcg_resolver(store.snapshot(), build)
    theme = resolver["modifiers"]["theme"]
    assert set(theme["contexts"]) == set(offered_themes())
    assert theme["default"] == DEFAULT_THEME


def test_an_old_graph_with_a_valueless_active_theme_shows_what_renders():
    """A graph that chose blueprint before this change rendered forge."""
    store, build = _system()
    silent = next(name for name in THEMES if name not in offered_themes())
    store.commit(store.snapshot().revision, replace=(
        Cell(ACTIVE_THEME_ROOT, NULL_CELL_ID, NULL_CELL_ID, silent.encode("utf-8")),
    ))
    theme = project_dtcg_resolver(store.snapshot(), build)["modifiers"]["theme"]
    assert theme["default"] == DEFAULT_THEME


def test_an_overlay_without_values_is_not_offered_and_cannot_be_chosen():
    store, build = _system()
    modifier = build.resolver_root + ":modifier:a11y"
    silent = [name for name in OVERLAYS if name not in offered_overlays()]
    assert "high-contrast" in silent
    before = store.snapshot().revision
    for name in silent:
        with pytest.raises(InvalidCell):
            set_active_overlay(store, modifier, name)
    assert store.snapshot().revision == before
    a11y = project_dtcg_resolver(store.snapshot(), build)["modifiers"]["a11y"]
    assert set(a11y["contexts"]) == set(offered_overlays())


def test_an_old_graph_with_high_contrast_active_shows_what_renders():
    store, build = _system()
    store.commit(store.snapshot().revision, replace=(
        Cell(ACTIVE_OVERLAY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"high-contrast"),
    ))
    a11y = project_dtcg_resolver(store.snapshot(), build)["modifiers"]["a11y"]
    assert a11y["default"] == DEFAULT_OVERLAY


def test_the_default_theme_resolves_to_the_foundation_itself():
    assert resolve_theme(FOUNDATION, DEFAULT_THEME) == dict(FOUNDATION)
    with pytest.raises(InvalidCell):
        resolve_theme(FOUNDATION, "midnight")
