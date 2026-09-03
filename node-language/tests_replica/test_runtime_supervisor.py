"""Courts for the persistent, graph-admitted local runtime gateway owner."""
from __future__ import annotations

from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.runtime_gateway import BackendGeneration, GatewayError
from nodelang.runtime_supervisor import (
    RuntimeDrainPipe,
    RuntimeSupervisor,
    RuntimeSupervisorConfig,
    RuntimeSupervisorError,
    build_runtime_worker_command,
)


class _FakeProcess:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        self.pid = 7000 + exit_code

    def poll(self):
        return None

    def wait(self, timeout=None):
        return self.exit_code

    def terminate(self):
        self.exit_code = -15

    def kill(self):
        self.exit_code = -9


class _FakeClient:
    def __init__(self, backend: BackendGeneration) -> None:
        self.backend = backend
        self.calls = 0

    def runtime_backend_generation(self) -> BackendGeneration:
        self.calls += 1
        return self.backend


class _FakeGate:
    def __init__(self) -> None:
        self.drained = []
        self.backend = None

    def begin_drain(self, generation: int, *, timeout: float):
        self.drained.append((generation, timeout))


class _FakeGateway:
    def __init__(self, activation_verifier) -> None:
        self.url = "http://127.0.0.1:8495"
        self.activation_verifier = activation_verifier
        self.gate = _FakeGate()
        self.started = False
        self.closed = False
        self.activated = []

    def start(self):
        self.started = True
        return self

    def activate(self, backend: BackendGeneration) -> None:
        self.activation_verifier(backend)
        self.activated.append(backend)
        self.gate.backend = backend

    def close(self) -> None:
        self.closed = True


def _configuration(tmp_path: Path) -> RuntimeSupervisorConfig:
    return RuntimeSupervisorConfig(
        host="127.0.0.1",
        port=8495,
        state_path=tmp_path / "state.json.gz",
        universal_state_path=tmp_path / "universal.sqlite3",
        descriptor_path=tmp_path / "active-universal-runtime.json",
        working_directory=Path(__file__).resolve().parents[1],
        startup_timeout=5.0,
        drain_timeout=3.0,
        restart_delay=0.0,
        max_crashes=3,
        crash_window_seconds=60.0,
    )


def _assert_public_origin_is_separate_from_worker_origin(tmp_path: Path) -> None:
    public_origin = "http://127.0.0.1:8495"
    server = ApplicationServer(
        fresh=True,
        public_server_url=public_origin,
    ).start()
    try:
        assert server.url != public_origin
        assert server.bootstrap_url.startswith(public_origin + "/?bootstrap=")
        readiness = server.dispatch_universal_machine_route({
            "method": "GET",
            "path": "/api/universal/browser-handoff",
            "body": {},
        })
        handoff = server.dispatch_universal_machine_route({
            "method": "POST",
            "path": "/api/universal/browser-handoff",
            "body": {},
        })
        backend = server.dispatch_universal_machine_route({
            "method": "GET",
            "path": "/api/universal/runtime-backend",
            "body": {},
        })
        assert readiness["server_url"] == public_origin
        assert handoff["server_url"] == public_origin
        assert handoff["document_url"].startswith(public_origin + "/?bootstrap=")
        assert backend["server_url"] == server.url
    finally:
        server.close()


