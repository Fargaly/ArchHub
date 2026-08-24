"""Memos that survive the commits which did not touch what they read.

A memo keyed on the store revision is thrown away by every commit, and in
an application where looking at something commits (a focus, a viewport, a
session) that means the expensive read is paid again on every click. The
catalogue read cost 24.8s of a 51.4s scope entry for exactly that reason.

Enumerating a read set and comparing IDS was tried twice on this graph and
a publish slipped past both times: a newly added definition writes cells
whose ids were never read, so nothing in the enumerated set changed while
the answer did. The fix is to compare INCIDENCE as well as identity -- a
new cell that joins a region links to something in that region, and the
journal records both links. A memo is kept only when nothing written since
it names, or points at, anything it read.

The append-only rule is what makes this sound: nothing below the memo's
revision can change, so the whole question is what was written above it.
"""
from __future__ import annotations

from typing import AbstractSet


def read_set_unchanged(store, memo_revision: int, touched: AbstractSet[str]) -> bool:
    """True when no commit above `memo_revision` touched the read set.

    Fails closed: a store that cannot say what it wrote invalidates.
    """
    if memo_revision is None or not touched:
        return False
    if store.revision == memo_revision:
        return True
    reader = getattr(store, "_history_reader", None)
    written = getattr(reader, "cells_written_since", None)
    if written is None:
        return False
    try:
        rows = written(memo_revision)
    except Exception:
        return False
    for cell_id, link0, link1 in rows:
        if cell_id in touched or link0 in touched or link1 in touched:
            return False
    return True
