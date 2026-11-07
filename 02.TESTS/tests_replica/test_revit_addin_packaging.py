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

ROOT = Path(__file__).resolve().parents[2]
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
           "ProgramData": str(tmp_path / "ProgramData"), 'LOCALAPPDATA': str(profile), 'TEMP': str(profile), 'TMP': str(profile)}
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
    source = tmp_path / "tests_replica"
    source.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "03.TOOLS/installer", tmp_path / "installer", dirs_exist_ok=True)
    for harness_file in (ROOT / "02.TESTS/tests_replica").glob("*harness.iss"):
        shutil.copy2(harness_file, source / harness_file.name)
    out = tmp_path / "harness-out"
    built = subprocess.run([compiler, "/Q", "/O" + str(out), str(source / "host_uninstall_harness.iss")],
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
    iss = (ROOT / "03.TOOLS/installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert '#include "host_registrations.iss"' in iss
    step = iss[iss.index("procedure CurUninstallStepChanged"):]
    step = step[:step.index("\nend;\n")]
    assert "RemoveOwnRevitRegistrationsIn(ExpandConstant('{userappdata}') + '\\Autodesk\\Revit\\Addins'" in step
    assert "ExpandConstant('{app}'));" in step
    assert "RemoveOwnMaxStartupScriptsIn(ExpandConstant('{localappdata}') + '\\Autodesk\\3dsMax'" in step
    assert "if CurUninstallStep = usUninstall then" in step


def test_the_installer_carries_the_payload_and_the_build_produces_it():
    iss = (ROOT / "03.TOOLS/installer" / "ArchHub.iss").read_text(encoding="utf-8")
    for host in ("revit", "autocad"):
        assert re.search(r'Source: "\{#HostPayloadPath\}\\bridges\\%s\\\*"; DestDir: "\{app\}\\bridges\\%s"'
                         % (host, host), iss), host
    assert 'Source: "{#HostPayloadPath}\\HOST_ARTIFACTS.json"; DestDir: "{app}"' in iss
    release = (ROOT / "03.TOOLS/installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert '"/DHostPayloadPath=$hostPayload"' in release and "build_host_bridges.ps1" in release
    script = (ROOT / "03.TOOLS/installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    # Activation is written only from a supplied review, never invented.
    assert script.count("reviewed-authenticated-broker") == 1
    assert "if ($review) {\n        $manifest.runtime_closure_reviewed = $true" in script
    assert "if ($review) { $index.max.activation = $review }" in script
    assert "acad_mcp/AcadMCP.csproj" in script


def test_the_legacy_sweep_payload_keep_check_still_holds():
    sweep = (ROOT / "03.TOOLS/installer" / "legacy_sweep.iss").read_text(encoding="utf-8")
    assert "KeepPayload := LegacyAddinsReference(Root + '\\payload');" in sweep
    assert "if KeepPayload and (CompareText(Copy(Rel, 1, 8), 'payload\\') = 0) then\n        continue;" in sweep
    # The packaged add-in never loads from payload\, so a new registration can
    # neither pin a v1 payload nor be swept with it.
    script = (ROOT / "03.TOOLS/installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    assert "bridges/revit/$year" in script
    assert "payload\\" not in script.lower() and "payload/" not in script.lower()


@pytest.mark.parametrize("payload", ["reviewed", "unreviewed", "absent"])
def test_setup_retires_legacy_archhub_for_all_installed_years(machine, payload):
    from nodelang.host_broker_installation import _registration
    years = ["2020", "2023", "2024", "2025", "2027"]
    machine.install.mkdir(parents=True)
    if payload != "absent":
        _package(machine, "2025", reviewed=payload == "reviewed")
    owned, foreign = [], []
    for base in (machine.appdata, Path(machine.env["ProgramData"])):
        for year in years:
            folder = base / "Autodesk/Revit/Addins" / year
            folder.mkdir(parents=True)
            # Legacy ClientId, arbitrary filename, UTF-16: ownership is XML identity.
            raw = _registration(Path("C:/Legacy/ArchHub/Revit") / year / "RevitMCP.dll")
            text = raw.decode().replace("AddInId", "ClientId").replace("utf-8", "utf-16")
            path = folder / "OldArchHub.addin"
            path.write_bytes(text.encode("utf-16"))
            owned.append((path, path.read_bytes()))
            other = folder / "RevitMCP.addin"
            other.write_bytes(b'<RevitAddIns><AddIn><Name>Other vendor</Name></AddIn></RevitAddIns>')
            foreign.append((other, other.read_bytes()))
    colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=years)
    for path, raw in owned:
        assert not path.exists(), str(path)
        assert path.with_suffix(".addin.retired").read_bytes() == raw
    for path, raw in foreign:
        assert path.read_bytes() == raw
    # Repeated setup cannot overwrite retired evidence or foreign registrations.
    colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=years)
    for path, raw in owned:
        assert path.with_suffix(".addin.retired").read_bytes() == raw


def test_setup_replaces_supported_legacy_and_retires_unsupported(machine):
    from nodelang.host_broker_installation import _registration
    _package(machine, "2025", reviewed=True)
    paths = []
    for base in (machine.appdata, Path(machine.env["ProgramData"])):
        for year in ("2020", "2023", "2024", "2025", "2027"):
            folder = base / "Autodesk/Revit/Addins" / year
            folder.mkdir(parents=True)
            path = folder / "RevitMCP.addin"
            path.write_bytes(_registration(Path("C:/Legacy/Revit") / year / "RevitMCP.dll"))
            paths.append(path)
    rows = colleague_setup.register_revit_add_ins(machine.install, environment=machine.env,
                                                 detected_years=["2020", "2023", "2024", "2025", "2027"])
    assert next(r for r in rows if r["host_version"] == "2025")["registered"] is True
    expected = machine.appdata / "Autodesk/Revit/Addins/2025/RevitMCP.addin"
    assert expected.read_bytes() == _registration(machine.install / "bridges/revit/2025/RevitMCP.dll")
    assert all(not p.exists() for p in paths if p != expected)


@pytest.mark.parametrize("year", [str(y) for y in range(2020, 2028)])
def test_setup_activates_only_the_selected_year_reviewed_closure(machine, year):
    from nodelang.host_broker_installation import _registration
    _package(machine, year, reviewed=True)
    host = machine.host.parent / ("Revit " + year)
    host.mkdir(exist_ok=True)
    for name in ("Revit.exe", "RevitAPI.dll", "RevitAPIUI.dll"):
        if host != machine.host:
            (host / name).write_bytes((machine.host / name).read_bytes())
    old = machine.appdata / "Autodesk/Revit/Addins" / year / "RevitMCP.addin"
    old.parent.mkdir(parents=True)
    old.write_bytes(_registration(Path("C:/Legacy/Revit") / year / "RevitMCP.dll"))
    rows = colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=[year])
    assert rows[0]["status"] == "registered_pending_host_restart", rows
    assert old.read_bytes() == _registration(machine.install / "bridges/revit" / year / "RevitMCP.dll")
    again = colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=[year])
    assert again[0]["status"] == "unchanged_pending_host_restart"


def test_retirement_preserves_collision_and_mixed_vendor_manifests(machine):
    from nodelang.host_broker_installation import _registration, retire_revit_registrations, RegistrationRefused
    user = machine.appdata / "Autodesk/Revit/Addins"
    machine_root = Path(machine.env["ProgramData"]) / "Autodesk/Revit/Addins"
    folder = user / "2025"
    folder.mkdir(parents=True)
    old = folder / "RevitMCP.addin"
    raw = _registration(Path("C:/Legacy/RevitMCP.dll"))
    old.write_bytes(raw)
    retired = old.with_suffix(".addin.retired")
    retired.write_bytes(b"earlier retirement")
    result = retire_revit_registrations(user_addins_root=user, machine_addins_root=machine_root, host_version="2025")
    assert retired.read_bytes() == b"earlier retirement"
    assert Path(result[0]).read_bytes() == raw and not old.exists()
    mixed = raw.replace(b"</RevitAddIns>", b'<AddIn><Name>Foreign</Name></AddIn></RevitAddIns>')
    old.write_bytes(mixed)
    with pytest.raises(RegistrationRefused, match="shares a manifest"):
        retire_revit_registrations(user_addins_root=user, machine_addins_root=machine_root, host_version="2025")
    assert old.read_bytes() == mixed


def test_tampered_payload_retires_legacy_instead_of_loading_it(machine):
    from nodelang.host_broker_installation import _registration
    _package(machine, "2025", reviewed=True)
    (machine.install / "bridges/revit/2025/RevitMCP.dll").write_bytes(b"tampered")
    old = machine.appdata / "Autodesk/Revit/Addins/2025/RevitMCP.addin"
    old.parent.mkdir(parents=True)
    old.write_bytes(_registration(Path("C:/Legacy/RevitMCP.dll")))
    rows = colleague_setup.register_revit_add_ins(machine.install, environment=machine.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused"
    assert not old.exists() and old.with_suffix(".addin.retired").exists()


def test_bridge_packager_omits_failed_year_and_keeps_supported_year(tmp_path):
    import os
    import shutil
    import subprocess
    candidates = [Path(sys.executable).with_name("pwsh.exe"),
                  Path("C:/Program Files/PowerShell/7/pwsh.exe"),
                  *sorted(Path("C:/Program Files/WindowsApps").glob(
                      "Microsoft.PowerShell_*_x64__*/pwsh.exe"), reverse=True)]
    powershell = next((str(path) for path in candidates if path.is_file()), None) or shutil.which("pwsh")
    assert powershell, "PowerShell 7 is required to exercise the bridge packager"
    source = tmp_path / "sources"
    source.mkdir()
    (source / "max_mcp").mkdir()
    (source / "max_mcp/max_mcp_startup.py").write_text("# fixture")
    program_files = tmp_path / "ProgramFiles"
    for year in (2020, 2027):
        host = program_files / "Autodesk" / ("Revit %s" % year)
        host.mkdir(parents=True)
        for name in ("RevitAPI.dll", "RevitAPIUI.dll"):
            (host / name).write_bytes(b"fixture API")
    dotnet = tmp_path / "dotnet.ps1"
    dotnet.write_text(
        '$ErrorActionPreference = "Stop"\n$BuildArgs = $args\n'
        'if (($BuildArgs -join " ") -match "RevitYear=2020") { exit 1 }\n'
        'if ($BuildArgs[0] -eq "build") {\n'
        '  $out = $BuildArgs[[Array]::IndexOf($BuildArgs, "-o") + 1]\n'
        '  $name = [IO.Path]::GetFileNameWithoutExtension($BuildArgs[1]) + ".dll"\n'
        '  [IO.File]::WriteAllText((Join-Path $out $name), "fixture bridge")\n'
        '}\nexit 0\n')
    out = tmp_path / "payload"
    runner = tmp_path / "build.ps1"
    runner.write_text("$ErrorActionPreference = 'Stop'\n"
                      "$env:ProgramFiles = $env:ARCHHUB_FIXTURE_PROGRAMFILES\n"
                      "& $env:ARCHHUB_FIXTURE_BUILDER @args\n")
    result = subprocess.run([
        powershell, "-NoProfile", "-File", str(runner),
        "-SourceRoot", str(source), "-OutputRoot", str(out), "-SourceRevision", "a" * 40,
        "-BuildId", "fixture", "-DotnetPath", str(dotnet)],
        env=dict(os.environ, PATH="", ARCHHUB_FIXTURE_PROGRAMFILES=str(program_files),
                 ARCHHUB_FIXTURE_BUILDER=str(ROOT / "03.TOOLS/installer/build_host_bridges.ps1")),
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    index = json.loads((out / "HOST_ARTIFACTS.json").read_text())
    assert set(index["revit"]) == {"2027"}, result.stdout + result.stderr
    assert not list(out.rglob(".build-*"))
    assert not list((out / "bridges/revit/2020").rglob("*.dll"))
