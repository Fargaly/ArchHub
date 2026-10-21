"""Independent RESUME4 courts: edited boot and sidecar-free 2230 rollback."""
from contextlib import closing, contextmanager
import importlib.util
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import unquote

import pytest

from nodelang import conversation_archive as archive
from nodelang import universal_cell as kernel
from nodelang.conversation_history import ConversationHistoryStore
from tests_replica import test_adopt_archive as custody
from tests_replica.test_adopt_archive_identity import _retire


@contextmanager
def _rollback_kernel():
    revision = 'e41d56aa'
    source = subprocess.check_output(
        ['git', 'show', revision + ':01.APP/nodelang/universal_cell.py'],
        cwd=Path(__file__).resolve().parents[2])
    name = 'nodelang._adopt_review_2230_kernel'
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(source, revision + ':01.APP/nodelang/universal_cell.py', 'exec'), module.__dict__)
        yield module
    finally:
        sys.modules.pop(name, None)


def _bytes(store):
    return {cell.id: (cell.link0, cell.link1, cell.atom)
            for cell in store.snapshot().cells.values()}


def test_ordinary_edits_after_archive_reopen_without_full_partition_reproof(tmp_path, monkeypatch):
    path, cold_path = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    with kernel.CellStore(path) as store:
        retired = _retire(store, cold_path)
        edited = set()
        for number in range(7):
            cell = kernel.Cell(f'work:ordinary-edit:{number}', kernel.NULL_CELL_ID,
                               kernel.NULL_CELL_ID, str(number).encode())
            store.commit(store.revision, create=(cell,))
            edited.add(cell.id)
        expected_revision = store.revision

    full_reproofs, validated, cold_reads, statements = [], [], [], []
    original_reproof = kernel._SqliteJournal._partition_chain_digest
    original_validate = kernel._validate_cell
    original_connect = sqlite3.connect

    def reproof(journal, through):
        full_reproofs.append(through)
        return original_reproof(journal, through)

    def validate(cell):
        validated.append(cell.id)
        return original_validate(cell)

    def connect(database, *args, **kwargs):
        if cold_path.as_posix().casefold() in unquote(str(database)).replace('\\', '/').casefold():
            cold_reads.append(str(database))
        connection = original_connect(database, *args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(kernel._SqliteJournal, '_partition_chain_digest', reproof)
    monkeypatch.setattr(kernel, '_validate_cell', validate)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    with kernel.CellStore(path) as reopened:
        assert reopened.revision == expected_revision
        assert set(reopened.snapshot().cells) == edited | {kernel.NULL_CELL_ID}
    assert full_reproofs == [], 'ordinary edits must not invalidate the archived-prefix proof'
    assert set(validated) <= edited | {kernel.NULL_CELL_ID}
    assert retired.id not in validated
    assert len(validated) <= len(edited) + 1, 'boot may validate only the committed delta'
    assert cold_reads == []
    prefix_counts = [statement for statement in statements if re.search(
        r'\bSELECT\s+COUNT\(\*\)\s+FROM\s+cell_versions\b.*\bWHERE\s+revision\s*<=',
        ' '.join(statement.split()), re.IGNORECASE)]
    assert prefix_counts == [], 'boot must count the delta rather than enumerate the covered index prefix'
    print('ADOPT_EDITED_BOOT', dict(edits=len(edited), full_reproofs=len(full_reproofs),
                                    validated_cells=len(validated), archived_reads=len(cold_reads)))


def test_partitioned_flat_journal_2230_opens_and_saves_without_any_sidecar(tmp_path, monkeypatch):
    path = tmp_path / 'archhub-test.universal.sqlite3'
    cold_path = tmp_path / 'cold.sqlite3'
    with kernel.CellStore(path) as store:
        graph = kernel.Cell('work:graph', kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'founder work')
        store.commit(store.revision, create=(graph,))
        original = _retire(store, cold_path)
        expected = _bytes(store)
        original_head = store.revision_chain_digest()
        archived_revision = store.revision
    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        Path(str(path) + suffix).unlink(missing_ok=True)
    assert not Path(str(path) + '.accelerators').exists()

    with _rollback_kernel() as old:
        with old.CellStore(path) as previous:
            assert previous.revision == archived_revision
            assert _bytes(previous) == expected
            marker = old.Cell('work:2230-edit', old.NULL_CELL_ID, old.NULL_CELL_ID, b'2230 saved')
            previous.commit(previous.revision, create=(marker,))
            assert previous.snapshot().cells[marker.id].atom == marker.atom

    expected[marker.id] = (marker.link0, marker.link1, marker.atom)
    new_marker = kernel.Cell(marker.id, marker.link0, marker.link1, marker.atom)
    expected_head = kernel.revision_chain_digest_step(
        bytes.fromhex(original_head), archived_revision + 1, (new_marker,)).hex()
    cold_reads = []
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if cold_path.as_posix().casefold() in unquote(str(database)).replace('\\', '/').casefold():
            cold_reads.append(str(database))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connect)
    with kernel.CellStore(path) as reopened:
        assert _bytes(reopened) == expected
        assert reopened.revision_chain_digest() == expected_head
        assert cold_reads == [], 'rollback recovery must not open archived Cells during boot'
        current_edit = kernel.Cell('work:readopt-edit', kernel.NULL_CELL_ID,
                                   kernel.NULL_CELL_ID, b'ADOPT saved')
        reopened.commit(reopened.revision, create=(current_edit,))
        assert reopened.read(current_edit.id) == current_edit
    with kernel.CellStore(path) as twice:
        assert twice.read(current_edit.id) == current_edit
        assert twice.read(graph.id) == graph
    assert cold_reads == []
    page = archive.read_trace_archive(cold_path, 'identity-session')
    assert [(cell['id'], cell['atom']) for cell in page['cells']] == [(original.id, original.atom)]
    assert cold_reads, 'archived content remains openable on demand'
    print('ADOPT_ROLLBACK_PARTITION', dict(kernel='e41d56aa', graph_cells=len(expected),
                                         archived_cells=len(page['cells']), saved_edits=2))


