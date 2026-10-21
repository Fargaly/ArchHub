"""Executable transport and attribution courts for ACOMPILER's real callers."""
import json
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import runpy
import tempfile
from types import SimpleNamespace

import pytest

from tools import ratchet
from tools.pipeline import build, install_hooks, package_compiler, pre_commit, record_observation, strict_check


def run_git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def test_numbered_compiler_admission_memory_invalidates_after_rule_change(repository):
    root = repository
    rules = root / "03.TOOLS/tools/archhub-compiler/rules.json"
    rules.parent.mkdir(parents=True)
    rules.write_text('{"rule":"before"}', encoding="utf-8")
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", "numbered compiler")
    before = build.compiler_identity(root)
    assert before != hashlib.sha256().hexdigest()
    rules.write_text('{"rule":"after"}', encoding="utf-8")
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", "changed rule")
    assert build.compiler_identity(root) != before


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "Compiler court")
    run_git(root, "config", "user.email", "court@example.invalid")
    if os.name == "nt":
        run_git(root, "config", "core.longpaths", "true")
    (root / "01.APP/nodelang").mkdir(parents=True)
    (root / "01.APP/nodelang" / "old.py").write_text("old = 'legacy'\n", encoding="utf-8")
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", "base")
    return root


def diagnostic(file="01.APP/nodelang/old.py", code="E0001", language="python"):
    return {"file": file, "code": code, "language": language, "line": 1, "column": 1,
            "message": "duplicate owner", "help": "keep exactly one owner"}


def report(*diagnostics, files=None):
    files = list(files) if files is not None else [{"file": "01.APP/nodelang/old.py", "language": "python"},
                                                  {"file": "01.APP/nodelang/new.py", "language": "python"}]
    for diagnostic_item in diagnostics:
        if not any(item["language"] == diagnostic_item["language"] for item in files):
            files.append({"file": diagnostic_item["file"], "language": diagnostic_item["language"]})
    languages = {item["language"] for item in files}
    counts = {code: {language: 0 for language in languages} for code in strict_check.CODES}
    for item in diagnostics:
        bucket = counts.setdefault(item["code"], {})
        bucket[item["language"]] = bucket.get(item["language"], 0) + 1
    return {"schema_version": 1, "counts": counts, "diagnostics": list(diagnostics), "files": files}


def fake_compiler(tmp_path, payload=None, source=None):
    target = tmp_path / "transport.py"
    target.write_text(source if source is not None else "import json\nprint(" + repr(json.dumps(payload)) + ")\n", encoding="utf-8")
    return [sys.executable, str(target)]


def test_no_owned_change_never_launches_compiler(repository, monkeypatch):
    (repository / "01.APP/nodelang" / "bystander.py").write_text("bad = True\n", encoding="utf-8")
    monkeypatch.setattr(strict_check, "scan_model", lambda *a, **k: pytest.fail("compiler launched without an owned edit"))
    assert strict_check.check_changed(repository) == {"ok": True, "selected": [], "diagnostics": [], "counts": {}}
    assert ratchet.main(["compare", str(repository), "missing.json"]) == 0


def test_staged_files_only_ignore_bystander_diagnostics(repository, tmp_path):
    (repository / "01.APP/nodelang" / "new.py").write_text("new = 'valid'\n", encoding="utf-8")
    run_git(repository, "add", "01.APP/nodelang/new.py")
    # Unstaged legacy errors belong to somebody else.
    (repository / "01.APP/nodelang" / "old.py").write_text("old = 'changed bystander'\n", encoding="utf-8")
    result = strict_check.check_changed(repository, compiler_command=fake_compiler(tmp_path, report(diagnostic())))
    assert result["selected"] == ["01.APP/nodelang/new.py"]
    assert result["ok"] is True
    assert result["counts"]["E0001"] == {"python": 1}


def test_selected_duplicate_refuses_and_fixed_owner_passes(repository, tmp_path):
    (repository / "01.APP/nodelang/old.py").write_text("old = 'changed owner'\n", encoding="utf-8")
    command = fake_compiler(tmp_path, report(diagnostic()))
    assert strict_check.check_files(repository, ["01.APP/nodelang/old.py"], compiler_command=command)["ok"] is False
    command = fake_compiler(tmp_path, report())
    assert strict_check.check_files(repository, ["01.APP/nodelang/old.py"], compiler_command=command)["ok"] is True


def test_session_record_explicitly_scopes_unstaged_files(repository, tmp_path):
    selected = repository / "01.APP/nodelang" / "new.py"
    selected.write_text("new = 'valid'\n", encoding="utf-8")
    record = tmp_path / "session.txt"
    record.write_text(str(selected) + "\n", encoding="utf-8")
    result = strict_check.check_changed(repository, session_record=record,
                                       compiler_command=fake_compiler(tmp_path, report(diagnostic())))
    assert result["selected"] == ["01.APP/nodelang/new.py"] and result["ok"]


def test_outside_record_cannot_expand_agent_scope(repository, tmp_path):
    with pytest.raises(strict_check.CompilerFailure, match="outside compiler root"):
        strict_check.selected_files(repository, files=[tmp_path / "another-agent.py"])


def test_shared_session_record_filters_other_product_roots(repository, tmp_path):
    record = tmp_path / "shared-session.txt"
    record.write_text(str(tmp_path / "other-repo" / "source.py") + "\n" +
                      str(repository / "01.APP/nodelang" / "old.py") + "\n", encoding="utf-8")
    assert strict_check.selected_files(repository, session_record=record) == ["01.APP/nodelang/old.py"]


def test_ambiguous_mixed_scopes_refuse(repository):
    with pytest.raises(strict_check.CompilerFailure, match="choose one scope"):
        strict_check.selected_files(repository, files=[], base="HEAD")


def test_partially_staged_file_refuses_wrong_content(repository, tmp_path):
    selected = repository / "01.APP/nodelang" / "old.py"
    selected.write_text("old = 'staged'\n", encoding="utf-8")
    run_git(repository, "add", "01.APP/nodelang/old.py")
    selected.write_text("old = 'different worktree'\n", encoding="utf-8")
    with pytest.raises(strict_check.CompilerFailure, match="differ from checked revision/index"):
        strict_check.check_changed(repository, compiler_command=fake_compiler(tmp_path, report()))


