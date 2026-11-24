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
import sys
from tempfile import TemporaryDirectory
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
    # A Setup that ran and failed is recorded (never rerun at every start); a refusal before Setup stays staged.
    assert qu.staged_update(state, app)["status"] == ("rolled_back" if safe else "staged")


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
    monkeypatch.setattr(qu, "_session_zero", lambda _pid: False)  # the stand-in runs in the user's session
    wait = Mock(return_value=([], [process]))
    monkeypatch.setattr(psutil, "wait_procs", wait)
    setup = Mock()
    result = qu.apply_staged(state, app, runner=setup)
    assert result["status"] == "failed" and not result["applied"] and result["staged"]
    assert str(process.pid) in result["reason"]
    assert wait.call_count == (0 if denied else 2)
    setup.assert_not_called()
    assert qu.staged_update(state, app)["status"] == "staged"


def _fake_process(pid, exe):
    from unittest.mock import Mock
    process = Mock(pid=pid)
    process.info = {"pid": pid, "exe": exe}
    return process


@pytest.mark.parametrize("system_session", [True, False])
def test_registry_bare_name_with_install_cwd_is_never_a_termination_candidate(tmp_path, monkeypatch, system_session):
    """Build 18 field defect: psutil names PID 420 "Registry" by bare name; with cwd = the install folder
    (ArchHub.vbs sets it) the name resolved under the install and the update refused at every launch."""
    import psutil

    app = tmp_path / "ArchHub"
    app.mkdir()
    monkeypatch.chdir(app)  # exactly what ArchHub.vbs does
    assert Path("Registry").resolve().is_relative_to(app.resolve())  # the trap the old selection fell into
    registry = _fake_process(420, "Registry")
    system = _fake_process(4, "System")
    compression = _fake_process(2000000003, "Memory Compression")
    owned = _fake_process(2000000001, str(app / "nodelang" / "worker.exe"))
    external = _fake_process(2000000002, r"C:\Windows\System32\cmd.exe")
    sessions = []

    def session_zero(pid):
        sessions.append(pid)
        return system_session and pid in (4, 420, 2000000003)

    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: (list(procs), []))
    stopped = qu.stop_runtime_processes(app, session_zero=session_zero,
                                        process_iter=lambda _attrs: [registry, system, compression, owned, external])
    assert stopped == [2000000001]
    owned.terminate.assert_called_once()
    for skipped in (registry, system, compression, external):
        skipped.terminate.assert_not_called()
        skipped.kill.assert_not_called()
    # The bare names and the external program are refused on their path alone, before any session read.
    assert sessions == [2000000001]


def test_an_owned_program_in_session_zero_is_left_alone(tmp_path, monkeypatch):
    import psutil

    app = tmp_path / "ArchHub"
    service = _fake_process(2000000004, str(app / "bridges" / "service.exe"))
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: pytest.fail("nothing to wait for"))
    assert qu.stop_runtime_processes(app, session_zero=lambda _pid: True,
                                     process_iter=lambda _attrs: [service]) == []
    service.terminate.assert_not_called()


_SUPERVISOR = r"C:\Users\x\AppData\Local\Python\pythoncore-3.14-64\python.exe"
_HOSTS = {"cursor": r"C:\Users\x\AppData\Local\Programs\cursor\Cursor.exe",
          "claude": r"C:\Users\x\.local\bin\claude.exe",
          "codex": r"C:\Users\x\AppData\Roaming\npm\node_modules\codex\codex.exe",
          "opencode": r"C:\Users\x\AppData\Local\Programs\OpenCode\OpenCode.exe"}


def _transport_chain(app, host, supervised=True):
    """The real shape seen live: agent -> supervisor (ArchHub-Runtime, base Python) -> install venv python."""
    connector = (str(app / ".venv" / "Scripts" / "python.exe"),
                 "python.exe -I -B -c import runpy,sys;runpy.run_module('nodelang.native_agent_mcp') " + str(app))
    if not supervised:  # the entry before ArchHub-Runtime: the agent started the install's python itself
        return [(connector[0], "python.exe -m nodelang.native_agent_mcp"), (_HOSTS[host], host)]
    supervisor = (_SUPERVISOR, "python.exe -I -B ArchHub-Runtime\\mcp_supervisor.py " + str(app))
    return [connector, supervisor, (_HOSTS[host], host)]


def test_agent_hosted_connectors_are_never_stopped_but_archhub_leftovers_are(tmp_path, monkeypatch):
    """Codex e988: 10 live native_agent_mcp transports run the install's python under Cursor, Claude, Codex
    and OpenCode. Their supervisor pauses them for Setup; the updater must never stop them itself."""
    import psutil

    app = tmp_path / "ArchHub"
    venv_python = str(app / ".venv" / "Scripts" / "python.exe")
    chains, processes = {}, []
    for number, host in enumerate(_HOSTS, start=2000000100):
        processes.append(_fake_process(number, venv_python))
        chains[number] = _transport_chain(app, host)
    leftover = _fake_process(2000000200, str(app / "nodelang" / "worker.exe"))
    chains[2000000200] = [(str(app / "nodelang" / "worker.exe"), "worker.exe"), (r"C:\Windows\explorer.exe", "")]
    goose_child = _fake_process(2000000201, venv_python)  # BABOOM's goose ships inside the install: ArchHub's own
    chains[2000000201] = [(venv_python, "python.exe tool.py"), (str(app / "goose.exe"), "goose.exe acp")]
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: (list(procs), []))
    stopped = qu.stop_runtime_processes(app, process_iter=lambda _attrs: [*processes, leftover, goose_child],
                                        session_zero=lambda _pid: False, chain_of=lambda p: chains[p.pid])
    assert stopped == [2000000200, 2000000201]
    for transport in processes:
        transport.terminate.assert_not_called()
        transport.kill.assert_not_called()


@pytest.mark.parametrize("host", list(_HOSTS))
def test_an_unsupervised_agent_connector_defers_the_update_before_anything_stops(tmp_path, monkeypatch, host):
    import psutil

    release = _build_output(tmp_path / "release", "next", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "ArchHub", "old", "2026-11-17T16:08:00Z")
    state = tmp_path / "updater-state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    leftover = _fake_process(2000000300, str(app / "nodelang" / "worker.exe"))
    transport = _fake_process(2000000301, str(app / ".venv" / "Scripts" / "python.exe"))
    chains = {2000000300: [(str(app / "nodelang" / "worker.exe"), "")],
              2000000301: _transport_chain(app, host, supervised=False)}
    monkeypatch.setattr(psutil, "wait_procs", lambda *a, **k: pytest.fail("waited on a process"))

    def stop(directory):
        return qu.stop_runtime_processes(directory, process_iter=lambda _attrs: [leftover, transport],
                                         session_zero=lambda _pid: False, chain_of=lambda p: chains[p.pid])

    result = qu.apply_staged(state, app, runner=lambda *a, **k: pytest.fail("Setup ran"), stop_runtime=stop)
    assert result["applied"] is False and result["reason"].startswith("deferred: an agent's ArchHub connector")
    leftover.terminate.assert_not_called()
    transport.terminate.assert_not_called()
    assert qu.staged_update(state, app)["status"] == "staged"  # retried at the next check, nothing recorded as failed
    assert qu.auto_install_held(state) == ""


def _supervisor_fixture(tmp_path, reports):
    """Real disposable report files beside a fake process list: one live supervisor per report key."""
    app = tmp_path / "LOCAL" / "ArchHub"
    runtime = tmp_path / "LOCAL" / "ArchHub-Runtime"
    (runtime / "connectors").mkdir(parents=True)
    script = str(runtime / "mcp_supervisor.py")
    processes = [SimpleNamespace(info={"pid": 99, "cmdline": ["python.exe", "other_supervisor.py"]})]
    for pid, body in reports.items():
        processes.append(SimpleNamespace(info={"pid": pid, "cmdline": ["python.exe", "-I", "-B", script, str(app)]}))
        if body is not None:
            (runtime / "connectors" / ("%d.json" % pid)).write_text(body, encoding="utf-8")
    return app, runtime / "connectors", (lambda _attrs: processes)


@pytest.mark.parametrize("body, held", [
    ('{"pending": 0, "admission": "closed", "attempt": "A"}', None),                    # the only all-clear
    ('{"pending": 0, "admission": "open", "attempt": "A"}', "admission still open"),
    ('{"pending": 0, "admission": "closed", "attempt": "older"}', "has not acknowledged this attempt"),
    ('{"pending": 0, "admission": "closed"}', "has not acknowledged this attempt"),
    ('{"pending": 1, "admission": "closed", "attempt": "A"}', "1 call(s) in flight"),
    ('{"admission": "closed", "attempt": "A"}', "no call count"),
    ('{"pending": "0", "admission": "closed", "attempt": "A"}', "no call count"),
    ('{"pending": false, "admission": "closed", "attempt": "A"}', "no call count"),
    ('[0]', "no call count"),
    ('{"pending": 0, "admission": ', "report unreadable"),                              # invalid JSON
    (None, "no report (older supervisor)"),
])
def test_only_a_valid_closed_idle_acknowledgement_of_this_attempt_lets_the_install_go_on(tmp_path, body, held):
    app, _folder, processes = _supervisor_fixture(tmp_path, {11: body})
    reasons = qu.connector_acknowledgements(app, "A", process_iter=processes)
    assert reasons == [] if held is None else (len(reasons) == 1 and held in reasons[0])


