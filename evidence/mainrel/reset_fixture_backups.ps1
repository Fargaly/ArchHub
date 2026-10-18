$ErrorActionPreference = 'Stop'
$lane = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$profileRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'court-state/big-profile'))
if (-not $profileRoot.StartsWith($lane + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Fixture cleanup leaves the named lane'
}
$targets = @(Get-ChildItem -LiteralPath $profileRoot -Directory -Recurse -Filter '*-closed')
$records = foreach ($target in $targets) {
    $absolute = [IO.Path]::GetFullPath($target.FullName)
    if (-not $absolute.StartsWith($profileRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Fixture cleanup target leaves its owned profile'
    }
    $children = @(Get-ChildItem -LiteralPath $absolute -Recurse -Force)
    if (($target.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'Fixture cleanup refuses links'
    }
    $receipt = Get-Content -LiteralPath (Join-Path $absolute 'closed-files.json') -Raw | ConvertFrom-Json
    if ($receipt.build -cne 'mainrel-big' -or $receipt.producer -cne 'archhub-product-installer/v1') {
        throw 'Fixture cleanup refuses an unknown backup owner'
    }
    [ordered]@{path=$absolute;parent=$target.Parent.FullName;bytes=($children | Where-Object { -not $_.PSIsContainer } | Measure-Object -Property Length -Sum).Sum}
}
$evidence = [ordered]@{kind='original multi-directory layout measured before fixture-only cleanup';
    directories=$records;backup_roots=@($records.parent | Sort-Object -Unique).Count}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'old-layout-red.json'), ($evidence | ConvertTo-Json -Depth 8))
foreach ($record in $records) { Remove-Item -LiteralPath $record.path -Recurse -Force }
Write-Output ('FIXTURE BACKUPS REMOVED: ' + $records.Count + '; source journals and CURRENT kept')
