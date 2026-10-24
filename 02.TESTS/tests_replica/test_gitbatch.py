"""Batched revision reads answer exactly as the per-path Git pairs, in constant spawns."""
import json
from pathlib import Path
import subprocess
import sys
import time

from tools.pipeline import build, strict_check


def git(root, *args, input=None):
    return subprocess.run(["git", "-C", str(root), *args], check=True, input=input,
                          capture_output=True).stdout.decode().strip()


def commit(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def old_blob(root, revision, path):
    """The replaced per-path pair, verbatim."""
    present = strict_check.git(root, "ls-tree", "-z", revision, "--", path) if revision else \
        strict_check.git(root, "ls-files", "--stage", "-z", "--", path)
    return strict_check.git(root, "show", f"{revision}:{path}" if revision else f":{path}") if present else None


def old_overlay(root, revision, paths):
    """build.py's replaced overlay loop, verbatim apart from the decode exception capture."""
    overlay = {}
    for path in paths:
        present = strict_check.git(root, "ls-tree", "-z", revision, "--", path)
        overlay[path] = None
        if present:
            raw = strict_check.git(root, "show", f"{revision}:{path}")
            try:
                overlay[path] = raw.decode("utf-8")
            except UnicodeError:
                if Path(path).suffix.lower() not in strict_check.NON_CODE:
                    raise
                overlay[path] = ""
    return overlay


def outcome(call):
    try:
        return "ok", call()
    except Exception as exc:  # the exact failure is part of the semantics
        return "error", type(exc).__name__, str(exc)


def repository(tmp_path, name="REPO"):
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    for key, value in (("user.name", "Batch court"), ("user.email", "court@example.invalid"),
                       ("core.longpaths", "true"), ("core.hooksPath", str(tmp_path / "NOHOOKS")),
                       ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        git(root, "config", key, value)
    (root / ".gitignore").write_bytes("tools/archhub-compiler/target/\n".encode())
    registry = root / "evidence" / "acompiler-intents.json"
    registry.parent.mkdir()
    registry.write_bytes(json.dumps({"schema_version": 1, "intents": {"BATCH": {"source": "court", "scope": ["*"]}}}).encode())
    return root


def history(root, bulk=6):
    """Adds, deletes, binaries, a rename, a file that becomes a directory, a symlink."""
    (root / "app.py").write_bytes("value = 1\n".encode())
    (root / "keep.py").write_bytes("kept = True\n".encode())
    (root / "old_name.py").write_bytes("def moved():\n    return 1\n".encode())
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary")
    (root / "doc.md").write_bytes("notes\n".encode())
    (root / "swap").write_bytes("a file first\n".encode())
    base = commit(root, "base")
    target = git(root, "hash-object", "-w", "--stdin", input=b"app.py")
    git(root, "update-index", "--add", "--cacheinfo", f"120000,{target},link")
    git(root, "commit", "-qm", "BATCH: link\n\nWhy: court")
    links = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--", "link")
    (root / "app.py").write_bytes("value = 2\n".encode())
    (root / "keep.py").unlink()
    (root / "new.py").write_bytes("fresh = 'é'\n".encode("utf-8"))
    (root / "old_name.py").rename(root / "new_name.py")
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xfe\xfe\x00changed")
    (root / "swap").unlink()
    (root / "swap").mkdir()
    (root / "swap" / "inner.py").write_bytes("inside = 1\n".encode())
    for index in range(bulk):
        (root / "bulk").mkdir(exist_ok=True)
        (root / "bulk" / f"m{index:03}.py").write_bytes(f"n = {index}\n".encode())
    restructure = commit(root, "BATCH: restructure\n\nWhy: court")
    for index in range(0, bulk, 2):
        (root / "bulk" / f"m{index:03}.py").unlink()
    (root / "bulk" / "m001.py").write_bytes("n = 'changed'\n".encode())
    prune = commit(root, "BATCH: prune\n\nWhy: court")
    return base, links, restructure, prune


def every_path(root, revisions):
    paths = set()
    for revision in revisions:
        paths.update(filter(None, git(root, "ls-tree", "-r", "--name-only", revision).splitlines()))
    return sorted(paths | {"swap", "bulk", "missing.py", "App.py", "swap/missing.py", "gone/deep.py",
                           "*.py", "?pp.py", "[a]pp.py", ":(glob)*.py", ":(top)app.py"})


def test_revision_blobs_match_per_path_pairs_at_every_revision(tmp_path):
    root = repository(tmp_path)
    revisions = history(root)
    paths = every_path(root, revisions)
    for revision in revisions:
        for path in paths:
            assert outcome(lambda: strict_check.revision_blobs(root, revision, [path])[path]) == \
                outcome(lambda: old_blob(root, revision, path)), (revision, path)
        readable = [path for path in paths if outcome(lambda: old_blob(root, revision, path))[0] == "ok"]
        assert strict_check.revision_blobs(root, revision, readable) == {path: old_blob(root, revision, path) for path in readable}
    assert strict_check.revision_blobs(root, revisions[2], ["image.png"])["image.png"] == b"\x89PNG\r\n\x1a\n\xfe\xfe\x00changed"
    assert strict_check.revision_blobs(root, revisions[1], ["link"])["link"] == b"app.py"


def test_gitlink_reads_fail_as_per_path_pairs(tmp_path):
    root = repository(tmp_path)
    history(root)
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},vendor/sub")
    git(root, "commit", "-qm", "gitlink")
    for revision in ("HEAD", None):
        for path in ("vendor/sub", "vendor", "vendor/sub/inner.py"):
            assert outcome(lambda: strict_check.revision_blobs(root, revision, [path])[path]) == \
                outcome(lambda: old_blob(root, revision, path)), (revision, path)
    assert outcome(lambda: old_blob(root, "HEAD", "vendor/sub"))[0] == "error"  # the gitlink branch is exercised


def test_index_reads_match_per_path_pairs_including_conflicts_and_pathspec_names(tmp_path):
    root = repository(tmp_path)
    history(root)
    (root / "[id].py").write_bytes("bracket = 1\n".encode())
    (root / "i.py").write_bytes("letter = 1\n".encode())
    (root / "new.py").write_bytes("staged = 2\n".encode())
    git(root, "add", "i.py", "new.py")
    oid = git(root, "hash-object", "-w", "--stdin", input=b"side\n")
    git(root, "update-index", "--index-info", input="".join(
        f"100644 {oid} {stage}\tconflict.py\n" for stage in (1, 2, 3)).encode())
    paths = every_path(root, ["HEAD"]) + ["[id].py", "i.py", "conflict.py", "*.py", ":(glob)*.py", "a\\b.py"]
    for path in paths:
        assert outcome(lambda: strict_check.revision_blobs(root, None, [path])[path]) == \
            outcome(lambda: old_blob(root, None, path)), path
    assert strict_check.revision_blobs(root, None, ["new.py"])["new.py"] == b"staged = 2\n"


def captured_admission(root, base, monkeypatch):
    seen = {}
    monkeypatch.setattr(strict_check, "check_files", lambda root_, paths, **k:
                        seen.__setitem__(k["revision"], dict(k["overlay"])) or {"ok": True, "diagnostics": []})
    monkeypatch.setattr(strict_check, "_command", lambda *a, **k: [sys.executable])
    return outcome(lambda: build.admit_sequence(root, base)), seen


def test_admission_overlays_match_per_path_reads(tmp_path, monkeypatch):
    root = repository(tmp_path)
    base, *later = history(root)
    status, seen = captured_admission(root, base, monkeypatch)
    assert status == ("ok", 0)
    for revision in later:
        parent = git(root, "rev-parse", f"{revision}^")
        paths = sorted(filter(None, git(root, "diff", "--no-renames", "--name-only", parent, revision).splitlines()))
        assert seen[parent] == old_overlay(root, revision, paths), revision
    assert seen[git(root, "rev-parse", f"{later[1]}^")]["image.png"] == ""
    assert seen[git(root, "rev-parse", f"{later[1]}^")]["old_name.py"] is None
    # A committed non-UTF-8 source refuses exactly as before.
    (root / "bad.py").write_bytes(b"\xff\xfe = 1\n")
    bad = commit(root, "BATCH: bad bytes\n\nWhy: court")
    build.admitted_record(root)[0].unlink()
    status, _ = captured_admission(root, base, monkeypatch)
    assert status[:2] == ("error", "UnicodeDecodeError")
    assert outcome(lambda: old_overlay(root, bad, ["bad.py"]))[:2] == status[:2]


def old_check_overlay(root, commit, paths):
    """check_changed's replaced overlay loop, verbatim."""
    overlay = {}
    for path in paths:
        present = strict_check.git(root, "ls-tree", "-z", commit, "--", path) if commit else \
            strict_check.git(root, "ls-files", "--stage", "-z", "--", path)
        if not present:
            overlay[path] = None
            continue
        raw = strict_check.git(root, "show", f"{commit}:{path}" if commit else f":{path}")
        try:
            overlay[path] = raw.decode("utf-8")
        except UnicodeError as exc:
            if Path(path).suffix.lower() not in strict_check.NON_CODE:
                raise strict_check.CompilerFailure(f"owned source is not UTF-8: {path}") from exc
    return overlay


def test_check_changed_overlays_match_for_commits_and_index(tmp_path, monkeypatch):
    root = repository(tmp_path)
    revisions = history(root)
    (root / "bad.py").write_bytes(b"\xff\xfe = 1\n")
    revisions += (commit(root, "BATCH: bad bytes\n\nWhy: court"),)
    seen = []
    monkeypatch.setattr(strict_check, "check_files", lambda root_, paths, **k:
                        seen.append(k["overlay"]) or {"ok": True})
    for revision in revisions[1:]:
        git(root, "checkout", "-q", revision)
        paths = strict_check.selected_files(root, commit=revision)
        actual = outcome(lambda: strict_check.check_changed(root, commit=revision) and seen[-1])
        assert actual == outcome(lambda: old_check_overlay(root, revision, paths)), revision
    assert actual[0] == "error" and "bad.py" in actual[2]
    assert "image.png" not in seen[-2] and seen[-2]["keep.py"] is None
    git(root, "checkout", "-q", revisions[-2])
    (root / "app.py").write_bytes("value = 'staged'\n".encode())
    (root / "new.py").unlink()
    (root / "picture.png").write_bytes(b"\xff\xd8\xff")
    git(root, "add", "-A")
    paths = strict_check.selected_files(root)
    strict_check.check_changed(root)
    assert seen[-1] == old_check_overlay(root, None, paths) == {"app.py": "value = 'staged'\n", "new.py": None}


def test_change_context_matches_per_path_reads(tmp_path, monkeypatch):
    root = repository(tmp_path)
    _, _, restructure, _ = history(root)
    parent = git(root, "rev-parse", f"{restructure}^")
    selected = sorted(filter(None, git(root, "diff", "--no-renames", "--name-only", parent, restructure).splitlines()))
    candidate = {path: (value.decode("utf-8", "replace") if value is not None else None)
                 for path, value in strict_check.revision_blobs(root, restructure, selected).items()}
    renamed = {"new_name.py": "old_name.py"}
    def run():
        scope = {}
        context = strict_check.change_context(root, selected, candidate, parent, {"author": "Batch court", "intent": "BATCH"},
                                              patch_scope=scope, committed_history=True, renamed=renamed)
        return context, scope
    batched = run()
    monkeypatch.setattr(strict_check, "revision_blobs", lambda root_, revision, paths:
                        {path: old_blob(root_, revision, path) for path in paths})
    assert run() == batched
    assert batched[1]["new.py"]["new"] and not batched[1]["app.py"]["new"]
    assert "old_name.py" not in batched[1] and not batched[1]["new_name.py"]["ranges"]


def spawns(monkeypatch):
    calls = []
    real = subprocess.run
    def counting(command, *args, **kwargs):
        if command and command[0] == "git":
            calls.append(command)
        return real(command, *args, **kwargs)
    monkeypatch.setattr(strict_check.subprocess, "run", counting)
    return calls


def test_spawns_are_constant_per_revision_not_per_path(tmp_path, monkeypatch):
    root = repository(tmp_path)
    _, _, restructure, prune = history(root, bulk=300)
    paths = sorted(filter(None, git(root, "diff", "--no-renames", "--name-only", restructure, prune).splitlines()))
    assert len(paths) == 151  # 150 deletes and one modification
    calls = spawns(monkeypatch)
    # The whole admission of one commit spawns the same count for 151 or 1 changed files.
    monkeypatch.setattr(strict_check, "check_files", lambda *a, **k: {"ok": True, "diagnostics": []})
    monkeypatch.setattr(strict_check, "_command", lambda *a, **k: [sys.executable])
    (root / "app.py").write_bytes(b"value = 'tiny'\n")
    tiny = commit(root, "BATCH: one file\n\nWhy: court")
    per_commit = []
    for start in (restructure, prune):  # one commit each: 151 changed files, then 1
        git(root, "checkout", "-q", prune if start == restructure else tiny)
        build.admitted_record(root)[0].unlink(missing_ok=True)
        calls.clear()
        assert build.admit_sequence(root, start) == 0
        per_commit.append(len(calls))
    assert per_commit[0] == per_commit[1], per_commit
    timings = {}
    for label, selection in (("one", ["bulk/m001.py"]), ("all", paths)):
        calls.clear()
        started = time.perf_counter()
        strict_check.revision_blobs(root, prune, selection)
        timings[label] = (len(calls), time.perf_counter() - started)
    print("revision_blobs spawns/seconds:", timings)
    assert timings["one"][0] == timings["all"][0] == 2, timings
    assert [command[3] for command in calls] == ["ls-tree", "cat-file"]
    # change_context reads the parent once, whatever the selection size.
    counts = []
    for selection in (paths[:1], paths):
        calls.clear()
        strict_check.change_context(root, selection, {path: None for path in selection}, restructure,
                                    {"author": "Batch court", "intent": "BATCH"}, committed_history=True)
        counts.append(len(calls))
    assert counts[0] == counts[1], counts
