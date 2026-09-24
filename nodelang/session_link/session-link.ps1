$bridgeArgs = @($args)
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
$bridgeEntry = if ($bridgeArgs.Count -gt 0 -and $bridgeArgs[0] -in @('ask','answer')) { 'ask.mjs' } else { 'bridge.mjs' }
# The state folder reaches the child only; the caller's shell keeps its own value.
$env:SESSION_LINK_STATE_DIR = $bridgeState
try {
    & $bridgeNode (Join-Path $PSScriptRoot $bridgeEntry) @bridgeArgs
    $bridgeExit = $LASTEXITCODE
} finally {
    $env:SESSION_LINK_STATE_DIR = $bridgePriorState
}
exit $bridgeExit
