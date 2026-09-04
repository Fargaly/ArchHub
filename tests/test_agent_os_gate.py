from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import agent_os_gate as gate  # noqa: E402


def test_ifeo_payload_uses_configured_target_and_strips_original_exe():
    config = {
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Codex": {"path": "C:\\Apps\\Codex\\Codex.exe"},
        },
    }

    payload = gate.ifeo_request_payload(
        config,
        "Codex",
        ["C:\\Apps\\Codex\\Codex.exe", "--new-window"],
    )

    assert payload == {
        "app": "Codex",
        "target": "C:\\Apps\\Codex\\Codex.exe",
        "args": ["--new-window"],
        "cwd": "C:\\Users\\fargaly\\00.ARCHUB",
        "launch_kind": "top_level",
        "governed_strict": True,
        "workshop_authority_required": True,
    }


def test_ifeo_payload_marks_chromium_child_process_launches():
    config = {
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Antigravity": {"path": "C:\\Apps\\Antigravity\\Antigravity.exe"},
        },
    }

    payload = gate.ifeo_request_payload(
        config,
        "Antigravity",
        [
            "C:\\Apps\\Antigravity\\Antigravity.exe",
            "--type=gpu-process",
            "--user-data-dir=C:\\Users\\fargaly\\AppData\\Roaming\\Antigravity",
        ],
    )

    assert payload["launch_kind"] == "app_child"
    assert payload["args"][0] == "--type=gpu-process"


def test_cmd_ifeo_blocks_raw_launch_when_broker_is_unreachable():
    config = {
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Claude": {"path": "C:\\Apps\\Claude\\Claude.exe"},
        },
    }

    code = gate.cmd_ifeo_from_config(
        config,
        app="Claude",
        original_argv=["C:\\Apps\\Claude\\Claude.exe"],
        post_fn=lambda _config, _payload: {"ok": False, "error": "broker down"},
    )

    assert code == gate.GATE_BLOCK_EXIT