def test_base_and_commit_are_deterministic(repository):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (repository / "01.APP/nodelang" / "new.py").write_text("new = 'valid'\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "new owner")
    assert strict_check.selected_files(repository, base=base) == ["01.APP/nodelang/new.py"]
    assert strict_check.selected_files(repository, commit="HEAD") == ["01.APP/nodelang/new.py"]
    with pytest.raises(strict_check.CompilerFailure, match="checked-out HEAD"):
        strict_check.selected_files(repository, commit=base)


def test_rename_scope_removes_old_path_and_checks_new_path(repository):
    run_git(repository, "mv", "01.APP/nodelang/old.py", "01.APP/nodelang/renamed.py")
    assert strict_check.selected_files(repository) == ["01.APP/nodelang/old.py", "01.APP/nodelang/renamed.py"]


def test_unknown_language_cannot_disappear_from_scan(repository, tmp_path):
    (repository / "new.unregistered").write_text("execute secret_magic", encoding="utf-8")
    result = strict_check.check_files(repository, ["new.unregistered"], compiler_command=fake_compiler(tmp_path, report()))
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "E0010"


def test_overlay_is_sent_to_executable_and_removed(repository, tmp_path):
    capture = tmp_path / "overlay-path.txt"
    command = fake_compiler(tmp_path, source="import json, pathlib, sys\n"
        f"if '--overlay' not in sys.argv: print({json.dumps(report())!r}); sys.exit(0)\n"
        "overlay_path = pathlib.Path(sys.argv[sys.argv.index('--overlay') + 1])\n"
        f"pathlib.Path({str(capture)!r}).write_text(str(overlay_path), encoding='utf-8')\n"
        "overlay = json.loads(overlay_path.read_text(encoding='utf-8'))\n"
        "assert overlay == {'01.APP/nodelang/new.py': 'route = 1\\n'}\n"
        f"print({json.dumps(report())!r})\n")
    result = strict_check.check_files(repository, ["01.APP/nodelang/new.py"], {"01.APP/nodelang/new.py": "route = 1\n"}, compiler_command=command)
    assert result["ok"]
    assert not Path(capture.read_text(encoding="utf-8")).exists()
    assert not (repository / "01.APP/nodelang/new.py").exists()


def test_overlay_cannot_hide_unowned_existing_owners(repository):
    with pytest.raises(strict_check.CompilerFailure, match="outside the owned change set"):
        strict_check.check_files(repository, [], {"01.APP/nodelang/old.py": ""})


def test_deleted_reader_attributes_cross_file_error_to_owned_change(repository, tmp_path):
    selected = repository / "01.APP/nodelang" / "reader.py"
    selected.write_text("read_timeout()\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "reader")
    selected.write_text("print('reader removed')\n", encoding="utf-8")
    files = [{"file": "01.APP/nodelang/reader.py", "language": "python"},
             {"file": "01.APP/nodelang/catalogue.py", "language": "python"}]
    clean = json.dumps(report(files=files))
    broken = json.dumps(report(diagnostic("01.APP/nodelang/catalogue.py", "E0002"), files=files))
    command = fake_compiler(tmp_path, source="import json, pathlib, sys\n"
        "assert len(sys.argv[sys.argv.index('--revision') + 1]) == 40\n"
        "overlay = json.loads(pathlib.Path(sys.argv[sys.argv.index('--overlay')+1]).read_text()) if '--overlay' in sys.argv else {}\n"
        f"print({broken!r} if overlay and 'read_timeout' not in overlay.get('01.APP/nodelang/reader.py', '') else {clean!r})\n")
    result = strict_check.check_files(repository, ["01.APP/nodelang/reader.py"], compiler_command=command)
    assert result["ok"] is False
    assert result["diagnostics"][0]["file"] == "01.APP/nodelang/catalogue.py"
    assert result["diagnostics"][0]["caused_by"] == ["01.APP/nodelang/reader.py"]


@pytest.mark.parametrize("source,expected", [
    ("print('not JSON')", "invalid JSON"),
    ("import sys; sys.exit(7)", "exited 7"),
    ("print('{}')", "schema_version"),
])
def test_transport_refuses_invalid_results(repository, tmp_path, source, expected):
    with pytest.raises(strict_check.CompilerFailure, match=expected):
        strict_check.scan_model(repository, compiler_command=fake_compiler(tmp_path, source=source))


def test_transport_timeout_refuses(repository, tmp_path):
    with pytest.raises(strict_check.CompilerFailure, match="invocation failed"):
        strict_check.scan_model(repository, compiler_command=fake_compiler(tmp_path, source="import time; time.sleep(10)"), timeout=0.05)


def test_transport_counts_must_match_diagnostics(repository, tmp_path):
    malformed = report(diagnostic())
    malformed["counts"]["E0001"]["python"] = 0
    with pytest.raises(strict_check.CompilerFailure, match="disagree with diagnostics"):
        strict_check.scan_model(repository, compiler_command=fake_compiler(tmp_path, malformed))


def test_transport_cannot_omit_rule_language_coverage(repository, tmp_path):
    malformed = report()
    malformed["counts"]["E0009"] = {}
    with pytest.raises(strict_check.CompilerFailure, match="code/language rule coverage"):
        strict_check.scan_model(repository, compiler_command=fake_compiler(tmp_path, malformed))


def test_change_context_cannot_forge_owned_files_scope_or_history(repository, tmp_path):
    captured = tmp_path / "context.json"
    clean = json.dumps(report())
    missing = json.dumps(report(diagnostic(code="E0100")))
    command = fake_compiler(tmp_path, source="import json, pathlib, sys\n"
        "context = json.loads(pathlib.Path(sys.argv[sys.argv.index('--context')+1]).read_text()) if '--context' in sys.argv else None\n"
        f"if context is not None: pathlib.Path({str(captured)!r}).write_text(json.dumps(context))\n"
        f"print({missing!r} if context is not None and not context.get('intent') else {clean!r})\n")
    assert not strict_check.check_files(repository, ["01.APP/nodelang/old.py"], compiler_command=command)["ok"]
    supplied = {"intent": "ACOMPILER", "files": ["other.py"], "scope": ["**"],
                "history": [{"author": "forged"}], "metrics": {"files": 0}}
    assert strict_check.check_files(repository, ["01.APP/nodelang/old.py"], context=supplied, compiler_command=command)["ok"]
    context = json.loads(captured.read_text())
    assert context["files"] == ["01.APP/nodelang/old.py"] and context["metrics"]["files"] == 1
    assert context["history"] == [] and "scope" not in context


def test_artifact_uses_same_binary_and_accepts_host_target_spans(repository, tmp_path):
    item = diagnostic(file="Wall:42", code="E0009", language="model")
    command = fake_compiler(tmp_path, report(item, files=[{"file": "Wall:42", "language": "model"}]))
    result = strict_check.check_artifact(repository, {"kind": "model", "target": "Wall:42", "content": {}},
                                        {"author": "court", "intent": "ACOMPILER"}, compiler_command=command)
    assert not result["ok"] and result["diagnostics"][0]["file"] == "Wall:42"


def test_no_external_checker_subprocess(repository, tmp_path, monkeypatch):
    original = subprocess.run
    commands = []
    def observed(command, *args, **kwargs):
        commands.append(list(command))
        assert not any(str(part).lower() in ("ruff", "pyright", "tsc", "ruff.exe", "pyright.exe", "tsc.exe") for part in command)
        return original(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", observed)
    assert strict_check.check_files(repository, ["01.APP/nodelang/old.py"], compiler_command=fake_compiler(tmp_path, report()))["ok"]
    assert any("scan" in command for command in commands)


def test_commit_message_enforces_final_intent(repository, tmp_path, monkeypatch):
    missing = {"ok": False, "diagnostics": [diagnostic(code="E0100")]}
    seen = []
    def inspect(root, **kwargs):
        seen.append(kwargs["context"])
        return {"ok": True, "diagnostics": []} if kwargs["context"].get("intent") == "ACOMPILER" else missing
    monkeypatch.setattr(strict_check, "check_changed", inspect)
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("change without trailer\n", encoding="utf-8")
    args = ["--root", str(repository), "--phase", "commit-msg", "--commit-message", str(message)]
    assert pre_commit.main(args) == 1
    message.write_text("change\n\nIntent: ACOMPILER\nWhy: closes the checker bypass\n", encoding="utf-8")
    assert pre_commit.main(args) == 0
    assert seen[-1]["why"] == "closes the checker bypass"


def test_precommit_can_defer_intent_only_to_verified_commit_message_hook(repository, monkeypatch):
    def missing(*args, **kwargs):
        return {"ok": False, "diagnostics": [diagnostic(code="E0100")]}
    monkeypatch.setattr(strict_check, "check_changed", missing)
    args = ["--root", str(repository), "--paired-hook"]
    assert pre_commit.main(args) == 2
    hooks = install_hooks.install(repository)
    assert pre_commit.main(args) == 0
    assert pre_commit.main(["--root", str(repository)]) == 1
    (hooks / "commit-msg").unlink()
    assert pre_commit.main(args) == 2
    monkeypatch.setattr(strict_check, "check_changed", lambda *a, **k: {"ok": True, "diagnostics": []})
    assert pre_commit.main(args) == 0


def test_paired_hooks_preserve_existing_hook_and_refuse_real_git_commit(repository, tmp_path):
    old_marker = tmp_path / "old-hook.txt"
    previous = repository / ".git" / "hooks" / "pre-commit"
    previous.write_text("#!/bin/sh\nprintf old > '" + str(old_marker).replace("\\", "/") + "'\n", encoding="utf-8")
    previous.chmod(0o755)
    marker = tmp_path / "compiler-phases.txt"
    runner = tmp_path / "fake-compiler-hook.py"
    runner.write_text("import pathlib, sys\n"
        "phase=sys.argv[sys.argv.index('--phase')+1]\n"
        f"with pathlib.Path({str(marker)!r}).open('a') as stream: stream.write(phase+'\\n')\n"
        "sys.exit(7 if phase=='commit-msg' else 0)\n", encoding="utf-8")
    destination = install_hooks.install(repository, runner=runner)
    assert pre_commit.paired_hook_exists(repository)
    # Idempotent installation never chains to itself.
    assert install_hooks.install(repository, runner=runner) == destination
    (repository / "01.APP/nodelang" / "old.py").write_text("changed = True\n", encoding="utf-8")
    run_git(repository, "add", ".")
    process = subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Intent: ACOMPILER"], capture_output=True)
    assert process.returncode != 0
    assert old_marker.read_text() == "old"
    assert marker.read_text().splitlines() == ["pre-commit", "commit-msg"]


def admitted_result(repository, content="new = 'valid'\n"):
    (repository / "01.APP/nodelang" / "old.py").write_text(content, encoding="utf-8")
    run_git(repository, "add", ".")
    author = run_git(repository, "var", "GIT_AUTHOR_IDENT").decode().split("<", 1)[0].strip()
    revision = run_git(repository, "rev-parse", "HEAD").decode().strip()
    context = strict_check.change_context(repository, ["01.APP/nodelang/old.py"], {"01.APP/nodelang/old.py": content},
                                           revision, {"author": author, "intent": "ACOMPILER"})
    context["metrics"].update(rule_hits=0, ratchet_deltas=0)
    observation = {"author": author, "metrics": {key: {"median": value, "mad": 0, "samples": 1}
        for key, value in context["metrics"].items()}, "method_changes": [{"metric": "files", "median": 1}]}
    return {"ok": True, "selected": ["01.APP/nodelang/old.py"], "diagnostics": [], "context": context,
            "observation": observation, "admitted_tree": run_git(repository, "write-tree").decode().strip()}


def test_author_observation_records_exact_committed_tree_once(repository):
    admitted = admitted_result(repository)
    receipt = record_observation.admit(repository, admitted)
    run_git(repository, "commit", "-qm", "Intent: ACOMPILER")
    assert record_observation.record(repository) is True
    assert record_observation.record(repository) is False
    baseline_path = repository / "05.EVIDENCE" / "acompiler-baseline.json"
    baseline = json.loads(baseline_path.read_text())
    assert len(baseline["history"]) == 1
    assert baseline["history"][0]["metrics"] == admitted["context"]["metrics"]
    assert baseline["history"][0]["method_changes"] == admitted["observation"]["method_changes"]
    assert baseline["authors"][receipt["author"]]["deviation_state"] == admitted["observation"]
    assert not record_observation.receipt_path(repository).exists()
    assert b"05.EVIDENCE/" in run_git(repository, "status", "--porcelain")


def test_observation_never_records_refused_or_unmeasured_admission(repository):
    with pytest.raises(strict_check.CompilerFailure, match="no successful measured"):
        record_observation.admit(repository, {"ok": True, "diagnostics": []})
    assert not record_observation.receipt_path(repository).exists()
    with pytest.raises(strict_check.CompilerFailure, match="no successful measured"):
        record_observation.admit(repository, {"ok": False, "diagnostics": [diagnostic()]})


def test_observation_refuses_tree_changed_during_or_after_admission(repository):
    admitted = admitted_result(repository)
    (repository / "extra.txt").write_text("new unadmitted file", encoding="utf-8")
    run_git(repository, "add", ".")
    with pytest.raises(strict_check.CompilerFailure, match="index tree changed"):
        record_observation.admit(repository, admitted)
    # Capture a valid receipt, then change the index again before committing.
    run_git(repository, "reset", "HEAD", "--", "extra.txt")
    (repository / "extra.txt").unlink()
    record_observation.admit(repository, admitted_result(repository))
    (repository / "extra.txt").write_text("changed after admission", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "Intent: ACOMPILER")
    with pytest.raises(strict_check.CompilerFailure, match="committed tree differs"):
        record_observation.record(repository)
    assert not (repository / "05.EVIDENCE" / "acompiler-baseline.json").exists()


def test_observation_refuses_different_commit_author(repository):
    record_observation.admit(repository, admitted_result(repository))
    run_git(repository, "commit", "-qm", "Intent: ACOMPILER", "--author", "Different <different@example.invalid>")
    with pytest.raises(strict_check.CompilerFailure, match="committed author differs"):
        record_observation.record(repository)
    assert not (repository / "05.EVIDENCE" / "acompiler-baseline.json").exists()


def test_observation_binds_captured_commit_when_head_advances(repository, monkeypatch):
    record_observation.admit(repository, admitted_result(repository))
    run_git(repository, "commit", "-qm", "first admitted commit")
    admitted_commit = run_git(repository, "rev-parse", "HEAD").decode().strip()
    admitted_date = run_git(repository, "show", "-s", "--format=%aI", admitted_commit).decode().strip()
    original_git = record_observation.git
    advanced = False
    def moving_head(root, *args):
        nonlocal advanced
        result = original_git(root, *args)
        if args == ("rev-parse", "HEAD") and not advanced:
            advanced = True
            (repository / "01.APP/nodelang" / "old.py").write_text("subsequent = 'unrelated'\n", encoding="utf-8")
            run_git(repository, "add", ".")
            run_git(repository, "commit", "-qm", "concurrent later commit")
        return result
    monkeypatch.setattr(record_observation, "git", moving_head)
    assert record_observation.record(repository) is True
    assert run_git(repository, "rev-parse", "HEAD").decode().strip() != admitted_commit
    row = json.loads((repository / "05.EVIDENCE" / "acompiler-baseline.json").read_text())["history"][0]
    assert row["commit"] == admitted_commit
    assert row["committed_at"] == admitted_date


def test_observation_cannot_consume_a_contending_new_admission(repository, monkeypatch):
    record_observation.admit(repository, admitted_result(repository))
    run_git(repository, "commit", "-qm", "first admitted commit")
    pending = admitted_result(repository, "later = 'next admitted candidate'\n")
    original_write = record_observation._write_json
    contention = []
    def replace_at_baseline_write(path, data):
        if path.name == "acompiler-baseline.json":
            with pytest.raises(FileExistsError):
                record_observation.admit(repository, pending)
            with pytest.raises(FileExistsError):
                record_observation.clear_receipt(repository)
            contention.append(True)
            assert record_observation.receipt_path(repository).exists()
        return original_write(path, data)
    monkeypatch.setattr(record_observation, "_write_json", replace_at_baseline_write)
    assert record_observation.record(repository) is True
    assert contention == [True]
    future = record_observation.admit(repository, pending)
    assert json.loads(record_observation.receipt_path(repository).read_text())["tree"] == future["tree"]


def runtime_fixture(tmp_path):
    owner = tmp_path / "installed"
    for name in strict_check.RUNTIME_FILES:
        path = owner / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# verified runtime bridge\n", encoding="utf-8")
    runtime = owner / "runtime" / "acompiler"
    runtime.mkdir(parents=True)
    contents = {"archhub-compiler.exe": b"binary fixture", "rules.json": b'{"machine_rules": {}}',
                "NOTICE": b"compiler notices", "LICENSES.txt": b"pinned dependency licenses"}
    for name, data in contents.items():
        (runtime / name).write_bytes(data)
    source_map = {name: hashlib.sha256(name.encode()).hexdigest() for name in strict_check.COMPILER_SOURCES}
    source_map.update({"NOTICE": package_compiler.sha(runtime / "NOTICE"),
                       "03.TOOLS/tools/archhub-compiler/rules.json": package_compiler.sha(runtime / "rules.json")})
    provenance = {"schema_version": 1, "source_sha256": strict_check.source_digest(source_map), "sources": source_map,
        "runtime_files": {name: package_compiler.sha(owner / name) for name in strict_check.RUNTIME_FILES},
        "executable_sha256": package_compiler.sha(runtime / "archhub-compiler.exe"),
        "rules_sha256": package_compiler.sha(runtime / "rules.json"), "notice_sha256": package_compiler.sha(runtime / "NOTICE"),
        "licenses_sha256": package_compiler.sha(runtime / "LICENSES.txt"), "crt": "static",
        "rustflags": str(strict_check.node_parameter("compiler_rustflags")), "windows_dlls": ["kernel32.dll", "ntdll.dll"]}
    (runtime / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    return owner, runtime, provenance


def test_installed_compiler_needs_no_cargo_and_detects_modified_binary(tmp_path, monkeypatch):
    owner, runtime, _ = runtime_fixture(tmp_path)
    monkeypatch.setattr(strict_check, "__file__", str(owner / "03.TOOLS/tools" / "pipeline" / "strict_check.py"))
    assert strict_check._command(owner) == [str(runtime / "archhub-compiler.exe")]
    assert strict_check._environment().get("CARGO_HOME") == os.environ.get("CARGO_HOME")
    (runtime / "archhub-compiler.exe").write_bytes(b"changed")
    with pytest.raises(strict_check.CompilerFailure, match="payload hash mismatch"):
        strict_check._command(owner)


def test_installed_closure_rejects_missing_lock_proof_and_dynamic_crt(tmp_path):
    owner, runtime, provenance = runtime_fixture(tmp_path)
    provenance["windows_dlls"].append("vcruntime140.dll")
    (runtime / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(strict_check.CompilerFailure, match="unpackaged runtime"):
        strict_check.verify_runtime(owner)
    provenance["windows_dlls"].pop()
    provenance["sources"].pop("03.TOOLS/tools/archhub-compiler/Cargo.lock")
    provenance["source_sha256"] = strict_check.source_digest(provenance["sources"])
    (runtime / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(strict_check.CompilerFailure, match="source/lock/rule proof"):
        strict_check.verify_runtime(owner)


@pytest.mark.parametrize("tamper", [False, True])
def test_static_package_uses_snapshot_and_freezes_source_closure(tmp_path, monkeypatch, tamper):
    monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path / "cargo-target"))
    root = tmp_path / "snapshot"
    origin = tmp_path / "origin"
    for name in set(strict_check.RUNTIME_FILES) | set(strict_check.COMPILER_SOURCES):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if name.endswith(".json") else "source fixture\n", encoding="utf-8")
    sdk = tmp_path / "sdk"
    dumpbin = sdk / "bin" / "Hostx64" / "x64" / "dumpbin.exe"
    dumpbin.parent.mkdir(parents=True)
    dumpbin.write_bytes(b"tool fixture")
    rustup = tmp_path / "rustup"
    license_path = rustup / "toolchains" / "stable-x86_64-pc-windows-msvc" / "share" / "doc" / "rust" / "LICENSE-MIT"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("Rust license fixture", encoding="utf-8")
    monkeypatch.setattr(package_compiler, "_environment", lambda **kwargs: {"VCToolsInstallDir": str(sdk), "RUSTUP_HOME": str(rustup)})
    seen = []
    def execute(command, **kwargs):
        seen.append((command, kwargs))
        if command[1] == "build":
            assert "--locked" in command
            assert str(root / "03.TOOLS/tools" / "archhub-compiler" / "Cargo.toml") in command
            target = Path(command[command.index("--target-dir") + 1]) / "release" / "archhub-compiler.exe"
            assert target.parent.parent == tmp_path / "cargo-target" / "package-static"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"built compiler fixture")
            if tamper:
                (root / "03.TOOLS/tools" / "archhub-compiler" / "Cargo.lock").write_text("changed after build", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1] == "/dependents":
            return SimpleNamespace(returncode=0, stdout="    KERNEL32.dll\n    ntdll.dll\n", stderr="")
        assert command[1] == "metadata"
        return SimpleNamespace(returncode=0, stdout=json.dumps({"packages": [{"name": "archhub-compiler"}]}), stderr="")
    monkeypatch.setattr(package_compiler.subprocess, "run", execute)
    if tamper:
        with pytest.raises(strict_check.CompilerFailure, match="snapshot changed"):
            package_compiler.package(root, origin)
        assert not (root / "runtime" / "acompiler").exists()
    else:
        manifest = package_compiler.package(root, origin)
        assert set(path.name for path in (root / "runtime" / "acompiler").iterdir()) == {
            "archhub-compiler.exe", "provenance.json", "rules.json", "NOTICE", "LICENSES.txt"}
        assert manifest["source_sha256"] == strict_check.source_digest(package_compiler.sources(root))
        assert manifest["windows_dlls"] == ["kernel32.dll", "ntdll.dll"]
        assert strict_check.verify_runtime(root).name == "archhub-compiler.exe"
    assert seen[0][1]["env"]["RUSTFLAGS"] == strict_check.node_parameter("compiler_rustflags")


@pytest.mark.parametrize("mutation", [None, "license", "revision"])
def test_omitted_registry_license_uses_pinned_verified_retained_bytes(tmp_path, mutation):
    owner = Path(__file__).resolve().parents[2]
    root = tmp_path / "snapshot"
    crate = root / "03.TOOLS/tools" / "archhub-compiler"
    (crate / "licenses").mkdir(parents=True)
    license_name = "licenses/tree-sitter-html-0.23.2-LICENSE.txt"
    for relative in ("THIRD_PARTY.md", license_name):
        shutil.copyfile(owner / "03.TOOLS/tools" / "archhub-compiler" / relative, crate / relative)
    registry = tmp_path / "registry" / "tree-sitter-html-0.23.2"
    registry.mkdir(parents=True)
    row = next(line.split("|") for line in (crate / "THIRD_PARTY.md").read_text().splitlines()
               if line.startswith("| tree-sitter-html |") and "raw.githubusercontent.com" in line)
    revision = row[4].strip().split("/")[-2]
    (registry / ".cargo_vcs_info.json").write_text(json.dumps({"git": {"sha1": "0" * 40 if mutation == "revision" else revision}}))
    manifest = registry / "Cargo.toml"
    manifest.write_text("# published crate omits LICENSE\n")
    if mutation == "license":
        (crate / license_name).write_text("modified license")
    package = {"name": "tree-sitter-html", "version": "0.23.2", "manifest_path": str(manifest), "license": "MIT"}
    rustup = tmp_path / "rustup"
    rust_docs = rustup / "toolchains" / "stable-x86_64-pc-windows-msvc" / "share" / "doc" / "rust"
    rust_docs.mkdir(parents=True)
    (rust_docs / "COPYRIGHT.html").write_text("Rust license court")
    if mutation:
        with pytest.raises(strict_check.CompilerFailure, match="hash mismatch|different pinned"):
            package_compiler.licenses({"packages": [package]}, rustup, root)
    else:
        text = package_compiler.licenses({"packages": [package]}, rustup, root)
        assert "Copyright (c) 2014 Max Brunsfeld" in text
        assert "tree-sitter-html 0.23.2" in text


def test_release_snapshot_admits_exact_compiler_sources_never_target_binary(tmp_path):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell
    source = Path(__file__).resolve().parents[2] / "01.APP/installer" / "build_release.ps1"
    judge = tmp_path / "snapshot-compiler.ps1"
    judge.write_text(r'''
param([string]$Source)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$null, [ref]$null)
foreach ($name in '$acompilerInputs', '$selectedInputs') {
    $assignment = $ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq $name}, $true)
    . ([scriptblock]::Create($assignment.Extent.Text))
}
$definition = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Test-CandidateInput'}, $true)
. ([scriptblock]::Create($definition.Extent.Text))
@{ source=(Test-CandidateInput 'selected' '03.TOOLS/tools/archhub-compiler/src/lib.rs');
   bridge=(Test-CandidateInput 'selected' '03.TOOLS/tools/pipeline/strict_check.py');
   target=(Test-CandidateInput 'selected' '03.TOOLS/tools/archhub-compiler/target/release/archhub-compiler.exe');
   runtime=(Test-CandidateInput 'selected' 'runtime/acompiler/archhub-compiler.exe');
   selected=($selectedInputs -ccontains '03.TOOLS/tools/archhub-compiler/Cargo.lock') } | ConvertTo-Json -Compress
''', encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(judge), "-Source", str(source)],
                            capture_output=True, text=True, check=True, timeout=strict_check.node_timeout())
    assert json.loads(result.stdout) == {"source": True, "bridge": True, "target": False, "runtime": False, "selected": True}


@pytest.fixture
def patched_stop_gate(tmp_path):
    external = Path("C:/Users/fargaly/00.ARCHUB/00.GOVERNANCE/03.AGENT-HOOKS")
    if not external.is_dir():
        pytest.skip("external governance handoff source unavailable on this machine")
    destination = tmp_path / "governance" / "00.GOVERNANCE" / "03.AGENT-HOOKS"
    destination.mkdir(parents=True)
    for name in ("agent_stop_gate.py", "archhub_enforcer.py"):
        shutil.copyfile(external / name, destination / name)
    patch = Path(os.environ.get("ACOMPILER_GOVERNANCE_HANDOFF", str(Path(__file__).resolve().parents[2] / "05.EVIDENCE" / "acompiler-governance-hooks.patch")))
    subprocess.run(["git", "-c", "core.autocrlf=false", "apply", str(patch)], cwd=destination.parents[1],
                   capture_output=True, check=True)
    source = destination / "agent_stop_gate.py"
    spec = importlib.util.spec_from_file_location("court_stop_gate", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TMP = tmp_path
    return module, source


def test_stop_handoff_blocks_fourth_violation_and_excludes_unowned_sessions(patched_stop_gate, repository, monkeypatch):
    module, _ = patched_stop_gate
    (repository / "03.TOOLS/tools").mkdir()
    (repository / "03.TOOLS/tools" / "ratchet.py").write_text("# court", encoding="utf-8")
    (repository / "05.EVIDENCE").mkdir()
    (repository / "05.EVIDENCE" / "ratchet.json").write_text("{}", encoding="utf-8")
    module.record_path("owned").write_text(str(repository / "01.APP/nodelang" / "old.py"), encoding="utf-8")
    commands = []
    def reject(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout="owned error", stderr="")
    monkeypatch.setattr(module.subprocess, "run", reject)
    assert module.gate({"session_id": "reviewer-with-no-edits"}) == 0
    assert commands == []
    assert [module.gate({"session_id": "owned"}) for _ in range(4)] == [2, 2, 2, 2]
    module.record_path("owned").write_text(json.dumps({"intent": "ACOMPILER", "author": "court",
        "files": [str(repository / "01.APP/nodelang" / "old.py")]}), encoding="utf-8")
    assert module.gate({"session_id": "owned"}) == 2
    module.record({"session_id": "owned", "tool_input": {"file_path": str(repository / "01.APP/nodelang" / "old.py")}})
    assert json.loads(module.record_path("owned").read_text())["intent"] == "ACOMPILER"
    assert all("--session-record" in command and "--changed" not in command for command in commands)


def test_stop_handoff_tool_exceptions_refuse(patched_stop_gate, repository, monkeypatch):
    module, source = patched_stop_gate
    (repository / "03.TOOLS/tools").mkdir()
    (repository / "03.TOOLS/tools" / "ratchet.py").write_text("# court", encoding="utf-8")
    (repository / "05.EVIDENCE").mkdir()
    (repository / "05.EVIDENCE" / "ratchet.json").write_text("{}", encoding="utf-8")
    module.record_path("owned").write_text(str(repository / "01.APP/nodelang" / "old.py"), encoding="utf-8")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(module.TMP))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "owned"})))
    monkeypatch.setattr(sys, "argv", [str(source)])
    def broken(*args, **kwargs):
        raise RuntimeError("compiler unavailable")
    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_path(str(source), run_name="__main__")
    assert exit_result.value.code == 2