def test_historical_work_incidence_retains_trace_dependency_for_sidecar_free_2230(tmp_path, monkeypatch):
    from nodelang.conversation_retention_maintenance import partition_archived_trace_batch

    path, graph, old, recent, sessions = custody._trace_fixture(tmp_path, monkeypatch)
    content = Path(str(path) + '.conversations.sqlite3')
    cold_path = archive.trace_archive_path(content)
    protected_session = sessions[sorted(old)[0]]
    protected = {identifier for identifier in old if sessions[identifier] == protected_session}
    dependency = max(protected)
    with kernel.CellStore(path) as store, ConversationHistoryStore(
            content, instance_id='historical-incidence-review') as history:
        historical = kernel.Cell('work:historical-workflow', dependency,
                                 kernel.NULL_CELL_ID, b'required historical workflow')
        historical_revision = store.commit(store.revision, create=(historical,))
        current = kernel.Cell(historical.id, kernel.NULL_CELL_ID,
                              kernel.NULL_CELL_ID, b'current workflow no longer links trace')
        store.commit(store.revision, replace=(current,))
        history.initialize_trace_maintenance()
        custody._export(store, cold_path, sorted(old), sessions, history)
        before = _bytes(store)
        with pytest.raises(kernel.InvalidCell, match='dependencies'):
            partition_archived_trace_batch(store, history, cold_path, sorted(old),
                                           sessions, check=lambda: None)
        assert _bytes(store) == before
        selected = sorted(set(old) - protected)
        assert partition_archived_trace_batch(store, history, cold_path, selected,
                                             sessions, check=lambda: None) == len(selected)
        assert set(store.snapshot().cells) == set(graph) | set(recent) | protected | {current.id}
        assert store.read(historical.id, revision=historical_revision) == historical
        assert store.read(dependency, revision=historical_revision) == old[dependency]
        expected = _bytes(store)

    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        Path(str(path) + suffix).unlink(missing_ok=True)
    with _rollback_kernel() as previous_kernel:
        with previous_kernel.CellStore(path) as previous:
            assert _bytes(previous) == expected
            assert previous.read(historical.id, revision=historical_revision).link0 == dependency
            assert previous.read(dependency, revision=historical_revision).atom == old[dependency].atom
            marker = previous_kernel.Cell('work:historical-rollback-saved', previous_kernel.NULL_CELL_ID,
                                          previous_kernel.NULL_CELL_ID, b'rollback history remains open')
            previous.commit(previous.revision, create=(marker,))
            assert previous.read(marker.id).atom == marker.atom
    with kernel.CellStore(path) as reopened:
        assert reopened.read(marker.id).atom == marker.atom
        assert reopened.read(current.id) == current
        assert reopened.read(historical.id, revision=historical_revision) == historical
    print('ADOPT_HISTORICAL_INCIDENCE', dict(protected=len(protected), archived=len(selected),
                                           historical_revision=historical_revision, kernel='e41d56aa'))


