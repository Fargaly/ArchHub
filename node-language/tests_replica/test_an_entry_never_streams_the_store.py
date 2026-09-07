"""A deliberation entry never streams the whole store to check a reference.

`set(snapshot.cells)` streamed every id (162,904 on the founder's graph)
for one membership check on every entry. Each brain observe appends a
control receipt through the app's pipe, so each observe held the mutation
lock for the whole scan; the brain's tool workers queued on the pipe,
health timed out, and the watchdog killed the brain in a loop (2026-09-07).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nodelang.cell_deliberation import absent_roots

ROOT = Path(__file__).resolve().parents[1]


class _HeadMap:
    """Answers membership by key, refuses to be iterated."""

    def __init__(self, held):
        self.held = set(held)

    def __contains__(self, key):
        return key in self.held

    def __iter__(self):
        raise AssertionError("the whole store was streamed for a membership check")


def test_references_are_checked_by_point_reads():
    cells = _HeadMap({"a", "b", "c"})
    assert absent_roots(cells, ("a", "b")) == ()
    assert absent_roots(cells, ("a", "z", "y")) == ("y", "z")
    assert absent_roots(cells, ("a", "z"), pending=("z",)) == ()


def test_no_module_on_the_entry_path_materialises_the_store():
    for name in ("cell_deliberation.py", "cell_relation_exposure_policy.py",
                 "cell_legacy_custom_nodes.py", "cell_value_graph.py"):
        source = (ROOT / "nodelang" / name).read_text(encoding="utf-8")
        assert not re.search(r"set\(snapshot\.cells\)", source), name
    app = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    assert "required - set(snapshot.cells)" not in app