def test_new_code_and_new_language_cannot_hide_under_total_drop():
    assert strict_check.compare_counts({"E0001": {"python": 0, "rust": 1}, "E0009": {"python": 1}},
                                      {"E0001": {"python": 50}}) == [
        {"code": "E0001", "language": "rust", "baseline": 0, "current": 1},
        {"code": "E0009", "language": "python", "baseline": 0, "current": 1}]


def test_whole_tree_ratchet_refuses_language_regression(repository, tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"schema_version": 1, "counts": {"E0001": {"python": 20}}}), encoding="utf-8")
    result = strict_check.check_ratchet(repository, baseline,
        compiler_command=fake_compiler(tmp_path, report(diagnostic(language="rust"))))
    assert result["ok"] is False
    assert result["regressions"] == [{"code": "E0001", "language": "rust", "baseline": 0, "current": 1}]


def test_legacy_scoped_ratchet_ignores_unowned_growth(repository, monkeypatch):
    (repository / "01.APP/nodelang" / "bystander.py").write_text("HTTPServer()\nplaceholder = True\n", encoding="utf-8")
    selected = repository / "01.APP/nodelang" / "old.py"
    selected.write_text("old = 'owned, same metrics'\n", encoding="utf-8")
    monkeypatch.setattr(strict_check, "check_changed", lambda *a, **k: {"ok": True, "diagnostics": []})
    assert ratchet.main(["compare", str(repository), "ignored-for-scoped.json", "--files", "01.APP/nodelang/old.py"]) == 0
    selected.write_text("HTTPServer()\n", encoding="utf-8")
    assert ratchet.main(["compare", str(repository), "ignored-for-scoped.json", "--files", "01.APP/nodelang/old.py"]) == 1


