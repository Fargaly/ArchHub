"""Real authenticated package actions and journal reopen; no imported code runs."""
import base64
import io
import json
import shutil
import zipfile
from types import SimpleNamespace

import pytest

from nodelang import commit_intent, universal_pipeline
from nodelang.universal_cell import InvalidCell
from tests_replica import test_approval_actions as support


@pytest.fixture(scope="module")
def hostskills(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setattr(universal_pipeline, "seed_engine_library", lambda *args: 0)
    directory = tmp_path_factory.mktemp("HOSTSKILLS")
    fixture = support.approvals.__wrapped__(directory, patch,
        SimpleNamespace(node=SimpleNamespace(name="hostskills_durable")))
    surface = next(fixture)
    try:
        yield surface
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        patch.undo()
        shutil.rmtree(directory)
        assert not directory.exists()


def skill(surface, name):
    return surface.call("importHostSkill", {"host":"Revit", "name":name,
        "text":"---\nname: " + name + "\ndescription: Check dimensions\nlicense: MIT\n---\nCheck dimensions without editing the source."})


def bundle(surface, name):
    manifest = {"manifest_version":"0.3", "name":name, "version":"1.0.0",
        "description":"Local fixture", "author":{"name":"Fixture"}, "license":"MIT",
        "server":{"type":"python", "entry_point":"SERVER/main.py",
                  "mcp_config":{"command":"python", "args":["${__dirname}/SERVER/main.py"]}},
        "tools":[{"name":"measure", "description":"Read measurement"}],
        "user_config":{"precision":{"type":"number", "default":2, "min":0, "max":6},
                       "units":{"type":"string", "default":"mm", "enum":["mm","m"]},
                       "enabled":{"type":"boolean", "default":True}}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("SERVER/main.py", "raise RuntimeError('Fixture scripts must never run')\n")
    return surface.call("inspectConnectorBundle", {"name":name+".mcpb",
        "base64":base64.b64encode(stream.getvalue()).decode()})


def reopen(surface):
    before = surface.call("readHostSkills")
    surface.server.close()
    surface.start()
    after = surface.call("readHostSkills")
    assert after == before
    return after


def test_importHostSkill_pins_inert_content_and_reopens(hostskills):
    row = skill(hostskills, "import-dimensions")
    assert row["enabled"] is False and len(row["digest"]) == 64
    saved = next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])
    assert saved["description"].startswith("Check dimensions")
    assert hostskills.call("listApprovals") == []


def test_inspectConnectorBundle_persists_manifest_assets_operations(hostskills):
    row = bundle(hostskills, "inspect-measure")
    assert row["tools"][0]["name"] == "measure" and row["status"] == "Ready for review"
    assert row["installed"] is False
    assert reopen(hostskills)["connectorBundle"]["digest"] == row["digest"]
    from nodelang.host_skill_owner import HostSkillOwner
    assert "SERVER/main.py" in HostSkillOwner.package_files(hostskills.store.snapshot(), row["id"])


def test_configureConnectorBundle_only_declared_typed_settings_reopen(hostskills):
    row = bundle(hostskills, "configure-measure")
    result = hostskills.call("configureConnectorBundle", row["id"], "precision", 4)
    assert next(r for r in result["config"] if r["key"] == "precision")["value"] == 4
    assert reopen(hostskills)["connectorBundle"]["config"] == result["config"]
    for key, value in [("precision", True), ("precision", 99), ("unknown", "value"), ("units", "bad")]:
        with pytest.raises(InvalidCell):
            hostskills.call("configureConnectorBundle", row["id"], key, value)


def test_installConnectorBundle_exactly_one_approval_and_persistent_graph_effect(hostskills):
    row = bundle(hostskills, "install-measure")
    card = hostskills.call("installConnectorBundle", row["id"])
    assert card["approvalKind"] == "hostskills" and card["status"] == "pending"
    reviewed = json.loads(card["rows"][0]["after"])
    assert reviewed["audit"]["digest"] == row["digest"]
    assert reviewed["audit"]["scripts"] == ["SERVER/main.py"]
    assert hostskills.call("installConnectorBundle", row["id"])["id"] == card["id"]
    assert not hostskills.call("readHostSkills")["connectorBundle"]["installed"]
    reopen(hostskills)
    result = hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    assert result["status"] == "approved"
    held = reopen(hostskills)["connectorBundle"]
    assert held["installed"] is True and held["activeDigest"] == row["digest"]
    assert held["connected"] is False
    hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    assert len([r for r in hostskills.call("listApprovals") if r["id"] == card["id"]]) == 1


