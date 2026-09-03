# brainwrap.ps1 - thin Windows wrapper around tools/brainwrap.py.
#
# Lets a Windows user / vendor launch ANY CLI with the brain wrapped around
# it (connect + inject + diligence) without typing the python invocation:
#
#   powershell -ExecutionPolicy Bypass -File tools/brainwrap.ps1 -- codex exec "fix the bug"
#   powershell -ExecutionPolicy Bypass -File tools/brainwrap.ps1 --context-file AGENTS.md -- gemini -p "..."
#   powershell -ExecutionPolicy Bypass -File tools/brainwrap.ps1 health
#
# Everything after this script's name is forwarded to brainwrap.py
# (including the `--` and the vendor command + args). The vendor CLI's exit
# code is preserved.
#
# Robustness note: when this script is invoked via the call operator
# (`& tools/brainwrap.ps1 -- foo`), PowerShell SILENTLY EATS the first bare
# `--` token before $args is populated, so brainwrap.py would never see the
# wrapper/vendor boundary. Invoked via `-File` the `--` survives. To work
# the same either way, we detect a missing `--` and re-insert it before the
# first token that is not a recognized brainwrap option — restoring the
# clean contract brainwrap.py expects.
#
# All real logic lives in brainwrap.py (pure stdlib). This wrapper only
# resolves a Python interpreter and forwards args.

# do NOT use $ErrorActionPreference=Stop here: a non-zero vendor exit code
# must pass through, not throw.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$brainwrapPy = Join-Path $scriptDir "brainwrap.py"

if (-not (Test-Path $brainwrapPy)) {
    Write-Error "brainwrap.ps1: cannot find brainwrap.py next to this script ($brainwrapPy)"
    exit 2
}

# Resolve a Python interpreter. Prefer an explicit override, then the
# console `python`, then the launcher `py`. (Use `python`, not `pythonw`,
# so the wrapper's [brainwrap] status lines on stderr are visible.)
$pythonExe = $env:BRAINWRAP_PYTHON
if (-not $pythonExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $pythonExe = $cmd.Source
    } else {
        $cmd = Get-Command py -ErrorAction SilentlyContinue
        if ($cmd) { $pythonExe = $cmd.Source }
    }
}
if (-not $pythonExe) {
    Write-Error "brainwrap.ps1: no Python interpreter found (set BRAINWRAP_PYTHON to override)"
    exit 2
}

# Rebuild the forwarded argument list, guaranteeing a `--` boundary.
$forward = @($args)

if ($forward -notcontains '--') {
    # PowerShell likely ate the `--` (call-operator invocation). Walk the
    # leading recognized wrapper options/subcommands; the first token that
    # isn't one starts the vendor command, so insert `--` there.
    $valueFlags  = @('--context-file', '--transcript', '--prompt', '--cwd')
    $switchFlags = @('--no-stdin-context', '--skip-daemon-start')
    $subcommands = @('launch', 'context', 'stop', 'health')

    $boundary = $forward.Count   # default: everything is wrapper args
    $i = 0
    while ($i -lt $forward.Count) {
        $tok = $forward[$i]
        if ($valueFlags -contains $tok) {
            $i += 2                      # flag + its value
        } elseif ($switchFlags -contains $tok) {
            $i += 1
        } elseif ($subcommands -contains $tok) {
            $i += 1
        } elseif ($tok -eq '--vendor') {
            $i += 2                      # context/stop subcommand option
        } else {
            $boundary = $i               # first non-wrapper token
            break
        }
    }

    if ($boundary -lt $forward.Count) {
        $head = if ($boundary -gt 0) { $forward[0..($boundary - 1)] } else { @() }
        $tail = $forward[$boundary..($forward.Count - 1)]
        $forward = @($head) + @('--') + @($tail)
    }
}

& $pythonExe $brainwrapPy @forward
exit $LASTEXITCODE
