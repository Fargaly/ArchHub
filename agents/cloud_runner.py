"""Cloud daemon entry point — runs the agent loop 24/7 on Fly.io.

Differences vs `agents/run.py`:

  * LLM backend is Anthropic by default (toggle via env
    `ARCHHUB_AGENTS_BACKEND=anthropic|ollama`).
  * Outputs / logs / heartbeat all land under `/data/agents/` so they
    survive container restarts via the Fly persistent volume.
  * Heartbeat file gets touched every cycle so the cloud_backend (or
    the bundled /healthz endpoint) can report "last seen N min ago".
  * Cycle = 60s by default — Anthropic responses are fast enough that
    the local 5-minute interval is overkill in the cloud.
  * Graceful SIGTERM shutdown so Fly's deploy / scale-to-zero doesn't
    leave half-written outputs.
  * The dashboard FastAPI sub-app runs in the same process on a
    daemon thread, so port 8080 stays answerable while the loop ticks.

Filesystem dependency: the daemon expects `recurring.yaml` at
`/app/agents/recurring.yaml` (copied in by the Dockerfile). It does
NOT need the rest of the host repo — task outputs and the queue
live entirely under `/data/agents/`.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Pre-import setup: rebase the queue's storage roots onto /data so the
# Fly persistent volume takes ownership. We do this BEFORE importing the
# rest of the agents package so the module-level path constants pick up
# the override. Fall back to the local layout when /data isn't mounted
# (e.g. when running cloud_runner on a dev box).
DATA_ROOT = Path(os.environ.get("ARCHHUB_AGENTS_DATA_ROOT", "/data/agents"))
try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    _USE_DATA = True
except (PermissionError, OSError):
    DATA_ROOT = Path(__file__).resolve().parent
    _USE_DATA = False

# Heartbeat lives at a stable path the dashboard endpoint can read.
HEARTBEAT_PATH = DATA_ROOT / "heartbeat.txt"

# Now wire the queue + log roots if we're on the volume.
if _USE_DATA:
    from . import queue as _queue_mod
    _queue_mod.TASKS_DIR = DATA_ROOT / "tasks"
    _queue_mod.OUTPUTS_DIR = DATA_ROOT / "outputs"
    _queue_mod.LOGS_DIR = DATA_ROOT / "logs"
    for d in (_queue_mod.TASKS_DIR, _queue_mod.OUTPUTS_DIR, _queue_mod.LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _select_backend() -> str:
    """Choose anthropic vs ollama. Cloud default is anthropic; local
    `python -m agents.run` keeps using ollama untouched."""
    return os.environ.get("ARCHHUB_AGENTS_BACKEND", "anthropic").lower().strip()


def _install_backend(backend: str) -> None:
    """Monkey-patch the symbols agents.base imports from agents.ollama
    so the rest of the package keeps working unchanged.

    This is the only place that knows there's more than one LLM
    backend. Departments themselves stay LLM-agnostic.
    """
    if backend == "ollama":
        return  # default — nothing to do

    if backend != "anthropic":
        raise ValueError(f"Unknown ARCHHUB_AGENTS_BACKEND: {backend!r}")

    from . import anthropic_client, base, ollama
    # Replace the three symbols base.py uses from .ollama
    base.complete = anthropic_client.complete  # type: ignore[attr-defined]
    base.is_running = anthropic_client.is_running  # type: ignore[attr-defined]
    base.OllamaCompletion = anthropic_client.AnthropicCompletion  # type: ignore[attr-defined]
    # Also overlay the module attributes so anything else that imports
    # from agents.ollama at runtime gets the cloud client.
    ollama.complete = anthropic_client.complete  # type: ignore[assignment]
    ollama.is_running = anthropic_client.is_running  # type: ignore[assignment]


# ---------------------------------------------------------------------------
class CloudDaemon:
    """The full 24/7 loop. Iteration = (heartbeat → scheduler tick → sleep)."""

    def __init__(
        self,
        cycle_seconds: int = 60,
        heartbeat_path: Path = HEARTBEAT_PATH,
    ):
        self.cycle_seconds = cycle_seconds
        self.heartbeat_path = heartbeat_path
        self._stop = threading.Event()
        self._cycles = 0
        self._scheduler = None  # lazy — let backend install run first

    # ---- lifecycle --------------------------------------------------------

    def install_signal_handlers(self) -> None:
        def _stop(_signum, _frame):
            self._stop.set()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):
                # SIGTERM is unavailable on some Windows shells; OK.
                pass

    def write_heartbeat(self) -> None:
        """Two-line file: ISO timestamp, then cycles-since-boot count."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(
                f"{ts}\n{self._cycles}\n", encoding="utf-8",
            )
        except Exception as ex:
            print(f"[cloud_runner] heartbeat write failed: {ex}", flush=True)

    def tick_once(self) -> dict:
        """One cycle without sleeping. Returns the scheduler summary."""
        from .scheduler import Scheduler
        if self._scheduler is None:
            self._scheduler = Scheduler()
        summary = self._scheduler.tick()
        self._cycles += 1
        self.write_heartbeat()
        return summary

    def run_forever(self) -> int:
        """Block forever. Returns process exit code."""
        self.install_signal_handlers()
        print(f"[cloud_runner] starting; cycle={self.cycle_seconds}s "
              f"backend={_select_backend()} data={DATA_ROOT}", flush=True)

        # First heartbeat *before* the first tick so /healthz can answer
        # immediately while the initial scheduler call runs.
        self.write_heartbeat()

        while not self._stop.is_set():
            try:
                summary = self.tick_once()
                print(f"[cloud_runner] tick {self._cycles}: {summary}", flush=True)
            except Exception as ex:
                print(f"[cloud_runner] error: {type(ex).__name__}: {ex}",
                      flush=True)
            self._stop.wait(timeout=self.cycle_seconds)

        print("[cloud_runner] SIGTERM/SIGINT received — exiting cleanly",
              flush=True)
        return 0