def test_drain_closes_admission_first_then_waits_for_every_acknowledgement(tmp_path):
    app, folder, processes = _supervisor_fixture(tmp_path, {11: '{"pending": 1, "admission": "closed", "attempt": "A"}',
                                                            12: '{"pending": 0, "admission": "open"}'})
    seen = []

    def acknowledgements(directory, attempt):
        seen.append((folder / qu.DRAIN_REQUEST).read_text(encoding="utf-8"))  # admission already closed
        if len(seen) == 3:  # both supervisors catch up: the call finished, the request was seen
            (folder / "11.json").write_text('{"pending": 0, "admission": "closed", "attempt": "A"}', encoding="utf-8")
            (folder / "12.json").write_text('{"pending": 0, "admission": "closed", "attempt": "A"}', encoding="utf-8")
        return qu.connector_acknowledgements(directory, attempt, process_iter=processes)

    qu.drain_connectors(app, "A", acknowledgements=acknowledgements, sleep=lambda _s: None, bound=60)
    assert seen[0] == '{"attempt": "A"}' and len(seen) == 3   # held twice, cleared on the third check
    assert (folder / qu.DRAIN_REQUEST).exists()   # still closed while the install goes on


@pytest.mark.parametrize("body", [None, '{"pending": 0, "admission": "open", "attempt": "A"}', "{bad json",
                                  '{"pending": 2, "admission": "closed", "attempt": "A"}'])
def test_anything_short_of_an_acknowledgement_defers_reopens_and_stops_nothing(tmp_path, monkeypatch, body):
    release = _build_output(tmp_path / "release", "next", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "LOCAL" / "ArchHub", "old", "2026-11-17T16:08:00Z")
    state = tmp_path / "updater-state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    _app, folder, processes = _supervisor_fixture(tmp_path, {11: body})

    def drain(directory, attempt):
        return qu.drain_connectors(directory, attempt, sleep=lambda _s: None, bound=3,
                                   acknowledgements=lambda d, a: qu.connector_acknowledgements(d, a, process_iter=processes))

    result = qu.apply_staged(state, app, runner=lambda *a, **k: pytest.fail("Setup ran"),
                             stop_runtime=lambda _d: pytest.fail("stopped a process"), drain=drain)
    assert result["applied"] is False and result["reason"].startswith("deferred: 1 agent connector(s) did not confirm")
    assert not (folder / qu.DRAIN_REQUEST).exists()   # admission reopened before the deferral was reported
    assert qu.staged_update(state, app)["status"] == "staged"
    monkeypatch.setattr(qu, "state_directory", lambda: state)
    monkeypatch.setattr(qu, "_desktop_running", lambda: False)
    monkeypatch.setattr(qu, "apply_staged", lambda *a, **k: result)
    monkeypatch.setattr(qu, "_relaunch", lambda *_a: None)
    qu.hand_off(app, relaunch=False, sleep=lambda _s: None)
    assert "update: error deferred: 1 agent connector(s) did not confirm" in \
        (state / "logs" / "updates.log").read_text(encoding="utf-8")


def test_a_refusal_after_the_drain_reopens_admission(tmp_path):
    release = _build_output(tmp_path / "release", "next", "2026-11-17T17:44:00Z")
    app = _installed_app(tmp_path / "LOCAL" / "ArchHub", "old", "2026-11-17T16:08:00Z")
    state = tmp_path / "updater-state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    _app, folder, processes = _supervisor_fixture(tmp_path, {})

    def refused(_directory):
        assert (folder / qu.DRAIN_REQUEST).exists()  # admission was closed for this attempt
        raise OSError("runtime process 7 refused termination")

    drain = lambda d, a: qu.drain_connectors(d, a, sleep=lambda _s: None, bound=3,
                                            acknowledgements=lambda dd, aa: qu.connector_acknowledgements(dd, aa, process_iter=processes))
    result = qu.apply_staged(state, app, runner=lambda *a, **k: pytest.fail("Setup ran"), stop_runtime=refused, drain=drain)
    assert result["applied"] is False and not (folder / qu.DRAIN_REQUEST).exists()


@pytest.mark.parametrize("exe, owned", [
    ("Registry", False), ("System", False), ("", False), (None, False),
    ("nodelang\\worker.exe", False),            # relative: never joined to the current folder
    ("C:worker.exe", False),                   # drive-relative is not absolute
    ("ABSOLUTE_OWNED", True), (r"C:\Windows\System32\cmd.exe", False),
])
def test_only_an_absolute_path_inside_the_install_is_owned(tmp_path, monkeypatch, exe, owned):
    app = (tmp_path / "ArchHub").resolve()
    app.mkdir()
    monkeypatch.chdir(app)
    if exe == "ABSOLUTE_OWNED":
        exe = str(app / "nodelang" / "worker.exe")
    assert (qu._owned_executable(exe, app) is not None) is owned


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


@pytest.mark.parametrize("mode", ["build-only", "local", "local-refused"])
def test_local_stable_build_publication_handoff(tmp_path, monkeypatch, mode):
    if not PWSH:
        pytest.skip("PowerShell required")
    monkeypatch.delenv("PSModulePath", raising=False)
    publisher = tmp_path / "packaging/windows/publish_release.ps1"
    publisher.parent.mkdir(parents=True)
    publisher.write_text('param($ReleaseDirectory, $ExpectedSourceRevision, $PythonPath, [switch]$DryRun)\n'
                         'Add-Content -LiteralPath $env:GH_CALLS -Value "dryrun=$DryRun"\n'
                         "if ($DryRun -and $env:REFUSE_PUBLICATION) { throw 'HTTP 422: refused' }\n")
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    if mode == "local-refused":
        monkeypatch.setenv("REFUSE_PUBLICATION", "1")
    else:
        monkeypatch.delenv("REFUSE_PUBLICATION", raising=False)
    harness = tmp_path / "build-tail.ps1"
    harness.write_text('''param($Build, $Root, [switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
$tail = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$env:GITHUB_ACTIONS'
}, $true)
if (-not $tail) { throw 'missing automatic publication branch' }
if ($BuildOnly -and $ast.ParamBlock.Parameters.Name.VariablePath.UserPath -notcontains 'BuildOnly') {
    throw 'build script does not expose -BuildOnly'
}
$selectedRoot = $Root; $output = $Root; $sourceRevision = 'fixture'; $PythonPath = 'fixture'
$assetName = 'ArchHub-Setup-0.exe'; $BuildId = 'fixture'
$statusName = 'status.txt'; $utf8 = [Text.UTF8Encoding]::new($false)
& ([scriptblock]::Create($tail.Extent.Text))
''')
    command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness),
               "-Build", str(ROOT / "03.TOOLS/installer/build_release.ps1"), "-Root", str(tmp_path)]
    if mode == "build-only":
        command.append("-BuildOnly")
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == int(mode == "local-refused"), result.stdout + result.stderr
    recorded = calls.read_text().splitlines() if calls.exists() else []
    if mode == "build-only":
        assert recorded == []
        assert "Built stable artifact ArchHub-Setup-0.exe" in result.stdout
        assert not (tmp_path / "status.txt").exists()
    elif mode == "local":
        assert recorded == ["dryrun=True", "dryrun=False"]
        assert (tmp_path / "status.txt").read_text().startswith("PUBLISHED:")
    else:
        assert "HTTP 422: refused" in result.stderr
        assert recorded == ["dryrun=True"]
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


def _write_installed_inventory(destination: Path, build_id: str, *, omit: tuple[str, ...] = ()) -> bytes:
    from nodelang.host_addin_retarget import LEGACY_IDENTITY_FILE, write_manifest

    source_files = (LEGACY_IDENTITY_FILE, "nodelang/data/baboom/persona.json", "app/__init__.py",
                    "app/credential_lock.py", "app/secrets_store.py", "bridges/rhino/archhub_mcp.py",
                    "bridges/blender/archhub_mcp/__init__.py", "bridges/sources/max_mcp/max_mcp_startup.py")
    host_files = [f"bridges/autocad/2026/{build_id}/AcadMCP.dll"]
    for year in (2020, 2023, 2024, 2025, 2027):
        base = f"bridges/revit/{year}"
        host_files.extend([f"{base}/host-artifacts.json", f"{base}/{build_id}/RevitMCP.dll",
                           f"{base}/{build_id}/RevitMCPCore.dll"])
    with TemporaryDirectory(dir=destination.parent) as fixture:
        source, hosts = Path(fixture) / "source", Path(fixture) / "hosts"
        for name in source_files:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture source")
        for name in host_files:
            if name.startswith(omit):
                continue
            path = hosts / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture host file")
        write_manifest(source, hosts, destination)
    return destination.read_bytes()


