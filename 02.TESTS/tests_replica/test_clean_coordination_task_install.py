"""The installer retires both headless task launchers; no tasks are registered."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ISS = ROOT / "03.TOOLS/installer" / 'ArchHub.iss'
BUILD = ROOT / "03.TOOLS/installer" / 'build_release.ps1'
TASK_SCRIPT = 'packaging/windows/install_clean_coordination_task.ps1'


def _retirement():
    source = ISS.read_text(encoding='utf-8')
    start = source.index('procedure RemoveRetiredRuntimeTask(')
    return source, source[start:source.index('\nend;', start) + 5]


def test_installer_never_registers_another_runtime_task():
    source, _ = _retirement()
    assert 'Register-ScheduledTask' not in source
    assert '/Create ' not in source
    assert not (ROOT / TASK_SCRIPT).exists()


def test_upgrade_retires_the_clean_coordination_task():
    source, body = _retirement()
    assert "CleanCoordinationTask = 'ArchHub Clean Coordination'" in source
    assert 'RemoveRetiredRuntimeTask(CleanCoordinationTask);' in source
    assert "'/End /TN" in body and "'/Delete /TN" in body
    assert body.index("'/End /TN") < body.index("'/Delete /TN")


def test_upgrade_also_retires_the_old_universal_runtime_task():
    source, _ = _retirement()
    assert "UniversalRuntimeTask = 'ArchHub Universal Runtime'" in source
    assert 'RemoveRetiredRuntimeTask(UniversalRuntimeTask);' in source
    assert not (ROOT / "03.TOOLS/packaging/windows/install_runtime_task.ps1").exists()


def test_upgrade_has_no_unconditional_file_deletions():
    source = ISS.read_text(encoding='utf-8').split('[InstallDelete]', 1)[1].split('[UninstallDelete]', 1)[0]
    assert not any(line.startswith('Type:') for line in source.splitlines())


def test_retirement_does_not_require_a_developer_or_installed_python():
    _, body = _retirement()
    assert 'python' not in body.casefold()
    assert "{sys}\\schtasks.exe" in body
    assert "RunBounded(Scheduler, '/Query /TN" in body
    assert body.index('/Query /TN') < body.index('/End /TN')
    assert 'ewWaitUntilTerminated' not in body


def test_scheduler_requests_are_bounded_and_a_missing_task_is_left_alone(tmp_path):
    """Compile the production RunBounded/RemoveRetiredRuntimeTask and run them: a hung child is
    stopped at its limit, exit codes come back, and the real scheduler query skips an absent task."""
    import sys, time, uuid
    compiler = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
    source = ISS.read_text(encoding='utf-8')
    start = source.index('type\n  { Setup is a 32-bit')
    end = source.index('\nend;', source.index('procedure RemoveRetiredRuntimeTask(')) + 5
    absent = 'ArchHub Court Absent ' + uuid.uuid4().hex
    out, log = tmp_path / 'result.txt', tmp_path / 'setup.log'
    script = tmp_path / 'bounded.iss'
    script.write_text(r'''[Setup]
AppName=Bounded court
AppVersion=1
DefaultDirName={tmp}\court
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
OutputBaseFilename=bounded-court
[Code]
const
  SchedulerWaitMs = 15000;
''' + source[start:end] + r'''
function InitializeSetup(): Boolean;
var
  Python: String;
begin
  Python := ExpandConstant('{param:python}');
  SaveStringToFile(ExpandConstant('{param:out}'),
    IntToStr(RunBounded(Python, '-c "import time;time.sleep(60)"', 1500)) + ' ' +
    IntToStr(RunBounded(Python, '-c "import sys;sys.exit(3)"', 15000)), False);
  RemoveRetiredRuntimeTask(ExpandConstant('{param:task}'));
  Result := False;
end;
''', encoding='utf-8')
    built = subprocess.run([str(compiler), '/Q', '/O' + str(tmp_path), str(script)], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    began = time.monotonic()
    subprocess.run([str(tmp_path / 'bounded-court.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/python=' + sys.executable,
                    '/out=' + str(out), '/task=' + absent, '/LOG=' + str(log)], timeout=60)
    assert time.monotonic() - began < 30
    assert out.read_text() == '-1 3'
    text = log.read_text(errors='replace')
    # A healthy scheduler says the task is absent; a hung one (seen on the founder PC) is bounded and skipped.
    assert ('Retired runtime task ' + absent + ' absent (query exit 1).' in text
            or 'Task Scheduler did not answer for ' + absent + '; left for the next upgrade.' in text), text
    assert 'not removed' not in text


def test_all_shortcuts_use_the_same_installed_qt_launcher():
    source, _ = _retirement()
    assert '#define AppExe "ArchHub.vbs"' in source
    launcher = (ROOT / "03.TOOLS/installer/ArchHub.vbs").read_text(encoding='utf-8')
    assert 'nodelang\\launcher.py' in launcher and 'pythonw.exe' in launcher
    assert 'clean_coordination_service' not in launcher


def test_the_release_snapshot_excludes_the_retired_task_script(tmp_path):
    """build_release.ps1 compiles only its selected inputs: the script setup ships must be one,
    and its own payload filter must admit it (evaluated from the build script itself)."""
    judge = tmp_path / "judge.ps1"
    judge.write_text(r'''
param([string]$Build, [string]$Path)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
$assignment = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -ceq '$selectedInputs' }, $true)
. ([scriptblock]::Create($assignment.Extent.Text))
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -ceq 'Test-CandidateInput' }, $true)
. ([scriptblock]::Create($definition.Extent.Text))
@{ selected = ($selectedInputs -ccontains $Path); admitted = (Test-CandidateInput 'selected' $Path) } | ConvertTo-Json -Compress
''', encoding="utf-8")
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(judge), "-Build", str(BUILD), "-Path", TASK_SCRIPT],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"selected": False, "admitted": False}
