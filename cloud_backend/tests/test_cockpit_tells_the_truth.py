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
# ONE SOURCE: the cockpit .jsx live only in 13.NODE-LANGUAGE/nodelang/studio; the cloud build compiles
# them from there, and cockpit_assets keeps the page, the vendor files and the compiled output.
STUDIO = Path(__file__).resolve().parents[3] / "13.NODE-LANGUAGE" / "nodelang" / "studio"

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


@pytest.fixture(scope="module")
def registry() -> str:
    return read("param-types.js")


# -- 1. a wire is a node: it has parameters, from the shared registry ----------

def test_wire_parameters_are_published_on_the_shared_registry(panels: str, registry: str) -> None:
    """The six connection parameters exist once, in param-types.jsx, for both graphs."""
    assert "window.WIRE_PARAMS" in panels
    for key in ("enabled", "lacing", "tree", "condition", "on_fail", "throttle_ms"):
        assert "'%s'" % key in registry, "wire parameter %s is missing" % key
    for label in ("Lacing", "Data tree", "On block", "Throttle"):
        assert label in registry, "wire parameter label %s is missing" % label


def test_wire_parameter_options_are_the_engine_vocabulary(registry: str) -> None:
    """Dynamo lacing and Grasshopper tree ops, spelled as the design spells them."""
    for option in ("shortest", "longest", "cross product",
                   "flatten", "graft", "simplify",
                   "pass last", "pass empty"):
        assert "'%s'" % option in registry, "option %s is missing" % option


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


def test_the_registry_types_carry_a_colour_and_a_label(registry: str) -> None:
    for kind in ("number", "toggle", "text", "menu", "colour",
                 "elements", "view", "dims", "file", "any"):
        assert re.search(r"\b%s: \{\s*label:" % kind, registry), (
            "type %s is missing from the registry" % kind)


def test_the_registry_is_one_file_every_cockpit_page_loads(panels: str, registry: str) -> None:
    """The panels carried a fallback copy of the registry that had drifted from
    param-types.jsx. The cloud page loads the one file before the panels now, and the
    panels hold no copy of their own."""
    assert "WIRE_PARAMS" in registry and "PM_TYPES" in registry
    assert "cross product" not in panels, "the panels still carry their own wire options"
    assert "label: 'Number'" not in panels, "the panels still carry their own type registry"
    page = (SOURCES / "map.html").read_text(encoding="utf-8")
    assert "compiled/param-types.js" in page, "the cloud page never loads the registry"
    assert page.index("compiled/param-types.js") < page.index("compiled/atlas-panels.js")


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
    # His heading, from the design handoff: the lens is a conversation with
    # the agents, not a log to watch. The rows it renders are still the real
    # task queue, which is what the rest of this court holds (2026-09-07).
    assert "CONVERSATIONS WITH YOUR AGENTS" in side
    assert "SessionComposer" in side, "and there is a way to say something new"


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
    assert "NO LIVE PUSH" in cockpit, "an absent push must be named, not drawn as a model"
    assert "mapMeta" in cockpit
    assert "taken " in cockpit


def test_the_map_says_whether_the_app_is_answering(cockpit: str) -> None:
    assert "app has not answered yet" in cockpit
    assert "app answered " in cockpit
    assert "appSeen" in cockpit


def test_an_empty_map_says_why_it_is_empty(cockpit: str) -> None:
    """With no push the model is empty on purpose; the canvas says so instead of a bare grid."""
    assert "No map yet." in cockpit
    assert "Your app pushed a map with no domains." in cockpit


def test_no_hook_runs_below_the_loading_return(cockpit: str) -> None:
    """A hook after the early return is skipped on the first render and called once the map
    loads; React then throws error 310 and the whole cockpit goes blank."""
    start = cockpit.index("loading the grand map")
    body = cockpit[start:cockpit.index("ARailIcon", start)]
    assert "React.use" not in body, "a hook is declared below the loading return"


# -- 7. nothing on the page is a person or an agent the app did not report ----

def test_the_masthead_names_no_invented_person(cockpit: str) -> None:
    """The design's sample avatar was drawn as if it were the signed-in founder."""
    assert "Mehdi Habib" not in cockpit


def test_every_agent_list_is_the_agents_the_app_reported(panels: str, cockpit: str) -> None:
    """DB.agents started empty and nothing filled it, so every assign list was blank.
    The one list is now derived from the control block the app pushes."""
    assert "reportedAgents(M.control)" in cockpit
    assert "Your app has not reported any agents yet." in panels
    assert "WIRED TO FOUNDER BRAIN" not in panels, "an assignment kept in this page is not wired to the brain"


