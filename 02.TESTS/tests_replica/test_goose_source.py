"""GOOSESOURCE: goose.exe is built from the pinned upstream commit, ArchHub's Cargo.lock and ArchHub's ordered patches
(never empty: founder rule F5), never the release ZIP. goose-pin.json is the one typed goose.source node declaration.

No real git, cargo or network: the build's commands are replaced by a fake that writes what they would.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "03.TOOLS/packaging/windows"
COMMIT = "cd643d2126fffab4c6a6186905211ba868d6a657"
UPSTREAM_LOCK = b"upstream lock\n"
sys.path.insert(0, str(WINDOWS))
import build_goose  # noqa: E402
import stage_goose  # noqa: E402


@pytest.fixture
def pin(tmp_path):
    """The real goose.source node, with the lock digest of the fake upstream lock and one fake patch."""
    value = json.loads((WINDOWS / "goose-pin.json").read_text(encoding="utf-8"))
    value["params"]["cargo_lock_sha256"] = hashlib.sha256(UPSTREAM_LOCK).hexdigest()
    value["params"]["patches"] = ["0001-archhub.patch"]
    path = tmp_path / "goose-pin.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _declare(pin, names):
    value = json.loads(pin.read_text(encoding="utf-8"))
    value["params"]["patches"] = list(names)
    pin.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def ours(tmp_path):
    folder = tmp_path / "goose"
    (folder / "patches").mkdir(parents=True)
    (folder / "patches" / "0001-archhub.patch").write_text("diff archhub\n", encoding="utf-8")
    return folder


@pytest.fixture
def fake_tools(monkeypatch):
    ran = []

    def run(command, cwd, env=None, capture=False):
        ran.append((command, env))
        cwd = Path(cwd)
        if command[:2] == ["git", "checkout"]:
            (cwd / "LICENSE").write_text("Apache License 2.0\n", encoding="utf-8")
            (cwd / "Cargo.lock").write_bytes(UPSTREAM_LOCK)
        if command[:2] == ["git", "rev-parse"]:
            return COMMIT
        if command[0] == "cargo":
            exe = cwd / "target" / "x86_64-pc-windows-msvc" / "release" / "goose.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ goose from source " + (cwd / "Cargo.lock").read_bytes())
        if command[0] == "rustc":
            return "rustc 1.92.0 (fake)"
        return ""
    monkeypatch.setattr(build_goose, "_run", run)
    monkeypatch.setattr(build_goose, "idle_or_away", lambda: True)
    class FakeCargo:   # stands in for the cargo child that _cargo launches through Popen; no real cargo runs
        def __init__(self, argv, cwd=None, env=None, **_options):
            run(argv, cwd, env)
            self.stdout, self.returncode = iter(()), 0

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False
    monkeypatch.setattr(build_goose.subprocess, "Popen", FakeCargo)
    return ran


def _build(tmp_path, ours, pin, **kw):
    return build_goose.build(tmp_path / "src", tmp_path / "out", archhub_rev="abc123", ours=ours, pin_path=pin, **kw)


def _stage(tmp_path, ours, pin, name, rev="abc123"):
    return stage_goose.stage_goose(tmp_path / "out", tmp_path / name, archhub_rev=rev, ours=ours, pin_path=pin)


def test_the_pin_names_source_and_its_lock_not_a_release_archive():
    node = json.loads((WINDOWS / "goose-pin.json").read_text(encoding="utf-8"))
    assert node["id"] == "goose.source" and not (WINDOWS / "goose" / "patches" / "series").exists()
    pin = build_goose.load_pin(WINDOWS / "goose-pin.json")
    assert pin["commit"] == COMMIT and pin["version"] == "1.54.0" and pin["license"] == "Apache-2.0"
    assert pin["cargo_lock_sha256"] == "0fd5e83cea2f0c77607d8b8e4e06633c4d4e70745860db975dd7431bbc4ef41f"
    assert "url" not in pin and "sha256" not in pin


def test_goose_pin_uses_the_dynamic_crt():
    pin = build_goose.load_pin(WINDOWS / "goose-pin.json")
    assert "crt-static" not in pin["rustflags"]


def test_stock_goose_never_builds_or_stages(tmp_path, ours, pin, fake_tools):
    _declare(pin, [])
    with pytest.raises(ValueError, match="F5"):
        _build(tmp_path, ours, pin, seed_lock=True)
    assert not fake_tools


def test_the_repository_ships_archhubs_goose_changes_and_its_own_pinned_lock():
    pin = build_goose.load_pin(WINDOWS / "goose-pin.json")
    series = build_goose.archhub_patches(WINDOWS / "goose")
    assert [name for name, _ in series] == ["0001-telemetry-off-by-default.patch", "0002-archhub-config-path.patch",
                                            "0003-baboom-identity.patch", "0004-archhub-default-extension.patch",
                                            "0005-archhub-advisory-dependencies.patch"]
    build_goose.check_lock(WINDOWS / "goose" / "Cargo.lock", pin)
    text = {name: (WINDOWS / "goose" / "patches" / name).read_text(encoding="utf-8") for name, _ in series}
    assert "+    Some(config.get_param::<bool>(TELEMETRY_ENABLED_KEY).unwrap_or(false))" in text["0001-telemetry-off-by-default.patch"]
    assert '+                author: "ArchHub".to_string(),' in text["0002-archhub-config-path.patch"]
    assert "+You are BABOOM, the ArchHub agent" in text["0003-baboom-identity.patch"]
    assert 'std::env::var("ARCHHUB_MCP_URL")' in text["0004-archhub-default-extension.patch"]


def test_the_advisory_fix_keeps_every_capability_and_carries_its_licences():
    """0005 fixes zip, rmcp, rustls and opentelemetry_sdk without dropping a feature: code-mode and the
    computer-controller document tools (docx/pdf/xlsx) stay in goose-cli's defaults."""
    patch = (WINDOWS / "goose" / "patches" / "0005-archhub-advisory-dependencies.patch").read_text(encoding="utf-8")
    assert '+zip = { version = "9.0.5"' in patch
    assert 'docx-rs = { git = "https://github.com/bokuweb/docx-rs", rev = "3b959fa73e6ea78a3c96ab50416407b2c3b8fa7a" }' in patch
    assert 'rev = "e14032bc282a6d0707f704d2d70f1e1677583458"' in patch                     # umya-spreadsheet 4.0.0
    assert "+        for (index, worksheet) in self.workbook.sheet_collection()?.iter().enumerate() {" in patch
    for crate in ("pctx_config", "pctx_registry", "pctx_code_execution_runtime", "pctx_code_mode"):
        assert '+%s = { path = "vendor/%s" }' % (crate, crate) in patch
        assert "+++ b/vendor/%s/LICENSE" % crate in patch                                   # MIT, Sideko, Inc.
    assert "+++ b/vendor/pctx_code_execution_runtime/src/just-bash/LICENSE-just-bash" in patch   # Apache-2.0
    assert "+use rmcp::model::{CallToolRequestParams, ContentBlock, JsonObject};" in patch
    assert "p.server_info.as_ref().and_then(|info| info.title.clone())" in patch
    assert '"code-mode",' not in "\n".join(line for line in patch.splitlines() if line.startswith("-"))
    assert "computer-controller" not in "\n".join(line for line in patch.splitlines() if line.startswith(("-", "+")))


