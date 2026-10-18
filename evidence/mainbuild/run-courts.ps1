param([ValidateSet('fast','strict','replay','full')][string]$Mode='fast')
$ErrorActionPreference='Stop'
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'
$root=(Resolve-Path .).Path
$state=Join-Path $root '.c/mainbuild-state'
New-Item -ItemType Directory -Force "$state/profile","$state/local","$state/roaming","$state/temp" | Out-Null
$env:LOCALAPPDATA="$state/local"
$env:APPDATA="$state/roaming"
$env:USERPROFILE="$state/profile"
$env:TEMP="$state/temp"
$env:TMP="$state/temp"
$env:ARCHHUB_TEST_STATE_DIR="$state/local/fixture"
$env:PYTHONUTF8='1'
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='core.longpaths'
$env:GIT_CONFIG_VALUE_0='true'
$env:CARGO_HOME='C:/Users/fargaly/00.ARCHUB/10.PRODUCT/rust/cargo'
$env:RUSTUP_HOME='C:/Users/fargaly/00.ARCHUB/10.PRODUCT/rust/rustup'
$env:CARGO_TARGET_DIR=Join-Path $root 'tools/archhub-compiler/target'
$env:ARCHHUB_INTENT_CONTEXT=$null
$env:ACOMPILER_REAL_BINARY=Join-Path $root 'tools/archhub-compiler/target/release/archhub-compiler.exe'
$python='C:/Users/fargaly/AppData/Local/Python/pythoncore-3.14-64/python.exe'
if($Mode -eq 'fast') {
 & $python -m pytest -q -p no:cacheprovider tests_replica/test_acompiler_gate.py -k 'release_replays or release_refuses_earlier or release_preserves or release_rejects or default_release or release_binary or build_runs or release_history' '--tb=short' *> evidence/mainbuild/fast-tests.txt
 exit $LASTEXITCODE
}
if($Mode -eq 'strict') {
 & $python tools/pipeline/strict_check.py --changed --context evidence/mainbuild/context.json *> evidence/mainbuild/strict.txt
 exit $LASTEXITCODE
}
if($Mode -eq 'replay') {
 & $python tools/pipeline/build.py --root . *> evidence/mainbuild/build.txt
 $code=$LASTEXITCODE
 Add-Content evidence/mainbuild/build.txt "EXIT $code"
 exit $code
}
if($Mode -eq 'full') {
 & $python -m pytest -q -p no:cacheprovider tests_replica/test_acompiler_gate.py tests_replica/test_mainrel_connectors.py tests_replica/test_assistant_registration.py tests_replica/test_acompiler2b.py '--tb=short' *> evidence/mainbuild/gate-tests.txt
 exit $LASTEXITCODE
}
