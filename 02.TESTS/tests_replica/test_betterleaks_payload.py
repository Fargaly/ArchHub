"""The release carries the pinned Betterleaks binary and the hook runs it.

The archive hash is the one published in the v1.9.0 checksums.txt. The fake
key is generated per run in a shape the scanner knows; it is not a credential.
"""
import importlib.util
import json
import random
import string
import subprocess
from pathlib import Path

import pytest

from nodelang import hook_decision as hd

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "03.TOOLS/packaging/windows/betterleaks-pin.json"
BUILD = ROOT / "03.TOOLS/installer/build_release.ps1"
STAGE = ROOT / "03.TOOLS/packaging/windows/stage_betterleaks.py"
PUBLISHED_ARCHIVE_SHA256 = "b765daec9fda475b031b5a5159798cbe4294a3f2a50683cbc0471226e376d3da"


def _stage_module():
    spec = importlib.util.spec_from_file_location("stage_betterleaks", STAGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    destination = tmp_path_factory.mktemp("betterleaks")
    manifest = _stage_module().fetch_betterleaks(destination, pin_path=PIN)
    return destination, manifest


def _aws_shaped_text():
    """A deterministic AWS-shaped pair. Seed 8 is one Betterleaks 1.9.0 flags."""
    alphabet = string.ascii_uppercase + string.digits
    secret_alphabet = string.ascii_letters + string.digits + "+/"
    rnd = random.Random(8)
    access = "AK" + "IA" + "".join(rnd.choice(alphabet) for _ in range(16))
    secret = "".join(rnd.choice(secret_alphabet) for _ in range(40))
    return "aws_access_key_id = " + access + "\naws_secret_access_key = " + secret + "\n"


def _env(tmp_path, exe):
    home = tmp_path / "home"
    (home / "00.ARCHUB").mkdir(parents=True)
    (tmp_path / "tmp").mkdir()
    return {"USERPROFILE": str(home), "HOME": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(tmp_path / "tmp"), "ARCHHUB_HOOK_STATE": str(tmp_path / "state"),
            "ARCHHUB_BETTERLEAKS": str(exe)}


def test_real_scanner_flags_a_fake_aws_key_and_ignores_clean_text(staged, tmp_path):
    destination, manifest = staged
    exe = destination / "betterleaks.exe"
    env = _env(tmp_path, exe)
    state, found, version = hd.scan_secrets(_aws_shaped_text(), env)
    assert state == "ok" and found and version == "1.9.0"
    assert all(item["kind"] == "secret" for item in found)
    state, found, version = hd.scan_secrets("the meeting notes have no credentials\n", env)
    assert (state, found, version) == ("ok", [], "1.9.0")
    decision = hd.decide({"session_id": "s-scan", "tool_name": "Bash",
                          "tool_input": {"command": "echo meeting notes"}},
                         "claude-code", environment=env)
    assert decision["verdict"] == "allow"
    assert decision["scanners"]["secrets"] == "ok"
    assert "Secret scan: Betterleaks 1.9.0." in decision["notes"]
    assert manifest["version"] == "1.9.0"
    assert manifest["archive_sha256"] == PUBLISHED_ARCHIVE_SHA256


def _run_payload_check(pin, staged_dir):
    judge = staged_dir.parent / "betterleaks-payload-check.ps1"
    judge.write_text(r"""
param([string]$Build, [string]$Pin, [string]$Staged)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Get-BetterleaksPayload' }, $true)
if (-not $definition) { throw 'payload check is missing' }
. ([scriptblock]::Create($definition.Extent.Text))
Get-BetterleaksPayload -PinPath $Pin -StagedDirectory $Staged
""".lstrip(), encoding="utf-8")
    return subprocess.run(
        [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
         "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(judge), "-Build", str(BUILD), "-Pin", str(pin), "-Staged", str(staged_dir)],
        capture_output=True, text=True, timeout=120)


def test_release_payload_check_lists_the_pinned_executable(staged, tmp_path):
    destination, _manifest = staged
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert pin["sha256"] == PUBLISHED_ARCHIVE_SHA256
    done = _run_payload_check(PIN, destination)
    assert done.returncode == 0, done.stderr
    rows = [line for line in done.stdout.splitlines() if line.strip()]
    assert rows == ["runtime/betterleaks/betterleaks.exe\t" + pin["executable_sha256"]]
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    data = bytearray((destination / "betterleaks.exe").read_bytes())
    data[-1] ^= 0xFF
    (tampered / "betterleaks.exe").write_bytes(data)
    (tampered / "manifest.json").write_bytes((destination / "manifest.json").read_bytes())
    refused = _run_payload_check(PIN, tampered)
    assert refused.returncode != 0
