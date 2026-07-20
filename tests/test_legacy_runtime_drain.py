from __future__ import annotations

import json
import inspect
import subprocess
import sys
import types
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
BRAIN_SRC = Path(__file__).resolve().parent.parent / "personal-brain-mcp" / "src"
for path in (TOOLS, BRAIN_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import legacy_runtime_drain as drain  # noqa: E402
from personal_brain import active_work as aw  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


def _audit(holder_count: int, holders: list[dict] | None = None) -> dict:
    return {
        "schema": "archhub-live-runtime-holders/v1",
        "runtime_copy": "node_runtime",
        "exists": True,
        "holder_count": holder_count,
        "archive_safe_now": holder_count == 0,
        "required_action": "do not archive or move while holders exist",
        "holders": holders or [{"pid": 123}],
    }


def test_register_drain_leaf_writes_brain_active_work_without_claiming(tmp_path, monkeypatch):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    workspace = tmp_path
    (product_root / "node_runtime").mkdir(parents=True)
    brain_path = tmp_path / "brain.db"
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(1))

    result = drain.register_drain_leaf(
        product_root,
        workspace,
        "founder",
        tmp_path,
        "20260717-190100",
        brain_path,
    )

    store = BrainStore.open(brain_path)
    try:
        ledger = aw.get_ledger(store, owner_user="founder")
    finally:
        store.close()

    assert result["holder_count"] == 1
    assert result["archive_safe_now"] is False
    assert ledger is not None
    leaf = ledger.leaves[result["leaf_id"]]
    assert leaf.title == drain.TITLE
    assert leaf.state == aw.LeafState.OPEN
    assert leaf.governance_context["non_destructive"] is True
    assert Path(leaf.governance_context["drain_plan"]).exists()


def test_drain_plan_classifies_holders_without_permission_to_interrupt(tmp_path):
    holder_payload = {
        "holder_report": _audit(3, [
            {"pid": 1, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python -m pytest x.py -q"},
            {"pid": 2, "name": "pythonw.exe", "cwd": "node_runtime", "cmdline": "pythonw.exe run_application_server.py --port 8482"},
            {"pid": 3, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python.exe -"},
        ]),
    }

    plan = drain.build_drain_plan(tmp_path / "10.PRODUCT" / "12.PRODUCTION", tmp_path, holder_payload)

    assert plan["drain_complete"] is False
    assert plan["by_type"] == {
        "application_server": 1,
        "stdin_python": 1,
        "test_runner": 1,
    }
    assert all("kill" in item["forbidden_action"] for item in plan["holders"])


def test_runtime_args_duplicate_groups_and_authority_relaunch_are_visible(tmp_path):
    cmd = (
        "python -m nodelang.application_server --host 127.0.0.1 --port 8505 "
        "--cloud-host 127.0.0.1 --cloud-port 8506 "
        "--state-path C:\\Temp\\archhub-node-runtime-8505.json --fresh"
    )
    holder_payload = {
        "holder_report": _audit(2, [
            {"pid": 1, "name": "python.exe", "cwd": "node_runtime", "cmdline": cmd},
            {"pid": 2, "name": "python.exe", "cwd": "node_runtime", "cmdline": cmd},
        ]),
    }

    plan = drain.build_drain_plan(tmp_path / "10.PRODUCT" / "12.PRODUCTION", tmp_path, holder_payload)
    first = plan["holders"][0]

    assert first["runtime_args"]["port"] == 8505
    assert first["runtime_args"]["cloud_port"] == 8506
    assert first["authority_relaunch"] == {
        "cwd": str(tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"),
        "command": [
            "python", "-m", "nodelang.application_server",
            "--host", "127.0.0.1",
            "--port", "8505",
            "--cloud-host", "127.0.0.1",
            "--cloud-port", "8506",
            "--state-path", "C:\\Temp\\archhub-node-runtime-8505.json",
            "--fresh",
        ],
        "dry_run_only": True,
        "machine_transport": False,
        "note": (
            "Derived raw server relaunch command only; this planner does not "
            "execute it. This preserves parsed server flags but does not enable "
            "the Brain/Workshop machine transport."
        ),
    }
    assert first["desktop_authority_handoff"]["command"] == [
        "python", "-m", "nodelang.desktop",
    ]
    assert first["desktop_authority_handoff"]["machine_transport"] is True
    assert first["desktop_authority_handoff"]["status"] \
        == "not_exact_for_non_default_endpoint"
    assert first["desktop_authority_handoff"]["safe_to_execute_now"] is False
    assert plan["duplicate_server_groups"][0]["pids"] == [1, 2]
    assert plan["duplicate_server_groups"][0]["authority_relaunch"] == first["authority_relaunch"]
    assert plan["duplicate_server_groups"][0]["desktop_authority_handoff"] \
        == first["desktop_authority_handoff"]


def test_authority_replacement_status_marks_owned_and_shadow_ports(tmp_path, monkeypatch):
    cmd = (
        "python -m nodelang.application_server --port 8505 "
        "--cloud-port 8506 --state-path C:\\Temp\\archhub-node-runtime-8505.json"
    )
    holder_payload = {
        "holder_report": _audit(2, [
            {"pid": 10, "name": "python.exe", "cwd": "node_runtime", "cmdline": cmd},
            {"pid": 20, "name": "python.exe", "cwd": "node_runtime", "cmdline": cmd},
        ]),
    }
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {10}, 8506: {10}})

    plan = drain.build_drain_plan(tmp_path / "10.PRODUCT" / "12.PRODUCTION", tmp_path, holder_payload)

    assert plan["exact_authority_replacement"] == {
        "replacement_specs": 2,
        "blocked_exact_authority_launches": 2,
        "endpoint_owning_legacy_holders": 1,
        "shadow_legacy_holders": 1,
        "runnable_now": 0,
        "unknown": 0,
        "rule": "do not execute exact authority relaunch while its target ports are occupied",
    }
    assert plan["holders"][0]["authority_replacement_status"]["status"] == "blocked_by_this_live_holder"
    assert plan["holders"][1]["authority_replacement_status"]["status"] == "shadow_holder_without_endpoint"
    schedule = plan["handoff_schedule"]
    assert schedule["schema"] == "archhub-legacy-runtime-handoff-schedule/v1"
    assert schedule["all_steps_non_interrupting"] is True
    endpoint_steps = [
        step for step in schedule["steps"]
        if step["kind"] == "coordinate_duplicate_endpoint_handoff"
    ]
    assert endpoint_steps == [{
        "sequence": 1,
        "kind": "coordinate_duplicate_endpoint_handoff",
        "port": 8505,
        "cloud_port": 8506,
        "state_path": "C:\\Temp\\archhub-node-runtime-8505.json",
        "endpoint_owner_pids": [10],
        "shadow_pids": [20],
        "authority_relaunch": plan["holders"][0]["authority_relaunch"],
        "desktop_authority_handoff": plan["holders"][0]["desktop_authority_handoff"],
        "required_action": (
            "choose a handoff window for the endpoint owner, then relaunch "
            "the same endpoint from the Universal Cell authority; inspect "
            "shadow holders separately before cleanup"
        ),
        "may_interrupt": False,
    }]
    assert schedule["steps"][-1]["kind"] == "verify_drain_complete"


def test_default_visible_runtime_handoff_is_blocked_until_proven(tmp_path):
    state_path = Path.home() / "AppData" / "Local" / "ArchHub" / "node-native-wip.json.gz"
    holder_payload = {
        "holder_report": _audit(1, [{
            "pid": 10,
            "name": "pythonw.exe",
            "cwd": "node_runtime",
            "cmdline": (
                "pythonw.exe run_application_server.py --host 127.0.0.1 "
                "--port 8482 --cloud-host 127.0.0.1 --cloud-port 8484 "
                f"--state-path {state_path}"
            ),
        }]),
    }

    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        holder_payload,
    )
    handoff = plan["holders"][0]["desktop_authority_handoff"]
    bridge = plan["authority_bridge_launch"]

    assert handoff["status"] == "blocked_until_visible_authority_handoff"
    assert handoff["command"] == ["python", "-m", "nodelang.desktop"]
    assert handoff["machine_transport"] is True
    assert handoff["safe_to_execute_now"] is False
    assert handoff["requires_endpoint_free"] is True
    assert handoff["requires_machine_descriptor_free"] is True
    assert handoff["requires_browser_session_handoff"] is True
    assert handoff["visible_url"] == "http://127.0.0.1:8482"
    assert bridge["command"] == [
        "python", "-m", "nodelang.authority_bridge", "--standalone-owner",
    ]
    assert bridge["machine_transport"] is True
    assert bridge["safe_to_execute_now"] is False
    assert bridge["requires_exclusive_universal_state"] is True
    assert bridge["requires_founder_approved_handoff"] is True
    assert bridge["live_default_state_owner_pids"] == [10]
    assert bridge["window_style"] == "hidden"


