"""Courts for reflexion: with no ledger, nothing is remembered."""
from __future__ import annotations

from nodelang.cell_brain_reflexion import LEDGER_ROOT, occurrences
from nodelang.universal_cell import CellStore

SIGNATURE = "group-settle-timeout"


def test_no_ledger_remembers_nothing():
    store = CellStore()
    assert LEDGER_ROOT not in store.snapshot().cells
    assert occurrences(store.snapshot(), SIGNATURE) == ()
