"""Synthetic ADOPT custody courts; the live-count requirement stays enforced.

Export-only code can pass byte custody and fail retirement. That failure is
intentional release-blocker evidence, never an accepted retention substitute.
"""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from nodelang import conversation_archive as archive
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_cell import Cell, CellStore, DatabaseOwnerConflict, InvalidCell, NULL_CELL_ID
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile
ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _registry_court(tmp_path, monkeypatch):
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang.cell_protocols import compose_relation_cells, prepare_append_relation_member
    import nodelang.universal_cell as kernel
    path = tmp_path / 'registry.sqlite3'
    content = Path(str(path)+'.conversations.sqlite3')
    old_at = time.time()-40*86400
    role = 'app:value-graph-protocol:role:value-member'
    root = 'app:value-graph-protocol:root'
    old = Cell('app:deliberation-payload:registry-old', NULL_CELL_ID,
        'app:deliberation-payload:registry-old:child', b'old text')
    child = Cell(old.link1, NULL_CELL_ID, NULL_CELL_ID, b'child')
    work = Cell('work:registry-value', NULL_CELL_ID, NULL_CELL_ID, b'work')
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='registry-court') as history:
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old_at))
            relation = compose_relation_cells(((role, old.id),), relation_id=root)
            store.commit(store.revision, create=(Cell(role, NULL_CELL_ID, NULL_CELL_ID, b''), old, child, *relation.cells))
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-86400))
            appended = prepare_append_relation_member(store.snapshot(), root, role, work.id)
            store.commit(store.revision, create=(work, *appended.create), replace=appended.replace)
        room = 'app:deliberation:registry-court'
        history.initialize_trace_maintenance()
        history.ensure_conversation(room)
        with history._transaction(write=True):
            history._db.execute('INSERT INTO trace_migrations(conversation_id,source_authority,source_revision,delta_cell,cursor,controls,state,last_activity_at) VALUES(?,?,?,?,?,?,?,?)',
                (room, store.authority_identity, store.revision, '', '', '[]', 'bound', old_at))
            for cell in (old, child):
                history._db.execute('INSERT INTO trace_migration_cells(conversation_id,cell_id,digest,owned,activity_at) VALUES(?,?,?,1,?)',
                    (room, cell.id, maintenance._trace_cell_digest(cell), old_at))
        broker = SimpleNamespace(commit_authenticated=lambda _context, target, revision, **patch: target.commit(revision, **patch))
        registry = SimpleNamespace(value_graph_protocol=SimpleNamespace(root_id=root, role=lambda _name: role),
            authorization=SimpleNamespace(subject_root='court', broker=broker))
        service = SimpleNamespace(_owner=SimpleNamespace(universal_store=store, universal_registry=registry), _path=content)
        yield store, history, service, old, child, work, room


def _registry_until(store, history, service, phase):
    from nodelang import conversation_retention_maintenance as maintenance
    for _ in range(100):
        maintenance._advance_trace_registry(service, history, object(), lambda: None, 1)
        state = history._db.execute('SELECT phase FROM trace_registry_state WHERE singleton=1').fetchone()
        if state and state[0] == phase:
            return
    pytest.fail('bounded native registry preparation did not reach '+phase)


@pytest.mark.parametrize('interruption', ('before-publication', 'after-publication'))
def test_registry_first_root_promotion_resumes_verified_custody(tmp_path, monkeypatch, interruption):
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang.cell_protocols import read_relation
    class Interrupted(RuntimeError):
        pass
    with _registry_court(tmp_path, monkeypatch) as (store, history, service, old, child, work, room):
        root = service._owner.universal_registry.value_graph_protocol.root_id
        original_root = store.read(root)
        original_work_chain = store.read(original_root.link1)
        work_incidence = store.read(original_work_chain.link0)
        before = _rows(store.sqlite_storage()[0])
        _registry_until(store, history, service, 'detach')
        broker = service._owner.universal_registry.authorization.broker
        target, attribute = ((broker, 'commit_authenticated') if interruption == 'before-publication'
                             else (maintenance, '_registry_ack_splice'))
        with monkeypatch.context() as crash:
            crash.setattr(target, attribute, lambda *_args, **_kwargs: (_ for _ in ()).throw(Interrupted()))
            with pytest.raises(Interrupted):
                maintenance._advance_trace_registry(service, history, object(), lambda: None, 1)
        assert history._db.execute('SELECT pending FROM trace_registry_state').fetchone()[0]
        replacement = "INSERT OR REPLACE INTO trace_registry_state(singleton,phase,cursor,ordinal,source_revision,pending) VALUES(1,'ordinary','',0,?,NULL)"
        with pytest.raises(sqlite3.IntegrityError, match='registry custody is immutable'):
            history._db.execute(replacement, (store.revision,))
        with closing(sqlite3.connect(service._path)) as external:
            with pytest.raises(sqlite3.OperationalError, match='trace_registry_custody_write'):
                external.execute(replacement, (store.revision,))
        assert store.read(old.id) == old and store.read(child.id) == child
        assert store.read(root) == original_root if interruption == 'before-publication' else store.read(root).link0 == work_incidence.id
        store._trace_registry_cache = None
        assert not maintenance._registry_partition_admitted(store, history, old.id)
        _registry_until(store, history, service, 'ordinary')
        proof = tuple(history._db.execute('SELECT * FROM trace_registry_detached LIMIT 1').fetchone())
        attacks = (('INSERT OR REPLACE INTO trace_registry_detached VALUES(?,?,?,?,?)', proof),
                   ('UPDATE trace_registry_detached SET activity_at=0 WHERE cell_id=?', (proof[0],)),
                   ('DELETE FROM trace_registry_detached WHERE cell_id=?', (proof[0],)))
        for statement, arguments in attacks:
            with pytest.raises(sqlite3.IntegrityError, match='registry custody is immutable'):
                history._db.execute(statement, arguments)
            with closing(sqlite3.connect(service._path)) as external:
                with pytest.raises(sqlite3.OperationalError, match='trace_registry_custody_write'):
                    external.execute(statement, arguments)
        assert [(member.role_id, member.participant_id) for member in read_relation(store.snapshot(), root)] == [
            (service._owner.universal_registry.value_graph_protocol.role('value-member'), work.id)]
        while maintenance._advance_family_inventory(store, history, lambda: None, 1)['status'] != 'family-ready':
            pass
        cold_path = archive.trace_archive_path(service._path)
        ids = (old.id, child.id, original_root.link0, original_work_chain.id)
        _export(store, cold_path, (old.id, child.id), dict.fromkeys((old.id, child.id), room), history)
        assert maintenance.partition_archived_trace_batch(store, history, cold_path, ids,
            dict.fromkeys(ids, room), check=lambda: None) == len(ids)
        assert set(ids).isdisjoint(store.snapshot().cells)
        assert store.read(work.id) == work and store.read(work_incidence.id) == work_incidence
        assert store.read(root).id == original_root.id
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            for identifier in ids:
                expected = [row for row in before['versions'] if row[1] == identifier]
                actual = [tuple(row) for row in cold.execute('SELECT revision,cell_id,link0,link1,atom,source_rowid FROM trace_versions WHERE cell_id=? ORDER BY revision', (identifier,))]
                assert actual == expected