def test_handoff_schedule_puts_tests_and_unknowns_before_endpoint_handoffs(tmp_path, monkeypatch):
    holder_payload = {
        "holder_report": _audit(4, [
            {"pid": 1, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python -m pytest x.py -q"},
            {"pid": 2, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python.exe -"},
            {"pid": 3, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python -m nodelang.application_server --port 8505"},
            {"pid": 4, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python -m nodelang.application_server --port 8506"},
        ]),
    }
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {3}, 8506: {4}})

    plan = drain.build_drain_plan(tmp_path / "10.PRODUCT" / "12.PRODUCTION", tmp_path, holder_payload)
    steps = plan["handoff_schedule"]["steps"]

    assert [step["kind"] for step in steps] == [
        "passive_wait",
        "inspect_unknown_holder",
        "coordinate_single_endpoint_handoff",
        "coordinate_single_endpoint_handoff",
        "verify_drain_complete",
    ]
    assert steps[0]["pids"] == [1]
    assert steps[1]["pids"] == [2]
    assert {steps[2]["pid"], steps[3]["pid"]} == {3, 4}


def test_handoff_board_is_compact_read_only_evidence(tmp_path, monkeypatch):
    holder_payload = {
        "holder_report": _audit(3, [
            {
                "pid": 1,
                "name": "python.exe",
                "cwd": "node_runtime",
                "cmdline": "python -m pytest x.py -q",
                "age_seconds": 3700.0,
                "status": "running",
                "cpu_total_seconds": 5.0,
            },
            {"pid": 2, "name": "python.exe", "cwd": "node_runtime", "cmdline": "python.exe -"},
            {
                "pid": 3,
                "name": "python.exe",
                "cwd": "node_runtime",
                "cmdline": "python -m nodelang.application_server --port 8505 --state-path C:\\Temp\\state.json",
                "age_seconds": 42.0,
                "status": "sleeping",
                "cpu_total_seconds": 0.5,
            },
        ]),
    }
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {3}})

    plan = drain.build_drain_plan(tmp_path / "10.PRODUCT" / "12.PRODUCTION", tmp_path, holder_payload)
    board = plan["handoff_board"]

    assert board["schema"] == "archhub-runtime-handoff-board/v1"
    assert board["archive_allowed"] is False
    assert board["summary"] == {
        "holders": 3,
        "application_servers": 1,
        "blocked_endpoints": 1,
        "runnable_endpoints": 0,
        "unknown_endpoints": 0,
        "passive_wait_pids": 1,
        "long_running_test_pids": 1,
        "low_activity_test_pids": 1,
        "inspect_pids": 1,
        "handoff_steps": 4,
        "replacement_specs": 1,
        "source_drift_count": 0,
    }
    assert board["blockers"] == {
        "source_drift": {
            "ok": True,
            "drift_count": 0,
            "missing_in_authority": 0,
            "different_from_authority": 0,
        },
        "passive_wait_pids": [1],
        "long_running_test_pids": [1],
        "low_activity_test_pids": [1],
        "inspect_before_touch_pids": [2],
        "blocked_endpoint_pids": [3],
    }
    assert board["endpoint_cards"] == [{
        "pid": 3,
        "status": "blocked_by_this_live_holder",
        "ports": [8505],
        "port_owners": {"8505": [3]},
        "co_owner_pids": [],
        "non_holder_port_owner_pids": [],
        "state_path": "C:\\Temp\\state.json",
        "age_seconds": 42.0,
        "process_status": "sleeping",
        "cpu_total_seconds": 0.5,
        "holder_risk_class": "unclassified_copied_runtime_holder",
        "drain_posture": "inspect manually before any drain decision",
        "script_evidence": {
            "launch_mode": "python_module",
            "module": "nodelang.application_server",
            "stdin_mode": False,
            "script_path": None,
            "script_exists": False,
            "script_size_bytes": None,
            "script_mtime_utc": None,
            "script_sha256": None,
        },
        "authority_relaunch": plan["holders"][2]["authority_relaunch"],
        "desktop_authority_handoff": plan["holders"][2]["desktop_authority_handoff"],
        "allowed_action": plan["holders"][2]["allowed_action"],
        "forbidden_action": plan["holders"][2]["forbidden_action"],
    }]
    assert "read-only evidence" in board["rule"]


def test_drain_plan_exposes_holder_risk_and_script_evidence(tmp_path):
    holder_payload = {
        "holder_report": _audit(3, [
            {
                "pid": 1,
                "name": "pythonw.exe",
                "cwd": "node_runtime",
                "cmdline": (
                    "pythonw.exe run_application_server.py --port 8482 "
                    "--cloud-port 8484"
                ),
            },
            {
                "pid": 2,
                "name": "python.exe",
                "cwd": "node_runtime",
                "cmdline": (
                    "python C:\\Users\\fargaly\\AppData\\Local\\Temp\\"
                    "archhub_nary_qa_server.py"
                ),
            },
            {
                "pid": 3,
                "name": "python.exe",
                "cwd": "node_runtime",
                "cmdline": "python.exe -",
            },
        ]),
    }

    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        holder_payload,
    )

    by_pid = {holder["pid"]: holder for holder in plan["holders"]}
    assert by_pid[1]["holder_risk_class"] == "visible_legacy_endpoint"
    assert by_pid[2]["holder_risk_class"] == "qa_server_script_missing"
    assert by_pid[2]["script_evidence"]["script_exists"] is False
    assert by_pid[3]["holder_risk_class"] == "stdin_python_holder"
    assert plan["handoff_board"]["risk_classes"] == {
        "qa_server_script_missing": 1,
        "stdin_python_holder": 1,
        "visible_legacy_endpoint": 1,
    }
    assert [card["pid"] for card in plan["handoff_board"]["inspect_cards"]] == [2, 3]


