"""Regression: the Startup-folder .vbs shim must be VALID VBScript.

Root cause (founder hit it live, 2026-06-19): `_windows_install_startup_folder`
embedded `full_cmd` — which already wraps the python path in quotes for
`schtasks /tr` — directly into a VBScript string literal:

    oShell.Run "{full_cmd}", 0, False

VBScript escapes a literal `"` by DOUBLING it. The un-escaped form emitted
`oShell.Run ""C:\...python.exe" -m ...` which VBScript parses as an EMPTY string
("") immediately followed by a bare `C:\...` token → compile error 800A0401
"Expected end of statement" in a Windows Script Host popup at every logon, and
the brain never autostarted. The fix doubles the quotes before embedding.

These gates assert the emitted .vbs is a single well-formed string literal that
ROUND-TRIPS back to the original command (the real semantic check), plus a guard
for the exact broken byte-pattern. RED on the un-escaped code, GREEN after.
"""
from __future__ import annotations

import json
import re
import socket

from personal_brain import service


def test_existing_daemon_state_never_competes_with_an_occupied_port(monkeypatch):
    monkeypatch.setattr(service, "_probe_daemon", lambda _port: True)
    monkeypatch.setattr(service, "_port_is_bound", lambda _port: True)
    assert service._existing_daemon_state(8473) == "healthy"

    monkeypatch.setattr(service, "_probe_daemon", lambda _port: False)
    assert service._existing_daemon_state(8473) == "occupied"

    monkeypatch.setattr(service, "_port_is_bound", lambda _port: False)
    assert service._existing_daemon_state(8473) == "available"


