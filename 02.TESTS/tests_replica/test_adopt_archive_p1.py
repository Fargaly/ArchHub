"""Synthetic archive scale courts; never inspect an installed profile."""
from contextlib import closing
import json
import sqlite3

import pytest

from nodelang import conversation_archive as archive
from nodelang.conversation_history import ConversationHistoryStore
from tests_replica import test_adopt_archive as custody

isolated_profile = custody.isolated_profile


def _source():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE current_cells(cell_id TEXT PRIMARY KEY,revision INTEGER,link0 TEXT,link1 TEXT,atom BLOB)')
    connection.execute('CREATE TABLE cell_versions(revision INTEGER,cell_id TEXT,link0 TEXT,link1 TEXT,atom BLOB)')
    connection.execute('CREATE INDEX version_cell ON cell_versions(cell_id,revision)')
    return connection


def _add(source, identifier, atom):
    row = (identifier, 1, 'null', 'null', atom)
    source.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)', row)
    source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)', (1, identifier, 'null', 'null', atom))


def _preserve(source, path, ids):
    return archive.preserve_trace_batch(source, path, 'synthetic-authority',
        ids, dict.fromkeys(ids, 'synthetic-session'), lambda: None)


def test_receipt_batches_never_reread_total_text_or_recount_cold_session(tmp_path):
    path = tmp_path / 'cold.sqlite3'
    with closing(_source()) as source, ConversationHistoryStore(tmp_path / 'content.sqlite3',
            instance_id='synthetic-index') as history:
        history.initialize_trace_maintenance()
        _add(source, '000-text', b'actual conversation text')
        with closing(_preserve(source, path, ('000-text',))[0]) as cold:
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=path,
                cell_ids=('000-text',))
        denied = []

        def guard(operation, table, column, _database, _trigger):
            if operation == sqlite3.SQLITE_READ and table == 'trace_sessions' and column in (
                    'content', 'text_atoms', 'content_digest'):
                denied.append((table, column))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        history._db.set_authorizer(guard)
        for number in range(4):
            ids = tuple(f'{number+1:03d}-receipt-{i:03d}' for i in range(128))
            for identifier in ids:
                _add(source, identifier, b'')
            with closing(_preserve(source, path, ids)[0]) as cold:
                # A delta-scaled batch must not execute aggregate recounts.
                def no_count(operation, _table, function, _database, _trigger):
                    if operation == sqlite3.SQLITE_FUNCTION and function.lower() == 'count':
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                cold.set_authorizer(no_count)
                history.index_trace_archive(cold, ('synthetic-session',), archive_path=path, cell_ids=ids)
                history.index_trace_archive(cold, ('synthetic-session',), archive_path=path, cell_ids=ids)
        history._db.set_authorizer(None)
        assert denied == []
        indexed = history.archived_trace_session('synthetic-session')
        assert indexed['cell_count'] == 513
        assert indexed['content'] == 'actual conversation text'


def test_byte_selection_adapts_and_oversized_single_cell_progresses(tmp_path):
    with closing(_source()) as source:
        for identifier in ('a', 'b', 'c'):
            _add(source, identifier, b'x' * (3 * 1024 * 1024))
        assert archive.choose_trace_batch(source, ('a', 'b', 'c'), lambda: None) == ('a', 'b')
        _add(source, 'oversized', b'z' * (9 * 1024 * 1024))
        assert archive.choose_trace_batch(source, ('oversized', 'c'), lambda: None) == ('oversized',)
        with closing(_preserve(source, tmp_path / 'large.sqlite3', ('oversized',))[0]):
            pass
        page = archive.read_trace_archive(tmp_path / 'large.sqlite3', 'synthetic-session')
        assert page['cells'][0]['atom'] == b'z' * (9 * 1024 * 1024)
        assert page['next'] is None


def test_oversized_singleton_preservation_retains_all_versions(tmp_path):
    with closing(_source()) as source:
        _add(source, 'large-history', b'x' * (5 * 1024 * 1024))
        source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)',
            (2, 'large-history', 'null', 'null', b'y' * (5 * 1024 * 1024)))
        with closing(_preserve(source, tmp_path / 'versions.sqlite3', ('large-history',))[0]) as cold:
            assert cold.execute('SELECT SUM(length(atom)) FROM trace_versions').fetchone()[0] == 10 * 1024 * 1024


