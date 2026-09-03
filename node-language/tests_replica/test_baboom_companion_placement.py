"""Courts for BABOOM's screen-bounded, low-intrusion placement."""
from __future__ import annotations

import pytest

from nodelang.baboom_companion_placement import Rect, place_baboom_companion


def test_companion_moves_away_from_occupied_default_corner():
    screen = Rect(0, 0, 1920, 1080)
    layout = place_baboom_companion(
        screen,
        sprite_size=(180, 240),
        message_size=(280, 76),
        occupied=(Rect(1500, 700, 420, 380),),
    )

    assert layout.edge == "bottom-left"
    assert layout.overlap_area == 0
    assert layout.sprite.contained_by(screen)
    assert layout.message is not None and layout.message.contained_by(screen)
    assert layout.message.intersection_area(layout.sprite) == 0


def test_companion_never_walks_or_places_a_message_outside_the_screen():
    screen = Rect(100, 50, 640, 420)
    layout = place_baboom_companion(
        screen,
        sprite_size=(180, 240),
        message_size=(280, 120),
        occupied=(),
    )

    assert layout.sprite.contained_by(screen)
    assert layout.message is not None and layout.message.contained_by(screen)
    assert layout.message.intersection_area(layout.sprite) == 0


def test_companion_yields_the_desktop_when_every_perimeter_slot_is_busy():
    screen = Rect(0, 0, 800, 600)
    layout = place_baboom_companion(
        screen,
        sprite_size=(160, 220),
        occupied=(Rect(0, 0, 800, 600),),
    )

    assert layout.message is None
    assert layout.sprite.contained_by(screen)
    assert layout.overlap_area == layout.sprite.width * layout.sprite.height
    assert layout.collision_state == "yield"


def test_companion_searches_a_clear_perimeter_slot_before_covering_work():
    screen = Rect(0, 0, 1920, 1080)
    layout = place_baboom_companion(
        screen,
        sprite_size=(180, 240),
        occupied=(
            Rect(0, 0, 260, 260),
            Rect(1660, 0, 260, 260),
            Rect(0, 820, 260, 260),
            Rect(1660, 820, 260, 260),
        ),
    )

    assert layout.edge == "left"
    assert layout.collision_state == "clear"
    assert layout.overlap_area == 0
    assert all(layout.sprite.intersection_area(item) == 0 for item in (
        Rect(0, 0, 260, 260),
        Rect(1660, 0, 260, 260),
        Rect(0, 820, 260, 260),
        Rect(1660, 820, 260, 260),
    ))


def test_companion_hides_the_report_box_before_covering_active_work():
    screen = Rect(0, 0, 800, 600)
    layout = place_baboom_companion(
        screen,
        sprite_size=(160, 200),
        message_size=(280, 80),
        occupied=(Rect(540, 270, 310, 110),),
    )

    assert layout.edge == "bottom-right"
    assert layout.collision_state == "clear"
    assert layout.sprite.intersection_area(Rect(540, 270, 310, 110)) == 0
    assert layout.message is None


def test_oversized_visuals_fail_before_any_layout_is_returned():
    with pytest.raises(ValueError, match="does not fit"):
        place_baboom_companion(
            Rect(0, 0, 320, 240),
            sprite_size=(321, 160),
        )
