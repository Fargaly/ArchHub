[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = "ArchHub Universal Runtime",
    [string]$AuthorityRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$Pythonw = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    [string]$StatePath = "$env:LOCALAPPDATA\ArchHub\authority-bridge-headless.json.gz",
    [string]$UniversalStatePath = "$env:LOCALAPPDATA\ArchHub\authority-bridge-headless.json.gz.universal.sqlite3",
    [string]$DescriptorPath = "$env:LOCALAPPDATA\ArchHub\active-universal-runtime.json",
    [switch]$AuditOnly
)

$ErrorActionPreference = "Stop"

function Quote-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "pythonw executable is unavailable: $Pythonw"
}
if (-not (Test-Path -LiteralPath $AuthorityRoot -PathType Container)) {
    throw "Node Language authority root is unavailable: $AuthorityRoot"
}

$arguments = @(
    "-m",
    "nodelang.runtime_supervisor",
    "--host", "127.0.0.1",
    "--port", "8495",
    "--state-path", (Quote-TaskArgument $StatePath),
    "--universal-state-path", (Quote-TaskArgument $UniversalStatePath),
    "--machine-descriptor-path", (Quote-TaskArgument $DescriptorPath)
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
    -Description "Source-owned ArchHub gateway supervisor; activation is separate and governed."

if ($AuditOnly) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $existingAction = if ($null -ne $existing) { @($existing.Actions)[0] } else { $null }
    $checks = [ordered]@{
        exists = $null -ne $existing
        executable = $null -ne $existingAction -and $existingAction.Execute -eq $Pythonw
        arguments = $null -ne $existingAction -and $existingAction.Arguments -eq $arguments
        working_directory = $null -ne $existingAction -and $existingAction.WorkingDirectory -eq $AuthorityRoot
        multiple_instances = $null -ne $existing -and $existing.Settings.MultipleInstances -eq "IgnoreNew"
        limited_privilege = $null -ne $existing -and $existing.Principal.RunLevel -eq "Limited"
    }
    $compliant = -not ($checks.Values -contains $false)
    [pscustomobject]@{
        task_name = $TaskName
        compliant = $compliant
        checks = $checks
    } | ConvertTo-Json -Depth 4
    if (-not $compliant) { exit 1 }
    return
}

if ($PSCmdlet.ShouldProcess($TaskName, "Register source-owned runtime supervisor task")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
}
