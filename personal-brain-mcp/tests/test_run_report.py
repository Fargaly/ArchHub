"""Run-report ledger tests for Brain governance."""
from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from personal_brain import compliance_report as cr  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _report_payload() -> dict:
    return {
        "what_i_did": ["Implemented the gate"],
        "where_we_are": ["Gate is wired to Brain"],
        "evidence": ["pytest personal-brain-mcp/tests/test_run_report.py"],
        "problems_risks": ["Dashboard still needs to surface it"],
        "whats_next": ["Expose reports in Cockpit"],
    }


def _run_report_module():
    try:
        return importlib.import_module("personal_brain.run_report")
    except ImportError as ex:
        pytest.fail(f"personal_brain.run_report module is missing: {ex}")


def test_run_report_append_persists_node_and_compliance_event(store):
    rr = _run_report_module()

    result = rr.append_run_report(
        store,
        owner_user="founder",
        leaf_id="leaf-123",
        runtime="codex",
        agent_id="codex-session",
        report=_report_payload(),
        changed_nodes=["brain.run_report_append", "brain.work_release"],
    )

    assert result["ok"] is True
    assert result["report"]["schema"] == "archhub-run-report/v1"
    assert result["report"]["leaf_id"] == "leaf-123"
    assert result["report"]["sections"]["what_i_did"] == ["Implemented the gate"]
    assert result["report"]["changed_nodes"] == [
        "brain.run_report_append",
        "brain.work_release",
    ]
    assert result["report"]["report_id"]
    assert result["total"] == 1

    raw = json.loads(store.get_meta(rr.RUN_REPORT_META_KEY))
    stored = raw["owners"]["founder"]["reports"][0]
    assert stored["report_id"] == result["report"]["report_id"]

    latest = rr.get_run_reports(
        store,
        owner_user="founder",
        leaf_id="leaf-123",
        limit=10,
    )
    assert latest["ok"] is True
    assert latest["total"] == 1
    assert latest["reports"][0]["leaf_id"] == "leaf-123"

    history = cr.get_compliance_history(store, owner_user="founder", limit=1)
    assert history["events"][0]["event_type"] == "run_report_append"
    assert history["events"][0]["leaf_id"] == "leaf-123"


def test_server_registers_run_report_tools(store):
    from personal_brain.server import build_server

    rr = _run_report_module()
    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}

    assert "brain.run_report_append" in names
    assert "brain.run_report_append_cell_first" in names
    assert "brain.run_report_get" in names

    appended = mcp._tools["brain.run_report_append"].handler(
        report=_report_payload(),
        owner_user="founder",
        leaf_id="leaf-123",
        runtime="codex",
        agent_id="codex-session",
        changed_nodes=["run_report_v1"],
    )
    fetched = mcp._tools["brain.run_report_get"].handler(
        owner_user="founder",
        leaf_id="leaf-123",
        limit=10,
    )

    assert appended["ok"] is False
    assert appended["migration_only"] is True
    assert appended["deprecated"] is True
    assert appended["code"] == "legacy_governance_route_retired"
    assert appended["brain_written"] is False
    assert appended["cell_first_alternative"] == \
        "brain.run_report_append_cell_first"
    assert fetched["ok"] is False
    assert fetched["cell_first"] is True
    assert fetched["reports"] == []
    assert store.get_meta(rr.RUN_REPORT_META_KEY) is None


def test_legacy_run_report_tool_discloses_cell_first_alternative(store):
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    tool = next(
        item for item in mcp.list_tools()
        if item["name"] == "brain.run_report_append"
    )

    assert "RETIRED" in tool["description"]
    result = mcp._tools["brain.run_report_append"].handler(
        report=_report_payload(),
        owner_user="founder",
        leaf_id="leaf-legacy-report",
        runtime="codex",
        agent_id="codex-session",
        changed_nodes=["legacy-report"],
    )

    assert result["ok"] is False
    assert result["migration_only"] is True
    assert result["deprecated"] is True
    assert result["code"] == "legacy_governance_route_retired"
    assert result["brain_written"] is False
    assert result["cell_first_alternative"] == \
        "brain.run_report_append_cell_first"