def test_archive_location_stays_at_original_profile_after_adoption(tmp_path):
    original = tmp_path / 'archhub-test.universal.sqlite3.conversations.sqlite3'
    adopted = tmp_path / 'unified-authority' / 'generations' / '71743447-6dd5-4050-bc4f-d228f7a1d91e' / 'authority.sqlite3.conversations.sqlite3'
    assert archive.archive_directory(adopted) == archive.archive_directory(original)
    assert archive.trace_archive_path(adopted) == archive.trace_archive_path(original)
    ordinary = tmp_path / 'other' / 'content.sqlite3'
    assert archive.archive_directory(ordinary) == ordinary.parent / 'Conversation archive'


def test_adaptive_selection_checks_cancellation():
    with closing(_source()) as source:
        _add(source, 'a', b'')
        def cancelled():
            raise TimeoutError('synthetic cancellation')
        with pytest.raises(TimeoutError, match='synthetic cancellation'):
            archive.choose_trace_batch(source, ('a',), cancelled)


def test_profile_relocation_keeps_archived_only_content_openable(tmp_path):
    old_profile = tmp_path / 'Synthetic-Old'
    new_profile = tmp_path / 'Synthetic-New'
    original = old_profile / 'legacy.sqlite3.conversations.sqlite3'
    generation = '71743447-6dd5-4050-bc4f-d228f7a1d91e'
    adopted = old_profile / 'unified-authority' / 'generations' / generation / 'authority.sqlite3.conversations.sqlite3'
    adopted.parent.mkdir(parents=True)
    (adopted.parents[2] / 'CURRENT').write_text(generation, encoding='ascii')
    (adopted.parent / 'migration.json').write_text(json.dumps(dict(
        format='archhub-application-journal-migration/v1', generation_id=generation,
        source_path=str(original).removesuffix('.conversations.sqlite3'))), encoding='utf-8')
    cold_path = archive.trace_archive_path(original)
    with closing(_source()) as source, ConversationHistoryStore(original,
            instance_id='synthetic-adopted') as history:
        history.initialize_trace_maintenance()
        _add(source, 'cold-only', b'text kept outside the live store')
        with closing(_preserve(source, cold_path, ('cold-only',))[0]) as cold:
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=cold_path,
                cell_ids=('cold-only',))
    original.rename(adopted)
    relative = adopted.relative_to(old_profile)
    assert old_profile.parent.resolve() == new_profile.parent.resolve() == tmp_path.resolve()
    old_profile.rename(new_profile)
    adopted = new_profile / relative
    with ConversationHistoryStore(adopted, instance_id='synthetic-adopted', create=False) as history:
        indexed = history.archived_trace_session('synthetic-session')
        assert indexed['content'] == 'text kept outside the live store'
        assert archive.trace_archive_path(adopted) == new_profile / 'Conversation archive' / archive.TRACE_ARCHIVE_NAME
        assert archive.read_trace_archive(archive.trace_archive_path(adopted),
            'synthetic-session')['cells'][0]['id'] == 'cold-only'


def test_empty_retry_detects_projection_tamper_without_losing_cold_custody(tmp_path):
    path = tmp_path / 'tamper.sqlite3'
    with closing(_source()) as source, ConversationHistoryStore(tmp_path / 'content.sqlite3',
            instance_id='synthetic-tamper') as history:
        history.initialize_trace_maintenance()
        _add(source, 'a-text', b'original text')
        _add(source, 'b-receipt', b'')
        with closing(_preserve(source, path, ('a-text', 'b-receipt'))[0]) as cold:
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=path,
                cell_ids=('a-text', 'b-receipt'))
            history._db.execute("UPDATE trace_sessions SET content='tampered' WHERE session_id='synthetic-session'")
            with pytest.raises(ValueError, match='integrity'):
                history.index_trace_archive(cold, ('synthetic-session',), archive_path=path,
                    cell_ids=('b-receipt',))
        assert archive.read_trace_archive(path, 'synthetic-session')['cells'][0]['atom'] == b'original text'


