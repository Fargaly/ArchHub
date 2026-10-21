"""Court: on a colleague's fresh machine the installed build activates its host brokers.

Before this court a release could ship every Revit, AutoCAD and 3ds Max year
with "reviewed": false (build_release.ps1 made -BrokerReviewPath optional), so
setup refused every broker; the AutoCAD add-in shipped with no registration
owner at all; and the Rhino and Blender rows told the person to run a script
from a payload folder the build no longer has.

What this court holds:
* the broker review record (archhub-broker-review/v1) binds one human decision
  to the exact bridges/ bytes and source revision the release compiles;
* a release refuses to build without it, and a release check fails when any
  shipped Revit or AutoCAD year, or the Max script, is unreviewed;
* setup registers the reviewed AutoCAD add-in through a per-user
  ApplicationPlugins bundle, behind the same review gate, never touching a
  bundle it did not place; uninstall removes only files it placed;
* Rhino and Blender are opened with their bridge in one click from ArchHub.
Everything runs on temporary profile folders; no host is started.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import colleague_setup  # noqa: E402

REVISION = "a" * 40


def _review_module():
    from nodelang import host_artifact_review
    return host_artifact_review


def _bridges(tmp_path) -> Path:
    bridges = tmp_path / "source" / "bridges"
    (bridges / "sources" / "acad_mcp").mkdir(parents=True)
    (bridges / "sources" / "acad_mcp" / "AcadMCPApp.cs").write_text("class AcadMCPApp {}\n")
    (bridges / "rhino").mkdir()
    (bridges / "rhino" / "archhub_mcp.py").write_text("# rhino\n")
    return bridges


def _review(tmp_path, bridges, **overrides) -> Path:
    record = {"schema": "archhub-broker-review/v1", "source_revision": REVISION,
              "bridges_tree_sha256": _review_module().bridges_tree_sha256(bridges),
              "reviewer": "an independent reviewer", "decision": "approve-activation",
              "hosts": ["revit", "autocad", "max"]}
    record.update(overrides)
    path = tmp_path / "broker-review.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# ------------------------------------------------------------ review record --

def test_the_review_record_binds_the_exact_bridge_bytes_and_revision(tmp_path):
    review = _review_module()
    bridges = _bridges(tmp_path)
    path = _review(tmp_path, bridges)
    accepted = review.load_review(path, source_revision=REVISION, bridges_root=bridges)
    assert accepted["activation"] == {"eligibility": "reviewed-authenticated-broker",
                                      "review_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert accepted["hosts"] == ["autocad", "max", "revit"]
    # One changed byte of any shipped bridge voids the review.
    (bridges / "rhino" / "archhub_mcp.py").write_text("# rhino, edited\n")
    with pytest.raises(review.ReviewRefused, match="bridges tree"):
        review.load_review(path, source_revision=REVISION, bridges_root=bridges)


@pytest.mark.parametrize("override, reason", [
    ({"source_revision": "b" * 40}, "source revision"),
    ({"decision": "looks fine"}, "decision"),
    ({"reviewer": " "}, "reviewer"),
    ({"schema": "v0"}, "schema"),
    ({"hosts": ["revit", "rhino"]}, "hosts"),
])
def test_a_review_record_that_does_not_decide_this_source_is_refused(tmp_path, override, reason):
    review = _review_module()
    bridges = _bridges(tmp_path)
    with pytest.raises(review.ReviewRefused, match=reason):
        review.load_review(_review(tmp_path, bridges, **override), source_revision=REVISION, bridges_root=bridges)


# --------------------------------------------------------- release check --

def _shipped_index(tmp_path, activation, *, autocad_activation=True, max_activation=True):
    out = tmp_path / "hostpayload"
    manifest_dir = out / "bridges" / "revit" / "2025"
    manifest_dir.mkdir(parents=True)
    manifest = {"schema": "archhub-host-artifacts/v1", "host": "revit", "host_version": "2025"}
    if activation:
        manifest.update(runtime_closure_reviewed=True, activation=activation)
    raw = json.dumps(manifest).encode()
    (manifest_dir / "host-artifacts.json").write_bytes(raw)
    index = {"schema": "archhub-host-artifacts-index/v1", "source_revision": REVISION,
             "revit": {"2025": {"manifest": "bridges/revit/2025/host-artifacts.json",
                                "sha256": hashlib.sha256(raw).hexdigest(), "reviewed": bool(activation)}},
             "autocad": {"2024": {"reviewed": bool(activation and autocad_activation)}},
             "max": {"script": "bridges/max/max_mcp_startup.py", "reviewed": bool(activation and max_activation)}}
    if activation and autocad_activation:
        index["autocad"]["2024"]["activation"] = activation
    if activation and max_activation:
        index["max"]["activation"] = activation
    path = out / "HOST_ARTIFACTS.json"
    path.write_text(json.dumps(index))
    return path


def _check(index, review_path, bridges):
    return subprocess.run([sys.executable, str(ROOT / "nodelang" / "host_artifact_review.py"), "check",
                           "--index", str(index), "--review", str(review_path),
                           "--revision", REVISION, "--bridges", str(bridges)],
                          capture_output=True, text=True, timeout=60)


def test_the_release_check_fails_when_any_shipped_year_is_unreviewed(tmp_path):
    bridges = _bridges(tmp_path)
    path = _review(tmp_path, bridges)
    activation = _review_module().load_review(path, source_revision=REVISION, bridges_root=bridges)["activation"]
    unreviewed = _check(_shipped_index(tmp_path / "a", None), path, bridges)
    assert unreviewed.returncode == 1
    for entry in ("revit 2025", "autocad 2024", "max"):
        assert entry in unreviewed.stdout, unreviewed.stdout
    only_acad = _check(_shipped_index(tmp_path / "b", activation, autocad_activation=False), path, bridges)
    flagged = only_acad.stdout.split("UNREVIEWED:", 1)[1]
    assert only_acad.returncode == 1 and "autocad 2024" in flagged and "revit 2025" not in flagged
    reviewed = _check(_shipped_index(tmp_path / "c", activation), path, bridges)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr
    assert "revit 2025" in reviewed.stdout and "autocad 2024" in reviewed.stdout


def test_the_release_check_refuses_a_review_that_does_not_cover_a_shipped_host(tmp_path):
    bridges = _bridges(tmp_path)
    path = _review(tmp_path, bridges, hosts=["revit", "max"])
    activation = _review_module().load_review(path, source_revision=REVISION, bridges_root=bridges)["activation"]
    result = _check(_shipped_index(tmp_path / "a", activation), path, bridges)
    assert result.returncode == 1 and "autocad 2024" in result.stdout


def test_release_builds_require_the_review_and_run_the_check():
    release = (ROOT / "installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert "if (-not $BrokerReviewPath -and -not $isCandidate) {" in release
    head = release[:release.index("$output = [IO.Path]::GetFullPath($OutputDirectory)")]
    assert "if (-not $BrokerReviewPath -and -not $isCandidate) {" in head, "refused before any output is made"
    build = release[release.index("installer/build_host_bridges.ps1"):release.index("& $compiler ")]
    assert "host_artifact_review.py" in build and "'check'" in build
    assert "Release refused: a shipped host broker is unreviewed" in build
    script = (ROOT / "installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    # AutoCAD years carry the same supplied review; activation is still never invented.
    assert script.count("reviewed-authenticated-broker") == 1
    assert "if ($review) { $index.autocad[\"$year\"].activation = $review }" in script
    assert "no AutoCAD registration owner exists" not in script


# ------------------------------------------------------------ AutoCAD setup --

@pytest.fixture
def acad(tmp_path):
    install = tmp_path / "ArchHub"
    program_files = tmp_path / "Program Files"
    host = program_files / "Autodesk" / "AutoCAD 2025"
    host.mkdir(parents=True)
    for name in ("acad.exe", "acmgd.dll", "acdbmgd.dll", "accoremgd.dll"):
        (host / name).write_bytes(b"MZ " + name.encode())
    profile = tmp_path / "Users" / "person"
    appdata = profile / "AppData" / "Roaming"
    appdata.mkdir(parents=True)
    env = {"USERPROFILE": str(profile), "APPDATA": str(appdata), "ProgramFiles": str(program_files),
           "ProgramData": str(tmp_path / "ProgramData"), "LOCALAPPDATA": str(profile / "AppData" / "Local")}
    bundle = appdata / "Autodesk" / "ApplicationPlugins" / "ArchHub.AcadMCP.bundle"
    return type("Acad", (), {"install": install, "host": host, "env": env, "bundle": bundle})


def _pin(path: Path) -> dict:
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _acad_package(acad, year="2025", *, reviewed=True, body=b"MZ acadmcp"):
    payload = acad.install / "bridges" / "autocad" / year
    payload.mkdir(parents=True, exist_ok=True)
    (payload / "AcadMCP.dll").write_bytes(body + b" " + year.encode())
    (payload / "Newtonsoft.Json.dll").write_bytes(b"MZ json")
    row = {"assembly": "bridges/autocad/%s/AcadMCP.dll" % year,
           "files": [{"path": "bridges/autocad/%s/%s" % (year, name), **_pin(payload / name)}
                     for name in ("AcadMCP.dll", "Newtonsoft.Json.dll")],
           "host_api": {name: _pin(acad.host / name) for name in ("acmgd.dll", "acdbmgd.dll", "accoremgd.dll")},
           "framework": "net8.0-windows", "reviewed": reviewed}
    if reviewed:
        row["activation"] = {"eligibility": "reviewed-authenticated-broker", "review_sha256": "d" * 64}
    index_path = acad.install / "HOST_ARTIFACTS.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"revit": {}, "autocad": {}}
    index["autocad"][year] = row
    index_path.write_text(json.dumps(index))


def test_setup_registers_the_reviewed_autocad_add_in_as_a_user_bundle(acad):
    _acad_package(acad)
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "registered_pending_host_restart", rows
    contents = ET.parse(acad.bundle / "PackageContents.xml").getroot()
    assert contents.tag == "ApplicationPackage"
    entries = contents.findall("./Components/ComponentEntry")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.get("ModuleName") == "./Contents/2025/AcadMCP.dll"
    assert entry.get("AppType") == ".Net" and entry.get("LoadOnAutoCADStartup") == "True"
    requirement = entry.find("RuntimeRequirements")
    assert (requirement.get("SeriesMin"), requirement.get("SeriesMax"), requirement.get("OS")) == ("R25.0", "R25.0", "Win64")
    shipped = acad.install / "bridges" / "autocad" / "2025"
    for name in ("AcadMCP.dll", "Newtonsoft.Json.dll"):
        assert (acad.bundle / "Contents" / "2025" / name).read_bytes() == (shipped / name).read_bytes()
    again = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert again[0]["status"] == "unchanged_pending_host_restart", again


def test_an_unreviewed_or_altered_autocad_payload_is_never_registered(acad):
    _acad_package(acad, reviewed=False)
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused" and "not reviewed for activation" in rows[0]["reason"]
    assert not acad.bundle.exists()
    _acad_package(acad, reviewed=True)
    (acad.install / "bridges" / "autocad" / "2025" / "AcadMCP.dll").write_bytes(b"MZ swapped after release")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused" and "artifact" in rows[0]["reason"]
    assert not acad.bundle.exists()


def test_an_autocad_host_that_differs_from_the_reviewed_api_is_refused(acad):
    _acad_package(acad)
    (acad.host / "acmgd.dll").write_bytes(b"MZ updated host")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused" and "host API" in rows[0]["reason"]
    assert not acad.bundle.exists()


def test_a_bundle_setup_did_not_place_is_left_alone(acad):
    _acad_package(acad)
    acad.bundle.mkdir(parents=True)
    (acad.bundle / "PackageContents.xml").write_text("<ApplicationPackage/>")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused" and "not placed by ArchHub" in rows[0]["reason"]
    assert (acad.bundle / "PackageContents.xml").read_text() == "<ApplicationPackage/>"


def test_an_upgrade_replaces_only_the_bundle_this_install_placed(acad):
    _acad_package(acad)
    colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    _acad_package(acad, body=b"MZ acadmcp v2")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "registered_pending_host_restart", rows
    assert (acad.bundle / "Contents" / "2025" / "AcadMCP.dll").read_bytes() == b"MZ acadmcp v2 2025"
    # A file someone else added makes the bundle no longer provably ours.
    (acad.bundle / "Contents" / "2025" / "extra.dll").write_bytes(b"MZ someone else")
    _acad_package(acad, body=b"MZ acadmcp v3")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused"
    assert (acad.bundle / "Contents" / "2025" / "AcadMCP.dll").read_bytes() == b"MZ acadmcp v2 2025"


def test_an_autocad_year_without_a_known_series_is_refused_not_guessed(acad):
    host = acad.host.parent / "AutoCAD 2029"
    host.mkdir()
    for name in ("acmgd.dll", "acdbmgd.dll", "accoremgd.dll"):
        (host / name).write_bytes(b"MZ " + name.encode())
    acad.host = host
    _acad_package(acad, "2029")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2029"])
    assert rows[0]["status"] == "refused" and "series" in rows[0]["reason"]


def test_setup_runs_the_autocad_registration():
    source = inspect.getsource(colleague_setup.main)
    assert "register_autocad_add_ins(Path(os.path.abspath(__file__)).parent)" in source


def test_uninstall_removes_only_the_autocad_files_this_install_placed(acad, tmp_path):
    import os
    import shutil
    _acad_package(acad)
    colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    foreign = acad.bundle / "Contents" / "2025" / "someone-else.txt"
    foreign.write_text("keep")
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    out = tmp_path / "harness-out"
    built = subprocess.run([compiler, "/Q", "/O" + str(out), str(ROOT / "tests_replica" / "host_uninstall_harness.iss")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    done = tmp_path / "done.txt"
    empty = tmp_path / "none"
    subprocess.run([str(out / "host-uninstall-harness.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/revit=" + str(empty), "/app=" + str(acad.install), "/max=" + str(empty),
                    "/shipped=" + str(empty / "x.py"), "/acad=" + str(acad.bundle), "/done=" + str(done)], timeout=120)
    assert done.read_text() == "ran"
    assert not (acad.bundle / "PackageContents.xml").exists()
    assert not (acad.bundle / "Contents" / "2025" / "AcadMCP.dll").exists()
    assert foreign.read_text() == "keep"
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    step = iss[iss.index("procedure CurUninstallStepChanged"):]
    assert "RemoveOwnAutocadBundle(ExpandConstant('{userappdata}') + '\\Autodesk\\ApplicationPlugins\\ArchHub.AcadMCP.bundle');" in step


# ------------------------------------------------------------ Rhino / Blender --

def test_rhino_and_blender_rows_offer_the_one_click_open_not_a_missing_folder():
    import nodelang.host_brokers as hb
    source = inspect.getsource(hb.probe_host_rows)
    assert "payload/rhino" not in source
    assert 'say \\"open Rhino\\" in ArchHub' in source and 'say \\"open Blender\\" in ArchHub' in source


def test_setup_tells_the_person_how_to_connect_rhino_and_blender(capsys, tmp_path):
    (tmp_path / "bridges" / "rhino").mkdir(parents=True)
    (tmp_path / "bridges" / "rhino" / "archhub_mcp.py").write_text("#")
    (tmp_path / "bridges" / "blender" / "archhub_mcp").mkdir(parents=True)
    (tmp_path / "bridges" / "blender" / "archhub_mcp" / "__init__.py").write_text("#")
    rows = colleague_setup.report_rhino_blender(tmp_path, detected={"rhino": ["8"], "blender": []})
    out = capsys.readouterr().out
    assert rows == [{"host": "rhino", "version": "8", "status": "one-click-open"}]
    assert 'say "open Rhino" in ArchHub' in out
    assert "blender" not in out.lower()

# ------------------------------------------------ verifier findings, round 2 --

def test_the_bridges_digest_covers_every_file_including_bytecode(tmp_path):
    review = _review_module()
    bridges = _bridges(tmp_path)
    before = review.bridges_tree_sha256(bridges)
    cache = bridges / "rhino" / "__pycache__"
    cache.mkdir()
    (cache / "archhub_mcp.cpython-314.pyc").write_bytes(b"\x00 loadable bytecode")
    assert review.bridges_tree_sha256(bridges) != before
    stray = bridges / "rhino" / "extra.pyo"
    stray.write_bytes(b"\x00")
    assert review.bridges_tree_sha256(bridges) != before


def _forge_bundle(acad, receipt_text=None):
    """A same-named bundle whose receipt honestly lists its own files: not ours."""
    import hashlib as _h
    files = {"PackageContents.xml": b"<ApplicationPackage ProductCode=\"x\"/>",
             "Contents/2025/AcadMCP.dll": b"MZ someone else"} if receipt_text is None else {}
    for rel, data in files.items():
        path = acad.bundle / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    acad.bundle.mkdir(parents=True, exist_ok=True)
    if receipt_text is None:
        receipt_text = "".join("%s  %s\n" % (_h.sha256(d).hexdigest(), r) for r, d in sorted(files.items()))
    (acad.bundle / "archhub-bundle.sha256").write_text(receipt_text, encoding="utf-8")
    return files


@pytest.mark.parametrize("receipt", [None, ""])
def test_a_self_consistent_or_empty_receipt_does_not_make_a_bundle_ours(acad, receipt):
    _acad_package(acad)
    files = _forge_bundle(acad, receipt)
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused", rows
    for rel, data in files.items():
        assert (acad.bundle / rel).read_bytes() == data
    assert (acad.bundle / "archhub-bundle.sha256").exists()
    assert not (acad.bundle / "Contents" / "2025" / "Newtonsoft.Json.dll").exists()


def test_a_bundle_is_ours_only_with_our_install_record(acad, tmp_path):
    _acad_package(acad)
    first = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert first[0]["status"] == "registered_pending_host_restart"
    record = Path(acad.env["LOCALAPPDATA"]) / "ArchHub-Test" / "autocad-bundle.json"
    stored = json.loads(record.read_text(encoding="utf-8"))
    from nodelang.autocad_broker_installation import PRODUCT_CODE
    assert stored["product_code"] == PRODUCT_CODE and stored["bundle"] == str(acad.bundle)
    record.unlink()  # another user state, or a bundle copied in from elsewhere
    _acad_package(acad, body=b"MZ acadmcp v2")
    rows = colleague_setup.register_autocad_add_ins(acad.install, environment=acad.env, detected_years=["2025"])
    assert rows[0]["status"] == "refused" and "not placed by ArchHub" in rows[0]["reason"]


def _harness(tmp_path):
    import os
    import shutil
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    out = tmp_path / "harness-out"
    built = subprocess.run([compiler, "/Q", "/O" + str(out), str(ROOT / "tests_replica" / "host_uninstall_harness.iss")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return out / "host-uninstall-harness.exe"


def test_uninstall_never_follows_a_junction_inside_the_bundle(acad, tmp_path):
    victim_dir = tmp_path / "Documents"
    victim_dir.mkdir()
    victim = victim_dir / "victim.dll"
    victim.write_bytes(b"precious")
    bundle = acad.bundle
    (bundle / "Contents").mkdir(parents=True)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(bundle / "Contents" / "j"), str(victim_dir)],
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    (bundle / "archhub-bundle.sha256").write_text(
        "%s  Contents/j/victim.dll\n" % hashlib.sha256(b"precious").hexdigest(), encoding="utf-8")
    exe = _harness(tmp_path)
    done = tmp_path / "done.txt"
    empty = tmp_path / "none"
    subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/revit=" + str(empty),
                    "/app=" + str(acad.install), "/max=" + str(empty), "/shipped=" + str(empty / "x.py"),
                    "/acad=" + str(bundle), "/done=" + str(done)], timeout=120)
    assert done.read_text() == "ran"
    assert victim.read_bytes() == b"precious", "uninstall deleted a file through a junction"
    # The bundle itself redirected: its receipt and files live somewhere else entirely.
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    other = elsewhere / "victim.dll"
    other.write_bytes(b"precious too")
    (elsewhere / "archhub-bundle.sha256").write_text(
        "%s  victim.dll\n" % hashlib.sha256(b"precious too").hexdigest(), encoding="utf-8")
    redirected = tmp_path / "Plugins2" / "ArchHub.AcadMCP.bundle"
    redirected.parent.mkdir()
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(redirected), str(elsewhere)], capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    done.unlink()
    subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/revit=" + str(empty),
                    "/app=" + str(acad.install), "/max=" + str(empty), "/shipped=" + str(empty / "x.py"),
                    "/acad=" + str(redirected), "/done=" + str(done)], timeout=120)
    assert done.read_text() == "ran"
    assert other.read_bytes() == b"precious too", "uninstall deleted through a redirected bundle"
    assert (elsewhere / "archhub-bundle.sha256").exists()
    host_registrations = (ROOT / "installer" / "host_registrations.iss").read_text(encoding="utf-8")
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in host_registrations


def _compile_reviewed_core(tmp_path):
    import os
    csc = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
    if not os.path.isfile(csc):
        pytest.skip("no .NET Framework csc on this machine")
    harness = tmp_path / "Harness.cs"
    harness.write_text(
        "using System;\n"
        "class H { static int Main(string[] a) { string why; "
        "bool ok = ArchHub.Shared.ReviewedCore.Verify(a[0], a[1], out why); "
        "Console.WriteLine(ok ? \"ACCEPTED\" : \"REFUSED: \" + why); return ok ? 0 : 1; } }\n")
    exe = tmp_path / "reviewed_core.exe"
    built = subprocess.run([csc, "/nologo", "/out:" + str(exe), str(harness),
                            str(ROOT / "bridges" / "sources" / "shared" / "ReviewedCore.cs")],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    return exe


def test_revit_reload_loads_only_the_installed_core_matching_its_reviewed_pin(tmp_path):
    exe = _compile_reviewed_core(tmp_path)
    install = tmp_path / "bridges" / "revit" / "2025"
    install.mkdir(parents=True)
    core = install / "RevitMCPCore.dll"
    core.write_bytes(b"MZ reviewed core")
    elsewhere = tmp_path / "Downloads" / "RevitMCPCore.dll"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"MZ reviewed core")

    def run(candidate):
        result = subprocess.run([str(exe), str(candidate), str(core)], capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout

    def manifest(sha, reviewed=True):
        body = {"schema": "archhub-host-artifacts/v1", "host": "revit", "host_version": "2025",
                "files": [{"path": "bridges/revit/2025/RevitMCP.dll", "size": 1, "sha256": "0" * 64},
                          {"path": "bridges/revit/2025/RevitMCPCore.dll", "size": 16, "sha256": sha}]}
        if reviewed:
            body["activation"] = {"eligibility": "reviewed-authenticated-broker", "review_sha256": "b" * 64}
        (install / "host-artifacts.json").write_text(json.dumps(body, indent=4), encoding="utf-8")

    pin = hashlib.sha256(b"MZ reviewed core").hexdigest()
    assert run(core)[0] == 1  # no manifest beside it
    manifest(pin, reviewed=False)
    assert run(core)[0] == 1 and "not reviewed" in run(core)[1]
    manifest(pin)
    assert run(core) == (0, "ACCEPTED\n") or run(core)[1].strip() == "ACCEPTED"
    assert run(elsewhere)[0] == 1 and "only the installed reviewed Core" in run(elsewhere)[1]
    core.write_bytes(b"MZ unreviewed core")
    assert run(core)[0] == 1 and "differs from the reviewed pin" in run(core)[1]


def test_both_sides_of_revit_reload_go_through_the_reviewed_core_gate():
    sources = ROOT / "bridges" / "sources"
    core = (sources / "revit_mcp_core" / "RevitMCPCore.cs").read_text(encoding="utf-8")
    reload = core[core.index("private async Task<string> ReloadAsync"):core.index("// ─── session registry")]
    assert "ReviewedCore.Verify(newCorePath, _corePath, out var why)" in reload
    assert reload.index("ReviewedCore.Verify") < reload.index("trigger(pathCapture)")
    shim = (sources / "revit_mcp" / "RevitMCPApp.cs").read_text(encoding="utf-8")
    trigger = shim[shim.index("Action<string> reloadTrigger"):shim.index("Func<Func<object, string>, Task<string>> submit")]
    # The shim verifies and reads in one step (VerifyAndRead), then loads those bytes.
    assert "ReviewedCore.VerifyAndRead(newPath, _installedCorePath, out var why)" in trigger
    assert trigger.index("ReviewedCore.Verify") < trigger.index("_loader.Unload()")
    for project in ("revit_mcp/RevitMCP.csproj", "revit_mcp_core/RevitMCPCore.csproj"):
        assert '<Compile Include="..\\shared\\ReviewedCore.cs"' in (sources / project).read_text(encoding="utf-8"), project


def test_script_compilation_ignores_an_environment_compiler_override():
    compiler = (ROOT / "bridges" / "sources" / "shared" / "ScriptCompiler.cs").read_text(encoding="utf-8")
    assert "ARCHHUB_CSC_PATH" not in compiler
    assert "ARCHHUB_CSC_PATH" not in (ROOT / "colleague_setup.py").read_text(encoding="utf-8")


def test_the_autocad_api_package_is_pinned_exactly_per_year():
    import re as _re
    project = (ROOT / "bridges" / "sources" / "acad_mcp" / "AcadMCP.csproj").read_text(encoding="utf-8")
    assert "-*" not in project and "$(AcadObjectArxMajor)" not in project
    pins = dict(_re.findall(r"<AcadPackageVersion Condition=\"'\$\(AcadYear\)' == '(20\d\d)'\">([0-9.]+)</AcadPackageVersion>", project))
    assert pins == {"2020": "23.1.0", "2021": "24.0.0", "2022": "24.1.51000", "2023": "24.2.0",
                    "2024": "24.3.0", "2025": "25.0.2", "2026": "25.1.1", "2027": "26.0.0"}
    assert 'Version="[$(AcadPackageVersion)]"' in project
    assert "No exact AutoCAD.NET pin for AutoCAD $(AcadYear)" in project

# ------------------------------------------- reload loads the verified bytes --

def _compile_verified_read(tmp_path):
    import os
    csc = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
    if not os.path.isfile(csc):
        pytest.skip("no .NET Framework csc on this machine")
    harness = tmp_path / "Harness2.cs"
    harness.write_text(
        "using System; using System.IO; using ArchHub.Shared;\n"
        "class H { static int Main(string[] a) { string why;\n"
        "  var m = ReviewedCore.VerifyAndRead(a[0], a[1], out why);\n"
        "  if (m == null) { Console.WriteLine(\"REFUSED: \" + why); return 1; }\n"
        "  File.WriteAllBytes(a[1], new byte[] { 1, 2, 3 });\n"  # the path changes after the check
        "  Console.WriteLine(\"ACCEPTED \" + m.Count + \" \" + ReviewedCore.Sha256OfBytes(m[\"RevitMCPCore\"])"
        " + \" \" + ReviewedCore.Sha256OfBytes(m[\"System.Text.Json\"])); return 0; } }\n")
    exe = tmp_path / "verified_read.exe"
    built = subprocess.run([csc, "/nologo", "/out:" + str(exe), str(harness),
                            str(ROOT / "bridges" / "sources" / "shared" / "ReviewedCore.cs")],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    return exe


def test_reload_hands_the_loader_the_bytes_it_hashed_and_pins_every_dependency(tmp_path):
    exe = _compile_verified_read(tmp_path)
    install = tmp_path / "bridges" / "revit" / "2025"
    install.mkdir(parents=True)
    bodies = {"RevitMCP.dll": b"MZ shim", "RevitMCPCore.dll": b"MZ reviewed core", "System.Text.Json.dll": b"MZ json"}

    def lay_out():
        for name, body in bodies.items():
            (install / name).write_bytes(body)
        rows = [{"path": "bridges/revit/2025/" + name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                for name, body in bodies.items()]
        (install / "host-artifacts.json").write_text(json.dumps(
            {"schema": "archhub-host-artifacts/v1", "host": "revit", "host_version": "2025", "files": rows,
             "activation": {"eligibility": "reviewed-authenticated-broker", "review_sha256": "b" * 64}}, indent=4),
            encoding="utf-8")

    core = install / "RevitMCPCore.dll"

    def run():
        result = subprocess.run([str(exe), str(core), str(core)], capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout.strip()

    lay_out()
    code, out = run()
    assert code == 0, out
    # The returned Core bytes are the reviewed ones although the file changed after the check.
    assert out == "ACCEPTED 2 %s %s" % (hashlib.sha256(b"MZ reviewed core").hexdigest(),
                                         hashlib.sha256(b"MZ json").hexdigest())
    lay_out()
    (install / "System.Text.Json.dll").write_bytes(b"MZ swapped dependency")
    code, out = run()
    assert code == 1 and "System.Text.Json.dll differs from its reviewed pin" in out, out
    lay_out()
    (install / "Evil.dll").write_bytes(b"MZ unpinned")
    code, out = run()
    assert code == 1 and "unpinned DLL beside Core: Evil.dll" in out, out
    (install / "Evil.dll").unlink()
    (install / "System.Text.Json.dll").unlink()
    code, out = run()
    assert code == 1 and "System.Text.Json.dll" in out, out


def test_the_loader_never_rereads_a_verified_core_or_dependency_from_disk():
    sources = ROOT / "bridges" / "sources"
    loader = (sources / "shared" / "CoreLoader.cs").read_text(encoding="utf-8")
    assert "IDictionary<string, byte[]> verified" in loader
    load = loader[loader.index("public int Load("):loader.index("// Find the *.CoreEntry type")]
    assert "_alc.LoadFromStream(new MemoryStream(coreBytes))" in load
    assert "Assembly.Load(coreBytes)" in load
    resolving = loader[loader.index("private Assembly AlcResolving"):loader.index("public void Unload()")]
    assert resolving.index("if (verified != null)") < resolving.index("LoadFromAssemblyPath")
    assert "ctx.LoadFromStream(new MemoryStream(bytes))" in resolving
    shim = (sources / "revit_mcp" / "RevitMCPApp.cs").read_text(encoding="utf-8")
    trigger = shim[shim.index("Action<string> reloadTrigger"):shim.index("Func<Func<object, string>, Task<string>> submit")]
    assert "ReviewedCore.VerifyAndRead(newPath, _installedCorePath, out var why)" in trigger
    assert "LoadCoreInto(newPath, verified)" in trigger
    resolver = shim[shim.index("private static Assembly AddinDirResolver"):]
    assert resolver.index("CoreLoader.VerifiedDependencies") < resolver.index("Assembly.LoadFrom(candidate)")
    core = (sources / "revit_mcp_core" / "RevitMCPCore.cs").read_text(encoding="utf-8")
    # Loaded from bytes, Core has no Location; scripts reference the installed, verified file.
    assert "string.IsNullOrEmpty(typeof(ScriptContext).Assembly.Location) ? _corePath" in core