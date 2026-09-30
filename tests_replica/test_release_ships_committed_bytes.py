"""Court: an installed build carries exactly what Git holds, and nothing retired.

(a) installer/build_release.ps1 snapshots checkout bytes. Under
    `* text=auto eol=lf` a CRLF working copy of an LF blob reads as unchanged
    to `git diff`, so a release shipped CRLF bytes whose sha256 matched no
    committed blob (cell_value_graph.py, studio/mount.jsx on 2026-10-01).
    The snapshot now refuses any clean tracked file whose bytes are not its
    HEAD blob; a candidate's content-changed files stay reviewed working bytes.
(b) An upgrade never sweeps directories, so a module retired from source stays
    installed unless [InstallDelete] names it (runtime_announcement.py).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "installer" / "build_release.ps1"
PWSH = shutil.which("pwsh")


def _install_delete():
    text = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    section = text.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip().startswith("Type:")]


def test_an_upgrade_removes_the_retired_runtime_announcement():
    entries = _install_delete()
    assert 'Type: files; Name: "{app}\\nodelang\\runtime_announcement.py"' in entries
    assert 'Type: files; Name: "{app}\\nodelang\\__pycache__\\runtime_announcement.*.pyc"' in entries
    assert not (ROOT / "nodelang" / "runtime_announcement.py").exists()


def test_the_snapshot_is_held_to_committed_blobs():
    source = BUILD.read_text(encoding="utf-8")
    body = source.split("function Read-ReleaseSnapshotManifest", 1)[1].split("\nfunction ", 1)[0]
    assert "Assert-CommittedBlobBytes $selectedRoot $selectedInputs $rows -WorkingCandidate:$WorkingCandidate" in body


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args],
                   check=True, capture_output=True)


def _judge(tmp_path, repo, rows, candidate=False):
    """Run the build script's own functions (parsed from it) against ``repo``."""
    script = tmp_path / "judge.ps1"
    script.write_text(r'''
param([string]$Build, [string]$Repo, [string]$RowsJson, [switch]$Candidate)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
foreach ($name in 'Get-GitBlobId', 'Assert-CommittedBlobBytes') {
    $definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name }, $true)
    if (-not $definition) { throw "missing $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
$rows = @(($RowsJson | ConvertFrom-Json) | ForEach-Object {
    [pscustomobject]@{ Path = $_; SourcePath = (Join-Path $Repo $_) } })
try {
    Assert-CommittedBlobBytes $Repo @('.') $rows -WorkingCandidate:$Candidate
    @{ ok = $true } | ConvertTo-Json -Compress
} catch {
    @{ ok = $false; message = $_.Exception.Message } | ConvertTo-Json -Compress
}
''', encoding="utf-8")
    command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(script),
               "-Build", str(BUILD), "-Repo", str(repo), "-RowsJson", json.dumps(rows)]
    if candidate:
        command.append("-Candidate")
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 builds releases")
def test_a_crlf_copy_of_an_lf_blob_is_refused_and_git_bytes_pass(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (repo / "kept.py").write_bytes(b"a = 1\nb = 2\n")
    (repo / "drifted.py").write_bytes(b"c = 3\nd = 4\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=court", "-c", "user.email=court@example.invalid", "commit", "-qm", "base")

    # The hole: CRLF bytes of an LF blob read as unchanged to git diff.
    (repo / "drifted.py").write_bytes(b"c = 3\r\nd = 4\r\n")
    clean = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", "drifted.py"])
    assert clean.returncode == 0

    refused = _judge(tmp_path, repo, ["kept.py", "drifted.py"])
    assert refused["ok"] is False
    assert "not the committed blob" in refused["message"] and "drifted.py" in refused["message"]
    # A local candidate is held to the same rule for content it did not change.
    assert _judge(tmp_path, repo, ["drifted.py"], candidate=True)["ok"] is False

    (repo / "drifted.py").write_bytes(b"c = 3\nd = 4\n")
    assert _judge(tmp_path, repo, ["kept.py", "drifted.py"]) == {"ok": True}


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 builds releases")
def test_a_candidates_reviewed_change_and_new_files_are_not_held_to_head(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (repo / "edited.py").write_bytes(b"e = 5\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=court", "-c", "user.email=court@example.invalid", "commit", "-qm", "base")
    (repo / "edited.py").write_bytes(b"e = 6\r\n")
    (repo / "added.py").write_bytes(b"f = 7\r\n")

    assert _judge(tmp_path, repo, ["edited.py", "added.py"], candidate=True) == {"ok": True}
    # A public release never gets that allowance (its inputs must be committed).
    assert _judge(tmp_path, repo, ["edited.py"])["ok"] is False
