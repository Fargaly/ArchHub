[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = "ArchHub Clean Coordination",
    [string]$AuthorityRoot,
    [string]$Pythonw = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    [int]$Port = 8474,
    [switch]$AuditOnly
)

# Installs the clean coordination service as a logon task so it returns after
# a crash or a reboot instead of surviving only as an orphaned process.
#
# This is deliberately NOT install_runtime_task.ps1. That one registers
# nodelang.runtime_supervisor against the legacy headless state and the
# active-universal-runtime.json descriptor. This service owns the clean
# generation under the runtime root, advertises liveness through its owner
# lock rather than a descriptor, and serves only signed coordination.

$ErrorActionPreference = "Stop"

# $PSScriptRoot is empty when this file is invoked through a relative -File
# path, so the root is resolved from the invocation itself when not supplied.
if (-not $AuthorityRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) {
        $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $AuthorityRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}

if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "pythonw executable is unavailable: $Pythonw"
}
if (-not (Test-Path -LiteralPath $AuthorityRoot -PathType Container)) {
    throw "Node Language authority root is unavailable: $AuthorityRoot"
}
if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "clean coordination port is outside its bound: $Port"
}

$arguments = @(
    "-m", "nodelang.clean_coordination_service",
    "--host", "127.0.0.1",
    "--port", $Port
) -join " "

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $Pythonw `
    -Argument $arguments `
    -WorkingDirectory $AuthorityRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
# IgnoreNew keeps the single-owner rule: the graph takes one owner, and a
# second instance would be refused by the owner lock anyway.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -Hidden
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Clean ArchHub coordination owner on 127.0.0.1:$Port."

if ($AuditOnly) {
    [pscustomobject]@{
        TaskName  = $TaskName
        Execute   = $Pythonw
        Arguments = $arguments
        Registered = [bool](Get-ScheduledTask -TaskName $TaskName -EA SilentlyContinue)
    } | Format-List
    return
}

if ($PSCmdlet.ShouldProcess($TaskName, "Register clean coordination task")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Get-ScheduledTask -TaskName $TaskName |
        Select-Object TaskName, State |
        Format-List
}
