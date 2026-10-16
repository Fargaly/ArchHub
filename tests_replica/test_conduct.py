"""Stage 1 courts exercise the real compiler with no physical effects."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from tools.pipeline import strict_check

ROOT = Path(__file__).resolve().parents[1]


def test_every_actionable_founder_row_has_narrow_scope():
    registry = json.loads((ROOT / "evidence/acompiler-intents.json").read_text(encoding="utf-8"))["intents"]
    expected = set()
    for line in (ROOT / "inputs/DELIVERY-STATUS.md").read_text(encoding="utf-8-sig").splitlines():
        if not re.match(r"^\| F\d+ \|", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not re.match(r"^(INSTALLED|DONE|HELD|RULE|STUDY DONE|SUPERSEDED|SKIPPED)", cells[-1]) or "needs" in cells[-1]:
            expected.add(cells[0])
    assert expected <= registry.keys(), sorted(expected - registry.keys())
    for row in expected:
        entry = registry[row]
        assert entry["source"].endswith(f"DELIVERY-STATUS.md#{row}")
        assert entry["scope_basis"]
        assert entry["scope"]
        for scope in entry["scope"]:
            assert "*" not in scope and scope not in {"/", "./", "nodelang/", "tools/", "tests_replica/"}, (row, scope)
        assert "READ-PROOF.md" in entry["scope"], row
        assert any(scope.startswith("tests") for scope in entry["scope"]), row
    print(f"INTENT REGISTRY PASS: {len(expected)} actionable rows; no wildcard scope")


def test_each_rule_through_real_binary(tmp_path):
    binary = os.environ["ACOMPILER_REAL_BINARY"]
    fixtures = json.loads((ROOT / "tools/archhub-compiler/tests/fixtures/conduct.json").read_text())
    for fixture in fixtures:
        for color, refused in [("red", True), ("green", False)]:
            context = {"author":"court", "intent":"ACOMPILER2B", "files":["tools/archhub-compiler/worker.py"], "conduct_events":[fixture[color]]}
            report = strict_check.check_conduct(ROOT, context, compiler_command=[binary])
            hits = [d for d in report["diagnostics"] if fixture["rule"] in d["message"]]
            assert bool(hits) == refused, (fixture["rule"], color, report)
            assert report["ok"] == (not refused), (fixture["rule"], color, report)
    print("CONDUCT BINARY PASS: six RED/GREEN pairs")


def test_hook_and_commit_use_same_event_admission(tmp_path):
    binary = os.environ["ACOMPILER_REAL_BINARY"]
    context = {"author":"court", "intent":"ACOMPILER2B", "files":["tools/archhub-compiler/worker.py"], "conduct_events":[{"kind":"lane_result", "done":False}]}
    report = strict_check.check_conduct(ROOT, context, compiler_command=[binary])
    assert any("R102" in d["message"] for d in report["diagnostics"])
    context["conduct_events"] = [{"kind":"unknown"}]
    assert not strict_check.check_conduct(ROOT, context, compiler_command=[binary])["ok"]
    context.pop("conduct_events")
    with pytest.raises(strict_check.CompilerFailure):
        strict_check.check_conduct(ROOT, context, compiler_command=[binary])


def make_project(root):
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "court")
    git("config", "user.email", "court@example.invalid")
    (root / "evidence").mkdir()
    (root / "old.py").write_text("print('ready')\n")
    (root / "tasks.json").write_text(json.dumps({"owner":"codex","next_task":"continue","tasks":[{"state":"ACTIVE"}]}))
    (root / "evidence/acompiler-intents.json").write_text(json.dumps({"schema_version":1,"intents":{"F76":{"source":"court","scope":["old.py","tasks.json","RESULT-COURT.md","summary.founder.md"]}}}))
    git("add", ".")
    git("commit", "-qm", "court policy")
    return git


def test_owned_result_and_founder_report_are_inferred(tmp_path):
    project = tmp_path / "project"
    make_project(project)
    binary = [os.environ["ACOMPILER_REAL_BINARY"]]
    context = {"intent":"F76","author":"court"}
    def check(path, content):
        (project / path).write_text(content)
        return strict_check.check_files(project, [path], context=context, compiler_command=binary)
    assert check("RESULT-COURT.md", "State: ACTIVE\n")['ok']
    (project / "tasks.json").write_text('{}')
    # Unselected working ledger cannot grant continuation authority.
    assert check("RESULT-COURT.md", "State: ACTIVE\n")['ok']
    assert not check("summary.founder.md", "Ratchet queued tomorrow")['ok']
    assert check("summary.founder.md", "The settings details are saved.")['ok']
    assert not strict_check.check_files(project, ["old.py"], {"old.py":"print('next')\n"},
        context={**context,"conduct_events":[{"kind":"lane_result","done":False}]}, compiler_command=binary)['ok']


def test_must_pass_cannot_be_shrunk_by_pending_manifest_or_event(tmp_path):
    project = tmp_path / "project"
    git = make_project(project)
    manifest = project / "evidence/must_pass.json"
    manifest.write_text(json.dumps({"schema_version":1,"must_pass":["released-case"]}))
    git("add", ".")
    git("commit", "-qm", "release requirement")
    rules = json.loads((ROOT / "tools/archhub-compiler/rules.json").read_text())
    floor = rules["machine_rules"]["conduct"]["R110"]["must_pass"]
    event = {"kind":"regression","must_pass":[],"results":{case:"pass" for case in floor}}
    c = {"intent":"F76","author":"court","files":["old.py"],"conduct_events":[event]}
    binary = [os.environ["ACOMPILER_REAL_BINARY"]]
    assert not strict_check.check_conduct(project,c,compiler_command=binary)['ok']
    manifest.write_text(json.dumps({"schema_version":1,"must_pass":[]}))
    assert not strict_check.check_conduct(project,c,compiler_command=binary)['ok']
    event['results']['released-case']='pass'
    report = strict_check.check_conduct(project,c,compiler_command=binary)
    assert report['ok'], report['diagnostics']
    c['machine_rule_parameters'] = rules['machine_rules']
    assert strict_check.check_conduct(project,c,compiler_command=binary)['ok']
    manifest.write_text(json.dumps({"schema_version":1,"must_pass":["released-case"]}))
    git("rm", "evidence/acompiler-intents.json")
    git("commit", "-qam", "manifest without registry")
    del event['results']['released-case']
    c.update(intent="ACOMPILER2B",files=["tools/archhub-compiler/worker.py"])
    report = strict_check.check_conduct(project,c,compiler_command=binary)
    assert any("R110" in d['message'] for d in report['diagnostics'])


def test_governance_patch_applies_and_adapter_uses_real_pass(tmp_path, monkeypatch):
    import importlib.util
    import shutil
    isolated = ROOT / "tmp-base"
    assert not isolated.exists()
    try:
        target = isolated / "00.GOVERNANCE/hooks"
        target.mkdir(parents=True)
        source = Path("C:/Users/fargaly/00.ARCHUB/00.GOVERNANCE/hooks")
        for name in ["agent_stop_gate.py", "pretooluse_validate.py"]:
            shutil.copyfile(source / name, target / name)
        patch = ROOT / "evidence/conduct-governance.patch"
        for args in [["--check"], []]:
            result = subprocess.run(["git", "apply", *args, "--directory=tmp-base", str(patch)], cwd=ROOT, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        spec = importlib.util.spec_from_file_location("conduct_gate_court", target / "conduct_gate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = tmp_path / "project"
        make_project(project)
        context_path = tmp_path / "context.json"
        context_path.write_text(json.dumps({"session_id":"court-session","root":str(project),"intent":"F76","author":"court","files":["old.py"]}))
        monkeypatch.setenv("ARCHHUB_INTENT_CONTEXT",str(context_path))
        monkeypatch.setenv("ARCHHUB_CONDUCT_RUNTIME_ROOT",str(ROOT))
        monkeypatch.setattr(strict_check,"verify_runtime",lambda *_: Path(os.environ["ACOMPILER_REAL_BINARY"]))
        monkeypatch.setattr(module,"_snapshot_path",lambda session, call: tmp_path / ("before-" + call + ".json"))
        event = {"session_id":"court-session","tool_use_id":"A","tool_name":"computer_click","tool_input":{}}
        monkeypatch.setattr(module,"_presence",lambda: {"state":"active","age_seconds":0})
        with pytest.raises(RuntimeError):
            module.pre_tool(event)
        with pytest.raises(RuntimeError):
            module.pre_tool({**event,"tool_name":"Bash","tool_input":{"command":"python -c \"import subprocess; subprocess.run(['cargo','test'])\""}})
        monkeypatch.setattr(module,"_presence",lambda: {"state":"away","age_seconds":0})
        module.pre_tool(event)
        (project / "old.py").write_text("print('shell edit')\n")
        assert module.post_tool(event) == [str((project / "old.py").resolve())]
        second = {**event,"tool_use_id":"B"}
        module.pre_tool(event)
        module.pre_tool(second)
        with pytest.raises(FileExistsError):
            module.pre_tool(second)
        (project / "old.py").write_text("print('first parallel edit')\n")
        assert module.post_tool(event) == [str((project / "old.py").resolve())]
        (project / "old.py").write_text("print('second parallel edit')\n")
        assert module.post_tool(second) == [str((project / "old.py").resolve())]
        (project / "tasks.json").write_text(json.dumps({"tasks":[{"state":"ACTIVE"}]}))
        assert module.stop(event,[project / "old.py"]) == 2
        (project / "tasks.json").write_text(json.dumps({"owner":"codex","next_task":"finish","tasks":[{"state":"ACTIVE"}]}))
        assert module.stop(event,[project / "old.py"]) == 0
        with pytest.raises(RuntimeError):
            module.pre_tool({"session_id":"court-session","tool_name":"AskUserQuestion","tool_input":{"questions":["Which port?"]}})
        assert module.stop({**event,"last_assistant_message":"Ratchet queued tomorrow"},[project / "old.py"]) == 2
        assert module.stop({**event,"last_assistant_message":"Which port should I use?"},[project / "old.py"]) == 2
        executed = []
        monkeypatch.setattr(module,"_execute",lambda *args: executed.append(args) or 0)
        monkeypatch.setattr(module,"_presence",lambda: {"state":"active","age_seconds":0})
        assert module.queued_checks("court-session",str(project),str(tmp_path / "record.txt")) == 2
        assert executed == []
    finally:
        assert isolated.resolve().parent == ROOT.resolve() and isolated.name == "tmp-base"
        shutil.rmtree(isolated)


def test_global_wildcard_authority_is_refused(tmp_path):
    project = tmp_path / "project"
    git = make_project(project)
    registry = project / "evidence/acompiler-intents.json"
    data = json.loads(registry.read_text())
    data["intents"]["F76"]["scope"] = ["*"]
    registry.write_text(json.dumps(data))
    git("add", ".")
    git("commit", "-qm", "invalid broad scope")
    with pytest.raises(strict_check.CompilerFailure):
        strict_check.check_conduct(project,{"author":"court","intent":"F76","files":["old.py"],"conduct_events":[{"kind":"operation","effect":"read"}]},compiler_command=[os.environ["ACOMPILER_REAL_BINARY"]])
