from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
BRAIN_SRC = Path(__file__).resolve().parent.parent / "personal-brain-mcp" / "src"
if str(BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(BRAIN_SRC))

import authority_wip_classify as awc  # noqa: E402
from personal_brain import active_work as aw  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


NON_AUTHORITY_WIP_BASELINE = {
    # The two Teams REST connector paths were already public WIP; this court
    # allows only their reclassification out of unclassified_noncoordinated.
    "adapter_payload_candidate": 6,
    "cloud_capability_readiness_evidence": 8,
    "documentation_decision_evidence": 7,
    "governance_brain_authority_layer": 65,
    "legacy_handbuilt_projection_court": 1,
    "legacy_handbuilt_projection_cell_catalog_bridge": 1,
    "legacy_handbuilt_projection_frozen_adapter": 0,
    "legacy_handbuilt_projection_to_consume": 0,
    "legacy_probe_capability_evidence": 0,
    "live_locked_legacy_typed_runtime_copy": 1,
    "runtime_retirement_gate_hook": 3,
    "legacy_webshell_host_court": 23,
    "legacy_webshell_host_with_cell_bridge": 7,
    "legacy_typed_grammar_frozen_adapter": 1,
    "legacy_typed_registry_frozen_adapter": 1,
    "legacy_typed_ui_node_frozen_adapter": 1,
    "legacy_custom_node_runtime_bridge": 1,
    "legacy_core_node_runtime_bridge": 1,
    "legacy_self_extension_runtime_bridge": 1,
    "legacy_workflow_composition_frozen_adapter": 1,
    "legacy_workflow_runtime_frozen_adapter": 1,
    "legacy_workflow_runtime_court": 19,
    "legacy_workflow_runtime_to_consume": 0,
    "legacy_workflow_schema_frozen_adapter": 2,
    "ui_runtime_evidence_probe": 5,
    "universal_cell_authority_court": 2,
    "universal_cell_bridge_court": 5,
    "universal_cell_bridge": 2,
    "universal_cell_projection_bridge": 2,
    "universal_cell_runtime_adapter": 2,
    "separate_cell_authority_to_consume": 0,
}

RECLASSIFIED_CONNECTOR_CAPABILITY_PATHS = {
    "app/connectors/teams_connector.py",
    "tests/test_rest_connectors.py",
}


def test_parse_porcelain_handles_modified_untracked_and_renames():
    entries = awc.parse_porcelain(
        " M app/bridge.py\n"
        "?? app/workflows/universal_grand_map_surface.py\n"
        "R  old.py -> tools/brainwrap.py\n"
    )

    assert entries == [
        {"code": " M", "path": "app/bridge.py"},
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
        {"code": "R ", "path": "tools/brainwrap.py"},
    ]


