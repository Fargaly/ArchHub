"""Forcing tests for the non-destructive Windows packaging contract."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging" / "windows"


def _read(name):
    return (PACKAGE / name).read_text(encoding="utf-8")


def test_package_metadata_matches_the_universal_application_schema_and_is_versioned():
    manifest = json.loads(_read("package-manifest.json"))
    application = (ROOT / "nodelang" / "universal_application.py").read_text(
        encoding="utf-8"
    )
    schema = re.search(
    r"UNIVERSAL_APPLICATION_SCHEMA_VERSION\s*=\s*['\"]([^'\"]+)", application
    ).group(1)
    assert manifest["format"] == "archhub-windows-package-v2"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["product_version"])
    assert manifest["runtime"] == "universal-cell"
    assert manifest["universal_application_schema_version"] == schema
    assert "application_schema_version" not in manifest
    assert manifest["state_path"] == r"%LOCALAPPDATA%\ArchHub\node-native-wip.json.gz"


def test_launcher_is_portable_quiet_and_uses_only_the_bundled_runtime(tmp_path):
    launcher = _read("Launch-ArchHub.vbs")
    assert "ArchHub.exe" in launcher
    assert "python" not in launcher.lower()
    assert "C:\\Users\\" not in launcher
    assert 'shell.Run command, 0, False' in launcher
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path / "Local App Data")
    result = subprocess.run(
        ["cscript.exe", "//nologo", str(PACKAGE / "Launch-ArchHub.vbs"), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert f"executable={PACKAGE / 'ArchHub.exe'}" in result.stdout
    assert f"state_path={tmp_path / 'Local App Data' / 'ArchHub' / 'node-native-wip.json.gz'}" in result.stdout
    assert "window_style=0" in result.stdout and "wait=false" in result.stdout


def test_pyinstaller_bundle_is_windowed_onedir_and_collects_runtime_dependencies():
    spec = _read("ArchHub.spec")
    requirements = [
        line for line in _read("requirements-build.txt").splitlines() if line
    ]
    assert "console=False" in spec
    assert "COLLECT(" in spec
    assert "target_arch=\"x86_64\"" in spec
    assert "PyQt6.QtWebEngineWidgets" in spec
    assert "cryptography.hazmat.primitives.ciphers.aead" in spec
    assert "win32com.client" in spec
    assert "pythoncom" in spec
    assert "nodelang.baboom_native_runtime" in spec
    assert "spritesheet.png" in spec
    assert "public_runtime_map.json" in spec
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+==[^=\s]+", line) for line in requirements)
    assert any(line.startswith("PyInstaller==") for line in requirements)
    assert any(line.startswith("PyQt6-WebEngine==") for line in requirements)
    assert "pywin32==311" in requirements


def test_inno_contract_installs_per_user_with_shortcuts_and_preserves_wip():
    setup = _read("setup.iss")
    assert "PrivilegesRequired=lowest" in setup
    assert r"DefaultDirName={localappdata}\Programs\{#AppName}" in setup
    assert r'Name: "{userprograms}\{#AppName}"' in setup
    assert r'Name: "{userdesktop}\{#AppName}"' in setup
    assert "UninstallDisplayName={#AppName}" in setup
    assert "UninstallDisplayIcon={app}\\ArchHub.exe" in setup
    assert "[UninstallDelete]" not in setup
    assert r"{localappdata}\ArchHub\node-native-wip.json.gz" not in setup
    assert "Launch-ArchHub.vbs" in setup
    assert "{app}" not in setup.split("[Code]", 1)[1]


def test_build_outputs_stay_outside_the_repository_and_signing_uses_cert_store():
    build = _read("build.ps1")
    signing = _read("sign.ps1")
    assert 'Join-Path $env:LOCALAPPDATA "ArchHub\\packaging\\$version"' in build
    assert "requirements-build.txt" in build and "ArchHub.spec" in build
    assert "Test-SourcePortability.ps1" in build
    assert "nodelang\\universal_application.py" in build
    assert "UNIVERSAL_APPLICATION_SCHEMA_VERSION" in build
    assert "nodelang\\application.py" not in build
    assert "ARCHHUB_SIGN_CERT_SHA1" in signing
    assert "/sha1" in signing
    assert ".pfx" not in signing.lower()
    assert "/p " not in signing.lower()


def test_source_portability_gate_accepts_portable_input_and_rejects_private_absolute_paths(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "module.py").write_text("STATE = '%LOCALAPPDATA%/ArchHub'\n", encoding="utf-8")
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(PACKAGE / "Test-SourcePortability.ps1"), "-SourceRoot", str(clean),
    ]
    clean_result = subprocess.run(command, capture_output=True, text=True)
    assert clean_result.returncode == 0, clean_result.stderr

    leaked = tmp_path / "leaked"
    leaked.mkdir()
    (leaked / "module.py").write_text(
        r"AUTHORITY = 'C:\Users\founder\00.ARCHUB\30.KNOWLEDGE\map.json'" + "\n",
        encoding="utf-8",
    )
    leaked_result = subprocess.run(
        command[:-1] + [str(leaked)], capture_output=True, text=True
    )
    assert leaked_result.returncode == 3
    assert "Non-portable or private absolute paths" in (
        leaked_result.stdout + leaked_result.stderr
    )


def test_all_packaging_powershell_scripts_parse():
    for script in PACKAGE.glob("*.ps1"):
        env = os.environ.copy()
        env["ARCHHUB_PARSE_TARGET"] = str(script)
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$env:ARCHHUB_PARSE_TARGET, [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_validate_only_runs_the_complete_preflight_and_reports_tooling():
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(PACKAGE / "build.ps1"), "-ValidateOnly"],
        check=True, capture_output=True, text=True,
    )
    start = result.stdout.find("{")
    report = json.loads(result.stdout[start:])
    assert report["runtime"] == "universal-cell"
    assert report["universal_application_schema_version"] == "universal-cell-v1"
    assert report["source_portable"] is True
    assert set(report) >= {
        "pyinstaller_installed", "inno_setup_installed", "signtool_installed"
    }
