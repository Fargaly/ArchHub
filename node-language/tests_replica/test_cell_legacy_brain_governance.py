"""The legacy Brain governance layer must be a Cell-held projection contract."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = PRODUCT_ROOT / "12.PRODUCTION"

from nodelang.cell_legacy_brain_governance import (  # noqa: E402
    ACTIVE_CELL_AUTHORITY,
    AUTHORITY_STATUS,
    BRAIN_GOVERNANCE_SPECS,
    bootstrap_legacy_brain_governance_protocol,
    brain_governance_contract_digest,
    build_legacy_brain_governance_contract,
    project_legacy_brain_governance_contract,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell  # noqa: E402
import nodelang.cell_legacy_brain_governance as contract_module  # noqa: E402


def _function_body(source: str, name: str) -> str:
    """Return one exact function body, including nested MCP handlers."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError("function %s is missing" % name)


def _contract_world():
    store = CellStore()
    protocol = bootstrap_legacy_brain_governance_protocol(store)
    built = build_legacy_brain_governance_contract(store, protocol)
    return store, protocol, built


def test_brain_governance_contract_is_cells_and_non_promotable():
    store, protocol, built = _contract_world()
    projection = project_legacy_brain_governance_contract(
        store.snapshot(), protocol, built.root_id
    )

    assert projection["capability_count"] == len(BRAIN_GOVERNANCE_SPECS)
    assert projection["digest"] == brain_governance_contract_digest(
        BRAIN_GOVERNANCE_SPECS
    )
    assert projection["active_authority"] == ACTIVE_CELL_AUTHORITY
    assert projection["authority_status"] == AUTHORITY_STATUS
    assert projection["promotion_allowed"] is False
    assert all(
        item["authority"] == ACTIVE_CELL_AUTHORITY
        for item in projection["capabilities"]
    )
    modes = set(projection["authority_modes"])
    assert "cell-first-route" in modes
    assert "mixed-cell-first" in modes
    assert "legacy-control-projection" not in modes
    assert "external-adapter-projection" in modes


def test_brain_governance_contract_matches_real_sources_and_courts():
    for spec in BRAIN_GOVERNANCE_SPECS:
        source_path = PUBLIC_ROOT / str(spec["source_path"])
        assert source_path.is_file(), spec["source_path"]
        source = source_path.read_text(encoding="utf-8", errors="ignore")
        assert str(spec["source_symbol"]) in source
        for tool_name in spec["tool_names"]:
            assert ('name="%s"' % tool_name) in source
        for court in spec["required_courts"]:
            assert (PUBLIC_ROOT / str(court)).is_file(), court

    by_capability = {
        str(spec["capability"]): spec
        for spec in BRAIN_GOVERNANCE_SPECS
    }
    assert "brain.hook_coverage_repair_cell_first" in by_capability[
        "hook-coverage"
    ]["tool_names"]
    assert "brain.compliance_event_append_cell_first" in by_capability[
        "compliance-history"
    ]["tool_names"]
    for capability in (
        "universal-runtime-work", "hook-coverage", "compliance-history",
        "run-report", "core-values-authority",
    ):
        channel = by_capability[capability]
        assert channel["authority_mode"] == "cell-first-route"
        assert channel["legacy_migration_only"] == "false"
        assert channel["brain_meta_write"] == "false"
    assert by_capability["runtime-holder-audit"]["tool_names"] == ()
    assert by_capability["runtime-holder-audit"]["source_path"] == (
        "tools/legacy_runtime_drain.py"
    )
    assert by_capability["runtime-holder-audit"]["source_symbol"] == (
        "sync_runtime_holders_to_universal"
    )
    assert by_capability["runtime-holder-audit"]["authority_mode"] == (
        "mixed-cell-first"
    )
    assert by_capability["runtime-holder-audit"]["cell_read"] == "true"
    assert by_capability["runtime-holder-audit"]["cell_write"] == "true"
    roma = by_capability["roma-requirement-court"]
    assert roma["authority_mode"] == "cell-first-route"
    assert roma["legacy_migration_only"] == "false"
    assert roma["brain_meta_write"] == "false"
    assert roma["cell_read"] == "true"
    assert roma["cell_write"] == "true"
    assert by_capability["secret-resolution"]["effect_boundary"] == "secret-custody"
    grand_map = by_capability["grand-map-sync"]
    assert grand_map["authority_mode"] == "cell-first-route"
    assert grand_map["brain_meta_write"] == "false"
    assert grand_map["legacy_migration_only"] == "false"
    assert grand_map["tool_names"] == (
        "brain.grand_map_work_preview_cell_first",
        "brain.grand_map_work_sync_cell_first",
    )