def test_classification_keeps_universal_cell_separate_from_legacy():
    assert (
        awc.classify_path("app/workflows/universal_grand_map_surface.py")
        == "universal_cell_projection_bridge"
    )
    assert awc.classify_path("app/bridge.py") == "legacy_webshell_host_with_cell_bridge"
    assert awc.classify_path("app/workflows/baboom_cell_surface.py") == "universal_cell_projection_bridge"
    assert awc.classify_path("tests/test_baboom_cell_surface_bridge.py") == "universal_cell_bridge_court"
    assert (
        awc.classify_path("personal-brain-mcp/node_courts/court_workshop_atom_is_leaf.py")
        == "universal_cell_authority_court"
    )
    assert (
        awc.classify_path("personal-brain-mcp/src/personal_brain/cell_room.py")
        == "universal_cell_runtime_adapter"
    )
    assert (
        awc.classify_path("personal-brain-mcp/src/personal_brain/cell_room_wiring.py")
        == "universal_cell_runtime_adapter"
    )
    assert (
        awc.classify_path("personal-brain-mcp/src/personal_brain/universal_runtime.py")
        == "universal_cell_bridge"
    )
    assert (
        awc.classify_path("personal-brain-mcp/src/personal_brain/active_work_cell_migration.py")
        == "universal_cell_bridge"
    )
    assert (
        awc.classify_path("personal-brain-mcp/tests/test_universal_runtime_bridge.py")
        == "universal_cell_bridge_court"
    )
    assert (
        awc.classify_path("personal-brain-mcp/tests/test_active_work_cell_migration.py")
        == "universal_cell_bridge_court"
    )
    assert (
        awc.classify_path("personal-brain-mcp/tests/test_brain_control_cell_migration.py")
        == "universal_cell_bridge_court"
    )
    assert (
        awc.classify_path("tools/production_webshell_preview.py")
        == "legacy_webshell_host_with_cell_bridge"
    )
    assert awc.classify_path("tests/test_bridge_wire_validation.py") == "legacy_workflow_runtime_court"
    assert awc.classify_path("app/workflows/graph.py") == "legacy_workflow_schema_frozen_adapter"
    assert awc.classify_path("app/workflows/node_grammar.py") == "legacy_typed_grammar_frozen_adapter"
    assert awc.classify_path("app/workflows/runner.py") == "legacy_workflow_runtime_frozen_adapter"
    assert awc.classify_path("app/workflows/subgraph.py") == "legacy_workflow_composition_frozen_adapter"
    assert awc.classify_path("app/workflows/typesystem.py") == "legacy_workflow_schema_frozen_adapter"
    assert awc.classify_path("app/workflows/custom_nodes.py") == "legacy_custom_node_runtime_bridge"
    assert awc.classify_path("app/workflows/nodes/core.py") == "legacy_core_node_runtime_bridge"
    assert awc.classify_path("app/agents/self_extend.py") == "legacy_self_extension_runtime_bridge"
    assert awc.classify_path("app/workflows/nodes/__init__.py") == "legacy_typed_registry_frozen_adapter"
    assert awc.classify_path("app/workflows/nodes/ui.py") == "legacy_typed_ui_node_frozen_adapter"
    assert (
        awc.classify_path("app/workflows/grand_map_ui.py")
        == "legacy_handbuilt_projection_cell_catalog_bridge"
    )
    assert (
        awc.classify_path("tests/test_grand_map_ui_surface.py")
        == "legacy_handbuilt_projection_court"
    )
    assert (
        awc.classify_path("node_runtime/core.py")
        == "live_locked_legacy_typed_runtime_copy"
    )
    assert awc.classify_path("tools/safety_court_gate.py") == "governance_brain_authority_layer"
    assert awc.classify_path(".githooks/pre-commit") == "runtime_retirement_gate_hook"
    assert awc.classify_path(".githooks/pre-push") == "runtime_retirement_gate_hook"
    assert awc.classify_path("tests/test_runtime_retirement_hook.py") == "runtime_retirement_gate_hook"
    assert awc.classify_path("tests/test_adapter_payload_candidate.py") == "adapter_payload_candidate"
    assert awc.classify_path("app/connectors/teams_connector.py") == "adapter_payload_candidate"
    assert awc.classify_path("tests/test_rest_connectors.py") == "adapter_payload_candidate"
    assert awc.classify_path("tests/test_universal_cell_node_courts.py") == "universal_cell_authority_court"
    assert awc.classify_path("tools/legacy_runtime_drain.py") == "governance_brain_authority_layer"
    assert awc.classify_path("tests/test_legacy_runtime_drain.py") == "governance_brain_authority_layer"
    assert (
        awc.classify_path("tests/test_legacy_webshell_host_boundary.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("docs/_meta/authority_wip_classification.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/live_runtime_holders.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_handoff_board.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_handoff_inspection.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_handoff_disposable_cleanup.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_handoff_shadow_probe.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_source_drift.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/legacy_runtime_source_drift_work_plan.latest.json")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path(
            "docs/_meta/legacy_runtime_universal_holder_verification.latest.json"
        )
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("docs/_meta/run_report_2026-07-19_authority_split.md")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("personal-brain-mcp/src/personal_brain/run_report.py")
        == "governance_run_evidence"
    )
    assert (
        awc.classify_path("personal-brain-mcp/tests/test_run_report.py")
        == "governance_run_evidence"
    )
    assert awc.classify_path("tests/test_port_type_speckle_adapter.py") == "adapter_payload_candidate"
    assert awc.classify_path("cloud_backend/readiness.py") == "cloud_capability_readiness_evidence"
    assert awc.classify_path("cloud_backend/main.py") == "cloud_capability_readiness_evidence"
    assert awc.classify_path("cloud_backend/tests/conftest.py") == "cloud_capability_readiness_evidence"
    assert awc.classify_path("app/workflows/live_nodes.py") == "legacy_probe_capability_evidence"
    assert awc.classify_path("tests/test_live_nodes.py") == "legacy_probe_capability_evidence"
    assert (
        awc.classify_path("cloud_backend/cockpit.py")
        == "separate_cockpit_backend_to_consume_or_archive"
    )
    assert (
        awc.classify_path("app/web_ui/studio-lm.jsx")
        == "legacy_webshell_host_with_cell_bridge"
    )
    assert (
        awc.classify_path("app/web_ui/index.html")
        == "legacy_webshell_host_with_cell_bridge"
    )
    assert (
        awc.classify_path("app/web_ui/tokens.jsx")
        == "legacy_webshell_host_with_cell_bridge"
    )
    assert (
        awc.classify_path("tests/test_design_system_tokens.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_a11y_phase_4_dropdown_nav.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_canvas_ux_fin.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_gpu_resilience.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_host_node_v2_s1.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_jswire_visibility.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_production_webshell_preview.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_reactflow_p2a_groundwork.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_brain_bridge_slots.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_new_bridge_slots.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_canvas_adapter.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_adapter_nodes.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_ai_plan_node.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_code_nodes.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_recook_param.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_typed_ai_nodes.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_self_extend_free_text_live.py")
        == "legacy_workflow_runtime_court"
    )
    assert awc.classify_path("pyproject.toml") == "governance_brain_authority_layer"
    assert awc.classify_path("personal-brain-mcp/src/personal_brain/workers.py") == "governance_brain_authority_layer"
    assert (
        awc.classify_path("tests/test_ui_grammar.py")
        == "legacy_workflow_runtime_court"
    )
    assert (
        awc.classify_path("tests/test_ui_cdp_smoke.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_self_heal_inspector.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_skill_json_split_view.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_skills_search_panels_wiring.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_ui_fake_gate.py")
        == "legacy_webshell_host_court"
    )
    assert (
        awc.classify_path("tests/test_version_footer_real.py")
        == "legacy_webshell_host_court"
    )


