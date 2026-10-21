"""A court passes only on tests that RAN and passed.

judge_by_binding counted every matching case as a success and rejected only
"fail". It computed a "skip" outcome and never used it. And a declared
selector the report never mentioned was ignored, as long as some other
selector matched something. Both were reproduced against the function
itself (Codex audit, 2026-09-07).

A court that can pass without evidence is worse than no court: it is the
scoreboard telling the founder a thing is done when nothing proved it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evidence"))
from the_court_judge import judge_by_binding  # noqa: E402


DECL = {"bindings": {"C-1": {"tests": ["tests/test_a.py", "tests/test_b.py"]}}}
ONE = {"bindings": {"C-1": {"tests": ["tests/test_a.py::test_it"]}}}


def test_a_skipped_test_does_not_pass_its_court():
    verdict, reason = judge_by_binding(
        "C-1", {"tests/test_a.py": [("test_it", "skip")]}, ONE
    )
    assert verdict is None, "a skip proves nothing; it cannot be a PASS"
    assert "skipped" in reason


def test_a_declared_selector_with_no_result_is_not_judged():
    verdict, reason = judge_by_binding(
        "C-1", {"tests/test_a.py": [("test_one", "pass")]}, DECL
    )
    assert verdict is None, "half the declared evidence is not the evidence"
    assert "tests/test_b.py" in reason


def test_a_real_failure_still_fails():
    verdict, reason = judge_by_binding(
        "C-1",
        {
            "tests/test_a.py": [("test_one", "fail")],
            "tests/test_b.py": [("test_two", "pass")],
        },
        DECL,
    )
    assert verdict is False
    assert "failed" in reason


def test_every_declared_test_running_and_passing_is_a_pass():
    verdict, reason = judge_by_binding(
        "C-1",
        {
            "tests/test_a.py": [("test_one", "pass")],
            "tests/test_b.py": [("test_two", "pass")],
        },
        DECL,
    )
    assert verdict is True
    assert "2 bound tests passed" in reason


def test_a_court_with_no_results_at_all_is_not_judged():
    verdict, reason = judge_by_binding("C-1", {}, DECL)
    assert verdict is None
    assert "none of them" in reason


def test_a_court_nobody_declared_is_not_judged():
    assert judge_by_binding("C-9", {}, DECL) == (None, None)


@pytest.mark.parametrize("outcome", ["skip", "fail"])
def test_one_bad_result_among_good_ones_is_never_hidden(outcome):
    verdict, _reason = judge_by_binding(
        "C-1",
        {
            "tests/test_a.py": [("test_one", "pass"), ("test_two", outcome)],
            "tests/test_b.py": [("test_three", "pass")],
        },
        DECL,
    )
    assert verdict is not True
