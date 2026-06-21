"""Coverage-matrix + per-vendor wiring tests for the brain installer.

These pin the HONEST wiring contract the installer must keep:

  * Claude Code  → REAL native hooks (UserPromptSubmit/PostToolUse/Stop).
  * Cursor       → REAL Agent Hooks (beforeSubmitPrompt + stop) pointed at
                   brainwrap, PLUS mcpServers + rules — because Verify
                   confirmed hooks.json is real (https://cursor.com/docs/hooks).
  * Codex        → REAL hooks.json (UserPromptSubmit + Stop → brainwrap),
                   PLUS the config.toml mcp_servers.brain block — because
                   Confirm validated the hook surface verbatim
                   (https://developers.openai.com/codex/hooks). post-tool is
                   enforced-per-turn-flush: the Stop hook → brainwrap writes the
                   turn's memory to brain.write ONCE per turn (no per-tool hook).
  * Gemini CLI   → REAL settings.json hooks (per-turn BeforeAgent → context,
                   per-turn AfterAgent → stop, both brainwrap), PLUS
                   mcpServers — because Confirm validated them verbatim
                   (https://geminicli.com/docs/hooks/reference/). post-tool is
                   enforced-per-turn-flush: AfterAgent → brainwrap flushes the
                   turn's memory to brain.write ONCE per turn (no per-tool hook).
  * The HONESTY FLOOR that survives this upgrade: only Claude Code's post-tool
    write is PER-TOOL (enforced-by-hook). Every other vendor's post-tool write
    is enforced-per-turn-flush — a coarser, once-per-turn brain.write on the
    stop hook. The matrix prints every cell honestly and never claims per-tool
    parity for the foreign vendors.

Uses HOME redirection so nothing touches the real ~/.claude / ~/.cursor / etc.
"""
from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

import pytest

from personal_brain import installer


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    installer.ALL_PLANS["claude-code"].config_path = (
        tmp_path / ".claude" / "settings.json")
    installer.ALL_PLANS["cursor"].config_path = tmp_path / ".cursor" / "mcp.json"
    installer.ALL_PLANS["codex"].config_path = tmp_path / ".codex" / "config.toml"
    installer.ALL_PLANS["gemini-cli"].config_path = (
        tmp_path / ".gemini" / "settings.json")
    yield tmp_path


# ───────────────────────── Claude Code = REAL hooks ─────────────────────


def test_claude_code_gets_real_hooks_for_all_three_touchpoints(fake_home):
    (fake_home / ".claude").mkdir()
    installer.install_all(only=["claude-code"])
    cfg = json.loads(installer._claude_code_path().read_text())
    hooks = cfg["hooks"]
    # pre-prompt inject — brain.context was repointed at the hook-shaped wrapper
    # brain.hook_context (carries the typed `arguments` the bare hook lacked).
    assert any(e.get("tool") == "brain.hook_context"
               for e in hooks["UserPromptSubmit"])
    # post-tool write — brain.write was repointed at the hook-shaped wrapper
    # brain.observe (synthesizes the ADD WriteOp the bare hook couldn't).
    assert any(e.get("tool") == "brain.observe" for e in hooks["PostToolUse"])
    # stop-gate: the anti_laziness command gate is present
    stop = hooks["Stop"]
    assert any("anti_laziness_gate" in str(e.get("command", "")) for e in stop)
    # matrix agrees: all three enforced-by-hook
    m = installer.coverage_matrix(["claude-code"])["claude-code"]
    assert all(v == installer.ENFORCED for v in m.values())


def test_claude_code_still_has_mcpservers(fake_home):
    """The working Claude path must not regress its mcpServers entry."""
    (fake_home / ".claude").mkdir()
    installer.install_all(only=["claude-code"])
    cfg = json.loads(installer._claude_code_path().read_text())
    assert "brain" in cfg["mcpServers"]


# ───────────────────────── Cursor = REAL hooks (Verify) ─────────────────


