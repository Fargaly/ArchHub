#!/usr/bin/env python3
"""Real smoke test for the ``archhub-agents`` Fly container — CLD-12.

The reality probe (``scripts/reality_smoke.py``) checks the agents daemon by
hitting the *deployed* ``archhub-agents.fly.dev`` ``/healthz`` + ``/status``.
That only works once something is already deployed and alive — there was no way
to prove the container's health surface actually boots and answers *before*
(or independent of) a Fly deploy. So a broken build, a renamed endpoint, or a
heartbeat regression would only surface hours later when the hourly reality
cron went red against production.

This script closes that gap. It boots the **real** agents dashboard app
(``agents.dashboard_endpoint.build_app`` — the exact FastAPI app the Dockerfile
serves on port 8080), writes a **real** heartbeat via the production heartbeat
writer (``agents.cloud_runner.CloudDaemon.write_heartbeat``), seeds a **real**
completed-today task marker, then runs the **actual** agents checks from
``reality_smoke`` against the live local server:

  * ``agents.healthz``  — GET /healthz → 200 + heartbeat within 5 min
  * ``agents.status``   — GET /status → dept list + completed_today > 0

Exit 0 iff both checks are green; 1 otherwise. ``--json`` emits a machine
report (same ``CheckResult`` shape the reality probe uses). This is what CI runs
to prove the container is deployable, and what the deploy workflow can run
against the live URL post-deploy with ``--url``.

No Fly, no flyctl, no network egress: a self-contained boot of the real app.

Usage:
    python scripts/agents_smoke.py
    python scripts/agents_smoke.py --json
    python scripts/agents_smoke.py --url https://archhub-agents.fly.dev   # probe a live deploy
    python scripts/agents_smoke.py --port 8099 --timeout 20
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# Make the repo-root `agents` package (the Fly daemon package) importable, and
# ensure REPO_ROOT wins over any `app/` entry already on sys.path. The desktop
# app ships a SEPARATE `app/agents/` package (composer/node-smith agents); when
# `app/` is ahead of REPO_ROOT (e.g. the test suite's conftest puts it there)
# a bare `import agents` resolves to that one, which has no `cloud_runner`. We
# want the daemon package unambiguously, so REPO_ROOT goes to the front.
_repo = str(REPO_ROOT)
if _repo in sys.path:
    sys.path.remove(_repo)
sys.path.insert(0, _repo)


def _load_reality_smoke():
    """Load scripts/reality_smoke.py as an importable module.

    Registered in sys.modules BEFORE exec so its @dataclass decorators can
    resolve their owning module (Python 3.14 requirement) — same loader the
    reality-smoke test suite uses.
    """
    path = REPO_ROOT / "scripts" / "reality_smoke.py"
    spec = importlib.util.spec_from_file_location("reality_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reality_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _free_port() -> int:
    """Grab an ephemeral TCP port the OS just told us is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_real_state(data_root: Path, heartbeat_path: Path) -> None:
    """Write a real heartbeat + a real completed-today task marker.

    Uses the PRODUCTION heartbeat writer (CloudDaemon.write_heartbeat) so the
    file format the dashboard parses is exactly what the daemon emits — not a
    hand-rolled stand-in. The ``.done`` marker is the same artefact the live
    daemon drops when a department task finishes, so ``/status`` reports a
    non-zero ``completed_today`` the way it would in production after one tick.
    """
    from agents.cloud_runner import CloudDaemon

    daemon = CloudDaemon(heartbeat_path=heartbeat_path)
    daemon.write_heartbeat()

    # A real completed-today marker: tasks/<dept>/<id>.done, mtime = now.
    tasks_dir = data_root / "tasks" / "eng"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    done = tasks_dir / "smoke-boot.done"
    done.write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8",
    )


def _wait_until_serving(url: str, timeout: float) -> bool:
    """Poll GET {url}/healthz until it answers 200 or we run out of time."""
    smoke = sys.modules.get("reality_smoke") or _load_reality_smoke()
    deadline = time.monotonic() + timeout
    healthz = f"{url.rstrip('/')}/healthz"
    while time.monotonic() < deadline:
        try:
            r = smoke.http_request(healthz, timeout=2)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def _boot_local_app(port: int, data_root: Path, heartbeat_path: Path):
    """Start the REAL agents dashboard app on a uvicorn server thread.

    Returns (server, thread). The caller stops it via server.should_exit.
    """
    import uvicorn

    from agents.dashboard_endpoint import build_app

    app = build_app(heartbeat_path=heartbeat_path, data_root=data_root)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, name="agents-smoke-dashboard", daemon=True,
    )
    thread.start()
    return server, thread


