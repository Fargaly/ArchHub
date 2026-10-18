[CmdletBinding()]
param(
    [string]$BaseTag,
    [string]$CandidateTag,
    [string]$WorkRoot = 'C:\',
    [string]$BaseInstaller,
    [string]$CandidateInstaller,
    [string]$BaseNotes,
    [string]$CandidateNotes,
    [string]$PythonInstaller,
    [ValidateRange(30,7200)][int]$StepDeadline = 1800,
    [ValidateRange(1073741824,1099511627776)][long]$WorkingReserveBytes = 6442450944,
    [ValidateRange(268435456,8937168896)][long]$FixtureBytes = 8937168896,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$repository = 'Fargaly/archhub-rehearsal'
$pythonDigest = '9D9EB2709EF81BF5CD30DB3C2096BDBC4EA10087C22E62F27D356B36F6AE9649'
$legacyDigest = 'AB968ABE5B78DB0BE4C51C0321A2F1F5F6DA58B74914503A3AC3A9902C90F258'
$core = Join-Path $PSScriptRoot '..\rollback-rehearsal.ps1'
$utf8 = [Text.UTF8Encoding]::new($false)
if ($DryRun) {
    $absoluteRoot = [IO.Path]::GetFullPath($WorkRoot).TrimEnd('\')
    $nativeLocal = [Environment]::GetFolderPath('LocalApplicationData')
    foreach ($protected in @((Join-Path $nativeLocal 'ArchHub'),(Join-Path $nativeLocal 'ArchHub-Test'))) {
        if ($absoluteRoot -eq $protected -or $protected.StartsWith($absoluteRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $absoluteRoot.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'DryRun requires an isolated WorkRoot outside application profiles.' }
    }
}
if (-not $DryRun) {
    if ((& $core -CheckExecutionProfile) -ne 'GITHUB' -or $WorkRoot -ne 'C:\') { throw 'Only the approved GitHub-hosted runneradmin profile may prepare a real rehearsal.' }
    foreach ($tag in @($BaseTag,$CandidateTag)) {
        if ($tag -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$') { throw 'A release tag is missing or invalid.' }
    }
    $BaseInstaller = Join-Path $WorkRoot 'Mainrel0400\ArchHub-Setup-0.exe'
    $CandidateInstaller = Join-Path $WorkRoot 'MainrelMain\ArchHub-Setup-0.exe'
    $PythonInstaller = Join-Path $WorkRoot 'MainrelPython\python-3.14.7-amd64.exe'
    foreach ($file in @($BaseInstaller,$CandidateInstaller,$PythonInstaller)) {
        if (Test-Path -LiteralPath $file) { throw 'Rehearsal inputs already exist; refusing a reused runner.' }
    }
    foreach ($directory in @('Mainrel0400','MainrelMain','MainrelPython','MainrelInput','MainrelResults')) {
        New-Item -ItemType Directory -Path (Join-Path $WorkRoot $directory) -Force | Out-Null
    }
    & gh release download $BaseTag --repo $repository --pattern 'ArchHub-Setup-0.exe' --dir (Split-Path $BaseInstaller)
    if ($LASTEXITCODE -ne 0) { throw 'Base release download failed.' }
    $BaseNotes = (& gh release view $BaseTag --repo $repository --json body --jq '.body') -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Base release notes could not be read.' }
    & gh release download $CandidateTag --repo $repository --pattern 'ArchHub-Setup-0.exe' --dir (Split-Path $CandidateInstaller)
    if ($LASTEXITCODE -ne 0) { throw 'Candidate release download failed.' }
    $CandidateNotes = (& gh release view $CandidateTag --repo $repository --json body --jq '.body') -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Candidate release notes could not be read.' }
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe' -OutFile $PythonInstaller
}
function Release-Identity($File,$Notes) {
    $hashes = [regex]::Matches($Notes,'(?im)^SHA256\s+ArchHub-Setup-0\.exe:\s*([a-f0-9]{64})(?:\s*\(\d+ bytes\))?\s*$')
    $builds = [regex]::Matches($Notes,'(?im)^BUILD_ID:\s*([A-Za-z0-9._-]{1,128})\s*$')
    if ($hashes.Count -ne 1 -or $builds.Count -ne 1) { throw 'Release notes need exactly one SHA256 asset line and one BUILD_ID line.' }
    $observed = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
    if ($observed -ne $hashes[0].Groups[1].Value) { throw 'Release asset SHA-256 differs from its release notes.' }
    return @{sha256=$observed;build_id=$builds[0].Groups[1].Value;file=(Split-Path $File -Leaf)}
}
$base = Release-Identity $BaseInstaller $BaseNotes
$candidate = Release-Identity $CandidateInstaller $CandidateNotes
if ($base.build_id -ne '20261018-0400-fd62cb8' -or $base.build_id -eq $candidate.build_id) { throw 'The base must be0400 and the candidate must differ.' }
$pythonHash = (Get-FileHash -LiteralPath $PythonInstaller -Algorithm SHA256).Hash
if (-not $DryRun -and ($base.sha256 -ne $legacyDigest -or $pythonHash -ne $pythonDigest)) { throw 'Real0400 or pinned offline Python hash differs.' }
if ($DryRun) {
    foreach ($directory in @('MainrelInput','MainrelResults')) { New-Item -ItemType Directory -Path (Join-Path $WorkRoot $directory) -Force | Out-Null }
}
$inputDirectory = Join-Path $WorkRoot 'MainrelInput'
$planPath = Join-Path $inputDirectory 'plan.json'
if (Test-Path -LiteralPath $planPath) { throw 'A previous plan exists; evidence is never overwritten.' }
$fixed = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq 'Fixed' })
$systemRoot = [IO.Path]::GetPathRoot([Environment]::GetFolderPath('LocalApplicationData'))
$backupDrive = $fixed | Where-Object {$_.Name -ne $systemRoot} | Sort-Object AvailableFreeSpace -Descending | Select-Object -First 1
if (-not $backupDrive) { $backupDrive = [IO.DriveInfo]::new($systemRoot) }
$sameDrive = $backupDrive.Name -eq $systemRoot
$plan = [ordered]@{
    schema='archhub-rollback-rehearsal/v1';mode=$(if ($DryRun) {'DRY-RUN'} else {'GITHUB'})
    host_machine=[Environment]::MachineName;repository=$repository;run_id=$env:GITHUB_RUN_ID
    legacy_file=$base.file;main_file=$candidate.file;legacy_sha256=$base.sha256;main_sha256=$candidate.sha256
    legacy_build_id=$base.build_id;main_build_id=$candidate.build_id
    python_file=(Split-Path $PythonInstaller -Leaf);python_sha256=$pythonDigest;python_actual_sha256=$pythonHash
    step_deadline=$StepDeadline;marker=('MAINREL-rollback-'+[guid]::NewGuid().ToString('N'))
    fixture_requested_bytes=$FixtureBytes;guest_working_bytes=$WorkingReserveBytes
    minimum_guest_free_bytes=($WorkingReserveBytes+$(if ($sameDrive) {25L*1024*1024*1024} else {0}))
    backup_base=(Join-Path $backupDrive.Name 'MainrelBackups')
    measured_drives=@($fixed | ForEach-Object {@{root=$_.Name;free_bytes=$_.AvailableFreeSpace}})
    steps=@('0400-install-open-write-close','pad-synthetic-journal','main-install-open-write-close','0400-reinstall-open-main-journal-close')
}
[IO.File]::WriteAllText($planPath,($plan|ConvertTo-Json -Depth 10),$utf8)
[IO.File]::WriteAllText((Join-Path $inputDirectory 'base-release-notes.txt'),$BaseNotes,$utf8)
[IO.File]::WriteAllText((Join-Path $inputDirectory 'candidate-release-notes.txt'),$CandidateNotes,$utf8)
if ($DryRun) { Write-Output 'DRY-RUN: release note hashes verified; no downloads, installers or workflow started.' }
else { Write-Output 'Runner plan ready: release note hashes and pinned0400/Python verified.' }
