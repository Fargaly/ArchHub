"""Behavioural installer prune/receipt courts; every target is a temporary install tree."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from nodelang import host_addin_retarget as prune
from nodelang import host_addin_retarget as retarget
from nodelang.host_broker_installation import ADDIN_ID, CLASS_NAME, VENDOR_ID

ROOT = Path(__file__).resolve().parents[2]


def _manifest(root):
    rows = [prune.HEADER, "path\tsha256"]
    for name in ("nodelang/current.py", "app/__init__.py", "bridges/revit/2027/new/RevitMCP.dll"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"current build\n")
        rows.append(name + "\t" + hashlib.sha256(path.read_bytes()).hexdigest())
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
    for name in orphans + protected:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    before = {name: (root / name).read_bytes() for name in protected}
    return digest, orphans, before


def test_fake_install_prunes_all_product_roots_and_preserves_state(tmp_path):
    digest, orphans, before = _seed(tmp_path)
    assert set(prune.prune(tmp_path, digest)) == set(orphans)
    assert all(not (tmp_path / name).exists() for name in orphans)
    assert before == {name: (tmp_path / name).read_bytes() for name in before}
    assert prune.prune(tmp_path, digest) == []


def test_bad_manifest_or_copy_aborts_before_any_delete(tmp_path):
    digest, orphans, _ = _seed(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        prune.prune(tmp_path, "0" * 64)
    (tmp_path / "nodelang/current.py").write_bytes(b"wrong copy")
    with pytest.raises(ValueError, match="differs"):
        prune.prune(tmp_path, digest)
    assert all((tmp_path / name).exists() for name in orphans)


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
    assert not (app / "Revit/2027").exists()
    assert (app / "Revit/2024/RevitMCP.dll").read_bytes() == b"old"
    for root in roots:
        assert not list(root.glob("*/*.tmp"))
        assert not list(root.glob("*/ArchHub.addin.retired"))
        assert len(list(root.glob("*/Foreign.addin.retired"))) == 3
    receipts = [json.loads(line.removeprefix("REVIT FOREIGN RECEIPT ")) for line in capsys.readouterr().out.splitlines()
                if line.startswith("REVIT FOREIGN RECEIPT ")]
    assert len(receipts) == 12
    assert len(foreign) == 6
    assert all(row["unchanged"] and row["before_sha256"] == row["after_sha256"] for row in receipts)


def test_inno_post_copy_runs_the_same_pruner(tmp_path):
    compiler = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
    if not compiler.is_file():
        pytest.skip("Inno Setup is not installed")
    app = tmp_path / "installed"
    app.mkdir()
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
[Code]
procedure CurStepChanged(Step: TSetupStep);
var Code: Integer;
begin
  if Step = ssPostInstall then begin
    if not Exec(ExpandConstant('{param:python}'), '-B "' + ExpandConstant('{app}') + '\\nodelang\\host_addin_retarget.py" --prune "' + ExpandConstant('{app}') + '" {#Digest}', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then RaiseException('could not run prune');
    if Code <> 0 then RaiseException('prune failed');
  end;
end;
''', encoding="utf-8")
    # The copied pruner is itself in this build's manifest.
    helper = ROOT / "01.APP/nodelang/host_addin_retarget.py"
    manifest = app / "source-manifest.tsv"
    manifest.write_text(manifest.read_text() + "nodelang/host_addin_retarget.py\t" + hashlib.sha256(helper.read_bytes()).hexdigest() + "\n")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    build = subprocess.run([str(compiler), "/Q", "/O" + str(tmp_path), "/DSource=" + str(helper), "/DDigest=" + digest, str(script)], capture_output=True, text=True, timeout=90)
    assert build.returncode == 0, build.stdout + build.stderr
    done = subprocess.run([str(tmp_path / "prune-court.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/app=" + str(app), "/python=" + sys.executable, "/LOG=" + str(tmp_path / "install.log")], capture_output=True, timeout=90)
    assert done.returncode == 0, (tmp_path / "install.log").read_text(errors="replace")
    assert all(not (app / name).exists() for name in orphans)
    assert before == {name: (app / name).read_bytes() for name in before}


def test_manifest_covers_generated_studio_and_gated_hosts_only(tmp_path):
    source, hosts = tmp_path / "source", tmp_path / "hosts"
    included = ["nodelang/host_addin_retarget.py", "nodelang/studio/compiled/main.js",
                "app/__init__.py", "app/credential_lock.py", "app/secrets_store.py",
                "bridges/rhino/archhub_mcp.py", "bridges/blender/archhub_mcp/__init__.py",
                "bridges/sources/max_mcp/max_mcp_startup.py"]
    for name in included + ["nodelang/__pycache__/old.pyc", "app/unshipped.py", "nodelang/private.db"]:
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
    assert not any("__pycache__" in name or "unshipped" in name or name.endswith(".db") for name in rows)


def test_pruner_does_not_follow_a_junction(tmp_path):
    digest, _, _ = _seed(tmp_path)
    foreign = tmp_path / "outside"
    foreign.mkdir()
    (foreign / "keep.py").write_bytes(b"foreign")
    link = tmp_path / "nodelang/redirected"
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(foreign)], capture_output=True)
    assert done.returncode == 0, done.stderr
    prune.prune(tmp_path, digest)
    assert (foreign / "keep.py").read_bytes() == b"foreign"
