"""Real-browser direct-manipulation acceptance for the Universal graph editor."""
import gc
import json
import tempfile
from pathlib import Path
import shutil

import pytest
import nodelang.universal_application as universal_application_module

from nodelang.application_server import ApplicationServer
from nodelang.browser_graph_editor_court import (
    BrowserGraphEditorCourt,
    _admitted_editor_screenshot_directory,
)
from nodelang.cell_attestations import CourtEvidenceDenied
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    restore_universal_application,
    select_universal_root,
)
from nodelang.universal_cell import CellStore


ROOT = Path(__file__).resolve().parents[1]


def test_editor_screenshot_evidence_stays_in_os_temp(tmp_path):
    admitted = tmp_path / "graph-editor-screens"
    assert Path(_admitted_editor_screenshot_directory(str(admitted))) == (
        admitted.resolve()
    )
    with pytest.raises(CourtEvidenceDenied):
        _admitted_editor_screenshot_directory(
            str(ROOT / "test-results" / "graph-editor-screens")
        )
    with pytest.raises(CourtEvidenceDenied):
        _admitted_editor_screenshot_directory(tempfile.gettempdir())
    with pytest.raises(CourtEvidenceDenied):
        _admitted_editor_screenshot_directory(
            str(Path.home() / "archhub-court-screens")
        )


def test_editor_court_emits_exact_authored_roots_for_restart_proof():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    for evidence_binding in (
        "createdRoot: parameterPayload.created_root || \"\"",
        "createdRoot: interfacePayload.created_root || \"\"",
        "createdRoot: inputPayload.created_root || \"\"",
    ):
        assert evidence_binding in script


def test_directional_marquee_starts_and_ends_on_blank_canvas():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    assert "function isMarqueeEndpoint(canvas, x, y)" in script
    assert "top: card.top + card.height * 0.45" in script
    assert "partialWindow: { startX: partialBox.left" in script
    assert "crossing: { startX: partialBox.right" in script


def test_visual_acceptance_measures_layout_tabs_and_pointer_geometry():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    for check in (
        '"visual-layout-contract"',
        '"inspector-tab-semantics"',
        '"selection-box-tracks-pointer"',
    ):
        assert check in script
    assert "minimumPortWidth >= 24" in script
    assert "minimumPortHeight >= 24" in script
    assert "overflowingTitles === 0" in script
    assert "panel.hidden === (tab.getAttribute" in script
    assert "liveSelectionGeometry.maximumEdgeError <= 3" in script
    assert "endpoints.every(([x, y]) => isMarqueeEndpoint(canvas, x, y))" in script
    assert "card.left + card.width * 0.45" not in script


def test_property_edit_uses_one_natural_change_event():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    assert 'await titleInput.fill(editedTitle);' in script
    assert 'await titleInput.press("Tab");' in script
    assert (
        'titleInput.evaluate(input => input.dispatchEvent(new Event("change"'
        not in script
    )


def test_modifier_clicks_target_live_cards_with_explicit_modifiers():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    assert "function canvasCard(page, root)" in script
    assert 'canvasCard(page, second.id).click({ modifiers: ["Control"] })' in script
    assert 'canvasCard(page, first.id).click({ modifiers: ["Shift"] })' in script
    assert 'canvasCard(page, first.id).click({ modifiers: ["Control"] })' in script
    assert 'canvasCard(page, retained.id).click({ modifiers: ["Control"] })' in script


def test_modifier_marquee_compares_canonical_selection_as_a_root_set():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    assert "details.modifierMarquee.afterControl.length === 2" in script
    assert "details.modifierMarquee.afterControl.includes(retained.id)" in script
    assert "details.modifierMarquee.afterControl.includes(marquee.id)" in script
    assert "details.modifierMarquee.afterControl[0] === retained.id" not in script


def test_history_court_requires_redo_only_after_undo_is_accepted():
    script = BrowserGraphEditorCourt().script_path.read_text(encoding="utf-8")
    assert "if (await undoControl.count())" in script
    assert "if (await undoControl.count() && await redoControl.count())" not in script
    assert 'await redoControl.waitFor({ state: "attached", timeout: 15000 });' in script