def test_classification_summary_is_machine_readable():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/universal_runtime.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room_wiring.py"},
        {"code": "??", "path": "tests/test_universal_grand_map_surface_bridge.py"},
        {"code": "??", "path": "app/workflows/grand_map_ui.py"},
        {"code": "??", "path": "app/workflows/graph.py"},
        {"code": "??", "path": "app/workflows/node_grammar.py"},
        {"code": "??", "path": "app/workflows/runner.py"},
        {"code": "??", "path": "app/workflows/subgraph.py"},
        {"code": "??", "path": "app/workflows/typesystem.py"},
        {"code": "??", "path": "app/workflows/custom_nodes.py"},
        {"code": "??", "path": "app/workflows/nodes/core.py"},
        {"code": "??", "path": "app/agents/self_extend.py"},
        {"code": "??", "path": "app/workflows/nodes/__init__.py"},
        {"code": "??", "path": "app/workflows/nodes/ui.py"},
        {"code": "??", "path": "tests/test_grand_map_ui_surface.py"},
        {"code": "??", "path": "tests/test_authority_wip_classify.py"},
        {"code": " M", "path": "personal-brain-mcp/src/personal_brain/hook_coverage.py"},
        {"code": "??", "path": "cloud_backend/tests/test_readiness.py"},
        {"code": " M", "path": "unknown.txt"},
    ])

    assert report["schema"] == "archhub-public-wip-authority-classification/v1"
    assert report["total"] == 21
    assert report["summary"]["universal_cell_bridge"] == 1
    assert report["summary"]["universal_cell_projection_bridge"] == 1
    assert report["summary"]["universal_cell_runtime_adapter"] == 2
    assert report["summary"]["universal_cell_bridge_court"] == 1
    assert report["summary"]["legacy_handbuilt_projection_cell_catalog_bridge"] == 1
    assert report["summary"]["legacy_handbuilt_projection_court"] == 1
    assert report["summary"]["legacy_typed_grammar_frozen_adapter"] == 1
    assert report["summary"]["legacy_typed_registry_frozen_adapter"] == 1
    assert report["summary"]["legacy_typed_ui_node_frozen_adapter"] == 1
    assert report["summary"]["legacy_custom_node_runtime_bridge"] == 1
    assert report["summary"]["legacy_core_node_runtime_bridge"] == 1
    assert report["summary"]["legacy_self_extension_runtime_bridge"] == 1
    assert report["summary"]["legacy_workflow_composition_frozen_adapter"] == 1
    assert report["summary"]["legacy_workflow_runtime_frozen_adapter"] == 1
    assert report["summary"]["legacy_workflow_schema_frozen_adapter"] == 2
    assert report["summary"]["governance_brain_authority_layer"] == 2
    assert report["summary"]["cloud_capability_readiness_evidence"] == 1
    assert report["summary"]["unclassified_noncoordinated"] == 1
    assert report["gate"]["no_unclassified"]["ok"] is False
    assert report["gate"]["no_unclassified"]["paths"] == ["unknown.txt"]
    assert "categories" in report
    assert report["classification_digest"]
    assert report["active_work_leaves"]


