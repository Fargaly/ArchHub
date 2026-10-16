"""Contracts of the sole colleague installer; no install or app is launched."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packaging' / 'windows'


def test_one_package_uses_the_current_product_version_and_canonical_state():
    from nodelang.persistence import application_database_path
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert application_database_path(Path('fixture-profile')).name == 'authority.sqlite3'
    assert not (PACKAGE / 'package-manifest.json').exists()


def test_installed_launcher_uses_only_its_private_pythonw_and_same_entry():
    launcher = (ROOT / 'installer/ArchHub.vbs').read_text(encoding='utf-8')
    assert 'launch_archhub_test.py' in launcher
    assert '\\.venv\\Scripts\\pythonw.exe' in launcher
    assert 'C:\\Users\\' not in launcher
    assert 'args, 0, True' in launcher
    assert not (PACKAGE / 'Launch-ArchHub.vbs').exists()


def test_the_single_runtime_ships_qt_webengine_and_host_dependencies():
    requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    assert 'PyQt6>=' in requirements and 'PyQt6-WebEngine>=' in requirements
    assert 'pywin32==311' in requirements
    assert not (PACKAGE / 'ArchHub.spec').exists()
    assert not (PACKAGE / 'entrypoint.py').exists()


def test_per_user_shortcuts_all_use_the_same_application_icon_and_launcher():
    source = (ROOT / 'installer/ArchHub.iss').read_text(encoding='utf-8')
    assert 'PrivilegesRequired=lowest' in source
    assert 'DefaultDirName={localappdata}\\ArchHub' in source
    shortcuts = source.split('[Icons]', 1)[1].split('[', 1)[0]
    assert shortcuts.count('Filename: "{app}\\{#AppExe}"') == 2
    assert shortcuts.count('IconFilename: "{app}\\archhub.ico"') == 2
    uninstall = source.split('[UninstallDelete]', 1)[1].split('[', 1)[0]
    assert '{localappdata}' not in uninstall


def test_build_requires_an_explicit_output_and_signing_uses_the_os_certificate_store():
    build = (ROOT / 'installer/build_release.ps1').read_text(encoding='utf-8')
    signing = (PACKAGE / 'sign.ps1').read_text(encoding='utf-8')
    assert '[string]$OutputDirectory' in build
    assert 'ARCHHUB_SIGN_CERT_SHA1' in signing and '/sha1' in signing
    assert '.pfx' not in signing.lower() and '/p ' not in signing.lower()
    assert not (PACKAGE / 'build.ps1').exists()


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


def test_the_module_entry_can_be_imported_without_loading_qt_or_an_application():
    code = "import sys; import nodelang.desktop; assert 'PyQt6.QtWidgets' not in sys.modules"
    done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
