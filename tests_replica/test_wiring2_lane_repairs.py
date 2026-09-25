"""wiring2: one Run, one library, one presence, real cockpit values, real parameters.

Audit at 72bcaae, re-checked on 35d3e8f; each finding pinned by courts that
fail on 35d3e8f and pass with the wiring2 patch:

1. Two Run engines: the clean stem runner carried no effect engines, the
   pipeline runner ignored rules.engine, and the two Studios posted Run to
   different routes.
2. Two node libraries: Studio typed its own AH_LIBRARY; a shared engine could
   not get its card's defaults; the signed Studio sent an item id as a
   definition id.
3. Two presence sources: the run-graph route replaced the graph's own
   baboom.presence engine with an in-memory session list.
4. The cockpit map collapsed a node's status to live/partial and cut values to
   48 characters, and editing wrote the cut copy back, swallowing errors.
5. The cockpit minted an Attention node, watcher nodes, adapter nodes and
   local wires that no graph held.
6. The base AI (ai.master) and Skill (skill.wrap) stems always pended.
7. If/Else condition, Switch cases, Number min/max/step and File extensions
   were read by no code; dimension presets set rows no engine reads; the
   Speckle connector said "no wire" while push_speckle exists.
8. Wire lacing/tree/condition/on_fail/throttle were drawn but any non-default
   refused the whole run.
9. The logic cards advertised branches and inputs their sockets lacked.
"""
from __future__ import annotations

import json
import re
import uuid as _uuid
from pathlib import Path

import pytest

from nodelang import universal_application as app
from nodelang.map_import import resolve_map_path
from nodelang.stem_graph_evaluation import StemNode, StemWire, evaluate_stem_graph
from nodelang.universal_application import (
    build_universal_application,
    connect_universal_roots,
    create_universal_property,
    project_universal_canvas,
)
from nodelang.universal_pipeline import (
    _owner_properties,
    create_engine_node,
    project_atlas_map,
    run_universal_pipeline,
)
from tests_replica.test_workshop_milestone_one import harness  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "nodelang" / "studio"


def _read(name: str) -> str:
    return (STUDIO / name).read_text(encoding="utf-8")


@pytest.fixture()
def graph():
    store, registry = build_universal_application(resolve_map_path())
    try:
        yield store, registry
    finally:
        store.close()


def _port(projection, root, side, name):
    node = next(node for node in projection["nodes"] if node["id"] == root)
    return next(
        (port for port in node["ports"]
         if port.get("owner") == root and port.get("side") == side and port.get("name") == name),
        None,
    )


def _wire(store, registry, source, source_name, target, target_name):
    projection = project_universal_canvas(store, registry)
    out = _port(projection, source, "source", source_name)
    socket = _port(projection, target, "target", target_name)
    assert out is not None and socket is not None, (source_name, target_name)
    wire_root, _revision = connect_universal_roots(
        store, registry, source, target,
        source_interface=out["id"], target_interface=socket["id"],
    )
    return wire_root


# ---------------------------------------------------------------- finding 1

