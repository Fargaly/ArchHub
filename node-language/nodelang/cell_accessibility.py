"""The accessibility overlay as a second graph-held modifier.

The Grand Map carries `A11y Token Overlay` -- high contrast plus a zoom scale,
composed onto whatever theme is active. It lived only in the superseded app.

It is built exactly like themes and for the same reason: WHICH overlays exist
is authority and belongs to the deterministic system, WHICH ONE IS ACTIVE (and
at what zoom) is state and lives in its own relation. An overlay never replaces
the theme -- it composes after it, which is what the resolution order says.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot

ACTIVE_OVERLAY_ROOT = "app:design-token:active-a11y-overlay"
ZOOM_ROOT = "app:design-token:a11y-zoom"

OVERLAYS: Mapping[str, str] = MappingProxyType({
    "standard": "No overlay; the theme as released",
    "high-contrast": "Raised contrast for every surface and edge",
})
DEFAULT_OVERLAY = "standard"

# The zoom the founder's overlay offered. A percentage the graph holds, not a
# free number: an unadmitted zoom is refused rather than silently clamped.
ZOOM_STEPS: tuple[int, ...] = (100, 125, 150, 200)
DEFAULT_ZOOM = 100


@dataclass(frozen=True, slots=True)
class AccessibilityOverlay:
    modifier_root: str
    contexts: tuple[str, ...]
    active: str
    zoom: int


def overlay_context_root(modifier_root: str, name: str) -> str:
    return "%s:context:%s" % (modifier_root, name)


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("accessibility text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_active_overlay(store: CellStore, modifier_root: str) -> str:
    """Install the overlay and zoom pointers if the graph holds none."""
    snapshot = store.snapshot()
    create = []
    if ACTIVE_OVERLAY_ROOT not in snapshot.cells:
        create.append(Cell(ACTIVE_OVERLAY_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                           DEFAULT_OVERLAY.encode("utf-8")))
    if ZOOM_ROOT not in snapshot.cells:
        create.append(Cell(ZOOM_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                           str(DEFAULT_ZOOM).encode("utf-8")))
    if create:
        store.commit(snapshot.revision, create=tuple(create))
    return read_active_overlay(store.snapshot(), modifier_root)


def set_active_overlay(store: CellStore, modifier_root: str, name: str) -> str:
    if name not in OVERLAYS:
        raise InvalidCell("overlay is not an admitted context: %s" % name)
    snapshot = store.snapshot()
    if overlay_context_root(modifier_root, name) not in snapshot.cells:
        raise InvalidCell("overlay context is not installed: %s" % name)
    replacement = Cell(ACTIVE_OVERLAY_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                       name.encode("utf-8"))
    current = snapshot.cells.get(ACTIVE_OVERLAY_ROOT)
    if current is None:
        store.commit(snapshot.revision, create=(replacement,))
    elif current != replacement:
        store.commit(snapshot.revision, replace=(replacement,))
    return name


def set_zoom(store: CellStore, percent: int) -> int:
    """Zoom is a step the graph admits, never an arbitrary number."""
    if percent not in ZOOM_STEPS:
        raise InvalidCell("zoom is not an admitted step: %s" % percent)
    snapshot = store.snapshot()
    replacement = Cell(ZOOM_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                       str(percent).encode("utf-8"))
    current = snapshot.cells.get(ZOOM_ROOT)
    if current is None:
        store.commit(snapshot.revision, create=(replacement,))
    elif current != replacement:
        store.commit(snapshot.revision, replace=(replacement,))
    return percent


def read_zoom(snapshot: Snapshot) -> int:
    if ZOOM_ROOT not in snapshot.cells:
        raise InvalidCell("accessibility zoom is not installed")
    raw = _text(snapshot, ZOOM_ROOT)
    try:
        percent = int(raw)
    except ValueError as exc:
        raise InvalidCell("accessibility zoom is not a number: %s" % raw) from exc
    if percent not in ZOOM_STEPS:
        raise InvalidCell("accessibility zoom is not an admitted step: %s" % percent)
    return percent


def read_active_overlay(snapshot: Snapshot, modifier_root: str) -> str:
    if ACTIVE_OVERLAY_ROOT not in snapshot.cells:
        raise InvalidCell("active accessibility overlay is not installed")
    name = _text(snapshot, ACTIVE_OVERLAY_ROOT)
    if overlay_context_root(modifier_root, name) not in snapshot.cells:
        raise InvalidCell("active overlay names an uninstalled context: %s" % name)
    return name


def read_accessibility_overlay(
    snapshot: Snapshot,
    modifier_root: str,
    context_role: str,
) -> AccessibilityOverlay:
    contexts = tuple(
        _text(snapshot, member.participant_id)
        for member in read_relation(snapshot, modifier_root, budget=256)
        if member.role_id == context_role
    )
    if not contexts:
        raise InvalidCell("accessibility modifier holds no context")
    return AccessibilityOverlay(
        modifier_root,
        contexts,
        read_active_overlay(snapshot, modifier_root),
        read_zoom(snapshot),
    )


def project_accessibility_modifier(
    snapshot: Snapshot,
    modifier_root: str,
    context_role: str,
) -> dict[str, object]:
    """The DTCG `a11y` modifier, projected out of the graph."""
    overlay = read_accessibility_overlay(snapshot, modifier_root, context_role)
    return {
        "contexts": {name: [] for name in overlay.contexts},
        "default": overlay.active,
        "zoom": overlay.zoom,
    }