def run_smoke(
    *,
    url: Optional[str] = None,
    port: Optional[int] = None,
    timeout: float = 15.0,
) -> list:
    """Run the agents health/status checks and return a list of CheckResults.

    When ``url`` is given, probes that live deploy directly (used post-deploy).
    Otherwise boots the real local app and probes ``127.0.0.1:<port>``.
    """
    smoke = _load_reality_smoke()
    args = argparse.Namespace(
        cloud_url=smoke.DEFAULT_CLOUD_URL,
        agents_url=smoke.DEFAULT_AGENTS_URL,
        stripe_check=False, llm_check=False, json=False, quiet=False, retry=1,
    )

    if url:
        args.agents_url = url
        if not _wait_until_serving(url, timeout):
            return [smoke.CheckResult(
                "agents.boot", "Agents 24/7", smoke.STATUS_FAIL,
                f"{url} did not answer /healthz within {timeout:.0f}s")]
        return [
            smoke.check_agents_healthz(args),
            smoke.check_agents_status(args),
        ]

    # Local boot path — exercises the real container app + heartbeat writer.
    port = port or _free_port()
    with tempfile.TemporaryDirectory(prefix="agents-smoke-") as tmp:
        data_root = Path(tmp) / "agents"
        data_root.mkdir(parents=True, exist_ok=True)
        heartbeat_path = data_root / "heartbeat.txt"
        _seed_real_state(data_root, heartbeat_path)

        server, thread = _boot_local_app(port, data_root, heartbeat_path)
        local_url = f"http://127.0.0.1:{port}"
        try:
            if not _wait_until_serving(local_url, timeout):
                return [smoke.CheckResult(
                    "agents.boot", "Agents 24/7", smoke.STATUS_FAIL,
                    f"local app did not serve /healthz within {timeout:.0f}s")]
            args.agents_url = local_url
            boot_ok = smoke.CheckResult(
                "agents.boot", "Agents 24/7", smoke.STATUS_OK,
                f"real app booted on :{port}")
            return [
                boot_ok,
                smoke.check_agents_healthz(args),
                smoke.check_agents_status(args),
            ]
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="agents_smoke",
        description="Boot the real archhub-agents app and smoke its health "
                    "surface (or probe a live deploy with --url).",
    )
    p.add_argument("--url", default="",
                   help="Probe this live agents URL instead of booting locally "
                        "(e.g. https://archhub-agents.fly.dev)")
    p.add_argument("--port", type=int, default=0,
                   help="Local port to bind (default: an ephemeral free port)")
    p.add_argument("--timeout", type=float, default=15.0,
                   help="Seconds to wait for the app to start serving")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of human text")
    args = p.parse_args(argv)

    results = run_smoke(
        url=args.url or None,
        port=args.port or None,
        timeout=args.timeout,
    )

    failed = sum(1 for r in results if r.status == "fail")
    exit_code = 0 if failed == 0 else 1

    if args.json:
        payload = {
            "schema": "archhub.agents_smoke/1",
            "generated_at": datetime.now(timezone.utc)
                                    .isoformat(timespec="seconds"),
            "mode": "live" if args.url else "local-boot",
            "target": args.url or f"127.0.0.1:{args.port or 'ephemeral'}",
            "summary": {
                "green": sum(1 for r in results if r.status == "ok"),
                "failed": failed,
                "exit_code": exit_code,
            },
            "checks": [r.to_dict() for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("archhub-agents smoke "
              f"({'live ' + args.url if args.url else 'local boot'})")
        for r in results:
            tag = {"ok": "[OK]  ", "fail": "[FAIL]", "skip": "[SKIP]"}[r.status]
            detail = f" — {r.detail}" if r.detail else ""
            print(f"  {tag}  {r.name:<20}{detail}")
        print(f"{'GREEN' if exit_code == 0 else 'RED'}: "
              f"{sum(1 for r in results if r.status == 'ok')} ok, "
              f"{failed} failed")

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