def test_f1_clean_run_graph_route_runs_ai_skill_and_number_on_one_engine_table(tmp_path, monkeypatch):
    """The signed Studio presses Run on /api/universal/run-graph (the route the
    other Studio uses), and the clean runner carries the pipeline engines: the
    base AI and Skill stems answer instead of pending."""
    from nodelang import pipeline_engines
    from nodelang.base_universal_catalogue import install_base_universal_catalogue
    from nodelang.clean_browser_authority import revise_clean_browser_focus
    from nodelang.unified_authority import instantiate_definition, published_definition_named
    from tests_replica.test_clean_server_visual_projection import (
        _issue_clean_session,
        _json,
        _provision_clean_runtime,
        _start_clean_server,
    )

    monkeypatch.delenv("ARCHHUB_AGENT_MODEL", raising=False)
    skill_file = tmp_path / "court-skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("---\nname: court-skill\n---\nMeasure twice.\n", encoding="utf-8")
    monkeypatch.setattr(pipeline_engines, "skills_catalogue", lambda params, feeds: (
        {"out": [{"name": "court-skill", "description": "", "path": str(skill_file), "source": "court"}]},
        "1 skill"))

    built, provider = _provision_clean_runtime(tmp_path)
    install_base_universal_catalogue(built.location.authority, caller=built.caller)
    server = _start_clean_server(built, provider)
    token, csrf = "wiring2-token", "wiring2-csrf"
    # Lock-light: an effect runs while the graph lock is free for other routes.
    import threading
    lock_free = []
    from nodelang import library_engines
    real_skill = library_engines.STEM_EFFECT_ENGINES["skill.wrap"]

    def probing_skill(params, feeds):
        taken = []
        other = threading.Thread(target=lambda: taken.append(
            server._mutation_lock.acquire(timeout=5) and (server._mutation_lock.release() or True)))
        other.start()
        other.join()
        lock_free.append(bool(taken and taken[0]))
        return real_skill(params, feeds)

    monkeypatch.setitem(library_engines.STEM_EFFECT_ENGINES, "skill.wrap", probing_skill)
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        auth, caller = built.location.authority, built.caller
        door = built.grand_map.root_id

        def place(name, values):
            return instantiate_definition(
                auth, published_definition_named(auth, name, caller=caller), values,
                scope_root=door, caller=caller, command_id=str(_uuid.uuid4())).root_id

        num = place("Number", {"value": "42"})
        res = place("Result", {})
        skill = place("Skill", {"name": "court-skill"})
        ai = place("AI", {"action": "think", "prompt": "hello"})
        st, wired = _json(server.url, "/api/universal/connect",
                          {"source": num, "source_interface": "value",
                           "target": res, "target_interface": "value"},
                          token=token, csrf=csrf)
        assert st == 200, wired
        binding = server._resolve_binding(token)
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[num], primary_root=num,
            caller=caller, command_id=str(_uuid.uuid4()))
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert st == 200
        run_binding = next(item for item in canvas["interaction_projection"]["bindings"]
                           if item["control"] == "app:control:canvas:run")
        st, ran = _json(server.url, "/api/universal/run-graph",
                        {"interaction": run_binding["interaction"],
                         "control": run_binding["control"],
                         "event": run_binding["event"],
                         "revision": canvas["interaction_projection"]["revision"]},
                        token=token, csrf=csrf)
        assert st == 200, ran
        assert ran["ran"] == "stem-graph"
        assert ran["results"] == {"result": 42}
        assert skill not in ran["pending"], ran["pending"]
        assert "court-skill" in ran["display"][skill]
        assert ai not in ran["pending"], ran["pending"]
        assert ran["display"][ai].startswith("think: ")
        assert lock_free == [True], "the effect ran while the graph lock was held"
        # Without the CSRF token the route refuses and runs nothing.
        before = len(lock_free)
        st, refused = _json(server.url, "/api/universal/run-graph",
                            {"interaction": run_binding["interaction"],
                             "control": run_binding["control"],
                             "event": run_binding["event"],
                             "revision": canvas["interaction_projection"]["revision"]},
                            token=token, csrf="wrong-csrf")
        assert st != 200 and refused.get("ok") is False, refused
        assert len(lock_free) == before
        # Run refuses anything that is not the scope's Run control.
        st, refused = _json(server.url, "/api/universal/run-graph",
                            {"control": num}, token=token, csrf=csrf)
        assert st != 200 and refused.get("ok") is False, refused
    finally:
        server.close()
        built.location.authority.store.close()


def test_f1_pipeline_run_reads_the_definition_rules_engine(graph, monkeypatch):
    """A node with no engine row runs the engine its definition's rules declare."""
    from nodelang import universal_pipeline

    store, registry = graph
    projection = project_universal_canvas(store, registry)
    definition = next(item["id"] for item in projection["catalog"] if item["name"] == "Ordered List")
    root, _revision = app.instantiate_universal_definition(store, registry, definition, x=10.0, y=10.0)
    original = universal_pipeline.project_universal_canvas

    def with_rules(*args, **kwargs):
        held = original(*args, **kwargs)
        for node in held["nodes"]:
            if node["id"] == root:
                node["assembly"] = dict(node.get("assembly") or {}, rules=[
                    {"id": "rule", "label": "rule", "value": json.dumps({"engine": "library.add_text"})}])
        return held

    monkeypatch.setattr(universal_pipeline, "project_universal_canvas", with_rules)
    create_universal_property(store, registry, root, "text", "FFL +0.00")
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    ran = run_universal_pipeline(store, registry, effect_engines=PIPELINE_ENGINES, only_roots=[root])
    assert ran["ran"] == 1, ran
    assert root in ran["display"], ran