def test_cursor_writes_real_hooks_json(fake_home):
    (fake_home / ".cursor").mkdir()
    installer.install_all(only=["cursor"])
    hooks_path = installer._cursor_hooks_path()
    assert hooks_path.exists(), "Cursor hooks.json must be written"
    hooks_cfg = json.loads(hooks_path.read_text())
    assert hooks_cfg.get("version") == 1
    hooks = hooks_cfg["hooks"]
    # Verify-confirmed schema: beforeSubmitPrompt (pre-prompt) + stop.
    assert "beforeSubmitPrompt" in hooks
    assert "stop" in hooks
    pre_cmd = hooks["beforeSubmitPrompt"][0]["command"]
    stop_cmd = hooks["stop"][0]["command"]
    assert "brainwrap" in pre_cmd and "context" in pre_cmd
    assert "brainwrap" in stop_cmd and "stop" in stop_cmd


def test_cursor_keeps_mcpservers_and_rules(fake_home):
    (fake_home / ".cursor").mkdir()
    installer.install_all(only=["cursor"])
    cfg = json.loads(installer._cursor_path().read_text())
    assert "brain" in cfg["mcpServers"]
    rules = installer._cursor_rules_path()
    assert rules.exists()
    assert "brain.context" in rules.read_text()


def test_cursor_hooks_idempotent(fake_home):
    (fake_home / ".cursor").mkdir()
    installer.install_all(only=["cursor"])
    installer.install_all(only=["cursor"])
    hooks = json.loads(installer._cursor_hooks_path().read_text())["hooks"]
    # exactly one brainwrap entry per hook, not duplicated
    for name in ("beforeSubmitPrompt", "stop"):
        brain_entries = [e for e in hooks[name]
                         if "brainwrap" in str(e.get("command", ""))]
        assert len(brain_entries) == 1


def test_cursor_hooks_preserve_user_entries(fake_home):
    (fake_home / ".cursor").mkdir()
    hooks_path = installer._cursor_hooks_path()
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps({
        "version": 1,
        "hooks": {"beforeSubmitPrompt": [{"command": "./my/audit.sh"}]},
    }))
    installer.install_all(only=["cursor"])
    hooks = json.loads(hooks_path.read_text())["hooks"]
    cmds = [e.get("command") for e in hooks["beforeSubmitPrompt"]]
    assert "./my/audit.sh" in cmds  # user entry preserved
    assert any("brainwrap" in c for c in cmds)  # brain entry added


def test_cursor_uninstall_removes_only_brain_hook(fake_home):
    (fake_home / ".cursor").mkdir()
    hooks_path = installer._cursor_hooks_path()
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps({
        "version": 1,
        "hooks": {"beforeSubmitPrompt": [{"command": "./my/audit.sh"}]},
    }))
    installer.install_all(only=["cursor"])
    installer.uninstall_all(only=["cursor"])
    hooks = json.loads(hooks_path.read_text()).get("hooks", {})
    cmds = [e.get("command") for e in hooks.get("beforeSubmitPrompt", [])]
    assert "./my/audit.sh" in cmds
    assert not any("brainwrap" in (c or "") for c in cmds)


# ───────────────── Codex = REAL hooks.json (Confirm) ─────────────────────


def test_codex_writes_real_hooks_json_with_confirmed_schema(fake_home):
    """Codex hooks.json (Confirmed: developers.openai.com/codex/hooks) wires
    UserPromptSubmit → brainwrap context and Stop → brainwrap stop, in the
    verbatim `{"hooks": {"<Event>": [{"hooks": [{"type":"command",...}]}]}}`
    shape."""
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    hooks_path = installer._codex_hooks_path()
    assert hooks_path.exists(), "Codex hooks.json must be written"
    cfg = json.loads(hooks_path.read_text())
    hooks = cfg["hooks"]
    # Confirmed events present.
    assert "UserPromptSubmit" in hooks
    assert "Stop" in hooks
    # Confirmed nesting: event → [group] → group["hooks"] → [command hook].
    pre_hook = hooks["UserPromptSubmit"][0]["hooks"][0]
    stop_hook = hooks["Stop"][0]["hooks"][0]
    assert pre_hook["type"] == "command"
    assert "brainwrap" in pre_hook["command"] and "context" in pre_hook["command"]
    assert "brainwrap" in stop_hook["command"] and "stop" in stop_hook["command"]
    # Stop carries the 30s (SECONDS) budget like the Claude gate.
    assert stop_hook["timeout"] == 30
    # matrix: pre-prompt + stop enforced-by-hook; post-tool is now the
    # per-turn flush the Stop hook performs (NOT docs-only, NOT per-tool).
    m = installer.coverage_matrix(["codex"])["codex"]
    assert m["pre_prompt_inject"] == installer.ENFORCED
    assert m["stop_gate"] == installer.ENFORCED
    assert m["post_tool_write"] == installer.PER_TURN


