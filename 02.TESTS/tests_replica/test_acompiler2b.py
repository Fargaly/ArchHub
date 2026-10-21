"""Stage 1b courts use the release compiler and fake physical sinks only."""
import copy
from functools import partial
import json
import os
from pathlib import Path
import subprocess

import pytest

from nodelang.enforce import guarded_write
from tools.pipeline import install_hooks, record_observation, strict_check


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "court-human")
    git(root, "config", "user.email", "court@example.invalid")
    (root / "05.EVIDENCE").mkdir()
    (root / "05.EVIDENCE/acompiler-intents.json").write_text(json.dumps({"schema_version": 1, "intents": {
        "F76": {"source": "DELIVERY-STATUS.md#F76", "scope": ["old.py", "05.EVIDENCE/acompiler-baseline.json", "revit://project-1/", "autocad://project-1/"]}}}), encoding="utf-8")
    (root / "old.py").write_text("print('before')\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "authoritative session scope")
    return root


@pytest.fixture
def compiler():
    binary = Path(os.environ["ACOMPILER_REAL_BINARY"])
    assert binary.is_file(), "build the real release compiler before courts"
    return [str(binary)]


def context(**values):
    return {"intent": "F76", "author": "court-human", **values}


def test_git_blob_batch_reads_exact_bytes_and_missing_paths(project):
    (project / "spaced name.py").write_bytes(b"first\x00second\n")
    git(project, "add", "spaced name.py")
    result = strict_check.git_blobs(project, ["HEAD:old.py", ":spaced name.py", "HEAD:absent.py"])
    assert result == {"HEAD:old.py": b"print('before')\n", ":spaced name.py": b"first\x00second\n",
                      "HEAD:absent.py": None}


@pytest.mark.parametrize("data", [b"oid tree 1\x00x\x00", b"oid blob 50\x00x\x00"])
def test_git_blob_batch_refuses_non_blobs_and_truncated_bytes(project, monkeypatch, data):
    from types import SimpleNamespace
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=data))
    with pytest.raises(strict_check.CompilerFailure):
        strict_check.git_blobs(project, ["HEAD:old.py"])


@pytest.mark.parametrize("introduced,staged_match", [(False, True), (True, True), (False, False)])
@pytest.mark.parametrize("numbered", [False, True])
def test_staged_rename_preserves_only_the_existing_diagnostic(project, monkeypatch, introduced, staged_match, numbered):
    destination = "03.TOOLS/old.py" if numbered else "moved.py"
    if numbered:
        (project / "old.py").write_text("print('before')\n" + "# original path details\n" * 30, encoding="utf-8")
        git(project, "add", "old.py")
        git(project, "commit", "-qm", "baseline source")
        (project / "03.TOOLS").mkdir()
    git(project, "mv", "old.py", destination)
    source = (project / destination).read_text(encoding="utf-8")
    if numbered:
        source = source.replace("# original path details", "# numbered source locations")
    if introduced:
        source += "print('new defect')\n"
    (project / destination).write_text(source, encoding="utf-8")
    git(project, "add", destination)
    pending = source if staged_match else source + "print('not staged')\n"

    def scan(root, *, overlay=None, **kwargs):
        path = destination if overlay else "old.py"
        diagnostics = [{"code": "E0004", "language": "python", "file": path,
                        "line": 1, "column": 1, "message": "existing defect", "help": "repair it"}]
        if overlay and introduced:
            diagnostics.append({**diagnostics[0], "line": 2, "message": "new defect"})
        return {"diagnostics": diagnostics, "counts": {"E0004": {"python": len(diagnostics)}},
                "files": [{"file": path, "language": "python"}]}

    monkeypatch.setattr(strict_check, "scan_model", scan)
    result = strict_check.check_files(project, ["old.py", destination],
                                     {"old.py": None, destination: pending}, context=context())
    assert result["ok"] is (not introduced and staged_match), result
    assert result["context"]["metrics"]["tests_removed"] == 0


def test_intent_and_scope_real_binary_red_green(project, compiler, monkeypatch):
    calls = []
    original = subprocess.run
    def observe(command, **options):
        calls.append(list(command))
        assert not any(Path(str(arg)).name.lower() in {"ruff", "ruff.exe", "pyright", "pyright.exe", "tsc", "tsc.exe"} for arg in command)
        return original(command, **options)
    monkeypatch.setattr(subprocess, "run", observe)
    options = {"compiler_command": compiler}
    no_intent = strict_check.check_files(project, ["old.py"], {"old.py": "print('after')\n"}, context={"author": "court-human"}, **options)
    assert any(row["code"] == "E0100" for row in no_intent["diagnostics"])
    good = strict_check.check_files(project, ["old.py"], {"old.py": "print('after')\n"}, context=context(), **options)
    assert good["ok"], good
    bad = strict_check.check_files(project, ["outside.py"], {"outside.py": "print('after')\n"}, context=context(scope=["outside.py"]), **options)
    assert any(row["code"] == "E0101" for row in bad["diagnostics"])
    assert not any("ruff" in command or "pyright" in command or "tsc" in command for command in calls)