def test_handoff_board_exposes_non_holder_port_coowners(tmp_path, monkeypatch):
    holder_payload = {
        "holder_report": _audit(1, [{
            "pid": 3,
            "name": "python.exe",
            "cwd": "node_runtime",
            "cmdline": "python -m nodelang.application_server --port 8505 --cloud-port 8506",
        }]),
    }
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {
        8505: {3},
        8506: {3, 99, 100},
    })

    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        holder_payload,
    )
    card = plan["handoff_board"]["endpoint_cards"][0]

    assert card["port_owners"] == {"8505": [3], "8506": [3, 99, 100]}
    assert card["co_owner_pids"] == [99, 100]
    assert card["non_holder_port_owner_pids"] == [99, 100]


def test_handoff_board_blocks_archive_when_runtime_source_drift_exists(tmp_path):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "only.py").write_text("# runtime only\n", encoding="utf-8")
    plan = drain.build_drain_plan(
        product_root,
        tmp_path,
        {"holder_report": _audit(0, [])},
    )

    board = plan["handoff_board"]

    assert board["archive_allowed"] is False
    assert board["summary"]["source_drift_count"] == 1
    assert board["blockers"]["source_drift"] == {
        "ok": False,
        "drift_count": 1,
        "missing_in_authority": 1,
        "different_from_authority": 0,
    }


def test_disposable_holder_court_allows_only_missing_temp_qa_without_clients():
    board = {
        "blockers": {
            "inspect_before_touch_pids": [21, 30, 99],
            "blocked_endpoint_pids": [10],
        },
        "endpoint_cards": [{
            "pid": 10,
            "co_owner_pids": [99],
            "non_holder_port_owner_pids": [99],
        }],
    }
    inspection = {
        "schema": "archhub-live-runtime-pid-inspection/v1",
        "available": True,
        "processes": [
            {
                "pid": 21,
                "exists": True,
                "process_risk_class": "qa_server_script_missing",
                "script_path": (
                    "C:\\Users\\fargaly\\AppData\\Local\\Temp\\"
                    "archhub_nary_qa_server.py"
                ),
                "script_exists": False,
                "child_pids": [6084],
                "listening_ports": [8515, 8516],
                "established_connection_count": 0,
                "endpoint_fingerprints": [{
                    "port": 8515,
                    "path": "/",
                    "ok": True,
                    "status": 200,
                }],
            },
            {
                "pid": 6084,
                "exists": True,
                "name": "conhost.exe",
                "cmdline": "\\??\\C:\\Windows\\system32\\conhost.exe 0x4",
                "process_risk_class": "unclassified_process_holder",
                "script_path": "",
                "script_exists": False,
                "child_pids": [],
                "listening_ports": [],
                "established_connection_count": 0,
                "endpoint_fingerprints": [],
            },
            {
                "pid": 30,
                "exists": True,
                "process_risk_class": "stdin_python_listener_child",
                "script_path": "",
                "script_exists": False,
                "child_pids": [],
                "listening_ports": [52780],
                "established_connection_count": 0,
                "endpoint_fingerprints": [],
            },
            {
                "pid": 99,
                "exists": True,
                "process_risk_class": "qa_server_script_missing",
                "script_path": "C:\\Temp\\archhub_nary_qa_server.py",
                "script_exists": False,
                "child_pids": [],
                "listening_ports": [8515],
                "established_connection_count": 0,
                "endpoint_fingerprints": [{
                    "port": 8515,
                    "path": "/",
                    "ok": True,
                    "status": 200,
                }],
            },
        ],
    }

    court = drain.build_disposable_holder_court(board, inspection)

    assert court["schema"] == "archhub-disposable-runtime-holder-court/v1"
    assert court["cleanup_allowed_pids"] == [21]
    assert court["blocked_pids"] == [30, 99]
    by_pid = {row["pid"]: row for row in court["rows"]}
    assert by_pid[21]["verdict"] == "disposable_cleanup_allowed"
    assert by_pid[21]["checks"]["known_disposable_shape"] is True
    assert by_pid[21]["checks"]["no_child_dependency"] is True
    assert by_pid[30]["checks"]["known_disposable_shape"] is False
    assert "known_disposable_shape" in by_pid[30]["failed_checks"]
    assert by_pid[99]["checks"]["not_protected_endpoint_or_coowner"] is False
    assert "not_protected_endpoint_or_coowner" in by_pid[99]["failed_checks"]
    assert "does not stop" in by_pid[21]["rule"]


def test_disposable_holder_court_blocks_when_inspection_unavailable():
    court = drain.build_disposable_holder_court(
        {"blockers": {"inspect_before_touch_pids": [21]}},
        {"available": False, "reason": "psutil unavailable"},
    )

    assert court["available"] is False
    assert court["cleanup_allowed_pids"] == []
    assert court["reason"] == "psutil unavailable"


def test_authority_launch_readiness_requires_importable_cli_with_handoff_flags(tmp_path, monkeypatch):
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    (authority / "nodelang").mkdir(parents=True)
    (authority / "nodelang" / "application_server.py").write_text("# app server\n", encoding="utf-8")
    (authority / "nodelang" / "authority_bridge.py").write_text("# bridge\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        assert kwargs["cwd"] == str(authority)
        if command[-2:] == ["nodelang.application_server", "--help"]:
            stdout = (
                "--host --port --cloud-host --cloud-port --state-path --fresh "
                "--universal-state-path --universal-checkpoint-path "
                "--universal-checkpoint-authority-path"
            )
        elif command[-2:] == ["nodelang.authority_bridge", "--help"]:
            stdout = (
                "--state-path --descriptor-path --status-path --probe "
                "--standalone-owner"
            )
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(drain.subprocess, "run", fake_run)

    readiness = drain.authority_launch_readiness(authority)

    assert readiness["ok"] is True
    assert readiness["missing_flags"] == []
    assert readiness["bridge_missing_flags"] == []
    assert readiness["bridge_module_exists"] is True
    assert "importable" in readiness["reason"]


def test_authority_launch_readiness_is_red_when_module_missing(tmp_path):
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"

    readiness = drain.authority_launch_readiness(authority)

    assert readiness["ok"] is False
    assert readiness["module_exists"] is False
    assert readiness["missing_flags"]


def test_authority_launch_readiness_is_red_when_bridge_module_missing(
    tmp_path,
):
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    (authority / "nodelang").mkdir(parents=True)
    (authority / "nodelang" / "application_server.py").write_text(
        "# app server\n", encoding="utf-8"
    )

    readiness = drain.authority_launch_readiness(authority)

    assert readiness["ok"] is False
    assert readiness["module_exists"] is True
    assert readiness["bridge_module_exists"] is False
    assert readiness["reason"] == "authority bridge module is missing"


def test_authority_shadow_launch_probe_uses_bootstrap_state_and_health(tmp_path, monkeypatch):
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    (authority / "nodelang").mkdir(parents=True)
    (authority / "nodelang" / "application_server.py").write_text("# app server\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        script = command[-1]
        assert kwargs["cwd"] == str(authority)
        assert "server.bootstrap_url" in script
        assert '"/api/state"' in script
        assert '"/api/universal/health"' in script
        assert "enable_machine_transport=True" in script
        assert "UniversalRuntimeClient" in script
        assert '"/api/universal/work"' in script
        assert "HTTPCookieProcessor" in script
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "ok": True,
                "bootstrap_status": 200,
                "state_status": 200,
                "health_status": 200,
                "state_valid": True,
                "health_ok": True,
                "machine_transport_descriptor": True,
                "machine_work_application": "app:application",
                "machine_work_registry": "app:work:registry",
                "machine_work_items": 0,
                "csrf_meta_present": True,
                "session_cookie_http_only": True,
            }),
            stderr="",
        )

    monkeypatch.setattr(drain.subprocess, "run", fake_run)

    probe = drain.authority_shadow_launch_probe(authority)

    assert probe["ok"] is True
    assert probe["ran"] is True
    assert "temporary ports" in probe["reason"]
    assert "machine work transport" in probe["reason"]