def test_codex_keeps_config_toml_mcp_block(fake_home):
    """The hook upgrade must not drop the config.toml mcp_servers.brain block
    (still needed so Codex can call brain tools directly)."""
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    text = installer._codex_path().read_text()
    assert "[mcp_servers.brain]" in text
    assert "personal-brain-mcp" in text


def test_codex_hooks_idempotent(fake_home):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    installer.install_all(only=["codex"])
    cfg = json.loads(installer._codex_hooks_path().read_text())
    hooks = cfg["hooks"]
    for event in ("UserPromptSubmit", "Stop"):
        brain_groups = [g for g in hooks[event]
                        if any("brainwrap" in str(h.get("command", ""))
                               for h in g.get("hooks", []))]
        assert len(brain_groups) == 1, f"{event} brain hook must dedupe"
    # config.toml block also stays single.
    assert installer._codex_path().read_text().count("[mcp_servers.brain]") == 1


def test_codex_hooks_preserve_user_entries(fake_home):
    (fake_home / ".codex").mkdir()
    hooks_path = installer._codex_hooks_path()
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps({
        "hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "./my/audit.sh"}]}]},
    }))
    installer.install_all(only=["codex"])
    hooks = json.loads(hooks_path.read_text())["hooks"]
    all_cmds = [h.get("command")
                for g in hooks["UserPromptSubmit"] for h in g.get("hooks", [])]
    assert "./my/audit.sh" in all_cmds       # user entry preserved
    assert any("brainwrap" in (c or "") for c in all_cmds)  # brain added


def test_codex_uninstall_removes_hook_and_block(fake_home):
    (fake_home / ".codex").mkdir()
    # Seed a user hook that must survive uninstall.
    hooks_path = installer._codex_hooks_path()
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps({
        "hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "./my/audit.sh"}]}]},
    }))
    installer.install_all(only=["codex"])
    installer.uninstall_all(only=["codex"])
    # config.toml block gone.
    assert "[mcp_servers.brain]" not in installer._codex_path().read_text()
    # brain hook gone but user hook preserved.
    hooks = json.loads(hooks_path.read_text()).get("hooks", {})
    cmds = [h.get("command")
            for g in hooks.get("UserPromptSubmit", []) for h in g.get("hooks", [])]
    assert "./my/audit.sh" in cmds
    assert not any("brainwrap" in (c or "") for c in cmds)


# ───────────────── Gemini = REAL settings.json hooks (Confirm) ────────────


def test_gemini_writes_real_hooks_with_confirmed_events(fake_home):
    """Gemini hooks (Confirmed: geminicli.com/docs/hooks/reference) wire the
    per-turn BeforeAgent → brainwrap context and per-turn AfterAgent →
    brainwrap stop, in the `{event: [{matcher, hooks:[{type,command}]}]}`
    shape — alongside the preserved mcpServers entry."""
    (fake_home / ".gemini").mkdir()
    installer.install_all(only=["gemini-cli"])
    cfg = json.loads(installer._gemini_path().read_text())
    assert "brain" in cfg["mcpServers"]      # mcpServers preserved
    hooks = cfg["hooks"]
    assert "BeforeAgent" in hooks            # per-turn context inject
    assert "AfterAgent" in hooks             # per-turn stop (final response)
    pre_hook = hooks["BeforeAgent"][0]["hooks"][0]
    stop_hook = hooks["AfterAgent"][0]["hooks"][0]
    assert pre_hook["type"] == "command"
    assert "brainwrap" in pre_hook["command"] and "context" in pre_hook["command"]
    assert "brainwrap" in stop_hook["command"] and "stop" in stop_hook["command"]
    # matrix: pre-prompt + stop enforced-by-hook; post-tool is now the per-turn
    # flush AfterAgent → brainwrap performs (NOT docs-only, NOT per-tool).
    m = installer.coverage_matrix(["gemini-cli"])["gemini-cli"]
    assert m["pre_prompt_inject"] == installer.ENFORCED
    assert m["stop_gate"] == installer.ENFORCED
    assert m["post_tool_write"] == installer.PER_TURN


