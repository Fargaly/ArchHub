from __future__ import annotations

import json
import os
import subprocess

import pytest
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
    if not (WORKSPACE / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py").is_file():
        pytest.skip("workstation court: the governance hook lives outside the repository")
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
    assert "DENIED" in payload["reason"]
    # This used to assert "outside_allowed_paths", the verdict of
    # cde_gate.validate_write_scope run against the container in the env
    # above. That string is unreachable from the before-phase today and
    # asserting it certified nothing: authority moved out of a local JSON
    # projection and into the signed graph-held container bound to the
    # session's claimed Work, and governed_write_broker._active_cde_container
    # now returns None outright the moment ARCHHUB_ACTIVE_CDE_CONTAINER is
    # set -- "a caller-selected inline container or state path is not
    # authority". The refusal that matters is the signed CDE permit, and it
    # is what this court now names (2026-09-07).
    assert "signed CDE gate DENIED" in payload["reason"]


def test_a_container_the_caller_hands_the_gate_can_never_widen_its_scope():
    """The env container is a claim, not authority, and must not admit.

    An agent that can set its own ARCHHUB_ACTIVE_CDE_CONTAINER could
    otherwise name the file it wants in allowed_paths and walk through the
    scope gate it just authored. The write still has to be granted by the
    graph-held container bound to the claimed Work, so pointing the local
    claim straight at the target changes nothing.
    """
    if not (WORKSPACE / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py").is_file():
        pytest.skip("workstation court: the governance hook lives outside the repository")
    target = "10.PRODUCT/12.PRODUCTION/app/bridge.py"
    permissive = _active_ui_container()
    permissive["allowed_paths"] = [target]

    event = {
        "hook_event_name": "PreToolUse",
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": target, "Content": "unsafe write"},
        },
        "conversationId": "antigravity-widened-session",
        "workspacePaths": [str(WORKSPACE)],
    }
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["ARCHHUB_WORKSPACE_ROOT"] = str(WORKSPACE)
    env["ARCHHUB_ACTIVE_CDE_CONTAINER"] = json.dumps(permissive)
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


def test_an_antigravity_write_is_refused_for_the_write_not_for_the_adapter():
    """Reaching the signed permit at all is what this proves.

    Antigravity capitalises its arguments and issues no call id, so every
    write used to stop at "write session identity is unresolved" or "write
    content is unresolved" -- refusals about the adapter wearing the words
    of a refusal about the write. Whatever the verdict is, it has to be a
    verdict about the write (2026-09-07).
    """
    if not (WORKSPACE / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py").is_file():
        pytest.skip("workstation court: the governance hook lives outside the repository")
    event = {
        "hook_event_name": "PreToolUse",
        "toolCall": {
            "name": "write_to_file",
            "args": {
                "TargetFile": "10.PRODUCT/12.PRODUCTION/app/bridge.py",
                "Content": "unsafe write",
            },
        },
        "conversationId": "antigravity-reaches-the-permit",
        "workspacePaths": [str(WORKSPACE)],
    }
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["ARCHHUB_WORKSPACE_ROOT"] = str(WORKSPACE)
    env["BRAIN_COMPLIANCE_EVENT_APPEND"] = "0"

    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "antigravity_scope_gate.py")],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=str(REPO),
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "write session identity is unresolved" not in payload["reason"]
    assert "write content is unresolved" not in payload["reason"]
