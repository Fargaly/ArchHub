"""Hermetic tests for ai.plan's THE-DRIVE (no-later) lint helper `_lint_plan`.

Runnable both under pytest and as a bare script (`python test_ai_plan_lint.py`).
Loads the ai_plan module by its absolute file path via importlib so collection
never depends on cwd / package layout; falls back to adding app/ on sys.path.
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[1]
_AI_PLAN = _REPO / "app" / "workflows" / "nodes" / "ai_plan.py"
_APP = _REPO / "app"


def _load_lint_plan():
    # Primary: import the module file directly by absolute path.
    try:
        spec = importlib.util.spec_from_file_location(
            "archhub_ai_plan_under_test", str(_AI_PLAN))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._lint_plan
    except Exception:
        # Fallback: add app/ on sys.path and import the package path.
        if str(_APP) not in sys.path:
            sys.path.insert(0, str(_APP))
        from workflows.nodes.ai_plan import _lint_plan  # type: ignore
        return _lint_plan


_lint_plan = _load_lint_plan()


def test_bare_later_blocks():
    assert _lint_plan("do the rest later")["action"] == "block"


def test_all_done_allows():
    assert _lint_plan("all done, every sheet tagged")["action"] == "allow"


def test_safety_gated_allows():
    assert _lint_plan(
        "S5 rollout safety-gated: after red-team")["action"] == "allow"


if __name__ == "__main__":
    cases = [
        ("bare_later_blocks", test_bare_later_blocks),
        ("all_done_allows", test_all_done_allows),
        ("safety_gated_allows", test_safety_gated_allows),
    ]
    failures = 0
    for name, fn in cases:
        try:
            fn()
            print("PASS", name)
        except AssertionError as ex:
            failures += 1
            print("FAIL", name, "-", ex or "assertion failed")
        except Exception as ex:  # pragma: no cover - defensive
            failures += 1
            print("FAIL", name, "- error:", repr(ex))
    print("SUMMARY: {} passed, {} failed".format(len(cases) - failures, failures))
    sys.exit(1 if failures else 0)
