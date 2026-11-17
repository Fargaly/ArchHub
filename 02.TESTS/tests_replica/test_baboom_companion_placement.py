"""Courts for BABOOM's screen-bounded, low-intrusion placement."""
from __future__ import annotations

import pytest

from nodelang.baboom_companion_placement import Rect, place_baboom_beside_composer, place_baboom_companion, screen_at


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


# ONEBABOOM: his two monitors as measured (the app on the right one), and the app's composer strip.
LEFT, RIGHT = Rect(-1920, 0, 1920, 1040), Rect(0, 0, 1920, 1040)


def _composer(app):
    return Rect(app.x + 280, app.bottom - 96, app.width - 320, 72)


def test_baboom_stands_above_the_right_end_of_the_composer_on_the_apps_screen():
    app = Rect(240, 66, 1440, 900)
    composer = _composer(app)
    stood = place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87), composer=composer)

    assert (stood.right, stood.bottom) == (composer.right, composer.y - 4)
    assert stood.contained_by(app) and stood.contained_by(RIGHT)
    assert stood.intersection_area(composer) == 0
    assert screen_at((LEFT, RIGHT), stood.x, stood.y) == RIGHT
    # A page with no composer: the window's bottom right corner.
    corner = place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87))
    assert (corner.right, corner.bottom) == (app.right - 16, app.bottom - 16)


def test_baboom_steps_aside_off_a_control_by_at_most_48_px():
    app = Rect(240, 66, 1440, 900)
    composer = _composer(app)
    home = place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87), composer=composer)
    zoom_control = Rect(home.x + 10, home.bottom - 30, 60, 28)

    stepped = place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87), composer=composer, busy=(zoom_control,))
    assert stepped.intersection_area(zoom_control) == 0
    assert (stepped.x, home.y - stepped.y) == (home.x, 48)
    # Text right across the patch leaves no clear spot: he stays where he lives, never hunting the screen.
    paragraph = Rect(app.x, home.y - 60, app.width, 160)
    assert place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87), composer=composer, busy=(paragraph,)) == home


@pytest.mark.parametrize("width", [1009, 1440])
def test_baboom_stays_whole_in_the_work_area_at_snapped_and_full_widths(width):
    for x in (0, 240, RIGHT.right - width, RIGHT.right - 300):   # the last hangs off the right edge of the screen
        app = Rect(x, 66, width, 900)
        stood = place_baboom_beside_composer(app, RIGHT, sprite_size=(80, 87), composer=_composer(app))
        assert stood.contained_by(RIGHT), (width, x, stood)
        assert stood.x >= app.x and stood.bottom <= _composer(app).y


def test_a_spot_on_no_screen_is_on_no_screen():
    assert screen_at((LEFT, RIGHT), -1592, 954) == LEFT   # his saved spot: a real screen, but not the app's
    assert screen_at((RIGHT,), -1592, 954) is None        # the left monitor unplugged
    assert screen_at((LEFT, RIGHT), 5000, 5000) is None


def test_oversized_visuals_fail_before_any_layout_is_returned():
    with pytest.raises(ValueError, match="does not fit"):
        place_baboom_companion(
            Rect(0, 0, 320, 240),
            sprite_size=(321, 160),
        )