def test_active_authority_runtime_bridge_reports_stopped_descriptor(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    descriptor = home / "AppData" / "Local" / "ArchHub" / "active-universal-runtime.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(json.dumps({
        "status": "stopped",
        "process_id": 88884,
        "runtime_id": "stale-runtime",
        "database": str(tmp_path / "dead.sqlite3"),
    }), encoding="utf-8")
    monkeypatch.setattr(drain.Path, "home", staticmethod(lambda: home))

    result = drain.active_authority_runtime_bridge_status(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
    )

    assert result["ok"] is False
    assert result["descriptor_exists"] is True
    assert result["descriptor_status"] == "stopped"
    assert result["descriptor_process_id"] == 88884
    assert result["descriptor_runtime_id"] == "stale-runtime"
    assert result["reason"] == "active Universal runtime descriptor is not active"


def test_active_authority_runtime_bridge_prefers_compact_work_index(
    tmp_path,
    monkeypatch,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    source = product_root / "personal-brain-mcp" / "src"
    source.mkdir(parents=True)
    home = tmp_path / "home"
    descriptor = home / "AppData" / "Local" / "ArchHub" / "active-universal-runtime.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(json.dumps({
        "status": "active",
        "process_id": 777,
        "runtime_id": "runtime-compact",
        "database": str(tmp_path / "live.sqlite3"),
    }), encoding="utf-8")
    monkeypatch.setattr(drain.Path, "home", staticmethod(lambda: home))
    calls = {}

    class FakeBridge:
        def work_index(self, *, response_timeout_seconds=None):
            calls["work_index_timeout"] = response_timeout_seconds
            return {
                "revision": 42,
                "application": "app:archhub",
                "registry": "app:governed-work-registry",
                "brain_scope": "gm:domain:brain",
                "items": [{"root": "work:one"}],
            }

        def work_list(self):
            raise AssertionError("full work_list must not be used for bridge health")

        def browser_handoff_status(self, *, response_timeout_seconds=None):
            calls["browser_handoff_timeout"] = response_timeout_seconds
            return {
                "application": "app:archhub",
                "supported": True,
                "one_use_route": "POST /api/universal/browser-handoff",
                "server_url": "http://127.0.0.1:61663",
                "revision": 43,
            }

    fake_module = types.SimpleNamespace(UniversalRuntimeBridge=FakeBridge)
    monkeypatch.setitem(
        sys.modules,
        "personal_brain.universal_runtime",
        fake_module,
    )

    result = drain.active_authority_runtime_bridge_status(
        product_root,
        tmp_path,
    )

    assert result["ok"] is True
    assert result["revision"] == 42
    assert result["items"] == 1
    assert result["machine_work_index_ok"] is True
    assert result["visible_browser_handoff_ok"] is True
    assert calls == {
        "work_index_timeout": drain.ACTIVE_AUTHORITY_RUNTIME_RESPONSE_TIMEOUT_SECONDS,
        "browser_handoff_timeout": drain.ACTIVE_AUTHORITY_RUNTIME_RESPONSE_TIMEOUT_SECONDS,
    }
    assert "visible browser handoff readiness" in result["reason"]


def test_active_authority_runtime_bridge_reports_missing_browser_handoff(
    tmp_path,
    monkeypatch,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    source = product_root / "personal-brain-mcp" / "src"
    source.mkdir(parents=True)
    home = tmp_path / "home"
    descriptor = home / "AppData" / "Local" / "ArchHub" / "active-universal-runtime.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(json.dumps({
        "status": "active",
        "process_id": 777,
        "runtime_id": "runtime-compact",
        "database": str(tmp_path / "live.sqlite3"),
    }), encoding="utf-8")
    monkeypatch.setattr(drain.Path, "home", staticmethod(lambda: home))

    class FakeBridge:
        def work_index(self):
            return {
                "revision": 42,
                "application": "app:archhub",
                "registry": "app:governed-work-registry",
                "brain_scope": "gm:domain:brain",
                "items": [{"root": "work:one"}],
            }

        def browser_handoff_status(self):
            raise RuntimeError("machine route is not admitted")

    fake_module = types.SimpleNamespace(UniversalRuntimeBridge=FakeBridge)
    monkeypatch.setitem(
        sys.modules,
        "personal_brain.universal_runtime",
        fake_module,
    )

    result = drain.active_authority_runtime_bridge_status(
        product_root,
        tmp_path,
    )

    assert result["ok"] is False
    assert result["machine_work_index_ok"] is True
    assert result["visible_browser_handoff_ok"] is False
    assert result["visible_browser_handoff"]["error"] == (
        "machine route is not admitted"
    )
    assert "handoff is not proven" in result["reason"]