def _lock_versions(name):
    lock = (WINDOWS / "goose" / "Cargo.lock").read_text(encoding="utf-8").split("\n")
    return {tuple(int(part) for part in lock[i + 1].split('"')[1].split("-")[0].split(".")[:3])
            for i, line in enumerate(lock) if line == 'name = "%s"' % name}


def test_the_reviewed_lock_carries_only_fixed_versions():
    """GHSA-m665-v7pm-7grj (zip), the rmcp, rustls and opentelemetry_sdk advisories: every copy in the lock (not only
    the shipped graph) is at or above its fixed version."""
    assert _lock_versions("zip") and min(_lock_versions("zip")) >= (9, 0, 5)
    assert _lock_versions("rmcp") and min(_lock_versions("rmcp")) >= (2, 1, 0)
    assert _lock_versions("rustls") and min(_lock_versions("rustls")) >= (0, 23, 46)
    assert _lock_versions("opentelemetry_sdk") and min(_lock_versions("opentelemetry_sdk")) >= (0, 32, 1)


def test_build_fetches_the_pinned_commit_and_builds_locked_with_a_receipt(tmp_path, ours, pin, fake_tools):
    receipt = _build(tmp_path, ours, pin, seed_lock=True)
    commands = [c for c, _ in fake_tools]
    assert ["git", "fetch", "-q", "--depth", "1", "https://github.com/aaif-goose/goose.git", COMMIT] in commands
    cargo, env = next((c, e) for c, e in fake_tools if c[0] == "cargo")
    assert cargo == ["cargo", "build", "--release", "--locked", "--target", "x86_64-pc-windows-msvc",
                     "-p", "goose-cli", "--bin", "goose"]
    assert "RUSTFLAGS" not in env and "CARGO_ENCODED_RUSTFLAGS" not in env
    assert receipt["upstream_commit"] == COMMIT and receipt["archhub_rev"] == "abc123"
    assert receipt["patches"] == [["0001-archhub.patch", build_goose.sha(ours / "patches" / "0001-archhub.patch")]]
    assert receipt["cargo_lock_sha256"] == hashlib.sha256(UPSTREAM_LOCK).hexdigest()
    assert receipt["executable_sha256"] == build_goose.sha(tmp_path / "out" / "goose.exe")
    assert (ours / "Cargo.lock").read_bytes() == UPSTREAM_LOCK          # seeded: ArchHub's own lock from now on
    assert json.loads((tmp_path / "out" / "receipt.json").read_text(encoding="utf-8")) == receipt


