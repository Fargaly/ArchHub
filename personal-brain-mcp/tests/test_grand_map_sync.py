"""Grand Map to Brain active-work sync tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from personal_brain import active_work as aw  # noqa: E402
from personal_brain import compliance_report as cr  # noqa: E402
from personal_brain import grand_map_sync as gms  # noqa: E402
from personal_brain.meeting_room import room_say  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _write_map(
    tmp_path: Path,
    *,
    target_runtime: str = "10.PRODUCT/12.PRODUCTION",
) -> tuple[Path, Path]:
    grand_map = {
        "graph": {
            "nodes": [
                {"id": "brain_history", "title": "Compliance History", "status": "planned"},
                {"id": "ui_dashboard", "title": "Compliance Dashboard", "status": "planned"},
            ]
        }
    }
    overlay = {
        "target_runtime": target_runtime,
        "containers": {
            "brain_history": {
                "tier": "T1",
                "lifecycle_state": "WIP",
                "suitability_status": "S1",
                "revision": "P01",
                "owner": "agent",
                "checker": "court",
                "allowed_paths": [
                    f"{target_runtime}/personal-brain-mcp/"
                ],
                "gate_kind": "pytest",
                "gate_spec": {
                    "path": f"{target_runtime}/personal-brain-mcp/tests/test_compliance_report.py"
                },
                "evidence_ref": "",
            },
            "ui_dashboard": {
                "tier": "T1",
                "lifecycle_state": "WIP",
                "suitability_status": "S1",
                "revision": "P01",
                "owner": "agent",
                "checker": "court",
                "allowed_paths": [f"{target_runtime}/app/web_ui/"],
                "gate_kind": "cdp",
                "gate_spec": {"selector": "[data-compliance-dashboard]"},
                "evidence_ref": "",
            },
        }
    }
    grand_path = tmp_path / "grand.json"
    overlay_path = tmp_path / "overlay.json"
    grand_path.write_text(json.dumps(grand_map), encoding="utf-8")
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    return grand_path, overlay_path


def _room_plan(store: BrainStore, leaf_id: str) -> None:
    room_say(
        store,
        frm="grand-map-sync-court",
        kind="plan",
        refs=[leaf_id],
        text=f"Plan evidence for generated route {leaf_id}.",
    )


def test_sync_grand_map_adds_valid_cde_leaves_and_records_history(store, tmp_path):
    grand_path, overlay_path = _write_map(tmp_path)

    result = gms.sync_grand_map_work_leaves(
        store,
        grand_map_path=grand_path,
        overlay_path=overlay_path,
        owner_user="founder",
    )

    assert result["ok"] is True
    assert result["leaf_count"] == 2
    assert result["skipped_count"] == 0

    ledger = aw.get_ledger(store, owner_user="founder")
    assert ledger is not None
    assert len(ledger.leaves) == 2
    assert {
        leaf.cde_container["container_id"]
        for leaf in ledger.leaves.values()
    } == {"GM.brain.brain_history", "GM.ui.ui_dashboard"}

    history = cr.get_compliance_history(store, owner_user="founder", limit=5)
    assert history["events"][0]["event_type"] == "grand_map_work_sync"
    assert history["events"][0]["leaf_count"] == 2


def test_sync_grand_map_dry_run_does_not_mutate_ledger(store, tmp_path):
    grand_path, overlay_path = _write_map(tmp_path)

    result = gms.sync_grand_map_work_leaves(
        store,
        grand_map_path=grand_path,
        overlay_path=overlay_path,
        owner_user="founder",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert aw.get_ledger(store, owner_user="founder") is None


def test_preview_discovers_canonical_overlay_beside_grand_map_data(tmp_path):
    data_dir = tmp_path / "grand-map" / "data"
    data_dir.mkdir(parents=True)
    grand_path, written_overlay = _write_map(data_dir)
    canonical_overlay = data_dir.parent / "cde_overlay_node_native.json"
    written_overlay.replace(canonical_overlay)

    result = gms.preview_grand_map_work_leaves(grand_map_path=grand_path)

    assert result["ok"] is True
    assert result["resolved_overlay_path"] == str(canonical_overlay.resolve())
    assert result["target_runtime"] == "10.PRODUCT/12.PRODUCTION"
    assert result["leaf_count"] == 2


def test_canonical_node_native_ui_leaf_carries_declared_court_budget():
    workspace = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "00.GOVERNANCE").is_dir()
    )
    grand_path = workspace / "30.KNOWLEDGE" / "grand-map" / "data" / "grand_domains.json"
    overlay_path = workspace / "30.KNOWLEDGE" / "grand-map" / "cde_overlay_node_native.json"

    result = gms.preview_grand_map_work_leaves(
        grand_map_path=grand_path,
        overlay_path=overlay_path,
    )
    vellum = next(
        leaf
        for leaf in result["leaves"]
        if leaf["cde_container"]["node_id"] == "ui_theme_vellum"
    )

    assert result["ok"] is True
    assert vellum["gate_spec"]["timeout_s"] == 900
    assert vellum["gate_spec"]["command"] == (
        "python -m pytest tests_replica/test_node_native_application.py -q"
    )
    assert vellum["cde_container"]["gate_spec"] == vellum["gate_spec"]


def test_server_registers_grand_map_sync_tools(store, tmp_path):
    from personal_brain.server import build_server

    grand_path, overlay_path = _write_map(tmp_path)
    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}

    assert "brain.grand_map_work_preview" in names
    assert "brain.grand_map_work_sync" in names
    assert "brain.grand_map_work_preview_cell_first" in names
    assert "brain.grand_map_work_sync_cell_first" in names

    preview = mcp._tools["brain.grand_map_work_preview"].handler(
        grand_map_path=str(grand_path),
        overlay_path=str(overlay_path),
    )
    sync = mcp._tools["brain.grand_map_work_sync"].handler(
        grand_map_path=str(grand_path),
        overlay_path=str(overlay_path),
        owner_user="founder",
    )

    assert preview["ok"] is True
    assert preview["leaf_count"] == 2
    assert sync["ok"] is True
    assert aw.status(store, owner_user="founder")["total"] == 2


def test_cell_first_grand_map_tools_call_universal_runtime_without_brain_write(store):
    class _Bridge:
        def __init__(self):
            self.calls = []

        def grand_map_work_preview(self, *, limit, include_live):
            self.calls.append(("preview", limit, include_live))
            return {
                "ok": True,
                "schema": "archhub-universal-grand-map-work/v1",
                "items": [{"external_key": "grand-map:brain_history"}],
            }

        def grand_map_work_sync(self, *, limit, include_live):
            self.calls.append(("sync", limit, include_live))
            return {
                "ok": True,
                "created_count": 1,
                "created": [{"external_key": "grand-map:brain_history"}],
            }

    bridge = _Bridge()
    preview = gms.preview_grand_map_work_leaves_cell_first(
        bridge=bridge,
        limit=7,
        include_live=True,
    )
    sync = gms.sync_grand_map_work_leaves_cell_first(
        bridge=bridge,
        limit=3,
    )

    assert preview["schema"] == "archhub-universal-grand-map-work/v1"
    assert sync["created_count"] == 1
    assert bridge.calls == [
        ("preview", 7, True),
        ("sync", 3, False),
    ]
    assert aw.get_ledger(store, owner_user="founder") is None


def test_cell_first_grand_map_tools_fail_closed_when_runtime_unavailable(monkeypatch):
    class _Unavailable:
        def grand_map_work_preview(self, **_kwargs):
            raise RuntimeError("missing runtime descriptor")

    result = gms.preview_grand_map_work_leaves_cell_first(
        bridge=_Unavailable(),
        limit=1,
    )

    assert result["ok"] is False
    assert result["code"] == "universal_runtime_unavailable"
    assert "missing runtime descriptor" in result["error"]


def test_sync_repairs_open_generated_routes_without_touching_claimed_or_custom_leaves(
        store, tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_CELL_ROOM", "0")
    grand_path, current_overlay = _write_map(tmp_path)
    stale_overlay = tmp_path / "stale-overlay.json"
    stale = json.loads(current_overlay.read_text(encoding="utf-8"))
    stale["target_runtime"] = "10.PRODUCT/13.NODE-LANGUAGE"
    for container in stale["containers"].values():
        container["allowed_paths"] = [
            path.replace(
                "10.PRODUCT/12.PRODUCTION",
                "10.PRODUCT/13.NODE-LANGUAGE",
            )
            for path in container["allowed_paths"]
        ]
    stale_overlay.write_text(json.dumps(stale), encoding="utf-8")

    initial = gms.preview_grand_map_work_leaves(
        grand_map_path=grand_path,
        overlay_path=stale_overlay,
    )
    aw.add_leaves(store, owner_user="founder", leaves=initial["leaves"])
    generated = {
        leaf.cde_container["node_id"]: leaf
        for leaf in aw.get_ledger(store, owner_user="founder").leaves.values()
    }
    claimed = generated["brain_history"]
    _room_plan(store, claimed.leaf_id)
    aw.claim(
        store,
        leaf_id=claimed.leaf_id,
        agent_id="working-agent",
        runtime="codex",
        owner_user="founder",
    )
    aw.add_leaves(
        store,
        owner_user="founder",
        leaves=[{
            "title": "Founder custom visual hierarchy work",
            "gate_kind": "manual",
            "cde_container": {"container_id": "CUSTOM.visual-hierarchy"},
        }],
    )

    result = gms.sync_grand_map_work_leaves(
        store,
        grand_map_path=grand_path,
        overlay_path=current_overlay,
        owner_user="founder",
    )

    assert result["ok"] is True
    assert result["reconciliation"] == {
        "added": 0,
        "updated_open": 1,
        "preserved_in_flight": 1,
        "preserved_external": 1,
    }
    ledger = aw.get_ledger(store, owner_user="founder")
    repaired = next(
        leaf for leaf in ledger.leaves.values()
        if leaf.cde_container.get("node_id") == "ui_dashboard"
    )
    still_claimed = ledger.leaves[claimed.leaf_id]
    assert repaired.state == aw.LeafState.OPEN
    assert repaired.cde_container["allowed_paths"] == [
        "10.PRODUCT/12.PRODUCTION/app/web_ui/"
    ]
    assert still_claimed.state == aw.LeafState.CLAIMED
    assert still_claimed.claimed_by == "working-agent"
    assert still_claimed.cde_container["allowed_paths"] == [
        "10.PRODUCT/13.NODE-LANGUAGE/personal-brain-mcp/"
    ]
    assert any(
        leaf.title == "Founder custom visual hierarchy work"
        for leaf in ledger.leaves.values()
    )


def test_sync_rejects_routes_outside_declared_target_runtime(store, tmp_path):
    grand_path, overlay_path = _write_map(
        tmp_path,
        target_runtime="10.PRODUCT/12.PRODUCTION/node_runtime",
    )
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    overlay["containers"]["brain_history"]["allowed_paths"] = [
        "10.PRODUCT/12.PRODUCTION/personal-brain-mcp/"
    ]
    overlay["containers"]["brain_history"]["gate_spec"]["path"] = (
        "10.PRODUCT/12.PRODUCTION/personal-brain-mcp/tests/test_compliance_report.py"
    )
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

    result = gms.sync_grand_map_work_leaves(
        store,
        grand_map_path=grand_path,
        overlay_path=overlay_path,
        owner_user="founder",
    )

    assert result["ok"] is False
    assert result["code"] == "invalid_cde_routes"
    assert result["route_issues"]
    assert aw.get_ledger(store, owner_user="founder") is None
    history = cr.get_compliance_history(store, owner_user="founder", limit=1)
    assert history["events"][0]["event_type"] == "grand_map_work_sync_rejected"