def _relation_at(store, root, revision, null_id):
    members, visited = [], set()
    cursor = root
    while cursor != null_id:
        assert cursor not in visited, 'historical catalog must stay acyclic'
        visited.add(cursor)
        chain = store.read(cursor, revision=revision)
        assert chain.atom == b''
        if chain.link0 == null_id:
            assert chain.link1 == null_id, 'empty catalog cannot retain a dangling tail'
            break
        incidence = store.read(chain.link0, revision=revision)
        assert incidence.atom == b''
        store.read(incidence.link0, revision=revision)
        store.read(incidence.link1, revision=revision)
        members.append((incidence.link0, incidence.link1))
        cursor = chain.link1
    return members


def test_native_registry_retirement_preserves_historical_work_and_cold_root_versions(tmp_path, monkeypatch):
    from nodelang import conversation_retention_maintenance as maintenance

    with custody._registry_court(tmp_path, monkeypatch) as (
            store, history, service, old, child, work, room):
        path = Path(store.database_path)
        root = service._owner.universal_registry.value_graph_protocol.root_id
        role = service._owner.universal_registry.value_graph_protocol.role('value-member')
        original_root = store.read(root)
        original_work_chain = store.read(original_root.link1)
        work_incidence = store.read(original_work_chain.link0)
        historical_revision = store.revision
        assert (role, work.id) in _relation_at(store, root, historical_revision, kernel.NULL_CELL_ID)
        connection, _lock = store.sqlite_storage()
        original_versions = [tuple(row) for row in connection.execute(
            'SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions '
            'WHERE cell_id=? ORDER BY revision', (root,))]

        custody._registry_until(store, history, service, 'ordinary')
        live_root = store.read(root)
        while maintenance._advance_family_inventory(store, history, lambda: None, 1)['status'] != 'family-ready':
            pass
        cold_path = archive.trace_archive_path(service._path)
        selected = (old.id, child.id, original_root.link0, original_work_chain.id)
        custody._export(store, cold_path, (old.id, child.id),
                        dict.fromkeys((old.id, child.id), room), history)
        assert maintenance.partition_archived_trace_batch(store, history, cold_path, selected,
            dict.fromkeys(selected, room), check=lambda: None) == len(selected)
        assert set(selected).isdisjoint(store.snapshot().cells)
        assert store.read(root) == live_root
        assert store.read(work.id) == work
        assert store.read(work_incidence.id) == work_incidence
        assert _relation_at(store, root, historical_revision, kernel.NULL_CELL_ID) == [(role, work.id)]
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            copied = [tuple(row) for row in cold.execute(
                'SELECT revision,cell_id,link0,link1,atom,source_rowid FROM trace_versions '
                'WHERE cell_id=? ORDER BY revision', (root,))]
            assert copied == original_versions, 'every replaced catalog version needs exact cold custody'
        expected = _bytes(store)

    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        Path(str(path) + suffix).unlink(missing_ok=True)
    cold_reads = []
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if cold_path.as_posix().casefold() in unquote(str(database)).replace('\\', '/').casefold():
            cold_reads.append(str(database))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connect)
    with _rollback_kernel() as previous_kernel:
        with previous_kernel.CellStore(path) as previous:
            assert _bytes(previous) == expected
            assert _relation_at(previous, root, historical_revision, previous_kernel.NULL_CELL_ID) == [(role, work.id)]
            assert previous.read(work.id).atom == work.atom
            assert cold_reads == [], '2230 must prove the live projection without opening cold Cells'
            marker = previous_kernel.Cell('work:native-registry-rollback', previous_kernel.NULL_CELL_ID,
                                          previous_kernel.NULL_CELL_ID, b'2230 saved after native retirement')
            previous.commit(previous.revision, create=(marker,))
    with kernel.CellStore(path) as reopened:
        assert reopened.read(marker.id).atom == marker.atom
        assert reopened.read(root) == live_root
        assert _relation_at(reopened, root, historical_revision, kernel.NULL_CELL_ID) == [(role, work.id)]
    assert cold_reads == []
    page = archive.read_trace_archive(cold_path, room)
    assert {row['id']: row['atom'] for row in page['cells']}[old.id] == old.atom
    assert cold_reads
    print('ADOPT_NATIVE_ROLLBACK', dict(kernel='e41d56aa', retired=len(selected),
                                      original_root_versions=len(original_versions), preserved_work=work.id))


