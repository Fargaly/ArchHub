"""Application defaults and reader links are projections, never open-time data."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

from nodelang import universal_application as app
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import CellStore, InvalidCell


ROOT = Path(__file__).resolve().parents[2]
PRE_SYSNODES = "7d6b008a1e4a26a67a33908b8782b378570baf39"
WORKSHOP = app._system_tool_canvas_root("tool_workshop")
DEFAULTS = {
    "stale_claim_after_idle_minutes": 30,
    "archive_after_idle_days": 20,
    "tick_cadence_minutes": 5,
}


def _keys():
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    return keys


def _state(store):
    snapshot = store.dense_snapshot()
    return snapshot.revision, dict(snapshot.cells)


def _workshop_rows(store, registry):
    canvas = app.project_universal_canvas(store, registry)
    node = next(node for node in canvas["nodes"] if node["id"] == WORKSHOP)
    return {row["label"]: row for row in node["params"]}


def test_defaults_and_reader_selection_never_materialize_graph_cells():
    store, registry = app.build_universal_application(resolve_map_path(), key_provider=_keys())
    try:
        for key in DEFAULTS:
            relation, value = app._workshop_board_property_root(WORKSHOP, key)
            assert relation not in store.snapshot().cells
            assert value not in store.snapshot().cells
        assert not any(root.startswith("app:relation:setting-reader:") for root in store.snapshot().cells)
        before = _state(store)
        for _ in range(2):
            rows = _workshop_rows(store, registry)
            assert {key: rows[key]["value"] for key in DEFAULTS} == DEFAULTS
            canvas = app.project_universal_canvas(store, registry)
            wire = next(wire for wire in canvas["wires"] if wire["id"].startswith("app:relation:setting-reader:"))
            app.apply_universal_canvas_gesture(
                store, registry, roots=[wire["id"]], focus_root=wire["id"],
                expected_scope=canvas["scope"]["current"],
            )
            selected = app.project_universal_canvas(store, registry)
            assert next(row for row in selected["wires"] if row["id"] == wire["id"])["selected"] is True
            assert _state(store) == before
    finally:
        store.close()


def test_first_properties_edit_is_the_only_write_and_reopens_same_cell(tmp_path):
    path = tmp_path / "settings.sqlite3"
    keys = _keys()
    store, registry = app.build_universal_application(resolve_map_path(), CellStore(path), key_provider=keys)
    key = "stale_claim_after_idle_minutes"
    relation, value_root = app._workshop_board_property_root(WORKSHOP, key)
    try:
        assert value_root not in store.snapshot().cells
        app.apply_universal_canvas_gesture(store, registry, roots=[WORKSHOP], focus_root=WORKSHOP)
        canvas = app.project_universal_canvas(store, registry)
        row = next(row for row in canvas["properties"] if row["label"] == key)
        assert row["relation"] == relation
        before = _state(store)
        for value in ("0", "1.5", "1441"):
            with pytest.raises(InvalidCell):
                app.edit_universal_property(store, registry, relation, value)
            assert _state(store) == before
        with pytest.raises(AuthorizationDenied):
            app.edit_universal_property(store, registry, relation, "17", authentication_context=object())
        assert _state(store) == before
        app.edit_universal_property(store, registry, relation, "30")
        assert _state(store) == before
        edited_root = app.edit_universal_property(store, registry, relation, "17")
        assert edited_root == value_root
        assert app._workshop_board_stale_claim_after_idle_minutes(store.snapshot(), registry) == 17
        assert _workshop_rows(store, registry)[key]["value_root"] == value_root
        assert _workshop_rows(store, registry)[key]["value"] == 17
        app.undo_universal_change(store, registry)
        assert app._workshop_board_stale_claim_after_idle_minutes(store.snapshot(), registry) == 30
        app.redo_universal_change(store, registry)
        assert app._workshop_board_stale_claim_after_idle_minutes(store.snapshot(), registry) == 17
        assert _workshop_rows(store, registry)[key]["value_root"] == value_root
        before_reopen = _state(store)
    finally:
        store.close()
    reopened, restored = app.restore_universal_application(resolve_map_path(), CellStore(path), key_provider=keys)
    try:
        assert _state(reopened) == before_reopen
        assert app._workshop_board_stale_claim_after_idle_minutes(reopened.snapshot(), restored) == 17
        row = _workshop_rows(reopened, restored)[key]
        assert row["value_root"] == value_root and row["value"] == 17
        assert not any(root.startswith("app:relation:setting-reader:") for root in reopened.snapshot().cells)
        assert _state(reopened) == before_reopen
    finally:
        reopened.close()


def test_selected_workshop_defaults_need_no_persisted_interaction_bindings():
    store, registry = app.build_universal_application(resolve_map_path(), key_provider=_keys())
    try:
        subject = registry.authorization.subject_root
        # Prime only the generic event/interaction vocabulary, as the application
        # already does; code-defined parameter rows must add no bindings to it.
        app.ensure_universal_property_interactions(store, registry, subject, {"properties": []})
        app.apply_universal_canvas_gesture(store, registry, roots=[WORKSHOP], focus_root=WORKSHOP)
        for value in (None, "17"):
            if value is not None:
                relation, _ = app._workshop_board_property_root(WORKSHOP, "stale_claim_after_idle_minutes")
                app.edit_universal_property(store, registry, relation, value)
            projection = app.project_universal_canvas(store, registry)
            assert {row["label"] for row in projection["properties"]} == set(DEFAULTS)
            before = _state(store)
            interactions, _, _ = app.ensure_universal_property_interactions(store, registry, subject, projection)
            assert not interactions
            assert _state(store) == before
    finally:
        store.close()


@pytest.fixture(scope="module")
def pre_sysnodes_graph(tmp_path_factory):
    """Write actual pre-SYSNODES bytes with that release's own source."""
    base = tmp_path_factory.mktemp("sysnodes2-old")
    state = base / "old.sqlite3"
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", PRE_SYSNODES, "nodelang"],
        capture_output=True, check=True, timeout=300,
    )
    with tempfile.TemporaryDirectory(prefix="old-source-", dir=base) as directory:
        source = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(source, filter="data")
        script = """
import sys
from pathlib import Path
from nodelang import universal_application as app
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import CellStore
keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
keys.add_key('archhub.local.court-attestation', b'c' * 32)
map_path = Path('01.APP/nodelang/data/public_runtime_map.json').resolve()
store, registry = app.build_universal_application(map_path, CellStore(sys.argv[1]), key_provider=keys)
store.close()
store, registry = app.restore_universal_application(map_path, CellStore(sys.argv[1]), key_provider=keys)
store.close()
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-c", script, str(state)], cwd=source, env=environment,
            capture_output=True, text=True, timeout=300,
        )
        assert completed.returncode == 0, completed.stderr[-4000:]
    return state


@pytest.mark.parametrize("lazy", [False, True])
def test_pre_sysnodes_first_open_is_read_only_before_any_user_setup(pre_sysnodes_graph, tmp_path, lazy):
    path = tmp_path / "old.sqlite3"
    shutil.copy2(pre_sysnodes_graph, path)
    store = CellStore(path)
    try:
        before = _state(store)
        store, registry = app.restore_universal_application(
            ROOT / "01.APP/nodelang/data/public_runtime_map.json", store, key_provider=_keys(), lazy=lazy,
        )
        assert _state(store) == before
        for _ in range(2):
            rows = _workshop_rows(store, registry)
            assert {key: rows[key]["value"] for key in DEFAULTS} == DEFAULTS
            assert _state(store) == before
    finally:
        store.close()