def test_build_runs_requested_command_only_after_admission(repository, tmp_path, monkeypatch):
    marker = tmp_path / "built.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('built')"]
    seen = []
    monkeypatch.setattr(ratchet, "main", lambda args: seen.append(args) or 1)
    assert build.main(["--root", str(repository), "--base", "HEAD", "--", *command]) == 1
    assert not marker.exists()
    assert "--whole-tree" in seen[0]
    monkeypatch.setattr(ratchet, "main", lambda args: 0)
    assert build.main(["--root", str(repository), "--base", "HEAD", "--", *command]) == 0
    assert marker.read_text() == "built"


def test_release_builder_refuses_before_output_creation(tmp_path):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell, "PowerShell is required for the real release entrypoint court"
    marker = tmp_path / "preflight.txt"
    interpreter = tmp_path / "reject-python.ps1"
    # The release entrypoint actually executes this interpreter for its compiler
    # preflight; no 01.APP/installer/build/host work is launched.
    interpreter.write_text("[IO.File]::WriteAllText('" + str(marker).replace("'", "''") + "', ($args -join '|'))\nexit 7\n", encoding="utf-8")
    archive = tmp_path / "goose.zip"
    archive.write_bytes(b"court only")
    output = tmp_path / "output"
    script = Path(__file__).resolve().parents[2] / "01.APP/installer" / "build_release.ps1"
    process = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-BuildId", "compiler-court", "-OutputDirectory", str(output), "-GooseArchivePath", str(archive),
        "-PythonPath", str(interpreter)], capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "ACOMPILER refused release build" in process.stderr
    assert "tools" in marker.read_text() and "build.py" in marker.read_text()
    assert not output.exists()