def test_classification_generates_category_active_work_leaves():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
        {"code": "??", "path": "tests/test_universal_grand_map_surface_bridge.py"},
        {"code": "??", "path": "app/bridge.py"},
    ])
    leaves = {
        leaf["governance_context"]["category"]: leaf
        for leaf in report["active_work_leaves"]
    }

    assert sorted(leaves) == [
        "legacy_webshell_host_with_cell_bridge",
        "universal_cell_bridge_court",
        "universal_cell_projection_bridge",
    ]
    bridge = leaves["universal_cell_projection_bridge"]
    assert bridge["title"] == (
        "Consume public WIP category: universal_cell_projection_bridge"
    )
    assert bridge["gate_kind"] == "pytest"
    assert bridge["gate_spec"]["path"] == "tests/test_authority_wip_classify.py"
    assert bridge["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_universal_grand_map_surface_bridge.py",
    ]
    assert bridge["gate_spec"]["required_courts"] == [
        "tests/test_universal_grand_map_surface_bridge.py"
    ]
    assert bridge["cde_container"] == awc.CDE_CONTAINER
    assert bridge["governance_context"]["paths"] == [
        "app/workflows/universal_grand_map_surface.py"
    ]
    assert bridge["governance_context"]["required_courts"] == [
        "tests/test_universal_grand_map_surface_bridge.py"
    ]
    assert bridge["fit"] == [
        "governance", "universal-cell-authority", "wip-convergence",
    ]
    assert bridge["priority"] == awc.CATEGORY_PRIORITY[
        "universal_cell_projection_bridge"
    ]


def test_category_leaf_gate_executes_required_courts_not_only_classifier():
    report = awc.classify_entries([
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/universal_runtime.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"},
    ])
    leaves = {
        leaf["governance_context"]["category"]: leaf
        for leaf in report["active_work_leaves"]
    }
    bridge = leaves["universal_cell_bridge"]

    assert bridge["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "personal-brain-mcp/tests/test_active_work_cell_migration.py",
        "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
        "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
    ]
    assert bridge["gate_spec"]["required_courts"] == [
        "personal-brain-mcp/tests/test_active_work_cell_migration.py",
        "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
        "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
    ]


def test_register_active_work_leaves_writes_grouped_brain_leaves(tmp_path):
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
        {"code": "??", "path": "app/bridge.py"},
    ])
    brain_path = tmp_path / "brain.db"

    registration = awc.register_active_work_leaves(
        report,
        repo=Path(__file__).resolve().parent.parent,
        brain_path=brain_path,
        owner_user="founder",
    )

    store = BrainStore.open(brain_path)
    try:
        ledger = aw.get_ledger(store, owner_user="founder")
    finally:
        store.close()

    assert registration["schema"] \
        == "archhub-public-wip-active-work-registration/v1"
    assert registration["leaf_count"] == 2
    assert sorted(registration["leaf_ids"]) == sorted(
        registration["open_leaf_ids"]
    )
    assert ledger is not None
    titles = sorted(leaf.title for leaf in ledger.leaves.values())
    assert titles == [
        "Consume public WIP category: legacy_webshell_host_with_cell_bridge",
        "Consume public WIP category: universal_cell_projection_bridge",
    ]
    for leaf in ledger.leaves.values():
        assert leaf.gate_kind == "pytest"
        assert leaf.cde_container == awc.CDE_CONTAINER
        assert leaf.governance_context["classification_digest"] \
            == report["classification_digest"]


def test_classification_can_embed_live_runtime_holder_evidence(tmp_path, monkeypatch):
    runtime = tmp_path / "node_runtime"
    runtime.mkdir()
    monkeypatch.setattr(
        awc.live_runtime_holders,
        "audit",
        lambda path: {
            "schema": "archhub-live-runtime-holders/v1",
            "runtime_copy": str(path),
            "exists": True,
            "holder_count": 2,
            "archive_safe_now": False,
            "required_action": "do not archive or move while holders exist",
            "holders": [{"pid": 1}, {"pid": 2}],
        },
    )

    report = awc.classify_entries(
        [{"code": "??", "path": "node_runtime/core.py"}],
        include_runtime_holders=True,
        repo=tmp_path,
    )

    assert report["summary"]["live_locked_legacy_typed_runtime_copy"] == 1
    assert report["live_runtime_holders"]["holder_count"] == 2
    assert report["live_runtime_holders"]["archive_safe_now"] is False