def _build_output(folder: Path, build_id: str, built_at: str) -> Path:
    """The files the stable publisher checks, with stand-in payload bytes."""
    folder.mkdir(parents=True)
    asset = _installer_bytes(build_id, built_at)
    (folder / qu.ASSET_NAME).write_bytes(asset)
    metadata = json.dumps({"format": 1, "build_id": build_id, "built_at": built_at},
                          separators=(",", ":")) + "\n"
    (folder / "BUILD_METADATA.json").write_bytes(metadata.encode("utf-8"))
    (folder / "source-manifest.tsv").write_bytes(b"ARCHHUB_RELEASE_SOURCE_MANIFEST_V2\n")
    (folder / "studio-build.json").write_bytes(b'{"format":1}\n')
    installed = _write_installed_inventory(folder / "installed-source-manifest.tsv", build_id)
    manifest = {
        "format": 1, "build_id": build_id, "built_at": built_at,
        "build_metadata_sha256": _sha(metadata.encode("utf-8")),
        "source_revision": REVISION,
        "payload_manifest": "source-manifest.tsv",
        "payload_manifest_sha256": _sha((folder / "source-manifest.tsv").read_bytes()),
        "installed_source_manifest_sha256": _sha(installed),
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


def test_stable_publish_refuses_inventory_that_would_retire_working_hosts(tmp_path):
    import colleague_setup
    from nodelang.host_broker_installation import _registration

    released = _build_output(tmp_path / "release", "next", "2026-11-21T10:00:00Z")
    assert offer_check.reconcile(released)["build_id"] == "next"
    proposed = released / "installed-source-manifest.tsv"
    assert b"host-artifacts.json" not in proposed.read_bytes()
    empty = _write_installed_inventory(proposed, "next", omit=("bridges/revit/", "bridges/autocad/"))
    release_json = released / "release.json"
    metadata = json.loads(release_json.read_bytes())
    metadata["installed_source_manifest_sha256"] = _sha(empty)
    release_json.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(offer_check.Refused, match="drop supported native host payloads: revit 2020.*autocad 2026"):
        offer_check.reconcile(released)

    root = tmp_path / "ArchHub"
    root.mkdir()
    (root / "HOST_ARTIFACTS.json").write_text('{"revit":{},"autocad":{}}', encoding="utf-8")
    env = {key: str(tmp_path / key) for key in ("APPDATA", "ProgramData")}
    year = "2025"
    assembly = root / f"bridges/revit/{year}/previous/RevitMCP.dll"
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"previous broker")
    registration = Path(env["APPDATA"]) / f"Autodesk/Revit/Addins/{year}/RevitMCP.addin"
    registration.parent.mkdir(parents=True)
    original = _registration(assembly)
    registration.write_bytes(original)
    outcome = colleague_setup.register_revit_add_ins(root, environment=env, detected_years=[year])
    assert outcome[0]["status"] == "retired_pending_host_restart"
    assert registration.with_suffix(".addin.retired").read_bytes() == original
    assert not registration.exists()


@pytest.mark.parametrize(("omit", "missing"), [
    ("bridges/revit/2024/next/RevitMCPCore.dll", "revit 2024"),
    ("bridges/autocad/2026/", "autocad 2026"),
])
def test_stable_coverage_refuses_one_missing_dll_or_year(tmp_path, omit, missing):
    manifest = tmp_path / "installed-source-manifest.tsv"
    _write_installed_inventory(manifest, "next", omit=(omit,))
    with pytest.raises(offer_check.Refused) as error:
        offer_check.check_host_payloads(manifest, "next")
    assert str(error.value) == f"stable release would drop supported native host payloads: {missing}"


def test_missing_host_sdks_names_each_absent_year_before_any_compile(tmp_path):
    good = tmp_path / "cad-host"
    for host, years in offer_check.STABLE_HOST_YEARS.items():
        product, names = offer_check.HOST_SDK_FILES[host]
        for year in years:
            folder = good / "Autodesk" / f"{product} {year}"
            folder.mkdir(parents=True)
            for name in names:
                (folder / name).write_bytes(b"sdk")
    assert offer_check.missing_host_sdks(good) == []
    (good / "Autodesk/Revit 2027/RevitAPIUI.dll").unlink()
    assert offer_check.missing_host_sdks(good) == ["revit 2027 (RevitAPIUI.dll)"]
    hosted = tmp_path / "hosted"
    hosted.mkdir()
    missing = offer_check.missing_host_sdks(hosted)
    assert len(missing) == 6 and missing[0] == "revit 2020 (RevitAPI.dll, RevitAPIUI.dll)"
    assert missing[-1] == "autocad 2026 (acmgd.dll, acdbmgd.dll, accoremgd.dll)"
    assert offer_check.main(["--missing-host-sdks", str(hosted)]) == 1
    (good / "Autodesk/Revit 2027/RevitAPIUI.dll").write_bytes(b"sdk")
    assert offer_check.main(["--missing-host-sdks", str(good)]) == 0


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


def test_recorded_local_light_origin_recovers_only_to_newer_verified_setup(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    origin = "20261119-0904-665c785+light-f10-b598855b"
    record = (b'{"format":1,"build_id":"20261119-0904-665c785+light-f10-b598855b",'
              b'"base_build":"20261119-0904-665c785","built_at":"2026-11-20T12:32:32Z",'
              b'"source_revision":"b598855b","stage":"light-f10-studio",'
              b'"note":"tip context-menus.jsx+api.js + compile_studio; not a new MSIX/Setup; '
              b'Goose receipt still required for full release"}\r\n')
    (app / "BUILD_ID").write_text(origin, encoding="utf-8")
    metadata = app / "BUILD_METADATA.json"
    metadata.write_bytes(record)
    assert qu.installed_build_id(app) == origin
    assert qu._ordering_refusal(app, {"build_id":"old","built_at":"2026-11-20T12:32:32Z"}, origin)
    assert not qu._BUILD_RE.fullmatch("BUILD_ID: " + origin)
    metadata.write_bytes(record.replace(b"12:32:32Z", b"12:32:31Z"))
    assert qu.installed_build_id(app) == ""
    metadata.write_bytes(record)
    (app / "BUILD_ID").write_text(origin + "x", encoding="utf-8")
    assert qu.installed_build_id(app) == ""
    (app / "BUILD_ID").write_text(origin, encoding="utf-8")

    target = "20261121-062548-44875457384-1-f662a21c576a"
    state = _fixture_state(tmp_path / "updater-state")
    before = _state_fingerprint(state)
    release = _build_output(tmp_path / "release", target, "2026-11-21T06:25:48Z")
    staged = qu.stage_if_newer(state, app, opener=_local_github(release))
    assert staged["staged"] and staged["bytes_verified"]
    calls = []
    applied = qu.apply_staged(state, app, runner=_fake_installer(calls), expect=(target, staged["sha256"]))
    assert applied["applied"] and len(calls) == 1
    assert qu.confirm_applied(state, app)["confirmed"]
    assert qu.installed_build_id(app) == target
    assert _state_fingerprint(state) == before


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


@pytest.mark.skipif(not PWSH, reason="Windows publisher requires PowerShell")
def test_preview_prose_edit_keeps_machine_block_assets_and_stable(tmp_path):
    from copy import deepcopy
    setup_sha = hashlib.sha256(b"setup").hexdigest()
    manifest = {"build_id": "20261122-preview", "built_at": "2026-11-22T01:00:00Z",
                "asset_sha256": setup_sha, "asset_bytes": 5, "source_revision": REVISION,
                "requirements_sha256": "a" * 64}
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    block = ("## Build\nBUILD_ID: 20261122-preview\nBUILT_AT: 2026-11-22T01:00:00Z\n"
             f"SHA256 {qu.ASSET_NAME}: {setup_sha}\nSOURCE_REVISION: {REVISION}\nREQUIREMENTS_SHA256: " + "a" * 64 + "\n")
    (tmp_path / "release-notes.md").write_text(block, encoding="utf-8")
    prose = tmp_path / "human.md"
    prose.write_text("Updated preview instructions.", encoding="utf-8")
    tag = "build-" + manifest["build_id"]
    url = f"https://github.com/Fargaly/ArchHub/releases/download/{tag}/"
    assets = [{"id": i, "name": name, "size": size, "digest": "sha256:" + digest,
               "browser_download_url": url + name} for i, (name, size, digest) in enumerate([
                   (qu.ASSET_NAME, 5, setup_sha), ("release.json", path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())], 1)]
    preview = {"id": 42, "tag_name": tag, "draft": False, "prerelease": True, "assets": assets, "body": "Old notes\n\n" + block}
    stable = {**deepcopy(preview), "id": 10, "prerelease": False, "tag_name": "stable"}
    original = deepcopy(stable), deepcopy(assets)
    def snap(name, value):
        (tmp_path / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')
    (tmp_path / "revision").write_text(REVISION)
    snap('stable', stable)
    snap('preview', preview)
    harness = tmp_path / 'outer.ps1'
    harness.write_text(r"""param($publisher,$root,$tag,$whichPython,$faultPhase,$faultJson,[switch]$PlanOnly)
$ErrorActionPreference='Stop'
function gh {
    $global:LASTEXITCODE=0
    if ($args[0] -ne 'api') { throw 'unexpected GitHub action' }
    if ($args[1] -ceq 'repos/Fargaly/ArchHub/releases/latest') { Get-Content -Raw -Encoding UTF8 "$root/stable.json"; return }
    if ($args[1] -ceq "repos/Fargaly/ArchHub/releases/tags/$tag") { Get-Content -Raw -Encoding UTF8 "$root/preview.json"; return }
    if ($args[1] -ceq "repos/Fargaly/ArchHub/commits/tags/$tag") { Get-Content "$root/revision"; return }
    Add-Content "$root/attempts" ($args[1])
    if (($args -join ' ') -notmatch '^api repos/Fargaly/ArchHub/releases/42 --method PATCH --field body=@.+ --silent$') { throw 'unexpected write' }
    $release = Get-Content -Raw -Encoding UTF8 "$root/preview.json" | ConvertFrom-Json
    $release.body = [IO.File]::ReadAllText($args[5].Substring(6))
    [IO.File]::WriteAllText("$root/preview.json", ($release | ConvertTo-Json -Depth 10))
    Add-Content "$root/writes" 'body'
}
function FixtureChecker {
    if ($args[-1] -eq $faultPhase) { $global:LASTEXITCODE=0; Get-Content -LiteralPath $faultJson -Raw -Encoding UTF8; return }
    & $whichPython @args
}
$checker = if ($faultPhase) { 'FixtureChecker' } else { $whichPython }
& $publisher -ReleaseDirectory $root -PreviewTag $tag -PreviewNotesFile "$root/human.md" -PythonPath $checker -DryRun:$PlanOnly
""", encoding='utf-8')
    def run(selected_tag=tag, *extra):
        return subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(harness),
                               str(ROOT / '03.TOOLS/packaging/windows/publish_release.ps1'), str(tmp_path),
                               selected_tag, sys.executable, *extra], capture_output=True, timeout=90)
    good = {"ok":True, "changed":False, "id":42, "stable_tag":"stable"}
    for verdict in ({**good, "ok":False}, {**good, "ok":"true"}, {**good, "changed":"false"},
                    {**good, "id":10, "changed":True}, {"ok":True}, [good]):
        snap('fault', verdict)
        for switches in ((), ('-PlanOnly',)):
            bad = run(tag, 'before', str(tmp_path / 'fault.json'), *switches)
            assert bad.returncode != 0 and b'verified' not in bad.stdout.lower(), bad.stdout
            assert b'verdict' in bad.stderr.lower(), bad.stderr
            assert not (tmp_path / 'attempts').exists()
    for changes in ({"ok":False}, {"changed":True}, {"id":10}):
        snap('preview', dict(preview, body='Updated preview instructions.\n\n' + block))
        snap('fault', {**good, **changes})
        bad = run(tag, 'after', str(tmp_path / 'fault.json'))
        assert bad.returncode != 0 and b'verified published' not in bad.stdout.lower()
        assert b'verdict' in bad.stderr.lower(), bad.stderr
        assert not (tmp_path / 'attempts').exists()
    minimal = "\n".join(block.splitlines()[:4]) + "\n"
    snap('preview', dict(preview, body='Existing intro\n\n' + minimal))
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    edited = json.loads((tmp_path / 'preview.json').read_text(encoding='utf-8'))
    assert edited['body'] == 'Updated preview instructions.\n\n' + block
    assert (json.loads((tmp_path / 'stable.json').read_text()), edited['assets']) == original
    assert offer_check.updater_reads(edited, channel='preview')['tag'] == tag
    assert offer_check.updater_reads(edited) is None
    edited['body'] = edited['body'].replace('\n', '\r\n')
    snap('preview', edited)
    assert run().returncode == 0
    alias = dict(edited, tag_name='build-wrong')
    snap('preview', alias)
    assert run('build-wrong').returncode != 0
    for conflict in (block + 'BUILT_AT: bad\n', block.replace(REVISION, 'b' * 40),
                     minimal + 'SOURCE_REVISION: wrong\n', minimal + minimal, minimal.replace('BUILT_AT:', 'TIME:')):
        snap('preview', dict(edited, body=conflict))
        assert run().returncode != 0
    snap('preview', edited)
    prose.write_text('BUILD_ID: another-build', encoding='utf-8')
    assert run().returncode != 0
    assert (tmp_path / 'writes').read_text().splitlines() == ['body']
    prose.write_text('Updated preview instructions.', encoding='utf-8')
    (tmp_path / "after-revision").write_text(REVISION)
    for label, release in (('stable', stable), ('preview', edited)):
        snap('before-' + label, release)
        snap('after-' + label, release)
    for label, release in (('stable', stable), ('preview', edited)):
        different = deepcopy(release)
        if label == 'stable':
            different['id'] += 1
        else:
            different['assets'][0]['id'] += 1
        snap('after-' + label, different)
        with pytest.raises(offer_check.Refused, match='readback'):
            offer_check.preview_notes(tmp_path, tag, prose, REVISION, tmp_path, 'after')
        snap('after-' + label, release)


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
    update.state_dir = update.app_dir = None
    monkeypatch.setattr(qu, "staged_update", lambda _s, _a: {"staged": True, "status": "staged", "build_id": "B"})
    with pytest.raises(UpdateRestartRefused, match="chat answer"):
        update.reload()


