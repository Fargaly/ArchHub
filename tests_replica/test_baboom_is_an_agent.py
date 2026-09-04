"""BABOOM means what it shows: motion = state, the staff = the brain, every command answers."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nodelang.baboom_companion_placement import Rect
from nodelang.baboom_native_visual import BaboomNativeVisualFrame, _MOTION_ROWS
from nodelang.baboom_visual_assets import inspect_baboom_sprite_atlas_v2

SHEET = Path(__file__).resolve().parents[1] / "nodelang" / "data" / "baboom" / "spritesheet.png"


def test_the_staff_orb_is_measured_for_every_drawn_pose():
    atlas = inspect_baboom_sprite_atlas_v2(SHEET)
    for motion, row in _MOTION_ROWS.items():
        for frame in range(atlas.frames_in_row(row)):
            point = atlas.orb_point(row, frame)
            assert point is not None, (motion, frame)
            assert 0 < point[0] < atlas.cell_width and 0 < point[1] < atlas.cell_height


def test_the_staff_lights_with_the_brain():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QImage
    app = QApplication.instance() or QApplication([])
    from nodelang.baboom_native_companion import render_baboom_native_sprite
    atlas_image = QImage(str(SHEET))
    atlas = inspect_baboom_sprite_atlas_v2(SHEET)
    orb = atlas.orb_point(0, 0)
    layout_sprite = Rect(0, 0, 144, 156)
    from nodelang.baboom_companion_placement import BaboomCompanionLayout
    def frame(state):
        return BaboomNativeVisualFrame(
            revision=1, atlas_path=str(SHEET), source=Rect(0, 0, 192, 208),
            layout=BaboomCompanionLayout(sprite=layout_sprite, message=None, edge="bottom-right", overlap_area=0),
            motion="idle", persona_form="steward", report=None, action="", action_label="",
            report_style="flat-no-border", orb=(round(orb[0] * 0.75), round(orb[1] * 0.75)), brain_state=state)
    lit = render_baboom_native_sprite(atlas_image, frame("lit"))
    down = render_baboom_native_sprite(atlas_image, frame("down"))
    unknown = render_baboom_native_sprite(atlas_image, frame("unknown"))
    x, y = round(orb[0] * 0.75), round(orb[1] * 0.75)
    c_lit, c_down, c_unknown = lit.pixelColor(x, y), down.pixelColor(x, y), unknown.pixelColor(x, y)
    assert c_lit.green() > c_lit.red() + 40, "lit orb is cyan"
    assert c_down.red() > c_down.green() + 40, "down orb is red"
    assert c_lit != c_unknown, "an unknown brain paints no light"


def test_every_catalogue_intent_has_an_answer_that_is_not_the_menu():
    import inspect as _i
    import nodelang.universal_application as ua
    src = _i.getsource(ua.respond_universal_baboom_utterance)
    assert "command-guidance" not in src, "the canned menu is gone"
    assert "not-in-this-build" in src
    for intent in ("brain-health", "work-focus", "check-meetings", "archhub-map", "assign-and-claim"):
        assert intent in src, intent
    exec_src = _i.getsource(ua.execute_universal_baboom_utterance)
    assert "assign-and-claim" in exec_src, "take on this task creates Work"


def test_the_lens_names_agents_brain_and_hosts():
    import inspect as _i
    import nodelang.universal_application as ua
    src = _i.getsource(ua.project_universal_baboom_context)
    for key in ("agents_working", "brain_view", "hosts_down"):
        assert key in src, key
    prod = _i.getsource(ua.project_universal_baboom_companion_directive)
    assert "agents-working" in prod and "brain-down" in prod


def test_the_report_names_agents_brain_and_hosts():
    from nodelang.baboom_native_visual import baboom_actionable_report_text
    report = {"data": {
        "governed_work": {"active": 1, "items": [{"state": "claimed", "title": "Wire BABOOM"}]},
        "workshop": {"count": 0},
        "attention": {"blocked_obligations": 0},
        "context": {
            "agents": {"working": [{"title": "Wire BABOOM", "state": "claimed", "agent": "claude"}], "count": 1},
            "brain": {"ok": True, "facts": 2298},
            "hosts": {"down": ["revit"]},
        },
    }}
    text = baboom_actionable_report_text(report)
    assert "claude on: Wire BABOOM" in text
    assert "Brain: 2298 facts." in text
    assert "Hosts down: revit." in text
    dead = {"data": {**report["data"], "context": {"brain": {"ok": False, "facts": 0}}}}
    assert "Brain: not answering." in baboom_actionable_report_text(dead)
    # An older server without a lens leaves the report exactly as it was.
    bare = {"data": {k: v for k, v in report["data"].items() if k != "context"}}
    assert baboom_actionable_report_text(bare) == "Work: 1 active. Workshop: 0 entries. Attention: 0 blocked. Next claimed: Wire BABOOM"


def test_the_launcher_retries_attach_under_its_own_id():
    """connect() binds the identity before start() can time out; a retry under the same
    id is refused as already bound and the founder gets no companion for the session."""
    src = (Path(__file__).resolve().parents[1] / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert 'founder-desktop-baboom:retry-%d' in src
    assert '"already bound" not in text' in src


def test_brain_health_answers_from_the_live_brain_not_a_default():
    import inspect as _i
    import nodelang.universal_application as ua
    import nodelang.application_server as srv
    src = _i.getsource(ua.respond_universal_baboom_utterance)
    assert "brain_state=brain_state, hosts=hosts" in src
    server_src = _i.getsource(srv)
    assert server_src.count("brain_state=self._brain_state()") >= 6, "directive, briefing and responder sites all feed the lens"
    assert server_src.count("brain_state=owner._brain_state()") >= 1, "the machine dispatcher feeds it too"


def test_a_transient_open_error_never_sets_the_graph_aside():
    """2026-09-03: a force-stopped predecessor left the WAL closing; the next launch hit
    'disk I/O error', retried once, then quarantined 337 MB of the founder's graph and
    opened an empty canvas. Transients are retried and then refused, never set aside."""
    src = (Path(__file__).resolve().parents[1] / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert 'for _open_attempt in range(6)' in src
    assert '"disk I/O error", "database is locked", "already owned", "unable to open",' in src
    assert "the graph is kept in place" in src
    assert src.index("the graph is kept in place") < src.index("old data kept in")


def test_every_utterance_answers_end_to_end_on_a_real_graph():
    """A source-level court let a NameError ship: the responder's revision check lost its
    assignment and every BABOOM answer raised. This court speaks to a real graph."""
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_application import build_universal_application, respond_universal_baboom_utterance
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    brain = {"ok": True, "facts": 2298}
    kinds = {}
    for utterance in ("status", "brain health", "brief me on ArchHub", "what matters now", "work focus",
                      "check meetings", "archhub map", "show governed work", "do a backflip"):
        result = respond_universal_baboom_utterance(
            store, registry, utterance=utterance, authentication_context=context, brain_state=brain, hosts=[])
        kinds[utterance] = result["response"]["kind"]
        assert result["command"]["revision"] == store.revision
    assert kinds["brain health"] == "brain-health"
    assert "command-guidance" not in kinds.values()
    health = respond_universal_baboom_utterance(
        store, registry, utterance="brain health", authentication_context=context, brain_state=brain, hosts=[])
    assert health["response"]["data"]["brain"] == {"ok": True, "facts": 2298}
    assert "2298 facts" in health["response"]["summary"]


def test_only_claimed_work_counts_as_an_agent_working():
    import inspect as _i
    import nodelang.universal_application as ua
    src = _i.getsource(ua.project_universal_baboom_context)
    assert 'if state != "claimed":' in src
    assert '{"claimed", "blocked", "review"}' not in src


def test_the_orb_advances_with_the_pose():
    import inspect as _i
    import nodelang.baboom_native_companion as c
    src = _i.getsource(c)
    assert "orb=controller.orb_for(self._frame.motion" in src
    assert "def orb_for(self, motion: str, sprite_size" in src


def test_right_click_is_all_of_archhub_and_run_engine_acts_on_the_graph():
    """BABOOM is the brain and the graph: right-click offers brain, graph runs on the
    brokers, work, agents, reports, updates, cockpit; 'run <engine> on the graph'
    creates the node and runs the pipeline."""
    import inspect as _i
    import nodelang.universal_application as ua
    from nodelang.baboom_native_companion import create_baboom_native_companion_window
    src = _i.getsource(create_baboom_native_companion_window)
    for label in ("Ask the brain...", "Graph: run on the canvas", "Assign a task...", "Agents:", "Know", "Open the cockpit", "def contextMenuEvent"):
        assert label in src, label
    assert any(spec[0] == "run-engine" for spec in ua._BABOOM_COMMAND_SPECS)
    ex = _i.getsource(ua.execute_universal_baboom_utterance)
    assert 'command["intent"] == "run-engine"' in ex and "create_engine_node" in ex and "run_universal_pipeline" in ex
