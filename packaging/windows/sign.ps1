[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$CertificateSha1 = $env:ARCHHUB_SIGN_CERT_SHA1,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Path)) { throw "Signing target not found: $Path" }
if ([string]::IsNullOrWhiteSpace($CertificateSha1)) {
    throw "ARCHHUB_SIGN_CERT_SHA1 is required; use a certificate in the Windows certificate store"
}
$signTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signTool) { throw "signtool.exe is required from the Windows SDK" }

& $signTool sign /sha1 $CertificateSha1 /fd SHA256 /tr $TimestampUrl /td SHA256 /v $Path
if ($LASTEXITCODE -ne 0) { throw "signtool failed with exit code $LASTEXITCODE" }
& $signTool verify /pa /v $Path
if ($LASTEXITCODE -ne 0) { throw "signature verification failed with exit code $LASTEXITCODE" }
