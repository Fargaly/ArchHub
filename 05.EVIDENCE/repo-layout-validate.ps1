$ErrorActionPreference = 'Stop'
foreach ($scriptName in @('repo-layout-baseline.ps1', 'repo-layout-measure-source.ps1')) {
    $tokens = $null; $parseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $scriptName), [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    Write-Output "PASS PowerShell parse: $scriptName"
}
python (Join-Path $PSScriptRoot 'repo-layout-validate.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
