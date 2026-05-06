# Chocolatey install script for ArchHub.
# Downloads the Inno Setup installer from GitHub Releases and runs it
# silently with the same flags the in-app updater uses, so the
# experience is identical regardless of how the user got here.

$ErrorActionPreference = 'Stop'

$packageName = 'archhub'
$version     = '0.16.0'
$url         = "https://github.com/Fargaly/ArchHub/releases/download/v$version/ArchHub-Setup-$version.exe"

# SHA256 is filled in by CI on each release. Until signing is wired,
# the manifest is republished after the .exe is built so the hash matches.
$checksum    = '0000000000000000000000000000000000000000000000000000000000000000'

$packageArgs = @{
  packageName    = $packageName
  fileType       = 'exe'
  url            = $url
  checksum       = $checksum
  checksumType   = 'sha256'
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
