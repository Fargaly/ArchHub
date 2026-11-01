# Proves deploy.ps1 stops when flyctl fails, and does not run interactive login.
$ErrorActionPreference = "Stop"
$deploy = Join-Path $PSScriptRoot "deploy.ps1"
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("grok-deployfix-" + [guid]::NewGuid().ToString("n"))
$profileDir = Join-Path $root "profile"
$homeDir = Join-Path $root "home"
$localDir = Join-Path $root "local"
$roamDir = Join-Path $root "roam"
$tempDir = Join-Path $root "temp"
$binDir = Join-Path $root "bin"
$calls = Join-Path $root "calls.log"
$transcript = Join-Path $root "transcript.txt"
$stdoutFile = Join-Path $root "stdout.txt"
$stderrFile = Join-Path $root "stderr.txt"
$emptyIn = Join-Path $root "empty-in.txt"
$pwsh = (Get-Command pwsh).Source
New-Item -ItemType Directory -Path @($root, $profileDir, $homeDir, $localDir, $roamDir, $tempDir, $binDir) -Force | Out-Null
New-Item -ItemType File -Path $emptyIn -Force | Out-Null
$batLines = @(
    "@echo off",
    "echo %*>> `"$calls`"",
    "echo Error: no access token available. Please login with 'flyctl auth login' 1>&2",
    "exit 1"
)
Set-Content -LiteralPath (Join-Path $binDir "flyctl.cmd") -Value $batLines -Encoding ascii
$tcp = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback, 0)
$tcp.Start()
$port = ([System.Net.IPEndPoint]$tcp.LocalEndpoint).Port
$rs = [runspacefactory]::CreateRunspace()
$rs.Open()
$worker = [powershell]::Create()
$worker.Runspace = $rs
[void]$worker.AddScript({
    param($listener)
    try {
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        $buf = New-Object byte[] 2048
        $got = 0
        try { $got = $stream.Read($buf, 0, $buf.Length) } catch { $got = 0 }
        $body = '{"ok":true}'
        $head = "HTTP/1.1 200 OK`r`nContent-Type: application/json`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
        $payload = [System.Text.Encoding]::ASCII.GetBytes($head + $body)
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush()
        $client.Close()
    } catch {
        $got = 0
    }
}).AddArgument($tcp)
$pending = $worker.BeginInvoke()
try {
$health = "http://127.0.0.1:$port/healthz"
$env:USERPROFILE = $profileDir
$env:HOME = $homeDir
$env:LOCALAPPDATA = $localDir
$env:APPDATA = $roamDir
$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:PATH = "$binDir;" + $env:PATH
$proc = Start-Process -FilePath $pwsh -ArgumentList @("-NoProfile", "-File", $deploy, "-NonInteractive", "-SkipSecrets", "-PublicHealthUrl", $health) -WorkingDirectory $root -PassThru -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -RedirectStandardInput $emptyIn
$finished = $proc.WaitForExit(20000)
if (-not $finished) {
    try { $proc.Kill() } catch { $finished = $false }
    Write-Host "FAIL deploy.ps1 did not stop within 20s"
    exit 1
}
$proc.Refresh()
$text = ""
foreach ($path in @($transcript, $stdoutFile, $stderrFile)) {
    if (Test-Path -LiteralPath $path) { $text += [System.IO.File]::ReadAllText($path) }
}
$logged = ""
if (Test-Path -LiteralPath $calls) { $logged = [System.IO.File]::ReadAllText($calls).Trim() }
$failed = @()
if ($proc.ExitCode -eq 0) { $failed += "exit code was 0" }
if ($text -notmatch "REFUSED: sign-in failed:") { $failed += "missing REFUSED sign-in line" }
if ($text -notmatch "no access token available") { $failed += "flyctl error text was dropped" }
if ($text -notmatch "(?m)^flyctl auth login\s*$") { $failed += "missing the one owner command" }
if ($text -match "Running flyctl auth login") { $failed += "ran interactive login" }
if ($text -match "Done\. Cloud backend deployed") { $failed += "claimed the backend was deployed" }
if ($text -match "OK deployed") { $failed += "printed OK deployed" }
if ($logged -notmatch "auth whoami") { $failed += "flyctl auth whoami was not invoked: [$logged]" }
if ($logged -match "auth login") { $failed += "flyctl auth login was invoked: [$logged]" }
if ($failed.Count -gt 0) {
    Write-Host "FAIL"
    $failed | ForEach-Object { Write-Host " - $_" }
    Write-Host "--- output ---"
    Write-Host $text
    Write-Host "--- calls ---"
    Write-Host $logged
    Write-Host "--- exit $($proc.ExitCode) ---"
    exit 1
}
Write-Host "PASS deploy stops when flyctl fails (exit $($proc.ExitCode))"
Write-Host $text
exit 0
} finally {
    if ($tcp) { $tcp.Stop() }
    if ($worker -and $pending) {
        try { $worker.EndInvoke($pending) } catch { $got = 0 }
        $worker.Dispose()
    }
    if ($rs) { $rs.Close() }
}