def test_gemini_hooks_idempotent(fake_home):
    (fake_home / ".gemini").mkdir()
    installer.install_all(only=["gemini-cli"])
    installer.install_all(only=["gemini-cli"])
    hooks = json.loads(installer._gemini_path().read_text())["hooks"]
    for event in ("BeforeAgent", "AfterAgent"):
        brain_groups = [g for g in hooks[event]
                        if any("brainwrap" in str(h.get("command", ""))
                               for h in g.get("hooks", []))]
        assert len(brain_groups) == 1, f"{event} brain hook must dedupe"


def test_gemini_hooks_preserve_user_entries(fake_home):
    (fake_home / ".gemini").mkdir()
    path = installer._gemini_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "hooks": {"BeforeAgent": [
            {"hooks": [{"type": "command", "command": "./my/audit.sh"}]}]},
    }))
    installer.install_all(only=["gemini-cli"])
    hooks = json.loads(path.read_text())["hooks"]
    cmds = [h.get("command")
            for g in hooks["BeforeAgent"] for h in g.get("hooks", [])]
    assert "./my/audit.sh" in cmds                      # user entry preserved
    assert any("brainwrap" in (c or "") for c in cmds)  # brain added


def test_gemini_uninstall_removes_hooks_and_server(fake_home):
    (fake_home / ".gemini").mkdir()
    path = installer._gemini_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "hooks": {"AfterAgent": [
            {"hooks": [{"type": "command", "command": "./my/audit.sh"}]}]},
    }))
    installer.install_all(only=["gemini-cli"])
    installer.uninstall_all(only=["gemini-cli"])
    cfg = json.loads(path.read_text())
    assert "brain" not in cfg.get("mcpServers", {})
    cmds = [h.get("command")
            for g in cfg.get("hooks", {}).get("AfterAgent", [])
            for h in g.get("hooks", [])]
    assert "./my/audit.sh" in cmds
    assert not any("brainwrap" in (c or "") for c in cmds)


# ───────────────────────── matrix invariants ────────────────────────────


def test_every_non_claude_vendor_has_mcpservers_plus_wrapper_or_hook():
    """Spec: Claude=hooks; every OTHER vendor = at least mcpServers + wrapper.

    Assert at the matrix level that no non-Claude vendor is left with all
    three touchpoints as bare docs-only (i.e. each carries a real wrapper or
    hook somewhere)."""
    matrix = installer.coverage_matrix()
    assert set(matrix["claude-code"].values()) == {installer.ENFORCED}
    for vendor, cells in matrix.items():
        if vendor == "claude-code":
            continue
        states = set(cells.values())
        assert states & {installer.ENFORCED, installer.PER_TURN,
                         installer.WRAPPER}, (
            f"{vendor} has no real wiring (all docs-only) — spec requires "
            f"at least mcpServers + brainwrap wrapper")


def test_enforced_cells_have_doc_url():
    """Any vendor with a hook-backed cell (per-tool ENFORCED or per-turn-flush)
    must cite a real doc URL — no auto-fire claim without Confirm-backed proof.
    Both states are driven by a verified vendor hook, so both demand the URL."""
    matrix = installer.coverage_matrix()
    for vendor, cells in matrix.items():
        if any(s in (installer.ENFORCED, installer.PER_TURN)
               for s in cells.values()):
            assert vendor in installer.HOOK_DOC_URLS
            assert installer.HOOK_DOC_URLS[vendor].startswith("http")


