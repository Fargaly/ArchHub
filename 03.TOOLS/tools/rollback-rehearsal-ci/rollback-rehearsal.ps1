<#
0400 -> main -> 0400, exclusively inside Windows Sandbox. The host only hashes
inputs, writes the plan and waits for a guest receipt. -DryRun never starts a
process. Requires Windows Sandbox already enabled (no feature/reboot changes).
Release/script mappings are read-only; only the selected results folder is writable.
Example (717 supplies the final built main artifact/hash/build id):
  .\installer\rollback-rehearsal.ps1 -LegacyInstaller <0400.exe> -MainInstaller <main.exe> -MainSha256 <sha256> -MainBuildId <id> -OutputDirectory <new-empty-output>
Repeat with -DryRun first. Real run refuses the wrong 0400 hash. DryRun also
works with dummy files, explicitly reports DRY-RUN and cannot produce a PASS.
Source: Microsoft Windows Sandbox configuration (read-only mappings + LogonCommand).
#>
[CmdletBinding()]
param(
    [string]$LegacyInstaller,
    [string]$MainInstaller,
    [ValidatePattern('^[a-fA-F0-9]{64}$')][string]$MainSha256,
    [ValidatePattern('^[A-Za-z0-9._-]+$')][string]$MainBuildId,
    [string]$OutputDirectory,
    [string]$PythonInstaller,
    [ValidateRange(1073741824,1099511627776)][long]$GuestWorkingBytes = 12884901888,
    [ValidateRange(30,7200)][int]$StepDeadline = 600,
    [ValidateRange(60,21600)][int]$RunDeadline = 3600,
    [switch]$DryRun,
    [switch]$CheckExecutionProfile,
    [switch]$Guest,
    [string]$PlanPath
)
$ErrorActionPreference = 'Stop'
$PollPeriod = [int]500
$CapturePeriod = [int]5000
$PythonDigest = '9D9EB2709EF81BF5CD30DB3C2096BDBC4EA10087C22E62F27D356B36F6AE9649'
$LegacyDigest = 'AB968ABE5B78DB0BE4C51C0321A2F1F5F6DA58B74914503A3AC3A9902C90F258'
$utf8 = [Text.UTF8Encoding]::new($false)
function Write-Record($Path, $Value) {
    $pending = $Path + '.' + [guid]::NewGuid().ToString('N') + '.pending'
    [IO.File]::WriteAllText($pending, ($Value | ConvertTo-Json -Depth 20), $utf8)
    [IO.File]::Move($pending, $Path)
}
function Get-RehearsalProfile {
    $account = [Security.Principal.WindowsIdentity]::GetCurrent().Name.Split('\')[-1]
    $nativeProfile = [Environment]::GetFolderPath('UserProfile')
    $kind = 'HOST'
    if ($account -eq 'WDAGUtilityAccount' -and $nativeProfile -eq 'C:\Users\WDAGUtilityAccount') { $kind = 'SANDBOX' }
    if ($account -eq 'runneradmin' -and $nativeProfile -eq 'C:\Users\runneradmin' -and
        $env:GITHUB_ACTIONS -eq 'true' -and $env:RUNNER_OS -eq 'Windows' -and
        $env:RUNNER_ENVIRONMENT -eq 'github-hosted' -and
        $env:GITHUB_REPOSITORY -eq 'Fargaly/archhub-rehearsal' -and $env:GITHUB_RUN_ID -match '^\d+$') { $kind = 'GITHUB' }
    return @{kind=$kind;local=[Environment]::GetFolderPath('LocalApplicationData');machine=[Environment]::MachineName}
}
if ($CheckExecutionProfile) { (Get-RehearsalProfile).kind; return }
if (-not $Guest) {
    foreach ($path in @($LegacyInstaller,$MainInstaller)) {
        if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Both installer files must exist; no build or download is performed.' }
    }
    if (-not $MainBuildId -or -not $MainSha256 -or -not $OutputDirectory) { throw 'MainBuildId, MainSha256 and a new empty OutputDirectory are required.' }
    $legacy = (Resolve-Path -LiteralPath $LegacyInstaller).Path
    $main = (Resolve-Path -LiteralPath $MainInstaller).Path
    $output = [IO.Path]::GetFullPath($OutputDirectory)
    # Never map an application profile or an input release as a writable result.
    $localProfile = [Environment]::GetFolderPath('LocalApplicationData')
    foreach ($forbidden in @((Join-Path $localProfile 'ArchHub'),(Join-Path $localProfile 'ArchHub-Test'),(Split-Path $legacy),(Split-Path $main))) {
        if ($output.Equals($forbidden,[StringComparison]::OrdinalIgnoreCase) -or $output.StartsWith($forbidden + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'OutputDirectory must be separate from profiles and release folders.' }
    }
    if ((Test-Path -LiteralPath $output) -and @(Get-ChildItem -LiteralPath $output -Force).Count) { throw 'OutputDirectory must be new or empty; previous evidence is never overwritten.' }
    $legacyHash = (Get-FileHash -LiteralPath $legacy -Algorithm SHA256).Hash
    $mainHash = (Get-FileHash -LiteralPath $main -Algorithm SHA256).Hash
    if ($mainHash -ne $MainSha256) { throw 'Main installer SHA-256 mismatch.' }
    if (-not $DryRun -and $legacyHash -ne $LegacyDigest) { throw 'This is not the real installed 0400 installer.' }
    $prerequisiteFile = ''
    if ($PythonInstaller) {
        $prerequisiteFile = (Resolve-Path -LiteralPath $PythonInstaller).Path
        if (-not $DryRun -and (Get-FileHash -LiteralPath $prerequisiteFile -Algorithm SHA256).Hash -ne $PythonDigest) { throw 'Offline Python installer does not match Setup pinned3.14.7 digest.' }
    } elseif (-not $DryRun) { throw 'Networking is disabled: supply the pinned offline Python3.14.7 installer via -PythonInstaller.' }
    $inputs = Join-Path $output 'input'
    $results = Join-Path $output 'results'
    New-Item -ItemType Directory -Path $inputs,$results -Force | Out-Null
    Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $inputs 'rollback-rehearsal.ps1')
    $plan = [ordered]@{
        schema='archhub-rollback-rehearsal/v1'; host_machine=$env:COMPUTERNAME
        legacy_file=(Split-Path $legacy -Leaf); main_file=(Split-Path $main -Leaf)
        legacy_sha256=$legacyHash; main_sha256=$mainHash; expected_legacy_sha256=$LegacyDigest
        main_build_id=$MainBuildId; legacy_build_id='20261018-0400-fd62cb8'
        python_file=$(if ($prerequisiteFile) {Split-Path $prerequisiteFile -Leaf} else {''}); python_sha256=$PythonDigest
        guest_working_bytes=$GuestWorkingBytes; minimum_guest_free_bytes=(25L * 1024 * 1024 * 1024 + $GuestWorkingBytes)
        step_deadline=$StepDeadline; marker=('MAINREL-rollback-' + [guid]::NewGuid().ToString('N'))
        steps=@('0400-install-open-write-close','main-install-open-verify-write-close','0400-reinstall-open-main-journal-close')
        mode=$(if ($DryRun) {'DRY-RUN'} else {'SANDBOX'})
    }
    Write-Record (Join-Path $inputs 'plan.json') $plan
    $maps = @(@((Split-Path $legacy),'C:\Mainrel0400','true'),@((Split-Path $main),'C:\MainrelMain','true'),@($inputs,'C:\MainrelInput','true'),@($results,'C:\MainrelResults','false'))
    if ($prerequisiteFile) { $maps += ,@((Split-Path $prerequisiteFile),'C:\MainrelPython','true') }
    $mapped = foreach ($map in $maps) {
        '<MappedFolder><HostFolder>' + [Security.SecurityElement]::Escape($map[0]) + '</HostFolder><SandboxFolder>' + $map[1] + '</SandboxFolder><ReadOnly>' + $map[2] + '</ReadOnly></MappedFolder>'
    }
    $command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\MainrelInput\rollback-rehearsal.ps1 -Guest -PlanPath C:\MainrelInput\plan.json'
    $xml = '<Configuration><VGpu>Disable</VGpu><Networking>Disable</Networking><ClipboardRedirection>Disable</ClipboardRedirection><MappedFolders>' + ($mapped -join '') + '</MappedFolders><LogonCommand><Command>' + [Security.SecurityElement]::Escape($command) + '</Command></LogonCommand></Configuration>'
    $wsb = Join-Path $output 'rollback.wsb'
    [IO.File]::WriteAllText($wsb,$xml,$utf8)
    $null = [xml]$xml
    if ($DryRun) {
        Write-Record (Join-Path $output 'dry-run.json') @{state='DRY-RUN';steps=$plan.steps;installers_started=0;read_only_input_mappings=($maps.Count-1);writable_result_mappings=1;legacy_sha256=$legacyHash;main_sha256=$mainHash;real0400=($legacyHash -eq $LegacyDigest)}
        Write-Output 'DRY-RUN: three read-only input mappings, one writable results mapping; 0400 -> main -> 0400; zero processes started.'
        exit 0
    }
    $sandbox = Get-Command WindowsSandbox.exe -ErrorAction Stop
    $before = @(Get-Process -Name @('WindowsSandbox','WindowsSandboxClient') -ErrorAction SilentlyContinue)
    if ($before.Count) { throw 'An existing Sandbox is open; no second instance is started or touched.' }
    $launcher = Start-Process -FilePath $sandbox.Source -ArgumentList ('"' + $wsb + '"') -WindowStyle Hidden -PassThru
    $launchedAt = $launcher.StartTime
    $child = $null
    $result = $null
    try {
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $receipt = Join-Path $results 'result.json'
        while (-not (Test-Path -LiteralPath $receipt) -or $null -eq $child) {
            # Windows11 delegates to WindowsSandboxClient. A new native window
            # must belong to the exact launcher's parent chain, not just a name.
            foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name='WindowsSandbox.exe' OR Name='WindowsSandboxClient.exe'")) {
                if (-not $candidate.ExecutablePath) { continue }
                $signature = Get-AuthenticodeSignature -FilePath $candidate.ExecutablePath
                if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Microsoft*') { continue }
                $process = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
                if (-not $process -or $process.StartTime -lt $launchedAt -or $process.MainWindowHandle -eq 0) { continue }
                $ancestor = $candidate
                $owned = $candidate.ProcessId -eq $launcher.Id
                for ($depth = 0; -not $owned -and $ancestor -and $depth -lt 16; $depth++) {
                    $owned = $ancestor.ParentProcessId -eq $launcher.Id
                    if (-not $owned) { $ancestor = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ancestor.ParentProcessId) }
                }
                if ($owned) { $child = $process; $ownedStart = $process.StartTime; break }
            }
            if ($clock.Elapsed.TotalSeconds -gt $RunDeadline) { throw 'Sandbox exceeded its deadline without an owned client and guest result; no acceptance.' }
            if ($child) { $child.Refresh(); if ($child.HasExited -and -not (Test-Path -LiteralPath $receipt)) { throw 'Owned Sandbox client exited without a result.' } }
            [Threading.Thread]::Sleep($PollPeriod)
        }
        $result = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
        if ($result.state -ne 'PASS' -or $result.steps.Count -ne 3 -or $result.legacy_sha256 -ne $LegacyDigest -or $result.main_sha256 -ne $MainSha256 -or $result.screenshots.Count -lt 6) { throw 'Sandbox rehearsal failed; inspect results/result.json and screenshots.' }
        foreach ($shot in $result.screenshots) {
            if ($shot.file -notmatch '^[A-Za-z0-9-]+\.png$') { throw 'Invalid screenshot receipt path.' }
            $file = Join-Path $results $shot.file
            if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $shot.sha256) { throw 'Screenshot receipt mismatch.' }
        }
    } finally {
        # Guest shuts its disposable machine down after writing the result.
        # Wait on the real window owner, never the delegating launcher.
        $disposed = $false
        if ($child) {
            $disposed = $child.WaitForExit(30000)
            if (-not $disposed -and $child.StartTime -eq $ownedStart) {
                $null = $child.CloseMainWindow()
                $disposed = $child.WaitForExit(10000)
            }
        }
        Write-Record (Join-Path $output 'sandbox-disposal.json') @{launcher_pid=$launcher.Id;client_pid=$(if ($child) {$child.Id} else {$null});process_exited=$disposed;instance_disposal_confirmed=($disposed -and $null -ne $result)}
        if (-not $disposed -or $null -eq $result) { throw 'Owned Sandbox instance disposal is unconfirmed; no acceptance. No unrelated process was stopped.' }
    }
    Write-Output ('SANDBOX PASS: ' + $receipt)
    exit 0
}