@pytest.mark.parametrize("staged, busy, expected", [
    ({"staged": False, "reason": "No verified update is ready."}, "2 calls in flight", "refused: No verified"),
    ({"staged": True, "status": "confirmed", "build_id": "A"}, "2 calls in flight", "up to date"),
    ({"staged": True, "status": "staged", "build_id": "B"}, "2 calls in flight", "refused: 2 calls"),
    ({"staged": True, "status": "staged", "build_id": "B"}, None, "restarted"),
])
def test_reload_reads_the_package_before_the_busy_guard(monkeypatch, staged, busy, expected):
    """e988 cc0f3cd1: an up-to-date or empty package showed the busy-agents refusal; the live guard runs last."""
    import threading
    from nodelang.application_update import ApplicationUpdate, UpdateRestartRefused
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update._closed, update._state, update._worker, update._lock = False, "ready", None, threading.RLock()
    update.state_dir = update.app_dir = None
    update._available, update._detail, update._restart_reason = "B", "Restart to update", "busy before"
    update.status = lambda: {"state": update._state, "detail": update._detail, "available_build": update._available}
    restarts = []
    update._request_restart = lambda: restarts.append(1)
    update._restart_refusal = lambda: busy
    monkeypatch.setattr(qu, "staged_update", lambda _s, _a: staged)
    try:
        result = update.reload()
        outcome = "up to date" if "up to date" in result["detail"] else "restarted"
    except UpdateRestartRefused as error:
        outcome = "refused: " + str(error)
    assert outcome.startswith(expected), outcome
    assert restarts == ([1] if expected == "restarted" else [])
    if expected == "up to date":   # e988 0c3795b6: the next normal status read no longer offers the old build
        assert update.status() == {"state": "idle", "detail": "ArchHub is up to date.", "available_build": ""}
        assert update._restart_reason == ""


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


_STUB_NETWORK = """import io, urllib.request
from pathlib import Path
# Court stand-in for GitHub: releases/latest answers with the published release, nothing else is reachable.
_RELEASE = Path(__file__).with_name("published-release.json").read_bytes()
class _Body(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *_exc):
        return False
def _github(request, timeout=0):
    if getattr(request, "full_url", request) != "https://api.github.com/repos/Fargaly/ArchHub/releases/latest":
        raise OSError("court: only the stubbed releases/latest is reachable")
    return _Body(_RELEASE)
urllib.request.urlopen = _github
"""


@pytest.mark.parametrize("layout", ["numbered", "flattened", "no_parser"])
def test_publish_reads_back_latest_through_the_real_parser_in_both_layouts(tmp_path, monkeypatch, layout):
    """After promotion, publish_release.ps1 reads releases/latest back with the installed updater's own parser
    (nodelang.quiet_update). Numbered repository: nodelang is in 01.APP beside 03.TOOLS; flattened release snapshot:
    nodelang beside packaging/. The real publisher, profile guard and parser run from a neutral folder; gh, the
    pre-upload checker and the network are stand-ins, so nothing is uploaded."""
    if not PWSH:
        pytest.skip("PowerShell required")
    monkeypatch.delenv("PSModulePath", raising=False)
    release = _build_output(tmp_path / "release", "20261108-test", "2026-11-08T01:00:00Z")
    published = offer_check.reconcile(release)["github_release"]
    root = tmp_path / "layout"
    tools, app = (root / "03.TOOLS", root / "01.APP") if layout == "numbered" else (root, root)
    windows = tools / "packaging" / "windows"
    windows.mkdir(parents=True)
    shutil.copyfile(ROOT / "03.TOOLS/packaging/windows/publish_release.ps1", windows / "publish_release.ps1")
    (windows / "report.json").write_text(json.dumps(offer_check.check(release)), encoding="utf-8")
    (windows / "check_update_offer.py").write_text(   # the pre-upload check is its own court; here it approves
        "from pathlib import Path\nprint(Path(__file__).with_name('report.json').read_text(encoding='utf-8'))\n",
        encoding="utf-8")
    guard = tools / "tools" / "real_app_check"
    guard.mkdir(parents=True)
    for name in ("profile_guard.py", "real_app_check.py"):
        shutil.copyfile(ROOT / "03.TOOLS/tools/real_app_check" / name, guard / name)
    if layout != "no_parser":
        (app / "nodelang").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "01.APP/nodelang/quiet_update.py", app / "nodelang" / "quiet_update.py")
        (app / "nodelang" / "__init__.py").write_text(_STUB_NETWORK, encoding="utf-8")
        (app / "nodelang" / "published-release.json").write_text(json.dumps(published), encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "gh.cmd").write_text('@echo off\r\necho %*>>"%GH_CALLS%"\r\nexit /b 0\r\n')
    calls = tmp_path / "gh-calls.txt"
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GH_CALLS", str(calls))
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(windows / "publish_release.ps1"),
                             "-ReleaseDirectory", str(release), "-PythonPath", sys.executable,
                             "-ExpectedSourceRevision", REVISION],
                            cwd=neutral, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    recorded = calls.read_text().splitlines() if calls.exists() else []
    if layout == "no_parser":
        assert result.returncode == 1 and "nothing was published" in result.stdout + result.stderr
        assert recorded == []                                  # refused before any GitHub call
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert [line.split()[:2] for line in recorded] == [["auth", "status"], ["release", "create"], ["release", "edit"]]
    assert '"build_id": "20261108-test"' in result.stdout     # read back by quiet_update.read_latest_release
    assert "PUBLISHED build-20261108-test as latest" in result.stdout


