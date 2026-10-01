"""The run's OWN graph owner (clean coordination service), designed and proven before it is launched.

Not wired into real_app_check.main yet: Ping reviews this design and its courts first. The plan:

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
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
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


def owner_isolation_problems(plan: dict, python: str, code_root: Path) -> list:
    """Resolve the owner's and desktop's roots under the plan's environment; each must lie in the run
    folder, and the coordination endpoint must be the run's own. Any doubt is a problem."""
    run_dir = Path(plan["run_dir"]).resolve()
    done = subprocess.run([python, "-B", "-c", _RESOLVE, str(code_root)], env=plan["env"],
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
    Gated: real_app_check does not call this until Ping has reviewed the plan and its courts."""
    command = " ".join('"%s"' % part if " " in part else part for part in [python, *plan["service_args"]])
    return desktop.spawn(command, env=plan["env"], cwd=str(code_root))
