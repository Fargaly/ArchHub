"""Persistent loopback gateway owner for replaceable Universal Cell workers."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from queue import Empty, Queue
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, TextIO
from urllib.parse import urlsplit
import uuid

from .application_machine_transport import (
    MachineTransportError,
    UniversalRuntimeClient,
    default_runtime_descriptor_path,
)
from .cell_secret_keys import WindowsDpapiSigningKeyProvider
from .runtime_gateway import BackendGeneration, GatewayError, RuntimeGateway


class RuntimeSupervisorError(RuntimeError):
    pass


_DRAIN_REQUEST_PREFIX = "ARCHHUB_RUNTIME_DRAIN_V1 "
_DRAIN_ACK_PREFIX = "ARCHHUB_RUNTIME_DRAIN_ACK_V1 "
_DRAIN_RECORD_LIMIT = 4096


def _control_record(prefix: str, payload: dict[str, object]) -> str:
    return prefix + json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ) + "\n"


def _parse_control_record(line: str, prefix: str) -> dict[str, object]:
    if type(line) is not str or len(line.encode("utf-8")) > _DRAIN_RECORD_LIMIT:
        raise RuntimeSupervisorError("runtime drain control record is invalid")
    if not line.endswith("\n") or not line.startswith(prefix):
        raise RuntimeSupervisorError("runtime drain control record is invalid")
    try:
        payload = json.loads(line[len(prefix):])
    except (TypeError, ValueError) as exc:
        raise RuntimeSupervisorError(
            "runtime drain control record is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeSupervisorError("runtime drain control record is invalid")
    return payload


def _drain_identity(
    backend: BackendGeneration, nonce: str
) -> dict[str, object]:
    if type(nonce) is not str or not nonce or len(nonce) > 128:
        raise RuntimeSupervisorError("runtime drain nonce is invalid")
    return {
        "generation": backend.generation,
        "nonce": nonce,
        "ownership_root": backend.ownership_root,
        "url": backend.url,
    }


class RuntimeDrainPipe:
    """Child end of one bounded parent-owned gateway drain handshake."""

    def __init__(
        self,
        *,
        reader: TextIO,
        writer: TextIO,
        timeout: float = 30.0,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        if not 0.1 <= float(timeout) <= 300.0:
            raise ValueError("runtime drain pipe timeout is outside its bound")
        self.reader = reader
        self.writer = writer
        self.timeout = float(timeout)
        self.nonce_factory = nonce_factory or (lambda: uuid.uuid4().hex)

    def begin_drain(self, backend: BackendGeneration) -> None:
        nonce = self.nonce_factory()
        identity = _drain_identity(backend, nonce)
        responses: Queue[object] = Queue(maxsize=1)

        def read_response() -> None:
            try:
                responses.put(self.reader.readline(_DRAIN_RECORD_LIMIT + 1))
            except Exception as exc:
                responses.put(exc)

        reader_thread = threading.Thread(
            target=read_response,
            name="archhub-runtime-drain-ack",
            daemon=True,
        )
        reader_thread.start()
        self.writer.write(_control_record(_DRAIN_REQUEST_PREFIX, identity))
        self.writer.flush()
        try:
            response = responses.get(timeout=self.timeout)
        except Empty as exc:
            raise RuntimeSupervisorError(
                "runtime supervisor drain acknowledgement timed out"
            ) from exc
        if isinstance(response, Exception):
            raise RuntimeSupervisorError(
                "runtime supervisor drain acknowledgement failed"
            ) from response
        acknowledgement = _parse_control_record(response, _DRAIN_ACK_PREFIX)
        expected = dict(identity)
        expected["status"] = "drained"
        if acknowledgement != expected:
            raise RuntimeSupervisorError(
                "runtime supervisor drain acknowledgement is not exact"
            )


@dataclass(frozen=True, slots=True)
class RuntimeSupervisorConfig:
    host: str
    port: int
    state_path: Path
    universal_state_path: Path
    descriptor_path: Path
    working_directory: Path
    startup_timeout: float = 180.0
    drain_timeout: float = 60.0
    restart_delay: float = 1.0
    max_crashes: int = 5
    crash_window_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1" or not 1 <= int(self.port) <= 65535:
            raise ValueError("runtime supervisor requires a numeric loopback origin")
        for name in (
            "state_path", "universal_state_path", "descriptor_path",
            "working_directory",
        ):
            value = Path(getattr(self, name)).expanduser().resolve()
            object.__setattr__(self, name, value)
        if not self.working_directory.is_dir():
            raise ValueError("runtime supervisor working directory is unavailable")
        if not 1.0 <= float(self.startup_timeout) <= 600.0:
            raise ValueError("runtime worker startup timeout is outside its bound")
        if not 0.1 <= float(self.drain_timeout) <= 300.0:
            raise ValueError("runtime worker drain timeout is outside its bound")
        if not 0.0 <= float(self.restart_delay) <= 60.0:
            raise ValueError("runtime worker restart delay is outside its bound")
        if not 1 <= int(self.max_crashes) <= 20:
            raise ValueError("runtime worker crash limit is outside its bound")
        if not 1.0 <= float(self.crash_window_seconds) <= 3600.0:
            raise ValueError("runtime worker crash window is outside its bound")

    @property
    def public_url(self) -> str:
        return "http://%s:%d" % (self.host, int(self.port))


def build_runtime_worker_command(
    config: RuntimeSupervisorConfig,
    *,
    executable: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Render the secret-free worker process boundary from one configuration."""
    return [
        os.fspath(executable or sys.executable),
        "-m", "nodelang.application_server",
        "--host", "127.0.0.1",
        "--port", "0",
        "--state-path", os.fspath(config.state_path),
        "--universal-state-path", os.fspath(config.universal_state_path),
        "--machine-transport",
        "--machine-descriptor-path", os.fspath(config.descriptor_path),
        "--public-server-url", config.public_url,
        "--supervisor-control-stdio",
    ]


