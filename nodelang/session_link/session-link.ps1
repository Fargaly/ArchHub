$bridgeArgs = @($args)
# PowerShell pipeline input (a here-string piped to this script) is message data
# for --stdin only. It is forwarded to Node as UTF-8 bytes and never evaluated.
# Without --stdin, pipeline input and stdin are never read, so stray or open
# stdin cannot block or change any other command. The pipeline enumerator is
# looked up at run time only: a literal automatic-input reference makes
# powershell -File drain redirected stdin before the script runs. Under -File
# stdin stays unread here and Node inherits it byte-for-byte.
$bridgePiped = @()
if ($args -contains '--stdin') {
    $bridgePipeline = Get-Variable -Name input -ValueOnly
    $bridgePiped = @(foreach ($bridgeItem in $bridgePipeline) { $bridgeItem })
}
$bridgePriorState = $env:SESSION_LINK_STATE_DIR
$bridgeState = $bridgePriorState
$bridgeStateIndex = [Array]::IndexOf($bridgeArgs, '--state-dir')
if ($bridgeStateIndex -ge 0) {
    if ($bridgeStateIndex + 1 -ge $bridgeArgs.Count) { throw 'Missing state directory' }
    $bridgeState = $bridgeArgs[$bridgeStateIndex + 1]
    $bridgeArgs = @(for ($bridgeIndex=0; $bridgeIndex -lt $args.Count; $bridgeIndex++) {
        if ($bridgeIndex -ne $bridgeStateIndex -and $bridgeIndex -ne ($bridgeStateIndex+1)) { $args[$bridgeIndex] }
    })
}
# The installed application owns Session Link state: the same folder the app
# composes (ARCHHUB_TEST_STATE_DIR or %LOCALAPPDATA%\ArchHub-Test, then session-link).
if (-not $bridgeState) {
    $bridgeStateRoot = $env:ARCHHUB_TEST_STATE_DIR
    if (-not $bridgeStateRoot) {
        if (-not $env:LOCALAPPDATA) { throw 'Application state directory unavailable' }
        $bridgeStateRoot = Join-Path $env:LOCALAPPDATA 'ArchHub-Test'
    }
    $bridgeState = Join-Path $bridgeStateRoot 'session-link'
}
$bridgeNode = $env:SESSION_LINK_NODE
if (-not $bridgeNode) { $bridgeNode = $env:CODEX_MCP_NODE_PATH }
if (-not $bridgeNode) { $bridgeNode = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'runtime\node.exe' }
if (-not (Test-Path -LiteralPath $bridgeNode)) { throw 'Declared Session Link Node runtime unavailable' }
$bridgeEntry = if ($bridgeArgs.Count -gt 0 -and $bridgeArgs[0] -in @('ask','answer','interrupt')) { 'ask.mjs' } else { 'bridge.mjs' }
# The state folder reaches the child only; the caller's shell keeps its own value.
$env:SESSION_LINK_STATE_DIR = $bridgeState
try {
    if ($bridgePiped.Count -gt 0) {
        $bridgeText = ($bridgePiped | ForEach-Object { [string]$_ }) -join "`n"
        $bridgeQuote = { param([string]$v) if ($v -and $v -notmatch '[\s"]') { $v } else { '"' + (($v -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' } }
        $bridgeStart = New-Object System.Diagnostics.ProcessStartInfo $bridgeNode
        $bridgeStart.Arguments = (@((Join-Path $PSScriptRoot $bridgeEntry)) + $bridgeArgs | ForEach-Object { & $bridgeQuote ([string]$_) }) -join ' '
        $bridgeStart.UseShellExecute = $false
        $bridgeStart.RedirectStandardInput = $true
        $bridgeStart.EnvironmentVariables['SESSION_LINK_STATE_DIR'] = $bridgeState
        $bridgeProcess = [System.Diagnostics.Process]::Start($bridgeStart)
        $bridgeBytes = (New-Object System.Text.UTF8Encoding $false).GetBytes($bridgeText)
        $bridgeProcess.StandardInput.BaseStream.Write($bridgeBytes, 0, $bridgeBytes.Length)
        $bridgeProcess.StandardInput.Close()
        $bridgeProcess.WaitForExit()
        $bridgeExit = $bridgeProcess.ExitCode
    } else {
        & $bridgeNode (Join-Path $PSScriptRoot $bridgeEntry) @bridgeArgs
        $bridgeExit = $LASTEXITCODE
    }
} finally {
    $env:SESSION_LINK_STATE_DIR = $bridgePriorState
}
exit $bridgeExit
