import hashlib
import json
import os
import shutil
import subprocess

import pytest

from nodelang import session_link_config as slc

# The 2026-09-22 activation's single-quoted shape: a re-render must read it.
LOADER = (
    "import {tool} from '@opencode-ai/plugin/tool';\n"
    "import {createOpenCodeGovernance} from '%(uri)s?revision=%(rev)s';\n"
    "export const ArchHubGovernance = createOpenCodeGovernance({\n"
    " workToolFactory:tool,\n"
    " sessionLink:{node:'%(node)s',stateDirectory:'C:/old/handoff',connections:{'ses_A1':['aaaaaaaaaaaaaaaa'],'ses_B2':['bbbbbbbbbbbbbbbb']}},\n"
    " expectedSessions:{'ses_A1':'app:agent-session:runtime:%(a)s','ses_B2':'app:agent-session:runtime:%(b)s'},\n"
    " selectedWorks:{'ses_A1':'assembly-instance:%(a)s','ses_B2':'assembly-instance:%(b)s'},\n"
    " gateCommand:'C:/py/python.exe',\n"
    " gateArgs:['C:/gov/hooks/opencode_native_gate.py'],\n"
    "});\n")


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "ArchHub"
    (root / "nodelang" / "session_link").mkdir(parents=True)
    (root / "runtime").mkdir()
    (root / "runtime" / "node.exe").write_bytes(b"node")
    module = root / "nodelang" / "session_link" / "opencode-governance.mjs"
    module.write_bytes(b"export const x=1;\n")
    values = {"uri": module.as_uri(), "rev": hashlib.sha256(module.read_bytes()).hexdigest(),
              "node": str(root / "runtime" / "node.exe").replace("\\", "/"),
              "a": "a" * 32, "b": "b" * 32}
    return root, LOADER % values


def _record(folder, connection, suffix, text):
    (folder / "connections").mkdir(parents=True, exist_ok=True)
    (folder / "connections" / (connection + suffix)).write_text(text)