def test_f1_both_studios_press_run_on_one_route():
    html = _read("studio.html")
    authority = _read("studio-authority.js")
    start = authority.index("      run() {")
    run = authority[start:start + 2000]
    assert "jpost('/api/universal/run-graph'" in html
    assert "post('/api/universal/run-graph', request)" in run
    assert "post('/api/universal/interaction', request)" not in run


# ---------------------------------------------------------------- finding 2

def test_f2_the_item_id_gives_a_shared_engine_its_own_defaults(graph):
    store, registry = graph
    for item, field in (("f_type", "type"), ("f_cat", "category"), ("f_level", "level")):
        root = create_engine_node(store, registry, title=item, engine="library.filter_field", item=item)["root"]
        assert _owner_properties(store.snapshot(), registry)[root]["field"][1] == field
    with pytest.raises(ValueError):
        create_engine_node(store, registry, title="x", engine="library.sort_by", item="f_type")


def test_f2_studio_reads_the_one_served_library(harness):
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    harness.start()
    served = harness.request("/api/universal/node-library")
    items = {item["id"]: item for group in served["groups"] for item in group["items"]}
    assert set(items) == set(LIBRARY_ITEM_ENGINES)
    for item, entry in items.items():
        assert entry["engine"] == LIBRARY_ITEM_ENGINES[item]["engine"]
        assert entry["params"] == LIBRARY_ITEM_ENGINES[item]["params"]
    assert served["categories"]["lines.watch"] == "annotate"
    created = harness.request("/api/universal/node-create", {
        "item": "f_level", "title": "where level", "engine": "library.filter_field",
        "x": 100, "y": 100, "params": {}})
    canvas = harness.request("/api/universal/canvas")
    rows = {row["label"]: row["value"] for row in canvas["properties"] if row["owner"] == created["root"]}
    assert rows.get("field") == "level", rows
    registry_js = _read("node-registry.jsx")
    assert "AH_LIBRARY = [" not in registry_js and "engine:'" not in registry_js
    assert "jget('/api/universal/node-library')" in _read("studio.html")


def test_f2_signed_studio_never_sends_an_item_id_as_a_definition():
    source = _read("studio-lm.jsx")
    body = source[source.index("const addNodeFromLibrary = "):source.index("// Docs and Settings are mutually exclusive")]
    assert "libItem.definition || libItem.id" not in body
    assert "definition: libItem.definition," in body
    assert ".catch(() => false)" not in body
    assert "item: libItem.id" in body


# ---------------------------------------------------------------- finding 3

def test_f3_card_and_presence_routes_read_one_source(harness, monkeypatch):
    """The BABOOM Presence card, run-graph and every BABOOM presence route
    (baboom-presence, baboom-context, native frame via
    _machine_agent_runtime_presence) give one answer: the graph's leases.
    An in-memory session with no lease is not BABOOM being here."""
    import time as _time
    from types import SimpleNamespace
    from nodelang import cell_runtime_presence

    server = harness.start()
    with server._machine_agent_session_lock:
        server._machine_agent_sessions["app:agent-session:runtime:court"] = {
            "runtime": "baboom", "expires_at": _time.time() + 3600}
    seeded = harness.request("/api/universal/pipeline-seed", {})
    card = seeded["placed"]["BABOOM Presence"]

    def card_says():
        ran = harness.request("/api/universal/run-graph", {})
        return ran["display"].get(card) or ran["pending"].get(card)

    route = server._machine_agent_runtime_presence()
    assert route["baboom_connected"] is False and route["active_runtime_sessions"] == 0, route
    assert card_says().startswith("companion not attached · 0 signed runtime session(s)")

    leased = (SimpleNamespace(runtime="baboom", expires_at=_time.time() + 60),)
    monkeypatch.setattr(cell_runtime_presence, "list_active_runtime_presences",
                        lambda snapshot, protocol, now, lease_storage=None: leased)
    route = server._machine_agent_runtime_presence()
    assert route["baboom_connected"] is True and route["active_runtime_sessions"] == 1, route
    assert route["current_runtime_device_proven"] is True
    assert card_says().startswith("companion ATTACHED · 1 signed runtime session(s)")


# ---------------------------------------------------------------- finding 4