def _assert_supervisor_admits_only_exact_signed_generations(tmp_path: Path) -> None:
    config = _configuration(tmp_path)
    backends = [
        BackendGeneration("http://127.0.0.1:61001", 7, "owner-7"),
        BackendGeneration("http://127.0.0.1:61002", 8, "owner-8"),
    ]
    clients = [_FakeClient(value) for value in backends]
    processes = [_FakeProcess(0), _FakeProcess(1)]
    gateways = []
    commands = []

    def gateway_factory(**kwargs):
        gateway = _FakeGateway(kwargs["activation_verifier"])
        gateways.append(gateway)
        return gateway

    def process_factory(command, **kwargs):
        commands.append((list(command), kwargs))
        return processes.pop(0)

    def client_factory(_descriptor, _provider):
        return clients.pop(0)

    supervisor = RuntimeSupervisor(
        config,
        gateway_factory=gateway_factory,
        process_factory=process_factory,
        client_factory=client_factory,
        key_provider=SimpleNamespace(),
        readiness_probe=lambda url: url in {item.url for item in backends},
        sleep=lambda _seconds: None,
    )
    result = supervisor.run(max_cycles=2)

    gateway = gateways[0]
    assert result == 1
    assert gateway.started is True and gateway.closed is True
    assert gateway.activated == backends
    assert gateway.gate.drained == [(7, 3.0), (8, 3.0)]
    assert len(commands) == 2
    assert all("--public-server-url" in command for command, _kwargs in commands)
    assert all(kwargs.get("cwd") == str(config.working_directory) for _c, kwargs in commands)

    supervisor._candidate_client = _FakeClient(backends[-1])
    with pytest.raises(GatewayError, match="proof does not match"):
        supervisor._verify_gateway_activation(
            BackendGeneration(backends[-1].url, 9, "forged-owner")
        )


def _assert_worker_command_is_bounded_and_secret_free(tmp_path: Path) -> None:
    config = _configuration(tmp_path)
    command = build_runtime_worker_command(config, executable="pythonw.exe")
    joined = " ".join(command)
    assert command[:4] == [
        "pythonw.exe", "-m", "nodelang.application_server", "--host",
    ]
    assert "--port 0" in joined
    assert "--machine-transport" in command
    assert "--public-server-url http://127.0.0.1:8495" in joined
    assert "--state-path" in command and "--universal-state-path" in command
    assert "--machine-descriptor-path" in command
    assert "--supervisor-control-stdio" in command
    assert all(word not in joined.casefold() for word in (
        "token=", "secret=", "password=", "private-key", "bearer ",
    ))


