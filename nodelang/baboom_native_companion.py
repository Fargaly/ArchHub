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
import os
from pathlib import Path
import threading
from typing import Any

from .baboom_companion_placement import (
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
    painter.end()
    return image


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
        self._animation_tick = 0

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
        frame = project_baboom_native_visual_frame(
            snapshot,
            self._atlas,
            screen=screen,
            occupied=self._occupied_rectangles(),
            animation_tick=self._animation_tick,
        )
        return frame if frame.layout.collision_state == "clear" else None

    def next_sprite_source(self, motion: str) -> Rect:
        """Advance only the released sprite crop; layout stays stable."""
        self._animation_tick += 1
        return baboom_sprite_source(
            self._atlas, motion=motion, animation_tick=self._animation_tick
        )

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
) -> Any:
    """Create, but never show or start, the one transparent companion window."""
    if type(controller) is not BaboomNativeCompanionController:
        raise ValueError("BABOOM native companion controller is invalid")
    if on_response is not None and not callable(on_response):
        raise ValueError("BABOOM native companion response callback is invalid")
    if voice_input is not None and type(voice_input) is not BaboomVoiceInput:
        raise ValueError("BABOOM native companion voice input is invalid")
    try:
        from PyQt6.QtCore import QPoint, QRect, QTimer, Qt, pyqtSignal
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
            self._frame: BaboomNativeVisualFrame | None = None
            self._layout: BaboomCompanionLayout | None = None
            self._sprite: Any = None
            self._origin = QPoint(0, 0)
            self._sprite_rect = QRect()
            self._message_rect: QRect | None = None
            self._transient_report: str | None = None
            self._transient_revision: int | None = None
            self._pending_task_utterance: str | None = None
            self._submitted_utterance = ""
            self._interaction_requested = False
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
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setStyleSheet("background:transparent;border:0;")
            self._projection_timer = QTimer(self)
            self._projection_timer.setInterval(750)
            self._projection_timer.timeout.connect(self.refresh)
            self._animation_timer = QTimer(self)
            self._animation_timer.setInterval(160)
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
            screen = self.screen()
            if screen is None:
                return None
            geometry = screen.availableGeometry()
            return Rect(geometry.x(), geometry.y(), geometry.width(), geometry.height())

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
            message_size = baboom_compact_message_size(report)
            if (
                layout.message is not None
                and
                layout.message.width == message_size[0]
                and layout.message.height == message_size[1]
            ):
                return layout
            occupied = controller._occupied_rectangles()
            return place_baboom_companion(
                screen,
                sprite_size=(layout.sprite.width, layout.sprite.height),
                message_size=message_size,
                occupied=occupied,
            )

        def _advance_animation(self) -> None:
            if self._frame is None or self._sprite is None or not self.isVisible():
                return
            frame = replace(
                self._frame,
                source=controller.next_sprite_source(self._frame.motion),
            )
            self._frame = frame
            self._sprite = render_baboom_native_sprite(self._atlas, frame)
            self.update()

        def refresh(self) -> None:
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
            if self._sprite is None or self._frame is None:
                return
            painter = QPainter(self)
            painter.drawImage(self._sprite_rect, self._sprite)
            painter.end()

        def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if self._frame is not None and self._layout is not None:
                self._pending_task_utterance = None
                self._confirm.hide()
                self._transient_report = None
                self._transient_revision = None
                self._interaction_requested = True
                self.refresh()
                if self._message_rect is None:
                    super().mousePressEvent(event)
                    return
                self._report.hide()
                self._input.show()
                if self._message_rect is not None:
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
            super().mousePressEvent(event)

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
            self._interaction_requested = False
            self._confirm.hide()
            if isinstance(response, Mapping):
                self._transient_report = compact_baboom_response_report(response)
                self._transient_revision = (
                    self._frame.revision if self._frame is not None else None
                )
            if (
                isinstance(command, Mapping)
                and command.get("intent") == "assign-task"
                and isinstance(response, Mapping)
                and response.get("kind") == "task-confirmation"
            ):
                utterance = self._submitted_utterance
                if utterance:
                    self._pending_task_utterance = utterance
                    self._transient_report = "Create this open task in ArchHub?"
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
            self._report.setText("Creating task...")
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
