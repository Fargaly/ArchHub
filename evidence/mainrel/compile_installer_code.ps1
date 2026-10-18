$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$source = [IO.File]::ReadAllText((Join-Path $root 'installer/ArchHub.iss'))
$code = $source.Substring($source.IndexOf('[Code]'))
foreach ($include in @('legacy_sweep.iss', 'host_registrations.iss', 'host_file_staging.iss')) {
    $code = $code.Replace('#include "' + $include + '"', '#include "' + (Join-Path $root ('installer/' + $include)) + '"')
}
$court = Join-Path $PSScriptRoot 'court-state/inno-code'
New-Item -ItemType Directory -Path $court -Force | Out-Null
$header = @'
#define AppName "ArchHub"
#define AppExe "ArchHub.vbs"
#define BuildId "mainrel-code-court"
#define RequirementsSha256 "0000000000000000000000000000000000000000000000000000000000000000"
#define BundledNodeSha256 "0000000000000000000000000000000000000000000000000000000000000000"
[Setup]
AppName=MAINREL code compilation court
AppVersion=0
DefaultDirName={tmp}\MAINREL-code-court
PrivilegesRequired=lowest
Uninstallable=no
CreateAppDir=no
OutputBaseFilename=MAINREL-code-only-NOT-A-RELEASE
[Files]
'@
$files = foreach ($name in @('application_recovery_files.py', 'backup_retention.py', 'conversation_trace_shapes.py',
                            'assistant_registration.py', 'client_mcp_installation.py', 'native_workshop_profile.py')) {
    'Source: "' + (Join-Path $root ('nodelang/' + $name)) + '"; Flags: dontcopy'
}
$script = Join-Path $court 'code-court.iss'
[IO.File]::WriteAllText($script, $header + "`n" + ($files -join "`n") + "`n" + $code)
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' ('/O' + $court) $script
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output 'MAINREL full production [Code] ISCC compilation PASS; fixture installer is never run.'
