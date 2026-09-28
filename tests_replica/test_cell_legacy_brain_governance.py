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

RETIRED = ("Retired with 12.PRODUCTION (ce8ab49 'Retire 12.PRODUCTION: Brain port, cloud import, founder rules, native compliance observer', 2026-09-26): the personal-brain-mcp sources this court read are no longer part of the product; compliance now means the landed governance hooks (25675e4) and the application's Brain answers from the graph (36e8549).")

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
    """The contract still names each legacy channel's source and courts, but
    those sources were retired with 12.PRODUCTION (see RETIRED). What stays
    protected: none of them is carried back into this repository, nothing here
    imports the retired Brain, and every channel keeps its fenced authority."""
    for spec in BRAIN_GOVERNANCE_SPECS:
        assert not (ROOT / str(spec["source_path"])).exists(), (
            "a retired Brain source came back: %s" % spec["source_path"])
    for path in list((ROOT / "nodelang").rglob("*.py")) + [ROOT / "launch_archhub_test.py"]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "import personal_brain" not in text and "from personal_brain" not in text, path.name

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


@pytest.mark.skip(reason=RETIRED)
def test_public_brain_ledger_routes_cannot_fall_back_to_metadata_or_assemblies():
    """Held the retired personal-brain-mcp ledger routes (compliance, run
    report, hook coverage, active work, core values, universal work) to
    Cell-first reads with no metadata or assembly fallback. Those routes left
    the product with 12.PRODUCTION; the Cell-held contract above stays."""


@pytest.mark.skip(reason=RETIRED)
def test_core_values_public_audit_cannot_fall_back_to_brain_metadata():
    """Held the retired personal-brain-mcp core-values audit to Cell-first
    reads. It left the product with 12.PRODUCTION."""


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