def test_the_compile_never_starts_while_the_desktop_is_in_use(tmp_path, ours, pin, fake_tools, monkeypatch):
    monkeypatch.setattr(build_goose, "idle_or_away", lambda: False)
    with pytest.raises(RuntimeError, match="desktop is in use"):
        _build(tmp_path, ours, pin, seed_lock=True)
    assert not any(c[0] == "cargo" for c, _ in fake_tools)
    assert not (tmp_path / "out").exists()


def test_a_lock_that_is_not_the_pinned_one_refuses(tmp_path, ours, pin, fake_tools):
    with pytest.raises(ValueError, match="missing"):
        _build(tmp_path, ours, pin)                                       # no lock, no seeding asked
    (ours / "Cargo.lock").write_bytes(b"edited lock\n")
    with pytest.raises(ValueError, match="pinned lock"):
        _build(tmp_path, ours, pin)
    assert not fake_tools


def test_patches_go_into_the_build_in_series_order(tmp_path, ours, pin, fake_tools):
    (ours / "Cargo.lock").write_bytes(UPSTREAM_LOCK)
    for name in ("02-b.patch", "01-a.patch"):
        (ours / "patches" / name).write_text("diff\n", encoding="utf-8")
    _declare(pin, ["02-b.patch", "01-a.patch"])
    receipt = _build(tmp_path, ours, pin)
    applied = [Path(c[-1]).name for c, _ in fake_tools if c[:2] == ["git", "apply"]]
    assert applied == ["02-b.patch", "01-a.patch"] and [name for name, _ in receipt["patches"]] == applied


def test_a_wrong_commit_or_a_used_folder_refuses_before_cargo(tmp_path, ours, pin, fake_tools, monkeypatch):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "old").write_text("x")
    with pytest.raises(ValueError, match="empty"):
        _build(tmp_path, ours, pin, seed_lock=True)
    (tmp_path / "out" / "old").unlink()
    real = build_goose._run
    monkeypatch.setattr(build_goose, "_run", lambda c, *a, **k: "0" * 40 if c[:2] == ["git", "rev-parse"] else real(c, *a, **k))
    with pytest.raises(ValueError, match="pinned commit"):
        _build(tmp_path, ours, pin, seed_lock=True)
    assert not any(c[0] == "cargo" for c, _ in fake_tools)


def test_stage_refuses_a_reversed_series_another_revision_or_other_engine_inputs(tmp_path, ours, pin, fake_tools):
    for name in ("01-a.patch", "02-b.patch"):
        (ours / "patches" / name).write_text("diff " + name + "\n", encoding="utf-8")
    _declare(pin, ["01-a.patch", "02-b.patch"])
    _build(tmp_path, ours, pin, seed_lock=True)
    _declare(pin, ["02-b.patch", "01-a.patch"])   # same files, reversed
    with pytest.raises(ValueError, match="order"):
        _stage(tmp_path, ours, pin, "p1")
    _declare(pin, ["01-a.patch", "02-b.patch"])
    with pytest.raises(ValueError, match="another ArchHub revision"):
        _stage(tmp_path, ours, pin, "p2", rev="def456")
    value = json.loads(pin.read_text(encoding="utf-8"))
    value["params"]["rustflags"] = "-C target-feature=+crt-static"
    pin.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="other engine inputs"):
        _stage(tmp_path, ours, pin, "p3")


def test_stage_takes_only_a_build_that_matches_pin_lock_series_and_receipt(tmp_path, ours, pin, fake_tools):
    _build(tmp_path, ours, pin, seed_lock=True)
    manifest = _stage(tmp_path, ours, pin, "payload")
    assert manifest == {"version": "1.54.0", "source_commit": COMMIT, "archhub_rev": "abc123",
                        "executable_sha256": build_goose.sha(tmp_path / "out" / "goose.exe"),
                        "source_url": "https://github.com/aaif-goose/goose.git"}
    assert sorted(p.name for p in (tmp_path / "payload").iterdir()) == ["LICENSE", "goose.exe", "manifest.json", "receipt.json"]
    (ours / "Cargo.lock").write_bytes(b"edited lock\n")
    with pytest.raises(ValueError, match="pinned lock"):
        _stage(tmp_path, ours, pin, "p2")
    (ours / "Cargo.lock").write_bytes(UPSTREAM_LOCK)
    (tmp_path / "out" / "goose.exe").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="receipt"):
        _stage(tmp_path, ours, pin, "p3")


def _runtime_with(tmp_path, manifest):
    from nodelang import goose_runtime
    package = tmp_path / "runtime" / "goose"
    package.mkdir(parents=True)
    (package / "goose.exe").write_bytes(b"MZ")
    (package / "manifest.json").write_text(json.dumps({"version": "1.54.0", "executable_sha256": build_goose.sha(package / "goose.exe"),
                                                       **manifest}), encoding="utf-8")
    return goose_runtime.GooseRuntime(app_root=tmp_path, state_dir=tmp_path / "state", control=None)


