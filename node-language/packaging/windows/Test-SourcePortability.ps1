[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $SourceRoot).Path
$extensions = @(".py", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")
$patterns = @(
    '(?i)[A-Z]:\\Users\\[^\\]+\\',
    '(?i)[A-Z]:\\[^\r\n"'']*\\(?:20\.CLIENTS|30\.KNOWLEDGE|60\.PERSONAL)\\'
)
$violations = @()

Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $extensions -contains $_.Extension -and
    $_.FullName -notmatch '[\\/](?:__pycache__|build|dist)[\\/]'
} | ForEach-Object {
    $path = $_.FullName
    $content = Get-Content -LiteralPath $path -Raw
    foreach ($pattern in $patterns) {
        if ($content -match $pattern) {
            $violations += $path
            break
        }
    }
}

if ($violations.Count -gt 0) {
    [Console]::Error.WriteLine("Non-portable or private absolute paths found:`n  " +
        (($violations | Sort-Object -Unique) -join "`n  "))
    exit 3
}

Write-Output "Source portability gate: PASS ($root)"
return
