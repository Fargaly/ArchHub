"""Rendered-DOM court for the universal canvas and Properties lens."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import nodelang.cell_catalog as cell_catalog_module
import nodelang.universal_application as universal_application_module

from nodelang.cell_protocols import prepare_append_relation_members
from nodelang.map_import import resolve_map_path
from nodelang.ui_runtime import CLIENT_SCRIPT, UNIVERSAL_CANVAS_SCRIPT
from nodelang.universal_application import (
    build_universal_application,
    edit_universal_interface_collection,
    instantiate_universal_definition,
    instantiate_universal_primitive,
    instantiate_universal_relation_definition,
    move_universal_root,
    preview_universal_theme,
    preview_universal_presentation_color,
    project_universal_canvas,
    select_universal_root,
    set_universal_inspector_lens,
    set_universal_properties_panel,
    set_universal_selection,
    set_universal_scope,
    redo_universal_change,
    undo_universal_change,
    update_universal_relation_composer,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, InvalidCell
from nodelang.universal_view import project_universal_document


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "universal_interaction_probe.mjs"


def _assert_collision_free_placement(projection, payload):
    components = projection["configuration"]["design_system"]["components"]
    width = float(components["card"]["width"]["value"].removesuffix("px"))
    margin = float(
        components["canvas"]["grid-size"]["value"].removesuffix("px")
    )
    left = float(payload["x"])
    top = float(payload["y"])
    assert left >= margin
    assert top >= margin
    right = left + width
    bottom = top + 112
    for node in projection["nodes"]:
        node_left = float(node["x"])
        node_top = float(node["y"])
        node_right = node_left + width
        node_bottom = node_top + 112
        assert (
            right + margin <= node_left
            or left >= node_right + margin
            or bottom + margin <= node_top
            or top >= node_bottom + margin
        ), "catalogue placement overlaps %s" % node["id"]
    if "viewport" in payload:
        assert set(payload["viewport"]) == {"pan_x", "pan_y", "zoom"}
        assert 0.1 <= float(payload["viewport"]["zoom"]) <= 4.0


def test_selected_or_hovered_nodes_expose_real_source_sockets(
    rendered_application,
):
    page, _projection = rendered_application
    assert (
        '.graph-node[data-selected="True"] '
        '.node-port-exact[data-context="False"]'
    ) in page
    assert (
        '.graph-node:hover .node-port-exact[data-context="False"]'
    ) in page
    assert (
        '.node-port.node-port-exact.wire-target-ready'
        '{opacity:1;pointer-events:auto}'
    ) in page


def test_universal_document_excludes_the_legacy_typed_browser_controller(
    rendered_application,
):
    page, _projection = rendered_application
    assert UNIVERSAL_CANVAS_SCRIPT in page
    assert CLIENT_SCRIPT not in page
    assert "function runBatch(" not in page


def test_every_visible_wire_has_one_graph_identical_wide_hit_target(
    rendered_application,
):
    page, _projection = rendered_application
    result = _probe(rendered_application, "click_payload")
    assert result["renderedWireCount"] == len(rendered_application[1]["wires"])
    assert result["wireHitCount"] == result["renderedWireCount"]
    assert result["wireHitParity"] is True
    assert ".wire-hit{" in page
    assert "stroke-width:14" in page
    assert ".universal-wire{pointer-events:none}" in page
    assert ".universal-wire-preview{" in page
    assert "stroke-opacity:.9;pointer-events:none}" in page


@pytest.fixture(scope="module")
def rendered_application():
    store, registry = build_universal_application(resolve_map_path())
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        project_universal_canvas(store, registry),
    )


@pytest.fixture(scope="module")
def rendered_relation_composer_application():
    store, registry = build_universal_application(resolve_map_path())
    participant_root = "test:relation-composer:terminal-participant"
    store.commit(store.revision, create=(
        Cell(participant_root, NULL_CELL_ID, NULL_CELL_ID, b"Court value"),
    ))
    canvas_patch = prepare_append_relation_members(
        store.snapshot(),
        registry.canvas_root,
        ((registry.roles["member"], participant_root),),
        budget=100_000,
    )
    store.commit(
        store.revision,
        create=canvas_patch.create,
        replace=canvas_patch.replace,
    )
    view = registry.view_sessions[registry.authorization.subject_root]
    administrator = registry.authorization.subject_root
    universal_application_module._issue_resource_audience_bindings(
        store,
        registry.authorization,
        resource_roots=(participant_root,),
        lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["wip"]
        ),
        owner_root=view.subject_root,
        administrator_root=administrator,
    )
    grants = universal_application_module._issue_view_projection_grants(
        store,
        registry.authorization,
        subject_root=view.subject_root,
        visibility_root=view.visibility_root,
        target_roots=(participant_root,),
        administrator_root=administrator,
    )
    snapshot = store.snapshot()
    visibility_patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((registry.roles["visible"], participant_root),),
        budget=100_000,
    )
    session_patch = prepare_append_relation_members(
        snapshot,
        view.root_id,
        ((registry.roles["relation"], root) for root in grants),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*visibility_patch.create, *session_patch.create),
        replace=(*visibility_patch.replace, *session_patch.replace),
    )
    definition = next(
        item for item in project_universal_canvas(store, registry)["catalog"]
        if item["composition_contract"]
    )
    set_universal_selection(store, registry, (), focus_root=definition["id"])
    initial = project_universal_canvas(store, registry)
    responses = []
    while True:
        composer = project_universal_canvas(
            store, registry
        )["selected_definition"]["composer"]
        empty = next((
            (role, entry)
            for role in composer["roles"]
            for entry in role["entries"]
            if not entry["value"]
        ), None)
        if empty is None:
            break
        role, entry = empty
        choice = entry["choices"][0]
        update_universal_relation_composer(
            store,
            registry,
            definition["id"],
            "select",
            role_root=role["role"],
            entry_root=entry["id"],
            participant_root=choice["id"],
        )
        responses.append(project_universal_canvas(store, registry))
    update_universal_relation_composer(
        store,
        registry,
        definition["id"],
        "position",
        x=420,
        y=260,
    )
    responses.append(project_universal_canvas(store, registry))
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        initial,
        responses,
    )


@pytest.fixture(scope="module")
def rendered_history_application():
    store, registry = build_universal_application(resolve_map_path())
    move_universal_root(store, registry, registry.visible_roots[0], 420, 260)
    set_universal_properties_panel(
        store, registry, registry.properties_panel_roots["history"]
    )
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        project_universal_canvas(store, registry),
    )


@pytest.fixture(scope="module")
def rendered_connection_application():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    relation_root = next(
        wire["id"] for wire in projection["wires"] if not wire["nary"]
    )
    select_universal_root(store, registry, relation_root)
    projection = project_universal_canvas(store, registry)
    assert projection["selected_relation"]["id"] == relation_root
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_relation_application():
    store, registry = build_universal_application(resolve_map_path())
    participant_root = "test:rendered-relation:participant"
    store.commit(store.revision, create=(
        Cell(participant_root, NULL_CELL_ID, NULL_CELL_ID, b"1"),
    ))
    canvas_patch = prepare_append_relation_members(
        store.snapshot(),
        registry.canvas_root,
        ((registry.roles["member"], participant_root),),
        budget=100_000,
    )
    store.commit(
        store.revision,
        create=canvas_patch.create,
        replace=canvas_patch.replace,
    )
    view = registry.view_sessions[registry.authorization.subject_root]
    administrator = registry.authorization.subject_root
    universal_application_module._issue_resource_audience_bindings(
        store,
        registry.authorization,
        resource_roots=(participant_root,),
        lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["wip"]
        ),
        owner_root=view.subject_root,
        administrator_root=administrator,
    )
    grants = universal_application_module._issue_view_projection_grants(
        store,
        registry.authorization,
        subject_root=view.subject_root,
        visibility_root=view.visibility_root,
        target_roots=(participant_root,),
        administrator_root=administrator,
    )
    snapshot = store.snapshot()
    visibility_patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((registry.roles["visible"], participant_root),),
        budget=100_000,
    )
    session_patch = prepare_append_relation_members(
        snapshot,
        view.root_id,
        ((registry.roles["relation"], root) for root in grants),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*visibility_patch.create, *session_patch.create),
        replace=(*visibility_patch.replace, *session_patch.replace),
    )
    projection = project_universal_canvas(store, registry)
    definition = next(
        item for item in projection["catalog"]
        if item["name"] == "Model Descriptor"
    )
    contract = definition["composition_contract"]
    bindings = tuple(
        (
            role["role"],
            role["fixed"]["id"] if role["fixed"] else participant_root,
        )
        for role in contract["roles"]
        for _ in range(role["minimum"])
    )
    instantiate_universal_relation_definition(
        store,
        registry,
        definition["id"],
        bindings,
        x=420.0,
        y=260.0,
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["build"]
    )
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["interfaces"],
    )
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        project_universal_canvas(store, registry),
    )


@pytest.fixture(scope="module")
def rendered_floor_application():
    store, registry = build_universal_application(resolve_map_path())
    root, _ = instantiate_universal_primitive(
        store, registry, x=420, y=260, title="Floor-editable Cell"
    )
    set_universal_inspector_lens(
        store,
        registry,
        registry.inspector_lens_roots["floor"],
    )
    projection = project_universal_canvas(store, registry)
    assert projection["primitive"]["visible"] is True
    assert projection["physical"]["identity"] == root
    assert projection["physical"]["editable"] is True
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_property_authoring_application():
    store, registry = build_universal_application(resolve_map_path())
    owner_root, _ = instantiate_universal_primitive(
        store,
        registry,
        x=420,
        y=260,
        title="Editable Cell",
    )
    projection = project_universal_canvas(store, registry)
    assert projection["selected"] == owner_root
    assert projection["authoring"]["add_property"] is True
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_interface_authoring_application():
    store, registry = build_universal_application(resolve_map_path())
    owner_root, _ = instantiate_universal_primitive(
        store,
        registry,
        x=420,
        y=260,
        title="Interface owner",
    )
    set_universal_inspector_lens(
        store,
        registry,
        registry.inspector_lens_roots["build"],
    )
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["interfaces"],
    )
    projection = project_universal_canvas(store, registry)
    assert projection["selected"] == owner_root
    assert projection["authoring"]["add_interface"] is True
    assert projection["authoring"]["interface_presentations"]
    assert projection["authoring"]["interface_contracts"]
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_interface_value_application():
    store, registry = build_universal_application(resolve_map_path())
    definition = next(
        item for item in project_universal_canvas(store, registry)["catalog"]
        if item["name"] == "Permission Request"
    )
    instantiate_universal_definition(
        store, registry, definition["id"], x=420, y=260
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["build"]
    )
    set_universal_properties_panel(
        store, registry, registry.properties_panel_roots["interfaces"]
    )
    projection = project_universal_canvas(store, registry)
    assert any(
        item["editable"] is True and item["mode"] == "connection"
        for item in projection["selected_interfaces"]
    )
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_collection_value_application():
    store, registry = build_universal_application(resolve_map_path())
    definition = next(
        item for item in project_universal_canvas(store, registry)["catalog"]
        if item["name"] == "Ordered List"
    )
    root, _ = instantiate_universal_definition(
        store, registry, definition["id"], x=420, y=260
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["build"]
    )
    set_universal_properties_panel(
        store, registry, registry.properties_panel_roots["interfaces"]
    )
    interface = project_universal_canvas(
        store, registry
    )["selected_interfaces"][0]
    assert interface["mode"] == "collection"
    edit_universal_interface_collection(
        store, registry, root, interface["id"], "append", value="Alpha"
    )
    page = project_universal_document(store, registry, csrf_token="a" * 32)
    projection = project_universal_canvas(store, registry)
    item = projection["selected_interfaces"][0]["items"][0]
    assert isinstance(item["control"], str)
    assert isinstance(item["event_fact_input"], str)
    return page, projection


@pytest.fixture(scope="module")
def rendered_presentation_application():
    store, registry = build_universal_application(resolve_map_path())
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["presentation"],
    )
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        project_universal_canvas(store, registry),
    )


@pytest.fixture(scope="module")
def rendered_presentation_override_application():
    store, registry = build_universal_application(resolve_map_path())
    owner_root = registry.visible_roots[0]
    revision = preview_universal_presentation_color(
        store, registry, owner_root, "#2f80ed"
    )
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["presentation"],
    )
    projection = project_universal_canvas(store, registry)
    color = next(
        row for row in projection["properties"] if row["label"] == "color"
    )
    assert color["presentation_revision"] == revision
    assert color["presentation_reset"] is True
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_theme_application():
    store, registry = build_universal_application(resolve_map_path())
    view = registry.view_sessions[registry.authorization.subject_root]
    select_universal_root(store, registry, view.settings_root)
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["presentation"],
    )
    projection = project_universal_canvas(store, registry)
    assert projection["selected"] == view.settings_root
    assert projection["configuration"]["theme_fields"]
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


@pytest.fixture(scope="module")
def rendered_theme_restore_application():
    store, registry = build_universal_application(resolve_map_path())
    view = registry.view_sessions[registry.authorization.subject_root]
    preview_universal_theme(store, registry, {"accent": "#2f80ed"})
    select_universal_root(store, registry, view.settings_root)
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["presentation"],
    )
    projection = project_universal_canvas(store, registry)
    assert any(
        item["current"] is False and isinstance(item["restore_control"], str)
        for item in projection["configuration"]["history"]
    )
    return (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )


def _probe(
    rendered_application,
    scenario: str,
    viewport: dict | None = None,
    **options,
) -> dict:
    page, projection = rendered_application
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": page,
            "projection": projection,
            "scenario": scenario,
            "viewport": viewport,
            **options,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_click_selects_without_requesting_arrange_authority(rendered_application):
    result = _probe(rendered_application, "click_payload")
    assert result["gesture"] is not None
    assert result["gesture"]["payload"]["roots"] == [result["nodeIds"][0]]
    assert "positions" not in result["gesture"]["payload"]
    assert result["selected"] == [result["nodeIds"][0]]
    assert result["canvasIdentityPreserved"] is True


def test_clicking_a_socket_selects_its_exact_interface_root(rendered_application):
    result = _probe(
        rendered_application,
        "interface_click_payload",
        deltaResponses=True,
    )
    interface_root = result["initialFirstSocketId"]
    assert interface_root
    assert result["gesture"] is not None
    payload = result["gesture"]["payload"]
    assert payload["roots"] == []
    assert payload["focus"] == interface_root
    assert payload["projection_mode"] == "interaction-delta-v1"
    assert type(payload["projection_revision"]) is int
    assert set(payload) == {
        "roots", "focus", "projection_mode", "projection_revision",
    }
    assert result["selectedSocketIds"] == [interface_root]
    assert result["pressedSocketIds"] == [interface_root]
    assert result["socketIdentityPreserved"] is True


def test_delta_consumer_replaces_canonical_authorization_and_catalog(
    rendered_application,
):
    result = _probe(
        rendered_application,
        "delta_authority_catalog_merge",
        deltaResponses=True,
    )
    accepted = result["deltaAuthorityCatalog"]
    assert accepted["assignedCanvasRoots"] == 987
    assert accepted["firstDefinitionLabel"] == "Updated canonical definition"
    assert accepted["revision"] == (
        result["gesture"]["payload"]["projection_revision"] + 1
    )


def test_use_lens_hides_the_physical_cell_from_the_normal_catalogue(
    rendered_application,
):
    _page, projection = rendered_application
    assert projection["primitive"]["visible"] is False
    assert _probe(rendered_application, "click_payload")["primitiveVisible"] == 0


def test_fit_measures_the_projected_graph_instead_of_using_a_magic_zoom(
    rendered_application,
):
    result = _probe(rendered_application, "fit")
    viewport = result["gesture"]["payload"]["viewport"]
    assert 0.25 <= viewport["zoom"] <= 1.25
    assert viewport != {"pan_x": 18, "pan_y": 18, "zoom": 0.82}
    assert result["canvasScroll"] == {"left": 0, "top": 0}


def test_shift_removes_and_ctrl_does_not_remove(rendered_application):
    shifted = _probe(rendered_application, "shift_remove")
    assert shifted["gesture"]["payload"]["roots"] == [shifted["nodeIds"][1]]

    controlled = _probe(rendered_application, "ctrl_retains")
    assert controlled["selected"] == [controlled["nodeIds"][0]]
    assert controlled["gesture"] is None
    assert controlled["gestureRequests"] == []


def test_shift_marquee_removes_and_ctrl_marquee_adds(rendered_application):
    result = _probe(rendered_application, "modifier_marquee")
    assert result["modifierMarquee"]["afterShift"] == []
    assert result["modifierMarquee"]["afterControl"] == [result["nodeIds"][0]]
    assert len(result["gestureRequests"]) == 2


def test_containing_marquee_uses_canvas_screen_coordinates(rendered_application):
    result = _probe(rendered_application, "marquee")
    assert result["gesture"] is not None
    assert result["gesture"]["payload"]["roots"] == [result["nodeIds"][0]]
    assert result["liveMarquee"]["display"] == "block"
    assert result["liveMarquee"]["mode"] == "window"
    assert float(result["liveMarquee"]["left"].removesuffix("px")) == (
        pytest.approx(result["expectedMarquee"]["left"])
    )
    assert float(result["liveMarquee"]["top"].removesuffix("px")) == (
        pytest.approx(result["expectedMarquee"]["top"])
    )
    assert float(result["liveMarquee"]["width"].removesuffix("px")) == (
        pytest.approx(result["expectedMarquee"]["width"])
    )
    assert float(result["liveMarquee"]["height"].removesuffix("px")) == (
        pytest.approx(result["expectedMarquee"]["height"])
    )


def test_marquee_origin_accounts_for_scrollable_canvas_content(
    rendered_application,
):
    result = _probe(rendered_application, "marquee_scroll")
    assert result["gesture"] is not None
    assert result["gesture"]["payload"]["roots"] == [result["nodeIds"][0]]
    assert result["liveMarquee"]["display"] == "block"
    assert result["liveMarquee"]["mode"] == "window"
    assert float(
        result["liveMarquee"]["left"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["left"])
    assert float(
        result["liveMarquee"]["top"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["top"])
    assert float(
        result["liveMarquee"]["width"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["width"])
    assert float(
        result["liveMarquee"]["height"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["height"])


@pytest.mark.parametrize(
    "viewport",
    [
        {"pan_x": 220.0, "pan_y": 160.0, "zoom": 0.25},
        {"pan_x": -20.0, "pan_y": 180.0, "zoom": 0.25},
        {"pan_x": 120.0, "pan_y": 80.0, "zoom": 1.0},
        {"pan_x": 240.0, "pan_y": -10.0, "zoom": 1.0},
        {"pan_x": -80.0, "pan_y": -120.0, "zoom": 2.5},
        {"pan_x": 40.0, "pan_y": -160.0, "zoom": 2.5},
    ],
)
def test_marquee_origin_matches_pointer_across_zoom_and_pan(
    rendered_application,
    viewport,
):
    result = _probe(rendered_application, "marquee_viewport", viewport)
    assert result["gesture"]["payload"]["roots"] == [result["nodeIds"][0]]
    assert result["liveMarquee"]["display"] == "block"
    assert float(
        result["liveMarquee"]["left"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["left"])
    assert float(
        result["liveMarquee"]["top"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["top"])


def test_crossing_marquee_selects_intersections_from_right_to_left(
    rendered_application,
):
    result = _probe(rendered_application, "crossing")
    assert result["gesture"]["payload"]["roots"] == result["nodeIds"][:2]
    assert result["liveMarquee"]["mode"] == "crossing"
    assert float(
        result["liveMarquee"]["left"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["left"])
    assert float(
        result["liveMarquee"]["top"].removesuffix("px")
    ) == pytest.approx(result["expectedMarquee"]["top"])


def test_pointer_cancel_restores_selection_positions_and_owner(rendered_application):
    result = _probe(rendered_application, "cancel")
    assert result["gesture"] is None
    assert result["selected"] == [result["nodeIds"][0]]
    assert all(
        item["left"] == item["initial"]["left"]
        and item["top"] == item["initial"]["top"]
        for item in result["positions"]
    )
    assert result["pointerOwner"] is None


def test_escape_cancels_drag_without_clearing_selection(rendered_application):
    result = _probe(rendered_application, "escape_cancel")
    assert result["gesture"] is None
    assert result["selected"] == [result["nodeIds"][0]]
    assert all(
        item["left"] == item["initial"]["left"]
        and item["top"] == item["initial"]["top"]
        for item in result["positions"]
    )
    assert result["pointerOwner"] is None


def test_space_selects_focused_node_without_arming_a_pointer(rendered_application):
    result = _probe(rendered_application, "keyboard_select")
    assert result["gesture"]["payload"]["roots"] == [result["nodeIds"][0]]
    assert result["selected"] == [result["nodeIds"][0]]
    assert result["pointerOwner"] is None


def test_rejected_selection_restores_previous_projection_and_reports_reason(
    rendered_application,
):
    result = _probe(rendered_application, "rejected_gesture")
    assert result["selected"] == [result["nodeIds"][0]]
    assert result["focused"] == result["nodeIds"][0]
    assert result["statusMessage"] == "Selection denied by authority"
    assert all(
        item["left"] == item["initial"]["left"]
        and item["top"] == item["initial"]["top"]
        for item in result["positions"]
    )


def test_successful_authoritative_projection_clears_an_old_rejection(
    rendered_application,
):
    result = _probe(rendered_application, "rejected_then_success")
    assert result["selected"] == [result["nodeIds"][2]]
    assert result["statusMessage"] == ""
    assert result["statusVisible"] == "False"


def test_rapid_queued_gestures_use_the_latest_visible_revision(
    rendered_application,
):
    initial_revision = rendered_application[1]["revision"]
    result = _probe(
        rendered_application,
        "rapid_queued_gestures",
        deltaResponses=True,
        syntheticCount=3,
    )

    assert [
        item["payload"]["projection_revision"]
        for item in result["gestureRequests"]
    ] == [initial_revision, initial_revision + 1]
    assert result["staleGestureCount"] == 0
    assert result["fixtureSelection"] == [result["nodeIds"][2]]
    assert result["selected"] == [result["nodeIds"][2]], (
        result["gestureRequests"], result["fixtureSelection"], result["errors"]
    )


def test_queued_governed_mutations_use_the_accepted_projection_revision(
    rendered_application,
):
    initial_revision = rendered_application[1]["revision"]
    result = _probe(
        rendered_application,
        "queued_governed_mutations",
        deltaResponses=True,
    )

    assert [
        item["payload"]["projection_revision"]
        for item in result["gestureRequests"]
    ] == [initial_revision, initial_revision + 1]
    assert result["staleGestureCount"] == 0
    assert result["errors"] == []


def test_rapid_selection_reversal_is_not_dropped_as_a_stale_noop(
    rendered_application,
):
    initial_revision = rendered_application[1]["revision"]
    result = _probe(
        rendered_application,
        "rapid_queued_selection_reversal",
        deltaResponses=True,
    )

    assert [
        item["payload"]["projection_revision"]
        for item in result["gestureRequests"]
    ] == [initial_revision, initial_revision + 1]
    assert result["staleGestureCount"] == 0
    assert result["fixtureSelection"] == [result["nodeIds"][0]]
    assert result["selected"] == [result["nodeIds"][0]]
    assert result["errors"] == []


def test_rapid_modifier_selection_uses_the_latest_visible_selection(
    rendered_application,
):
    initial_revision = rendered_application[1]["revision"]
    result = _probe(
        rendered_application,
        "rapid_modifier_selection_queue",
        deltaResponses=True,
    )

    requests = result["gestureRequests"]
    assert [item["payload"]["projection_revision"] for item in requests] == [
        initial_revision,
        initial_revision + 1,
    ]
    assert [item["payload"]["roots"] for item in requests] == [
        result["nodeIds"][:2],
        [result["nodeIds"][1]],
    ]
    assert result["fixtureSelection"] == [result["nodeIds"][1]]
    assert result["selected"] == [result["nodeIds"][1]]
    assert result["staleGestureCount"] == 0
    assert result["errors"] == []


def test_wire_pointer_has_one_preview_and_releases_on_cancel(rendered_application):
    result = _probe(rendered_application, "wire_cancel")
    assert result["wirePreviewCount"] == 1
    assert result["wireTargetReadyCount"] > 0
    assert result["remainingWirePreviews"] == 0
    assert result["remainingWireTargetReadyCount"] == 0
    assert result["pointerOwner"] is None


def test_graph_defined_properties_panels_are_functional_tabs(
    rendered_application,
):
    result = _probe(rendered_application, "tabs")
    controls = {
        item["key"]: item
        for item in rendered_application[1]["inspector"][
            "controls_descriptor"
        ]
    }
    assert result["inspectorLensLabel"] == controls[
        "inspector:lenses"
    ]["attributes"]["aria-label"]
    assert result["propertiesTablistLabel"] == controls[
        "inspector:tabs"
    ]["attributes"]["aria-label"]
    assert result["panelRequest"] is None
    assert result["interactionRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": "court:interaction:1",
                "control": result["tabs"][1]["panel"],
                "event": "court:event:activate",
                "revision": rendered_application[1]["revision"],
                "projection_mode": "interaction-delta-v1",
        },
    }
    assert result["lensRequest"] is None
    assert result["tabs"]
    assert len(result["panels"]) == len(result["tabs"])
    assert all(tab["id"] and tab["controls"] for tab in result["tabs"])
    assert all(panel["id"] and panel["labelledBy"] for panel in result["panels"])
    assert [tab["tabIndex"] for tab in result["tabs"]].count(0) == 1
    assert result["activeElement"] == result["tabs"][1]["panel"]


def test_active_history_tab_renders_plain_graph_transaction_rows(
    rendered_history_application,
):
    result = _probe(rendered_history_application, "history_panel")
    assert result["sessionActionHeadings"] == ["SESSION ACTIONS / 1"]
    assert result["sessionActionLabels"] == ["APPLIED / Move"]
    assert result["sessionActionValues"] == ["2 changes"]
    assert result["visibleLegacyHistoryControlCount"] == 0
    assert result["errors"] == []


def test_expired_properties_capability_refreshes_once_before_retry(
    rendered_application,
):
    result = _probe(rendered_application, "tabs_expired_lease")
    assert result["interactionRequestCount"] == 2
    assert result["refreshCanvasRequestCount"] == 1
    assert result["tabs"][1]["selected"] == "true"
    assert result["panels"][1]["hidden"] is False
    assert result["errors"] == []


def test_graph_held_build_lens_reprojects_canvas_authoring_interfaces(
    rendered_application,
):
    result = _probe(rendered_application, "build_lens")
    build_root = next(
        lens["id"] for lens in rendered_application[1]["inspector"]["lenses"]
        if lens["name"] == "build"
    )
    assert result["lensRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": "court:interaction:lens:build",
            "control": build_root,
            "event": "court:event:activate",
            "revision": rendered_application[1]["revision"],
            "projection_mode": "interaction-delta-v1",
        },
    }
    assert result["directLensRequestCount"] == 0
    assert result["activeInspectorLens"] == "build"
    assert result["initialExpandedSocketCount"] == 0
    assert result["expandedSocketCount"] > 0
    assert result["exactSocketCount"] < result["initialExactSocketCount"]
    assert result["canvasIdentityPreserved"] is True
    assert result["errors"] == []


def test_rejected_wire_is_explained_in_the_visible_status(rendered_application):
    result = _probe(rendered_application, "wire_rejected")
    request = result["connectRequest"]
    assert request is not None
    assert request["route"] == "/api/universal/interaction"
    assert set(request["payload"]) == {
        "interaction", "control", "event", "revision",
        "projection_mode", "event_facts",
    }
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    assert request["payload"]["revision"] == rendered_application[1]["revision"]
    assert request["payload"]["event_facts"][0]["value"] == 0
    assert result["directTopologyRequestCount"] == 0
    assert result["statusMessage"] == "Connection contract rejected this wire"
    assert result["statusVisible"] == "True"
    assert result["errors"] == []


def test_delete_detaches_the_selected_binary_wire_and_reconciles_topology(
    rendered_application,
):
    _page, projection = rendered_application
    selected_wire = next(wire for wire in projection["wires"] if not wire["nary"])
    result = _probe(rendered_application, "wire_delete")
    request = result["disconnectRequest"]
    assert request["route"] == "/api/universal/interaction"
    assert request["payload"] == {
        "interaction": request["payload"]["interaction"],
        "control": selected_wire["disconnect_control"],
        "event": request["payload"]["event"],
        "revision": projection["revision"],
        "projection_mode": "topology-delta-v1",
    }
    assert result["directTopologyRequestCount"] == 0
    assert result["renderedWireCount"] == len(projection["wires"]) - 1
    assert result["remainingWirePreviews"] == 0
    assert result["pointerOwner"] is None
    assert result["errors"] == []


def test_selected_wire_endpoints_drag_to_exact_compatible_canvas_ports(
    rendered_connection_application,
):
    page, projection = rendered_connection_application
    relation = projection["selected_relation"]
    wire = next(item for item in projection["wires"] if item["id"] == relation["id"])
    result = _probe(rendered_connection_application, "wire_endpoint_rewire")
    request = result["rewireRequest"]
    assert request is not None, result
    assert request["route"] == "/api/universal/interaction"
    assert request["payload"]["control"] == wire["target_rewire_control"]
    assert set(request["payload"]) == {
        "interaction", "control", "event", "revision",
        "projection_mode", "event_facts",
    }
    candidate_index = request["payload"]["event_facts"][0]["value"]
    chosen_target = wire["target_rewire_choices"][candidate_index]
    assert chosen_target["id"] != (
        relation["target"]["participant_interface"]
    )
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    assert request["payload"]["revision"] == projection["revision"]
    assert result["directTopologyRequestCount"] == 0
    reconnectable = [
        item for item in projection["wires"]
        if not item["nary"]
        and item["source_incidence"] and item["target_incidence"]
    ]
    assert result["wireEndpointCount"] == len(reconnectable) * 2
    assert result["focusedWireEndpointCount"] == 2
    handles = {
        handle["side"]: handle for handle in result["focusedWireEndpointData"]
    }
    assert handles["source"] == {
        "relation": relation["id"],
        "segment": wire["segment"],
        "side": "source",
        "incidence": relation["source"]["incidence"],
        "interface": relation["source"]["participant_interface"],
        "node": relation["source"]["participant_owner"],
        "fixedInterface": chosen_target["id"],
        "fixedNode": chosen_target["owner"],
        "inLayer": True,
        "interfaceRendered": True,
    }
    assert handles["target"] == {
        "relation": relation["id"],
        "segment": wire["segment"],
        "side": "target",
        "incidence": relation["target"]["incidence"],
        "interface": chosen_target["id"],
        "node": chosen_target["owner"],
        "fixedInterface": relation["source"]["participant_interface"],
        "fixedNode": relation["source"]["participant_owner"],
        "inLayer": True,
        "interfaceRendered": True,
    }
    assert result["rewireTargetReadyCount"] > 0
    assert result["wirePreviewCount"] == 1
    assert result["remainingRewireTargetReadyCount"] == 0
    assert result["remainingWirePreviews"] == 0
    assert result["pointerOwner"] is None
    assert ".wire-endpoint[data-focused=\"True\"]" in page
    assert ".node-port.wire-reconnect-ready" in page
    assert result["errors"] == []


def test_graph_mutations_are_serialized_before_revision_bound_interactions(
    rendered_application,
):
    result = _probe(rendered_application, "tabs_after_mutation")
    assert result["gesture"] is not None
    assert result["interactionRequest"] is not None
    assert result["interactionRequest"]["payload"]["revision"] == (
        rendered_application[1]["revision"] + 1
    )
    assert result["tabs"][1]["selected"] == "true"
    assert result["panels"][1]["hidden"] is False
    assert result["errors"] == []


def test_generic_browser_interaction_binding_has_no_product_dispatch():
    projector = UNIVERSAL_CANVAS_SCRIPT.split(
        "function projectedInteraction", 1
    )[1].split("function applyViewport", 1)[0]
    for product_term in (
        "properties",
        "panel",
        "group",
        "brain",
        "domain",
        "publish",
        "catalog",
    ):
        assert product_term not in projector.lower()
    assert "'/api/universal/interaction'" in projector
    for retired_topology_route in (
        "'/api/universal/connect'",
        "'/api/universal/disconnect'",
        "'/api/universal/rewire'",
    ):
        assert retired_topology_route not in UNIVERSAL_CANVAS_SCRIPT
    for retired_appearance_route in (
        "'/api/universal/presentation-preview'",
        "'/api/universal/presentation-reset'",
        "'/api/universal/theme-preview'",
        "'/api/universal/theme-restore'",
    ):
        assert retired_appearance_route not in UNIVERSAL_CANVAS_SCRIPT

    delegated_click = UNIVERSAL_CANVAS_SCRIPT.split(
        "document.addEventListener('click'", 1
    )[1].split("const addInterface", 1)[0]
    assert "[data-universal-interaction]" in delegated_click
    assert "executeProjectedInteraction(projected)" in delegated_click


def test_property_response_preserves_the_exact_input_dom_node(
    rendered_application,
):
    assert "'/api/universal/property'" not in UNIVERSAL_CANVAS_SCRIPT
    assert '"/api/universal/property"' not in UNIVERSAL_CANVAS_SCRIPT
    _page, projection = rendered_application
    result = _probe(rendered_application, "property_identity")
    request = result["propertyEditRequest"]
    assert request["route"] == "/api/universal/interaction"
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    assert request["payload"]["projection_mode"] == "interaction-delta-v1"
    edited = next(row for row in projection["properties"] if row["editable"])
    assert request["payload"]["control"] == edited["relation"]
    assert request["payload"]["event_facts"][0]["input"] == (
        edited["event_fact_input"]
    )
    assert "relation" not in request["payload"]
    assert "value" not in request["payload"]
    assert result["propertyInputIdentityPreserved"] is True
    assert result["canvasIdentityPreserved"] is True
    assert result["wireIdentityPreserved"] is True
    assert result["socketIdentityPreserved"] is True
    assert result["libraryIdentityPreserved"] is True
    assert result["toolbarIdentityPreserved"] is True


def test_multi_selection_property_input_uses_one_batch_graph_interaction():
    store, registry = build_universal_application(resolve_map_path())
    first, _ = instantiate_universal_primitive(
        store, registry, x=420, y=180, title="First Cell", atom="first"
    )
    second, _ = instantiate_universal_primitive(
        store, registry, x=760, y=360, title="Second Cell", atom="second"
    )
    set_universal_selection(store, registry, (first, second), focus_root=second)
    projection = project_universal_canvas(store, registry)
    rendered = (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )
    result = _probe(rendered, "property_identity")
    request = result["propertyEditRequest"]
    edited = next(
        row for row in projection["properties"]
        if row.get("control") == request["payload"]["control"]
    )
    assert edited["batch"] is True
    assert edited["mixed"] is True
    assert request["route"] == "/api/universal/interaction"
    assert request["payload"]["control"] == edited["relation"]
    assert request["payload"]["event_facts"] == [{
        "input": edited["event_fact_input"],
        "value": " updated",
    }]
    assert result["propertyInputIdentityPreserved"] is True
    assert result["errors"] == []


def test_interface_value_uses_the_same_graph_interaction_boundary(
    rendered_interface_value_application,
):
    assert "'/api/universal/interface-value'" not in UNIVERSAL_CANVAS_SCRIPT
    assert '"/api/universal/interface-value"' not in UNIVERSAL_CANVAS_SCRIPT
    _page, projection = rendered_interface_value_application
    result = _probe(
        rendered_interface_value_application, "interface_value_identity"
    )
    request = result["interfaceValueRequest"]
    assert request["route"] == "/api/universal/interaction"
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    interface = next(
        item for item in projection["selected_interfaces"]
        if item["editable"] is True and item["mode"] == "connection"
    )
    assert request["payload"]["control"] == interface["control"]
    assert request["payload"]["event_facts"][0]["input"] == (
        interface["event_fact_input"]
    )
    assert "root" not in request["payload"]
    assert "interface" not in request["payload"]
    assert "value" not in request["payload"]


def test_collection_item_value_uses_the_same_graph_interaction_boundary(
    rendered_collection_value_application,
):
    _page, projection = rendered_collection_value_application
    result = _probe(
        rendered_collection_value_application, "collection_item_identity"
    )
    request = result["collectionValueRequest"]
    assert request["route"] == "/api/universal/interaction"
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    item = projection["selected_interfaces"][0]["items"][0]
    assert request["payload"]["control"] == item["control"]
    assert request["payload"]["event_facts"] == [{
        "input": item["event_fact_input"],
        "value": "Alpha updated",
    }]
    assert "root" not in request["payload"]
    assert "interface" not in request["payload"]
    assert "incidence" not in request["payload"]
    assert "action" not in request["payload"]
    assert "value" not in request["payload"]
    assert result["directInterfaceRequestCount"] == 0


def test_collection_structure_controls_send_only_graph_leases_and_event_facts(
    rendered_collection_value_application,
):
    _page, projection = rendered_collection_value_application
    result = _probe(
        rendered_collection_value_application, "collection_actions_identity"
    )
    remove, append = result["relationMemberRequests"]
    collection = projection["selected_interfaces"][0]
    assert remove["payload"]["control"] == collection["items"][0][
        "remove_control"
    ]
    assert "event_facts" not in remove["payload"]
    assert append["payload"]["control"] == collection["append_control"]
    assert append["payload"]["event_facts"] == [{
        "input": collection["append_event_fact_input"],
        "value": "Beta",
    }]
    for request in (remove, append):
        assert request["route"] == "/api/universal/interaction"
        assert not {
            "root", "interface", "incidence", "action", "order", "value"
        }.intersection(request["payload"])
    assert result["directInterfaceRequestCount"] == 0


def test_canvas_keyed_join_enters_and_exits_only_changed_graph_identities(
    rendered_application,
):
    result = _probe(rendered_application, "topology_reconcile")
    assert result["enteredNodeCount"] == 1
    assert result["enteredWireCount"] == 1
    assert result["retainedCardIdentityCount"] == result["renderedNodeCount"] - 1
    assert result["retainedWireIdentityCount"] == result["renderedWireCount"] - 1
    assert result["socketIdentityPreserved"] is True


def test_topology_delta_adds_only_new_graph_identities_and_keeps_stable_ui(
    rendered_application,
):
    result = _probe(rendered_application, "topology_delta_reconcile")
    assert result["instantiateRequest"]["payload"]["projection_mode"] == (
        "topology-delta-v1"
    )
    assert type(
        result["instantiateRequest"]["payload"]["revision"]
    ) is int
    assert result["enteredNodeCount"] == 1
    assert result["enteredWireCount"] == 1
    assert result["retainedCardIdentityCount"] == result["renderedNodeCount"] - 1
    assert result["retainedWireIdentityCount"] == result["renderedWireCount"] - 1
    assert result["libraryIdentityPreserved"] is True
    assert result["toolbarIdentityPreserved"] is True


def test_canvas_rejects_duplicate_projected_graph_identity_before_mutation(
    rendered_application,
):
    result = _probe(rendered_application, "duplicate_projection")
    assert result["renderedNodeCount"] == result["expectedUniqueNodeCount"]
    assert any(
        "Duplicate or missing projected node identity" in error
        for error in result["errors"]
    )


def test_dense_property_response_retains_250_cards_and_500_cables(
    rendered_application,
):
    result = _probe(
        rendered_application,
        "performance_property_250",
        syntheticCount=250,
        syntheticWireCount=500,
    )
    assert result["renderedNodeCount"] == 250
    assert result["renderedWireCount"] == 500
    assert result["retainedCardIdentityCount"] == 250
    assert result["retainedWireIdentityCount"] == 500
    assert result["propertyInputIdentityPreserved"] is True
    assert result["propertyReconcileMs"] < 1_000


def test_dense_canvas_wheel_zoom_and_space_pan_paint_before_commit(
    rendered_application,
):
    """Keep direct canvas navigation responsive under a dense graph."""
    for scenario, feedback_key, commit_key in (
        ("performance_wheel_250", "wheelFeedbackMs", "wheelCommitMs"),
        ("performance_pan_250", "panFeedbackMs", "panCommitMs"),
    ):
        result = _probe(
            rendered_application,
            scenario,
            syntheticCount=250,
            syntheticWireCount=500,
        )
        assert result["renderedNodeCount"] == 250
        assert result["renderedWireCount"] == 500
        assert result[feedback_key] is not None
        assert result[commit_key] is not None
        assert result[feedback_key] < 1_000
        assert result[commit_key] < 1_000


def test_graph_authored_presentation_color_uses_value_interaction_lease(
    rendered_presentation_application,
):
    _page, projection = rendered_presentation_application
    color = next(
        row for row in projection["properties"] if row["label"] == "color"
    )
    result = _probe(rendered_presentation_application, "presentation_color")
    assert result["presentationColorControlCount"] == 1
    assert result["presentationSourceTexts"] == [
        "PERSONAL-WIP / Personal appearance draft"
    ]
    assert result["canvasIdentityPreserved"] is True
    assert result["wireIdentityPreserved"] is True
    assert result["presentationPreviewRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": (
                "court:interaction:appearance:preview:%s"
                % color["relation"]
            ),
            "control": color["presentation_control"],
            "event": "court:event:change",
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
            "event_facts": [{
                "input": color["presentation_event_fact_input"],
                "value": "#336699",
            }],
        },
    }


def test_graph_authored_presentation_reset_uses_transition_interaction_lease(
    rendered_presentation_override_application,
):
    _page, projection = rendered_presentation_override_application
    color = next(
        row for row in projection["properties"] if row["label"] == "color"
    )
    result = _probe(
        rendered_presentation_override_application, "presentation_reset"
    )
    assert result["presentationResetControlCount"] == 0
    assert result["presentationSourceTexts"] == [
        "INHERITED / Inherited node appearance"
    ]
    assert result["presentationResetRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": (
                "court:interaction:appearance:reset:%s"
                % color["relation"]
            ),
            "control": color["presentation_reset_control"],
            "event": "court:event:activate",
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
        },
    }


def test_graph_authored_theme_preview_uses_value_interaction_lease(
    rendered_theme_application,
):
    _page, projection = rendered_theme_application
    accent = next(
        field for field in projection["configuration"]["theme_fields"]
        if field["key"] == "accent"
    )
    result = _probe(rendered_theme_application, "theme_preview")
    assert result["themePreviewRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": "court:interaction:theme-preview:accent",
            "control": accent["control"],
            "event": "court:event:change",
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
            "event_facts": [{
                "input": accent["event_fact_input"],
                "value": "#336699",
            }],
        },
    }
    assert result["themeAccent"] == "#336699"
    assert result["canvasIdentityPreserved"] is True
    assert result["wireIdentityPreserved"] is True


def test_graph_authored_theme_restore_uses_transition_interaction_lease(
    rendered_theme_restore_application,
):
    _page, projection = rendered_theme_restore_application
    historical = next(
        item for item in projection["configuration"]["history"]
        if item["current"] is False
    )
    result = _probe(rendered_theme_restore_application, "theme_restore")
    assert result["themeRestoreRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": (
                "court:interaction:theme-restore:%s"
                % historical["revision"]
            ),
            "control": historical["restore_control"],
            "event": "court:event:activate",
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
        },
    }
    assert result["canvasIdentityPreserved"] is True
    assert result["wireIdentityPreserved"] is True


def test_graph_authored_add_parameter_uses_the_governed_command_by_keyboard(
    rendered_property_authoring_application,
):
    _page, projection = rendered_property_authoring_application
    result = _probe(rendered_property_authoring_application, "property_create")
    assert result["propertyCreateControlCount"] == 1
    form = projection["authoring"]["property_form"]
    binding = {
        "interaction": "court:interaction:%s" % form["root"],
        "control": form["control"],
        "event": "court:event:submit",
    }
    assert result["propertyCreateRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            **binding,
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
            "event_facts": [
                {"input": form["inputs"]["label"], "value": "Acoustic rating"},
                {"input": form["inputs"]["value"], "value": "Rw 50"},
            ],
        },
    }


def test_graph_authored_add_interface_uses_exact_graph_options_by_keyboard(
    rendered_interface_authoring_application,
):
    _page, projection = rendered_interface_authoring_application
    result = _probe(
        rendered_interface_authoring_application, "interface_create"
    )
    assert result["interfaceCreateControlCount"] == 1
    form = projection["authoring"]["interface_form"]
    assert result["interfaceCreateRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": "court:interaction:%s" % form["root"],
            "control": form["control"],
            "event": "court:event:submit",
            "revision": projection["revision"],
            "projection_mode": "interaction-delta-v1",
            "event_facts": [
                {"input": form["inputs"]["name"], "value": "Acoustic source"},
                {
                    "input": form["inputs"]["presentation"],
                    "value": projection["authoring"]
                    ["interface_presentations"][0]["id"],
                },
                {
                    "input": form["inputs"]["contract"],
                    "value": projection["authoring"]
                    ["interface_contracts"][0]["id"],
                },
            ],
        },
    }


def test_properties_shows_and_opens_the_exact_persistent_focus_reason(
    rendered_application,
):
    result = _probe(rendered_application, "focus_reason")
    assert result["focusSummary"] == "USER / ACTIVE"
    assert result["focusReasonLabels"] == ["Initial application focus"]
    payload = result["gesture"]["payload"]
    assert payload == {
        "roots": [],
        "focus": "app:focus-reason:initial-view",
        "projection_mode": "interaction-delta-v1",
        "projection_revision": rendered_application[1]["revision"],
    }


def test_relation_contract_drives_visible_roles_and_the_create_payload(
    rendered_relation_composer_application,
):
    page, projection, responses = rendered_relation_composer_application
    definition = projection["selected_definition"]
    result = _probe(
        (page, projection),
        "relation_composer",
        relationComposerResponses=responses,
    )
    assert result["contractRoleCount"] == len(
        definition["composition_contract"]["roles"]
    )
    request = result["instantiateRequest"]
    assert request is not None
    assert request["route"] == "/api/universal/interaction"
    assert request["payload"]["control"] \
        == definition["composer"]["create_control"]
    assert not {
        "definition", "action", "role", "entry", "participant", "bindings"
    } & set(request["payload"])
    assert result["relationComposerRequestCount"] == len(responses)
    assert result["directRelationComposerRequestCount"] == 0
    assert result["directRelationCreateRequestCount"] == 0


def test_universal_cell_is_draggable_only_in_the_authorized_floor_catalogue(
    rendered_floor_application,
):
    _page, projection = rendered_floor_application
    result = _probe(rendered_floor_application, "primitive_drag")
    floor_lens = next(
        lens for lens in projection["inspector"]["lenses"]
        if lens["id"] == projection["inspector"]["active"]
    )
    assert projection["primitive"]["kicker"] == floor_lens["label"]
    assert result["primitiveKickerTexts"] == [floor_lens["label"]]
    assert result["primitiveDraggable"] is True
    request = result["instantiateRequest"]
    assert request is not None
    assert request["route"] == "/api/universal/interaction"
    payload = request["payload"]
    assert payload["control"] == projection["primitive"]["id"]
    assert set(payload) == {
        "interaction",
        "control",
        "event",
        "event_facts",
        "revision",
        "projection_mode",
    }
    assert payload["projection_mode"] == "topology-delta-v1"
    assert payload["revision"] == projection["revision"]
    assert "primitive" not in payload
    assert "title" not in payload
    assert "atom" not in payload
    assert result["placementPayload"]["primitive"] is True
    _assert_collision_free_placement(projection, result["placementPayload"])


def test_floor_atom_uses_its_declared_property_interaction(
    rendered_floor_application,
):
    _page, projection = rendered_floor_application
    assert "'/api/universal/cell'" not in UNIVERSAL_CANVAS_SCRIPT
    result = _probe(rendered_floor_application, "floor_atom_identity")
    assert result["directCellRequestCount"] == 0
    request = result["propertyEditRequest"]
    assert request is not None
    assert request["route"].endswith("/interaction")
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    physical = projection["physical"]
    assert request["payload"]["control"] == physical["control"]
    assert request["payload"]["event_facts"][0]["input"] == (
        physical["event_fact_input"]
    )


def test_every_catalogue_assembly_has_an_explicit_place_control(
    rendered_application,
):
    _page, projection = rendered_application
    placeable = next(
        item for item in projection["catalog"]
        if not item["composition_contract"]
    )
    result = _probe(rendered_application, "library_place")
    assert result["definitionCount"] == len(projection["catalog"])
    assert result["definitionPlaceControlCount"] == len(projection["catalog"])
    request = result["instantiateRequest"]
    assert request is not None
    assert request["route"].endswith("/interaction")
    assert request["payload"]["control"] == placeable["id"]
    assert "definition" not in request["payload"]
    assert set(request["payload"]) == {
        "interaction",
        "control",
        "event",
        "event_facts",
        "revision",
        "projection_mode",
    }
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    assert request["payload"]["revision"] == projection["revision"]
    _assert_collision_free_placement(projection, result["placementPayload"])


def test_catalogue_placement_remains_collision_free_with_250_visible_nodes(
    rendered_application,
):
    result = _probe(
        rendered_application,
        "performance_topology_250",
        syntheticCount=250,
        syntheticWireCount=500,
    )
    assert result["placementNonnegative"] is True
    assert result["placementCollisionCount"] == 0
    assert result["renderedNodeCount"] == 251
    assert result["renderedWireCount"] == 501
    assert result["topologyReconcileMs"] < 1_000


def test_visible_icon_controls_project_real_cell_native_lucide_geometry(
    rendered_application,
):
    _page, projection = rendered_application
    result = _probe(rendered_application, "library_sections")
    design_system = projection["configuration"]["design_system"]
    assert design_system["icon_catalog"]["source"]["package"] == "lucide-static"
    assert design_system["icon_catalog"]["source"]["version"] == "1.25.0"
    assert len(design_system["control_catalog"]["controls"]) == 15
    assert result["railGraphIconCount"] == 4
    assert result["libraryPlaceGraphIconCount"] == len(projection["catalog"])
    assert result["toolbarGraphIconCount"] == 3
    assert result["missingGraphIconControls"] == []
    assert result["textGlyphControlCount"] == 0
    assert result["graphIconCount"] == 4 + len(projection["catalog"]) + 3


def test_canvas_toolbar_order_activation_and_keyboard_are_graph_authored(
    rendered_application,
):
    _page, projection = rendered_application
    controls = [
        control for control in projection["configuration"]["design_system"]
        ["control_catalog"]["controls"]
        if control["zone"] == "canvas-toolbar" and control["applicable"]
    ]
    controls.sort(key=lambda control: control["order"])
    result = _probe(rendered_application, "toolbar_keyboard")
    assert result["toolbarControlOwners"] == [
        control["owner"] for control in controls
    ]
    assert result["toolbarControlBindingRoots"] == [
        control["activation"]["binding"] for control in controls
    ]
    assert result["toolbarTabStopCount"] == 1
    assert result["activeToolbarControl"] == controls[1]["owner"]
    assert result["errors"] == []


def test_cell_native_history_controls_drive_keyboard_undo_and_redo():
    store, registry = build_universal_application(resolve_map_path())
    root = registry.visible_roots[0]
    original = project_universal_canvas(store, registry)
    original_node = next(node for node in original["nodes"] if node["id"] == root)
    x = float(original_node["x"]) + 144.0
    y = float(original_node["y"]) + 96.0
    move_universal_root(store, registry, root, x, y)
    moved = project_universal_canvas(store, registry)
    page = project_universal_document(store, registry, csrf_token="a" * 32)
    undo_universal_change(store, registry)
    undone = project_universal_canvas(store, registry)
    redo_universal_change(store, registry)
    redone = project_universal_canvas(store, registry)

    result = _probe(
        (page, moved),
        "history_keyboard",
        historyRoot=root,
        historyProjectionResponses=[undone, redone],
    )
    assert result["historyRequests"] == [
        {
            "route": "/api/universal/interaction",
            "payload": {
                "interaction": "court:interaction:history:undo",
                "control": "app:control:canvas:undo",
                "event": "court:event:activate",
                "revision": moved["revision"],
                "projection_mode": "topology-delta-v1",
            },
        },
        {
            "route": "/api/universal/interaction",
            "payload": {
                "interaction": "court:interaction:history:redo",
                "control": "app:control:canvas:redo",
                "event": "court:event:activate",
                "revision": undone["revision"],
                "projection_mode": "topology-delta-v1",
            },
        },
    ]
    assert result["directControlRequestCount"] == 0
    assert result["historyPositions"] == {
        "before": {"left": f"{x:g}px", "top": f"{y:g}px"},
        "undone": {
            "left": f"{float(original_node['x']):g}px",
            "top": f"{float(original_node['y']):g}px",
        },
        "redone": {"left": f"{x:g}px", "top": f"{y:g}px"},
    }
    assert result["visibleLegacyHistoryControlCount"] == 0
    assert result["errors"] == []


def test_history_compensation_reuses_the_dependency_tracked_catalogue_proof(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    root = registry.visible_roots[0]
    projection = project_universal_canvas(store, registry)
    node = next(item for item in projection["nodes"] if item["id"] == root)
    move_universal_root(
        store,
        registry,
        root,
        float(node["x"]) + 48.0,
        float(node["y"]) + 48.0,
    )

    def unexpected_catalogue_traversal(*_args, **_kwargs):
        raise AssertionError(
            "history compensation repeated the released catalogue traversal"
        )

    monkeypatch.setattr(
        cell_catalog_module,
        "_catalog_digest",
        unexpected_catalogue_traversal,
    )
    undo_universal_change(store, registry)


def test_history_compensation_rejects_a_changed_catalogue_dependency():
    store, registry = build_universal_application(resolve_map_path())
    root = registry.visible_roots[0]
    projection = project_universal_canvas(store, registry)
    node = next(item for item in projection["nodes"] if item["id"] == root)
    move_universal_root(
        store,
        registry,
        root,
        float(node["x"]) + 48.0,
        float(node["y"]) + 48.0,
    )

    snapshot = store.snapshot()
    catalogue = cell_catalog_module.read_catalog(
        snapshot,
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )
    definition = cell_catalog_module.read_definition(
        snapshot,
        registry.assembly_protocol,
        catalogue.definition_roots[0],
    )
    name = snapshot.cells[definition.name_root]
    store.commit(snapshot.revision, replace=(Cell(
        name.id,
        name.link0,
        name.link1,
        name.atom + b" drift",
    ),))

    with pytest.raises(InvalidCell, match="definition has drifted"):
        undo_universal_change(store, registry)


def test_scope_entry_reuses_the_dependency_tracked_catalogue_proof(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    target = next(
        node["id"] for node in projection["nodes"] if node["openable"]
    )

    def unexpected_catalogue_traversal(*_args, **_kwargs):
        raise AssertionError(
            "scope entry repeated the released catalogue traversal"
        )

    monkeypatch.setattr(
        cell_catalog_module,
        "_catalog_digest",
        unexpected_catalogue_traversal,
    )
    set_universal_scope(
        store,
        registry,
        target,
        expected_revision=projection["revision"],
        projected_canvas=projection,
    )


def test_scope_entry_does_not_materialize_the_complete_cell_store(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    target = next(
        node["id"] for node in projection["nodes"] if node["openable"]
    )

    def unexpected_dense_snapshot():
        raise AssertionError(
            "scope entry materialized the complete Cell Store"
        )

    monkeypatch.setattr(store, "dense_snapshot", unexpected_dense_snapshot)
    set_universal_scope(
        store,
        registry,
        target,
        expected_revision=projection["revision"],
        projected_canvas=projection,
    )


def test_scope_entry_rejects_a_changed_catalogue_dependency():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    target = next(
        node["id"] for node in projection["nodes"] if node["openable"]
    )
    snapshot = store.snapshot()
    catalogue = cell_catalog_module.read_catalog(
        snapshot,
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )
    definition = cell_catalog_module.read_definition(
        snapshot,
        registry.assembly_protocol,
        catalogue.definition_roots[0],
    )
    name = snapshot.cells[definition.name_root]
    store.commit(snapshot.revision, replace=(Cell(
        name.id,
        name.link0,
        name.link1,
        name.atom + b" drift",
    ),))

    with pytest.raises(InvalidCell, match="definition has drifted"):
        set_universal_scope(
            store,
            registry,
            target,
            expected_revision=store.revision,
            projected_canvas={**projection, "revision": store.revision},
        )


def test_multi_selection_delta_reprojects_group_control_from_graph_state():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    roots = [node["id"] for node in before["nodes"][:2]]
    set_universal_selection(store, registry, roots, focus_root=roots[-1])
    after = project_universal_canvas(store, registry)
    rendered = (
        project_universal_document(store, registry, csrf_token="a" * 32),
        before,
    )
    result = _probe(
        rendered,
        "toolbar_group_dynamic",
        deltaResponses=True,
        controlStateAfter=after["configuration"]["design_system"]
        ["control_catalog"],
    )
    assert result["selected"] == roots
    assert result["toolbarControlOwners"][-1] == "app:control:canvas:group"
    assert result["toolbarControlBindingRoots"][-1] == (
        "app:control-binding:canvas:group"
    )
    assert result["toolbarTabStopCount"] == 1
    assert result["errors"] == []


def test_group_toolbar_click_uses_only_its_graph_interaction():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    roots = [node["id"] for node in before["nodes"][:2]]
    set_universal_selection(store, registry, roots, focus_root=roots[-1])
    projection = project_universal_canvas(store, registry)
    rendered = (
        project_universal_document(store, registry, csrf_token="a" * 32),
        projection,
    )
    result = _probe(rendered, "group_control")
    assert result["compositionRequest"] == {
        "route": "/api/universal/interaction",
        "payload": {
            "interaction": "court:interaction:composition:group",
            "control": "app:control:canvas:group",
            "event": "court:event:activate",
            "revision": projection["revision"],
            "projection_mode": "topology-delta-v1",
        },
    }
    assert result["directCompositionRequestCount"] == 0
    assert result["directControlRequestCount"] == 0
    assert result["errors"] == []


def test_openable_card_enters_its_graph_scope_and_breadcrumb_returns(
    rendered_application,
):
    _page, projection = rendered_application
    openable = next(node for node in projection["nodes"] if node["openable"])
    result = _probe(rendered_application, "scope_navigation")
    assert len(result["scopeRequests"]) == 2
    assert [
        request["payload"]["control"]
        for request in result["scopeRequests"]
    ] == [openable["id"], projection["scope"]["current"]]
    assert all(
        request["route"] == "/api/universal/interaction"
        and request["payload"]["projection_mode"] == "topology-delta-v1"
        and "target" not in request["payload"]
        for request in result["scopeRequests"]
    )
    assert result["directScopeRequestCount"] == 0
    assert result["scopeHeading"] == projection["scope"]["current_label"]
    assert result["scopeTrail"] == [projection["scope"]["current_label"]]
    assert result["canvasScroll"] == {"left": 0, "top": 0}
    assert result["gestureRequests"] == []


def test_enter_activates_openable_card_and_space_remains_selection(
    rendered_application,
):
    page, projection = rendered_application
    openable = next(node for node in projection["nodes"] if node["openable"])
    entered = _probe(rendered_application, "scope_keyboard")
    assert len(entered["scopeRequests"]) == 1
    assert entered["scopeRequests"][0]["route"] \
        == "/api/universal/interaction"
    assert entered["scopeRequests"][0]["payload"]["control"] == openable["id"]
    assert entered["scopeRequests"][0]["payload"]["projection_mode"] \
        == "topology-delta-v1"
    assert "target" not in entered["scopeRequests"][0]["payload"]
    assert entered["directScopeRequestCount"] == 0
    assert entered["scopeHeading"] == openable["label"]
    assert entered["canvasScroll"] == {"left": 0, "top": 0}
    assert entered["gestureRequests"] == []

    selected = _probe(rendered_application, "keyboard_select")
    assert selected["scopeRequests"] == []
    assert selected["gesture"] is not None
    assert (
        '.graph-node[data-universal-openable="True"] .node-title'
        '{cursor:zoom-in}'
    ) in page


def test_projection_reconciliation_cannot_replay_a_stale_property_change(
    rendered_application,
):
    result = _probe(rendered_application, "scope_reconciliation_change")
    assert result["reconciliationChangeDispatches"] == 1
    assert len(result["scopeRequests"]) == 1
    assert result["errors"] == []


def test_toolbar_renderer_has_no_control_owner_or_legacy_action_dispatch():
    start = UNIVERSAL_CANVAS_SCRIPT.index("function renderToolbar")
    end = UNIVERSAL_CANVAS_SCRIPT.index("function projectedNodeWidth", start)
    renderer = UNIVERSAL_CANVAS_SCRIPT[start:end]
    assert "app:control:canvas" not in renderer
    assert "projectedControlButton" not in renderer
    assert "controlCapabilities" not in renderer
    assert "element('button'" not in renderer
    assert "projection.selection.length >= 2" not in renderer
    assert "focused?.composition" not in renderer
    assert "closest('[data-universal-group]')" not in UNIVERSAL_CANVAS_SCRIPT
    assert "closest('[data-universal-ungroup]')" not in UNIVERSAL_CANVAS_SCRIPT


def test_legacy_canvas_controller_cannot_claim_the_universal_canvas():
    pointerdown = CLIENT_SCRIPT.split(
        "document.addEventListener('pointerdown'", 1
    )[1].split("document.addEventListener('pointermove'", 1)[0]
    wheel = CLIENT_SCRIPT.split(
        "document.addEventListener('wheel'", 1
    )[1].split("document.addEventListener('keydown'", 1)[0]
    keydown = CLIENT_SCRIPT.split(
        "document.addEventListener('keydown'", 1
    )[1].split("document.addEventListener('keyup'", 1)[0]

    assert "closest('.canvas[data-universal=\"true\"]')" in pointerdown
    assert "surface.dataset.universal === 'true'" in wheel
    assert "document.querySelector('.canvas[data-universal=\"true\"]')" \
        in keydown
    assert (
        '.canvas[data-pan-surface="true"]:not([data-universal="true"])'
        in CLIENT_SCRIPT
    )


def test_openable_card_has_one_deliberate_navigation_gesture():
    delegated_click = UNIVERSAL_CANVAS_SCRIPT.split(
        "document.addEventListener('click'", 1
    )[1].split("const addInterface", 1)[0]
    assert (
        "projected?.matches(\n"
        "      '.canvas[data-universal=\"true\"] [data-universal-root]'"
        in delegated_click
    )
    assert UNIVERSAL_CANVAS_SCRIPT.count(
        "document.addEventListener('dblclick'"
    ) == 1
    assert UNIVERSAL_CANVAS_SCRIPT.count("await navigateScope(card)") == 2


def test_semantic_toolbar_activation_has_no_browser_product_dispatch():
    activation = UNIVERSAL_CANVAS_SCRIPT.split(
        "async function activateProjectedControl", 1
    )[1].split("function renderStaticControls", 1)[0]
    for hidden_operation in (
        "scope", "group", "ungroup", "undo", "redo", "composition",
        "/api/universal/group", "/api/universal/ungroup",
    ):
        assert hidden_operation not in activation.lower()
    assert "controlCapabilities.viewport" in activation
    assert "'/api/universal/control'" not in activation
    assert "executeProjectedInteraction(button,topologyDeltaMode)" in activation


def test_library_place_control_presentation_is_not_authored_in_browser_code():
    renderer = UNIVERSAL_CANVAS_SCRIPT.split(
        "function renderLibrary", 1
    )[1].split("function keyed", 1)[0]
    assert "applyControlPresentation" not in renderer
    assert "place.title=" not in renderer
    assert "place.setAttribute('aria-label'" not in renderer
    assert "place.append(graphIcon(placeControl.icon,projection))" in renderer


def test_catalogue_sections_are_visible_graph_authored_groups(
    rendered_application,
):
    _page, projection = rendered_application
    result = _probe(rendered_application, "library_sections")
    assert result["libraryPanelTitles"] == [projection["library"]["title"]]
    assert result["statusStripTexts"] == [
        "UNIVERSAL CELL RUNTIME",
        "CATALOGUE",
        "COMPOSER",
        "ADAPTERS",
        "WIP / SHARED / PUBLISHED",
    ]
    assert result["librarySections"] == [
        {
            "id": section["id"],
            "label": section["label"],
            "definitions": len(section["definitions"]),
        }
        for section in projection["catalog_sections"]
    ]
    assert sum(
        section["definitions"] for section in result["librarySections"]
    ) == len(projection["catalog"])


def test_node_library_search_filters_graph_metadata_and_places_by_keyboard(
    rendered_application,
):
    _page, projection = rendered_application
    watcher = next(
        item for item in projection["catalog"] if item["name"] == "Watcher"
    )
    result = _probe(
        rendered_application,
        "library_search",
        query="agents cognition",
    )
    assert result["librarySearchPresent"] is True
    assert result["librarySearchVisibleNames"] == [
        "Model Descriptor", "Model Binding", "Cognition Request", "Proposal",
    ]
    assert result["librarySearchVisibleSections"] == ["Agents & Cognition"]
    assert result["librarySearchResultCount"] == "4 nodes"
    assert result["librarySearchRequestCount"] == 0

    keyboard = _probe(
        rendered_application,
        "library_search_keyboard",
        query="watcher",
    )
    assert keyboard["librarySearchVisibleNames"] == ["Watcher"]
    assert keyboard["instantiateRequest"] is not None, (
        "active=%r disabled=%r routes=%r errors=%r status=%r" % (
            keyboard["librarySearchActiveName"],
            keyboard["librarySearchActivePlaceDisabled"],
            keyboard["requestRoutes"],
            keyboard["errors"],
            keyboard["statusMessage"],
        )
    )
    assert keyboard["instantiateRequest"]["payload"]["control"] == watcher["id"]
    assert keyboard["errors"] == []


def test_rejected_catalogue_placement_is_explained_in_the_visible_status(
    rendered_application,
):
    result = _probe(rendered_application, "library_place_rejected")
    assert result["instantiateRequest"] is not None
    assert result["statusMessage"] == "Governed placement was rejected"
    assert result["statusVisible"] == "True"
    assert result["errors"] == []


def test_real_nary_relation_incidence_cables_reach_real_role_sockets(
    rendered_relation_application,
):
    _page, projection = rendered_relation_application
    nary_wires = [wire for wire in projection["wires"] if wire["nary"]]
    assert nary_wires
    result = _probe(rendered_relation_application, "nary_wire_select")
    assert result["naryWireCount"] == len(nary_wires)
    assert result["naryWireGeometryCount"] == len(nary_wires)
    assert result["naryRoleSocketCount"] == len({
        wire["target_interface"] for wire in nary_wires
    })
    assert result["participantIncidenceSocketCount"] >= len(nary_wires)
    assert result["naryExactParticipantSocketCount"] == len(nary_wires)
    reconnectable = [
        wire for wire in projection["wires"]
        if not wire["nary"]
        and wire["source_incidence"] and wire["target_incidence"]
    ]
    assert sorted(result["wireEndpointRelations"]) == sorted(
        wire["id"] for wire in reconnectable for _side in range(2)
    )
    build_active = any(
        lens["active"] and lens["name"] == "build"
        for lens in projection["inspector"]["lenses"]
    )
    expanded_port_groups = [
        [
            port for port in node["ports"]
            if port["side"] == side and build_active and (
                port["connectable"]
                or port["mode"] == "connection" and not port.get("read_only")
                or port["mode"] == "relation-role" and port.get("editable")
            )
        ]
        for node in projection["nodes"]
        for side in ("source", "target")
    ]
    if any(len(group) > 1 for group in expanded_port_groups):
        assert result["minimumPortGap"] >= 24
    else:
        assert result["minimumPortGap"] is None
    expected_exact_sockets = sum(
        not build_active or not (
            port["connectable"]
            or port["mode"] == "connection" and not port.get("read_only")
            or port["mode"] == "relation-role" and port.get("editable")
        )
        for node in projection["nodes"]
        for port in node["ports"]
    )
    assert result["exactSocketCount"] == expected_exact_sockets
    assert result["exactSocketIdentityCount"] == expected_exact_sockets
    assert result["exactSocketLabelCount"] == expected_exact_sockets
    assert result["gesture"]["payload"] == {
        "roots": [],
        "focus": nary_wires[0]["id"],
        "projection_mode": "interaction-delta-v1",
        "projection_revision": projection["revision"],
    }


def test_relation_role_control_submits_only_its_graph_lease_and_event_fact(
    rendered_relation_application,
):
    _page, projection = rendered_relation_application
    result = _probe(rendered_relation_application, "relation_role_edit")
    assert "'/api/universal/interface'" not in UNIVERSAL_CANVAS_SCRIPT
    assert result["directInterfaceRequestCount"] == 0
    request = result["relationMemberRequest"]
    assert request is not None
    assert request["route"].endswith("/interaction")
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    interface = next(
        item for item in projection["selected_interfaces"]
        if any(
            member["replace_control"] == request["payload"]["control"]
            for member in item["items"]
        )
    )
    assert interface["mode"] == "relation-role"
    member = next(
        item for item in interface["items"]
        if item["replace_control"] == request["payload"]["control"]
    )
    assert request["payload"]["event_facts"] == [{
        "input": member["replace_event_fact_input"],
        "value": request["payload"]["event_facts"][0]["value"],
    }]
    participant_index = request["payload"]["event_facts"][0]["value"]
    assert type(participant_index) is int
    assert interface["choices"][participant_index]["id"] != member["participant"]


def test_incidence_socket_drag_rewires_the_exact_relation_role(
    rendered_relation_application,
):
    _page, projection = rendered_relation_application
    result = _probe(rendered_relation_application, "relation_role_wire_edit")
    assert result["directInterfaceRequestCount"] == 0
    request = result["relationMemberRequest"]
    assert request is not None
    assert request["route"].endswith("/interaction")
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    interface = next(
        item for item in projection["selected_interfaces"]
        if any(
            member["replace_control"] == request["payload"]["control"]
            for member in item["items"]
        )
    )
    assert interface["mode"] == "relation-role"
    member = next(
        item for item in interface["items"]
        if item["replace_control"] == request["payload"]["control"]
    )
    assert request["payload"]["event_facts"][0]["input"] == (
        member["replace_event_fact_input"]
    )
    participant_index = request["payload"]["event_facts"][0]["value"]
    assert type(participant_index) is int
    participant = interface["choices"][participant_index]["id"]
    assert participant not in {
        item["participant"] for item in interface["items"]
    }
    assert result["relationCandidateCount"] > 0
    assert result["wirePreviewCount"] == 1
    assert result["remainingWirePreviews"] == 0
    assert result["pointerOwner"] is None


def test_role_socket_drag_appends_only_when_cardinality_has_capacity(
    rendered_relation_application,
):
    _page, projection = rendered_relation_application
    result = _probe(rendered_relation_application, "relation_role_wire_append")
    assert result["directInterfaceRequestCount"] == 0
    request = result["relationMemberRequest"]
    assert request is not None
    assert request["route"].endswith("/interaction")
    assert set(request["payload"]) == {
        "interaction", "control", "event", "event_facts", "revision",
        "projection_mode",
    }
    assert request["payload"]["projection_mode"] == "topology-delta-v1"
    interface = next(
        item for item in projection["selected_interfaces"]
        if item.get("append_control") == request["payload"]["control"]
    )
    assert interface["mode"] == "relation-role"
    assert interface["fixed_participant"] is None
    assert interface["maximum"] is None or (
        len(interface["items"]) < interface["maximum"]
    )
    assert request["payload"]["event_facts"][0]["input"] == (
        interface["append_event_fact_input"]
    )
    participant_index = request["payload"]["event_facts"][0]["value"]
    assert type(participant_index) is int
    participant = interface["choices"][participant_index]["id"]
    assert participant not in {
        item["participant"] for item in interface["items"]
    }
    assert result["relationCandidateCount"] > 0
    assert result["wirePreviewCount"] == 1
    assert result["remainingWirePreviews"] == 0
    assert result["pointerOwner"] is None


def test_selected_relation_exposes_real_endpoints_gates_and_presentation():
    store, registry = build_universal_application(resolve_map_path())
    relation_root = registry.relation_roots[0]
    select_universal_root(store, registry, relation_root)
    set_universal_properties_panel(
        store,
        registry,
        registry.properties_panel_roots["relations"],
    )
    projection = project_universal_canvas(store, registry)
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": projection,
            "scenario": "relation_rewire",
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    relation = projection["selected_relation"]
    assert result["inspectorKicker"] == "RELATION NODE"
    initial_endpoints = [
        relation["source"]["participant_interface"],
        relation["target"]["participant_interface"],
    ]
    assert result["initialRelationEndpointValues"] == initial_endpoints
    assert result["relationGateCount"] == len(relation["gates"])
    assert len(projection["properties"]) >= 3
    assert result["relationPropertyCount"] == 0
    assert next(tab for tab in result["tabs"] if tab["panel"] == (
        registry.properties_panel_roots["relations"]
    ))["selected"] == "true"
    request = result["rewireRequest"]
    assert request["route"] == "/api/universal/interaction"
    assert request["payload"]["control"] == (
        next(item for item in projection["wires"] if item["id"] == relation["id"])[
            "source_rewire_control"
        ]
    )
    assert set(request["payload"]) == {
        "interaction", "control", "event", "revision",
        "projection_mode", "event_facts",
    }
    candidate_index = request["payload"]["event_facts"][0]["value"]
    expected_source = relation["source"]["rewire_choices"][candidate_index]["id"]
    assert expected_source != initial_endpoints[0]
    assert result["relationEndpointValues"] == [
        expected_source,
        initial_endpoints[1],
    ]
    assert result["directTopologyRequestCount"] == 0
