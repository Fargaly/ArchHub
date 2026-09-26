"""Court: runtime compliance means the landed governance hooks, not the Brain.

The personal Brain is retired, so a client whose config binds the landed
gates (00.GOVERNANCE/hooks/agent_scope_gate.py before and after each tool,
native_start_hook.py at session start, native_stop_hook.py at completion where
the vendor supports them) is compliant WITHOUT the Brain MCP entry or brainwrap.
A client missing the pre-tool gate is not compliant, whatever else it has. A
vendor with no hook mechanism is reported not-enforceable and never passes.
The configs live in a temporary profile -- never the founder's.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nodelang.runtime_compliance_adapter import (
    RUNTIME_COMPLIANCE_CHECKS,
    run_physical_runtime_compliance_court,
)

PY = "C:/Users/someone/AppData/Local/Python/python.exe"
GATE = PY + " C:/Users/someone/ArchHub/00.GOVERNANCE/hooks/agent_scope_gate.py --vendor %s"
START = PY + " C:/Users/someone/AppData/Local/ArchHub/nodelang/native_start_hook.py --runtime %s"
STOP = PY + " C:/Users/someone/AppData/Local/ArchHub/nodelang/native_stop_hook.py --vendor claude-code"


def _cmd(command):
    return [{"hooks": [{"type": "command", "command": command}]}]


def _claude(home, *, pre=True, brain_only=False):
    hooks = {}
    if brain_only:
        hooks = {"SessionStart": _cmd(PY + " C:/x/tools/brainwrap.py session-start --vendor claude-code"),
                 "Stop": _cmd(PY + " C:/x/tools/brainwrap.py stop --vendor claude-code"),
                 "UserPromptSubmit": [{"hooks": [{"type": "mcp_tool", "server": "brain",
                                                  "tool": "brain.hook_context"}]}]}
    else:
        if pre:
            hooks["PreToolUse"] = _cmd(GATE % "claude")
        hooks["PostToolUse"] = _cmd(GATE % "claude")
        hooks["SessionStart"] = _cmd(START % "claude")
        hooks["Stop"] = _cmd(STOP)
    settings = {"hooks": hooks}
    if brain_only:
        settings["mcpServers"] = {"brain": {"command": "personal-brain.exe"}}
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


def _court(monkeypatch, home, runtime):
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return run_physical_runtime_compliance_court(
        SimpleNamespace(external_parameters={"runtime": runtime}))


def test_landed_hooks_without_the_brain_mcp_are_compliant(monkeypatch, tmp_path):
    _claude(tmp_path)
    result = _court(monkeypatch, tmp_path, "claude")
    assert result.passed is True, result.details
    assert result.checks == {name: True for name in RUNTIME_COMPLIANCE_CHECKS}
    assert result.details["adapter"] == "native-hook-observer-v1"


def test_a_client_missing_the_landed_pre_tool_gate_is_not_compliant(monkeypatch, tmp_path):
    _claude(tmp_path, pre=False)
    result = _court(monkeypatch, tmp_path, "claude")
    assert result.passed is False
    assert result.checks["scope-gate"] is False and result.checks["required-hooks"] is False


def test_the_brain_mcp_and_brainwrap_are_not_compliance(monkeypatch, tmp_path):
    _claude(tmp_path, brain_only=True)
    result = _court(monkeypatch, tmp_path, "claude-code")
    assert result.passed is False
    assert result.checks["scope-gate"] is False
    assert result.checks["brain-connected"] is False      # brainwrap session-start is not the app


def test_codex_needs_its_gates_and_start_hook_but_has_no_native_stop(monkeypatch, tmp_path):
    path = tmp_path / ".codex" / "hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {
        "PreToolUse": _cmd(GATE % "codex"), "PostToolUse": _cmd(GATE % "codex"),
        "UserPromptSubmit": _cmd(START % "codex")}}), encoding="utf-8")
    result = _court(monkeypatch, tmp_path, "codex-desktop")
    assert result.passed is True, result.details
    assert "no supported native completion hook" in result.details["note:workshop-authority"]


def test_a_vendor_with_no_hook_mechanism_is_not_enforceable(monkeypatch, tmp_path):
    result = _court(monkeypatch, tmp_path, "some-new-agent")
    assert result.passed is False
    assert result.details["status"] == "not-enforceable"
    assert "no hook mechanism" in result.details["note:reason"]


def test_the_retired_brain_package_is_gone():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "personal_brain").exists()
    iss = (root / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert not [line for line in iss.splitlines() if line.startswith("Source:") and "personal_brain" in line]
    assert "personal_brain" not in (root / "installer" / "build_release.ps1").read_text(encoding="utf-8")

def test_an_upgrade_removes_the_retired_brain_files():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    for name in ("personal_brain\\hook_coverage.py", "personal_brain\\installer.py",
                 "personal_brain\\__init__.py", "personal_brain\\ambient_policy.py",
                 "nodelang\\brain_supervisor_start.py"):
        assert 'Type: files; Name: "{app}\\%s"' % name in section, name


from nodelang.runtime_hook_observer import observe_runtime_compliance  # noqa: E402


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def _claude_with(home, pre_matcher, extra=None):
    hooks = {"PreToolUse": [{"matcher": pre_matcher, "hooks": [{"type": "command", "command": GATE % "claude"}]}],
             "PostToolUse": _cmd(GATE % "claude"), "SessionStart": _cmd(START % "claude"), "Stop": _cmd(STOP)}
    _write(home / ".claude" / "settings.json", {"hooks": hooks, **(extra or {})})


def test_a_gate_that_misses_a_write_tool_is_not_the_scope_gate(tmp_path):
    _claude_with(tmp_path, "Write|Edit")                      # MultiEdit, NotebookEdit unseen
    result = observe_runtime_compliance("claude", home=tmp_path)
    assert result["checks"]["scope-gate"] is False
    assert "MultiEdit" in result["notes"]["scope-gate"]


def test_a_gate_blind_to_the_shell_is_reported_partial(tmp_path):
    _claude_with(tmp_path, "Write|Edit|MultiEdit|NotebookEdit|Update")
    result = observe_runtime_compliance("claude", home=tmp_path)
    assert result["status"] == "green"
    assert result["notes"]["coverage"].startswith("partial: the gate does not see Bash")


def test_disable_all_hooks_turns_every_hook_check_off(tmp_path):
    _claude_with(tmp_path, None, {"disableAllHooks": True})
    result = observe_runtime_compliance("claude", home=tmp_path)
    assert result["status"] == "red" and result["checks"]["scope-gate"] is False


def test_codex_trust_is_by_hook_identity_not_by_position(tmp_path):
    from nodelang.runtime_hook_observer import codex_hook_hash
    hooks_path = tmp_path / ".codex" / "hooks.json"
    pre = {"type": "command", "command": GATE % "codex"}
    start = {"type": "command", "command": START % "codex"}
    _write(hooks_path, {"hooks": {"PreToolUse": [{"hooks": [pre]}], "PostToolUse": _cmd(GATE % "codex"),
                                  "UserPromptSubmit": [{"hooks": [start]}]}})
    stale = codex_hook_hash("UserPromptSubmit", None, {"command": "python brainwrap.py context"})
    _write(tmp_path / ".codex" / "config.toml",
           "[hooks.state]\n\n[hooks.state.'%s:pre_tool_use:0:0']\ntrusted_hash = \"%s\"\n\n"
           "[hooks.state.'%s:user_prompt_submit:0:0']\ntrusted_hash = \"%s\"\n"
           % (hooks_path, codex_hook_hash("PreToolUse", None, pre), hooks_path, stale))
    notes = observe_runtime_compliance("codex", home=tmp_path)["notes"]
    assert "trust:pre_tool_use:0:0" not in notes                       # same identity: trusted
    assert "no trust record" in notes["trust:post_tool_use:0:0"]
    # A stale brainwrap trust at the same position is NOT trust for the new hook.
    assert "different hook definition" in notes["trust:user_prompt_submit:0:0"]


def test_codex_hook_hash_matches_codex_canonical_form():
    """codex-rs hooks hook_hash: sorted compact JSON, default timeout 600, async false."""
    import hashlib as _h
    from nodelang.runtime_hook_observer import codex_hook_hash
    expected = _h.sha256(b'{"event_name":"pre_tool_use","hooks":[{"async":false,"command":"x",'
                         b'"timeout":600,"type":"command"}],"matcher":"apply_patch"}').hexdigest()
    assert codex_hook_hash("PreToolUse", "apply_patch", {"command": "x"}) == "sha256:" + expected


def test_opencode_governance_plugin_is_found_in_the_singular_plugin_folder(tmp_path):
    _write(tmp_path / ".config" / "opencode" / "plugins" / "session-link.js", "export default {}")
    red = observe_runtime_compliance("opencode", home=tmp_path)
    assert red["status"] == "red" and red["checks"]["scope-gate"] is False
    _write(tmp_path / ".config" / "opencode" / "plugin" / "archhub-governance-abc-product.js",
           "const gate = 'C:/Users/someone/ArchHub/00.GOVERNANCE/hooks/opencode_native_gate.py';")
    assert observe_runtime_compliance("opencode", home=tmp_path)["status"] == "green"