def test_family_partition_preserves_workflow_and_its_transitive_trace_dependencies(tmp_path, monkeypatch):
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
    from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID
    path, graph, old, recent, sessions = custody._trace_fixture(tmp_path, monkeypatch)
    content = path.with_suffix('.sqlite3.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    protected_session = sessions[sorted(old)[0]]
    protected = {ident for ident in old if sessions[ident] == protected_session}
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='family-protection') as history:
        workflow = Cell('work:required-workflow', max(protected), NULL_CELL_ID, b'required workflow')
        store.commit(store.revision, create=(workflow,))
        history.initialize_trace_maintenance()
        custody._export(store, cold_path, sorted(old), sessions, history)
        before = dict(store.snapshot().cells)
        with pytest.raises(InvalidCell, match='dependencies'):
            partition_archived_trace_batch(store, history, cold_path, sorted(old), sessions, check=lambda: None)
        assert dict(store.snapshot().cells) == before
        selected = sorted(set(old) - protected)
        assert partition_archived_trace_batch(store, history, cold_path, selected, sessions, check=lambda: None) == len(selected)
        assert set(store.snapshot().cells) == set(graph) | set(recent) | protected | {workflow.id}
        assert store.read(workflow.id) == workflow
        assert all(store.read(ident) == old[ident] for ident in protected)


def test_family_inventory_resumes_bounded_pages_and_refuses_recent_control_cells(tmp_path, monkeypatch):
    from nodelang.conversation_retention_maintenance import _advance_family_inventory, partition_archived_trace_batch
    from nodelang.universal_cell import CellStore, InvalidCell
    path, _graph, old, recent, sessions = custody._trace_fixture(tmp_path, monkeypatch)
    content = path.with_suffix('.sqlite3.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store:
        with ConversationHistoryStore(content, instance_id='family-resume') as history:
            history.initialize_trace_maintenance()
            first = _advance_family_inventory(store, history, lambda: None, 3)
            assert first['inspected'] == 3
            cursor = history._db.execute('SELECT cursor FROM trace_family_state').fetchone()[0]
        with ConversationHistoryStore(content, instance_id='family-resume', create=False) as history:
            assert history._db.execute('SELECT cursor FROM trace_family_state').fetchone()[0] == cursor
            for _ in range(100):
                result = _advance_family_inventory(store, history, lambda: None, 3)
                assert result['inspected'] <= 3
                if result['status'] == 'family-ready':
                    break
            else:
                pytest.fail('bounded family inventory did not reach export')
            custody._export(store, cold_path, sorted(recent), sessions, history)
            before = dict(store.snapshot().cells)
            with pytest.raises(InvalidCell, match='inactive session'):
                partition_archived_trace_batch(store, history, cold_path, sorted(recent), sessions, check=lambda: None)
            with pytest.raises(InvalidCell, match='graph and control'):
                partition_archived_trace_batch(store, history, cold_path, ('work:nodes',),
                    {'work:nodes': 'work:nodes'}, check=lambda: None)
            assert dict(store.snapshot().cells) == before
            assert set(old) <= set(before)


@pytest.mark.parametrize('table', ('trace_current', 'trace_versions'))
def test_partition_refuses_tampered_cold_digest_before_live_transfer(tmp_path, monkeypatch, table):
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
    from nodelang.universal_cell import CellStore
    path, _graph, old, _recent, sessions = custody._trace_fixture(tmp_path, monkeypatch)
    content = path.with_suffix('.sqlite3.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='cold-digest') as history:
        history.initialize_trace_maintenance()
        custody._export(store, cold_path, sorted(old), sessions, history)
        with closing(sqlite3.connect(cold_path)) as cold:
            cold.execute('UPDATE '+table+' SET digest=? WHERE cell_id=?', ('0'*64, sorted(old)[0]))
            cold.commit()
        before = dict(store.snapshot().cells)
        with pytest.raises(archive.ArchiveConflict, match='custody digest'):
            partition_archived_trace_batch(store, history, cold_path, sorted(old), sessions, check=lambda: None)
        assert dict(store.snapshot().cells) == before


def test_registered_old_entry_can_archive_despite_a_recent_entry_in_same_room(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import time
    import nodelang.universal_cell as kernel
    from nodelang.conversation_retention_maintenance import _trace_cell_digest, partition_archived_trace_batch
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    path = tmp_path / 'registered.sqlite3'
    content = path.with_suffix('.sqlite3.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    room = 'app:workshop:conversation:synthetic'
    old = Cell(room+':entry:old-payload', NULL_CELL_ID, NULL_CELL_ID, b'old indexed text')
    recent = Cell(room+':entry:recent-payload', NULL_CELL_ID, NULL_CELL_ID, b'recent work stays readable')
    old_at = time.time()-40*86400
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='registered-family') as history:
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old_at))
            store.commit(store.revision, create=(old,))
        store.commit(store.revision, create=(recent,))
        history.initialize_trace_maintenance()
        history.ensure_conversation(room)
        with history._transaction(write=True):
            history._db.execute('INSERT INTO trace_migrations(conversation_id,source_authority,source_revision,delta_cell,cursor,controls,state) VALUES(?,?,?,?,?,?,?)',
                (room, store.authority_identity, store.revision, room, '', '[]', 'bound'))
            for cell, activity in ((old, old_at), (recent, time.time())):
                history._db.execute('INSERT INTO trace_migration_cells(conversation_id,cell_id,digest,owned,activity_at) VALUES(?,?,?,1,?)',
                    (room, cell.id, _trace_cell_digest(cell), activity))
        custody._export(store, cold_path, (old.id,), {old.id: room}, history)
        assert partition_archived_trace_batch(store, history, cold_path, (old.id,),
            {old.id: room}, check=lambda: None) == 1
        assert old.id not in store.snapshot().cells
        assert store.read(recent.id) == recent
        assert history.archived_trace_session(room)['content'] == 'old indexed text'
        assert archive.read_trace_archive(cold_path, room)['cells'][0]['atom'] == old.atom


def test_default_cursor_empty_retry_refuses_tampered_prior_projection(tmp_path):
    path = tmp_path / 'empty-retry.sqlite3'
    with closing(_source()) as source, ConversationHistoryStore(tmp_path / 'content.sqlite3',
            instance_id='empty-default-retry') as history:
        history.initialize_trace_maintenance()
        _add(source, 'a-text', b'prior indexed text')
        with closing(_preserve(source, path, ('a-text',))[0]) as cold:
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=path)
            # The ordered cursor has no new rows on either retry.
            history.index_trace_archive(cold, ('synthetic-session',), archive_path=path)
            history._db.execute("UPDATE trace_sessions SET content='tampered' WHERE session_id='synthetic-session'")
            with pytest.raises(ValueError, match='integrity'):
                history.index_trace_archive(cold, ('synthetic-session',), archive_path=path)
        assert archive.read_trace_archive(path, 'synthetic-session')['cells'][0]['atom'] == b'prior indexed text'


