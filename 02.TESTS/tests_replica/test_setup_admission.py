"""Court: a Setup run by hand uses the updater's admission/drain owner before its marker or any program file.

Disposable folders and real supervisor processes only; no installed app, no agent connection of this PC.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "01.APP"
sys.path.insert(0, str(APP))
from nodelang import quiet_update as qu  # noqa: E402

SLOW = textwrap.dedent("""
    import json, os, sys, time
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        if m["method"] == "slow":
            time.sleep(m["params"]["seconds"])
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "f", "version": "1"}} \\
            if m["method"] == "initialize" else {"content": [{"type": "text", "text": str(os.getpid())}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\\n")
        sys.stdout.flush()
""")


def _layout(tmp_path):
    app = tmp_path / "ArchHub"
    runtime = tmp_path / "ArchHub-Runtime"
    (runtime / "connectors").mkdir(parents=True)
    app.mkdir()
    fixture = tmp_path / "slow.py"
    fixture.write_text(SLOW, encoding="utf-8")
    return app, runtime, fixture


def _start(script, app, fixture, *, report):
    """A supervisor process whose command line names this layout's ArchHub-Runtime\\mcp_supervisor.py."""
    load = ("import importlib.util,os,sys;from pathlib import Path;"
            "s=importlib.util.spec_from_file_location('sup',sys.argv[1]);m=importlib.util.module_from_spec(s);"
            "s.loader.exec_module(m);kw={'pause':Path(sys.argv[2])};"
            + ("kw['report']=Path(sys.argv[3])/('%d.json'%os.getpid());" if report else "")
            + "sys.exit(m.Supervisor(sys.argv[4:],dict(os.environ),sys.stdin.buffer,sys.stdout.buffer,**kw).run())")
    return subprocess.Popen([sys.executable, "-I", "-c", load, str(script), str(app / ".archhub-installing"),
                             str(script.parent / "connectors"), sys.executable, "-I", str(fixture)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _send(proc, message):
    proc.stdin.write((json.dumps(message) + "\n").encode())
    proc.stdin.flush()


def _reply(proc, want_id, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        reply = json.loads(proc.stdout.readline())
        if reply.get("id") == want_id:
            return reply
    raise AssertionError("no reply for %r" % want_id)


def _init(proc):
    _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "result" in _reply(proc, 1)
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()


def _stop(proc):
    proc.stdin.close()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()


def _legacy_supervisor(runtime):
    """The exact pre-receipt supervisor of 665c785f (the founder report's legacy script), from git history."""
    try:
        source = subprocess.run(["git", "show", "665c785f:01.APP/nodelang/mcp_supervisor.py"], cwd=APP.parent,
                                capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git history with 665c785f is not available in this checkout")
    script = runtime / "mcp_supervisor.py"
    script.write_bytes(source)
    return script


def test_manual_setup_goes_ahead_past_a_legacy_supervisor_and_its_call_keeps_running(tmp_path):
    """Founder 2026-11-25: Update closes everything; a connector that cannot report no longer holds Setup."""
    app, runtime, fixture = _layout(tmp_path)
    proc = _start(_legacy_supervisor(runtime), app, fixture, report=False)
    try:
        _init(proc)
        _send(proc, {"jsonrpc": "2.0", "id": 5, "method": "slow", "params": {"seconds": 4}})
        time.sleep(0.5)  # the call is in flight in the legacy supervisor's connector
        drain = lambda d, a: qu.drain_connectors(d, a, sleep=lambda _s: None, bound=1.0)
        mode, attempt = qu.setup_admission(app, "B1", drain=drain)
        assert mode == "owned" and (runtime / "connectors" / qu.DRAIN_REQUEST).exists()
        qu.reopen_connectors(app, attempt)
        answered = _reply(proc, 5)
        assert "result" in answered, "the legacy supervisor's call got its real answer, not a cut"
        assert proc.poll() is None
    finally:
        _stop(proc)


def test_manual_setup_waits_for_the_call_in_flight_then_owns_and_reopens_its_drain(tmp_path):
    app, runtime, fixture = _layout(tmp_path)
    script = runtime / "mcp_supervisor.py"
    script.write_bytes((APP / "nodelang" / "mcp_supervisor.py").read_bytes())
    proc = _start(script, app, fixture, report=True)
    try:
        _init(proc)
        report = runtime / "connectors" / ("%d.json" % proc.pid)
        for _ in range(100):
            if report.is_file():
                break
            time.sleep(0.1)
        _send(proc, {"jsonrpc": "2.0", "id": 5, "method": "slow", "params": {"seconds": 3}})
        time.sleep(0.5)
        outcome, started = {}, time.time()
        worker = threading.Thread(target=lambda: outcome.update(result=qu.setup_admission(app, "B2")))
        worker.start()
        answered = _reply(proc, 5)
        worker.join(60)
        assert "result" in answered, "the call in flight finished with its real answer"
        mode, attempt = outcome["result"]
        assert mode == "owned" and attempt.startswith("setup-B2-")
        assert time.time() - started >= 2, "admission waited for the call"
        request = runtime / "connectors" / qu.DRAIN_REQUEST
        assert json.loads(request.read_text(encoding="utf-8")) == {"attempt": attempt}
        _send(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call"})
        assert _reply(proc, 6)["error"]["data"]["archhub"] == "unstarted", "no new call starts while Setup holds it"
        qu.reopen_connectors(app, attempt)  # what Setup's DeinitializeSetup does for its own attempt
        assert not request.exists()
        for attempt_no in range(40):
            _send(proc, {"jsonrpc": "2.0", "id": 10 + attempt_no, "method": "tools/call"})
            if "result" in _reply(proc, 10 + attempt_no):
                break
            time.sleep(0.25)
        else:
            raise AssertionError("calls never flowed again after the drain was reopened")
    finally:
        _stop(proc)


def test_setup_inherits_only_the_drain_of_the_updater_that_launched_it(tmp_path):
    app, runtime, _fixture = _layout(tmp_path)
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    idle, busy = (lambda _d, attempt: []), (lambda _d, attempt: ["pid 7: 1 call(s) in flight"])
    request.write_text(json.dumps({"attempt": "A"}), encoding="utf-8")
    before = request.read_bytes()
    assert qu.setup_admission(app, "B3", expected="A", acknowledgements=idle) == ("existing", "A")
    assert qu.setup_admission(app, "B3", expected="A", acknowledgements=busy) == ("existing", "A")  # busy never holds
    for kwargs, match in (({"expected": "Z", "acknowledgements": idle}, "another install attempt"),
                          ({"acknowledgements": idle, "ancestors": lambda: [4242]}, "another install attempt")):
        with pytest.raises(ValueError, match=match):
            qu.setup_admission(app, "B3", **kwargs)
    assert request.read_bytes() == before, "Setup never rewrites or removes another attempt's drain"
    # An older updater passes no attempt: its "<build>-<pid>-<ns>" request is inherited only from a live ancestor.
    request.write_text(json.dumps({"attempt": "B3-4242-99"}), encoding="utf-8")
    assert qu.setup_admission(app, "B3", acknowledgements=idle, ancestors=lambda: [17, 4242]) == ("existing", "B3-4242-99")
    with pytest.raises(ValueError, match="another install attempt"):
        qu.setup_admission(app, "B3", acknowledgements=idle, ancestors=lambda: [17])
    with pytest.raises(ValueError, match="another install attempt"):  # same pid, other build
        qu.setup_admission(app, "B9", acknowledgements=idle, ancestors=lambda: [4242])
    request.unlink()
    with pytest.raises(ValueError, match="drain request is missing"):
        qu.setup_admission(app, "B3", expected="A", acknowledgements=idle)
    assert not request.exists()


@pytest.mark.parametrize("raw, match", [
    ("{}", "names no install attempt"),
    ('{"attempt": ""}', "names no install attempt"),
    ('{"attempt": "   "}', "names no install attempt"),
    ('{"attempt": 7}', "names no install attempt"),
    ('{"attempt": "A", "extra": 1}', "names no install attempt"),
    ("[]", "names no install attempt"),
    ("{not json", "unreadable"),
    ('{"attempt": "setup-B0-11-22"}', "another install attempt"),  # a stale earlier manual Setup
])
def test_malformed_foreign_or_stale_requests_hold_setup_and_are_left_as_they_are(tmp_path, raw, match):
    app, runtime, _fixture = _layout(tmp_path)
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    request.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        qu.setup_admission(app, "B3", acknowledgements=lambda _d, attempt: [], ancestors=lambda: [11])
    assert request.read_text(encoding="utf-8") == raw


def test_a_call_that_does_not_finish_in_the_bound_no_longer_holds_setup(tmp_path):
    app, runtime, _fixture = _layout(tmp_path)
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    busy = lambda _d, attempt: ["pid 7: 1 call(s) in flight"] if attempt else []
    drain = lambda d, a: qu.drain_connectors(d, a, acknowledgements=busy, sleep=lambda _s: None, bound=1.0)
    mode, attempt = qu.setup_admission(app, "B4", acknowledgements=busy, drain=drain)
    assert mode == "owned" and json.loads(request.read_text(encoding="utf-8")) == {"attempt": attempt}
    qu.reopen_connectors(app, attempt)


def test_the_setup_command_prints_its_owned_attempt_for_the_installer(tmp_path, capsys):
    app, runtime, _fixture = _layout(tmp_path)
    assert qu.main(["--setup-admission", str(app), "--build-id", "B5"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("ARCHHUB-ADMISSION owned setup-B5-")
    attempt = line.split()[-1]
    assert json.loads((runtime / "connectors" / qu.DRAIN_REQUEST).read_text(encoding="utf-8")) == {"attempt": attempt}
    qu.reopen_connectors(app, attempt)


def test_a_drain_request_held_open_for_a_moment_is_still_removed(tmp_path, monkeypatch):
    app, runtime, _fixture = _layout(tmp_path)
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({"attempt": "A1"}), encoding="utf-8")
    real, refusals = Path.unlink, iter([PermissionError(32, "in use")] * 3)

    def unlink(self, *args, **kwargs):
        error = next(refusals, None)
        if error is not None:
            raise error
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    qu.reopen_connectors(app, "A1", sleep=lambda _s: None)
    assert not request.exists()
    request.write_text(json.dumps({"attempt": "A1"}), encoding="utf-8")
    refusals = iter([PermissionError(32, "in use")] * 99)
    with pytest.raises(OSError, match="could not be removed"):
        qu.reopen_connectors(app, "A1", sleep=lambda _s: None, tries=3)


# ---- The compiled installer path: a real Inno Setup harness with the SHIPPED connector admission block of ArchHub.iss.

def _compiler():
    import os
    import shutil
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if os.name != "nt" or not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    return compiler


HARNESS = r"""; Court fixture only; never packaged. PrepareToInstall and DeinitializeSetup call the shipped admission code.
[Setup]
AppName=ArchHub connector admission court
AppVersion=1
DefaultDirName={param:app}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
Uninstallable=no
PrivilegesRequired=lowest
CloseApplications=no
RestartApplications=no
OutputBaseFilename=connector-admission-court

[Files]
Source: "{#PayloadPath}\payload.txt"; DestDir: "{app}"; Flags: ignoreversion

[Code]
#include IncludePath

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := AdmitConnectors(ExpandConstant('{app}'), ExpandConstant('{param:runtime}'), ExpandConstant('{param:python}'),
    ExpandConstant('{param:code}'), 'HB', ExpandConstant('{param:ARCHHUBDRAIN|}'));
  if Result <> '' then
    SaveStringToFile(ExpandConstant('{param:refused}'), Result, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Held: AnsiString;
begin
  if CurStep = ssInstall then
    SaveStringToFile(ExpandConstant('{app}\.archhub-installing'), 'HB', False);
  if CurStep = ssPostInstall then
  begin
    if not LoadStringFromFile(ExpandConstant('{param:runtime}\connectors\drain-request.json'), Held) then
      Held := '';
    SaveStringToFile(ExpandConstant('{param:seen}'), Held, False);
  end;
end;

procedure DeinitializeSetup();
begin
  DeleteFile(ExpandConstant('{app}\.archhub-installing'));
  ReleaseSetupDrain(ExpandConstant('{param:runtime}'));
end;
"""


@pytest.fixture(scope="module")
def court(tmp_path_factory):
    root = tmp_path_factory.mktemp("admission-court")
    (root / "payload").mkdir()
    (root / "payload" / "payload.txt").write_text("new build\n", encoding="utf-8")
    code = root / "code" / "nodelang"  # as Setup stages it: a stub package and the owner modules
    code.mkdir(parents=True)
    (code / "__init__.py").write_text("", encoding="utf-8")
    for name in ("quiet_update.py", "canvas_triggers.py"):
        (code / name).write_bytes((APP / "nodelang" / name).read_bytes())
    (root / "court.iss").write_text(HARNESS, encoding="utf-8")
    shipped = (APP.parent / "03.TOOLS" / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    begin, end = shipped.index("{ BEGIN connector admission"), shipped.index("{ END connector admission }")
    include = root / "connector_admission.iss"  # exactly the shipped block, compiled on its own
    include.write_text(shipped[begin:end], encoding="utf-8")
    built = subprocess.run([_compiler(), "/Q", "/O" + str(root / "out"), "/DPayloadPath=" + str(root / "payload"),
                            "/DIncludePath=" + str(include), str(root / "court.iss")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return root / "out" / "connector-admission-court.exe", root / "code"


def _setup(court, tmp_path, app, runtime, *extra):
    exe, code = court
    done = subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/app=" + str(app),
                           "/runtime=" + str(runtime), "/python=" + sys.executable, "/code=" + str(code),
                           "/refused=" + str(tmp_path / "refused.txt"), "/seen=" + str(tmp_path / "seen.txt"), *extra],
                          capture_output=True, timeout=180)
    refused = tmp_path / "refused.txt"
    seen = tmp_path / "seen.txt"
    return (done.returncode, refused.read_text(encoding="utf-8") if refused.exists() else "",
            seen.read_text(encoding="utf-8") if seen.exists() else None)


def test_compiled_setup_installs_past_a_live_legacy_supervisor(court, tmp_path):
    app, runtime, fixture = _layout(tmp_path)
    proc = _start(_legacy_supervisor(runtime), app, fixture, report=False)
    try:
        _init(proc)
        _send(proc, {"jsonrpc": "2.0", "id": 5, "method": "slow", "params": {"seconds": 6}})
        code, refused, _seen = _setup(court, tmp_path, app, runtime)
        assert (code, refused) == (0, "") and (app / "payload.txt").exists()
        assert not (app / ".archhub-installing").exists() and not (runtime / "connectors" / qu.DRAIN_REQUEST).exists()
        assert "result" in _reply(proc, 5), "the legacy supervisor's call still got its real answer"
    finally:
        _stop(proc)


def test_compiled_manual_setup_owns_its_drain_while_installing_and_reopens_after(court, tmp_path):
    app, runtime, _fixture = _layout(tmp_path)
    (runtime / "mcp_supervisor.py").write_bytes((APP / "nodelang" / "mcp_supervisor.py").read_bytes())
    code, refused, seen = _setup(court, tmp_path, app, runtime)
    assert (code, refused) == (0, "") and (app / "payload.txt").exists()
    assert json.loads(seen)["attempt"].startswith("setup-HB-"), "admission stayed closed for the whole install"
    assert not (runtime / "connectors" / qu.DRAIN_REQUEST).exists(), "its own attempt was reopened at the end"
    assert not (app / ".archhub-installing").exists()


def test_compiled_updater_launched_setup_keeps_the_updaters_drain(court, tmp_path):
    app, runtime, _fixture = _layout(tmp_path)
    (runtime / "mcp_supervisor.py").write_bytes((APP / "nodelang" / "mcp_supervisor.py").read_bytes())
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    request.write_text(json.dumps({"attempt": "HB-1-2"}), encoding="utf-8")
    before = request.read_bytes()
    code, refused, _seen = _setup(court, tmp_path, app, runtime, "/ARCHHUBDRAIN=HB-1-2")
    assert (code, refused) == (0, "") and (app / "payload.txt").exists()
    assert request.read_bytes() == before, "the updater reopens its own attempt; Setup leaves it"


@pytest.mark.parametrize("raw", ["{}", '{"attempt": ""}', '{"attempt": "setup-HB-9-9"}'])
def test_compiled_setup_refuses_malformed_or_stale_requests_untouched(court, tmp_path, raw):
    app, runtime, _fixture = _layout(tmp_path)
    (runtime / "mcp_supervisor.py").write_bytes((APP / "nodelang" / "mcp_supervisor.py").read_bytes())
    request = runtime / "connectors" / qu.DRAIN_REQUEST
    request.write_text(raw, encoding="utf-8")
    code, refused, seen = _setup(court, tmp_path, app, runtime)
    assert code != 0 and refused and seen is None and not (app / "payload.txt").exists()
    assert request.read_text(encoding="utf-8") == raw


def test_compiled_fresh_install_proceeds_with_an_empty_runtime_left_by_an_uninstall(court, tmp_path):
    app, runtime, _fixture = _layout(tmp_path)  # ArchHub-Runtime exists, no supervisor script, no environment
    code, refused, _seen = _setup(court, tmp_path, app, runtime, "/python=" + str(tmp_path / "missing" / "python.exe"))
    assert (code, refused) == (0, "") and (app / "payload.txt").exists()
