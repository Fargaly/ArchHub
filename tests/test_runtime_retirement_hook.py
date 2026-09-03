from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _git_bash() -> str:
    # On a Windows runner a bare bash is WSL with no distribution; the hooks run under Git for Windows.
    import os, shutil
    if os.name == "nt":
        for candidate in ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe"):
            if Path(candidate).is_file():
                return candidate
    return shutil.which("bash") or "bash"


_BASH = _git_bash()


def _bash(repo: Path, command: str, *, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_BASH, "-lc", command],
        cwd=repo,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _bash_check(repo: Path, command: str) -> subprocess.CompletedProcess:
    result = _bash(repo, command)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def test_pre_commit_hooks_node_runtime_to_retirement_gate():
    hook = REPO / ".githooks" / "pre-commit"
    text = hook.read_text(encoding="utf-8")

    assert "STAGED_NODE_RUNTIME" in text
    assert "-- node_runtime" in text
    assert "tools/legacy_runtime_drain.py --no-write --enforce-retirement-gate" in text
    assert "COMMIT BLOCKED" in text
    assert "node_runtime retirement gate is red" in text


def test_pre_push_hooks_node_runtime_to_retirement_gate():
    hook = REPO / ".githooks" / "pre-push"
    text = hook.read_text(encoding="utf-8")

    assert "runtime_changes=$(git log --name-only" in text
    assert "node_runtime 2>/dev/null" in text
    assert "tools/legacy_runtime_drain.py --no-write --enforce-retirement-gate" in text
    assert "PUSH BLOCKED" in text
    assert "node_runtime retirement gate is red" in text


def _copy_hook_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _bash_check(repo, "git init")
    _bash_check(repo, "git config user.email test@example.invalid")
    _bash_check(repo, "git config user.name 'Hook Test'")
    (repo / ".githooks").mkdir()
    (repo / "tools").mkdir()
    for name in ("pre-commit", "pre-push"):
        shutil.copyfile(REPO / ".githooks" / name, repo / ".githooks" / name)
    # The hook now runs the public-privacy ratchet first and blocks when the
    # script is missing; these courts test the retirement gate, so the
    # fixture carries a ratchet that passes under the bash the tests use as
    # ARCHHUB_PYTHON.
    (repo / "tools" / "public_privacy_ratchet.py").write_text("exit 0" + chr(10), encoding="utf-8")
    (repo / "tools" / "legacy_runtime_drain.py").write_text(
        "echo '{\"retirement_gate\":{\"archive_allowed\":false}}'\n"
        "exit 2\n",
        encoding="utf-8",
    )
    return repo


def test_pre_commit_blocks_staged_node_runtime_when_retirement_gate_is_red(tmp_path):
    repo = _copy_hook_fixture(tmp_path)
    (repo / "node_runtime").mkdir()
    (repo / "node_runtime" / "marker.txt").write_text("legacy\n", encoding="utf-8")
    _bash_check(repo, "git add node_runtime/marker.txt")

    result = _bash(repo, "ARCHHUB_PYTHON=/bin/bash .githooks/pre-commit")

    assert result.returncode == 1
    assert "COMMIT BLOCKED - node_runtime retirement gate is red" in result.stderr


def test_pre_commit_allows_unrelated_staged_change_when_retirement_gate_is_red(tmp_path):
    repo = _copy_hook_fixture(tmp_path)
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    _bash_check(repo, "git add README.md")

    result = _bash(repo, "ARCHHUB_PYTHON=/bin/bash .githooks/pre-commit")

    assert result.returncode == 0


def test_pre_push_blocks_introduced_node_runtime_commit_when_retirement_gate_is_red(tmp_path):
    repo = _copy_hook_fixture(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _bash_check(repo, "git add README.md")
    _bash_check(repo, "git commit -m base")
    base_sha = _bash_check(repo, "git rev-parse HEAD").stdout.strip()
    (repo / "node_runtime").mkdir()
    (repo / "node_runtime" / "marker.txt").write_text("legacy\n", encoding="utf-8")
    _bash_check(repo, "git add node_runtime/marker.txt")
    _bash_check(repo, "git commit -m runtime")
    head_sha = _bash_check(repo, "git rev-parse HEAD").stdout.strip()
    stdin = f"refs/heads/main {head_sha} refs/heads/main {base_sha}\n"
    (repo / "push-stdin.txt").write_text(stdin, encoding="utf-8")

    result = _bash(repo, "ARCHHUB_PYTHON=/bin/bash .githooks/pre-push origin unused < push-stdin.txt")

    assert result.returncode == 1
    assert "PUSH BLOCKED - node_runtime retirement gate is red" in result.stderr