def _held_fixture(tmp_path):
    release = _build_output(tmp_path / "release", "20261120-0100-aaaaaaa", "2026-11-19T21:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20261119-0904-665c785", "2026-11-19T05:04:00Z")
    state = tmp_path / "state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"] is True
    return app, state


def _ticking_desktop(state, app, preflight, restarts):
    """The desktop's update pulse, as nograph_launcher.consider_update runs it once a minute."""
    import threading
    from nodelang.application_update import ApplicationUpdate
    from nodelang.nograph_launcher import _auto_install_held, _update_refusal

    server = SimpleNamespace(busy_reason=lambda: None)
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update.state_dir, update.app_dir = state, app
    update._closed, update._state, update._worker, update._lock = False, "ready", None, threading.RLock()
    update._prerelease, update._available, update._restart_reason = False, "20261120-0100-aaaaaaa", ""
    update._updated = None
    update._policy = lambda: {"auto_apply_on_quit": True, "idle_minutes": 15}
    update._request_restart = lambda: restarts.append("closed the Studio")
    update._restart_refusal = lambda: _update_refusal(server, state, app, preflight=preflight, desktop_pids=set())

    def tick():
        if not _auto_install_held(state):
            update.install_if_safe(closing=True, canvas_running=False)
    return tick


def test_the_minute_by_minute_close_reopen_loop_cannot_happen(tmp_path):
    """Field defect (installed 0904, launcher.log 19:57-20:11): the install was refused before Setup, the
    marker stayed "staged", the Studio read "ready" again and closed itself every minute.
    Now the refusal is seen before the close and recorded: zero closes over ten ticks."""
    app, state = _held_fixture(tmp_path)
    restarts, scans = [], []

    def refusing_preflight(_app, *, desktop_pids):
        scans.append(1)
        return "runtime process 420 refused termination"

    tick = _ticking_desktop(state, app, refusing_preflight, restarts)
    for _minute in range(10):
        tick()
    assert restarts == []                               # the Studio was never closed
    assert len(scans) == 1                              # refused once, then left alone without rescanning
    assert qu.auto_install_held(state) == "runtime process 420 refused termination"
    assert qu.staged_update(state, app)["status"] == "staged"   # the verified package is kept for Retry


@pytest.mark.parametrize("report, expected", [
    (None, "no report (older supervisor)"),
    ('{"pending": 1, "admission": "open", "attempt": null}', "1 call(s) in flight"),
    ('{"admission": "open", "attempt": null}', "no call count"),
    ("unsupervised", "runs without its supervisor"),
])
def test_connector_preflight_keeps_studio_open_and_retries_after_exit(tmp_path, report, expected):
    app, state = _held_fixture(tmp_path)
    folder = qu._runtime_connectors(app)
    folder.mkdir(parents=True)
    pid = 2000000311
    script = str(folder.parent / "mcp_supervisor.py")
    transport = _fake_process(pid, str(app / ".venv" / "Scripts" / "python.exe"))
    supervisor = SimpleNamespace(info={"pid": pid, "cmdline": ["python.exe", script, str(app)]})
    processes = [transport if report == "unsupervised" else supervisor]
    if report is not None and report != "unsupervised":
        (folder / ("%d.json" % pid)).write_text(report, encoding="utf-8")
    restarts = []

    def preflight(directory, *, desktop_pids):
        return qu.preflight_refusal(directory, desktop_pids=desktop_pids, process_iter=lambda _a: processes,
                                    can_terminate=lambda _pid: pytest.fail("queried termination rights"),
                                    chain_of=lambda _p: _transport_chain(app, "codex", supervised=False))

    assert expected in preflight(app, desktop_pids=set())
    tick = _ticking_desktop(state, app, preflight, restarts)
    tick()
    tick()
    assert restarts == []
    assert qu.auto_install_held(state) == ""
    assert not (folder / qu.DRAIN_REQUEST).exists()
    transport.terminate.assert_not_called()
    processes.clear()
    tick()
    assert restarts == ["closed the Studio"]


def test_a_refusal_inside_the_installer_step_also_holds_the_build(tmp_path):
    app, state = _held_fixture(tmp_path)

    def refused(_directory):
        raise OSError("runtime process 420 refused termination")

    result = qu.apply_staged(state, app, runner=lambda *a, **k: pytest.fail("Setup ran"), stop_runtime=refused)
    assert result["applied"] is False and qu.auto_install_held(state) == "runtime process 420 refused termination"
    # The in-folder launcher that is still exiting clears by itself: never a hold.
    app2, state2 = _held_fixture(tmp_path / "second")

    def still_exiting(_directory):
        raise ValueError(qu._LAUNCHER_HOLDS_INSTALL)

    qu.apply_staged(state2, app2, runner=lambda *a, **k: pytest.fail("Setup ran"), stop_runtime=still_exiting)
    assert qu.auto_install_held(state2) == ""


def test_only_a_newer_build_or_the_users_retry_re_arms_a_held_build(tmp_path):
    app, state = _held_fixture(tmp_path)
    assert qu.hold_auto_install(state, "runtime process 420 refused termination") is True
    # Retry (the user's own Update / Restart to update) is not blocked by the hold and clears it once it gets past.
    calls = []
    retried = qu.apply_staged(state, app, runner=lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=1),
                              stop_runtime=lambda _d: None)
    assert calls and "auto_held" not in json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
    assert retried["applied"] is False  # this fixture's Setup fails: recorded as failed, still not auto-retried
    # A newer build replaces the held one and is offered normally.
    app3, state3 = _held_fixture(tmp_path / "third")
    qu.hold_auto_install(state3, "deferred")
    newer = _build_output(tmp_path / "third" / "release2", "20261121-0100-bbbbbbb", "2026-11-20T21:00:00Z")
    assert qu.stage_if_newer(state3, app3, opener=_local_github(newer))["staged"] is True
    assert qu.auto_install_held(state3) == ""


def test_preflight_predicts_a_refusal_without_touching_any_process(tmp_path, monkeypatch):
    app = (tmp_path / "ArchHub").resolve()
    app.mkdir()
    monkeypatch.chdir(app)  # ArchHub.vbs sets this; a bare name must still never resolve into the install
    processes = [SimpleNamespace(info={"pid": 420, "exe": "Registry"}),
                 SimpleNamespace(info={"pid": 7001, "exe": str(app / "tools" / "held.exe")}),
                 SimpleNamespace(info={"pid": 9001, "exe": str(app / ".venv" / "Scripts" / "pythonw.exe")})]
    asked = []

    def can_terminate(pid):
        asked.append(pid)
        return pid != 7001

    assert qu.preflight_refusal(app, desktop_pids={9001}, process_iter=lambda _a: processes,
                                can_terminate=can_terminate) == "runtime process 7001 refused termination"
    assert asked == [7001]  # "Registry" (PID 420) is not ArchHub's; the desktop's own process is never asked
    assert qu.preflight_refusal(app, desktop_pids={9001}, process_iter=lambda _a: [processes[0], processes[2]],
                                can_terminate=lambda _pid: pytest.fail("asked")) == ""


def test_an_unresolved_save_conflict_holds_the_automatic_restart_until_keep_or_discard(tmp_path):
    """Codex fixture, installed 0904: two edits on one socket, the remote one saved, the local wire held
    behind Keep/Discard; canvas_job_running read False and the idle restart dropped the local wire."""
    import threading
    from nodelang.application_update import ApplicationUpdate, UpdateRestartRefused, canvas_job_running
    from nodelang.nograph_launcher import _update_refusal
    from nodelang.nograph_server import NoGraphServer, r_session_files

    app, state = _held_fixture(tmp_path)
    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    server.busy_reason = lambda: NoGraphServer.busy_reason(server)
    restarts = []
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update.state_dir, update.app_dir = state, app
    update._closed, update._state, update._worker, update._lock = False, "ready", None, threading.RLock()
    update._prerelease, update._available, update._restart_reason = False, "20261120-0100-aaaaaaa", ""
    update._updated, update._detail, update.confirmed_build = None, "", None
    update._policy = lambda: {"auto_apply_on_quit": True, "idle_minutes": 15}
    update._request_restart = lambda: restarts.append("closed the Studio")
    update._restart_refusal = lambda: _update_refusal(server, state, app, preflight=lambda _a, desktop_pids: "",
                                                      desktop_pids=set())

    def report(view, seq, unsaved, path="C:/work/flow.archhub"):
        return r_session_files(server, SimpleNamespace(body={"action": "edit_state", "view": view, "file": path,
                                                              "seq": seq, "unsaved": unsaved}))

    report("view-1", 1, True)                # local wire unsaved, Keep/Discard alert open
    assert canvas_job_running(server) is True
    assert update.install_if_safe(closing=False, canvas_running=canvas_job_running(server), user_idle=True) is False
    assert update.install_if_safe(closing=True, canvas_running=False, user_idle=True) is False  # refusal also holds it
    assert restarts == []
    with pytest.raises(UpdateRestartRefused, match="unsaved changes"):
        update.reload()                      # a manual Restart says why instead of dropping the edit
    # Codex v2 (a): a second, clean view must not clear the first view's draft.
    report("view-2", 1, False)
    assert canvas_job_running(server) is True and restarts == []
    # A late, older report from the first view cannot undo its newer dirty one.
    assert report("view-1", 1, False)["accepted"] is False
    assert canvas_job_running(server) is True
    report("view-1", 2, False)               # Keep (copy saved) or Discard chosen in view 1 releases view 1 only
    assert canvas_job_running(server) is False
    assert update.install_if_safe(closing=False, canvas_running=False, user_idle=True) is True
    assert restarts == ["closed the Studio"]