def test_runtime_copy_source_drift_detects_missing_and_different_source(tmp_path):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    (runtime / "nodelang").mkdir(parents=True)
    (runtime / "tests_replica").mkdir(parents=True)
    (runtime / "public_site" / "dist").mkdir(parents=True)
    (runtime / "nodelang" / "__pycache__").mkdir(parents=True)
    (authority / "nodelang").mkdir(parents=True)

    (runtime / "nodelang" / "same.py").write_text("same\n", encoding="utf-8")
    (authority / "nodelang" / "same.py").write_text("same\n", encoding="utf-8")
    (runtime / "nodelang" / "authority_bridge.py").write_text(
        "runtime\n", encoding="utf-8"
    )
    (authority / "nodelang" / "authority_bridge.py").write_text(
        "authority\n", encoding="utf-8"
    )
    (runtime / "tests_replica" / "test_canvas_interaction_quality.py").write_text(
        "new\n", encoding="utf-8"
    )
    (runtime / "public_site" / "dist" / "bundle.js").write_text(
        "generated\n", encoding="utf-8"
    )
    (runtime / "nodelang" / "__pycache__" / "cached.pyc").write_bytes(b"cache")

    result = drain.runtime_copy_source_drift(product_root, authority)

    assert result["schema"] == "archhub-runtime-copy-source-drift/v1"
    assert result["ok"] is False
    assert result["checked_runtime_files"] == 3
    assert result["drift_count"] == 2
    assert result["migration_candidate_count"] == 2
    assert result["decision_summary"] == {
        "schema": "archhub-runtime-source-drift-decision-summary/v1",
        "candidate_count": 2,
        "all_classified": True,
        "unmapped_paths": [],
        "by_track": {
            "runtime_transport_and_broker": 1,
            "visual_workspace_interaction": 1,
        },
        "by_kind": {
            "court_candidate": 1,
            "implementation_candidate": 1,
        },
        "by_resolution_state": {
            "classified_unresolved": 2,
        },
        "promotion_allowed": False,
        "bulk_copy_allowed": False,
    }
    assert [row["path"] for row in result["different_from_authority"]] == [
        "nodelang/authority_bridge.py"
    ]
    assert [row["path"] for row in result["missing_in_authority"]] == [
        "tests_replica/test_canvas_interaction_quality.py"
    ]
    candidates = {
        row["path"]: row
        for row in result["migration_candidates"]
    }
    assert candidates["tests_replica/test_canvas_interaction_quality.py"]["status"] == (
        "missing_in_authority"
    )
    assert candidates["nodelang/authority_bridge.py"]["status"] == (
        "different_from_authority"
    )
    assert candidates["tests_replica/test_canvas_interaction_quality.py"][
        "candidate_kind"
    ] == "court_candidate"
    assert candidates["tests_replica/test_canvas_interaction_quality.py"][
        "migration_track"
    ] == (
        "visual_workspace_interaction"
    )
    assert candidates["nodelang/authority_bridge.py"]["migration_track"] == (
        "runtime_transport_and_broker"
    )
    assert candidates["nodelang/authority_bridge.py"]["authority_disposition"] == (
        "migration_evidence_not_authority"
    )
    assert candidates["nodelang/authority_bridge.py"]["promotion_allowed"] is False
    assert candidates["nodelang/authority_bridge.py"]["bulk_copy_allowed"] is False
    assert candidates["nodelang/authority_bridge.py"]["authority_sha256"]
    assert all(row["candidate_id"].startswith("runtime-source-drift:") for row in candidates.values())
    assert all("bulk-copy" in row["forbidden_action"] for row in candidates.values())
    assert all("bundle.js" not in json.dumps(row) for row in result["missing_in_authority"])


def test_runtime_copy_source_drift_is_green_when_runtime_matches_authority(tmp_path):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "universal_application.py").write_text("# same\n", encoding="utf-8")
    (authority / "universal_application.py").write_text("# same\n", encoding="utf-8")

    result = drain.runtime_copy_source_drift(product_root, authority.parent)

    assert result["ok"] is True
    assert result["drift_count"] == 0
    assert result["migration_candidate_count"] == 0
    assert result["decision_summary"]["all_classified"] is True
    assert result["decision_summary"]["candidate_count"] == 0
    assert result["missing_in_authority"] == []
    assert result["different_from_authority"] == []
    assert result["migration_candidates"] == []


def test_known_runtime_source_drift_paths_are_classified_not_promotable():
    paths = [
        "nodelang/cell_baboom_activity.py",
        "tests_replica/test_application_boundary_ports.py",
        "tests_replica/test_canvas_interaction_quality.py",
        "tests_replica/test_canvas_visual_grammar.py",
        "tests_replica/test_cell_baboom_activity.py",
        "tests_replica/test_playable_interaction.py",
        "tests_replica/test_projection_delta.py",
        "tests_replica/test_relation_junction_visual_grammar.py",
        "tests_replica/test_relation_security.py",
        "tests_replica/test_relation_topology_editor.py",
        "tests_replica/test_store_concurrency.py",
        "tests_replica/test_universal_cell_capabilities.py",
        "tests_replica/test_visual_graph_workspace.py",
        "tests_replica/test_visual_node_authority.py",
        "nodelang/application_server.py",
        "nodelang/authority_bridge.py",
        "nodelang/capabilities.py",
        "nodelang/cell_baboom_connector_execution.py",
        "nodelang/cell_baboom_model_execution.py",
        "nodelang/universal_application.py",
        "nodelang/universal_cloud_gateway.py",
        "public_site/README.md",
        "public_site/build.mjs",
        "tests_replica/test_application_machine_transport.py",
        "tests_replica/test_application_server_governance.py",
        "tests_replica/test_universal_application.py",
        "tests_replica/test_universal_baboom_cognition_planner.py",
        "tests_replica/test_universal_cloud_gateway.py",
        "tests_replica/test_universal_work_completion_court.py",
    ]

    rows = [drain.classify_source_drift_candidate(path) for path in paths]

    assert all(row["migration_track"] != "unmapped_runtime_candidate" for row in rows)
    assert all(row["authority_disposition"] == "migration_evidence_not_authority" for row in rows)
    assert all(row["promotion_allowed"] is False for row in rows)
    assert all(row["bulk_copy_allowed"] is False for row in rows)
    assert {
        "application_graph_projection",
        "baboom_context_and_cognition",
        "governed_work_lifecycle",
        "public_site_projection",
        "revision_integrity_court",
        "runtime_transport_and_broker",
        "visual_workspace_interaction",
    }.issubset({row["migration_track"] for row in rows})


def test_source_drift_migration_work_groups_candidates_by_authority_track(tmp_path):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    source_drift = {
        "schema": "archhub-runtime-copy-source-drift/v1",
        "migration_candidate_count": 3,
        "decision_summary": {"all_classified": True},
        "migration_candidates": [
            {
                "candidate_id": "runtime-source-drift:a",
                "path": "nodelang/authority_bridge.py",
                "candidate_kind": "implementation_candidate",
                "migration_track": "runtime_transport_and_broker",
                "required_canonical_first_step": "broker court first",
            },
            {
                "candidate_id": "runtime-source-drift:b",
                "path": "tests_replica/test_canvas_interaction_quality.py",
                "candidate_kind": "court_candidate",
                "migration_track": "visual_workspace_interaction",
                "required_canonical_first_step": "visual court first",
            },
            {
                "candidate_id": "runtime-source-drift:c",
                "path": "tests_replica/test_visual_graph_workspace.py",
                "candidate_kind": "court_candidate",
                "migration_track": "visual_workspace_interaction",
                "required_canonical_first_step": "visual court first",
            },
        ],
    }

    result = drain.build_source_drift_migration_work(
        source_drift,
        product_root=product_root,
        workspace=tmp_path,
    )

    assert result["schema"] == "archhub-runtime-source-drift-migration-work/v1"
    assert result["candidate_count"] == 3
    assert result["track_count"] == 2
    assert result["unresolved_track_count"] == 2
    assert result["all_candidates_classified"] is True
    assert result["all_work_authority_scoped"] is True
    assert result["all_non_promoting"] is True
    assert result["all_bulk_copy_forbidden"] is True
    assert result["all_non_interrupting"] is True
    by_track = {item["migration_track"]: item for item in result["work_items"]}
    assert by_track["runtime_transport_and_broker"]["implementation_candidate_paths"] == [
        "nodelang/authority_bridge.py"
    ]
    assert by_track["runtime_transport_and_broker"]["court_candidate_paths"] == []
    assert by_track["visual_workspace_interaction"]["court_candidate_paths"] == [
        "tests_replica/test_canvas_interaction_quality.py",
        "tests_replica/test_visual_graph_workspace.py",
    ]
    assert by_track["visual_workspace_interaction"]["promotion_allowed"] is False
    assert by_track["visual_workspace_interaction"]["bulk_copy_allowed"] is False
    assert by_track["visual_workspace_interaction"]["live_process_interruption_allowed"] is False
    assert by_track["visual_workspace_interaction"]["cde_container"] == {
        "container_id": "10.PRODUCT/13.NODE-LANGUAGE",
        "authority": "10.PRODUCT/13.NODE-LANGUAGE",
        "lifecycle": "WIP",
        "privacy_tier": "T0 PUBLIC",
    }


