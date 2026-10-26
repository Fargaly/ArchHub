"""Release admission cache dependencies and build-before-execute courts."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.pipeline import build, strict_check


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True).stdout.decode().strip()


def commit(root, message):
    git(root, "add", ".")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def test_registry_change_only_replays_its_users(tmp_path, monkeypatch):
    root = tmp_path / "REPO"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Cache court")
    git(root, "config", "user.email", "court@example.invalid")
    git(root, "config", "core.longpaths", "true")
    git(root, "config", "core.hooksPath", str(tmp_path / "NOHOOKS"))
    git(root, "config", "user.signingkey", "")
    git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text("tools/archhub-compiler/target/\n")
    registry = root / "evidence" / "acompiler-intents.json"
    registry.parent.mkdir()
    entries = {key: {"source": key, "scope": ["app.py"]} for key in ("FIRST", "SECOND")}
    def save():
        registry.write_text(json.dumps({"schema_version": 1, "intents": entries}))
    save()
    base = commit(root, "base")
    (root / "app.py").write_text("value = 1\n")
    first = commit(root, "FIRST: one\n\nWhy: first")
    (root / "app.py").write_text("value = 2\n")
    second = commit(root, "second\n\nIntent: SECOND\nWhy: second")
    seen = []
    monkeypatch.setattr(strict_check, "check_files", lambda *a, **k:
                        seen.append(k["context"]["intent"]) or {"ok": True, "diagnostics": []})
    # Exercise the actual replay loop, Git history and admitted.json. Only the
    # expensive compiler transport is replaced; its identity remains real bytes.
    monkeypatch.setattr(strict_check, "_command", lambda *a, **k: [sys.executable])
    assert build.admit_sequence(root, base) == 0
    assert seen == ["FIRST", "SECOND"]
    seen.clear()
    entries["UNRELATED"] = {"source": "new", "scope": ["other.py"]}
    save()
    registration = commit(root, "register\n\nIntent: UNRELATED\nWhy: new request")
    assert build.admit_sequence(root, base) == 0
    assert seen == ["ACOMPILER2B"], seen
    seen.clear()
    entries["FIRST"]["scope"].append("extra.py")
    save()
    changed = commit(root, "policy change\n\nIntent: FIRST\nWhy: changed scope")
    assert build.admit_sequence(root, base) == 0
    assert seen == ["FIRST", "FIRST"], seen
    _, data = build.admitted_record(root)
    assert set(data) == {first, second, registration, changed}
    seen.clear()
    assert build.admit_sequence(root, base) == 0
    assert seen == []
    entries["UNRELATED"]["external_entrypoints"] = [{"name": "hook", "source": "hook.py", "blob_oid": "a" * 40}]
    save()
    commit(root, "register external\n\nIntent: UNRELATED\nWhy: Add an input shared by every scan")
    assert build.admit_sequence(root, base) == 0
    assert len(seen) == 5, seen
    seen.clear()
    entries["UNRELATED"]["external_entrypoints"][0]["blob_oid"] = "b" * 40
    save()
    commit(root, "repin external\n\nIntent: UNRELATED\nWhy: Replace an input shared by every scan")
    assert build.admit_sequence(root, base) == 0
    assert len(seen) == 6, seen
    seen.clear()
    assert build.admit_sequence(root, base) == 0
    assert seen == []
    monkeypatch.setattr(strict_check, "_command", lambda *a, **k: [__file__])
    assert build.admit_sequence(root, base) == 0
    assert len(seen) == 6


def test_external_repin_invalidates_every_intent():
    registry = {"intents": {"FIRST": {}, "SECOND": {}, "EXTERNAL": {
        "external_entrypoints": [{"name": "hook", "blob_oid": "a" * 40}]}}}
    original = {intent: build.admission_identity("compiler", registry, {"intent": intent})
                for intent in ("FIRST", "SECOND")}
    registry["intents"]["EXTERNAL"]["external_entrypoints"][0]["blob_oid"] = "b" * 40
    repinned = {intent: build.admission_identity("compiler", registry, {"intent": intent})
                for intent in original}
    assert all(repinned[intent] != original[intent] for intent in original)
    registry["intents"]["EXTERNAL"].pop("external_entrypoints")
    assert all(build.admission_identity("compiler", registry, {"intent": intent}) != repinned[intent]
               for intent in original)


def test_compiler_is_built_once_then_executed_and_stale_inputs_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(strict_check, "idle_or_away", lambda: True)
    owner = tmp_path / "OWNER"
    crate = owner / "tools" / "archhub-compiler"
    (crate / "src").mkdir(parents=True)
    (crate / "src" / "main.rs").write_text("fn main() {}")
    (crate / "Cargo.toml").write_text('[package]\nname="archhub-compiler"\nversion="0.1.0"\n')
    (crate / "Cargo.lock").write_text("version = 4\n")
    (crate / "rules.json").write_text("{}")
    module = owner / "tools" / "pipeline" / "strict_check.py"
    monkeypatch.setattr(strict_check, "__file__", str(module))
    cargo_home = tmp_path / "CARGO"
    cargo = cargo_home / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    cargo.parent.mkdir(parents=True)
    cargo.touch()
    monkeypatch.setenv("CARGO_HOME", str(cargo_home))
    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    builds = []
    def run(command, **kwargs):
        assert command[1] in ("build", "run"), command
        builds.append((command, kwargs))
        executable = crate / "target" / "HOST-TARGET" / "release" / ("archhub-compiler.exe" if os.name == "nt" else "archhub-compiler")
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"fresh compiler")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"reason": "compiler-artifact",
            "target": {"name": "archhub-compiler"}, "executable": str(executable)}))
    monkeypatch.setattr(strict_check, "_environment", lambda *a, **k: dict(os.environ))
    monkeypatch.setattr(strict_check.subprocess, "run", run)
    first = strict_check._command(owner)
    assert len(first) == 1 and Path(first[0]).is_file()
    assert strict_check._command(owner) == first
    assert len(builds) == 1
    for filename in (crate / "rules.json", crate / "src" / "main.rs"):
        filename.write_text(filename.read_text() + "\n")
        assert strict_check._command(owner) == first
    assert len(builds) == 3
    Path(first[0]).write_bytes(b"stale replacement")
    assert strict_check._command(owner) == first
    assert len(builds) == 4
    assert all("run" not in command for command, _ in builds)
    assert all("timeout" not in kwargs for _, kwargs in builds)
    assert all(kwargs["encoding"] == "utf-8" for _, kwargs in builds)
    monkeypatch.setattr(strict_check, "idle_or_away", lambda: False)
    (crate / "rules.json").write_text("{\"changed\":true}")
    fallback = strict_check._command(owner)
    assert fallback == [str(cargo), "run", "--quiet", "--release", "--locked", "--jobs", "2", "--manifest-path", str(crate / "Cargo.toml"), "--"]
    assert len(builds) == 4
    prepared = strict_check._command(owner, executable_only=True)
    assert prepared == first
    assert len(builds) == 5
    assert builds[-1][0][1] == "run"
    assert builds[-1][0][-2:] == ["--", "source-identities"]
    assert builds[-1][1]["input"] == "[]"
    assert strict_check._command(owner) == first
    assert len(builds) == 5


@pytest.mark.parametrize("age, expected", [(0.0, False), (2.0, True), (float("inf"), False), (float("nan"), False)])
def test_idle_preparation_uses_baboom_presence(age, expected, monkeypatch):
    from nodelang import baboom_native_companion
    monkeypatch.setattr(baboom_native_companion, "desktop_input_idle_seconds", lambda: age)
    assert strict_check.idle_or_away() is expected


@pytest.mark.skipif(not os.environ.get("ACOMPILER_REAL_BINARY"), reason="requires the built compiler")
def test_real_compiler_cache_preserves_parent_admission(tmp_path, monkeypatch):
    root = tmp_path / "REAL"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Cache court")
    git(root, "config", "user.email", "court@example.invalid")
    git(root, "config", "core.longpaths", "true")
    git(root, "config", "core.hooksPath", str(tmp_path / "NOHOOKS"))
    git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text("tools/archhub-compiler/target/\n")
    registry = root / "evidence" / "acompiler-intents.json"
    registry.parent.mkdir()
    entries = {key: {"source": "Founder exact cache regression court", "scope": ["note.md"]}
               for key in ("FIRST", "SECOND")}
    def save():
        registry.write_text(json.dumps({"schema_version": 1, "intents": entries}))
    save()
    base = commit(root, "base")
    for intent in ("FIRST", "SECOND"):
        (root / "note.md").write_text(intent)
        commit(root, f"{intent}: documentation\n\nWhy: Verify historical authority using the real compiler.")
    seen = []
    original = strict_check.check_files
    def check(*args, **kwargs):
        seen.append(kwargs["context"]["intent"])
        return original(*args, **kwargs)
    monkeypatch.setattr(strict_check, "check_files", check)
    # A release may start active (Cargo launcher) and scan later while idle.
    # Only the launcher selection changes; every admission uses the real binary.
    active = [True]
    def command(*args, **kwargs):
        if active[0]:
            active[0] = False
            if not kwargs.get("executable_only"):
                return [sys.executable, "run", "--"]
        return [os.environ["ACOMPILER_REAL_BINARY"]]
    monkeypatch.setattr(strict_check, "_command", command)
    assert build.admit_sequence(root, base) == 0
    assert seen == ["FIRST", "SECOND"]
    seen.clear()
    entries["UNRELATED"] = {"source": "Founder unrelated request", "scope": ["other.md"]}
    save()
    commit(root, "register\n\nIntent: UNRELATED\nWhy: Register a separate founder request without replaying history.")
    assert build.admit_sequence(root, base) == 0
    assert seen == ["ACOMPILER2B"]
    seen.clear()
    entries["FIRST"]["scope"].append("extra.md")
    save()
    commit(root, "ACOMPILER2B: update request\n\nWhy: Verify that only users of changed authority are re-admitted.")
    assert build.admit_sequence(root, base) == 0
    assert seen == ["FIRST", "ACOMPILER2B"]
    seen.clear()
    changed_compiler = tmp_path / "changed-compiler.exe"
    changed_compiler.write_bytes(Path(os.environ["ACOMPILER_REAL_BINARY"]).read_bytes() + b"\nGATEFAST identity court\n")
    changed_compiler.chmod(Path(os.environ["ACOMPILER_REAL_BINARY"]).stat().st_mode)
    monkeypatch.setattr(strict_check, "_command", lambda *a, **k: [str(changed_compiler)])
    assert build.admit_sequence(root, base) == 0
    assert seen == ["FIRST", "SECOND", "ACOMPILER2B", "ACOMPILER2B"]
    seen.clear()
    assert build.admit_sequence(root, base) == 0
    assert seen == []


@pytest.mark.skipif(os.name != "nt", reason="Windows inherited pipe lifetime regression")
def test_scan_returns_when_exited_compiler_child_inherits_output_handles(tmp_path):
    import time
    report = {"schema_version": 1, "counts": {code: {} for code in strict_check.CODES},
              "diagnostics": [], "files": []}
    compiler = tmp_path / "compiler.py"
    compiler.write_text(
        "import json, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'], close_fds=False)\n"
        f"print(json.dumps({report!r}), flush=True)\n", encoding="utf-8")
    started = time.monotonic()
    actual = strict_check.scan_model(tmp_path, compiler_command=[sys.executable, str(compiler)], timeout=2)
    elapsed = time.monotonic() - started
    assert actual == report
    assert elapsed < 2, f"exited compiler waited for inherited output handles: {elapsed:.3f}s"
