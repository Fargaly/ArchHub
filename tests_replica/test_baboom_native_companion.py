"""Courts for the transparent physical BABOOM companion projection."""
from __future__ import annotations

import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtTest import QTest

from nodelang.baboom_companion_placement import BaboomCompanionLayout, Rect
from nodelang.baboom_native_companion import (
    BaboomNativeCompanionController,
    compact_baboom_response_report,
    create_baboom_native_companion_window,
    render_baboom_native_sprite,
)
from nodelang.baboom_native_voice import BaboomVoiceInput
from nodelang.baboom_native_host import BaboomNativeHost
from nodelang.baboom_native_visual import BaboomNativeVisualFrame
from nodelang.baboom_visual_assets import BaboomSpriteAtlas


def test_native_companion_renders_only_the_transparent_sprite_crop():
    atlas = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    atlas.fill(QColor(0, 0, 0, 0))
    atlas.setPixelColor(2, 2, QColor(28, 187, 171, 255))
    frame = BaboomNativeVisualFrame(
        revision=41,
        atlas_path=str(Path("C:/court/baboom.png")),
        source=Rect(0, 0, 8, 8),
        layout=BaboomCompanionLayout(
            sprite=Rect(10, 20, 8, 8),
            message=None,
            edge="bottom-right",
            overlap_area=0,
        ),
        motion="idle",
        persona_form="steward",
        report=None,
        action="",
        action_label="",
        report_style="flat-no-border",
    )

    sprite = render_baboom_native_sprite(atlas, frame)

    assert sprite.width() == 8
    assert sprite.height() == 8
    assert sprite.pixelColor(0, 0).alpha() == 0
    assert sprite.pixelColor(2, 2) == QColor(28, 187, 171, 255)


def test_native_companion_compacts_founder_safe_graph_detail_without_a_second_store():
    report = compact_baboom_response_report({
        "kind": "model-council-report",
        "summary": "Latest bounded founder-local Workshop entries.",
        "data": {
            "admitted_providers": ["claude", "gemini", "gpt", "local", "openrouter"],
            "reviewed_providers": ["claude", "gpt"],
            "state": "peer-review-in-progress",
            "next_provider": "gemini",
        },
    })

    assert report == "Two of five models have reviewed; peer review in progress. Gemini is next."


class _Transport:
    def __init__(self) -> None:
        self.agent_session_root = ""

    def bind_agent_session(self, **kwargs):
        self.agent_session_root = "app:agent-session:runtime:companion-court"
        return {"agent_session": self.agent_session_root}

    def renew_runtime_presence(self):
        return {
            "agent_session": self.agent_session_root,
            "runtime": "baboom",
            "expires_at": 1234.5,
        }

    def baboom_native_frame(self, **kwargs):
        now = time.time()
        context = {
            "revision": 41,
            "work": {"blocked": 0, "review": 0},
            "attention": {"blocked_obligations": 0},
            "workshop": {"entry_count": 0},
            "meeting_notes": {"active_sessions": 0},
        }
        governed_work = {
            "revision": 41,
            "active": 1,
            "items": [{"state": "review", "title": "Review native frame"}],
        }
        workshop = {"revision": 41, "count": 2}
        attention = {"revision": 41, "blocked_obligations": 0}
        return {
            "projection": "app:baboom-native-frame:v2",
            "revision": 41,
            "issued_at": now,
            "expires_at": now + 30.0,
            "context": context,
            "directive": {
                "revision": 41,
                "motion": "idle",
                "message": "No governed Work needs attention.",
                "compact_message": "1 Work item needs review.",
                "persona_form": "steward",
                "action": "review-work",
                "action_label": "Review Work",
                "ttl_seconds": 30.0,
            },
            "report": {
                "kind": "steward-briefing",
                "summary": "Founder-local Work, Workshop, and attention briefing.",
                "revision": 41,
                "data": {
                    "projection": "founder-local-baboom-steward-briefing",
                    "revision": 41,
                    "context": context,
                    "governed_work": governed_work,
                    "workshop": workshop,
                    "attention": attention,
                },
            },
        }

    def record_baboom_steward_signal(self, **kwargs):
        raise AssertionError("idle companion must not emit a signal")

    def resolve_baboom_command(self, **kwargs):
        return {
            "catalog": "app:baboom-command-catalog:v1",
            "intent": "open-question",
            "payload": kwargs["utterance"],
            "revision": 41,
        }

    def respond_baboom_command(self, **kwargs):
        return {
            "command": self.resolve_baboom_command(**kwargs),
            "response": {"kind": "command-guidance", "summary": "Ready.", "data": {}},
        }

    def execute_baboom_command(self, **kwargs):
        return {
            "catalog": "app:baboom-command-catalog:v1",
            "intent": "assign-task",
            "work": "assembly-instance:governed-work:companion-court",
            "external_key": "baboom-founder-task:v1:" + "b" * 64,
            "created": True,
            "state": "open",
            "revision": 42,
        }


