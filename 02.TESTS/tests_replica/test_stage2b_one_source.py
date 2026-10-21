"""Reviewer-owned STAGE2B courts: isolated stores and mocked 01.APP/desktop/cloud only."""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import runpy
import sqlite3

import pytest

from nodelang import backup_retention, cloud_session, persistence
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_cell import CellStore


ROOT = Path(__file__).resolve().parents[2]


def _backup(parent, name, stamp, size=8):
    path = parent / name
    path.mkdir()
    (path / "authority.sqlite3").write_bytes(b"x" * size)
    os.utime(path, (stamp, stamp))
    return path


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _history(path):
    with ConversationHistoryStore(path, instance_id="fixture-account") as history:
        history.ensure_conversation("workshop")
        history.initialize_retention()
        history.append("workshop", author="account:alice", content="preserve me",
                       recipients=("account:bob",), idempotency_key="original-message",
                       message_id="message:1", created_at="2026-10-16T08:00:00Z")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO message_tombstones VALUES(?,?,?,?)",
                           ("workshop", 2, "a" * 64, "b" * 64))


def _table_state(path):
    with closing(sqlite3.connect(path)) as connection:
        tables = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return {name: (sql, sorted(connection.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr))
                for name, sql in tables}


def test_retention_counts_same_day_and_undated_backups(tmp_path):
    paths = [_backup(tmp_path, name, number) for number, name in enumerate(
        ("20261016-a", "20261016-b", "undated-old", "undated-new", "20261016-verified"), 1)]
    unrelated = tmp_path / "README.txt"
    unrelated.write_text("leave alone", encoding="utf-8")
    result = backup_retention.prune_backups(
        tmp_path, keep=paths[-1], keep_count=3, max_bytes=1000)
    assert {p.name for p in paths if p.exists()} == {p.name for p in paths[-3:]}
    assert len(result["removed"]) == 2
    assert result["retained_bytes"] == 24
    assert result["budget_exceeded"] is False
    assert unrelated.read_text(encoding="utf-8") == "leave alone"


def test_retention_enforces_bytes_and_protects_verified_and_named(tmp_path):
    protected = _backup(tmp_path, "20261014-protected", 1, 20)
    obsolete = _backup(tmp_path, "20261015-obsolete", 2, 20)
    verified = _backup(tmp_path, "20261016-verified", 3, 20)
    result = backup_retention.prune_backups(
        tmp_path, keep=verified, keep_count=3, max_bytes=25,
        protected_names=(protected.name,))
    assert protected.exists() and verified.exists()
    assert not obsolete.exists()
    assert result["retained_bytes"] == 40
    assert result["budget_exceeded"] is True


def test_retention_removes_recent_backups_until_within_budget(tmp_path):
    paths = [_backup(tmp_path, "backup-%s" % index, index, 10) for index in range(4)]
    result = backup_retention.prune_backups(
        tmp_path, keep=paths[-1], keep_count=3, max_bytes=15)
    assert [p for p in paths if p.exists()] == paths[-1:]
    assert result["retained_bytes"] <= 15
    assert result["budget_exceeded"] is False


def test_retention_never_traverses_a_symlink(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_bytes(b"keep")
    link = backups / "20200101-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation to this test account")
    verified = _backup(backups, "20261016-current", 100)
    backup_retention.prune_backups(backups, keep=verified, keep_count=1, max_bytes=8)
    assert link.is_symlink()
    assert (outside / "precious").read_bytes() == b"keep"


