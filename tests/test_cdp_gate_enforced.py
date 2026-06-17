"""TCI-09 — the CDP smoke proof is an ENFORCED, honest gate, not a no-op.

`test_ui_cdp_smoke.py` is the canonical "shipped" proof: it clicks the running
ArchHub over CDP and asserts a real, observable state change. Its weakness (the
TCI-09 gap) was structural, not in the test body:

  1. **No CI job ever ran it with a display.** The only place it was collected
     (`.github/workflows/test.yml`) ran it under `QT_QPA_PLATFORM=offscreen`
     with no display and no `ARCHHUB_CDP_AUTOLAUNCH`, so it ALWAYS hit the
     "inspector not reachable" skip. The canonical proof was a permanent no-op
     on CI — "enforced only on the founder's machine", exactly as the leaf says.
  2. **A skip could silently mask a shipped feature.** Nothing checked that the
     ~13 `pytest.skip(...)` reasons were all environment-class. A future edit
     could add `pytest.skip("feature not landed yet")` and the suite would stay
     green over a real regression.

This guard closes both — and unlike the live CDP test it needs NO display, so
it runs (and is enforced) on every headless runner:

  * `test_cdp_smoke_is_collected_not_ignored` — the CDP gate is not excluded
    from any CI `--ignore` set (the blessed dev command + daily-audit + test.yml
    must COLLECT it).
  * `test_a_ci_job_runs_cdp_under_display_with_autolaunch` — some CI workflow
    runs `test_ui_cdp_smoke.py` under a real display (xvfb / `xvfb-run` /
    `setup-xvfb`) AND sets `ARCHHUB_CDP_AUTOLAUNCH=1`, so the proof actually
    EXECUTES on CI the moment a display is present.
  * `test_every_cdp_skip_reason_is_honest` — every skip reason in the CDP test
    is environment-class (matches `HONEST_SKIP_TOKENS`) and carries NO
    founder-deferral marker, so a skip can never stand in for a shipped feature.

Together these make "the canonical CDP proof is wired to run + can only skip for
honest reasons" a machine-checked invariant — the no-op gap can't recur.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

import yaml  # PyYAML — already a transitive dep of the toolchain; assert it loads

REPO_ROOT = Path(__file__).resolve().parent.parent
CDP_TEST = REPO_ROOT / "tests" / "test_ui_cdp_smoke.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CDP_TEST_NAME = "test_ui_cdp_smoke.py"

# A skip reason that contains any of these is a founder-deferral / feature-mask
# marker and is BANNED in the CDP gate — a skip must be about the environment,
# never about a feature that "isn't done".
BANNED_SKIP_MARKERS = (
    "not landed",
    "shipped yet",
    "not shipped",
    "tracked in roadmap",
    "agent 3",
    "todo",
    "fixme",
    "for now",
    "later",
    "wip",
    "coming soon",
)


def _load_honest_tokens() -> tuple[str, ...]:
    """Pull HONEST_SKIP_TOKENS straight from the CDP module (single source of
    truth — the test owns its own taxonomy, this guard just enforces it)."""
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    import test_ui_cdp_smoke as cdp  # noqa: E402
    toks = getattr(cdp, "HONEST_SKIP_TOKENS", None)
    assert toks, (
        "test_ui_cdp_smoke.py must define HONEST_SKIP_TOKENS — the audited "
        "allowlist of environment-class skip reasons.")
    return tuple(t.lower() for t in toks)


def _skip_reason_strings(tree: ast.AST) -> list[str]:
    """Every literal text fed to `pytest.skip(...)` in the module, including the
    constant parts of f-strings (the dynamic `{...}` holes are ignored — the
    honest token always lives in a literal part)."""
    reasons: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_skip = (
            (isinstance(fn, ast.Attribute) and fn.attr == "skip")
            and isinstance(getattr(fn, "value", None), ast.Name)
            and fn.value.id == "pytest"
        )
        if not is_skip or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            reasons.append(arg.value)
        elif isinstance(arg, ast.JoinedStr):  # f-string
            lit = "".join(
                p.value for p in arg.values
                if isinstance(p, ast.Constant) and isinstance(p.value, str)
            )
            reasons.append(lit)
        else:
            # A non-literal skip reason (a bare variable / call) can't be
            # audited statically — that itself is a violation of the taxonomy.
            reasons.append("<<non-literal skip reason>>")
    return reasons


# ───────────────────────────────────────────────────────────────────────────
# 1. The CDP gate is COLLECTED by CI (not excluded by any --ignore).
# ───────────────────────────────────────────────────────────────────────────
def test_cdp_smoke_is_collected_not_ignored():
    """No CI workflow may `--ignore` the CDP smoke test. It was deliberately
    REMOVED from the ignore set (test.yml comment block) so it is collected +
    run; this guard makes that permanent. (The two live-Qt harnesses
    test_bridge_qt / test_ui_smoke MAY be ignored — only the CDP proof is
    pinned as collected.)"""
    assert CDP_TEST.exists(), f"{CDP_TEST} missing"
    offenders = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        # Any `--ignore=...test_ui_cdp_smoke.py` (with or without the tests/ prefix).
        if re.search(r"--ignore=\S*" + re.escape(CDP_TEST_NAME), text):
            offenders.append(wf.name)
    assert not offenders, (
        "CDP smoke gate is --ignore'd in: " + ", ".join(offenders) +
        " — that re-buries the canonical proof. Remove the ignore so it is "
        "collected + run.")


# ───────────────────────────────────────────────────────────────────────────
# 2. A CI job actually RUNS it under a display + AUTOLAUNCH (so it executes).
# ───────────────────────────────────────────────────────────────────────────
def test_a_ci_job_runs_cdp_under_display_with_autolaunch():
    """At least one workflow must run the CDP smoke test under a real display
    (xvfb) AND with ARCHHUB_CDP_AUTOLAUNCH=1, so the canonical click-the-app
    proof EXECUTES on CI instead of permanently self-skipping on a headless
    runner. We parse the YAML and look for a step that:

      * names test_ui_cdp_smoke.py in its run command, AND
      * runs it under xvfb (xvfb-run / Xvfb / a setup-xvfb action / a
        DISPLAY-backed run), AND
      * has ARCHHUB_CDP_AUTOLAUNCH set to '1' in scope (job env or step env).
    """
    assert WORKFLOWS.is_dir(), f"{WORKFLOWS} missing"

    def _runs_cdp(run_text: str) -> bool:
        return CDP_TEST_NAME in run_text

    def _under_display(step: dict, wf_text: str) -> bool:
        run = str(step.get("run", "")) if isinstance(step, dict) else ""
        uses = str(step.get("uses", "")) if isinstance(step, dict) else ""
        if re.search(r"\bxvfb-run\b|\bXvfb\b|\bxvfb\b", run):
            return True
        if "setup-xvfb" in uses or "xvfb-action" in uses:
            return True
        # A step that explicitly sets a DISPLAY for a real X server also counts.
        if re.search(r"DISPLAY\s*[:=]", run):
            return True
        return False

    found = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        wf_text = wf.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(wf_text)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_env = job.get("env") or {}
            steps = job.get("steps") or []
            # Track whether AUTOLAUNCH is on for the job, or set per-step.
            for step in steps:
                if not isinstance(step, dict):
                    continue
                run = str(step.get("run", ""))
                if not _runs_cdp(run):
                    continue
                step_env = step.get("env") or {}
                autolaunch = str(
                    step_env.get("ARCHHUB_CDP_AUTOLAUNCH",
                                 job_env.get("ARCHHUB_CDP_AUTOLAUNCH", ""))
                ).strip()
                # xvfb may be set up in an EARLIER step (e.g. a global
                # `xvfb-run` wrapper or a setup-xvfb action), so accept either
                # this step being under xvfb OR any step in the job being so.
                disp = _under_display(step, wf_text) or any(
                    _under_display(s, wf_text) for s in steps
                    if isinstance(s, dict))
                if autolaunch == "1" and disp:
                    found.append(f"{wf.name}:{job_name}")

    assert found, (
        "No CI workflow runs test_ui_cdp_smoke.py under a display (xvfb) with "
        "ARCHHUB_CDP_AUTOLAUNCH=1. Without it the canonical CDP proof can only "
        "ever SKIP on CI — 'enforced only on the founder's machine'. Add a job "
        "that runs it under xvfb + software GL with AUTOLAUNCH on.")


# ───────────────────────────────────────────────────────────────────────────
# 3. Every CDP skip reason is honest (env-class token, no deferral marker).
# ───────────────────────────────────────────────────────────────────────────
def test_every_cdp_skip_reason_is_honest():
    """Parse the CDP test's AST and assert every `pytest.skip(...)` reason is
    environment-class (contains a HONEST_SKIP_TOKENS substring) and carries NO
    founder-deferral / feature-mask marker. A skip that could fire because a
    SHIPPED feature regressed is the banned self-neutralizing skip; here it is
    impossible to merge one."""
    tokens = _load_honest_tokens()
    tree = ast.parse(CDP_TEST.read_text(encoding="utf-8"), filename=str(CDP_TEST))
    reasons = _skip_reason_strings(tree)
    assert reasons, "expected to find pytest.skip(...) calls in the CDP gate"

    dishonest = []
    for r in reasons:
        low = r.lower()
        if any(b in low for b in BANNED_SKIP_MARKERS):
            dishonest.append(("deferral-marker", r))
            continue
        if not any(t in low for t in tokens):
            dishonest.append(("no-env-token", r))

    assert not dishonest, (
        "CDP skip reasons that could mask a shipped feature:\n  " +
        "\n  ".join(f"[{why}] {r!r}" for why, r in dishonest) +
        "\nEvery skip must be environment-class (a HONEST_SKIP_TOKENS token) "
        "and free of deferral markers ('not landed', 'shipped yet', "
        "'tracked in ROADMAP', 'TODO', ...).")
