"""Behavioural installer prune/receipt courts; every target is a temporary install tree."""
import hashlib
import json
import os
import shutil
from contextlib import contextmanager, nullcontext
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from nodelang import host_addin_retarget as prune
from nodelang import host_addin_retarget as retarget
from nodelang.host_broker_installation import ADDIN_ID, CLASS_NAME, VENDOR_ID

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "ArchHub"
    root.mkdir()
    return root


def _manifest(root):
    rows = [prune.HEADER, "path\tsha256"]
    for name in ("nodelang/current.py", "app/__init__.py", "bridges/revit/2027/new/RevitMCP.dll"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"current build\n")
        rows.append(name + "\t" + hashlib.sha256(path.read_bytes()).hexdigest())
    identity = root / 'nodelang/legacy_cleanup_identities.json'
    if identity.is_file():
        rows.append('nodelang/legacy_cleanup_identities.json\t' + hashlib.sha256(identity.read_bytes()).hexdigest())
    raw = ("\n".join(rows) + "\n").encode()
    (root / "source-manifest.tsv").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _seed(root):
    digest = _manifest(root)
    # Exact installed-aef09cd static audit, plus every product root.
    orphans = ['nodelang/authority_adoption_record.py', 'nodelang/authority_adoption_structure.py', 'nodelang/authority_handoff.py', 'nodelang/automation.py', 'nodelang/baboom_attach.py', 'nodelang/boot_profile.py', 'nodelang/brain_memory_accelerators.py', 'nodelang/browser_graph_editor_court.py', 'nodelang/cell_attention_reactions.py', 'nodelang/cell_baboom_model_execution.py', 'nodelang/cell_baboom_steward.py', 'nodelang/cell_brain_fanout.py', 'nodelang/cell_brain_federation.py', 'nodelang/cell_legacy_brain_governance.py', 'nodelang/cell_legacy_core_nodes.py', 'nodelang/cell_legacy_custom_nodes.py', 'nodelang/cell_legacy_self_extension.py', 'nodelang/cell_legacy_surface_catalog.py', 'nodelang/cell_legacy_webshell_host.py', 'nodelang/cell_transparency_witness.py', 'nodelang/clean_agent_conversation.py', 'nodelang/clean_agent_coordination.py', 'nodelang/clean_application_server.py', 'nodelang/clean_application_view.py', 'nodelang/clean_model_adapter.py', 'nodelang/conversation_history_upgrade.py', 'nodelang/existing_workshop_model_worker.py', 'nodelang/existing_workshop_native_host.py', 'nodelang/gui_thread.py', 'nodelang/import_work_plan.py', 'nodelang/native_workshop_tools.py', 'nodelang/opencode_workshop_tools.py', 'nodelang/session_link_config.py', 'nodelang/session_link_transport.py', 'nodelang/social_research_community_backend.py', 'nodelang/startup_backup.py', 'nodelang/workshop_clean_archive.py', 'nodelang/workshop_page_lifecycle.py', 'nodelang/workshop_presentation.py', 'nodelang/workshop_project_resolution.py', 'nodelang/work_proposals.py', 'app/clean_shell.py', 'app/core.py', 'app/google_client.py', 'app/graph.py', 'app/runner.py', 'app/connectors/connector_health.py', 'app/connectors/sketchup_connector.py']
    orphans += ["studio/old.js", "bridges/revit/2027/old/RevitMCP.dll"]
    protected = ["settings/user.json", "workshop/messages.sqlite3", "logs/run.log", ".venv/user.pkg",
                 "Sessions/a.archhub", "recent/x.json", "checkpoints/x.json",
                 "nodelang/settings/user.json", "nodelang/test.universal.sqlite3",
                 "app/test.universal.sqlite3-wal", "studio/test.universal.sqlite3-shm",
                 "bridges/.venv/user.pkg", "nodelang/workshop/messages.sqlite3"]
    protected += [f"{root}/user{suffix}" for root in prune.ROOTS for suffix in
                  (".archhub", ".db", ".sqlite", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
                   ".json", ".yaml", ".toml", ".log")]
    for name in orphans + protected:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    (root / "BUILD_ID").write_text("previous-build")
    # A pre-baseline installer recorded creating this bridge year, but had no file manifest.
    prune.save_state(root, {"manifest": None, "installed_at_ns": (root / "BUILD_ID").stat().st_mtime_ns,
                            "bridge_years": ["bridges/revit/2027"], "pending_prune": {}})
    before = {name: (root / name).read_bytes() for name in protected}
    return digest, orphans, before


def test_fake_install_prunes_all_product_roots_and_preserves_state(install_root):
    tmp_path = install_root
    digest, orphans, before = _seed(tmp_path)
    assert set(prune.prune(tmp_path, digest)) == {name.casefold() for name in orphans}
    assert all(not (tmp_path / name).exists() for name in orphans)
    assert before == {name: (tmp_path / name).read_bytes() for name in before}
    assert prune.prune(tmp_path, digest) == []