class _VoiceBackend:
    def capture_once(self, *, cancel, timeout_seconds):
        assert not cancel.is_set()
        assert timeout_seconds == 20.0
        return "BABOOM, brief me on ArchHub"


def test_native_companion_controller_executes_only_the_host_confirmed_task(tmp_path):
    atlas_path = tmp_path / "controller.png"
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    assert image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-execute-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()

    controller = BaboomNativeCompanionController(host, atlas)
    # A desktop with a maximised window has no clear ground. A companion
    # that answers that by vanishing is one nobody ever sees, so it settles
    # into a screen corner above the work instead -- present, without the
    # report panel.
    crowded = BaboomNativeCompanionController(
        host,
        atlas,
        occupied_provider=lambda: (Rect(0, 0, 1920, 1080),),
    ).next_frame(Rect(0, 0, 1920, 1080))
    assert crowded is not None
    assert crowded.layout.sprite.contained_by(Rect(0, 0, 1920, 1080))

    result = controller.execute(
        "Assign task: review the bounded Workshop"
    )

    assert result["intent"] == "assign-task"
    assert result["created"] is True


def test_native_companion_window_is_transparent_outside_the_sprite_and_report(tmp_path):
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "companion.png"
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()
    controller = BaboomNativeCompanionController(
        host, atlas, occupied_provider=lambda: ()
    )
    window = create_baboom_native_companion_window(controller)
    try:
        window.start_projection()
        app.processEvents()
        rendered = window.grab().toImage()
        assert rendered.width() > 144
        assert rendered.pixelColor(0, rendered.height() - 1).alpha() == 0
        assert any(
            rendered.pixelColor(x, y).alpha() == 255
            for x in range(rendered.width())
            for y in range(rendered.height())
        )
    finally:
        window.stop_projection()
        window.close()


def test_native_companion_keeps_reply_available_without_relaying_every_tick(tmp_path):
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "reply.png"
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-reply-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    voice = BaboomVoiceInput(backend_factory=_VoiceBackend)
    window = create_baboom_native_companion_window(controller, voice_input=voice)
    try:
        window.start_projection()
        app.processEvents()
        first_geometry = window.geometry()
        window.refresh()
        app.processEvents()
        assert window.geometry() == first_geometry
        assert window._projection_timer.interval() >= 500
        assert window._animation_timer.interval() == 900
        # An ambient companion that sits behind the founder's work is one he
        # never sees. It stays on top, frameless and click-through outside
        # its own sprite, which is how every desktop companion behaves.
        assert bool(
            window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )
        assert bool(
            window.windowFlags() & Qt.WindowType.FramelessWindowHint
        )
        assert "border:0" in window._report.styleSheet()
        assert "border-radius:0" in window._report.styleSheet()
        assert window._report.font().family() == "Segoe UI"
        assert window._input.font().family() == "Segoe UI"
        assert window._message_rect is not None
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            pos=window._sprite_rect.center(),
        )
        app.processEvents()
        assert window._input.isVisible()
        assert window._talk.isVisible()
        assert window._input.geometry() == window._message_rect
        window.refresh()
        app.processEvents()
        assert window._input.isVisible()
        QTest.mouseClick(window._talk, Qt.MouseButton.LeftButton)
        QTest.qWait(50)
        app.processEvents()
        # Talk is the lucide mic icon; its label lives in the accessible name,
        # which returns to "Talk" once a capture has finished.
        assert window._talk.accessibleName() == "Talk"
        assert not window._talk.icon().isNull()
        assert not window._input.isVisible()
        assert window._transient_report == "Ready."
    finally:
        window.stop_projection()
        window.close()