@pytest.mark.skipif(not os.environ.get("ACOMPILER_REAL_BINARY"), reason="release binary court enabled by coordinator after cargo build")
def test_real_compiler_duplicate_route_fails_and_clears(repository):
    binary = os.environ["ACOMPILER_REAL_BINARY"]
    target = repository / "01.APP/nodelang" / "routes.py"
    target.write_text("ROUTES = {'/compiler-court': 'first', '/compiler-court': 'second'}\n", encoding="utf-8")
    result = strict_check.check_files(repository, ["01.APP/nodelang/routes.py"], compiler_command=[binary])
    assert any(d["code"] == "E0001" for d in result["diagnostics"])
    target.write_text("ROUTES = {'/compiler-court': 'first'}\n", encoding="utf-8")
    result = strict_check.check_files(repository, ["01.APP/nodelang/routes.py"], compiler_command=[binary])
    assert not any(d["code"] == "E0001" for d in result["diagnostics"])


@pytest.mark.skipif(not os.environ.get("ACOMPILER_PACKAGE_PROBE"), reason="static package court enabled by coordinator")
def test_real_static_snapshot_package_runs_verified_installed_binary_without_cargo():
    owner = Path(__file__).resolve().parents[2]
    target = (owner / "03.TOOLS/tools" / "archhub-compiler" / "target").resolve()
    snapshot = Path(tempfile.mkdtemp(prefix="package-court-", dir=target)).resolve()
    assert snapshot.parent == target
    inputs = set(strict_check.COMPILER_SOURCES) | set(strict_check.RUNTIME_FILES)
    before = {name: package_compiler.sha(owner / name) for name in inputs}
    proof = owner / "05.EVIDENCE" / "acompiler-package-proof.json"
    proof.unlink(missing_ok=True)
    try:
        for name in inputs:
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(owner / name, destination)
        assert {name: package_compiler.sha(snapshot / name) for name in inputs} == before
        provenance = package_compiler.package(snapshot, owner)
        assert {name: package_compiler.sha(snapshot / name) for name in inputs} == before
        spec = importlib.util.spec_from_file_location("installed_compiler_court", snapshot / "03.TOOLS/tools" / "pipeline" / "strict_check.py")
        installed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installed)
        command = installed._command(snapshot)
        binary = snapshot / "runtime" / "acompiler" / "archhub-compiler.exe"
        assert command == [str(binary)]
        explanation = subprocess.run([*command, "--explain", "E0001"], capture_output=True, text=True,
            check=True, timeout=strict_check.node_timeout())
        assert "E0001" in explanation.stdout
        receipt = {"schema_version": 1, "source_sha256": provenance["source_sha256"],
            "executable_sha256": provenance["executable_sha256"], "observed_build_options": provenance["rustflags"],
            "windows_dlls": provenance["windows_dlls"], "runtime_files": provenance["runtime_files"],
            "licenses_sha256": provenance["licenses_sha256"], "source_unchanged": True,
            "installed_command": "runtime/acompiler/archhub-compiler.exe --explain E0001",
            "installed_command_exit": explanation.returncode, "cargo_invoked_by_installed_command": False}
        proof.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        assert snapshot.parent == target and snapshot.name.startswith("package-court-")
        shutil.rmtree(snapshot)


