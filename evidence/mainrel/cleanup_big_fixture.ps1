$ErrorActionPreference = 'Stop'
$lane = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'court-state/big-profile'))
if (-not $target.StartsWith($lane + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cleanup target is outside this lane'
}
$rootItem = Get-Item -LiteralPath $target -Force
$items = @(Get-ChildItem -LiteralPath $target -Recurse -Force)
if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    @($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw 'Cleanup refuses linked fixture content'
}
$backups = @($items | Where-Object { $_.Name -eq 'closed-files.json' })
$records = foreach ($backup in $backups) {
    $receipt = Get-Content -LiteralPath $backup.FullName -Raw | ConvertFrom-Json
    if ($receipt.producer -cne 'archhub-product-installer/v1' -or $receipt.build -cne 'mainrel-big') {
        throw 'Unexpected backup owner in the disposable fixture'
    }
    [ordered]@{path=$backup.Directory.FullName;container=$backup.Directory.Parent.Parent.FullName;receipt=$receipt}
}
$evidence = [ordered]@{fixture_root=$target;backup_containers=@($records.container | Sort-Object -Unique);
    backups=$records;files=@($items | Where-Object { -not $_.PSIsContainer }).Count;
    bytes=($items | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum;
    free_before_bytes=(Get-PSDrive C).Free;purpose='Recorded byte-scale fixture removed after its completed court; no live profile used'}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'backup-layout-and-cleanup.json'), ($evidence | ConvertTo-Json -Depth 15))
Remove-Item -LiteralPath $target -Recurse -Force
Write-Output ('OWNED FIXTURE REMOVED; FREE_BYTES=' + (Get-PSDrive C).Free)