def test_native_companion_stays_where_the_founder_puts_it(tmp_path):
    """The founder's placement outranks every search, and survives a restart.

    His report: "BABOOM has a transparent frame around it and keeps hopping
    left and right across the screen." The hop was the 750ms projection
    re-running the placement search as his foreground windows changed. A
    pinned companion answers a changed screen by staying put -- clamped
    inside the new bounds, never re-searched -- and a companion he drags
    stays exactly where he dropped it, across restarts.
    """
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "pinned.png"
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-pinned-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()

    # A screen whose occupied windows keep changing must not move it.
    moving = [(), (Rect(0, 0, 1920, 200),), (Rect(0, 0, 1920, 1080),)]
    calls = {"n": 0}

    def shifting_windows():
        seen = moving[min(calls["n"], len(moving) - 1)]
        calls["n"] += 1
        return seen

    screen = Rect(0, 0, 1920, 1080)
    controller = BaboomNativeCompanionController(
        host, atlas, occupied_provider=shifting_windows
    )
    homes = {
        (
            controller.next_frame(screen).layout.sprite.x,
            controller.next_frame(screen).layout.sprite.y,
        )
        for _ in range(4)
    }
    assert len(homes) == 1, "the companion re-placed itself as windows changed"

    # A narrower screen keeps it, clamped, rather than sending it hunting.
    narrow = controller.next_frame(Rect(0, 0, 1280, 720))
    assert narrow is not None
    assert narrow.layout.sprite.contained_by(Rect(0, 0, 1280, 720))

    # Where the founder drops it is where it lives.
    controller.pin_sprite_origin(410, 260)
    placed = controller.next_frame(screen)
    assert (placed.layout.sprite.x, placed.layout.sprite.y) == (410, 260)
    assert controller.next_frame(screen).layout.sprite.x == 410

    # And it is remembered across a restart.
    position_path = tmp_path / "baboom-position.json"
    position_path.write_text('{"x": 410, "y": 260}', encoding="utf-8")
    restarted = BaboomNativeCompanionController(
        host, atlas, occupied_provider=lambda: ()
    )
    window = create_baboom_native_companion_window(
        restarted, position_path=position_path
    )
    try:
        assert restarted.next_frame(screen).layout.sprite.x == 410
        assert restarted.next_frame(screen).layout.sprite.y == 260
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_native_companion_click_opens_and_closes_the_ask_box(tmp_path):
    """A click opens the box, a second click or Escape closes it.

    His report: "I do not know how to deal with it." There was a press
    handler that only ever opened the input, and no way back -- no second
    click, no Escape, no drag.
    """
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "click.png"
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-click-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()
    controller = BaboomNativeCompanionController(
        host, atlas, occupied_provider=lambda: ()
    )
    window = create_baboom_native_companion_window(controller)
    try:
        window.start_projection()
        app.processEvents()
        window.refresh()
        app.processEvents()
        assert not window._input.isVisible()

        window._open_interaction()
        app.processEvents()
        assert window._input.isVisible(), "a click must open the ask box"

        window._close_interaction()
        app.processEvents()
        assert not window._input.isVisible(), "a second click must close it"
        assert not window._talk.isVisible()
        assert not window._confirm.isVisible()

        # Escape, from inside the box, is the same exit.
        window._open_interaction()
        app.processEvents()
        assert window._input.isVisible()
        QTest.keyClick(window._input, Qt.Key.Key_Escape)
        app.processEvents()
        assert not window._input.isVisible(), "Escape must close the ask box"
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_native_companion_report_box_fits_the_whole_briefing(tmp_path):
    """Every line of what BABOOM says must fit inside its box.

    His words: "the text of what it says is very long" -- and then, exactly:
    "I do not mean shorten the message, I mean I cannot see all of it." The
    box was sized from an assumed characters-per-line, the real font wrapped
    one line further, and the last line fell outside the box.
    """
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / "fit.png"
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path,
        width=1536,
        height=2288,
        columns=8,
        rows=11,
        cell_width=192,
        cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(),
        external_session_id="companion-fit-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()
    controller = BaboomNativeCompanionController(
        host, atlas, occupied_provider=lambda: ()
    )
    window = create_baboom_native_companion_window(controller)
    try:
        window.refresh()
        app.processEvents()
        # The briefing his machine actually showed, whose last line was cut.
        briefing = (
            "Work: 2 active. Workshop: 563 entries. Attention: 0 blocked. "
            "Next open: A wire can own its parameters"
        )
        width, height = window._report_size(briefing)
        needed = window._report.fontMetrics().boundingRect(
            QRect(0, 0, width - 12, 1 << 16),
            int(Qt.TextFlag.TextWordWrap),
            briefing,
        )
        assert height >= needed.height(), "the briefing does not fit its box"

        # And the box the layout actually hands the label is that size.
        window._transient_report = briefing
        window._transient_revision = None
        window.refresh()
        app.processEvents()
        assert window._message_rect is not None
        assert window._message_rect.height() >= needed.height()
        assert window._report.text() == briefing
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_native_companion_says_it_is_stale_rather_than_lie(tmp_path):
    """Past its lease the companion stays and SAYS the host is silent.

    It used to hide, and hiding on every brief lapse read as "keeps
    appearing and disappearing" on the founder's desktop (2026-09-04, again
    2026-09-06). The founder's design is that the sprite stays. The lie this
    court forbids is the other one: presenting an hour-old count as live.
    The notice must therefore reach the face even when the face is busy."""
    import time as _time
    from dataclasses import replace as _replace

    atlas_path = tmp_path / "lease.png"
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    assert image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(path=atlas_path, width=1536, height=2288, columns=8, rows=11, cell_width=192, cell_height=208)
    host = BaboomNativeHost(_Transport(), external_session_id="companion-lease-court",
                            device_credential_provider=lambda challenge: {"proof": "approved"})
    host.connect()
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    screen = Rect(0, 0, 1920, 1080)
    assert controller.next_frame(screen) is not None, "a live lease must draw"
    stale = _replace(host.latest_snapshot, frame_expires_at=_time.time() - 3600.0)
    with host._lock:
        host._latest = stale
    frame = controller.next_frame(screen)
    assert frame is not None, "the sprite stays; the founder asked for that"
    assert controller.host_silent_seconds >= 3600.0

    # The face must carry the staleness, and must carry it even when there is
    # more to say than fits: the notice used to be appended last and dropped
    # by the truncation on exactly the busy faces that needed it.
    from nodelang.baboom_native_companion import baboom_face_line, FACE_MAX_CHARS
    quiet, _offer = baboom_face_line(
        {"host_silent_seconds": controller.host_silent_seconds}, None
    )
    assert "haven't heard from ArchHub in 60 minutes" in quiet
    crowded_context = {
        "host_silent_seconds": controller.host_silent_seconds,
        "work": {"open": 9, "blocked": 4, "review": 7},
        "agents": {"count": 3},
        "brain": {"ok": True, "facts": 999999},
    }
    crowded, _ = baboom_face_line(crowded_context, None)
    assert len(crowded) <= FACE_MAX_CHARS
    assert "haven't heard" in crowded, (
        "a busy face dropped the staleness notice: %r" % crowded
    )


