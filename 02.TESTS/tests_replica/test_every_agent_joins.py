"""Court F177: every installed agent joins with the same rules; none gets the refusal line.

Each client runs the real onboarding entry (python -m nodelang.agent_onboard <client>) against
an isolated profile that holds only that client's own config folder."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nodelang import agent_onboard, model_execution_broker
from nodelang.native_agent_hooks import install_cursor_hook_entries, plain_hook_command

APP = Path(agent_onboard.__file__).resolve().parents[1]
REFUSAL = "Installed governance adapter unavailable"
SPEC_LINE = (APP.parent / "04.DOCS" / "SPEC.md").read_text(encoding="utf-8").strip().splitlines()[0]

CASES = [  # runtime name, client folder in the profile, instruction file it must read
    ("cursor", ".cursor", ".cursor/rules/archhub-product.mdc"),
    ("cursor-agent", ".cursor", ".cursor/rules/archhub-product.mdc"),
    ("antigravity", ".gemini", ".gemini/GEMINI.md"),
    ("opencode", ".config/opencode", ".config/opencode/AGENTS.md"),
    ("goose", ".config/goose", ".config/goose/.goosehints"),
    ("kiro", ".kiro", ".kiro/AGENTS.md"),  # no row: the generic path
]


def _join(name, home):
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home),
           "PYTHONPATH": str(APP) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    return subprocess.run([sys.executable, "-m", "nodelang.agent_onboard", name], cwd=str(APP), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("name,folder,rules", CASES, ids=[case[0] for case in CASES])
def test_agent_joins_with_rules_and_plain_gate_words(isolated_profile, name, folder, rules):
    (isolated_profile / folder).mkdir(parents=True)
    done = _join(name, isolated_profile)
    assert done.returncode == 0, done.stdout + done.stderr
    assert REFUSAL not in done.stdout + done.stderr
    target = isolated_profile / rules
    assert ("product rules saved to %s" % target) in done.stdout
    text = target.read_text(encoding="utf-8")
    assert text.count(agent_onboard.BEGIN) == 1 and SPEC_LINE in text
    assert "it cannot run: " + agent_onboard.GATES in done.stdout  # said plainly, never a silent gap
    if rules.endswith(".mdc"):
        assert text.startswith("---\n") and "alwaysApply: true" in text.split("---")[1]
    again = _join(name, isolated_profile)
    assert again.returncode == 0 and target.read_text(encoding="utf-8") == text  # idempotent


def test_unknown_agent_without_a_folder_still_joins_and_points_at_the_rules(isolated_profile):
    done = _join("brand-new-agent", isolated_profile)
    assert done.returncode == 0, done.stderr
    assert REFUSAL not in done.stdout
    assert "product rules not saved (agent configuration directory is absent)" in done.stdout
    assert "SPEC.md" in done.stdout and "it cannot run: " + agent_onboard.GATES in done.stdout
    assert not (isolated_profile / ".brand-new-agent").exists()


def test_unsafe_agent_names_are_refused_before_any_path_is_built(isolated_profile):
    for name in ("../evil", "a/b", ""):
        done = _join(name, isolated_profile)
        assert done.returncode == 2 and "usage:" in done.stdout


def test_user_rules_in_the_file_stay(isolated_profile):
    goose = isolated_profile / ".config/goose"
    goose.mkdir(parents=True)
    (goose / ".goosehints").write_text("My own goose hints.\n", encoding="utf-8")
    assert _join("goose", isolated_profile).returncode == 0
    assert (goose / ".goosehints").read_text(encoding="utf-8").startswith("My own goose hints.\n")


# --- FAULT B: hook command lines run under Git Bash and PowerShell; cursor-agent children lose Git Bash markers.

def _shells():
    git_bash = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe")
    bash = git_bash if os.path.isfile(git_bash) else shutil.which("bash") or ""  # never WSL's System32 bash
    pwsh = shutil.which("pwsh")
    if not (os.path.isfile(bash) and pwsh):
        pytest.skip("needs Git Bash and PowerShell 7")
    return bash, pwsh


def test_generated_cursor_hook_line_runs_under_bash_and_pwsh(tmp_path):
    bash, pwsh = _shells()
    script = tmp_path / "native_stop_hook.py"
    marker = tmp_path / "ran.txt"
    script.write_text("import pathlib, sys\npathlib.Path(__file__).with_name('ran.txt')"
                      ".write_text(' '.join(sys.argv[1:]) + '|' + sys.stdin.read())\n", encoding="utf-8")
    command = plain_hook_command(sys.executable, script, "--vendor", "cursor")
    assert "\\" not in command and not command.startswith(("\"", "&"))
    for shell in ([bash, "-c", command], [pwsh, "-NoProfile", "-Command", command]):
        marker.unlink(missing_ok=True)
        ran = subprocess.run(shell, input="{}", capture_output=True, text=True, timeout=60)
        assert ran.returncode == 0, (shell[0], ran.stderr)
        assert marker.read_text() == "--vendor cursor|{}", shell[0]


def test_cursor_hook_install_rewrites_the_old_quoted_spelling_in_place(tmp_path):
    old = '"C:\\Python\\python.exe" "C:\\App\\nodelang\\native_stop_hook.py" --vendor cursor'
    hooks = tmp_path / ".cursor" / "hooks.json"
    hooks.parent.mkdir()
    import json
    hooks.write_text(json.dumps({"version": 1, "hooks": {
        "stop": [{"command": "guard"}, {"command": old, "loop_limit": 5}],
        "beforeSubmitPrompt": [{"command": old}]}}), encoding="utf-8")
    new = plain_hook_command("C:/Python/python.exe", "C:/App/nodelang/native_stop_hook.py", "--vendor", "cursor")
    install_cursor_hook_entries(tmp_path, new)
    data = json.loads(hooks.read_text(encoding="utf-8"))
    assert data["hooks"]["stop"] == [{"command": "guard"}, {"command": new, "loop_limit": 5}]
    assert data["hooks"]["beforeSubmitPrompt"] == [{"command": new}]


def test_cursor_agent_child_runs_without_git_bash_markers(monkeypatch):
    monkeypatch.setenv("MSYSTEM", "MINGW64")
    monkeypatch.setenv("EXEPATH", r"C:\Program Files\Git\bin")
    monkeypatch.setenv("SHELL", r"C:\Program Files\Git\bin\bash.exe")
    env = model_execution_broker.launch_environment([r"C:\x\cursor-agent.cmd", "-p"])
    assert not {"MSYSTEM", "EXEPATH", "SHELL"} & {key.upper() for key in env}
    assert env["USERPROFILE"] == os.environ["USERPROFILE"]
    assert model_execution_broker.launch_environment(["claude", "-p"]) is None