def test_the_runtime_accepts_the_source_build_and_refuses_the_release_zip_manifest(tmp_path, monkeypatch):
    from nodelang.goose_adapter import GooseRefused
    old = _runtime_with(tmp_path / "zip", {"archive_sha256": "5c39bc91c3eadc231847e21a8a469e778431084437b233a63a950fee22db6239"})
    with pytest.raises(GooseRefused, match="different digest"):
        old.start()
    built = _runtime_with(tmp_path / "src", {"source_commit": COMMIT})
    monkeypatch.setattr(built, "_start_host_extension", lambda: (_ for _ in ()).throw(RuntimeError("past the package check")))
    with pytest.raises(RuntimeError, match="past the package check"):
        built.start()


def test_release_builds_goose_from_source_and_never_fetches_the_zip():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    release = (ROOT / "03.TOOLS/installer/build_release.ps1").read_text(encoding="utf-8")
    assert "build_goose.py" in workflow and "-GooseBuildPath $env:GOOSE_BUILD_PATH" in workflow
    assert "goose-x86_64-pc-windows-msvc.zip" not in workflow and "$pin.url" not in workflow
    assert "GooseArchivePath" not in release and "$GooseBuildPath $goosePayload --archhub-rev $sourceRevision" in release


def test_ci_is_away_and_the_founders_desk_still_decides(monkeypatch):
    monkeypatch.setattr(build_goose, "desk_idle_or_away", lambda: False)   # input unreadable or in use
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert build_goose.idle_or_away() is False                           # founder's machine: refuse
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    assert build_goose.idle_or_away() is False
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert build_goose.idle_or_away() is True                            # headless release runner: away