def test_legacy_entries_are_not_promotable_authority():
    report = awc.classify_entries([
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/universal_runtime.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"},
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room_wiring.py"},
        {"code": "??", "path": "tests/test_universal_grand_map_surface_bridge.py"},
        {"code": "??", "path": "app/bridge.py"},
        {"code": "??", "path": "app/web_ui/studio-lm.jsx"},
        {"code": "??", "path": "cloud_backend/cockpit.py"},
    ])

    by_path = {entry["path"]: entry for entry in report["entries"]}
    assert by_path["personal-brain-mcp/src/personal_brain/universal_runtime.py"]["promotion_allowed"] == "false"
    assert by_path["personal-brain-mcp/src/personal_brain/universal_runtime.py"]["disposition"] == "runtime_authority_client"
    assert by_path["personal-brain-mcp/src/personal_brain/universal_runtime.py"]["required_courts"] == [
        "personal-brain-mcp/tests/test_universal_runtime_bridge.py"
    ]
    assert by_path["personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"]["promotion_allowed"] == "false"
    assert by_path["personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"]["disposition"] == "runtime_authority_client"
    assert by_path["personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"]["required_courts"] == [
        "personal-brain-mcp/tests/test_active_work_cell_migration.py",
        "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
    ]
    assert by_path["app/workflows/universal_grand_map_surface.py"]["promotion_allowed"] == "false"
    assert by_path["app/workflows/universal_grand_map_surface.py"]["disposition"] == "runtime_projection_adapter"
    assert by_path["app/workflows/universal_grand_map_surface.py"]["required_courts"] == [
        "tests/test_universal_grand_map_surface_bridge.py"
    ]
    assert by_path["personal-brain-mcp/src/personal_brain/cell_room.py"]["promotion_allowed"] == "false"
    assert by_path["personal-brain-mcp/src/personal_brain/cell_room.py"]["disposition"] == "runtime_client_adapter"
    assert by_path["personal-brain-mcp/src/personal_brain/cell_room_wiring.py"]["promotion_allowed"] == "false"
    assert by_path["personal-brain-mcp/src/personal_brain/cell_room_wiring.py"]["disposition"] == "runtime_client_adapter"
    assert by_path["tests/test_universal_grand_map_surface_bridge.py"]["promotion_allowed"] == "false"
    assert by_path["tests/test_universal_grand_map_surface_bridge.py"]["disposition"] == "active_cell_bridge_court"
    assert by_path["app/bridge.py"]["promotion_allowed"] == "false"
    assert by_path["app/bridge.py"]["disposition"] == "legacy_host"
    assert by_path["app/bridge.py"]["required_courts"] == [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_webshell_host.py",
        "tests/test_legacy_webshell_host_boundary.py",
        "tests/test_production_webshell_preview.py",
    ]
    assert by_path["app/web_ui/studio-lm.jsx"]["promotion_allowed"] == "false"
    assert by_path["app/web_ui/studio-lm.jsx"]["disposition"] == "legacy_host"
    assert by_path["app/web_ui/studio-lm.jsx"]["required_courts"] == [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_webshell_host.py",
        "tests/test_legacy_webshell_host_boundary.py",
        "tests/test_production_webshell_preview.py",
    ]
    assert by_path["cloud_backend/cockpit.py"]["promotion_allowed"] == "false"
    assert "consume" in by_path["cloud_backend/cockpit.py"]["required_action"]
    assert report["gate"]["promotion_candidates"] == {
        "count": 0,
        "items": [],
    }


def test_current_public_wip_has_no_unclassified_entries():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries(awc.current_status(repo))

    assert report["gate"]["no_unclassified"] == {
        "ok": True,
        "count": 0,
        "paths": [],
    }


def test_connector_reclassification_is_exact_not_bucket_growth():
    report = awc.classify_entries([
        {"code": " M", "path": "app/connectors/teams_connector.py"},
        {"code": " M", "path": "tests/test_rest_connectors.py"},
        {"code": " M", "path": "tests/test_adapter_payload_candidate.py"},
        {"code": " M", "path": "tests/test_port_type_speckle_adapter.py"},
        {"code": " M", "path": "payload/rhino/manifest.json"},
        {"code": " M", "path": "payload/rhino/adapter.json"},
    ])
    adapter_paths = {
        entry["path"] for entry in report["entries"]
        if entry["category"] == "adapter_payload_candidate"
    }

    assert RECLASSIFIED_CONNECTOR_CAPABILITY_PATHS.issubset(adapter_paths)
    assert len(adapter_paths - RECLASSIFIED_CONNECTOR_CAPABILITY_PATHS) == 4


def test_non_authority_public_wip_is_shrink_only():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries(awc.current_status(repo))

    violations = {}
    for category, limit in NON_AUTHORITY_WIP_BASELINE.items():
        current = report["summary"].get(category, 0)
        if current > limit:
            violations[category] = {"current": current, "limit": limit}

    assert violations == {}
    assert report["summary"].get("old_studio_ui_surface_migration_evidence", 0) == 0


def test_universal_cell_runtime_clients_do_not_open_side_stores():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries(awc.current_status(repo))
    candidates = [
        entry["path"]
        for entry in report["entries"]
        if entry["category"] == "universal_cell_bridge"
    ]
    if not candidates:
        candidates = [
            "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py",
            "personal-brain-mcp/src/personal_brain/universal_runtime.py",
        ]

    assert candidates
    forbidden = (
        "CellStore",
        "sqlite3",
        "open_baboom_authority",
        "restore_baboom_authority",
        "build_universal_application",
    )
    violations = {}
    for path in candidates:
        source = (repo / path).read_text(encoding="utf-8")
        found = [term for term in forbidden if term in source]
        if found:
            violations[path] = found

    assert violations == {}


def test_no_public_wip_file_is_promotable_authority_by_classification():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries(awc.current_status(repo))
    candidates = sorted(
        entry["path"]
        for entry in report["entries"]
        if entry["promotion_allowed"] == "true"
    )

    assert candidates == []


