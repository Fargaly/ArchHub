param([switch]$SkipBuild, [string]$StartAt, [switch]$RestoreOnly, [switch]$DesignSystemOnly)
$ErrorActionPreference = 'Stop'
$laneRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$gate = 'C:\Users\fargaly\00.ARCHUB\70.HANDOFFS\archhub-integrated-repair-20260909\tools\run-heavy.ps1'
$python = '"C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe"'
function Court([string]$label, [string]$line) {
    Write-Output "Starting COH3 court: $label"
    & $gate -Label "COH3-$label" -WorkingDirectory $laneRoot -CommandLine $line
    if ($LASTEXITCODE -ne 0) { throw "COH3 court failed: $label (exit $LASTEXITCODE)" }
    Write-Output "Completed COH3 court: $label"
    if ($label.EndsWith('.py')) {
        Select-String -LiteralPath (Join-Path $laneRoot ('evidence/coh3/' + $label.Replace('.py','.out'))) -Pattern '^=+ .*passed.*=+$' | Select-Object -Last 1 | ForEach-Object { Write-Output $_.Line }
    }
}
if (-not $SkipBuild -and -not $StartAt -and -not $RestoreOnly -and -not $DesignSystemOnly) {
    Court 'studio-build' 'npm run build:studio > evidence/coh3/studio-build.out 2>&1'
}
if (-not $StartAt -and -not $RestoreOnly -and -not $DesignSystemOnly) {
    Court 'studio-targeted' 'node --test --test-concurrency=1 --test-force-exit tests_js/studio_design_screens.test.cjs tests_js/studio_docs_coherence.test.cjs tests_js/studio_foundations_tokens.test.cjs tests_js/studio_rail_shortcuts.test.cjs > evidence/coh3/studio-targeted.out 2>&1'
    Court 'export' ($python + ' evidence/coh3/export_check.py > evidence/coh3/export.out 2>&1')
}
$files = @(
    'test_website_truth.py', 'test_website_docs_pages.py', 'test_website_definition_revision.py',
    'test_done_needs_docs.py', 'test_website_live_findings.py', 'test_website_package_docs.py',
    'test_website_public_routes.py', 'test_website_site_script.py', 'test_the_launcher_starts_no_brain.py',
    'test_node_native_application.py', 'test_node_native_website.py', 'test_application_persistence.py',
    'test_clean_server_visual_projection.py', 'test_goose_brain.py'
)
if ($RestoreOnly) {
    Court 'export' ($python + ' evidence/coh3/export_check.py > evidence/coh3/export.out 2>&1')
    $files = @('test_website_definition_revision.py', 'test_node_native_website.py', 'test_application_persistence.py')
}
if ($DesignSystemOnly) {
    Court 'export' ($python + ' evidence/coh3/export_check.py > evidence/coh3/export.out 2>&1')
    Court 'ds-port-assets' ($python + ' -m pytest -v -p no:cacheprovider --tb=short tests/test_ds_port_assets.py > evidence/coh3/ds-port-assets.out 2>&1')
    Court 'ds-port-ratchet' ($python + ' -m pytest -v -p no:cacheprovider --tb=short tests/test_ds_port_ratchet.py > evidence/coh3/ds-port-ratchet.out 2>&1')
    $files = @('test_node_native_website.py')
}
if ($StartAt) {
    $startIndex = [Array]::IndexOf($files, $StartAt)
    if ($startIndex -lt 0) { throw "Unknown starting court: $StartAt" }
    $files = $files[$startIndex..($files.Count - 1)]
}
foreach ($file in $files) {
    Court $file ($python + ' -m pytest -s -x -v -p no:cacheprovider --tb=short -o faulthandler_timeout=90 tests_replica/' + $file + ' > evidence/coh3/' + $file.Replace('.py','.out') + ' 2>&1')
}
if (-not $DesignSystemOnly) {
    Court 'zero-idle' ($python + ' -m pytest -v -p no:cacheprovider --tb=short tests/test_zero_idle_growth.py > evidence/coh3/zero-idle.out 2>&1')
}
Court 'ratchet' ($python + ' tools/ratchet.py compare . evidence/ratchet.json > evidence/coh3/ratchet.out 2>&1')