def test_build_goose_imports_its_guard_in_the_release_checkout_layout(tmp_path):
    """release.yml runs `python selected/03.TOOLS/packaging/windows/build_goose.py` from a full checkout: the same layout
    as this repository. Load it isolated, from another folder, with no test path tweaks."""
    import subprocess
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "python selected/03.TOOLS/packaging/windows/build_goose.py " in workflow
    probe = ("import runpy,sys; g=runpy.run_path(sys.argv[1]); "
             "print(g['idle_or_away'].__module__, g['desk_idle_or_away'].__module__)")
    done = subprocess.run([sys.executable, "-I", "-c", probe, str(WINDOWS / "build_goose.py")], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60, env={"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), "GITHUB_ACTIONS": "true"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[1] == "tools.pipeline.strict_check"


def test_the_documentation_export_reads_the_typed_pin_with_no_runtime_manifest(tmp_path):
    from nodelang.site_export import documentation_goose_version
    (tmp_path / "packaging" / "windows").mkdir(parents=True)
    (tmp_path / "packaging" / "windows" / "goose-pin.json").write_bytes((WINDOWS / "goose-pin.json").read_bytes())
    assert not (tmp_path / "runtime").exists()
    assert documentation_goose_version(tmp_path) == "1.54.0"
    deployed = tmp_path / "deployed"
    (deployed / "runtime" / "goose").mkdir(parents=True)
    (deployed / "runtime" / "goose" / "manifest.json").write_text('{"version": "1.54.0"}', encoding="utf-8")
    assert documentation_goose_version(deployed) == "1.54.0"            # the deployed-manifest fallback stays


def test_check_mode_prepares_the_same_source_and_runs_only_cargo_check(tmp_path, ours, pin, fake_tools):
    (ours / "Cargo.lock").write_bytes(UPSTREAM_LOCK)
    result = build_goose.check(tmp_path / "src", archhub_rev="abc123", ours=ours, pin_path=pin)
    commands = [c for c, _ in fake_tools]
    assert ["git", "fetch", "-q", "--depth", "1", "https://github.com/aaif-goose/goose.git", COMMIT] in commands
    assert [Path(c[-1]).name for c in commands if c[:2] == ["git", "apply"]] == ["0001-archhub.patch"]
    cargo = [c for c in commands if c[0] == "cargo"]
    assert cargo == [["cargo", "check", "--locked", "--target", "x86_64-pc-windows-msvc", "-p", "goose-cli"]]
    assert result["mode"] == "check" and result["upstream_commit"] == COMMIT
    assert not (tmp_path / "out").exists() and not list(tmp_path.glob("*/receipt.json"))   # no output, no receipt


def _evaluate(expression, context, status):
    """The subset of GitHub expressions used here, including the implicit success guard."""
    if expression is None:
        return status == "success"
    text = str(expression).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    checks = {"success": status == "success", "failure": status == "failure", "cancelled": status == "cancelled", "always": True}
    if not any(f"{name}()" in text for name in checks) and status != "success":
        return False
    for name, value in checks.items():
        text = text.replace(f"{name}()", repr(value))
    def reference(match):
        name = match[0]
        step, output, _key = name.partition(".outputs.")
        if output and f"{step}.outcome" in context:
            return repr(context.get(name, ""))
        return repr(context[name])

    text = re.sub(r"\b(?:github|inputs|steps)(?:\.[a-zA-Z_][a-zA-Z0-9_-]*)+", reference, text)
    text = re.sub(r"!(?!=)", " not ", text).replace("&&", " and ").replace("||", " or ")
    return bool(eval(text.strip(), {"__builtins__": {}}, {}))


def _ran(workflow, event, mode, results=None):
    """Run step guards in source order, exposing only already-completed step outputs."""
    results = results or {}
    ran, statuses = {}, {}
    triggers = workflow.get("on", workflow.get(True))
    defaults = {f"inputs.{name}": spec.get("default", False if spec["type"] == "boolean" else "")
                for name, spec in triggers["workflow_dispatch"]["inputs"].items()}
    for name, job in workflow["jobs"].items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        context = {**defaults, "github.event_name": event, "inputs.mode": mode}
        if not all(statuses.get(need) == "success" for need in needs) or not _evaluate(job.get("if"), context, "success"):
            continue
        ran[name], status = [], "success"
        for step in job["steps"]:
            step_id = step.get("id")
            outcome, outputs = "skipped", {}
            if _evaluate(step.get("if"), context, status):
                ran[name].append(step.get("name", step.get("uses", "")))
                outcome, outputs = results.get(step_id, ("success", {}))
                if outcome in ("failure", "cancelled"):
                    status = outcome
            if step_id:
                context[f"steps.{step_id}.outcome"] = outcome
                context.update({f"steps.{step_id}.outputs.{key}": value for key, value in outputs.items()})
        statuses[name] = status
    return ran


def test_check_dispatch_reaches_no_write_permission_upload_or_publish_step():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["workflow_dispatch"]["inputs"]["mode"]["options"] == ["release", "check", "build", "goose", "verify-published"]
    assert triggers["workflow_dispatch"]["inputs"]["mode"]["default"] == "release"
    assert workflow["permissions"] == {"contents": "read"}
    check = _ran(workflow, "workflow_dispatch", "check")
    assert list(check) == ["goose-check-budget", "goose-check"]
    for name in check:
        job = workflow["jobs"][name]
        assert job["permissions"] == {"contents": "read"}, name
        text = yaml.safe_dump(job)
        for forbidden in ("upload-artifact", "download-artifact", "actions/cache", "publish_release", "build_release",
                          "gh release", "GH_TOKEN", "github.token", "contents: write", "persist-credentials: true"):
            assert forbidden not in text, (name, forbidden)
    runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["goose-check"]["steps"])
    assert "build_goose.py --check" in runs and "--output" not in runs
def test_build_dispatch_reuses_packaging_with_read_only_permissions_and_no_publish():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    ran = _ran(workflow, "workflow_dispatch", "build")
    assert set(ran) == {"build"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["build"]
    assert job["permissions"] == {"contents": "read"}
    steps = [step for step in job["steps"] if step.get("name") in ran["build"]]
    body = yaml.safe_dump(steps)
    assert "build_goose.py --source" in body and "build_release.ps1" in body
    for forbidden in ("publish_release", "gh release", "GH_TOKEN", "github.token", "persist-credentials: true"):
        assert forbidden not in body
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    paths = set(uploads[0]["with"]["path"].splitlines())
    for name in ("ArchHub-Setup-0.exe", "goose.exe", "receipt.json"):
        assert {f"release-output/{name}", f"release-output/{name}.sha256"} <= paths
    publish = workflow["jobs"]["publish"]
    publish_step = next(step for step in publish["steps"] if "publish_release.ps1" in step.get("run", ""))
    release_only = "${{ github.event_name == 'repository_dispatch' || (github.event_name == 'workflow_dispatch' && inputs.mode == 'release') }}"
    assert publish["if"] == publish_step["if"] == release_only
    assert "publish" not in _ran(workflow, "workflow_dispatch", "unexpected")


def test_release_dispatches_keep_the_existing_build_and_publish_path():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    other_paths = {"Prepare standalone Goose runtime checksums", "Retain standalone Goose runtime, receipt and license",
                   "Prepare build-only artifact checksums", "Retain build-only installer, Goose and receipt",
                   "Retain failed snapshot and partial build for inspection"}
    every = {name: [step.get("name", step.get("uses", "")) for step in workflow["jobs"][name]["steps"]
                    if step.get("name") not in other_paths]
             for name in ("build", "publish")}
    for event, mode in (("workflow_dispatch", "release"), ("repository_dispatch", None)):
        ran = _ran(workflow, event, mode)
        assert set(ran) == {"build", "publish"}, (event, ran)
        assert {name: [s for s in steps] for name, steps in ran.items()} == every, event


def test_goose_only_build_dispatch_uses_the_standalone_artifact():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    ran = _ran(workflow, "workflow_dispatch", "goose")
    assert set(ran) == {"build"}
    assert workflow["jobs"]["build"]["permissions"] == {"contents": "read"}
    steps = _uploads(workflow, ran["build"])
    [artifact] = steps
    assert artifact["with"]["name"].startswith("archhub-goose-")
    assert {item.rsplit("/", 1)[-1] for item in artifact["with"]["path"].splitlines()} == {
        "goose.exe", "goose.exe.sha256", "receipt.json", "receipt.json.sha256", "LICENSE", "LICENSE.sha256"
    }
    assert "Compile Studio and installer from verified source snapshots" not in ran["build"]
    assert set(_ran(workflow, "workflow_dispatch", "verify-published")) == {"verify-published"}


def _uploads(workflow, ran):
    return [step for step in workflow["jobs"]["build"]["steps"]
            if step.get("name") in ran and step.get("uses", "").startswith("actions/upload-artifact@")]


def test_installer_dispatch_retains_goose_only_after_missing_native_hosts(tmp_path, monkeypatch):
    yaml = pytest.importorskip("yaml")
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell runs the isolated installer step fixture")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    steps = {step.get("id"): step for step in workflow["jobs"]["build"]["steps"]}
    installer = steps["installer"]
    assert not installer.get("continue-on-error", False)
    script = (ROOT / "03.TOOLS/installer/build_release.ps1").read_text(encoding="utf-8")
    coverage_error = re.search(r"throw '(Stable release native host coverage failed;[^']+)'", script)[1]
    stub = tmp_path / "selected/03.TOOLS/installer/build_release.ps1"
    stub.parent.mkdir(parents=True)
    stub.write_text("param($BuildId,$GooseBuildPath,$BrokerReviewPath,$OutputDirectory)\n"
                    "if ($env:FIXTURE_INSTALLER_ERROR) { throw $env:FIXTURE_INSTALLER_ERROR }\n", encoding="utf-8")
    call = tmp_path / "installer-call.ps1"
    call.write_text("$ErrorActionPreference = 'Stop'\ntry {\n"
                    + installer["run"].split("\ntry {\n", 1)[1], encoding="utf-8")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BUILD_ID", "fixture")
    monkeypatch.setenv("BROKER_REVIEW_PATH", "fixture")
    payload = tmp_path / "goose-build"
    payload.mkdir()
    monkeypatch.setenv("GOOSE_BUILD_PATH", str(payload))

    def run_installer(error):
        output.write_text("", encoding="utf-8")
        monkeypatch.setenv("FIXTURE_INSTALLER_ERROR", error)
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(call)], cwd=tmp_path, capture_output=True, text=True)
        assert (result.returncode != 0) == bool(error), result.stderr
        if error:
            assert error in result.stderr
        return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())

    assert run_installer("") == {}
    unrelated = run_installer("Independent review invalid.")
    assert unrelated == {}
    missing = run_installer(coverage_error)
    assert missing == {"missing_host_payloads": "true"}

    fixture = {"goose.exe": b"sample runtime", "receipt.json": b'{"pinned": true}', "LICENSE": b"sample license"}
    for name, contents in fixture.items():
        (payload / name).write_bytes(contents)
    checksums = tmp_path / "checksums.ps1"
    checksums.write_text(steps["goose_checksums"]["run"], encoding="utf-8")
    subprocess.run([pwsh, "-NoProfile", "-File", str(checksums)], cwd=tmp_path, check=True)
    for name, contents in fixture.items():
        assert (payload / name).read_bytes() == contents
        assert (payload / (name + ".sha256")).read_text(encoding="ascii").strip() == (
            hashlib.sha256(contents).hexdigest() + "  " + name
        )

    def assets(event, mode, results):
        ran = _ran(workflow, event, mode, results)
        assert "publish" not in ran
        return [step["with"] for step in _uploads(workflow, ran["build"]) if step["with"]["name"].startswith("archhub-goose-")]

    [expected] = [step["with"] for step in _uploads(
        workflow, _ran(workflow, "workflow_dispatch", "goose")["build"])]
    for event, mode in (("workflow_dispatch", "release"), ("workflow_dispatch", "build"), ("repository_dispatch", None)):
        successful = _ran(workflow, event, mode)
        [normal] = _uploads(workflow, successful["build"])
        assert not normal["with"]["name"].startswith("archhub-goose-")
        assert assets(event, mode, {"installer": ("failure", missing)}) == [expected]
        assert assets(event, mode, {"installer": ("failure", unrelated)}) == []
        assert assets(event, mode, {"installer": ("cancelled", missing)}) == []
        assert assets(event, mode, {"installer": ("failure", missing), "goose_checksums": ("failure", {})}) == []


