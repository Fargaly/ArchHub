"""Pure, volatile geometry for a non-intrusive BABOOM projection.

This module does not inspect windows, capture screens, or persist desktop
state. A native client may supply its own consented foreground/occupied
rectangles, and this helper chooses a contained candidate for a sprite and its
single compact message rectangle. The graph never receives those rectangles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("BABOOM rectangle dimensions are invalid")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersection_area(self, other: "Rect") -> int:
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return max(0, right - left) * max(0, bottom - top)

    def contained_by(self, outer: "Rect") -> bool:
        return (
            self.x >= outer.x
            and self.y >= outer.y
            and self.right <= outer.right
            and self.bottom <= outer.bottom
        )


@dataclass(frozen=True, slots=True)
class BaboomCompanionLayout:
    """One ephemeral layout that a renderer can apply without resizing it."""

    sprite: Rect
    message: Rect | None
    edge: str
    overlap_area: int
    collision_state: str = "clear"


def _bounded_rect(screen: Rect, *, width: int, height: int, x: int, y: int) -> Rect:
    if width > screen.width or height > screen.height:
        raise ValueError("BABOOM visual element does not fit on the screen")
    return Rect(
        min(max(x, screen.x), screen.right - width),
        min(max(y, screen.y), screen.bottom - height),
        width,
        height,
    )


def _perimeter_positions(
    screen: Rect,
    *,
    sprite_width: int,
    sprite_height: int,
    margin: int,
    obstacles: tuple[Rect, ...],
) -> tuple[tuple[str, int, int], ...]:
    """Return contained perimeter anchors plus obstacle-clearance anchors.

    A future renderer supplies only consented, process-local rectangles.  This
    is deliberately a deterministic search over the screen perimeter rather
    than a window manager or a persisted desktop-layout authority.
    """
    defaults = (
        ("bottom-right", screen.right - margin - sprite_width, screen.bottom - margin - sprite_height),
        ("bottom-left", screen.x + margin, screen.bottom - margin - sprite_height),
        ("top-right", screen.right - margin - sprite_width, screen.y + margin),
        ("top-left", screen.x + margin, screen.y + margin),
    )
    horizontal = [screen.x + margin, screen.right - margin - sprite_width]
    vertical = [screen.y + margin, screen.bottom - margin - sprite_height]
    for obstacle in obstacles:
        horizontal.extend((
            obstacle.x - margin - sprite_width,
            obstacle.right + margin,
        ))
        vertical.extend((
            obstacle.y - margin - sprite_height,
            obstacle.bottom + margin,
        ))

    positions = list(defaults)
    # Side positions are preferred after the familiar corners.  They let
    # BABOOM remain at the screen perimeter when all four corners are busy.
    for y in vertical:
        positions.append(("left", screen.x + margin, y))
    for y in vertical:
        positions.append(("right", screen.right - margin - sprite_width, y))
    for x in horizontal:
        positions.append(("bottom", x, screen.bottom - margin - sprite_height))
    for x in horizontal:
        positions.append(("top", x, screen.y + margin))

    seen: set[tuple[int, int]] = set()
    bounded: list[tuple[str, int, int]] = []
    for edge, x, y in positions:
        sprite = _bounded_rect(
            screen, width=sprite_width, height=sprite_height, x=x, y=y
        )
        key = (sprite.x, sprite.y)
        if key in seen:
            continue
        seen.add(key)
        bounded.append((edge, sprite.x, sprite.y))
    return tuple(bounded)


def _clear_message(
    screen: Rect,
    *,
    sprite: Rect,
    message_width: int,
    message_height: int,
    gap: int,
    obstacles: tuple[Rect, ...],
) -> Rect | None:
    """Return one clear flat report rectangle or hide it entirely.

    The report is optional: it must never cover active work, force a border
    around the pet, or push either visual outside the screen.
    """
    if message_width == 0 or message_height == 0:
        return None
    x = min(
        max(sprite.x + (sprite.width - message_width) // 2, screen.x),
        screen.right - message_width,
    )
    y_values = (
        sprite.y - gap - message_height,
        sprite.bottom + gap,
    )
    for y in y_values:
        message = Rect(x, y, message_width, message_height)
        if (
            message.contained_by(screen)
            and message.intersection_area(sprite) == 0
            and all(message.intersection_area(item) == 0 for item in obstacles)
        ):
            return message
    return None


def place_baboom_companion(
    screen: Rect,
    *,
    sprite_size: tuple[int, int],
    message_size: tuple[int, int] | None = None,
    occupied: Iterable[Rect] = (),
    margin: int = 16,
    gap: int = 10,
) -> BaboomCompanionLayout:
    """Choose a fully contained layout or yield the desktop projection.

    A message size of ``None`` means BABOOM needs no report panel. When no
    perimeter candidate is clear, the layout is marked ``yield`` and the
    native projection must hide rather than cover active work.
    """
    if type(screen) is not Rect:
        raise ValueError("BABOOM screen bounds are invalid")
    if (
        type(sprite_size) is not tuple
        or len(sprite_size) != 2
        or any(type(value) is not int or value < 1 for value in sprite_size)
        or type(margin) is not int
        or type(gap) is not int
        or margin < 0
        or gap < 0
    ):
        raise ValueError("BABOOM placement values are invalid")
    if message_size is None:
        message_width = message_height = 0
    elif (
        type(message_size) is tuple
        and len(message_size) == 2
        and all(type(value) is int and value > 0 for value in message_size)
    ):
        message_width, message_height = message_size
    else:
        raise ValueError("BABOOM message bounds are invalid")
    obstacles = tuple(occupied)
    if any(type(item) is not Rect for item in obstacles):
        raise ValueError("BABOOM occupied bounds are invalid")
    if message_width > screen.width or message_height > screen.height:
        raise ValueError("BABOOM visual element does not fit on the screen")
    candidates = _perimeter_positions(
        screen,
        sprite_width=sprite_size[0],
        sprite_height=sprite_size[1],
        margin=margin,
        obstacles=obstacles,
    )
    ranked = []
    for index, (edge, x, y) in enumerate(candidates):
        sprite = _bounded_rect(
            screen,
            width=sprite_size[0],
            height=sprite_size[1],
            x=x,
            y=y,
        )
        overlap = sum(sprite.intersection_area(obstacle) for obstacle in obstacles)
        message = _clear_message(
            screen,
            sprite=sprite,
            message_width=message_width,
            message_height=message_height,
            gap=gap,
            obstacles=obstacles,
        )
        # A report never competes with active work. The sprite itself must
        # yield as well when every candidate intersects declared work.
        if overlap:
            message = None
        ranked.append((overlap, index, edge, sprite, message))
    overlap, _index, edge, sprite, message = min(
        ranked, key=lambda item: (item[0], item[1])
    )
    return BaboomCompanionLayout(
        sprite=sprite,
        message=message,
        edge=edge,
        overlap_area=overlap,
        collision_state="clear" if overlap == 0 else "yield",
    )


__all__ = ["BaboomCompanionLayout", "Rect", "place_baboom_companion"]