def test_f4_the_map_carries_real_status_and_the_full_value(graph):
    from nodelang.universal_application import set_universal_scope
    store, registry = graph
    # The map draws the members of the top-level domains: place one inside one.
    set_universal_scope(store, registry, registry.map.domains["website"])
    root = create_engine_node(store, registry, title="Note", engine="library.add_text",
                              properties={"text": "N" * 90})["root"]
    create_universal_property(store, registry, root, "status", "3 rows x 2 columns")
    set_universal_scope(store, registry, "app:canvas")
    held = project_atlas_map(store, registry)
    atlas = json.loads(held[len("window.ATLAS_MAP = "):held.index("; window.ATLAS_LIVE")])
    node = next(node for node in atlas["nodes"] if node["id"] == root)
    assert node["status_text"] == "3 rows x 2 columns"
    rows = {row["k"]: row for row in node["params"]}
    assert rows["text"]["v"] == "N" * 48 and rows["text"]["full"] == "N" * 90


def test_f4_map_param_rows_hold_the_full_value_and_hide_paths():
    from nodelang.universal_pipeline import _atlas_param
    long = _atlas_param("text", "rel:1", "N" * 90)
    assert long["v"] == "N" * 48 and long["full"] == "N" * 90
    path = _atlas_param("image_path", "rel:2", "C:\\drawings\\plan.png")
    assert path["v"] == "plan.png" and "full" not in path and path["editable"] is False


def test_f4_cockpit_edits_the_full_value_and_shows_write_errors():
    panels = _read("atlas-panels.jsx")
    start = panels.index("function StemParams(")
    body = panels[start:panels.index(chr(10) + "}" + chr(10), start)]
    assert ".catch(() => {})" not in body
    assert "setWriteError('Not saved: '" in body
    assert "value={fullValue(p)}" in body
    assert "node.status_text" in panels


# ---------------------------------------------------------------- finding 5

def test_f5_the_cockpit_invents_no_nodes_or_wires():
    cockpit = _read("atlas-cockpit.jsx")
    assert "id: 'sys_attention'" not in cockpit
    assert "'adp_' + Date.now()" not in cockpit
    assert "'watch_' + Date.now()" not in cockpit
    connect = cockpit[cockpit.index("const connectNodes = "):cockpit.index("const disconnectWire = ")]
    assert "setM(" not in connect
    watcher = cockpit[cockpit.index("const addWatcher = "):cockpit.index("const patchDomain = ")]
    assert "setM(" not in watcher


# ---------------------------------------------------------------- finding 6

def test_f6_ai_and_skill_stems_are_effect_engines(monkeypatch):
    from nodelang.agent_composer import NO_MODEL_CHOSEN
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    monkeypatch.delenv("ARCHHUB_AGENT_MODEL", raising=False)
    nodes = [StemNode("ai", "ai.master", {"action": "think", "model": "", "prompt": "x"}),
             StemNode("skill", "skill.wrap", {"name": ""})]
    evaluation = evaluate_stem_graph(nodes, [], None, PIPELINE_ENGINES)
    assert evaluation.display["ai"] == "think: " + NO_MODEL_CHOSEN
    assert evaluation.pending["skill"] == "set the name parameter to a saved skill"


# ---------------------------------------------------------------- finding 7

def test_f7_if_else_evaluates_its_condition():
    nodes = [StemNode("list", "data.list", {"value": "[1, 2]"}),
             StemNode("gate", "control.if", {"condition": "count > 2"})]
    wires = [StemWire("list", "value", "gate", "value")]
    assert evaluate_stem_graph(nodes, wires).display["gate"] == "false"
    nodes[1] = StemNode("gate", "control.if", {"condition": "count >= 2"})
    assert evaluate_stem_graph(nodes, wires).display["gate"] == "true"
    nodes[1] = StemNode("gate", "control.if", {"condition": "item.match(/x/)"})
    assert "not one this version evaluates" in evaluate_stem_graph(nodes, wires).pending["gate"]


def test_f7_switch_routes_by_its_cases():
    nodes = [StemNode("v", "data.constant", {"value": "7"}),
             StemNode("k", "data.constant", {"value": "door"}),
             StemNode("s", "control.switch", {"cases": "wall, door, window"})]
    wires = [StemWire("v", "value", "s", "value"), StemWire("k", "value", "s", "key")]
    evaluation = evaluate_stem_graph(nodes, wires)
    assert evaluation.node_outputs["s"] == {"b": 7}
    nodes[1] = StemNode("k", "data.constant", {"value": "roof"})
    assert "matches no case" in evaluate_stem_graph(nodes, wires).pending["s"]


