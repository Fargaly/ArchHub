# loop_audit.ps1 — POST-LOOP-AUDIT MANDATE (founder 2026-05-25)
#
# Runs after every /loop iteration. Output IS the iteration summary +
# blocks the "done" report on any failure.
#
# Usage:
#   pwsh tools/loop_audit.ps1 -StartSha <sha>
#   (StartSha = commit SHA at start of iteration; defaults to HEAD~1)

param(
    [string]$StartSha = "HEAD~1",
    [int]$CdpPort = 9223
)

$ErrorActionPreference = "Continue"
$fail = $false
function Section($t) { ""; "═" * 72; "  $t"; "═" * 72 }

Section "1. Commits in iteration"
$commits = git log --oneline "$StartSha..HEAD" 2>$null
if (-not $commits) {
    "  (no commits in range $StartSha..HEAD)"
    $fail = $true
} else {
    $commits | ForEach-Object { "  $_" }
}

Section "2. Files touched"
$files = git diff --name-only "$StartSha..HEAD" 2>$null
if ($files) {
    $files | ForEach-Object { "  $_" }
} else {
    "  (no files touched)"
}

Section "3. TODO / FOUNDER / FIXME grep on touched files"
$bannedPat = "TODO\(founder\)|FOUNDER:|FIXME\(later\)|verify in app$|for testing"
$hits = @()
foreach ($f in ($files | Where-Object { Test-Path $_ })) {
    $matches = Select-String -Path $f -Pattern $bannedPat -ErrorAction SilentlyContinue
    if ($matches) {
        $matches | ForEach-Object {
            $hits += "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
        }
    }
}
if ($hits.Count -gt 0) {
    "  FAIL — open-thread markers found:"
    $hits | ForEach-Object { "    $_" }
    $fail = $true
} else {
    "  PASS — no open-thread markers."
}

Section "4. ArchHub PID + restart-after-commit check"
$archhub = Get-Process pythonw -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
$headCommitEpoch = git log -1 --pretty=format:"%ct" 2>$null
if ($archhub -and $headCommitEpoch) {
    $procEpoch = [int][double]::Parse((Get-Date $archhub.StartTime -UFormat %s))
    if ($procEpoch -ge [int]$headCommitEpoch) {
        "  PASS — pid=$($archhub.Id) start=$($archhub.StartTime) >= commit_ts=$(Get-Date -UnixTimeSeconds ([int]$headCommitEpoch))"
    } else {
        "  FAIL — process started BEFORE HEAD commit. Restart required."
        $fail = $true
    }
} else {
    "  FAIL — no pythonw process running OR no commit data."
    $fail = $true
}

Section "5. CDP bundle hash matches disk"
$cdp = $null
try { $cdp = Invoke-WebRequest "http://localhost:$CdpPort/json" -UseBasicParsing -TimeoutSec 3 } catch {}
if ($cdp) {
    "  PASS — CDP $CdpPort responding."
    # Bundle hash compare deferred — needs CDP WS round-trip. Marked CHECK-IN-CDP.
    "  CHECK-IN-CDP — fetch live bundle hash via Runtime.evaluate('window.__jsxBundleHash')"
    "                 + compare to (sha256 of studio-lm.jsx)"
} else {
    "  FAIL — CDP not reachable."
    $fail = $true
}

Section "6. ROADMAP items flipped + proof screenshots"
$roadmap = "docs/ROADMAP.md"
if (Test-Path $roadmap) {
    $diff = git diff "$StartSha..HEAD" -- $roadmap 2>$null
    $flipped = ($diff | Select-String "^\+- \[x\]").Matches.Count
    if ($flipped -gt 0) {
        "  $flipped item(s) flipped to [x] this iteration."
        $proofDate = Get-Date -Format "yyyy-MM-dd"
        $proofDir = "proofs/$proofDate"
        if (-not (Test-Path $proofDir)) {
            "  WARN — proofs/$proofDate/ does not exist. Mandate requires CDP screenshot per flipped item."
            $fail = $true
        } else {
            $proofCount = (Get-ChildItem $proofDir -File -Filter "proof_*.png" -ErrorAction SilentlyContinue).Count
            if ($proofCount -ge $flipped) {
                "  PASS — $proofCount proof screenshot(s) found in $proofDir."
            } else {
                "  FAIL — need $flipped proof screenshot(s), found $proofCount."
                $fail = $true
            }
        }
    } else {
        "  (no roadmap items flipped this iteration)"
    }
} else {
    "  (no $roadmap)"
}

Section "7. AgDR linkage on architecture commits"
foreach ($c in $commits) {
    $sha = ($c -split " ")[0]
    $body = git log -1 --pretty=format:"%B" $sha 2>$null
    if ($body -match "feat\(|refactor\(" -and $body -notmatch "AgDR-\d{4}") {
        "  WARN — $sha is feat/refactor without AgDR reference."
    }
}

Section "VERDICT"
if ($fail) {
    Write-Host "  AUDIT FAILED — 'done' report BLOCKED until gaps closed." -ForegroundColor Red
    exit 1
} else {
    Write-Host "  AUDIT PASSED — iteration may be reported as done." -ForegroundColor Green
    exit 0
}