def test_truth_migration_is_complete_backed_up_idempotent_and_source_preserving(tmp_path):
    legacy = tmp_path / "legacy.conversations.sqlite3"
    settings = tmp_path / "settings.json"
    graph = tmp_path / "authority.sqlite3"
    _history(legacy)
    expected_settings = {"theme": "dark", "backup_count": 3, "nested": {"enabled": True}}
    settings.write_text(json.dumps(expected_settings), encoding="utf-8")
    originals = (_digest(legacy), _digest(settings))
    source_tables = _table_state(legacy)
    with CellStore(graph) as store:
        result = persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert result["state"] == "migrated"
        assert Path(result["backup_path"]).exists()
        snapshot = store.snapshot()
        assert "app:local-truth-migration" in snapshot.cells
        assert json.loads(snapshot.cells["app:imported-settings"].atom) == expected_settings
        revision = store.revision
        again = persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert again["state"] == "already_migrated"
        assert store.revision == revision
    target_tables = _table_state(graph)
    for name, (schema, rows) in source_tables.items():
        assert name in target_tables, "lost history table: " + name
        assert target_tables[name] == (schema, rows), "history/schema changed: " + name
    assert originals == (_digest(legacy), _digest(settings))
    with CellStore(graph) as reopened:
        assert json.loads(reopened.snapshot().cells["app:imported-settings"].atom) == expected_settings


def test_completed_migration_refuses_changed_source_without_graph_effect(tmp_path):
    legacy, settings = tmp_path / "history.sqlite3", tmp_path / "settings.json"
    _history(legacy)
    settings.write_text('{"theme":"dark"}', encoding="utf-8")
    with CellStore(tmp_path / "authority.sqlite3") as store:
        persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        revision = store.revision
        settings.write_text('{"theme":"light"}', encoding="utf-8")
        with pytest.raises((ValueError, OSError)):
            persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert store.revision == revision


def test_invalid_settings_or_failed_backup_has_no_migration_effect(tmp_path, monkeypatch):
    legacy, settings = tmp_path / "history.sqlite3", tmp_path / "settings.json"
    _history(legacy)
    settings.write_text("invalid JSON", encoding="utf-8")
    with CellStore(tmp_path / "authority.sqlite3") as store:
        revision = store.revision
        with pytest.raises((ValueError, OSError)):
            persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert store.revision == revision
        assert "app:local-truth-migration" not in store.snapshot().cells
        assert "messages" not in _table_state(store.database_path)
        settings.write_text('{"theme":"dark"}', encoding="utf-8")
        def no_backup(*_args, **_kwargs):
            raise PermissionError("fixture backup denied")
        monkeypatch.setattr(Path, "mkdir", no_backup)
        with pytest.raises(OSError):
            persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert store.revision == revision
        assert "app:local-truth-migration" not in store.snapshot().cells


def test_desktop_main_routes_to_installed_launcher_without_opening_ui(monkeypatch):
    from nodelang import desktop
    calls = []
    def execute(path, **kwargs):
        calls.append((Path(path).resolve(), kwargs))
        return {"__name__": "__main__"}
    monkeypatch.setattr(runpy, "run_path", execute)
    desktop.main()
    assert calls == [(ROOT / "01.APP/nodelang/launcher.py", {"run_name": "__main__"})]


def test_production_entry_modules_do_not_construct_a_second_application():
    for relative in ("01.APP/nodelang/desktop.py", "01.APP/nodelang/authority_bridge.py",
                     "01.APP/nodelang/clean_coordination_service.py", "01.APP/nodelang/main.py"):
        path = ROOT / relative
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        constructors = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "ApplicationServer" or
            isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ApplicationServer" and node.func.attr == "from_unified_authority")]
        assert not constructors, relative + " still constructs an independent application"


def test_account_identity_comes_from_bearer_verified_me_not_edited_local_email(tmp_path):
    record = tmp_path / "cloud.json"
    record.write_text(json.dumps({"email": "edited@example.com", "token": "fixture-token",
                                  "cloud_base_url": "https://attacker.invalid"}), encoding="utf-8")
    calls = []
    def fetch(url, bearer):
        calls.append((url, bearer))
        return 200, {"email": "Actual@Example.com"}
    assert cloud_session.signed_in_cloud_account(record, fetch=fetch) == "actual@example.com"
    assert len(calls) == 1 and calls[0][0].endswith("/v1/me")
    assert "attacker.invalid" not in calls[0][0]
    assert calls[0][1] == "fixture-token"