def test_active_work_migration_uses_runtime_bridge_not_runtime_ownership():
    repo = Path(__file__).resolve().parent.parent
    source = (
        repo
        / "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"
    ).read_text(encoding="utf-8")

    assert "UniversalRuntimeBridge" in source
    assert "runtime.work_list()" in source
    assert "runtime.work_create(" in source
    assert "ApplicationServer" not in source
    assert "CellStore" not in source


def test_brain_control_migration_uses_runtime_bridge_not_runtime_ownership():
    repo = Path(__file__).resolve().parent.parent
    source = (
        repo
        / "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py"
    ).read_text(encoding="utf-8")

    assert "migrate_brain_control_records_to_cells" in source
    assert "UniversalRuntimeBridge" in source
    assert "runtime.work_list()" in source
    assert "runtime.work_create(" in source
    assert "runtime.assembly_create(" in source
    assert "ApplicationServer" not in source
    assert "CellStore" not in source
    assert "sqlite3" not in source


def test_brain_room_adapter_consumes_runtime_not_side_store():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries([
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room.py"},
    ])
    by_path = {entry["path"]: entry for entry in report["entries"]}
    path = "personal-brain-mcp/src/personal_brain/cell_room.py"
    entry = by_path[path]
    source = (repo / path).read_text(encoding="utf-8")
    assert entry["category"] == "universal_cell_runtime_adapter"
    assert entry["disposition"] == "runtime_client_adapter"
    assert entry["promotion_allowed"] == "false"
    assert "UniversalRuntimeBridge" in source
    assert "workshop_say(" in source
    forbidden = (
        "CellStore",
        "sqlite3",
        "bootstrap_deliberation_protocol",
        "compose_deliberation_space",
        "brain:room:",
        "nodelang.cell_deliberation",
    )
    assert [term for term in forbidden if term in source] == []


def test_runtime_adapter_leaf_gate_executes_workshop_wiring_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room.py"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/cell_room_wiring.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] == "universal_cell_runtime_adapter"
    assert leaf["governance_context"]["paths"] == [
        "personal-brain-mcp/src/personal_brain/cell_room.py",
        "personal-brain-mcp/src/personal_brain/cell_room_wiring.py",
    ]
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "personal-brain-mcp/tests/test_active_work_db.py::test_build_server_prefers_runtime_workshop_when_available",
        "personal-brain-mcp/tests/test_active_work_db.py::test_build_server_registers_fail_closed_room_when_runtime_unavailable",
        "personal-brain-mcp/tests/test_server.py::test_context_does_not_fallback_to_legacy_room_when_cell_workshop_unwired",
    ]


def test_legacy_webshell_leaf_gate_executes_boundary_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "app/bridge.py"},
        {"code": " M", "path": "app/web_ui/studio-lm.jsx"},
        {"code": "??", "path": "tools/production_webshell_preview.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "legacy_webshell_host_with_cell_bridge"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_webshell_host.py",
        "tests/test_legacy_webshell_host_boundary.py",
        "tests/test_production_webshell_preview.py",
    ]
    assert leaf["gate_spec"]["required_courts"] == [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_webshell_host.py",
        "tests/test_legacy_webshell_host_boundary.py",
        "tests/test_production_webshell_preview.py",
    ]


def test_legacy_handbuilt_projection_adapter_gate_executes_cell_catalog_court():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/grand_map_ui.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "legacy_handbuilt_projection_cell_catalog_bridge"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_surface_catalog.py",
        "tests/test_grand_map_ui_surface.py",
    ]
    assert leaf["gate_spec"]["required_courts"] == [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_surface_catalog.py",
        "tests/test_grand_map_ui_surface.py",
    ]


def test_legacy_runner_adapter_gate_executes_node_native_court():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/runner.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "legacy_workflow_runtime_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_workflow_runner.py",
    ]
    assert leaf["gate_spec"]["required_courts"] == [
        "tests/test_workflow_runner.py",
    ]


def test_legacy_workflow_schema_adapter_gate_executes_graph_schema_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/graph.py"},
        {"code": "??", "path": "app/workflows/typesystem.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_bridge_wire_validation.py",
        "tests/test_core_nodes.py",
        "tests/test_wire_fields.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_workflow_schema_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_legacy_subgraph_adapter_gate_executes_composition_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/subgraph.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_subgraph.py",
        "tests/test_subgraph_tunable_cell.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_workflow_composition_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_legacy_typed_grammar_adapter_gate_executes_palette_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/node_grammar.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_grammar_config_schema.py",
        "tests/test_node_grammar.py",
        "tests/test_typed_grammar_end_to_end.py",
        "tests/test_ui_grammar.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_typed_grammar_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_legacy_typed_ui_node_adapter_gate_executes_ui_court():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/nodes/ui.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "legacy_typed_ui_node_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_ui_grammar.py",
    ]
    assert leaf["gate_spec"]["required_courts"] == [
        "tests/test_ui_grammar.py",
    ]


