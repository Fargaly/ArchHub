"""CLD-12 — archhub-agents has a real health/smoke test + a CI deploy.

Three gaps closed by this leaf, each pinned by a test below:

  1. **No real smoke endpoint/script.** The reality probe only checks the
     *deployed* agents URL. ``scripts/agents_smoke.py`` boots the REAL agents
     dashboard app (``agents.dashboard_endpoint.build_app``) with the REAL
     heartbeat writer (``agents.cloud_runner.CloudDaemon.write_heartbeat``) and
     runs the ACTUAL ``reality_smoke`` agents checks against it — proving the
     container's health surface boots and answers, with no Fly deploy.
     ``test_agents_smoke_script_boots_real_app_and_passes`` runs the script as a
     real subprocess and asserts exit 0 + green JSON.

  2. **No CI deploy job.** ``.github/workflows/agents_deploy.yml`` deploys the
     ``archhub-agents`` Fly app on push to main (gated on ``FLY_API_TOKEN``) and
     runs the reality probe post-deploy against the live URL. Before this leaf,
     ``agents_dispatch.yml`` drained the queue in Actions but nothing redeployed
     the Fly container, so it drifted / went down silently.
     ``test_agents_deploy_workflow_*`` assert the workflow exists, deploys via
     flyctl, runs the smoke as a pre-deploy gate, and probes reality post-deploy.

  3. **Deploy undocumented for CI.** ``test_cloud_deploy_doc_covers_ci_deploy``
     asserts ``agents/CLOUD_DEPLOY.md`` documents the CI deploy + the smoke
     script (not just the manual ``deploy.ps1`` path).

RED on origin/main: ``scripts/agents_smoke.py`` and
``.github/workflows/agents_deploy.yml`` do not exist; CLOUD_DEPLOY.md has no CI
section → the script run, the workflow assertions, and the doc assertion all
fail. GREEN after this leaf adds them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "agents_smoke.py"
DEPLOY_WF = REPO_ROOT / ".github" / "workflows" / "agents_deploy.yml"
CLOUD_DEPLOY_DOC = REPO_ROOT / "agents" / "CLOUD_DEPLOY.md"

# The smoke boots a real FastAPI app on uvicorn; skip cleanly (not fail) if a
# runner somehow lacks those — honest typed unavailability, never a false red.
_HAVE_SERVER_DEPS = True
try:  # pragma: no cover - import probe
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
except Exception:  # pragma: no cover
    _HAVE_SERVER_DEPS = False


# ─────────────────────────── 1. real smoke script ──────────────────────────
def test_agents_smoke_script_exists():
    assert SMOKE_SCRIPT.is_file(), f"missing real smoke script {SMOKE_SCRIPT}"


@pytest.mark.skipif(not _HAVE_SERVER_DEPS,
                    reason="fastapi/uvicorn not installed")
def test_agents_smoke_script_boots_real_app_and_passes():
    """Run scripts/agents_smoke.py for real and assert it boots the agents app
    and reports green. This is the behavioural gate: the script must actually
    stand up the container's health surface and the real reality checks must
    pass against it."""
    proc = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--json", "--timeout", "30"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, (
        f"agents_smoke.py exited {proc.returncode}\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert payload["summary"]["failed"] == 0, payload
    assert payload["summary"]["green"] >= 3, payload
    names = {c["name"]: c["status"] for c in payload["checks"]}
    # The three real checks must all be green: the app booted, /healthz is
    # fresh, and /status reports departments + a completed-today task.
    assert names.get("agents.boot") == "ok", names
    assert names.get("agents.healthz") == "ok", names
    assert names.get("agents.status") == "ok", names


@pytest.mark.skipif(not _HAVE_SERVER_DEPS,
                    reason="fastapi/uvicorn not installed")
def test_agents_smoke_run_smoke_callable_returns_green():
    """The importable entrypoint (run_smoke) returns all-ok CheckResults — so
    other tooling (CI, the deploy workflow's pre-deploy gate) can call it
    in-process, not just via the CLI.

    Run in a CLEAN subprocess (cwd=repo root) so the repo-root ``agents``
    daemon package resolves unambiguously. The desktop app ships a separate
    ``app/agents/`` package and this suite's conftest puts ``app/`` on
    sys.path; calling ``run_smoke`` directly inside the pytest interpreter
    could bind ``agents`` to that shadow. A subprocess avoids mutating the
    test interpreter's sys.modules at all — honest isolation, no surgery.
    """
    code = (
        "import sys, json; sys.path.insert(0, 'scripts'); "
        "import agents_smoke; "
        "r = agents_smoke.run_smoke(timeout=30); "
        "print(json.dumps({x.name: x.status for x in r}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, (
        f"run_smoke subprocess exited {proc.returncode}\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    statuses = json.loads(proc.stdout.strip().splitlines()[-1])
    assert statuses, "run_smoke returned no checks"
    assert all(s == "ok" for s in statuses.values()), statuses
    assert "agents.healthz" in statuses and "agents.status" in statuses


# ─────────────────────────── 2. CI deploy workflow ─────────────────────────
def test_agents_deploy_workflow_exists():
    assert DEPLOY_WF.is_file(), (
        f"no CI deploy workflow for archhub-agents at {DEPLOY_WF} — the Fly app "
        f"has no automated deploy and drifts/goes down"
    )


def test_agents_deploy_workflow_deploys_via_flyctl():
    text = DEPLOY_WF.read_text(encoding="utf-8")
    # Real deploy: uses the official flyctl action + a fly deploy against the
    # agents fly.toml, gated on the FLY_API_TOKEN secret.
    assert "superfly/flyctl-actions/setup-flyctl" in text, text[:400]
    assert "flyctl deploy" in text and "agents/fly.toml" in text, text[:400]
    assert "FLY_API_TOKEN" in text, "deploy must be gated on FLY_API_TOKEN secret"


def test_agents_deploy_workflow_runs_smoke_then_probes_reality():
    text = DEPLOY_WF.read_text(encoding="utf-8")
    # Pre-deploy gate: run the real smoke script so a broken build never ships.
    assert "scripts/agents_smoke.py" in text, "deploy must gate on agents_smoke"
    # Post-deploy: the reality probe is green against the live agents URL.
    assert "scripts/reality_smoke.py" in text, "deploy must probe reality post-deploy"
    assert "archhub-agents.fly.dev" in text or "--agents-url" in text, text[:600]


# ─────────────────────────── 3. documented ─────────────────────────────────
def test_cloud_deploy_doc_covers_ci_deploy():
    assert CLOUD_DEPLOY_DOC.is_file(), f"missing {CLOUD_DEPLOY_DOC}"
    text = CLOUD_DEPLOY_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    # Names the CI workflow + the smoke script so the deploy path is documented,
    # not just the manual deploy.ps1.
    assert "agents_deploy.yml" in text, "CLOUD_DEPLOY.md must document the CI deploy workflow"
    assert "agents_smoke.py" in text, "CLOUD_DEPLOY.md must document the smoke script"
    assert "fly_api_token" in lowered, "CLOUD_DEPLOY.md must document the FLY_API_TOKEN secret"