def test_registry_forged_ack_and_foreign_append_never_authorize_partition(tmp_path, monkeypatch):
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang.cell_protocols import prepare_append_relation_member
    with _registry_court(tmp_path, monkeypatch) as (store, history, service, old, child, _work, room):
        _registry_until(store, history, service, 'prospective')
        cache = store._trace_registry_cache
        assert cache['complete'] and cache['roots'][old.id] == 1
        with pytest.raises(sqlite3.IntegrityError, match='registry custody is immutable'):
            history._db.execute('INSERT INTO trace_registry_detached VALUES(?,?,?,?,?)',
                ('work:registry-value', old.id, room, time.time()-40*86400, maintenance._trace_cell_digest(store.read('work:registry-value'))))
        with pytest.raises(sqlite3.IntegrityError, match='registry custody is immutable'):
            history._db.execute("UPDATE trace_registry_state SET pending='{}'")
        history._db.execute("UPDATE trace_registry_state SET phase='ordinary',source_revision=?", (store.revision,))
        history._db.execute('UPDATE trace_registry_members SET detached=1')
        assert not maintenance._registry_partition_admitted(store, history, old.id)
        assert not maintenance._registry_partition_admitted(store, history, child.id)
        # Restore actual progress, detach once, then append a NEW occurrence.
        history._db.execute("UPDATE trace_registry_state SET phase='prospective'")
        history._db.execute('UPDATE trace_registry_members SET detached=0')
        _registry_until(store, history, service, 'ordinary')
        protocol = service._owner.universal_registry.value_graph_protocol
        patch = prepare_append_relation_member(store.snapshot(), protocol.root_id, protocol.role('value-member'), old.id)
        store.commit(store.revision, create=patch.create, replace=patch.replace)
        history._db.execute('UPDATE trace_registry_state SET source_revision=?', (store.revision,))
        assert not maintenance._registry_partition_admitted(store, history, old.id)
        cold_path = archive.trace_archive_path(service._path)
        _export(store, cold_path, (old.id,), {old.id: room}, history)
        with pytest.raises(InvalidCell, match='current value catalog membership'):
            maintenance.partition_archived_trace_batch(store, history, cold_path, (old.id,), {old.id: room}, check=lambda: None)
        assert store.read(old.id) == old and store.read(child.id) == child
        # A durable cursor cannot certify an unwalked suffix after restart.
        store._trace_registry_cache = None
        _registry_until(store, history, service, 'scan')
        maintenance._advance_trace_registry(service, history, object(), lambda: None, 1)
        history._db.execute('UPDATE trace_registry_state SET cursor=?,ordinal=999', (NULL_CELL_ID,))
        maintenance._advance_trace_registry(service, history, object(), lambda: None, 1)
        assert store._trace_registry_cache is None
        # Native relation removal admits the empty permanent root on rescan.
        store.commit(store.revision, replace=(Cell(protocol.root_id, NULL_CELL_ID, NULL_CELL_ID, b''),))
        _registry_until(store, history, service, 'prospective')
        assert store._trace_registry_cache['complete']
        assert store._trace_registry_cache['roots'] == {}
        assert store._trace_registry_cache['indexes'] == {protocol.root_id}


def test_registry_work_reference_to_payload_child_preserves_registration(tmp_path, monkeypatch):
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang.cell_protocols import prepare_append_relation_member, read_relation
    with _registry_court(tmp_path, monkeypatch) as (store, history, service, old, child, _work, _room):
        required = Cell('work:old-value-child', child.id, NULL_CELL_ID, b'saved work')
        protocol = service._owner.universal_registry.value_graph_protocol
        unknown = prepare_append_relation_member(store.snapshot(), protocol.root_id, 'work:catalog-role', old.id)
        store.commit(store.revision, create=(required, Cell('work:catalog-role', NULL_CELL_ID, NULL_CELL_ID, b''), *unknown.create), replace=unknown.replace)
        before = _rows(store.sqlite_storage()[0])
        members = read_relation(store.snapshot(), protocol.root_id)
        _registry_until(store, history, service, 'ordinary')
        assert _rows(store.sqlite_storage()[0]) == before
        assert read_relation(store.snapshot(), protocol.root_id) == members
        assert not maintenance._registry_partition_admitted(store, history, old.id)
        assert not maintenance._registry_partition_admitted(store, history, child.id)


def _trace_fixture(tmp_path, monkeypatch):
    import nodelang.universal_cell as kernel
    path = tmp_path / "synthetic.sqlite3"
    sessions, old, recent = {}, {}, {}
    now = time.time()
    with CellStore(path) as store:
        graph = tuple(Cell("work:"+kind, NULL_CELL_ID, NULL_CELL_ID, kind.encode())
            for kind in ("nodes", "wires", "settings", "brain", "authority", "receipts", "workflows"))
        store.commit(store.revision, create=graph)
        graph = dict(store.snapshot().cells)
        for age, target in ((40, old), (1, recent)):
            cells = []
            for prefix in ("app:deliberation-payload:", "app:agent-session:",
                           "app:workshop:", "app:baboom-session:"):
                session = prefix+f"session-{age}"
                previous = NULL_CELL_ID
                for number in range(8 if age == 40 else 2):
                    ident = session+f":chain:{number:04d}"
                    atom = f"conversation text {session}".encode() if number == 0 else b""
                    cell = Cell(ident, previous, NULL_CELL_ID, atom)
                    target[ident] = cell
                    sessions[ident] = session
                    cells.append(cell)
                    previous = ident
            with monkeypatch.context() as clock:
                clock.setattr(kernel, "time", SimpleNamespace(time=lambda a=age: now-a*86400))
                store.commit(store.revision, create=tuple(cells))
        # A real second historical version must survive exact cold export too.
        ident = sorted(old)[0]
        cell = old[ident]
        old[ident] = Cell(cell.id, cell.link0, cell.link1, cell.atom+b" revised")
        with monkeypatch.context() as clock:
            clock.setattr(kernel, "time", SimpleNamespace(time=lambda: now-39*86400))
            store.commit(store.revision, replace=(old[ident],))
    return path, graph, old, recent, sessions


def _rows(connection):
    return {name: [tuple(row) for row in connection.execute(query)] for name, query in (
        ("current", "SELECT cell_id,revision,link0,link1,atom FROM current_cells ORDER BY cell_id"),
        ("versions", "SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions ORDER BY revision,cell_id"),
        ("revisions", "SELECT * FROM revisions ORDER BY revision"))}


def _export(store, cold_path, ids, sessions, history=None, check=lambda: None):
    connection, lock = store.sqlite_storage()
    selected = {ident: sessions[ident] for ident in ids}
    with lock:
        cold, versions = archive.preserve_trace_batch(connection, cold_path,
            store.authority_identity, tuple(ids), selected, check)
        try:
            if history is not None:
                history.index_trace_archive(cold, tuple(selected.values()),
                    archive_path=cold_path, check=check, cell_ids=tuple(ids))
        finally:
            cold.close()
    return versions