def test_pid_bound_liveness_probe_parses_the_serving_process(monkeypatch):
    observed = {}
    envelope = {
        "result": {
            "structuredContent": {"ok": True, "server_pid": 4321},
            "content": [],
        },
    }

    class Response:
        status = 200

        def read(self, _limit):
            return ("event: message\ndata: " + json.dumps(envelope) + "\n").encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        observed["timeout"] = timeout
        observed["payload"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(service.urllib.request, "urlopen", fake_urlopen)

    assert service._probe_daemon_details(8473, timeout=9.0) == {
        "ok": True,
        "server_pid": 4321,
    }
    assert observed["timeout"] == 9.0
    assert observed["payload"]["params"]["name"] == "brain.liveness"


def test_pid_bound_liveness_probe_rejects_a_reply_without_a_process_id(monkeypatch):
    envelope = {"result": {"structuredContent": {"ok": True}, "content": []}}

    class Response:
        status = 200

        def read(self, _limit):
            return ("data: " + json.dumps(envelope) + "\n").encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert service._probe_daemon_details(8473) is None


def test_only_a_pid_bound_reply_can_prove_the_supervised_child_owns_listener():
    assert service._listener_is_owned_by_child({"server_pid": 4321}, 4321) is True
    assert service._listener_is_owned_by_child({"server_pid": 8765}, 4321) is False
    assert service._listener_is_owned_by_child(None, 4321) is False


def test_bound_port_is_occupied_even_when_it_cannot_accept_a_probe_connection(monkeypatch):
    """A slow listener must never trigger a competing Brain startup."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        monkeypatch.setattr(
            service.socket,
            "create_connection",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("busy")),
        )
        assert service._port_is_bound(port) is True
    finally:
        listener.close()


def test_windows_port_probe_requests_exclusive_address_use(monkeypatch):
    """A reuse-enabled legacy listener must still block a new Brain child."""
    calls = []

    class Probe:
        def setsockopt(self, *args):
            calls.append(("setsockopt", args))

        def bind(self, address):
            calls.append(("bind", address))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.socket, "SO_EXCLUSIVEADDRUSE", 77, raising=False)
    monkeypatch.setattr(service.socket, "socket", lambda *_args: Probe())

    assert service._port_is_bound(8473) is False
    assert calls == [
        ("setsockopt", (service.socket.SOL_SOCKET, 77, 1)),
        ("bind", ("127.0.0.1", 8473)),
        ("close",),
    ]


def test_runtime_status_distinguishes_the_listener_from_supervisor_heartbeat(monkeypatch):
    monkeypatch.setattr(service, "_existing_daemon_state", lambda _port: "healthy")
    monkeypatch.setattr(service, "_probe_daemon_details", lambda _port: None)
    monkeypatch.setattr(service, "_supervisor_heartbeat_age_s", lambda: 3.2)
    monkeypatch.setattr(
        service,
        "_read_supervisor_state",
        lambda: {"state": "fresh", "mode": "adopting", "listener": "healthy", "age_seconds": 1.0},
    )

    status = service._runtime_status(8473)

    assert status == {
        "port": 8473,
        "listener": "healthy",
        "liveness": "legacy-health",
        "health": "degraded",
        "supervisor_heartbeat": "fresh",
        "supervisor_heartbeat_age_s": 3.2,
        "recovery_action": "controlled_rollover_required",
        "supervisor": {"state": "fresh", "mode": "adopting", "listener": "healthy", "age_seconds": 1.0},
    }


def test_runtime_status_requires_pid_bound_liveness_for_a_healthy_claim(monkeypatch):
    monkeypatch.setattr(service, "_existing_daemon_state", lambda _port: "healthy")
    monkeypatch.setattr(
        service, "_probe_daemon_details", lambda _port: {"ok": True, "server_pid": 4321}
    )
    monkeypatch.setattr(service, "_supervisor_heartbeat_age_s", lambda: None)
    monkeypatch.setattr(service, "_read_supervisor_state", lambda: {"state": "unavailable"})

    status = service._runtime_status(8473)

    assert status["liveness"] == "pid-bound"
    assert status["health"] == "healthy"
    assert status["recovery_action"] == "none"


def test_supervisor_state_receipt_is_bounded_and_rejects_invalid_shapes(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_supervisor_log_dir", lambda: tmp_path)
    monkeypatch.setattr(service, "HEALTH_INTERVAL_S", 10.0)
    monkeypatch.setattr(service, "HEALTH_TIMEOUT_S", 4.0)
    monkeypatch.setattr(service.time, "time", lambda: 100.0)

    service._write_supervisor_state(
        port=8473,
        mode="waiting",
        listener="occupied",
        child_pid=123,
        consecutive_failures=2,
    )

    assert service._read_supervisor_state() == {
        "state": "fresh",
        "mode": "waiting",
        "listener": "occupied",
        "age_seconds": 0.0,
    }

    (tmp_path / "brain-supervisor.state.json").write_text("[]", encoding="utf-8")
    assert service._read_supervisor_state() == {"state": "unavailable"}


def _emit_vbs(monkeypatch, tmp_path, full_cmd: str) -> str:
    # Both _windows_install_startup_folder and _startup_vbs_path resolve the
    # folder through _startup_folder_path — point it at a throwaway dir.
    monkeypatch.setattr(service, "_startup_folder_path", lambda: tmp_path)
    res = service._windows_install_startup_folder(full_cmd)
    assert res.get("ok") is True, res
    return (tmp_path / "ArchHub-Brain.vbs").read_text(encoding="utf-8")


def test_vbs_quotes_round_trip(monkeypatch, tmp_path):
    """The Run-line string literal decodes back to the EXACT full_cmd."""
    full_cmd = ('"C:\\Users\\x\\AppData\\Local\\Python\\python.exe"'
                ' -m personal_brain.service supervise --port 8473')
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    m = re.search(r'oShell\.Run "(.*)", 0, False', vbs)
    assert m, f"no well-formed Run line in:\n{vbs}"
    literal = m.group(1)
    # VBScript: "" inside a string is one literal ". Decode it back.
    decoded = literal.replace('""', '"')
    assert decoded == full_cmd, (
        f"escaped .vbs literal does not round-trip to the command.\n"
        f"decoded={decoded!r}\nexpected={full_cmd!r}")


def test_vbs_no_broken_empty_string_pattern(monkeypatch, tmp_path):
    """Guard the exact 800A0401 byte-pattern: Run followed by ""<drive>."""
    full_cmd = '"C:\\py\\python.exe" -m personal_brain.service supervise --port 8473'
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    assert 'oShell.Run ""C:' not in vbs, (
        "emitted the broken empty-string-then-bare-path form (800A0401)")
    assert 'oShell.Run """C:' in vbs, "expected the properly escaped triple-quote opening"


def test_vbs_unquoted_command_unaffected(monkeypatch, tmp_path):
    """A command with no embedded quotes is emitted verbatim (no over-escaping)."""
    full_cmd = "pythonw -m personal_brain.service supervise --port 8473"
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    assert f'oShell.Run "{full_cmd}", 0, False' in vbs


def test_autostart_prefers_windowless_pythonw(monkeypatch, tmp_path):
    """The logon autostart must launch the WINDOWLESS pythonw.exe (no console
    window) — python.exe always allocates a console; pythonw.exe doesn't.
    Derived next to sys.executable. RED before the fix (used sys.executable =
    python.exe), GREEN after. Founder saw a console pop at logon 2026-06-19."""
    import types

    exe = tmp_path / "python.exe"
    exe.write_text("")
    (tmp_path / "pythonw.exe").write_text("")  # sibling windowless interpreter
    monkeypatch.setattr(service.sys, "executable", str(exe))

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    res = service._windows_install(port=8473)
    assert res.get("ok") is True, res
    cmd = captured["cmd"]
    tr = cmd[cmd.index("/tr") + 1]
    assert "pythonw.exe" in tr, f"autostart must launch pythonw.exe, got: {tr}"