@pytest.mark.parametrize("event,mode,office_required", [
    ("workflow_dispatch", "build", False),
    ("workflow_dispatch", "release", True),
    ("repository_dispatch", None, True),
])
def test_installer_dispatch_installs_locked_studio_dependencies_and_gates_release_on_office(
        event, mode, office_required):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build"]["steps"]
    checkout = next(step for step in steps if step["name"] == "Check out selected runtime and installer")
    install = next(step for step in steps if step.get("run") == "npm ci --no-audit --no-fund")
    compile_step = "Compile Studio and installer from verified source snapshots"
    ran = _ran(workflow, event, mode)["build"]
    assert install["working-directory"] == checkout["with"]["path"] == "selected"
    assert ran.index("Use the reviewed Studio build runtime") < ran.index(install["name"]) < ran.index(compile_step)
    office = next(step for step in steps if step["name"] == "Prove Office round-trips in the built Goose")
    assert (office["name"] in ran) == office_required
    if office_required:
        assert ran.index(compile_step) < ran.index(office["name"]) < ran.index("Retain exact installer and metadata for review")
        assert "continue-on-error" not in office
        assert "build" in workflow["jobs"]["publish"]["needs"]


@pytest.mark.parametrize("mode", ["build", "release"])
def test_packaging_step_supplies_the_existing_x64_environment_loader(mode):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["build"]["steps"] if "build_release.ps1" in step.get("run", ""))
    assert step["name"] in _ran(workflow, "workflow_dispatch", mode)["build"]
    run = step["run"]
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in run
    assert "VC/Auxiliary/Build/vcvars64.bat" in run
    assert "selected/03.TOOLS/tools/archhub-compiler/target/msvc" in run
    assert run.index("Set-Content -LiteralPath (Join-Path $msvc 'setup_x64.bat')") < run.index("build_release.ps1")