# ---------------------------------------------------------------------------
def _start_dashboard_thread(heartbeat_path: Path) -> Optional[threading.Thread]:
    """Spin up the FastAPI dashboard on a daemon thread.

    We import lazily so a `python -m agents.cloud_runner --once` run
    doesn't need uvicorn pulled in just to drain one cycle.
    """
    try:
        import uvicorn
        from .dashboard_endpoint import build_app
    except ImportError as ex:
        print(f"[cloud_runner] dashboard disabled (import error): {ex}",
              flush=True)
        return None

    app = build_app(
        heartbeat_path=heartbeat_path,
        data_root=DATA_ROOT,
    )
    port = int(os.environ.get("PORT", "8080"))
    config = uvicorn.Config(
        app, host="0.0.0.0", port=port,
        log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)

    def _serve():
        try:
            server.run()
        except Exception as ex:
            print(f"[cloud_runner] dashboard crashed: {ex}", flush=True)

    th = threading.Thread(target=_serve, name="agents-dashboard", daemon=True)
    th.start()
    print(f"[cloud_runner] dashboard listening on :{port}", flush=True)
    return th


# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    backend = _select_backend()
    _install_backend(backend)

    daemon = CloudDaemon(
        cycle_seconds=int(os.environ.get("ARCHHUB_AGENTS_CYCLE", "60")),
    )

    # --once = run a single scheduler tick then exit. Used by tests + CI.
    if "--once" in argv:
        daemon.write_heartbeat()
        summary = daemon.tick_once()
        import json
        print(json.dumps(summary, indent=2))
        return 0

    # In daemon mode, spin up /healthz alongside the loop.
    if "--no-dashboard" not in argv:
        _start_dashboard_thread(HEARTBEAT_PATH)

    return daemon.run_forever()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