def test_f7_number_and_file_enforce_their_declared_limits():
    over = StemNode("n", "data.constant", {"value": "12", "min": "0", "max": "10", "step": "1"})
    assert evaluate_stem_graph([over], []).pending["n"] == "value 12 is above max 10"
    off = StemNode("n", "data.constant", {"value": "2.5", "min": "", "max": "", "step": "1"})
    assert "not on a step" in evaluate_stem_graph([off], []).pending["n"]
    good = StemNode("n", "data.constant", {"value": "4", "min": "0", "max": "10", "step": "2"})
    assert evaluate_stem_graph([good], []).display["n"] == "4"
    wrong = StemNode("f", "data.constant", {"value": "C:/a/plan.png", "extensions": ".dxf, dwg"})
    assert "is not one of .dxf, .dwg" in evaluate_stem_graph([wrong], []).pending["f"]
    right = StemNode("f", "data.constant", {"value": "C:/a/plan.DXF", "extensions": ".dxf"})
    assert evaluate_stem_graph([right], []).display["f"] == "C:/a/plan.DXF"


def test_f7_dimension_presets_set_only_rows_the_engine_reads():
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    source = _read("studio-params.jsx")
    block = source[source.index("const PM_PRESETS = {"):source.index("};", source.index("const PM_PRESETS = {"))]
    keyed = re.findall(r"^\s{2}'([\w.]+)': \[", block, re.M)
    assert keyed == ["library.dimensions"], keyed
    read = set(LIBRARY_ITEM_ENGINES["a_dims"]["params"])
    for vals in re.findall(r"vals: \{([^}]*)\}", block):
        assert {key.strip().split(":")[0] for key in vals.split(",")} <= read, vals
    assert "PM_PRESETS[node.cat]" not in source and "PM_PRESETS[node.id]" not in source


def test_f7_old_studio_holds_no_template_or_port_type_copy():
    assert "LM_NODE_TEMPLATES" not in _read("studio-lm.jsx")
    assert "PORT_TYPES" not in _read("studio.html")


def test_f7_speckle_names_its_wire():
    from nodelang.pipeline_engines import PIPELINE_ENGINES, probe_connectors
    row = next(row for row in probe_connectors() if row["id"] == "speckle")
    assert row["drive"] == "library.push_speckle" in PIPELINE_ENGINES
    assert "no wire" not in row["detail"]


# ---------------------------------------------------------------- finding 8

def test_f8_wire_rows_are_applied_by_the_evaluator():
    rows = StemNode("rows", "data.list", {"value": "[[1, [2]], [3]]"})
    count = StemNode("count", "shape.count", {})
    flat = evaluate_stem_graph([rows, count], [StemWire("rows", "value", "count", "items", tree="flatten")])
    assert flat.display["count"] == "3"
    blocked = evaluate_stem_graph([rows, count], [StemWire("rows", "value", "count", "items", condition="count > 5")])
    assert blocked.pending["count"] == "blocked by wire condition 'count > 5'"
    empty = evaluate_stem_graph([rows, count], [StemWire("rows", "value", "count", "items",
                                                         condition="count > 5", on_fail="pass empty")])
    assert empty.display["count"] == "0"


def test_f8_a_wire_condition_runs_instead_of_refusing_the_run(graph):
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    store, registry = graph
    note = create_engine_node(store, registry, title="Note", engine="library.add_text",
                              properties={"text": "A"})["root"]
    merge = create_engine_node(store, registry, title="Merge", engine="library.merge", x=500.0)["root"]
    wire = _wire(store, registry, note, "out", merge, "in")
    from nodelang.universal_pipeline import _ensure_wire_parameters
    _ensure_wire_parameters(store, registry, wire)
    rows = _owner_properties(store.snapshot(), registry)[wire]
    app.edit_universal_property(store, registry, rows["condition"][0], "count > 5")
    ran = run_universal_pipeline(store, registry, effect_engines=PIPELINE_ENGINES, only_roots=[note, merge])
    assert ran["pending"][merge] == "blocked by wire condition 'count > 5'"
    create_universal_property(store, registry, wire, "lacing", "longest")
    with pytest.raises(app.InvalidCell):
        run_universal_pipeline(store, registry, effect_engines=PIPELINE_ENGINES, only_roots=[note, merge])


