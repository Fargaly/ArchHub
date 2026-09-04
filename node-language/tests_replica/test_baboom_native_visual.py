"""Courts for BABOOM's render-only native visual adapter."""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_host import BaboomNativeSnapshot
from nodelang.baboom_native_visual import (
    baboom_compact_message_size,
    project_baboom_native_visual_frame,
)
from nodelang.baboom_visual_assets import BaboomSpriteAtlas


def _atlas() -> BaboomSpriteAtlas:
    return BaboomSpriteAtlas(
        path=Path("C:/court/baboom/spritesheet.png"),
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )


def _snapshot(
    *,
    motion: str = "working",
    actionable: bool = False,
    title: str = "Review the native-frame contract",
) -> BaboomNativeSnapshot:
    context = {"revision": 41}
    work = {
        "revision": 41,
        "active": 1,
        "items": [{"state": "review", "title": title}],
    }
    workshop = {"revision": 41, "count": 2}
    attention = {"revision": 41, "blocked_obligations": 0}
    return BaboomNativeSnapshot(
        revision=41,
        presence_expires_at=1234.5,
        frame_issued_at=1200.0,
        frame_expires_at=1234.0,
        context=MappingProxyType(context),
        directive=MappingProxyType({
            "projection": "app:baboom-companion-directive:v1",
            "revision": 41,
            "persona_form": "auditor",
            "motion": motion,
            "compact_message": "1 Work item needs review." if actionable else "",
            "action": "review-work" if actionable else "",
            "action_label": "Review Work" if actionable else "",
        }),
        report=(
            MappingProxyType({
                "kind": "steward-briefing",
                "summary": "Founder-local Work, Workshop, and attention briefing.",
                "revision": 41,
                "data": {
                    "projection": "founder-local-baboom-steward-briefing",
                    "revision": 41,
                    "context": context,
                    "governed_work": work,
                    "workshop": workshop,
                    "attention": attention,
                },
            }) if actionable else None
        ),
        steward_signal_root=None,
    )


def test_native_visual_frame_keeps_quiet_graph_presence_sprite_only():
    frame = project_baboom_native_visual_frame(
        _snapshot(), _atlas(), screen=Rect(0, 0, 1920, 1080), animation_tick=3
    )

    assert frame.revision == 41
    assert frame.source == Rect(576, 1456, 192, 208)
    assert frame.layout.sprite == Rect(1760, 908, 144, 156)
    assert frame.layout.sprite.contained_by(Rect(0, 0, 1920, 1080))
    assert frame.report is None
    assert frame.layout.message is None
    assert frame.report_style == "flat-no-border"


def test_native_visual_frame_hides_its_report_before_covering_declared_work():
    frame = project_baboom_native_visual_frame(
        _snapshot(actionable=True),
        _atlas(),
        screen=Rect(0, 0, 800, 600),
        occupied=(Rect(460, 345, 340, 75),),
    )

    assert frame.layout.sprite.contained_by(Rect(0, 0, 800, 600))
    assert frame.layout.collision_state == "clear"
    assert frame.report is None
    assert frame.layout.message is None


def test_native_visual_frame_refuses_an_unreleased_motion_name():
    with pytest.raises(ValueError, match="directive"):
        project_baboom_native_visual_frame(
            _snapshot(motion="invented-motion", actionable=True), _atlas(), screen=Rect(0, 0, 800, 600)
        )


def test_native_visual_expands_a_simple_box_for_a_long_graph_report():
    message = (
        "One detailed ArchHub report must remain readable without adding a framed "
        "panel, hiding its final action, or forcing the founder to guess what "
        "BABOOM is asking them to review before the next governed step begins."
    )
    snapshot = _snapshot(actionable=True, title=message)

    frame = project_baboom_native_visual_frame(
        snapshot, _atlas(), screen=Rect(0, 0, 1920, 1080)
    )

    assert frame.layout.message is not None
    assert (frame.layout.message.width, frame.layout.message.height) == (
        baboom_compact_message_size(frame.report)
    )
    assert frame.layout.message.height > 64


def test_native_visual_frame_uses_one_same_revision_actionable_report():
    frame = project_baboom_native_visual_frame(
        _snapshot(actionable=True), _atlas(), screen=Rect(0, 0, 1920, 1080)
    )

    assert frame.report == (
        "Work: 1 active. Workshop: 2 entries. Attention: 0 blocked. "
        "Next review: Review the native-frame contract"
    )
    assert frame.layout.message is not None


def test_every_motion_pose_is_drawn_art_not_an_empty_cell():
    """BABOOM must never render a transparent cell and vanish.

    The founder's report: "BABOOM has a transparent frame around it and it
    is not stable." The sheet is 8 columns wide, but the idle row carries 7
    poses and each action row 6 -- so cycling the grid drew a fully
    transparent cell every few ticks and the companion blinked out, leaving
    the empty outline he saw. The player cycles the frames a row actually
    has; this holds it there.
    """
    from pathlib import Path

    from nodelang.baboom_native_visual import _MOTION_ROWS, baboom_sprite_source
    from nodelang.baboom_visual_assets import inspect_baboom_sprite_atlas_v2

    sheet = Path(__file__).resolve().parents[1] / "nodelang" / "data" / "baboom" / "spritesheet.png"
    atlas = inspect_baboom_sprite_atlas_v2(sheet)

    # Measured from the shipped art: seven idle poses, six per action row.
    assert atlas.frame_counts == (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
    assert atlas.frames_in_row(0) == 7
    assert atlas.frames_in_row(7) == 6

    payload = sheet.read_bytes()
    import zlib

    from nodelang.baboom_visual_assets import _unfilter_rgba_rows

    idat = []
    offset = 8
    width = height = 0
    while offset < len(payload):
        length = int.from_bytes(payload[offset:offset + 4], "big")
        kind = payload[offset + 4:offset + 8]
        data = payload[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width = int.from_bytes(data[0:4], "big")
            height = int.from_bytes(data[4:8], "big")
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            break
        offset += length + 12
    scanlines = _unfilter_rgba_rows(
        zlib.decompress(b"".join(idat)), width=width, height=height
    )

    for motion in _MOTION_ROWS:
        for tick in range(24):
            source = baboom_sprite_source(atlas, motion=motion, animation_tick=tick)
            opaque = any(
                alpha > 0
                for scanline in scanlines[source.y:source.y + source.height]
                for alpha in scanline[source.x * 4 + 3:(source.x + source.width) * 4:4]
            )
            assert opaque, (
                "motion %r tick %d renders an empty cell -- BABOOM would vanish"
                % (motion, tick)
            )