def test_legacy_typed_registry_adapter_gate_executes_core_node_court():
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/nodes/__init__.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "legacy_typed_registry_frozen_adapter"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_core_nodes.py",
    ]
    assert leaf["gate_spec"]["required_courts"] == [
        "tests/test_core_nodes.py",
    ]


def test_legacy_custom_node_bridge_gate_executes_cell_permission_court():
    report = awc.classify_entries([
        {"code": " M", "path": "app/workflows/custom_nodes.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_custom_node_bridge.py",
        "tests/test_capability_nodes.py",
        "tests/test_subgraph_config_seed.py::test_config_seed_reaches_impl_kind_graph_node",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_custom_node_runtime_bridge"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_legacy_core_node_bridge_gate_executes_cell_delegation_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "app/workflows/nodes/core.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_connector_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_model_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_core_node_bridge.py",
        "tests/test_core_nodes.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_core_node_runtime_bridge"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_legacy_self_extension_bridge_gate_executes_cell_effect_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "app/agents/self_extend.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_connector_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_self_extension_bridge.py",
        "tests/test_self_extend_loop.py",
        "tests/test_self_extend_ui_widget.py",
        "tests/test_self_extend_free_text_live.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_self_extension_runtime_bridge"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *sorted(expected_courts),
    ]
    assert leaf["gate_spec"]["required_courts"] == sorted(expected_courts)


def test_legacy_workflow_leaf_gate_executes_node_authority_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "app/workflows/future_behavior.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_grammar_config_schema.py",
        "tests/test_node_grammar.py",
        "tests/test_subgraph.py",
        "tests/test_subgraph_tunable_cell.py",
        "tests/test_typed_grammar_end_to_end.py",
        "tests/test_ui_grammar.py",
        "tests/test_wire_fields.py",
        "tests/test_workflow_runner.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "legacy_workflow_runtime_to_consume"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_cloud_readiness_leaf_gate_executes_capability_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "cloud_backend/readiness.py"},
        {"code": " M", "path": "cloud_backend/baboom_relay.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "cloud_backend/tests/test_baboom_relay.py",
        "cloud_backend/tests/test_readiness.py",
    ]
    assert leaf["governance_context"]["category"] \
        == "cloud_capability_readiness_evidence"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_adapter_payload_leaf_gate_executes_permission_and_payload_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "payload/rhino/_ensure_bridge.ps1"},
        {"code": " M", "path": "payload/rhino/_install_task.ps1"},
        {"code": "??", "path": "tests/test_adapter_payload_candidate.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_adapter_nodes.py",
        "tests/test_adapter_payload_candidate.py",
        "tests/test_capability_nodes.py",
        "tests/test_port_type_speckle_adapter.py",
        "tests/test_revit_speckle_ops.py",
        "tests/test_speckle_wire.py",
    ]
    assert leaf["governance_context"]["category"] == "adapter_payload_candidate"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_runtime_retirement_leaf_gate_executes_drain_courts():
    report = awc.classify_entries([
        {"code": " M", "path": ".githooks/pre-commit"},
        {"code": " M", "path": ".githooks/pre-push"},
        {"code": " M", "path": "tests/test_runtime_retirement_hook.py"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_legacy_runtime_drain.py",
        "tests/test_live_runtime_holders.py",
        "tests/test_runtime_retirement_hook.py",
    ]
    assert leaf["governance_context"]["category"] == "runtime_retirement_gate_hook"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_live_locked_runtime_copy_leaf_gate_executes_drain_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "node_runtime/core.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] \
        == "live_locked_legacy_typed_runtime_copy"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_legacy_runtime_drain.py",
        "tests/test_live_runtime_holders.py",
        "tests/test_runtime_retirement_hook.py",
    ]


def test_live_node_runtime_copy_is_ignored_as_source_but_still_auditable():
    repo = Path(__file__).resolve().parent.parent
    ignored = subprocess.run(
        ["git", "check-ignore", "node_runtime/SPEC.md"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert ignored.returncode == 0
    assert ignored.stdout.strip().replace("\\", "/") == "node_runtime/SPEC.md"
    report = awc.classify_entries([
        {"code": "??", "path": "node_runtime/SPEC.md"},
    ])
    assert report["summary"] == {"live_locked_legacy_typed_runtime_copy": 1}
    assert report["active_work_leaves"][0]["gate_spec"]["required_courts"] == [
        "tests/test_legacy_runtime_drain.py",
        "tests/test_live_runtime_holders.py",
        "tests/test_runtime_retirement_hook.py",
    ]


def test_ui_runtime_probe_leaf_gate_executes_static_and_surface_courts():
    report = awc.classify_entries([
        {"code": "??", "path": "tools/verify_ui_child_relation_authority.cjs"},
        {"code": "??", "path": "tools/verify_live_relation_payload_runtime.cjs"},
    ])
    leaf = report["active_work_leaves"][0]

    expected_courts = [
        "tests/test_cdp_gate_enforced.py",
        "tests/test_grand_map_ui_surface.py",
        "tests/test_ui_fake_gate.py",
        "tests/test_ui_fake_gate_selfcheck.py",
    ]
    assert leaf["governance_context"]["category"] == "ui_runtime_evidence_probe"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_documentation_decision_leaf_gate_executes_freshness_and_contract_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "docs/research_digest.md"},
    ])
    leaf = report["active_work_leaves"][0]
    expected_courts = sorted(awc.DOCUMENTATION_DECISION_COURTS)

    assert leaf["governance_context"]["category"] \
        == "documentation_decision_evidence"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_governance_brain_leaf_gate_executes_control_plane_courts():
    report = awc.classify_entries([
        {"code": " M", "path": "personal-brain-mcp/src/personal_brain/hook_coverage.py"},
        {"code": " M", "path": "tools/governed_sessions.py"},
    ])
    leaf = report["active_work_leaves"][0]
    expected_courts = sorted(awc.GOVERNANCE_BRAIN_CONTROL_COURTS)

    assert leaf["governance_context"]["category"] \
        == "governance_brain_authority_layer"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_governance_run_evidence_leaf_gate_executes_run_report_court():
    report = awc.classify_entries([
        {"code": " M", "path": "docs/_meta/run_report_2026-07-19_authority_split.md"},
        {"code": "??", "path": "docs/_meta/live_runtime_holders.latest.json"},
        {"code": "??", "path": "docs/_meta/legacy_runtime_handoff_board.latest.json"},
        {"code": "??", "path": "docs/_meta/legacy_runtime_handoff_inspection.latest.json"},
        {"code": "??", "path": "docs/_meta/legacy_runtime_source_drift.latest.json"},
        {"code": "??", "path": "docs/_meta/legacy_runtime_source_drift_work_plan.latest.json"},
        {"code": "??", "path": "docs/_meta/legacy_runtime_universal_holder_verification.latest.json"},
        {"code": "??", "path": "personal-brain-mcp/src/personal_brain/run_report.py"},
        {"code": "??", "path": "personal-brain-mcp/tests/test_run_report.py"},
    ])
    leaf = report["active_work_leaves"][0]
    expected_courts = sorted(awc.GOVERNANCE_RUN_EVIDENCE_COURTS)

    assert leaf["governance_context"]["category"] == "governance_run_evidence"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_universal_cell_authority_court_leaf_executes_node_court_wrapper():
    report = awc.classify_entries([
        {"code": "??", "path": "personal-brain-mcp/node_courts/run_all.py"},
        {"code": "??", "path": "tests/test_universal_cell_node_courts.py"},
    ])
    leaf = report["active_work_leaves"][0]
    expected_courts = sorted({
        *awc.UNIVERSAL_CELL_AUTHORITY_COURTS,
        "tests/test_universal_cell_node_courts.py",
    })

    assert leaf["governance_context"]["category"] \
        == "universal_cell_authority_court"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        *expected_courts,
    ]
    assert leaf["gate_spec"]["required_courts"] == expected_courts


