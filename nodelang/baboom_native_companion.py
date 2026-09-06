"""Transparent native BABOOM companion projection.

This module is an explicit physical renderer for a connected ``BaboomNativeHost``.
It has no launcher, graph store, queue, authority, or lifecycle ownership. A
controlled desktop handoff may construct it only after the graph and physical
holder gates have cleared.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import ctypes
from ctypes import wintypes
from dataclasses import replace
import json
import os
import time
from pathlib import Path
import threading
from typing import Any

from .baboom_companion_placement import (
    _bounded_rect,
    _clear_message,
    BaboomCompanionLayout,
    Rect,
    place_baboom_companion,
)
from .baboom_native_host import BaboomNativeHost
from .baboom_native_visual import (
    BaboomNativeVisualFrame,
    baboom_compact_message_size,
    baboom_sprite_source,
    project_baboom_native_visual_frame,
)
from .baboom_native_voice import (
    BaboomVoiceCancelled,
    BaboomVoiceError,
    BaboomVoiceInput,
)
from .baboom_visual_assets import BaboomSpriteAtlas


def foreground_window_rect_windows() -> Rect | None:
    """Read only the foreground window bounds; never capture its content."""
    try:
        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        bounds = wintypes.RECT()
        if not handle or not user32.GetWindowRect(handle, ctypes.byref(bounds)):
            return None
        width = bounds.right - bounds.left
        height = bounds.bottom - bounds.top
        if width < 1 or height < 1:
            return None
        return Rect(bounds.left, bounds.top, width, height)
    except (AttributeError, OSError):
        return None


def foreground_window_rects_windows() -> tuple[Rect, ...]:
    """Return zero or one foreground rectangle in the controller sequence form."""
    rect = foreground_window_rect_windows()
    return () if rect is None else (rect,)


_FOREGROUND_PROCESS_LABELS = {
    "acad.exe": "AutoCAD",
    "brave.exe": "Browser",
    "chrome.exe": "Browser",
    "code.exe": "VS Code",
    "codex.exe": "Codex",
    "cursor.exe": "Cursor",
    "excel.exe": "Excel",
    "explorer.exe": "Files",
    "firefox.exe": "Browser",
    "msedge.exe": "Browser",
    "powerpnt.exe": "PowerPoint",
    "revit.exe": "Revit",
    "rhino.exe": "Rhino",
    "3dsmax.exe": "3ds Max",
    "winword.exe": "Word",
}


def foreground_application_windows() -> str | None:
    """Return one released app label, never a window title or process path."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        handle = user32.GetForegroundWindow()
        process_id = wintypes.DWORD()
        if not handle or not user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id)):
            return None
        process = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not process:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32_768)
            length = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(length)
            ):
                return None
            executable = Path(buffer.value).name.casefold()
            return _FOREGROUND_PROCESS_LABELS.get(executable)
        finally:
            kernel32.CloseHandle(process)
    except (AttributeError, OSError):
        return None


def _message_beside(screen: Rect, sprite: Rect, width: int, height: int) -> Rect | None:
    """A report rectangle next to a sprite that stays where it is.

    Above or below first (the released placement's own preference), then to
    the side the screen has room on. The sprite never moves to make room for
    its own words -- a companion that hops to fit a sentence reads as broken.
    """
    if width <= 0 or height <= 0:
        return None
    clear = _clear_message(
        screen,
        sprite=sprite,
        message_width=width,
        message_height=height,
        gap=8,
        obstacles=(),
    )
    if clear is not None:
        return clear
    x = sprite.x - 8 - width
    if x < screen.x:
        x = sprite.right + 8
    try:
        return _bounded_rect(screen, width=width, height=height, x=x, y=sprite.y)
    except ValueError:
        return None