def _page_all(path, session):
    cells, cursor = {}, ""
    while cursor is not None:
        page = archive.read_trace_archive(path, session, limit=3, after=cursor)
        cells.update({row["id"]: row for row in page["cells"]})
        if page["next"] is not None:
            assert page["next"] > cursor
        cursor = page["next"]
    return cells


@pytest.mark.parametrize('interruption', ['none', 'append', 'external', 'committed-fault'])
def test_mainfix_partition_count_witness_preserves_exact_checkpoint(tmp_path, monkeypatch, interruption):
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
    path, graph, old, recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path)+'.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    removed = sorted(old)[:24]
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='adopt-court') as history:
        history.initialize_trace_maintenance()
        _export(store, cold_path, sorted(old), sessions, history)
        connection, _ = store.sqlite_storage()
        statements = []
        connection.set_trace_callback(statements.append)
        try:
            for page in range(3):
                if page == 1 and interruption == 'append':
                    store.commit(store.revision, create=(Cell('work:count-witness-edit', NULL_CELL_ID, NULL_CELL_ID, b'saved'),))
                if page == 1 and interruption == 'external':
                    with closing(sqlite3.connect(path)) as other:
                        other.execute('PRAGMA application_id=7040')
                ids = removed[page*8:(page+1)*8]
                if page == 1 and interruption == 'committed-fault':
                    def fault(stage):
                        if stage == 'trace_partition_committed':
                            raise RuntimeError('court interrupted after durable partition')
                    with monkeypatch.context() as failures:
                        failures.setattr(store._journal, '_fault_injector', fault)
                        with pytest.raises(RuntimeError, match='after durable partition'):
                            partition_archived_trace_batch(store, history, cold_path, ids, sessions, check=lambda: None)
                else:
                    partition_archived_trace_batch(store, history, cold_path, ids, sessions, check=lambda: None)
        finally:
            connection.set_trace_callback(None)
        recounts = sum(statement.strip().upper() == 'SELECT COUNT(*) FROM CELL_VERSIONS' for statement in statements)
        assert recounts == (1 if interruption == 'none' else 2), 'unchanged custody must not rescan the entire history per batch'
        actual = connection.execute('SELECT COUNT(*) FROM cell_versions').fetchone()[0]
        checkpoint = store._journal._accelerators().execute('SELECT prefix_rows FROM partition_checkpoints ORDER BY revision DESC LIMIT 1').fetchone()[0]
        assert checkpoint == actual
        assert set(removed).isdisjoint(store.snapshot().cells)
        assert all(store.read(ident) == cell for ident, cell in {**graph, **recent}.items())
        digest = store.revision_chain_digest()
        print('MAINFIX_PARTITION', json.dumps(dict(interruption=interruption, batches=3, full_recounts=recounts, exact_checkpoint=True)))
    with CellStore(path) as reopened:
        assert reopened.revision_chain_digest() == digest
        assert set(removed).isdisjoint(reopened.snapshot().cells)
        if interruption == 'append':
            assert reopened.read('work:count-witness-edit').atom == b'saved'


def test_cold_custody_keeps_every_current_and_historical_byte_once(tmp_path, monkeypatch):
    path, graph, old, recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path)+".conversations.sqlite3")
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id="adopt-court") as history:
        history.initialize_trace_maintenance()
        connection, _lock = store.sqlite_storage()
        before = _rows(connection)
        expected_versions = [row for row in before["versions"] if row[1] in old]
        for _ in range(2):
            assert _export(store, cold_path, sorted(old), sessions, history) == len(expected_versions)
        assert _rows(connection) == before, "an exact export must not alter original custody"
        with closing(sqlite3.connect(cold_path)) as cold:
            actual = cold.execute("SELECT revision,cell_id,link0,link1,atom,source_rowid "
                "FROM trace_versions ORDER BY revision,cell_id").fetchall()
            assert actual == expected_versions
            assert cold.execute("SELECT COUNT(*) FROM trace_current").fetchone()[0] == len(old)
        for session in sorted({sessions[ident] for ident in old}):
            wanted = {ident: cell for ident, cell in old.items() if sessions[ident] == session}
            actual = _page_all(cold_path, session)
            assert set(actual) == set(wanted)
            for ident, cell in wanted.items():
                assert (actual[ident]["link0"], actual[ident]["link1"], actual[ident]["atom"]) \
                    == (cell.link0, cell.link1, cell.atom)
            indexed = history.archived_trace_session(session)
            assert indexed["cell_count"] == len(wanted)
            assert indexed["content"] == "\n".join(cell.atom.decode() for _, cell in sorted(wanted.items()) if cell.atom)
        assert history._db.execute("SELECT COUNT(*) FROM trace_sessions").fetchone()[0] \
            == len({sessions[ident] for ident in old})
        assert all(store.snapshot().cells[ident] == cell for ident, cell in {**graph, **recent}.items())
        print("ADOPT_ARCHIVE_CUSTODY", json.dumps(dict(selected=len(old), exported=len(old),
            historical_versions=len(expected_versions), graph=len(graph), recent=len(recent),
            indexed_sessions=len({sessions[ident] for ident in old}))))