def test_retirement_gate_blocks_archive_until_all_conditions_are_green():
    holder_report = _audit(1)
    readiness = {"ok": True}
    shadow = {"ok": True}
    active_bridge = {"ok": True}
    replacement = {"blocked_exact_authority_launches": 0}
    schedule = {"all_steps_non_interrupting": True}

    gate = drain.build_retirement_gate(
        holder_report, readiness, shadow, active_bridge, replacement, schedule
    )

    assert gate["archive_allowed"] is False
    assert gate["failures"] == ["no_live_holders"]
    assert "do not archive" in gate["required_action"]


def test_retirement_gate_blocks_when_shadow_probe_was_not_run(tmp_path):
    holder_report = _audit(0, [])
    readiness = {"ok": True}
    shadow = drain.authority_shadow_launch_probe_not_run(
        tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    )
    active_bridge = {"ok": True}
    replacement = {"blocked_exact_authority_launches": 0}
    schedule = {"all_steps_non_interrupting": True}

    gate = drain.build_retirement_gate(
        holder_report, readiness, shadow, active_bridge, replacement, schedule
    )

    assert gate["archive_allowed"] is False
    assert gate["failures"] == ["authority_shadow_launch_proven"]


def test_retirement_gate_blocks_when_ignored_runtime_source_drift_exists():
    gate = drain.build_retirement_gate(
        _audit(0, []),
        {"ok": True},
        {"ok": True},
        {"ok": True},
        {"blocked_exact_authority_launches": 0},
        {"all_steps_non_interrupting": True},
        {"ok": False, "drift_count": 1},
    )

    assert gate["archive_allowed"] is False
    assert gate["checks"]["runtime_copy_source_drift_clear"] is False
    assert gate["failures"] == ["runtime_copy_source_drift_clear"]


def test_retirement_gate_allows_archive_only_after_drain_and_ready_authority():
    holder_report = _audit(0, [])
    readiness = {"ok": True}
    shadow = {"ok": True}
    active_bridge = {"ok": True}
    replacement = {"blocked_exact_authority_launches": 0}
    schedule = {"all_steps_non_interrupting": True}

    gate = drain.build_retirement_gate(
        holder_report, readiness, shadow, active_bridge, replacement, schedule
    )

    assert gate == {
        "schema": "archhub-runtime-copy-retirement-gate/v1",
        "archive_allowed": True,
        "checks": {
            "runtime_copy_exists": True,
            "runtime_copy_source_drift_clear": True,
            "authority_launch_ready": True,
            "authority_shadow_launch_proven": True,
            "active_authority_runtime_bridge": True,
            "no_live_holders": True,
            "no_blocked_exact_replacements": True,
            "handoff_schedule_non_interrupting": True,
        },
        "failures": [],
        "required_action": (
            "archive copied node_runtime through governed archive procedure; "
            "rerun WIP classifier and focused courts afterward"
        ),
    }


def test_cli_enforce_drained_returns_red_when_holder_remains(tmp_path, monkeypatch, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    brain_path = tmp_path / "brain.db"
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 123, "cmdline": "python -m pytest x.py -q"}]),
    )

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(tmp_path),
        "--brain-path", str(brain_path),
        "--timestamp", "20260717-191500",
        "--enforce-drained",
    ])

    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["holder_count"] == 1
    assert out["archive_safe_now"] is False


def test_cli_no_write_prints_plan_without_files_or_brain(tmp_path, monkeypatch, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    out_dir = tmp_path / "must-not-exist"
    brain_path = tmp_path / "brain.db"
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 123, "cmdline": "python -m nodelang.application_server --port 8505"}]),
    )

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--brain-path", str(brain_path),
        "--no-write",
        "--enforce-drained",
    ])

    assert code == 2
    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == "archhub-legacy-runtime-drain-plan/v1"
    assert plan["holder_count"] == 1
    assert plan["holders"][0]["authority_relaunch"]["cwd"] == str(
        tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE"
    )
    assert not out_dir.exists()
    assert not brain_path.exists()


def test_cli_handoff_board_prints_only_board_without_files_or_brain(tmp_path, monkeypatch, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    out_dir = tmp_path / "must-not-exist"
    brain_path = tmp_path / "brain.db"
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 123, "cmdline": "python -m nodelang.application_server --port 8505"}]),
    )
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {123}})

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--brain-path", str(brain_path),
        "--handoff-board",
    ])

    assert code == 0
    board = json.loads(capsys.readouterr().out)
    assert board["schema"] == "archhub-runtime-handoff-board/v1"
    assert "endpoint_cards" in board
    assert "holders" not in board
    assert board["blockers"]["blocked_endpoint_pids"] == [123]
    assert not out_dir.exists()
    assert not brain_path.exists()


def test_cli_handoff_board_enforce_retirement_gate_returns_red_when_blocked(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 123, "cmdline": "python -m nodelang.application_server --port 8505"}]),
    )
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {123}})

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--handoff-board",
        "--enforce-retirement-gate",
    ])

    assert code == 2
    board = json.loads(capsys.readouterr().out)
    assert board["archive_allowed"] is False


def test_cli_inspect_board_pids_is_read_only_and_uses_board_blockers(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    out_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(2, [
            {
                "pid": 1,
                "cmdline": "python -m pytest x.py -q",
                "age_seconds": 3700.0,
                "cpu_total_seconds": 1.0,
            },
            {
                "pid": 2,
                "cmdline": "python -m nodelang.application_server --port 8505",
            },
        ]),
    )
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {2}})
    seen = {}

    def fake_inspect(pids):
        seen["pids"] = list(pids)
        return {
            "schema": "archhub-live-runtime-pid-inspection/v1",
            "available": True,
            "processes": [],
        }

    monkeypatch.setattr(drain.live_runtime_holders, "inspect_pids", fake_inspect)

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--inspect-board-pids",
    ])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "archhub-runtime-handoff-pid-inspection/v1"
    assert seen["pids"] == [1, 2]
    assert out["inspection"]["schema"] == "archhub-live-runtime-pid-inspection/v1"
    assert out["disposable_holder_court"]["schema"] == (
        "archhub-disposable-runtime-holder-court/v1"
    )
    assert not out_dir.exists()


