"""The aggregate store inspector cannot mutate or disclose fixture content."""
import hashlib
import json
import sqlite3

from tools.measure_store import measure


def test_store_inspection_is_readonly_and_aggregate_only(tmp_path, capsys):
    path = tmp_path / "shape.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE revisions(revision INTEGER PRIMARY KEY, committed_at REAL NOT NULL)")
        db.execute("CREATE TABLE cell_versions(revision INTEGER NOT NULL, cell_id TEXT NOT NULL, link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL, PRIMARY KEY(revision,cell_id))")
        db.execute("CREATE TABLE current_cells(cell_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL)")
        db.execute("INSERT INTO revisions VALUES(1,0)")
        db.execute("INSERT INTO cell_versions VALUES(1,'app:fixture:value','00000000-0000-0000-0000-000000000000','00000000-0000-0000-0000-000000000000',?)", (b"private-content-sentinel",))
        db.execute("INSERT INTO current_cells SELECT cell_id,revision,link0,link1,atom FROM cell_versions")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = measure(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert result["tables"]["current_cells"]["rows"] == 1
    assert result["current_structure"]["atom_bytes"] == len(b"private-content-sentinel")
    assert result["history"]["superseded_rows"] == 0
    assert result["current_id_categories"][0]["family"] == "app:fixture"
    assert result["current_id_categories"][0]["cells"] == 1
    assert result["current_id_categories"][0]["logical_column_bytes"] == result["tables"]["current_cells"]["logical_column_bytes"]
    assert "private-content-sentinel" not in json.dumps(result) + capsys.readouterr().out
    assert not list(tmp_path.glob("*-journal"))


def test_nonexistent_store_inspection_cannot_create_database(tmp_path):
    import pytest
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        measure(missing)
    assert not missing.exists()


def test_measurement_output_cannot_overwrite_input_or_sidecars(tmp_path):
    import pytest
    from tools.measure_store import validate_output
    store = tmp_path / "source.sqlite3"
    for suffix in ("", "-wal", "-shm", ".accelerators", ".conversations.sqlite3"):
        with pytest.raises(ValueError):
            validate_output([store], tmp_path / (store.name + suffix))
    validate_output([store], tmp_path / "shape.json")


def test_large_store_semantic_fixture_is_deterministic(tmp_path):
    from contextlib import ExitStack
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from tools.seed_large_store import seed_large_store
    with ExitStack() as fixtures:
        paths = [Path(fixtures.enter_context(TemporaryDirectory(prefix="ArchHub-lazyboot-deterministic-"))) for _ in range(2)]
        results = [seed_large_store(path, target_gb=0.001) for path in paths]
        digests = []
        for result in results:
            digest = hashlib.sha256()
            db = sqlite3.connect(result["path"].resolve().as_uri() + "?mode=ro", uri=True)
            try:
                for table, order in (("revisions", "revision"), ("cell_versions", "revision,cell_id"), ("current_cells", "cell_id")):
                    for row in db.execute("SELECT * FROM " + table + " ORDER BY " + order):
                        digest.update(repr(row).encode("utf-8"))
                digests.append(digest.hexdigest())
            finally:
                db.close()
        if digests[0] != digests[1]:
            from itertools import zip_longest
            left = sqlite3.connect(results[0]["path"].resolve().as_uri() + "?mode=ro", uri=True)
            right = sqlite3.connect(results[1]["path"].resolve().as_uri() + "?mode=ro", uri=True)
            try:
                for table, order in (("revisions", "revision"), ("cell_versions", "revision,cell_id"), ("current_cells", "cell_id")):
                    differences = 0
                    for first, second in zip_longest(left.execute("SELECT * FROM " + table + " ORDER BY " + order), right.execute("SELECT * FROM " + table + " ORDER BY " + order)):
                        if first != second:
                            print("determinism differing table", table, "row identity", first[:2] if first else None,
                                  "changed columns", [index for index, pair in enumerate(zip(first or (), second or ())) if pair[0] != pair[1]])
                            if table == "revisions":
                                print("revision scalar values", first, second)
                            elif first and second and first[-1] != second[-1]:
                                print("atom lengths", len(first[-1]), len(second[-1]))
                            differences += 1
                            if differences == 5:
                                break
            finally:
                left.close()
                right.close()
        assert digests[0] == digests[1]
        print("deterministic fixture semantic SHA256:", digests[0])


def test_source_relation_workload_is_readonly_not_boot_admission(tmp_path):
    from tools.measure_restore_workload import measure_workload
    from nodelang.cell_protocols import compose_relation_cells
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    path = tmp_path / "discovery.sqlite3"
    store = CellStore(path)
    role = Cell("gm:role:member", NULL_CELL_ID, NULL_CELL_ID, b"member")
    value = Cell("fixture:payload", NULL_CELL_ID, NULL_CELL_ID, b"synthetic")
    relations = (
        compose_relation_cells(((role.id, value.id),), relation_id="fixture:ledger"),
        compose_relation_cells(((role.id, "fixture:ledger"),), relation_id="app:archhub"),
        compose_relation_cells(((role.id, value.id),), relation_id="app:canvas"),
        compose_relation_cells((), relation_id="gm:domain:brain"),
    )
    store.commit(store.snapshot().revision, create=(role, value, *(cell for relation in relations for cell in relation.cells)))
    store.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = measure_workload(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "subset" in result["scope"]
    assert result["stages"]["restore_original_session_candidate_probe"]["valid_relations"] == 1
    assert result["stages"]["lazy_namespaced_view_candidate_subset"]["relation_attempts"] == 0
    assert result["physical_rows_read_including_refetch"] > 0


def test_physical_allocation_reader_is_readonly_when_optional_apsw_supplied(tmp_path):
    import os
    from pathlib import Path
    import pytest
    from tools.measure_store_allocations import measure_allocations
    dependency = os.environ.get("LAZYBOOT_APSW_PATH")
    if not dependency:
        pytest.skip("optional DBSTAT measurement dependency not supplied")
    path = tmp_path / "allocations.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE fixture(id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        db.execute("INSERT INTO fixture VALUES('fixture',?)", (b"private-content-sentinel",))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = measure_allocations(path, Path(dependency))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert result["allocations"]["fixture"]["allocated_bytes"] > 0
    assert result["index_allocated_bytes"] > 0
    assert result["btree_allocated_bytes"] + result["freelist_bytes"] + result["non_btree_non_free_bytes"] == result["snapshot_allocated_file_bytes"]
    assert "private-content-sentinel" not in json.dumps(result)