def test_a_delete_in_the_cockpit_does_not_claim_to_change_the_graph(cockpit: str) -> None:
    """The push owns nodes and wires; a delete here lasts until the next pull."""
    assert "can't be undone" not in cockpit and "can\\'t be undone" not in cockpit
    assert "The graph in your app is not changed" in cockpit


def test_the_refresh_hook_the_ask_bar_calls_exists(cockpit: str) -> None:
    """map.html calls window.ATLAS_RELOAD after a confirmed change, so it must exist."""
    assert "window.ATLAS_RELOAD = reloadMap" in cockpit
    assert "/founder/map-assets/map-data.js" in cockpit
    assert "assembleModel" in cockpit
    page = (SOURCES / "map.html").read_text(encoding="utf-8")
    assert "window.ATLAS_RELOAD" in page, "the ask bar no longer calls the hook"


# -- 8. incidents and model routing are what the cloud and the app hold -------

def test_incidents_are_the_failures_the_cloud_holds(side: str, cockpit: str) -> None:
    """The incident list read a collection this page kept and nothing filled, then said
    Queue clear. It counts failed instruction rows and cloud server errors now, and says it
    cannot tell when neither can be read."""
    assert "DB.issues" not in side, "incidents still come from a list the page keeps"
    assert "Queue clear" not in side
    assert "r.status === 'failed'" in side
    assert "serverErrors" in side and "/founder/api/errors" in cockpit
    assert "cannot tell whether anything failed" in side


def test_model_routing_is_what_the_app_published(side: str) -> None:
    """Routing read a model list nothing filled and claimed a change rewrote the fleet."""
    assert "ctl.models" in side and "ctl.routes" in side
    assert "has not published its model list" in side
    assert "rewrites the fleet" not in side
    assert "setColl('models'" not in side, "a route is still written to a list the page keeps"


# -- 9. the map corner is the one he drew ----------------------------------------

def test_the_map_corner_is_the_designed_one_and_the_truth_chips_sit_in_the_masthead() -> None:
    """His corner holds the model chip and find on one row with the scale ladder below. The
    source and offer chips wrapped that row onto three lines and pushed the ladder over the
    top cards, so they moved into the open span of the masthead (2026-09-17)."""
    if not (STUDIO / "atlas-cockpit.jsx").is_file():
        pytest.skip("the cockpit source tree is not beside this one")
    source = (STUDIO / "atlas-cockpit.jsx").read_text(encoding="utf-8").replace("\r\n", "\n")
    masthead = source[source.index("THE GRAND MAP"):source.index("{/* corner controls */}")]
    corner = source[source.index("{/* corner controls */}"):source.index("{/* SCALE LADDER")]
    assert "Federated model" in corner and "find\u2026" in corner
    for moved in ("LIVE PUSH", "OFFER", "reloadMap"):
        assert moved not in corner, "%s is back in the map corner" % moved
        assert moved in masthead, "%s left the masthead" % moved
    assert "position: 'absolute', top: 12, left: 14, right: 372, display: 'flex', alignItems: 'center'" in corner
    ladder = source[source.index("function ScaleLadder"):source.index("function AtlasCockpit")]
    assert "position: 'absolute', top: 54, left: '50%'" in ladder, "the ladder is not where he drew it"


# -- the built assets: freshness is held by test_the_cockpit_has_one_source.py -------

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
    paths = [COMPILED / "atlas-runtime.js"]
    if (STUDIO / "atlas-runtime.jsx").is_file():
        paths.append(STUDIO / "atlas-runtime.jsx")
    for path in paths:
        name = path.name
        text = path.read_text(encoding="utf-8")
        body = "\n".join(
            line for line in text.split("\n")
            if not line.lstrip().startswith("//"))
        assert "Math.random" not in body, name
        for invented in ("18 rooms", "1,820 tok", "sheet set A.101", "212 elements remapped",
                         "session live", "handshake", "12 rules passed"):
            assert invented not in body, "%s still ships %r" % (name, invented)
        # A node that has not run shows the quiet em dash the founder drew,
        # never an invented result. The words "not run" printed in success
        # green on every watcher card until something ran (2026-09-07).
        assert "—" in body, "%s lost the empty state" % name
        assert "not run" not in body, "%s still writes words where a dash belongs" % name
