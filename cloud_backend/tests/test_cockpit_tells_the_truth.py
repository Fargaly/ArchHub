"""The cockpit must SHOW THE DESIGN and must not INVENT NUMBERS.

These read the built assets the browser actually downloads (cockpit_assets/
compiled/*.js) rather than the JSX sources, because a source fix that was never
rebuilt is a fix the founder never sees.

What they hold to:

  (1) A wire is a node, so it has parameters, and they come from the SHARED type
      registry: one definition of what a connection means, read by the cockpit
      and by the inspector in the app.
  (2) A node parameter draws the typed socket glyph on a 34px row, the shape the
      design specifies, not the old bordered card.
  (3) Nothing fabricates a run: no random duration, no random failure, no canned
      per-category result text anywhere the cockpit can reach.
  (4) The Agentic panel carries no invented conversations and no invented dollar
      figure; it renders the agent-task rows the cloud really holds.
  (5) The live control block the app pushes is still rendered: the merge kept it.
  (6) The map says where it came from and when, and the refresh hook the ask bar
      calls exists.

Run: python -m pytest cloud_backend/tests/test_cockpit_tells_the_truth.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parents[1] / "cockpit_assets"
COMPILED = SOURCES / "compiled"

COCKPIT_BUNDLES = ("atlas-panels.js", "atlas-side.js", "atlas-cockpit.js")


def read(name: str) -> str:
    path = COMPILED / name
    assert path.is_file(), (
        "%s is missing. Run: node cloud_backend/tools/build_cockpit_assets.js" % name)
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def panels() -> str:
    return read("atlas-panels.js")


@pytest.fixture(scope="module")
def side() -> str:
    return read("atlas-side.js")


@pytest.fixture(scope="module")
def cockpit() -> str:
    return read("atlas-cockpit.js")


# -- 1. a wire is a node: it has parameters, from the shared registry ----------

def test_wire_parameters_are_published_on_the_shared_registry(panels: str) -> None:
    """The six connection parameters exist once, on window, for both graphs."""
    assert "window.WIRE_PARAMS" in panels
    for key in ("enabled", "lacing", "tree", "condition", "on_fail", "throttle_ms"):
        assert "'%s'" % key in panels, "wire parameter %s is missing" % key
    for label in ("Lacing", "Data tree", "On block", "Throttle"):
        assert label in panels, "wire parameter label %s is missing" % label


def test_wire_parameter_options_are_the_engine_vocabulary(panels: str) -> None:
    """Dynamo lacing and Grasshopper tree ops, spelled as the design spells them."""
    for option in ("shortest", "longest", "cross product",
                   "flatten", "graft", "simplify",
                   "pass last", "pass empty"):
        assert "'%s'" % option in panels, "option %s is missing" % option


def test_the_wire_inspector_reads_the_registry_not_a_local_copy(panels: str) -> None:
    """WirePanel builds its rows from window.WIRE_PARAMS, so one edit moves both."""
    assert "WIRE PARAMETERS" in panels
    body = panels[panels.index("function WirePanel"):]
    assert "WIRE_PARAM_DEFS" in body
    defs = panels[panels.index("WIRE_PARAM_DEFS ="):]
    assert "window.WIRE_PARAMS" in defs[:400]


def test_the_wire_inspector_can_change_a_wire_parameter(panels, cockpit) -> None:
    """A control that cannot write is decoration. The panel takes patchWire, and the
    cockpit supplies one that stores the value on the wire records themselves."""
    assert "patchWire" in panels
    assert "patchWire(members, patch)" in cockpit
    assert "patchWire: patchWire" in cockpit


# -- 2. the node parameter row is the row the design drew ---------------------

def test_a_parameter_row_draws_the_typed_socket(panels: str) -> None:
    """Colour is the type, shape is the cardinality, and the socket promotes."""
    assert "ptypeSocket" in panels
    assert "window.PM_TYPES" in panels
    stem = panels[panels.index("function StemParams"):]
    assert "ptypeSocket(t, on)" in stem, "the parameter row does not draw a socket"


def test_a_parameter_row_is_34px_and_flat(panels: str) -> None:
    """The design specifies a 34px hairline row, not a bordered card."""
    stem = panels[panels.index("function StemParams"):panels.index("function NodeInspector")]
    assert "minHeight: 34" in stem
    card = stem[:stem.index("addBtn")]
    assert "borderRadius: 8" not in card, (
        "the parameter row is still drawn as a rounded card")


def test_the_registry_types_carry_a_colour_and_a_label(panels: str) -> None:
    for kind in ("number", "toggle", "text", "menu", "colour",
                 "elements", "view", "dims", "file", "any"):
        assert re.search(r"\b%s: \{\s*label:" % kind, panels), (
            "type %s is missing from the registry" % kind)


# -- 3. nothing invents a run -------------------------------------------------

@pytest.mark.parametrize("name", COCKPIT_BUNDLES)
def test_no_bundle_rolls_a_random_run_outcome(name: str) -> None:
    """A random duration or a random failure presented as a run is invented data."""
    text = read(name)
    for line in text.splitlines():
        if "Math.random" not in line:
            continue
        assert not re.search(r"Math\.random\(\) *[<>]", line), (
            "%s decides an outcome with a coin flip: %s" % (name, line.strip()))
        head = line.split("Math.random")[0]
        assert "ms" not in head[-24:], (
            "%s invents a duration: %s" % (name, line.strip()))


@pytest.mark.parametrize("name", COCKPIT_BUNDLES)
def test_no_bundle_calls_the_fabricating_run_maker(name: str) -> None:
    """mkRun and rtResult make up an outcome and a result string. Nothing calls them."""
    text = read(name)
    assert "mkRun" not in text, "%s still fabricates a run" % name
    assert "rtResult" not in text, "%s still fabricates a result string" % name


def test_a_node_without_an_engine_says_there_is_nothing_to_run(cockpit: str) -> None:
    """Run on an engineless node reports the truth, not a manufactured result."""
    body = cockpit[cockpit.index("runNode ="):cockpit.index("runVariant =")]
    assert "no engine" in body
    assert "nothing to run" in body
    assert "setTimeout" not in body, (
        "a fabricated run is still being timed out into existence")


def test_only_a_node_with_an_engine_relays_to_the_app(cockpit: str) -> None:
    body = cockpit[cockpit.index("runNode ="):cockpit.index("runVariant =")]
    assert "node.engine" in body
    assert "run engine " in body
    assert "/founder/api/command" in body


def test_a_variant_re_runs_rather_than_making_a_second_result(cockpit: str) -> None:
    body = cockpit[cockpit.index("runVariant ="):cockpit.index("addWatcher =")]
    assert "nothing to re-run" in body
    assert "runNode(id)" in body


# -- 4. the agentic panel carries no fixtures ---------------------------------

def test_the_agentic_panel_has_no_scripted_conversations(side: str) -> None:
    """The four hand-written founder and agent exchanges are gone."""
    assert "seedSessions" not in side
    for invented in ("Monetization gaps",
                     "Brain recall latency regression",
                     "Connector fleet health sweep",
                     "Self-extension proposal review",
                     "Recall p50 rose"):
        assert invented not in side, "invented conversation still present: %s" % invented


def test_the_agentic_panel_has_no_invented_spend(side: str) -> None:
    """No hardcoded call volumes, no rate maths, no dollar total."""
    assert "42000" not in side and "8600" not in side, "hardcoded call volumes are back"
    assert "EST / MONTH" not in side
    assert "String.fromCharCode(36)" not in side, "a dollar figure is being assembled"
    assert "spendByVendor" not in side
    assert "Not measured" in side, "the panel must say plainly that spend is unknown"


def test_the_sessions_lens_renders_real_agent_task_rows(side: str) -> None:
    """The real record of the founder talking to his app is the task queue."""
    assert "directive" in side
    assert "claimed_by" in side
    assert "taskStamp" in side
    assert "WHAT YOU ASKED YOUR APP" in side


def test_the_cockpit_feeds_the_panel_real_rows(cockpit: str) -> None:
    assert "/founder/api/agent-tasks" in cockpit
    assert "setAgentTasks" in cockpit
    assert "tasks: agentTasks" in cockpit


def test_an_unmeasured_duration_is_not_printed(side: str) -> None:
    """A relayed run reports no duration. Printing 0ms would be a made-up number."""
    assert "r.ms ?" in side


# -- 5. the live control block survived the merge -----------------------------

def test_the_live_control_block_is_still_rendered(panels: str) -> None:
    """Bringing the design across must not drop what the running app pushes."""
    assert "LiveDomainControl" in panels
    for marker in ("IN YOUR APP", "AGENTS ON YOUR MACHINE",
                   "GOVERNED WORK", "work_items", "work_summary"):
        assert marker in panels, "the live control block lost %s" % marker


def test_the_open_buttons_for_hosts_survived(panels: str) -> None:
    assert "OPENABLE" in panels
    for host in ("excel", "word", "powerpoint", "outlook", "rhino", "blender"):
        assert "'%s'" % host in panels, "host %s can no longer be opened" % host


# -- 6. the map says where it came from, and refresh is real ------------------

def test_the_map_states_its_source_and_when_it_was_taken(cockpit: str) -> None:
    assert "LIVE PUSH" in cockpit
    assert "AUTHORED MODEL" in cockpit
    assert "mapMeta" in cockpit
    assert "taken " in cockpit


def test_the_map_says_whether_the_app_is_answering(cockpit: str) -> None:
    assert "app has not answered yet" in cockpit
    assert "app answered " in cockpit
    assert "appSeen" in cockpit


def test_the_refresh_hook_the_ask_bar_calls_exists(cockpit: str) -> None:
    """map.html calls window.ATLAS_RELOAD after a confirmed change, so it must exist."""
    assert "window.ATLAS_RELOAD = reloadMap" in cockpit
    assert "/founder/map-assets/map-data.js" in cockpit
    assert "assembleModel" in cockpit
    page = (SOURCES / "map.html").read_text(encoding="utf-8")
    assert "window.ATLAS_RELOAD" in page, "the ask bar no longer calls the hook"


# -- the built assets match the sources they were built from ------------------

@pytest.mark.parametrize("stem", ("atlas-panels", "atlas-side", "atlas-cockpit"))
def test_the_built_asset_is_newer_than_its_source(stem: str) -> None:
    """A source edit that was never rebuilt never reaches the browser."""
    src = SOURCES / (stem + ".jsx")
    out = COMPILED / (stem + ".js")
    assert out.stat().st_mtime >= src.stat().st_mtime, (
        "%s.js is stale. Run: node cloud_backend/tools/build_cockpit_assets.js" % stem)


def test_the_inspector_run_list_omits_an_unmeasured_duration(panels: str) -> None:
    """A relayed run carries no duration. The row prints the field only when it exists."""
    assert "RunsList" in panels
    body = panels[panels.index("RunsList = function"):]
    assert "r.ms ?" in body[:4000], "the run row prints a duration it was never given"


def test_the_relayed_run_record_carries_no_duration(cockpit: str) -> None:
    """The app reports an outcome and a text, not a timing. Do not store a zero."""
    body = cockpit[cockpit.index("runNode ="):cockpit.index("runVariant =")]
    assert "r_app_" in body, "the relayed run record is missing"
    assert "ms: 0" not in body, "a zero duration is being stored as if it were measured"


def test_the_runtime_bundle_invents_neither_a_result_nor_a_duration():
    """The last fabricator lived one file away from the cockpit's own guard.

    atlas-runtime.js was outside the bundle list the other guard walks, so it
    kept a per-category fixture ("18 rooms - 96 walls", "1,820 tok - $0.04")
    and a run maker that rolled a duration and an 8 percent failure. A watcher
    card read like it had measured something on a canvas where nothing had run.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "cockpit_assets"
    for name in ("atlas-runtime.jsx", "compiled/atlas-runtime.js"):
        text = (root / name).read_text(encoding="utf-8")
        body = "\n".join(
            line for line in text.split("\n")
            if not line.lstrip().startswith("//"))
        assert "Math.random" not in body, name
        for invented in ("18 rooms", "1,820 tok", "sheet set A.101", "212 elements remapped",
                         "session live", "handshake", "12 rules passed"):
            assert invented not in body, "%s still ships %r" % (name, invented)
        assert "not run" in body  # a node that has not run says exactly that
