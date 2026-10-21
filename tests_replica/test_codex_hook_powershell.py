"""Court: the Codex hook command ArchHub writes runs under PowerShell for any path.

Codex runs a hook command through PowerShell (codex shell-command/src/powershell.rs:
pwsh -NoProfile -Command with a UTF-8 output-encoding prefix). There a command that
starts with a quoted path is a ParserError, so the rendered command must call it."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nodelang import session_link_config as config

pytestmark = pytest.mark.skipif(os.name != "nt" or not shutil.which("pwsh"),
                                reason="Codex hooks run through Windows PowerShell")

_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
_WRITES_MARKER = ("import pathlib, sys\n"
                  "pathlib.Path(__file__).with_name('ran.txt').write_text(' '.join(sys.argv[1:]))\n")


def _codex_runs(command, cwd):
    """Execute a hook command the way Codex's hook runner does."""
    return subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", _PREFIX + command],
                          input="{}", capture_output=True, text=True, timeout=60, cwd=cwd)


@pytest.fixture(params=["ArchHub", "Arch Hub With Space"], ids=["no-space", "with-space"])
def installed(request, tmp_path):
    """A real installed layout: a venv interpreter and a stop script that writes a marker."""
    root = tmp_path / request.param
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")],
                   check=True, capture_output=True, timeout=120)
    script = root / "nodelang" / "native_stop_hook.py"
    script.parent.mkdir(parents=True)
    script.write_text(_WRITES_MARKER, encoding="utf-8")
    gate = root / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"
    gate.parent.mkdir(parents=True)
    gate.write_text(_WRITES_MARKER, encoding="utf-8")
    (root / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    return root


def _old_wrapper(command):
    """The spelling f9241c2 wrote: the same command without the call operator."""
    return command[2:] if command.startswith("& ") else command


def test_rendered_codex_stop_hook_starts_the_installed_script(installed):
    command = config.render_stop_hook("codex", install_root=installed)["Stop"][0]["hooks"][0]["command"]
    marker = installed / "nodelang" / "ran.txt"
    old = _codex_runs(_old_wrapper(command), installed)
    assert old.returncode != 0 and not marker.exists()  # the wrapper Ping hand-corrected
    ran = _codex_runs(command, installed)
    assert ran.returncode == 0, ran.stderr
    assert marker.read_text() == "--vendor codex"


def test_rendered_codex_tool_hooks_start_the_gate(installed):
    python = installed / ".venv" / "Scripts" / "python.exe"
    gate = installed / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"
    managed = config.render_client_hooks("codex", python_executable=python,
                                        gate_script=gate, install_root=installed)
    marker = gate.with_name("ran.txt")
    for event in ("PreToolUse", "PostToolUse"):
        command = managed[event][0]["hooks"][0]["command"]
        marker.unlink(missing_ok=True)
        ran = _codex_runs(command, installed)
        assert ran.returncode == 0, ran.stderr
        assert marker.read_text() == "--vendor codex"
        # Parser identity: the call operator names the same interpreter and script.
        assert config._hook_command_parts(managed[event][0]["hooks"][0]) == (
            python.as_posix(), gate.as_posix(), ("--vendor", "codex"))


def test_a_quoted_codex_stop_entry_is_repaired_and_the_hand_fix_is_kept(installed):
    managed = config.render_stop_hook("codex", install_root=installed)
    desired = managed["Stop"][0]["hooks"][0]["command"]
    quoted = {"type": "command", "command": _old_wrapper(desired), "timeout": 30}
    settings, binding, _ = config.merge_stop_hook({"hooks": {"Stop": [{"hooks": [quoted]}]}},
                                                  managed, vendor="codex", install_root=installed)
    assert binding == "ours"
    assert [h["command"] for h in settings["hooks"]["Stop"][0]["hooks"]] == [desired]
    python = (installed / ".venv" / "Scripts" / "python.exe").as_posix()
    if " " not in python:
        # Ping's live hand fix: bare interpreter path, quoted script. It runs; keep it.
        hand = {"type": "command", "timeout": 30,
                "command": python + ' "' + (installed / "nodelang" / "native_stop_hook.py").as_posix()
                           + '" --vendor codex'}
        existing = {"hooks": {"Stop": [{"hooks": [hand]}]}}
        kept, _, _ = config.merge_stop_hook(existing, managed, vendor="codex", install_root=installed)
        assert json.dumps(kept) == json.dumps(existing)


def test_claude_rendering_is_unchanged(installed):
    # Claude Code runs hooks under Git Bash, where the call operator never works; Gemini
    # CLI runs them under PowerShell and is courted by the Gemini test below.
    command = config.render_stop_hook("claude-code", install_root=installed)["Stop"][0]["hooks"][0]["command"]
    assert command.startswith('"') and not command.startswith("&")
    claude = {"type": "command", "command": config.render_stop_hook(
        "codex", install_root=installed)["Stop"][0]["hooks"][0]["command"]}
    assert config._claude_bash_broken(claude, "claude-code")  # `&` never works under Git Bash

def test_rendered_gemini_stop_hook_starts_the_installed_script(installed):
    # Gemini CLI on Windows runs hooks through PowerShell too: the quoted spelling was a
    # ParserError on every AfterAgent (field evidence 2026-10-15).
    command = config.render_stop_hook("gemini-cli", install_root=installed)["AfterAgent"][0]["hooks"][0]["command"]
    assert command.startswith("& ")
    marker = installed / "nodelang" / "ran.txt"
    old = _codex_runs(_old_wrapper(command), installed)
    assert old.returncode != 0 and not marker.exists()
    ran = _codex_runs(command, installed)
    assert ran.returncode == 0, ran.stderr
    assert marker.read_text() == "--vendor gemini"

def test_an_installed_quoted_gemini_stop_entry_is_repaired_by_merge_and_runs(installed):
    # Ping RETURN on GEMHOOK: the renderer alone left the already-installed quoted
    # AfterAgent hook in place, because the merge judged it a healthy equivalent.
    managed = config.render_stop_hook("gemini-cli", install_root=installed)
    desired = managed["AfterAgent"][0]["hooks"][0]["command"]
    quoted = {"type": "command", "name": "archhub-stop-followup", "command": _old_wrapper(desired),
              "timeout": 41}
    theirs = {"type": "command", "command": "someone-elses-hook --keep", "timeout": 5}
    existing = {"hooks": {"AfterAgent": [{"matcher": "*", "hooks": [quoted, theirs]}]}, "theme": "x"}
    settings, binding, _ = config.merge_stop_hook(existing, managed, vendor="gemini-cli",
                                                  install_root=installed)
    assert binding == "ours"
    group = settings["hooks"]["AfterAgent"][0]
    assert group["matcher"] == "*" and settings["theme"] == "x"
    assert group["hooks"] == [{**quoted, "command": desired}, theirs]  # only the command changed
    marker = installed / "nodelang" / "ran.txt"
    ran = _codex_runs(group["hooks"][0]["command"], installed)
    assert ran.returncode == 0, ran.stderr
    assert marker.read_text() == "--vendor gemini"
    again, _, _ = config.merge_stop_hook(settings, managed, vendor="gemini-cli", install_root=installed)
    assert json.dumps(again) == json.dumps(settings)  # idempotent


def test_quoted_gemini_tool_hooks_are_repaired_by_merge_and_a_bare_hand_fix_is_kept(installed):
    python = installed / ".venv" / "Scripts" / "python.exe"
    gate = installed / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"
    managed = config.render_client_hooks("gemini-cli", python_executable=python,
                                        gate_script=gate, install_root=installed)
    marker = gate.with_name("ran.txt")
    for event in ("BeforeTool", "AfterTool"):
        desired = managed[event][0]["hooks"][0]["command"]
        quoted = {"type": "command", "name": "archhub-scope", "command": _old_wrapper(desired), "timeout": 30000}
        existing = {"hooks": {event: [{"matcher": ".*", "hooks": [quoted]}]}}
        after = config.merge_client_hooks(existing, managed, vendor="gemini-cli", known_owned_commands=())
        assert after["hooks"][event] == [{"matcher": ".*", "hooks": [{**quoted, "command": desired}]}]
        marker.unlink(missing_ok=True)
        ran = _codex_runs(desired, installed)
        assert ran.returncode == 0, ran.stderr
        assert marker.read_text() == "--vendor gemini"
        if " " not in python.as_posix():
            # The live hand spelling: bare paths, no quotes. It runs under PowerShell; keep it.
            hand = {"type": "command", "command": python.as_posix() + " " + gate.as_posix() + " --vendor gemini"}
            kept_in = {"hooks": {event: [{"matcher": ".*", "hooks": [hand]}]}}
            kept = config.merge_client_hooks(kept_in, managed, vendor="gemini-cli", known_owned_commands=())
            assert json.dumps(kept["hooks"][event]) == json.dumps(kept_in["hooks"][event])  # the other event gains only its own managed hook
