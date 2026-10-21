"""BIGMIGRATE2: real SQLite blobs, copy fidelity, progress and measured baseline."""
import ast
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess

import pytest

from nodelang import persistence


@pytest.fixture(scope="module")
def frozen_digest():
    # Execute precisely the named baseline's function, with current unchanged
    # reader/advance globals. No second production digest implementation.
    source = subprocess.check_output(
        ["git", "show", "624300f2:nodelang/persistence.py"], text=True, encoding="utf-8",
        cwd=Path(__file__).resolve().parents[2])
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_sqlite_source_digest")
    namespace = dict(vars(persistence))
    exec(compile(ast.Module(body=[function], type_ignores=[]), "624300f2:persistence.py", "exec"), namespace)
    return namespace["_sqlite_source_digest"]


@pytest.mark.parametrize("kind", ["graph", "truth"])
def test_released_marker_digest_remains_idempotent_and_detects_changes(
        tmp_path, monkeypatch, frozen_digest, kind):
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    from tests_replica.test_stage2b_one_source import _history

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    source = tmp_path / "retired.sqlite3"
    if kind == "graph":
        with CellStore(source) as old:
            old.commit(old.revision, create=(Cell("test:old", NULL_CELL_ID, NULL_CELL_ID, b"work"),))
    else:
        _history(source)
    original = persistence._sqlite_legacy_source_digest
    assert original(source) == frozen_digest(source)
    with CellStore(tmp_path / "authority.sqlite3") as owner:
        def migrate():
            return (persistence.migrate_graph_source(owner, source) if kind == "graph" else
                    persistence.migrate_local_truths(owner, history_path=source))

        # Create the marker using the actual released function, then replay it
        # through the current reader; a format change must not strand old work.
        monkeypatch.setattr(persistence, "_sqlite_legacy_source_digest", frozen_digest)
        assert migrate()["state"] == "migrated"
        monkeypatch.setattr(persistence, "_sqlite_legacy_source_digest", original)
        revision = owner.revision
        assert migrate()["state"] == "already_migrated"
        assert owner.revision == revision
        if kind == "graph":
            with CellStore(source) as old:
                old.commit(old.revision, create=(Cell("test:changed", NULL_CELL_ID, NULL_CELL_ID, b"changed"),))
        else:
            with closing(sqlite3.connect(source)) as database:
                database.execute("PRAGMA user_version=42")
                database.commit()
        with pytest.raises(ValueError, match="changed"):
            migrate()