def test_court_categories_execute_their_own_test_paths():
    report = awc.classify_entries([
        {"code": "??", "path": "tests/test_legacy_webshell_host_boundary.py"},
        {"code": "??", "path": "tests/test_production_webshell_preview.py"},
    ])
    leaf = report["active_work_leaves"][0]

    assert leaf["governance_context"]["category"] == "legacy_webshell_host_court"
    assert leaf["gate_spec"]["selectors"] == [
        "tests/test_authority_wip_classify.py",
        "tests/test_legacy_webshell_host_boundary.py",
        "tests/test_production_webshell_preview.py",
    ]


def test_runtime_projection_adapters_do_not_open_side_stores():
    repo = Path(__file__).resolve().parent.parent
    report = awc.classify_entries([
        {"code": "??", "path": "app/workflows/baboom_cell_surface.py"},
        {"code": "??", "path": "app/workflows/universal_grand_map_surface.py"},
    ])
    adapters = sorted(
        entry["path"]
        for entry in report["entries"]
        if entry["category"] == "universal_cell_projection_bridge"
    )

    assert adapters == [
        "app/workflows/baboom_cell_surface.py",
        "app/workflows/universal_grand_map_surface.py",
    ]
    forbidden = (
        "CellStore",
        "sqlite3",
        "authority.sqlite3",
        "open_baboom_authority",
        "restore_baboom_authority",
        "build_universal_application",
        "project_universal_canvas",
    )
    for path in adapters:
        source = (repo / path).read_text(encoding="utf-8")
        assert [term for term in forbidden if term in source] == []