# Fail before every installer/app effect unless a disposable native profile owns it.
if ($PlanPath -ne 'C:\MainrelInput\plan.json') { throw 'Guest mode requires the Windows Sandbox account and mapped plan.' }
$executionProfile = Get-RehearsalProfile
if ($executionProfile.kind -notin @('SANDBOX','GITHUB')) { throw 'Guest mode requires the Windows Sandbox account and mapped plan; or the approved GitHub-hosted runneradmin profile.' }
$guestLocal = $executionProfile.local
$env:LOCALAPPDATA = $guestLocal
$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
if ($executionProfile.kind -eq 'SANDBOX') {
    if ($plan.mode -ne 'SANDBOX' -or $plan.host_machine -eq $executionProfile.machine) { throw 'Refusing a dry-run plan or the host machine.' }
} elseif ($plan.mode -ne 'GITHUB' -or $plan.run_id -ne $env:GITHUB_RUN_ID -or $plan.repository -ne $env:GITHUB_REPOSITORY) { throw 'Runner plan does not belong to this approved workflow run.' }
$StepDeadline = [int]$plan.step_deadline
$out = 'C:\MainrelResults'
$work = 'C:\MainrelWork'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$steps = [Collections.Generic.List[object]]::new()
$shots = [Collections.Generic.List[object]]::new()
$receipt = @{state='FAIL';steps=$steps;screenshots=$shots;legacy_sha256=$plan.legacy_sha256;main_sha256=$plan.main_sha256}
Add-Type -AssemblyName @('System.Drawing', 'System.Windows.Forms')
function Screenshot($Name) {
    $screen = [Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = [Drawing.Bitmap]::new($screen.Width,$screen.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($screen.Left,$screen.Top,0,0,$bitmap.Size)
        $path = Join-Path $out ($Name + '.png')
        $bitmap.Save($path,[Drawing.Imaging.ImageFormat]::Png)
        $shots.Add(@{file=($Name+'.png');sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash})
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
}
function Install-Release($File,$Hash,$Name,$BuildId) {
    if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ne $Hash) { throw 'Guest installer SHA-256 mismatch.' }
    $log = Join-Path $out ($Name + '-setup.log')
    # /SILENT retains the progress wizard; /VERYSILENT would hide guard3.
    $process = Start-Process -FilePath $File -ArgumentList ('/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="" /LOG="' + $log + '"') -PassThru
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $ordinal = 0
    $nextCapture = 0
    do {
        if ($clock.Elapsed.TotalMilliseconds -ge $nextCapture) {
            Screenshot ($Name + '-setup-' + $ordinal)
            $ordinal += 1
            $nextCapture = $clock.Elapsed.TotalMilliseconds + $CapturePeriod
        }
        if ($clock.Elapsed.TotalSeconds -gt $StepDeadline) { throw 'Setup exceeded the step deadline.' }
        [Threading.Thread]::Sleep($PollPeriod)
        $process.Refresh()
    } while (-not $process.HasExited)
    if ($process.ExitCode -ne 0) { throw ('Setup failed with exit code ' + $process.ExitCode) }
    $installed = (Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'ArchHub\BUILD_ID') -Raw).Trim()
    if ($installed -ne $BuildId) { throw 'Installed BUILD_ID differs from the selected release.' }
    return @{stage=$Name;build_id=$installed;installer_sha256=$Hash;elapsed=$clock.Elapsed.TotalSeconds}
}