@pytest.mark.parametrize("case,expected", [
    ("untouched_legacy", True), ("changed_legacy", False),
    ("file_code_rise", False), ("bucket_rise", False),
    ("new_file", False), ("deleted_lines", True), ("deleted_file", True),
])
def test_changed_line_admission_contract(repository, monkeypatch, case, expected):
    path = "01.APP/nodelang/old.py"
    before = "legacy = 1\nclean = 2\ntail = 3\n"
    (repository / path).write_text(before, encoding="utf-8")
    run_git(repository, "add", path)
    run_git(repository, "commit", "-qm", "legacy baseline")
    old = diagnostic()
    after = before.replace("clean = 2", "clean = 4")
    baseline = report(old)
    current = report(old)
    if case == "changed_legacy":
        after = before.replace("legacy = 1", "legacy = 4")
    elif case == "file_code_rise":
        # Another file improves, so the global bucket holds, but this file rises.
        other = diagnostic(file="01.APP/nodelang/other.py")
        baseline = report(old, other)
        current = report(old, dict(old, line=3, message="second owner"))
    elif case == "bucket_rise":
        # A duplicate affects a different file, away from the touched line.
        current = report(old, diagnostic(file="01.APP/nodelang/other.py", code="E0009"))
    elif case == "new_file":
        path = "01.APP/nodelang/new.py"
        current = report(old, diagnostic(file=path))
    elif case == "deleted_lines":
        after = before.replace("clean = 2\n", "")
    elif case == "deleted_file":
        after = None
        current = report(files=[])
    monkeypatch.setattr(strict_check, "scan_model", lambda *a, **k: current if k.get("overlay") is not None else baseline)
    result = strict_check.check_files(repository, [path], {path: after})
    assert result["ok"] is expected, result
    if case == "file_code_rise":
        assert result["file_regressions"] == [{"file": path, "code": "E0001", "baseline": 1, "current": 2}]
    if case == "deleted_lines":
        assert result["changed_lines"][path] == []


