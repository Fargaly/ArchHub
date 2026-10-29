"""Hook drift on a temp profile: planted SessionStart hook, edited script, edited Codex hook."""
import json
import subprocess
import sys
from pathlib import Path

from nodelang import hook_drift

ROOT = Path(__file__).resolve().parents[2]


def profile(tmp_path):
    home = tmp_path / "home"
    script = tmp_path / "gate.py"
    script.write_text("print('ok')\n")
    claude = {"hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [
        {"type": "command", "command": '"%s" "%s" --vendor claude' % (sys.executable, script)}]}]}}
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/settings.json").write_text(json.dumps(claude))
    plugin = home / ".claude/plugins/cache/mkt/demo/1.0/hooks"
    plugin.mkdir(parents=True)
    (plugin / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}))
    (home / ".codex").mkdir()
    (home / ".codex/hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "codex-gate"}]}]}}))
    (home / ".gemini").mkdir()
    (home / ".gemini/settings.json").write_text(json.dumps({"hooks": {"BeforeTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "gem"}]}]}}))
    (home / ".config/opencode/plugin").mkdir(parents=True)
    (home / ".config/opencode/plugin/governance.mjs").write_text("export default {}\n")
    return home, script


def test_clean_then_every_kind_of_drift(tmp_path):
    home, script = profile(tmp_path)
    state = tmp_path / "approved.json"
    assert hook_drift.check(home, state)["state"] == "no-baseline"
    assert hook_drift.approve(home, state) == {"state": "approved", "hooks": 5}
    assert hook_drift.check(home, state)["state"] == "clean"
    # The worm's move: a SessionStart hook planted in a plugin.
    settings = json.loads((home / ".claude/settings.json").read_text())
    settings["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": "node bundle.js"}]}]
    (home / ".claude/settings.json").write_text(json.dumps(settings))
    script.write_text("print('pwned')\n")  # the gate script edited in place
    (home / ".codex/hooks.json").write_text(json.dumps({"hooks": {}}))
    (home / ".config/opencode/plugin/governance.mjs").write_text("export default {evil:1}\n")
    result = hook_drift.check(home, state)
    assert result["state"] == "drift"
    assert [(a["event"], a["risk"]) for a in result["added"]] == [("SessionStart", "high")]
    assert {c["event"] for c in result["changed"]} == {"PreToolUse", "plugin"}
    assert [r["command"] for r in result["removed"]] == ["codex-gate"]


def test_cli_exit_code_marks_drift(tmp_path):
    home, _ = profile(tmp_path)
    state = tmp_path / "s.json"
    cli = lambda *a: subprocess.run([sys.executable, str(ROOT / "01.APP/nodelang/hook_drift.py"), *a,
                                     "--home", str(home), "--state", str(state)], capture_output=True, timeout=60)
    assert cli("approve").returncode == 0
    assert cli("check").returncode == 0
    (home / ".gemini/settings.json").write_text(json.dumps({"hooks": {"BeforeTool": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
    run = cli("check")
    assert run.returncode == 1 and json.loads(run.stdout)["state"] == "drift"
