# Personal Brain — one-shot device bootstrap.
#
# Run ONCE per device. Wires brain into Claude Code / Cursor / Codex /
# Gemini CLI / Cline / Continue. Registers daemon for autostart at login.
# Idempotent — safe to re-run.
#
# Usage:
#   irm https://your-repo-host/bootstrap.ps1 | iex
# OR locally:
#   pwsh -ExecutionPolicy Bypass -File bootstrap.ps1

$ErrorActionPreference = "Stop"

Write-Host "──────────────────────────────────────────────"
Write-Host " Personal Brain — bootstrap"
Write-Host "──────────────────────────────────────────────"

# 1. Resolve repo location (script lives in personal-brain-mcp/)
$RepoRoot = Split-Path -Parent (Resolve-Path $PSScriptRoot)
$BrainPkg = Join-Path $RepoRoot "personal-brain-mcp"
if (-not (Test-Path $BrainPkg)) {
    Write-Error "personal-brain-mcp not found at $BrainPkg"
    exit 1
}

# 2. Ensure deps
Write-Host "[1/4] Installing Python deps..."
python -m pip install --user --upgrade fastmcp pydantic loro specklepy fastapi anthropic 2>&1 | Select-Object -Last 3

# 3. Install brain package itself (editable)
Write-Host "[2/4] Installing personal-brain-mcp (editable)..."
python -m pip install -e $BrainPkg 2>&1 | Select-Object -Last 3

# 4. Wire all detected MCP clients
Write-Host "[3/4] Wiring MCP clients..."
$env:PYTHONPATH = (Join-Path $BrainPkg "src")
python -m personal_brain.installer

# 5. Register daemon autostart (Startup folder fallback — zero admin)
Write-Host "[4/4] Registering daemon autostart..."
python -m personal_brain.service install --port 8473

# 6. Verify daemon is alive (or start it now)
Write-Host ""
Write-Host "Probing daemon..."
$probe = $null
try {
    $body = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"brain.health","arguments":{}}}'
    $probe = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8473/mcp `
        -ContentType "application/json" `
        -Headers @{"Accept" = "application/json, text/event-stream"} `
        -Body $body -TimeoutSec 3 -ErrorAction Stop
} catch {}

if ($probe) {
    Write-Host "  daemon LIVE on :8473" -ForegroundColor Green
} else {
    Write-Host "  daemon not running — starting now (background)..."
    Start-Process -WindowStyle Hidden python -ArgumentList "-m","personal_brain.server","--http","8473"
    Start-Sleep -Seconds 4
    Write-Host "  daemon spawned (will autostart on next login via Startup folder)" -ForegroundColor Green
}

Write-Host ""
Write-Host "──────────────────────────────────────────────"
Write-Host " Done. New Claude Code / Cursor / Codex / Gemini"
Write-Host " sessions will auto-connect to the brain."
Write-Host "──────────────────────────────────────────────"
Write-Host ""
Write-Host "Verify in a fresh Claude Code session by typing:"
Write-Host "  /mcp"
Write-Host "  — brain should appear in the MCP server list"
Write-Host ""
Write-Host "Sync brain across devices (optional):"
Write-Host "  Put %APPDATA%\ArchHub\brain\ inside iCloud Drive / OneDrive /"
Write-Host "  Dropbox / Syncthing — Loro CRDT merges automatically on"
Write-Host "  concurrent writes. Or tunnel :8473 over Tailscale and have"
Write-Host "  other devices connect to the primary's daemon."
