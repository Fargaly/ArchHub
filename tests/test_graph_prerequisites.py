"""Fresh-user prerequisite and package closure checks; no real Graph SDK calls."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from nodelang import host_brokers
from nodelang import outlook_graph as graph


ROOT = Path(__file__).resolve().parents[1]


def test_missing_powershell_is_reported_without_starting_a_process(monkeypatch):
    monkeypatch.setattr(graph.shutil, "which", lambda name: None)
    monkeypatch.setattr(graph.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    result = graph.invoke("prerequisites", {})
    assert result["state"] == "dependency-missing"
    assert "PowerShell 7" in result["reason"]


def test_missing_packaged_script_is_reported_before_process(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "SCRIPT", tmp_path / "missing.ps1")
    monkeypatch.setattr(graph.shutil, "which", lambda name: "C:/PowerShell/pwsh.exe")
    monkeypatch.setattr(graph.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    result = graph.invoke("prerequisites", {})
    assert result["state"] == "dependency-missing"
    assert "repair the ArchHub installation" in result["reason"]


def test_passive_check_is_bounded_and_uses_data_input(monkeypatch):
    monkeypatch.setattr(graph.shutil, "which", lambda name: "C:/PowerShell/pwsh.exe")
    def run(command, **options):
        assert "-NonInteractive" in command
        assert "-InteractiveSignIn" not in command and "-Command" not in command
        assert options["timeout"] == 5
        assert json.loads(options["input"]) == {"operation": "prerequisites"}
        return subprocess.CompletedProcess(command, 0, json.dumps(
            {"ok": True, "state": "prerequisites-ready", "reason": "Ready", "out": []}), "")
    monkeypatch.setattr(graph.subprocess, "run", run)
    assert graph.invoke("prerequisites", {})["state"] == "prerequisites-ready"


@pytest.mark.parametrize("state,ok,expected", [
    ("dependency-missing", False, "dependency-missing"),
    ("prerequisites-ready", True, "prerequisites-ready"),
    ("timeout", False, "timeout"),
])
def test_connector_discovery_reports_actual_prerequisite_result(monkeypatch, state, ok, expected):
    for name in ("_port_open", "_running", "_installed", "_com_alive"):
        monkeypatch.setattr(host_brokers, name, lambda *a, **k: False)
    monkeypatch.setattr(host_brokers, "_notion_token", lambda: "")
    monkeypatch.setattr(host_brokers, "_dropbox_root", lambda: None)
    calls = []
    def invoke(operation, params):
        calls.append((operation, params))
        return {"ok": ok, "state": state, "reason": "Exact prerequisite result", "out": []}
    monkeypatch.setattr(graph, "invoke", invoke)
    row = next(row for row in host_brokers.probe_host_rows() if row["id"] == "outlook-new")
    assert row["state"] == expected
    if ok:
        assert "authentication has not been checked" in row["detail"]
    else:
        assert row["detail"] == "Exact prerequisite result"
    assert calls == [("prerequisites", {})]


@pytest.mark.parametrize("module_present", [False, True])
def test_shipped_script_prerequisites_never_import_or_authenticate(module_present):
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell 7 runtime required for the actual script check")
    candidate = "[pscustomobject]@{Version=[version]'2.39.0'}" if module_present else "return"
    quoted_script = str(graph.SCRIPT).replace("'", "''")
    command = (
        "function Get-Module { " + candidate + " }; "
        "function Import-Module { throw 'Unexpected SDK import' }; "
        "function Get-MgContext { throw 'Unexpected credential access' }; "
        "function Connect-MgGraph { throw 'Unexpected authentication' }; "
        "function Invoke-MgGraphRequest { throw 'Unexpected network access' }; "
        "& '" + quoted_script + "'"
    )
    result = subprocess.run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                            input=json.dumps({"operation": "prerequisites"}), text=True,
                            capture_output=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, "PowerShell prerequisite harness failed"
    response = json.loads(result.stdout)
    assert response["state"] == ("prerequisites-ready" if module_present else "dependency-missing")
    assert response["ok"] is module_present


def test_release_allowlist_admits_only_the_exact_graph_script():
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell required to execute the release allowlist")
    source = str(ROOT / "installer/build_release.ps1").replace("'", "''")
    command = (
        "$ast=[System.Management.Automation.Language.Parser]::ParseFile('" + source + "',[ref]$null,[ref]$null);"
        "$f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-CandidateInput'},$false);"
        "Invoke-Expression $f.Extent.Text;"
        "@{graph=(Test-CandidateInput 'selected' 'nodelang/outlook_graph.ps1');"
        "other=(Test-CandidateInput 'selected' 'nodelang/arbitrary.ps1')}|ConvertTo-Json -Compress"
    )
    result = subprocess.run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                            text=True, capture_output=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"graph": True, "other": False}
    source_text = (ROOT / "installer/build_release.ps1").read_text(encoding="utf-8")
    assert "'selected/nodelang/outlook_graph.ps1'" in source_text
    assert "'nodelang', 'nodelang/outlook_graph.ps1'" in source_text
