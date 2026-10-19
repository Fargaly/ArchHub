"""Independent 717 upgrade court: newest committed history, never file size.

Frozen before the implementation. Run only through the lane's BelowNormal rig.
All paths and signing keys belong to fixtures; no desktop or live profile opens.
"""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import uuid

import pytest

from nodelang import persistence
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    local = tmp_path / "LOCALAPPDATA"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "APPDATA"))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(local / "ArchHub"))
    monkeypatch.delenv("ARCHHUB_LEGACY_STATE_DIR", raising=False)
    from nodelang import backup_retention
    monkeypatch.setattr(backup_retention, "backup_policy", lambda *_: {
        "keep_count": 3, "max_bytes": 10 * 1024**3})
    return local


def _journal(path, label, timestamp, commits=1, *, trace_history=False):
    import nodelang.universal_cell as kernel
    path.parent.mkdir(parents=True, exist_ok=True)
    # Set the commit clock at creation; journal triggers remain fully enabled.
    # Replacing this module binding avoids changing other products' clocks.
    with pytest.MonkeyPatch.context() as clock:
        clock.setattr(kernel, "time", SimpleNamespace(time=lambda: timestamp))
        with CellStore(path) as store:
            store.commit(store.revision, create=(
                Cell("app:archhub", NULL_CELL_ID, NULL_CELL_ID, label.encode()),))
            for index in range(commits):
                store.commit(store.revision, create=(Cell(
                    ("app:agent-session:fixture:chain:" if trace_history and index else "work:") + str(index), NULL_CELL_ID, NULL_CELL_ID,
                    (label + ":" + str(index)).encode()),))
    return path


def _selected(root, label="stale", timestamp=100, commits=1, *, trace_history=False):
    ident = str(uuid.uuid4())
    folder = root / "unified-authority" / "generations" / ident
    database = _journal(folder / "authority.sqlite3", label, timestamp, commits, trace_history=trace_history)
    (folder / "bootstrap.json").write_text(json.dumps({"graph_id": ident}), encoding="utf-8")
    (root / "unified-authority" / "CURRENT").write_text(ident, encoding="ascii")
    return database


def _bytes(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for source in paths for path in source.parent.glob(source.name + "*")
            if path.is_file() and not path.name.endswith(".owner.lock")}


def _closed_backup(source):
    # Runtime import avoids the shared synthetic-fixture module's import cycle.
    from tests_replica.test_adopt import closed_backup
    return closed_backup(source.parent, source, include_content_when_absent=False)


def _preserved_paths(paths, original, backup):
    # The adopted inode is the writable live owner; the installer rollback copy
    # retains its original closed bytes. Disposable accelerators may refresh.
    return (*(path for path in paths if path != original), *backup.iterdir())


def _history(path):
    # Every fixture is checkpointed and closed before observation. Immutable
    # avoids SQLite creating -wal/-shm while inspecting the original bytes.
    assert not Path(str(path) + "-wal").exists() or Path(str(path) + "-wal").stat().st_size == 0
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
        return {table: database.execute("SELECT * FROM " + table + " ORDER BY " + order).fetchall()
                for table, order in (("revisions", "revision"),
                    ("cell_versions", "revision,cell_id"), ("current_cells", "cell_id"))}


def _prepare(root, **kwargs):
    prepare = getattr(persistence, "prepare_application_database", None)
    # The old launcher has no preparation step; its actual behavior is to open
    # CURRENT directly. RED must name wrong history, rather than a missing API.
    result = (prepare(root, persistence.application_database_path(root), **kwargs)
              if prepare is not None else {})
    selected = persistence.application_database_path(root)
    # The launcher must consume the same post-migration locator as every reader.
    assert Path(result.get("database_path", selected)).resolve() == selected
    return selected


@pytest.mark.parametrize("winner,stale_commits,legacy_time,root_time", [
    ("legacy", 9, 200, 150),
    ("root", 1, 150, 200),
    ("selected", 1, 50, 75),
])
def test_all_declared_candidates_choose_newest_committed_time(
        isolated_profile, winner, stale_commits, legacy_time, root_time):
    local = isolated_profile
    root = local / "ArchHub"
    stale = _selected(root, commits=stale_commits, trace_history=True)
    legacy = _journal(local / "ArchHub-Test" / "archhub-test.universal.sqlite3", "legacy", legacy_time)
    direct = _journal(root / "authority.sqlite3", "root", root_time)
    sources = {"selected": stale, "legacy": legacy, "root": direct}
    backup = _closed_backup(sources[winner])
    preserved = _preserved_paths(sources.values(), sources[winner], backup)
    before = _bytes(preserved)
    physical = sources[winner].stat().st_dev, sources[winner].stat().st_ino
    expected = _history(sources[winner])
    selected = _prepare(root)
    assert _history(selected) == expected
    assert _bytes(preserved) == before
    assert (selected.stat().st_dev, selected.stat().st_ino) == physical
    if winner == "selected":
        assert selected == stale.resolve()
    else:
        assert selected == sources[winner].resolve()
        generation = root / "unified-authority/generations" / (root / "unified-authority/CURRENT").read_text().strip()
        migration = json.loads((generation / "migration.json").read_text())
        assert migration["generation_id"] == generation.name
        assert (root / migration["journal_relative_path"]).resolve() == selected


