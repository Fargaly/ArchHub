"""Slice 3 — installer tests. Uses HOME redirection so tests never touch
the real user's ~/.claude / ~/.cursor / etc.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from personal_brain import installer


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() (and HOME / USERPROFILE) into a tmp dir so the
    installer reads/writes there instead of the real filesystem."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Force re-binding of plan paths since they captured at import time
    installer.ALL_PLANS["claude-code"].config_path = (
        tmp_path / ".claude" / "settings.json"
    )
    installer.ALL_PLANS["cursor"].config_path = (
        tmp_path / ".cursor" / "mcp.json"
    )
    installer.ALL_PLANS["codex"].config_path = (
        tmp_path / ".codex" / "config.toml"
    )
    installer.ALL_PLANS["gemini-cli"].config_path = (
        tmp_path / ".gemini" / "settings.json"
    )
    yield tmp_path


def test_detect_when_dir_present(fake_home):
    (fake_home / ".claude").mkdir()
    detected = installer.detect_clients()
    assert "claude-code" in detected


def test_claude_code_fresh_install(fake_home):
    (fake_home / ".claude").mkdir()
    res = installer.install_all(only=["claude-code"])
    assert res[0]["changed"]
    cfg = json.loads(installer._claude_code_path().read_text())
    assert "brain" in cfg["mcpServers"]
    assert "UserPromptSubmit" in cfg["hooks"]
    # exact hook entry shape — UserPromptSubmit[0] is the RECALL wrapper
    # (brain.context was repointed at the hook-shaped brain.hook_context, which
    # carries the typed `arguments` map the bare tool couldn't synthesize).
    entry = cfg["hooks"]["UserPromptSubmit"][0]
    assert entry["server"] == "brain"
    assert entry["tool"] == "brain.hook_context"
    # the wrapper MUST carry its arguments (a bare hook fired the tool with {}
    # and failed — the whole reason for the wrapper rename).
    assert entry["arguments"]["prompt"] == "${prompt}"


def test_claude_code_idempotent(fake_home):
    (fake_home / ".claude").mkdir()
    installer.install_all(only=["claude-code"])
    res2 = installer.install_all(only=["claude-code"])
    # Second run: no functional change (notes may say "replaced" but config
    # converges to same shape). UserPromptSubmit now carries TWO brain mcp_tool
    # hooks — RECALL (brain.hook_context, the hook-shaped wrapper for
    # brain.context) AND the DRIVE (brain.work_assigned_block) — and re-install
    # must dedupe each to exactly one (never stack).
    cfg = json.loads(installer._claude_code_path().read_text())
    entries = cfg["hooks"]["UserPromptSubmit"]
    tools = [e.get("tool") for e in entries if e.get("server") == "brain"]
    assert tools.count("brain.hook_context") == 1, (
        "must dedupe the brain.hook_context recall wrapper")
    assert tools.count("brain.work_assigned_block") == 1, (
        "must dedupe the brain.work_assigned_block DRIVE hook")
    assert len(tools) == 2, f"expected exactly the 2 brain pre-prompt hooks, got {tools}"


def test_claude_code_preserves_existing_servers(fake_home):
    path = fake_home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "mcpServers": {
            "existing-server": {"command": "other", "args": ["x"]}
        },
        "hooks": {
            "UserPromptSubmit": [
                {"type": "command", "command": "echo hi"}
            ]
        },
    }))
    installer.install_all(only=["claude-code"])
    cfg = json.loads(path.read_text())
    assert "existing-server" in cfg["mcpServers"]
    assert "brain" in cfg["mcpServers"]
    # existing command hook preserved
    cmds = [e for e in cfg["hooks"]["UserPromptSubmit"]
             if e.get("type") == "command"]
    assert any(c.get("command") == "echo hi" for c in cmds)
    # brain hooks added — BOTH the recall (brain.hook_context, the hook-shaped
    # wrapper for brain.context) and the DRIVE (brain.work_assigned_block)
    # pre-prompt hooks, alongside the preserved user command hook.
    brain_tools = [e.get("tool") for e in cfg["hooks"]["UserPromptSubmit"]
                   if e.get("server") == "brain"]
    assert "brain.hook_context" in brain_tools
    assert "brain.work_assigned_block" in brain_tools
    assert len(brain_tools) == 2


def test_dry_run_does_not_write(fake_home):
    (fake_home / ".claude").mkdir()
    res = installer.install_all(only=["claude-code"], dry_run=True)
    assert res[0]["would_change"]
    assert not installer._claude_code_path().exists()


def test_uninstall_removes_brain_entries(fake_home):
    (fake_home / ".claude").mkdir()
    installer.install_all(only=["claude-code"])
    res = installer.uninstall_all(only=["claude-code"])
    assert res[0]["changed"]
    cfg = json.loads(installer._claude_code_path().read_text())
    assert "brain" not in cfg.get("mcpServers", {})


def test_uninstall_preserves_other_servers(fake_home):
    path = fake_home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "mcpServers": {"other": {"command": "o"}},
    }))
    installer.install_all(only=["claude-code"])
    installer.uninstall_all(only=["claude-code"])
    cfg = json.loads(path.read_text())
    assert "other" in cfg["mcpServers"]
    assert "brain" not in cfg["mcpServers"]


def test_cursor_install_writes_rules_file(fake_home):
    (fake_home / ".cursor").mkdir()
    res = installer.install_all(only=["cursor"])
    cfg = json.loads(installer._cursor_path().read_text())
    assert "brain" in cfg["mcpServers"]
    rules = installer._cursor_rules_path()
    assert rules.exists()
    body = rules.read_text()
    assert "brain.context" in body
    assert "alwaysApply: true" in body


def test_codex_install_appends_brain_block(fake_home):
    (fake_home / ".codex").mkdir()
    cfg_path = installer._codex_path()
    cfg_path.write_text("# existing\n[some.other]\nkey = 'val'\n")
    installer.install_all(only=["codex"])
    text = cfg_path.read_text()
    assert "[some.other]" in text  # preserved
    assert "[mcp_servers.brain]" in text
    assert "personal-brain-mcp" in text


def test_codex_install_idempotent(fake_home):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    installer.install_all(only=["codex"])  # second time
    text = installer._codex_path().read_text()
    # Should only contain ONE brain block
    assert text.count("[mcp_servers.brain]") == 1


def test_codex_uninstall_removes_block(fake_home):
    (fake_home / ".codex").mkdir()
    cfg_path = installer._codex_path()
    cfg_path.write_text("[other]\nx = 1\n")
    installer.install_all(only=["codex"])
    installer.uninstall_all(only=["codex"])
    text = cfg_path.read_text()
    assert "[mcp_servers.brain]" not in text
    assert "[other]" in text  # preserved


def test_gemini_install_writes_settings(fake_home):
    (fake_home / ".gemini").mkdir()
    installer.install_all(only=["gemini-cli"])
    cfg = json.loads(installer._gemini_path().read_text())
    assert "brain" in cfg["mcpServers"]


def test_install_unknown_client_returns_error(fake_home):
    res = installer.install_all(only=["nonexistent-client"])
    assert res[0]["error"]


def test_install_creates_backup_when_modifying(fake_home):
    path = fake_home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"old": {"command": "x"}}}))
    res = installer.install_all(only=["claude-code"])
    # Backup file present
    backups = list(path.parent.glob("settings.json.brain-bak.*"))
    assert len(backups) >= 1


def test_main_list_subcommand(fake_home, capsys):
    (fake_home / ".claude").mkdir()
    code = installer.main(["--list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "claude-code" in out