function Add-RunnerFixture($Journal) {
    $source = [IO.Path]::GetFullPath($Journal)
    if (-not $source.StartsWith($guestLocal+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture source is outside the disposable profile.' }
    $sourceDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($source))
    $backupDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($plan.backup_base))
    $originalBytes = (Get-Item -LiteralPath $source).Length
    $reserve = [long]$plan.guest_working_bytes
    $backupReserve = 256L * 1024 * 1024
    $systemReserve = [long]26843545600
    $headroom = 64L * 1024 * 1024
    if ($sourceDrive.Name -eq $backupDrive.Name) {
        $capacity = [long](($sourceDrive.AvailableFreeSpace - $reserve - $systemReserve + $originalBytes) / 2)
    } else {
        $capacity = [Math]::Min($sourceDrive.AvailableFreeSpace-$reserve+$originalBytes,$backupDrive.AvailableFreeSpace-$backupReserve)
    }
    $target = [long]([Math]::Floor(([Math]::Min([long]$plan.fixture_requested_bytes,$capacity-$headroom))/1048576)*1048576)
    if ($target -lt [Math]::Max($originalBytes,$backupReserve)) { throw 'Hosted runner capacity cannot fit the journal, a verified backup and the declared payload reserve.' }
    # This is a fixture input to the ONE installer-owned preference, not a
    # second backup owner. The installed app reads the identical value.
    $identityBytes = [Text.Encoding]::UTF8.GetBytes(([IO.Path]::GetFullPath($guestLocal)).TrimEnd('\').ToLowerInvariant())
    $identity = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($identityBytes)).Replace('-','').ToLowerInvariant()
    $container = Join-Path $plan.backup_base ('ArchHub-backups\profile-'+$identity)
    $preference = Join-Path $guestLocal 'ArchHub\backup-location.json'
    if (Test-Path -LiteralPath $preference) { throw 'Runner profile already has a backup preference; refusing to replace unknown state.' }
    Write-Record $preference @{location=$plan.backup_base;directory=$container}
    $paddingCode = @'
from contextlib import closing
from pathlib import Path
import sqlite3,sys
path,target=Path(sys.argv[1]),int(sys.argv[2])
with closing(sqlite3.connect(path)) as db:
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('CREATE TABLE mainrel_rehearsal_padding(id INTEGER PRIMARY KEY,payload BLOB)')
    while path.stat().st_size < target:
        db.executemany('INSERT INTO mainrel_rehearsal_padding(payload) VALUES (zeroblob(1048576))',[()]*16)
        db.commit()
        print('FIXTURE_BYTES='+str(path.stat().st_size),flush=True)
print(path.stat().st_size)
'@
    $app = Join-Path $guestLocal 'ArchHub'
    & (Join-Path $app '.venv\Scripts\python.exe') -I -B -c $paddingCode $source $target | Tee-Object -FilePath (Join-Path $out 'fixture-padding.log') | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic runner fixture creation failed.' }
    $observed = (Get-Item -LiteralPath $source).Length
    return @{requested_bytes=[long]$plan.fixture_requested_bytes;target_bytes=$target;actual_bytes=[long]$observed;
        backup_base=$plan.backup_base;working_reserve_bytes=$reserve;headroom_bytes=$headroom;
        reduced_for_capacity=([long]$observed -lt [long]$plan.fixture_requested_bytes);
        source_free_after=$sourceDrive.AvailableFreeSpace;backup_free_after=$backupDrive.AvailableFreeSpace}
}

# Node's native CDP/WebSocket client acts on the installed app's real authenticated
# page. It writes a main-only graph, then reopens it through the rolled-back app.
$probe = @'
'use strict';
const [port, operation, marker] = process.argv.slice(2);
const deadline = 120000;
const timer = setTimeout(() => { console.error('CDP step deadline'); process.exit(1); }, deadline);
(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find(t => t.type === 'page' && /^http:\/\/127\.0\.0\.1:/.test(t.url));
  if (!target) throw Error('Installed Studio target is absent');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject) => {ws.onopen=resolve;ws.onerror=reject;});
  const expression = `(async () => {
    const session=window.__archhubSession;
    if (!session?.token || !session?.csrf || !document.querySelector('main')) throw Error('Installed Studio is not ready');
    const headers={'Content-Type':'application/json','X-ArchHub-Session':session.token,'X-ArchHub-CSRF':session.csrf};
    const call=async(path,body) => {const r=await fetch(path,{headers,...(body?{method:'POST',body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok||d.ok===false)throw Error(d.error||'Route refused');return d;};
    const marker=${JSON.stringify(marker)}, operation=${JSON.stringify(operation)};
    if(operation==='ready') return {ok:true,operation};
    if(operation==='seed') await call('/api/universal/graph-create',{title:marker+'-0400'});
    let index=await call('/api/universal/graphs');
    if(!index.graphs.some(g=>g.title===marker+'-0400'))throw Error('Original 0400 journal marker is missing');
    if(operation==='main') {await call('/api/universal/graph-create',{title:marker+'-main'});index=await call('/api/universal/graphs');}
    if(operation==='rollback') {
      const graph=index.graphs.find(g=>g.title===marker+'-main');
      if(!graph)throw Error('0400 cannot see the journal main left');
      const opened=await call('/api/universal/graph-open',{root:graph.id});
      if(opened.current_graph!==graph.id)throw Error('0400 did not open the main graph');
    }
    return {ok:true,operation,titles:index.graphs.filter(g=>g.title.startsWith(marker)).map(g=>g.title)};
  })()`;
  const message = await new Promise((resolve,reject) => {
    ws.onerror=reject;
    ws.onmessage=e=>{const d=JSON.parse(e.data);if(d.id===1)resolve(d);};
    ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}));
  });
  ws.close();
  if(message.error || message.result.exceptionDetails || message.result.result.value?.ok!==true) throw Error(JSON.stringify(message));
  console.log(JSON.stringify(message.result.result.value));
})().then(()=>{clearTimeout(timer);}).catch(e=>{console.error(e);process.exit(1);});
'@
[IO.File]::WriteAllText((Join-Path $work 'probe.cjs'),$probe,$utf8)
function Open-Verify-Close($Stage,$Operation) {
    $app = Join-Path $env:LOCALAPPDATA 'ArchHub'
    $port = 19225
    $env:QTWEBENGINE_REMOTE_DEBUGGING = '127.0.0.1:' + $port
    $env:ARCHHUB_VERIFY_NO_GPU = '1'
    $null = Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wscript.exe') -ArgumentList ('"' + (Join-Path $app 'ArchHub.vbs') + '"') -WorkingDirectory $app -PassThru
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        try { $targets = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $port + '/json/list'); if ($targets.Count) { break } } catch { $receipt.last_readiness_error = $_.Exception.Message }
        if ($clock.Elapsed.TotalSeconds -gt $StepDeadline) { throw 'Installed app did not expose its guest-only test page.' }
        [Threading.Thread]::Sleep($PollPeriod)
    } while ($true)
    # Wait for the actual authenticated Home, not just the CDP listener.
    do {
        $null = & (Join-Path $app 'runtime\node.exe') (Join-Path $work 'probe.cjs') $port 'ready' $plan.marker 2> (Join-Path $out ($Stage+'-ready-error.txt'))
        if ($LASTEXITCODE -eq 0) { break }
        if ($clock.Elapsed.TotalSeconds -gt $StepDeadline) { throw 'Installed journal open/write court failed; see probe error.' }
        [Threading.Thread]::Sleep($PollPeriod)
    } while ($true)
    # Effectful probes run once only; an ambiguous write is never replayed.
    $probeOutput = & (Join-Path $app 'runtime\node.exe') (Join-Path $work 'probe.cjs') $port $Operation $plan.marker 2> (Join-Path $out ($Stage+'-probe-error.txt'))
    if ($LASTEXITCODE -ne 0) { throw 'Installed journal court failed; no write was retried.' }
    [IO.File]::WriteAllText((Join-Path $out ($Stage+'-probe.json')),($probeOutput -join "`n"),$utf8)
    Screenshot ($Stage+'-opened')
    Set-Location $app
    $database = & (Join-Path $app '.venv\Scripts\python.exe') -E -s -c 'from nodelang.persistence import application_database_path; print(application_database_path().resolve())'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $database -PathType Leaf)) { throw 'Installed app selected no journal.' }
    [IO.File]::WriteAllText((Join-Path $app 'quit-request'),'quit',$utf8)
    do {
        $running = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and ($_.CommandLine -like ('*' + $app + '*nodelang\launcher.py*') -or $_.CommandLine -like ('*' + $app + '*launch_archhub_test.py*')) })
        if (-not $running.Count) { break }
        if ($clock.Elapsed.TotalSeconds -gt $StepDeadline) { throw 'Installed app did not close cleanly; no next installer was started.' }
        [Threading.Thread]::Sleep($PollPeriod)
    } while ($true)
    $hash = (Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash
    return @{path=[string]$database;sha256=$hash;operation=$Operation;elapsed=$clock.Elapsed.TotalSeconds}
}
try {
    if ($plan.legacy_sha256 -ne $LegacyDigest) { throw 'Guest plan does not name real0400.' }
    $drive = [IO.DriveInfo]::new('C:\')
    $receipt.guest_free_bytes = $drive.AvailableFreeSpace
    $receipt.minimum_guest_free_bytes = [long]$plan.minimum_guest_free_bytes
    if ($drive.AvailableFreeSpace -lt [long]$plan.minimum_guest_free_bytes) { throw ('Guest disk over budget: ' + $drive.AvailableFreeSpace + ' bytes free; requires ' + $plan.minimum_guest_free_bytes + ' bytes under this plan.') }
    $prerequisiteFile = Join-Path 'C:\MainrelPython' $plan.python_file
    if ((Get-FileHash -LiteralPath $prerequisiteFile -Algorithm SHA256).Hash -ne $PythonDigest) { throw 'Guest offline Python hash mismatch.' }
    $prerequisite = Start-Process -FilePath $prerequisiteFile -ArgumentList '/quiet /norestart InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_doc=0 PrependPath=0' -PassThru
    if (-not $prerequisite.WaitForExit($StepDeadline * 1000) -or $prerequisite.ExitCode -notin @(0,3010)) { throw 'Offline Python prerequisite failed or exceeded deadline.' }
    $legacy = Join-Path 'C:\Mainrel0400' $plan.legacy_file
    $main = Join-Path 'C:\MainrelMain' $plan.main_file
    $first = Install-Release $legacy $LegacyDigest '0400-before' $plan.legacy_build_id
    $first.journal = Open-Verify-Close '0400-before' 'seed'
    if ($executionProfile.kind -eq 'GITHUB') { $receipt.fixture = Add-RunnerFixture $first.journal.path }
    $steps.Add($first)
    $second = Install-Release $main $plan.main_sha256 'main' $plan.main_build_id
    $second.journal = Open-Verify-Close 'main' 'main'
    $steps.Add($second)
    $third = Install-Release $legacy $LegacyDigest '0400-after' $plan.legacy_build_id
    $third.journal = Open-Verify-Close '0400-after' 'rollback'
    if ($third.journal.path -ne $second.journal.path) { throw 'Rollback opened a different physical journal.' }
    $steps.Add($third)
    $receipt.state = 'PASS'
} catch {
    $receipt.error = $_.Exception.Message
    Screenshot 'failure'
} finally {
    Write-Record (Join-Path $out 'result.json') $receipt
    if ($executionProfile.kind -eq 'SANDBOX') { & (Join-Path $env:WINDIR 'System32\shutdown.exe') /s /t 0 /f }
}
if ($receipt.state -ne 'PASS') { exit 1 }
exit 0