def test_equal_committed_time_uses_revision_not_file_mtime(isolated_profile):
    local = isolated_profile
    root = local / "ArchHub"
    stale = _selected(root, timestamp=100, commits=1)
    legacy = _journal(local / "ArchHub-Test" / "archhub-test.universal.sqlite3", "legacy", 100, commits=4)
    backup = _closed_backup(legacy)
    preserved = _preserved_paths((stale, legacy), legacy, backup)
    before = _bytes(preserved)
    expected = _history(legacy)
    selected = _prepare(root)
    assert _history(selected) == expected
    assert _bytes(preserved) == before


def test_committed_wal_and_shared_memory_bytes_stay_untouched(isolated_profile):
    local = isolated_profile
    root = local / "ArchHub"
    stale = _selected(root)
    legacy = _journal(local / "ArchHub-Test" / "archhub-test.universal.sqlite3", "legacy", 200)
    first = _history(legacy)["revisions"][-1][0]
    # Keep the SQLite writer handle open without a CellStore ownership fence,
    # matching the existing WAL adoption court. No writer runs during migration.
    with closing(sqlite3.connect(legacy, isolation_level=None)) as journal:
        journal.execute("PRAGMA journal_mode=WAL")
        journal.execute("PRAGMA wal_autocheckpoint=0")
        journal.execute("BEGIN IMMEDIATE")
        journal.execute("INSERT INTO revisions(revision,committed_at) VALUES(?,?)", (first + 1, 300))
        journal.execute("INSERT INTO cell_versions(revision,cell_id,link0,link1,atom) VALUES(?,?,?,?,?)",
            (first + 1, "work:wal", NULL_CELL_ID, NULL_CELL_ID, b"committed only in WAL"))
        journal.execute("INSERT INTO current_cells(cell_id,revision,link0,link1,atom) VALUES(?,?,?,?,?)",
            ("work:wal", first + 1, NULL_CELL_ID, NULL_CELL_ID, b"committed only in WAL"))
        journal.execute("COMMIT")
        assert Path(str(legacy) + "-wal").stat().st_size > 0
        before = _bytes((stale, legacy))
        # A committed hot WAL opens in place; the boot snapshot preserves its
        # committed edit and the previous selection remains byte-identical.
        result = persistence.prepare_application_database(root, stale)
        assert persistence.application_database_path(root) == legacy
        assert _bytes((stale,))[str(stale)] == before[str(stale)]
        with CellStore(legacy) as reopened:
            assert reopened.read('work:wal').atom == b'committed only in WAL'
        assert result['backup_path']
    # Installer close/checkpoint establishes the independently restorable file;
    # adoption must retain the exact committed history, including its WAL edit.
    backup = _closed_backup(legacy)
    preserved = _preserved_paths((stale, legacy), legacy, backup)
    before = _bytes(preserved)
    chosen = _prepare(root)
    assert _bytes(preserved) == before
    adopted = _history(chosen)
    assert adopted["revisions"][-1] == (first + 1, 300)
    assert ("work:wal", first + 1, NULL_CELL_ID, NULL_CELL_ID,
            b"committed only in WAL") in adopted["current_cells"]