def test_account_identity_rejects_expired_or_absent_session(tmp_path):
    record = tmp_path / "cloud.json"
    record.write_text('{"email":"claim@example.com","token":"expired"}', encoding="utf-8")
    assert cloud_session.signed_in_cloud_account(record, fetch=lambda *_: (401, None)) is None
    record.write_text('{"email":"claim@example.com"}', encoding="utf-8")
    def forbidden(*_):
        pytest.fail("account lookup without a bearer")
    assert cloud_session.signed_in_cloud_account(record, fetch=forbidden) is None


def test_embedded_history_shares_owner_connection_lock_and_survives_adapter_close(tmp_path):
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    graph = tmp_path / "authority.sqlite3"
    with CellStore(graph) as store:
        connection, lock = store.sqlite_storage()
        history = ConversationHistoryStore(graph, instance_id="fixture-account", store=store)
        assert history._db is connection
        assert history._lock is lock
        history.ensure_conversation("workshop")
        history.initialize_retention()
        history.initialize_page_protection()
        history.append("workshop", author="account:alice", content="shared connection persists",
                       idempotency_key="embedded:1")
        history.close()
        store.commit(store.revision, create=(
            Cell("test:after-history-close", NULL_CELL_ID, NULL_CELL_ID, b"still open"),))
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    with CellStore(graph) as reopened:
        assert reopened.read("test:after-history-close").atom == b"still open"
        with ConversationHistoryStore(graph, instance_id="fixture-account", create=False,
                                      store=reopened) as history:
            messages = history.search("workshop", "persists", principal="account:alice")
            assert len(messages) == 1
            assert messages[0]["content"] == "shared connection persists"
            replay = history.append("workshop", author="account:alice",
                                    content="shared connection persists", idempotency_key="embedded:1")
            assert replay["created"] is False


