"""Courts for the accessibility overlay: composed onto the theme, graph-held."""
from __future__ import annotations

import pytest

from nodelang.cell_accessibility import (
    ACTIVE_OVERLAY_ROOT,
    DEFAULT_OVERLAY,
    DEFAULT_ZOOM,
    OVERLAYS,
    ZOOM_ROOT,
    ZOOM_STEPS,
    read_active_overlay,
    read_zoom,
    set_active_overlay,
    set_zoom,
)
from nodelang.cell_design_tokens import (
    PROTOCOL_PREFIX,
    ensure_archhub_design_token_system,
    project_dtcg_resolver,
)
from nodelang.cell_theme_sets import set_active_theme
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


# The shipped palette is the fixture; a hand-copy drifted before
# (it kept the failing #5e574f ink_muted after production moved on).
from nodelang.universal_presentation_seed import THEME as THEME_VALUES


def _system():
    store = CellStore()
    roots = {name: "test:theme:%s" % name for name in THEME_VALUES}
    store.commit(store.revision, create=tuple(
        Cell(roots[name], NULL_CELL_ID, NULL_CELL_ID, value.encode("ascii"))
        for name, value in THEME_VALUES.items()
    ))
    build = ensure_archhub_design_token_system(store, roots)
    return store, build, build.resolver_root + ":modifier:a11y"


def test_every_overlay_is_a_graph_context_with_a_zoom():
    store, build, _modifier = _system()
    resolver = project_dtcg_resolver(store.snapshot(), build)
    a11y = resolver["modifiers"]["a11y"]
    assert set(a11y["contexts"]) == set(OVERLAYS)
    assert a11y["default"] == DEFAULT_OVERLAY
    assert a11y["zoom"] == DEFAULT_ZOOM


def test_the_overlay_composes_after_the_theme_never_instead_of_it():
    store, build, _modifier = _system()
    resolver = project_dtcg_resolver(store.snapshot(), build)
    order = [item["$ref"] for item in resolver["resolutionOrder"]]
    assert order.index("#/modifiers/a11y") > order.index("#/modifiers/theme")
    assert "#/sets/foundation" == order[0]


def test_high_contrast_and_a_theme_hold_at_the_same_time():
    store, build, modifier = _system()
    set_active_theme(store, build.resolver_root + ":modifier:theme", "vellum")
    set_active_overlay(store, modifier, "high-contrast")
    resolver = project_dtcg_resolver(store.snapshot(), build)
    assert resolver["modifiers"]["theme"]["default"] == "vellum"
    assert resolver["modifiers"]["a11y"]["default"] == "high-contrast"


def test_zoom_moves_through_the_admitted_steps():
    store, build, _modifier = _system()
    for step in ZOOM_STEPS:
        set_zoom(store, step)
        assert read_zoom(store.snapshot()) == step
        assert project_dtcg_resolver(
            store.snapshot(), build)["modifiers"]["a11y"]["zoom"] == step


def test_an_unadmitted_zoom_is_refused_and_changes_nothing():
    store, build, _modifier = _system()
    before_revision = store.snapshot().revision
    before_zoom = read_zoom(store.snapshot())
    with pytest.raises(InvalidCell):
        set_zoom(store, 137)
    assert store.snapshot().revision == before_revision
    assert read_zoom(store.snapshot()) == before_zoom


def test_an_unadmitted_overlay_is_refused_and_changes_nothing():
    store, build, modifier = _system()
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        set_active_overlay(store, modifier, "night-vision")
    assert store.snapshot().revision == before
    assert read_active_overlay(store.snapshot(), modifier) == DEFAULT_OVERLAY


def test_projection_refuses_an_overlay_the_graph_does_not_hold():
    store, build, _modifier = _system()
    snapshot = store.snapshot()
    store.commit(snapshot.revision, replace=(
        Cell(ACTIVE_OVERLAY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"night-vision"),
    ))
    with pytest.raises(InvalidCell):
        project_dtcg_resolver(store.snapshot(), build)


def test_projection_refuses_a_zoom_the_graph_does_not_admit():
    store, build, _modifier = _system()
    snapshot = store.snapshot()
    store.commit(snapshot.revision, replace=(
        Cell(ZOOM_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"137"),
    ))
    with pytest.raises(InvalidCell):
        project_dtcg_resolver(store.snapshot(), build)


def test_overlay_survives_a_reopen():
    store, build, modifier = _system()
    set_active_overlay(store, modifier, "high-contrast")
    set_zoom(store, 150)
    assert read_active_overlay(store.snapshot(), modifier) == "high-contrast"
    assert read_zoom(store.snapshot()) == 150