def render_baboom_native_sprite(
    atlas: Any,
    frame: BaboomNativeVisualFrame,
) -> Any:
    """Render only the frame crop onto a transparent sprite-sized image."""
    try:
        from PyQt6.QtCore import QRect, Qt
        from PyQt6.QtGui import QImage, QPainter
    except ImportError as exc:  # pragma: no cover - exercised by desktop packaging
        raise RuntimeError("BABOOM native companion requires PyQt6") from exc
    if atlas.isNull():
        raise ValueError("BABOOM native atlas image is invalid")
    source = frame.source
    if (
        source.right > atlas.width()
        or source.bottom > atlas.height()
        or frame.layout.sprite.width < 1
        or frame.layout.sprite.height < 1
    ):
        raise ValueError("BABOOM native sprite frame is outside its atlas")
    image = QImage(
        frame.layout.sprite.width,
        frame.layout.sprite.height,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(
        QRect(0, 0, image.width(), image.height()),
        atlas,
        QRect(source.x, source.y, source.width, source.height),
    )
    # The staff orb is the brain light: cyan when the brain answers and
    # holds facts, grey when it answers empty, red when it is down. It
    # follows the orb measured from the art for this exact pose.
    orb = getattr(frame, "orb", None)
    state = getattr(frame, "brain_state", "unknown")
    if orb is not None and state != "unknown":
        from PyQt6.QtGui import QColor, QRadialGradient
        colour = {"lit": QColor(126, 223, 211), "dim": QColor(150, 150, 150), "down": QColor(200, 68, 59)}[state]
        radius = max(6, round(image.width() * 0.09))
        glow = QRadialGradient(orb[0], orb[1], radius)
        core = QColor(colour); core.setAlpha(230); halo = QColor(colour); halo.setAlpha(0)
        glow.setColorAt(0.0, core); glow.setColorAt(1.0, halo)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(glow)
        painter.drawEllipse(orb[0] - radius, orb[1] - radius, radius * 2, radius * 2)
    painter.end()
    return image


# What the confirm control says for each act BABOOM performs. One question,
# one glyph, one progress line -- the founder always knows what he is pressing.
_BABOOM_ACT_PROMPTS = {
    "assign-task": ("Create this open task in ArchHub?", "Create the confirmed task"),
    "run-engine": ("Run this on the graph?", "Run it on the graph"),
    "agent-message": ("Send this to the agent?", "Send it to the agent"),
    "agent-interrupt": ("Interrupt that agent?", "Interrupt the agent"),
    "restart-to-update": ("Restart ArchHub to install it?", "Restart and install"),
    "open-host": ("Open it from ArchHub?", "Open the host"),
}
_BABOOM_ACT_GLYPHS = {
    "assign-task": "+", "run-engine": "▸", "agent-message": "→",
    "agent-interrupt": "■", "restart-to-update": "↻", "open-host": "△",
}
_BABOOM_ACT_PROGRESS = {
    "assign-task": "Creating task...", "run-engine": "Running on the graph...",
    "agent-message": "Sending...", "agent-interrupt": "Interrupting...",
    "restart-to-update": "Restarting...",
}


def compact_baboom_response_report(response: Mapping[str, object]) -> str:
    """Render the useful founder-safe detail from one graph command response.

    The physical companion receives only the response lens, never Cells or a
    Workshop export.  This keeps its small report factual and avoids creating a
    desktop-side task or conversation store.
    """
    summary = response.get("summary")
    fallback = " ".join(summary.split()) if isinstance(summary, str) else ""
    data = response.get("data")
    if not isinstance(data, Mapping):
        return fallback

    kind = response.get("kind")
    report = fallback
    if kind == "workshop-report":
        count = data.get("count")
        entries = data.get("entries")
        if type(count) is int and isinstance(entries, list) and entries:
            latest = entries[-1]
            if isinstance(latest, Mapping):
                entry_kind = latest.get("kind")
                entry_text = latest.get("text")
                if isinstance(entry_kind, str) and isinstance(entry_text, str):
                    report = f"Workshop: {count} entries. {entry_kind}: {entry_text}"
    elif kind == "governed-work-report":
        active = data.get("active")
        items = data.get("items")
        if type(active) is int and isinstance(items, list) and items:
            next_item = items[0]
            if isinstance(next_item, Mapping):
                state = next_item.get("state")
                title = next_item.get("title")
                model_state = next_item.get("model_state")
                if isinstance(state, str) and isinstance(title, str):
                    suffix = f"; model {model_state}" if isinstance(model_state, str) and model_state else ""
                    report = f"Work: {active} active. {state}: {title}{suffix}"
        elif type(active) is int:
            report = f"Work: {active} active."
    elif kind == "model-council-report":
        reviewed = data.get("reviewed_providers")
        admitted = data.get("admitted_providers")
        state = data.get("state")
        next_provider = data.get("next_provider")
        if isinstance(reviewed, list) and isinstance(admitted, list) and isinstance(state, str):
            report = f"Council: {len(reviewed)}/{len(admitted)} reviewed; {state.replace('-', ' ')}."
            if isinstance(next_provider, str) and next_provider:
                report += f" Next: {next_provider}."
    elif kind == "attention-briefing":
        focus = data.get("focus")
        blocked = data.get("blocked_obligations")
        if isinstance(focus, Mapping) and type(blocked) is int:
            label = focus.get("label")
            if isinstance(label, str):
                report = f"Focus: {label}. {blocked} blocked attention item(s)."
    elif kind == "steward-briefing":
        work = data.get("governed_work")
        workshop = data.get("workshop")
        attention = data.get("attention")
        if isinstance(work, Mapping) and isinstance(workshop, Mapping) and isinstance(attention, Mapping):
            active = work.get("active")
            entries = workshop.get("count")
            blocked = attention.get("blocked_obligations")
            if type(active) is int and type(entries) is int and type(blocked) is int:
                report = f"Work: {active} active. Workshop: {entries} entries. Attention: {blocked} blocked."
                items = work.get("items")
                if isinstance(items, list) and items and isinstance(items[0], Mapping):
                    state = items[0].get("state")
                    title = items[0].get("title")
                    if isinstance(state, str) and isinstance(title, str):
                        report += f" Next {state}: {title}."

    compact = " ".join(report.split())
    return compact if compact else "BABOOM has no report yet."


# A poll can land a few seconds late on a busy machine; that is not a dead server.
_FRAME_GRACE_SECONDS = 20.0
# Past this much silence the host is really gone (not merely busy); before it
# the last frame stays on screen so BABOOM never blinks.
_FRAME_SILENCE_SECONDS = 600.0


class BaboomNativeCompanionController:
    """Volatile visual controller; host snapshots remain the only input truth."""

    def __init__(
        self,
        host: BaboomNativeHost,
        atlas: BaboomSpriteAtlas,
        *,
        occupied_provider: Callable[[], Iterable[Rect]] = foreground_window_rects_windows,
    ) -> None:
        if type(host) is not BaboomNativeHost or type(atlas) is not BaboomSpriteAtlas:
            raise ValueError("BABOOM native companion configuration is invalid")
        if not callable(occupied_provider):
            raise ValueError("BABOOM occupied bounds provider is invalid")
        self._host = host
        self._atlas = atlas
        self._occupied_provider = occupied_provider
        self._user_origin: tuple[int, int] | None = None
        self._animation_tick = 0

    @property
    def latest_snapshot(self):
        """The host's newest snapshot, for the window that draws from it."""
        return self._host.latest_snapshot

    def pin_sprite_origin(self, x: int, y: int) -> None:
        """The founder put BABOOM here; it stays here until he moves it again."""
        self._user_origin = (int(x), int(y))
        self._pinned_layout = None

    def _occupied_rectangles(self) -> tuple[Rect, ...]:
        raw = self._occupied_provider()
        if raw is None:
            return ()
        if type(raw) is Rect:
            return (raw,)
        try:
            occupied = tuple(raw)
        except TypeError as exc:
            raise ValueError("BABOOM occupied bounds provider returned invalid data") from exc
        if any(type(item) is not Rect for item in occupied):
            raise ValueError("BABOOM occupied bounds provider returned invalid data")
        return occupied

    def next_frame(self, screen: Rect) -> BaboomNativeVisualFrame | None:
        """Project one host snapshot without polling, writing, or moving Work."""
        snapshot = self._host.latest_snapshot
        if snapshot is None:
            return None
        # A frame carries the lease the server gave it. When the server is
        # slow to renew it (a pipeline run, a relay answer, a probe holding
        # the store) the lease lapses for a few seconds. Hiding on every
        # lapse made BABOOM blink on the founder's desktop (2026-09-04
        # "keeps appearing and disappearing"). Presence first: the last
        # snapshot keeps drawing; the companion only ever disappears when
        # the host has been silent for a long time.
        if time.time() > float(snapshot.frame_expires_at) + _FRAME_SILENCE_SECONDS:
            return None
        frame = project_baboom_native_visual_frame(
            snapshot,
            self._atlas,
            screen=screen,
            occupied=self._occupied_rectangles(),
            animation_tick=self._animation_tick,
        )
        # A companion that recomputes its home every 750ms WANDERS: the
        # founder's foreground windows change, the placement search
        # answers differently, and the sprite hops around the desktop.
        # It lives in ONE place until the screen itself changes.
        user = self._user_origin
        if user is not None:
            # The founder dragged it here. His placement outranks every
            # search: BABOOM sits where he put it, and its report opens
            # beside it rather than moving it.
            base = frame.layout
            sprite = _bounded_rect(
                screen,
                width=base.sprite.width,
                height=base.sprite.height,
                x=user[0],
                y=user[1],
            )
            message = None
            if base.message is not None:
                message = _message_beside(
                    screen, sprite, base.message.width, base.message.height
                )
            layout = replace(
                base,
                sprite=sprite,
                message=message,
                edge="founder",
                overlap_area=0,
                collision_state="clear",
            )
            return replace(
                frame,
                layout=layout,
                report=frame.report if message is not None else None,
            )
        pinned = getattr(self, "_pinned_layout", None)
        pinned_screen = getattr(self, "_pinned_screen", None)
        if pinned is not None:
            if pinned_screen != screen:
                # The screen changed shape (a taskbar, a dock, a fullscreen
                # app). Keep the companion where it already is, clamped
                # inside the new bounds -- never search for a new home,
                # which is what made it jump across the desktop.
                sprite = _bounded_rect(
                    screen,
                    width=pinned.sprite.width,
                    height=pinned.sprite.height,
                    x=pinned.sprite.x,
                    y=pinned.sprite.y,
                )
                pinned = replace(pinned, sprite=sprite, message=None)
                self._pinned_layout = pinned
                self._pinned_screen = screen
            return replace(frame, layout=pinned)
        if frame.layout.collision_state == "clear":
            self._pinned_layout = frame.layout
            self._pinned_screen = screen
            return frame
        # A desktop with a maximised window has NO clear ground, and a
        # companion that answers that by vanishing is one nobody ever
        # sees. Every ambient Windows assistant solves this the same way:
        # sit in a screen corner, above the work, without the panel.
        # Presence first, politeness second.
        settled = project_baboom_native_visual_frame(
            snapshot,
            self._atlas,
            screen=screen,
            occupied=(),
            animation_tick=self._animation_tick,
        )
        self._pinned_layout = settled.layout
        self._pinned_screen = screen
        return settled

    def next_sprite_source(self, motion: str) -> Rect:
        """Advance only the released sprite crop; layout stays stable."""
        self._animation_tick += 1
        return baboom_sprite_source(
            self._atlas, motion=motion, animation_tick=self._animation_tick
        )

    def orb_for(self, motion: str, sprite_size: tuple[int, int]) -> tuple[int, int] | None:
        """The staff orb for the pose the CURRENT tick shows, scaled to the sprite.

        The orb travels with the arm; a light left at the previous pose"s orb
        floats beside the staff every other frame."""
        from .baboom_native_visual import _MOTION_ROWS
        row = _MOTION_ROWS[motion]
        raw = self._atlas.orb_point(row, self._animation_tick % self._atlas.frames_in_row(row))
        if raw is None:
            return None
        return (round(raw[0] * sprite_size[0] / self._atlas.cell_width),
                round(raw[1] * sprite_size[1] / self._atlas.cell_height))

    def respond(self, utterance: str) -> Mapping[str, object]:
        """Return a graph-backed response before any founder-confirmed action."""
        return self._host.respond_input(utterance)

    def execute(self, utterance: str) -> Mapping[str, object]:
        """Create only one explicit, graph-authorized founder task."""
        return self._host.execute_input(utterance)


def create_baboom_native_companion_window(
    controller: BaboomNativeCompanionController,
    *,
    on_response: Callable[[Mapping[str, object]], None] | None = None,
    voice_input: BaboomVoiceInput | None = None,
    position_path: Path | None = None,
) -> Any:
    """Create, but never show or start, the one transparent companion window."""
    if type(controller) is not BaboomNativeCompanionController:
        raise ValueError("BABOOM native companion controller is invalid")
    if on_response is not None and not callable(on_response):
        raise ValueError("BABOOM native companion response callback is invalid")
    if voice_input is not None and type(voice_input) is not BaboomVoiceInput:
        raise ValueError("BABOOM native companion voice input is invalid")
    try:
        from PyQt6.QtCore import QEvent, QPoint, QRect, QTimer, Qt, pyqtSignal
        from PyQt6.QtGui import QFont, QFontDatabase, QImage, QPainter
        from PyQt6.QtWidgets import QLineEdit, QLabel, QToolButton, QWidget
    except ImportError as exc:  # pragma: no cover - exercised by desktop packaging
        raise RuntimeError("BABOOM native companion requires PyQt6") from exc

    def companion_font() -> Any:
        """Load the installed Windows UI font when Qt has no discovered fonts."""
        windows_font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
        if windows_font.is_file():
            font_id = QFontDatabase.addApplicationFont(str(windows_font))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return QFont(families[0], 10)
        return QFont()

    class CompanionWindow(QWidget):
        response_ready = pyqtSignal(object)
        execution_ready = pyqtSignal(object)
        voice_ready = pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            self._atlas = QImage(str(controller._atlas.path))
            if self._atlas.isNull():
                raise ValueError("BABOOM native atlas cannot be loaded")
            if position_path is not None and position_path.is_file():
                # Where the founder last put it, across restarts.
                try:
                    remembered = json.loads(
                        position_path.read_text(encoding="utf-8")
                    )
                    controller.pin_sprite_origin(
                        int(remembered["x"]), int(remembered["y"])
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            self._frame: BaboomNativeVisualFrame | None = None
            self._layout: BaboomCompanionLayout | None = None
            self._sprite: Any = None
            self._origin = QPoint(0, 0)
            self._sprite_rect = QRect()
            self._message_rect: QRect | None = None
            self._transient_report: str | None = None
            self._transient_revision: int | None = None
            self._pending_task_utterance: str | None = None
            self._act_progress: str = ""
            self._submitted_utterance = ""
            self._interaction_requested = False
            self._press_global: Any = None
            self._press_window_pos: Any = None
            self._dragged = False
            self._position_path = position_path
            self._voice_input = voice_input or BaboomVoiceInput()
            self._voice_cancel: threading.Event | None = None
            self._companion_font = companion_font()
            self._report = QLabel(self)
            self._report.setFont(self._companion_font)
            self._report.setWordWrap(True)
            self._report.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self._report.setStyleSheet(
                "background:#181d20;color:#f1f4f5;border:0;padding:3px 6px;"
                "border-radius:0;font-size:12px;line-height:15px;"
            )
            self._input = QLineEdit(self)
            self._input.setFont(self._companion_font)
            self._input.setPlaceholderText("Reply or assign a task")
            self._input.setStyleSheet(
                "background:#181d20;color:#f1f4f5;border:0;padding:3px 6px;"
                "border-radius:0;font-size:12px;"
            )
            self._input.returnPressed.connect(self._submit_input)
            self._input.installEventFilter(self)
            self._input.hide()
            self._talk = QToolButton(self)
            self._talk.setText("Talk")
            self._talk.setToolTip("Speak one BABOOM command")
            self._talk.setAccessibleName("Speak one BABOOM command")
            self._talk.setStyleSheet(
                "background:transparent;color:#7edfd3;border:0;padding:0 6px;"
                "font-size:11px;font-weight:600;"
            )
            self._talk.clicked.connect(self._toggle_voice_capture)
            self._talk.hide()
            self._confirm = QToolButton(self)
            self._confirm.setText("+")
            self._confirm.setToolTip("Create the confirmed task")
            self._confirm.setAccessibleName("Create confirmed BABOOM task")
            self._confirm.setStyleSheet(
                "background:#27231a;color:#f6d781;border:0;border-radius:4px;"
                "font-size:16px;font-weight:600;"
            )
            self._confirm.clicked.connect(self._execute_task)
            self._confirm.hide()
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # Never let Qt or the system paint a background behind the sprite:
            # with the ask box open the founder saw the whole window rectangle
            # filled light grey with a rounded border around his companion.
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setStyleSheet("background:transparent;border:0;")
            self._projection_timer = QTimer(self)
            self._projection_timer.setInterval(750)
            self._projection_timer.timeout.connect(self.refresh)
            self._animation_timer = QTimer(self)
            # A companion that changes pose three times a second reads as
            # restless. It breathes, it does not fidget.
            self._animation_timer.setInterval(900)
            self._animation_timer.timeout.connect(self._advance_animation)
            self.response_ready.connect(self._apply_response)
            self.execution_ready.connect(self._apply_execution)
            self.voice_ready.connect(self._apply_voice)

        def start_projection(self) -> None:
            """Start paint and bounded projection checks; never start the host."""
            self._projection_timer.start()
            self._animation_timer.start()
            self.refresh()

        def stop_projection(self) -> None:
            self._projection_timer.stop()
            self._animation_timer.stop()

        def _screen_rect(self) -> Rect | None:
            # The screen the WINDOW happens to sit on is the wrong
            # authority at birth: a fresh frameless widget can be assigned
            # a secondary monitor and place the companion at a negative x,
            # off every visible desktop. The primary screen is where the
            # founder is.
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen() or self.screen()
            if screen is None:
                return None
            geometry = screen.availableGeometry()
            return Rect(geometry.x(), geometry.y(), geometry.width(), geometry.height())

        def _report_size(self, text: str) -> tuple[int, int]:
            """Size the report box from the REAL font, so nothing is clipped.

            The pure geometry assumes a fixed characters-per-line. That is
            close but not exact for the installed UI font, and the founder's
            own briefing wrapped one line further than the estimate: its last
            line fell outside the box, so he could not read the end of what
            BABOOM was telling him. Qt knows the true wrap, so it decides the
            height here. The estimate stays the floor.
            """
            width, minimum = baboom_compact_message_size(text)
            padding_x, padding_y = 12, 8
            wrapped = self._report.fontMetrics().boundingRect(
                QRect(0, 0, width - padding_x, 1 << 16),
                int(Qt.TextFlag.TextWordWrap),
                text,
            )
            return (width, max(minimum, wrapped.height() + padding_y))

        def _layout_for_report(
            self,
            frame: BaboomNativeVisualFrame,
            screen: Rect,
            report: str | None,
        ) -> BaboomCompanionLayout:
            """Re-place only when a longer transient report needs more height."""
            layout = frame.layout
            if not report:
                return layout
            message_size = self._report_size(report)
            if (
                layout.message is not None
                and
                layout.message.width == message_size[0]
                and layout.message.height == message_size[1]
            ):
                return layout
            # A longer report never relocates the companion; the report
            # opens beside it instead.
            message = _message_beside(
                screen, layout.sprite, message_size[0], message_size[1]
            )
            return replace(
                layout, message=message, overlap_area=0, collision_state="clear"
            )

        def _advance_animation(self) -> None:
            if self._frame is None or self._sprite is None or not self.isVisible():
                return
            # A companion that flips through poses while it has nothing to
            # say reads as broken, not alive. It breathes only when there
            # IS something: a report, or the founder talking to it.
            if self._frame.report is None and not self._interaction_requested:
                return
            sprite = self._frame.layout.sprite
            frame = replace(
                self._frame,
                source=controller.next_sprite_source(self._frame.motion),
                orb=controller.orb_for(self._frame.motion, (sprite.width, sprite.height)),
            )
            self._frame = frame
            self._sprite = render_baboom_native_sprite(self._atlas, frame)
            self.update()

        def refresh(self) -> None:
            if self._dragged:
                # A drag in progress owns the geometry; the 750ms
                # projection must not fight the founder's hand.
                return
            screen = self._screen_rect()
            if screen is None:
                return
            frame = controller.next_frame(screen)
            if frame is None:
                self.hide()
                return
            if (
                self._transient_revision is not None
                and self._transient_revision != frame.revision
                and self._pending_task_utterance is None
                and not self._input.isVisible()
            ):
                self._transient_report = None
                self._transient_revision = None
                self._interaction_requested = False
            report = self._transient_report or frame.report
            if report is None and self._interaction_requested:
                report = "Reply or assign a task"
            layout = self._layout_for_report(frame, screen, report)
            self._frame = frame
            self._layout = layout
            self._sprite = render_baboom_native_sprite(self._atlas, frame)
            bounds = layout.sprite
            if layout.message is not None:
                message = layout.message
                left = min(bounds.x, message.x)
                top = min(bounds.y, message.y)
                right = max(bounds.right, message.right)
                bottom = max(bounds.bottom, message.bottom)
            else:
                left, top, right, bottom = (
                    bounds.x, bounds.y, bounds.right, bounds.bottom
                )
            self._origin = QPoint(left, top)
            window_rect = QRect(left, top, right - left, bottom - top)
            if self.geometry() != window_rect:
                self.setGeometry(window_rect)
            sprite_rect = QRect(
                bounds.x - left, bounds.y - top, bounds.width, bounds.height
            )
            self._sprite_rect = sprite_rect
            if layout.message is None or report is None:
                self._report.hide()
                self._input.hide()
                self._talk.hide()
                self._confirm.hide()
                self._pending_task_utterance = None
                self._act_progress = ""
                self._interaction_requested = False
                self._message_rect = None
            else:
                message = layout.message
                message_rect = QRect(
                    message.x - left, message.y - top, message.width, message.height
                )
                self._message_rect = message_rect
                if not self._input.isVisible():
                    self._report.setText(report)
                    self._report.setGeometry(message_rect)
                    self._report.show()
                self._input.setGeometry(message_rect)
                if self._input.isVisible():
                    self._input.setTextMargins(0, 0, 40, 0)
                    self._talk.setGeometry(
                        message_rect.right() - 42, message_rect.top() + 4, 38, 22
                    )
                    self._talk.show()
                    self._talk.raise_()
                if self._confirm.isVisible():
                    self._confirm.setGeometry(
                        message_rect.right() - 28, message_rect.top() + 6, 22, 22
                    )
                    self._confirm.raise_()
            if not self.isVisible():
                self.show()
            self.update()

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            painter = QPainter(self)
            # Clear the whole window to transparent first, every paint, so no
            # frame and no fill ever shows around the sprite and its box.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self._sprite is not None and self._frame is not None:
                painter.drawImage(self._sprite_rect, self._sprite)
            painter.end()

        def showEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            super().showEvent(event)
            # Windows 11 draws a rounded corner and a 1px border on every
            # top-level window; on a transparent companion that border IS the
            # frame the founder saw. Tell the compositor: no corners, no border.
            try:
                import ctypes
                hwnd = int(self.winId())
                dwm = ctypes.windll.dwmapi
                corner = ctypes.c_int(1)          # DWMWCP_DONOTROUND
                dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(corner), 4)
                border = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
                dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 34, ctypes.byref(border), 4)
            except Exception:
                pass

        def _open_interaction(self) -> None:
            """Show the ask box: BABOOM is listening."""
            if self._frame is None or self._layout is None:
                return
            self._pending_task_utterance = None
            self._confirm.hide()
            self._transient_report = None
            self._transient_revision = None
            self._interaction_requested = True
            self.refresh()
            if self._message_rect is None:
                return
            self._report.hide()
            self._input.show()
            self._input.setTextMargins(0, 0, 40, 0)
            self._talk.setGeometry(
                self._message_rect.right() - 42,
                self._message_rect.top() + 4,
                38,
                22,
            )
            self._talk.show()
            self._talk.raise_()
            self._input.setFocus()

        def _close_interaction(self) -> None:
            """Back to the sprite alone: no box, no stale answer."""
            self._interaction_requested = False
            self._transient_report = None
            self._transient_revision = None
            self._pending_task_utterance = None
            self._input.clear()
            self._input.setEnabled(True)
            self._input.hide()
            self._talk.hide()
            self._confirm.hide()
            self._report.hide()
            self.refresh()

        def _save_position(self, x: int, y: int) -> None:
            if self._position_path is None:
                return
            try:
                self._position_path.parent.mkdir(parents=True, exist_ok=True)
                self._position_path.write_text(
                    json.dumps({"x": int(x), "y": int(y)}), encoding="utf-8"
                )
            except OSError:
                pass

        def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt callback name
            # Escape inside the ask box closes it, rather than leaving the
            # founder with a text field and no way out.
            if (
                obj is self._input
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self._close_interaction()
                return True
            return super().eventFilter(obj, event)

        def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if event.key() == Qt.Key.Key_Escape:
                self._close_interaction()
                return
            super().keyPressEvent(event)

        # Right-click: all of ArchHub, from the graph itself. Every entry is an
        # utterance the graph already answers or executes; nothing here is a
        # promise the runtime cannot keep.
        def _say(self, utterance: str) -> None:
            self._open_interaction()
            self._input.setText(utterance)
            self._submit_input()

        def _prefill(self, prefix: str) -> None:
            self._open_interaction()
            self._input.setText(prefix)
            self._input.setFocus()
            self._input.setCursorPosition(len(prefix))

        def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            from PyQt6.QtWidgets import QMenu
            # The window has no host of its own: it is a closure over the
            # controller, which holds the host. Reading self._host here raised
            # AttributeError on every right-click and the launcher's excepthook
            # turned that into "ArchHub could not open" (2026-09-06).
            snapshot = controller.latest_snapshot
            context = dict(getattr(snapshot, "context", {}) or {}) if snapshot is not None else {}
            menu = QMenu(self)
            brain = context.get("brain") or {}
            brain_line = ("Brain: %d facts" % int(brain.get("facts") or 0)) if brain.get("ok") else ("Brain: not answering" if brain.get("ok") is False else "Brain")
            b = menu.addMenu(brain_line)
            b.addAction("Ask the brain...", lambda: self._prefill(""))
            b.addAction("Remember...", lambda: self._prefill("remember: "))
            b.addAction("Recall on the graph", lambda: self._say("run brain.recall on the graph"))
            b.addAction("Brain health", lambda: self._say("brain health"))
            g = menu.addMenu("Graph: run on the canvas")
            for label, engine in (("Revit sessions", "revit.sessions"), ("Revit walls", "revit.read"), ("AutoCAD lines", "cad.host_lines"),
                                  ("Excel workbooks", "office.read"), ("Outlook inbox", "outlook.inbox"), ("3ds Max", "max.exec"),
                                  ("Rhino", "rhino.exec"), ("Blender", "blender.exec"), ("Notion search", "notion.search"),
                                  ("Dropbox files", "dropbox.list"), ("Connector status", "connector.status"), ("Skills catalogue", "skills.catalogue")):
                g.addAction(label, (lambda e=engine: self._say("run %s on the graph" % e)))
            w = menu.addMenu("Work")
            w.addAction("Assign a task...", lambda: self._prefill("Assign task: "))
            w.addAction("Take on this task...", lambda: self._prefill("take on this task: "))
            w.addAction("Show governed work", lambda: self._say("show governed work"))
            w.addAction("Show my plan", lambda: self._say("show my plan"))
            w.addAction("Claim next work", lambda: self._say("claim next work"))
            agents = (context.get("agents") or {}).get("working") or []
            a = menu.addMenu("Agents: %d working" % len(agents))
            for row in agents[:8]:
                a.addAction("%s on: %s" % (row.get("agent"), row.get("title")), lambda: self._say("show governed work"))
            a.addAction("Who is online", lambda: self._say("agents"))
            a.addAction("Tell an agent...", lambda: self._prefill("tell codex: "))
            a.addAction("Interrupt an agent...", lambda: self._prefill("interrupt codex"))
            a.addAction("Queue work for the agents...", lambda: self._prefill("Assign task: "))
            a.addAction("Send a task to a model...", lambda: self._prefill("assign task to claude: "))
            h = menu.addMenu("Hosts: open with ArchHub")
            for label, host in (("Excel", "excel"), ("Word", "word"), ("PowerPoint", "powerpoint"), ("Outlook", "outlook"),
                                ("Rhino (with bridge)", "rhino"), ("Blender (with add-on)", "blender")):
                h.addAction(label, (lambda hh=host: self._say("open " + hh)))
            k = menu.addMenu("Know")
            for label, phrase in (("Status", "status"), ("Brief me on ArchHub", "brief me on archhub"), ("What matters now", "what matters now"),
                                  ("Workshop report", "workshop report"), ("Model council", "model council"), ("My meetings", "check my meetings"),
                                  ("Capability map", "capability map"), ("Repo status", "repo status")):
                k.addAction(label, (lambda ph=phrase: self._say(ph)))
            menu.addSeparator()
            update = context.get("update") or {}
            if update.get("build_id"):
                menu.addAction("Restart to install build %s" % update["build_id"], lambda: self._say("restart-to-update"))
            else:
                menu.addAction("Check for updates", lambda: self._say("restart-to-update"))
            menu.addAction("Open the cockpit (api.archhub.io)", lambda: __import__("webbrowser").open("https://api.archhub.io/founder"))
            menu.addAction("Hide BABOOM until next launch", self.hide)
            menu.exec(event.globalPos())

        def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_global = event.globalPosition().toPoint()
                self._press_window_pos = self.pos()
                self._dragged = False
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if self._press_global is not None and (
                event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.globalPosition().toPoint() - self._press_global
                # A few pixels of travel separate a drag from a click, so a
                # slightly shaky click still opens the ask box.
                if self._dragged or delta.manhattanLength() > 4:
                    self._dragged = True
                    self.move(self._press_window_pos + delta)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._press_global is not None
            ):
                if self._dragged:
                    origin = self.pos() + self._sprite_rect.topLeft()
                    self._dragged = False
                    controller.pin_sprite_origin(origin.x(), origin.y())
                    self._save_position(origin.x(), origin.y())
                    self.refresh()
                elif self._input.isVisible() or self._transient_report is not None:
                    self._close_interaction()
                else:
                    self._open_interaction()
                self._press_global = None
                self._dragged = False
            super().mouseReleaseEvent(event)

        def _submit_input(self) -> None:
            utterance = self._input.text().strip()
            if not utterance:
                return
            self._submitted_utterance = utterance
            self._interaction_requested = False
            self._input.setEnabled(False)
            self._report.setText("Checking ArchHub...")
            self._report.show()
            self._input.hide()
            self._talk.hide()

            def resolve() -> None:
                try:
                    result: Mapping[str, object] = controller.respond(utterance)
                except Exception:
                    result = {
                        "response": {
                            "kind": "unavailable",
                            "summary": "BABOOM could not read the graph response.",
                            "data": {},
                        }
                    }
                self.response_ready.emit(result)

            threading.Thread(target=resolve, name="baboom-native-input", daemon=True).start()

        def _toggle_voice_capture(self) -> None:
            if self._voice_cancel is not None:
                self._voice_cancel.set()
                self._talk.setEnabled(False)
                return
            cancel = threading.Event()
            self._voice_cancel = cancel
            self._input.setEnabled(False)
            self._input.setPlaceholderText("Listening...")
            self._talk.setText("Stop")

            def capture() -> None:
                try:
                    result: Mapping[str, object] = {
                        "text": self._voice_input.capture_once(cancel=cancel)
                    }
                except BaboomVoiceCancelled:
                    result = {"cancelled": True}
                except BaboomVoiceError as exc:
                    result = {"error": str(exc)}
                self.voice_ready.emit(result)

            threading.Thread(
                target=capture, name="baboom-native-voice", daemon=True
            ).start()

        def _apply_voice(self, result: Mapping[str, object]) -> None:
            self._voice_cancel = None
            self._talk.setEnabled(True)
            self._talk.setText("Talk")
            self._input.setEnabled(True)
            self._input.setPlaceholderText("Reply or assign a task")
            text = result.get("text")
            if isinstance(text, str) and text.strip():
                self._input.setText(text)
                self._submit_input()
                return
            error = result.get("error")
            if isinstance(error, str) and error:
                self._transient_report = error
                self._transient_revision = (
                    self._frame.revision if self._frame is not None else None
                )
            self.refresh()

        def _apply_response(self, result: Mapping[str, object]) -> None:
            command = result.get("command")
            response = result.get("response")
            self._pending_task_utterance = None
            self._act_progress = ""
            self._interaction_requested = False
            self._confirm.hide()
            if isinstance(response, Mapping):
                self._transient_report = compact_baboom_response_report(response)
                self._transient_revision = (
                    self._frame.revision if self._frame is not None else None
                )
            # ANY act BABOOM can perform offers its confirm control -- the
            # graph says so by asking for an explicit execute. Gating this on
            # "assign-task" alone is what made BABOOM a reporter: running an
            # engine, telling an agent, interrupting one and installing an
            # update all reached this line and were dropped (2026-09-04).
            data = response.get("data") if isinstance(response, Mapping) else None
            offers_act = (
                isinstance(command, Mapping)
                and isinstance(response, Mapping)
                and isinstance(data, Mapping)
                and data.get("requires") == "explicit execute"
            )
            if offers_act:
                utterance = self._submitted_utterance
                if utterance:
                    intent = str(command.get("intent") or "")
                    question, label = _BABOOM_ACT_PROMPTS.get(
                        intent, ("Do this in ArchHub?", "Do it"))
                    self._pending_task_utterance = utterance
                    self._transient_report = question
                    self._act_progress = _BABOOM_ACT_PROGRESS.get(intent, "Working...")
                    self._confirm.setText(_BABOOM_ACT_GLYPHS.get(intent, "+"))
                    self._confirm.setToolTip(label)
                    self._confirm.setAccessibleName(label)
                    self._confirm.show()
            if self._pending_task_utterance is None:
                self._submitted_utterance = ""
            self._input.clear()
            self._input.setEnabled(True)
            self.refresh()
            if on_response is not None:
                on_response(result)

        def _execute_task(self) -> None:
            utterance = self._pending_task_utterance
            if not utterance:
                return
            self._pending_task_utterance = None
            self._confirm.hide()
            self._report.setText(self._act_progress or "Working...")
            self._report.show()

            def execute() -> None:
                try:
                    result: Mapping[str, object] = controller.execute(utterance)
                except Exception:
                    result = {"error": "BABOOM could not create the task."}
                self.execution_ready.emit(result)

            threading.Thread(
                target=execute, name="baboom-native-task", daemon=True
            ).start()

        def _apply_execution(self, result: Mapping[str, object]) -> None:
            created = result.get("created")
            if created is True:
                self._transient_report = "Task created in ArchHub."
            elif created is False:
                self._transient_report = "That task already exists in ArchHub."
            else:
                self._transient_report = "BABOOM could not create the task."
            self._transient_revision = (
                self._frame.revision if self._frame is not None else None
            )
            self._interaction_requested = False
            self.refresh()
            if on_response is not None:
                on_response({"execution": dict(result)})

    return CompanionWindow()


__all__ = [
    "BaboomNativeCompanionController",
    "compact_baboom_response_report",
    "create_baboom_native_companion_window",
    "foreground_application_windows",
    "foreground_window_rect_windows",
    "foreground_window_rects_windows",
    "render_baboom_native_sprite",
]
