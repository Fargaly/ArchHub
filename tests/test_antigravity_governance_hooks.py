from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parents[1]


def _active_ui_container() -> dict:
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
        "gate_spec": {
            "selector": "[data-uisurface='home-top']",
            "legacy_exception": "Antigravity scope regression test only",
        },
        "evidence_ref": "cdp:home-top",
    }


def test_project_antigravity_hooks_bind_scope_context_and_stop():
    hooks = json.loads((REPO / ".agents" / "hooks.json").read_text(encoding="utf-8"))
    entry = hooks["archhub-governance"]

    assert "PreToolUse" in entry
    assert "PreInvocation" in entry
    assert "Stop" in entry
    assert entry["PreToolUse"][0]["matcher"] == ".*"
    assert "antigravity_scope_gate.py" in entry["PreToolUse"][0]["hooks"][0]["command"]
    assert "antigravity_coordination_context.py" in entry["PreInvocation"][0]["command"]
    assert "brainwrap.py stop --vendor antigravity" in entry["Stop"][0]["command"]


def test_antigravity_scope_wrapper_denies_out_of_cde_write():
    event = {
        "hook_event_name": "PreToolUse",
        "toolCall": {
            "name": "write_to_file",
            "args": {
                "TargetFile": "10.PRODUCT/12.PRODUCTION/app/bridge.py",
                "Content": "unsafe write",
            },
        },
        "conversationId": "antigravity-test-session",
        "workspacePaths": [str(WORKSPACE)],
    }
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["ARCHHUB_WORKSPACE_ROOT"] = str(WORKSPACE)
    env["ARCHHUB_ACTIVE_CDE_CONTAINER"] = json.dumps(_active_ui_container())
    env["BRAIN_COMPLIANCE_EVENT_APPEND"] = "0"

    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "antigravity_scope_gate.py")],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=str(REPO),
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "CDE scope gate DENIED" in payload["reason"]
    assert "outside_allowed_paths" in payload["reason"]
