"""RELEASE GATE: an idle ArchHub graph does not grow.

Founder order, 2026-09-23: the graph must stop growing for nothing. SPEC.md
section 3.3 keeps heartbeats, leases, renewals, receipts and signals out of
graph revisions, and nodelang/commit_intent.py refuses any commit without a
closed-set intent. This court proves it on the thing that matters: a graph
written by an OLD release, opened by the code under test.

A fresh fixture built by the code under test cannot fail this court, so the
graph is built by the old release's own bytes in a separate process
(ARCHHUB_OLD_GRAPH_SOURCE, else ``git archive`` of OLD_GRAPH_SOURCE_REVISION
from this checkout). The code under test is this checkout, or
ARCHHUB_COURT_SOURCE (the build passes its verified snapshot). It opens the
old graph once (an admitted migration may publish here); BABOOM enrolls and
reports, the brain hook records a session start, and the founder's window
reads its canvas. Then nobody acts:

* ten intervals on a fake clock, each past the runtime-presence lease and
  inside the browser renewal lead: agent-session lease renewal, runtime
  presence heartbeat, foreground activity, an unchanged steward signal, a
  brain session-start receipt, the Desktop browser-handoff renewal, and
  agent and browser reads;
* a close and two restarts.

max(revision), count(cell_versions) and count(current_cells) must not move
from the baseline. The build refuses a release when this court is red.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest


OLD_GRAPH_SOURCE_REVISION = "9eefd8145db822940ab2458dadc1643e5af1081d"
ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).with_name("zero_idle_growth_driver.py")
PHASE_TIMEOUT_SECONDS = 900


def _source_under_test() -> Path:
    configured = os.environ.get("ARCHHUB_COURT_SOURCE", "").strip()
    source = Path(configured).resolve() if configured else ROOT
    if not (source / "nodelang" / "universal_cell.py").is_file():
        pytest.fail("source under test has no nodelang package: %s" % source)
    return source


def _old_source(target: Path) -> Path:
    configured = os.environ.get("ARCHHUB_OLD_GRAPH_SOURCE", "").strip()
    if configured:
        source = Path(configured).resolve()
        if not (source / "nodelang" / "universal_cell.py").is_file():
            pytest.fail("ARCHHUB_OLD_GRAPH_SOURCE has no nodelang package: %s" % source)
        return source
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar",
         OLD_GRAPH_SOURCE_REVISION, "nodelang", "launch_archhub_test.py"],
        capture_output=True, timeout=300,
    )
    if archive.returncode != 0:
        pytest.fail(
            "the old-shape graph needs release %s (git archive failed: %s); "
            "set ARCHHUB_OLD_GRAPH_SOURCE to its source tree"
            % (OLD_GRAPH_SOURCE_REVISION, archive.stderr.decode(errors="replace")[:300])
        )
    target.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
        bundle.extractall(target, filter="data")
    return target


def _run(phase: str, source: Path, state: Path, *extra: str) -> str:
    environment = dict(os.environ)
    environment.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Each release reads its own packaged map; never a machine-local one.
        "ARCHHUB_GRAND_MAP_PATH": str(
            source / "nodelang" / "data" / "public_runtime_map.json"
        ),
    })
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(DRIVER), phase, str(source), str(state), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=PHASE_TIMEOUT_SECONDS, env=environment, cwd=str(state.parent),
    )
    if completed.returncode != 0:
        pytest.fail("%s phase failed (exit %d):\n%s" % (
            phase, completed.returncode, completed.stderr[-4000:]
        ))
    return completed.stdout


@pytest.fixture(scope="module")
def old_graph(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("zero-idle-old")
    source = _old_source(base / "old-source")
    state = base / "old-state"
    state.mkdir()
    _run("build-old", source, state)
    return state


def _copy_graph(old_state: Path, target: Path) -> Path:
    target.mkdir()
    for item in old_state.iterdir():
        if (item.name.startswith("graph.sqlite3") and not item.name.endswith(".lock")
                or item.name == "old-edit.json"):
            shutil.copy2(item, target / item.name)
    return target


def test_an_old_graph_opened_by_new_code_does_not_grow_while_idle(old_graph, tmp_path):
    state = _copy_graph(old_graph, tmp_path / "state")
    result_path = tmp_path / "zero-idle-result.json"
    _run("idle", _source_under_test(), state, str(result_path))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    baseline = result["baseline"]
    observed = {
        **{"interval %d" % (index + 1): counts
           for index, counts in enumerate(result["intervals"])},
        "close": result["closed"],
        "restart 1": result["restart_1"],
        "restart 2": result["restart_2"],
    }
    grew = {name: counts for name, counts in observed.items() if counts != baseline}
    print("zero-idle baseline [max(revision), cell_versions, current_cells]:", baseline)
    print("zero-idle after:", json.dumps(observed))
    assert len(result["intervals"]) == 10
    assert not grew, (
        "the graph grew while nobody acted: baseline %s, %s; commits: %s"
        % (baseline, json.dumps(grew), json.dumps([
            item for item in result["commits"] if item["phase"] != "warm"
        ][:40]))
    )


def test_old_change_records_undo_and_redo_on_an_old_graph_with_new_code(
    old_graph, tmp_path
):
    """Undo history is a released protocol: an edit recorded by the old
    release (per-change before/after image Cells) must still undo and redo
    after the new code opens its graph, and a new edit must record a compact
    change (images read back from cell_versions) that undoes and redoes."""
    state = _copy_graph(old_graph, tmp_path / "state")
    result_path = tmp_path / "undo-result.json"
    _run("undo-old", _source_under_test(), state, str(result_path))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    old = result["old_edit"]
    print("undo court: old-release edit wrote %d cells; new edit wrote %d cells"
          % (old["cells"], result["new_edit"]["cells"]))
    assert result["opened"] == old["moved"]
    assert result["after_old_undo"] == old["original"]
    assert result["after_old_redo"] == old["moved"]
    assert result["new_edit"]["position"] == ["512.0", "128.0"]
    assert result["after_new_undo"] == old["moved"]
    assert result["after_new_redo"] == ["512.0", "128.0"]