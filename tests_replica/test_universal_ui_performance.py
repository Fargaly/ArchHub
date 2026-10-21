"""Bounded rendered-DOM load court for the universal graph projection."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
)
from nodelang.universal_view import project_universal_document


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "universal_interaction_probe.mjs"


def test_revision_history_uses_deltas_and_a_bounded_snapshot_cache():
    store, _registry = build_universal_application(resolve_map_path())
    stats = store.retention_stats()
    assert stats["revision_count"] > 300
    assert stats["current_cell_count"] > 100_000
    assert stats["version_cell_count"] < stats["current_cell_count"] * 2
    assert stats["historical_snapshot_count"] <= 2
    assert stats["historical_snapshot_cell_count"] <= (
        stats["current_cell_count"] * 2
    )


def test_250_nodes_and_500_relation_views_select_within_one_frame():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
            # Selection is an interaction delta in the running Universal
            # server. A full graph response is a recovery path, not the
            # steady-state gesture contract being measured here.
            "deltaResponses": True,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["renderedNodeCount"] == 250
    assert result["renderedWireCount"] == 500
    assert result["canvasIdentityPreserved"] is True
    assert result["selected"] == ["court:node:249"]
    assert result["gesture"]["payload"]["projection_mode"] == (
        "interaction-delta-v1"
    )
    # Visible selection is local direct manipulation: the card must react in
    # the same frame. The subsequent Cell-authorized delta remains bounded
    # separately so a fast preview cannot hide a slow committed result.
    assert result["selectionFeedbackMs"] < 16.7
    assert result["selectionCommitMs"] < 100


def test_dense_property_change_reconciles_without_stage_rebuild():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_property_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["renderedNodeCount"] == 250
    assert result["renderedWireCount"] == 500
    assert result["retainedCardIdentityCount"] == 250
    assert result["retainedWireIdentityCount"] == 500
    assert result["propertyInputIdentityPreserved"] is True
    assert result["propertyEditRequest"]["payload"]["projection_mode"] == (
        "interaction-delta-v1"
    )
    assert result["propertyReconcileMs"] < 100


def test_topology_delta_adds_to_250_nodes_without_rebuilding_stable_ui():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_topology_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["renderedNodeCount"] == 251
    assert result["renderedWireCount"] == 501
    assert result["retainedCardIdentityCount"] == 250
    assert result["retainedWireIdentityCount"] == 500
    assert result["libraryIdentityPreserved"] is True
    assert result["toolbarIdentityPreserved"] is True
    assert result["topologyReconcileMs"] < 100


def test_dense_lens_switch_expands_ports_without_rebuilding_stable_graph():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_lens_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["renderedNodeCount"] == 250
    assert result["renderedWireCount"] == 500
    assert result["retainedCardIdentityCount"] == 250
    assert result["retainedWireIdentityCount"] == 500
    assert result["expandedSocketCount"] == 500
    assert result["lensReconcileMs"] < 150


def test_dense_wire_preview_marks_only_admitted_targets_within_one_frame():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_wire_preview_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["wirePreviewCount"] == 1
    assert result["wireTargetReadyCount"] == 250
    assert result["remainingWirePreviews"] == 0
    assert result["remainingWireTargetReadyCount"] == 0
    assert result["wirePreviewMs"] < 16.7


def test_dense_node_drag_feedback_is_one_frame_and_commits_within_100ms():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_drag_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
            "deltaResponses": True,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["canvasIdentityPreserved"] is True
    assert result["dragFeedbackMs"] < 16.7
    assert result["dragCommitMs"] < 100


def test_dense_wheel_zoom_responds_in_one_frame_then_commits_governed_viewport():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_wheel_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
            "deltaResponses": True,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["canvasIdentityPreserved"] is True
    assert result["gesture"]["payload"]["projection_mode"] == (
        "interaction-delta-v1"
    )
    # The zoom transform is direct manipulation; persistence follows after
    # the Cell-governed debounce and must not block the visible response.
    assert result["wheelFeedbackMs"] < 16.7
    assert result["wheelCommitMs"] < 300


def test_dense_space_pan_responds_in_one_frame_and_commits_within_100ms():
    store, registry = build_universal_application(resolve_map_path())
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        input=json.dumps({
            "html": project_universal_document(
                store, registry, csrf_token="a" * 32
            ),
            "projection": project_universal_canvas(store, registry),
            "scenario": "performance_pan_250",
            "syntheticCount": 250,
            "syntheticWireCount": 500,
            "deltaResponses": True,
        }),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["canvasIdentityPreserved"] is True
    assert result["gesture"]["payload"]["projection_mode"] == (
        "interaction-delta-v1"
    )
    assert result["panFeedbackMs"] < 16.7
    assert result["panCommitMs"] < 100
