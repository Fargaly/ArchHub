$dll = 'C:\Users\fargaly\AppData\Local\ArchHub\Revit\2025\RevitMCPCore.dll'
$asm = [Reflection.Assembly]::LoadFile($dll)
Write-Output "Loaded: $($asm.FullName)"
$types = $asm.GetTypes()
Write-Output "Total types: $($types.Count)"
foreach ($t in $types) {
    $ifaces = $t.GetInterfaces() | ForEach-Object { $_.FullName }
    if ($ifaces -match 'ICoreEntryPoint') {
        Write-Output "Impl found: $($t.FullName)"
        foreach ($i in $ifaces) { Write-Output "  iface: $i" }
    }
}
$shim = 'C:\Users\fargaly\AppData\Local\ArchHub\Revit\2025\RevitMCP.dll'
$shimAsm = [Reflection.Assembly]::LoadFile($shim)
Write-Output "Shim: $($shimAsm.FullName)"
$shimShared = $shimAsm.GetTypes() | Where-Object { $_.FullName -like 'ArchHub.Shared.*' } | ForEach-Object FullName
Write-Output "Shim ArchHub.Shared types: $($shimShared -join ', ')"
$coreShared = $asm.GetTypes() | Where-Object { $_.FullName -like 'ArchHub.Shared.*' } | ForEach-Object FullName
Write-Output "Core ArchHub.Shared types: $($coreShared -join ', ')"