def test_pending_scope_cannot_authorize_itself(project, compiler):
    registry = json.loads((project / "05.EVIDENCE/acompiler-intents.json").read_text())
    registry["intents"]["F76"]["scope"].append("outside.py")
    (project / "05.EVIDENCE/acompiler-intents.json").write_text(json.dumps(registry))
    result = strict_check.check_files(project, ["outside.py"], {"outside.py": "print('outside')\n"}, context=context(), compiler_command=compiler)
    assert any(row["code"] == "E0101" for row in result["diagnostics"])


def test_host_target_cannot_use_graph_format_to_skip_firm_standard(project, compiler):
    pending = {"kind": "model", "format": "archhub-graph-v1", "target": "revit://project-1/element/42",
        "content": {"action": "restore_baseline", "subgraph": "s", "baseline": "b"},
        "graph": {"root": "r", "manifest": "m", "records": [{"role": "body", "title": "x", "primitive": "value", "configuration": {}}]}}
    result = strict_check.check_artifact(project, pending, context=context(), compiler_command=compiler)
    assert not result["ok"] and any(row["code"] == "E0010" for row in result["diagnostics"])


def model(program="revit", value=3):
    return {"kind": "model", "format": "host-parameter-edit-v1", "target": program + "://project-1/element/42",
            "host": {"program": program, "document": "project-1", "operation": "set_parameters"},
            "content": {"elements": [{"id": "42", "parameters": {"height": {"type": "number", "value": value}}}]}}


@pytest.mark.parametrize("program", ["revit", "autocad"])
def test_human_host_standard_before_write_and_durable_history(project, compiler, program):
    writes = []
    params = {**context(), "repo_root": str(project), "rules": json.dumps({"model": {
        "value_types": ["number"], "parameters": {"height": {"type": "number", "min": 2, "max": 8}}}})}
    checker = partial(strict_check.check_artifact, compiler_command=compiler)
    def writer(pending):
        writes.append(copy.deepcopy(pending))
        return {"ok": True, "revision": str(len(writes))}
    options = {"params": params, "artifact_compiler": checker, "readback": lambda *_: writes[-1]}
    bad = guarded_write(model(program, 1), writer, **options)
    assert not bad["ok"] and not writes
    missing_format = model(program, 1)
    missing_format.pop("format")
    assert not guarded_write(missing_format, writer, **options)["ok"] and not writes
    good = guarded_write(model(program, 3), writer, **options)
    assert good["ok"], good
    assert len(writes) == 1 and good["content_sha256"] == good["readback_sha256"]
    history = json.loads((project / "05.EVIDENCE/acompiler-baseline.json").read_text())
    assert history["history"][-1]["author"] == "court-human"
    assert history["history"][-1]["metrics"]["files"] == 1
    assert set(history["history"][-1]["metrics"]) == record_observation.METRICS


def test_latest_committed_observation_is_read_before_bookkeeping_commit(project):
    author = "court-human"
    measured = {key: 0 for key in record_observation.METRICS}
    selected = strict_check.selected_files(project)
    observation = {"author": author, "metrics": {key: {} for key in measured}}
    admitted = {"ok": True, "diagnostics": [], "selected": selected,
                "admitted_tree": git(project, "write-tree").decode().strip(),
                "context": {**context(), "files": selected, "metrics": measured}, "observation": observation}
    record_observation.admit(project, admitted)
    record_observation.record(project)
    prepared = strict_check.change_context(project, ["old.py"], {"old.py": "print('next')\n"}, "HEAD", context())
    assert len(prepared["history"]) == 1


def test_human_host_project_needs_no_git_repository(project, compiler, tmp_path):
    root = tmp_path / "host-project"
    (root / "05.EVIDENCE").mkdir(parents=True)
    (root / "05.EVIDENCE/acompiler-intents.json").write_bytes((project / "05.EVIDENCE/acompiler-intents.json").read_bytes())
    checker = partial(strict_check.check_artifact, compiler_command=compiler)
    params = {**context(), "repo_root": str(root), "rules": {"model": {
        "value_types": ["number"], "parameters": {"height": {"type": "number", "min": 2}}}}}
    writes = []
    result = guarded_write(model(), lambda pending: writes.append(copy.deepcopy(pending)),
                           readback=lambda *_: writes[-1], params=params, artifact_compiler=checker)
    assert result["ok"], result
    assert len(strict_check.change_context(project, [], {}, "HEAD", context())["history"]) == 0
    assert len(record_observation.load_history(root)["history"]) == 1