def _browser_environment(monkeypatch):
    node = shutil.which("node")
    modules = ROOT / "node_modules"
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not node or not modules.joinpath("playwright", "package.json").is_file() \
            or not chrome.exists():
        pytest.skip("local real-browser court runtime is unavailable")
    monkeypatch.setenv("ARCHHUB_NODE_EXECUTABLE", node)
    monkeypatch.setenv("ARCHHUB_NODE_MODULE_PATH", str(modules))
    monkeypatch.setenv("ARCHHUB_CHROME_EXECUTABLE", str(chrome))


def _json_detail(result, name):
    value = result.details[name]
    assert isinstance(value, str)
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def _court_failure_payload(result):
    details = dict(result.details)
    return json.dumps({
        "failed": [
            name for name, passed in result.checks.items() if not passed
        ],
        "modifier_selection": details.get("modifierSelection"),
        "modifier_marquee": details.get("modifierMarquee"),
        "initial_selection_exchange": details.get("initialSelectionExchange"),
        "scope": details.get("scope"),
        "scope_response": details.get("scopeResponse"),
        "scope_error": details.get("scopeNavigationError"),
        "library_search": details.get("librarySearch"),
        "library_search_error": details.get("librarySearchError"),
        "parameter_creation": details.get("parameterCreation"),
        "parameter_creation_error": details.get("parameterCreationError"),
        "inspector_lens": details.get("inspectorLens"),
        "inspector_lens_error": details.get("inspectorLensError"),
        "inspector_tab": details.get("inspectorTab"),
        "inspector_tab_error": details.get("inspectorTabError"),
        "presentation_color": details.get("presentationColor"),
        "presentation_color_error": details.get("presentationColorError"),
        "history_keyboard": details.get("historyKeyboard"),
        "history_keyboard_error": details.get("historyKeyboardError"),
        "history_controls": details.get("historyControls"),
        "interface_creation": details.get("interfaceCreation"),
        "interface_creation_error": details.get("interfaceCreationError"),
        "input_interface_creation": details.get("inputInterfaceCreation"),
        "input_interface_creation_error": details.get(
            "inputInterfaceCreationError"
        ),
        "wire_creation": details.get("wireCreation"),
        "wire_creation_error": details.get("wireCreationError"),
        "wire_after_release": details.get("wireAfterRelease"),
        "wire_target_placement": details.get("wireTargetPlacement"),
        "wire_target_placement_error": details.get(
            "wireTargetPlacementError"
        ),
        "wire_surface": details.get("wireSurface"),
        "wire_pointer": details.get("wirePointer"),
        "wire_candidate_count": details.get("wireCandidateCount"),
        "authoring_surfaces": details.get("authoringSurfaces"),
        "grouping": details.get("grouping"),
        "performance_budgets": details.get("performanceBudgets"),
        "receipt_timings": details.get("receiptTimings"),
        "latencies": details.get("universalResponseLatencies"),
        "messages": details.get("messages"),
        "failed_responses": details.get("failedResponses"),
    }, indent=2)


