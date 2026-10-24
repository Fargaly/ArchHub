"""Release refusal executes the same predicate the real qualification calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from tools.real_app_check.agentlink_release import require_checks, QualificationRefused


@pytest.mark.parametrize("model", ["opencode/paid", "openrouter/thinkingmachines/inkling", "other/model:free", "openrouter/:free"])
def test_paid_or_unrecognized_models_refuse_before_profile_creation(tmp_path, model):
    from tools.real_app_check import agentlink_release as gate
    profile = tmp_path / "agentlink-qualification-paid"
    with pytest.raises(QualificationRefused, match="explicitly free"):
        gate.qualify(profile, model=model)
    assert not profile.exists()


def test_quota_exhaustion_uses_one_free_route_through_the_same_cli(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    log = tmp_path / "opencode.log"
    stub = tmp_path / "PROVIDER.py"
    stub.write_text("import pathlib,sys,time\n"
        "model=sys.argv[sys.argv.index('-m')+1]\n"
        "with pathlib.Path(sys.argv[1]).with_name('CALLS.txt').open('a') as calls: calls.write(model+'\\n')\n"
        "if model.startswith('opencode/'):\n"
        " pathlib.Path(sys.argv[1]).write_text('message=\"stream error\" providerID=opencode modelID=mimo-v2.6-flash-free small=false error=\"Free usage limit reached\"\\n')\n"
        " time.sleep(12)\n"
        "else:\n"
        " import os\n"
        " assert os.environ['OPENROUTER_API_KEY']=='fixture-key'\n"
        " print('REAL_ROUTE_OUTPUT')\n", encoding="utf-8")
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    env = dict(os.environ)
    # Replay the original direct _run call when exercising the pre-fix source.
    turn = getattr(gate, "_opencode_turn", lambda command, model, quota_log, **options: (gate._run(command, **options), model))
    output, selected = turn([sys.executable, str(stub), str(log), "-m", "opencode/mimo-v2.6-flash-free"],
        model="opencode/mimo-v2.6-flash-free", env=env, cwd=tmp_path, timeout=8, quota_log=log)
    assert output.strip() == "REAL_ROUTE_OUTPUT"
    assert selected == "openrouter/thinkingmachines/inkling:free"
    assert (tmp_path / "CALLS.txt").read_text().splitlines() == ["opencode/mimo-v2.6-flash-free", selected]
    assert not any(path.name == "auth.json" for path in tmp_path.rglob("*"))
    for failed in ("exchange", "overlap", "opencode"):
        with pytest.raises(QualificationRefused):
            require_checks({"exchange":True, "overlap":True, "opencode":True, failed:False})


@pytest.mark.parametrize("line", [
    'providerID=opencode modelID=other-free small=false Free usage limit reached',
    'providerID=opencode modelID=mimo-v2.6-flash-free small=true Free usage limit reached',
    'providerID=opencode modelID=mimo-v2.6-flash-free small=false unrelated failure'])
def test_unrelated_or_stale_quota_does_not_switch_route(tmp_path, line):
    from tools.real_app_check import agentlink_release as gate
    log = tmp_path / "opencode.log"
    log.write_text('message="stream error" providerID=opencode modelID=mimo-v2.6-flash-free small=false Free usage limit reached\n')
    line = 'message="stream error" ' + line
    command = [sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).open('a').write(sys.argv[2]);raise SystemExit(9)",
        str(log), line, "-m", "opencode/mimo-v2.6-flash-free"]
    with pytest.raises(QualificationRefused, match="nonzero exit 9"):
        gate._opencode_turn(command, model="opencode/mimo-v2.6-flash-free", env=dict(os.environ),
            cwd=tmp_path, timeout=8, quota_log=log)


def test_explicit_free_openrouter_uses_existing_key_and_no_fallback(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    model = "openrouter/thinkingmachines/inkling:free"
    command = [sys.executable, "-c", "import os;assert os.environ['OPENROUTER_API_KEY']=='fixture-key';print('free')", "-m", model]
    output, selected = gate._opencode_turn(command, model=model, env=dict(os.environ), cwd=tmp_path,
        timeout=8, quota_log=tmp_path / "absent.log")
    assert (output.strip(), selected) == ("free", model)


@pytest.mark.parametrize("title", ["thinkingmachines/inkling:free", "google/gemini-nano-banana-2.1"])
def test_actual_stream_log_rejects_implicit_nonfree_title_model(title):
    from tools.real_app_check import agentlink_release as gate
    model = "openrouter/thinkingmachines/inkling:free"
    streams = ('message=stream providerID=openrouter modelID=thinkingmachines/inkling:free small=false\n'
        'message=stream providerID=openrouter modelID=' + title + ' small=true\n')
    if title.endswith(":free"):
        assert gate._free_stream_models(streams, model) == [model]
    else:
        with pytest.raises(QualificationRefused, match="explicitly free"):
            gate._free_stream_models(streams, model)
    with pytest.raises(QualificationRefused, match="no isolated server stream evidence"):
        gate._free_stream_models("", model)


@pytest.mark.parametrize("failed", ["exchange", "overlap", "opencode"])
def test_each_required_scenario_refuses_in_a_real_gate_process(failed):
    program = ("from tools.real_app_check.agentlink_release import require_checks; "
        "require_checks({'exchange':True,'overlap':True,'opencode':True," + repr(failed) + ":False})")
    result = subprocess.run([sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[2] / "03.TOOLS", capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE":"1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode != 0
    assert "AGENTLINK release refused: " + failed in result.stderr


def test_missing_or_unknown_state_never_becomes_pass():
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True})
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True,"opencode":"skipped"})
    require_checks({"exchange":True,"overlap":True,"opencode":True})


def test_echoed_ids_are_not_tool_read_receipts():
    import json
    from tools.real_app_check.agentlink_release import read_messages, write_sequence
    message = {"id":"overlap-proof", "refs":["one", "two"]}
    echoed = json.dumps({"type":"text","part":{"text":json.dumps({"messages":[message]})}})
    assert read_messages(echoed) == []
    result = json.dumps({"type":"tool_use", "part":{"tool":"archhub_agent_coordination_read",
        "state":{"status":"completed","output":json.dumps({"messages":[message]})}}})
    assert read_messages(result) == [message]
    good = "\n".join(json.dumps({"type":"tool_use","part":{"tool":tool,
        "state":{"status":"completed","output":"ok"}}}) for tool in ["write","read","write","glob"])
    assert write_sequence(good)
    assert not write_sequence(good.replace('"status": "completed"','"status": "error"',1))


def test_goose_only_auto_allows_the_shared_mailbox_boundary():
    from nodelang.goose_adapter import safe_workshop_call
    def identity(tool):
        return {"extensionName":"archhub-agent", "toolName":"archhub-agent__"+tool}
    assert safe_workshop_call(identity("read"), {"since":0})
    assert safe_workshop_call(identity("declare"), {"task":"Check fixture","paths":["fixture"],"status":"working","request_id":"proof"})
    assert safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","reply_to":"root"})
    assert safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","reply_to":"root","idempotency_key":"stable-reply"})
    assert not safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","sender":"forged"})
    assert not safe_workshop_call(identity("office_execute"), {"code":"unsafe"})
    assert not safe_workshop_call({"extensionName":"other","toolName":"archhub-agent__read"}, {})


@pytest.mark.parametrize("peer", ["claude", "goose"])
@pytest.mark.parametrize("failure_stage", ["construct", "start"])
def test_qualification_server_and_native_mailbox_select_one_profile(tmp_path, monkeypatch, peer, failure_stage):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import application_server, cell_secret_keys, model_router, workshop_mailbox
    from nodelang.persistence import application_database_path

    profile = tmp_path / "agentlink-qualification-profile"
    native_gate = tmp_path / "native_gate.py"
    native_gate.touch()
    monkeypatch.setattr(gate, "_executable", lambda *_: sys.executable)
    monkeypatch.setattr(gate, "_claude_auth", lambda *_: None)
    monkeypatch.setattr(model_router, "discover_key", lambda *_: ("fixture-credential", "fixture"))
    monkeypatch.setattr(gate, "source_digest", lambda *_: "source-fixture")
    monkeypatch.setattr(gate.shutil, "copytree", lambda *_args, **_kwargs: None)

    class Keys:
        def __init__(self, *_):
            pass
        def current(self, *_):
            pass

    class SelectedProfileChecked(Exception):
        pass

    class PartialServer:
        def __init__(self):
            import sqlite3
            self.connection = sqlite3.connect(application_database_path(profile))
            self.connection.execute("CREATE TABLE fixture(value)")
        def start(self):
            raise SelectedProfileChecked
        def close(self):
            self.connection.close()

    def server(**options):
        assert os.environ["OPENROUTER_API_KEY"] == "fixture-credential"
        assert json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])["small_model"] == "opencode/mimo-v2.6-flash-free"
        if peer == "goose":
            assert json.loads(os.environ["OPENROUTER_PARAMETERS"]) == {"max_tokens":4096}
            assert os.environ["GOOSE_MODEL"] == gate._GOOSE_MODEL
        selected = options["universal_state_path"]
        assert selected == application_database_path(profile)
        assert selected == workshop_mailbox.profile_database()
        if failure_stage == "construct":
            raise SelectedProfileChecked
        return PartialServer()

    monkeypatch.setattr(cell_secret_keys, "WindowsDpapiSigningKeyProvider", Keys)
    monkeypatch.setattr(application_server, "ApplicationServer", server)
    with pytest.raises(SelectedProfileChecked):
        gate.qualify(profile, native_gate=native_gate, peer=peer)
    assert not profile.exists()


@pytest.mark.parametrize("refused", ["compiler", "agentlink"])
def test_actual_installer_refuses_before_creating_output(tmp_path, refused):
    product = tmp_path / "01.WIP" / "PRODUCT"
    (product / "installer").mkdir(parents=True)
    (product / "tools" / "pipeline").mkdir(parents=True)
    (product / "tools" / "real_app_check").mkdir()
    root = Path(__file__).resolve().parents[2]
    shutil.copyfile(root / "03.TOOLS/installer/build_release.ps1", product / "installer/build_release.ps1")
    (product / "tools/__init__.py").touch()
    (product / "tools/real_app_check/__init__.py").touch()
    (product / "tools/pipeline/build.py").write_text(
        "print('COMPILER_REACHED',flush=True)\nraise SystemExit(" + ("23" if refused == "compiler" else "0") + ")\n")
    (product / "tools/real_app_check/agentlink_release.py").write_text(
        "print('AGENTLINK_REACHED',flush=True)\nraise SystemExit(24)\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL":os.devnull, "PYTHONPATH":str(product)}
    for args in (["init", "--quiet"], ["add", "."],
                 ["-c", "user.name=Gate fixture", "-c", "user.email=gate@example.invalid",
                  "commit", "--quiet", "-m", "Fixture"]):
        subprocess.run(["git", "-c", "core.longpaths=true", *args],
                       cwd=product, env=env, check=True, capture_output=True)
    archive = tmp_path / "GOOSE.zip"
    archive.touch()
    output = tmp_path / "OUTPUT"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File",
        str(product / "installer/build_release.ps1"), "-BuildId", "candidate-FIXTURE",
        "-OutputDirectory", str(output), "-GooseArchivePath", str(archive), "-PythonPath", sys.executable],
        cwd=product, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode != 0
    assert "COMPILER_REACHED" in result.stdout
    assert ("AGENTLINK_REACHED" in result.stdout) == (refused == "agentlink")
    assert ("ACOMPILER refused release build" if refused == "compiler" else "AGENTLINK refused release") in result.stderr
    assert not output.exists()


def test_installer_includes_the_required_stylesheet_without_allowing_arbitrary_assets(tmp_path):
    script = tmp_path / "CHECK.ps1"
    script.write_text(r'''
param([string]$Build)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Build,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-CandidateInput'},$true)
Invoke-Expression $function.Extent.Text
$acompilerInputs=@()
@('nodelang/studio/style.css','nodelang/studio/other.css','nodelang/credentials.json','nodelang/.env') | ForEach-Object { Test-CandidateInput 'selected' $_ } | ConvertTo-Json -Compress
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Build",
        str(Path(__file__).resolve().parents[2] / "03.TOOLS/installer/build_release.ps1")],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [True, False, False, False]


@pytest.mark.parametrize("version", ["1.18.34", "1.18.21"])
def test_isolated_opencode_dependencies_complete_before_bootstrap(tmp_path, monkeypatch, version):
    from tools.real_app_check import agentlink_release as gate
    env = gate.isolated_environment(tmp_path)
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "opencode")
    monkeypatch.setattr(gate.shutil, "which", lambda *_args, **_kwargs: "npm-fixture")
    calls = []
    def run(command, **options):
        calls.append((command, options))
        if command[-1] == "--version":
            return version + "\n"
        config = options["cwd"]
        assert config == tmp_path / "opencode"
        assert json.loads((config / "package.json").read_text())["dependencies"] == {"@opencode-ai/plugin":version}
        assert options["env"] is env
        assert options["timeout"] == 90
        assert "--ignore-scripts" in command
        assert "--fetch-retries=0" in command
        return "installed"
    monkeypatch.setattr(gate, "_run", run)
    gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["version", "npm", "install"])
def test_dependency_preparation_failure_never_reaches_bootstrap(tmp_path, monkeypatch, failure):
    from tools.real_app_check import agentlink_release as gate
    env = gate.isolated_environment(tmp_path)
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "opencode")
    monkeypatch.setattr(gate.shutil, "which", lambda *_args, **_kwargs: None if failure == "npm" else "npm-fixture")
    def run(command, **_options):
        if command[-1] == "--version":
            return "untrusted-version" if failure == "version" else "1.18.34\n"
        raise gate.QualificationRefused("dependency install failed")
    monkeypatch.setattr(gate, "_run", run)
    with pytest.raises(gate.QualificationRefused):
        gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)


@pytest.fixture
def plugin_cache(tmp_path):
    """Real npm content-addressed cache, including a transitive dependency."""
    import base64
    import hashlib
    import io
    import tarfile
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        pytest.fail("npm is required for the dependency restoration court")
    npm_root = Path(npm).resolve().parent / "node_modules/npm"
    cache = tmp_path / "CACHE" / "_cacache"
    seed = []
    for name, version, dependencies in [("@opencode-ai/plugin", "1.18.34", {"fixture-dependency":"1.0.0", "fixture-optional":"2.0.0"}),
                                        ("fixture-dependency", "1.0.0", {})]:
        manifest = {"name":name, "version":version, "dependencies":dependencies}
        if name == "@opencode-ai/plugin":
            manifest["optionalDependencies"] = {"fixture-optional":"1.0.0"}
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for filename, content in [("package.json", json.dumps(manifest).encode()), ("index.js", b"export const proof = true;\n")]:
                info = tarfile.TarInfo("package/" + filename)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        blob = data.getvalue()
        manifest["dist"] = {"integrity":"sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode()}
        seed.append({"key":"make-fetch-happen:request-cache:https://registry.npmjs.org/" + name.replace("/", "%2f"),
                     "metadata":json.dumps({"versions":{version:manifest}}), "blob":base64.b64encode(blob).decode()})
    seed_file = tmp_path / "SEED.json"
    seed_file.write_text(json.dumps(seed), encoding="utf-8")
    program = "const fs=require('fs'),c=require(process.argv[1]+'/node_modules/cacache');(async()=>{for(const r of JSON.parse(fs.readFileSync(process.argv[3]))){await c.put(process.argv[2],r.key,r.metadata);await c.put(process.argv[2],'tar:'+r.key,Buffer.from(r.blob,'base64'));}})().catch(e=>{console.error(e);process.exitCode=1})"
    subprocess.run([shutil.which("node"), "-e", program, str(npm_root), str(cache), str(seed_file)], check=True, timeout=30)
    return cache, npm_root


def test_local_plugin_cache_avoids_npm_deadline(tmp_path, monkeypatch, plugin_cache):
    from tools.real_app_check import agentlink_release as gate
    cache, _ = plugin_cache
    env = gate.isolated_environment(tmp_path / "PROFILE")
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "PROFILE/opencode")
    monkeypatch.setenv("npm_config_cache", str(cache.parent))
    original_run = gate._run
    calls = []
    def run(command, **options):
        calls.append(command)
        if command[-1] == "--version":
            return "1.18.34\n"
        if "install" in command:
            return original_run([sys.executable, "-c", "import time; time.sleep(95)"], **options)
        return original_run(command, **options)
    monkeypatch.setattr(gate, "_run", run)
    gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)
    assert not any("install" in command for command in calls)
    plugin = Path(env["OPENCODE_CONFIG_DIR"]) / "node_modules/@opencode-ai/plugin"
    assert json.loads((plugin / "package.json").read_text())["version"] == "1.18.34"
    assert (plugin / "node_modules/fixture-dependency/index.js").read_bytes() == b"export const proof = true;\n"
    assert not (plugin / "node_modules/fixture-optional").exists()
    lock = json.loads((Path(env["OPENCODE_CONFIG_DIR"]) / "package-lock.json").read_text())
    assert lock["packages"][""]["dependencies"] == {"@opencode-ai/plugin":"1.18.34"}


@pytest.mark.parametrize("scenario", ["absent", "wrong-version", "corrupt", "traversal", "symlink"])
def test_local_dependency_cache_never_accepts_unverified_bytes(tmp_path, plugin_cache, scenario):
    import base64
    import hashlib
    import io
    import tarfile
    cache, npm_root = plugin_cache
    seed_file = tmp_path / "SEED.json"
    rows = json.loads(seed_file.read_text())
    if scenario == "absent":
        cache = tmp_path / "ABSENT"
    elif scenario == "corrupt":
        digest = hashlib.sha512(base64.b64decode(rows[0]["blob"])).hexdigest()
        (cache / "content-v2/sha512" / digest[:2] / digest[2:4] / digest[4:]).write_bytes(b"corrupted")
    else:
        metadata = json.loads(rows[0]["metadata"])
        manifest = metadata["versions"]["1.18.34"]
        if scenario == "wrong-version":
            metadata["versions"] = {"1.18.21":{**manifest, "version":"1.18.21"}}
        else:
            blob = io.BytesIO()
            with tarfile.open(fileobj=blob, mode="w:gz") as archive:
                info = tarfile.TarInfo("package/../../ESCAPED" if scenario == "traversal" else "package/link")
                if scenario == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "../../ESCAPED"
                archive.addfile(info)
            data = blob.getvalue()
            manifest["dist"]["integrity"] = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
            rows[0]["blob"] = base64.b64encode(data).decode()
        rows[0]["metadata"] = json.dumps(metadata)
        seed_file.write_text(json.dumps(rows), encoding="utf-8")
        program = "const fs=require('fs'),c=require(process.argv[1]+'/node_modules/cacache');(async()=>{const r=JSON.parse(fs.readFileSync(process.argv[3]))[0];await c.put(process.argv[2],r.key,r.metadata);await c.put(process.argv[2],'tar:'+r.key,Buffer.from(r.blob,'base64'));})().catch(e=>{console.error(e);process.exitCode=1})"
        subprocess.run([shutil.which("node"), "-e", program, str(npm_root), str(cache), str(seed_file)], check=True, timeout=30)
    helper = Path(__file__).resolve().parents[2] / "03.TOOLS/tools/real_app_check/agentlink_dependencies.cjs"
    output = tmp_path / "RESTORED"
    result = subprocess.run([shutil.which("node"), str(helper), str(npm_root), str(cache), str(output), "1.18.34"],
        capture_output=True, text=True, timeout=30)
    if scenario in {"absent", "wrong-version"}:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "LOCAL_DEPENDENCIES_ABSENT"
        assert not output.exists()
    elif scenario == "corrupt":
        assert result.returncode != 0
        assert "LOCAL_DEPENDENCIES_VERIFIED" not in result.stdout
    else:
        from tools.real_app_check import agentlink_release as gate
        assert result.returncode == 0, result.stderr
        with pytest.raises(gate.QualificationRefused, match="Unsafe cached dependency"):
            gate._extract_opencode_dependencies(output, tmp_path / "PLUGIN", "1.18.34")
    assert not (tmp_path / "ESCAPED").exists()


@pytest.mark.parametrize("scenario", ["running", "stopped", "tamper", "measured-budget", "expired"])
def test_snapshot_budget_keeps_rehash_integrity_and_deadline(tmp_path, scenario):
    root = tmp_path / "SOURCE"
    root.mkdir()
    source = root / "fixture.py"
    source.write_bytes(b"trusted")
    env = {**os.environ, "GIT_CONFIG_GLOBAL":os.devnull}
    for args in (["init", "--quiet"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Fixture"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)
    output = tmp_path / "OUTPUT/source/selected"
    output.mkdir(parents=True)
    (output / "fixture.py").write_bytes(b"altered" if scenario == "tamper" else b"trusted")
    script = tmp_path / "COURT.ps1"
    script.write_text(r'''
param([string]$Build,[string]$Root,[string]$Output,[string]$Scenario)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Build,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Build parse errors'}
foreach($name in @('Assert-PlainAncestors','Get-SourceIdentity','Get-RepositoryPath','Assert-TrackedInputs','Assert-CandidateSources','Assert-CandidateBudget','Read-CandidateFile','Assert-BuildSnapshot')){
  $function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  Invoke-Expression $function.Extent.Text
}
$plainDirectories=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$repositoryAreas=@{}
$selectedInputs=@('fixture.py');$isCandidate=$false
$sourceRevision=(& git -C $Root rev-parse HEAD).Trim()
$source=Join-Path $Root 'fixture.py'
$sha=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($source)))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
$row=[pscustomobject]@{Source='selected';Path='fixture.py';Bytes=7;Sha256=$digest;SourcePath=$source;Identity=(Get-SourceIdentity $source)}
$manifest=[pscustomobject]@{Rows=@($row);SelectedCheckout=$Root}
$candidateBuffer=[byte[]]::new(1MB)
# A delayed real read remains charged; the measured budget admits slow valid verification.
$candidateClock=[Diagnostics.Stopwatch]::StartNew()
if($Scenario -eq 'stopped'){$candidateClock.Stop()}
$originalRead=${function:Read-CandidateFile}
function Read-CandidateFile { param($Row,$Path,$Destination) Start-Sleep -Milliseconds 250; & $originalRead $Row $Path $Destination }
$start=$candidateClock.Elapsed.TotalSeconds
$wall=[Diagnostics.Stopwatch]::StartNew()
if($Scenario -in @('measured-budget','expired')){
  $seconds=if($Scenario -eq 'expired'){421}else{200}
  $candidateClock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=$seconds};IsRunning=$true}
}
$failed=$false
try { Assert-BuildSnapshot $manifest } catch {
  $failed=$true
  if($Scenario -eq 'tamper' -and $_.Exception.Message -notlike '*Source content differs*'){throw}
  if($Scenario -eq 'expired' -and $_.Exception.Message -notlike '*exceeded*seconds*'){throw}
}
if($Scenario -in @('tamper','expired')){if(-not $failed){throw 'Required refusal missing'}}elseif($failed){throw 'Valid snapshot refused'}
if($Scenario -notin @('expired','measured-budget')){
  if($candidateClock.IsRunning -ne ($Scenario -ne 'stopped')){throw 'Stopwatch running state changed'}
  if($Scenario -ne 'stopped' -and ($candidateClock.Elapsed.TotalSeconds-$start) -lt 0.20){throw 'Rehash time escaped snapshot budget'}
}
Write-Output ('SNAPSHOT COURT PASS '+$Scenario)
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Build",
        os.environ.get("RELFLAKE_BUILD_SCRIPT", str(Path(__file__).resolve().parents[2] / "03.TOOLS/installer/build_release.ps1")),
        "-Root", str(root), "-Output", str(tmp_path / "OUTPUT"), "-Scenario", scenario],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SNAPSHOT COURT PASS " + scenario in result.stdout
