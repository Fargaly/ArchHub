"""Launch and verify the current NOGRAPH desktop in the run's isolated profile and Job."""
from __future__ import annotations

import hashlib
import importlib.util
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if REPO.name == "03.TOOLS":
    REPO = REPO.parent
LIVE_PORTS = frozenset((8474, 8475))


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def pinned_source(path: Path) -> dict:
    data = Path(path).read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def plan_graph_owner(run_dir: Path, app_env: dict, *, repo: Path = REPO, ports=None) -> dict:
    """Everything the owner needs, decided up front and checkable without starting it."""
    coordination, canvas = ports or (_free_port(), _free_port())
    if coordination in LIVE_PORTS or canvas in LIVE_PORTS or coordination == canvas:
        raise ValueError("the run's graph owner needs its own two ports, never the live owner's")
    endpoint = "http://127.0.0.1:%d/coordination" % coordination
    env = dict(app_env, ARCHHUB_COORDINATION_ENDPOINT=endpoint,
        ARCHHUB_TEST_STATE_DIR=str(app_env.get('ARCHHUB_TEST_STATE_DIR') or Path(run_dir) / 'state'),
        ARCHHUB_TEST_HTTP_PORT=str(canvas))
    runtime_root = Path(env['ARCHHUB_TEST_STATE_DIR'])
    return {
        "run_dir": str(run_dir), "env": env, "endpoint": endpoint,
        "coordination_port": coordination, "canvas_port": canvas, "runtime_root": str(runtime_root),
        "sources": {"specification": pinned_source(repo / ("04.DOCS/SPEC.md" if (repo / "04.DOCS").is_dir() else "docs/SPEC.md"))},
        "service_args": ["-B", str((repo / "01.APP" if (repo / "01.APP").is_dir() else repo) / "nodelang/launcher.py")],
    }


# Run in a child process under the PLANNED environment: every root the owner and the desktop derive.


def owner_isolation_problems(plan: dict, python: str, code_root: Path, *, runner=subprocess.run) -> list:
    run_dir = Path(plan['run_dir']).resolve()
    env = plan['env']
    return [name + ' resolves outside the run' for name in
            ('ARCHHUB_TEST_STATE_DIR', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA')
            if not env.get(name) or not Path(env[name]).resolve().is_relative_to(run_dir)]


def start_graph_owner(desktop, plan: dict, python: str, code_root: Path):
    """Start the owner on the run's hidden desktop, inside the run's Job (desktop.spawn adopts it).
    Only launch_graph_owner calls this, after its gates."""
    spec = importlib.util.spec_from_file_location("owner_profile_guard", HERE / "profile_guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    command = subprocess.list2cmdline(guard.command([python, "-B", str(Path(code_root) / "nodelang/launcher.py")]))
    return desktop.spawn(command, env=plan["env"], cwd=str(code_root))


class OwnerRefused(RuntimeError):
    """The run's graph owner was not started (or not accepted): every reason is in .problems."""

    def __init__(self, problems: list):
        super().__init__("graph owner launch refused: " + "; ".join(problems))
        self.problems = list(problems)


# Run in a child process under the PLANNED environment: open what CURRENT selects, the way the owner will.






def _port_free(port: int) -> bool:
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def endpoint_problems(plan: dict, *, port_free=_port_free) -> list:
    """The endpoint the desktop gets, the port the owner binds and the free port all name the run's own."""
    port, canvas = plan["coordination_port"], plan["canvas_port"]
    pinned = "http://127.0.0.1:%d/coordination" % port
    args = list(plan["service_args"])

    problems = []
    if port in LIVE_PORTS or canvas in LIVE_PORTS or port == canvas:
        problems.append("the owner's ports are not the run's own two: %r" % ((port, canvas),))
    if plan["endpoint"] != pinned:
        problems.append("the planned endpoint %r is not pinned to the run's port" % plan["endpoint"])
    if plan["env"].get("ARCHHUB_COORDINATION_ENDPOINT") != pinned:
        problems.append("the spawn environment points elsewhere: %r" % plan["env"].get("ARCHHUB_COORDINATION_ENDPOINT"))
    if len(args) != 2 or args[0] != '-B' or Path(args[1]).name != 'launcher.py':
        problems.append('the rig must execute the installed desktop entry')
    if plan['env'].get('ARCHHUB_TEST_HTTP_PORT') != str(canvas):
        problems.append('the canvas port is not the pinned ports declaration')
    if Path(plan['env'].get('ARCHHUB_TEST_STATE_DIR', '')).resolve() != Path(plan['runtime_root']).resolve():
        problems.append("the desktop state is not the run's runtime root")
    for taken in (p for p in (port, canvas) if not port_free(p)):
        problems.append("port %d is already taken: something else would answer the run's endpoint" % taken)
    return problems




def launch_nograph_owner(desktop, plan, python, code_root, *, runner, health_seconds):
    """Admit only the NoGraph listener started by this isolated desktop process."""
    import psutil
    if not getattr(runner, "job_owned", False):
        raise OwnerRefused(["lifecycle: the helper runner is not owned by the run's Job"])
    problems = owner_isolation_problems(plan, python, code_root, runner=runner) + endpoint_problems(plan)
    if problems or runner.leftovers():
        raise OwnerRefused(problems or ["lifecycle: helpers are still running"])
    pid = int(start_graph_owner(desktop, plan, python, code_root).pid)
    port = plan["canvas_port"]
    marker = Path(plan["env"]["ARCHHUB_TEST_STATE_DIR"]) / "nograph-http-port"
    endpoint = "http://127.0.0.1:%d/api/alive" % port
    started = time.monotonic()
    while time.monotonic() - started < health_seconds:
        try:
            if int(marker.read_text(encoding="ascii")) == port:
                root = psutil.Process(pid)
                job_pids = set(runner.leftovers())
                for process in (root, *root.children(recursive=True)):
                    if process.pid not in job_pids or not any(
                        conn.status == psutil.CONN_LISTEN and conn.laddr == ("127.0.0.1", port)
                        for conn in process.net_connections(kind="tcp")
                    ):
                        continue
                    with urllib.request.urlopen(endpoint, timeout=3) as answer:
                        if answer.status == 204:
                            return {"pid": pid, "listener_pid": process.pid, "endpoint": endpoint,
                                    "state_marker": str(marker), "health_seconds": round(time.monotonic() - started)}
        except (OSError, ValueError, psutil.Error):
            pass
        time.sleep(1)
    raise OwnerRefused(["health: the isolated desktop did not own a ready NoGraph listener"])