def test_real_browser_graph_editor_direct_manipulation(monkeypatch, tmp_path):
    _browser_environment(monkeypatch)
    screenshot_directory = tmp_path / "graph-editor-screens"
    monkeypatch.setenv(
        "ARCHHUB_EDITOR_COURT_SCREENSHOT_DIR", str(screenshot_directory)
    )
    state_path = tmp_path / "browser-authoring-restart.sqlite3"
    key_provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    key_provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(),
        CellStore(state_path),
        key_provider=key_provider,
    )
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    result = None
    court_failure = None
    authored_revision = None
    authored_digest = None
    try:
        court = BrowserGraphEditorCourt()
        court.configure(server.url, server.browser_session_token)
        result = court.run()
        if not result.passed:
            court_failure = _court_failure_payload(result)
        authored_revision = store.revision
        authored_digest = store.revision_chain_digest(authored_revision)
    finally:
        server.close(preserve_browser_session=True)

    assert result is not None
    assert authored_revision is not None
    assert authored_digest is not None
    property_edit = _json_detail(result, "propertyEdit")
    grouping = _json_detail(result, "composition")
    scope = _json_detail(result, "scope")
    placement = _json_detail(result, "libraryPlacement")
    parameter = _json_detail(result, "parameterCreation")
    output_interface = _json_detail(result, "interfaceCreation")
    input_interface = _json_detail(result, "inputInterfaceCreation")
    wire = _json_detail(result, "wireCreation")
    screenshots = json.loads(result.details["screenshots"])
    assert [Path(item).name for item in screenshots] == [
        "graph-editor-initial.png",
        "graph-editor-presentation.png",
        "graph-editor-desktop.png",
    ]
    assert all(
        Path(item).is_file()
        and Path(item).resolve().parent == screenshot_directory.resolve()
        for item in screenshots
    )
    del server, store, registry
    gc.collect()

    reopened = CellStore(state_path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=key_provider
    )
    try:
        assert reopened.revision >= authored_revision
        assert reopened.revision_chain_digest(authored_revision) == authored_digest
        snapshot = reopened.snapshot()
        recovered = project_universal_canvas(reopened, restored)

        assert recovered["scope"]["current"] == scope["current"]
        assert universal_application_module._scope_label(
            snapshot, restored, property_edit["root"]
        ) == property_edit["editedTitle"]

        placement_root = placement["createdRoot"]
        parameter_root = parameter["createdRoot"]
        output_root = output_interface["createdRoot"]
        input_root = input_interface["createdRoot"]
        wire_root = wire["createdRoot"]
        for root in (
            placement_root,
            parameter_root,
            output_root,
            input_root,
            wire_root,
        ):
            assert root in snapshot.cells
        assert placement_root in {node["id"] for node in recovered["nodes"]}

        parameter_members = {
            member.role_id: member.participant_id
            for member in read_relation(snapshot, parameter_root, budget=16)
        }
        assert parameter_members[restored.roles["owner"]] == placement_root
        assert reopened.read(
            parameter_members[restored.roles["label"]]
        ).atom.decode("utf-8") == "Acoustic rating"
        assert reopened.read(
            parameter_members[restored.roles["value"]]
        ).atom.decode("utf-8") == "Rw 50"

        output_projection = universal_application_module._project_canvas_interface(
            snapshot, restored.assembly_protocol, output_root
        )
        input_projection = universal_application_module._project_canvas_interface(
            snapshot, restored.assembly_protocol, input_root
        )
        assert output_projection is not None
        assert output_projection["name"] == "Result"
        assert output_projection["side"] == "source"
        assert input_projection is not None
        assert input_projection["name"] == "Input"
        assert input_projection["side"] == "target"

        wire_members = {
            member.role_id: member.participant_id
            for member in read_relation(snapshot, wire_root, budget=16)
        }
        assert wire_members[restored.roles["source"]] == output_root
        assert wire_members[restored.roles["target"]] == input_root
        assert wire_members[restored.roles["scope"]] == scope["current"]

        assert grouping["root"] in snapshot.cells
        assert grouping["root"] not in {
            node["id"] for node in recovered["nodes"]
        }
        select_universal_root(
            reopened,
            restored,
            server.browser_session_root,
        )
        browser_session_projection = project_universal_canvas(
            reopened,
            restored,
        )
        assert browser_session_projection["selected"] == (
            server.browser_session_root
        )
        browser_session = next(
            item
            for item in browser_session_projection["authorization"][
                "browser_sessions"
            ]
            if item["root"] == server.browser_session_root
        )
        assert browser_session["subject"] == registry.authorization.subject_root
        assert browser_session["view"] == registry.authorization.session.root_id
        assert browser_session["tenant"] == registry.authorization.tenant_root
        assert browser_session["assurance"] == (
            registry.authorization.assurance_root
        )
        assert browser_session["state"] == "active"
        history_root = restored.view_sessions[
            restored.authorization.subject_root
        ].composition_history_root
        composition_history = read_relation(snapshot, history_root, budget=100_000)
        operations = {
            snapshot.cells[next(
                member.participant_id
                for member in read_relation(
                    snapshot, entry.participant_id, budget=32
                )
                if member.role_id == restored.roles["why"]
            )].atom.decode("ascii")
            for entry in composition_history
        }
        assert {"group", "ungroup"}.issubset(operations)
        assert recovered["authorization"]["default"] == "deny"
        assert recovered["authorization"]["state"] == "released"
    finally:
        reopened.close()
    if court_failure is not None:
        pytest.fail(court_failure)
    assert all(result.checks.values())