def test_cli_inspect_board_pids_expands_child_processes_for_court(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 21, "cmdline": "python.exe -"}]),
    )
    calls = []

    def fake_inspect(pids):
        calls.append(list(pids))
        if calls[-1] == [21]:
            return {
                "schema": "archhub-live-runtime-pid-inspection/v1",
                "available": True,
                "processes": [{
                    "pid": 21,
                    "exists": True,
                    "process_risk_class": "stdin_python_parent",
                    "child_pids": [6084],
                    "listening_ports": [],
                    "established_connection_count": 0,
                }],
            }
        return {
            "schema": "archhub-live-runtime-pid-inspection/v1",
            "available": True,
            "processes": [{
                "pid": 6084,
                "exists": True,
                "name": "conhost.exe",
                "cmdline": "\\??\\C:\\Windows\\system32\\conhost.exe 0x4",
                "child_pids": [],
                "listening_ports": [],
                "established_connection_count": 0,
            }],
        }

    monkeypatch.setattr(drain.live_runtime_holders, "inspect_pids", fake_inspect)

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--inspect-board-pids",
    ])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert calls == [[21], [6084]]
    assert out["inspection"]["expanded_child_pids"] == [6084]
    assert [process["pid"] for process in out["inspection"]["processes"]] == [
        21,
        6084,
    ]


def test_cli_inspect_board_pids_includes_non_holder_port_owners(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{
            "pid": 2,
            "cmdline": "python -m nodelang.application_server --port 8505 --cloud-port 8506",
        }]),
    )
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {2}, 8506: {2, 99}})
    seen = {}

    def fake_inspect(pids):
        seen["pids"] = list(pids)
        return {
            "schema": "archhub-live-runtime-pid-inspection/v1",
            "available": True,
            "processes": [],
        }

    monkeypatch.setattr(drain.live_runtime_holders, "inspect_pids", fake_inspect)

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--inspect-board-pids",
    ])

    assert code == 0
    json.loads(capsys.readouterr().out)
    assert seen["pids"] == [2, 99]


def test_cli_enforce_retirement_gate_returns_red_when_gate_blocks(tmp_path, monkeypatch, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{"pid": 123, "cmdline": "python -m nodelang.application_server --port 8505"}]),
    )
    monkeypatch.setattr(drain, "authority_launch_readiness", lambda authority: {"ok": True})
    monkeypatch.setattr(drain, "active_tcp_listeners", lambda: {8505: {123}})

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--no-write",
        "--enforce-retirement-gate",
    ])

    assert code == 2
    plan = json.loads(capsys.readouterr().out)
    assert plan["retirement_gate"]["archive_allowed"] is False
    assert plan["retirement_gate"]["failures"] == [
        "authority_shadow_launch_proven",
        "active_authority_runtime_bridge",
        "no_live_holders",
        "no_blocked_exact_replacements",
    ]


def test_cli_enforce_retirement_gate_returns_red_for_runtime_source_drift(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "runtime_only.py").write_text("# runtime source\n", encoding="utf-8")
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(0, []))
    monkeypatch.setattr(drain, "authority_launch_readiness", lambda authority: {"ok": True})
    monkeypatch.setattr(
        drain,
        "authority_shadow_launch_probe",
        lambda authority: {"ok": True, "ran": True},
    )
    monkeypatch.setattr(
        drain,
        "active_authority_runtime_bridge_status",
        lambda product_root, workspace: {"ok": True},
    )

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--no-write",
        "--authority-shadow-probe",
        "--enforce-retirement-gate",
    ])

    assert code == 2
    plan = json.loads(capsys.readouterr().out)
    assert plan["runtime_copy_source_drift"]["ok"] is False
    assert plan["runtime_copy_source_drift"]["missing_in_authority"][0]["path"] == (
        "nodelang/runtime_only.py"
    )
    assert plan["retirement_gate"]["failures"] == [
        "runtime_copy_source_drift_clear"
    ]


def test_cli_enforce_retirement_gate_returns_green_when_gate_allows(tmp_path, monkeypatch, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(0, []))
    monkeypatch.setattr(drain, "authority_launch_readiness", lambda authority: {"ok": True})
    monkeypatch.setattr(
        drain,
        "authority_shadow_launch_probe",
        lambda authority: {"ok": True, "ran": True},
    )
    monkeypatch.setattr(
        drain,
        "active_authority_runtime_bridge_status",
        lambda product_root, workspace: {"ok": True},
    )

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--no-write",
        "--authority-shadow-probe",
        "--enforce-retirement-gate",
    ])

    assert code == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["retirement_gate"]["archive_allowed"] is True


class _HolderSyncBridge:
    def __init__(self, existing=None):
        self.created = []
        self._items = list(existing or [])
        self._revision = 10

    def work_list(self):
        return {
            "application": "app:archhub",
            "brain_scope": "gm:domain:brain",
            "revision": self._revision,
            "items": list(self._items),
        }

    def work_create(self, **body):
        self.created.append(body)
        root = "work:%s" % len(self.created)
        external_key = body["external_key"]
        self._items.append({
            "root": root,
            "interfaces": {
                "external-key": {"value": external_key},
            },
        })
        self._revision += 1
        return {
            "created_root": root,
            "membership_wire": "wire:%s" % len(self.created),
        }


def test_sync_runtime_holders_to_universal_creates_governed_work_items(tmp_path):
    holder_payload = {
        "holder_report": _audit(2, [
            {
                "pid": 10,
                "name": "pythonw.exe",
                "cwd": "node_runtime",
                "cmdline": "pythonw.exe run_application_server.py --port 8482 --cloud-port 8484",
                "create_time": 100.25,
            },
            {
                "pid": 20,
                "name": "python.exe",
                "cwd": "node_runtime",
                "cmdline": (
                    "python C:\\Users\\fargaly\\AppData\\Local\\Temp\\"
                    "archhub_nary_qa_server.py"
                ),
                "create_time": 101.5,
            },
        ]),
    }
    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        holder_payload,
    )
    bridge = _HolderSyncBridge()

    result = drain.sync_runtime_holders_to_universal(plan, bridge=bridge)

    assert result["schema"] == "archhub-runtime-holder-universal-sync/v1"
    assert result["non_destructive"] is True
    assert [item["pid"] for item in result["imported"]] == [10, 20]
    assert result["skipped"] == []
    assert bridge.created[0]["external_key"] == "runtime-holder:10:100250"
    assert bridge.created[0]["priority"] == 9900
    assert bridge.created[0]["references"] == {"scope": "gm:domain:brain"}
    assert bridge.created[0]["structured_references"]["applicable-policy"][
        "no_process_interruption"
    ] is True
    assert bridge.created[0]["structured_references"]["inputs"]["holder"][
        "holder_risk_class"
    ] == "visible_legacy_endpoint"
    assert bridge.created[1]["structured_references"]["inputs"]["holder"][
        "holder_risk_class"
    ] == "qa_server_script_missing"
    selectors = bridge.created[0]["structured_references"]["requirements"][
        "gate"
    ]["spec"]["selectors"]
    assert selectors == [
        "tests/test_live_runtime_holders.py",
        "tests/test_legacy_runtime_drain.py",
        "tests/test_runtime_retirement_hook.py",
    ]


