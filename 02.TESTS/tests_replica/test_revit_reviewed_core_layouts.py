"""Court: Revit's Core loads only the exact reviewed bytes from the right manifest, in both install layouts.

The validator (bridges/sources/shared/ReviewedCore.cs) is compiled twice, for .NET Framework (Revit
2023-2024) and for modern .NET (Revit 2025+), and run against disposable install folders:
deployed  bridges/revit/<year>/<BuildId>/RevitMCPCore.dll with the year's one host-artifacts.json one
level up (installer/build_host_bridges.ps1), and the legacy flat bridges/revit/<year>/ layout with the
manifest beside Core. No Revit is opened and no live add-in folder is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "01.APP/bridges/sources"
HARNESS = (
    "using System; using System.Linq;\n"
    "class H { static int Main(string[] a) { string why; "
    "var closure = ArchHub.Shared.ReviewedCore.VerifyAndRead(a[0], a[1], out why); "
    "if (closure == null) { Console.WriteLine(\"REFUSED: \" + why); return 1; } "
    "Console.WriteLine(\"ACCEPTED \" + string.Join(\",\", closure.Keys.OrderBy(k => k).ToArray())); return 0; } }\n")
REVIEW = {"eligibility": "reviewed-authenticated-broker", "review_sha256": "b" * 64}


def _framework(tmp_path):
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not csc.is_file():
        pytest.skip("no .NET Framework csc on this machine")
    (tmp_path / "H.cs").write_text(HARNESS, encoding="utf-8")
    exe = tmp_path / "framework.exe"
    built = subprocess.run([str(csc), "/nologo", "/out:" + str(exe), str(tmp_path / "H.cs"),
                            str(SOURCES / "shared/ReviewedCore.cs")], capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    return [str(exe)]


def _modern(tmp_path):
    dotnet = shutil.which("dotnet")
    if not dotnet:
        pytest.skip("no dotnet on this machine")
    dotnet = Path(dotnet)
    version, sdk_root = subprocess.run([str(dotnet), "--list-sdks"], capture_output=True, text=True,
                                       check=True).stdout.splitlines()[-1].split(" [", 1)
    csc = Path(sdk_root.rstrip("]")) / version / "Roslyn/bincore/csc.dll"
    pack = sorted((dotnet.parent / "packs/Microsoft.NETCore.App.Ref").glob("*"))[-1]
    references = sorted(next((pack / "ref").iterdir()).glob("*.dll"))
    (tmp_path / "H.cs").write_text(HARNESS, encoding="utf-8")
    dll = tmp_path / "modern.dll"
    command = [str(dotnet), str(csc), "/nologo", "/noconfig", "/nostdlib+", "/target:exe", "/out:" + str(dll)]
    command += ["/r:" + str(path) for path in references] + [str(tmp_path / "H.cs"), str(SOURCES / "shared/ReviewedCore.cs")]
    built = subprocess.run(command, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    runtime = next(row.split()[1] for row in subprocess.run([str(dotnet), "--list-runtimes"], capture_output=True,
                   text=True, check=True).stdout.splitlines() if row.startswith("Microsoft.NETCore.App " + pack.name.split(".")[0] + "."))
    (tmp_path / "modern.runtimeconfig.json").write_text(json.dumps({"runtimeOptions": {
        "tfm": "net%s.0" % pack.name.split(".")[0], "framework": {"name": "Microsoft.NETCore.App", "version": runtime}}}))
    return [str(dotnet), str(dll)]


@pytest.fixture(params=["framework", "modern"])
def validator(request, tmp_path):
    folder = tmp_path / ("build-" + request.param)
    folder.mkdir()
    command = (_framework if request.param == "framework" else _modern)(folder)

    def run(candidate, installed=None):
        result = subprocess.run(command + [str(candidate), str(installed or candidate)],
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout.strip()
    return run


FILES = {"RevitMCP.dll": b"MZ shim", "RevitMCPCore.dll": b"MZ reviewed core", "Microsoft.CodeAnalysis.dll": b"MZ dependency"}


def _install(root: Path, *, year="2025", build="build-20261122-0101-abc1234", flat=False, review=True,
             rows_build=None, files=FILES):
    year_folder = root / "bridges" / "revit" / year
    core_folder = year_folder if flat else year_folder / build
    core_folder.mkdir(parents=True)
    prefix = "bridges/revit/%s/" % year + ("" if flat else "%s/" % (rows_build or build))
    for name, data in files.items():
        (core_folder / name).write_bytes(data)
    manifest = {"schema": "archhub-host-artifacts/v1", "host": "revit", "host_version": year,
                "assembly": prefix + "RevitMCP.dll",
                "files": [{"path": prefix + name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()],
                "host_api": {"RevitAPI.dll": {"size": 1, "sha256": "a" * 64}}}
    if review:
        manifest["runtime_closure_reviewed"] = True
        manifest["activation"] = REVIEW
    (year_folder / "host-artifacts.json").write_text(json.dumps(manifest, indent=4), encoding="utf-8")
    return core_folder / "RevitMCPCore.dll"


def test_the_deployed_build_folder_loads_the_reviewed_bytes_from_the_year_manifest(validator, tmp_path):
    core = _install(tmp_path)
    assert validator(core) == (0, "ACCEPTED Microsoft.CodeAnalysis,RevitMCPCore")


def test_a_four_digit_build_id_is_a_deployed_folder_not_a_year(validator, tmp_path):
    core = _install(tmp_path, build="1200")
    assert validator(core) == (0, "ACCEPTED Microsoft.CodeAnalysis,RevitMCPCore")
    other = _install(tmp_path / "b", build="1200", rows_build="1300")
    code, out = validator(other)
    assert code == 1 and "does not pin exactly one Core" in out


def test_the_legacy_flat_layout_still_loads(validator, tmp_path):
    core = _install(tmp_path, flat=True)
    assert validator(core) == (0, "ACCEPTED Microsoft.CodeAnalysis,RevitMCPCore")


def test_another_builds_rows_never_pin_this_folder(validator, tmp_path):
    core = _install(tmp_path, rows_build="build-older")
    code, out = validator(core)
    assert code == 1 and "does not pin exactly one Core" in out


def test_an_unreviewed_sibling_in_the_build_folder_refuses(validator, tmp_path):
    core = _install(tmp_path)
    (core.parent / "Injected.dll").write_bytes(b"MZ not reviewed")
    code, out = validator(core)
    assert code == 1 and "unpinned DLL beside Core: Injected.dll" in out


def test_changed_bytes_or_missing_review_refuse(validator, tmp_path):
    core = _install(tmp_path / "a")
    core.write_bytes(b"MZ changed core")
    assert validator(core)[0] == 1 and "differs from the reviewed pin" in validator(core)[1]
    unreviewed = _install(tmp_path / "b", review=False)
    assert validator(unreviewed)[0] == 1 and "not reviewed for activation" in validator(unreviewed)[1]


def test_only_the_installed_core_and_a_known_layout_are_accepted(validator, tmp_path):
    core = _install(tmp_path / "a")
    copy = tmp_path / "Downloads" / "RevitMCPCore.dll"
    copy.parent.mkdir()
    copy.write_bytes(FILES["RevitMCPCore.dll"])
    assert validator(copy, core)[0] == 1 and "only the installed reviewed Core" in validator(copy, core)[1]
    stray = tmp_path / "b" / "elsewhere" / "RevitMCPCore.dll"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(FILES["RevitMCPCore.dll"])
    assert validator(stray)[0] == 1 and "not in an installed" in validator(stray)[1]
