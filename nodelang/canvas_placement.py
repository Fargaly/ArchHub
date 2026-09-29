"""Where a new card goes: the first free slot in one scope, by real bounds.

Every writer that places a card used a fixed coordinate (240,200 for a
contact, 1080,180 for an agent session, 0,0 for Work) plus a fixed height
guess, so cards landed on each other. ``free_slot`` reads the bounds the
scope already holds and answers the first position whose rectangle, with
the Arrange gap around it, meets nothing. It reads; it never writes.

A card's bounds are its stored position plus its drawn size. The size is
the Studio's own card size (studio-lm.jsx measureCards reports it after
render): 240 wide, a header plus one row per drawn parameter, and 520
wide for an expanded AI card. ``card_size`` is that rule in one place.
"""
from __future__ import annotations

from typing import Iterable, Mapping

CARD_WIDTH = 240.0
AI_CARD_WIDTH = 520.0
CARD_HEADER = 76.0
CARD_ROW = 18.0
CARD_ROWS_DRAWN = 6
# The gap Arrange leaves between cards (studio-lm.jsx canvasArrangePositions).
GAP = 48.0
ORIGIN = (240.0, 200.0)
_AI_ENGINE_PREFIXES = ("ai.", "model.", "llm.")

Rect = tuple[float, float, float, float]


# Rows the canvas never draws inside a card (universal_application node
# projection, "params"); every other row is one drawn line.
UNDRAWN_ROWS = frozenset({
    "id", "cat", "key", "title", "sub", "status", "color",
    "position_x", "position_y", "definition", "version",
    "evidence_ref", "last_verified", "authority_source",
    "bim_phase", "standard", "placed",
})


def drawn_rows(labels: Iterable[str]) -> int:
    """How many of a card's property rows the canvas draws."""
    return sum(1 for label in labels if label not in UNDRAWN_ROWS)


def card_size(engine: str = "", parameters: int = 0) -> tuple[float, float]:
    """The drawn size of one card: width by kind, height by its rows."""
    wide = str(engine or "").startswith(_AI_ENGINE_PREFIXES)
    rows = max(0, min(int(parameters), CARD_ROWS_DRAWN))
    return (AI_CARD_WIDTH if wide else CARD_WIDTH, CARD_HEADER + rows * CARD_ROW)


def intersects(a: Rect, b: Rect, gap: float = 0.0) -> bool:
    """Whether two rectangles (x, y, w, h) meet, with ``gap`` kept between."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + gap <= bx or bx + bw + gap <= ax
        or ay + ah + gap <= by or by + bh + gap <= ay
    )


def free_slot(
    occupied: Iterable[Rect],
    size: tuple[float, float] = (CARD_WIDTH, CARD_HEADER),
    *,
    origin: tuple[float, float] = ORIGIN,
    gap: float = GAP,
    columns: int = 6,
    limit: int = 4096,
) -> tuple[float, float]:
    """The first position, row by row from ``origin``, that meets nothing.

    Candidates walk a lattice of the card's own pitch; a scope with more
    cards than ``limit`` lattice cells still answers, below everything.
    """
    rects = [tuple(float(v) for v in rect) for rect in occupied]
    width, height = float(size[0]), float(size[1])
    pitch_x, pitch_y = width + gap, height + gap
    x0, y0 = float(origin[0]), float(origin[1])
    for index in range(limit):
        x = x0 + (index % columns) * pitch_x
        y = y0 + (index // columns) * pitch_y
        candidate = (x, y, width, height)
        if not any(intersects(candidate, rect, gap) for rect in rects):
            return (x, y)
    bottom = max((rect[1] + rect[3] for rect in rects), default=y0)
    return (x0, bottom + gap)


def overlapping(rects: Mapping[str, Rect]) -> set[str]:
    """Every card whose bounds meet another card's bounds."""
    items = sorted(rects.items())
    hit: set[str] = set()
    for index, (left, a) in enumerate(items):
        for right, b in items[index + 1:]:
            if intersects(a, b):
                hit.add(left)
                hit.add(right)
    return hit


def arrange_on_open(nodes: Iterable[dict]) -> dict[str, object]:
    """Which drawn cards overlap, split by whether Arrange may move them.

    The Studio contract: on open it runs its existing Arrange over
    ``arrange`` (unpinned cards that meet another card) and draws an
    overlap badge on every id in ``badge`` (pinned cards it never moves).
    Each node dict gets ``overlap``: None, "arrange" or "pinned".
    """
    nodes = list(nodes)
    rects = {}
    for node in nodes:
        engine = str(node.get("engine") or "")
        width, height = card_size(engine, len(node.get("params") or ()))
        rects[str(node["id"])] = (
            float(node.get("x") or 0.0), float(node.get("y") or 0.0),
            width, height,
        )
    hit = overlapping(rects)
    arrange, badge = [], []
    for node in nodes:
        root = str(node["id"])
        if root not in hit:
            node["overlap"] = None
        elif node.get("pinned"):
            node["overlap"] = "pinned"
            badge.append(root)
        else:
            node["overlap"] = "arrange"
            arrange.append(root)
    return {"arrange": arrange, "badge": badge}