def test_completed_archive_must_leave_only_graph_plus_recent_traces(tmp_path, monkeypatch):
    path, graph, old, recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path)+".conversations.sqlite3")
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id="adopt-court") as history:
        history.initialize_trace_maintenance()
        _export(store, archive.trace_archive_path(content), sorted(old), sessions, history)
        from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
        partition_archived_trace_batch(store, history, archive.trace_archive_path(content),
            sorted(old), sessions, check=lambda: None)
        actual = set(store.snapshot().cells)
        expected = set(graph) | set(recent)
        print("ADOPT_LIVE_COUNT", json.dumps(dict(graph=len(graph), recent=len(recent),
            eligible=len(old), expected_live=len(expected), actual_live=len(actual))))
        assert actual == expected, "export-only custody leaves eligible old trace scaffolding in the live store"
        connection, _ = store.sqlite_storage()
        assert not any(row[0] in old for row in connection.execute('SELECT cell_id FROM cell_versions'))
        original_digest = store.revision_chain_digest()
    opened = []
    connect = sqlite3.connect
    def observe(database, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(database):
            opened.append(str(database))
        return connect(database, *args, **kwargs)
    # Force an actual cold journal proof, rather than accepting only a cache.
    accelerators = Path(str(path) + '.accelerators')
    accelerators.unlink()
    with monkeypatch.context() as observing:
        observing.setattr(sqlite3, 'connect', observe)
        with CellStore(path) as reopened:
            assert set(reopened.snapshot().cells) == expected
            assert reopened.revision_chain_digest() == original_digest
            reopened.commit(reopened.revision, create=(Cell('work:after-archive', NULL_CELL_ID,
                NULL_CELL_ID, b'edit still works'),))
        assert opened == [], 'startup reads and verifies zero archived cells'
    print('ADOPT_ARCHIVED_STARTUP_CELLS', len(opened))
    assert _page_all(archive.trace_archive_path(content), sessions[sorted(old)[0]])


def test_idle_compaction_reclaims_partitioned_pages_and_preserves_archive(tmp_path, monkeypatch):
    import nodelang.universal_cell as kernel
    from nodelang.conversation_retention_maintenance import (
        compact_trace_journal, partition_archived_trace_batch)
    path = tmp_path / 'synthetic.sqlite3'
    with closing(sqlite3.connect(path)) as initial:
        initial.execute('PRAGMA auto_vacuum=INCREMENTAL')
    path, graph, old, recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path) + '.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='compact-court') as history:
        ident = sorted(old)[0]
        cell = old[ident]
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-38*86400))
            store.commit(store.revision, replace=(Cell(cell.id, cell.link0, cell.link1, b'x' * (2*1024*1024)),))
        history.initialize_trace_maintenance()
        connection, _ = store.sqlite_storage()
        before = connection.execute('PRAGMA page_count').fetchone()[0]
        _export(store, cold_path, sorted(old), sessions, history)
        partition_archived_trace_batch(store, history, cold_path, sorted(old), sessions, check=lambda: None)
        assert connection.execute('PRAGMA freelist_count').fetchone()[0] > 0
        events = []
        result = compact_trace_journal(store, check=lambda: None, on_progress=events.append)
        assert result['status'] in ('compacted','compacting')
        assert result['reclaimed_pages'] <= 128
        assert connection.execute('PRAGMA auto_vacuum').fetchone()[0] == 2
        assert connection.execute('PRAGMA page_count').fetchone()[0] < before
        assert set(store.snapshot().cells) == set(graph) | set(recent)
        assert _page_all(cold_path, sessions[ident])[ident]['atom'] == b'x' * (2*1024*1024)
        assert events
        print('ADOPT_COMPACTION', json.dumps(result))


def test_newly_eligible_lower_id_is_indexed_once_after_higher_ids(tmp_path, monkeypatch):
    path, _graph, old, _recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path)+".conversations.sqlite3")
    cold_path = archive.trace_archive_path(content)
    session = sessions[sorted(old)[0]]
    ids = sorted(ident for ident in old if sessions[ident] == session)
    lower, higher = ids[:4], ids[4:]
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id="adopt-court") as history:
        history.initialize_trace_maintenance()
        cell = old[higher[-1]]
        store.commit(store.revision, replace=(Cell(cell.id, cell.link0, cell.link1, b"first high text"),))
        for batch in (higher, lower, higher, lower):
            _export(store, cold_path, batch, sessions, history)
        indexed = history.archived_trace_session(session)
        assert indexed["cell_count"] == len(ids)
        assert indexed["content"].count("first high text") == 1
        assert indexed["content"].count(old[lower[0]].atom.decode()) == 1
        assert history._db.execute("SELECT COUNT(*) FROM trace_sessions WHERE session_id=?", (session,)).fetchone()[0] == 1


@pytest.mark.parametrize("tamper", ["current", "history", "index"])
def test_tampered_archive_is_refused_and_originals_remain(tmp_path, monkeypatch, tamper):
    path, _graph, old, _recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path)+".conversations.sqlite3")
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id="adopt-court") as history:
        history.initialize_trace_maintenance()
        connection, _lock = store.sqlite_storage()
        before = _rows(connection)
        _export(store, cold_path, sorted(old), sessions, history)
        ident = sorted(old)[0]
        session = sessions[ident]
        if tamper == "index":
            original_index = history.archived_trace_session(session)
            history._db.execute("UPDATE trace_sessions SET content='tampered' WHERE session_id=?", (session,))
            with pytest.raises(ValueError, match="integrity"):
                history.archived_trace_session(session)
            history._db.execute("UPDATE trace_sessions SET content=? WHERE session_id=?",
                (original_index["content"], session))
            atoms = json.loads(original_index["text_atoms"])
            atoms[next(iter(atoms))] += " tampered map only"
            history._db.execute("UPDATE trace_sessions SET text_atoms=? WHERE session_id=?",
                (json.dumps(atoms), session))
            with pytest.raises(ValueError, match="integrity"):
                history.archived_trace_session(session)
            with pytest.raises(ValueError, match="integrity"):
                _export(store, cold_path, sorted(old), sessions, history)
        else:
            table = "trace_current" if tamper == "current" else "trace_versions"
            with closing(sqlite3.connect(cold_path)) as cold:
                cold.execute(f"UPDATE {table} SET atom=? WHERE cell_id=?", (b"tampered", ident))
                cold.commit()
            if tamper == "current":
                with pytest.raises(archive.ArchiveConflict, match="verification"):
                    _page_all(cold_path, session)
            with pytest.raises(archive.ArchiveConflict, match="differs"):
                _export(store, cold_path, sorted(old), sessions)
        assert _rows(connection) == before


def test_cancelled_export_resumes_without_losing_original_cells(tmp_path, monkeypatch):
    path, _graph, old, _recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    cold_path = archive.trace_archive_path(Path(str(path)+".conversations.sqlite3"))
    with CellStore(path) as store:
        connection, _lock = store.sqlite_storage()
        before = _rows(connection)
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            if calls == 7:
                raise TimeoutError("court cancellation during cold export")
        with pytest.raises(TimeoutError, match="court cancellation"):
            _export(store, cold_path, sorted(old), sessions, check=cancelled)
        assert _rows(connection) == before
        _export(store, cold_path, sorted(old), sessions)
        assert _rows(connection) == before
        assert sum(len(_page_all(cold_path, session)) for session in {sessions[i] for i in old}) == len(old)


_CHILD_EXPORT = r'''
import json, sys, threading
from pathlib import Path
from nodelang import conversation_archive as archive
from nodelang.universal_cell import CellStore
path, cold_path, marker = map(Path, sys.argv[1:4])
selected = json.loads(sys.argv[4])
with CellStore(path) as store:
    connection, lock = store.sqlite_storage()
    with lock:
        cold, versions = archive.preserve_trace_batch(connection, cold_path,
            store.authority_identity, tuple(selected), selected, lambda: None)
        cold.close()
    marker.write_text(str(versions))
    threading.Event().wait()
'''


_CHILD_PARTITION = r'''
import json,sys,threading
from pathlib import Path
from nodelang import conversation_archive as archive
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
from nodelang.universal_cell import CellStore
from tests_replica.test_adopt_archive import _export
path,content,marker=map(Path,sys.argv[1:4])
selected=json.loads(sys.argv[4])
boundary=sys.argv[5]
def pause(stage):
    if stage==boundary:
        marker.write_text(stage)
        threading.Event().wait()
with CellStore(path,fault_injector=pause) as store, ConversationHistoryStore(content,instance_id='kill-partition') as history:
    history.initialize_trace_maintenance()
    cold=archive.trace_archive_path(content)
    _export(store,cold,tuple(selected),selected,history)
    partition_archived_trace_batch(store,history,cold,tuple(selected),selected,check=lambda:None)
raise AssertionError('partition did not reach its owned interruption boundary')
'''


