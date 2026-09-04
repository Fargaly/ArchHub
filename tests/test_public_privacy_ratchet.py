from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import public_privacy_ratchet as ratchet  # noqa: E402


def _init_git_repo(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)


def test_public_private_identifier_debt_is_shrink_only():
    policy = ratchet.default_policy_path()
    if not policy.is_file():
        pytest.skip("private privacy policy is not present in this environment")
    report = ratchet.scan_public_tree(policy_path=policy)

    assert report["policy_storage"] == "private"
    assert report["file_count"] <= report["baseline_file_count"], (
        "Public private-identifier debt widened. Run the private audit in "
        "30.KNOWLEDGE/strategy/courts before changing the public tree."
    )
    assert report["hit_count"] <= report["baseline_hit_count"], (
        "Public private-identifier occurrence count widened. Replace new "
        "examples with neutral synthetic project placeholders."
    )


def test_public_privacy_ratchet_scans_synthetic_private_policy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "example.txt").write_text(
        "PROJECT-SECRET\n",
        encoding="utf-8",
    )
    _init_git_repo(repo)
    policy = tmp_path / "policy.private.json"
    policy.write_text(
        json.dumps({
            "schema": "archhub-public-privacy-ratchet-policy/v1",
            "baseline_file_count": 1,
            "baseline_hit_count": 1,
            "identifiers": ["PROJECT-SECRET"],
        }),
        encoding="utf-8",
    )

    report = ratchet.scan_public_tree(repo, policy_path=policy)

    assert report["ok"] is True
    assert report["file_count"] == 1
    assert report["hit_count"] == 1
    assert report["files"][0]["path"] == "example.txt"


def test_public_privacy_ratchet_cli_reports_current_baseline(capsys, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "example.txt").write_text("PROJECT-SECRET\n", encoding="utf-8")
    _init_git_repo(repo)
    policy = tmp_path / "policy.private.json"
    policy.write_text(
        json.dumps({
            "baseline_file_count": 1,
            "baseline_hit_count": 1,
            "identifiers": ["PROJECT-SECRET"],
        }),
        encoding="utf-8",
    )

    assert ratchet.main(["--repo", str(repo), "--policy", str(policy)]) == 0
    output = capsys.readouterr().out
    assert "[public-privacy-ratchet]" in output
    assert "files=" in output
    assert "hits=" in output


def test_public_privacy_ratchet_fails_when_private_policy_is_missing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    assert ratchet.main(["--repo", str(repo), "--policy", str(tmp_path / "missing.json")]) == 1


def test_public_privacy_ratchet_is_wired_to_local_hooks():
    pre_commit = (ratchet.REPO / ".githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    pre_push = (ratchet.REPO / ".githooks" / "pre-push").read_text(
        encoding="utf-8"
    )

    for hook in (pre_commit, pre_push):
        assert "tools/public_privacy_ratchet.py" in hook
        assert "python unavailable; blocking" in hook
        assert "gate script missing; blocking" in hook


def test_default_policy_lives_outside_public_product_tree():
    policy = ratchet.default_policy_path()

    assert ratchet.REPO not in policy.parents
    assert "30.KNOWLEDGE" in str(policy)
