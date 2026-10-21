"""Court: the packaged Revit add-in is registered per Revit year found, and only ours is removed.

Setup's registration step (colleague_setup.register_revit_add_ins) runs the
real registration owner (host_broker_installation.install_revit_broker)
against a real install layout in a temporary profile; the 3ds Max startup
placement likewise. The uninstall ownership rules (installer/
host_registrations.iss) are compiled by Inno Setup into a harness setup that
runs them on real folders. The v1 legacy sweep's payload keep-check is held
by text.
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


def _max_index(machine, *, reviewed: bool, script: bytes = b"# MaxMCP court script\n") -> None:
    shipped = machine.install / "bridges" / "max" / "max_mcp_startup.py"
    shipped.parent.mkdir(parents=True, exist_ok=True)
    shipped.write_bytes(script)
    index_path = machine.install / "HOST_ARTIFACTS.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"revit": {}}
    index["max"] = {"script": "bridges/max/max_mcp_startup.py", "sha256": hashlib.sha256(script).hexdigest(),
                    "reviewed": reviewed}
    if reviewed:
        index["max"]["activation"] = {"eligibility": "reviewed-authenticated-broker", "review_sha256": "c" * 64}
    index_path.write_text(json.dumps(index))


def _max_env(machine, tmp_path):
    return dict(machine.env, LOCALAPPDATA=str(tmp_path / "local"))


def test_setup_places_the_reviewed_max_script_and_never_overwrites_another(machine, tmp_path):
    env = _max_env(machine, tmp_path)
    _max_index(machine, reviewed=True)
    startup = tmp_path / "local/Autodesk/3dsMax/2026 - 64bit/ENU/scripts/startup"
    foreign = tmp_path / "local/Autodesk/3dsMax/2025 - 64bit/ENU/scripts/startup/max_mcp_startup.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"# someone else's MaxMCP\n")
    rows = {row["host_version"]: row for row in colleague_setup.register_max_startup(
        machine.install, environment=env, detected_years=["2026", "2025"])}
    assert rows["2026"]["status"] == "placed_pending_host_restart"
    assert (startup / "max_mcp_startup.py").read_bytes() == b"# MaxMCP court script\n"
    assert rows["2025"]["status"] == "refused" and foreign.read_bytes() == b"# someone else's MaxMCP\n"
    again = colleague_setup.register_max_startup(machine.install, environment=env, detected_years=["2026"])
    assert again[0]["status"] == "unchanged"


def test_an_unreviewed_max_script_is_never_placed(machine, tmp_path):
    env = _max_env(machine, tmp_path)
    _max_index(machine, reviewed=False)
    assert colleague_setup.register_max_startup(machine.install, environment=env,
                                                detected_years=["2026"])[0]["status"] == "refused"
    assert not (tmp_path / "local" / "Autodesk").exists()


def _run_uninstall_harness(tmp_path, *, revit_root, app, max_root, shipped):
    import os
    import shutil
    import subprocess
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    out = tmp_path / "harness-out"
    built = subprocess.run([compiler, "/Q", "/O" + str(out), str(ROOT / "tests_replica" / "host_uninstall_harness.iss")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    done = tmp_path / "done.txt"
    subprocess.run([str(out / "host-uninstall-harness.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/revit=" + str(revit_root), "/app=" + str(app), "/max=" + str(max_root),
                    "/shipped=" + str(shipped), "/done=" + str(done)], timeout=120)
    assert done.read_text() == "ran", "the uninstall rules did not run"


def test_uninstall_removes_exactly_what_this_install_placed(tmp_path):
    """The shipped Pascal rules, run by Inno Setup itself, on a non-ASCII install folder."""
    from nodelang.host_broker_installation import _registration
    app = tmp_path / "Ünïcode Ärch & Hub" / "ArchHub"
    revit = tmp_path / "Roaming" / "Autodesk" / "Revit" / "Addins"
    ours, other_install, legacy = revit / "2025", revit / "2024", revit / "2023"
    for folder in (ours, other_install, legacy):
        folder.mkdir(parents=True)
    # Exactly what setup writes (host_broker_installation), UTF-8 with the non-ASCII path.
    (ours / "RevitMCP.addin").write_bytes(_registration(app / "bridges" / "revit" / "2025" / "RevitMCP.dll"))
    (other_install / "RevitMCP.addin").write_bytes(
        _registration(tmp_path / "Other" / "ArchHub" / "bridges" / "revit" / "2024" / "RevitMCP.dll"))
    (legacy / "RevitMCP.addin").write_text(
        r"<RevitAddIns><AddIn><Assembly>C:\Users\someone\AppData\Local\ArchHub\Revit\2023\RevitMCP.dll"
        r"</Assembly></AddIn></RevitAddIns>", encoding="utf-8")
    (ours / "Other.addin").write_bytes(b"<RevitAddIns/>")
    shipped = app / "bridges" / "max" / "max_mcp_startup.py"
    shipped.parent.mkdir(parents=True)
    shipped.write_bytes(b"# MaxMCP shipped\n")
    max_root = tmp_path / "Local" / "Autodesk" / "3dsMax"
    placed = max_root / "2026 - 64bit/ENU/scripts/startup/max_mcp_startup.py"
    edited = max_root / "2025 - 64bit/ENU/scripts/startup/max_mcp_startup.py"
    for path, body in ((placed, b"# MaxMCP shipped\n"), (edited, b"# MaxMCP shipped, then edited\n")):
        path.parent.mkdir(parents=True)
        path.write_bytes(body)
    assert "Ü".encode("utf-8") in (ours / "RevitMCP.addin").read_bytes()

    _run_uninstall_harness(tmp_path, revit_root=revit, app=app, max_root=max_root, shipped=shipped)

    assert not (ours / "RevitMCP.addin").exists(), "this install's registration stayed"
    assert (other_install / "RevitMCP.addin").exists() and (legacy / "RevitMCP.addin").exists()
    assert (ours / "Other.addin").exists()
    assert not placed.exists() and edited.exists()


def test_the_installer_wires_the_shared_rules_into_uninstall():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert '#include "host_registrations.iss"' in iss
    step = iss[iss.index("procedure CurUninstallStepChanged"):]
    step = step[:step.index("\nend;\n")]
    assert "RemoveOwnRevitRegistrationsIn(ExpandConstant('{userappdata}') + '\\Autodesk\\Revit\\Addins'" in step
    assert "ExpandConstant('{app}'));" in step
    assert "RemoveOwnMaxStartupScriptsIn(ExpandConstant('{localappdata}') + '\\Autodesk\\3dsMax'" in step
    assert "if CurUninstallStep = usUninstall then" in step


def test_the_installer_carries_the_payload_and_the_build_produces_it():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    for host in ("revit", "autocad"):
        assert re.search(r'Source: "\{#HostPayloadPath\}\\bridges\\%s\\\*"; DestDir: "\{app\}\\bridges\\%s"'
                         % (host, host), iss), host
    assert 'Source: "{#HostPayloadPath}\\HOST_ARTIFACTS.json"; DestDir: "{app}"' in iss
    release = (ROOT / "installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert '"/DHostPayloadPath=$hostPayload"' in release and "build_host_bridges.ps1" in release
    script = (ROOT / "installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    # Activation is written only from a supplied review, never invented.
    assert script.count("reviewed-authenticated-broker") == 1
    assert "if ($review) {\n        $manifest.runtime_closure_reviewed = $true" in script
    assert "if ($review) { $index.max.activation = $review }" in script
    assert "acad_mcp/AcadMCP.csproj" in script


def test_the_legacy_sweep_payload_keep_check_still_holds():
    sweep = (ROOT / "installer" / "legacy_sweep.iss").read_text(encoding="utf-8")
    assert "KeepPayload := LegacyAddinsReference(Root + '\\payload');" in sweep
    assert "if KeepPayload and (CompareText(Copy(Rel, 1, 8), 'payload\\') = 0) then\n        continue;" in sweep
    # The packaged add-in never loads from payload\, so a new registration can
    # neither pin a v1 payload nor be swept with it.
    script = (ROOT / "installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    assert "bridges/revit/$year" in script
    assert "payload\\" not in script.lower() and "payload/" not in script.lower()
