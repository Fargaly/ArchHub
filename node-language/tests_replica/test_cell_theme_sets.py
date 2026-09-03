"""Courts for graph-held themes: which exist, which is active, and no literal."""
from __future__ import annotations

import pytest

from nodelang.cell_design_tokens import (
    ensure_archhub_design_token_system,
    project_dtcg_resolver,
)
from nodelang.cell_theme_sets import (
    ACTIVE_THEME_ROOT,
    DEFAULT_THEME,
    THEMES,
    read_active_theme,
    read_theme_modifier,
    set_active_theme,
    theme_context_root,
)
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
    return store, build, build.resolver_root + ":modifier:theme"


def test_every_founder_theme_is_a_graph_context():
    store, _build, modifier = _system()
    modifier_state = read_theme_modifier(
        store.snapshot(), modifier,
        _protocol_context_role(store, modifier),
    )
    assert set(modifier_state.contexts) == set(THEMES)
    assert modifier_state.active == DEFAULT_THEME


def _protocol_context_role(store, modifier):
    from nodelang.cell_design_tokens import PROTOCOL_PREFIX
    return PROTOCOL_PREFIX + ":role:context"


def test_resolver_names_every_theme_and_the_active_one():
    store, build, _modifier = _system()
    resolver = project_dtcg_resolver(store.snapshot(), build)
    contexts = resolver["modifiers"]["theme"]["contexts"]
    assert set(contexts) == set(THEMES)
    assert resolver["modifiers"]["theme"]["default"] == DEFAULT_THEME


def test_switching_the_active_theme_changes_the_projection():
    store, build, modifier = _system()
    before = project_dtcg_resolver(store.snapshot(), build)
    assert before["modifiers"]["theme"]["default"] == DEFAULT_THEME
    set_active_theme(store, modifier, "vellum")
    after = project_dtcg_resolver(store.snapshot(), build)
    assert after["modifiers"]["theme"]["default"] == "vellum"
    # The set of themes is authority and does not move when one is chosen.
    assert set(after["modifiers"]["theme"]["contexts"]) == set(
        before["modifiers"]["theme"]["contexts"]
    )


def test_the_active_theme_survives_a_reopen():
    store, build, modifier = _system()
    set_active_theme(store, modifier, "blueprint")
    assert read_active_theme(store.snapshot(), modifier) == "blueprint"


def test_an_unadmitted_theme_is_refused_and_changes_nothing():
    store, build, modifier = _system()
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        set_active_theme(store, modifier, "midnight")
    assert store.snapshot().revision == before
    assert read_active_theme(store.snapshot(), modifier) == DEFAULT_THEME


def test_projection_has_no_theme_the_graph_does_not_hold():
    """Delete the active pointer and the projection refuses -- no fallback."""
    store, build, _modifier = _system()
    snapshot = store.snapshot()
    store.commit(snapshot.revision, replace=(
        Cell(ACTIVE_THEME_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"midnight"),
    ))
    with pytest.raises(InvalidCell):
        project_dtcg_resolver(store.snapshot(), build)


def test_every_context_root_is_reachable_by_name():
    store, _build, modifier = _system()
    cells = store.snapshot().cells
    for name in THEMES:
        assert theme_context_root(modifier, name) in cells