def test_keep_or_discard_in_one_view_releases_only_its_own_draft():
    from nodelang.nograph_server import NoGraphServer, record_edit_state

    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    record_edit_state(server, {"view": "a", "file": "x.archhub", "seq": 1, "unsaved": True})
    record_edit_state(server, {"view": "b", "file": "y.archhub", "seq": 1, "unsaved": True})
    record_edit_state(server, {"view": "a", "file": "x.archhub", "seq": 2, "unsaved": False})  # Keep in view a
    assert "unsaved changes" in NoGraphServer.busy_reason(server)                          # view b still dirty
    record_edit_state(server, {"view": "b", "file": "y.archhub", "seq": 2, "unsaved": False})
    assert NoGraphServer.busy_reason(server) is None
    for bad in ({"view": "", "file": "", "seq": 1}, {"view": "a", "file": "x", "seq": "1"},
                {"view": "a", "file": "x", "seq": True}):
        with pytest.raises(Exception, match="view, file and sequence"):
            record_edit_state(server, bad)


def test_keep_my_changes_as_a_copy_then_a_reload_lets_the_update_go_on(tmp_path):
    """Codex compiled-browser case: Keep as a copy, view reload, both files intact, yet the old page's
    seq-3 dirty entry for private.archhub held the update forever."""
    from nodelang.nograph_server import NoGraphServer, record_edit_state

    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    busy = lambda: NoGraphServer.busy_reason(server)
    report = lambda body: record_edit_state(server, body)
    for seq in (1, 2, 3):  # the old page: edit, failed save, unresolved Keep/Discard
        report({"view": "old-page", "file": "private.archhub", "seq": seq, "unsaved": True})
    assert "unsaved changes" in busy()
    # Keep my changes as a copy: the resolution clears this page's own entry, server-side, before any reload.
    assert report({"view": "old-page", "file": "private.archhub", "seq": 4, "unsaved": False, "resolved": "keep"})["accepted"]
    assert busy() is None
    # The reload: the same tab's new page retires the old one; a late old-page report cannot re-add it.
    report({"view": "new-page", "file": "private.archhub", "seq": 1, "unsaved": False, "retire": "old-page"})
    assert report({"view": "old-page", "file": "private.archhub", "seq": 5, "unsaved": True})["accepted"] is False
    assert busy() is None
    # Genuine unresolved edits still hold: a fresh edit on the new page holds again.
    report({"view": "new-page", "file": "private.archhub", "seq": 2, "unsaved": True})
    assert "unsaved changes" in busy()


def test_a_reload_before_the_resolution_arrived_also_releases_the_old_page_but_other_tabs_never(tmp_path):
    from nodelang.nograph_server import NoGraphServer, record_edit_state

    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    record_edit_state(server, {"view": "tab-a", "file": "x.archhub", "seq": 3, "unsaved": True})
    record_edit_state(server, {"view": "tab-b", "file": "y.archhub", "seq": 1, "unsaved": True})
    # Tab A reloads (its draft was saved or recovered by the new page, which reports for itself).
    record_edit_state(server, {"view": "tab-a2", "file": "x.archhub", "seq": 1, "unsaved": False, "retire": "tab-a"})
    # Tab B is another tab: a clean report elsewhere never clears it, and a closed tab B keeps holding.
    record_edit_state(server, {"view": "tab-c", "file": "y.archhub", "seq": 1, "unsaved": False})
    assert server._unsaved_views == {("tab-b", "y.archhub")}
    assert "unsaved changes" in NoGraphServer.busy_reason(server)


@pytest.mark.parametrize("release", ["keep", "discard"])
def test_a_closed_tabs_draft_holds_until_that_exact_draft_is_kept_or_discarded(release):
    """Decision (builder lead + Codex): a clean save or reopen of the same file in another view never settles
    a closed tab's draft (those can be different wires). Only recovering that exact draft and keeping it,
    or explicitly discarding it, releases the hold."""
    from nodelang.nograph_server import NoGraphServer, record_edit_state

    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    busy = lambda: NoGraphServer.busy_reason(server)
    record_edit_state(server, {"view": "closed-tab", "file": "private.archhub", "seq": 3, "unsaved": True})
    # The tab closes. Another view opens the same file clean, edits and saves it cleanly: still held.
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 1, "unsaved": False, "opened": True})
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 2, "unsaved": True})
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 3, "unsaved": False})
    assert "unsaved changes" in busy()
    # A resolution that names another page's draft, or a plain clean report, does not release it either.
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 4, "unsaved": False,
                               "resolves": "some-other-page", "resolved": release})
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 5, "unsaved": False,
                               "resolves": "closed-tab"})                       # no keep/discard: not a resolution
    assert "unsaved changes" in busy()
    # Recovering that exact draft and keeping it as a copy (or discarding it) releases it.
    record_edit_state(server, {"view": "other", "file": "private.archhub", "seq": 6, "unsaved": False,
                               "resolves": "closed-tab", "resolved": release})
    assert busy() is None


def test_closed_tab_then_recover_then_keep_releases_the_hold_through_the_real_route(tmp_path):
    """Studio gap closed: the recovery banner's Keep sends exactly this body (api.resolveOrphanDraft) through
    the real session-files route, naming the closed window's view; a desktop restart is no longer needed."""
    from nodelang.nograph_server import NoGraphServer, r_session_files

    server = SimpleNamespace(_canvas_jobs=0, triggers=SimpleNamespace(running=set()), _chat_turns=set())
    route = lambda body: r_session_files(server, SimpleNamespace(body={"action": "edit_state", **body}))
    route({"view": "closed-window", "file": "C:/work/private.archhub", "seq": 3, "unsaved": True})
    # The window closes; a new window opens with its own clean canvas and shows the recovery banner.
    route({"view": "new-window", "file": "C:/work/other.archhub", "seq": 1, "unsaved": False, "opened": True})
    assert "unsaved changes" in NoGraphServer.busy_reason(server)
    # Keep those changes as a copy (the copy is saved first, then this report).
    route({"view": "new-window", "file": "C:/work/private.archhub", "seq": 2, "unsaved": False,
           "resolves": "closed-window", "resolved": "keep"})
    assert NoGraphServer.busy_reason(server) is None
    # The new window's own later edit of that file still holds as usual.
    route({"view": "new-window", "file": "C:/work/private.archhub", "seq": 3, "unsaved": True})
    assert "unsaved changes" in NoGraphServer.busy_reason(server)


@pytest.mark.parametrize("live, proceeds", [
    ({"unsaved": False, "file": "x"}, True),   # the live page answered: nothing unsaved
    ({"unsaved": True, "file": "x"}, False),   # it has a draft the reports have not shown yet (first edit)
    (None, False),                              # no answer, an old page or a broken one: never closes
    ({}, False), ("clean", False),
])
def test_the_desktop_closes_only_after_the_live_page_answers_clean(live, proceeds):
    from nodelang.nograph_launcher import _live_page_clean

    assert _live_page_clean(live) is proceeds


def _settings_server(state):
    from nodelang.nograph_server import JsonFile
    return SimpleNamespace(state_dir=state, files={
        "settings": JsonFile(state / "settings" / "settings.json", {"settingsScope": "User"}),
        "companion": JsonFile(state / "settings" / "companion.json", {})})


def _edit_setting(server, key, value):
    """What the Settings row and an explicit Workshop-node parameter edit both send (api.setApplicationSetting)."""
    from nodelang.nograph_server import r_settings_action
    return r_settings_action(server, SimpleNamespace(body={"function": "setApplicationSetting", "args": [key, value]}))


def test_turning_auto_update_off_and_on_reaches_the_node_the_row_and_the_policy(monkeypatch, tmp_path):
    """One value in one owner file: an explicit edit writes it; the node, the row and the policy all read it."""
    import threading
    from nodelang.application_update import ApplicationUpdate, default_update_policy, saved_application_settings
    from nodelang.pipeline_engines import tool_settings

    state = tmp_path / "state"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    server = _settings_server(state)
    assert default_update_policy()["auto_apply_on_quit"] is True
    _edit_setting(server, "update_auto_apply_on_quit", False)                          # OFF
    assert saved_application_settings() == {"update_auto_apply_on_quit": False}
    assert default_update_policy()["auto_apply_on_quit"] is False
    assert tool_settings({"tool": "workshop"}, {})[0]["out"]["update_auto_apply_on_quit"] is False
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update.state_dir, update._state, update._prerelease, update._lock = state, "ready", False, threading.RLock()
    update._policy, update._restart_refusal = (lambda: default_update_policy(state)), None
    update._request_restart = lambda: pytest.fail("restarted with auto-update off")
    assert update.install_if_safe(closing=True, canvas_running=False, user_idle=True) is False
    assert update.apply_on_quit() is False
    _edit_setting(server, "update_auto_apply_on_quit", True)                           # ON again
    assert default_update_policy()["auto_apply_on_quit"] is True and update.apply_on_quit() is True
    assert tool_settings({"tool": "workshop"}, {})[0]["out"]["update_auto_apply_on_quit"] is True
    with pytest.raises(Exception, match="within its Settings bounds"):
        _edit_setting(server, "update_idle_minutes", 0)                                # refused: nothing stored
    assert "update_idle_minutes" not in saved_application_settings()