def test_fresh_graph_binding_does_not_reset_old_obsolete_trace_age(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import time
    import nodelang.universal_cell as kernel
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    path = tmp_path / 'fresh-binding.sqlite3'
    content = path.with_suffix('.sqlite3.conversations.sqlite3')
    room = 'app:workshop:conversation:old-room'
    old = Cell(room+':chain:0000', NULL_CELL_ID, NULL_CELL_ID, b'old conversation trace')
    control = Cell(room, NULL_CELL_ID, NULL_CELL_ID, b'fresh content binding')
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='fresh-binding') as history:
        old_at = time.time()-40*86400
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old_at))
            store.commit(store.revision, create=(old,))
        store.commit(store.revision, create=(control,))
        history.initialize_trace_maintenance()
        cold_path = archive.trace_archive_path(content)
        custody._export(store, cold_path, (old.id,), {old.id: room}, history)
        assert partition_archived_trace_batch(store, history, cold_path, (old.id,),
            {old.id: room}, check=lambda: None) == 1
        assert old.id not in store.snapshot().cells
        assert store.read(control.id) == control
        assert archive.read_trace_archive(cold_path, room)['cells'][0]['atom'] == old.atom


def test_workshop_mailbox_table_does_not_block_trace_archive(tmp_path):
    # The founder's store: the Workshop mailbox added workshop_declarations to the
    # conversations file, and idle archival stopped at "unknown retention source schema objects".
    with ConversationHistoryStore(tmp_path / 'content.sqlite3', instance_id='mailbox-presence') as history:
        with history._transaction(write=True):
            history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                                "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
        history.initialize_trace_maintenance()
