"""Contracts of the sole colleague installer; no install or app is launched."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "03.TOOLS/packaging" / 'windows'


def test_one_package_uses_the_current_product_version_and_canonical_state():
    from nodelang.persistence import application_database_path
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert application_database_path(Path('fixture-profile')).name == 'authority.sqlite3'
    assert not (PACKAGE / 'package-manifest.json').exists()


def test_installed_launcher_uses_only_its_private_pythonw_and_same_entry(tmp_path):
    launcher = (ROOT / "03.TOOLS/installer/ArchHub.vbs").read_text(encoding='utf-8')
    assert 'nodelang\\launcher.py' in launcher
    assert '\\.venv\\Scripts\\pythonw.exe' in launcher
    assert 'C:\\Users\\' not in launcher
    if os.name == 'nt':
        function = launcher[launcher.index('Function RunAndWait('):launcher.index('Function RecoverFailedUpdate()')]
        harness = tmp_path / 'BOOTSTRAP.vbs'
        harness.write_text('''Class ShellFixture
Function Run(command, style, wait)
If command <> "fixture command" Or style <> 0 Or wait <> True Then Err.Raise 5
Run = 7
End Function
End Class
Dim sh
Set sh = New ShellFixture
''' + function + '''
If RunAndWait("fixture command", 0) <> 7 Then WScript.Quit 1
WScript.Echo "HIDDEN WAIT PASS"
''', encoding='utf-8')
        result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/cscript.exe'), '//nologo', str(harness)],
            capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and 'HIDDEN WAIT PASS' in result.stdout, result.stdout + result.stderr
    assert not (PACKAGE / 'Launch-ArchHub.vbs').exists()


def test_the_single_runtime_ships_qt_webengine_and_host_dependencies():
    requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    assert 'PyQt6>=' in requirements and 'PyQt6-WebEngine>=' in requirements
    assert 'pywin32==311' in requirements
    assert not (PACKAGE / 'ArchHub.spec').exists()
    assert not (PACKAGE / 'entrypoint.py').exists()


def test_per_user_shortcuts_all_use_the_same_application_icon_and_launcher():
    source = (ROOT / "03.TOOLS/installer/ArchHub.iss").read_text(encoding='utf-8')
    assert 'PrivilegesRequired=lowest' in source
    assert 'DefaultDirName={localappdata}\\ArchHub' in source
    shortcuts = source.split('[Icons]', 1)[1].split('[', 1)[0]
    assert shortcuts.count('Filename: "{app}\\{#AppExe}"') == 2
    assert shortcuts.count('IconFilename: "{app}\\archhub.ico"') == 2
    uninstall = source.split('[UninstallDelete]', 1)[1].split('[', 1)[0]
    assert '{localappdata}' not in uninstall


def test_build_requires_an_explicit_output_and_signing_uses_the_os_certificate_store():
    build = (ROOT / "03.TOOLS/installer/build_release.ps1").read_text(encoding='utf-8')
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


def test_reviewed_lane_copy_has_one_contained_candidate_output_root(tmp_path):
    lane = tmp_path / 'LANE'
    source = lane / '01.WIP' / 'PRODUCT'
    source.mkdir(parents=True)
    (source / '.git').mkdir()
    (lane / 'README.md').write_text('Public product source; private fixtures stay outside PRODUCT.')
    (lane / 'REGISTER.md').write_text('Generated register')
    outside = tmp_path / 'PRIVATE' / 'PRODUCT'
    outside.mkdir(parents=True)
    env = dict(os.environ, ARCHHUB_PACKAGE_SOURCE=str(ROOT / "03.TOOLS/installer/build_release.ps1"),
               ARCHHUB_ALLOWED_SOURCE=str(source), ARCHHUB_DENIED_SOURCE=str(outside))
    command = r"""
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:ARCHHUB_PACKAGE_SOURCE,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Builder parse failed'}
$definition=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CandidateRoots'},$true)
if($null -eq $definition){throw 'No governed lane candidate reader'}
. ([scriptblock]::Create($definition.Extent.Text))
$roots=@(Get-CandidateRoots $env:ARCHHUB_ALLOWED_SOURCE)
if($roots.Count -ne 1 -or $roots[0] -cne (Split-Path -Parent $env:ARCHHUB_ALLOWED_SOURCE)){throw 'Lane output escaped WIP'}
$refused=$false
try { Get-CandidateRoots $env:ARCHHUB_DENIED_SOURCE | Out-Null } catch { $refused=$true }
if(-not $refused){throw 'Ungoverned source accepted'}
Remove-Item -LiteralPath (Join-Path (Split-Path -Parent $roots[0]) 'REGISTER.md')
$refused=$false
try { Get-CandidateRoots $env:ARCHHUB_ALLOWED_SOURCE | Out-Null } catch { $refused=$true }
if($refused){throw 'Missing routine register blocked the reviewed source'}
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