def _preserve_review_version(store, cold_path, revision, identifier):
    connection, _lock = store.sqlite_storage()
    row = tuple(connection.execute('SELECT revision,cell_id,link0,link1,atom,rowid '
                                   'FROM cell_versions WHERE revision=? AND cell_id=?',
                                   (revision, identifier)).fetchone())
    with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=True)) as cold:
        cold.execute('INSERT INTO trace_versions VALUES(?,?,?,?,?,?,?)', (*row, archive._trace_digest(row)))
        cold.commit()
    return kernel.Cell(row[1], row[2], row[3], bytes(row[4]))


@pytest.mark.parametrize('invalid', ('current-version', 'duplicate-version', 'tampered-original'))
def test_kernel_projection_refuses_invalid_selection_without_mutation(tmp_path, monkeypatch, invalid):
    with custody._registry_court(tmp_path, monkeypatch) as (
            store, history, service, _old, _child, _work, _room):
        custody._registry_until(store, history, service, 'ordinary')
        root = service._owner.universal_registry.value_graph_protocol.root_id
        connection, _lock = store.sqlite_storage()
        revision = connection.execute(
            'SELECT MAX(revision) FROM cell_versions WHERE cell_id=?' if invalid == 'current-version'
            else 'SELECT MIN(revision) FROM cell_versions WHERE cell_id=?', (root,)).fetchone()[0]
        cold_path = archive.trace_archive_path(service._path)
        old = _preserve_review_version(store, cold_path, revision, root)
        new = kernel.Cell(root, kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, old.atom)
        projections = ((revision, old, new),)
        if invalid == 'duplicate-version':
            projections = projections * 2
        if invalid == 'tampered-original':
            with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=True)) as cold:
                cold.execute('UPDATE trace_versions SET atom=? WHERE revision=? AND cell_id=?',
                             (b'corrupted original', revision, root))
                cold.commit()
        before = custody._rows(connection)
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            with pytest.raises(kernel.InvalidCell, match='projection'):
                store.partition_archived_cells(cold, (), projections=projections, check=lambda: None)
        assert custody._rows(connection) == before


def test_historical_projection_restores_raw_write_guards_and_preserves_original(tmp_path, monkeypatch):
    with custody._registry_court(tmp_path, monkeypatch) as (
            store, history, service, _old, _child, _work, _room):
        custody._registry_until(store, history, service, 'ordinary')
        root = service._owner.universal_registry.value_graph_protocol.root_id
        connection, _lock = store.sqlite_storage()
        revision = connection.execute('SELECT MIN(revision) FROM cell_versions WHERE cell_id=?',
                                      (root,)).fetchone()[0]
        current = store.read(root)
        cold_path = archive.trace_archive_path(service._path)
        old = _preserve_review_version(store, cold_path, revision, root)
        projected = kernel.Cell(root, kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, old.atom)
        original_digest = store.revision_chain_digest()
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            original = tuple(cold.execute('SELECT * FROM trace_versions WHERE revision=? AND cell_id=?',
                                          (revision, root)).fetchone())
            store.partition_archived_cells(cold, (), projections=((revision, old, projected),), check=lambda: None)
        assert store.read(root) == current
        assert store.read(root, revision=revision) == projected
        assert store.revision_chain_digest() == original_digest
        before = custody._rows(connection)
        certificate = tuple(connection.execute('SELECT * FROM trace_projection_custody WHERE revision=? AND cell_id=?',
                                               (revision, root)).fetchone())
        for statement, arguments in (
                ('UPDATE cell_versions SET link0=? WHERE revision=? AND cell_id=?',
                 (old.link0, revision, root)),
                ('UPDATE trace_projection_custody SET live_hash=? WHERE revision=? AND cell_id=?',
                 ('0' * 64, revision, root)),
                ('DELETE FROM trace_projection_custody WHERE revision=? AND cell_id=?', (revision, root)),
                ('INSERT OR REPLACE INTO trace_projection_custody VALUES(?,?,?,?)', certificate)):
            with pytest.raises(sqlite3.Error):
                connection.execute(statement, arguments)
            with closing(sqlite3.connect(store.database_path)) as external:
                with pytest.raises(sqlite3.Error):
                    external.execute(statement, arguments)
        assert custody._rows(connection) == before
        assert tuple(connection.execute('SELECT * FROM trace_projection_custody WHERE revision=? AND cell_id=?',
                                        (revision, root)).fetchone()) == certificate
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            assert tuple(cold.execute('SELECT * FROM trace_versions WHERE revision=? AND cell_id=?',
                                      (revision, root)).fetchone()) == original


