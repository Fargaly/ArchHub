"""Governance probes must have live meat, not just node-shaped labels.

The existing launch policy already models Brain / hooks / process coverage as
nodes. This pins the missing executable part: pulling those probe nodes must
read real evidence surfaces and return bounded proof, while still keeping raw
process command lines out of the graph value.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import Store, validate_store  # noqa: E402
from nodelang import governance_probe  # noqa: E402
from nodelang.governance_policy import build_desktop_launch_policy  # noqa: E402


def _probe_by_check(store, policy, check):
    for nid in policy["probes"]:
        floor = store.nodes[nid]["body"]["floor"]
        if floor["spec"]["check"] == check:
            return nid
    raise AssertionError("missing probe for %s" % check)


def test_governance_policy_probes_pull_real_checks_not_unknown_labels():
    store = Store()
    policy = build_desktop_launch_policy(store, commands=("codex",))
    assert validate_store(store) is True

    for check in (
        "brain-health",
        "hook-coverage",
        "process-ancestry-governed",
        "normal-app-watchdog",
    ):
        value = store.pull(_probe_by_check(store, policy, check))
        assert value["kind"] == "governance"
        assert value["check"] == check
        assert value["detail"]
        assert "unknown probe kind" not in value["detail"].lower()


def test_brain_health_probe_uses_the_mcp_health_operation(monkeypatch):
    observed = {}

    def _healthy_tool(name, arguments, *, url, timeout):
        observed.update(name=name, arguments=arguments, url=url, timeout=timeout)
        return {"ok": True, "owner_user": "founder"}

    monkeypatch.setattr(governance_probe, "_mcp_tool", _healthy_tool)

    result = governance_probe._probe_brain_health(
        "brain-health",
        {"mcp_url": "http://brain.example/mcp", "timeout": 1.25},
    )

    assert observed == {
        "name": "brain.health",
        "arguments": {},
        "url": "http://brain.example/mcp",
        "timeout": 1.25,
    }
    assert result["ok"] is True
    assert result["source"] == "brain.health"
    assert result["detail"] == "brain.health reachable"


def test_process_governance_probe_uses_sanitized_session_summary(tmp_path):
    status_file = tmp_path / "sessions.json"
    status_file.write_text(
        json.dumps(
            {
                "ok": True,
                "current_sessions_total": 2,
                "current_sessions_governed": 2,
                "current_sessions_need_restart": 0,
                "sessions": [
                    {
                        "pid": 1,
                        "name": "codex.exe",
                        "status": "governed",
                        "command_line": "--api-key SECRET-SHOULD-NOT-LEAK",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = Store()
    probe = store.add(
        "op",
        "Probe: process-ancestry-governed",
        floor={
            "op": "probe",
            "kind": "governance",
            "spec": {
                "check": "process-ancestry-governed",
                "status_json": str(status_file),
            },
        },
    )

    value = store.pull(probe)
    assert value["ok"] is True
    assert value["counts"] == {"total": 2, "governed": 2, "need_restart": 0}

    blob = json.dumps(value).lower()
    assert "secret-should-not-leak" not in blob
    assert "command_line" not in blob
