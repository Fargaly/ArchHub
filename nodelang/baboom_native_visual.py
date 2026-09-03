"""Disposable native BABOOM visual frames with no local semantic authority.

The graph supplies the same-revision directive; the validated atlas supplies
transparent pixels; this adapter supplies bounded geometry for a future native
renderer. It neither opens a window nor persists animation, report, or desktop
state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .baboom_companion_placement import (
    BaboomCompanionLayout,
    Rect,
    place_baboom_companion,
)
from .baboom_native_host import BaboomNativeSnapshot
from .baboom_visual_assets import BaboomSpriteAtlas


_MOTION_ROWS = {
    "idle": 0,
    "warning": 6,
    "working": 7,
    "review": 8,
    "focus": 8,
    "desk-scan": 0,
}

_COMPACT_MESSAGE_WIDTH = 280
_COMPACT_MESSAGE_MIN_HEIGHT = 28
_COMPACT_MESSAGE_MAX_HEIGHT = 160
_COMPACT_MESSAGE_LINE_HEIGHT = 15
_COMPACT_MESSAGE_CHARS_PER_LINE = 38


def baboom_compact_message_size(message: str) -> tuple[int, int]:
    """Return a bounded simple-box size that can contain a short report.

    This is deliberately text-only geometry. The physical companion applies
    the same bounded layout before painting, so a longer graph-backed reply
    cannot be silently clipped inside the original two-line report rectangle.
    """
    if type(message) is not str:
        raise ValueError("BABOOM compact message is invalid")
    words = message.split()
    if not words:
        return (_COMPACT_MESSAGE_WIDTH, _COMPACT_MESSAGE_MIN_HEIGHT)
    lines = 1
    line_length = 0
    for word in words:
        word_length = len(word)
        if line_length and line_length + 1 + word_length > _COMPACT_MESSAGE_CHARS_PER_LINE:
            lines += 1
            line_length = word_length
        else:
            line_length += word_length + (1 if line_length else 0)
    height = max(
        _COMPACT_MESSAGE_MIN_HEIGHT,
        6 + lines * _COMPACT_MESSAGE_LINE_HEIGHT,
    )
    return (_COMPACT_MESSAGE_WIDTH, min(height, _COMPACT_MESSAGE_MAX_HEIGHT))


def baboom_actionable_report_text(report: object) -> str:
    """Format the released founder-local briefing without a second read path.

    The frame validator has already established the report's strict schema and
    revision. This is presentation only: it neither infers state from text nor
    persists a local briefing.
    """
    if not isinstance(report, dict):
        raise ValueError("BABOOM native report is invalid")
    data = report.get("data")
    if not isinstance(data, dict):
        raise ValueError("BABOOM native report is invalid")
    lens = data.get("context") if isinstance(data.get("context"), dict) else {}
    work = data.get("governed_work")
    workshop = data.get("workshop")
    attention = data.get("attention")
    if not (
        isinstance(work, dict)
        and isinstance(workshop, dict)
        and isinstance(attention, dict)
    ):
        raise ValueError("BABOOM native report is invalid")
    active = work.get("active")
    entries = workshop.get("count")
    blocked = attention.get("blocked_obligations")
    if type(active) is not int or type(entries) is not int or type(blocked) is not int:
        raise ValueError("BABOOM native report is invalid")
    parts = [
        f"Work: {active} active.",
        f"Workshop: {entries} entries.",
        f"Attention: {blocked} blocked.",
    ]
    items = work.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        state = items[0].get("state")
        title = items[0].get("title")
        if isinstance(state, str) and isinstance(title, str) and title:
            parts.append(f"Next {state}: {title}")
    # What the founder asked the companion to tell him: who is working on
    # what, whether the brain answers, which hosts are down. Absent keys
    # (an older server) leave the report as it was.
    agents = lens.get("agents") if isinstance(lens.get("agents"), dict) else {}
    for row in (agents.get("working") or [])[:2]:
        if isinstance(row, dict) and row.get("title"):
            parts.append(f"{row.get('agent') or 'Agent'} on: {row['title']}")
    brain = lens.get("brain") if isinstance(lens.get("brain"), dict) else {}
    if brain.get("ok") is True:
        parts.append(f"Brain: {int(brain.get('facts') or 0)} facts.")
    elif brain.get("ok") is False:
        parts.append("Brain: not answering.")
    hosts = lens.get("hosts") if isinstance(lens.get("hosts"), dict) else {}
    down = [str(name) for name in (hosts.get("down") or [])]
    if down:
        parts.append("Hosts down: " + ", ".join(down) + ".")
    return " ".join(parts)


def baboom_sprite_source(
    atlas: BaboomSpriteAtlas,
    *,
    motion: str,
    animation_tick: int,
) -> Rect:
    """Return one released sprite source without recomputing desktop layout."""
    if (
        type(atlas) is not BaboomSpriteAtlas
        or type(motion) is not str
        or motion not in _MOTION_ROWS
        or type(animation_tick) is not int
        or animation_tick < 0
    ):
        raise ValueError("BABOOM native sprite source is invalid")
    row = _MOTION_ROWS[motion]
    if row >= atlas.rows or atlas.columns < 2:
        raise ValueError("BABOOM atlas cannot render the released motion")
    # Cycle only the poses this row was drawn with. The grid is 8 wide and
    # most action rows carry 6, so cycling the grid rendered a fully
    # transparent cell every few ticks -- the companion blinked out of
    # existence and left an empty outline on the desktop.
    return Rect(
        (animation_tick % atlas.frames_in_row(row)) * atlas.cell_width,
        row * atlas.cell_height,
        atlas.cell_width,
        atlas.cell_height,
    )


@dataclass(frozen=True, slots=True)
class BaboomNativeVisualFrame:
    """One render-only frame derived from one immutable graph snapshot."""

    revision: int
    atlas_path: str
    source: Rect
    layout: BaboomCompanionLayout
    motion: str
    persona_form: str
    report: str | None
    action: str
    action_label: str
    report_style: str
    # The staff orb inside the sprite (already scaled), and what lights it.
    orb: tuple[int, int] | None = None
    brain_state: str = "unknown"


def project_baboom_native_visual_frame(
    snapshot: BaboomNativeSnapshot,
    atlas: BaboomSpriteAtlas,
    *,
    screen: Rect,
    occupied: Iterable[Rect] = (),
    animation_tick: int = 0,
    sprite_size: tuple[int, int] = (144, 156),
    message_size: tuple[int, int] | None = None,
) -> BaboomNativeVisualFrame:
    """Build one compact, transparent, non-authoritative native render frame.

    ``animation_tick`` is supplied by the renderer's monotonic clock. It is not
    persisted and has no effect on graph meaning. A report is removed whenever
    the placement adapter cannot keep it clear of declared active-work bounds.
    """
    if (
        type(snapshot) is not BaboomNativeSnapshot
        or type(atlas) is not BaboomSpriteAtlas
        or type(animation_tick) is not int
        or animation_tick < 0
    ):
        raise ValueError("BABOOM native visual frame inputs are invalid")
    directive = snapshot.directive
    motion = directive.get("motion")
    persona_form = directive.get("persona_form")
    message = directive.get("compact_message")
    action = directive.get("action")
    action_label = directive.get("action_label")
    if (
        type(motion) is not str
        or motion not in _MOTION_ROWS
        or type(persona_form) is not str
        or not persona_form
        or type(message) is not str
        or type(action) is not str
        or type(action_label) is not str
    ):
        raise ValueError("BABOOM native visual directive is invalid")
    report_payload = snapshot.report
    if not action:
        if message or report_payload is not None:
            raise ValueError("BABOOM quiet directive must not project a panel")
        report = None
    elif report_payload is None:
        raise ValueError("BABOOM actionable directive requires a report")
    else:
        report = baboom_actionable_report_text(dict(report_payload))
    source = baboom_sprite_source(
        atlas, motion=motion, animation_tick=animation_tick
    )
    effective_message_size = (
        None if report is None else message_size or baboom_compact_message_size(report)
    )
    layout = place_baboom_companion(
        screen,
        sprite_size=sprite_size,
        message_size=effective_message_size,
        occupied=occupied,
    )
    row = _MOTION_ROWS[motion]
    frame_index = animation_tick % atlas.frames_in_row(row)
    raw_orb = atlas.orb_point(row, frame_index)
    scale_x = sprite_size[0] / atlas.cell_width
    scale_y = sprite_size[1] / atlas.cell_height
    orb = (round(raw_orb[0] * scale_x), round(raw_orb[1] * scale_y)) if raw_orb else None
    brain = snapshot.context.get("brain") if isinstance(snapshot.context, dict) or hasattr(snapshot.context, "get") else None
    if not isinstance(brain, dict) and brain is not None:
        brain = dict(brain)
    if not brain or brain.get("ok") is None:
        brain_state = "unknown"
    elif brain.get("ok"):
        brain_state = "lit" if int(brain.get("facts") or 0) > 0 else "dim"
    else:
        brain_state = "down"
    return BaboomNativeVisualFrame(
        revision=snapshot.revision,
        atlas_path=str(atlas.path),
        source=source,
        layout=layout,
        motion=motion,
        persona_form=persona_form,
        report=report if layout.collision_state == "clear" and layout.message is not None else None,
        action=action,
        action_label=action_label,
        report_style="flat-no-border",
        orb=orb,
        brain_state=brain_state,
    )


__all__ = [
    "BaboomNativeVisualFrame",
    "baboom_actionable_report_text",
    "baboom_compact_message_size",
    "baboom_sprite_source",
    "project_baboom_native_visual_frame",
]
