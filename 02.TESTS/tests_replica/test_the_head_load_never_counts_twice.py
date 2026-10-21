"""The head load may audit. It may not compare a number to itself.

Until 326b657 the resumed load ended with

    indexed_count = SELECT COUNT(*) FROM current_cells
    if indexed_count != len(current): raise

and len(current) resolved through _LoadingHeadMap.__len__ and
_LazyHeadCellMap.__len__ to _HeadRowReader.count() -- the SAME statement.
Both sides were one scan of the founder's 3,921,457-row head, 12.17s each,
measured 2026-09-08: every boot paid about 24 seconds to establish that
3921457 equals 3921457.

326b657 replaced the load with a streamed, row-by-row audit. This court
holds the outcome, not a line number: the load never counts the head.

What the load must still CHECK is judged by behaviour elsewhere --
tests_replica/test_journal_streamed_recovery.py corrupts the index (missing,
extra, atom, link, revision) on a cold and on a checkpointed load and
requires the refusal. This file does not repeat that.
"""
from __future__ import annotations

import inspect
import re

from nodelang import universal_cell
from nodelang.universal_cell import _HeadRowReader, _SqliteJournal


_HEAD_COUNT = re.compile(r"COUNT\(\*\)\s+FROM\s+current_cells", re.I)


def _code(text: str) -> str:
    """Source with comments stripped -- the rule is about what RUNS."""
    return chr(10).join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_reader_count_is_a_full_scan_and_so_may_not_be_casual():
    """Why this matters at all, stated where it cannot rot."""
    body = inspect.getsource(_HeadRowReader.count)

    assert "SELECT COUNT(*) FROM current_cells" in body


def test_the_head_load_never_counts_the_head():
    load = _code(inspect.getsource(_SqliteJournal._load_head_in_transaction))

    assert not _HEAD_COUNT.search(load)
    assert "_JOURNAL_CURRENT_CELL_COUNT_QUERY" not in load
    assert ".count()" not in load
    assert "indexed_count" not in load


def test_no_self_comparing_count_returns_anywhere_in_the_journal():
    """One shape, held across the file, so it cannot come back renamed."""
    source = _code(
        open(universal_cell.__file__, encoding="utf-8").read()
    )

    assert not re.search(
        r"COUNT\(\*\)\s+FROM\s+current_cells[\s\S]{0,400}?!=\s*len\(",
        source,
    )