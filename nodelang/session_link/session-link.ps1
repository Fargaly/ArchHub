$bridgeArgs = @($args)
$bridgeStateIndex = [Array]::IndexOf($bridgeArgs, '--state-dir')
if ($bridgeStateIndex -ge 0) {
    if ($bridgeStateIndex + 1 -ge $bridgeArgs.Count) { throw 'Missing state directory' }
    $env:SESSION_LINK_STATE_DIR = $bridgeArgs[$bridgeStateIndex + 1]
    $bridgeArgs = @(for ($bridgeIndex=0; $bridgeIndex -lt $args.Count; $bridgeIndex++) {
        if ($bridgeIndex -ne $bridgeStateIndex -and $bridgeIndex -ne ($bridgeStateIndex+1)) { $args[$bridgeIndex] }
    })
}
$bridgeNode = $env:SESSION_LINK_NODE
if (-not $bridgeNode) { $bridgeNode = $env:CODEX_MCP_NODE_PATH }
if (-not $bridgeNode) { $bridgeNode = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'runtime\node.exe' }
if (-not (Test-Path -LiteralPath $bridgeNode)) { throw 'Declared Session Link Node runtime unavailable' }
$bridgeEntry = if ($bridgeArgs.Count -gt 0 -and $bridgeArgs[0] -in @('ask','answer')) { 'ask.mjs' } else { 'bridge.mjs' }
& $bridgeNode (Join-Path $PSScriptRoot $bridgeEntry) @bridgeArgs
exit $LASTEXITCODE