def test_bad_manifest_or_copy_aborts_before_any_delete(install_root):
    tmp_path = install_root
    digest, orphans, _ = _seed(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        prune.prune(tmp_path, "0" * 64)
    (tmp_path / "nodelang/current.py").write_bytes(b"wrong copy")
    with pytest.raises(ValueError, match="differs"):
        prune.prune(tmp_path, digest)
    assert all((tmp_path / name).exists() for name in orphans)


@pytest.fixture
def legacy_inventory(tmp_path, monkeypatch):
    # Synthetic bytes exercise the same identity contract without copying installed data.
    def identity(data):
        return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    data = {'directories': {name: {'directories': [], 'files': {
        'README.md': identity(b'retired documentation')}} for name in prune.LEGACY_DIRS},
        'revit': {year: {**identity(b'old DLL'), 'mtime_utc_date': '2026-06-10'}
                  for year in ('2020', '2023', '2024', '2025')}}
    path = tmp_path / 'ArchHub/nodelang/legacy_cleanup_identities.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_f253_exact_legacy_cleanup_and_log_retention(install_root, capsys, legacy_inventory):
    root = install_root
    digest = _manifest(root)
    names = ['_config_backup_2026-06-01', '_deploy_backup_20260623-002259',
             '_syncrung_backup_20260623-005335', '.retired-v1-docs']
    for name in names:
        folder = root / name
        folder.mkdir()
        path = folder / 'README.md'
        path.write_text('retired documentation')
        os.utime(path, (1, 1))
    for year in ('2020', '2023', '2024', '2025'):
        path = root / 'Revit' / year / 'RevitMCP.dll'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'old DLL')
        os.utime(path, (1781049600, 1781049600))
    before = {}
    for name in ('settings/user.json', 'workshop/messages.sqlite3', 'Sessions/user.archhub',
                 'user.db', 'user.sqlite-wal', 'launcher.log', 'updates.log',
                 '_deploy_backup_unknown/README.md', 'Revit/2026/RevitMCP.dll'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        before[name] = path.read_bytes()
    for i in range(92):
        path = root / f'candidate-{i:02}.log'
        path.write_text(str(i))
        os.utime(path, (i + 1, i + 1))
    prune.prune(root, digest)
    assert all(not (root / name).exists() for name in names)
    assert all(not (root / 'Revit' / year).exists() for year in ('2020', '2023', '2024', '2025'))
    assert before == {name:(root / name).read_bytes() for name in before}
    from nodelang.log_rotation import LOG_KEEP
    retained = list((root / 'logs').rglob('candidate-*.log'))
    assert sorted(path.name for path in retained) == [f'candidate-{i:02}.log' for i in range(92 - LOG_KEEP, 92)]
    assert not list(root.glob('candidate-*.log'))
    output = capsys.readouterr().out
    assert all(name + '/README.md' in output for name in names)


@pytest.mark.parametrize('unsafe', ['unknown.bin', 'user.archhub', 'user.db', 'user.sqlite3-wal',
                                   'settings/user.json', 'keys/token.key', 'unknown.md', 'new', 'cutoff'])
def test_f253_keeps_entire_unsafe_legacy_directory(install_root, unsafe, capsys):
    root = install_root
    digest = _manifest(root)
    folder = root / '_config_backup_2026-06-01'
    folder.mkdir()
    known = folder / 'settings.json'
    known.write_text('{}')
    os.utime(known, (1, 1))
    path = folder / ('README.md' if unsafe in {'new', 'cutoff'} else unsafe)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'preserve')
    if unsafe != 'new':
        stamp = 1782864000 if unsafe == 'cutoff' else 1
        os.utime(path, (stamp, stamp))
    prune.prune(root, digest)
    assert path.read_bytes() == b'preserve' and known.read_text() == '{}'
    assert 'kept' in capsys.readouterr().out


@pytest.mark.parametrize('name', prune.LEGACY_DIRS)
def test_f253_unknown_old_python_alone_keeps_whole_directory(install_root, name, capsys):
    path = install_root / name / 'my-analysis.py'
    path.parent.mkdir()
    path.write_bytes(b'personal analysis')
    os.utime(path, (1, 1))
    prune.cleanup_legacy(install_root)
    assert path.read_bytes() == b'personal analysis'
    assert 'legacy kept:' in capsys.readouterr().out