def test_f8_the_wire_rows_have_one_source_the_server_serves(harness):
    """Studio and the cockpit draw the wire rows the server serves; no page
    or registry types them again, and every row is one the run applies."""
    from nodelang.universal_pipeline import _WIRE_PARAMETERS, WIRE_PARAMETER_SPECS
    harness.start()
    served = harness.request("/api/universal/node-library")["wire_parameters"]
    assert [row["k"] for row in served] == [key for key, _default in _WIRE_PARAMETERS]
    assert served == [dict(spec) for spec in WIRE_PARAMETER_SPECS]
    assert {key for key, _default in _WIRE_PARAMETERS} == {"enabled", "tree", "condition", "on_fail"}
    assert "const WIRE_PARAMS = [" not in _read("param-types.jsx")
    assert "window.WIRE_PARAMS = nodeLibrary.wire_parameters" in _read("studio.html")
    assert "window.WIRE_PARAMS = answer.wire_parameters" in _read("cockpit.html")


# ---------------------------------------------------------------- finding 9

def test_f9_logic_cards_carry_the_sockets_they_advertise(graph):
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    store, registry = graph
    gate = create_engine_node(store, registry, title="if", engine="library.if")["root"]
    switch = create_engine_node(store, registry, title="switch", engine="library.switch", x=300.0)["root"]
    loop = create_engine_node(store, registry, title="loop", engine="library.loop", x=600.0)["root"]
    merge = create_engine_node(store, registry, title="merge", engine="library.merge", x=900.0)["root"]
    projection = project_universal_canvas(store, registry)
    for root, side, name in ((gate, "source", "false"), (gate, "target", "condition"),
                             (switch, "source", "b"), (switch, "target", "key"),
                             (loop, "source", "each"), (merge, "target", "b")):
        port = _port(projection, root, side, name)
        assert port is not None and port["connectable"] is True, (root, side, name)
    first = create_engine_node(store, registry, title="A", engine="library.add_text", properties={"text": "A"}, x=0.0, y=600.0)["root"]
    second = create_engine_node(store, registry, title="B", engine="library.add_text", properties={"text": "B"}, x=0.0, y=900.0)["root"]
    _wire(store, registry, first, "out", merge, "in")
    _wire(store, registry, second, "out", merge, "b")
    ran = run_universal_pipeline(store, registry, effect_engines=PIPELINE_ENGINES, only_roots=[first, second, merge])
    assert ran["display"][merge] == "2 items concatenated", ran

