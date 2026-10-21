"""What a boot may NOT do: stream or count the founder's entire head.

His head is 3.9M rows. Any line that materialises all of it, or counts all
of it, is paid on every launch -- and the boot performs dozens of protocol
projections, so one such line inside one of them is not one scan.

Measured on his machine, boot-profile.log 2026-09-07, a 148s boot:

    18.7%  universal_cell.py:count      <- len(snapshot.cells), 4x per boot
    15.7%  universal_cell.py:stream_ids <- frozenset(snapshot.cells)

cell_registry_projection.py learned this on 2026-09-05 and wrote the rule
down. These two sites predate the lesson. This file is the lesson made
enforceable, and it also courts the ABSENCE the counting was standing in
for: CellStore offers no way to delete, so a migration cannot lose a Cell
and does not need to count to prove it.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from nodelang.universal_cell import CellStore
from nodelang import universal_application, universal_map_import


ROOT = Path(__file__).resolve().parents[1]


def _code(text: str) -> str:
    """The source with comments stripped.

    The rule is about what the boot RUNS. A comment naming the forbidden
    call -- and the fixes here deliberately name it, so the next reader
    knows what was removed and why -- is not a scan.
    """
    return chr(10).join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_store_offers_no_way_to_delete_a_cell():
    """The invariant the four counts were buying, for free."""
    parameters = inspect.signature(CellStore.commit).parameters

    assert set(parameters) - {"self"} == {
        "expected_revision", "create", "replace", "precommit_guard"
    }
    assert not [
        name for name in dir(CellStore)
        if not name.startswith("_")
        and ("delete" in name.lower() or "remove" in name.lower())
    ]


def test_the_canvas_migrations_no_longer_count_the_whole_head():
    source = _code(inspect.getsource(
        universal_application._ensure_canvas_domain_interfaces
    ) + inspect.getsource(
        universal_application._ensure_canvas_domain_public_interfaces
    ))

    assert "len(snapshot.cells)" not in source
    assert "len(store.snapshot().cells)" not in source


def test_the_grand_map_import_never_materialises_every_id():
    source = _code(
        Path(universal_map_import.__file__).read_text(encoding="utf-8")
    )

    assert "frozenset(snapshot.cells)" not in source
    assert "set(snapshot.cells)" not in source
    assert "list(snapshot.cells)" not in source


def test_no_boot_path_module_materialises_the_head():
    """The rule, applied to every module the boot actually runs through."""
    offenders = []
    for name in (
        "universal_application.py",
        "universal_map_import.py",
        "cell_registry_projection.py",
        "cell_protocols.py",
    ):
        text = _code(
            (ROOT / "nodelang" / name).read_text(encoding="utf-8")
        )
        for marker in (
            "frozenset(snapshot.cells)",
            "set(snapshot.cells)",
            "list(snapshot.cells)",
            "sorted(snapshot.cells)",
        ):
            if marker in text:
                offenders.append("%s: %s" % (name, marker))

    assert offenders == []


def test_membership_is_still_proven_just_by_point_read():
    """Cheaper must not mean weaker: the checks still refuse a missing root."""
    source = Path(universal_map_import.__file__).read_text(encoding="utf-8")

    assert "root not in snapshot.cells" in source
    assert "persisted Grand Map role vocabulary is incomplete" in source
    assert "Grand Map property references missing Cells" in source
