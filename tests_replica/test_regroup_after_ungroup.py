"""Acceptance court: a pair grouped and ungrouped before groups again.

Found while profiling undo (2026-09-25, on 15e54ba): grouping a pair that
had been grouped and ungrouped before made the next ungroup refuse, "view
visibility differs from signed projection grants: 0 visible without a
grant [], 2 granted but not visible [...]". Group, ungroup, group again and
ungroup again each land; the canvas returns to the same drawing, reads
commit nothing, and the store reopens on it.
"""
from __future__ import annotations

import json

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    group_universal_selection,
    instantiate_universal_definition,
    project_universal_canvas,
    restore_universal_application,
    set_universal_selection,
    ungroup_universal_composition,
)
from nodelang.universal_cell import CellStore


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return provider


def _drawn(store, registry):
    revision = store.revision
    canvas = project_universal_canvas(store, registry)
    assert store.revision == revision, "a canvas read wrote the graph"
    return json.dumps(
        {
            "nodes": sorted(
                (node["id"], node["x"], node["y"]) for node in canvas["nodes"]
            ),
            "wires": sorted(wire["id"] for wire in canvas["wires"]),
        },
        sort_keys=True,
    )


def test_a_pair_grouped_and_ungrouped_before_groups_and_ungroups_again(
    tmp_path,
):
    path = tmp_path / "regroup.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        definitions = registry.standard_library.definition_roots
        pair = tuple(
            instantiate_universal_definition(
                store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
            )[0]
            for i in range(2)
        )
        apart = _drawn(store, registry)
        for cycle in range(3):
            set_universal_selection(store, registry, pair, focus_root=pair[-1])
            group, _ = group_universal_selection(
                store, registry, title="Again %d" % cycle
            )
            grouped = json.loads(_drawn(store, registry))
            assert group in {node[0] for node in grouped["nodes"]}, cycle
            assert not set(pair) & {node[0] for node in grouped["nodes"]}
            ungroup_universal_composition(store, registry, group)
            assert _drawn(store, registry) == apart, cycle
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert _drawn(store, registry) == apart
    finally:
        store.close()