@pytest.mark.parametrize('prefix', ('absent', 'rewritten'))
def test_retrospective_projection_deltas_telescope_to_original_history(tmp_path, prefix):
    path, cold_path = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    chain_id = 'conversation-control:review-index'
    role = kernel.Cell('control-role:review-member', kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'')
    targets = tuple(kernel.Cell('trace:proof-' + name, kernel.NULL_CELL_ID, kernel.NULL_CELL_ID,
                                name.encode()) for name in 'abcd')
    incidences = tuple(kernel.Cell('conversation-control:review-incidence-' + name,
                                   role.id, target.id, b'') for name, target in zip('abcd', targets))
    work = tuple(kernel.Cell('work:unchanged-' + name, kernel.NULL_CELL_ID,
                             kernel.NULL_CELL_ID, name.encode()) for name in ('nodes', 'workflow'))
    original_prefix = kernel.Cell(chain_id, incidences[0].id, kernel.NULL_CELL_ID, b'')
    current = kernel.Cell(chain_id, incidences[2].id, kernel.NULL_CELL_ID, b'')
    planned_early = kernel.Cell(chain_id, incidences[1].id, kernel.NULL_CELL_ID, b'')
    planned_later = kernel.Cell(chain_id, incidences[3].id, kernel.NULL_CELL_ID, b'')
    with kernel.CellStore(path) as store:
        assert store.commit(store.revision, create=(role, *targets, *incidences, *work)) == 1
        assert store.commit(store.revision, create=(original_prefix,) if prefix == 'rewritten' else (
            kernel.Cell('work:revision-two', kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'2'),)) == 2
        assert store.commit(store.revision, create=(
            kernel.Cell('work:revision-three', kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'3'),)) == 3
        assert store.commit(store.revision, **(
            {'replace': (current,)} if prefix == 'rewritten' else {'create': (current,)})) == 4
        expected_cells = _bytes(store)
        expected_accumulators = {revision: store.set_accumulator(store._history_reader.snapshot_at(revision))
                                 for revision in range(1, 5)}
        original_chain = store.revision_chain_digest()
        if prefix == 'rewritten':
            assert _preserve_review_version(store, cold_path, 2, chain_id) == original_prefix
        else:
            with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=True)):
                pass
        # Deliberately reverse request order: the kernel owns canonical ordering.
        projections = ((3, None, planned_later),
                       (2, original_prefix if prefix == 'rewritten' else None, planned_early))
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            store.partition_archived_cells(cold, (), projections=projections, check=lambda: None)
        assert _bytes(store) == expected_cells
        assert store.read(chain_id, revision=2) == planned_early
        assert store.read(chain_id, revision=3) == planned_later
        assert store.read(chain_id) == current
        assert all(store.read(cell.id) == cell for cell in work)
        for revision, expected in expected_accumulators.items():
            assert store.set_accumulator(store._history_reader.snapshot_at(revision)) == expected, (
                'projection correction must preserve the original logical set at every boundary', revision)
        assert store.revision_chain_digest() == original_chain

    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        Path(str(path) + suffix).unlink(missing_ok=True)
    with _rollback_kernel() as previous_kernel:
        with previous_kernel.CellStore(path) as previous:
            assert _bytes(previous) == expected_cells
            for revision, desired in ((2, planned_early), (3, planned_later), (4, current)):
                actual = previous.read(chain_id, revision=revision)
                assert (actual.id, actual.link0, actual.link1, actual.atom) == (
                    desired.id, desired.link0, desired.link1, desired.atom)
    with kernel.CellStore(path) as reopened:
        assert _bytes(reopened) == expected_cells
        for revision, expected in expected_accumulators.items():
            assert reopened.set_accumulator(reopened._history_reader.snapshot_at(revision)) == expected
        assert reopened.revision_chain_digest() == original_chain
    print('ADOPT_RETROSPECTIVE_DELTA', dict(prefix=prefix, boundaries=len(expected_accumulators),
                                          current_identities=len(expected_cells), kernel='e41d56aa'))


