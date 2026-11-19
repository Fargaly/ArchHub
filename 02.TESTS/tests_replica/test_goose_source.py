"""GOOSESOURCE: goose.exe is built from the pinned upstream commit, ArchHub's Cargo.lock and ArchHub's ordered patches
(never empty: founder rule F5), never the release ZIP. goose-pin.json is the one typed goose.source node declaration.

No real git, cargo or network: the build's commands are replaced by a fake that writes what they would.
"""
import hashlib
import json
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
    monkeypatch.setattr(build_goose.subprocess, "run", lambda argv, cwd, env, **kw: run(argv, cwd, env))
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
    assert pin["cargo_lock_sha256"] == "ca83de283bab2099eb696786fafdca59eb597d9ed65eaf9e6041e9abdc67e016"
    assert "url" not in pin and "sha256" not in pin


def test_stock_goose_never_builds_or_stages(tmp_path, ours, pin, fake_tools):
    _declare(pin, [])
    with pytest.raises(ValueError, match="F5"):
        _build(tmp_path, ours, pin, seed_lock=True)
    assert not fake_tools


def test_the_repository_ships_archhubs_goose_changes_and_its_own_pinned_lock():
    pin = build_goose.load_pin(WINDOWS / "goose-pin.json")
    series = build_goose.archhub_patches(WINDOWS / "goose")
    assert [name for name, _ in series] == ["0001-telemetry-off-by-default.patch", "0002-archhub-config-path.patch",
                                            "0003-baboom-identity.patch", "0004-archhub-default-extension.patch"]
    build_goose.check_lock(WINDOWS / "goose" / "Cargo.lock", pin)
    text = {name: (WINDOWS / "goose" / "patches" / name).read_text(encoding="utf-8") for name, _ in series}
    assert "+    Some(config.get_param::<bool>(TELEMETRY_ENABLED_KEY).unwrap_or(false))" in text["0001-telemetry-off-by-default.patch"]
    assert '+                author: "ArchHub".to_string(),' in text["0002-archhub-config-path.patch"]
    assert "+You are BABOOM, the ArchHub agent" in text["0003-baboom-identity.patch"]
    assert 'std::env::var("ARCHHUB_MCP_URL")' in text["0004-archhub-default-extension.patch"]


def test_build_fetches_the_pinned_commit_and_builds_locked_with_a_receipt(tmp_path, ours, pin, fake_tools):
    receipt = _build(tmp_path, ours, pin, seed_lock=True)
    commands = [c for c, _ in fake_tools]
    assert ["git", "fetch", "-q", "--depth", "1", "https://github.com/aaif-goose/goose.git", COMMIT] in commands
    cargo, env = next((c, e) for c, e in fake_tools if c[0] == "cargo")
    assert cargo == ["cargo", "build", "--release", "--locked", "--target", "x86_64-pc-windows-msvc",
                     "-p", "goose-cli", "--bin", "goose"]
    assert env["RUSTFLAGS"] == "-C target-feature=+crt-static"
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
    pin.write_text(pin.read_text(encoding="utf-8").replace("crt-static", "crt-static "), encoding="utf-8")
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