# --- G2 Task 13 BABOOM first slice (CODEX-FRONTEND-TASKS.md section 13,
# items 1, 3, 7, 8). Founder rule for BABOOM: colours come from THEME, text is
# readable (>= 4.5:1 for the menu hover and disabled rows), the menu is lifted by
# a shadow not a hairline border, buttons carry words not glyphs, the brain
# crystal is cyan/red/off from THEME, and the face line drops internal chatter.
# Every check below FAILS on 3a6bf6ba and passes on the slice patch.
import re as _t13_re
import nodelang.baboom_native_companion as _t13_companion
from nodelang.application import THEME as _T13_THEME

_T13_SRC = Path(_t13_companion.__file__).read_text(encoding="utf-8")
_T13_HEX = _t13_re.compile(r"#[0-9a-fA-F]{6}")


def _t13_rgb(value):
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _t13_luminance(rgb):
    def channel(raw):
        c = raw / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _t13_contrast(fg, bg):
    hi, lo = sorted((_t13_luminance(_t13_rgb(fg)), _t13_luminance(_t13_rgb(bg))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _t13_decl(style, selector):
    match = _t13_re.search(_t13_re.escape(selector) + r"\s*\{([^}]*)\}", style)
    return match.group(1) if match else ""


def _t13_prop(decl, name):
    match = _t13_re.search(r"(?:^|;|\s)" + name + r"\s*:\s*(#[0-9a-fA-F]{6})", decl)
    return match.group(1) if match else None


def _t13_window(tmp_path, name):
    app = QApplication.instance() or QApplication([])
    atlas_image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    atlas_image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(atlas_image)
    painter.fillRect(240, 50, 96, 120, QColor(28, 187, 171, 255))
    painter.end()
    atlas_path = tmp_path / name
    assert atlas_image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(
        path=atlas_path, width=1536, height=2288, columns=8, rows=11,
        cell_width=192, cell_height=208,
    )
    host = BaboomNativeHost(
        _Transport(), external_session_id="companion-t13-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    host.connect()
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    return app, create_baboom_native_companion_window(controller)


def test_t13_item1_companion_source_carries_no_raw_hex_colour():
    """item 1: every colour is a THEME token; no #rrggbb literal in the module."""
    hits = sorted(set(_T13_HEX.findall(_T13_SRC)))
    assert hits == [], "raw hex must be THEME tokens, found: %s" % hits


def _t13_hex(colour):
    return "#%02x%02x%02x" % (colour.red(), colour.green(), colour.blue())


def _t13_text_pixel(img, rect, bg_hex):
    """The row's solid text colour: the pixel whose luminance is furthest from bg.

    Works whether the text is lighter than the fill (white on accent, the base)
    or darker (on_fill on accent, the fix), so the ratio is the real text/bg one.
    """
    bg_lum = _t13_luminance(_t13_rgb(bg_hex))
    best = None
    best_dist = -1.0
    for y in range(max(0, rect.top()), min(img.height(), rect.bottom() + 1)):
        for x in range(max(0, rect.left()), min(img.width(), rect.right() + 1)):
            c = img.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            dist = abs(_t13_luminance((c.red(), c.green(), c.blue())) - bg_lum)
            if dist > best_dist:
                best_dist, best = dist, c
    return best


def test_t13_item1_menu_hover_and_disabled_meet_4_5_contrast():
    """item 1: measured from the RENDERED menu pixels, not token math.

    Base is white on accent = 3.12:1. The hovered row's real text pixels vs its
    real fill, and the disabled row's real text vs the real menu surface, must
    each read >= 4.5:1.
    """
    from PyQt6.QtWidgets import QApplication, QMenu
    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    menu.setStyleSheet(_t13_companion._MENU_STYLE)
    hovered = menu.addAction("Ask the brain")
    disabled = menu.addAction("Recall on the graph")
    disabled.setEnabled(False)
    menu.setActiveAction(hovered)          # force the :selected (hover) paint
    menu.resize(menu.sizeHint())
    menu.show()
    app.processEvents()
    img = menu.grab().toImage()
    try:
        hover_rect = menu.actionGeometry(hovered)
        dis_rect = menu.actionGeometry(disabled)
        hover_bg = img.pixelColor(hover_rect.right() - 15, hover_rect.center().y())
        hover_text = _t13_text_pixel(img, hover_rect, _t13_hex(hover_bg))
        menu_bg = img.pixelColor(3, 3)
        dis_text = _t13_text_pixel(img, dis_rect, _t13_hex(menu_bg))
        hover = _t13_contrast(_t13_hex(hover_text), _t13_hex(hover_bg))
        disabled_ratio = _t13_contrast(_t13_hex(dis_text), _t13_hex(menu_bg))
        assert hover >= 4.5, "rendered hover contrast %.2f < 4.5 (bg %s text %s)" % (
            hover, _t13_hex(hover_bg), _t13_hex(hover_text))
        assert disabled_ratio >= 4.5, "rendered disabled contrast %.2f < 4.5 (bg %s text %s)" % (
            disabled_ratio, _t13_hex(menu_bg), _t13_hex(dis_text))
    finally:
        menu.close()
        menu.deleteLater()
        app.processEvents()


def test_t13_item1_menu_surface_is_a_theme_token():
    """item 1: the menu surface is THEME['bg_raised'], not a hand-typed grey."""
    menu = _t13_decl(_t13_companion._MENU_STYLE, "QMenu")
    assert _t13_prop(menu, "background") == _T13_THEME["bg_raised"]


def test_t13_item1_menu_dropped_its_border_for_a_shadow():
    """item 1: no 1px hairline border; a QGraphicsDropShadowEffect lifts the menu."""
    menu = _t13_decl(_t13_companion._MENU_STYLE, "QMenu")
    assert "1px solid" not in menu, "menu must drop its hairline border; got %r" % menu
    assert "QGraphicsDropShadowEffect" in _T13_SRC, "the menu must be lifted by a drop shadow"


def test_t13_item3_act_glyphs_are_deleted():
    """item 3: the glyph table is gone; the confirm control speaks in words."""
    assert not hasattr(_t13_companion, "_BABOOM_ACT_GLYPHS"), (
        "delete _BABOOM_ACT_GLYPHS; the confirm button shows the action in words")


def test_t13_item3_confirm_and_cancel_carry_words(tmp_path):
    """item 3: confirm and cancel are labelled buttons, not a bare glyph."""
    app, window = _t13_window(tmp_path, "t13-buttons.png")
    try:
        confirm = window._confirm.text()
        assert confirm.strip() and any(c.isalpha() for c in confirm), (
            "the confirm button must carry a word, got %r" % confirm)
        assert hasattr(window, "_cancel"), "a labelled Cancel must sit beside Confirm"
        cancel = window._cancel.text()
        assert cancel.strip() and any(c.isalpha() for c in cancel), (
            "the cancel button must carry a word, got %r" % cancel)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def _t13_crystal_frame(state):
    return BaboomNativeVisualFrame(
        revision=1, atlas_path="x", source=Rect(0, 0, 8, 8),
        layout=BaboomCompanionLayout(
            sprite=Rect(0, 0, 8, 8), message=None, edge="bottom-right", overlap_area=0),
        motion="idle", persona_form="steward", report=None, action="", action_label="",
        report_style="flat-no-border", orb=(4, 4), brain_state=state)


def test_t13_item7_crystal_colours_come_from_theme():
    """item 7: the crystal colours are THEME tokens, not hand-typed QColor rgb."""
    for literal in ("QColor(126, 223, 211)", "QColor(150, 150, 150)", "QColor(200, 68, 59)"):
        assert literal not in _T13_SRC, "crystal colour %s must come from THEME" % literal


def test_t13_item7_dim_crystal_draws_no_glow():
    """item 7: a lit crystal glows; a dim (answered-empty) one draws nothing."""
    atlas = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    atlas.fill(QColor(0, 0, 0, 0))
    lit = render_baboom_native_sprite(atlas, _t13_crystal_frame("lit"))
    dim = render_baboom_native_sprite(atlas, _t13_crystal_frame("dim"))
    lit_px = sum(1 for x in range(8) for y in range(8) if lit.pixelColor(x, y).alpha() > 0)
    dim_px = sum(1 for x in range(8) for y in range(8) if dim.pixelColor(x, y).alpha() > 0)
    assert lit_px > 0, "the lit crystal must glow"
    assert dim_px == 0, "the dim crystal must not glow"


def test_t13_item8_face_line_drops_brain_and_card_chatter():
    """item 8: the face line no longer emits brain chatter or a canvas card counter."""
    from nodelang.baboom_native_companion import baboom_face_line
    line, _offer = baboom_face_line({"brain": {"ok": True}}, None)
    assert "The brain is answering." not in line, (
        "face_line must not narrate a healthy brain")
    line2, _offer2 = baboom_face_line({"canvas": {"ran": 9, "answered": 4}}, None)
    assert "on the canvas" not in line2, "the canvas card counter is founder noise; drop it"


def test_t13_item1_primary_confirm_uses_accent_fill_and_on_fill_text(tmp_path):
    """item 1: the primary act button is accent fill + THEME['on_fill'] text (>= 4.5)."""
    app, window = _t13_window(tmp_path, "t13-primary.png")
    try:
        ss = window._confirm.styleSheet()
        assert _T13_THEME["accent"] in ss, "primary confirm must fill with THEME accent, got %r" % ss
        assert _T13_THEME["on_fill"] in ss, "primary confirm text must be THEME on_fill, got %r" % ss
        assert _t13_contrast(_T13_THEME["on_fill"], _T13_THEME["accent"]) >= 4.5
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_t13_item3_talk_is_a_labelled_mic_icon(tmp_path):
    """item 3: Talk is the lucide mic icon with the accessible name 'Talk', not a word."""
    app, window = _t13_window(tmp_path, "t13-mic.png")
    try:
        assert not window._talk.icon().isNull(), "Talk must carry the lucide mic icon"
        assert window._talk.accessibleName() == "Talk"
        assert window._talk.text() == "", "Talk is an icon, not a text button"
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