def _backend_is_listening(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.25):
            return True
    except OSError:
        return False


class RuntimeSupervisor:
    """Keep one stable gateway while signed, graph-owned workers are replaced."""

    def __init__(
        self,
        config: RuntimeSupervisorConfig,
        *,
        gateway_factory: Callable[..., object] = RuntimeGateway,
        process_factory: Callable[..., object] = subprocess.Popen,
        client_factory: Callable[..., object] = UniversalRuntimeClient,
        key_provider=None,
        readiness_probe: Callable[[str], bool] = _backend_is_listening,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._process_factory = process_factory
        self._client_factory = client_factory
        self._key_provider = key_provider or WindowsDpapiSigningKeyProvider(
            WindowsDpapiSigningKeyProvider.default_path()
        )
        self._readiness_probe = readiness_probe
        self._sleep = sleep
        self._monotonic = monotonic
        self._candidate_client = None
        self._worker = None
        self._worker_control_thread = None
        self._worker_control_error = None
        self.gateway = gateway_factory(
            host=config.host,
            port=config.port,
            admission_timeout=15.0,
            backend_timeout=60.0,
            activation_verifier=self._verify_gateway_activation,
        )

    def _verify_gateway_activation(self, backend: BackendGeneration) -> None:
        client = self._candidate_client
        if client is None:
            raise GatewayError("runtime supervisor has no signed worker candidate")
        exact = client.runtime_backend_generation()
        if exact != backend:
            raise GatewayError("runtime worker proof does not match activation")
        if backend.url == self.gateway.url:
            raise GatewayError("runtime worker cannot point the gateway at itself")
        if not self._readiness_probe(backend.url):
            raise GatewayError("runtime worker listener is not ready")

    def _launch_worker(self):
        command = build_runtime_worker_command(self.config)
        kwargs = {
            "cwd": str(self.config.working_directory),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "strict",
            "bufsize": 1,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = self._process_factory(command, **kwargs)
        self._start_worker_control(process)
        return process

    def _accept_worker_drain_request(self, process, line: str) -> None:
        payload = _parse_control_record(line, _DRAIN_REQUEST_PREFIX)
        required = {"generation", "nonce", "ownership_root", "url"}
        if set(payload) != required:
            raise RuntimeSupervisorError(
                "runtime drain request shape is invalid"
            )
        if (
            type(payload["generation"]) is not int
            or payload["generation"] <= 0
            or type(payload["ownership_root"]) is not str
            or not payload["ownership_root"]
            or type(payload["url"]) is not str
        ):
            raise RuntimeSupervisorError(
                "runtime drain request identity is invalid"
            )
        nonce = payload["nonce"]
        requested = BackendGeneration(
            payload["url"], payload["generation"], payload["ownership_root"]
        )
        _drain_identity(requested, nonce)
        active = self.gateway.gate.backend
        if active != requested:
            raise RuntimeSupervisorError(
                "runtime drain request does not match the active generation"
            )
        self.gateway.gate.begin_drain(
            requested.generation,
            timeout=float(self.config.drain_timeout),
        )
        acknowledgement = dict(payload)
        acknowledgement["status"] = "drained"
        process.stdin.write(_control_record(_DRAIN_ACK_PREFIX, acknowledgement))
        process.stdin.flush()

    def _start_worker_control(self, process) -> None:
        if getattr(process, "stdout", None) is None or getattr(
            process, "stdin", None
        ) is None:
            self._worker_control_thread = None
            return

        def monitor() -> None:
            while True:
                line = process.stdout.readline(_DRAIN_RECORD_LIMIT + 1)
                if not line:
                    return
                if not line.startswith(_DRAIN_REQUEST_PREFIX):
                    continue
                try:
                    self._accept_worker_drain_request(process, line)
                except Exception as exc:
                    self._worker_control_error = exc
                    if process.poll() is None:
                        process.terminate()
                    return

        self._worker_control_thread = threading.Thread(
            target=monitor,
            name="archhub-runtime-worker-control",
            daemon=True,
        )
        self._worker_control_thread.start()

    def _close_worker_control(self, process) -> None:
        for stream_name in ("stdin", "stdout"):
            stream = getattr(process, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        thread = self._worker_control_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._worker_control_thread = None

    def _stop_owned_worker(self) -> None:
        process = self._worker
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
        finally:
            self._close_worker_control(process)
            self._worker = None

    def _await_candidate(
        self,
        process,
        previous_generation: int,
    ) -> BackendGeneration:
        deadline = self._monotonic() + float(self.config.startup_timeout)
        last_error = "runtime worker has not published a signed descriptor"
        while self._monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeSupervisorError(
                    "runtime worker exited before activation (%d)" % int(exit_code)
                )
            try:
                client = self._client_factory(
                    self.config.descriptor_path,
                    self._key_provider,
                )
                backend = client.runtime_backend_generation()
                if backend.generation <= int(previous_generation):
                    raise RuntimeSupervisorError(
                        "runtime worker generation did not advance"
                    )
                if backend.url == self.gateway.url:
                    raise RuntimeSupervisorError(
                        "runtime worker published the public gateway as its backend"
                    )
                if not self._readiness_probe(backend.url):
                    raise RuntimeSupervisorError(
                        "runtime worker listener is not ready"
                    )
                self._candidate_client = client
                return backend
            except (GatewayError, MachineTransportError, OSError,
                    RuntimeSupervisorError, ValueError) as exc:
                last_error = str(exc)
                self._sleep(0.1)
        raise RuntimeSupervisorError(
            "runtime worker activation timed out: " + last_error
        )

    def run(self, *, max_cycles: int | None = None) -> int:
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("runtime supervisor cycle bound must be positive")
        previous_generation = 0
        crash_times: list[float] = []
        cycles = 0
        self.gateway.start()
        try:
            while True:
                self._worker = self._launch_worker()
                backend = self._await_candidate(
                    self._worker,
                    previous_generation,
                )
                self.gateway.activate(backend)
                previous_generation = backend.generation
                exit_code = int(self._worker.wait())
                self._close_worker_control(self._worker)
                self.gateway.gate.begin_drain(
                    backend.generation,
                    timeout=float(self.config.drain_timeout),
                )
                control_error = self._worker_control_error
                self._worker_control_error = None
                self._candidate_client = None
                self._worker = None
                cycles += 1
                if control_error is not None:
                    raise RuntimeSupervisorError(
                        "runtime worker control pipe failed closed"
                    ) from control_error
                if max_cycles is not None and cycles >= max_cycles:
                    return exit_code
                if exit_code != 0:
                    now = self._monotonic()
                    crash_times = [
                        value for value in crash_times
                        if now - value <= float(self.config.crash_window_seconds)
                    ]
                    crash_times.append(now)
                    if len(crash_times) >= int(self.config.max_crashes):
                        raise RuntimeSupervisorError(
                            "runtime worker crash-loop court closed"
                        )
                self._sleep(float(self.config.restart_delay))
        finally:
            self._stop_owned_worker()
            self.gateway.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8495)
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--universal-state-path", required=True)
    parser.add_argument(
        "--machine-descriptor-path",
        default=str(default_runtime_descriptor_path()),
    )
    args = parser.parse_args(argv)
    config = RuntimeSupervisorConfig(
        host=args.host,
        port=args.port,
        state_path=Path(args.state_path),
        universal_state_path=Path(args.universal_state_path),
        descriptor_path=Path(args.machine_descriptor_path),
        working_directory=Path(__file__).resolve().parents[1],
    )
    try:
        return RuntimeSupervisor(config).run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RuntimeDrainPipe", "RuntimeSupervisor", "RuntimeSupervisorConfig",
    "RuntimeSupervisorError",
    "build_runtime_worker_command", "main",
]
