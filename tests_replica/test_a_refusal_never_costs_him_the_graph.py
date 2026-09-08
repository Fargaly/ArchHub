"""The boot may refuse. It may not decide, on his behalf, to start over.

Four times between 2026-09-01 and 2026-09-07 the launcher set the founder's
graph aside and opened an empty canvas, for four different reasons:

    runtime descriptor signature is invalid
    Cell database is held by another live process
    disk I/O error
    Application Agent Body catalog binding drifted

Only two of those were named in the keep-in-place list, so the other two
fell through to the set-aside branch. The last one is the tell: a binding
disagreeing with a catalogue is DERIVED state -- every Cell underneath it
was intact, and 5 GB of his work went into a folder he never saw because a
projection had drifted.

The list now names what is UNREADABLE rather than what is transient, so a
refusal nobody anticipated keeps the graph instead of replacing it.
"""
from __future__ import annotations

from pathlib import Path
import re


LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"
SOURCE = LAUNCHER.read_text(encoding="utf-8")


def _keep_branch() -> str:
    start = SOURCE.index("_UNREADABLE_MARKS")
    end = SOURCE.index("raise boot_refusal", start)
    return SOURCE[start:end]


def test_the_graph_is_kept_unless_the_bytes_cannot_be_read():
    """Keep is the default; only unreadable bytes fall through."""
    branch = _keep_branch()

    assert "not any(" in branch
    assert "mark in str(boot_refusal) for mark in _UNREADABLE_MARKS" in branch


def test_only_unreadable_marks_may_reach_the_set_aside():
    """Every mark that forfeits the graph names damage to the FILE."""
    marks = re.search(
        r"_UNREADABLE_MARKS = \((.*?)\)", SOURCE, re.S
    ).group(1)
    listed = re.findall(r'"([^"]+)"', marks)

    assert listed, "the unreadable list must not be empty"
    for mark in listed:
        assert any(
            word in mark
            for word in ("not a database", "malformed", "corruption", "no such table")
        ), "%r is not evidence the bytes are unreadable" % mark


def test_the_refusals_that_cost_him_the_graph_no_longer_do():
    """The exact four, by name, held so they cannot regress."""
    marks = re.search(r"_UNREADABLE_MARKS = \((.*?)\)", SOURCE, re.S).group(1)
    listed = re.findall(r'"([^"]+)"', marks)

    for refusal in (
        "runtime descriptor signature is invalid",
        "Cell database is held by another live process",
        "disk I/O error",
        "Application Agent Body catalog binding drifted",
    ):
        assert not any(mark in refusal for mark in listed), (
            "%r would still set the founder's graph aside" % refusal
        )


def test_the_set_aside_still_exists_for_a_graph_that_truly_cannot_be_read():
    """Inverting the default must not remove the escape hatch."""
    assert "set_aside = state_dir / (" in SOURCE
    assert "old data kept in" in SOURCE


def test_he_is_told_the_graph_was_kept_and_what_refused():
    """A refusal he cannot read is a crash with better manners."""
    branch = _keep_branch()

    assert "KEPT IN PLACE" in branch
    assert "could not open the saved graph" in branch