def test_f4_f5_the_cockpit_sources_still_compile():
    """The cockpit loads these through in-browser Babel, outside the Studio build."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "const fs=require('fs'),vm=require('vm'),path=require('path');"
        "const dir=process.argv[1];const B={};"
        "vm.runInNewContext(fs.readFileSync(path.join(dir,'vendor/babel.js'),'utf8'),{exports:B,module:{exports:B}});"
        "for(const f of ['atlas-cockpit.jsx','atlas-panels.jsx']){"
        "new vm.Script(B.transform(fs.readFileSync(path.join(dir,f),'utf8'),{presets:['env','react']}).code);}"
        "console.log('parsed');"
    )
    done = subprocess.run([node, "-e", script, str(STUDIO)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "parsed" in done.stdout, done.stderr[-500:]


def _old_shape_logic_card(store, registry, engine, x=0.0):
    """A logic card as a build before 2026-09-24 placed it: out/in only."""
    from nodelang.universal_pipeline import _ensure_pipeline_node_interfaces
    projection = project_universal_canvas(store, registry)
    definition = next(item["id"] for item in projection["catalog"] if item["name"] == "Ordered List")
    root, _revision = app.instantiate_universal_definition(store, registry, definition, x=x, y=40.0)
    create_universal_property(store, registry, root, "engine", engine)
    _ensure_pipeline_node_interfaces(store, registry, root)
    return root


def test_f9_old_logic_cards_get_their_sockets_in_one_migration_commit(graph):
    from nodelang import commit_intent
    from nodelang.universal_pipeline import ensure_logic_card_sockets
    store, registry = graph
    gate = _old_shape_logic_card(store, registry, "library.if")
    merge = _old_shape_logic_card(store, registry, "library.merge", x=400.0)
    plain = _old_shape_logic_card(store, registry, "library.sort_by", x=800.0)
    before = project_universal_canvas(store, registry)
    assert _port(before, gate, "source", "false") is None
    revision = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="first boot"):
        assert ensure_logic_card_sockets(store, registry) == 3
    # One commit for the sockets, one for the view's interface index.
    assert store.revision - revision <= 2, store.revision - revision
    migrated = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="second boot"):
        assert ensure_logic_card_sockets(store, registry) == 0
    assert store.revision == migrated, "the second boot commits nothing"
    after = project_universal_canvas(store, registry)
    for root, side, name in ((gate, "source", "false"), (gate, "target", "condition"), (merge, "target", "b")):
        port = _port(after, root, side, name)
        assert port is not None and port["connectable"] is True, (side, name)
    assert {p["name"] for p in next(n for n in after["nodes"] if n["id"] == plain)["ports"]
            if p.get("owner") == plain} >= {"out", "in"}


def test_f9_the_boot_migrates_old_logic_cards_once(harness):
    from nodelang import commit_intent
    server = harness.start()
    store, registry = server.universal_store, server.universal_registry
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="old-shape fixture"):
        gate = _old_shape_logic_card(store, registry, "library.if")
    harness.stop()
    server = harness.start()
    assert _port(project_universal_canvas(server.universal_store, server.universal_registry),
                 gate, "source", "false") is not None
    migrated = server.universal_store.revision
    harness.stop()
    server = harness.start()
    assert server.universal_store.revision == migrated, "the second boot adds nothing"


def test_scope_a_clean_run_never_spawns_a_terminal():
    """The clean runner carries the pipeline table, whose terminal engine is
    the unbound one: baboom-settings keeps terminals owner-only, and only the
    application run-graph binds the admitted terminal engine."""
    from types import SimpleNamespace
    from nodelang.application_server import _CleanAuthorityHttpServer
    evaluation = _CleanAuthorityHttpServer._clean_evaluate((
        [StemNode("term", "library.terminal", {"cwd": "", "command": "echo hi"})], [], None))
    assert evaluation.pending["term"] == "this shell has no adapter for library.terminal, so it reaches no host"


def test_scope_interaction_execute_uses_the_lock_light_runner():
    """The interaction Execute and run-graph share one runner; neither runs
    effects under the graph lock."""
    source = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    branch = source[source.index('if self.path == "/api/universal/interaction":'):]
    branch = branch[:branch.index("CAPABILITY_INSTANTIATE")]
    assert "owner._clean_run_graph(" in branch
    assert branch.index("if executes:") > branch.index("with owner._mutation_lock:")
    route = source[source.index('if self.path == "/api/universal/run-graph":'):]
    route = route[:route.index("return")]
    assert "owner._clean_run_graph(" in route and "_mutation_lock" not in route

def test_spec45_the_served_library_is_the_graph_relations(harness):
    """SPEC 4.5: the node library served to Studio is read from graph
    relations; removing a card from its section relation removes it from the
    served library, and appending it to another section moves it there."""
    from nodelang import commit_intent
    from nodelang.cell_protocols import prepare_remove_relation_members
    from nodelang.universal_application import prepare_append_relation_members, read_relation
    from nodelang.universal_pipeline import (
        _ENGINE_LIBRARY_ROLES, engine_library_entry_root,
        engine_library_section_root, seed_engine_library,
    )

    def served():
        body = harness.request("/api/universal/node-library")
        return {item["id"]: group["cat"] for group in body["groups"] for item in group["items"]}

    server = harness.start()
    store, registry = server.universal_store, server.universal_registry
    assert served()["l_merge"] == "logic"
    entry = engine_library_entry_root("l_merge")
    logic = engine_library_section_root("logic")
    ai = engine_library_section_root("ai")
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="edit library"):
        snapshot = store.snapshot()
        incidence = next(m.incidence_id for m in read_relation(snapshot, logic, budget=1024)
                         if m.participant_id == entry)
        patch = prepare_remove_relation_members(snapshot, logic, (incidence,), budget=1024)
        store.commit(snapshot.revision, replace=patch.replace)
    assert "l_merge" not in served()
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="edit library"):
        snapshot = store.snapshot()
        patch = prepare_append_relation_members(
            snapshot, ai, ((_ENGINE_LIBRARY_ROLES["entry"], entry),), budget=1024)
        store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    assert served()["l_merge"] == "ai"
    # The seed never re-adds or overwrites what the graph now says.
    revision = store.revision
    with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="second seed"):
        assert seed_engine_library(store, registry) == 0
    assert store.revision == revision

def _clean_ai_run(tmp_path, monkeypatch, *, as_owner):
    """One clean shell with an AI card, Run pressed on the scope Run control."""
    from nodelang import model_router
    from nodelang.base_universal_catalogue import install_base_universal_catalogue
    from nodelang.clean_browser_authority import revise_clean_browser_focus
    from nodelang.unified_authority import instantiate_definition, published_definition_named
    from tests_replica.test_clean_server_visual_projection import (
        _issue_clean_session, _json, _provision_clean_runtime, _start_clean_server,
    )

    calls = []
    monkeypatch.setenv("ARCHHUB_AGENT_MODEL", "openrouter/court/model")
    monkeypatch.setattr(model_router, "route_chat",
                        lambda route, messages, **kw: calls.append(route) or {"text": "court answer"})
    built, provider = _provision_clean_runtime(tmp_path)
    install_base_universal_catalogue(built.location.authority, caller=built.caller)
    server = _start_clean_server(built, provider)
    token, csrf = "v3-token", "v3-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        auth, caller = built.location.authority, built.caller
        door = built.grand_map.root_id
        ai = instantiate_definition(
            auth, published_definition_named(auth, "AI", caller=caller),
            {"action": "think", "prompt": "hello"}, scope_root=door,
            caller=caller, command_id=str(_uuid.uuid4())).root_id
        binding = server._resolve_binding(token)
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[ai], primary_root=ai,
            caller=caller, command_id=str(_uuid.uuid4()))
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert st == 200
        run_binding = next(item for item in canvas["interaction_projection"]["bindings"]
                           if item["control"] == "app:control:canvas:run")
        if not as_owner:
            real = server._resolve_binding

            def as_member(*args, **kwargs):
                held = real(*args, **kwargs)
                return type(held)(held.session_root, "app:identity:member-court",
                                  held.view_root, held.tenant_root, held.assurance_root)
            server._resolve_binding = as_member
        st, ran = _json(server.url, "/api/universal/run-graph",
                        {"interaction": run_binding["interaction"], "control": run_binding["control"],
                         "event": run_binding["event"],
                         "revision": canvas["interaction_projection"]["revision"]},
                        token=token, csrf=csrf)
        return st, ran, ai, calls
    finally:
        server.close()
        built.location.authority.store.close()


def test_v3_a_non_owner_run_never_reaches_the_model(tmp_path, monkeypatch):
    st, ran, ai, calls = _clean_ai_run(tmp_path, monkeypatch, as_owner=False)
    assert st == 200, ran
    assert calls == [], "the provider was called for a non-owner"
    assert ran["pending"][ai] == "ai.master runs only for this application owner"
    assert ran["effect_receipts"] == []


def test_v3_the_owner_run_calls_the_model_once_with_a_receipt(tmp_path, monkeypatch):
    st, ran, ai, calls = _clean_ai_run(tmp_path, monkeypatch, as_owner=True)
    assert st == 200, ran
    assert calls == ["openrouter/court/model"]
    assert ran["display"][ai].startswith("think: openrouter/court/model answered")
    assert len(ran["effect_receipts"]) == 1 and ran["effect_receipts"][0]


def test_v3_a_host_exec_card_refuses_on_the_clean_shell():
    from nodelang.application_server import _CleanAuthorityHttpServer
    nodes = [StemNode("max", "max.exec", {"code": "1+1"}),
             StemNode("pdf", "library.publish_pdf", {"sheets": "A101"}),
             StemNode("sort", "shape.count", {})]
    evaluation = _CleanAuthorityHttpServer._clean_evaluate((nodes, [], None))
    assert evaluation.pending["max"] == "this shell has no adapter for max.exec, so it reaches no host"
    assert evaluation.pending["pdf"] == "this shell has no adapter for library.publish_pdf, so it reaches no host"
    table = _CleanAuthorityHttpServer._clean_engine_table()
    from nodelang.library_engines import LIBRARY_ENGINES
    assert table["library.sort_by"] is LIBRARY_ENGINES["library.sort_by"]


def test_v3_node_create_without_an_item_takes_the_graph_library_defaults(harness):
    from nodelang import commit_intent
    from nodelang.universal_cell import Cell
    from nodelang.universal_pipeline import engine_library_entry_root
    server = harness.start()
    store = server.universal_store
    params_root = engine_library_entry_root("t_sort") + ":params"
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="edit library defaults"):
        snapshot = store.snapshot()
        held = snapshot.cells[params_root]
        store.commit(snapshot.revision, replace=(Cell(
            params_root, held.link0, held.link1, b'{"by": "height", "direction": "desc"}'),))
    created = harness.request("/api/universal/node-create", {
        "title": "sort", "engine": "library.sort_by", "x": 100, "y": 100, "params": {}})
    canvas = harness.request("/api/universal/canvas")
    rows = {row["label"]: row["value"] for row in canvas["properties"] if row["owner"] == created["root"]}
    assert rows.get("by") == "height" and rows.get("direction") == "desc", rows
