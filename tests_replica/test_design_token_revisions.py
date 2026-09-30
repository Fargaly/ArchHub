"""Design-token revisions open an OLD graph (G1, 717 decision (a)).

The design-token v1 cells are genesis: ensure/open refuse any cell that differs, so a
change to the design system is a revision (new cells only) resolved over v1, with the
active revision in one pointer cell. The 2026-08-05 lesson: a fresh fixture built by
the edited code cannot fail, so this court builds a durable graph with the PRE-CHANGE
code (HEAD 478da9b5, from ARCHHUB_OLD_CODE_DIR), copies it, and opens the COPY with
this code. It proves:
- the old graph opens with no drift;
- every v1 design-token cell is byte-identical afterwards;
- the revision applies once;
- the resolver returns caption 11 / label 12 and the card-category bindings;
- revert and reopen are correct;
- a second open changes nothing.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from nodelang.cell_design_tokens import (ACTIVE_REVISION_ROOT, REVISIONS, ensure_design_token_revisions,
                                         open_archhub_design_token_system, read_active_design_token_revision,
                                         revert_design_token_revision, set_active_design_token_revision)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import project_universal_canvas, restore_universal_application
from nodelang.universal_cell import CellStore

REVISION = REVISIONS[-1].name
BUILD_OLD = """
import sys
from pathlib import Path
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_cell import CellStore
keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
keys.add_key("archhub.local.court-attestation", b"c" * 32)
store, registry = build_universal_application(resolve_map_path(), CellStore(Path(sys.argv[1])), key_provider=keys)
store.close()
"""


def _keys():
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    return keys


def _design_cells(store):
    snapshot = store.snapshot()
    return {cell_id: snapshot.cells[cell_id] for cell_id in snapshot.cells
            if cell_id.startswith(("app:design-token", "app:presentation-component"))}


def _open(path):
    store = CellStore(path)
    return restore_universal_application(resolve_map_path(), store, key_provider=_keys())


def _resolved(store, registry):
    system = project_universal_canvas(store, registry)["configuration"]["design_system"]
    return system


@pytest.fixture(scope="module")
def old_graph(tmp_path_factory):
    old_code = os.environ.get("ARCHHUB_OLD_CODE_DIR", "")
    if not old_code or not (Path(old_code) / "nodelang" / "cell_design_tokens.py").is_file():
        pytest.skip("ARCHHUB_OLD_CODE_DIR must name an archive of the pre-change code (HEAD 478da9b5)")
    assert "ensure_design_token_revisions" not in (Path(old_code) / "nodelang" / "cell_design_tokens.py").read_text(
        encoding="utf-8"), "ARCHHUB_OLD_CODE_DIR must be the code from BEFORE the revision path"
    folder = tmp_path_factory.mktemp("old-graph")
    built = folder / "built-by-478da9b5.sqlite3"
    env = dict(os.environ, PYTHONPATH=old_code, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", BUILD_OLD, str(built)], cwd=old_code, env=env,
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-4000:]
    return built


@pytest.fixture
def copy(old_graph, tmp_path):
    target = tmp_path / "copy.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(old_graph) + suffix)
        if source.exists():
            shutil.copyfile(source, str(target) + suffix)
    return target


def test_the_old_graph_is_really_old_shaped(copy):
    store = CellStore(copy)
    try:
        snapshot = store.snapshot()
        assert ACTIVE_REVISION_ROOT not in snapshot.cells
        assert not any(cell_id.startswith("app:design-token-revision") for cell_id in snapshot.cells)
    finally:
        store.close()


def test_new_code_opens_the_old_graph_applies_the_revision_once_and_keeps_v1(copy):
    before = CellStore(copy)
    v1 = _design_cells(before)
    before.close()
    store, registry = _open(copy)
    try:
        after = _design_cells(store)
        assert {cell_id: after[cell_id] for cell_id in v1} == v1, "a v1 design-token cell changed"
        build = open_archhub_design_token_system(store.snapshot(), registry.presentation.theme_roots)
        assert read_active_design_token_revision(store.snapshot(), build).name == REVISION
        system = _resolved(store, registry)
        assert system["revision"] == REVISION
        assert system["tokens"]["typography.caption-size"]["value"] == "11px"
        assert system["tokens"]["typography.label-size"]["value"] == "12px"
        category = system["components"]["card-category"]
        assert len(category) == 10
        colours = [binding["value"] for binding in category.values()]
        assert len(set(colours)) == len(colours), category
        # A second ensure on the same graph commits nothing.
        revision = store.revision
        assert ensure_design_token_revisions(store, build) == REVISION
        assert store.revision == revision
    finally:
        store.close()
    del store, registry
    gc.collect()
    # A second open: nothing new, the same answer.
    store, registry = _open(copy)
    try:
        assert _design_cells(store) == after
        assert _resolved(store, registry)["tokens"]["typography.caption-size"]["value"] == "11px"
    finally:
        store.close()


def test_revert_survives_reopen_and_is_not_reapplied(copy):
    store, registry = _open(copy)
    build = open_archhub_design_token_system(store.snapshot(), registry.presentation.theme_roots)
    try:
        assert revert_design_token_revision(store, build) == ""
        system = _resolved(store, registry)
        assert system["revision"] == ""
        assert system["tokens"]["typography.caption-size"]["value"] == "9px"
        assert system["tokens"]["typography.label-size"]["value"] == "10px"
        assert "card-category" not in system["components"]
    finally:
        store.close()
    del store, registry
    gc.collect()
    store, registry = _open(copy)
    try:
        system = _resolved(store, registry)
        assert system["revision"] == "", "a reverted revision is never re-applied on open"
        assert system["tokens"]["typography.caption-size"]["value"] == "9px"
        build = open_archhub_design_token_system(store.snapshot(), registry.presentation.theme_roots)
        assert set_active_design_token_revision(store, build, REVISION) == REVISION
        assert _resolved(store, registry)["tokens"]["typography.caption-size"]["value"] == "11px"
    finally:
        store.close()


def test_a_revision_cell_that_drifted_is_refused_like_v1(copy):
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    store, registry = _open(copy)
    build = open_archhub_design_token_system(store.snapshot(), registry.presentation.theme_roots)
    try:
        value_root = "app:design-token-revision:%s:override:font.caption-size:value" % REVISION
        store.commit(store.revision, replace=(Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, b"30px"),))
        with pytest.raises(Exception, match="design-token revision drifted"):
            ensure_design_token_revisions(store, build)
    finally:
        store.close()
