"""A deliberation payload is evidence for one decision, not a report dump.

2026-09-05: the founder's graph was 4.29 GB and took 694s to boot (from 534 MB
and 45s). 2.3M of its 3.04M cells were one thing: the brain's hook-coverage
audit appending its whole per-client report on every run -- ~2,180 cells an
audit, 1,056 audits. The audit now writes a receipt, and the bound below makes
that structural for every caller."""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from nodelang import cell_deliberation

def _call_starts(text: str, needle: str):
    at, out = 0, []
    while True:
        at = text.find(needle, at)
        if at < 0:
            return out
        out.append(at + len(needle) - 1)
        at += len(needle)


def _call_end(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


BRAIN = Path(__file__).resolve().parents[2] / "12.PRODUCTION" / "personal-brain-mcp" / "src" / "personal_brain" / "hook_coverage.py"


def test_a_payload_is_bounded_in_cells():
    assert cell_deliberation._DELIBERATION_PAYLOAD_CELL_LIMIT == 400
    src = inspect.getsource(cell_deliberation.append_deliberation_value_entry)
    assert "len(prepared_value.create) > _DELIBERATION_PAYLOAD_CELL_LIMIT" in src
    assert "record a summary and a digest" in src
    # The bound is checked BEFORE the commit, never after.
    assert src.index("_DELIBERATION_PAYLOAD_CELL_LIMIT") < src.index("store.commit(")


@pytest.mark.skipif(not BRAIN.is_file(), reason="brain package is not beside this checkout")
def test_the_hook_coverage_audit_writes_a_receipt():
    src = BRAIN.read_text(encoding="utf-8")
    start = src.index("def audit_cell_first")
    audit = src[start:src.index("\ndef repair(", start)]
    assert "payload=receipt," in audit and "report_sha256" in audit
    assert "payload=report_payload," not in audit, "the whole report must not reach the ledger again"
    assert '"client_count"' in audit
    # the repair pair records digests, not the reports
    repair = src[src.index("def repair_cell_first"):]
    assert "before_sha256" in repair and "after_sha256" in repair
    # NO ledger call anywhere in this module may carry a serialised report.
    # (Return values may; they never reach the graph.)
    dumped_key = re.compile(r'"[a-z_]+":\s*\w+\.model_dump\(')
    for start in _call_starts(src, "deliberation_append("):
        call = src[start:_call_end(src, start)]
        found = dumped_key.search(call)
        assert found is None, "a ledger payload carries a whole report: " + found.group(0)
