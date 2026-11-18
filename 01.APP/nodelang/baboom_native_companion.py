"""Transparent native BABOOM companion projection.

This module is an explicit physical renderer for a connected ``BaboomNativeHost``.
It has no launcher, graph store, queue, authority, or lifecycle ownership. A
controlled desktop handoff may construct it only after the graph and physical
holder gates have cleared.
"""
from __future__ import annotations

from .settings_owner import THEME

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
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
    place_baboom_beside_composer,
    screen_at,
)
from .baboom_native_host import BaboomNativeHost
from .baboom_native_visual import (
    BaboomNativeVisualFrame,
    baboom_compact_message_size,
    baboom_sprite_source,
    project_baboom_native_visual_frame,
)
from .baboom_speech import compose_baboom_speech, plain_count, plain_title
from .baboom_persona import speech
from .baboom_visual_assets import BaboomSpriteAtlas


def desktop_input_idle_seconds() -> float:
    """Read input age only; no hooks, keystrokes or application content."""
    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]
    try:
        info = LastInput(ctypes.sizeof(LastInput), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return ((ctypes.windll.kernel32.GetTickCount() - info.tick) & 0xFFFFFFFF) / 1000
    except (AttributeError, OSError):
        return float("inf")


def foreign_foreground_window() -> bool:
    """Any foreign process, including applications with no host adapter."""
    try:
        process_id = wintypes.DWORD()
        getter = ctypes.windll.user32.GetForegroundWindow
        getter.restype = wintypes.HWND
        handle = getter()
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(process_id))
        return bool(handle and process_id.value != os.getpid())
    except (AttributeError, OSError):
        return False


def set_native_click_through(handle: int, idle: bool) -> None:
    """Idle layered sprite never consumes another application's input."""
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    get_style = user32.GetWindowLongW
    set_style = user32.SetWindowLongW
    style = get_style(ctypes.c_void_p(handle), -20)
    set_style(ctypes.c_void_p(handle), -20, style | 0x20 if idle else style & ~0x20)


def baboom_pixel_opaque(image: Any, x: int, y: int, *, alpha_floor: int = 16) -> bool:
    """True when this sprite pixel is visible enough to take a click."""
    if image is None or x < 0 or y < 0 or x >= image.width() or y >= image.height():
        return False
    return image.pixelColor(x, y).alpha() > alpha_floor


