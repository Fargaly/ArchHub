"""BABOOM's face reflects the graph, and offers help for the app in front.

The founder: "BABOOM is useless, it does not show that it reflects the graph
and its agent cannot help with anything being done" (2026-09-06). He was
right about what he could see: the state was in the snapshot and only a
right-click revealed it, and the companion knew where windows were but never
which app they belonged to. These courts hold the face and the offer.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from nodelang import baboom_native_companion as companion
from nodelang import universal_pipeline

ROOT = Path(__file__).resolve().parents[1]


def test_the_face_is_built_from_the_snapshot_never_invented():
    line, offer = companion.baboom_face_line({}, None)
    assert line == "watching the graph" and offer is None
    context = {
        "canvas": {"ran": 12, "answered": 9},
        "brain": {"ok": True, "facts": 2312},
        "agents": {"working": [{"agent": "codex"}, {"agent": "claude"}]},
        "work": {"title": "hosts open from ArchHub"},
        "attention": {"blocked_obligations": []},
    }
    line, offer = companion.baboom_face_line(context, None)
    assert "canvas 9/12 answered" in line
    assert "brain 2312" in line
    assert "2 agents working" in line
    assert "blocked" not in line and offer is None
    # The box holds two lines. Lower-priority parts are dropped whole rather
    # than cut mid-word: the founder saw "canvas 11/12 answered - brai".
    assert len(line) <= companion.FACE_MAX_CHARS, line
    assert not line.endswith(("-", chr(183), " "))

    short = dict(context, work=None, agents={"working": []})
    line, _ = companion.baboom_face_line(short, None)
    assert "canvas 9/12 answered" in line and "brain 2312" in line
    assert "agents working" not in line, "an idle fleet is not news"


def test_a_silent_brain_and_blocked_work_are_said_plainly():
    line, _ = companion.baboom_face_line(
        {"brain": {"ok": False}, "attention": {"blocked_obligations": ["x", "y"]}}, None)
    assert "brain silent" in line and "2 blocked" in line


def test_the_app_in_front_becomes_an_offer_the_graph_can_run():
    line, offer = companion.baboom_face_line({}, ("Revit", "revit.read", "read the walls"))
    assert line.startswith("Revit is open: read the walls?"), (
        "the app in front is the most useful thing on the face: %s" % line)
    assert offer == "run revit.read on the graph"
    # every foreground host maps to an engine the app really has
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    from nodelang.universal_pipeline import _graph_engines
    known = set(PIPELINE_ENGINES)
    for exe, (label, engine, verb) in companion._FOREGROUND_HOSTS.items():
        assert exe.endswith(".exe") and label and verb
        assert engine in known or engine in ("skills.catalogue",), engine


def test_the_probe_reads_the_foreground_process_by_name():
    src = inspect.getsource(companion.foreground_app_windows)
    assert "GetForegroundWindow" in src and "QueryFullProcessImageNameW" in src
    assert "_FOREGROUND_HOSTS.get(exe)" in src
    # the probe must never raise into the paint loop
    assert "except Exception:" in src and "return None" in src


def test_the_window_shows_the_face_when_nothing_else_is_said_and_a_click_runs_the_offer():
    src = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    window = src[src.index("class CompanionWindow"):]
    refresh = window[window.index("def refresh(self)"):window.index("def paintEvent")]
    assert "baboom_face_line(context, foreground_app_windows())" in refresh
    assert "if report is None and not self._input.isVisible():" in refresh
    events = window[window.index("def eventFilter"):window.index("def keyPressEvent")]
    assert "obj is self._report" in events and "self._say(self._face_offer)" in events
    assert "self._report.installEventFilter(self)" in window


def test_the_face_does_not_make_the_companion_fidget():
    """The face is not a report: breathing stays tied to real reports."""
    src = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    window = src[src.index("class CompanionWindow"):]
    animate = window[window.index("def _advance_animation"):window.index("def refresh(self)")]
    assert "self._frame.report is None" in animate
    assert "_face" not in animate


def test_the_lens_carries_the_canvas_from_the_pipelines_own_last_run():
    from nodelang import universal_application as ua
    lens = inspect.getsource(ua.project_universal_baboom_context)
    assert '"canvas": canvas_view' in lens and "last_pipeline_run()" in lens
    assert universal_pipeline.last_pipeline_run() == {} or set(universal_pipeline.last_pipeline_run()) >= {"ran", "answered", "pending", "at"}
    run = inspect.getsource(universal_pipeline.run_universal_pipeline)
    assert '"answered": len(evaluation.display)' in run


def test_a_long_state_is_trimmed_not_cut_mid_word():
    """The founder's screen: 'canvas 11/12 answered - brai', clipped."""
    context = {
        "canvas": {"ran": 12, "answered": 11},
        "brain": {"ok": True, "facts": 2313},
        "agents": {"working": [{"agent": "codex"}]},
        "work": {"title": "a piece of work with a deliberately long title"},
        "attention": {"blocked_obligations": ["a", "b"]},
    }
    line, offer = companion.baboom_face_line(context, ("Revit", "revit.read", "read the walls"))
    assert len(line) <= companion.FACE_MAX_CHARS, "%d chars: %s" % (len(line), line)
    assert line.startswith("Revit is open: read the walls?")
    assert offer == "run revit.read on the graph"
    for part in line.split(" " + chr(183) + " "):
        assert part.strip() == part and part, line


def test_a_silent_host_is_said_on_the_face_and_never_hides_the_companion():
    """It used to vanish after ten minutes of host silence, which the founder
    read as 'appears and disappears'. Presence first: say it, do not go."""
    line, _ = companion.baboom_face_line({"host_silent_seconds": 400.0}, None)
    assert "host silent 6m" in line
    src = inspect.getsource(companion)
    frame = src[src.index("def next_frame"):src.index("def next_sprite_source")] if "def next_sprite_source" in src else src[src.index("def next_frame"):]
    assert "_FRAME_SILENCE_SECONDS" not in frame, "a stale lease must not hide the sprite"
    assert "self.host_silent_seconds = max(0.0" in frame


def test_the_window_records_where_it_landed():
    """Twice now the app reported drawing while the founder saw nothing.
    Every geometry change writes one line, so the next time is readable."""
    src = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    assert "def watch_geometry(self, path)" in src
    assert "def geometry_receipt(self, line: str)" in src
    window = src[src.index("class CompanionWindow"):]
    assert 'receipt("sprite=%dx%d+%d+%d message=%s window=%dx%d+%d+%d"' in window
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert 'controller.watch_geometry(state_dir / "baboom-geometry.log")' in launcher


def test_the_app_can_be_asked_to_quit_so_its_tray_icon_goes_with_it():
    """14 force-kills in one day left 14 dead tray icons; the founder clicked
    one and nothing opened, because that icon owned no process."""
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "def _watch_quit_request()" in launcher
    watcher = launcher[launcher.index("def _watch_quit_request()"):]
    assert 'marker = state_dir / "quit-request"' in watcher
    assert "_tray_quit()" in watcher.split("def ", 2)[0] + watcher
    assert "_watch_quit_request()" in launcher.split("def _watch_quit_request")[0] or launcher.count("_watch_quit_request()") >= 2


def test_the_window_exposes_its_controller_so_the_receipt_can_be_wired():
    """The launcher asks the window for its controller to point the geometry
    receipt at a file. Nothing exposed it, so the log stayed empty exactly
    when the founder reported BABOOM missing (2026-09-06)."""
    src = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    assert "made.controller = controller" in src
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert 'getattr(baboom_window, "controller", None)' in launcher