def test_migration_preserves_rowid_gaps_fts_and_allows_live_embedded_append(tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    _history(legacy)
    with ConversationHistoryStore(legacy, instance_id="fixture-account", create=False) as history:
        history.append("workshop", author="account:alice", content="second searchable blossom",
                       idempotency_key="gap:2", message_id="message:2")
        history.initialize_page_protection()
    with closing(sqlite3.connect(legacy)) as connection, connection:
        connection.execute("UPDATE messages SET rowid=rowid+10")
        connection.execute("INSERT INTO message_search(message_search) VALUES('rebuild')")
        rowids = connection.execute("SELECT rowid,id FROM messages ORDER BY rowid").fetchall()
        assert rowids[0][0] > 1
    before = _digest(legacy)
    graph = tmp_path / "authority.sqlite3"
    with CellStore(graph) as store:
        persistence.migrate_local_truths(store, history_path=legacy)
        connection, _ = store.sqlite_storage()
        assert [tuple(row) for row in connection.execute(
            "SELECT rowid,id FROM messages ORDER BY rowid")] == rowids
        with ConversationHistoryStore(graph, instance_id="fixture-account", create=False,
                                      store=store) as history:
            hits = history.search("workshop", "blossom", principal="account:alice")
            assert [hit["id"] for hit in hits] == ["message:2"]
            result = history.append("workshop", author="account:alice", content="after migration",
                                    idempotency_key="new:3", message_id="message:3")
            assert result["created"] is True
            assert history.search("workshop", "after migration", principal="account:alice")[0]["id"] == "message:3"
    assert _digest(legacy) == before
    with CellStore(graph) as store:
        with ConversationHistoryStore(graph, instance_id="fixture-account", create=False,
                                      store=store) as history:
            assert history.get("workshop", "message:3", principal="account:alice")["content"] == "after migration"


def test_graph_before_commit_fault_rolls_back_history_schema_and_migration_cells_together(tmp_path):
    legacy, settings = tmp_path / "legacy.sqlite3", tmp_path / "settings.json"
    _history(legacy)
    settings.write_text('{"theme":"dark"}', encoding="utf-8")
    originals = (_digest(legacy), _digest(settings))
    armed = False
    def fault(stage):
        if armed and stage == "before_commit":
            raise RuntimeError("reviewer fault before graph commit")
    graph = tmp_path / "authority.sqlite3"
    with CellStore(graph, fault_injector=fault) as store:
        revision = store.revision
        original_tables = _table_state(graph)
        armed = True
        with pytest.raises(RuntimeError, match="reviewer fault before graph commit"):
            persistence.migrate_local_truths(store, history_path=legacy, settings_path=settings)
        assert store.revision == revision
        assert "app:local-truth-migration" not in store.snapshot().cells
        assert "app:imported-settings" not in store.snapshot().cells
        assert _table_state(graph) == original_tables
        assert originals == (_digest(legacy), _digest(settings))
        backups = list((tmp_path / "backups").glob("truth-migration-*"))
        assert len(backups) == 1
        assert (backups[0] / "graph.sqlite3").is_file()
        assert (backups[0] / "history.sqlite3").is_file()
        assert (backups[0] / "settings.json").read_bytes() == settings.read_bytes()
        with closing(sqlite3.connect(backups[0] / "graph.sqlite3")) as saved:
            assert saved.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        armed = False
        assert persistence.migrate_local_truths(store, history_path=legacy,
                                              settings_path=settings)["state"] == "migrated"
    with CellStore(graph) as store:
        assert "app:local-truth-migration" in store.snapshot().cells


def test_completed_migration_detects_retired_history_changes_still_only_in_wal(tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    _history(legacy)
    with closing(sqlite3.connect(legacy)) as writer, writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        with CellStore(tmp_path / "authority.sqlite3") as store:
            persistence.migrate_local_truths(store, history_path=legacy)
            revision = store.revision
            main_digest = _digest(legacy)
            writer.execute("UPDATE messages SET content='changed only in WAL' WHERE id='message:1'")
            writer.commit()
            assert _digest(legacy) == main_digest
            assert Path(str(legacy) + "-wal").stat().st_size > 0
            with pytest.raises((ValueError, OSError)):
                persistence.migrate_local_truths(store, history_path=legacy)
            assert store.revision == revision


def test_shared_recovery_and_restore_copy_one_physical_database_with_role_aliases(tmp_path):
    import time
    from nodelang.application_recovery_files import _MANIFEST_BYTES, publish_application_recovery
    from nodelang.application_recovery_restore_files import prepare_application_restore
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    graph = tmp_path / "authority.sqlite3"
    recovery = tmp_path / "recovery"
    restored = tmp_path / "restored"
    def verify_backup(paths, check):
        check()
        assert paths["graph"] == paths["content"]
        with closing(sqlite3.connect(paths["graph"])) as copied:
            assert copied.execute("SELECT content FROM messages").fetchone()[0] == "one physical copy"
        return {"test": "shared graph and content"}
    def verify_restore(paths, manifest, check):
        check()
        assert paths["graph"] == paths["content"]
        assert manifest["files"]["graph"] == manifest["files"]["content"]
    with CellStore(graph) as store:
        store.commit(store.revision, create=(Cell("test:recovery-budget-padding",
            NULL_CELL_ID, NULL_CELL_ID, b"x" * (_MANIFEST_BYTES + 4096)),))
        with ConversationHistoryStore(graph, instance_id="fixture-account", store=store) as history:
            history.ensure_conversation("workshop")
            history.append("workshop", author="account:alice", content="one physical copy",
                           idempotency_key="shared-recovery:1", message_id="recovery:1")
        connection, _ = store.sqlite_storage()
        one_database_bytes = (connection.execute("PRAGMA page_count").fetchone()[0] *
                              connection.execute("PRAGMA page_size").fetchone()[0])
        assert one_database_bytes > _MANIFEST_BYTES
        publish_application_recovery({"graph": connection, "content": connection}, recovery,
            verify_copies=verify_backup, before_publish=lambda: None,
            deadline=time.monotonic() + 30, max_bytes=one_database_bytes + _MANIFEST_BYTES)
    assert len(list(recovery.glob("*.sqlite3"))) == 1
    manifest = json.loads((recovery / "recovery.json").read_text(encoding="utf-8"))
    assert manifest["files"]["graph"] == manifest["files"]["content"]
    prepare_application_restore(recovery, restored,
        output_names={"graph": "authority.sqlite3", "content": "authority.sqlite3"},
        verify_copies=verify_restore, before_publish=lambda: None, deadline=time.monotonic() + 30)
    assert len(list(restored.glob("*.sqlite3"))) == 1
    with CellStore(restored / "authority.sqlite3") as store:
        with ConversationHistoryStore(restored / "authority.sqlite3", instance_id="fixture-account",
                                      create=False, store=store) as history:
            assert history.get("workshop", "recovery:1", principal="account:alice")["content"] == "one physical copy"


def test_retired_graph_change_during_backup_cannot_be_marked_migrated_but_omitted(tmp_path, monkeypatch):
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    source = tmp_path / "retired.sqlite3"
    with CellStore(source) as old:
        old.commit(old.revision, create=(Cell("legacy:original", NULL_CELL_ID, NULL_CELL_ID, b"original"),))
    with CellStore(tmp_path / "authority.sqlite3") as owner:
        original_backup = owner.backup_to
        mutated = False
        def backup_with_source_commit(destination):
            nonlocal mutated
            result = original_backup(destination)
            if not mutated:
                mutated = True
                with CellStore(source) as changed:
                    changed.commit(changed.revision, create=(
                        Cell("legacy:during-backup", NULL_CELL_ID, NULL_CELL_ID, b"must not vanish"),))
            return result
        monkeypatch.setattr(owner, "backup_to", backup_with_source_commit)
        revision = owner.revision
        try:
            persistence.migrate_graph_source(owner, source)
        except (ValueError, OSError):
            assert owner.revision == revision
            assert "legacy:original" not in owner.snapshot().cells
        else:
            assert mutated
            assert owner.snapshot().cells["legacy:during-backup"].atom == b"must not vanish"


def test_failed_migration_retries_reuse_one_verified_backup(tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    _history(legacy)
    original = _digest(legacy)
    armed = True
    def fault(stage):
        if armed and stage == "before_commit":
            raise RuntimeError("repeatable reviewer fault")
    with CellStore(tmp_path / "authority.sqlite3", fault_injector=fault) as store:
        for _ in range(4):
            with pytest.raises(RuntimeError, match="repeatable reviewer fault"):
                persistence.migrate_local_truths(store, history_path=legacy)
            assert store.revision == 0
            assert len(list((tmp_path / "backups").glob("truth-migration-*"))) == 1
            assert "messages" not in _table_state(store.database_path)
        backup = next((tmp_path / "backups").glob("truth-migration-*"))
        snapshots = {path.name: _digest(path) for path in backup.iterdir() if path.is_file()}
        armed = False
        result = persistence.migrate_local_truths(store, history_path=legacy)
        assert Path(result["backup_path"]) == backup
        assert {path.name: _digest(path) for path in backup.iterdir() if path.is_file()} == snapshots
        assert _digest(legacy) == original


def test_migration_refuses_projected_backup_over_budget_before_copy_or_graph_effect(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.sqlite3"
    _history(legacy)
    monkeypatch.setattr(backup_retention, "backup_policy", lambda *_: {"keep_count": 3, "max_bytes": 1})
    with CellStore(tmp_path / "authority.sqlite3") as store:
        def forbidden_copy(*_args, **_kwargs):
            pytest.fail("backup copy started despite projected byte budget")
        monkeypatch.setattr(store, "backup_to", forbidden_copy)
        with pytest.raises((ValueError, OSError), match="budget"):
            persistence.migrate_local_truths(store, history_path=legacy)
        assert store.revision == 0
        assert "messages" not in _table_state(store.database_path)
        assert "app:local-truth-migration" not in store.snapshot().cells
        assert not list((tmp_path / "backups").glob("truth-migration-*"))


def test_migration_retention_respects_armed_update_receipt(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.sqlite3"
    _history(legacy)
    backups = tmp_path / "backups"
    backups.mkdir()
    protected = _backup(backups, "20261014-armed-recovery", 1)
    obsolete = _backup(backups, "20261015-obsolete", 2)
    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "update-ready.json").write_text(
        json.dumps({"recovery": {"path": str(protected)}}), encoding="utf-8")
    monkeypatch.setattr(backup_retention, "backup_policy", lambda *_: {"keep_count": 1, "max_bytes": 1024**2})
    with CellStore(tmp_path / "authority.sqlite3") as store:
        result = persistence.migrate_local_truths(store, history_path=legacy)
        assert Path(result["backup_path"]).is_dir()
        assert protected.is_dir()
        assert (protected / "authority.sqlite3").read_bytes() == b"x" * 8
        assert not obsolete.exists()


def _signed_fixture_owner(path):
    from tests_replica.test_unified_authority import _authority
    from nodelang.unified_authority import bind_signed_commit_owner
    store = CellStore(path)
    try:
        authority = _authority(store)
        bind_signed_commit_owner(authority)
        return authority
    except BaseException:
        store.close()
        raise


def _head_root(authority, snapshot):
    from nodelang.unified_authority import relation_members
    return next(member.participant_id for member in relation_members(
        snapshot, authority.manifest.head_index_root)
        if member.role_id == authority.role("current-head"))


def test_bound_signed_owner_seals_app_and_native_changes_without_idle_heads_and_reopens(tmp_path):
    from nodelang import unified_authority as ua
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    graph = tmp_path / "authority.sqlite3"
    authority = _signed_fixture_owner(graph)
    store = authority.store
    manifest, provider = authority.manifest, authority.key_provider
    try:
        before, old_head = store.revision, _head_root(authority, store.snapshot())
        cell = Cell("app:reviewer-signed", NULL_CELL_ID, NULL_CELL_ID, b"app change")
        guards = []
        store.commit(before, create=(cell,), precommit_guard=lambda: guards.append("admitted"))
        assert guards == ["admitted"]
        assert store.revision == before + 1
        assert _head_root(authority, store.snapshot()) != old_head
        ua.verify_exact_authority_head(authority)
        ua.audit_authority_history(authority)
        current, head = store.revision, _head_root(authority, store.snapshot())
        physical = []
        assert store.commit(current, replace=(cell,), physical_write=lambda _: physical.append("write")) == current
        assert not physical
        assert _head_root(authority, store.snapshot()) == head
        native = Cell("app:reviewer-native", NULL_CELL_ID, NULL_CELL_ID, b"already sealed")
        ua._commit_signed_change(authority, store.snapshot(), create=(native,), replace_cells=())
        assert store.revision == current + 1
        ua.audit_authority_history(authority)
    finally:
        store.close()
    with CellStore(graph) as reopened:
        verified = ua.open_unified_authority(reopened, manifest, provider)
        ua.audit_authority_history(verified)
        assert reopened.read("app:reviewer-signed").atom == b"app change"
        assert reopened.read("app:reviewer-native").atom == b"already sealed"


def test_signed_owner_binding_is_idempotent_and_rejects_a_second_owner(tmp_path):
    from dataclasses import replace
    from nodelang import unified_authority as ua
    from nodelang.universal_cell import InvalidCell
    authority = _signed_fixture_owner(tmp_path / "authority.sqlite3")
    try:
        revision = authority.store.revision
        ua.bind_signed_commit_owner(authority)
        assert authority.store.revision == revision
        with pytest.raises(InvalidCell):
            ua.bind_signed_commit_owner(replace(authority))
        assert authority.store.revision == revision
    finally:
        authority.store.close()


@pytest.mark.parametrize("fault_at", ("signer", "guard", "physical"))
def test_signed_owner_fault_keeps_graph_and_physical_effect_atomic(tmp_path, monkeypatch, fault_at):
    from nodelang import unified_authority as ua
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    graph = tmp_path / "authority.sqlite3"
    authority = _signed_fixture_owner(graph)
    store = authority.store
    try:
        revision = store.revision
        head = _head_root(authority, store.snapshot())
        calls = []
        original_sign = authority.key_provider.sign
        def sign(key_id, version, payload):
            if fault_at == "signer" and json.loads(payload).get("revision", 0) > revision:
                raise RuntimeError("reviewer signer fault")
            return original_sign(key_id, version, payload)
        monkeypatch.setattr(authority.key_provider, "sign", sign)
        def guard():
            if fault_at == "guard":
                raise RuntimeError("reviewer guard fault")
        def physical(connection):
            calls.append("physical")
            connection.execute("CREATE TABLE reviewer_atomic_effect(value TEXT)")
            connection.execute("INSERT INTO reviewer_atomic_effect VALUES('must roll back')")
            if fault_at == "physical":
                raise RuntimeError("reviewer physical fault")
        with pytest.raises(RuntimeError, match="reviewer .* fault"):
            store.commit(revision,
                create=(Cell("app:reviewer-refused", NULL_CELL_ID, NULL_CELL_ID, b"unpublished"),),
                precommit_guard=guard, physical_write=physical)
        assert calls == (["physical"] if fault_at == "physical" else [])
        assert store.revision == revision
        assert "app:reviewer-refused" not in store.snapshot().cells
        assert _head_root(authority, store.snapshot()) == head
        assert "reviewer_atomic_effect" not in _table_state(graph)
        ua.audit_authority_history(authority)
    finally:
        store.close()


def test_signed_native_candidate_with_valid_signature_but_wrong_predecessor_is_refused(tmp_path):
    from types import MappingProxyType
    from nodelang import unified_authority as ua
    from nodelang.universal_cell import Cell, InvalidCell, NULL_CELL_ID, Snapshot, overlay_read_snapshot
    authority = _signed_fixture_owner(tmp_path / "authority.sqlite3")
    store = authority.store
    try:
        ancestor = _head_root(authority, store.snapshot())
        store.commit(store.revision, create=(
            Cell("app:reviewer-parent", NULL_CELL_ID, NULL_CELL_ID, b"current parent"),))
        snapshot = store.snapshot()
        current = ua._current_head_member(authority, snapshot)
        reference = snapshot.cells[current.incidence_id]
        fork_cells = dict(snapshot.cells)
        fork_cells[reference.id] = Cell(reference.id, reference.link0, ancestor, reference.atom)
        fork = Snapshot(snapshot.revision, MappingProxyType(fork_cells))
        plan = ua._prepare_signed_change(authority, fork,
            create=(Cell("app:reviewer-fork", NULL_CELL_ID, NULL_CELL_ID, b"wrong parent"),),
            replace_cells=())
        candidate = overlay_read_snapshot(snapshot, create=plan.create, replace=plan.replace)
        ua._verify_authority_head(authority, candidate, _head_root(authority, candidate),
                                 candidate_changes=(snapshot, plan.create, plan.replace))
        with pytest.raises(InvalidCell, match="descend|parent|predecessor"):
            store.commit(snapshot.revision, create=plan.create, replace=plan.replace)
        assert store.revision == snapshot.revision
        assert "app:reviewer-fork" not in store.snapshot().cells
        ua.audit_authority_history(authority)
    finally:
        store.close()


def test_signed_owner_refuses_rewriting_an_existing_signed_head_record(tmp_path):
    from nodelang import unified_authority as ua
    from nodelang.universal_cell import Cell, InvalidCell
    authority = _signed_fixture_owner(tmp_path / "authority.sqlite3")
    store = authority.store
    try:
        snapshot = store.snapshot()
        head = _head_root(authority, snapshot)
        signature_value = next(member.participant_id for member in ua.relation_members(snapshot, head)
                               if member.role_id == authority.role("signature"))
        payload = next(member.participant_id for member in ua.relation_members(snapshot, signature_value)
                       if member.role_id == authority.role("payload"))
        cell = snapshot.cells[payload]
        with pytest.raises(InvalidCell):
            store.commit(snapshot.revision, replace=(
                Cell(cell.id, cell.link0, cell.link1, json.dumps("0" * 64).encode()),))
        assert store.revision == snapshot.revision
        assert store.read(payload) == cell
        ua.audit_authority_history(authority)
    finally:
        store.close()
