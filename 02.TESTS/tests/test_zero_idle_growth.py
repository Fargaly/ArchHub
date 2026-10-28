"""RELEASE GATE: an idle ArchHub grows nothing, and a canvas change undoes and redoes exactly.

Founder order, 2026-09-23: the app must stop growing for nothing. NOGRAPH: the app runs
nograph_launcher -> NoGraphServer and never opens a graph, so this court boots exactly that, from
the code under test (this checkout, or ARCHHUB_COURT_SOURCE: the build passes its verified
snapshot), headless, in an isolated profile. The window saves and opens one .archhub document;
then nobody acts:

* ten intervals of window/agent reads (catalogue, revision poll, document read, canvas, project
  files), each past the local probe cache;
* a close and two restarts, each its own process.

No file in the data dir or the profile (no journal, no .archhub, nothing) may appear, change size
or be rewritten from the baseline. An agent canvas change must undo (canvas.undo), redo (the
window's redo saved through autosave) and undo again to the exact documents. The build refuses a
release when this court is red.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = Path(__file__).with_name("zero_idle_growth_driver.py")
PHASE_TIMEOUT_SECONDS = 900


def _source_under_test() -> Path:
    configured = os.environ.get("ARCHHUB_COURT_SOURCE", "").strip()
    source = Path(configured).resolve() if configured else ROOT / "01.APP"
    if not (source / "nodelang" / "nograph_server.py").is_file():
        pytest.fail("source under test has no NOGRAPH app: %s" % source)
    return source


def _run(phase: str, source: Path, state: Path, *extra: str) -> str:
    from tools.real_app_check.real_app_check import isolated_env
    from tools.real_app_check.profile_guard import command
    environment = isolated_env(dict(os.environ), state.parent / "PROFILE")
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        command([sys.executable, str(DRIVER), phase, str(source), str(state), *extra]),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=PHASE_TIMEOUT_SECONDS, env=environment, cwd=str(state.parent),
    )
    if completed.returncode != 0:
        pytest.fail("%s phase failed (exit %d):\n%s" % (
            phase, completed.returncode, completed.stderr[-4000:]
        ))
    return completed.stdout


def _changes(baseline: dict, after: dict) -> dict:
    return {path: [baseline.get(path), after.get(path)] for path in set(baseline) | set(after)
            if baseline.get(path) != after.get(path)}


def test_an_idle_app_grows_no_file(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    result_path = tmp_path / "zero-idle-result.json"
    source = _source_under_test()
    _run("idle", source, state, str(result_path))
    _run("restart", source, state, str(result_path))
    _run("restart", source, state, str(result_path))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    baseline = result["baseline"]
    observed = {
        **{"interval %d" % (index + 1): files for index, files in enumerate(result["intervals"])},
        "close": result["closed"],
        **{"restart %d" % (index + 1): files for index, files in enumerate(result["restarts"])},
    }
    grew = {name: _changes(baseline, files) for name, files in observed.items() if files != baseline}
    print("zero-idle baseline: %d files" % len(baseline))
    assert len(result["intervals"]) == 10 and len(result["restarts"]) == 2
    assert any(path.endswith(".archhub") for path in baseline), "the window's document was not saved"
    assert not grew, "the app wrote files while nobody acted: %s" % json.dumps(grew)[:4000]


def test_a_canvas_change_undoes_and_redoes_exactly(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    result_path = tmp_path / "undo-result.json"
    _run("undo", _source_under_test(), state, str(result_path))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    print("undo court: count through edit/undo/redo/undo:", result["count"])
    assert result["count"] == ["3", "2", "3", "2", "3"]
    assert result["changed"] and result["undo_exact"] and result["redo_exact"] and result["second_undo_exact"]
