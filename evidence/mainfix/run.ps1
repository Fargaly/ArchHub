param([ValidateSet('r2-big-conversation','r2-proposals','r2-red-js','r2-green-js','r2-green-python','r2-related-python','r2-related-js','red-python','red-js','green-python','green-js','red-big','green-big','fresh-big','related-python','related-js','red-receipts','green-receipts','green-receipt-page','red-partition','green-partition','related-partition','kernel-review','workshop-js','strict')][string]$Court)
$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path $PSScriptRoot 'court-state'
New-Item -ItemType Directory -Force $fixtureRoot | Out-Null
foreach ($name in @('LOCALAPPDATA','APPDATA','TEMP','TMP')) {
    $path = Join-Path $fixtureRoot $name
    New-Item -ItemType Directory -Force $path | Out-Null
    [Environment]::SetEnvironmentVariable($name, $path, 'Process')
}
$env:ARCHHUB_TEST_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ArchHub'
$env:PYTHONDONTWRITEBYTECODE = '1'
$python = 'C:\Users\fargaly\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$ErrorActionPreference = 'Continue' # Preserve complete native tracebacks in court evidence.
if ($Court -eq 'r2-big-conversation') {
    & $python tests_replica/mainfix_big_boot.py --conversation --expect-red-writes *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-proposals') {
    & $python -m pytest -q -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_agent_work_proposals.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-red-js') {
    $env:MAINFIX_BASELINE = 'aab5b20e'
    & node @('--test', '--test-concurrency=1', '--test-force-exit', '--test-name-pattern=deferred', 'tests_js/studio_mainfix.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-green-js') {
    $env:MAINFIX_BASELINE = '0'
    & node @('--test', '--test-concurrency=1', '--test-force-exit', 'tests_js/studio_mainfix.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-green-python') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_mainfix.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-related-python') {
    & $python -m pytest -q -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_mainrel_round3.py tests_replica/test_mainrel_installer.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'r2-related-js') {
    $env:CHATSEND_SOURCE = '1'
    & node @('--test', '--test-concurrency=1', '--test-force-exit', 'tests_js/studio_boot2_home.test.cjs', 'tests_js/studio_chatsend.test.cjs', 'tests_js/studio_workshop72_node_lazy.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -in @('red-partition','green-partition')) {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_archive.py -k 'test_mainfix_partition_count_witness' *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'related-partition') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_archive.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'kernel-review') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_review_kernel.py -k 'projection' *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'workshop-js') {
    & node @('--test', '--test-concurrency=1', '--test-force-exit', 'tests_js/studio_workshop72_node_lazy.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'red-receipts') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_owned_receipts.py -k 'test_receipt_scan_' *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'green-receipts') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_owned_receipts.py tests_replica/test_adopt_archive.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'green-receipt-page') {
    & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt_owned_receipts.py -k 'test_receipt_scan_' *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'related-python') {
    & $python -m pytest -q -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_adopt.py tests_replica/test_adopt_review.py tests_replica/test_adopt_backup_resume5.py tests_replica/test_ogboot_upgrade_selection.py tests_replica/test_adopt_archive_p1.py *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -eq 'related-js') {
    $env:CHATSEND_SOURCE = '1'
    & node @('--test', '--test-concurrency=1', '--test-force-exit', 'tests_js/studio_chatsend.test.cjs', 'tests_js/studio_composer_model_pick.test.cjs', 'tests_js/studio_inline_ask_retry_id.test.cjs', 'tests_js/studio_existing_workshop.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -like '*python') {
    if ($Court -eq 'red-python') {
        & $python evidence/mainfix/baseline.py "$fixtureRoot/pytest-$Court" *> "$PSScriptRoot/$Court.txt"
    } else {
        & $python -m pytest -q -s -p no:cacheprovider --basetemp "$fixtureRoot/pytest-$Court" tests_replica/test_mainfix.py *> "$PSScriptRoot/$Court.txt"
    }
} elseif ($Court -like '*js') {
    $env:MAINFIX_BASELINE = $(if ($Court -eq 'red-js') {'1'} else {'0'})
    & node @('--test', '--test-concurrency=1', '--test-force-exit', 'tests_js/studio_mainfix.test.cjs') *> "$PSScriptRoot/$Court.txt"
} elseif ($Court -like '*big') {
    if ($Court -eq 'red-big') {
        & $python tests_replica/mainfix_big_boot.py --baseline *> "$PSScriptRoot/$Court.txt"
    } elseif ($Court -eq 'fresh-big') {
        & $python tests_replica/mainfix_big_boot.py --boot-only *> "$PSScriptRoot/$Court.txt"
    } else {
        & $python tests_replica/mainfix_big_boot.py *> "$PSScriptRoot/$Court.txt"
    }
} else {
    $env:CARGO_HOME = 'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\rust\cargo'
    $env:RUSTUP_HOME = 'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\rust\rustup'
    $env:CARGO_TARGET_DIR = "$fixtureRoot/compiler-target"
    $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = Join-Path $env:RUSTUP_HOME 'toolchains\stable-x86_64-pc-windows-msvc\lib\rustlib\x86_64-pc-windows-msvc\bin\rust-lld.exe'
    $sdk = 'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\13.NODE-LANGUAGE\tools\archhub-compiler\target\msvc'
    $vc = "$sdk\VC\Tools\MSVC\14.44.35207"
    $kit = "$sdk\Windows Kits\10"
    $env:PATH = "$vc\bin\Hostx64\x64;$kit\bin\10.0.26100.0\x64;$env:PATH"
    $env:INCLUDE = "$vc\include;$kit\Include\10.0.26100.0\ucrt;$kit\Include\10.0.26100.0\shared;$kit\Include\10.0.26100.0\um"
    $env:LIB = "$vc\lib\x64;$kit\Lib\10.0.26100.0\ucrt\x64;$kit\Lib\10.0.26100.0\um\x64"
    & $python tools/pipeline/strict_check.py --changed --context evidence/mainfix/context.json *> "$PSScriptRoot/strict.txt"
}
exit $LASTEXITCODE
