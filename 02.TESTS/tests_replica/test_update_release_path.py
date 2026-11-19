"""Publish -> update, end to end, against a LOCAL release in a temp folder.

The release is written exactly as installer/build_release.ps1 writes one; the
GitHub release it would become is produced by packaging/windows/
check_update_offer.py (the one publish path); the installed updater
(nodelang.quiet_update) then reads, downloads, verifies, applies and confirms
it. Nothing reaches the network, the real installer or the founder's graph:
the graph is a throwaway sqlite fixture and the "installer" is a stand-in that
writes only into the application directory, as ArchHub.iss does.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
from textwrap import dedent
import time
from types import SimpleNamespace
import venv

import pytest

from nodelang import quiet_update as qu

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_update_offer", ROOT / "03.TOOLS/packaging" / "windows" / "check_update_offer.py")
offer_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offer_check)

REVISION = "72bcaaecc5c3c69d83a3155c9b691c9b8cf5d8d1"
# Match the existing snapshot courts: inbox PowerShell runs inside release jobs.
PWSH = shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.skipif(os.name != "nt", reason="Uses the Windows venv redirector")
@pytest.mark.parametrize("safe", [True, False])
def test_update_checks_windows_venv_redirector_before_setup(tmp_path, safe):
    import psutil

    release = _build_output(tmp_path / "release", "20261117-2144-ac0151d", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20261117-2008-e924eb9", "2026-11-17T16:08:00Z")
    state = _fixture_state(tmp_path / "updater-state")
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    environment = app / (".venv" if safe else "other-launcher")
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "Scripts/python.exe"
    evidence = tmp_path / "invoked-setup.txt"
    worker = dedent("""
        import os, subprocess, sys
        from pathlib import Path

        sys.path[:0] = sys.argv[1:3]
        from nodelang import quiet_update as qu
        import psutil

        app, state, evidence = map(Path, sys.argv[3:6])
        safe = sys.argv[6] == "safe"
        redirector = psutil.Process(os.getppid())
        assert Path(redirector.exe()).resolve() == Path(sys.executable).resolve()
        redirector.info = {"pid": redirector.pid, "exe": redirector.exe()}

        def cleanup(directory):
            # The only termination candidate is this disposable process's own redirector.
            assert qu.stop_runtime_processes(directory, process_iter=lambda _attrs: [redirector]) == []

        def setup(argv, **kwargs):
            assert Path(argv[0]) == state / "updates" / qu.ASSET_NAME
            assert "/DIR=" + str(app) in argv and "/NOCLOSEAPPLICATIONS" in argv
            with evidence.open("x", encoding="utf-8") as proof:
                proof.write("Setup reached once")
            return subprocess.CompletedProcess(argv, 17)

        result = qu.apply_staged(state, app, runner=setup, stop_runtime=cleanup)
        if safe:
            assert result["status"] == "failed" and "exit 17" in result["reason"], result
        else:
            assert result["status"] == "failed" and "in-folder launcher" in result["reason"], result
    """)
    result = subprocess.run([str(python), "-I", "-B", "-c", worker,
                             str(Path(qu.__file__).resolve().parents[1]),
                             str(Path(psutil.__file__).resolve().parents[1]),
                             str(app), str(state), str(evidence), "safe" if safe else "refuse"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=25,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr, qu.staged_update(state, app))
    if safe:
        assert evidence.read_text(encoding="utf-8") == "Setup reached once"
    else:
        assert not evidence.exists()
    assert qu.staged_update(state, app)["status"] == "staged"


@pytest.mark.parametrize("denied", [True, False])
def test_setup_refuses_an_unreleased_process(tmp_path, monkeypatch, denied):
    import psutil
    from unittest.mock import Mock

    release = _build_output(tmp_path / "release", "next", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "ArchHub", "old", "2026-11-17T16:08:00Z")
    state = tmp_path / "updater-state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    process = Mock(pid=2000000000)
    process.info = {"pid": process.pid, "exe": str(app / "worker.exe")}
    if denied:
        process.terminate.side_effect = psutil.AccessDenied(process.pid)
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: [process])
    wait = Mock(return_value=([], [process]))
    monkeypatch.setattr(psutil, "wait_procs", wait)
    setup = Mock()
    result = qu.apply_staged(state, app, runner=setup)
    assert result["status"] == "failed" and not result["applied"] and result["staged"]
    assert str(process.pid) in result["reason"]
    assert wait.call_count == (0 if denied else 2)
    setup.assert_not_called()
    assert qu.staged_update(state, app)["status"] == "staged"


@pytest.mark.parametrize("phase", ["rolled_back", "applying", "awaiting_boot", "staged"])
@pytest.mark.parametrize("damage", [None, "missing", "changed"])
def test_boot_reconciles_a_matching_build_installed_by_direct_setup(tmp_path, phase, damage):
    release = _build_output(tmp_path / "release", "20261117-2144-ac0151d", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20261117-2008-e924eb9", "2026-11-17T16:08:00Z")
    state = _fixture_state(tmp_path / "updater-state")
    opener = _local_github(release)
    staged = qu.stage_if_newer(state, app, opener=opener)
    qu._marker(state / "updates", {**staged, "phase": phase, "rollback_reason": "Previous attempt failed"})

    calls = []
    _fake_installer(calls)([staged["installer"], "/DIR=" + str(app)])
    if damage:
        member = app / "nodelang" / "__release_marker__.py"
        if damage == "missing":
            member.unlink()
        else:
            member.write_text("not the installed manifest member")
        assert qu.begin_update_boot(state, app)["status"] == "applying"
        assert qu.confirm_applied(state, app).get("confirmed") is False
        assert qu._read_stage_marker(state / "updates")["phase"] == phase
        return
    assert qu.begin_update_boot(state, app)["status"] == "awaiting_boot"
    assert qu.staged_update(state, app)["status"] == "awaiting_boot"
    assert qu.confirm_applied(state, app)["status"] == "confirmed"
    assert qu.staged_update(state, app)["status"] == "confirmed"
    assert qu.stage_if_newer(state, app, opener=opener)["reason"] == "up to date"
    assert len(calls) == 1


@pytest.mark.parametrize("confirms", [True, False])
def test_maintainer_recovers_a_failed_launcher_and_requires_boot_ack(tmp_path, monkeypatch, confirms):
    from nodelang.canvas_triggers import TRIGGER_NODE

    monkeypatch.setitem(TRIGGER_NODE["params"], "file_poll_floor_seconds", 7)
    state = tmp_path / "state"
    updates = state / "updates"
    updates.mkdir(parents=True)
    app = tmp_path / "ArchHub"
    build_id = "20261117-2144-ac0151d"
    marker = {"build_id": build_id, "sha256": "0" * 64, "phase": "awaiting_boot"}
    qu._marker(updates, marker)
    calls = []

    def relaunch(directory):
        calls.append(directory)
        if len(calls) == 1:
            raise OSError("test spawn failure")
        return SimpleNamespace(poll=lambda: None)

    delays = []

    def boot(seconds):
        delays.append(seconds)
        if confirms:
            qu._marker(updates, {**marker, "phase": "confirmed"})

    monkeypatch.setattr(qu, "_claim_maintainer", lambda _app: True)
    monkeypatch.setattr(qu, "_desktop_running", lambda: False)
    monkeypatch.setattr(qu, "state_directory", lambda: state)
    monkeypatch.setattr(qu, "check_for_update", lambda *_args: {"staged": True, "status": "staged"})
    monkeypatch.setattr(qu, "apply_staged", lambda *_args, **_kwargs: {"applied": True, "build_id": build_id})
    monkeypatch.setattr(qu, "_relaunch", relaunch)
    assert qu.maintain(app, sleep=boot) == (0 if confirms else 1)
    assert calls == [app, app]
    assert delays == [7] * (1 if confirms else 150)


@pytest.mark.parametrize("fault", ["refused", "empty_tag", "empty_revision", "wrong_tag", "wrong_revision",
                                  "wrong_build", "empty_asset", "wrong_asset", "string_ok", "malformed",
                                  "missing_build_heading", "missing_build_id", "missing_sha256",
                                  "native_checker", "auth", "create", "edit", "valid"])
def test_publisher_fails_closed_before_github_mutations(tmp_path, monkeypatch, fault):
    if not PWSH:
        pytest.skip("PowerShell required")
    monkeypatch.delenv("PSModulePath", raising=False)
    release = _build_output(tmp_path / "release", "20261108-test", "2026-11-08T01:00:00Z")
    report = offer_check.check(release)
    if fault == "refused":
        report = {"ok": False, "refused": "HTTP 422", "offer": {"tag": "", "source_revision": ""}}
    elif fault in ("empty_tag", "empty_revision", "wrong_tag", "wrong_revision", "wrong_build"):
        field = {"tag": "tag", "revision": "source_revision", "build": "build_id"}[fault.split("_")[1]]
        report["offer"][field] = "" if fault.startswith("empty") else "wrong"
    elif fault in ("empty_asset", "wrong_asset"):
        manifest = json.loads((release / "release.json").read_text())
        manifest["asset_name"] = "" if fault == "empty_asset" else "other.exe"
        (release / "release.json").write_text(json.dumps(manifest))
    elif fault == "string_ok":
        report["ok"] = "true"
    elif fault == "missing_build_heading":
        notes = (release / "release-notes.md").read_text(encoding="utf-8").replace("## Build\n", "")
        (release / "release-notes.md").write_bytes(notes.encode("utf-8"))
    elif fault == "missing_build_id":
        notes = re.sub(r"(?m)^BUILD_ID:.*\n", "", (release / "release-notes.md").read_text(encoding="utf-8"))
        (release / "release-notes.md").write_bytes(notes.encode("utf-8"))
    elif fault == "missing_sha256":
        notes = re.sub(r"(?m)^SHA256 .*\n", "", (release / "release-notes.md").read_text(encoding="utf-8"))
        (release / "release-notes.md").write_bytes(notes.encode("utf-8"))
    report_path = tmp_path / "report.json"
    report_path.write_text("not JSON" if fault == "malformed" else json.dumps(report))
    # Native stand-ins on PATH: no real checker, network, or GitHub writes.
    (tmp_path / "checker.cmd").write_text(
        '@echo off\r\ntype "%REPORT_PATH%"\r\nexit /b ' + ("7" if fault == "native_checker" else "0") + '\r\n')
    (tmp_path / "gh.cmd").write_text(
        '@echo off\r\necho %*>>"%GH_CALLS%"\r\n'
        'if "%1"=="auth" if "%GH_FAIL%"=="auth" exit /b 9\r\n'
        'if "%2"=="create" if "%GH_FAIL%"=="create" exit /b 9\r\n'
        'if "%2"=="edit" if "%GH_FAIL%"=="edit" exit /b 9\r\nexit /b 0\r\n')
    calls = tmp_path / "gh-calls.txt"
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("REPORT_PATH", str(report_path))
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.setenv("GH_FAIL", fault)
    launcher = tmp_path / "publish-parent.ps1"
    launcher.write_text('''param($Publisher, $ReleaseDirectory, $PythonPath, $ExpectedSourceRevision, [switch]$DryRun)
# Reproduce the build caller's stale native exit status in the parent scope.
$ErrorActionPreference = 'Stop'
$LASTEXITCODE = 0
& $Publisher -ReleaseDirectory $ReleaseDirectory -PythonPath $PythonPath -ExpectedSourceRevision $ExpectedSourceRevision -DryRun:$DryRun
''')
    command = [PWSH, "-NoProfile", "-NonInteractive", "-File",
               str(launcher), "-Publisher",
               str(ROOT / "03.TOOLS/packaging/windows/publish_release.ps1"),
               "-ReleaseDirectory", str(release), "-PythonPath", str(tmp_path / "checker.cmd"),
               "-ExpectedSourceRevision", REVISION]
    if fault == "valid":
        command.append("-DryRun")
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    recorded = calls.read_text().splitlines() if calls.exists() else []
    assert result.returncode == (0 if fault == "valid" else 1), result.stdout + result.stderr
    assert len(recorded) == {"auth": 1, "create": 2, "edit": 3}.get(fault, 0), recorded
    if fault == "valid":
        assert "PLAN 1: gh release create build-20261108-test" in result.stdout
    elif fault not in ("auth", "create", "edit"):
        assert "PLAN 1" not in result.stdout


def test_build_does_not_auto_publish_after_refused_dry_run(tmp_path, monkeypatch):
    if not PWSH:
        pytest.skip("PowerShell required")
    monkeypatch.delenv("PSModulePath", raising=False)
    publisher = tmp_path / "packaging/windows/publish_release.ps1"
    publisher.parent.mkdir(parents=True)
    publisher.write_text('param($ReleaseDirectory, $ExpectedSourceRevision, $PythonPath, [switch]$DryRun)\n'
                         'Add-Content -LiteralPath $env:GH_CALLS -Value "dryrun=$DryRun"\n'
                         "if ($DryRun) { throw 'HTTP 422: refused' }\n")
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    harness = tmp_path / "build-tail.ps1"
    harness.write_text('''param($Build, $Root)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
$tail = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$env:GITHUB_ACTIONS'
}, $true)
if (-not $tail) { throw 'missing automatic publication branch' }
$selectedRoot = $Root; $output = $Root; $sourceRevision = 'fixture'; $PythonPath = 'fixture'
$statusName = 'status.txt'; $utf8 = [Text.UTF8Encoding]::new($false)
& ([scriptblock]::Create($tail.ElseClause.Extent.Text.Trim().Substring(1).TrimEnd().TrimEnd('}')))
''')
    result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness),
                             "-Build", str(ROOT / "03.TOOLS/installer/build_release.ps1"),
                             "-Root", str(tmp_path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "HTTP 422: refused" in result.stderr
    assert calls.read_text().splitlines() == ["dryrun=True"]
    assert not (tmp_path / "status.txt").exists()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _installer_bytes(build_id: str, built_at: str) -> bytes:
    """Stand-in installer: the files it lays into {app}, nothing else."""
    metadata = json.dumps({"format": 1, "build_id": build_id, "built_at": built_at},
                          separators=(",", ":")) + "\n"
    return json.dumps({"BUILD_ID": build_id, "BUILD_METADATA.json": metadata,
                       "app/__init__.py": "", "bridges/fixture.dll": "stub",
                       "nodelang/__release_marker__.py": "BUILD = %r\n" % build_id}).encode("utf-8")


def _build_output(folder: Path, build_id: str, built_at: str) -> Path:
    """The six files build_release.ps1 writes for a release-mode build."""
    folder.mkdir(parents=True)
    asset = _installer_bytes(build_id, built_at)
    (folder / qu.ASSET_NAME).write_bytes(asset)
    metadata = json.dumps({"format": 1, "build_id": build_id, "built_at": built_at},
                          separators=(",", ":")) + "\n"
    (folder / "BUILD_METADATA.json").write_bytes(metadata.encode("utf-8"))
    (folder / "source-manifest.tsv").write_bytes(b"ARCHHUB_RELEASE_SOURCE_MANIFEST_V2\n")
    (folder / "studio-build.json").write_bytes(b'{"format":1}\n')
    manifest = {
        "format": 1, "build_id": build_id, "built_at": built_at,
        "build_metadata_sha256": _sha(metadata.encode("utf-8")),
        "source_revision": REVISION,
        "payload_manifest": "source-manifest.tsv",
        "payload_manifest_sha256": _sha((folder / "source-manifest.tsv").read_bytes()),
        "studio_manifest": "studio-build.json",
        "studio_manifest_sha256": _sha((folder / "studio-build.json").read_bytes()),
        "studio_files": offer_check.STUDIO_FILES,
        "asset_name": qu.ASSET_NAME, "asset_sha256": _sha(asset), "asset_bytes": len(asset),
    }
    (folder / "release.json").write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")
    notes = "## Build\nBUILD_ID: %s\nBUILT_AT: %s\nSHA256 %s: %s\nSOURCE_REVISION: %s\n" % (
        build_id, built_at, qu.ASSET_NAME, _sha(asset), REVISION)
    (folder / "release-notes.md").write_bytes(notes.encode("utf-8"))
    return folder


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _local_github(release_dir: Path, served_asset: bytes | None = None, downloads=None):
    """Serve the release exactly as GitHub would once publish_release.ps1 ran."""
    offer = offer_check.reconcile(release_dir)
    download_url = offer["github_release"]["assets"][0]["browser_download_url"]

    def opener(request, timeout=0):
        url = getattr(request, "full_url", request)
        if url == qu.RELEASE_API:
            return _Body(json.dumps(offer["github_release"]).encode("utf-8"))
        if url == download_url:
            if downloads is not None:
                downloads.append(url)
            data = served_asset if served_asset is not None else (release_dir / qu.ASSET_NAME).read_bytes()
            return _Body(data)
        raise AssertionError("unexpected network request: %s" % url)
    return opener


def _installed_app(folder: Path, build_id: str, built_at: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "BUILD_ID").write_text(build_id, encoding="utf-8")
    (folder / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": build_id, "built_at": built_at}) + "\n", encoding="utf-8")
    return folder


def _fixture_state(folder: Path) -> Path:
    """A throwaway graph (the persisted Cell shape, in WAL) plus user config."""
    folder.mkdir(parents=True)
    connection = sqlite3.connect(folder / "archhub-test.universal.sqlite3")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE cells (id TEXT PRIMARY KEY, link0 TEXT, link1 TEXT, atom BLOB)")
    connection.executemany("INSERT INTO cells VALUES (?, ?, ?, ?)",
                           [("c%03d" % i, "c%03d" % (i - 1), "", ("atom-%d" % i).encode()) for i in range(200)])
    connection.commit()
    connection.close()
    (folder / "settings.json").write_text(json.dumps({"default_model": "fixture", "theme": "dark"}), encoding="utf-8")
    (folder / "window-layout.json").write_text('{"panels":["Properties"]}', encoding="utf-8")
    return folder


def _state_fingerprint(state: Path) -> dict:
    return {str(p.relative_to(state)): _sha(p.read_bytes())
            for p in sorted(state.rglob("*")) if p.is_file() and "updates" not in p.relative_to(state).parts}


def _fake_installer(calls):
    """Inno stand-in: lays its files into /DIR= only, as ArchHub.iss does."""
    class _Done:
        returncode = 0

    def runner(argv, **_options):
        from nodelang.host_addin_retarget import HEADER, save_receipt

        calls.append(argv)
        target = Path(next(a for a in argv if a.startswith("/DIR="))[len("/DIR="):])
        payload = json.loads(Path(argv[0]).read_bytes())
        build_id = payload.pop("BUILD_ID")
        manifest = [HEADER, "path\tsha256"]
        for relative, text in payload.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = text.encode("utf-8")
            destination.write_bytes(content)
            if "/" in relative:
                manifest.append(relative + "\t" + _sha(content))
        raw = ("\n".join(manifest) + "\n").encode("utf-8")
        (target / "source-manifest.tsv").write_bytes(raw)
        save_receipt(target, raw, {}, ())
        marker = target / "BUILD_ID"
        marker.write_text(build_id, encoding="utf-8")
        # Some Windows filesystems cache a recent wall-clock tick for writes.
        os.utime(marker, ns=(time.time_ns(), time.time_ns()))
        return _Done()
    return runner


def test_newer_local_release_is_verified_applied_confirmed_and_keeps_graph_and_config(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    before = _state_fingerprint(state)
    downloads = []

    staged = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert staged["staged"] is True and staged["status"] == "staged", staged
    assert staged["build_id"] == "20260924-0900-abc1234" and staged["bytes_verified"] is True
    assert staged["sha256"] == _sha((release / qu.ASSET_NAME).read_bytes())
    assert _sha((state / "updates" / qu.ASSET_NAME).read_bytes()) == staged["sha256"]
    assert len(downloads) == 1
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae", "staging never installs"

    calls = []
    applied = qu.apply_staged(state, app, runner=_fake_installer(calls))
    assert applied["applied"] is True and applied["status"] == "awaiting_boot", applied
    assert calls and "/VERYSILENT" in calls[0] and "/DIR=" + str(app) in calls[0]
    confirmed = qu.confirm_applied(state, app)
    assert confirmed["confirmed"] is True and confirmed["status"] == "confirmed", confirmed
    assert qu.installed_build_id(app) == "20260924-0900-abc1234"

    assert _state_fingerprint(state) == before, "update changed the graph or user config"
    connection = sqlite3.connect("file:%s?mode=ro" % (state / "archhub-test.universal.sqlite3").as_posix(), uri=True)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 200
    finally:
        connection.close()

    again = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert again == {"staged": False, "reason": "up to date", "build_id": "20260924-0900-abc1234"}
    assert len(downloads) == 1, "an installed build is never downloaded again"


@pytest.mark.parametrize("offered_id,offered_at,reason", [
    ("20260923-1945-72bcaae", "2026-09-23T15:57:49Z", "up to date"),
    ("20260923-1946-rebuilt", "2026-09-23T15:57:49Z", "not newer"),
    ("20260918-1700-b63fdf3", "2026-09-18T12:43:29Z", "not newer"),
])
def test_equal_or_older_release_is_refused_without_download(tmp_path, offered_id, offered_at, reason):
    release = _build_output(tmp_path / "release", offered_id, offered_at)
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    downloads = []
    out = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert out["staged"] is False and reason in out["reason"], out
    assert downloads == []
    assert not (state / "updates" / qu.ASSET_NAME).exists()
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_corrupt_download_is_refused_and_nothing_is_staged_or_installed(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    good = (release / qu.ASSET_NAME).read_bytes()
    corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
    out = qu.stage_if_newer(state, app, opener=_local_github(release, served_asset=corrupt))
    assert out["staged"] is False and "did not match published SHA-256" in out["reason"], out
    assert not (state / "updates" / qu.ASSET_NAME).exists()
    assert not (state / "updates" / "staged.json").exists()
    assert not list((state / "updates").glob(".download-*")), "partial download retained"
    refused = qu.apply_staged(state, app, runner=_fake_installer([]))
    assert refused["applied"] is False
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_staged_installer_altered_on_disk_is_never_run(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"] is True
    (state / "updates" / qu.ASSET_NAME).write_bytes(b"swapped after verification")
    calls = []
    out = qu.apply_staged(state, app, runner=_fake_installer(calls))
    assert out["applied"] is False and "SHA-256" in out["reason"], out
    assert calls == [] and qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_publish_check_refuses_build_output_whose_bytes_do_not_reconcile(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with (release / qu.ASSET_NAME).open("ab") as stream:
        stream.write(b"!")
    with pytest.raises(offer_check.Refused, match="asset_bytes.*asset_sha256|asset_sha256"):
        offer_check.reconcile(release)
    release2 = _build_output(tmp_path / "release2", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with pytest.raises(offer_check.Refused, match="source_revision"):
        offer_check.reconcile(release2, expected_revision="0" * 40)


def test_a_prose_release_body_is_unreadable_to_installed_users(tmp_path):
    """build-20260918-1700-b63fdf3 was uploaded by hand with a prose body:
    every installed updater reads it as 'no release information'."""
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    offer = offer_check.reconcile(release)
    assert offer_check.updater_reads(offer["github_release"])["build_id"] == "20260924-0900-abc1234"
    prose = dict(offer["github_release"], body="Studio built from the founder's design.")
    assert offer_check.updater_reads(prose) is None
    (release / "release-notes.md").write_bytes(b"Studio built from the founder's design.\n")
    with pytest.raises(offer_check.Refused, match="notes"):
        offer_check.reconcile(release)


def test_release_notes_must_keep_build_block_and_parse_with_quiet_update(tmp_path):
    """F343: prose release notes are admitted only when they keep the ## Build
    block (exactly one BUILD_ID and one SHA256 ArchHub-Setup-0.exe line)."""
    build_id = "20261113-0022-60dc0f8"
    built_at = "2026-11-12T20:22:42Z"
    release = _build_output(tmp_path / "release", build_id, built_at)
    asset_sha = _sha((release / qu.ASSET_NAME).read_bytes())
    valid_with_prose = (
        "## What changed\n\n- Settings follows the approved board.\n\n"
        "## Build\n```\n"
        f"BUILD_ID: {build_id}\n"
        f"BUILT_AT: {built_at}\n"
        f"SHA256 {qu.ASSET_NAME}: {asset_sha}\n"
        f"SOURCE_REVISION: {REVISION}\n"
        "```\n"
    )
    (release / "release-notes.md").write_bytes(valid_with_prose.encode("utf-8"))
    offer = offer_check.reconcile(release)
    parsed = offer_check.updater_reads(offer["github_release"])
    assert parsed is not None
    assert parsed["build_id"] == build_id
    assert parsed["sha256"] == asset_sha

    for bad_notes in (
        valid_with_prose.replace("## Build\n", ""),
        re.sub(r"(?m)^BUILD_ID:.*\n", "", valid_with_prose),
        re.sub(r"(?m)^SHA256 .*\n", "", valid_with_prose),
        valid_with_prose + f"BUILD_ID: {build_id}\n",
        valid_with_prose + f"SHA256 {qu.ASSET_NAME}: {asset_sha}\n",
        f"BUILD_ID: {build_id}\nBUILT_AT: {built_at}\nSHA256 {qu.ASSET_NAME}: {asset_sha}\n## Build\n",
    ):
        (release / "release-notes.md").write_bytes(bad_notes.encode("utf-8"))
        with pytest.raises(offer_check.Refused, match="notes"):
            offer_check.reconcile(release)


OLDER_LIVE = lambda *_repository: {"build_id": "20260918-1700-b63fdf3", "built_at": "2026-09-18T12:43:29Z"}
FREE_AND_PUSHED = lambda url: 404 if "/git/ref/tags/" in url else 200


def test_publish_check_orders_against_live_latest_even_when_its_body_is_unreadable(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    ok = offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                           live_manifest=OLDER_LIVE)
    assert ok["ok"] and ok["remote"] == {"tag_free": True, "source_revision_pushed": True}
    with pytest.raises(offer_check.Refused, match="not newer than the live latest"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                          live_manifest=lambda *_r: {"build_id": "later", "built_at": "2026-09-25T00:00:00Z"})
    with pytest.raises(offer_check.Refused, match="cannot verify the live latest"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                          live_manifest=lambda *_r: None)
    with pytest.raises(offer_check.Refused, match="already exists"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=lambda url: 200,
                          live_manifest=OLDER_LIVE)
    with pytest.raises(offer_check.Refused, match="push it first"):
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: 404)


def test_studio_file_count_must_match_the_reviewed_build(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    assert offer_check.reconcile(release)["build_id"] == "20260924-0900-abc1234"
    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
    for wrong in (13, 9, "10", None):
        manifest["studio_files"] = wrong
        (release / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(offer_check.Refused, match="studio_files"):
            offer_check.reconcile(release)


def test_repository_is_passed_through_and_only_the_updaters_repository_is_readable(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    offer = offer_check.reconcile(release, repository="someone/fork")
    assert offer["github_release"]["assets"][0]["browser_download_url"].startswith(
        "https://github.com/someone/fork/releases/download/")
    seen, manifests = [], []
    def status(url):
        seen.append(url)
        return FREE_AND_PUSHED(url)
    with pytest.raises(offer_check.Refused, match="would not read"):
        offer_check.check(release, repository="someone/fork", live=True, status=status,
                          latest_reader=lambda: None, live_manifest=lambda r: manifests.append(r))
    assert seen == [], "a release the updater cannot read is refused before any live read"
    offer_check.check(release, repository="Fargaly/ArchHub", live=True, status=status,
                      latest_reader=lambda: None, live_manifest=lambda r: manifests.append(r) or OLDER_LIVE())
    assert manifests == ["Fargaly/ArchHub"]
    assert seen and all(u.startswith("https://api.github.com/repos/Fargaly/ArchHub/") for u in seen)
    publish = (ROOT / "03.TOOLS/packaging" / "windows" / "publish_release.ps1").read_text(encoding="utf-8")
    assert "'--repository', $Repository" in publish
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "-Repository $env:GH_REPO" in workflow


@pytest.mark.parametrize("code", [403, 429, 500])
def test_rate_limited_or_forbidden_github_reads_refuse_and_never_read_as_tag_exists(tmp_path, code):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with pytest.raises(offer_check.Refused) as refused:
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: code if "/git/ref/tags/" in url else 200)
    assert "cannot verify the tag" in str(refused.value) and "already exists" not in str(refused.value)
    with pytest.raises(offer_check.Refused, match="cannot verify the source revision"):
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: 404 if "/git/ref/tags/" in url else code)


def test_live_reads_use_gh_token_when_present_and_are_anonymous_otherwise(monkeypatch):
    sent = []
    class _Answer:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_exc): return False
    def urlopen(request, timeout=0):
        sent.append(request.get_header("Authorization"))
        return _Answer()
    monkeypatch.setattr(offer_check.urllib.request, "urlopen", urlopen)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert offer_check._status("https://api.github.com/repos/Fargaly/ArchHub/commits/x") == 200
    monkeypatch.setenv("GH_TOKEN", "fixture-credential-not-real")
    assert offer_check._status("https://api.github.com/repos/Fargaly/ArchHub/commits/x") == 200
    assert sent == [None, "Bearer fixture-credential-not-real"]


def test_real_installer_deletes_only_named_application_files_never_user_state():
    iss = (ROOT / "03.TOOLS/installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert re.search(r"(?m)^DefaultDirName=\{localappdata\}\\ArchHub\s*$", iss)
    uninstall = iss.split('[UninstallDelete]', 1)[1].split('\n[', 1)[0]
    removed = re.findall(r'(?m)^Type:\s*(\w+);\s*Name:\s*"([^"]+)"', uninstall)
    assert removed == [], removed
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    entries = re.findall(r'(?m)^Type:\s*(\w+);\s*Name:\s*"([^"]+)"', section)
    assert entries == [], entries
    from nodelang.user_paths import state_directory
    assert state_directory() == Path(os.environ["ARCHHUB_TEST_STATE_DIR"])
    assert not {'state', 'updates', 'web-profile'} & set(qu._PAYLOAD_DIRS), "rollback must not own user data"

@pytest.mark.parametrize("exit_code", [0, 10])
def test_postinstall_failure_is_reported_and_stale_identity_never_applied(tmp_path, exit_code):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    before = _state_fingerprint(state)
    qu.stage_if_newer(state, app, opener=_local_github(release))

    def failed_installer(argv, **options):
        assert '/DIR=' + str(app) in argv
        log = Path(next(arg[len('/LOG='):] for arg in argv if arg.startswith('/LOG=')))
        log.write_text('ArchHub Setup refused: Post-install failed: Product prune failed.\n')
        return type('Result', (), {'returncode': exit_code})()

    result = qu.apply_staged(state, app, runner=failed_installer, stop_runtime=None)
    assert result['applied'] is False and result['status'] == 'failed'
    assert result['reason'] == 'installer failed: Post-install failed: Product prune failed.'
    assert (app / 'BUILD_ID').read_text() == '20260923-1945-72bcaae'
    assert _state_fingerprint(state) == before


@pytest.mark.parametrize("outcome", ["installed", "failed"])
def test_hand_off_waits_for_the_closing_desktop_then_installs_or_reopens_the_old_build(tmp_path, monkeypatch, outcome):
    """UPDATERWORKS: Restart used to relaunch while the old desktop still held its profile; the
    new launch gave up and ArchHub stayed closed. The helper waits for the desktop and its
    in-folder launcher, installs once, and always leaves ArchHub open after a Restart."""
    state, app = tmp_path / "state", tmp_path / "ArchHub"
    desktop = iter([True, True, False, False, False])
    attempts, relaunched, reopened = [], [], []

    def apply(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:  # the old launcher is still exiting
            return {"applied": False, "status": "failed", "reason": qu._LAUNCHER_HOLDS_INSTALL}
        if outcome == "installed":
            return {"applied": True, "build_id": "20261120-0100-aaaaaaa"}
        return {"applied": False, "status": "failed", "reason": "installer failed (exit 5)"}

    monkeypatch.setattr(qu, "state_directory", lambda: state)
    monkeypatch.setattr(qu, "_desktop_running", lambda: next(desktop))
    monkeypatch.setattr(qu, "apply_staged", apply)
    monkeypatch.setattr(qu, "_relaunch", lambda directory: relaunched.append(directory))
    monkeypatch.setattr(qu, "_reopen_after_update",
                        lambda _state, directory, build, sleep, tray=False: reopened.append(build) or True)
    code = qu.hand_off(app, relaunch=True, sleep=lambda _seconds: None)
    log = (state / "logs" / "updates.log").read_text(encoding="utf-8")
    assert len(attempts) == 2
    if outcome == "installed":
        assert (code, reopened, relaunched) == (0, ["20261120-0100-aaaaaaa"], [])
        assert "update: installed 20261120-0100-aaaaaaa" in log and "update: confirmed" in log
    else:
        assert (code, reopened, relaunched) == (1, [], [app])
        assert "update: error installer failed (exit 5)" in log


def test_hand_off_never_installs_over_a_desktop_that_stays_open(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(qu, "state_directory", lambda: state)
    monkeypatch.setattr(qu, "_desktop_running", lambda: True)
    monkeypatch.setattr(qu, "apply_staged", lambda *_a, **_k: pytest.fail("installed over an open desktop"))
    monkeypatch.setattr(qu, "_relaunch", lambda _d: pytest.fail("second desktop started"))
    assert qu.hand_off(tmp_path / "ArchHub", relaunch=True, sleep=lambda _s: None, wait_seconds=2) == 0
    assert "install waits for the next start" in (state / "logs" / "updates.log").read_text(encoding="utf-8")


def test_restart_and_quit_hand_the_install_to_one_hidden_helper(tmp_path, monkeypatch):
    from nodelang import nograph_launcher

    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **options: started.append((argv, options)))
    for relaunch in (True, False):
        update = SimpleNamespace(apply_on_quit=lambda: True, close=lambda: None)
        lock = SimpleNamespace(close=lambda: None)
        nograph_launcher._arm_staged_update(update, tmp_path, tmp_path / "ArchHub", lock, relaunch=relaunch)
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert len(started) == 2
    for (argv, options), relaunch in zip(started, (True, False)):
        assert argv[4:6] == ["--apply-staged", str(tmp_path / "ArchHub")]
        assert ("--relaunch" in argv) is relaunch
        assert "wscript" not in " ".join(argv).lower()
        assert options["creationflags"] & hidden == hidden


def test_feed_read_retries_quietly_and_logs_why_it_failed(tmp_path):
    import urllib.error

    calls, waits = [], []

    def limited(request, timeout=0):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "rate limit", {"X-RateLimit-Remaining": "0"}, None)

    assert qu.read_latest_release_retrying(limited, (2, 8), waits.append) is None
    assert (len(calls), waits, qu.read_latest_release.cause) == (3, [2, 8], "HTTP 403 rate limited")

    def gone(request, timeout=0):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)

    calls.clear()
    assert qu.read_latest_release_retrying(gone, (2, 8), waits.append) is None
    assert (len(calls), qu.read_latest_release.cause) == (1, "HTTP 404")
    state, app = tmp_path / "state", tmp_path / "app"
    app.mkdir()
    qu.note_check(state, app, {"staged": False, "build_id": "", "reason": "no release information",
                               "cause": "HTTP 403 rate limited"})
    assert ("update: error no release information (HTTP 403 rate limited)"
            in (state / "logs" / "updates.log").read_text(encoding="utf-8"))


def test_review1_busy_desktop_refuses_every_restart_path(monkeypatch):
    """Only the desktop's own live work holds the update: chat turns, canvas runs, running automations.
    Workshop agents work around the clock; counting them would mean the update never installs."""
    import threading
    from nodelang import nograph_server
    from nodelang.application_update import ApplicationUpdate, UpdateRestartRefused
    from nodelang.nograph_launcher import _update_refusal

    monkeypatch.setattr(nograph_server, "_declarations",
                        lambda: [{"current": True, "status": "working"}] * 5)  # agents busy all day
    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    server.busy_reason = lambda: nograph_server.NoGraphServer.busy_reason(server)
    assert _update_refusal(server) is None
    for change, words in ((lambda: setattr(server, "_canvas_jobs", 1), "canvas run"),
                          (lambda: server.triggers.running.add("job"), "automation"),
                          (lambda: server._chat_turns.add(7), "chat answer")):
        server._canvas_jobs, server.triggers.running, server._chat_turns = 0, set(), set()
        change()
        assert words in _update_refusal(server)
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update._closed, update._state, update._worker, update._lock = False, "ready", None, threading.RLock()
    update._prerelease = False
    update._policy = lambda: {"auto_apply_on_quit": True}
    update._request_restart = lambda: pytest.fail("restarted over live work")
    update._restart_refusal = lambda: _update_refusal(server)
    assert update.apply_on_quit() is False  # Quit and idle/tray auto-install wait too
    with pytest.raises(UpdateRestartRefused, match="chat answer"):
        update.reload()


def test_review2_helper_and_relaunch_break_away_from_the_job_with_a_fallback(monkeypatch):
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    seen = []

    def refusing_job(argv, **options):
        seen.append(options["creationflags"])
        if breakaway and options["creationflags"] & breakaway:
            raise PermissionError("job forbids breakaway")
        return SimpleNamespace(argv=argv)

    monkeypatch.setattr(subprocess, "Popen", refusing_job)
    assert qu.spawn_detached(["x.exe"]).argv == ["x.exe"]
    assert seen == ([hidden | breakaway, hidden] if breakaway else [hidden])
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **options: started.append((argv, options["creationflags"])))
    qu._relaunch(Path("C:/ArchHub"), True)
    assert started[0][0][-2:] == [str(Path("C:/ArchHub") / "ArchHub.vbs"), "--tray"]
    assert started[0][1] == hidden | breakaway


def test_review3_failed_setup_is_recorded_and_never_rerun_by_the_next_start(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = tmp_path / "state"
    downloads = []
    opener = _local_github(release, downloads=downloads)
    assert qu.stage_if_newer(state, app, opener=opener)["staged"] is True
    failed = qu.apply_staged(state, app, runner=lambda argv, **o: SimpleNamespace(returncode=1), stop_runtime=None)
    assert failed["applied"] is False and failed["status"] == "failed"
    marker = json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
    assert marker["phase"] == "rolled_back" and "installer failed (exit 1)" in marker["rollback_reason"]
    # launcher.py runs apply_staged at start only for {"staged": True, "status": "staged"}.
    boot = qu.begin_update_boot(state, app)
    assert not (boot.get("staged") and boot.get("status") == "staged")
    assert qu.apply_staged(state, app, runner=lambda *a, **o: pytest.fail("Setup ran again"))["applied"] is False
    # The failed build id is skipped on every later check: no re-download, nothing staged.
    for _check in range(3):
        assert qu.stage_if_newer(state, app, opener=opener)["staged"] is False
    assert len(downloads) == 1
    # A strictly newer release replaces it and is staged normally.
    newer = _build_output(tmp_path / "release2", "20260925-0900-def5678", "2026-09-25T05:00:00Z")
    fresh = qu.stage_if_newer(state, app, opener=_local_github(newer, downloads=downloads))
    assert fresh["staged"] is True and fresh["build_id"] == "20260925-0900-def5678" and len(downloads) == 2


def test_review4_closing_desktop_stops_feed_retries_at_once():
    import threading
    import urllib.error

    calls = []

    def offline(request, timeout=0):
        calls.append(1)
        raise urllib.error.URLError(OSError("offline"))

    closing = threading.Event()
    closing.set()
    assert qu.read_latest_release_retrying(offline, (2, 8), closing.wait) is None
    assert len(calls) == 1


def test_review5_an_update_from_the_tray_reopens_in_the_tray(tmp_path, monkeypatch):
    from nodelang import nograph_launcher

    shown = []
    assert nograph_launcher._open_launch(["--tray"], {}, lambda: shown.append(1), lambda _d: shown.append(2)) is None
    assert shown == []
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **options: started.append(argv))
    update = SimpleNamespace(apply_on_quit=lambda: True, close=lambda: None)
    nograph_launcher._arm_staged_update(update, tmp_path, tmp_path / "ArchHub", SimpleNamespace(close=lambda: None),
                                        relaunch=True, tray=True)
    assert started[0][-2:] == ["--relaunch", "--tray"]
    reopened = []
    monkeypatch.setattr(qu, "state_directory", lambda: tmp_path / "state")
    monkeypatch.setattr(qu, "_desktop_running", lambda: False)
    monkeypatch.setattr(qu, "apply_staged", lambda *a, **k: {"applied": True, "build_id": "b"})
    monkeypatch.setattr(qu, "_reopen_after_update", lambda *a, sleep, tray: reopened.append(tray) or True)
    assert qu.hand_off(tmp_path / "ArchHub", relaunch=True, tray=True, sleep=lambda _s: None) == 0
    assert reopened == [True]


@pytest.mark.parametrize("arguments, tray_available, shown", [
    (["--tray"], True, False),             # update relaunch from the tray: never takes his screen
    (["--tray", "--baboom"], True, False),
    (["--tray"], False, True),             # no tray to live in: the window is the only way back
    ([], True, True),                      # a normal start opens the Studio
])
def test_a_tray_start_never_shows_the_window(arguments, tray_available, shown):
    """Both the cold-start loading card and the Studio open go through this one decision."""
    from nodelang.nograph_launcher import _show_unless_tray

    calls = []
    window = SimpleNamespace(show=lambda: calls.append("show"))
    assert _show_unless_tray(window, arguments, tray_available) is (not shown)
    assert calls == (["show"] if shown else [])
