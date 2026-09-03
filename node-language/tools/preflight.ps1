# preflight.ps1 — PRE-FLIGHT-CHECK MANDATE (founder 2026-05-25)
#
# 7-question Y/N gate. Run BEFORE the words "shipped" / "done" /
# "delivered" / "complete" appear in any report. ANY 'No' → not shipped.
#
# Usage:
#   pwsh tools/preflight.ps1 -Feature "GraphHealthBadge" -Selector "[data-testid='graph-health-badge']"
#   pwsh tools/preflight.ps1 -Feature "4 use case tiles" -Selector ".tile" -EntryActionPath "Home"

param(
    [Parameter(Mandatory=$true)][string]$Feature,
    [Parameter(Mandatory=$true)][string]$Selector,
    [string]$EntryActionPath = "from default view, ≤3 clicks",
    [int]$CdpPort = 9223
)

$ErrorActionPreference = "Continue"
$results = [ordered]@{
    Feature   = $Feature
    Timestamp = (Get-Date).ToString("o")
    Checks    = [ordered]@{}
}

function Add-Result($name, $pass, $detail) {
    $results.Checks[$name] = @{
        Pass   = $pass
        Detail = $detail
    }
}

# ── 1. Built? ────────────────────────────────────────────────────────
$status = git status --porcelain 2>$null
$lastCommit = git log -1 --pretty=format:"%h %s" 2>$null
$builtPass = [string]::IsNullOrWhiteSpace($status)
Add-Result "1. Built (clean tree + committed)" $builtPass "last: $lastCommit | dirty: $(if($status){'YES'}else{'NO'})"

# ── 2. Restarted? ────────────────────────────────────────────────────
$lastCommitEpoch = git log -1 --pretty=format:"%ct" 2>$null
$archhubProc = Get-Process pythonw -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
$restartPass = $false
$restartDetail = "no pythonw process"
if ($archhubProc -and $lastCommitEpoch) {
    $procEpoch = [int][double]::Parse((Get-Date $archhubProc.StartTime -UFormat %s))
    $restartPass = $procEpoch -ge [int]$lastCommitEpoch
    $restartDetail = "pid=$($archhubProc.Id) started=$($archhubProc.StartTime) commit_ts=$(Get-Date -UnixTimeSeconds ([int]$lastCommitEpoch))"
}
Add-Result "2. Restarted (PID newer than commit)" $restartPass $restartDetail

# ── 3. Reachable? ────────────────────────────────────────────────────
$cdp = $null
try {
    $cdp = Invoke-WebRequest "http://localhost:$CdpPort/json" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
} catch {}
$reachPass = $cdp -and ($cdp.StatusCode -eq 200)
$reachDetail = if($reachPass){ "CDP $CdpPort responding · $($cdp.Content.Length) bytes" } else { "CDP $CdpPort not reachable" }
Add-Result "3. Reachable (CDP up)" $reachPass $reachDetail

# ── 4-7. Visible / Clickable / Persistent / Discoverable ─────────────
# These need a CDP WebSocket round-trip. The script signals them as
# CHECK-IN-CDP — caller must run the JS probe + paste result here.
$cdpJs = @"
(() => {
  const el = document.querySelector('$Selector');
  return JSON.stringify({
    found: !!el,
    visible: el ? (el.offsetParent !== null) : false,
    bbox: el ? el.getBoundingClientRect() : null,
    text: el ? el.textContent.trim().slice(0,120) : null,
  });
})();
"@
Add-Result "4. Visible (DOM query)" "CDP" "Run JS:`n$cdpJs"
Add-Result "5. Clickable (interaction)" "CDP" "Dispatch click on '$Selector' + observe DOM mutation / network call / log line"
Add-Result "6. Persistent (survives restart)" "CDP" "Trigger interaction · restart ArchHub · verify state preserved"
Add-Result "7. Discoverable (≤3 actions from default)" "MANUAL" "Path: $EntryActionPath"

# ── output ───────────────────────────────────────────────────────────
"PRE-FLIGHT · $Feature · $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
"=" * 72
foreach ($k in $results.Checks.Keys) {
    $r = $results.Checks[$k]
    $tag = switch ($r.Pass) {
        $true   { "[PASS]" }
        $false  { "[FAIL]" }
        "CDP"   { "[CDP-CHECK]" }
        "MANUAL"{ "[MANUAL]" }
    }
    "$tag $k"
    "        $($r.Detail)"
    ""
}
$autoFails = ($results.Checks.GetEnumerator() | Where-Object { $_.Value.Pass -eq $false }).Count
"=" * 72
"Auto-failing checks: $autoFails / 3 (1-3 only — 4-7 need CDP round-trip)"
if ($autoFails -gt 0) {
    Write-Host "PREFLIGHT FAILED — 'shipped' word BANNED in this report." -ForegroundColor Red
    exit 1
}
"Auto-checks 1-3 PASS. Now run CDP checks 4-7 + paste output." -as [string]
exit 0
