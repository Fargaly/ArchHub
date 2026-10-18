$ErrorActionPreference = 'Stop'
$wrapper = Join-Path $PSScriptRoot 'run_pytests.ps1'
& $wrapper -Baseline *> (Join-Path $PSScriptRoot 'baseline-red.txt')
$baseline = $LASTEXITCODE
& $wrapper -Mode fast *> (Join-Path $PSScriptRoot 'guards-final.txt')
$guards = $LASTEXITCODE
& $wrapper -Court @('tests_replica/test_application_machine_transport.py::test_baboom_context_transport_accepts_bounded_founder_approval_count_and_rejects_bad_values') *> (Join-Path $PSScriptRoot 'shows-as-final.txt')
$shows = $LASTEXITCODE
& $wrapper -Court @('tests_replica/test_a_colleague_machine_is_not_the_founders.py::test_no_route_names_a_fixed_founder_account') -FailFast *> (Join-Path $PSScriptRoot 'rest-first-failure.txt')
$existing = $LASTEXITCODE
& $wrapper -Court @('tests_replica/test_autoupd.py') *> (Join-Path $PSScriptRoot 'autoupd-built-studio.txt')
$updater = $LASTEXITCODE
$receipt = [ordered]@{baseline_red_exit=$baseline;guards_exit=$guards;shows_as_exit=$shows;existing_route_refusal_exit=@{type='integer';value=$existing;unit='process-exit-code';mutability='measured';source='rest-first-failure.txt'};updater_exit=$updater}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'regression-status.json'), ($receipt | ConvertTo-Json))
if ($baseline -ne 1 -or $guards -ne 0 -or $shows -ne 0 -or $updater -ne 0) { exit 1 }
exit 0