@pytest.mark.parametrize('boundary', ['trace_partition_before_commit', 'trace_partition_committed'])
def test_hard_kill_during_live_partition_resumes_with_exact_custody(tmp_path, monkeypatch, boundary):
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
    path, graph, old, recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path) + '.conversations.sqlite3')
    cold = archive.trace_archive_path(content)
    marker = tmp_path / 'owned-partition-boundary.txt'
    selected = {ident: sessions[ident] for ident in old}
    process = subprocess.Popen([sys.executable, '-c', _CHILD_PARTITION, str(path), str(content),
        str(marker), json.dumps(selected), boundary], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            assert process.poll() is None, process.stderr.read().decode() if process.poll() is not None else ''
            assert time.monotonic() < deadline, 'owned child did not reach partition boundary'
            time.sleep(0.02)
        process.kill()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.communicate(timeout=10)
    # TerminateProcess can signal before Windows releases every file lock.
    # Retry only the exact child-owned fixture after confirmed process exit.
    with _open_after_killed_child(path, process) as store, ConversationHistoryStore(content, instance_id='kill-partition') as history:
        if boundary == 'trace_partition_before_commit':
            assert set(store.snapshot().cells) == set(graph) | set(old) | set(recent)
            partition_archived_trace_batch(store, history, cold, tuple(selected), selected, check=lambda: None)
        assert set(store.snapshot().cells) == set(graph) | set(recent)
        store.commit(store.revision, create=(Cell('work:resumed-edit', NULL_CELL_ID, NULL_CELL_ID, b'usable'),))
    assert sum(len(_page_all(cold, session)) for session in set(selected.values())) == len(old)


def _open_after_killed_child(path, process):
    assert process.poll() is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return CellStore(path)
        except DatabaseOwnerConflict:
            time.sleep(0.02)
    return CellStore(path)


def test_hard_kill_after_durable_batch_replays_exactly_once(tmp_path, monkeypatch):
    path, _graph, old, _recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    cold_path = archive.trace_archive_path(Path(str(path)+".conversations.sqlite3"))
    selected = {ident: sessions[ident] for ident in sorted(old)[:9]}
    marker = tmp_path/"batch-durable.txt"
    process = subprocess.Popen([sys.executable, "-c", _CHILD_EXPORT, str(path), str(cold_path),
        str(marker), json.dumps(selected)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic()+20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), process.communicate(timeout=1) if process.poll() is not None else "worker missed durable boundary"
        process.kill()  # Only this court-created synthetic exporter, as required by the brief.
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
    with CellStore(path) as store:
        before = dict(store.snapshot().cells)
        assert set(old) <= set(before)
        _export(store, cold_path, sorted(old), sessions)
        _export(store, cold_path, sorted(old), sessions)
        assert dict(store.snapshot().cells) == before
        with closing(sqlite3.connect(cold_path)) as cold:
            assert cold.execute("SELECT COUNT(*) FROM trace_current").fetchone()[0] == len(old)


def test_reopen_reads_zero_cold_archive_rows_until_demand(tmp_path, monkeypatch):
    path, _graph, old, _recent, sessions = _trace_fixture(tmp_path, monkeypatch)
    cold_path = archive.trace_archive_path(Path(str(path)+".conversations.sqlite3"))
    with CellStore(path) as store:
        _export(store, cold_path, sorted(old), sessions)
    opened = []
    connect = sqlite3.connect
    def observed(database, *args, **kwargs):
        if "agent-traces.sqlite3" in str(database):
            opened.append(str(database))
        return connect(database, *args, **kwargs)
    with monkeypatch.context() as observed_cold:
        observed_cold.setattr(sqlite3, "connect", observed)
        with CellStore(path) as store:
            assert set(old) <= set(store.snapshot().cells)
        assert opened == [], "startup must not open, read or verify archived rows"
        session = sessions[sorted(old)[0]]
        assert _page_all(cold_path, session)
        assert len(opened) > 0
    print("ADOPT_COLD_STARTUP_READS", 0)


@pytest.mark.parametrize("shared_payload", (False, True))
def test_real_content_owner_batches_legacy_conversion_and_answers_http_reads(tmp_path, monkeypatch, shared_payload):
    import hashlib
    from nodelang import commit_intent
    from nodelang import conversation_retention_maintenance as maintenance
    import nodelang.universal_cell as kernel
    from nodelang.cell_protocols import read_relation
    from nodelang.cell_value_graph import prepare_value_graph, read_value_graph
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_deliberation import (append_deliberation_entry, append_deliberation_value_entry,
        compose_deliberation_space, read_deliberation_space)
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from tests_replica.test_adopt_boot import _browser, _json

    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r"*32)
    keys.add_key("archhub.local.court-attestation", b"c"*32)
    server = ApplicationServer(universal_state_path=tmp_path/"legacy.sqlite3",
        conversation_history_path=tmp_path/"legacy.sqlite3.conversations.sqlite3",
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_brain_cloud_sync=False, live_watch=False).start()
    worker = None
    release = threading.Event()
    try:
        opener, _csrf = _browser(server)
        registry, store = server.universal_registry, server.universal_store
        authority = registry.authorization
        context = authority.session.context(minimum_validity_seconds=60)
        template = read_deliberation_space(store.snapshot(), registry.deliberation_protocol,
                                          registry.brain_control_ledger_root)
        with monkeypatch.context() as old_clock, commit_intent.declare(commit_intent.MIGRATION, actor="court",
                reason="synthetic actual pre-upgrade conversation control and payloads"):
            old_clock.setattr(kernel, "time", SimpleNamespace(time=lambda: time.time()-40*86400))
            room = compose_deliberation_space(store, registry.deliberation_protocol,
                space_id="app:deliberation:adopt-court", title="Existing user conversation",
                participant_roots=template.participant_roots, category_roots=template.category_roots,
                policy_root=template.policy_root, action_root=template.action_root,
                scope_roots=template.scope_roots, lifecycle_root=template.lifecycle_root,
                interface_root=template.interface_root, purpose_root=template.purpose_root,
                classification_root=template.classification_root, audience_root=template.audience_root,
                operational_state_root=template.operational_state_root)
            protected = Cell("work:protected-adopt-workflow", NULL_CELL_ID, NULL_CELL_ID, b"saved workflow")
            store.commit(store.revision, create=(protected,))
            work_value = {"saved": "work", "variants": [1, "kept", True]}
            prepared_work = prepare_value_graph(store.snapshot(), registry.value_graph_protocol,
                work_value, root_id="work:adopt-value")
            store.commit(store.revision, create=prepared_work.create, replace=prepared_work.replace)
            work_cells = {cell.id: cell for cell in prepared_work.create if cell.id == "work:adopt-value" or cell.id.startswith("work:adopt-value:")}
            entries = []
            ages = (60, 40, 30) * 4
            for index, days in enumerate(ages):
                stamp = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
                entry, _payload_root, _revision = append_deliberation_value_entry(
                    store, registry.deliberation_protocol, registry.value_graph_protocol,
                    space_root=room.root_id, actor_root=authority.subject_root,
                    category_root=template.category_roots[0], content=f"saved summary {index}",
                    payload={"message": index, "steps": ["first", "second"]},
                    payload_root=f"app:deliberation-payload:adopt-court-{index}",
                    idempotency_key=f"adopt-legacy-{index}", created_at=stamp,
                    authorization_protocol=authority.protocol, authentication_broker=authority.broker,
                    authentication_context=context)
                entries.append(entry)
            plain_prefix = "\x1eArchHub/conversation-trace/v1\n"+json.dumps(
                dict(summary="literal legacy text", payload={}, receipt=dict(trace_content_verified=True)))
            entries.append(append_deliberation_entry(store, registry.deliberation_protocol,
                space_root=room.root_id, actor_root=authority.subject_root,
                category_root=template.category_roots[0], content=plain_prefix,
                idempotency_key="adopt-plain-prefix-spoof", created_at=stamp,
                authorization_protocol=authority.protocol, authentication_broker=authority.broker,
                authentication_context=context))
        before_recent = set(store.snapshot().cells)
        with monkeypatch.context() as recent_clock, commit_intent.declare(commit_intent.MIGRATION,
                actor="court", reason="synthetic recent room remains readable during old trace retirement"):
            recent_clock.setattr(kernel, "time", SimpleNamespace(time=lambda: time.time()-86400))
            recent_room = compose_deliberation_space(store, registry.deliberation_protocol,
                space_id="app:deliberation:adopt-recent-court", title="Recent user conversation",
                participant_roots=template.participant_roots, category_roots=template.category_roots,
                policy_root=template.policy_root, action_root=template.action_root,
                scope_roots=template.scope_roots, lifecycle_root=template.lifecycle_root,
                interface_root=template.interface_root, purpose_root=template.purpose_root,
                classification_root=template.classification_root, audience_root=template.audience_root,
                operational_state_root=template.operational_state_root)
            recent_entry, _recent_payload, _recent_revision = append_deliberation_value_entry(
                store, registry.deliberation_protocol, registry.value_graph_protocol,
                space_root=recent_room.root_id, actor_root=authority.subject_root,
                category_root=template.category_roots[0], content="recent summary", payload={"recent": True},
                payload_root="app:deliberation-payload:adopt-recent-court",
                idempotency_key="adopt-recent-court", created_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
                authorization_protocol=authority.protocol, authentication_broker=authority.broker,
                authentication_context=context)
        if shared_payload:
            with commit_intent.declare(commit_intent.MIGRATION, actor="court",
                    reason="synthetic work retains an old registered payload"):
                shared_value_ref = Cell("work:adopt-shared-value", "app:deliberation-payload:adopt-court-0", NULL_CELL_ID, b"saved value reference")
                store.commit(store.revision, create=(shared_value_ref,))
        catalog_before = tuple(read_relation(store.snapshot(), registry.value_graph_protocol.root_id))
        catalog_cells, catalog_chain_by_incidence = {}, {}
        cursor = registry.value_graph_protocol.root_id
        while cursor != NULL_CELL_ID:
            chain = store.read(cursor)
            catalog_cells[chain.id] = chain
            catalog_cells[chain.link0] = store.read(chain.link0)
            catalog_chain_by_incidence[chain.link0] = chain.id
            cursor = chain.link1
        source_snapshot = store.snapshot()
        recent_cells = {ident: source_snapshot.cells[ident] for ident in source_snapshot.cells if ident not in before_recent}
        legacy_roots = (room.root_id, *(entry.root_id for entry in entries),
            *(f"app:deliberation-payload:adopt-court-{index}" for index in range(len(ages))))
        legacy_prefixes = tuple(root+":" for root in legacy_roots)
        legacy_cells = {ident: source_snapshot.cells[ident] for ident in source_snapshot.cells
            if ident in legacy_roots or ident.startswith(legacy_prefixes)}
        old_relation_ids, cursor = set(), room.root_id
        while cursor != NULL_CELL_ID:
            chain = source_snapshot.cells[cursor]
            legacy_cells[chain.id] = chain
            old_relation_ids.add(cursor)
            if chain.link0 != NULL_CELL_ID:
                old_relation_ids.add(chain.link0)
                legacy_cells[chain.link0] = source_snapshot.cells[chain.link0]
            cursor = chain.link1
        old_relation_ids.remove(room.root_id)
        expected_controls = tuple((member.role_id, member.participant_id)
            for member in read_relation(source_snapshot, room.root_id, budget=10000)
            if member.role_id != registry.deliberation_protocol.role("space-entry"))
        journal, _ = store.sqlite_storage()
        source_current = {ident: tuple(journal.execute(
            "SELECT cell_id,revision,link0,link1,atom FROM current_cells WHERE cell_id=?", (ident,)).fetchone())
            for ident in legacy_cells}
        source_versions = {ident: tuple(tuple(row) for row in journal.execute(
            "SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision", (ident,)))
            for ident in legacy_cells}
        catalog_current = {ident: tuple(journal.execute("SELECT cell_id,revision,link0,link1,atom FROM current_cells WHERE cell_id=?", (ident,)).fetchone()) for ident in catalog_cells}
        catalog_versions = {ident: tuple(tuple(row) for row in journal.execute("SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision", (ident,))) for ident in catalog_cells}
        # Record exact physical originals before any admitted historical projection.
        historical_scaffolds = set(catalog_chain_by_incidence.values()) | {room.root_id}
        original_scaffold_rows = {ident: tuple(tuple(row) for row in journal.execute(
            "SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions WHERE cell_id=? ORDER BY revision", (ident,)))
            for ident in set(catalog_cells) | {room.root_id}}
        historical_members = {root: {row[0]: tuple((member.role_id, member.participant_id)
            for member in read_relation(store.at(row[0]), root, budget=10000))
            for row in original_scaffold_rows[root]}
            for root in (registry.value_graph_protocol.root_id, room.root_id)}
        old_tail = next(member for member in catalog_before if member.participant_id == "app:deliberation-payload:adopt-court-11")
        assert journal.execute("SELECT r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id=?", (catalog_chain_by_incidence[old_tail.incidence_id],)).fetchone()[0] >= time.time()-20*86400
        shared_controls = [ident for ident in old_relation_ids
            if legacy_cells[ident].link0 == registry.deliberation_protocol.role("space-title")]
        assert len(shared_controls) == 1
        shared_incidence = shared_controls[0]
        external_work = Cell("work:shared-adopt-control", shared_incidence, NULL_CELL_ID, b"saved workflow reference")
        with commit_intent.declare(commit_intent.MIGRATION, actor="court",
                reason="synthetic required graph reference to exact old control incidence"):
            store.commit(store.revision, create=(external_work,))
        service = server.conversation_content
        server.last_user_action_monotonic = 0.0
        for _ in range(6000):
            prepared = maintenance.maintain_trace_families(service, authentication_context=context,
                max_cells=256, prepare_only=True)
            if prepared["status"] == "family-ready":
                break
        else:
            pytest.fail("bounded public family frontier failed to prewarm before registered conversion")
        trace_message = maintenance._trace_message
        def slow_payload(*args):
            time.sleep(0.075)
            return trace_message(*args)
        with monkeypatch.context() as slow:
            slow.setattr(maintenance, "_trace_message", slow_payload)
            first = service.maintain_legacy_traces(authentication_context=context,
                space_root=room.root_id, timeout_seconds=1.0)
        assert 0 < first["copied"] < len(entries), "default64 batch must commit a useful prefix before its deadline"
        assert service._history._db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?",
            (room.root_id,)).fetchone()[0] == first["copied"]
        ready, finished = threading.Event(), threading.Event()
        results, failures = [], []
        def background():
            try:
                for _ in range(300):
                    result = service.maintain_legacy_traces(authentication_context=context,
                        space_root=room.root_id, max_chain_cells=1)
                    results.append(result)
                    assert result["inspected"] <= 1
                    if result["copied"] >= 1 and not ready.is_set():
                        ready.set()
                        assert release.wait(15), "HTTP caller did not release the next idle batch"
                    if result["status"] in ("bound", "retirement-admission-required"):
                        break
                else:
                    raise AssertionError("bounded legacy cursor did not finish in 300 batches")
            except BaseException as error:
                failures.append(error)
            finally:
                finished.set()
                ready.set()
        worker = threading.Thread(target=background, name="adopt-court-idle-conversion")
        worker.start()
        assert ready.wait(20), "legacy conversion never reached its first durable batch"
        if failures:
            raise failures[0]
        assert not finished.is_set(), "HTTP read must occur while the background job remains active"
        started = time.monotonic()
        canvas = _json(opener, server, "/api/universal/canvas")
        read_seconds = time.monotonic()-started
        assert "viewport" in canvas and read_seconds < 10
        release.set()
        worker.join(timeout=30)
        assert not worker.is_alive(), "idle converter did not release the caller"
        if failures:
            raise failures[0]
        assert results[-1]["copied"] == len(entries)
        history = service._history
        rows = history._db.execute("SELECT id,content FROM messages WHERE conversation_id=? ORDER BY sequence",
                                   (room.root_id,)).fetchall()
        assert [row[0] for row in rows] == [entry.root_id for entry in entries]
        for index, row in enumerate(rows):
            if index == len(ages):
                assert row[1] == plain_prefix
                plain = history.get(room.root_id, row[0], principal=authority.subject_root, read_all=True)
                assert "trace_content_verified" not in plain
                continue
            prefix = "\x1eArchHub/conversation-trace/v1\n"
            assert row[1].startswith(prefix)
            envelope = json.loads(row[1][len(prefix):])
            assert envelope["summary"] == f"saved summary {index}"
            assert envelope["payload"] == {"message": index, "steps": ["first", "second"]}
            admitted = history.get(room.root_id, row[0], principal=authority.subject_root, read_all=True)
            assert admitted["trace_content_verified"] is True
        assert store.snapshot().cells[protected.id] == protected
        final = service.maintain_legacy_traces(authentication_context=context,
            space_root=room.root_id, max_chain_cells=1)
        assert final["copied"] == len(entries)
        assert history._db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?",
                                   (room.root_id,)).fetchone()[0] == len(entries)
        registered_ids = {row[0] for row in history._db.execute(
            "SELECT cell_id FROM trace_migration_cells WHERE conversation_id=? AND owned=1", (room.root_id,))}
        expected_retired = (registered_ids | old_relation_ids) - {shared_incidence}
        kept_payload = "app:deliberation-payload:adopt-court-0" if shared_payload else None
        if kept_payload:
            expected_retired -= {ident for ident in expected_retired if ident == kept_payload or ident.startswith(kept_payload+":")}
        removed_members = [member for member in catalog_before if member.participant_id.startswith("app:deliberation-payload:adopt-court-") and member.participant_id != kept_payload]
        removed_incidences = {member.incidence_id for member in removed_members}
        expected_catalog_retired = removed_incidences | {catalog_chain_by_incidence[ident] for ident in removed_incidences}
        expected_catalog_retired.discard(registry.value_graph_protocol.root_id)
        assert expected_retired and room.root_id not in expected_retired
        assert expected_retired <= set(legacy_cells), "retirement scope must be exact source-owned trace/scaffolding Cells"
        published_root = store.read(room.root_id)
        retired = 0
        peak_catalog_cache = 0
        cache_roots = cache_indexes = 0
        for _ in range(6000):
            batch = maintenance.maintain_trace_families(service, authentication_context=context, max_cells=256)
            retired += batch.get("moved", 0)
            cache = getattr(store, "_trace_registry_cache", None)
            if cache and cache["complete"]:
                measured = (sys.getsizeof(cache["roots"])+sys.getsizeof(cache["indexes"])
                    + sum(sys.getsizeof(key)+sys.getsizeof(value) for key, value in cache["roots"].items())
                    + sum(sys.getsizeof(value) for value in cache["indexes"]))
                peak_catalog_cache = max(peak_catalog_cache, measured)
                cache_roots = max(cache_roots, len(cache["roots"]))
                cache_indexes = max(cache_indexes, len(cache["indexes"]))
            if batch["status"] == "family-complete":
                break
        else:
            pytest.fail("bounded family retirement failed to complete after registered binding")
        assert expected_retired.isdisjoint(store.snapshot().cells), "verified published binding must release orphan old entries, chain and incidences"
        assert store.read(room.root_id) == published_root
        assert read_value_graph(store.snapshot(), registry.value_graph_protocol, "work:adopt-value") == work_value
        assert read_value_graph(store.snapshot(), registry.value_graph_protocol, "app:deliberation-payload:adopt-recent-court") == {"recent": True}
        assert all(store.read(ident) == cell for ident, cell in work_cells.items())
        if kept_payload:
            assert store.read(shared_value_ref.id) == shared_value_ref
            assert read_value_graph(store.snapshot(), registry.value_graph_protocol, kept_payload) == {"message": 0, "steps": ["first", "second"]}
        expected_catalog = tuple((member.role_id, member.participant_id, member.incidence_id) for member in catalog_before if member.incidence_id not in removed_incidences)
        assert tuple((member.role_id, member.participant_id, member.incidence_id) for member in read_relation(store.snapshot(), registry.value_graph_protocol.root_id)) == expected_catalog
        assert expected_catalog_retired.isdisjoint(store.snapshot().cells)
        for ident, cell in catalog_cells.items():
            if ident in expected_catalog_retired:
                continue
            current = store.read(ident)
            assert current.id == cell.id and current.atom == cell.atom
            if ident not in catalog_chain_by_incidence.values():
                assert current == cell
            elif ident != registry.value_graph_protocol.root_id:
                assert current.link0 == cell.link0
            projected = journal.execute("SELECT 1 FROM trace_projection_custody WHERE cell_id=? LIMIT 1", (ident,)).fetchone()
            if projected:
                assert ident in historical_scaffolds, "ordinary catalogue incidences cannot be projected"
            else:
                assert tuple(tuple(row) for row in journal.execute("SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision", (ident,)))[:len(catalog_versions[ident])] == catalog_versions[ident]
        assert store.read(protected.id) == protected
        assert store.read(external_work.id) == external_work
        assert tuple(journal.execute("SELECT cell_id,revision,link0,link1,atom FROM current_cells WHERE cell_id=?",
            (shared_incidence,)).fetchone()) == source_current[shared_incidence]
        assert tuple(tuple(row) for row in journal.execute(
            "SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision",
            (shared_incidence,))) == source_versions[shared_incidence]
        assert all(store.read(ident) == cell for ident, cell in recent_cells.items())
        assert all(store.read(ident) == cell for ident, cell in legacy_cells.items()
            if ident not in expected_retired and ident != room.root_id)
        assert tuple((member.role_id, member.participant_id)
            for member in read_relation(store.snapshot(), room.root_id, budget=10000)
            if member.role_id != registry.deliberation_protocol.role("space-content-store")) == expected_controls
        assert tuple(row[0] for row in journal.execute(
            "SELECT revision FROM cell_versions WHERE cell_id=? ORDER BY revision", (room.root_id,)))[:-1] == tuple(row[0] for row in source_versions[room.root_id])
        removed_payloads = {member.participant_id for member in removed_members}
        for root, versions in historical_members.items():
            for revision, original_members in versions.items():
                expected_members = tuple((role, target) for role, target in original_members
                    if (role != registry.deliberation_protocol.role("space-entry")
                        if root == room.root_id else target not in removed_payloads))
                assert tuple((member.role_id, member.participant_id)
                    for member in read_relation(store.at(revision), root, budget=10000)) == expected_members
        assert recent_entry.root_id in read_deliberation_space(store.snapshot(), registry.deliberation_protocol,
            recent_room.root_id).entry_roots
        cold_path = archive.trace_archive_path(service._path)
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            # Every changed retained historical row needs exact original cold
            # custody and both seals; unprojected rows remain physically equal.
            for ident, originals in original_scaffold_rows.items():
                if ident in expected_catalog_retired:
                    continue
                live = tuple(tuple(row) for row in journal.execute(
                    "SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions WHERE cell_id=? AND revision<=? ORDER BY revision",
                    (ident, originals[-1][0])))
                assert tuple(row[0] for row in live) == tuple(row[0] for row in originals)
                for original, current in zip(originals, live):
                    certificate = journal.execute("SELECT original_hash,live_hash FROM trace_projection_custody WHERE revision=? AND cell_id=?",
                        (original[0], ident)).fetchone()
                    if certificate is None:
                        assert current == original
                        continue
                    assert ident in historical_scaffolds
                    copied = cold.execute("SELECT revision,cell_id,link0,link1,atom,source_rowid,digest FROM trace_versions WHERE revision=? AND cell_id=?",
                        (original[0], ident)).fetchone()
                    assert copied is not None and tuple(copied[:6]) == original
                    assert copied[6] == archive._trace_digest(original)
                    assert tuple(certificate) == tuple(hashlib.sha256(repr(row).encode("utf-8")).hexdigest()
                        for row in (original, current))
            for ident in sorted(expected_catalog_retired):
                assert tuple(cold.execute("SELECT cell_id,revision,link0,link1,atom FROM trace_current WHERE cell_id=?", (ident,)).fetchone()) == catalog_current[ident]
                assert tuple(tuple(row) for row in cold.execute("SELECT revision,link0,link1,atom FROM trace_versions WHERE cell_id=? ORDER BY revision", (ident,))) == catalog_versions[ident]
                assert journal.execute("SELECT 1 FROM cell_versions WHERE cell_id=? LIMIT 1", (ident,)).fetchone() is None
            for ident in sorted(expected_retired):
                assert tuple(cold.execute("SELECT cell_id,revision,link0,link1,atom FROM trace_current WHERE cell_id=?", (ident,)).fetchone()) == source_current[ident]
                assert tuple(tuple(row) for row in cold.execute(
                    "SELECT revision,link0,link1,atom FROM trace_versions WHERE cell_id=? ORDER BY revision", (ident,))) == source_versions[ident]
                assert journal.execute("SELECT 1 FROM cell_versions WHERE cell_id=? LIMIT 1", (ident,)).fetchone() is None
        assert history._db.execute("SELECT id,content FROM messages WHERE conversation_id=? ORDER BY sequence",
            (room.root_id,)).fetchall() == rows
        print("ADOPT_REGISTERED_PARTITION", json.dumps(dict(old_entries=len(entries), old_scaffold=len(old_relation_ids),
            retired_current=len(expected_retired), retired_versions=sum(len(source_versions[ident]) for ident in expected_retired),
            moved=retired, recent_cells=len(recent_cells), shared_control_retained=1, graph_root_retained=True, catalog_retired=len(expected_catalog_retired), shared_payload=shared_payload,
            cache_roots=cache_roots, cache_indexes=cache_indexes, cache_approx_bytes=peak_catalog_cache, cache_measurement="getsizeof containers+keys+values, shared strings may counted twice")))
        assert getattr(store, "_trace_registry_cache", None) is None
        original_content = rows[0][1]
        try:
            history._db.execute("UPDATE messages SET content=? WHERE conversation_id=? AND id=?",
                (original_content+" tampered", room.root_id, rows[0][0]))
            with pytest.raises(ValueError, match="integrity"):
                history.get(room.root_id, rows[0][0], principal=authority.subject_root, read_all=True)
        finally:
            history._db.execute("UPDATE messages SET content=? WHERE conversation_id=? AND id=?",
                (original_content, room.root_id, rows[0][0]))
        try:
            history._db.execute("UPDATE trace_migration_messages SET structured=1 "
                "WHERE conversation_id=? AND message_id=?", (room.root_id, rows[-1][0]))
            with pytest.raises(ValueError, match="integrity"):
                history.get(room.root_id, rows[-1][0], principal=authority.subject_root, read_all=True)
        finally:
            history._db.execute("UPDATE trace_migration_messages SET structured=0 "
                "WHERE conversation_id=? AND message_id=?", (room.root_id, rows[-1][0]))
        spoof = history.append(room.root_id, author=authority.subject_root,
            content=prefix+json.dumps(dict(summary="client text", payload={},
                receipt=dict(trace_content_verified=True))), category=template.category_roots[0],
            message_id="ordinary-unsealed-prefix", idempotency_key="ordinary-unsealed-prefix")
        assert "trace_content_verified" not in history.get(room.root_id, spoof["id"],
            principal=authority.subject_root, read_all=True)
        print("ADOPT_BOUNDED_CONVERSION", json.dumps(dict(batches=len(results),
            copied=len(rows), first_default_batch_copied=first["copied"],
            http_read_seconds=read_seconds, final_status=final["status"])))
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=30)
        server.close()
