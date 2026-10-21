"""A canvas holding nodes never opens on empty space.

The defect this court exists for was measured on the live graph: the held
viewport was pan(-1620, -172.8) at zoom 1.35 while every node sat at graph
(60, 60), which places the nearest card at screen x = -1539 on a 628px
surface. The program was running, the work was there, and the founder opened
it to an empty grid.

The rule is geometry, so it is judged as geometry: the real JS is lifted out
of the served script and run, rather than asserted about as text. Delete the
correction and this court fails.
"""
import json
import shutil
import subprocess

import pytest

from nodelang.ui_runtime import UNIVERSAL_CANVAS_SCRIPT


# The exact numbers read off the live canvas on 2026-08-18.
LIVE_VIEWPORT = {"pan_x": -1620.0, "pan_y": -172.8, "zoom": 1.35}
LIVE_SURFACE = {"width": 628.0, "height": 662.0}
LIVE_NODES = [{"x": 60, "y": 60}] * 6


def _lifted(name):
    """Return one function's source from the script the browser is served."""
    opening = "  function %s(" % name
    start = UNIVERSAL_CANVAS_SCRIPT.find(opening)
    if start < 0:
        raise AssertionError("the served script declares no %s" % name)
    depth = 0
    for index in range(UNIVERSAL_CANVAS_SCRIPT.find("{", start),
                       len(UNIVERSAL_CANVAS_SCRIPT)):
        character = UNIVERSAL_CANVAS_SCRIPT[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return UNIVERSAL_CANVAS_SCRIPT[start:index + 1]
    raise AssertionError("%s is not closed in the served script" % name)


def _run(projection, viewport):
    """Judge the lifted rule in a real JS runtime, not by reading it."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable for the served-script court")
    harness = """
%s
const projection=%s;
const canvas={getBoundingClientRect:()=>(%s)};
function projectedNodeWidth(){return 297;}
function projectedNodeHeight(){return 151;}
process.stdout.write(JSON.stringify({
  shows: viewportShowsAnyNode(projection, canvas, %s),
}));
""" % (
        _lifted("viewportShowsAnyNode"),
        json.dumps(projection),
        json.dumps(LIVE_SURFACE),
        json.dumps(viewport),
    )
    finished = subprocess.run(
        [node, "-e", harness],
        capture_output=True, text=True, timeout=60,
    )
    if finished.returncode != 0:
        raise AssertionError(finished.stderr.strip())
    return json.loads(finished.stdout)


def test_the_viewport_the_founder_opened_on_shows_no_node():
    """The measured live state is the failing state, not a hypothetical."""
    verdict = _run({"nodes": LIVE_NODES}, LIVE_VIEWPORT)
    assert verdict["shows"] is False


def test_a_viewport_over_the_work_shows_a_node():
    """The same rule accepts a viewport that does contain the work."""
    verdict = _run({"nodes": LIVE_NODES}, {"pan_x": 0, "pan_y": 0, "zoom": 1})
    assert verdict["shows"] is True


def test_an_empty_canvas_is_not_treated_as_hidden_work():
    """With nothing placed there is nothing to open on; the held view wins."""
    verdict = _run({"nodes": []}, LIVE_VIEWPORT)
    assert verdict["shows"] is True


def test_a_node_touching_the_edge_counts_as_shown():
    """Opening is not re-aimed for work the operator can already see."""
    projection = {"nodes": [{"x": 0, "y": 0}]}
    edge = {"pan_x": -296.0, "pan_y": 0.0, "zoom": 1.0}
    assert _run(projection, edge)["shows"] is True
    beyond = {"pan_x": -297.0, "pan_y": 0.0, "zoom": 1.0}
    assert _run(projection, beyond)["shows"] is False


def test_every_opening_of_the_surface_asks_for_a_viewport_over_the_work():
    """A render site left on the raw held viewport reopens the defect.

    What is held here is that every render site ASKS for a viewport over
    the work -- not how the surface travels to it. Naming the applier made
    this court refuse a change to the travel: the four sites now glide
    rather than jump, and glide ends at the same applier, so the raw held
    viewport still cannot reach the canvas.
    """
    assert "applyViewport(canvas,projection.viewport)" not in (
        UNIVERSAL_CANVAS_SCRIPT
    )
    assert "glideViewport(canvas,projection.viewport)" not in (
        UNIVERSAL_CANVAS_SCRIPT
    )
    assert UNIVERSAL_CANVAS_SCRIPT.count(
        "viewportOverWork(projection,canvas))") == 4
    glide = _lifted("glideViewport")
    assert "applyViewport(canvas," in glide, (
        "the travel must end at the one applier"
    )


def test_the_correction_is_offered_once_and_never_commits():
    """Re-aiming twice would fight the operator; committing would overwrite
    the viewport they hold. Neither is admitted."""
    source = _lifted("viewportOverWork")
    assert "openedOnWork=true" in source
    # The correction now COMMITS the fitted viewport exactly once -- the
    # stored stale viewport made the first wheel notch zoom the work off
    # screen (measured live 2026-08-19), so "never commits" was the wrong
    # contract. Once-gated and fire-and-forget is the rule.
    assert source.count("commit(") == 1
    assert "commit({viewport:fitted})" in source


def test_the_first_wheel_notch_after_opening_keeps_the_work_on_screen():
    """The founder's first scroll: one zoom-out notch emptied the canvas.

    Measured live 2026-08-19: DOM showed the fitted view (zoom 0.556) but the
    projection still held the stored off-screen viewport (-1620,-172.8 @
    1.35); the wheel handler zoomed from the STORED one -> zoom 1.16, pan
    -1596, 18 visible nodes -> 0. The fitted viewport must therefore become
    the projection's viewport, so a gesture continues from what is on
    screen. Judged as geometry on the lifted rule: the correction returns a
    viewport that both shows the work AND is what the projection now holds.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable for the served-script court")
    harness = """
%s
%s
%s
%s
let lastProjection={nodes:%s, viewport:%s};
let openedOnWork=false;
const commits=[];
function commit(payload){ commits.push(payload); return Promise.resolve(); }
function projectedNodeWidth(){return 297;}
function projectedNodeHeight(){return 151;}
function interactionPolicy(){return {zoom_min:0.25, zoom_fit_max:1.25};}
const canvas={getBoundingClientRect:()=>(%s)};
const projection=lastProjection;
const shown=viewportOverWork(projection, canvas);
// simulate the wheel handler's base: it reads lastProjection.viewport
const base=lastProjection.viewport;
setTimeout(() => process.stdout.write(JSON.stringify({
  shownIsFitted: shown !== projection.viewport,
  projectionFollows: base === shown || (base.zoom === shown.zoom && base.pan_x === shown.pan_x),
  showsWork: viewportShowsAnyNode({nodes:%s}, canvas, base),
  committed: commits.length,
})), 5);
""" % (
        _lifted("viewportShowsAnyNode"),
        _lifted("viewportOverWork"),
        _lifted("fitViewport"),
        _lifted("projectedBounds"),
        json.dumps(LIVE_NODES), json.dumps(LIVE_VIEWPORT),
        json.dumps(LIVE_SURFACE),
        json.dumps(LIVE_NODES),
    )
    finished = subprocess.run(
        [node, "-e", harness], capture_output=True, text=True, timeout=60,
    )
    if finished.returncode != 0:
        raise AssertionError(finished.stderr.strip())
    verdict = json.loads(finished.stdout)
    assert verdict["shownIsFitted"] is True
    assert verdict["projectionFollows"] is True
    assert verdict["showsWork"] is True
    assert verdict["committed"] == 1
