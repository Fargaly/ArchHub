# Installs the ArchHub Rhino bridge watchdog WITHOUT admin:
#  1) HKCU Run key  -> auto-starts the infinite-watch watchdog at every logon
#  2) Start-Process -> launches it right now, detached + hidden, survives this session
$f = Join-Path $PSScriptRoot '_ensure_bridge.ps1'
$psArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $f + '" -Watch -TimeoutSec 0'

# 1) logon persistence (current-user hive, no elevation needed)
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty -Path $run -Name 'ArchHubRhinoBridge' -Value ('powershell.exe ' + $psArgs)
Write-Output ('Run key  : ' + (Get-ItemProperty -Path $run -Name 'ArchHubRhinoBridge').'ArchHubRhinoBridge')

# 2) start now (detached) if not already running
$existing = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match '_ensure_bridge' }
if ($existing) {
  Write-Output ('watchdog : already running PID ' + ($existing.ProcessId -join ','))
} else {
  Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$f,'-Watch','-TimeoutSec','0')
  Start-Sleep -Seconds 2
  $now = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match '_ensure_bridge' }
  Write-Output ('watchdog : ' + $(if ($now) { 'started PID ' + ($now.ProcessId -join ',') } else { 'NOT seen' }))
}

Write-Output ('9879     : ' + $(if (Get-NetTCPConnection -State Listen -LocalPort 9879 -EA SilentlyContinue) { 'UP' } else { 'down (idle until a file is open)' }))

# tidy any partial scheduled-task remnant from the earlier admin-blocked attempt
try { Unregister-ScheduledTask -TaskName 'ArchHubRhinoBridge' -Confirm:$false -ErrorAction Stop; Write-Output 'cleanup  : removed stray task' } catch { Write-Output 'cleanup  : no stray task' }