def test_public_brain_ledger_routes_cannot_fall_back_to_metadata_or_assemblies():
    sources = {
        "compliance": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/compliance_report.py"
        ).read_text(encoding="utf-8"),
        "run-report": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/run_report.py"
        ).read_text(encoding="utf-8"),
        "hook-coverage": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/hook_coverage.py"
        ).read_text(encoding="utf-8"),
        "active-work": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/active_work.py"
        ).read_text(encoding="utf-8"),
        "core-values": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/core_values_authority.py"
        ).read_text(encoding="utf-8"),
        "universal-work": (
            PUBLIC_ROOT / "personal-brain-mcp/src/personal_brain/server.py"
        ).read_text(encoding="utf-8"),
    }
    forbidden_by_function = {
        "append_compliance_event_cell_first": (
            "assembly_create", "_append_prepared_event",
            "_sync_control_records_to_cells", "store.update_meta",
        ),
        "get_compliance_history_cell_first": ("store.get_meta",),
        "append_run_report_cell_first": (
            "assembly_create", "_append_prepared_run_report", "store.update_meta",
        ),
        "get_run_reports_cell_first": ("store.get_meta",),
        "audit_cell_first": (
            "assembly_create", "_persist_receipt", "store.set_meta",
            "store.update_meta", "_append_history_event",
        ),
        "get_report_cell_first": ("store.get_meta",),
        "brain_universal_work_status": (
            "store.get_meta", "migrate_legacy_work", "assembly_create",
        ),
        "brain_universal_work_next": (
            "store.get_meta", "migrate_legacy_work", "assembly_create",
        ),
        "brain_universal_work_create": (
            "store.get_meta", "migrate_legacy_work", "assembly_create",
        ),
        "brain_universal_work_transition": (
            "store.get_meta", "migrate_legacy_work", "assembly_create",
        ),
        "brain_universal_work_court": (
            "store.get_meta", "migrate_legacy_work", "assembly_create",
        ),
        "repair_cell_first": (
            "assembly_create", "_persist_receipt", "store.set_meta",
            "store.update_meta", "_append_history_event",
        ),
        "brain_work_assigned_block": (
            "migrate_legacy_work", "legacy.get_ledger", "store.get_meta",
        ),
        "audit_cell_first": (
            "_persist_report", "store.set_meta", "store.update_meta",
        ),
        "get_report_cell_first": ("store.get_meta",),
    }
    for function, forbidden in forbidden_by_function.items():
        body = next(
            _function_body(source, function)
            for source in sources.values()
            if any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function
                for node in ast.walk(ast.parse(source))
            )
        )
        assert all(token not in body for token in forbidden), function


def test_core_values_public_audit_cannot_fall_back_to_brain_metadata():
    source = (
        PUBLIC_ROOT
        / "personal-brain-mcp/src/personal_brain/core_values_authority.py"
    ).read_text(encoding="utf-8")
    for function, forbidden in {
        "audit_cell_first": (
            "_persist_report", "store.set_meta", "store.update_meta",
        ),
        "get_report_cell_first": ("store.get_meta",),
    }.items():
        body = _function_body(source, function)
        assert all(token not in body for token in forbidden), function


def test_brain_governance_contract_rejects_graph_drift():
    store, protocol, built = _contract_world()
    authority_root = built.capability_roots[0] + ":authority"
    original = store.read(authority_root)
    store.commit(store.revision, replace=(
        Cell(original.id, original.link0, original.link1, b"legacy-brain"),
    ))

    with pytest.raises(InvalidCell, match="Cell authority|digest drifted"):
        project_legacy_brain_governance_contract(
            store.snapshot(), protocol, built.root_id
        )


def test_brain_governance_contract_rejects_unadmitted_channels():
    store = CellStore()
    protocol = bootstrap_legacy_brain_governance_protocol(store)
    bad_authority = dict(BRAIN_GOVERNANCE_SPECS[0])
    bad_authority["authority"] = "personal_brain.sqlite"
    with pytest.raises(InvalidCell, match="Cell authority"):
        build_legacy_brain_governance_contract(
            store, protocol, specs=(bad_authority,)
        )

    store = CellStore()
    protocol = bootstrap_legacy_brain_governance_protocol(store)
    bad_tool = dict(BRAIN_GOVERNANCE_SPECS[0])
    bad_tool["tool_names"] = ("shell.exec",)
    with pytest.raises(InvalidCell, match="tool must be namespaced"):
        build_legacy_brain_governance_contract(
            store, protocol, specs=(bad_tool,)
        )

    store = CellStore()
    protocol = bootstrap_legacy_brain_governance_protocol(store)
    bad_path = dict(BRAIN_GOVERNANCE_SPECS[0])
    bad_path["source_path"] = "../outside.py"
    with pytest.raises(InvalidCell, match="source path"):
        build_legacy_brain_governance_contract(
            store, protocol, specs=(bad_path,)
        )


def test_brain_governance_contract_module_does_not_import_or_execute_brain():
    source = inspect.getsource(contract_module)
    for forbidden in (
        "from personal_brain",
        "import personal_brain",
        "BrainStore",
        "FastMCP",
        "sqlite3",
        "subprocess",
        "ThreadingHTTPServer",
        "webbrowser",
        "open(",
        "exec(",
        "eval(",
    ):
        assert forbidden not in source