def baboom_opaque_hit_region(image: Any, origin_x: int = 0, origin_y: int = 0, *, alpha_floor: int = 16) -> Any:
    """Window region of one frame: opaque sprite pixels only.

    Transparent pixels are left out so the desktop underneath receives the click.
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QRegion

    region = QRegion()
    if image is None:
        return region
    width = image.width()
    height = image.height()
    for y in range(height):
        run: int | None = None
        for x in range(width + 1):
            opaque = x < width and baboom_pixel_opaque(image, x, y, alpha_floor=alpha_floor)
            if opaque and run is None:
                run = x
            elif not opaque and run is not None:
                region = region.united(QRegion(QRect(origin_x + run, origin_y + y, x - run, 1)))
                run = None
    return region


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
    # The crystal glows only when it has something to signal: cyan when the
    # brain answers with facts, red when it is down. A brain that answers empty
    # ("dim") shows no glow at all -- the grey light the founder read as a
    # fault is gone. The two live colours come from the product THEME.
    if orb is not None and state in ("lit", "down"):
        from PyQt6.QtGui import QColor, QRadialGradient
        colour = QColor(THEME["cyan"] if state == "lit" else THEME["err"])
        radius = max(6, round(image.width() * 0.09))
        glow = QRadialGradient(orb[0], orb[1], radius)
        core = QColor(colour); core.setAlpha(230); halo = QColor(colour); halo.setAlpha(0)
        glow.setColorAt(0.0, core); glow.setColorAt(1.0, halo)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(glow)
        painter.drawEllipse(orb[0] - radius, orb[1] - radius, radius * 2, radius * 2)
    painter.end()
    return image


# What the confirm control says for each act BABOOM performs: one question and
# one progress line. The button carries the action in words (below), never a
# glyph -- the founder always reads what he is pressing.
_BABOOM_ACT_PROMPTS = {
    "assign-task": ("Create this open task in ArchHub?", "Create the confirmed task"),
    "run-engine": ("Run this on the graph?", "Run it on the graph"),
    "agent-message": ("Send this to the agent?", "Send it to the agent"),
    "agent-interrupt": ("Interrupt that agent?", "Interrupt the agent"),
    "restart-to-update": ("Restart ArchHub to install it?", "Restart and install"),
    "open-host": ("Open it from ArchHub?", "Open the host"),
    "remember": ("Remember this in your Brain?", "Remember it"),
}
_BABOOM_EXECUTION_FAILED = "BABOOM could not create the task."


def baboom_execution_error_text(error: BaseException) -> str:
    """What the founder reads when a confirmed act does not complete.

    The graph's own refusal arrives as an authenticated MachineResponseError
    and is written for him ("Codex agents can't be interrupted ... Nothing was
    sent."). Swallowing it into "could not create the task" told him a Codex
    interrupt had failed to create a task (real-app acceptance 2026-10-01).
    Any other failure stays generic: its text was not written for him.
    """
    from .baboom_native_host import MachineResponseError
    text = str(error).strip() if isinstance(error, MachineResponseError) else ""
    return text[:400] if text else _BABOOM_EXECUTION_FAILED


_BABOOM_ACT_PROGRESS = {
    "assign-task": "Creating task...", "run-engine": "Running on the graph...",
    "agent-message": "Sending...", "agent-interrupt": "Interrupting...",
    "restart-to-update": "Restarting...", "remember": "Remembering...",
}


_WORK_STATE_SAID = {
    "open": "ready to claim", "claimed": "in progress",
    "blocked": "stuck", "review": "waiting for your review",
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
    # Sentences, not "Label: N." counters (founder, 2026-09-28).
    if kind == "workshop-report":
        entries = data.get("entries")
        if isinstance(entries, list) and entries and isinstance(entries[-1], Mapping):
            entry_kind = entries[-1].get("kind")
            entry_text = entries[-1].get("text")
            if isinstance(entry_kind, str) and isinstance(entry_text, str):
                text = " ".join(entry_text.split()).rstrip(" .")
                if entries[-1].get("protected") or text.startswith("[") or not text:
                    report = "The latest %s in the Workshop is protected." % entry_kind
                else:
                    report = "The latest %s in the Workshop reads: %s." % (entry_kind, text)
    elif kind == "governed-work-report":
        active = data.get("active")
        items = data.get("items")
        if type(active) is int:
            report = "%s %s active." % (
                plain_count(active, True), "job is" if active == 1 else "jobs are")
            if isinstance(items, list) and items and isinstance(items[0], Mapping):
                state = items[0].get("state")
                title = plain_title(items[0].get("title"))
                model_state = items[0].get("model_state")
                if isinstance(state, str) and title:
                    phrase = _WORK_STATE_SAID.get(state.casefold(), state)
                    report += " The next one is %s: %s." % (phrase, title)
                    if isinstance(model_state, str) and model_state:
                        report += " Its model is %s." % model_state
    elif kind == "model-council-report":
        reviewed = data.get("reviewed_providers")
        admitted = data.get("admitted_providers")
        state = data.get("state")
        next_provider = data.get("next_provider")
        if isinstance(reviewed, list) and isinstance(admitted, list) and isinstance(state, str):
            report = "%s of %s models %s reviewed; %s." % (
                plain_count(len(reviewed), True), plain_count(len(admitted)),
                "has" if len(reviewed) == 1 else "have", state.replace("-", " "))
            if isinstance(next_provider, str) and next_provider:
                report += " %s is next." % (next_provider[:1].upper() + next_provider[1:])
    elif kind == "attention-briefing":
        focus = data.get("focus")
        blocked = data.get("blocked_obligations")
        if isinstance(focus, Mapping) and type(blocked) is int:
            label = focus.get("label")
            if isinstance(label, str):
                said = ["Your focus is %s." % label.rstrip(" .")] if label.strip() else []
                said.append(
                    "%s %s your attention." % (
                        plain_count(blocked, True), "hold needs" if blocked == 1 else "holds need")
                    if blocked else "Nothing is on hold.")
                report = " ".join(said)
    elif kind == "steward-briefing":
        try:
            report = compose_baboom_speech(data)
        except ValueError:
            pass

    compact = " ".join(report.split())
    return compact if compact else "BABOOM has no report yet."


# In ArchHub BABOOM is the website's figure at the website's size (one-BABOOM spec 5: 80 x 87 frames).
_STANDING_SIZE = (80, 87)
# His one greeting a visit (spec 5, greeting bubble): when after he arrives, for how long, and the words.
GREETING_NODE = {"id": "baboom.greeting", "params": {
    "after_ms": 1200, "for_ms": 8000,
    "text": "Hi, I'm BABOOM. Ask me about ArchHub or your office standard."}}

# How he is drawn while he stands in ArchHub (spec 5: states, live dot, float, badge), as measured on the design
# prototype: an 80 x 100 box with the figure at its foot, a 46 x 9 ground glow 2 px below it, an 8 px live dot,
# an 18 px count badge, a 3 px float. A glow is a THEME colour and its strength; rest is the neutral shadow.
LOOK_NODE = {"id": "baboom.look", "params": {
    "box_height": 100, "ground": (46, 9), "ground_drop": 2, "rest_alpha": 0.45,
    "glow": {"working": ("accent", 0.7), "needs": ("warn", 0.8), "listening": ("cyan", 0.75)},
    "pulse_ms": {"working": 1400, "needs": 900}, "pulse_dim": 0.45, "pulse_squeeze": 0.8,
    "dot_px": 8, "dot_top": 10, "dot_right": 8, "dot_ring_px": 6, "dot_ring_alpha": 0.6, "dot_ring_turn": 0.7,
    "dot_pulse_ms": 2000, "float_px": 3, "float_ms": 3600,
    "badge_px": 18, "badge_top": 4, "badge_right": 6, "badge_pad": 5, "badge_ring_px": 2, "frame_ms": 200}}
_WORKING_STATES = ("thinking", "editing", "testing")


def baboom_ground_state(*, needs: int, working: bool, listening: bool) -> str:
    """The ground he stands on (spec 5, States): what needs you, then work, then listening, then rest."""
    return "needs" if needs > 0 else "working" if working else "listening" if listening else "rest"


def baboom_look_phase(now_ms: float, state: str) -> dict:
    """Where each of his motions is at this moment: the float, the glow pulse, the live dot's ring. Pure."""
    import math
    look = LOOK_NODE["params"]
    wave = lambda period: (1 - math.cos(2 * math.pi * (now_ms % period) / period)) / 2   # 0 -> 1 -> 0, eased
    pulse = wave(look["pulse_ms"][state]) if state in look["pulse_ms"] else 0.0
    turn, at = look["dot_ring_turn"], (now_ms % look["dot_pulse_ms"]) / look["dot_pulse_ms"]
    spread = at / turn if at < turn else (1 - at) / (1 - turn)                           # the ring grows, then returns
    return {"float": -round(look["float_px"] * wave(look["float_ms"])),
            "glow_alpha": 1 - (1 - look["pulse_dim"]) * pulse, "glow_width": 1 - (1 - look["pulse_squeeze"]) * pulse,
            "ring_px": look["dot_ring_px"] * spread, "ring_alpha": look["dot_ring_alpha"] * (1 - spread)}


# A poll can land a few seconds late on a busy machine; that is not a dead server.
_FRAME_GRACE_SECONDS = 20.0
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
        # How long the host has been silent, and where the window really
        # landed. Both exist so "BABOOM is not there" can be read off a file.
        self.host_silent_seconds = 0.0
        self._geometry_log = None

    def watch_geometry(self, path) -> None:
        """Record every geometry change to this file, newest last."""
        self._geometry_log = path

    def geometry_receipt(self, line: str) -> None:
        if self._geometry_log is None:
            return
        try:
            import time as _t
            from pathlib import Path as _Path
            from .log_rotation import GEOMETRY_LOG_BYTES, LOG_KEEP, LogRotator
            # Capped: 6.9 MB of geometry lines on one machine, 2026-09-24. A
            # refused rotation (file held open) backs off instead of retrying
            # on every receipt.
            rotator = getattr(self, "_geometry_rotator", None)
            if rotator is None or rotator.path != _Path(self._geometry_log):
                rotator = self._geometry_rotator = LogRotator(self._geometry_log, GEOMETRY_LOG_BYTES, LOG_KEEP)
            rotator()
            with open(self._geometry_log, "a", encoding="utf-8") as sink:
                sink.write("%s %s" % (_t.strftime("%H:%M:%S"), line) + chr(10))
        except Exception:
            pass

    @property
    def latest_snapshot(self):
        """The host's newest snapshot, for the window that draws from it."""
        return self._host.latest_snapshot

    def pin_sprite_origin(self, x: int, y: int) -> None:
        """The founder put BABOOM here; it stays here until he moves it again."""
        self._user_origin = (int(x), int(y))

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

    def _greeting_hour(self, directive) -> int | None:
        """Greet once per session: on the first thing BABOOM says, until it changes."""
        if not directive.get("action"):
            return None
        said = (directive.get("fingerprint"), directive.get("compact_message"))
        greeted = getattr(self, "_greeted", None)
        if greeted is None:
            greeted = self._greeted = (said, time.localtime().tm_hour)
        return greeted[1] if greeted[0] == said else None

    def next_frame(self, screen: Rect) -> BaboomNativeVisualFrame | None:
        """Project one host snapshot without polling, writing, or moving Work."""
        snapshot = self._host.latest_snapshot
        if snapshot is None:
            return None
        # Keep the revision-bound frame available for click-only details.
        self.host_silent_seconds = max(0.0, time.time() - float(snapshot.frame_expires_at))
        greeting_hour = self._greeting_hour(snapshot.directive)
        frame = project_baboom_native_visual_frame(
            snapshot,
            self._atlas,
            screen=screen,
            occupied=self._occupied_rectangles(),
            animation_tick=self._animation_tick,
            greeting_hour=greeting_hour,
            sprite_size=(52, 56),
        )
        if self.host_silent_seconds > _FRAME_GRACE_SECONDS or self._host.connection_state in {"closed", "reconnecting"}:
            frame = replace(frame, brain_state="unknown", action="", action_label="")
        return frame

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

    def respond(self, utterance: str, *, on_progress=None) -> Mapping[str, object]:
        """Return a graph-backed response before any founder-confirmed action."""
        return self._host.respond_input(utterance,
            **({"on_progress": on_progress} if on_progress is not None else {}))

    def execute(self, utterance: str) -> Mapping[str, object]:
        """Create only one explicit, graph-authorized founder task."""
        return self._host.execute_input(utterance)


# What the founder is working in right now, and the engine BABOOM can run
# for it. The companion used to know only where windows WERE, for placement;
# it never knew which app they belonged to, so it could not offer anything.
_FOREGROUND_HOSTS = {
    "revit.exe": ("Revit", "revit.read", "read the walls"),
    "acad.exe": ("AutoCAD", "cad.host_lines", "read the lines"),
    "excel.exe": ("Excel", "office.read", "read the workbook"),
    "winword.exe": ("Word", "office.read", "read the document"),
    "powerpnt.exe": ("PowerPoint", "office.read", "read the deck"),
    "outlook.exe": ("Outlook", "outlook.inbox", "read the inbox"),
    "rhino.exe": ("Rhino", "rhino.exec", "read the model"),
    "blender.exe": ("Blender", "blender.exec", "read the scene"),
    "3dsmax.exe": ("3ds Max", "max.exec", "read the scene"),
}

# What BABOOM can DO in the app in front, beyond reading it. These are the
# library engines that run with no parameters and write into the open
# model, so they live behind an explicit right-click pick, never behind the
# face click: a click on the face reads, a chosen menu line acts.
_FOREGROUND_ACTS = {
    "Revit": (
        ("tag the rooms in this view", "library.tag_rooms"),
        ("tag the doors in this view", "library.place_tags"),
        ("publish the sheets to PDF", "library.publish_pdf"),
    ),
}


def foreground_app_windows() -> tuple[str, str, str] | None:
    """(label, engine, verb) for the app in front, or None when it is not a host."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        handle = user32.GetForegroundWindow()
        if not handle:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if not pid.value:
            return None
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return None
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return None
        finally:
            kernel32.CloseHandle(process)
        exe = buffer.value.replace("/", chr(92)).rsplit(chr(92), 1)[-1].lower()
        return _FOREGROUND_HOSTS.get(exe)
    except Exception:
        return None


# Two lines of the compact box at the companion font. Beyond this the box
# either grows past the sprite or cuts a word; both read as broken.
FACE_MAX_CHARS = 72

# The companion menu paints itself from the product THEME (application.py),
# never a hand-typed colour. Terracotta stays the hover surface, but its label
# is THEME['on_fill'] (6.06:1) not white (3.12:1, which the founder could not
# read), the disabled row is THEME['ink_soft'] (5.54:1) not a faint grey, and a
# drop shadow lifts the menu instead of a 1px hairline border.
def _compose_menu_style() -> str:
    return (
        "QMenu {{ background: {bg}; color: {ink}; border: none;"
        " border-radius: 8px; padding: 5px; }}"
        "QMenu::item {{ padding: 7px 30px 7px 14px; border-radius: 5px;"
        " background: transparent; }}"
        "QMenu::item:selected {{ background: {accent}; color: {on_fill}; }}"
        "QMenu::item:disabled {{ color: {disabled}; }}"
        "QMenu::separator {{ height: 1px; background: {line}; margin: 5px 8px; }}"
        "QMenu::right-arrow {{ width: 9px; height: 9px; margin-right: 9px; }}"
    ).format(
        bg=THEME["bg_raised"], ink=THEME["ink"], accent=THEME["accent"],
        on_fill=THEME["on_fill"], disabled=THEME["ink_soft"], line=THEME["line"],
    )


_MENU_STYLE = _compose_menu_style()

# A cast shadow is black-with-alpha, not a palette hue, so it is an explicit,
# named exception to "every colour is a THEME token": pure black (0, 0, 0) at 38%
# opacity (97/255) for the menu's blur-20, 6px-down drop shadow.
_MENU_SHADOW_RGBA = (0, 0, 0, 97)


def _silence_said(seconds: float) -> str:
    minutes = int(seconds // 60)
    span = "under a minute" if minutes < 1 else "%d minute%s" % (minutes, "" if minutes == 1 else "s")
    return "I haven't heard from ArchHub in %s; live state is unavailable." % span


def baboom_face_line(context: Mapping[str, object], foreground: tuple[str, str, str] | None) -> tuple[str, str | None]:
    """A sentence or two of live graph state for BABOOM's face, and its offer.

    The founder said BABOOM did not show that it reflects the graph, and he
    was right: the state was there, in the snapshot, and only a right-click
    revealed it. This is what the companion says when nothing else is being
    said. It is built from the snapshot alone, never invented: a count that
    is missing is left out, not made up. It speaks in whole sentences, not
    dot-joined fragments (founder, 2026-09-28).
    """
    silent = context.get("host_silent_seconds") if isinstance(context, Mapping) else None
    if isinstance(silent, (int, float)) and silent > _FRAME_GRACE_SECONDS:
        # Never present an old count as live: the silence is all it says.
        return (_silence_said(silent), None)
    context = context if isinstance(context, Mapping) else {}
    said: list[str] = []
    offer = None
    # Priority order: what needs the founder, then what is wrong, then who is
    # working, then the canvas. Foreground-app offers stay in the menu only.
    workshop = context.get("workshop")
    pending = workshop.get("pending_founder_approvals") if isinstance(workshop, Mapping) else None
    if type(pending) is int and pending > 0:
        said.append("%s %s your approval in Workshop." % (
            pending, "thing needs" if pending == 1 else "things need"))
        offer = "open Workshop approvals"
    brain = context.get("brain")
    brain = brain if isinstance(brain, Mapping) else {}
    if brain.get("ok") is False:
        said.append("The brain is not answering.")
    attention = context.get("attention")
    blocked = attention.get("blocked_obligations") if isinstance(attention, Mapping) else None
    blocked = len(blocked) if isinstance(blocked, (list, tuple)) else blocked
    if type(blocked) is int and blocked > 0:
        said.append("%s %s your attention." % (
            plain_count(blocked, True), "hold needs" if blocked == 1 else "holds need"))
    agents = context.get("agents")
    working = agents.get("working") if isinstance(agents, Mapping) else None
    if isinstance(working, (list, tuple)) and working:
        said.append("%s %s working." % (
            plain_count(len(working), True), "agent is" if len(working) == 1 else "agents are"))
    # No canvas card counter and no "The brain is answering." line: the founder
    # read both as noise (2026-09-28), and baboom_speech (the one writer) omits
    # every internal counter and every calm all-clear. The face states only what
    # needs him -- what he is in front of, what is wrong, who is working.
    line = " ".join(said) if said else "I'm watching the graph."
    while len(line) > FACE_MAX_CHARS and len(said) > 1:
        said.pop()
        line = " ".join(said)
    return (line, offer)


def baboom_approval_html(approval: Mapping[str, object], binding: str) -> str:
    """Physical WebEngine adapter to the shipped shared card; no copied JSX."""
    from html import escape
    studio = Path(__file__).parent / "studio"
    sources = ["vendor/react.js", "vendor/react-dom.js", "compiled/tokens.js", "compiled/ds-index.js",
               "compiled/api.js", "compiled/icons.js", "compiled/ui.js"]
    scripts = "".join('<script src="%s"></script>' % escape((studio / source).resolve().as_uri(), quote=True)
        for source in sources)
    payload = json.dumps(dict(approval), ensure_ascii=True).replace("<", "\\u003c")
    identity = json.dumps(binding).replace("<", "\\u003c")
    return ('<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src file: qrc: \'unsafe-inline\'; style-src file: \'unsafe-inline\'; img-src data: file:">'
        '<style>html,body{margin:0;background:transparent}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}</style>'
        '<link rel="stylesheet" href="' + escape((studio / 'style.css').resolve().as_uri(), quote=True) + '">'
        '<script>window.ARCHHUB_NATIVE_APPROVAL={approval:' + payload + ',binding:' + identity + '};</script>'
        '<div id="approval"></div>' + scripts + '<script src="qrc:///qtwebchannel/qwebchannel.js"></script><script>'
        'document.documentElement.style.setProperty("--accent",window.AH.accent);'
        'window.ARCHHUB_APPROVAL_CARD=window.UI.ApprovalCard;'
        'new QWebChannel(qt.webChannelTransport,function(channel){const bridge=channel.objects.baboom;'
        'const approval=' + payload + ';const binding=' + identity + ';'
        'const decide=choice=>new Promise((resolve,reject)=>{'
        'if(choice==="decline"){bridge.choose(binding,choice);resolve();return;}'
        'const settle=(id,error)=>{if(id!==binding)return;bridge.settled.disconnect(settle);error?reject(new Error(error)):resolve();};'
        'bridge.settled.connect(settle);bridge.choose(binding,choice);});'
        'window.ARCHHUB_NATIVE_DECIDE=decide;'
        'ReactDOM.createRoot(document.getElementById("approval")).render(React.createElement(window.UI.Ctx.Provider,'
        '{value:{act:fn=>fn()}},React.createElement(window.ARCHHUB_APPROVAL_CARD,{id:approval.id||binding,compact:true})));});'
        '</script>')


def create_baboom_native_companion_window(
    controller: BaboomNativeCompanionController,
    *,
    on_response: Callable[[Mapping[str, object]], None] | None = None,
    position_path: Path | None = None,
    on_stop: Callable[[], None] | None = None,
    on_open: Callable[[], None] | None = None,
    on_open_task: Callable[[str], object] | None = None,
    reduced_motion: bool | None = None,
    work_rows: Callable[[], object] | None = None,
    sessions_directory: Callable[[], Path] | None = None,
) -> Any:
    """Create, but never show or start, the one transparent companion window."""
    if type(controller) is not BaboomNativeCompanionController:
        raise ValueError("BABOOM native companion controller is invalid")
    if on_response is not None and not callable(on_response):
        raise ValueError("BABOOM native companion response callback is invalid")
    if on_open_task is not None and not callable(on_open_task):
        raise ValueError("BABOOM task callback is invalid")
    if reduced_motion is not None and type(reduced_motion) is not bool:
        raise ValueError("BABOOM reduced motion parameter is invalid")
    if work_rows is not None and not callable(work_rows):
        raise ValueError("BABOOM work rows provider is invalid")
    if sessions_directory is not None and not callable(sessions_directory):
        raise ValueError("BABOOM skills directory provider is invalid")
    if work_rows is None:
        from .baboom_work_presence import read_workshop_task_rows
        work_rows = read_workshop_task_rows
    try:
        from PyQt6.QtCore import QEvent, QIODevice, QObject, QPoint, QRect, QSaveFile, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot
        from PyQt6.QtGui import QCursor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap, QColor
        from PyQt6.QtWidgets import QLabel, QMenu, QSystemTrayIcon, QToolButton, QToolTip, QWidget
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

    class ApprovalBridge(QObject):
        settled = pyqtSignal(str, str)

        @pyqtSlot(str, str)
        def choose(self, binding, choice):
            from .hook_decision import decide
            try:
                decide({"approval": "baboom", "owner": self.parent(), "id": binding, "decision": choice})
            except Exception as refused:  # a Qt slot must not raise; the card shows why
                self.settled.emit(binding, str(refused))

    class PositionWriter(QObject):
        failed = pyqtSignal(int)

        def save(self, path, x, y, revision):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                target = QSaveFile(str(path))
                data = json.dumps({"x": x, "y": y}).encode("utf-8")
                if not target.open(QIODevice.OpenModeFlag.WriteOnly) or target.write(data) != len(data) or not target.commit():
                    raise OSError(target.errorString())
            except OSError:
                self.failed.emit(revision)

    class CompanionWindow(QWidget):
        response_ready = pyqtSignal(object)
        execution_ready = pyqtSignal(object)
        progress_ready = pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            self._dismissed = False
            self._stopped = False
            self._shows_as = "Tray"
            self._details_open = False
            self._outage_since = None
            self._hover_since = None
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
            self._interaction_generation = 0
            self._busy = False
            self._response_received_at = 0.0
            self._response_owner = None
            self._result_visible = False
            self._steps: dict[str, Mapping[str, object]] = {}
            self._approval = None
            self._approval_binding = ""
            self._executing_approval_binding = ""
            self._approval_detail: Mapping[str, object] = {}
            self._approval_bridge = ApprovalBridge(self)
            self._press_global: Any = None
            self._press_window_pos: Any = None
            self._dragged = False
            self._work_presence = None
            self._transition_left = 0
            self._reduced_motion = reduced_motion
            self._work_rows = work_rows
            self._sessions_directory = sessions_directory
            self._skill_offer: dict[str, str] | None = None
            self._position_path = position_path
            self._position_revision = 0
            self._position_writer = PositionWriter()
            self._position_writer.failed.connect(self._position_save_failed)
            self._position_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="baboom-position")
            # With ArchHub (stand_with): its window, the pin setting, the composer door, and where the
            # window, its composer, the busy boxes and the screens are (follow_app).
            self._owner = self._pin = self._on_ask = self._beside = self._stood = self._app_screen = None
            self._pinned = False
            self._greeting = None  # None: not arrived yet; a time: arrived then; False: said or dismissed
            # What the page shows (follow_app): how many rows need him, his panel open; then how he is drawn now.
            self._needs, self._listening, self._look, self._phase = 0, False, None, None
            self._companion_font = companion_font()
            # Every companion colour comes from the product THEME, resolved once
            # here (lazy, so the renderer never hard-imports the application at
            # module load). No colour is hand-typed in this file. THEME['bg_raised']
            # is the one companion surface -- report and act panel -- so
            # nothing behind the words is ever the desktop showing through.
            self._theme = THEME
            self._report = QLabel(self)
            self._report.setFont(self._companion_font)
            self._report.setWordWrap(True)
            self._report.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self._report.setStyleSheet(
                "background:%s;color:%s;border:0;padding:12px;"
                "border-radius:0;font-size:13px;line-height:20px;"
                % (THEME["bg_raised"], THEME["ink"])
            )
            self._connection_status = QLabel("", self)
            self._connection_status.setAccessibleName("ArchHub connection status")
            self._connection_status.setStyleSheet("background:%s;border-radius:4px;" % THEME["warn"])
            self._connection_status.hide()
            # The confirm control carries the action in words, not a glyph, and a
            # labelled Cancel sits beside it so the founder always reads what he is
            # pressing and always has a way out. Confirm is the primary: the accent
            # fill with THEME['on_fill'] text (6.06:1), the pairing the design
            # system added precisely because white on accent measures 3.12:1.
            self._confirm = QToolButton(self)
            self._confirm.setText("Confirm")
            self._confirm.setToolTip("Create the confirmed task")
            self._confirm.setAccessibleName("Create confirmed BABOOM task")
            self._confirm.setStyleSheet(
                "background:%s;color:%s;border:0;border-radius:4px;padding:0 8px;"
                "font-size:11px;font-weight:600;"
                % (THEME["accent"], THEME["on_fill"])
            )
            self._confirm.clicked.connect(self._show_approval)
            self._confirm.hide()
            self._cancel = QToolButton(self)
            self._cancel.setText("Cancel")
            self._cancel.setToolTip("Dismiss without acting")
            self._cancel.setAccessibleName("Cancel the BABOOM action")
            self._cancel.setStyleSheet(
                "background:transparent;color:%s;border:0;padding:0 6px;"
                "font-size:11px;" % THEME["ink_muted"]
            )
            self._cancel.clicked.connect(self._close_interaction)
            self._cancel.hide()
            self._state_bubble = QLabel(self)
            self._state_bubble.setFont(self._companion_font)
            self._state_bubble.setWordWrap(True)
            self._state_bubble.setTextFormat(Qt.TextFormat.RichText)
            self._state_bubble.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
            self._state_bubble.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._state_bubble.linkActivated.connect(lambda _link: self._open_work_task())
            self._state_bubble.setStyleSheet(
                "background:%s;color:%s;border:0;padding:4px;font-size:11px;"
                % (THEME["bg_raised"], THEME["ink"])
            )
            self._state_bubble.hide()
            self._state_badge = QLabel("!", self)
            self._state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._state_badge.setAccessibleName("BABOOM needs you")
            look = LOOK_NODE["params"]
            self._badge_styles = (
                "background:%s;color:%s;border:0;border-radius:8px;font-size:11px;font-weight:600;"
                % (THEME["accent"], THEME["on_fill"]),
                "background:%s;color:%s;border:%dpx solid %s;border-radius:%dpx;font-size:11px;font-weight:600;"
                % (THEME["warn"], THEME["on_fill"], look["badge_ring_px"], THEME["bg"],
                   look["badge_px"] // 2 + look["badge_ring_px"]))
            self._state_badge.setStyleSheet(self._badge_styles[0])
            self._state_badge.hide()
            self._skill_run = QToolButton(self)
            self._skill_run.setText("Run")
            self._skill_run.setAccessibleName("Run the matching skill")
            self._skill_run.setToolTip("Run the saved skill on the dropped file")
            self._skill_run.setStyleSheet(
                "background:%s;color:%s;border:0;border-radius:4px;padding:0 8px;"
                "font-size:11px;font-weight:600;"
                % (THEME["accent"], THEME["on_fill"])
            )
            self._skill_run.clicked.connect(self._run_offered_skill)
            self._skill_run.hide()
            self.setAcceptDrops(True)
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # Never let Qt or the system paint a background behind the sprite:
            # with the ask box open the founder saw the whole window rectangle
            # filled light grey with a rounded border around his companion.
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setStyleSheet("background:transparent;border:0;")
            self._projection_timer = QTimer(self)
            self._projection_timer.setInterval(750)
            self._projection_timer.timeout.connect(self.refresh)
            self._reaction_state = 'idle'
            self._reaction_timer = QTimer(self)
            from .baboom_reactions import REACTION_NODE
            self._reaction_timer.setInterval(REACTION_NODE['params']['poll_ms'])
            self._reaction_timer.timeout.connect(self._check_reactions)
            self._animation_timer = QTimer(self)
            # A companion that changes pose three times a second reads as
            # restless. It breathes, it does not fidget.
            self._animation_timer.setInterval(900)
            self._animation_timer.timeout.connect(self._advance_animation)
            self._look_timer = QTimer(self)  # his float, glow pulse and live dot: paint only, from the clock
            self._look_timer.setInterval(LOOK_NODE["params"]["frame_ms"])
            self._look_timer.timeout.connect(self._advance_look)
            # A single click asks BABOOM. The same interval Windows
            # uses for a double-click lets that second click open ArchHub
            # instead, without the composer taking the caret first.
            from PyQt6.QtWidgets import QApplication
            self._quiet_click = QTimer(self)
            self._quiet_click.setSingleShot(True)
            app = QApplication.instance()
            interval = 400
            if app is not None:
                interval = max(200, int(app.styleHints().mouseDoubleClickInterval()))
            self._quiet_click.setInterval(interval)
            self._quiet_click.timeout.connect(self._open_from_click)
            self.response_ready.connect(self._apply_response)
            self.execution_ready.connect(self._apply_execution)
            self.progress_ready.connect(self._apply_progress)
            # The last host seen in front, and when: the right-click that opens
            # the menu activates this window, so the menu cannot ask then.
            self._front: tuple[str, str, str] | None = None
            self._front_at = 0.0
            self._tray = QSystemTrayIcon(self)
            self._tray_menu = QMenu(self)
            self._tray_menu.setStyleSheet(_MENU_STYLE)
            self._tray_open = self._tray_menu.addAction("Open ArchHub", self._open_archhub)
            self._tray_menu.addAction("Ask BABOOM…", lambda: self._open_interaction())
            self._tray_menu.addAction("BABOOM menu…", self._open_menu)
            self._tray_menu.addSeparator()
            self._tray_menu.addAction("Stop BABOOM for this launch", self.stop_baboom)
            self._tray.setContextMenu(self._tray_menu)
            self._tray.activated.connect(self._tray_activated)

        def _tray_activated(self, reason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                if self._result_visible and self._transient_report:
                    self._details_open = True
                    set_native_click_through(int(self.winId()), False)
                    self.refresh()
                else:
                    self._open_interaction()

        def _open_menu(self) -> None:
            from PyQt6.QtGui import QContextMenuEvent
            self.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(), QCursor.pos()))

        def _presence(self, frame) -> None:
            snapshot = controller.latest_snapshot
            context = snapshot.context if snapshot is not None else {}
            mode = context.get("shows_as", self._shows_as)
            self._shows_as = mode if mode in ("Screen", "Tray", "Hidden") else "Tray"
            stale = (controller._host.connection_state != "live"
                     or controller.host_silent_seconds > _FRAME_GRACE_SECONDS)
            now = time.monotonic()
            self._outage_since = (self._outage_since if self._outage_since is not None else now) if stale else None
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            icon = (render_baboom_native_sprite(self._atlas, frame) if frame is not None
                    else self._atlas.copy(0, 0, controller._atlas.cell_width, controller._atlas.cell_height))
            painter.drawImage(QRect(0, 0, 32, 32), icon)
            if stale:
                painter.setBrush(QColor(self._theme["warn"]))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(23, 23, 8, 8)
            painter.end()
            self._tray.setIcon(QIcon(pixmap))
            self._tray.setToolTip("BABOOM · " + ("Reconnecting to ArchHub" if stale else "Connected"))
            long_outage = self._outage_since is not None and now - self._outage_since >= 300
            self._tray_open.setText("ArchHub is closed · Open" if long_outage else "Open ArchHub")
            self._tray.setVisible(self._shows_as != "Hidden")
            self._connection_status.setVisible(stale and self._shows_as == "Screen" and not self._details_open)
            self._connection_status.setToolTip(self._tray.toolTip())

        def _motion_reduced(self) -> bool:
            from .baboom_work_presence import baboom_reduced_motion
            return baboom_reduced_motion(parameter=self._reduced_motion)

        def _timers_active(self) -> bool:
            presence = self._work_presence
            working = presence is not None and presence.state != "idle"
            reporting = self._frame is not None and self._frame.report is not None
            return bool(
                self._details_open or self._interaction_requested or reporting
                or working or self._transition_left > 0 or self._skill_offer is not None
            )

        def _sync_resource_timers(self) -> None:
            """Keep polling until dismissed; hidden and idle sprites need no animation."""
            if self._dismissed or self._stopped:
                self._projection_timer.stop()
                self._reaction_timer.stop()
                self._animation_timer.stop()
                self._look_timer.stop()
                return
            self._projection_timer.setInterval(750 if self._timers_active() else 5000)
            if not self._projection_timer.isActive():
                self._projection_timer.start()
            if not self._reaction_timer.isActive():
                self._reaction_timer.start()
            moving = self._look is not None and self.isVisible() and not self.isMinimized() and not self._motion_reduced()
            if moving != self._look_timer.isActive():
                self._look_timer.start() if moving else self._look_timer.stop()
            if not self.isVisible() or self.isMinimized() or self._motion_reduced() or not self._timers_active():
                self._animation_timer.stop()
                return
            self._animation_timer.setInterval(125 if self._transition_left > 0 else 900)
            if not self._animation_timer.isActive():
                self._animation_timer.start()

        def _check_reactions(self):
            if self._dismissed or self._stopped or self._dragged:
                return
            from .baboom_reactions import latest_soon
            reaction = latest_soon()  # never read files on the GUI thread
            state = reaction.state if reaction is not None else 'idle'
            if state != self._reaction_state:
                self._reaction_state = state
                self.refresh()

        def _overlay_work_pose(self, frame):
            from .baboom_work_presence import BaboomWorkPresence, baboom_work_presence
            previous = self._work_presence.state if self._work_presence is not None else "idle"
            reduced = self._motion_reduced()
            try:
                presence = baboom_work_presence(self._work_rows())
            except Exception:
                presence = BaboomWorkPresence("idle", "", "idle", False, "")
            from .baboom_reactions import latest_soon
            from .baboom_persona import speech
            reaction = latest_soon()
            if reaction is not None:
                presence = reaction
            snapshot = controller.latest_snapshot
            work = snapshot.context.get("work", {}) if snapshot is not None else {}
            active = work.get("active_turns", 0) if isinstance(work, Mapping) else 0
            if presence.state in {"idle", "done"} and (self._busy or (type(active) is int and active > 0)):
                name = self._submitted_utterance or "Working on your request"
                presence = BaboomWorkPresence("thinking", name, "think", False, name)
            if presence.state == "idle" and self._greeting_due():
                presence = BaboomWorkPresence("needs-you", "", "wave", False, GREETING_NODE["params"]["text"])
            if presence.bubble:
                from dataclasses import replace
                presence = replace(presence, bubble=speech(presence.bubble))
            if reduced:
                self._transition_left = 0
            elif presence.state != previous:
                self._transition_left = 4
            self._work_presence = presence
            return self._posed_frame(frame, bump=False)

        def _posed_frame(self, frame, *, bump: bool):
            from .baboom_native_visual import _MOTION_ROWS, baboom_sprite_source
            from .baboom_work_presence import baboom_pose_motion
            reduced = self._motion_reduced()
            if bump and not reduced:
                controller.next_sprite_source("idle")
            presence = self._work_presence
            state = presence.state if presence is not None else "idle"
            if reduced:
                self._transition_left = 0
            motion = baboom_pose_motion(
                state,
                controller._animation_tick,
                reduced_motion=reduced,
                transitioning=self._transition_left > 0 and not reduced,
            )
            if presence is not None and presence.motion in ('ponder', 'present'):
                motion = presence.motion
            shown = 0 if reduced else controller._animation_tick
            source = baboom_sprite_source(
                controller._atlas, motion=motion, animation_tick=shown
            )
            row = _MOTION_ROWS[motion]
            count = controller._atlas.frames_in_row(row)
            raw = controller._atlas.orb_point(row, shown % count)
            sprite = frame.layout.sprite
            orb = None if raw is None else (
                round(raw[0] * sprite.width / controller._atlas.cell_width),
                round(raw[1] * sprite.height / controller._atlas.cell_height),
            )
            return replace(frame, motion=motion, source=source, orb=orb)

        def _place_idle_chrome(self, spot: Rect, edge: str) -> None:
            """Keep the glyph on the edge. A state bubble sits inward of it."""
            x, y, width, height = spot.x, spot.y, spot.width, spot.height
            presence = self._work_presence
            text = ""
            badge = False
            if presence is not None and presence.state != "idle":
                text = presence.bubble
                badge = presence.badge
            self._state_bubble.hide()
            self._state_badge.hide()
            # In ArchHub he is the designed figure; away from it he stays the small desktop glyph.
            self._look = baboom_ground_state(
                needs=self._needs or int(badge), listening=self._listening,
                working=presence is not None and presence.state in _WORKING_STATES,
            ) if self._beside is not None and self._beside[0] is not None else None
            look = LOOK_NODE["params"]
            head, drop = (look["box_height"] - height, look["ground_drop"]) if self._look is not None else (0, 0)
            bubble_w = bubble_h = 0
            if text:
                from html import escape
                linked = on_open_task is not None and presence is not None and bool(presence.task_id)
                self._state_bubble.setText(('<a href="task" style="color:%s">%s</a>' % (self._theme["ink"], escape(text))) if linked else escape(text))
                self._state_bubble.setToolTip("Open task and full result" if linked else text)
                bubble_w = min(200, max(80, self._state_bubble.fontMetrics().horizontalAdvance(text) + 16))
                bubble_h = max(24, int(self._state_bubble.heightForWidth(bubble_w) or 24))
            gap = 6
            if text and edge == "right":
                origin_x, origin_y = x - gap - bubble_w, y
                sprite_x, sprite_y = gap + bubble_w, 0
                bubble_x, bubble_y = 0, 0
                win_w, win_h = width + gap + bubble_w, max(height, bubble_h)
            elif text and edge == "left":
                origin_x, origin_y = x, y
                sprite_x, sprite_y = 0, 0
                bubble_x, bubble_y = width + gap, 0
                win_w, win_h = width + gap + bubble_w, max(height, bubble_h)
            elif text and edge == "bottom":
                origin_x, origin_y = x, y - gap - bubble_h
                sprite_x, sprite_y = 0, gap + bubble_h
                bubble_x, bubble_y = 0, 0
                win_w, win_h = max(width, bubble_w), height + gap + bubble_h
            elif text:
                origin_x, origin_y = x, y
                sprite_x, sprite_y = 0, 0
                bubble_x, bubble_y = 0, height + gap
                win_w, win_h = max(width, bubble_w), height + gap + bubble_h
            else:
                origin_x, origin_y = x, y
                sprite_x = sprite_y = 0
                win_w, win_h = width, height
            # His box has room above him for the live dot and the badge, and below his feet for the ground glow.
            self.setGeometry(origin_x, origin_y - head, win_w, win_h + head + drop)
            self._sprite_rect = QRect(sprite_x, sprite_y + head, width, height)
            self._connection_status.setGeometry(
                self._sprite_rect.right() - 12, self._sprite_rect.bottom() - 12, 8, 8
            )
            if text:
                self._state_bubble.setGeometry(bubble_x, bubble_y + head, bubble_w, bubble_h)
                self._state_bubble.show()
                self._state_bubble.raise_()
            style = self._badge_styles[self._look is not None]
            if self._state_badge.styleSheet() != style:
                self._state_badge.setStyleSheet(style)
            count = self._needs if self._look is not None else 0
            badge_text = str(count) if count else "!"
            if self._state_badge.text() != badge_text:
                self._state_badge.setText(badge_text)
                self._state_badge.setAccessibleName(f"BABOOM needs you ({count})" if count else "BABOOM needs you")
            if self._look is not None:
                # The number is Home's own count of what needs him; an agent waiting with no row yet keeps the mark.
                self._float_badge()
                badge = badge or self._needs > 0
            elif badge:
                self._state_badge.setGeometry(self._sprite_rect.right() - 16, self._sprite_rect.top(), 16, 16)
            if badge:
                self._state_badge.show()
                self._state_badge.raise_()

        def _float_badge(self) -> None:
            """The count badge, top right of his box; it floats with him."""
            look, box = LOOK_NODE["params"], self._sprite_rect
            ring, size = look["badge_ring_px"], look["badge_px"]
            self._state_badge.ensurePolished()
            width = max(size, self._state_badge.fontMetrics().horizontalAdvance(self._state_badge.text()) + 2 * look["badge_pad"])
            top = box.y() + box.height() - look["box_height"] + look["badge_top"] + self._look_phase()["float"]
            self._state_badge.setGeometry(box.x() + box.width() - look["badge_right"] - width - ring, top - ring,
                                          width + 2 * ring, size + 2 * ring)

        def _look_rects(self) -> list:
            """What the look paints outside the figure, in window pixels: the ground glow, and the live dot with its ring."""
            look, box = LOOK_NODE["params"], self._sprite_rect
            (width, height), reach, size = look["ground"], look["dot_ring_px"], look["dot_px"]
            foot = box.y() + box.height()
            return [QRect(box.x() + (box.width() - width) // 2, foot + look["ground_drop"] - height, width, height),
                    QRect(box.x() + box.width() - look["dot_right"] - size - reach,
                          foot - look["box_height"] + look["dot_top"] - reach, size + 2 * reach, size + 2 * reach)]

        def _dot_shown(self) -> bool:
            """The live dot: he can answer (the brain is up) and his panel is closed."""
            return (self._look is not None and not self._listening
                    and self._frame is not None and self._frame.brain_state in ("lit", "dim"))

        def _look_phase(self) -> dict:
            """Where his motions are now; with the look timer stopped (reduced motion) he holds the first frame."""
            if self._phase is not None and self._look_timer.isActive():
                return self._phase
            return baboom_look_phase(0, self._look)

        def _advance_look(self) -> None:
            """One step of his float, glow pulse and live dot: paint only, from the clock; no read, no layout."""
            if self._look is None or self._dragged:
                return
            phase, shown = baboom_look_phase(time.monotonic() * 1000, self._look), self._phase
            self._phase = phase
            ground, dot = self._look_rects()
            lift = LOOK_NODE["params"]["float_px"]
            if shown is None or phase["float"] != shown["float"]:
                self._float_badge()
                self.update(self._sprite_rect.united(ground).united(dot).adjusted(0, -lift, 0, 0))
            else:
                if self._dot_shown():
                    self.update(dot.translated(0, phase["float"]))
                if self._look in LOOK_NODE["params"]["pulse_ms"]:
                    self.update(ground.translated(0, phase["float"]))

        def _paint_look(self, painter) -> None:
            """Draw him as designed: floating, the live dot at his shoulder, the ground glow of his state under his feet."""
            from PyQt6.QtCore import QPointF, QRectF
            from PyQt6.QtGui import QRadialGradient
            look, phase = LOOK_NODE["params"], self._look_phase()
            ground, dot = self._look_rects()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.translate(0, phase["float"])
            painter.drawImage(self._sprite_rect, self._sprite)
            if self._dot_shown():
                colour, centre, radius = QColor(THEME["cyan"]), QRectF(dot).center(), look["dot_px"] / 2
                ring = QColor(colour)
                ring.setAlphaF(phase["ring_alpha"])
                painter.setBrush(ring)
                painter.drawEllipse(centre, radius + phase["ring_px"], radius + phase["ring_px"])
                painter.setBrush(colour)
                painter.drawEllipse(centre, radius, radius)
            # The ground: neutral shadow at rest, his state's colour otherwise, strongest under him, gone at its edge.
            token, strength = look["glow"].get(self._look, (None, look["rest_alpha"]))
            core = QColor(THEME[token]) if token else QColor(Qt.GlobalColor.black)
            core.setAlphaF(strength * phase["glow_alpha"])
            edge = QColor(core)
            edge.setAlpha(0)
            glow = QRadialGradient(0, 0, 1)
            glow.setColorAt(0.0, core)
            glow.setColorAt(1.0, edge)
            painter.translate(ground.x() + ground.width() / 2, ground.y() + ground.height() / 2)
            painter.scale(ground.width() / 2 * phase["glow_width"], ground.height() / 2)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(0, 0), 1, 1)

        def _idle_presence(self, screen, frame) -> None:
            self._stood = sprite = self._home()
            edge = "right"
            if sprite is None:
                # One small glyph, always at an edge; never search through work areas.
                with_app = self._beside is not None and self._beside[0] is not None
                width, height = _STANDING_SIZE if with_app else (56, 56)
                x, y = self._free_spot() or (screen.right - width, screen.bottom - height)
                x = min(max(x, screen.x), screen.right - width)
                y = min(max(y, screen.y), screen.bottom - height)
                edge = min(((x - screen.x, "left"), (screen.right - width - x, "right"),
                            (y - screen.y, "top"), (screen.bottom - height - y, "bottom")))[1]
                if edge in ("left", "right"):
                    x = screen.x if edge == "left" else screen.right - width
                else:
                    y = screen.y if edge == "top" else screen.bottom - height
                sprite = Rect(x, y, width, height)
            self._layout = replace(frame.layout, sprite=sprite, message=None, edge=edge)
            self._frame = replace(frame, layout=self._layout, report=None)
            self._sprite = render_baboom_native_sprite(self._atlas, self._frame)
            self._message_rect = None
            for widget in (
                self._report, self._confirm, self._cancel, self._skill_run,
            ):
                widget.hide()
            if self._approval is not None:
                self._approval.hide()
            self._place_idle_chrome(sprite, edge)
            if self._shows_as != "Screen":
                self._state_bubble.hide()
                self._state_badge.hide()
                self._animation_timer.stop()
                self.hide()
                self._sync_resource_timers()
                return
            # The mask is the hit target. Opaque sprite pixels take the click;
            # transparent pixels are not part of the window, so they fall
            # through to the desktop. The whole window is never click-through.
            self._apply_hit_mask()
            if self._stood is not None and self._greeting is None:
                # He has just come to stand in ArchHub: the one greeting of this visit is due.
                self._greeting = time.monotonic()
                QTimer.singleShot(GREETING_NODE["params"]["after_ms"], self.refresh)
            set_native_click_through(int(self.winId()), False)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            if not self.isVisible():
                self.show()
            self._sync_resource_timers()
            self.update()

        def start_projection(self) -> None:
            """Start paint and bounded projection checks; never start the host."""
            if self._stopped:
                return
            self._dismissed = False
            self._projection_timer.start()
            self._reaction_timer.start()
            self._animation_timer.start()
            self.refresh()

        def stop_projection(self) -> None:
            self._dismissed = True
            self._projection_timer.stop()
            self._reaction_timer.stop()
            self._animation_timer.stop()
            self._look_timer.stop()
            self._tray.hide()

        def hide_until_next_launch(self) -> None:
            """Dismiss the projection without claiming to stop the host."""
            self._dismissed = True
            self.stop_projection()
            self.hide()

        def stop_baboom(self) -> None:
            # Stop admission first. Already-dispatched actions may still finish.
            controller._host.request_stop()
            self._stopped = True
            self._pending_task_utterance = None
            self.hide_until_next_launch()
            if on_stop is not None:
                on_stop()

        def stand_with(self, owner, pin, on_ask) -> None:
            """Belong to the ArchHub window: beside its composer, at its place among the windows.

            ``pin`` is the companion setting (its "pinned" is on while BABOOM stays on a spot he
            dragged it to); ``on_ask`` points ArchHub's one composer at BABOOM, with the words it is given.
            """
            self._owner, self._pin, self._on_ask = owner, pin, on_ask
            self._pinned = self._pin_on()
            self.winId()

        def follow_app(self, app, composer=None, busy=(), screens=(), needs=0, listening=False) -> None:
            """Where ArchHub is now: its window, its composer, the busy boxes above it, the screens.

            ``needs`` is Home's own count of what needs him and ``listening`` is true while BABOOM's
            panel is open; both are what the page reports, and both are nothing while ArchHub is away.

            ``app`` is None while the window is minimised or hidden to the tray. BABOOM stays on
            screen then (F277), small, in the bottom right corner of the screen ArchHub was last
            on, and is home beside the composer when ArchHub is shown again.
            """
            had, saw = self._beside, (self._needs, self._listening)
            self._beside = (app, composer, tuple(busy), tuple(screens))
            self._needs, self._listening = (max(0, int(needs)), bool(listening)) if app is not None else (0, False)
            if had is not None and had[0] is None and app is not None and self._pinned:
                self._pin_here(False)
            if had is None or (had[0] is None) != (app is None):
                # Beside ArchHub he keeps its place among the windows and is never over another program.
                # With ArchHub away he is the desktop companion he was: on top, owned by no window.
                self.windowHandle().setTransientParent(self._owner.windowHandle() if app is not None else None)
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, app is None)
                # That hid him; shown again for ArchHub's sake he must not take the keyboard, his own box open or not.
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            before, now = self._stood, self._home()
            if (had is None or (had[0] is None) != (app is None) or (before is None) != (now is None)
                    or saw != (self._needs, self._listening)):
                self.refresh()
            elif now is not None and self.isVisible() and not self._dragged:
                # ArchHub moved or resized: go along now, without a whole projection for every step of a drag.
                self._stood = now
                self.move(self.x() + now.x - before.x, self.y() + now.y - before.y)

        def _free_spot(self) -> tuple[int, int] | None:
            """The spot he dragged BABOOM to. With ArchHub it holds only while pinned and on a screen."""
            placed = controller._user_origin
            if self._beside is None:
                return placed
            if self._pinned and placed is not None and screen_at(self._beside[3], *placed) is not None:
                return placed
            return None

        def _home(self) -> Rect | None:
            """Where BABOOM stands in ArchHub; None with no ArchHub window on screen or on a spot of his own."""
            if self._beside is None or self._beside[0] is None or self._free_spot() is not None:
                return None
            app, composer, busy, _screens = self._beside
            return place_baboom_beside_composer(
                app, self._screen_rect(), sprite_size=_STANDING_SIZE, composer=composer, busy=busy)

        def _pin_here(self, pinned: bool) -> None:
            """Keep the one companion setting true: on his own spot, or home with ArchHub."""
            self._pinned = pinned
            if self._pin is not None:
                try:
                    self._pin.update({"pinned": pinned})
                except (OSError, ValueError, AttributeError, TypeError) as refused:
                    # A broken or locked settings file never costs him BABOOM; the miss goes to the geometry log.
                    controller.geometry_receipt("pin setting not saved: %s" % type(refused).__name__)

        def _pin_on(self) -> bool:
            """The companion setting's "pinned". A missing, broken or unreadable file reads as not pinned."""
            try:
                return self._pin.read().get("pinned") is True
            except (OSError, ValueError, AttributeError, TypeError):
                return False

        def _greeting_due(self) -> bool:
            """One greeting a visit: a moment after he arrives in ArchHub, while no box of his is open."""
            if type(self._greeting) is not float or self._details_open:
                return False
            timing = GREETING_NODE["params"]
            age = (time.monotonic() - self._greeting) * 1000
            return timing["after_ms"] <= age < timing["after_ms"] + timing["for_ms"]

        def _screen_rect(self) -> Rect | None:
            # The screen the WINDOW happens to sit on is the wrong
            # authority at birth: a fresh frameless widget can be assigned
            # a secondary monitor and place the companion at a negative x,
            # off every visible desktop. The primary screen is where the
            # founder is.
            from PyQt6.QtGui import QGuiApplication

            # Once the founder has PUT it somewhere, that screen is the
            # authority -- he could not move BABOOM to his second monitor
            # because every projection measured the primary screen and
            # placed it back there (2026-09-07). The primary screen is only
            # the answer at birth, when he has chosen nothing yet.
            screen = None
            placed = self._free_spot()
            if self._beside is not None:
                # With ArchHub the authority is the screen most of its window is on (the one it was last on
                # while it is minimised or in the tray), unless he pinned BABOOM elsewhere.
                app, screens = self._beside[0], self._beside[3]
                if placed:
                    return screen_at(screens, *placed)
                if app is not None:
                    self._app_screen = max(screens, key=app.intersection_area, default=app)
                if app is not None or self._app_screen in screens:
                    return self._app_screen
            if placed:
                from PyQt6.QtCore import QPoint

                screen = QGuiApplication.screenAt(
                    QPoint(int(placed[0]), int(placed[1]))
                )
            if screen is None:
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
            if self._approval is not None and self._approval.isVisible():
                return (400, 300)
            width, minimum = baboom_compact_message_size(text)
            width, minimum = max(360, width), max(52, minimum)
            padding_x, padding_y = 24, 24
            wrapped = self._report.fontMetrics().boundingRect(
                QRect(0, 0, width - padding_x, 1 << 16),
                int(Qt.TextFlag.TextWordWrap),
                text,
            )
            # The label wraps by its own style (padding, line-height), which
            # the bare font metrics do not see. Ask the label what it needs at
            # this width and take the larger answer, so no last line is lost.
            asked = 0
            try:
                self._report.setText(speech(text))
                asked = int(self._report.heightForWidth(width))
            except Exception:
                asked = 0
            return (width, max(minimum, wrapped.height() + padding_y, asked))

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
            if self._motion_reduced():
                return
            # A companion that flips through poses while it has nothing to
            # say reads as broken, not alive. It breathes for a report, a
            # conversation, a Workshop state, or the walk between states.
            if self._frame.report is None and not self._timers_active():
                return
            frame = self._posed_frame(self._frame, bump=True)
            if self._transition_left > 0:
                self._transition_left -= 1
            self._frame = frame
            sprite = self._frame.layout.sprite
            self._frame = replace(
                self._frame,
                orb=controller.orb_for(self._frame.motion, (sprite.width, sprite.height)),
            )
            self._sprite = render_baboom_native_sprite(self._atlas, self._frame)
            self._apply_hit_mask()
            self._sync_resource_timers()
            self.update()

        def refresh(self) -> None:
            if self._dismissed or self._stopped:
                return
            if self._dragged:
                # A drag in progress owns the geometry; the 750ms
                # projection must not fight the founder's hand.
                return
            if self._beside is not None:
                self._pinned = self._pin_on()
                if self._pinned and controller._user_origin is not None and self._free_spot() is None:
                    self._pin_here(False)  # his own spot is on no screen now: BABOOM is home again
            screen = self._screen_rect()
            if screen is None:
                return
            frame = controller.next_frame(screen)
            home = self._home()
            if frame is not None:
                if home is not None:
                    # With ArchHub he is drawn where he stands, at the spec's size, with a report open or not.
                    frame = replace(frame, layout=replace(
                        frame.layout, sprite=home, message=None, edge="right", overlap_area=0, collision_state="clear"))
                frame = self._overlay_work_pose(frame)
            else:
                frame = self._frame
            self._presence(frame)
            if frame is None:
                self._sync_resource_timers()
                return
            if self._shows_as == "Hidden":
                self._details_open = False
            if not self._details_open:
                if controller.host_silent_seconds > _FRAME_GRACE_SECONDS or controller._host.connection_state in {"closed", "reconnecting"}:
                    self._pending_task_utterance = None
                    self._confirm.hide()
                    self._cancel.hide()
                self._idle_presence(screen, frame)
                return
            self._state_bubble.hide()
            self._state_badge.hide()
            self._look = None  # with a report open he is drawn plain, beside his words
            if (
                self._transient_revision is not None
                and self._transient_revision != frame.revision
                and self._pending_task_utterance is None
                and not self._busy
                and not self._result_visible
                and not (self._approval is not None and self._approval.isVisible())
            ):
                self._transient_report = None
                self._transient_revision = None
                self._interaction_requested = False
            if self._response_owner is not None and self._response_owner != id(controller._host._transport):
                self._response_received_at = 0.0
                self._response_owner = None
                self._pending_task_utterance = None
                self._confirm.hide()
                self._cancel.hide()
                if self._approval is not None:
                    self._approval.hide()
                self._approval_binding = ""
                self._transient_report = "ArchHub restarted. Ask again."
            response_age = (time.monotonic() - self._response_received_at
                if self._response_received_at else float("inf"))
            stale = (controller.host_silent_seconds > _FRAME_GRACE_SECONDS
                or controller._host.connection_state in {"closed", "reconnecting"}) and response_age > _FRAME_GRACE_SECONDS and not self._busy
            report = self._transient_report if not stale else None
            if stale:
                self._interaction_requested = False
                self._pending_task_utterance = None
                self._confirm.hide()
                self._cancel.hide()
                if self._approval is not None:
                    self._approval.hide()
                self._approval_binding = ""
            # With ArchHub the report opens beside him inside the ArchHub window, not across the screen.
            layout = self._layout_for_report(frame, screen if home is None else self._beside[0], report)
            self._stood = home
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
            # A pending act shows Confirm and Cancel on their own row beneath the
            # question, so the buttons never sit on top of the words. Reserve that
            # row in the window bounds while the buttons are up.
            if (self._confirm.isVisible() or self._skill_run.isVisible()) and layout.message is not None:
                bottom = max(bounds.bottom, message.bottom) + 34
            self._origin = QPoint(left, top)
            window_rect = QRect(left, top, right - left, bottom - top)
            self.setGeometry(window_rect)
            sprite_rect = QRect(
                bounds.x - left, bounds.y - top, bounds.width, bounds.height
            )
            self._sprite_rect = sprite_rect
            self._connection_status.setGeometry(sprite_rect.center().x() + 12, sprite_rect.top() + 12, 8, 8)
            self._connection_status.raise_()
            if layout.message is None or report is None:
                self._report.hide()
                self._confirm.hide()
                self._cancel.hide()
                self._skill_run.hide()
                self._pending_task_utterance = None
                self._act_progress = ""
                self._interaction_requested = False
                self._message_rect = None
            else:
                message = layout.message
                message_rect = QRect(
                    message.x - left, message.y - top, message.width, message.height
                )
                # When an act is pending, the report box grows by one button row so
                # its bg_raised fill covers Confirm and Cancel -- nothing behind the
                # buttons is ever the transparent desktop.
                panel_rect = message_rect
                if self._confirm.isVisible() or self._skill_run.isVisible():
                    panel_rect = QRect(
                        message_rect.x(), message_rect.y(),
                        message_rect.width(), message_rect.height() + 34,
                    )
                self._message_rect = message_rect
                self._report.setText(speech(report))
                self._report.setGeometry(panel_rect)
                self._report.show()
                if self._approval is not None and self._approval.isVisible():
                    self._approval.setGeometry(message_rect)
                    self._report.hide()
                    self._approval.raise_()
                if self._confirm.isVisible():
                    band_y = panel_rect.bottom() - 28
                    self._confirm.setGeometry(
                        panel_rect.right() - 78, band_y, 72, 22
                    )
                    self._confirm.raise_()
                    if self._cancel.isVisible():
                        self._cancel.setGeometry(
                            panel_rect.right() - 78 - 62, band_y, 56, 22
                        )
                        self._cancel.raise_()
                elif self._skill_run.isVisible():
                    band_y = panel_rect.bottom() - 28
                    self._skill_run.setGeometry(panel_rect.right() - 78, band_y, 72, 22)
                    self._skill_run.raise_()
                    if self._cancel.isVisible():
                        self._cancel.setGeometry(
                            panel_rect.right() - 78 - 62, band_y, 56, 22
                        )
                        self._cancel.raise_()
            self._apply_hit_mask()
            self._sync_resource_timers()
            if not self.isVisible():
                self.show()
            self.update()

        def _disown(self) -> None:
            """Stop any window from owning this one.

            A Qt::Tool window is OWNED by whatever was active when it was
            created -- here the ArchHub main window. Windows moves and hides
            owned windows with their owner, which is how the companion ended
            up shrunk at the bottom of the screen after the main window was
            minimized and restored. The companion belongs to the desktop, or,
            once it stands with ArchHub (stand_with), to that window alone:
            it is placed again on every move, hide and restore of it.
            """
            try:
                import ctypes as _ct

                user32 = _ct.windll.user32
                handle = int(self.winId())
                with_app = self._beside is not None and self._beside[0] is not None
                owner = int(self._owner.winId()) if with_app else 0
                GWLP_HWNDPARENT = -8
                setter = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
                setter(_ct.c_void_p(handle), GWLP_HWNDPARENT, _ct.c_void_p(owner))
            except Exception:
                pass

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            painter = QPainter(self)
            # Clear the whole window to transparent first, every paint, so no
            # frame and no fill ever shows around the sprite and its box.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self._sprite is not None and self._frame is not None and self._look is not None:
                self._paint_look(painter)
            elif self._sprite is not None and self._frame is not None:
                painter.drawImage(self._sprite_rect, self._sprite)
            painter.end()

        def showEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            super().showEvent(event)
            self._disown()
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
            if not self._dismissed and not self._stopped:
                self._sync_resource_timers()

        def hideEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            super().hideEvent(event)
            self._sync_resource_timers()

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            self.hide_until_next_launch()
            super().closeEvent(event)

        def changeEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            super().changeEvent(event)
            if event.type() == QEvent.Type.WindowStateChange and not self._dismissed:
                self._sync_resource_timers()

        def _open_interaction(self, words: str = "") -> None:
            """Ask BABOOM. ArchHub has one composer, so this points it at him, with any words to start from
            (one-BABOOM spec 5b); he has no reply box of his own. With no ArchHub to stand with, it opens ArchHub."""
            self._greeting = False
            if self._on_ask is not None:
                self._on_ask(words)
            else:
                self._open_archhub()

        def apply_approval(self, binding: str, decision: str) -> None:
            """Apply hook_decision.decide()'s Approve/Deny to the one review on screen."""
            if binding != self._approval_binding or not self._pending_task_utterance:
                self._approval_bridge.settled.emit(binding, "This review expired. Request a fresh review.")
                return
            self._approval_binding = ""
            if decision == "approve":
                self._executing_approval_binding = binding
                self._execute_task()
            else:
                self._close_interaction()

        def _close_interaction(self) -> None:
            """Back to the sprite alone: no box, no stale answer."""
            self._details_open = False
            self._interaction_requested = False
            self._interaction_generation += 1
            self._result_visible = False
            self._busy = False
            self._approval_binding = ""
            if self._approval is not None:
                self._approval.hide()
            self._transient_report = None
            self._transient_revision = None
            self._pending_task_utterance = None
            self._confirm.hide()
            self._cancel.hide()
            self._skill_offer = None
            self._skill_run.hide()
            self._report.hide()
            self.refresh()

        def _save_position(self, x: int, y: int) -> None:
            if self._position_path is None:
                return
            self._position_revision += 1
            self._position_jobs.submit(self._position_writer.save, self._position_path, x, y, self._position_revision)

        @pyqtSlot(int)
        def _position_save_failed(self, revision: int) -> None:
            if revision == self._position_revision:
                QToolTip.showText(self.mapToGlobal(self._sprite_rect.center()),
                                  "Position couldn't be saved. Drag BABOOM again to retry.", self)

        def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if event.key() == Qt.Key.Key_Escape:
                self._close_interaction()
                return
            super().keyPressEvent(event)

        # Right-click: all of ArchHub, from the graph itself. Every entry is an
        # utterance the graph already answers or executes; nothing here is a
        # promise the runtime cannot keep.
        def _say(self, utterance: str) -> None:
            """Run one menu line; the answer opens in his report."""
            if self._frame is None or self._layout is None or self._busy or not utterance.strip():
                return
            self._details_open = True
            self.setWindowTitle("BABOOM")
            set_native_click_through(int(self.winId()), False)
            self._interaction_generation += 1
            if self._approval is not None:
                self._approval.hide()
            self._approval_binding = ""
            self._pending_task_utterance = None
            self._confirm.hide()
            self._cancel.hide()
            self._skill_offer = None
            self._skill_run.hide()
            self._submit(utterance.strip())

        def _prefill(self, prefix: str) -> None:
            """A menu line he finishes in his own words: the one composer, pointed at BABOOM, starting with them."""
            self._open_interaction(prefix)

        def _open_cockpit(self) -> None:
            "Open the cockpit on the app's own session, never on a sign-in page."
            import webbrowser
            from .cloud_relay import cockpit_url
            webbrowser.open(cockpit_url())

        def _open_archhub(self) -> None:
            if on_open is not None:
                on_open()
                return
            from PyQt6.QtGui import QDesktopServices
            programs = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
            # setup.iss installs directly in Programs; retain older installs'
            # ArchHub subfolder as a fallback, without copying a launcher.
            shortcut = programs / "ArchHub.lnk"
            if not shortcut.is_file():
                shortcut = programs / "ArchHub/ArchHub.lnk"
            if not shortcut.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(shortcut))):
                self._transient_report = "ArchHub could not open. Start it from the Start menu."
                self.refresh()

        def _open_work_task(self) -> None:
            presence = self._work_presence
            if on_open_task is None or presence is None or not presence.task_id:
                return
            try:
                result = on_open_task(presence.task_id)
                if result is False or (isinstance(result, Mapping) and result.get("ok") is False):
                    raise RuntimeError(str(result.get("error") or "Task is unavailable") if isinstance(result, Mapping) else "Task is unavailable")
            except Exception as refused:
                self._details_open = True
                self._result_visible = True
                self._transient_report = "Task could not open: " + str(refused)
                self.refresh()

        def _show_approval(self) -> None:
            """Render the very same card as Workshop, with this command's receipt."""
            if not self._pending_task_utterance:
                return
            from PyQt6.QtWebChannel import QWebChannel
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            if self._approval is None:
                self._approval = QWebEngineView(self)
                self._approval.page().setBackgroundColor(Qt.GlobalColor.transparent)
                self._approval_channel = QWebChannel(self._approval.page())
                self._approval_channel.registerObject("baboom", self._approval_bridge)
                self._approval.page().setWebChannel(self._approval_channel)
            self._approval_binding = hashlib.sha256((str(self._interaction_generation) + self._pending_task_utterance).encode()).hexdigest()
            approval = {**dict(self._approval_detail), "id": self._approval_binding, "state": "needs-user",
                "title": self._approval_label, "summary": self._transient_report,
                "target": "ArchHub", "undo_available": False}
            self._approval.setHtml(baboom_approval_html(approval, self._approval_binding),
                QUrl.fromLocalFile(str(Path(__file__).parent / "studio") + "/"))
            self._confirm.hide()
            self._cancel.hide()
            self._approval.show()
            self.refresh()

        def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            from PyQt6.QtWidgets import QMenu
            # The window has no host of its own: it is a closure over the
            # controller, which holds the host. Reading self._host here raised
            # AttributeError on every right-click and the launcher's excepthook
            # turned that into "ArchHub could not open" (2026-09-06).
            snapshot = controller.latest_snapshot
            context = dict(getattr(snapshot, "context", {}) or {}) if snapshot is not None else {}
            if snapshot is None or time.time() > snapshot.frame_expires_at + _FRAME_GRACE_SECONDS:
                context = {}
            menu = QMenu(self)
            # This window is styled "background:transparent;border:0;" so the
            # sprite has no rectangle behind it, and Qt cascades that into
            # every child widget -- including this menu, whose hover and
            # submenu-open highlight became invisible. The founder could not
            # see which row he was on (2026-09-07). The menu states its own
            # surface, so nothing is inherited and nothing is guessed.
            menu.setStyleSheet(_MENU_STYLE)
            # A soft drop shadow lifts the menu off the desktop in place of the
            # old 1px hairline border. The colour is the named shadow exception,
            # not a THEME hue (a cast shadow is black-with-alpha).
            from PyQt6.QtWidgets import QGraphicsDropShadowEffect
            from PyQt6.QtGui import QColor as _QColor
            shadow = QGraphicsDropShadowEffect(menu)
            shadow.setBlurRadius(20)
            shadow.setOffset(0, 6)
            shadow.setColor(_QColor(*_MENU_SHADOW_RGBA))
            menu.setGraphicsEffect(shadow)
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
            agents = (context.get("agents") or {}).get("working")
            a = menu.addMenu("Agents: %d working" % len(agents) if isinstance(agents, (list, tuple))
                             else "Agents: state unavailable")
            agents = agents if isinstance(agents, (list, tuple)) else []
            for row in agents[:8]:
                a.addAction("%s on: %s" % (row.get("agent"), row.get("title")), lambda: self._say("show governed work"))
            a.addAction("Who is online", lambda: self._say("agents"))
            a.addAction("Tell an agent...", lambda: self._prefill("tell codex: "))
            a.addAction("Interrupt an agent...", lambda: self._prefill("interrupt claude:"))
            a.addAction("Queue work for the agents...", lambda: self._prefill("Assign task: "))
            a.addAction("Send a task to a model...", lambda: self._prefill("assign task to claude: "))
            front = foreground_app_windows()
            if front is None and self._front is not None and time.monotonic() - self._front_at < 30.0:
                front = self._front
            if front is not None:
                front_label, front_engine, front_verb = front
                f = menu.addMenu("%s is open" % front_label)
                f.addAction(front_verb, (lambda e=front_engine: self._say("run %s on the graph" % e)))
                for act_label, act_engine in _FOREGROUND_ACTS.get(front_label, ()):
                    f.addAction(act_label, (lambda e=act_engine: self._say("run %s on the graph" % e)))
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
            menu.addAction("Open the cockpit", self._open_cockpit)
            menu.addAction("Hide BABOOM until next launch (keeps running)", self.hide_until_next_launch)
            menu.addAction("Stop BABOOM for this launch", self.stop_baboom)
            # Hold the companion still while the menu is open. refresh()
            # runs every 750ms and moves, reshapes and repaints this window,
            # during projection: each submenu popup opened on
            # hover and was immediately restacked underneath the companion,
            # so the founder saw a menu whose rows never opened (2026-09-07).
            self._projection_timer.stop()
            self._reaction_timer.stop()
            self._animation_timer.stop()
            self._look_timer.stop()
            try:
                menu.exec(event.globalPos())
            finally:
                self._sync_resource_timers()

        def _pointer_hits(self, point) -> bool:
            """A click counts only on the visible sprite or an open report control."""
            mask = self.mask()
            if mask.isEmpty():
                return False
            return mask.contains(point)

        def _apply_hit_mask(self) -> None:
            """Keep the window region on this frame's opaque pixels, plus open controls."""
            from PyQt6.QtGui import QRegion

            if self._sprite is None:
                return
            region = baboom_opaque_hit_region(
                self._sprite, self._sprite_rect.x(), self._sprite_rect.y()
            )
            for widget in (
                self._report, self._confirm, self._cancel, self._connection_status,
                self._state_bubble, self._state_badge, self._skill_run,
            ):
                if widget.isVisible():
                    region = region.united(QRegion(widget.geometry()))
            if self._approval is not None and self._approval.isVisible():
                region = region.united(QRegion(self._approval.geometry()))
            if self._look is not None:
                # A mask clips what it leaves out: the reach of his float, the ground glow and the live dot are his too.
                reach = LOOK_NODE["params"]["float_px"]
                region = region.united(region.translated(0, -reach))
                for rect in self._look_rects()[:1 + self._dot_shown()]:
                    region = region.united(QRegion(rect.adjusted(0, -reach, 0, 0)))
            if region.isEmpty():
                return
            self.setMask(region)

        def _open_from_click(self) -> None:
            """A quiet click that was not a double-click asks BABOOM: the one composer points at him."""
            if self._dragged or self._dismissed or self._stopped:
                return
            if self._transient_report is not None:
                return
            self._open_interaction()

        def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if event.button() == Qt.MouseButton.LeftButton:
                if not self._pointer_hits(event.position().toPoint()):
                    event.ignore()
                    return
                self._quiet_click.stop()
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
                # slightly shaky click still asks BABOOM.
                if self._dragged or delta.manhattanLength() > 4:
                    self._dragged = True
                    self._quiet_click.stop()
                    self.move(self._press_window_pos + delta)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if event.button() == Qt.MouseButton.LeftButton:
                if self._press_global is None:
                    if not self._pointer_hits(event.position().toPoint()):
                        event.ignore()
                    return
                if self._dragged:
                    origin = self.pos() + self._sprite_rect.topLeft()
                    self._dragged = False
                    if self._beside is None or self._pinned:
                        # With ArchHub a drag holds only after he un-pinned BABOOM from it; else he springs home.
                        controller.pin_sprite_origin(origin.x(), origin.y())
                        self._save_position(origin.x(), origin.y())
                    self.refresh()
                elif self._transient_report is not None:
                    self._quiet_click.stop()
                    self._close_interaction()
                else:
                    self._quiet_click.start()
                self._press_global = None
                self._dragged = False
            super().mouseReleaseEvent(event)

        def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._pointer_hits(event.position().toPoint())
            ):
                self._quiet_click.stop()
                self._press_global = None
                self._dragged = False
                self._open_archhub()
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

        def _sessions_folder(self) -> Path:
            if self._sessions_directory is not None:
                return Path(self._sessions_directory())
            from .session_files import sessions_directory
            return sessions_directory()

        def _offer_dropped_file(self, path: Path) -> None:
            from .baboom_work_presence import load_saved_skills, match_saved_skill
            if self._frame is None or self._busy or self._dismissed or self._stopped:
                return
            match = match_saved_skill(path, load_saved_skills(self._sessions_folder()))
            self._details_open = True
            self._interaction_requested = True
            self._result_visible = False
            self._confirm.hide()
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            set_native_click_through(int(self.winId()), False)
            if match is None:
                self._skill_offer = None
                self._skill_run.hide()
                self._cancel.hide()
                self._transient_report = "No saved skill matches %s." % path.name
            else:
                title = str(match.get("title") or match.get("id") or "skill")
                self._skill_offer = {
                    "prompt": "Run %s on %s?" % (title, path.name),
                    "skill_path": str(match["path"]),
                    "file": str(path),
                    "title": title,
                }
                self._transient_report = self._skill_offer["prompt"]
                self._skill_run.show()
                self._cancel.show()
            self._transient_revision = None
            self.refresh()

        def _run_offered_skill(self) -> None:
            offer = self._skill_offer
            if offer is None or self._busy:
                return
            from .baboom_work_presence import execute_saved_skill
            try:
                text = execute_saved_skill(offer["skill_path"], offer["file"])
            except Exception:
                text = "Skill failed: the skill did not finish."
            self._skill_offer = None
            self._skill_run.hide()
            self._cancel.hide()
            self._transient_report = text
            self._transient_revision = None
            self.refresh()

        def _accept_file_drop(self, event) -> str:
            urls = event.mimeData().urls() if event.mimeData() is not None else []
            local = next((url.toLocalFile() for url in urls if url.isLocalFile()), "")
            if not local:
                event.ignore()
                return ""
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return local

        def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            self._accept_file_drop(event)

        def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            self._accept_file_drop(event)

        def dropEvent(self, event) -> None:  # noqa: N802 - Qt callback name
            local = self._accept_file_drop(event)
            if local:
                self._offer_dropped_file(Path(local))

        def _submit(self, utterance: str) -> None:
            self._busy = True
            self._steps = {}
            self._result_visible = False
            generation = self._interaction_generation
            owner = id(controller._host._transport)
            self._submitted_utterance = utterance
            self._interaction_requested = False
            self._transient_report = "Asking ArchHub…"
            self._transient_revision = None
            self._report.setText(speech(self._transient_report))
            self._report.show()
            self.refresh()

            def resolve() -> None:
                try:
                    result: Mapping[str, object] = controller.respond(utterance,
                        on_progress=lambda step: self.progress_ready.emit((generation, step)))
                except Exception as error:
                    from .baboom_native_host import MachineResponseError
                    result = {
                        "response": {
                            "kind": "unavailable",
                            "summary": (str(error).strip()[:400] if isinstance(error, MachineResponseError)
                                else "BABOOM could not read the graph response."),
                            "data": {},
                        }
                    }
                self.response_ready.emit({"generation": generation, "owner": owner, "payload": result})

            threading.Thread(target=resolve, name="baboom-native-input", daemon=True).start()

        def _apply_progress(self, event) -> None:
            generation, step = event
            if generation != self._interaction_generation or self._dismissed or self._stopped:
                return
            self._steps[str(step["tool"])] = dict(step)
            from .baboom_persona import host_outcome
            self._transient_report = ('A tool is running.' if step.get('status') == 'running'
                                      else host_outcome([step]) or 'A tool completed.')
            self.refresh()

        def _apply_response(self, result: Mapping[str, object]) -> None:
            if self._dismissed or self._stopped:
                return
            if "generation" in result:
                if result["generation"] != self._interaction_generation:
                    return
                if result.get("owner", id(controller._host._transport)) != id(controller._host._transport):
                    self._busy = False
                    self._transient_report = "ArchHub restarted. Ask again."
                    self.refresh()
                    return
                result = result["payload"]
            self._busy = False
            command = result.get("command")
            response = result.get("response")
            if isinstance(response, Mapping) and response.get("kind") != "unavailable":
                self._response_received_at = time.monotonic()
                self._response_owner = id(controller._host._transport)
            self._pending_task_utterance = None
            self._act_progress = ""
            self._interaction_requested = False
            self._confirm.hide()
            self._cancel.hide()
            if isinstance(response, Mapping):
                self._result_visible = True
                self._transient_report = compact_baboom_response_report(response)
                steps = (response.get("data") or {}).get("steps") or []
                if steps:
                    from .baboom_persona import host_outcome
                    self._transient_report = host_outcome(steps) or self._transient_report
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
                # The confirm executes the graph's own words when it hands
                # them back ("restart to update build b-2"), so pressing it
                # installs the build he was shown and nothing staged since.
                confirm = data.get("confirm_utterance")
                utterance = (confirm if isinstance(confirm, str) and confirm.strip()
                             else self._submitted_utterance)
                if utterance:
                    intent = str(command.get("intent") or "")
                    question, label = _BABOOM_ACT_PROMPTS.get(
                        intent, ("Do this in ArchHub?", "Do it"))
                    label = str(data.get("approve_label") or label)
                    self._approval_detail = data.get("approval") or {}
                    if intent == "remember" and isinstance(data.get("text"), str):
                        self._approval_detail = {"rows": [{"id": "memory", "label": "Brain memory",
                            "now": "New memory", "after": data["text"]}]}
                    # An act that writes says WHAT before the founder presses:
                    # the app names the engine, the build, the fact.
                    said = response.get("summary") if isinstance(response, Mapping) else None
                    if (intent in {"run-engine", "restart-to-update", "remember"}
                            and isinstance(said, str) and said.strip()):
                        question = said.strip()
                    self._pending_task_utterance = utterance
                    self._transient_report = question
                    self._act_progress = _BABOOM_ACT_PROGRESS.get(intent, "Working...")
                    # Review opens the shared card; its action label names the
                    # exact write. The native button never executes directly.
                    self._approval_label = label
                    self._confirm.setText("Review")
                    self._confirm.setToolTip("Review · " + label)
                    self._confirm.setAccessibleName("Review · " + label)
                    self._confirm.show()
                    self._cancel.show()
            if self._pending_task_utterance is None:
                self._submitted_utterance = ""
            self.refresh()
            if on_response is not None:
                on_response(result)

        def _execute_task(self) -> None:
            utterance = self._pending_task_utterance
            if not utterance:
                return
            self._pending_task_utterance = None
            self._busy = True
            generation = self._interaction_generation
            owner = id(controller._host._transport)
            if self._approval is not None:
                self._approval.hide()
            self._confirm.hide()
            self._cancel.hide()
            self._report.setText(speech(self._act_progress or "Working..."))
            self._transient_report = self._act_progress or "Working…"
            self._report.show()

            def execute() -> None:
                try:
                    result: Mapping[str, object] = controller.execute(utterance)
                except Exception as error:
                    result = {"error": baboom_execution_error_text(error)}
                self.execution_ready.emit({"generation": generation, "owner": owner, "payload": result})

            threading.Thread(
                target=execute, name="baboom-native-task", daemon=True
            ).start()

        def _apply_execution(self, result: Mapping[str, object]) -> None:
            if self._dismissed or self._stopped:
                return
            if "generation" in result:
                if result["generation"] != self._interaction_generation:
                    return
                if result.get("owner", id(controller._host._transport)) != id(controller._host._transport):
                    self._busy = False
                    self._transient_report = "ArchHub restarted. Check the result in ArchHub."
                    if self._executing_approval_binding:
                        self._approval_bridge.settled.emit(self._executing_approval_binding, self._transient_report)
                        self._executing_approval_binding = ""
                    self.refresh()
                    return
                result = result["payload"]
            self._busy = False
            if not result.get("error"):
                self._response_received_at = time.monotonic()
                self._response_owner = id(controller._host._transport)
            self._result_visible = True
            created = result.get("created")
            summary = result.get("summary")
            if isinstance(summary, str) and summary.strip() and created is None:
                # Every act other than a task reports what it did in words
                # (engine-ran, agent-message...). Reading only "created"
                # here told the founder "could not create the task" after a
                # run that had happened (audit 2026-09-06).
                self._transient_report = summary.strip()
            elif created is True:
                self._transient_report = "Task created in ArchHub."
            elif created is False:
                self._transient_report = "That task already exists in ArchHub."
            else:
                error = result.get("error")
                self._transient_report = (
                    error.strip() if isinstance(error, str) and error.strip()
                    else _BABOOM_EXECUTION_FAILED)
            self._transient_revision = (
                self._frame.revision if self._frame is not None else None
            )
            self._interaction_requested = False
            if self._executing_approval_binding:
                error = str(result.get("error") or "")
                self._approval_bridge.settled.emit(self._executing_approval_binding, error)
                self._executing_approval_binding = ""
            self.refresh()
            if on_response is not None:
                on_response({"execution": dict(result)})

    made = CompanionWindow()
    # The launcher needs the controller to point the geometry receipt at a
    # file; nothing else exposed it, so the receipt was never wired and the
    # log stayed empty exactly when it was needed (2026-09-06).
    made.controller = controller
    return made


__all__ = [
    "BaboomNativeCompanionController",
    "compact_baboom_response_report",
    "create_baboom_native_companion_window",
    "foreground_application_windows",
    "foreground_window_rect_windows",
    "foreground_window_rects_windows",
    "render_baboom_native_sprite",
]