def test_state_dir_follows_the_application(tmp_path):
    assert slc.app_state_dir({"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "ArchHub-Test" / "session-link"
    assert slc.app_state_dir({"LOCALAPPDATA": "x", "ARCHHUB_TEST_STATE_DIR": str(tmp_path)}) == tmp_path / "session-link"
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.app_state_dir({})


def test_migration_keeps_ids_never_overwrites_or_deletes(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "new"
    a = "a" * 16
    _record(src, a, ".binding.json", '{"id":"%s"}' % a)
    _record(src, a, ".runtime.json", json.dumps({"pid": 0}))
    (src / "connections" / "notes.txt").write_text("ignored")
    receipt = slc.migrate_connections(src, dst)
    assert receipt["copied"] == [a + ".binding.json", a + ".runtime.json"]
    assert receipt["conflicts"] == {}
    assert not (dst / "connections" / "notes.txt").exists()
    assert (src / "connections" / (a + ".binding.json")).exists()
    again = slc.migrate_connections(src, dst)
    assert again["copied"] == [] and len(again["identical"]) == 2
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.migrate_connections(src, src)


def test_migration_moves_a_connection_whole_or_not_at_all(tmp_path):
    # Court: one differing file skips EVERY file of that connection; others still move.
    src, dst = tmp_path / "old", tmp_path / "new"
    b, c = "b" * 16, "c" * 16
    _record(src, b, ".binding.json", "theirs")
    _record(src, b, ".runtime.json", json.dumps({"pid": 0}))
    _record(src, b, ".events.jsonl", "history")
    _record(dst, b, ".binding.json", "ours")
    _record(src, c, ".binding.json", "clean")
    receipt = slc.migrate_connections(src, dst)
    assert receipt["conflicts"] == {b: [b + ".binding.json"]}
    assert not (dst / "connections" / (b + ".runtime.json")).exists()
    assert not (dst / "connections" / (b + ".events.jsonl")).exists()
    assert (dst / "connections" / (b + ".binding.json")).read_text() == "ours"
    assert receipt["copied"] == [c + ".binding.json"]


def test_migration_refuses_a_live_owner(tmp_path):
    src = tmp_path / "old"
    _record(src, "d" * 16, ".runtime.json", json.dumps({"pid": os.getpid()}))
    with pytest.raises(slc.SessionLinkConfigRefused, match="live"):
        slc.migrate_connections(src, tmp_path / "new")


def test_skill_names_only_the_installed_entry_and_app_state(tmp_path):
    state = tmp_path / "ArchHub-Test" / "session-link"
    text = slc.render_skill(tmp_path / "ArchHub", state)
    entry = str(tmp_path / "ArchHub" / "nodelang" / "session_link" / "session-link.ps1")
    assert text.count("& '%s' --state-dir '%s' " % (entry, state)) == 7
    assert "70.HANDOFFS" not in text and "{{" not in text


def test_shipped_skill_makes_no_machine_specific_claim():
    text = slc.SKILL_TEMPLATE.read_text(encoding="utf-8").lower()
    for claim in ("this machine", "this computer", "fargaly", "not detected"):
        assert claim not in text


def test_governance_rerender_keeps_identities_and_moves_only_the_state(install, tmp_path):
    root, loader = install
    state = tmp_path / "state" / "session-link"
    before = slc.spec_from_loader(loader)
    out = slc.render_governance_loader(before, install_root=root, state_dir=state)
    assert slc.spec_from_loader(out) == before
    assert json.dumps(str(state).replace("\\", "/")) in out and "C:/old/handoff" not in out
    # Values are JSON literals, and a re-render of the render is stable.
    assert out == slc.render_governance_loader(slc.spec_from_loader(out), install_root=root, state_dir=state)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_governance_loader_is_valid_javascript(install, tmp_path):
    root, loader = install
    out = slc.render_governance_loader(slc.spec_from_loader(loader), install_root=root,
                                       state_dir=tmp_path / "session-link")
    module = tmp_path / "loader.mjs"
    module.write_text(out, encoding="utf-8")
    assert subprocess.run([shutil.which("node"), "--check", str(module)], capture_output=True).returncode == 0


def test_governance_refuses_unsafe_or_incomplete_identity(install, tmp_path):
    root, loader = install
    spec = slc.spec_from_loader(loader)
    spec["gateArgs"] = ["x'); evil('"]
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.render_governance_loader(spec, install_root=root, state_dir=tmp_path)
    spec = slc.spec_from_loader(loader)
    spec["gateCommand"] = 'C:/py/python.exe","x'
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.render_governance_loader(spec, install_root=root, state_dir=tmp_path)
    spec = slc.spec_from_loader(loader)
    del spec["connections"]["ses_B2"]
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.render_governance_loader(spec, install_root=root, state_dir=tmp_path)


def test_write_keeps_a_backup_and_line_endings(tmp_path):
    target, backups = tmp_path / "SKILL.md", tmp_path / "backups"
    backups.mkdir()
    target.write_bytes(b"old\r\n")
    result = slc.write_with_backup(target, "new\nline\n", backups)
    assert target.read_bytes() == b"new\r\nline\r\n"
    assert (backups / os.path.basename(result["backup"])).read_bytes() == b"old\r\n"
    assert slc.write_with_backup(target, "new\nline\n", backups)["changed"] is False


def test_governance_lane_folders_render_round_trip_and_refuse_unsafe(install, tmp_path):
    root, loader = install
    state = tmp_path / "session-link"
    spec = slc.spec_from_loader(loader)
    assert "laneFolders" not in spec  # an existing loader re-renders byte-identically
    plain = slc.render_governance_loader(spec, install_root=root, state_dir=state)
    assert "laneFolders" not in plain
    lane = "C:/Users/someone/00.ARCHUB/70.HANDOFFS/repair/work/opencode-canvas"
    spec["laneFolders"] = {"ses_A1": lane}
    out = slc.render_governance_loader(spec, install_root=root, state_dir=state)
    assert slc.spec_from_loader(out)["laneFolders"] == {"ses_A1": lane}
    for bad in ("C:/Users/someone/10.PRODUCT/13.NODE-LANGUAGE", "relative/70.HANDOFFS/r/work/l",
                "C:/Users/someone/70.HANDOFFS/r/work/l','evil"):
        with pytest.raises(slc.SessionLinkConfigRefused):
            slc.render_governance_loader({**spec, "laneFolders": {"ses_A1": bad}}, install_root=root, state_dir=state)
    with pytest.raises(slc.SessionLinkConfigRefused):
        slc.render_governance_loader({**spec, "laneFolders": {"ses_Z9": lane}}, install_root=root, state_dir=state)
