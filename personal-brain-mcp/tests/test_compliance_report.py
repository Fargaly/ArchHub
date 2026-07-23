"""Compliance report tests for Brain governance status."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_NODE_LANGUAGE = Path(__file__).resolve().parents[4] / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(_NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(_NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from personal_brain import active_work as aw  # noqa: E402
from personal_brain import compliance_report as cr  # noqa: E402
from personal_brain import hook_coverage as hc  # noqa: E402
from personal_brain import installer  # noqa: E402
from personal_brain import runtime_holders as rh  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


class _InProcessRuntimeBridge:
    def __init__(self, server):
        self._server = server

    def deliberation_read(self, **body):
        return self._server.dispatch_universal_machine_route({
            "method": "GET", "path": "/api/universal/deliberation",
            "body": dict(body),
        })

    def deliberation_append(self, **body):
        return self._server.dispatch_universal_machine_route({
            "method": "POST", "path": "/api/universal/deliberation",
            "body": dict(body),
        })


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    installer.ALL_PLANS["claude-code"].config_path = (
        tmp_path / ".claude" / "settings.json")
    installer.ALL_PLANS["cursor"].config_path = tmp_path / ".cursor" / "mcp.json"
    installer.ALL_PLANS["codex"].config_path = tmp_path / ".codex" / "config.toml"
    installer.ALL_PLANS["gemini-cli"].config_path = (
        tmp_path / ".gemini" / "settings.json")
    yield tmp_path


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _container() -> dict:
    return {
        "container_id": "GM.ui.ui_home_topbar",
        "source_requirement": "grand-map:ui_home_topbar",
        "domain": "ui",
        "tier": "T1",
        "lifecycle_state": "PRODUCTION",
        "suitability_status": "S1",
        "revision": "P01",
        "owner": "agent",
        "checker": "court",
        "allowed_paths": ["10.PRODUCT/12.PRODUCTION/app/web_ui/"],
        "gate_kind": "cdp",
        "gate_spec": {"selector": "[data-uisurface='home-top']"},
        "evidence_ref": "cdp:home-top",
    }


def test_compliance_report_combines_hook_work_cde_and_gate(
    fake_home,
    store,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BRAIN_CELL_ROOM", "0")
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    audit = hc.audit_cell_first(
        store, only=["codex"], owner_user="founder", cell_bridge=bridge
    )
    assert audit["ok"] is True
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "home topbar from nodes",
        "gate_kind": "cdp",
        "gate_spec": {"selector": "[data-uisurface='home-top']"},
        "cde_container": _container(),
    }])
    from personal_brain.meeting_room import room_say
    ledger = aw.get_ledger(store, owner_user="founder")
    leaf_id = next(iter(ledger.leaves.values())).leaf_id
    room_say(
        store,
        frm="test-agent",
        kind="plan",
        refs=[leaf_id],
        text="Plan for compliance report CDE claim.",
    )
    claimed = aw.next_leaf(store, runtime="codex", owner_user="founder")

    cde_path = tmp_path / "active-cde.json"
    gate_path = tmp_path / "last-gate.json"
    monkeypatch.setenv("ARCHHUB_ACTIVE_CDE_STATE", str(cde_path))
    monkeypatch.setenv("ARCHHUB_LAST_GATE_DECISION", str(gate_path))
    cde_path.write_text(
        json.dumps({
            "schema": "archhub-active-cde/v1",
            "runtime": "codex",
            "leaf_id": claimed.leaf_id,
            "container": _container(),
        }),
        encoding="utf-8",
    )
    gate_path.write_text(
        json.dumps({
            "schema": "archhub-gate-decision/v1",
            "decision": "deny",
            "tool": "Write",
            "path": "10.PRODUCT/12.PRODUCTION/app/bridge.py",
            "code": "outside_allowed_paths",
            "container_id": "GM.ui.ui_home_topbar",
        }),
        encoding="utf-8",
    )

    report = cr.build_compliance_report(
        store, owner_user="founder", cell_bridge=bridge
    )
    server.close()

    assert report["ok"] is True
    assert report["hook_coverage"]["status"] == "green"
    assert report["work"]["counts"]["claimed"] == 1
    assert report["active_cde"]["container"]["container_id"] == "GM.ui.ui_home_topbar"
    assert report["last_gate_decision"]["decision"] == "deny"
    assert "Hook coverage: green" in report["markdown"]
    assert "Active CDE: GM.ui.ui_home_topbar" in report["markdown"]
    assert "Last gate: deny" in report["markdown"]


def test_compliance_report_suppresses_stale_active_cde_without_claimed_work(
    store, tmp_path, monkeypatch,
):
    cde_path = tmp_path / "active-cde.json"
    monkeypatch.setenv("ARCHHUB_ACTIVE_CDE_STATE", str(cde_path))
    cde_path.write_text(json.dumps({
        "schema": "archhub-active-cde/v1",
        "leaf_id": "stale-leaf",
        "container": _container(),
    }), encoding="utf-8")

    report = cr.build_compliance_report(store, owner_user="founder")

    assert report["work"]["counts"]["claimed"] == 0
    assert report["active_cde"] == {}
    assert "Active CDE: none" in report["markdown"]


def test_compliance_report_does_not_project_legacy_run_report_metadata(store):
    from personal_brain import run_report as rr

    rr.append_run_report(
        store,
        owner_user="founder",
        leaf_id="leaf-123",
        runtime="codex",
        agent_id="codex-session",
        report={
            "what_i_did": ["Added run_report_v1"],
            "where_we_are": ["Brain stores report nodes"],
            "evidence": ["pytest passed"],
            "problems_risks": [],
            "whats_next": ["Surface in Cockpit"],
        },
    )

    report = cr.build_compliance_report(store, owner_user="founder")

    assert report["run_reports"]["cell_first"] is True
    assert report["run_reports"]["total"] == 0
    assert report["run_reports"]["reports"] == []
    assert "Run reports: 0" in report["markdown"]


def test_compliance_report_includes_legacy_runtime_holder_evidence(
    store, tmp_path, monkeypatch,
):
    runtime = tmp_path / "node_runtime"
    runtime.mkdir()
    monkeypatch.setattr(rh, "default_runtime_copy", lambda: runtime)
    monkeypatch.setattr(
        rh,
        "iter_processes",
        lambda: [
            rh.ProcessRecord(
                pid=42,
                name="python.exe",
                cwd=str(runtime),
                cmdline="python -m nodelang.application_server",
            )
        ],
    )

    report = cr.build_compliance_report(store, owner_user="founder")

    holders = report["legacy_runtime_holders"]
    assert holders["schema"] == "archhub-live-runtime-holders/v1"
    assert holders["holder_count"] == 1
    assert holders["archive_safe_now"] is False
    assert holders["holders"][0]["pid"] == 42
    assert "Legacy runtime holders: 1" in report["markdown"]


def test_compliance_event_append_persists_bounded_history(store):
    first = cr.append_compliance_event(
        store,
        owner_user="founder",
        event={
            "event_type": "write_gate_decision",
            "decision": "deny",
            "code": "missing_active_cde",
            "path": "10.PRODUCT/12.PRODUCTION/app/web_ui/studio-lm.jsx",
        },
    )

    assert first["ok"] is True
    assert first["total"] == 1
    assert first["event"]["event_type"] == "write_gate_decision"
    assert first["event"]["event_id"]
    assert first["event"]["recorded_at"]

    raw = json.loads(store.get_meta(cr.HISTORY_META_KEY))
    assert raw["owners"]["founder"]["events"][0]["code"] == "missing_active_cde"

    second = cr.append_compliance_event(
        store,
        owner_user="founder",
        event={"event_type": "hook_coverage_audit", "status": "green"},
    )
    history = cr.get_compliance_history(store, owner_user="founder", limit=1)

    assert second["total"] == 2
    assert history["ok"] is True
    assert history["total"] == 2
    assert len(history["events"]) == 1
    assert history["events"][0]["event_type"] == "hook_coverage_audit"


def test_server_registers_compliance_report_tool(store):
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}
    assert "brain.compliance_report" in names
    assert "brain.compliance_event_append_cell_first" in names
    res = mcp._tools["brain.compliance_report"].handler(owner_user="founder")
    assert res["ok"] is True
    assert "markdown" in res
    assert "legacy_runtime_holders" in res


def test_server_registers_compliance_history_tools(store):
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    tools = {t["name"]: t for t in mcp.list_tools()}
    names = set(tools)

    assert "brain.compliance_event_append" in names
    assert "brain.compliance_history_get" in names
    assert "RETIRED" in tools["brain.compliance_event_append"]["description"]
    assert (
        "brain.compliance_event_append_cell_first"
        in tools["brain.compliance_event_append"]["description"]
    )

    append = mcp._tools["brain.compliance_event_append"].handler(
        event={
            "event_type": "write_gate_decision",
            "decision": "allow",
            "code": "allowed",
        },
        owner_user="founder",
    )
    history = mcp._tools["brain.compliance_history_get"].handler(
        owner_user="founder",
        limit=10,
    )

    assert append["ok"] is False
    assert append["migration_only"] is True
    assert append["deprecated"] is True
    assert append["code"] == "legacy_governance_route_retired"
    assert append["brain_written"] is False
    assert (
        append["cell_first_alternative"]
        == "brain.compliance_event_append_cell_first"
    )
    assert history["total"] == 0
    assert history["events"] == []
    assert store.get_meta(cr.HISTORY_META_KEY) is None
