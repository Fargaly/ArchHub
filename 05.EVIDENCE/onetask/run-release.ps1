$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$python = 'C:/Users/fargaly/AppData/Local/ArchHub/.venv/Scripts/python.exe'
$env:PATH = (Split-Path $python) + ';' + [Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + [Environment]::GetEnvironmentVariable('PATH','User')
$env:ARCHHUB_NODE_MODULES = "$root/node_modules"
$testFiles = Get-Content "$PSScriptRoot/release-files.json" -Raw | ConvertFrom-Json
$sourceFiles = @((git -C $root diff --name-only HEAD) | Where-Object { $_ -match '^(01.APP|02.TESTS)/' }) + '02.TESTS/tests/test_onetask.py'
$hashes = @{}
foreach ($file in $sourceFiles) {
    if (Test-Path -LiteralPath "$root/$file" -PathType Leaf) {
        $hashes[$file] = (Get-FileHash -LiteralPath "$root/$file" -Algorithm SHA256).Hash
    }
}
@{executable=$python;PATH=$env:PATH;files=$testFiles;source_sha256=$hashes} | ConvertTo-Json -Depth 5 | Set-Content "$PSScriptRoot/release-env.json" -Encoding utf8
& $python '-m' 'pytest' '-q' '-p' 'no:cacheprovider' '-rf' '--tb=short' @testFiles 2>&1 | Tee-Object -FilePath "$PSScriptRoot/release.txt"
exit $LASTEXITCODE