def _assert_pre_drain_pipe_is_exact_and_fail_closed(tmp_path: Path) -> None:
    backend = BackendGeneration(
        "http://127.0.0.1:63001", 13, "owner-13"
    )
    acknowledgement = (
        "ARCHHUB_RUNTIME_DRAIN_ACK_V1 "
        + json.dumps({
            "generation": backend.generation,
            "nonce": "court-nonce",
            "ownership_root": backend.ownership_root,
            "status": "drained",
            "url": backend.url,
        }, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    child_output = StringIO()
    RuntimeDrainPipe(
        reader=StringIO(acknowledgement),
        writer=child_output,
        timeout=1.0,
        nonce_factory=lambda: "court-nonce",
    ).begin_drain(backend)

    config = _configuration(tmp_path)
    gateways = []

    def gateway_factory(**kwargs):
        gateway = _FakeGateway(kwargs["activation_verifier"])
        gateway.gate.backend = backend
        gateways.append(gateway)
        return gateway

    supervisor = RuntimeSupervisor(
        config,
        gateway_factory=gateway_factory,
        key_provider=SimpleNamespace(),
    )
    parent_input = StringIO()
    process = SimpleNamespace(stdin=parent_input)
    supervisor._accept_worker_drain_request(
        process, child_output.getvalue()
    )

    assert gateways[0].gate.drained == [(13, 3.0)]
    assert parent_input.getvalue() == acknowledgement

    foreign = child_output.getvalue().replace('"generation":13', '"generation":14')
    with pytest.raises(RuntimeSupervisorError, match="active generation"):
        supervisor._accept_worker_drain_request(process, foreign)
    assert gateways[0].gate.drained == [(13, 3.0)]


def _assert_real_child_pipe_drains_before_exit(tmp_path: Path) -> None:
    backend = BackendGeneration(
        "http://127.0.0.1:63002", 14, "owner-14"
    )
    gateways = []

    def gateway_factory(**kwargs):
        gateway = _FakeGateway(kwargs["activation_verifier"])
        gateway.gate.backend = backend
        gateways.append(gateway)
        return gateway

    supervisor = RuntimeSupervisor(
        _configuration(tmp_path),
        gateway_factory=gateway_factory,
        key_provider=SimpleNamespace(),
    )
    source_root = Path(__file__).resolve().parents[1]
    child = f"""
import sys
sys.path.insert(0, {str(source_root)!r})
from nodelang.runtime_gateway import BackendGeneration
from nodelang.runtime_supervisor import RuntimeDrainPipe
RuntimeDrainPipe(reader=sys.stdin, writer=sys.stdout, timeout=5.0).begin_drain(
    BackendGeneration('http://127.0.0.1:63002', 14, 'owner-14')
)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child],
        cwd=source_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        bufsize=1,
    )
    supervisor._start_worker_control(process)
    try:
        assert process.wait(timeout=10.0) == 0, process.stderr.read()
    finally:
        supervisor._close_worker_control(process)
    assert gateways[0].gate.drained == [(14, 3.0)]
    assert supervisor._worker_control_error is None


def _assert_crash_loop_is_bounded(tmp_path: Path) -> None:
    config = replace(_configuration(tmp_path), max_crashes=2)
    backends = [
        BackendGeneration("http://127.0.0.1:62001", 11, "owner-11"),
        BackendGeneration("http://127.0.0.1:62002", 12, "owner-12"),
    ]
    clients = [_FakeClient(value) for value in backends]
    processes = [_FakeProcess(1), _FakeProcess(1)]
    gateways = []
    clock = {"value": 0.0}

    def monotonic():
        clock["value"] += 0.01
        return clock["value"]

    def gateway_factory(**kwargs):
        gateway = _FakeGateway(kwargs["activation_verifier"])
        gateways.append(gateway)
        return gateway

    supervisor = RuntimeSupervisor(
        config,
        gateway_factory=gateway_factory,
        process_factory=lambda _command, **_kwargs: processes.pop(0),
        client_factory=lambda _descriptor, _provider: clients.pop(0),
        key_provider=SimpleNamespace(),
        readiness_probe=lambda _url: True,
        sleep=lambda _seconds: None,
        monotonic=monotonic,
    )

    with pytest.raises(RuntimeSupervisorError, match="crash-loop court closed"):
        supervisor.run()
    assert gateways[0].activated == backends
    assert gateways[0].closed is True



def _assert_windows_task_contract_is_source_owned() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "packaging" / "windows" / "install_runtime_task.ps1"
    ).read_text(encoding="utf-8")
    required = (
        "SupportsShouldProcess",
        "New-ScheduledTaskAction",
        '"-m"',
        '"nodelang.runtime_supervisor"',
        "New-ScheduledTaskTrigger -AtLogOn",
        "New-ScheduledTaskPrincipal",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "New-ScheduledTaskSettingsSet",
        "-MultipleInstances IgnoreNew",
        "-RestartCount",
        "-RestartInterval",
        "-ExecutionTimeLimit ([TimeSpan]::Zero)",
        "-StartWhenAvailable",
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
        "Register-ScheduledTask",
        "$AuditOnly",
        "Get-ScheduledTask",
        "compliant =",
    )
    assert all(value in script for value in required)
    assert "Start-ScheduledTask" not in script
    assert "RunLevel Highest" not in script


def test_persistent_runtime_gateway_supervisor_contract(tmp_path):
    """One exact selector covers the source-only deployment ownership slice."""
    _assert_worker_command_is_bounded_and_secret_free(tmp_path)
    _assert_pre_drain_pipe_is_exact_and_fail_closed(tmp_path)
    _assert_real_child_pipe_drains_before_exit(tmp_path)
    _assert_public_origin_is_separate_from_worker_origin(tmp_path)
    _assert_supervisor_admits_only_exact_signed_generations(tmp_path)
    _assert_crash_loop_is_bounded(tmp_path)
    _assert_windows_task_contract_is_source_owned()
