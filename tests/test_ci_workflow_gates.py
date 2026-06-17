"""CI-workflow gates — TCI-01, TCI-02, TCI-08, TCI-12.

Each of these leaves is a hole in the CI contract: a production suite or a
release-asset check that simply was not wired into any workflow. The fix is a
workflow change, so the machine-checkable gate is a test that parses the
workflow YAML and asserts the required step/job is present. Every test here is
RED on origin/main (the step does not exist) and GREEN once the workflow is
committed.

We parse the real YAML on disk (not a snapshot) and assert on the resolved
job/step structure + the `run:` script text, so the gate tracks what CI will
actually execute.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # PyQt app dev/CI envs ship pyyaml.

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load_workflow(name: str) -> dict:
    path = WORKFLOWS / name
    assert path.is_file(), f"workflow {name} missing"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _all_run_text(workflow: dict) -> str:
    """Concatenate every step's `run:` across every job — the script CI runs."""
    chunks: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps", []) or []:
            run = step.get("run")
            if isinstance(run, str):
                chunks.append(run)
    return "\n".join(chunks)


def _job_run_text(workflow: dict, job_name: str) -> str:
    job = (workflow.get("jobs") or {}).get(job_name)
    assert job is not None, f"job '{job_name}' not found"
    return "\n".join(
        step["run"] for step in job.get("steps", []) or []
        if isinstance(step.get("run"), str)
    )


# ── TCI-01: personal-brain-mcp suite runs in CI ────────────────────────────
def test_tci01_brain_suite_runs_in_test_workflow():
    """test.yml must run the personal-brain-mcp suite. Gate from the leaf:
    grep -c "personal-brain-mcp" test.yml >= 1, AND a step actually invokes
    pytest against it."""
    wf = _load_workflow("test.yml")
    raw = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    assert raw.count("personal-brain-mcp") >= 1, (
        "test.yml never references personal-brain-mcp — the 600+ brain tests "
        "still run in NO workflow (TCI-01)"
    )
    # A step must cd/working-directory into the brain and run pytest.
    brain_step = False
    for job in wf["jobs"].values():
        for step in job.get("steps", []) or []:
            wd = str(step.get("working-directory", ""))
            run = str(step.get("run", ""))
            if "personal-brain-mcp" in wd and run.strip().startswith("pytest"):
                brain_step = True
            if "personal-brain-mcp" in run and "pytest" in run:
                brain_step = True
    assert brain_step, (
        "no test.yml step runs `pytest` against personal-brain-mcp — the brain "
        "suite is referenced but not executed"
    )


# ── TCI-02: agents/ package has a test job ─────────────────────────────────
def test_tci02_agents_tests_dir_exists():
    """`test -d agents/tests` — the leaf's structural gate."""
    assert (REPO_ROOT / "agents" / "tests").is_dir(), (
        "agents/ has no tests/ directory — the deployed archhub-agents modules "
        "still have zero coverage (TCI-02)"
    )


def test_tci02_agents_suite_runs_in_ci():
    """A required job runs `pytest agents/tests/`."""
    wf = _load_workflow("test.yml")
    assert "pytest agents/tests/" in _all_run_text(wf), (
        "no CI job runs `pytest agents/tests/` — agents coverage isn't gated"
    )


def test_tci02_agents_tests_cover_named_modules():
    """The leaf requires >=1 test each for scheduler / dispatcher / ceo_routine."""
    tests_dir = REPO_ROOT / "agents" / "tests"
    for mod in ("scheduler", "dispatcher", "ceo_routine"):
        f = tests_dir / f"test_{mod}.py"
        assert f.is_file(), f"agents/tests/test_{mod}.py missing"
        assert "def test_" in f.read_text(encoding="utf-8"), (
            f"agents/tests/test_{mod}.py has no test functions"
        )


# ── TCI-08: a CI job installs brain extras + runs the gated happy paths ─────
def test_tci08_brain_extras_job_installs_optional_deps():
    """A job installs the optional deps (clip/boto3/pillow/fastapi) the 10
    skip-gated brain tests need."""
    wf = _load_workflow("test.yml")
    run_text = _all_run_text(wf).lower()
    # The multimodal extra is sentence-transformers (what is_clip_available
    # probes) — installed via the brain's [multimodal] extra, plus cloud
    # (boto3) and federation (fastapi).
    assert "multimodal" in run_text and "cloud" in run_text and "federation" in run_text, (
        "no CI job installs the brain multimodal/cloud/federation extras — the "
        "CLIP/boto3/Pillow/FastAPI-gated happy-path tests never run (TCI-08)"
    )


def test_tci08_brain_extras_job_runs_the_four_files_and_asserts_no_skips():
    """The extras job runs the 4 named files AND fails if any happy-path test
    skipped (the anti-lie gate: extras installed must mean 0 skips)."""
    wf = _load_workflow("test.yml")
    extras = (wf.get("jobs") or {}).get("brain-extras")
    assert extras is not None, "no `brain-extras` job in test.yml (TCI-08)"
    run_text = _job_run_text(wf, "brain-extras")
    for fname in ("test_embedding.py", "test_phash.py",
                  "test_cloud_archive.py", "test_slices_9_through_16.py"):
        assert fname in run_text, f"brain-extras job does not run {fname}"
    # The job must DETECT a skip and fail — otherwise a silently-missing extra
    # would let the gated test skip and the job still go green.
    assert "SKIPPED" in run_text and "exit 1" in run_text, (
        "brain-extras job does not fail on a SKIPPED happy-path test — a "
        "missing extra could hide behind a green skip (TCI-08 anti-lie gate)"
    )


# ── TCI-12: build workflows smoke-test the built artifact ──────────────────
@pytest.mark.parametrize("workflow", ["build-linux.yml", "build-macos.yml", "release.yml"])
def test_tci12_build_workflow_has_launch_smoke(workflow):
    """Each build workflow runs a post-build import/launch smoke that asserts a
    clean exit (so a bundle that crashes on first launch can't ship)."""
    wf = _load_workflow(workflow)
    run_text = _all_run_text(wf)
    assert "--smoke" in run_text, (
        f"{workflow} has no `--smoke` launch check — a bundle that builds but "
        f"crashes on first import/launch would ship as a release asset (TCI-12)"
    )
    # And it must run the app/its bundle (not merely mention the flag).
    runs_app = (
        "app/main.py --smoke" in run_text          # source launch (windows)
        or "ArchHub --smoke" in run_text           # built bundle (linux/macos)
    )
    assert runs_app, (
        f"{workflow}'s smoke step doesn't invoke the app/bundle with --smoke"
    )


def test_tci12_app_main_supports_smoke_flag():
    """The smoke is REAL: app/main.py honours --smoke / ARCHHUB_SMOKE with a
    clean early exit before the event loop. Asserting the source carries the
    handler keeps the build smoke from silently degrading to a hung event loop."""
    main_src = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "--smoke" in main_src and "ARCHHUB_SMOKE" in main_src, (
        "app/main.py has no --smoke / ARCHHUB_SMOKE handler — the build smoke "
        "would launch the full event loop and hang the CI job"
    )
