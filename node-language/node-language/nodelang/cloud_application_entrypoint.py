"""Production process boundary for one remote Universal Cell authority."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading
from typing import Mapping, TextIO

from .cloud_runtime_bootstrap import (
    create_cloud_application_server,
    load_cloud_runtime_configuration,
)
from .map_import import PUBLIC_MAP_PATH


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_POLL_SECONDS = 0.25


def _emit(output: TextIO, state: str) -> None:
    output.write(f"ARCHHUB_CLOUD_RUNTIME {state}\n")
    output.flush()


def run_cloud_application(
    environment: Mapping[str, str],
    *,
    server_factory=create_cloud_application_server,
    stop_event: threading.Event | None = None,
    signal_module=signal,
    install_signal_handlers: bool = True,
    output: TextIO | None = None,
) -> int:
    """Run one fenced authority until a process signal requests a clean drain."""
    if output is None:
        output = sys.stderr
    if stop_event is None:
        stop_event = threading.Event()
    previous_handlers: list[tuple[int, object]] = []
    server = None
    failed = False

    def request_shutdown(_signal_number, _frame) -> None:
        stop_event.set()

    try:
        if install_signal_handlers:
            for signal_number in (
                signal_module.SIGTERM,
                signal_module.SIGINT,
            ):
                previous = signal_module.getsignal(signal_number)
                signal_module.signal(signal_number, request_shutdown)
                previous_handlers.append((signal_number, previous))

        configuration = load_cloud_runtime_configuration(environment)
        server = server_factory(
            configuration,
            map_path=PUBLIC_MAP_PATH,
            court_workspace_root=_PROJECT_ROOT,
        )
        server.start()
        _emit(output, "started")
        while not stop_event.wait(_POLL_SECONDS):
            server_thread = getattr(server, "thread", None)
            if server_thread is None or not server_thread.is_alive():
                raise RuntimeError("cloud runtime server stopped unexpectedly")
    except BaseException:
        failed = True
        _emit(output, "failed")
    finally:
        if server is not None:
            try:
                server.close()
            except BaseException:
                if not failed:
                    _emit(output, "failed")
                failed = True
        for signal_number, previous in previous_handlers:
            signal_module.signal(signal_number, previous)

    if failed:
        return 1
    _emit(output, "stopped")
    return 0


def main() -> int:
    return run_cloud_application(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_cloud_application"]
