#!/usr/bin/env python
"""Classify public repo WIP against the active Universal Cell authority.

Read-only convergence aid. It labels changed files so legacy typed-node,
webshell, cloud, and side-store Cell work cannot be promoted as authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import live_runtime_holders


def _policy(
    disposition: str,
    action: str,
    promotable: bool = False,
    required_courts: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "required_action": action,
        "promotion_allowed": promotable,
        "required_courts": list(required_courts),
    }


LEGACY_WORKFLOW_CONSUMPTION_COURTS = (
    "tests/test_workflow_runner.py",
    "tests/test_wire_fields.py",
    "tests/test_subgraph.py",
    "tests/test_subgraph_tunable_cell.py",
    "tests/test_grammar_config_schema.py",
    "tests/test_node_grammar.py",
    "tests/test_typed_grammar_end_to_end.py",
    "tests/test_ui_grammar.py",
)


CLOUD_CAPABILITY_READINESS_COURTS = (
    "cloud_backend/tests/test_readiness.py",
)


BABOOM_RELAY_RETIREMENT_COURTS = (
    "cloud_backend/tests/test_baboom_relay_retirement.py",
)


ADAPTER_PAYLOAD_COURTS = (
    "tests/test_adapter_payload_candidate.py",
    "tests/test_port_type_speckle_adapter.py",
    "tests/test_adapter_nodes.py",
    "tests/test_capability_nodes.py",
    "tests/test_revit_speckle_ops.py",
    "tests/test_speckle_wire.py",
)


RUNTIME_RETIREMENT_COURTS = (
    "tests/test_runtime_retirement_hook.py",
    "tests/test_legacy_runtime_drain.py",
    "tests/test_live_runtime_holders.py",
)


UI_RUNTIME_EVIDENCE_COURTS = (
    "tests/test_cdp_gate_enforced.py",
    "tests/test_ui_fake_gate.py",
    "tests/test_ui_fake_gate_selfcheck.py",
    "tests/test_grand_map_ui_surface.py",
)


DOCUMENTATION_DECISION_COURTS = (
    "tests/test_doc_freshness_coverage.py",
    "tests/test_node_grammar.py",
    "tests/test_grammar_config_schema.py",
    "cloud_backend/tests/test_readiness.py",
)


GOVERNANCE_BRAIN_CONTROL_COURTS = (
    "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_brain_governance.py",
    "personal-brain-mcp/tests/test_hook_coverage.py",
    "personal-brain-mcp/tests/test_active_work_db.py",
    "personal-brain-mcp/tests/test_compliance_report.py",
    "personal-brain-mcp/tests/test_grand_map_sync.py",
    "personal-brain-mcp/tests/test_installer.py",
    "personal-brain-mcp/tests/test_installer_coverage.py",
    "personal-brain-mcp/tests/test_mcp_core_http.py",
    "personal-brain-mcp/tests/test_reflexion.py",
    "personal-brain-mcp/tests/test_roma.py",
    "personal-brain-mcp/tests/test_run_report.py",
    "personal-brain-mcp/tests/test_secret_resolver.py",
    "personal-brain-mcp/tests/test_server.py",
    "personal-brain-mcp/tests/test_server_verify.py",
    "personal-brain-mcp/tests/test_universal_session_manager.py",
    "tests/test_agent_os_broker.py",
    "tests/test_agent_os_gate.py",
    "tests/test_brainwrap.py",
    "tests/test_cockpit_legacy_authority_boundary.py",
    "tests/test_governed_sessions.py",
    "tests/test_legacy_runtime_drain.py",
    "tests/test_live_runtime_holders.py",
)


GOVERNANCE_RUN_EVIDENCE_COURTS = (
    "personal-brain-mcp/tests/test_run_report.py",
)


EXTERNAL_WORKTREE_COURTS = (
    "tests/test_authority_wip_classify.py::test_generated_wip_classification_matches_live_external_worktree_state",
)


UNIVERSAL_CELL_AUTHORITY_COURTS = (
    "tests/test_universal_cell_node_courts.py",
)


CATEGORY_POLICY: dict[str, dict[str, Any]] = {
    "universal_cell_bridge": _policy(
        "runtime_authority_client",
        (
            "keep as a bounded client of the application-owned Universal Cell "
            "runtime; required courts must prove no side store, no local "
            "fallback, and no ownership of product authority"
        ),
    ),
    "universal_cell_projection_bridge": _policy(
        "runtime_projection_adapter",
        "keep as a read-only client of the application-owned Universal runtime; do not promote the adapter as authority",
    ),
    "universal_cell_runtime_adapter": _policy(
        "runtime_client_adapter",
        "keep as a client of the application-owned Universal runtime; do not promote the adapter as authority",
    ),
    "separate_cell_authority_to_consume": _policy(
        "cell_native_but_split_authority",
        "consume into the application-owned Universal Cell runtime or keep as non-authority evidence",
    ),
    "universal_cell_bridge_court": _policy(
        "active_cell_bridge_court",
        "run as evidence that bridge code consumes the Universal Cell authority; do not promote test files as product authority",
    ),
    "universal_cell_authority_court": _policy(
        "active_cell_court",
        "run as evidence for Universal Cell authority; do not treat as product runtime",
        required_courts=UNIVERSAL_CELL_AUTHORITY_COURTS,
    ),
    "governance_brain_authority_layer": _policy(
        "migration_control_layer",
        (
            "keep as enforcement/migration control only when the Brain "
            "governance boundary is graph-contracted, non-promotable, and "
            "admitted by the Universal Cell authority until fully consumed"
        ),
        required_courts=GOVERNANCE_BRAIN_CONTROL_COURTS,
    ),
    "legacy_handbuilt_projection_to_consume": _policy(
        "legacy_reference",
        "consume behavior into Cell projection or retire",
    ),
    "legacy_handbuilt_projection_frozen_adapter": _policy(
        "legacy_frozen_compatibility_adapter",
        (
            "keep only as a frozen, non-authoritative compatibility adapter; "
            "registry growth is blocked and every payload must point to the "
            "Universal Cell authority as superseding source"
        ),
    ),
    "legacy_handbuilt_projection_cell_catalog_bridge": _policy(
        "legacy_frozen_projection_with_cell_catalog",
        (
            "keep only as a frozen, non-authoritative compatibility adapter; "
            "its named surface registry must be mirrored as a digest-checked "
            "Universal Cell catalogue until every surface is consumed by the "
            "single application graph"
        ),
    ),
    "legacy_handbuilt_projection_court": _policy(
        "active_court",
        "prove hand-built projections remain non-authority until Cell-native replacement",
    ),
    "legacy_workflow_runtime_to_consume": _policy(
        "legacy_reference",
        "replace typed workflow behavior with graph protocols or retire",
        required_courts=LEGACY_WORKFLOW_CONSUMPTION_COURTS,
    ),
    "legacy_workflow_runtime_court": _policy(
        "active_court",
        "run as evidence for old typed runtime compatibility and migration boundaries; do not treat tests as product runtime",
    ),
    "legacy_workflow_runtime_frozen_adapter": _policy(
        "legacy_frozen_compatibility_runtime",
        (
            "keep only as a superseded typed-runtime adapter; direct callers "
            "must normalize graph-native wire, wire-layer, and parameter nodes "
            "before execution, and this runtime may not own product authority"
        ),
    ),
    "legacy_workflow_schema_frozen_adapter": _policy(
        "legacy_frozen_compatibility_schema",
        (
            "keep only as superseded typed graph/schema compatibility for saved "
            "Studio graphs and migration courts; custom namespaced protocols "
            "must remain open and this schema may not become product authority"
        ),
    ),
    "legacy_workflow_composition_frozen_adapter": _policy(
        "legacy_frozen_composition_adapter",
        (
            "keep only as superseded typed-runtime group/ungroup compatibility; "
            "compose, expand, facade ports, and exposed knobs must remain "
            "court-proven while Universal Cell owns graph composition authority"
        ),
    ),
    "legacy_typed_grammar_frozen_adapter": _policy(
        "legacy_frozen_palette_grammar_adapter",
        (
            "keep only as a superseded typed Studio palette/grammar adapter; "
            "engine grounding, parameter schemas, and end-to-end runner paths "
            "must stay court-proven while Universal Cell owns the language"
        ),
    ),
    "legacy_typed_ui_node_frozen_adapter": _policy(
        "legacy_frozen_ui_node_adapter",
        (
            "keep only as a superseded typed-runtime UI node shim for saved "
            "graphs and comparison courts; Universal Cell owns UI authority"
        ),
    ),
    "legacy_typed_registry_frozen_adapter": _policy(
        "legacy_frozen_registry_bootstrap",
        (
            "keep only as a superseded typed-runtime registration bootstrap; "
            "it may import compatibility node families but may not define "
            "product authority or widen the primitive catalogue"
        ),
    ),
    "legacy_custom_node_runtime_bridge": _policy(
        "legacy_custom_node_permission_bridge",
        (
            "keep only as a superseded typed custom-node compatibility path; "
            "executable custom specs must be mirrored as exact Universal Cell "
            "adapter capability, permission, and evidence before promotion"
        ),
    ),
    "legacy_core_node_runtime_bridge": _policy(
        "legacy_core_node_permission_bridge",
        (
            "keep only as a superseded typed host/document/conversation "
            "compatibility path; host, document, and model effects must be "
            "mirrored as exact Universal Cell connector/model delegations and "
            "redacted receipts before promotion"
        ),
    ),
    "legacy_self_extension_runtime_bridge": _policy(
        "legacy_self_extension_permission_bridge",
        (
            "keep only as a superseded typed self-extension compatibility path; "
            "build, court, and learn effects must be mirrored as exact "
            "Universal Cell connector delegations and redacted receipts before "
            "promotion"
        ),
    ),
    "old_studio_ui_surface_migration_evidence": _policy(
        "legacy_reference",
        "use only as UI/UX evidence until graph-native courts supersede it",
    ),
    "legacy_webshell_host_with_cell_bridge": _policy(
        "legacy_host",
        "keep only as a host for Universal Cell bridge evidence until replaced",
    ),
    "legacy_webshell_host_court": _policy(
        "active_court",
        "use as regression court for the legacy host boundary until graph-native courts supersede it",
    ),
    "separate_cockpit_backend_to_consume_or_archive": _policy(
        "nonconforming_separate_lens",
        "consume into the same graph lens or archive with evidence",
    ),
    "cloud_capability_readiness_evidence": _policy(
        "capability_evidence",
        "bind readiness outputs to Cell capability policy and release courts",
        required_courts=CLOUD_CAPABILITY_READINESS_COURTS,
    ),
    "retired_baboom_cloud_relay": _policy(
        "superseded_cloud_adapter_retirement",
        (
            "keep only as retirement evidence for the removed /v1/baboom "
            "cloud relay; Universal Cell work handoff is the successor "
            "authority and the retired routes must remain absent"
        ),
        required_courts=BABOOM_RELAY_RETIREMENT_COURTS,
    ),
    "legacy_probe_capability_evidence": _policy(
        "capability_evidence",
        "replace host/file/http probes with Cell capability requests, receipts, and policy gates",
    ),
    "live_locked_legacy_typed_runtime_copy": _policy(
        "superseded_runtime_copy_with_live_process_holders",
        "do not promote; drain or relaunch holders from 10.PRODUCT/13.NODE-LANGUAGE, then archive this copied runtime",
        required_courts=RUNTIME_RETIREMENT_COURTS,
    ),
    "runtime_retirement_gate_hook": _policy(
        "local_enforcement_gate",
        "keep wired to tools/legacy_runtime_drain.py --enforce-retirement-gate; this blocks staged node_runtime retirement while the runtime gate is red",
        required_courts=RUNTIME_RETIREMENT_COURTS,
    ),
    "adapter_payload_candidate": _policy(
        "capability_candidate",
        "bind to Cell capability policy and user permission gates",
        required_courts=ADAPTER_PAYLOAD_COURTS,
    ),
    "ui_runtime_evidence_probe": _policy(
        "evidence_probe",
        "keep as evidence only; not product authority",
        required_courts=UI_RUNTIME_EVIDENCE_COURTS,
    ),
    "documentation_decision_evidence": _policy(
        "decision_evidence",
        "promote only through AUTHORITY.md change protocol",
        required_courts=DOCUMENTATION_DECISION_COURTS,
    ),
    "governance_run_evidence": _policy(
        "run_evidence",
        "keep as generated convergence/drain evidence; do not promote as product authority",
        required_courts=GOVERNANCE_RUN_EVIDENCE_COURTS,
    ),
    "external_owner_worktree_wip": _policy(
        "external_owner_boundary",
        (
            "treat as serialized external worktree WIP; do not integrate, "
            "publish, or claim clean public authority until the owner either "
            "commits it on its branch, hands it off with exact courts, or "
            "explicitly releases it for classification/consumption"
        ),
        required_courts=EXTERNAL_WORKTREE_COURTS,
    ),
    "unclassified_noncoordinated": _policy(
        "blocked",
        "classify before any promotion or release claim",
    ),
}


CDE_CONTAINER = {
    "container_id": "10.PRODUCT/12.PRODUCTION",
    "authority": "10.PRODUCT/13.NODE-LANGUAGE",
    "lifecycle": "WIP",
    "privacy_tier": "T0 PUBLIC",
}


CATEGORY_PRIORITY = {
    "live_locked_legacy_typed_runtime_copy": 9800,
    "universal_cell_bridge": 9000,
    "universal_cell_projection_bridge": 8900,
    "universal_cell_runtime_adapter": 8800,
    "universal_cell_bridge_court": 8700,
    "universal_cell_authority_court": 8600,
    "governance_brain_authority_layer": 8200,
    "runtime_retirement_gate_hook": 8100,
    "legacy_workflow_runtime_to_consume": 7600,
    "legacy_workflow_runtime_frozen_adapter": 7550,
    "legacy_workflow_schema_frozen_adapter": 7525,
    "legacy_workflow_composition_frozen_adapter": 7515,
    "legacy_typed_grammar_frozen_adapter": 7510,
    "legacy_typed_ui_node_frozen_adapter": 7505,
    "legacy_typed_registry_frozen_adapter": 7502,
    "legacy_custom_node_runtime_bridge": 7501,
    "legacy_core_node_runtime_bridge": 7501,
    "legacy_self_extension_runtime_bridge": 7501,
    "legacy_webshell_host_with_cell_bridge": 7500,
    "legacy_handbuilt_projection_cell_catalog_bridge": 7451,
    "legacy_handbuilt_projection_frozen_adapter": 7450,
    "legacy_webshell_host_court": 7400,
    "legacy_workflow_runtime_court": 7375,
    "legacy_handbuilt_projection_to_consume": 7300,
    "legacy_handbuilt_projection_court": 7200,
    "cloud_capability_readiness_evidence": 6800,
    "adapter_payload_candidate": 6600,
    "documentation_decision_evidence": 6100,
    "governance_run_evidence": 6000,
    "ui_runtime_evidence_probe": 5800,
    "external_owner_worktree_wip": 5600,
}


LEGACY_WEBSHELL_BOUNDARY_COURTS = [
    "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_webshell_host.py",
    "tests/test_legacy_webshell_host_boundary.py",
    "tests/test_production_webshell_preview.py",
]

LEGACY_HANDMADE_PROJECTION_COURTS = [
    "../13.NODE-LANGUAGE/tests_replica/test_cell_legacy_surface_catalog.py",
    "tests/test_grand_map_ui_surface.py",
]


UNIVERSAL_CELL_RUNTIME_ADAPTER_COURTS = [
    "personal-brain-mcp/tests/test_active_work_db.py::test_build_server_prefers_runtime_workshop_when_available",
    "personal-brain-mcp/tests/test_active_work_db.py::test_build_server_registers_fail_closed_room_when_runtime_unavailable",
    "personal-brain-mcp/tests/test_server.py::test_context_does_not_fallback_to_legacy_room_when_cell_workshop_unwired",
]


REQUIRED_COURTS_BY_PATH: dict[str, list[str]] = {
    "personal-brain-mcp/src/personal_brain/universal_runtime.py": [
        "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
    ],
    "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py": [
        "personal-brain-mcp/tests/test_active_work_cell_migration.py",
        "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
    ],
    "app/workflows/universal_grand_map_surface.py": [
        "tests/test_universal_grand_map_surface_bridge.py",
    ],
    "app/workflows/baboom_cell_surface.py": [
        "tests/test_baboom_cell_surface_bridge.py",
    ],
    "app/connectors/teams_connector.py": [
        "tests/test_rest_connectors.py",
        "tests/test_adapter_payload_candidate.py",
    ],
    "tests/test_rest_connectors.py": [
        "tests/test_rest_connectors.py",
        "tests/test_adapter_payload_candidate.py",
    ],
    "app/bridge.py": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/web_ui/index.html": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/web_ui/jsx-boot.js": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/web_ui/studio-lm.compiled.js": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/web_ui/studio-lm.jsx": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/web_ui/tokens.jsx": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "tools/production_webshell_preview.py": LEGACY_WEBSHELL_BOUNDARY_COURTS,
    "app/workflows/grand_map_ui.py": LEGACY_HANDMADE_PROJECTION_COURTS,
    "app/workflows/graph.py": [
        "tests/test_core_nodes.py",
        "tests/test_wire_fields.py",
    ],
    "app/workflows/node_grammar.py": [
        "tests/test_grammar_config_schema.py",
        "tests/test_node_grammar.py",
        "tests/test_typed_grammar_end_to_end.py",
        "tests/test_ui_grammar.py",
    ],
    "app/workflows/runner.py": ["tests/test_workflow_runner.py"],
    "app/workflows/subgraph.py": [
        "tests/test_subgraph.py",
        "tests/test_subgraph_tunable_cell.py",
    ],
    "app/workflows/typesystem.py": [
        "tests/test_bridge_wire_validation.py",
        "tests/test_core_nodes.py",
    ],
    "app/workflows/nodes/__init__.py": ["tests/test_core_nodes.py"],
    "app/workflows/nodes/ui.py": ["tests/test_ui_grammar.py"],
    "app/workflows/custom_nodes.py": [
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_custom_node_bridge.py",
        "tests/test_capability_nodes.py",
        "tests/test_subgraph_config_seed.py::test_config_seed_reaches_impl_kind_graph_node",
    ],
    "app/workflows/nodes/core.py": [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_connector_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_model_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_core_node_bridge.py",
        "tests/test_core_nodes.py",
    ],
    "app/agents/self_extend.py": [
        "../13.NODE-LANGUAGE/tests_replica/test_cell_baboom_connector_execution.py",
        "../13.NODE-LANGUAGE/tests_replica/test_legacy_self_extension_bridge.py",
        "tests/test_self_extend_loop.py",
        "tests/test_self_extend_ui_widget.py",
        "tests/test_self_extend_free_text_live.py",
    ],
    "personal-brain-mcp/src/personal_brain/cell_room.py": UNIVERSAL_CELL_RUNTIME_ADAPTER_COURTS,
    "personal-brain-mcp/src/personal_brain/cell_room_wiring.py": UNIVERSAL_CELL_RUNTIME_ADAPTER_COURTS,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_porcelain(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append({"code": line[:2], "path": path})
    return entries


def classify_path(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("external-worktree:"):
        return "external_owner_worktree_wip"

    exact = {
        "personal-brain-mcp/src/personal_brain/active_work_cell_migration.py": "universal_cell_bridge",
        "personal-brain-mcp/src/personal_brain/universal_runtime.py": "universal_cell_bridge",
        "app/workflows/universal_grand_map_surface.py": "universal_cell_projection_bridge",
        "app/workflows/baboom_cell_surface.py": "universal_cell_projection_bridge",
        "cloud_backend/baboom_relay.py": "retired_baboom_cloud_relay",
        "cloud_backend/baboom_relay_protocol.py": "retired_baboom_cloud_relay",
        "cloud_backend/tests/test_baboom_relay.py": "retired_baboom_cloud_relay",
        "cloud_backend/tests/test_baboom_relay_retirement.py": "retired_baboom_cloud_relay",
        "personal-brain-mcp/src/personal_brain/cell_room.py": "universal_cell_runtime_adapter",
        "personal-brain-mcp/src/personal_brain/cell_room_wiring.py": "universal_cell_runtime_adapter",
        "tests/test_baboom_cell_surface_bridge.py": "universal_cell_bridge_court",
        "tests/test_universal_grand_map_surface_bridge.py": "universal_cell_bridge_court",
        "personal-brain-mcp/tests/test_universal_runtime_bridge.py": "universal_cell_bridge_court",
        "personal-brain-mcp/tests/test_active_work_cell_migration.py": "universal_cell_bridge_court",
        "personal-brain-mcp/tests/test_brain_control_cell_migration.py": "universal_cell_bridge_court",
        ".githooks/pre-commit": "runtime_retirement_gate_hook",
        ".githooks/pre-push": "runtime_retirement_gate_hook",
        "tests/test_runtime_retirement_hook.py": "runtime_retirement_gate_hook",
        "tests/test_adapter_payload_candidate.py": "adapter_payload_candidate",
        "app/connectors/teams_connector.py": "adapter_payload_candidate",
        "tests/test_rest_connectors.py": "adapter_payload_candidate",
        "tests/test_universal_cell_node_courts.py": "universal_cell_authority_court",
        "app/workflows/grand_map_ui.py": "legacy_handbuilt_projection_cell_catalog_bridge",
        "tests/test_grand_map_ui_surface.py": "legacy_handbuilt_projection_court",
        "app/workflows/live_nodes.py": "legacy_probe_capability_evidence",
        "tests/test_live_nodes.py": "legacy_probe_capability_evidence",
        "cloud_backend/db.py": "cloud_capability_readiness_evidence",
        "cloud_backend/main.py": "cloud_capability_readiness_evidence",
        "cloud_backend/readiness.py": "cloud_capability_readiness_evidence",
        "cloud_backend/tests/conftest.py": "cloud_capability_readiness_evidence",
        "cloud_backend/tests/test_readiness.py": "cloud_capability_readiness_evidence",
        "app/bridge.py": "legacy_webshell_host_with_cell_bridge",
        "app/web_ui/index.html": "legacy_webshell_host_with_cell_bridge",
        "app/web_ui/jsx-boot.js": "legacy_webshell_host_with_cell_bridge",
        "app/web_ui/studio-lm.compiled.js": "legacy_webshell_host_with_cell_bridge",
        "app/web_ui/studio-lm.jsx": "legacy_webshell_host_with_cell_bridge",
        "app/web_ui/tokens.jsx": "legacy_webshell_host_with_cell_bridge",
        "tools/production_webshell_preview.py": "legacy_webshell_host_with_cell_bridge",
        "tests/test_a11y_phase_4_dropdown_nav.py": "legacy_webshell_host_court",
        "tests/test_a11y_phase_4_modals.py": "legacy_webshell_host_court",
        "tests/test_brain_bridge_slots.py": "legacy_webshell_host_court",
        "tests/test_build_jsx_precompile.py": "legacy_webshell_host_court",
        "tests/test_canvas_ux_fin.py": "legacy_webshell_host_court",
        "tests/test_deck_state.py": "legacy_webshell_host_court",
        "tests/test_design_system_tokens.py": "legacy_webshell_host_court",
        "tests/test_final_shells_graph.py": "legacy_webshell_host_court",
        "tests/test_gpu_resilience.py": "legacy_webshell_host_court",
        "tests/test_host_node_v2_s1.py": "legacy_webshell_host_court",
        "tests/test_jswire_visibility.py": "legacy_webshell_host_court",
        "tests/test_jsx_signal_wiring.py": "legacy_webshell_host_court",
        "tests/test_new_bridge_slots.py": "legacy_webshell_host_court",
        "tests/test_production_webshell_preview.py": "legacy_webshell_host_court",
        "tests/test_reactflow_p2a_groundwork.py": "legacy_webshell_host_court",
        "tests/test_realify_surfaces_wiring.py": "legacy_webshell_host_court",
        "tests/test_self_heal_inspector.py": "legacy_webshell_host_court",
        "tests/test_skill_json_split_view.py": "legacy_webshell_host_court",
        "tests/test_skills_search_panels_wiring.py": "legacy_webshell_host_court",
        "tests/test_ui_cdp_smoke.py": "legacy_webshell_host_court",
        "tests/test_ui_fake_gate.py": "legacy_webshell_host_court",
        "tests/test_version_footer_real.py": "legacy_webshell_host_court",
        "tests/test_adapter_nodes.py": "legacy_workflow_runtime_court",
        "tests/test_ai_plan_node.py": "legacy_workflow_runtime_court",
        "tests/test_canvas_adapter.py": "legacy_workflow_runtime_court",
        "tests/test_bridge_wire_validation.py": "legacy_workflow_runtime_court",
        "app/workflows/graph.py": "legacy_workflow_schema_frozen_adapter",
        "tests/test_code_nodes.py": "legacy_workflow_runtime_court",
        "app/workflows/node_grammar.py": "legacy_typed_grammar_frozen_adapter",
        "app/workflows/runner.py": "legacy_workflow_runtime_frozen_adapter",
        "app/workflows/subgraph.py": "legacy_workflow_composition_frozen_adapter",
        "app/workflows/typesystem.py": "legacy_workflow_schema_frozen_adapter",
        "app/workflows/custom_nodes.py": "legacy_custom_node_runtime_bridge",
        "app/workflows/ui_projection.py": "legacy_workflow_runtime_to_consume",
        "app/workflows/nodes/core.py": "legacy_core_node_runtime_bridge",
        "app/workflows/nodes/__init__.py": "legacy_typed_registry_frozen_adapter",
        "tests/test_core_nodes.py": "legacy_workflow_runtime_court",
        "tests/test_grammar_config_schema.py": "legacy_workflow_runtime_court",
        "tests/test_node_grammar.py": "legacy_workflow_runtime_court",
        "tests/test_node_palette_drag.py": "legacy_workflow_runtime_court",
        "tests/test_param_promote.py": "legacy_workflow_runtime_court",
        "tests/test_recook_param.py": "legacy_workflow_runtime_court",
        "tests/test_subgraph.py": "legacy_workflow_runtime_court",
        "tests/test_typed_ai_nodes.py": "legacy_workflow_runtime_court",
        "app/workflows/nodes/ui.py": "legacy_typed_ui_node_frozen_adapter",
        "tests/test_ui_grammar.py": "legacy_workflow_runtime_court",
        "tests/test_ui_projection.py": "legacy_workflow_runtime_court",
        "tests/test_wire_fields.py": "legacy_workflow_runtime_court",
        "tests/test_workflow_runner.py": "legacy_workflow_runtime_court",
        "app/agents/self_extend.py": "legacy_self_extension_runtime_bridge",
        ".agents/hooks.json": "governance_brain_authority_layer",
        ".gitignore": "governance_brain_authority_layer",
        "pyproject.toml": "governance_brain_authority_layer",
        "tools/antigravity_coordination_context.py": "governance_brain_authority_layer",
        "tools/antigravity_scope_gate.py": "governance_brain_authority_layer",
        "tools/agent_desktop_watchdog.py": "governance_brain_authority_layer",
        "tools/authority_wip_classify.py": "governance_brain_authority_layer",
        "tools/brain_sort_inventory.py": "governance_brain_authority_layer",
        "tools/brainwrap.py": "governance_brain_authority_layer",
        "tools/founder_secret.py": "governance_brain_authority_layer",
        "tools/governed_sessions.py": "governance_brain_authority_layer",
        "tools/import_claude_sessions.py": "governance_brain_authority_layer",
        "tools/legacy_runtime_drain.py": "governance_brain_authority_layer",
        "tools/live_runtime_holders.py": "governance_brain_authority_layer",
        "tools/safety_court_gate.py": "governance_brain_authority_layer",
        "docs/_meta/local_application_servers.cleanup.json": "governance_run_evidence",
        "docs/_meta/local_application_servers.latest.json": "governance_run_evidence",
        "personal-brain-mcp/src/personal_brain/run_report.py": "governance_run_evidence",
        "personal-brain-mcp/tests/test_run_report.py": "governance_run_evidence",
        "tests/test_self_extend_free_text_live.py": "legacy_workflow_runtime_court",
        "tests/test_self_extend_loop.py": "legacy_workflow_runtime_court",
        "tests/test_self_extend_ui_widget.py": "legacy_workflow_runtime_court",
        "tests/test_agent_os_broker.py": "governance_brain_authority_layer",
        "tests/test_agent_os_gate.py": "governance_brain_authority_layer",
        "tests/test_antigravity_governance_hooks.py": "governance_brain_authority_layer",
        "tests/test_authority_wip_classify.py": "governance_brain_authority_layer",
        "tests/test_brainwrap.py": "governance_brain_authority_layer",
        "tests/test_cockpit_legacy_authority_boundary.py": "governance_brain_authority_layer",
        "tests/test_court_metamorphic.py": "governance_brain_authority_layer",
        "tests/test_governed_sessions.py": "governance_brain_authority_layer",
        "tests/test_legacy_runtime_drain.py": "governance_brain_authority_layer",
        "tests/test_legacy_webshell_host_boundary.py": "legacy_webshell_host_court",
        "tests/test_live_runtime_holders.py": "governance_brain_authority_layer",
    }
    if p in exact:
        return exact[p]
    if p.startswith(".agents/"):
        return "governance_brain_authority_layer"
    if p.startswith("personal-brain-mcp/node_courts/"):
        return "universal_cell_authority_court"
    if p.startswith("personal-brain-mcp/") or p.startswith("tools/agent_os_"):
        return "governance_brain_authority_layer"
    if p.startswith("node_runtime/"):
        return "live_locked_legacy_typed_runtime_copy"
    if p.startswith("app/workflows/grand_map_ui"):
        return "legacy_handbuilt_projection_to_consume"
    if p.startswith("cloud_backend/cockpit"):
        return "separate_cockpit_backend_to_consume_or_archive"
    if (
        p.startswith("app/web_ui/")
        or p.startswith("tests/test_a11y")
        or p.startswith("tests/test_build_jsx")
        or p.startswith("tests/test_canvas")
        or p.startswith("tests/test_deck_state")
        or p.startswith("tests/test_final_shells_graph")
        or p.startswith("tests/test_jsx")
        or p.startswith("tests/test_realify_surfaces_wiring")
    ):
        return "old_studio_ui_surface_migration_evidence"
    if (
        p.startswith("docs/_meta/authority_wip_classification")
        or p.startswith("docs/_meta/freshness")
        or p.startswith("docs/_meta/index")
        or p.startswith("docs/_meta/legacy_runtime_handoff_board")
        or p.startswith("docs/_meta/legacy_runtime_handoff_disposable_cleanup")
        or p.startswith("docs/_meta/legacy_runtime_handoff_inspection")
        or p.startswith("docs/_meta/legacy_runtime_handoff_shadow_probe")
        or p.startswith("docs/_meta/legacy_runtime_handoff_stale_stdin_cleanup")
        or p.startswith("docs/_meta/legacy_runtime_source_drift")
        or p.startswith("docs/_meta/legacy_runtime_universal_holder_verification")
        or p.startswith("docs/_meta/live_runtime_holders")
        or p.startswith("docs/_meta/run_report_")
    ):
        return "governance_run_evidence"
    if p.startswith("docs/"):
        return "documentation_decision_evidence"
    if p.startswith("payload/rhino/") or p.startswith("tests/test_port_type_speckle_adapter"):
        return "adapter_payload_candidate"
    if p.startswith("tools/verify_"):
        return "ui_runtime_evidence_probe"
    if (
        p.startswith("app/agents/self_extend.py")
        or p.startswith("app/workflows/")
        or p.startswith("tests/test_core_nodes")
        or p.startswith("tests/test_grammar_config_schema")
        or p.startswith("tests/test_node")
        or p.startswith("tests/test_param")
        or p.startswith("tests/test_self_extend_loop")
        or p.startswith("tests/test_self_extend_ui_widget")
        or p.startswith("tests/test_subgraph")
        or p.startswith("tests/test_wire")
        or p.startswith("tests/test_workflow")
    ):
        return "legacy_workflow_runtime_to_consume"
    return "unclassified_noncoordinated"


def classify_entries(
    entries: Iterable[dict[str, str]],
    *,
    include_runtime_holders: bool = False,
    repo: Path | None = None,
) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, str]]] = {}
    classified: list[dict[str, str]] = []
    for entry in entries:
        item = dict(entry)
        item["category"] = classify_path(item["path"])
        policy = CATEGORY_POLICY[item["category"]]
        item["disposition"] = policy["disposition"]
        item["required_action"] = policy["required_action"]
        item["promotion_allowed"] = str(bool(policy["promotion_allowed"])).lower()
        normalized_path = item["path"].replace("\\", "/")
        item["required_courts"] = REQUIRED_COURTS_BY_PATH.get(
            normalized_path, list(policy["required_courts"])
        )
        classified.append(item)
        by_category.setdefault(item["category"], []).append(item)
    unclassified = by_category.get("unclassified_noncoordinated", [])
    promotion_candidates = [
        {
            "path": item["path"],
            "required_courts": item["required_courts"],
        }
        for item in classified
        if item["promotion_allowed"] == "true"
    ]
    digest_source = [
        {
            "path": item["path"],
            "code": item["code"],
            "category": item["category"],
            "disposition": item["disposition"],
            "required_courts": item["required_courts"],
            **(
                {
                    "worktree_branch": item.get("worktree_branch", ""),
                    "worktree_head": item.get("worktree_head", ""),
                }
                if item.get("category") == "external_owner_worktree_wip"
                else {}
            ),
        }
        for item in sorted(classified, key=lambda value: value["path"])
    ]
    classification_digest = hashlib.sha256(
        json.dumps(digest_source, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    report: dict[str, Any] = {
        "schema": "archhub-public-wip-authority-classification/v1",
        "authority": "10.PRODUCT/13.NODE-LANGUAGE/AUTHORITY.md + SPEC.md",
        "total": len(classified),
        "classification_digest": classification_digest,
        "summary": {key: len(value) for key, value in sorted(by_category.items())},
        "gate": {
            "no_unclassified": {
                "ok": not unclassified,
                "count": len(unclassified),
                "paths": [item["path"] for item in unclassified],
            },
            "promotion_rule": (
                "No public WIP file outside 10.PRODUCT/13.NODE-LANGUAGE is a "
                "product-authority candidate by classification alone. "
                "universal_cell_bridge entries may be kept only as bounded "
                "runtime clients when their listed courts prove they consume "
                "the application-owned Universal Cell runtime, open no side "
                "store, and fail closed without local fallback. Cell-native side "
                "stores are not authority candidates. Runtime projection "
                "adapters may read the application-owned runtime but do not own "
                "authority. Every other category is migration control, "
                "evidence, or material to consume/archive."
            ),
            "promotion_candidates": {
                "count": len(promotion_candidates),
                "items": promotion_candidates,
            },
        },
        "entries": classified,
        "categories": CATEGORY_POLICY,
    }
    report["active_work_leaves"] = wip_category_leaves(report)
    if include_runtime_holders:
        root = repo or repo_root()
        report["live_runtime_holders"] = live_runtime_holders.audit(
            live_runtime_holders.default_runtime_copy(root)
        )
        report["local_application_servers"] = (
            live_runtime_holders.audit_local_application_servers(root.parents[1])
        )
    return report


def wip_category_leaves(report: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report.get("entries") or []:
        grouped.setdefault(str(item["category"]), []).append(item)
    leaves: list[dict[str, Any]] = []
    for category, items in sorted(grouped.items()):
        if category == "unclassified_noncoordinated":
            continue
        policy = CATEGORY_POLICY[category]
        paths = sorted(str(item["path"]) for item in items)
        courts = sorted({
            str(court)
            for item in items
            for court in item.get("required_courts", [])
        })
        if category.endswith("_court"):
            courts = sorted({
                *courts,
                *(
                    path for path in paths
                    if path.endswith(".py")
                    and (
                        path.startswith("tests/")
                        or path.startswith("personal-brain-mcp/tests/")
                    )
                ),
            })
        selectors = list(dict.fromkeys([
            "tests/test_authority_wip_classify.py",
            *courts,
        ]))
        leaves.append({
            "title": "Consume public WIP category: %s" % category,
            "gate_kind": "pytest",
            "gate_spec": {
                "path": "tests/test_authority_wip_classify.py",
                "selectors": selectors,
                "args": ["-q"],
                "category": category,
                "classification_digest": report.get("classification_digest"),
                "required_courts": courts,
            },
            "cde_container": dict(CDE_CONTAINER),
            "governance_context": {
                "schema": "archhub-public-wip-category-consumption/v1",
                "authority": report.get("authority"),
                "category": category,
                "disposition": policy["disposition"],
                "required_action": policy["required_action"],
                "classification_digest": report.get("classification_digest"),
                "path_count": len(paths),
                "paths": paths,
                "required_courts": courts,
                "promotion_allowed": False,
            },
            "fit": ["governance", "universal-cell-authority", "wip-convergence"],
            "priority": CATEGORY_PRIORITY.get(category, 5000),
        })
    return leaves


def register_active_work_leaves(
    report: dict[str, Any],
    *,
    repo: Path,
    brain_path: Path | None = None,
    owner_user: str = "founder",
) -> dict[str, Any]:
    leaves = list(report.get("active_work_leaves") or [])
    if not leaves:
        return {
            "schema": "archhub-public-wip-active-work-registration/v1",
            "owner_user": owner_user,
            "leaf_count": 0,
            "leaf_ids": [],
        }
    source = repo / "personal-brain-mcp" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from personal_brain import active_work as aw  # noqa: WPS433
    from personal_brain.storage import BrainStore, default_brain_path  # noqa: WPS433

    store = BrainStore.open(brain_path or default_brain_path())
    try:
        ledger = aw.add_leaves(store, owner_user=owner_user, leaves=leaves)
    finally:
        store.close()
    leaf_ids = [
        aw._leaf_id(owner_user, str(leaf["title"]))  # noqa: SLF001
        for leaf in leaves
    ]
    return {
        "schema": "archhub-public-wip-active-work-registration/v1",
        "owner_user": owner_user,
        "leaf_count": len(leaves),
        "leaf_ids": leaf_ids,
        "open_leaf_ids": [
            leaf_id for leaf_id in leaf_ids
            if leaf_id in ledger.leaves
            and ledger.leaves[leaf_id].state == aw.LeafState.OPEN
        ],
        "classification_digest": report.get("classification_digest"),
        "brain_path": str(brain_path or default_brain_path()),
    }


def current_status(repo: Path) -> list[dict[str, str]]:
    text = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
    )
    return parse_porcelain(text)


def _worktree_paths(repo: Path) -> list[Path]:
    text = subprocess.check_output(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        text=True,
    )
    paths: list[Path] = []
    for line in text.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def external_worktree_status(repo: Path) -> list[dict[str, str]]:
    """Return ordinary WIP from registered worktrees outside ``repo``.

    Missing/prunable worktrees are excluded here because they are Git metadata
    cleanup work, not source WIP that can be consumed into product authority.
    """
    root = repo.resolve()
    entries: list[dict[str, str]] = []
    for worktree in _worktree_paths(repo):
        if not worktree.exists():
            continue
        try:
            resolved = worktree.resolve()
        except OSError:
            continue
        if resolved == root:
            continue
        status_text = subprocess.check_output(
            ["git", "-C", str(resolved), "status", "--porcelain"],
            text=True,
        )
        branch = subprocess.check_output(
            ["git", "-C", str(resolved), "branch", "--show-current"],
            text=True,
        ).strip()
        head = subprocess.check_output(
            ["git", "-C", str(resolved), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        label = branch or resolved.name
        for item in parse_porcelain(status_text):
            local_path = item["path"].replace("\\", "/")
            external_path = f"external-worktree:{label}/{local_path}"
            entry = {
                "code": item["code"],
                "path": external_path,
                "worktree_path": str(resolved),
                "worktree_branch": label,
                "worktree_head": head,
                "worktree_entry_path": local_path,
            }
            entries.append(entry)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify public repo WIP against Universal Cell authority."
    )
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--output", default="")
    parser.add_argument("--enforce-no-unclassified", action="store_true")
    parser.add_argument("--include-runtime-holders", action="store_true")
    parser.add_argument("--include-worktrees", action="store_true")
    parser.add_argument("--register-active-work", action="store_true")
    parser.add_argument("--brain-path", default="")
    parser.add_argument("--owner-user", default="founder")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    entries = current_status(repo)
    if args.include_worktrees:
        entries = [*entries, *external_worktree_status(repo)]
    report = classify_entries(
        entries,
        include_runtime_holders=args.include_runtime_holders,
        repo=repo,
    )
    if args.register_active_work:
        report["active_work_registration"] = register_active_work_leaves(
            report,
            repo=repo,
            brain_path=Path(args.brain_path).resolve() if args.brain_path else None,
            owner_user=args.owner_user,
        )
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.enforce_no_unclassified and not report["gate"]["no_unclassified"]["ok"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
