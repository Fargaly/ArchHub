"""The run's OWN graph owner (clean coordination service), started only when every gate passes.

The plan:

  1. Provision a fresh unified authority with the product's own provisioning
     (clean_runtime_bootstrap.provision_clean_runtime) under the run's environment, so its root
     (<run>\\LOCALAPPDATA\\ArchHub\\unified-authority), the authority DPAPI provider and the caller key
     store all resolve inside the run folder. Sources are pinned by sha256: SPEC.md from this
     repository and owner_grand_map.json shipped with this tool.
  2. Start `nodelang.clean_coordination_service --root <runtime root> --port <free> --canvas-port
     <free>` through the run's HiddenDesktop, so the run's Job owns it and ends it.
  3. Point the desktop at it: ARCHHUB_COORDINATION_ENDPOINT=http://127.0.0.1:<port>/coordination.

Never :8474/:8475, never the founder's DPAPI files, descriptor or agent-discovery roots: every path
the owner and the desktop derive is resolved under the planned environment and must lie in the run.

launch_graph_owner is the only way the run starts it. At the actual spawn it refuses unless all three
hold: the plan (every derived root in the run), the provisioning read-back (the generation CURRENT
selects in the run's root opens, signed, as the graph just provisioned) and the pinned endpoint (the
env, the service arguments and a still-free port all name the run's own port). Every helper child it
runs (the plan resolve, the provisioning, the read-back) goes through a Job-owned runner, and none may
still be alive in the run's Job when the owner is spawned.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LIVE_PORTS = frozenset((8474, 8475))
OWNER_MAP = HERE / "owner_grand_map.json"


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
    env = dict(app_env, ARCHHUB_COORDINATION_ENDPOINT=endpoint)
    runtime_root = Path(env["LOCALAPPDATA"]) / "ArchHub" / "unified-authority"
    return {
        "run_dir": str(run_dir), "env": env, "endpoint": endpoint,
        "coordination_port": coordination, "canvas_port": canvas, "runtime_root": str(runtime_root),
        "sources": {"specification": pinned_source(repo / "SPEC.md"), "grand_map": pinned_source(OWNER_MAP)},
        "service_args": ["-B", "-m", "nodelang.clean_coordination_service", "--root", str(runtime_root),
                         "--port", str(coordination), "--canvas-port", str(canvas)],
    }


# Run in a child process under the PLANNED environment: every root the owner and the desktop derive.
_RESOLVE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority_runtime import default_runtime_root
from nodelang.application_machine_transport import default_runtime_descriptor_path
from nodelang.session_link_config import app_state_dir
from nodelang.assistant_registration import install_roots
paths = {
    "authority_provider": WindowsDpapiSigningKeyProvider.default_path(),
    "caller_key_store": WindowsDpapiCallerKeyStore.default_path(),
    "runtime_root": default_runtime_root(),
    "runtime_descriptor": default_runtime_descriptor_path(),
    "session_link_state": app_state_dir(),
    "assistant_state": install_roots()[1],
    "home": Path.home(),
}
print(json.dumps({"paths": {k: str(v) for k, v in paths.items()},
                  "endpoint": os.environ.get("ARCHHUB_COORDINATION_ENDPOINT", "")}))
"""