def test_the_canvas_reads_the_effective_update_settings_it_displays(monkeypatch, tmp_path):
    """The Workshop card/Properties render from this (api.refreshLiveUpdatePolicy), never the file's stored copy."""
    from nodelang.nograph_server import r_settings_action

    state = tmp_path / "state"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    server = _settings_server(state)
    read = lambda: r_settings_action(server, SimpleNamespace(body={"function": "readUpdatePolicySettings"}))["result"]
    assert read()["update_auto_apply_on_quit"] is True and read()["update_idle_minutes"] == 15   # defaults
    _edit_setting(server, "update_auto_apply_on_quit", False)
    assert read()["update_auto_apply_on_quit"] is False                                      # what the card shows


def test_an_older_saved_workflow_reopened_and_run_emits_the_live_setting(monkeypatch, tmp_path):
    """Codex: a workflow saved while the default was On, Settings then set Off, reopen + Run emitted On."""
    from nodelang.application_update import default_update_policy, saved_application_settings
    from nodelang.pipeline_engines import tool_settings

    state = tmp_path / "state"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    saved_in_file = {"tool": "workshop", "update_auto_apply_on_quit": True, "update_idle_minutes": 15}
    _edit_setting(_settings_server(state), "update_auto_apply_on_quit", False)
    out = tool_settings(saved_in_file, {})[0]["out"]                                     # Run on the reopened file
    assert out["update_auto_apply_on_quit"] is False                                   # the node emits Off
    assert saved_application_settings() == {"update_auto_apply_on_quit": False}        # running never wrote On
    assert default_update_policy()["auto_apply_on_quit"] is False


def test_the_update_policy_reads_the_saved_settings_value(tmp_path):
    from nodelang.application_update import default_update_policy
    from nodelang.nograph_server import JsonFile, r_settings_action

    state = tmp_path / "state"
    assert default_update_policy(state)["auto_apply_on_quit"] is True     # nothing saved: catalogue default
    server = SimpleNamespace(state_dir=state, files={
        "settings": JsonFile(state / "settings" / "settings.json", {"settingsScope": "User"}),
        "companion": JsonFile(state / "settings" / "companion.json", {})})
    saved = r_settings_action(server, SimpleNamespace(body={"function": "setApplicationSetting",
                                                             "args": ["update_auto_apply_on_quit", False]}))
    assert saved["result"]["update_auto_apply_on_quit"] is False
    assert default_update_policy(state)["auto_apply_on_quit"] is False
    with pytest.raises(Exception, match="within its Settings bounds"):
        r_settings_action(server, SimpleNamespace(body={"function": "setApplicationSetting",
                                                         "args": ["update_idle_minutes", 99999]}))
    assert default_update_policy(state)["idle_minutes"] == 15                 # the refused value was never stored


def test_a_package_swapped_at_the_handoff_is_never_installed(tmp_path):
    """Codex: the caller selected build X; the staged file was replaced by another valid build before the drain."""
    release = _build_output(tmp_path / "release", "20261120-1200-abc4321", "2026-11-20T08:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20261119-0904-665c785", "2026-11-19T05:04:00Z")
    state = tmp_path / "state"
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    marker = json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
    selected = ("20261118-0000-0000000", marker["sha256"])          # what the caller selected earlier
    before = (state / "updates" / "staged.json").read_bytes()
    result = qu.apply_staged(state, app, expect=selected, runner=lambda *a, **k: pytest.fail("Setup ran"),
                             stop_runtime=lambda _d: pytest.fail("stopped a process"),
                             drain=lambda *_a: pytest.fail("drained connectors"))
    assert result["applied"] is False and result["reason"].startswith("staged build changed since it was selected")
    assert (state / "updates" / "staged.json").read_bytes() == before   # the replacement is left exactly as it is
    wrong_sha = (marker["build_id"], "0" * 64)
    assert qu.apply_staged(state, app, expect=wrong_sha, runner=lambda *a, **k: pytest.fail("Setup ran"),
                           stop_runtime=lambda _d: pytest.fail("stopped"), drain=lambda *_a: pytest.fail("drained"))["applied"] is False
    calls = []
    matching = (marker["build_id"], marker["sha256"].upper())          # the selected one: case does not matter
    qu.apply_staged(state, app, expect=matching, runner=lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=1),
                    stop_runtime=lambda _d: None, drain=lambda *_a: None)
    assert len(calls) == 1


@pytest.mark.skipif(not PWSH, reason="Windows publisher requires PowerShell")
def test_preview_creation_and_same_release_promotion(tmp_path, monkeypatch):
    monkeypatch.delenv("PSModulePath", raising=False)
    release = _build_output(tmp_path / "release", "next", "2026-11-22T20:31:10Z")
    manifest = json.loads((release / "release.json").read_bytes())
    manifest["requirements_sha256"] = "a" * 64
    (release / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
    with (release / "release-notes.md").open("ab") as stream:
        stream.write(("REQUIREMENTS_SHA256: " + "a" * 64 + "\n").encode())
    candidate = offer_check.reconcile(release)["github_release"]
    candidate.update(id=42, draft=True, prerelease=True, target_commitish=REVISION)
    url = candidate["assets"][0]["browser_download_url"].rsplit("/", 1)[0]
    names = set(offer_check.FILES) - {"release-notes.md", offer_check.INSTALLED_MANIFEST}
    candidate["assets"] = [
        dict(id=n, name=name, size=(release / name).stat().st_size,
             digest="sha256:" + _sha((release / name).read_bytes()), browser_download_url=url + "/" + name)
        for n, name in enumerate(sorted(names), 1)]
    stable = dict(candidate, id=10, tag_name="old", prerelease=False, draft=False,
                  body=candidate["body"].replace("2026-11-22", "2026-11-21"),
                  assets=[dict(a, browser_download_url=a["browser_download_url"].replace("build-next", "old"))
                          for a in candidate["assets"]])
    def save(name, record):
        (tmp_path / name).write_text(json.dumps(record), encoding="utf-8")
    save("stable.json", stable)
    save("former.json", stable)
    save("template.json", candidate)
    # Only the HTTP transport changes: run both the release checker and the updater parser.
    (tmp_path / "transport.py").write_text(dedent("""
        import io, json, runpy, sys, urllib.request, urllib.error
        from pathlib import Path
        root = Path(__file__).parent
        def read(name):
            return json.loads((root / name).read_text(encoding="utf-8-sig"))
        class Response(io.BytesIO):
            status = 200
        def open_fixture(request, timeout=0):
            key = request.full_url.split('/repos/Fargaly/ArchHub/')[-1]
            if key == "releases/latest": data = read("stable.json")
            elif key == "releases/10": data = read("former.json")
            elif key == "releases/42": data = read("preview.json")
            elif key == "releases?per_page=20": data = [read("preview.json"), read("stable.json")]
            elif key == "git/ref/tags/build-next" and not (root / "ref").exists():
                raise urllib.error.HTTPError(request.full_url, 404, "absent", {}, None)
            elif key in ("commits/tags/build-next", "git/ref/tags/build-next"):
                data = {"sha": (root / "ref").read_text().strip()}
            elif key.startswith("commits/") and key[8:] == read("template.json")["target_commitish"]:
                data = {"sha": key[8:]}
            else: raise AssertionError(key)
            if (root / "fault").exists() and "ready" in sys.argv:
                fault = (root / "fault").read_text()
                if key == "releases/latest" and fault == "stable": data["body"] += " "
                if key == "releases/42" and fault == "preview": data["assets"][0]["id"] += 100
                if key == "releases?per_page=20" and fault == "feed": data = [read("stable.json")]
            return Response(json.dumps(data).encode())
        urllib.request.urlopen = open_fixture
        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name="__main__")
    """), encoding="utf-8")
    harness = tmp_path / "cmd.ps1"
    harness.write_text(r"""param($root,$publisher,$py,$mode,[switch]$Plan)
$ErrorActionPreference='Stop'
function Checker {
    $args2 = @($args[0..2]) + @("$root/transport.py") + @($args[3..($args.Count-1)])
    & $py @args2
}
function gh {
    $global:LASTEXITCODE=0
    $command = $args -join ' '
    if ($command -like 'release create *') {
        if ($command -notlike '*--draft *' -or $command -notlike '*--prerelease*') { throw $command }
        $index = [array]::IndexOf($args,'--notes-file')
        $r = Get-Content "$root/template.json" -Raw | ConvertFrom-Json
        $r.body = [IO.File]::ReadAllText($args[$index+1])
    } elseif ($command -like 'release view *') { 42; return }
    elseif ($command -eq 'api repos/Fargaly/ArchHub/releases/42') { Get-Content "$root/preview.json" -Raw; return }
    elseif ($command -like 'api repos/Fargaly/ArchHub/git/refs --method POST *') {
        if (Test-Path "$root/ref") { throw 'ref collision' }
        [IO.File]::WriteAllText("$root/ref", ($args | Where-Object { $_ -like 'sha=*' }).Substring(4)); return
    } elseif ($command -like 'api repos/Fargaly/ArchHub/releases/42 --method PATCH *') {
        $r = Get-Content "$root/preview.json" -Raw | ConvertFrom-Json
        if ($args -contains 'make_latest=true' -and $args -contains 'prerelease=false') {
            $r.prerelease=$false
            [IO.File]::WriteAllText("$root/stable.json", ($r | ConvertTo-Json -Depth 8))
        } elseif ($args -contains 'make_latest=false' -and $args -contains 'draft=false' -and $args -contains 'prerelease=true') {
            $r.draft=$false
        } else { throw $command }
    } else { throw $command }
    [IO.File]::WriteAllText("$root/preview.json", ($r | ConvertTo-Json -Depth 8))
    Add-Content "$root/mutations" $command
}
$options = @{StableReleaseId=10;ExpectedSourceRevision=(Get-Content "$root/template.json" -Raw | ConvertFrom-Json).target_commitish}
if ($mode -eq 'create') { $options.CreatePreview=$true } else { $options.PromotePreview=$true; $options.PreviewReleaseId=42 }
& $publisher -ReleaseDirectory "$root/release" -PythonPath Checker @options -DryRun:$Plan
""", encoding="utf-8")
    def run(mode, dry=False, refused=False):
        r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness), str(tmp_path),
                            str(ROOT / "03.TOOLS/packaging/windows/publish_release.ps1"),
                            sys.executable, mode] + (["-Plan"] if dry else []),
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        assert (r.returncode != 0) == refused, r.stderr.decode(errors="replace")
    run("create", dry=True)
    assert not (tmp_path / "mutations").exists()
    run("create")
    preview = json.loads((tmp_path / "preview.json").read_bytes())
    assert preview == dict(candidate, draft=False)
    assert json.loads((tmp_path / "stable.json").read_bytes()) == stable
    run("create", refused=True)
    run("promote", dry=True)
    for fault in ("stable", "preview", "feed"):
        (tmp_path / "fault").write_text(fault)
        run("promote", refused=True)
    (tmp_path / "fault").unlink()
    for corrupted in (dict(preview, id=43), dict(preview, assets=preview["assets"][:-1]),
                      dict(preview, assets=[dict(a, digest="sha256:" + "0" * 64) for a in preview["assets"]])):
        save("preview.json", corrupted)
        run("promote", refused=True)
    save("preview.json", preview)
    (tmp_path / "ref").write_text("f" * 40)
    run("promote", refused=True)
    (tmp_path / "ref").write_text(REVISION)
    save("stable.json", dict(stable, body=stable["body"].replace("2026-11-21", "2026-11-23")))
    run("promote", refused=True)
    save("stable.json", stable)
    assert len((tmp_path / "mutations").read_text().splitlines()) == 2
    run("promote")
    assert json.loads((tmp_path / "stable.json").read_bytes()) == dict(preview, prerelease=False)
    assert len((tmp_path / "mutations").read_text().splitlines()) == 3


