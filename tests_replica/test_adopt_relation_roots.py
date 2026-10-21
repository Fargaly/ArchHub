"""Real relation roots must not make orphan trace scaffolding immortal."""
import json
import time
from types import SimpleNamespace

import pytest

from nodelang import conversation_archive as archive, universal_cell as kernel
from nodelang.cell_protocols import compose_relation_cells, read_relation
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.conversation_retention_maintenance import partition_archived_trace_batch
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID, Snapshot
from tests_replica import test_adopt_archive as custody


@pytest.mark.parametrize('root,session', [
    ('app:agent-session:typed:view-receipt', 'app:agent-session:typed'),
    ('app:workshop:typed:entry:one', 'app:workshop:typed'),
    ('app:baboom-session:typed:entry:one', 'app:baboom-session:typed'),
])
@pytest.mark.parametrize('required_by_workflow', [False, True])
def test_source_composed_old_relation_root_transfers_or_preserves_required_graph(
        tmp_path, monkeypatch, root, session, required_by_workflow):
    path, content = tmp_path / 'live.sqlite3', tmp_path / 'content.sqlite3'
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='typed-root') as history:
        graph = tuple(Cell('work:' + name, NULL_CELL_ID, NULL_CELL_ID, name.encode())
                      for name in ('role-a', 'role-b', 'value-a', 'value-b'))
        store.commit(store.revision, create=graph)
        relation = compose_relation_cells((('work:role-a', 'work:value-a'),
            ('work:role-b', 'work:value-b'), ('work:role-a', 'work:value-b')), relation_id=root)
        old_time = time.time() - 40 * 86400
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old_time))
            store.commit(store.revision, create=relation.cells)
        original = read_relation(store.snapshot(), root)
        if required_by_workflow:
            store.commit(store.revision, create=(Cell('work:required-workflow', root,
                NULL_CELL_ID, b'required graph dependency'),))
        history.initialize_trace_maintenance()
        identifiers = tuple(sorted(cell.id for cell in relation.cells))
        sessions = dict.fromkeys(identifiers, session)
        custody._export(store, cold_path, identifiers, sessions, history)
        before = dict(store.snapshot().cells)
        if required_by_workflow:
            with pytest.raises(InvalidCell, match='dependencies'):
                partition_archived_trace_batch(store, history, cold_path, identifiers,
                    sessions, check=lambda: None)
            assert dict(store.snapshot().cells) == before
            assert read_relation(store.snapshot(), root) == original
        else:
            assert partition_archived_trace_batch(store, history, cold_path, identifiers,
                sessions, check=lambda: None) == len(identifiers)
            assert len(store.snapshot().cells) == len(graph) + 1
            assert not set(identifiers) & set(store.snapshot().cells)
            page = archive.read_trace_archive(cold_path, session)
            archived = {row['id']: Cell(row['id'], row['link0'], row['link1'], row['atom'])
                        for row in page['cells']}
            requested = Snapshot(store.revision, {**dict(store.snapshot().cells), **archived})
            assert read_relation(requested, root) == original
            assert history.archived_trace_session(session)['cell_count'] == len(identifiers)
            print('ADOPT_TYPED_RELATION_LIVE', json.dumps(dict(graph=len(graph)+1,
                recent=0, archived=len(identifiers), live=len(store.snapshot().cells))))


@pytest.mark.parametrize('identifier', [
    'app:agent-session:x:view-receipt-settings',
    'app:agent-session:x:view-receipt:arbitrary-workflow-settings',
    'app:agent-session:x:scope-receipt:chain:0:settings',
    'app:agent-session:x:close-receipt:incidence:settings',
    'app:agent-session:x:view-receiptchain:1',
    'app:agent-session:x:view-receipt::chain:1',
    'app:workshop:x:entry:one:settings',
    'app:baboom-session:x:entry:',
])
def test_similarly_named_graph_controls_cannot_be_partitioned(tmp_path, monkeypatch, identifier):
    path, content = tmp_path / 'live.sqlite3', tmp_path / 'content.sqlite3'
    cold_path = archive.trace_archive_path(content)
    with CellStore(path) as store, ConversationHistoryStore(content, instance_id='graph-controls') as history:
        control = Cell(identifier, NULL_CELL_ID, NULL_CELL_ID, b'protected work settings')
        old_time = time.time() - 40 * 86400
        with monkeypatch.context() as clock:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: old_time))
            store.commit(store.revision, create=(control,))
        history.initialize_trace_maintenance()
        sessions = {identifier: 'app:agent-session:x'}
        custody._export(store, cold_path, (identifier,), sessions, history)
        with pytest.raises(InvalidCell, match='graph and control'):
            partition_archived_trace_batch(store, history, cold_path, (identifier,),
                sessions, check=lambda: None)
        assert store.read(identifier) == control
