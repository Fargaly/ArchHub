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
    """The DTCG `theme` modifier, projected out of the graph."""
    modifier = read_theme_modifier(snapshot, modifier_root, context_role)
    return {
        "contexts": {name: [] for name in modifier.contexts},
        "default": modifier.active,
    }