@pytest.mark.parametrize('change', ('stable', 'backdated', 'restart', 'delta'))
def test_activity_inventory_skip_requires_complete_unchanged_session_ages(tmp_path, monkeypatch, change):
    from types import SimpleNamespace
    import time
    from nodelang import conversation_retention_maintenance as maintenance

    now = time.time()
    dependency = kernel.Cell('app:deliberation:clock-dependency:chain:0',
        kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'older dependency must stay readable')
    member = kernel.Cell('app:workshop:review-clock:chain:0', dependency.id,
        kernel.NULL_CELL_ID, b'old member')
    later = kernel.Cell('app:workshop:review-clock:chain:1',
        kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'previous version')
    path, content = tmp_path / 'clock.sqlite3', tmp_path / 'clock-content.sqlite3'
    with kernel.CellStore(path) as store:
        for age, create, replace in (
                (40, (dependency, member), ()),
                (1 if change == 'backdated' else 40, (later,), ()),
                (40, (), (kernel.Cell(later.id, later.link0, later.link1, b'backdated current'),))):
            with monkeypatch.context() as clock:
                clock.setattr(kernel, 'time', SimpleNamespace(time=lambda age=age: now-age*86400))
                store.commit(store.revision, create=create, replace=replace)
        history = ConversationHistoryStore(content, instance_id='clock-review')
        try:
            history.initialize_trace_maintenance()
            for _ in range(64):
                maintenance._advance_family_inventory(store, history, lambda: None, 1)
                state = history._db.execute('SELECT phase FROM trace_family_state').fetchone()
                if state[0] == 'delta':
                    break
            else:
                pytest.fail('tiny historical clock fixture did not reach delta')
            assert history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id=?',
                (dependency.id,)).fetchone() is None
            if change == 'backdated':
                assert history._trace_activity_inventory is None
                assert history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?',
                    ('app:workshop:review-clock',)).fetchone()[0] == now-86400
            elif change == 'restart':
                history.close()
                history = ConversationHistoryStore(content, instance_id='clock-review', create=False)
                assert getattr(history, '_trace_activity_inventory', None) is None
            elif change == 'delta':
                store.commit(store.revision, create=(kernel.Cell('app:workshop:review-clock:chain:2',
                    kernel.NULL_CELL_ID, kernel.NULL_CELL_ID, b'new session activity'),))
            for _ in range(16):
                maintenance._advance_family_inventory(store, history, lambda: None, 1)
                phase = history._db.execute('SELECT phase FROM trace_family_state').fetchone()[0]
                if phase != 'delta':
                    break
            assert phase == ('protect' if change == 'stable' else 'retain')
            if change in ('backdated', 'delta'):
                for _ in range(16):
                    maintenance._advance_family_inventory(store, history, lambda: None, 1)
                    if history._db.execute('SELECT phase FROM trace_family_state').fetchone()[0] != 'retain':
                        break
                assert history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id=?',
                    (dependency.id,)).fetchone() is not None
                assert store.read(dependency.id) == dependency
        finally:
            history.close()


@pytest.fixture
def review_receipt_server(tmp_path, monkeypatch, request):
    from tests_replica import test_adopt_owned_receipts as receipts
    local = custody.upgrade.isolated_profile.__wrapped__(tmp_path, monkeypatch)
    yield from receipts.server.__wrapped__(local, tmp_path, request, monkeypatch)