def test_sync_runtime_holders_to_universal_skips_existing_external_keys(tmp_path):
    holder = {
        "pid": 10,
        "name": "python.exe",
        "cwd": "node_runtime",
        "cmdline": "python.exe -",
        "create_time": 100.0,
    }
    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        {"holder_report": _audit(1, [holder])},
    )
    bridge = _HolderSyncBridge(existing=[{
        "root": "existing:work",
        "interfaces": {
            "external-key": {"value": "runtime-holder:10:100000"},
        },
    }])

    result = drain.sync_runtime_holders_to_universal(plan, bridge=bridge)

    assert result["imported"] == []
    assert result["skipped"] == [{
        "external_key": "runtime-holder:10:100000",
        "pid": 10,
        "work_root": "existing:work",
    }]
    assert bridge.created == []


def test_verify_runtime_holders_in_universal_is_read_only_and_reports_all_synced(tmp_path):
    holders = [
        {
            "pid": 10,
            "name": "pythonw.exe",
            "cwd": "node_runtime",
            "cmdline": "pythonw.exe run_application_server.py --port 8482",
            "create_time": 100.25,
        },
        {
            "pid": 20,
            "name": "python.exe",
            "cwd": "node_runtime",
            "cmdline": "python.exe -",
            "create_time": 101.5,
        },
    ]
    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        {"holder_report": _audit(2, holders)},
    )
    bridge = _HolderSyncBridge(existing=[
        {
            "root": "work:10",
            "interfaces": {
                "external-key": {"value": "runtime-holder:10:100250"},
            },
        },
        {
            "root": "work:20",
            "interfaces": {
                "external-key": {"value": "runtime-holder:20:101500"},
            },
        },
    ])

    result = drain.verify_runtime_holders_in_universal(plan, bridge=bridge)

    assert result["schema"] == "archhub-runtime-holder-universal-verification/v1"
    assert result["ok"] is True
    assert result["holder_count"] == 2
    assert result["verified_count"] == 2
    assert result["missing_count"] == 0
    assert [row["work_root"] for row in result["verified"]] == ["work:10", "work:20"]
    assert result["missing"] == []
    assert result["non_destructive"] is True
    assert bridge.created == []


def test_verify_runtime_holders_in_universal_reports_missing_without_writes(tmp_path):
    holder = {
        "pid": 10,
        "name": "python.exe",
        "cwd": "node_runtime",
        "cmdline": "python.exe -",
        "create_time": 100.0,
    }
    plan = drain.build_drain_plan(
        tmp_path / "10.PRODUCT" / "12.PRODUCTION",
        tmp_path,
        {"holder_report": _audit(1, [holder])},
    )
    bridge = _HolderSyncBridge()

    result = drain.verify_runtime_holders_in_universal(plan, bridge=bridge)

    assert result["ok"] is False
    assert result["verified"] == []
    assert result["missing"] == [{
        "external_key": "runtime-holder:10:100000",
        "pid": 10,
        "holder_risk_class": "stdin_python_holder",
    }]
    assert bridge.created == []


def test_runtime_holder_sync_uses_bridge_not_cell_store():
    source = inspect.getsource(drain.sync_runtime_holders_to_universal)

    assert "UniversalRuntimeBridge" in source
    assert "_runtime_work_index(runtime)" in source
    assert "runtime.work_create(" in source
    assert "CellStore" not in source
    assert "ApplicationServer" not in source
    assert "sqlite3" not in source


def test_cli_rejects_universal_holder_sync_in_read_only_mode(tmp_path, capsys):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--no-write",
        "--sync-universal-holders",
    ])

    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "archhub-legacy-runtime-drain-error/v1"
    assert "cannot be combined with read-only flags" in out["reason"]


def test_cli_verify_universal_holders_is_read_only_and_enforced(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    (product_root / "node_runtime").mkdir(parents=True)
    seen = {}
    monkeypatch.setattr(
        drain.live_runtime_holders,
        "audit",
        lambda path: _audit(1, [{
            "pid": 10,
            "cmdline": "python.exe -",
            "create_time": 100.0,
        }]),
    )

    def fake_verify(plan):
        seen["holder_count"] = plan["holder_count"]
        return {
            "schema": "archhub-runtime-holder-universal-verification/v1",
            "ok": False,
            "holder_count": 1,
            "verified_count": 0,
            "missing_count": 1,
            "verified": [],
            "missing": [{"pid": 10}],
            "non_destructive": True,
        }

    monkeypatch.setattr(drain, "verify_runtime_holders_in_universal", fake_verify)

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--verify-universal-holders",
    ])

    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "archhub-runtime-holder-universal-verification/v1"
    assert out["ok"] is False
    assert seen["holder_count"] == 1


def test_cli_source_drift_report_is_read_only_candidate_inventory(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "candidate.py").write_text("# runtime candidate\n", encoding="utf-8")
    out_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(0, []))

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--source-drift-report",
    ])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "archhub-runtime-copy-source-drift/v1"
    assert out["ok"] is False
    assert out["migration_candidate_count"] == 1
    assert out["decision_summary"]["candidate_count"] == 1
    assert out["decision_summary"]["all_classified"] is False
    assert out["decision_summary"]["unmapped_paths"] == ["nodelang/candidate.py"]
    assert out["migration_candidates"][0]["path"] == "nodelang/candidate.py"
    assert out["migration_candidates"][0]["status"] == "missing_in_authority"
    assert not out_dir.exists()


def test_cli_source_drift_work_plan_is_read_only_authority_scoped(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "authority_bridge.py").write_text("# runtime\n", encoding="utf-8")
    out_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(0, []))

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--source-drift-work-plan",
    ])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "archhub-runtime-source-drift-migration-work/v1"
    assert out["track_count"] == 1
    assert out["all_work_authority_scoped"] is True
    assert out["all_non_promoting"] is True
    assert out["all_bulk_copy_forbidden"] is True
    assert out["all_non_interrupting"] is True
    assert out["work_items"][0]["migration_track"] == "runtime_transport_and_broker"
    assert out["work_items"][0]["implementation_candidate_paths"] == [
        "nodelang/authority_bridge.py"
    ]
    assert not out_dir.exists()


def test_cli_can_write_selected_json_evidence_without_process_mutation(
    tmp_path,
    monkeypatch,
    capsys,
):
    product_root = tmp_path / "10.PRODUCT" / "12.PRODUCTION"
    runtime = product_root / "node_runtime" / "nodelang"
    authority = tmp_path / "10.PRODUCT" / "13.NODE-LANGUAGE" / "nodelang"
    runtime.mkdir(parents=True)
    authority.mkdir(parents=True)
    (runtime / "authority_bridge.py").write_text("# runtime\n", encoding="utf-8")
    out_dir = tmp_path / "must-not-exist"
    evidence = tmp_path / "evidence" / "work-plan.json"
    monkeypatch.setattr(drain.live_runtime_holders, "audit", lambda path: _audit(0, []))

    code = drain.main([
        "--product-root", str(product_root),
        "--workspace", str(tmp_path),
        "--output-dir", str(out_dir),
        "--source-drift-work-plan",
        "--output-json", str(evidence),
    ])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert json.loads(evidence.read_text(encoding="utf-8")) == out
    assert out["schema"] == "archhub-runtime-source-drift-migration-work/v1"
    assert not out_dir.exists()