def test_verify_published_budget_has_a_default():
    """An omitted verify_minutes made fromJSON('') fail before the Windows job started."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    block = workflow[workflow.index("      verify_minutes:"):workflow.index("\npermissions:")]
    assert "options: ['15', '20', '25', '30']" in block
    # An omitted budget falls back to the first allowed one in both the job limit and the step check.
    assert "timeout-minutes: ${{ fromJSON(inputs.verify_minutes || '15') }}" in workflow
    assert "VERIFY_MINUTES: ${{ inputs.verify_minutes || '15' }}" in workflow


def test_clean_windows_verify_checks_the_installed_update_controller():
    """e988 eb8390bd: the published-installer run clicks and re-reads the shipped update controller."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "real_app_check/update_controller_check.py" in workflow
    assert "archhub-verify-published/update-controller.json" in workflow   # uploaded beside install.json
    assert (ROOT / "03.TOOLS/tools/real_app_check/update_controller_check.py").is_file()


def test_preview_channel_picks_the_newest_validated_build_whatever_the_list_order():
    """e988 d50e5d09: GitHub listed stable 0ea5038, then 50d908c, then the new 9864 pre-release; the first
    non-draft was taken, so the preview channel offered the old stable. The newest validated build wins."""
    import io

    def release(build_id, built_at, prerelease, *, draft=False, body_extra=""):
        tag = "build-" + build_id
        digest = hashlib.sha256(build_id.encode()).hexdigest()
        body = ("## Build\nBUILD_ID: %s\n" % build_id + ("BUILT_AT: %s\n" % built_at if built_at else "")
                + "SHA256 %s: %s\n" % (qu.ASSET_NAME, digest) + body_extra)
        return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "body": body, "assets": [
            {"name": qu.ASSET_NAME, "size": 5,
             "browser_download_url": "https://github.com/Fargaly/ArchHub/releases/download/%s/%s" % (tag, qu.ASSET_NAME)}]}

    def read(items):
        payload = json.dumps(items).encode()
        return qu.read_latest_release(lambda _request, timeout: io.BytesIO(payload), channel="preview")

    stable_old = release("20261123-2137-0ea5038", "2026-11-23T17:37:19Z", False)
    stable_older = release("20261123-1723-50d908c", "2026-11-23T13:23:00Z", False)
    newest = release("20261124-0112-9864b61", "2026-11-23T21:12:00Z", True)
    found = read([stable_old, stable_older, newest])
    assert found["build_id"] == "20261124-0112-9864b61" and qu.read_latest_release.saw_prerelease is True
    assert read([newest, stable_old])["build_id"] == "20261124-0112-9864b61"
    # Once the stable is newer than every pre-release, the preview channel follows it.
    later_stable = release("20261125-0900-aaaaaaa", "2026-11-25T09:00:00Z", False)
    assert read([newest, later_stable])["build_id"] == "20261125-0900-aaaaaaa"
    assert qu.read_latest_release.saw_prerelease is False
    # Drafts and releases with an invalid identity never win, even when their date is newest.
    draft = release("20261130-0000-bbbbbbb", "2026-11-30T00:00:00Z", True, draft=True)
    broken = release("20261129-0000-ccccccc", "2026-11-29T00:00:00Z", True, body_extra="BUILT_AT: twice\n")
    assert read([draft, broken, stable_old])["build_id"] == "20261123-2137-0ea5038"
    assert read([draft, broken]) is None
    # The stable channel is unchanged: the latest-release object, never a pre-release.
    payload = json.dumps(stable_old).encode()
    assert qu.read_latest_release(lambda _r, timeout: io.BytesIO(payload))["build_id"] == "20261123-2137-0ea5038"
    payload = json.dumps(newest).encode()
    assert qu.read_latest_release(lambda _r, timeout: io.BytesIO(payload)) is None


def test_publisher_resumes_a_timed_out_preview_draft_instead_of_creating_another(tmp_path):
    """e988 2e8a46bb: GitHub timed out returning the create response, leaving draft 456140451 with no assets."""
    script = ROOT / "03.TOOLS/packaging/windows/publish_release.ps1"
    source = script.read_text(encoding="utf-8")
    body = source[source.index("if ($CreatePreview -and $ResumeDraftId) {"):source.index("} elseif ($CreatePreview) {")]
    assert '"repos/$Repository/releases/$ResumeDraftId"' in body
    assert "$existing.draft -ne $true" in body and "$existing.tag_name -cne $tag" in body
    assert "$existing.target_commitish -cne $offer.source_revision" in body
    assert "gh release upload $tag @missing" in body and "--clobber" not in body   # never overwrite present bytes
    assert "release create" not in body                                          # never a second draft
    # The resumed draft goes through the same ready/after checks as a fresh one.
    after = source[source.index("} elseif ($CreatePreview) {"):]
    assert after.index("Read-PublicationState 'ready'") < after.index("Read-PublicationState 'after'")
    # Resume belongs to -CreatePreview only.
    for extra in (["-PromotePreview", "-PreviewReleaseId", "7"], []):
        done = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script), "-ReleaseDirectory", str(tmp_path),
                               "-ExpectedSourceRevision", "a" * 40, "-StableReleaseId", "5", "-ResumeDraftId", "9",
                               "-PythonPath", sys.executable, *extra], capture_output=True, text=True, timeout=60)
        assert done.returncode != 0 and "Choose one release operation" in (done.stdout + done.stderr)


def test_an_uncertain_publish_patch_is_settled_by_the_read_only_after_check(tmp_path):
    """e988 be0aad49: the publish PATCH on 456140451 timed out but had succeeded; the after check alone decides.
    e988 9e38ad7d: with native errors escalated, a non-zero PATCH threw before reaching that check."""
    source = (ROOT / "03.TOOLS/packaging/windows/publish_release.ps1").read_text(encoding="utf-8")
    start = source.index("if ($patchExit -ne 0) {")
    body = source[start:source.index('Write-Output "Verified $mode of release', start)]
    assert body.count("Read-PublicationState 'after'") == 2                 # once on the uncertain path, once normally
    assert "gh api" not in body                                              # the mutation is never replayed
    assert "Publication response uncertain and not verified" in body         # unverifiable stays unknown, never success
    # Run the publisher's exact PATCH lines against a real native gh that exits 17, under the publisher's preferences.
    invoke = source[source.index("    $PSNativeCommandUseErrorActionPreference = $false"):start]
    (tmp_path / "gh.cmd").write_text("@exit /b 17\r\n", encoding="ascii")
    probe = tmp_path / "probe.ps1"
    probe.write_text("$ErrorActionPreference = 'Stop'\n$PSNativeCommandUseErrorActionPreference = $true\n"
                     "$env:PATH = '" + str(tmp_path) + ";' + $env:PATH\n$endpoint = 'x'\n$patch = @()\n"
                     + invoke + "\"after_reached=$patchExit escalation=$PSNativeCommandUseErrorActionPreference\"\n",
                     encoding="utf-8")
    pwsh7 = shutil.which("pwsh") or PWSH
    done = subprocess.run([pwsh7, "-NoProfile", "-NonInteractive", "-File", str(probe)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "after_reached=17 escalation=True" in done.stdout                  # reached, and the preference restored
