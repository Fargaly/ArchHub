"""Tests for the repo-scoped Claude Code Stop hook (settings.json).

The repo-scoped settings.json is expected to MERGE with the founder's global
~/.claude hooks (it does not replace them). This test only asserts the
repo-scoped Stop hook wires THE DRIVE via tools/completion_gate.py.

Runnable two ways:
  - pytest:   python -m pytest tests/test_repo_stop_hook.py -q
  - directly: python tests/test_repo_stop_hook.py
"""

import json
import os

# Resolve .claude/settings.json relative to this test file so it works no
# matter the current working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
SETTINGS_PATH = os.path.join(_REPO_ROOT, ".claude", "settings.json")


def _load_settings():
    # utf-8-sig tolerates a BOM if one is present.
    with open(SETTINGS_PATH, encoding="utf-8-sig") as fh:
        return json.load(fh)


def test_settings_json_is_valid_and_loads():
    data = _load_settings()
    assert isinstance(data, dict)


def test_stop_hook_command_targets_completion_gate():
    data = _load_settings()
    command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert command.endswith("completion_gate.py"), command
    assert "completion_gate.py" in command


def test_stop_hook_matcher_is_wildcard():
    data = _load_settings()
    assert data["hooks"]["Stop"][0]["matcher"] == "*"


def test_stop_hook_is_command_type():
    data = _load_settings()
    assert data["hooks"]["Stop"][0]["hooks"][0]["type"] == "command"


def _main():
    data = _load_settings()
    command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert command.endswith("completion_gate.py"), command
    assert "completion_gate.py" in command
    assert data["hooks"]["Stop"][0]["matcher"] == "*"
    assert data["hooks"]["Stop"][0]["hooks"][0]["type"] == "command"
    print("OK repo Stop hook ->", command)


if __name__ == "__main__":
    _main()
