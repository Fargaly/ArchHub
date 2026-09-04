from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import authority_wip_classify as awc  # noqa: E402
from production_webshell_preview import (  # noqa: E402
    BRIDGE_SCRIPT_PATH,
    inject_preview_bridge,
    preview_bridge_source,
)


def test_webshell_files_are_legacy_host_not_promotable_authority():
    for path in (
        "app/web_ui/jsx-boot.js",
        "app/web_ui/studio-lm.compiled.js",
        "app/web_ui/studio-lm.jsx",
    ):
        assert awc.classify_path(path) == "legacy_webshell_host_with_cell_bridge"
        report = awc.classify_entries([{"code": " M", "path": path}])
        entry = report["entries"][0]
        assert entry["promotion_allowed"] == "false"
        assert entry["disposition"] == "legacy_host"
        assert "Universal Cell bridge" in entry["required_action"]


def test_preview_bridge_is_the_authority_boundary_for_legacy_webshell():
    html = (
        '<script>window.bridgeJson = async () => null;</script>'
        '<script src="vendor/react.production.min.js"></script>'
    )
    injected = inject_preview_bridge(html)
    bridge = preview_bridge_source()

    assert f'<script src="{BRIDGE_SCRIPT_PATH}"></script>' in injected
    assert "get_grand_map_ui_surface" in bridge
    assert "get_node_grammar" in bridge
    assert "submit_universal_interaction" in bridge
    assert "/__archhub/grand-map-ui-surface" in bridge
    assert "/__archhub/node-grammar" in bridge
    assert "/__archhub/universal-interaction" in bridge


def test_legacy_webshell_source_does_not_claim_cell_native_completion():
    for path in (
        ROOT / "app" / "web_ui" / "jsx-boot.js",
        ROOT / "app" / "web_ui" / "studio-lm.jsx",
    ):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        assert "cell-native product complete" not in text
        assert "universal cell complete" not in text
        assert "final authority" not in text
        assert "source of truth" not in text


def test_pyqt_bridge_labels_old_brain_and_grammar_as_legacy_projection():
    text = (ROOT / "app" / "bridge.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )

    forbidden_false_authority = (
        "ONE source of truth",
        "CANONICAL store",
        "canonical fact count",
        "This is the ONE store",
    )
    for phrase in forbidden_false_authority:
        assert phrase not in text

    assert "Legacy node-grammar projection" in text
    assert "Legacy Brain telemetry bridge" in text
    assert "not Universal Cell product authority" in text


def test_webshell_action_bus_has_universal_interaction_route():
    text = (ROOT / "app" / "web_ui" / "studio-lm.jsx").read_text(
        encoding="utf-8",
        errors="ignore",
    )

    assert "const submitUniversalInteraction = (payload) =>" in text
    assert "bridgeAsync('submit_universal_interaction', JSON.stringify(request))" in text
    assert "archhub-universal-interaction-result" in text
    assert (
        "window.__archhubSubmitUniversalInteraction = submitUniversalInteraction"
        in text
    )
    assert "registerUiHostCapability('universal.interaction.submit'" in text
    assert "universalInteractionPayloadFromAction(detail || {})" in text


def test_webshell_canvas_mutations_route_to_universal_authority():
    text = (ROOT / "app" / "web_ui" / "studio-lm.jsx").read_text(
        encoding="utf-8",
        errors="ignore",
    )

    assert "const submitUniversalCanvasInteraction = (payload) =>" in text
    assert "source: 'legacy_webshell_canvas'" in text
    assert "interaction: 'node_parameter_update'" in text
    assert "interaction: 'wire_layer_parameter_update'" in text
    assert "interaction: 'relation_wire_layer_update'" in text
    assert "interaction: 'workflow_wire_birth'" in text
    assert "interaction: 'workflow_wire_delete'" in text
    assert "interaction: 'canvas_selection_update'" in text
    assert "interaction: 'canvas_viewport_update'" in text
    assert "interaction: 'canvas_node_position_commit'" in text
