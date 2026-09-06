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
    assert "on: hosts open from ArchHub" in line
    assert "blocked" not in line and offer is None


def test_a_silent_brain_and_blocked_work_are_said_plainly():
    line, _ = companion.baboom_face_line(
        {"brain": {"ok": False}, "attention": {"blocked_obligations": ["x", "y"]}}, None)
    assert "brain silent" in line and "2 blocked" in line


def test_the_app_in_front_becomes_an_offer_the_graph_can_run():
    line, offer = companion.baboom_face_line({}, ("Revit", "revit.read", "read the walls"))
    assert "Revit is open: read the walls?" in line
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