def test_release_goose_office_round_trips(tmp_path, monkeypatch):
    """Run the existing Office round-trip on the release job's exact Goose artifact."""
    artifact = os.environ.get("ARCHHUB_RELEASE_GOOSE_EXE")
    if not artifact:
        pytest.skip("the release job supplies ARCHHUB_RELEASE_GOOSE_EXE")
    runtime = Path(artifact).resolve(strict=True)

    import xml.etree.ElementTree as ET
    import zipfile

    from openpyxl import Workbook, load_workbook
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    system = {"SYSTEMROOT", "WINDIR", "COMSPEC", "OS", "PATH", "PATHEXT", "SYSTEMDRIVE",
              "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}
    for name in tuple(os.environ):
        if name.upper() not in system:
            monkeypatch.delenv(name)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
                 "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "GOOSE_PATH_ROOT"):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT / "01.APP"))
    from nodelang import custom_mcp

    row = {"id": "native-office", "name": "Goose Office", "command": str(runtime),
           "args": ["mcp", "computercontroller"], "transport": "stdio", "env": []}
    store = object()
    names = sorted(tool["name"] for tool in custom_mcp.rpc(row, "tools/list", {}, store=store)["tools"])
    assert names == ["docx_tool", "pdf_tool", "xlsx_tool"]

    def call(name, operation, file, **arguments):
        result = custom_mcp.call_tool(row, name, {"operation": operation, "path": str(file), **arguments}, store=store)
        return json.dumps(result, ensure_ascii=True)

    docx = tmp_path / "note.docx"
    note = "ArchHub native word check"
    call("docx_tool", "update_doc", docx, content=note)
    assert note in call("docx_tool", "extract_text", docx)
    with zipfile.ZipFile(docx) as archive:
        assert note in "".join(ET.fromstring(archive.read("word/document.xml")).itertext())

    pdf = tmp_path / "page.pdf"
    sentence = "ArchHub native PDF check"
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=160)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 15 75 Td ({sentence}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with pdf.open("wb") as output:
        writer.write(output)
    assert sentence in PdfReader(pdf).pages[0].extract_text()
    assert sentence in call("pdf_tool", "extract_text", pdf)

    xlsx = tmp_path / "book.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Works"
    sheet["A1"], sheet["B2"] = "Before", "Keep"
    workbook.save(xlsx)
    workbook.close()
    cell = {"worksheet": "Works", "row": 1, "col": 1}
    assert "Works" in call("xlsx_tool", "list_worksheets", xlsx)
    assert "Before" in call("xlsx_tool", "get_cell", xlsx, **cell)
    call("xlsx_tool", "update_cell", xlsx, value="After", **cell)
    assert "After" in call("xlsx_tool", "get_cell", xlsx, **cell)
    saved = load_workbook(xlsx, read_only=True)
    try:
        assert (saved["Works"]["A1"].value, saved["Works"]["B2"].value) == ("After", "Keep")
    finally:
        saved.close()

    with runtime.open("rb") as executable:
        digest = hashlib.file_digest(executable, "sha256").hexdigest()
    print(f"Office round-trips PASS on Goose SHA-256 {digest}: DOCX XML, PDF text, XLSX A1 Before to After and B2 Keep.")


def test_the_check_job_is_bounded_by_the_pinned_120_minute_budget():
    """goose-check's upper bound is a named, typed parameter of the goose.source node (the measured release-run budget
    the governed build.ps1 uses), read by a read-only job and wired into timeout-minutes; never a bare literal."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    check, budget = workflow["jobs"]["goose-check"], workflow["jobs"]["goose-check-budget"]
    assert check["needs"] == "goose-check-budget"
    assert check["timeout-minutes"] == "${{ fromJSON(needs.goose-check-budget.outputs.minutes) }}"
    assert budget["outputs"]["minutes"] == "${{ steps.budget.outputs.minutes }}"
    step = next(step for step in budget["steps"] if step.get("id") == "budget")
    assert ".params.check_timeout_minutes" in step["run"] and "goose-pin.json" in step["run"]
    # the effective timeout: what the budget step reads from the pinned settings
    effective = build_goose.load_pin(WINDOWS / "goose-pin.json")["check_timeout_minutes"]
    assert type(effective) is int and effective == 120


# Native (non-Python) children like cargo itself, writing to BOTH streams; the test harness rewraps Python children.
_FAILING_CARGO = {
    101: ["cmd.exe", "/d", "/c", "echo    Compiling pctx_registry v0.1.3& "
                                 "echo error[E0432]: unresolved import `rmcp::model::RawContent` 1>&2& exit /b 101"],
    23: ["cmd.exe", "/d", "/c", "echo    Compiling pctx_registry v0.1.3& "
                                "echo error[E0432]: unresolved import `rmcp::model::RawContent` 1>&2& exit /b 23"],
}


@pytest.mark.parametrize("code", [101, 23])
@pytest.mark.parametrize("ci", [False, True])
def test_a_failing_cargo_reports_both_streams_and_its_own_exit_code(tmp_path, monkeypatch, capfd, ci, code):
    """A real non-interactive Windows child that fails like cargo, writing to stdout AND stderr. The old launch flags
    dropped both streams and kept only the code (Codex saw 23 on Windows). Both now reach the caller (desktop: the
    kept tail of one hidden low-priority pipe; CI: streamed to the job log) with the child's own exit code."""
    if ci:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setattr(build_goose, "desk_idle_or_away", lambda: True)
    with pytest.raises(build_goose.subprocess.CalledProcessError) as failure:
        build_goose._cargo(_FAILING_CARGO[code], tmp_path, dict(os.environ))
    assert failure.value.returncode == code
    captured = capfd.readouterr()
    assert "error[E0432]: unresolved import `rmcp::model::RawContent`" in captured.err + captured.out   # stderr
    assert "Compiling pctx_registry v0.1.3" in captured.err + captured.out                              # stdout


@pytest.mark.parametrize("ci", [False, True])
def test_cargo_logs_unencodable_output_and_keeps_its_exit_code(tmp_path, monkeypatch, ci):
    import contextlib
    import io
    from types import SimpleNamespace

    if ci:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(build_goose, "idle_or_away", lambda: True)
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout" if ci else "stderr", stream)
    child = SimpleNamespace(stdout=iter(["Compiling caf\u00e9\u240d\n", "link failed\n"]), returncode=101)
    monkeypatch.setattr(build_goose.subprocess, "Popen", lambda *args, **kwargs: contextlib.nullcontext(child))

    with pytest.raises(build_goose.subprocess.CalledProcessError) as failure:
        build_goose._cargo(["cargo", "build"], tmp_path, {})
    assert failure.value.returncode == 101
    assert output.getvalue().decode("cp1252").splitlines() == ["Compiling caf\u00e9\\u240d", "link failed"]


def test_the_desktop_keeps_only_a_bounded_tail(tmp_path, monkeypatch, capfd):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(build_goose, "desk_idle_or_away", lambda: True)
    noisy = [sys.executable, "-c", "import sys; [print('line', i) for i in range(5000)]; sys.exit(3)"]
    with pytest.raises(build_goose.subprocess.CalledProcessError) as failure:
        build_goose._cargo(noisy, tmp_path, dict(os.environ))
    lines = [line for line in capfd.readouterr().err.splitlines() if line.startswith("line ")]
    assert failure.value.returncode == 3 and len(lines) == build_goose.CARGO_TAIL_LINES and lines[-1] == "line 4999"


def test_the_command_line_exits_with_cargos_own_code(monkeypatch, capfd):
    def refuse(*_args, **_kwargs):
        raise build_goose.subprocess.CalledProcessError(101, ["cargo", "check", "--locked"])
    monkeypatch.setattr(build_goose, "check", refuse)
    assert build_goose.main(["--check", "--source", "x", "--archhub-rev", "abc"]) == 101
    assert "cargo check exited with code 101" in capfd.readouterr().err


@pytest.mark.parametrize("rustflags", ["", "-C debuginfo=1"])
def test_cargo_receives_only_an_explicit_rustflags_override(tmp_path, ours, pin, fake_tools, monkeypatch, rustflags):
    monkeypatch.setenv("RUSTFLAGS", "-C opt-level=1")
    monkeypatch.setenv("CARGO_ENCODED_RUSTFLAGS", "-C\x1fopt-level=2")
    monkeypatch.delenv("LLAMA_STATIC_CRT", raising=False)
    value = json.loads(pin.read_text(encoding="utf-8"))
    value["params"]["rustflags"] = rustflags
    pin.write_text(json.dumps(value), encoding="utf-8")
    receipt = _build(tmp_path, ours, pin, seed_lock=True)
    env = next(e for c, e in fake_tools if c[0] == "cargo")
    assert {key: env[key] for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS") if key in env} == (
        {"RUSTFLAGS": rustflags} if rustflags else {}
    )
    assert "LLAMA_STATIC_CRT" not in env
    assert receipt["rustflags"] == rustflags
