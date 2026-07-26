"""Courts for the transparent physical BABOOM companion projection."""
from __future__ import annotations

import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtCore import Qt
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

    assert report == "Council: 2/5 reviewed; peer review in progress. Next: gemini."


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
    assert BaboomNativeCompanionController(
        host,
        atlas,
        occupied_provider=lambda: Rect(0, 0, 1920, 1080),
    ).next_frame(Rect(0, 0, 1920, 1080)) is None

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
        assert window._animation_timer.interval() == 160
        assert not bool(
            window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
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
        assert window._talk.text() == "Talk"
        assert not window._input.isVisible()
        assert window._transient_report == "Ready."
    finally:
        window.stop_projection()
        window.close()