def test_setHostSkillEnabled_approval_controls_reusable_graph_node_and_reopens(hostskills):
    row = skill(hostskills, "enable-dimensions")
    card = hostskills.call("setHostSkillEnabled", row["id"], True)
    assert not next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["enabled"]
    hostskills.call("postponeApproval", card["id"])
    with pytest.raises(InvalidCell):
        hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    hostskills.call("resumeApproval", card["id"])
    hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    assert next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["enabled"]
    from nodelang.canvas_graph_owner import CanvasOwner
    ops = CanvasOwner(hostskills.store, hostskills.registry, hostskills.binding.context)
    assert ops._rows(None, row["id"])["frozen"]["value"] == "false"
    hostskills.call("setHostSkillEnabled", row["id"], False)
    assert not next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["enabled"]
    ops = CanvasOwner(hostskills.store, hostskills.registry, hostskills.binding.context)
    assert ops._rows(None, row["id"])["frozen"]["value"] == "true"


def test_auditHostSkill_records_script_network_license_findings_and_reopens(hostskills):
    row = hostskills.call("importHostSkill", {"host":"Revit", "name":"audit-dimensions",
        "text":"---\nname: audit-dimensions\ndescription: Audit\n---\nUse SCRIPTS/check.py with https://example.test",
        "files":{"SCRIPTS/check.py":"import urllib.request\n# audit only, never executed\n"}})
    audited = hostskills.call("auditHostSkill", row["id"])
    assert audited["scripts"] == ["SCRIPTS/check.py"] and audited["network"] is True
    assert audited["findings"]["license"] == "Unspecified"
    assert audited["findings"]["digest"] == row["digest"]
    assert next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["findings"] == audited["findings"]


def test_changed_settings_after_review_refuses_approved_digest(hostskills):
    row = bundle(hostskills, "stale-measure")
    card = hostskills.call("installConnectorBundle", row["id"])
    hostskills.call("configureConnectorBundle", row["id"], "precision", 5)
    with pytest.raises(InvalidCell, match="changed|digest|stale"):
        hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    assert not reopen(hostskills)["connectorBundle"]["installed"]


def test_hostskill_inputs_refuse_traversal_and_secrets_without_mutation(hostskills):
    before = hostskills.store.revision
    for files in [{"../outside.py":"bad"}, {"C:/outside.py":"bad"}, {".env":"secret"}]:
        with pytest.raises(InvalidCell):
            hostskills.call("importHostSkill", {"host":"Revit", "name":"invalid",
                "text":"---\nname: invalid\ndescription: invalid\n---\nBody", "files":files})
    assert hostskills.store.revision == before


def test_reenable_disabled_skill_requires_fresh_single_approval(hostskills):
    row = skill(hostskills, "review-reenable")
    first = hostskills.call("setHostSkillEnabled", row["id"], True)
    hostskills.call("decideHostSkill", first["id"], first["input_digest"], "approve")
    hostskills.call("setHostSkillEnabled", row["id"], False)
    second = hostskills.call("setHostSkillEnabled", row["id"], True)
    assert second["id"] != first["id"] and second["status"] == "pending"
    assert hostskills.call("setHostSkillEnabled", row["id"], True)["id"] == second["id"]
    assert not next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["enabled"]
    hostskills.call("decideHostSkill", second["id"], second["input_digest"], "approve")
    assert next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["enabled"]


def test_audit_includes_script_filenames_with_spaces(hostskills):
    row = hostskills.call("importHostSkill", {"host":"Revit",
        "text":"---\nname: spaced-script\ndescription: Audit accepted files\n---\nReview included scripts.",
        "files":{"SCRIPTS/check dimensions.py":"raise RuntimeError('must never execute')"}})
    result = hostskills.call("auditHostSkill", row["id"])
    assert result["scripts"] == ["SCRIPTS/check dimensions.py"]
    assert next(r for r in reopen(hostskills)["hostSkills"] if r["id"] == row["id"])["findings"]["scripts"] == result["scripts"]


def test_connector_literal_environment_refused_before_graph_mutation(hostskills):
    manifest = {"manifest_version":"0.3", "name":"literal-env", "version":"1.0.0", "description":"Refuse literal credentials",
        "server":{"type":"python", "entry_point":"SERVER/main.py",
            "mcp_config":{"command":"python", "args":["SERVER/main.py"], "env":{"API_KEY":"fixture-not-a-real-key"}}}}
    raw = json.dumps({"manifest":manifest, "files":{"SERVER/main.py":"raise RuntimeError('never run')"}}).encode()
    before = hostskills.store.revision
    with pytest.raises(InvalidCell):
        hostskills.call("inspectConnectorBundle", {"name":"literal-env.json", "base64":base64.b64encode(raw).decode()})
    assert hostskills.store.revision == before


