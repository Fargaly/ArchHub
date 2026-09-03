# Chocolatey uninstall script — defers to the Inno Setup uninstaller
# Inno registers under [HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{appid}]
# (per-user lowest-privilege install, matches setup.iss).

$ErrorActionPreference = 'Stop'

$packageName  = 'archhub'
$softwareName = 'ArchHub*'

$uninstalled = $false
[array]$key = Get-UninstallRegistryKey -SoftwareName $softwareName

if ($key.Count -eq 1) {
    $key | ForEach-Object {
        $packageArgs = @{
            packageName    = $packageName
            fileType       = 'exe'
            silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
            validExitCodes = @(0)
            file           = "$($_.UninstallString)"
        }
        Uninstall-ChocolateyPackage @packageArgs
    }
} elseif ($key.Count -eq 0) {
    Write-Warning "$packageName not installed — nothing to do."
} else {
    Write-Warning "Multiple ArchHub registrations found. Uninstall manually."
    $key | ForEach-Object { Write-Warning "  $($_.DisplayName) :: $($_.UninstallString)" }
}