def test_candidate_head_observation_honors_migration_deadline(isolated_profile, monkeypatch):
    root = isolated_profile / "ArchHub"
    stale = _selected(root)
    current = root / "unified-authority" / "CURRENT"
    pointer, before = current.read_bytes(), _bytes((stale,))
    clock = {"now": 0.0}
    monkeypatch.setattr(persistence, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    original = persistence._application_journal_reader

    @contextmanager
    def slow_observation(path, **kwargs):
        clock["now"] = 2.0
        # A source view crossing its deadline must abort before any publication,
        # including when CURRENT itself would otherwise win and return early.
        kwargs.get("check_budget", lambda: None)()
        with original(path, **kwargs) as reader:
            yield reader

    monkeypatch.setattr(persistence, "_application_journal_reader", slow_observation)
    with pytest.raises(TimeoutError, match="application journal migration time budget exceeded"):
        persistence.prepare_application_database(root, stale, timeout_seconds=1.0)
    assert current.read_bytes() == pointer
    assert _bytes((stale,)) == before
    assert not (root / "backups").exists()


def test_legacy_conversation_import_preserves_all_original_file_bytes(isolated_profile):
    from tests_replica.test_stage2b_one_source import _history as make_history

    root = isolated_profile / "ArchHub"
    root.mkdir()
    history = root / "archhub-test.universal.sqlite3.conversations.sqlite3"
    make_history(history)
    with closing(sqlite3.connect(history.as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
        tables = [row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        expected = {name: sorted(source.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                    for name in tables}
    before = _bytes((history,))
    graph = root / "authority.sqlite3"
    with CellStore(graph) as owner:
        result = persistence.migrate_local_truths(owner, history_path=history)
        assert result["state"] == "migrated"
        assert Path(result["backup_path"]).is_dir()
        assert _bytes((history,)) == before
        revision = owner.revision
        assert persistence.migrate_local_truths(owner, history_path=history)["state"] == "already_migrated"
        assert owner.revision == revision
    assert _bytes((history,)) == before
    with closing(sqlite3.connect(graph.as_uri() + "?mode=ro&immutable=1", uri=True)) as adopted:
        for name in tables:
            assert sorted(adopted.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr) == expected[name]


def test_real_application_receipts_survive_new_generation_and_server_reopen(isolated_profile, tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_application import _verify_application_agent_receipts
    from tests_replica.test_unified_authority_runtime import _provision

    local = isolated_profile
    root = local / "ArchHub"
    # Unlike the compact ranking fixtures, this CURRENT is a real signed authority.
    selected_owner = _provision(root / "unified-authority")
    stale = Path(selected_owner.database_path)
    selected_owner.authority.store.close()
    manifest = stale.parent / "bootstrap.json"
    manifest_before = manifest.read_bytes()
    legacy = local / "ArchHub-Test" / "archhub-test.universal.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    kwargs = dict(universal_key_provider=keys, universal_workspace_root=tmp_path,
                  enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server = ApplicationServer(universal_state_path=legacy, **kwargs)
    try:
        evidence = _verify_application_agent_receipts(server.universal_store,
            server.universal_registry.authorization, server.universal_registry.agent_body)
        assert evidence
        revision = server.universal_store.revision
    finally:
        server.close()
    backup = _closed_backup(legacy)
    preserved = (stale, *(backup / name for name in (legacy.name, legacy.name + ".conversations.sqlite3")))
    before = _bytes(preserved)
    expected = _history(legacy)
    assert expected["revisions"][-1][0] == revision
    chosen = _prepare(root, key_provider=keys)
    assert chosen != stale and chosen == legacy
    generation = root / "unified-authority/generations" / (root / "unified-authority/CURRENT").read_text().strip()
    migrated = _history(chosen)
    for table in ("revisions", "cell_versions"):
        assert [row for row in migrated[table] if row[0] <= revision] == expected[table]
    original_ids = {row[0] for row in expected["current_cells"]}
    assert [row for row in migrated["current_cells"] if row[0] in original_ids] == expected["current_cells"]
    # Boot adopts the physical journal; the existing idle owner anchors its
    # signed authority after archival. Emulate that phase on this small fixture.
    with CellStore(chosen) as background_store:
        persistence.finalize_application_adoption(background_store, keys)
    assert (generation / "adoption.json").is_file()
    assert _bytes(preserved) == before
    assert manifest.read_bytes() == manifest_before
    # The adopted legacy journal must not impersonate the old unified graph identity.
    assert not (generation / "bootstrap.json").exists()
    assert (generation / "migration.json").is_file()
    reopened = ApplicationServer(universal_state_path=chosen, **kwargs)
    try:
        assert reopened.universal_store._signed_commit_authority.store is reopened.universal_store
        assert _verify_application_agent_receipts(reopened.universal_store,
            reopened.universal_registry.authorization, reopened.universal_registry.agent_body) == evidence
    finally:
        reopened.close()
    for table in ("revisions", "cell_versions"):
        after = _history(chosen)[table]
        assert [row for row in after if row[0] <= revision] == expected[table]
    assert _bytes(preserved) == before
    assert manifest.read_bytes() == manifest_before

    # An unchanged accepted snapshot cannot cover a changed retained-history
    # prefix. Reopening must consult the prefix independently of that snapshot.
    from nodelang.unified_authority import BootstrapManifest, open_unified_authority
    from nodelang.universal_cell import InvalidCell
    adopted_manifest = BootstrapManifest.from_json(
        (generation / "adoption.json").read_text(encoding="utf-8"))
    with CellStore(chosen) as check:
        original_digest = check.revision_chain_digest
        source_revision = adopted_manifest.accepted_revision

        def mismatched_prefix(revision=None):
            return "0" * 64 if revision == source_revision else original_digest(revision)

        monkeypatch.setattr(check, "revision_chain_digest", mismatched_prefix)
        with pytest.raises(InvalidCell, match="adoption history hash mismatch"):
            open_unified_authority(check, adopted_manifest, keys)
        assert getattr(check, "_signed_commit_authority", None) is None

def test_migrated_selected_profile_binds_signed_owner_for_coordination(isolated_profile, tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang import clean_coordination_service, desktop
    from tests_replica.test_unified_authority_runtime import _provision

    root = isolated_profile / "ArchHub"
    selected_owner = _provision(root / "unified-authority")
    stale = Path(selected_owner.database_path)
    selected_owner.authority.store.close()
    legacy = isolated_profile / "ArchHub-Test" / "archhub-test.universal.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    kwargs = dict(universal_key_provider=keys, universal_workspace_root=tmp_path,
                  enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    original = ApplicationServer(universal_state_path=legacy, **kwargs)
    original.close()
    backup = _closed_backup(legacy)
    preserved = (stale, *(backup / name for name in (legacy.name, legacy.name + ".conversations.sqlite3")))
    before = _bytes(preserved)
    chosen = _prepare(root, key_provider=keys)
    assert chosen != stale and chosen == legacy
    assert persistence.selected_application_generation(chosen)
    # Signed coordination is the post-archival background phase, never boot's
    # full-graph adoption work. Preserve the same actual signed-owner court.
    with CellStore(chosen) as background_store:
        persistence.finalize_application_adoption(background_store, keys)
    reopened = ApplicationServer(universal_state_path=chosen, **kwargs)
    try:
        authority = getattr(reopened.universal_store, "_signed_commit_authority", None)
        assert authority is not None, "migrated selected profile has no bound signed commit owner; coordination cannot attach"
        assert authority.store is reopened.universal_store
        # Only the physical socket service is replaced. Authority binding,
        # coordination graph host and catalogue installation remain real.
        services = []

        def no_socket_service(host, **_kwargs):
            service = SimpleNamespace(serve_forever=lambda: None,
                shutdown=lambda: None, server_close=lambda: None, graph_host=host)
            services.append(service)
            return service

        monkeypatch.setattr(clean_coordination_service, "build_bound_service", no_socket_service)
        assert desktop.bind_coordination_surface(reopened, root) is services[0]
        assert reopened._coordination_surface is services[0]
        reopened._coordination_thread.join(timeout=1)
        assert not reopened._coordination_thread.is_alive()
    finally:
        reopened.close()
    assert _bytes(preserved) == before

@pytest.mark.parametrize("invalid", ("receipts", "history"))
def test_adoption_refuses_invalid_receipts_or_history_without_writes(
        isolated_profile, tmp_path, invalid):
    from nodelang import authority_adoption
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_identity import RelationshipAuthorityDenied
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.universal_cell import InvalidCell

    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    database = isolated_profile / "legacy" / "authority.sqlite3"
    server = ApplicationServer(universal_state_path=database,
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    receipt_root = server.universal_registry.agent_body.body.creation_receipt_root
    server.close()
    with CellStore(database) as store:
        if invalid == "receipts":
            # A real persisted receipt has been replaced by an invalid relation.
            # The expected chain below includes the tamper, so only receipt
            # validation (not stale expected history) can reject this case.
            store.commit(store.revision, replace=(
                Cell(receipt_root, NULL_CELL_ID, NULL_CELL_ID, b"invalid receipt"),))
        before_revision = store.revision
        before_cells = dict(store.snapshot().cells)
        before_history = store.snapshot_transition().chain_digest
        expected = "0" * 64 if invalid == "history" else before_history
        with pytest.raises((InvalidCell, RelationshipAuthorityDenied),
                match="(?i)(adoption|receipt|history).*(invalid|mismatch|match|changed|missing)"):
            authority_adoption.adopt_application_authority(
                store, keys, source_history_digest=expected)
        assert store.revision == before_revision
        assert dict(store.snapshot().cells) == before_cells
        assert store.snapshot_transition().chain_digest == before_history
        assert getattr(store, "_signed_commit_authority", None) is None
    assert not (database.parent / "adoption.json").exists()