@pytest.mark.parametrize("kind", ["skill", "connector"])
def test_approved_package_outputs_exact_persisted_descriptor_via_graph_runner(hostskills, kind):
    from nodelang.host_skill_owner import HostSkillOwner
    row = skill(hostskills, "review-output-skill") if kind == "skill" else bundle(hostskills, "review-output-connector")
    action = "setHostSkillEnabled" if kind == "skill" else "installConnectorBundle"
    card = hostskills.call(action, row["id"], True) if kind == "skill" else hostskills.call(action, row["id"])
    hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    reopened = reopen(hostskills)
    files = HostSkillOwner.package_files(hostskills.store.snapshot(), row["id"])
    with commit_intent.declare(commit_intent.USER_ACTION, actor=hostskills.binding.subject_root, reason="review approved inert graph descriptor"):
        result = universal_pipeline.run_universal_pipeline(hostskills.store, hostskills.registry,
            effect_engines={}, authentication_context=hostskills.binding.context, only_roots=[row["id"]])
    assert result["ran"] == 1 and not result["pending"]
    value = result["outputs"][row["id"]]["value"]
    if kind == "skill":
        assert value == files["SKILL.md"]
    else:
        manifest = json.loads(files["manifest.json"])
        settings = {r["key"]:r["value"] for r in reopened["connectorBundle"]["config"]}
        assert json.loads(value) == {"server":manifest["server"], "tools":manifest["tools"], "settings":settings, "digest":row["digest"]}
        assert "Fixture scripts must never run" in files["SERVER/main.py"]


@pytest.mark.parametrize("kind", ["skill", "connector"])
def test_deactivation_clears_descriptor_even_for_direct_graph_runner(hostskills, kind):
    row = skill(hostskills, "review-disable-output") if kind == "skill" else bundle(hostskills, "review-configure-output")
    card = hostskills.call("setHostSkillEnabled", row["id"], True) if kind == "skill" else hostskills.call("installConnectorBundle", row["id"])
    hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    if kind == "skill":
        hostskills.call("setHostSkillEnabled", row["id"], False)
    else:
        hostskills.call("configureConnectorBundle", row["id"], "precision", 5)
    reopen(hostskills)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=hostskills.binding.subject_root, reason="review deactivated package has no executable descriptor"):
        result = universal_pipeline.run_universal_pipeline(hostskills.store, hostskills.registry,
            effect_engines={}, authentication_context=hostskills.binding.context, only_roots=[row["id"]])
    assert result["ran"] == 1 and not result["pending"]
    assert result["outputs"][row["id"]]["value"] == ""


def test_changed_package_after_approval_refuses_reusing_approved_digest(hostskills):
    from nodelang.universal_cell import Cell
    row = bundle(hostskills, "review-tamper-approved")
    card = hostskills.call("installConnectorBundle", row["id"])
    hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    snapshot = hostskills.store.snapshot()
    cell = snapshot.cells[row["id"] + ":host-package"]
    record = json.loads(cell.atom)
    record["package"]["files"]["SERVER/main.py"] += "# fixture content changed after approval\n"
    changed = Cell(cell.id, cell.link0, cell.link1, json.dumps(record).encode())
    with commit_intent.declare(commit_intent.USER_ACTION, actor=hostskills.binding.subject_root, reason="review fixture simulates changed approved content"):
        hostskills.store.commit(snapshot.revision, replace=(changed,))
    assert next(r for r in hostskills.call("listApprovals") if r["id"] == card["id"])["status"] == "stale"
    with pytest.raises(InvalidCell, match="changed|digest|stale"):
        hostskills.call("decideHostSkill", card["id"], card["input_digest"], "approve")
    assert next(r for r in reopen(hostskills)["connectorBundles"] if r["id"] == row["id"])["digest"] == row["digest"]


def test_skill_yaml_aliases_refused_before_graph_mutation(hostskills):
    before = hostskills.store.revision
    with pytest.raises(InvalidCell):
        hostskills.call("importHostSkill", {"host":"Revit", "text":
            "---\nname: alias-fixture\ndescription: Reject alias expansion\nmetadata:\n  base: &base [one, two]\n  expanded: [*base, *base]\n---\nBounded instructions."})
    assert hostskills.store.revision == before
