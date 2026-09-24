"""Court: the packaged Revit add-in is registered per Revit year found, and only ours is removed.

Setup's registration step (colleague_setup.register_revit_add_ins) runs the
real registration owner (host_broker_installation.install_revit_broker)
against a real install layout in a temporary profile. The installer's
uninstall rule and the v1 legacy sweep's payload keep-check are held by text,
because their Pascal runs only inside Inno Setup.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import colleague_setup  # noqa: E402


def _pin(path: Path) -> dict:
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def machine(tmp_path):
    install = tmp_path / "ArchHub"
    program_files = tmp_path / "Program Files"
    host = program_files / "Autodesk" / "Revit 2025"
    host.mkdir(parents=True)
    for name, body in (("Revit.exe", b"MZ revit"), ("RevitAPI.dll", b"MZ api"), ("RevitAPIUI.dll", b"MZ apiui")):
        (host / name).write_bytes(body)
    profile = tmp_path / "Users" / "person"
    appdata = profile / "AppData" / "Roaming"
    appdata.mkdir(parents=True)
    env = {"USERPROFILE": str(profile), "APPDATA": str(appdata), "ProgramFiles": str(program_files),
           "ProgramData": str(tmp_path / "ProgramData")}
    return type("Machine", (), {"install": install, "host": host, "env": env, "appdata": appdata})


def _package(machine, year: str, *, reviewed: bool) -> None:
    payload = machine.install / "bridges" / "revit" / year
    payload.mkdir(parents=True)
    (payload / "RevitMCP.dll").write_bytes(b"MZ shim " + year.encode())
    (payload / "RevitMCPCore.dll").write_bytes(b"MZ core " + year.encode())
    manifest = {
        "schema": "archhub-host-artifacts/v1", "source_revision": "a" * 40,
        "host": "revit", "host_version": year,
        "assembly": "bridges/revit/%s/RevitMCP.dll" % year,
        "files": [{"path": "bridges/revit/%s/%s" % (year, name), **_pin(payload / name)}
                  for name in ("RevitMCP.dll", "RevitMCPCore.dll")],
        "host_api": {name: _pin(machine.host / name) for name in ("RevitAPI.dll", "RevitAPIUI.dll")},
    }
    if reviewed:
        manifest["runtime_closure_reviewed"] = True
        manifest["activation"] = {"eligibility": "reviewed-authenticated-broker", "review_sha256": "b" * 64}
    raw = json.dumps(manifest).encode("utf-8")
    (payload / "host-artifacts.json").write_bytes(raw)
    index_path = machine.install / "HOST_ARTIFACTS.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"revit": {}}
    index["revit"][year] = {"manifest": "bridges/revit/%s/host-artifacts.json" % year,
                            "sha256": hashlib.sha256(raw).hexdigest()}
    index_path.write_text(json.dumps(index))


def test_setup_registers_each_packaged_year_that_is_installed(machine):
    _package(machine, "2025", reviewed=True)
    _package(machine, "2023", reviewed=True)
    outcomes = colleague_setup.register_revit_add_ins(
        machine.install, environment=machine.env, detected_years=["2025", "2024"])
    by_year = {row["host_version"]: row for row in outcomes}
    assert by_year["2023"]["status"] == "host-not-installed"
    assert by_year["2025"]["status"] == "registered_pending_host_restart", by_year["2025"]
    addin = machine.appdata / "Autodesk" / "Revit" / "Addins" / "2025" / "RevitMCP.addin"
    text = addin.read_text(encoding="utf-8")
    assert str(machine.install / "bridges" / "revit" / "2025" / "RevitMCP.dll") in text
    assert not (machine.appdata / "Autodesk" / "Revit" / "Addins" / "2023").exists()
    # Running setup again is a no-op on the same bytes.
    again = colleague_setup.register_revit_add_ins(
        machine.install, environment=machine.env, detected_years=["2025"])
    assert {row["host_version"]: row["status"] for row in again}["2025"] == "unchanged_pending_host_restart"


def test_an_unreviewed_payload_is_never_registered(machine):
    _package(machine, "2025", reviewed=False)
    outcome = colleague_setup.register_revit_add_ins(
        machine.install, environment=machine.env, detected_years=["2025"])[0]
    assert outcome["status"] == "refused" and "not reviewed for activation" in outcome["reason"]
    assert not (machine.appdata / "Autodesk" / "Revit" / "Addins" / "2025").exists()


def test_a_build_without_the_payload_says_so(machine, capsys):
    machine.install.mkdir()
    assert colleague_setup.register_revit_add_ins(machine.install, environment=machine.env,
                                                  detected_years=["2025"]) == []
    assert "carries no Revit add-in payload" in capsys.readouterr().out


def test_uninstall_removes_only_the_registration_that_loads_from_this_install(machine):
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    body = iss[iss.index("procedure RemoveOwnRevitRegistrations();"):]
    body = body[:body.index("\nend;\n\nprocedure CurUninstallStepChanged")]
    assert "Owned := Lowercase(ExpandConstant('{app}') + '\\bridges\\revit\\');" in body
    assert "'\\RevitMCP.addin'" in body and "Pos(Owned, Lowercase(String(Text))) > 0" in body
    assert "if CurUninstallStep = usUninstall then\n    RemoveOwnRevitRegistrations();" in iss
    # What setup writes matches that rule; the founder-style legacy registration does not.
    _package(machine, "2025", reviewed=True)
    colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=["2025"])
    ours = (machine.appdata / "Autodesk/Revit/Addins/2025/RevitMCP.addin").read_text(encoding="utf-8")
    owned = (str(machine.install) + "\\bridges\\revit\\").lower()
    assert owned in ours.lower()
    legacy = r"<Assembly>C:\Users\someone\AppData\Local\ArchHub\Revit\2025\RevitMCP.dll</Assembly>"
    assert owned not in legacy.lower()


def test_the_installer_carries_the_payload_and_the_build_produces_it():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert re.search(r'Source: "\{#HostPayloadPath\}\\bridges\\revit\\\*"; DestDir: "\{app\}\\bridges\\revit"', iss)
    assert 'Source: "{#HostPayloadPath}\\HOST_ARTIFACTS.json"; DestDir: "{app}"' in iss
    release = (ROOT / "installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert '"/DHostPayloadPath=$hostPayload"' in release and "build_revit_bridge.ps1" in release
    script = (ROOT / "installer" / "build_revit_bridge.ps1").read_text(encoding="utf-8")
    # Activation is written only from a supplied review, never invented.
    assert script.count("reviewed-authenticated-broker") == 1
    assert "if ($review) {\n        $manifest.runtime_closure_reviewed = $true" in script


def test_the_legacy_sweep_payload_keep_check_still_holds():
    sweep = (ROOT / "installer" / "legacy_sweep.iss").read_text(encoding="utf-8")
    assert "KeepPayload := LegacyAddinsReference(Root + '\\payload');" in sweep
    assert "if KeepPayload and (CompareText(Copy(Rel, 1, 8), 'payload\\') = 0) then\n        continue;" in sweep
    # The packaged add-in never loads from payload\, so a new registration can
    # neither pin a v1 payload nor be swept with it.
    script = (ROOT / "installer" / "build_revit_bridge.ps1").read_text(encoding="utf-8")
    assert "bridges/revit/$year" in script
    assert "payload\\" not in script.lower() and "payload/" not in script.lower()