def owner_isolation_problems(plan: dict, python: str, code_root: Path, *, runner=subprocess.run) -> list:
    """Resolve the owner's and desktop's roots under the plan's environment; each must lie in the run
    folder, and the coordination endpoint must be the run's own. Any doubt is a problem."""
    run_dir = Path(plan["run_dir"]).resolve()
    done = runner([python, "-B", "-c", _RESOLVE, str(code_root)], env=plan["env"],
                  capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        return ["the owner's paths could not be resolved: " + (done.stderr or done.stdout)[-400:]]
    resolved = json.loads(done.stdout.strip().splitlines()[-1])
    problems = ["%s resolves outside the run: %s" % (name, path) for name, path in resolved["paths"].items()
                if not Path(path).resolve().is_relative_to(run_dir)]
    if resolved["endpoint"] != plan["endpoint"]:
        problems.append("the coordination endpoint is not the run's own: %r" % resolved["endpoint"])
    if any(":%d/" % port in resolved["endpoint"] for port in LIVE_PORTS):
        problems.append("the coordination endpoint is the live owner's")
    return problems


def provision_command(plan: dict, python: str, code_root: Path) -> list:
    return [python, "-B", str(HERE / "owner_provision.py"), str(code_root),
            plan["sources"]["specification"]["path"], plan["sources"]["specification"]["sha256"],
            plan["sources"]["grand_map"]["path"], plan["sources"]["grand_map"]["sha256"]]


def start_graph_owner(desktop, plan: dict, python: str, code_root: Path):
    """Start the owner on the run's hidden desktop, inside the run's Job (desktop.spawn adopts it).
    Only launch_graph_owner calls this, after its gates."""
    command = " ".join('"%s"' % part if " " in part else part for part in [python, *plan["service_args"]])
    return desktop.spawn(command, env=plan["env"], cwd=str(code_root))


class OwnerRefused(RuntimeError):
    """The run's graph owner was not started (or not accepted): every reason is in .problems."""

    def __init__(self, problems: list):
        super().__init__("graph owner launch refused: " + "; ".join(problems))
        self.problems = list(problems)


# Run in a child process under the PLANNED environment: open what CURRENT selects, the way the owner will.
_READBACK = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.unified_authority_runtime import default_runtime_root, open_current_authority
location = open_current_authority(default_runtime_root(),
                                  WindowsDpapiSigningKeyProvider(WindowsDpapiSigningKeyProvider.default_path()))
try:
    print(json.dumps({"graph_id": location.authority.manifest.graph_id, "root": str(location.root),
                      "database": str(location.database_path), "manifest": str(location.manifest_path)}))
finally:
    location.authority.store.close()
"""


def _child_answer(runner, command: list, env: dict, timeout: int):
    done = runner(command, env=env, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        return None, (done.stderr or done.stdout)[-400:]
    try:
        return json.loads(done.stdout.strip().splitlines()[-1]), None
    except (ValueError, IndexError):
        return None, "no answer: " + done.stdout[-200:]


def provisioning_problems(plan: dict, python: str, code_root: Path, *, runner=subprocess.run) -> tuple:
    """Provision under the plan's environment, then read it back: CURRENT in the run's root must select
    the provisioned graph, and that generation must open (signature checked) from inside the run."""
    run_dir, root = Path(plan["run_dir"]).resolve(), Path(plan["runtime_root"]).resolve()
    built, error = _child_answer(runner, provision_command(plan, python, code_root), plan["env"], 600)
    if error is not None:
        return ["provisioning failed: " + error], None
    graph_id = built.get("graph_id")
    read, error = _child_answer(runner, [python, "-B", "-c", _READBACK, str(code_root)], plan["env"], 300)
    if error is not None:
        return ["the provisioned graph could not be read back: " + error], None
    problems = []
    if not graph_id or read.get("graph_id") != graph_id:
        problems.append("the graph read back (%r) is not the one provisioned (%r)" % (read.get("graph_id"), graph_id))
    if Path(read.get("root", "")).resolve() != root:
        problems.append("the graph read back lives at %s, not in the run's runtime root" % read.get("root"))
    for name in ("database", "manifest"):
        if not Path(read.get(name, "")).resolve().is_relative_to(run_dir):
            problems.append("the read-back %s lies outside the run: %s" % (name, read.get(name)))
    try:
        pointer = (root / "CURRENT").read_text(encoding="ascii").strip()
    except OSError:
        pointer = None
    if pointer != graph_id:
        problems.append("CURRENT in the run's root does not select the provisioned graph")
    return problems, (graph_id if not problems else None)


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

    def given(flag):
        return args[args.index(flag) + 1] if args.count(flag) == 1 and args.index(flag) + 1 < len(args) else None
    problems = []
    if port in LIVE_PORTS or canvas in LIVE_PORTS or port == canvas:
        problems.append("the owner's ports are not the run's own two: %r" % ((port, canvas),))
    if plan["endpoint"] != pinned:
        problems.append("the planned endpoint %r is not pinned to the run's port" % plan["endpoint"])
    if plan["env"].get("ARCHHUB_COORDINATION_ENDPOINT") != pinned:
        problems.append("the spawn environment points elsewhere: %r" % plan["env"].get("ARCHHUB_COORDINATION_ENDPOINT"))
    if given("--port") != str(port) or given("--canvas-port") != str(canvas):
        problems.append("the owner would bind %r/%r, not the pinned ports" % (given("--port"), given("--canvas-port")))
    if given("--root") != plan["runtime_root"]:
        problems.append("the owner would open %r, not the run's runtime root" % given("--root"))
    for taken in (p for p in (port, canvas) if not port_free(p)):
        problems.append("port %d is already taken: something else would answer the run's endpoint" % taken)
    return problems


def _health(port: int):
    with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=3) as answer:
        return json.loads(answer.read().decode("utf-8"))


def launch_graph_owner(desktop, plan: dict, python: str, code_root: Path, *, runner, health_seconds: int = 300,
                       port_free=_port_free, health=_health) -> dict:
    """Start the run's graph owner only when the plan, the provisioning read-back and the pinned endpoint
    all pass, checked here at the spawn itself; then accept it only when /health on the run's own port
    answers with the provisioned graph. Anything else raises OwnerRefused.

    runner must be Job-owned (real_app_check.JobRunner): every helper child joins the run's Job before
    it runs, keeps its handle and is waited on with a bound."""
    if not getattr(runner, "job_owned", False):
        raise OwnerRefused(["lifecycle: the helper runner is not owned by the run's Job; nothing was started"])
    record = {"endpoint": plan["endpoint"], "runtime_root": plan["runtime_root"], "sources": plan["sources"],
              "helpers": getattr(runner, "children", None)}
    problems = owner_isolation_problems(plan, python, code_root, runner=runner)
    if problems:                       # never provision when a root could land outside the run
        raise OwnerRefused(["plan: " + problem for problem in problems])
    problems, graph_id = provisioning_problems(plan, python, code_root, runner=runner)
    if problems:
        raise OwnerRefused(["provisioning read-back: " + problem for problem in problems])
    problems = endpoint_problems(plan, port_free=port_free)
    if problems:
        raise OwnerRefused(["pinned endpoint: " + problem for problem in problems])
    alive = runner.leftovers()
    if alive:
        raise OwnerRefused(["lifecycle: helper processes are still alive in the run's Job: %r" % (alive,)])
    record["graph_id"] = graph_id
    record["pid"] = int(start_graph_owner(desktop, plan, python, code_root).pid)
    started, last = time.monotonic(), None
    while time.monotonic() - started < health_seconds:
        try:
            last = health(plan["coordination_port"])
        except Exception as exc:  # noqa: BLE001 - not answering yet
            last = "%s: %s" % (type(exc).__name__, str(exc)[:120])
        if isinstance(last, dict) and last.get("ok"):
            if last.get("graph_id") != graph_id:
                raise OwnerRefused(["health: the owner on the run's port serves %r, not the provisioned %r"
                                    % (last.get("graph_id"), graph_id)])
            record["health"], record["health_seconds"] = last, round(time.monotonic() - started)
            return record
        time.sleep(1)
    raise OwnerRefused(["health: the run's owner did not answer /health within %ds (last: %r)"
                        % (health_seconds, last)])