def test_codex_and_gemini_post_tool_is_per_turn_flush_with_urls():
    """Codex + Gemini keep pre-prompt + stop enforced-by-hook (per-tool), and
    their post-tool write is now enforced-per-turn-flush — the Stop/AfterAgent
    hook → brainwrap writes the turn's memory to brain.write ONCE per turn. It
    is explicitly NOT upgraded to per-tool ENFORCED (that would be false parity
    with Claude Code, which writes the brain after EVERY tool call)."""
    matrix = installer.coverage_matrix()
    for vendor, url_frag in (("codex", "developers.openai.com/codex/hooks"),
                             ("gemini-cli", "geminicli.com/docs/hooks")):
        cells = matrix[vendor]
        assert cells["pre_prompt_inject"] == installer.ENFORCED
        assert cells["stop_gate"] == installer.ENFORCED
        assert cells["post_tool_write"] == installer.PER_TURN
        # the honesty floor: NOT marked per-tool ENFORCED.
        assert cells["post_tool_write"] != installer.ENFORCED
        assert url_frag in installer.HOOK_DOC_URLS[vendor]


def test_post_tool_write_only_claude_is_per_tool():
    """Honesty floor after the per-turn-flush change: ONLY Claude Code's
    post-tool write is per-tool (ENFORCED). Every foreign vendor's post-tool
    write is enforced-per-turn-flush — hook-backed but coarser, never claiming
    Claude's per-tool granularity. This is the cell that keeps the matrix from
    asserting false parity."""
    matrix = installer.coverage_matrix()
    for vendor, cells in matrix.items():
        if vendor == "claude-code":
            assert cells["post_tool_write"] == installer.ENFORCED
        else:
            assert cells["post_tool_write"] == installer.PER_TURN
            assert cells["post_tool_write"] != installer.ENFORCED


def test_matrix_never_claims_per_tool_parity_for_foreign_vendors():
    """Honesty floor (updated for the per-turn flush): every cell may now be
    hook-backed, so the OLD floor ('at least one non-hook cell') no longer
    applies. The truthful floor is sharper — no FOREIGN vendor's post-tool
    write may be the per-tool ENFORCED state. Claude alone owns per-tool
    brain.write; the rest are honestly the coarser per-turn flush."""
    matrix = installer.coverage_matrix()
    foreign_post = [cells["post_tool_write"]
                    for v, cells in matrix.items() if v != "claude-code"]
    assert foreign_post, "expected at least one non-Claude vendor"
    assert all(s == installer.PER_TURN for s in foreign_post), (
        "foreign vendors' post-tool write must be enforced-per-turn-flush")
    assert all(s != installer.ENFORCED for s in foreign_post), (
        "matrix must NOT claim per-tool parity with Claude for any foreign "
        "vendor — that would be the false-parity lie the 4th state prevents")
    # And the two enforced states are distinct labels (no silent collapse).
    assert installer.ENFORCED != installer.PER_TURN


def test_print_coverage_matrix_outputs_all_vendors_and_states():
    buf = io.StringIO()
    returned = installer.print_coverage_matrix(stream=buf)
    out = buf.getvalue()
    # prints a row for every vendor
    for vendor in installer.COVERAGE_MATRIX:
        assert vendor in out
    # prints the FOUR honest state words + the three touchpoint headers
    assert installer.ENFORCED in out
    assert installer.PER_TURN in out
    assert installer.WRAPPER in out
    assert installer.DOCS in out
    assert "pre-prompt inject" in out
    assert "post-tool write" in out
    assert "stop-gate" in out
    # cites Cursor's real-hook doc URL as proof
    assert "cursor.com/docs/hooks" in out
    # the legend must DISCLOSE the per-turn-flush caveat so no reader infers
    # per-tool parity with Claude Code (honest, not false, parity).
    low = out.lower()
    assert "per tool" in low          # Claude's per-tool granularity named
    assert "once per turn" in low     # the foreign-vendor flush cadence named
    assert "coarser" in low           # the explicit "not the same" disclosure
    # returns the same matrix it printed
    assert returned == installer.coverage_matrix()


def test_main_matrix_flag_prints(capsys):
    code = installer.main(["--matrix"])
    out = capsys.readouterr().out
    assert code == 0
    assert "coverage" in out.lower()
    assert "claude-code" in out and "cursor" in out


def test_install_run_prints_matrix(fake_home, capsys):
    (fake_home / ".claude").mkdir()
    code = installer.main(["--only", "claude-code"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Install results:" in out
    # the honest matrix is appended after the install results
    assert installer.ENFORCED in out
    assert "legend:" in out