def test_historical_receipt_projection_retains_changing_children_and_different_meaning(
        review_receipt_server, monkeypatch):
    from collections.abc import Mapping
    import time
    from nodelang import commit_intent
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang import conversation_trace_receipts as receipts
    from nodelang.cell_agent_body import _read_authorization_receipt
    from tests_replica import test_adopt_owned_receipts as fixture

    server = review_receipt_server
    session = fixture._session(server, monkeypatch, label='independent-historical-receipt')
    store, registry = server.universal_store, server.universal_registry
    history = fixture._history(server)
    connection, lock = store.sqlite_storage()
    roots = (session.view_receipt_root, session.scope_receipt_root, session.close_receipt_root)
    initial = {root: store.read(root) for root in roots}
    revisions = {root: connection.execute('SELECT MIN(revision) FROM cell_versions WHERE cell_id=?',
        (root,)).fetchone()[0] for root in roots}

    class HistoricalCells(Mapping):
        def __init__(self, revision):
            self.revision = revision
        def __getitem__(self, key):
            return store.read(key, revision=self.revision)
        def __iter__(self):
            raise AssertionError('receipt court must not enumerate graph history')
        def __len__(self):
            return len(store.snapshot().cells)

    def historical(root):
        revision = revisions[root]
        return _read_authorization_receipt(kernel.Snapshot(revision, HistoricalCells(revision)),
            registry.agent_body.protocol, registry.authorization.protocol, root)

    before = {root: historical(root) for root in roots}
    # View changes and returns to its original meaning without a root rewrite.
    # Scope retains a different meaning. Close is an unchanged positive control.
    with commit_intent.declare(commit_intent.MIGRATION, actor='independent receipt court',
            reason='synthetic historical terminal changes'):
        terminal = store.read(roots[0]+':reason')
        store.commit(store.revision, replace=(kernel.Cell(terminal.id,
            terminal.link0, terminal.link1, b'transient historical reason'),))
        store.commit(store.revision, replace=(terminal,))
        scope_reason = store.read(roots[1]+':reason')
        store.commit(store.revision, replace=(kernel.Cell(scope_reason.id,
            scope_reason.link0, scope_reason.link1, b'different current reason'),))

    cold_path = archive.trace_archive_path(server.conversation_content._path)
    for root in roots:
        snapshot = store.snapshot()
        original = snapshot.cells[root]
        _before, compact, children = receipts._receipt_shape(snapshot,
            registry.agent_body.protocol, registry.authorization.protocol, root, lambda: None)
        ordered = sorted((original, *children.values()), key=lambda cell: cell.id)
        receipts._begin_receipt(history, store, session.root_id, original, compact,
            time.time()-40*86400, lambda: None)
        # Same durable copy/register/publication order as the converter, without
        # running its incremental idle scheduler in this admission countercourt.
        for start in range(0, len(ordered), 256):
            page = ordered[start:start+256]
            with lock, closing(archive.preserve_trace_batch(connection, cold_path,
                    store.authority_identity, tuple(cell.id for cell in page),
                    {cell.id: session.root_id for cell in page}, lambda: None)[0]) as cold:
                history.index_trace_archive(cold, (session.root_id,), archive_path=cold_path,
                    cell_ids=tuple(cell.id for cell in page))
            receipts._register_children(history, session.root_id, root, page,
                time.time()-40*86400, page[-1].id, lambda: None)
        with history._transaction(write=True):
            history._db.execute("UPDATE trace_migrations SET state='bound' WHERE conversation_id=?",
                (session.root_id,))
        with commit_intent.declare(commit_intent.MIGRATION, actor=registry.authorization.subject_root,
                reason='publish exactly verified synthetic compact receipt'):
            registry.authorization.broker.commit_authenticated(registry.authorization.session.context(),
                store, store.revision, replace=(compact,))

    store._trace_archive_registry = registry
    current = _bytes(store)
    revision = store.revision
    for index, root in enumerate(roots):
        state = {'delta_revision': revisions[root], 'delta_cell': root[:-1]}
        assert maintenance._project_trace_catalogue_page(store, history, state,
            lambda: None, 1) == (revisions[root], root)
        expected = initial[root] if index < 2 else store.read(root)
        assert store.read(root, revision=revisions[root]) == expected
        assert historical(root) == before[root]
        with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
            held = cold.execute('SELECT link0,link1,atom FROM trace_versions WHERE revision=? AND cell_id=?',
                (revisions[root], root)).fetchone()
            assert held is not None and (held[0], held[1], bytes(held[2])) == (
                initial[root].link0, initial[root].link1, initial[root].atom)
    assert _bytes(store) == current and store.revision == revision
    assert store.read(roots[0], revision=revisions[roots[0]]).atom == b''
    assert store.read(roots[1], revision=revisions[roots[1]]).atom == b''
    assert store.read(roots[2], revision=revisions[roots[2]]).atom
