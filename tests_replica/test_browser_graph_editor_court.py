"""Real-browser direct-manipulation acceptance for the Universal graph editor."""
import json
import tempfile
from pathlib import Path
import shutil

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.browser_graph_editor_court import (
    BrowserGraphEditorCourt,
    _admitted_editor_screenshot_directory,
)
from nodelang.cell_attestations import CourtEvidenceDenied
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application


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


def test_real_browser_graph_editor_direct_manipulation(monkeypatch):
    _browser_environment(monkeypatch)
    store, registry = build_universal_application(resolve_map_path())
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        court = BrowserGraphEditorCourt()
        court.configure(server.url, server.browser_session_token)
        result = court.run()
        if not result.passed:
            details = dict(result.details)
            pytest.fail(json.dumps({
                "failed": [
                    name for name, passed in result.checks.items()
                    if not passed
                ],
                "initial_selection_exchange": details.get(
                    "initialSelectionExchange"
                ),
                "scope": details.get("scope"),
                "scope_response": details.get("scopeResponse"),
                "scope_error": details.get("scopeNavigationError"),
                "library_search": details.get("librarySearch"),
                "library_search_error": details.get("librarySearchError"),
                "parameter_creation": details.get("parameterCreation"),
                "parameter_creation_error": details.get(
                    "parameterCreationError"
                ),
                "inspector_lens": details.get("inspectorLens"),
                "inspector_lens_error": details.get("inspectorLensError"),
                "inspector_tab": details.get("inspectorTab"),
                "inspector_tab_error": details.get("inspectorTabError"),
                "presentation_color": details.get("presentationColor"),
                "presentation_color_error": details.get(
                    "presentationColorError"
                ),
                "history_keyboard": details.get("historyKeyboard"),
                "history_keyboard_error": details.get(
                    "historyKeyboardError"
                ),
                "interface_creation": details.get("interfaceCreation"),
                "interface_creation_error": details.get(
                    "interfaceCreationError"
                ),
                "input_interface_creation": details.get(
                    "inputInterfaceCreation"
                ),
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
                "modifier_selection": details.get("modifierSelection"),
                "modifier_marquee": details.get("modifierMarquee"),
                "authoring_surfaces": details.get("authoringSurfaces"),
                "grouping": details.get("grouping"),
                "performance_budgets": details.get("performanceBudgets"),
                "receipt_timings": details.get("receiptTimings"),
                "latencies": details.get("universalResponseLatencies"),
                "messages": details.get("messages"),
                "failed_responses": details.get("failedResponses"),
            }, indent=2))
        assert all(result.checks.values())
    finally:
        server.close()
