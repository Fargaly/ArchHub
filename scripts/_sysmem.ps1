$os = Get-CimInstance Win32_OperatingSystem
$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$totGB  = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$pct    = [math]::Round(100 * $freeGB / $totGB, 1)
Write-Output "RAM free: $freeGB GB / $totGB GB ($pct% free)"
Write-Output "Processes: $((Get-Process).Count)"
$rev  = @(Get-Process Revit  -ErrorAction SilentlyContinue).Count
$acad = @(Get-Process acad   -ErrorAction SilentlyContinue).Count
$pyw  = @(Get-Process pythonw -ErrorAction SilentlyContinue).Count
Write-Output "Revit: $rev  AutoCAD: $acad  pythonw: $pyw"
