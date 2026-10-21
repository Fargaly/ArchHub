"""Independent real-owner court for recurrent retirement after signed adoption."""
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from nodelang import commit_intent, conversation_archive as archive, persistence
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.conversation_retention_maintenance import (
    _advance_trace_registry, partition_archived_trace_batch,
)
from nodelang.cell_value_graph import project_value_graph_protocol
from nodelang.universal_application import _verify_application_agent_receipts
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
from tests_replica.test_adopt_archive import _export, _page_all
from tests_replica.test_ogboot_upgrade_selection import (
    _closed_backup, _prepare, _selected,
)
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile


def _old_family(store, session, monkeypatch):
    import nodelang.universal_cell as kernel
    old = time.time() - 40 * 86400
    cells = (
        Cell(session + ":chain:0", NULL_CELL_ID, NULL_CELL_ID, b"preserved original text"),
        Cell(session + ":chain:1", session + ":chain:0", NULL_CELL_ID, b""),
    )
    with monkeypatch.context() as clock:
        clock.setattr(kernel, "time", SimpleNamespace(time=lambda: old))
        with commit_intent.declare(commit_intent.MIGRATION, actor="court",
                reason="synthetic historical trace fixture"):
            store.commit(store.revision, create=cells)
    return cells, {cell.id: session for cell in cells}


def _partition(store, history, path, cells, sessions):
    identifiers = tuple(cell.id for cell in cells)
    graph = {identifier: cell for identifier, cell in store.snapshot().cells.items() if identifier not in identifiers}
    revision = store.revision
    if 'app:value-graph-protocol:root' in store.snapshot().cells:
        protocol = project_value_graph_protocol(store.snapshot(), prefix='app:value-graph-protocol')
        owner = SimpleNamespace(universal_store=store,
            universal_registry=SimpleNamespace(value_graph_protocol=protocol))
        service = SimpleNamespace(_owner=owner)
        for _ in range(6000):
            if _advance_trace_registry(service, history, None, lambda: None, 256) is None:
                break
        else:
            raise AssertionError('actual work-only catalog inventory did not finish')
    assert store.revision == revision
    _export(store, path, identifiers, sessions, history)
    assert partition_archived_trace_batch(store, history, path, identifiers, sessions,
                                         check=lambda: None) == len(identifiers)
    assert not set(identifiers) & set(store.snapshot().cells)
    assert dict(store.snapshot().cells) == graph
    connection, _ = store.sqlite_storage()
    for identifier in identifiers:
        assert connection.execute("SELECT 1 FROM cell_versions WHERE cell_id=?", (identifier,)).fetchone() is None


def test_recurrent_archive_keeps_signed_head_and_reopens_without_cold_reads(isolated_profile, tmp_path, monkeypatch):
    root = isolated_profile / "ArchHub"
    _selected(root)
    source = isolated_profile / "ArchHub-Test/archhub-test.universal.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    kwargs = dict(universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server = ApplicationServer(universal_state_path=source, **kwargs)
    saved = Cell("work:signed-review-saved", NULL_CELL_ID, NULL_CELL_ID, b"saved work survives")
    try:
        receipts = _verify_application_agent_receipts(server.universal_store,
            server.universal_registry.authorization, server.universal_registry.agent_body)
        history_id = server.conversation_content._history.instance_id
        with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="synthetic saved work"):
            server.universal_store.commit(server.universal_store.revision, create=(saved,))
        first, first_sessions = _old_family(server.universal_store,
            "app:workshop:signed-review-before", monkeypatch)
    finally:
        server.close()
    _closed_backup(source)
    chosen = _prepare(root, key_provider=keys)
    with CellStore(chosen) as store:
        with ConversationHistoryStore(chosen, instance_id=history_id, store=store) as history:
            history.initialize_trace_maintenance()
            cold = archive.trace_archive_path(chosen)
            _partition(store, history, cold, first, first_sessions)
            authority = persistence.finalize_application_adoption(store, keys)
            assert authority is store._signed_commit_authority
            second, second_sessions = _old_family(store,
                "app:workshop:signed-review-after", monkeypatch)
            signed_revision = store.revision
            _partition(store, history, cold, second, second_sessions)
            assert store.revision == signed_revision
    # Accelerators are disposable: force a cold live proof without consulting
    # the cold archive's retired cells or trusting the previous process cache.
    Path(str(chosen) + ".accelerators").unlink(missing_ok=True)
    opened = []
    connect = sqlite3.connect
    def observed(database, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(database):
            opened.append(str(database))
        return connect(database, *args, **kwargs)
    with monkeypatch.context() as observing:
        observing.setattr(sqlite3, "connect", observed)
        reopened = ApplicationServer(universal_state_path=chosen, **kwargs)
        try:
            assert reopened.universal_store._signed_commit_authority.store is reopened.universal_store
            assert _verify_application_agent_receipts(reopened.universal_store,
                reopened.universal_registry.authorization, reopened.universal_registry.agent_body) == receipts
            assert reopened.universal_store.read(saved.id) == saved
        finally:
            reopened.close()
        assert opened == [], "startup must not read or verify any archived Cells"
    for cells, sessions in ((first, first_sessions), (second, second_sessions)):
        rows = _page_all(cold, next(iter(sessions.values())))
        assert set(rows) == {cell.id for cell in cells}
        for cell in cells:
            assert (rows[cell.id]["link0"], rows[cell.id]["link1"], rows[cell.id]["atom"]) == (
                cell.link0, cell.link1, cell.atom)
    print("ADOPT_SIGNED_ARCHIVE_STARTUP_COLD_OPENS", len(opened))
