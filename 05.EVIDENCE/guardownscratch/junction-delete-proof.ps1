# Run inside an isolated profile through run-heavy.ps1, with the invoking interpreter.
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
$python = $PythonExecutable
$proofRoot = Join-Path $env:TEMP "junction-proof-$PID"
$lane = Join-Path $proofRoot 'lane-inner-junction-proof'
$workspace = Join-Path $env:USERPROFILE '00.ARCHUB'
$retained = Join-Path $workspace "70.COMPANY/retained-$PID/bytes.bin"
if ($env:USERPROFILE -notlike '*lane-guardownscratch\.cache\guardownscratch-*-profile') {
    throw 'Expected the isolated lane profile'
}
New-Item -ItemType Directory -Force -Path (Split-Path $retained), "$lane/target" | Out-Null
[IO.File]::WriteAllBytes($retained, [byte[]](0..255))
$before = (Get-FileHash -LiteralPath $retained).Hash
foreach ($link in @("$lane/node_modules", "$lane/target/msvc")) {
    New-Item -ItemType Junction -Path $link -Target (Split-Path $retained) | Out-Null
    if (-not ((Get-Item -LiteralPath $link).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Expected a real junction'
    }
}
$env:ARCHHUB_JUNCTION_PROOF_LANE = $lane
$env:ARCHHUB_JUNCTION_PROOF_WORKSPACE = $workspace
& $python -B -c 'import os; from nodelang import hook_decision as h; p=os.environ["ARCHHUB_JUNCTION_PROOF_LANE"]; assert not h.founder_data_targeted("Remove-Item -LiteralPath " + chr(34) + p + chr(34) + " -Recurse -Force", os.environ["ARCHHUB_JUNCTION_PROOF_WORKSPACE"], os.environ); print("INNER-JUNCTION powershell: shared decision ALLOWED")'
if ($LASTEXITCODE) { throw 'Shared decision refused lane cleanup' }
if (-not ([IO.Path]::GetFullPath($lane).StartsWith([IO.Path]::GetFullPath($env:TEMP) + [IO.Path]::DirectorySeparatorChar))) {
    throw 'Deletion target escaped the isolated TEMP'
}
Remove-Item -LiteralPath $lane -Recurse -Force
if ((Test-Path -LiteralPath $lane) -or (Get-FileHash -LiteralPath $retained).Hash -ne $before) {
    throw 'Lane removal or retained target bytes failed'
}
"INNER-JUNCTION PowerShell $($PSVersionTable.PSVersion): lane removed; target bytes survive; SHA256=$before"
# These are exact synthetic fixture paths, after verifying the junction target survived.
Remove-Item -LiteralPath $retained
Remove-Item -LiteralPath (Split-Path $retained)
Remove-Item -LiteralPath $proofRoot
