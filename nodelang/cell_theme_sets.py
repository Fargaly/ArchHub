"""Themes as graph-held DTCG contexts, and the one that is active.

The design system already carried a `theme` modifier -- with exactly one
context, `dark`, and a resolver projection that printed `{"dark": []}` as a
literal instead of reading the graph. So the founder's three themes existed
only in the superseded app.

The contexts are part of the deterministic system (see `cell_design_tokens`):
which themes exist is authority, not state. Which one is ACTIVE is state, so
it lives in its own relation that a command may replace without the
deterministic set drifting.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot

ACTIVE_THEME_ROOT = "app:design-token:active-theme"

# The founder's three, by the surface each one paints.
THEMES: Mapping[str, str] = MappingProxyType({
    "forge": "Default dark warm surface",
    "blueprint": "Cool architectural blue dark surface",
    "vellum": "Light paper surface",
})
DEFAULT_THEME = "forge"

# What each theme repaints (theme_values), as THEME key -> colour over the
# foundation (the shipped THEME, which IS forge). A theme is offered only when it carries a
# value for EVERY foundation key; a partial set would paint a light page on a
# dark canvas, and an empty one is a switch that changes nothing (frontend
# brief task 9). The names in THEMES stay installed either way: they are the
# deterministic design system, and removing one would make every existing
# graph read as drifted.
#
# vellum is the design system's light mirror: tokens.jsx l_* (THEME l_*) and
# hub-kit.jsx HB_LIGHT. Together they give 18 of the foundation's 27 keys; the
# rest (bg_hover, bg_deep, bg_canvas, bg_ink, on_fill, line_hair, accent_dim,
# accent_press, cyan) have no light value in any design source, so vellum is
# held but not offered until the design supplies them. blueprint has no values
# anywhere.
# Only the HB_LIGHT values THEME does not already hold as l_*; the l_* ones are
# read from THEME itself so the two can never drift.
_VELLUM_EXTRAS: Mapping[str, str] = MappingProxyType({
    "bg_raised": "#ffffff", "ink_dim": "#b8b0a2", "line_soft": "#eee9de",
    "accent_hi": "#b4522f", "accent_soft": "#f2e2d8", "blue": "#395b86",
    "ok": "#4c7a4e", "warn": "#a8772a", "err": "#b0402f", "purple": "#6a5699",
})


def _theme_source() -> Mapping[str, str]:
    from .application import THEME
    return THEME


def _foundation() -> dict[str, str]:
    # The l_* keys are the light mirror's source values, not surfaces.
    return {key: value for key, value in _theme_source().items()
            if not key.startswith("l_")}


def theme_values(name: str) -> dict[str, str]:
    """What ``name`` paints over the foundation; empty for forge and for themes
    that have no values anywhere."""
    if name == "vellum":
        light = {key[2:]: value for key, value in _theme_source().items()
                 if key.startswith("l_")}
        return {**light, **_VELLUM_EXTRAS}
    return {}


def offered_themes() -> tuple[str, ...]:
    """Themes that repaint every foundation key -- the only ones a user may pick."""
    keys = set(_foundation())
    return tuple(
        name for name in THEMES
        if name == DEFAULT_THEME or (theme_values(name) and keys <= set(theme_values(name)))
    )


def resolve_theme(foundation: Mapping[str, str], name: str) -> dict[str, str]:
    """The colours to paint for ``name``: the foundation with its values over it.

    This is the one call the runtime needs: build ``configuration.theme`` from
    ``resolve_theme(THEME, active)`` and applyThemeProjection already writes
    every key as a CSS variable.
    """
    if name not in offered_themes():
        raise InvalidCell("theme has no values to paint: %s" % name)
    resolved = dict(foundation)
    resolved.update({key: value for key, value in theme_values(name).items()
                     if key in resolved})
    return resolved


@dataclass(frozen=True, slots=True)
class ThemeModifier:
    """What the graph says about themes, read back."""

    modifier_root: str
    contexts: tuple[str, ...]
    active: str


def theme_context_root(modifier_root: str, name: str) -> str:
    return "%s:context:%s" % (modifier_root, name)


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("theme text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_active_theme(
    store: CellStore,
    modifier_root: str,
    name: str = DEFAULT_THEME,
) -> str:
    """Install the active-theme pointer if the graph does not hold one."""
    if name not in THEMES:
        raise InvalidCell("theme is not an admitted context: %s" % name)
    snapshot = store.snapshot()
    if ACTIVE_THEME_ROOT in snapshot.cells:
        return read_active_theme(store.snapshot(), modifier_root)
    store.commit(snapshot.revision, create=(
        Cell(ACTIVE_THEME_ROOT, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")),
    ))
    return name


def set_active_theme(store: CellStore, modifier_root: str, name: str) -> str:
    """Switch the active theme. The contexts themselves never move."""
    if name not in THEMES:
        raise InvalidCell("theme is not an admitted context: %s" % name)
    if name not in offered_themes():
        raise InvalidCell("theme has no values to paint yet: %s" % name)
    snapshot = store.snapshot()
    if theme_context_root(modifier_root, name) not in snapshot.cells:
        raise InvalidCell("theme context is not installed: %s" % name)
    current = snapshot.cells.get(ACTIVE_THEME_ROOT)
    replacement = Cell(
        ACTIVE_THEME_ROOT, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")
    )
    if current is None:
        store.commit(snapshot.revision, create=(replacement,))
    elif current != replacement:
        store.commit(snapshot.revision, replace=(replacement,))
    return name


def read_active_theme(snapshot: Snapshot, modifier_root: str) -> str:
    """The active theme, from the graph. No default, no fallback."""
    if ACTIVE_THEME_ROOT not in snapshot.cells:
        raise InvalidCell("active theme is not installed")
    name = _text(snapshot, ACTIVE_THEME_ROOT)
    if theme_context_root(modifier_root, name) not in snapshot.cells:
        raise InvalidCell("active theme names an uninstalled context: %s" % name)
    return name


def read_theme_modifier(
    snapshot: Snapshot,
    modifier_root: str,
    context_role: str,
) -> ThemeModifier:
    """Every installed theme and the active one, read from the graph."""
    contexts = tuple(
        _text(snapshot, member.participant_id)
        for member in read_relation(snapshot, modifier_root, budget=256)
        if member.role_id == context_role
    )
    if not contexts:
        raise InvalidCell("theme modifier holds no context")
    return ThemeModifier(
        modifier_root, contexts, read_active_theme(snapshot, modifier_root)
    )


def project_theme_modifier(
    snapshot: Snapshot,
    modifier_root: str,
    context_role: str,
) -> dict[str, object]:
    """The DTCG `theme` modifier, projected out of the graph.

    Only offered themes appear, each with the values it paints. A graph whose
    active pointer names a theme without values rendered the default all
    along, so the projection says so rather than naming a switch that did
    nothing.
    """
    modifier = read_theme_modifier(snapshot, modifier_root, context_role)
    offered = offered_themes()
    contexts = {
        name: ([theme_values(name)] if theme_values(name) else [])
        for name in modifier.contexts if name in offered
    }
    return {
        "contexts": contexts,
        "default": modifier.active if modifier.active in contexts else DEFAULT_THEME,
    }