def test_host_action_baseline_then_unexplained_deviation_is_refused(project, compiler):
    checker = partial(strict_check.check_artifact, compiler_command=compiler)
    params = {**context(), "repo_root": str(project), "rules": {"model": {
        "value_types": ["number"], "parameters": {"height": {"type": "number"}}}}}
    writes = []
    options = {"params": params, "artifact_compiler": checker, "readback": lambda *_: writes[-1]}
    def writer(pending):
        writes.append(copy.deepcopy(pending))
        return {"ok": True}
    for _ in range(5):
        result = guarded_write(model(), writer, **options)
        assert result["ok"], result
    expanded = model()
    expanded["content"]["description"] = "\n".join("record" for _ in range(100))
    # More typed parameter edits create a real measured shape deviation.
    expanded["content"]["elements"][0]["parameters"].update({
        "height" + str(index): {"type": "number", "value": index} for index in range(100)})
    params["rules"]["model"]["parameters"].update({"height" + str(index): {"type": "number"} for index in range(100)})
    bad = guarded_write(expanded, writer, **options)
    assert not bad["ok"] and any(row["code"] == "E0200" for row in bad["diagnostics"])
    assert len(writes) == 5
    offered = int(bool(bad["observation"]["notices"]))
    for _ in range(7):
        refused = guarded_write(expanded, writer, **options)
        assert not refused["ok"] and any(row["code"] == "E0200" for row in refused["diagnostics"])
        offered += int(bool(refused["observation"]["notices"]))
    assert offered == 5 and len(writes) == 5
    params["why"] = "Authorized bulk parameter edit after individual calibration."
    good = guarded_write(expanded, writer, **options)
    assert good["ok"] and len(writes) == 6, good


def test_check_only_enforce_does_not_record_effect(project, compiler, monkeypatch):
    from nodelang.enforce import engine
    original = strict_check.check_artifact
    monkeypatch.setattr(strict_check, "check_artifact", partial(original, compiler_command=compiler))
    params = {**context(), "repo_root": str(project), "rules": {"model": {
        "value_types": ["number"], "parameters": {"height": {"type": "number"}}}}}
    result, _ = engine(params, {"pending": model()})
    assert result["ok"], result
    assert record_observation.load_history(project)["history"] == []


def test_applied_receipt_survives_bookkeeping_io_failure(project, compiler, monkeypatch):
    def unavailable(*_):
        raise OSError("observation storage unavailable")
    monkeypatch.setattr(record_observation, "_save_history", unavailable)
    writes = []
    checker = partial(strict_check.check_artifact, compiler_command=compiler)
    params = {**context(), "repo_root": str(project), "rules": {"model": {
        "value_types": ["number"], "parameters": {"height": {"type": "number"}}}}}
    def writer(pending):
        writes.append(copy.deepcopy(pending))
        return {"ok": True, "revision": "applied-once"}
    result = guarded_write(model(), writer, readback=lambda *_: writes[-1], params=params, artifact_compiler=checker)
    assert not result["ok"] and result["effect_applied"] and len(writes) == 1
    assert result["receipt"]["revision"] == "applied-once"
    assert result["bookkeeping_pending"] == "observation storage unavailable"


def test_real_shared_human_commit_hooks_require_intent(project, compiler):
    install_hooks.install(project)
    original = git(project, "rev-parse", "HEAD")
    (project / "old.py").write_text("print('human edit')\n", encoding="utf-8")
    git(project, "add", "old.py")
    bad = subprocess.run(["git", "-C", str(project), "commit", "-qm", "human edit without intent"], capture_output=True, text=True)
    assert bad.returncode != 0 and "E0100" in bad.stdout + bad.stderr
    assert git(project, "rev-parse", "HEAD") == original
    good = subprocess.run(["git", "-C", str(project), "commit", "-qm", "human edit\n\nIntent: F76"], capture_output=True, text=True)
    assert good.returncode == 0, good.stdout + good.stderr
    assert "ACOMPILER COMMIT PASS" in good.stdout + good.stderr
    assert record_observation.load_history(project)["history"][-1]["author"] == "court-human"
    git(project, "add", "05.EVIDENCE/acompiler-baseline.json")
    exported = subprocess.run(["git", "-C", str(project), "commit", "-qm", "record admitted author history\n\nIntent: F76"], capture_output=True, text=True)
    assert exported.returncode == 0, exported.stdout + exported.stderr
