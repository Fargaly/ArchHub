$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
$profileRoot = Join-Path $PSScriptRoot 'court-state/js-proposal-profile'
foreach ($name in @('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP')) {
    $directory = Join-Path $profileRoot $name
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
$env:ARCHHUB_TEST_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ArchHub'
$env:PYTHON = 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe'
foreach ($name in @('LAZYBOOT_CANVAS_REPORT','LAZYBOOT_WORKSPACE_REPORT','LAZYBOOT_GRAPH_REPORT','ARCHHUB_LEGACY_STATE_DIR')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$original = [IO.File]::ReadAllText((Join-Path $root 'tests_js/studio_lazyboot_home.test.cjs'))
$old = "const projectionEnd = html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);', end);"
$replacement = @'
const projectionEnd = html.indexOf('    const {nodes, wires} = window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;', end);
assert.ok(projectionEnd > end, 'canvas loader declarations end before the authenticated owner read');
'@
if ($original.Split(@($old), [StringSplitOptions]::None).Count -ne 2) {
    throw 'Proposal requires exactly one unchanged extraction boundary'
}
$target = Join-Path $root 'tmp-base/studio_lazyboot_home.test.cjs'
if (Test-Path -LiteralPath $target) { throw 'Refusing to replace an existing attribution slice' }
New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
try {
    [IO.File]::WriteAllText($target, $original.Replace($old, $replacement))
    $receipt = [ordered]@{original_sha256=(Get-FileHash 'tests_js/studio_lazyboot_home.test.cjs' -Algorithm SHA256).Hash;
        proposed_test_sha256=(Get-FileHash $target -Algorithm SHA256).Hash;
        proposal_sha256=(Get-FileHash 'evidence/mainrel/lazyboot-harness-proposal.patch' -Algorithm SHA256).Hash;
        scope='One temporary test copy, same product root; original claimed test path is never written'}
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'lazyboot-proposal-binding.json'), ($receipt | ConvertTo-Json))
    & 'C:\Program Files\nodejs\node.exe' '--test' '--test-concurrency=1' '--test-force-exit' 'tests_js/studio_home_session.test.cjs' 'tests_js/studio_existing_workshop.test.cjs' $target
    $status = $LASTEXITCODE
} finally {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
}
exit $status