@pytest.mark.parametrize('change', ['extra', 'changed', 'missing', 'empty-directory'])
def test_f253_exact_inventory_mismatch_keeps_every_file(install_root, legacy_inventory, change, capsys):
    folder = install_root / prune.LEGACY_DIRS[0]
    folder.mkdir()
    known = folder / 'README.md'
    known.write_bytes(b'retired documentation')
    if change == 'extra':
        (folder / 'my-analysis.py').write_bytes(b'user code')
    elif change == 'changed':
        known.write_bytes(b'RETIRED documentation')
    elif change == 'missing':
        known.unlink()
    else:
        (folder / 'user-folder').mkdir()
    before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    prune.cleanup_legacy(install_root, hashlib.sha256(legacy_inventory.read_bytes()).hexdigest())
    assert folder.is_dir()
    assert before == {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    assert 'legacy kept:' in capsys.readouterr().out


@pytest.mark.parametrize('year', ['2020', '2023', '2024', '2025'])
@pytest.mark.parametrize('change', ['hash', 'date'])
def test_f253_modified_revit_dll_kept(install_root, legacy_inventory, year, change, capsys):
    path = install_root / 'Revit' / year / 'RevitMCP.dll'
    path.parent.mkdir(parents=True)
    data = b'new DLL' if change == 'hash' else b'old DLL'
    path.write_bytes(data)
    stamp = 1781049600 if change == 'hash' else 1781136000
    os.utime(path, (stamp, stamp))
    prune.cleanup_legacy(install_root, hashlib.sha256(legacy_inventory.read_bytes()).hexdigest())
    assert path.read_bytes() == data
    assert 'kept: unrecognized Revit/' + year in capsys.readouterr().out


def _owned():
    return ('<RevitAddIns><AddIn><AddInId>%s</AddInId><FullClassName>%s</FullClassName>'
            '<VendorId>%s</VendorId></AddIn></RevitAddIns>' % (ADDIN_ID, CLASS_NAME, VENDOR_ID)).encode()


def test_revit_receipts_both_roots_all_years_and_gated_legacy_cleanup(tmp_path, capsys):
    env = {key: str(tmp_path / key) for key in ("APPDATA", "ProgramData")}
    roots = retarget.addins_roots(env)
    foreign = []
    for root in roots:
        for year in ("2024", "2027", "2029"):
            folder = root / year
            folder.mkdir(parents=True)
            path = folder / "Vendor.addin"
            path.write_bytes(b"<RevitAddIns><AddIn><Name>Other vendor</Name></AddIn></RevitAddIns>")
            foreign.append(path)
            (folder / "ArchHub.addin.retired").write_bytes(_owned())
            (folder / "Foreign.addin.retired").write_bytes(b"foreign")
            (folder / ".archhub-addin-abcd.tmp").write_bytes(b"incomplete")
    app = tmp_path / "ArchHub"
    for year in ("2024", "2027"):
        folder = app / "Revit" / year
        folder.mkdir(parents=True)
        for name in ("RevitMCP.dll", "RevitMCP.pdb", "RevitMCP.deps.json", "RevitMCPCore.dll",
                     "RevitMCPCore.pdb", "RevitMCPCore.deps.json"):
            (folder / name).write_bytes(b"old")
        (folder / "RevitMCP.addin").write_bytes(_owned())
    setup = SimpleNamespace(register_revit_add_ins=lambda root: [
        {"host_version": "2027", "registered": True, "status": "registered"},
        {"host_version": "2024", "registered": False, "status": "refused"}],
        register_autocad_add_ins=lambda root: None)
    assert retarget.retarget(app, setup, env) == 0
    assert (app / "Revit/2027/RevitMCP.dll").read_bytes() == b"old"
    assert (app / "Revit/2027/RevitMCP.deps.json").read_bytes() == b"old"
    assert (app / "Revit/2024/RevitMCP.dll").read_bytes() == b"old"
    for root in roots:
        assert len(list(root.glob("*/*.tmp"))) == 3
        assert not list(root.glob("*/ArchHub.addin.retired"))
        assert len(list(root.glob("*/Foreign.addin.retired"))) == 3
    receipts = [json.loads(line.removeprefix("REVIT FOREIGN RECEIPT ")) for line in capsys.readouterr().out.splitlines()
                if line.startswith("REVIT FOREIGN RECEIPT ")]
    assert len(receipts) == 12
    assert len(foreign) == 6
    assert all(row["unchanged"] and row["before_sha256"] == row["after_sha256"] for row in receipts)


@contextmanager
def _held_open(path):
    import ctypes
    from ctypes import wintypes
    create = ctypes.windll.kernel32.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    handle = create(str(path), 0x80000000, 1, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value
    try:
        with pytest.raises(PermissionError):
            path.unlink()
        yield
    finally:
        assert close(handle)


@pytest.mark.skipif(sys.platform != 'win32', reason='real Windows file locks')
def test_f253_locked_revit_and_logs_defer_then_retry(install_root, capsys, legacy_inventory):
    root = install_root
    digest = _manifest(root)
    dll = root / 'Revit/2024/RevitMCP.dll'
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b'old DLL')
    os.utime(dll, (1781049600, 1781049600))
    log = root / 'candidate-held.log'
    log.write_bytes(b'held log')
    with _held_open(dll), _held_open(log):
        prune.prune(root, digest)
        assert dll.read_bytes() == b'old DLL' and log.read_bytes() == b'held log'
        assert 'deferred: in use by a running program' in capsys.readouterr().out
    prune.prune(root, digest)
    assert not dll.parent.exists() and not log.exists()
    assert (root / 'logs/root/candidate-held.log').read_bytes() == b'held log'


@pytest.mark.parametrize("locked", [False, True])
def test_inno_post_copy_runs_the_same_pruner(tmp_path, install_root, locked):
    compiler = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
    if not compiler.is_file():
        pytest.skip("Inno Setup is not installed")
    app = install_root
    digest, orphans, before = _seed(app)
    script = tmp_path / "prune.iss"
    script.write_text('''[Setup]
AppName=ArchHub prune court
AppVersion=1
DefaultDirName={param:app}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=no
CloseApplications=no
RestartApplications=no
OutputBaseFilename=prune-court
[Files]
Source: "{#Source}"; DestDir: "{app}\\nodelang"; Flags: ignoreversion
Source: "{#Source}"; Flags: dontcopy
Source: "{#Manifest}"; DestDir: "{app}"; DestName: "source-manifest.tsv"; Flags: ignoreversion
[Code]
procedure OnPruneLog(const S: String; const Error, FirstLine: Boolean);
begin
  Log(S);
end;
procedure CurStepChanged(Step: TSetupStep);
var Code: Integer;
begin
  if Step = ssInstall then begin
    ExtractTemporaryFile('host_addin_retarget.py');
    ExtractTemporaryFile('source-manifest.tsv');
    if not ExecAndLogOutput(ExpandConstant('{param:python}'), '-B "' + ExpandConstant('{tmp}') + '\\host_addin_retarget.py" --prepare "' + ExpandConstant('{app}') + '" "' + ExpandConstant('{tmp}') + '\\source-manifest.tsv" {#Digest}', ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, Code, @OnPruneLog) then RaiseException('could not prepare prune');
    if Code <> 0 then RaiseException('prune preparation failed');
  end;
  if Step = ssPostInstall then begin
    if not ExecAndLogOutput(ExpandConstant('{param:python}'), '-B "' + ExpandConstant('{app}') + '\\nodelang\\host_addin_retarget.py" --prune "' + ExpandConstant('{app}') + '" {#Digest}', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code, @OnPruneLog) then RaiseException('could not run prune');
    if Code <> 0 then RaiseException('prune failed');
  end;
end;
''', encoding="utf-8")
    # The copied pruner is itself in this build's manifest.
    helper = ROOT / "01.APP/nodelang/host_addin_retarget.py"
    manifest = app / "source-manifest.tsv"
    manifest.write_text(manifest.read_text() + "nodelang/host_addin_retarget.py\t" + hashlib.sha256(helper.read_bytes()).hexdigest() + "\n")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    build = subprocess.run([str(compiler), "/Q", "/O" + str(tmp_path), "/DSource=" + str(helper), "/DManifest=" + str(manifest), "/DDigest=" + digest, str(script)], capture_output=True, text=True, timeout=90)
    assert build.returncode == 0, build.stdout + build.stderr
    command = [str(tmp_path / "prune-court.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/app=" + str(app), "/python=" + sys.executable, "/LOG=" + str(tmp_path / "install.log")]
    old = "bridges/revit/2027/old/RevitMCP.dll"
    with _held_open(app / old) if locked else nullcontext():
        done = subprocess.run(command, capture_output=True, timeout=90)
        log = (tmp_path / "install.log").read_text(errors="replace")
        assert done.returncode == 0, log
        assert "PRUNE DRY RUN" in log
        if locked:
            assert (app / old).read_bytes() == old.encode()
            assert "deferred: in use by a running program" in log
            state = json.loads((app / prune.RECEIPT).read_text())
            assert old.casefold() in state["pending_prune"]
            orphans.remove(old)
    if locked:
        # A second install retries the saved pending-prune list after the handle closes.
        assert subprocess.run(command, capture_output=True, timeout=90).returncode == 0
        assert not (app / old).exists()
        assert json.loads((app / prune.RECEIPT).read_text())["pending_prune"] == {}
    assert all(not (app / name).exists() for name in orphans)
    assert before == {name: (app / name).read_bytes() for name in before}


def test_manifest_covers_generated_studio_and_gated_hosts_only(tmp_path):
    source, hosts = tmp_path / "source", tmp_path / "hosts"
    included = ["nodelang/host_addin_retarget.py", "nodelang/studio/compiled/main.js",
                "app/__init__.py", "app/credential_lock.py", "app/secrets_store.py",
                "bridges/rhino/archhub_mcp.py", "bridges/blender/archhub_mcp/__init__.py",
                "bridges/sources/max_mcp/max_mcp_startup.py",
                "nodelang/legacy_cleanup_identities.json", "nodelang/workshop/mailbox.mjs",
                "nodelang/workshop/vendor/sdk.cjs"]
    excluded = ["nodelang/__pycache__/old.pyc", "app/unshipped.py", "nodelang/private.db",
                "nodelang/other.json", "nodelang/workshop/messages.sqlite3", "workshop/user.py"]
    for name in included + excluded:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    dll = hosts / "bridges/revit/2027/build/RevitMCP.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"gated")
    output = tmp_path / "source-manifest.tsv"
    prune.write_manifest(source, hosts, output)
    rows = dict(line.split("\t") for line in output.read_text().splitlines()[2:])
    assert "nodelang/studio/compiled/main.js" in rows
    assert "bridges/revit/2027/build/RevitMCP.dll" in rows
    assert "bridges/max/max_mcp_startup.py" in rows
    for name in included:
        if name != 'bridges/sources/max_mcp/max_mcp_startup.py':
            assert rows[name] == hashlib.sha256((source / name).read_bytes()).hexdigest()
    assert not set(excluded) & rows.keys()
    assert not any("__pycache__" in name or "unshipped" in name or name.endswith(".db") for name in rows)


def test_identity_payload_admission_is_exact():
    script = ROOT / '03.TOOLS/installer/build_release.ps1'
    command = r'''
param($Script)
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$null, [ref]$null)
$f = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Test-CandidateInput'}, $true)
Invoke-Expression $f.Extent.Text
@('nodelang/legacy_cleanup_identities.json', 'nodelang/other.json',
  'nodelang/workshop/legacy_cleanup_identities.json', 'nodelang/settings/user.json',
  'nodelang/LEGACY_CLEANUP_IDENTITIES.json', 'nodelang/workshop/mailbox.mjs') |
  ForEach-Object { [bool](Test-CandidateInput 'selected' $_) } | ConvertTo-Json -Compress
'''
    result = subprocess.run([shutil.which('powershell') or shutil.which('pwsh'), '-NoProfile', '-Command', '& { ' + command + ' }', str(script)],
                            capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == [True, False, False, False, False, True]


def test_manifest_covers_real_workshop_programs(tmp_path):
    source = ROOT / '01.APP'
    output = tmp_path / 'manifest.tsv'
    prune.write_manifest(source, tmp_path / 'hosts', output)
    rows = prune.manifest_rows(output.read_bytes())
    programs = [path for path in (source / 'nodelang/workshop').rglob('*')
                if path.is_file() and path.suffix in {'.js', '.mjs', '.cjs', '.py', '.ps1'}]
    assert programs
    for path in programs:
        assert rows[path.relative_to(source).as_posix()] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert prune.protected(Path('workshop/user.py'))
    assert not prune.protected(Path('nodelang/workshop/mailbox.mjs'))
    assert prune.protected(Path('nodelang/workshop/messages.sqlite3'))


@pytest.mark.parametrize('fault', ['missing', 'changed', 'unmanifested'])
def test_identity_fault_skips_legacy_cleanup(install_root, legacy_inventory, fault, capsys):
    folder = install_root / prune.LEGACY_DIRS[0]
    folder.mkdir()
    known = folder / 'README.md'
    known.write_bytes(b'retired documentation')
    if fault == 'unmanifested':
        raw = legacy_inventory.read_bytes()
        legacy_inventory.unlink()
        digest = _manifest(install_root)
        legacy_inventory.write_bytes(raw)
    else:
        digest = _manifest(install_root)
        if fault == 'missing':
            legacy_inventory.unlink()
        else:
            legacy_inventory.write_bytes(legacy_inventory.read_bytes() + b' ')
    prune.prune(install_root, digest)
    assert known.read_bytes() == b'retired documentation'
    assert 'PRUNE legacy kept:' in capsys.readouterr().out


def test_pruner_does_not_follow_a_junction(install_root):
    tmp_path = install_root
    digest, _, _ = _seed(tmp_path)
    foreign = tmp_path / "outside"
    foreign.mkdir()
    (foreign / "keep.py").write_bytes(b"foreign")
    link = tmp_path / "nodelang/redirected"
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(foreign)], capture_output=True)
    assert done.returncode == 0, done.stderr
    prune.prune(tmp_path, digest)
    assert (foreign / "keep.py").read_bytes() == b"foreign"


def test_reviewer_three_root_manifest_keeps_user_documents_and_databases(install_root):
    digest = _manifest(install_root)
    names = ("nodelang/my-work.archhub", "nodelang/brain.sqlite3", "nodelang/user.db")
    before = {}
    for name in names:
        path = install_root / name
        path.write_bytes(name.encode())
        before[name] = path.read_bytes()
    prune.prune(install_root, digest)
    assert before == {name: (install_root / name).read_bytes() for name in names}


def _add_row(root, name, data=b"installed code"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    manifest = root / "source-manifest.tsv"
    manifest.write_bytes(manifest.read_bytes() + (name + "\t" + hashlib.sha256(data).hexdigest() + "\n").encode())
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_previous_manifest_only_drops_owned_unchanged_files(install_root, capsys):
    root = install_root
    _manifest(root)
    _add_row(root, "nodelang/dropped.py")
    _add_row(root, "app/changed.py")
    digest = _add_row(root, "studio/old.png")
    prune.prune(root, digest)
    state = json.loads((root / prune.RECEIPT).read_text())
    assert "nodelang/dropped.py" in state["manifest"]
    (root / "app/changed.py").write_bytes(b"user edits")
    user = root / "nodelang/unmanifested.py"
    user.write_bytes(b"user program")
    os.utime(user, ns=(1_000_000_000, 1_000_000_000))
    digest = _manifest(root)
    assert set(prune.prune(root, digest)) == {"nodelang/dropped.py", "studio/old.png"}
    assert user.read_bytes() == b"user program"
    assert (root / "app/changed.py").read_bytes() == b"user edits"
    log = capsys.readouterr().out
    assert log.index("PRUNE DRY RUN [\"app/changed.py\"") < log.index("PRUNE nodelang/dropped.py")


@pytest.mark.parametrize("name", ["nodelang/user.archhub", "app/owner.db", "studio/owner.sqlite3",
                                   "bridges/owner.sqlite-wal", "app/user.json", "studio/user.yaml",
                                   "nodelang/user.toml", "app/run.log", "bridges/owner.sqlite3-shm",
                                   *[f"nodelang/{folder}/keep.py" for folder in prune.STATE_DIRS - {'workshop'}]])
def test_never_delete_candidate_aborts_entire_prune(install_root, capsys, name):
    root = install_root
    _manifest(root)
    _add_row(root, "nodelang/dropped.py")
    digest = _add_row(root, name, b"user bytes")
    prune.prune(root, digest)
    digest = _manifest(root)
    assert prune.prune(root, digest) == []
    assert (root / name).read_bytes() == b"user bytes"
    assert (root / "nodelang/dropped.py").read_bytes() == b"installed code"
    log = capsys.readouterr().out
    assert "PRUNE DRY RUN" in log and "PRUNE skipped: never-delete candidate" in log
    assert json.loads((root / prune.RECEIPT).read_text())["manifest"] == (root / "source-manifest.tsv").read_text()


def test_legacy_allowlist_time_and_directory_ownership(install_root):
    root = install_root
    digest = _manifest(root)
    kept = ["nodelang/user.py", "nodelang/readme.html", "app/user.exe", "studio/user.dll",
            "bridges/revit/2027/user.dll", "bridges/autocad/2026/user.addin", "app/photo.png"]
    deleted = ["nodelang/old.py", "app/old.pyi", "studio/old.html", "nodelang/studio/old.html",
               "bridges/rhino/old.py"]
    for name in kept + deleted:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    (root / "BUILD_ID").write_text("previous")
    future = (root / "BUILD_ID").stat().st_mtime_ns + 1_000_000_000
    os.utime(root / kept[0], ns=(future, future))
    assert set(prune.prune(root, digest)) == set(deleted)
    assert all((root / name).read_bytes() == name.encode() for name in kept)


def test_prepare_records_only_new_years_and_previous_manifest(install_root, tmp_path):
    root = install_root
    digest = _manifest(root)
    old = (root / "source-manifest.tsv").read_bytes()
    (root / "BUILD_ID").write_text("previous")
    cutoff = (root / "BUILD_ID").stat().st_mtime_ns
    incoming = tmp_path / "incoming.tsv"
    incoming.write_bytes(old + b"bridges/autocad/2026/build/AcadMCP.dll\t" + b"a" * 64 + b"\n")
    prune.prepare(root, incoming, hashlib.sha256(incoming.read_bytes()).hexdigest())
    state = json.loads((root / prune.RECEIPT).read_text())
    assert state["manifest"].encode() == old
    assert state["installed_at_ns"] == cutoff
    assert state["bridge_years"] == ["bridges/autocad/2026"]
    assert prune.prune(root, digest) == []


def test_outside_install_and_corrupt_receipt_never_prune(install_root, tmp_path, capsys):
    root = tmp_path / "outside"
    root.mkdir()
    digest, orphans, _ = _seed(root)
    with pytest.raises(ValueError, match="outside plain"):
        prune.prune(root, digest)
    assert all((root / name).exists() for name in orphans)
    digest, orphans, _ = _seed(install_root)
    (install_root / prune.RECEIPT).write_text("{broken")
    with pytest.raises(ValueError, match="invalid previous installed manifest"):
        prune.prune(install_root, digest)
    assert all((install_root / name).exists() for name in orphans)


def test_forbidden_candidate_keeps_pending_lock_retry(install_root):
    root = install_root
    _manifest(root)
    _add_row(root, "app/user.json", b"user data")
    digest = _add_row(root, "bridges/revit/2027/old/Locked.dll", b"old code")
    prune.prune(root, digest)
    digest = _manifest(root)
    old = root / "bridges/revit/2027/old/Locked.dll"
    state = json.loads((root / prune.RECEIPT).read_text())
    state["pending_prune"] = {"bridges/revit/2027/old/locked.dll": {
        "sha256": hashlib.sha256(old.read_bytes()).hexdigest(), "mtime_ns": old.stat().st_mtime_ns}}
    prune.save_state(root, state)
    with _held_open(old):
        assert prune.prune(root, digest) == []  # user.json aborts all deletion
        assert json.loads((root / prune.RECEIPT).read_text())["pending_prune"]
    assert prune.prune(root, digest) == ["bridges/revit/2027/old/locked.dll"]
    assert (root / "app/user.json").read_bytes() == b"user data"

@pytest.mark.parametrize("fault", [False, True, "outside", "receipt", "terminated", "founder", "legacy"])
def test_production_postinstall_events(tmp_path, install_root, monkeypatch, fault, legacy_inventory):
    """Execute production event code, including its error handling, without host/profile effects."""
    compiler = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
    app = install_root
    digest, orphans, before = _seed(app)
    (app / "BUILD_ID").write_text("20261107-2320-37990c4")
    if fault == 'legacy':
        for name in prune.LEGACY_DIRS:
            path = app / name / 'README.md'
            path.parent.mkdir()
            path.write_bytes(b'retired documentation')
            os.utime(path, (1, 1))
        for year in ('2020', '2023', '2024', '2025'):
            path = app / 'Revit' / year / 'RevitMCP.dll'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'old DLL')
            os.utime(path, (1781049600, 1781049600))
        for i in range(92):
            path = app / f'candidate-{i:02}.log'
            path.write_text(str(i))
            os.utime(path, (i + 1, i + 1))
    if fault == "founder":
        for name in list(orphans):
            if not Path(name).name.startswith("cell_"):
                (app / name).unlink()
                orphans.remove(name)
        assert len(orphans) == 12
        prune.save_state(app, {"manifest": None, "installed_at_ns": 1794080448225386100,
                               "pending_prune": {}, "bridge_years": []})
    source = ROOT / "03.TOOLS/installer/ArchHub.iss"
    text = source.read_text()
    callback = text[text.index("var\n  BackupProgress:"):text.index("function PrepareToInstall(")]
    # Real prepare/postinstall, real logger; external assistant/host actions are inert.
    callback = callback.replace("RemoveRetiredRuntimeTask(CleanCoordinationTask)", "RemoveRetiredRuntimeTask('clean')")
    callback = callback.replace("RemoveRetiredRuntimeTask(UniversalRuntimeTask)", "RemoveRetiredRuntimeTask('universal')")
    helper = ROOT / "01.APP/nodelang/host_addin_retarget.py"
    shipped = tmp_path / "payload"
    shipped.mkdir()
    for name in ("nodelang/current.py", "app/__init__.py", "bridges/revit/2027/new/RevitMCP.dll"):
        dest = shipped / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((app / name).read_bytes())
    bridge = shipped / "bridges/autocad/2026/new/AcadMCP.dll"
    bridge.parent.mkdir(parents=True)
    bridge.write_bytes(b"new bridge")
    target = shipped / "nodelang/host_addin_retarget.py"
    target.write_bytes(helper.read_bytes())
    (shipped / 'nodelang/legacy_cleanup_identities.json').write_bytes(legacy_inventory.read_bytes())
    (shipped / 'nodelang/log_rotation.py').write_bytes((ROOT / '01.APP/nodelang/log_rotation.py').read_bytes())
    for name, data in {"nodelang/__init__.py": b"", "nodelang/assistant_registration.py": b"",
                       "nodelang/host_broker_installation.py": b"def _read_registration(path): raise RegistrationRefused()\ndef _parse_registration(*args): pass\ndef _same_id(value): return False\nCLASS_NAME=VENDOR_ID=\"court\"\nclass RegistrationRefused(Exception): pass\n",
                       "colleague_setup.py": b"def register_revit_add_ins(root): return []\ndef register_autocad_add_ins(root): return []\n"}.items():
        (shipped / name).write_bytes(data)
    manifest = tmp_path / "source-manifest.tsv"
    rows = [prune.HEADER, "path\tsha256"]
    for path in shipped.rglob('*'):
        if path.is_file() and path.relative_to(shipped).parts[0] in prune.ROOTS:
            rows.append(path.relative_to(shipped).as_posix() + '\t' + hashlib.sha256(path.read_bytes()).hexdigest())
    manifest.write_text('\n'.join(rows) + '\n')
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if fault is True:
        target.write_bytes(b"import sys\nprint('helper stdout', flush=True)\nprint('helper stderr', file=sys.stderr, flush=True)\nraise RuntimeError('forced postinstall failure')\n")
    elif fault == "terminated":
        target.write_bytes(b"import ctypes\nctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), 0xffffffff)\n")
    script = tmp_path / 'production.iss'
    script.write_text(r'''[Setup]
AppName=ArchHub postinstall court
AppVersion=1
DefaultDirName={param:app}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=no
OutputBaseFilename=production-court
[Tasks]
Name: "connectassistants"; Description: "Connect"; Flags: unchecked
[Files]
Source: "{#Source}"; Flags: dontcopy
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "{#Manifest}"; DestDir: "{app}"; DestName: "source-manifest.tsv"; Flags: ignoreversion
[Code]
function FindPython(): String;
begin Result := ExpandConstant('{param:python}'); end;
procedure CloseInstallConnectors(); begin end;
procedure HostFilesInstalled(); begin end;
procedure RemoveRetiredRuntimeTask(Name: String); begin end;
''' + callback + r'''
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  BackupProgress := CreateOutputMarqueeProgressPage('Court', 'Court');
  Result := '';
end;
''', encoding='utf-8')
    result = subprocess.run([str(compiler), '/Q', '/O' + str(tmp_path), '/DBuildId=20261108-0143-37d007e',
        '/DRequirementsSha256=unused', '/DInstalledManifestSha256=' + digest,
        '/DPayload=' + str(shipped), '/DSource=' + str(helper), '/DManifest=' + str(manifest), str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    log = tmp_path / 'production.log'
    if fault == 'outside':
        monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'other-profile'))
    with _held_open(app / prune.RECEIPT) if fault == 'receipt' else nullcontext():
        done = subprocess.run([str(tmp_path / 'production-court.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/DIR=' + str(app), '/python=' + sys.executable, '/LOG=' + str(log)], timeout=90)
    output = log.read_text(errors='replace')
    print(output)
    if fault in ('outside', 'receipt'):
        assert done.returncode != 0, output
        assert 'Product prune preparation failed' in output
        assert (app / 'BUILD_ID').read_text() == '20261107-2320-37990c4'
        assert before == {name: (app / name).read_bytes() for name in before}
    elif fault is True or fault == "terminated":
        assert done.returncode != 0, output
        assert 'ArchHub Setup refused:' in output
        assert done.returncode == 10
        assert 'Post-install failed' in (app / 'logs/postinstall.log').read_text()
        for captured in (output, (app / 'logs/postinstall.log').read_text()):
            assert 'Product prune starting:' in captured
            assert ('Product prune exited 1' if fault is True else 'Product prune exited -1') in captured
            if fault is True:
                assert 'helper stdout' in captured
                assert 'helper stderr' in captured
                assert 'Traceback (most recent call last)' in captured
                assert "RuntimeError: forced postinstall failure" in captured
        assert (app / 'BUILD_ID').read_text() == '20261107-2320-37990c4'
    else:
        assert done.returncode == 0, output
        assert (app / 'BUILD_ID').read_text() == '20261108-0143-37d007e', output
        state = json.loads((app / prune.RECEIPT).read_text())
        assert state['manifest'].encode() == manifest.read_bytes()
        assert 'bridges/autocad/2026' in state['bridge_years']
        assert all(not (app / name).exists() for name in orphans)
        assert before == {name: (app / name).read_bytes() for name in before}
        if fault == 'legacy':
            assert all(not (app / name).exists() for name in prune.LEGACY_DIRS)
            assert all(not (app / 'Revit' / year).exists() for year in ('2020', '2023', '2024', '2025'))
            from nodelang.log_rotation import LOG_KEEP
            assert sorted(path.name for path in (app / 'logs/root').glob('*.log')) == [
                f'candidate-{i:02}.log' for i in range(92 - LOG_KEEP, 92)]
            for captured in (output, (app / 'logs/postinstall.log').read_text()):
                assert all(name + '/README.md' in captured for name in prune.LEGACY_DIRS)