@pytest.mark.skipif(not os.environ.get("ACOMPILER_REAL_BINARY"), reason="coordinator supplies built compiler")
def test_real_compiler_changed_line_admission(repository):
    path = "03.TOOLS/tools/pipeline/court.py"
    target = repository / path
    target.parent.mkdir(parents=True)
    source = "def legacy():\n    try:\n        return int('x')\n    except Exception:\n        pass\ndef clean() -> int:\n    return 1\n"
    target.write_text(source, encoding="utf-8")
    run_git(repository, "add", path)
    run_git(repository, "commit", "-qm", "legacy source")
    context = {"author": "Compiler court", "intent": "ACOMPILER", "why": "Verify changed-line admission with actual compiler locations."}
    def judge(content, **extra):
        return strict_check.check_files(repository, [path], {path: content}, context={**context, **extra},
                                        compiler_command=[os.environ["ACOMPILER_REAL_BINARY"]])
    untouched = judge(source.replace("return 1", "return 2"))
    assert untouched["ok"], untouched
    changed = judge(source.replace("except Exception", "except ValueError"))
    assert not changed["ok"] and any(d["code"] == "E0004" and d["line"] == 4 for d in changed["diagnostics"]), changed
    rise = judge(source.replace("return 1", "print(1)"))
    assert not rise["ok"] and any(item["code"] == "E0024" for item in rise["file_regressions"]), rise
    invalid_context = judge(source.replace("return 1", "return 2"), vendor={"unmodified": True})
    assert not invalid_context["ok"] and any(d["code"] == "E0102" for d in invalid_context["diagnostics"]), invalid_context


def test_node_build_options_change_command_and_child_environment(repository, tmp_path, monkeypatch):
    options = {"jobs": 3, "rustflags": "-C target-feature=+crt-static"}
    monkeypatch.setenv("RUSTFLAGS", "inherited-invalid-flags")
    monkeypatch.setenv("CARGO_ENCODED_RUSTFLAGS", "inherited-encoded-flags")
    configured = strict_check._environment(options=options)
    assert configured["RUSTFLAGS"] == options["rustflags"] and "CARGO_ENCODED_RUSTFLAGS" not in configured
    cargo_home = tmp_path / "CARGO"
    cargo = cargo_home / "bin" / "cargo.exe"
    original_is_file = Path.is_file
    monkeypatch.setenv("CARGO_HOME", str(cargo_home))
    monkeypatch.setattr(Path, "is_file", lambda path: path == cargo or original_is_file(path))
    command = strict_check._command(repository, options)
    assert command[0] == str(cargo)
    assert command[command.index("--jobs") + 1] == "3"
    payload = json.dumps(report())
    child = fake_compiler(tmp_path, source="import os\nassert os.environ['RUSTFLAGS'] == '-C target-feature=+crt-static'\nprint(" + repr(payload) + ")\n")
    result = strict_check.scan_model(repository, compiler_command=child, build_options=options)
    assert not result["diagnostics"]
    with pytest.raises(strict_check.CompilerFailure, match="positive integer jobs"):
        strict_check._command(repository, {"jobs": 0})


def test_ratchet_keeps_main_ui_metrics_and_refuses_missing_baseline(repository, tmp_path, monkeypatch):
    source = "const localBtn = () => ({color: 'red'}); const HoverBtn = () => null; const x = <div style={{color: 'red'}}/>;"
    counts = ratchet.measure(repository, {"01.APP/nodelang/studio/court.jsx": source})
    assert counts["local_button_helpers"] == 2 and counts["inline_styles"] == 1
    baseline = tmp_path / "incomplete.json"
    baseline.write_text(json.dumps({"counts": {}}), encoding="utf-8")
    monkeypatch.setattr(strict_check, "check_changed", lambda *a, **k: pytest.fail("missing baseline reached compiler"))
    assert ratchet.main(["compare", str(repository), str(baseline), "--whole-tree"]) == 2


def _release_commit(repository, text, message, author="Release author"):
    target = repository / "01.APP/nodelang" / "old.py"
    target.write_text(text, encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "-c", "user.name=" + author, "commit", "-qm", message)
    return run_git(repository, "rev-parse", "HEAD").decode().strip()


def test_release_replays_each_author_intent_and_exact_blob(repository, monkeypatch):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    first = _release_commit(repository, "old = 1\n", "first\n\nIntent: FIRST\nWhy: first reason", "First author")
    second = _release_commit(repository, "old = 2\n", "second\n\nIntent: SECOND", "Second author")
    seen = []
    def check(root, paths, **kwargs):
        seen.append((paths, kwargs))
        return {"ok": True, "diagnostics": []}
    monkeypatch.setattr(strict_check, "check_files", check)
    assert build.admit_sequence(repository, base) == 0
    assert len(seen) == 2
    assert seen[0][1] == {"overlay": {"01.APP/nodelang/old.py": "old = 1\n"}, "revision": base,
                          "context": {"intent": "FIRST", "why": "first reason", "author": "First author"}, "committed_history": True}
    assert seen[1][1]["revision"] == first
    assert seen[1][1]["context"] == {"intent": "SECOND", "author": "Second author"}
    assert seen[1][1]["overlay"] == {"01.APP/nodelang/old.py": "old = 2\n"}
    assert second == run_git(repository, "rev-parse", "HEAD").decode().strip()


def test_release_refuses_earlier_bad_commit_before_final_ratchet(repository, monkeypatch):
    evidence = repository / "05.EVIDENCE"
    evidence.mkdir()
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (evidence / "acompiler.json").write_text(json.dumps({"base_revision": base}), encoding="utf-8")
    _release_commit(repository, "old = 1\n", "bad\n\nIntent: FIRST")
    _release_commit(repository, "old = 2\n", "good\n\nIntent: SECOND")
    seen = []
    def check(*args, **kwargs):
        seen.append(kwargs["context"]["intent"])
        return {"ok": False, "diagnostics": []}
    monkeypatch.setattr(strict_check, "check_files", check)
    monkeypatch.setattr(ratchet, "main", lambda *args: pytest.fail("ratchet after refused commit"))
    assert build.main(["--root", str(repository)]) == 1
    assert seen == ["FIRST"]


def test_release_preserves_deletions_and_merge_resolution(repository, monkeypatch):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    branch = run_git(repository, "branch", "--show-current").decode().strip()
    run_git(repository, "checkout", "-qb", "side")
    (repository / "side.txt").write_text("side", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "side\n\nIntent: SIDE")
    run_git(repository, "checkout", branch)
    run_git(repository, "rm", "01.APP/nodelang/old.py")
    run_git(repository, "commit", "-qm", "delete\n\nIntent: DELETE")
    run_git(repository, "merge", "--no-ff", "side", "-m", "merge\n\nIntent: MERGE")
    seen = []
    monkeypatch.setattr(strict_check, "check_files", lambda *a, **k: seen.append(k) or {"ok": True, "diagnostics": []})
    assert build.admit_sequence(repository, base) == 0
    assert seen[0]["overlay"] == {"01.APP/nodelang/old.py": None}
    assert seen[1]["overlay"] == {"side.txt": "side"}
    assert seen[1]["context"]["intent"] == "MERGE"


def test_release_rejects_dirty_tree_and_unrelated_base(repository, monkeypatch):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (repository / "01.APP/nodelang/old.py").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from HEAD"):
        build.admit_sequence(repository, base)
    run_git(repository, "checkout", "--", ".")
    run_git(repository, "checkout", "--orphan", "unrelated")
    run_git(repository, "commit", "-qm", "unrelated")
    with pytest.raises(strict_check.CompilerFailure):
        build.admit_sequence(repository, base)


def test_default_release_keeps_final_whole_tree_gate(repository, monkeypatch):
    evidence = repository / "05.EVIDENCE"
    evidence.mkdir()
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (evidence / "acompiler.json").write_text(json.dumps({"base_revision": base}), encoding="utf-8")
    _release_commit(repository, "old = 1\n", "change\n\nIntent: FIRST")
    monkeypatch.setattr(strict_check, "check_files", lambda *a, **k: {"ok": True, "diagnostics": []})
    seen = []
    monkeypatch.setattr(ratchet, "main", lambda args: seen.append(args) or 1)
    assert build.main(["--root", str(repository)]) == 1
    assert seen[0][-2:] == ["--commit", "HEAD"]
    assert "--whole-tree" in seen[0]


def test_release_rejects_untracked_source(repository):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (repository / "untracked.py").write_text("value = 1", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted source"):
        build.admit_sequence(repository, base)


def test_release_binary_assets_never_read_from_current_tree(repository, monkeypatch):
    base = run_git(repository, "rev-parse", "HEAD").decode().strip()
    (repository / "icon.png").write_bytes(b"\xff\x00")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "asset\n\nIntent: ASSET")
    seen = []
    monkeypatch.setattr(strict_check, "check_files", lambda *a, **k: seen.append(k) or {"ok": True, "diagnostics": []})
    assert build.admit_sequence(repository, base) == 0
    assert seen[0]["overlay"] == {"icon.png": ""}


def test_release_history_ignores_future_local_observations(repository):
    path = record_observation.history_path(repository)
    path.write_text(json.dumps({"schema_version": 1, "history": [{"commit": "future", "author": "Future author"}],
                                "authors": {"Future author": {"deviation_state": {"poison": True}}}}), encoding="utf-8")
    assert record_observation.load_history(repository)["history"][0]["commit"] == "future"
    context = strict_check.change_context(repository, ["01.APP/nodelang/old.py"], {"01.APP/nodelang/old.py": "old = 2"},
                                         "HEAD", {"author": "Future author", "intent": "FIRST"}, committed_history=True)
    assert context["history"] == []
    assert context["deviation_state"] == {}


def test_result_context_without_a_root_lane_ledger(repository):
    text = "State: BLOCKED\nExternal release court is not green.\n"
    context = strict_check.change_context(repository, ["RESULT-RELEASE.md"], {"RESULT-RELEASE.md": text},
                                         "HEAD", {"intent": "ACOMPILER"})
    assert context["conduct_events"] == [{"kind": "lane_result", "done": False,
                                          "ledger": {"next_task": None, "owner": None}}]


@pytest.mark.parametrize("message,why", [
    ("change\n\nThe founder needs the8GB journal adopted in place.\n\nIntent: ADOPT\nCo-Authored-By: Agent <agent@example.invalid>\n", "The founder needs the8GB journal adopted in place."),
    ("change\n\nExisting explanation.\n\nIntent: FIRST\nWhy: explicit reason", "explicit reason"),
    ("subject only", None),
    ("subject\n\nChange-Id: I123\nReviewed-on: https://example.invalid\nIntent: FIRST", None),
    ("subject\n\nRecorded reason.\n\nChange-Id: I123\nReviewed-on: https://example.invalid\nIntent: FIRST", "Recorded reason."),
    ("subject\n\nIntent: FIRST\nSigned-off-by: Person <person@example.invalid>\nReviewed-by: Agent", None),
])
def test_release_preserves_recorded_explanation_without_inventing_one(message, why):
    context = build.release_context(message, "Recorded author")
    assert context["author"] == "Recorded author"
    assert context.get("why") == why


@pytest.mark.parametrize('message, intent', [
    ('ACOMPILER2B: register selected-profile qualifier repair', 'ACOMPILER2B'),
    ('MAINREL: prepare the existing release', 'MAINREL'),
    ('ACOMPILER2B: registration\n\nIntent: NEWAPP', 'NEWAPP'),
    ('fix: ordinary subject without an owner', None),
    ('MAINREL:\nbody is not a subject-line attribution', None),
])
def test_release_reads_explicit_subject_owner_without_overriding_trailers(message, intent):
    context = build.release_context(message, 'Recorded author')
    assert context.get('intent') == intent
    assert context['author'] == 'Recorded author'


@pytest.mark.parametrize('kind', ['additive', 'mixed-code', 'changed-old', 'removed-old', 'changed-policy'])
def test_release_bootstrap_registration_keeps_immutable_authority_checks(repository, monkeypatch, kind):
    registry = repository / 'evidence' / 'acompiler-intents.json'
    registry.parent.mkdir()
    old = {'schema_version': 1, 'intents': {'EXISTING': {'source': 'Existing request', 'scope': ['nodelang/old.py']}}}
    registry.write_text(json.dumps(old), encoding='utf-8')
    run_git(repository, 'add', '.')
    run_git(repository, 'commit', '-qm', 'Initial authority')
    base = run_git(repository, 'rev-parse', 'HEAD').decode().strip()
    updated = json.loads(json.dumps(old))
    updated['intents']['NEW'] = {'source': 'Founder new request', 'scope': ['nodelang/new.py']}
    if kind == 'mixed-code':
        (repository / '01.APP/nodelang' / 'old.py').write_text('changed = True\n', encoding='utf-8')
    elif kind == 'changed-old':
        updated['intents']['EXISTING']['scope'].append('nodelang/unclaimed.py')
    elif kind == 'removed-old':
        del updated['intents']['EXISTING']
    elif kind == 'changed-policy':
        updated['schema_version'] = 2
    registry.write_text(json.dumps(updated), encoding='utf-8')
    run_git(repository, 'add', '.')
    run_git(repository, 'commit', '-qm', 'Register new request\n\nIntent: NEW\nWhy: Founder request')
    head = run_git(repository, 'rev-parse', 'HEAD')
    seen = []
    def check(root, paths, **kwargs):
        seen.append(kwargs['context'])
        return {'ok': kwargs['context']['intent'] == 'ACOMPILER2B', 'diagnostics': []}
    monkeypatch.setattr(strict_check, 'check_files', check)
    assert build.admit_sequence(repository, base) == (0 if kind == 'additive' else 1)
    assert seen[0]['author'] == 'Compiler court'
    assert seen[0]['why'] == 'Founder request'
    assert seen[0]['intent'] == ('ACOMPILER2B' if kind == 'additive' else 'NEW')
    assert run_git(repository, 'rev-parse', 'HEAD') == head
