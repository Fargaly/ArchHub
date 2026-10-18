"""Typed production receipt roots must not pin all obsolete child scaffolding."""
from collections import ChainMap
from contextlib import closing
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from nodelang import commit_intent, conversation_archive as archive
from nodelang.application_server import ApplicationServer
from nodelang.cell_agent_body import (
    _read_authorization_receipt, close_agent_session, read_agent_body, read_agent_session,
)
from nodelang.cell_identity import verify_relationship_authority_snapshot
from nodelang.cell_protocols import compose_relation_cells, read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.conversation_history import ConversationHistoryStore
from nodelang import conversation_trace_receipts as receipts
from nodelang.conversation_retention_maintenance import (
    _advance_family_inventory, _advance_trace_registry, _legacy_trace_history, partition_archived_trace_batch,
    maintain_trace_families,
)
from nodelang.universal_application import (
    _agent_body_request, begin_universal_runtime_agent_session,
    _verify_application_agent_receipts,
)
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID, Snapshot
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile


@pytest.fixture
def server(isolated_profile, tmp_path, request, monkeypatch):
    path = tmp_path / 'synthetic-receipt-owner.sqlite3'
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    keys.add_key('archhub.local.court-attestation', b'c' * 32)
    import nodelang.universal_cell as kernel
    with monkeypatch.context() as clock:
        age = getattr(request, 'param', 0)
        if age:
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-age*86400))
        app = ApplicationServer(universal_state_path=path, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, live_watch=False)
    app._receipt_court_keys = keys
    app._receipt_court_path = path
    app._receipt_court_workspace = tmp_path
    try:
        yield app
    finally:
        app.close()


def _session(server, monkeypatch, *, label='old-closed', age=40, closed=True):
    import nodelang.universal_cell as kernel
    store, registry = server.universal_store, server.universal_registry
    authorization, protocol = registry.authorization, registry.agent_body.protocol
    context = authorization.session.context()
    root = 'app:agent-session:runtime:receipt-court-' + label
    with monkeypatch.context() as clock, commit_intent.declare(commit_intent.MIGRATION,
            actor='court', reason='synthetic historical session through actual typed creator'):
        clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-age*86400))
        session, _ = begin_universal_runtime_agent_session(store, registry,
            session_root=root, runtime='baboom-execution', external_session_fingerprint='b'*64,
            catalog_entry_root='app:agent-body-catalog:entry:baboom-execution',
            authentication_context=context)
        if closed:
            body = read_agent_body(store.snapshot(), protocol, authorization.protocol, session.body_root)
            authority_snapshot = verify_relationship_authority_snapshot(store.snapshot(),
                authorization.identity_protocol, authorization.relationship_broker)
            close_agent_session(store, protocol, authorization.protocol, authorization.broker,
                context, _agent_body_request(authorization, protocol, body.lifecycle_root,
                    'execute', root, lineage_roots=(session.scope_root,)), root,
                resolver_state=authority_snapshot)
    return read_agent_session(store.snapshot(), protocol, authorization.protocol, root)


def _history(server):
    history = _legacy_trace_history(server.conversation_content, server.universal_store.snapshot())
    history.initialize_trace_maintenance()
    history.admit_trace_custody(server.universal_store.authority_identity, server.universal_registry.application_root)
    history._db.execute("INSERT OR IGNORE INTO trace_receipt_state VALUES(1,'',0,0)")
    return history


def _prepare(server, history):
    store = server.universal_store
    context = server.universal_registry.authorization.session.context()
    for _ in range(6000):
        registry_step = _advance_trace_registry(server.conversation_content, history,
            context, lambda: None, 256)
        if registry_step is not None:
            continue
        result = _advance_family_inventory(store, history, lambda: None, 256)
        if result['status'] in ('family-ready', 'family-complete'):
            return
    pytest.fail('bounded family inventory failed to complete')


def _convert(server, session, receipt, *, check=lambda: None, once=False):
    history = _history(server)
    copied, versions = 0, 0
    for _ in range(2000):
        result = receipts._convert_receipt(server.conversation_content, history,
            server.universal_store.snapshot(), session.root_id, receipt, time.time()-40*86400,
            server.universal_registry.authorization.session.context(), check)
        copied += result['copied']
        versions += result['versions']
        if once or result['converted']:
            return {**result, 'copied': copied, 'versions': versions}
    raise AssertionError('bounded receipt conversion did not complete')


def _owned_children(history, session):
    return tuple(row[0] for row in history._db.execute(
        'SELECT cell_id FROM trace_migration_cells WHERE conversation_id=? AND owned=1 ORDER BY cell_id',
        (session.root_id,)))


def test_actual_closed_session_receipt_children_retire_root_and_graph_reads_remain(server, monkeypatch):
    session = _session(server, monkeypatch)
    recent = _session(server, monkeypatch, label='recent-count-control', age=1)
    store, registry = server.universal_store, server.universal_registry
    history = _history(server)
    roots = (session.view_receipt_root, session.scope_receipt_root, session.close_receipt_root)
    recent_roots = (recent.view_receipt_root, recent.scope_receipt_root, recent.close_receipt_root)
    assert len(set(roots)) == 3 and all(roots)
    original = store.snapshot()
    original_roots = {root: store.read(root) for root in roots}
    original_versions = {root: tuple(store.sqlite_storage()[0].execute(
        'SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision', (root,)))
        for root in roots}
    before = {root: _read_authorization_receipt(original, registry.agent_body.protocol,
        registry.authorization.protocol, root) for root in roots}
    children = [set(receipts._receipt_shape(original, registry.agent_body.protocol,
        registry.authorization.protocol, root, lambda: None)[2]) for root in roots]
    expected_children = set().union(*children)
    assert len(expected_children) == sum(map(len, children)), 'each old receipt owns its exact children'
    recent_children = set().union(*(set(receipts._receipt_shape(original, registry.agent_body.protocol,
        registry.authorization.protocol, root, lambda: None)[2]) for root in recent_roots))
    assert recent_children and not expected_children.intersection(recent_children)
    expected_retained = {key: cell for key, cell in original.cells.items() if key not in expected_children}
    graph_count = len(expected_retained)-len(recent_children)
    count_before = len(original.cells)
    for root in roots:
        assert _convert(server, session, root)['converted'] == 1
        assert json.loads(store.read(root).atom)['version'] == 1
        assert _read_authorization_receipt(store.snapshot(), registry.agent_body.protocol,
            registry.authorization.protocol, root) == before[root]
    ids = _owned_children(history, session)
    assert set(ids) == set(expected_children)
    history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
    _prepare(server, history)
    moved = 0
    cold = archive.trace_archive_path(server.conversation_content._path)
    for offset in range(0, len(ids), 256):
        batch = ids[offset:offset+256]
        moved += partition_archived_trace_batch(store, history, cold, batch,
            {ident: session.root_id for ident in batch}, check=lambda: None)
    assert moved == len(expected_children)
    assert len(store.snapshot().cells) == count_before-moved == graph_count+len(recent_children)
    assert {key: cell for key, cell in store.snapshot().cells.items() if key not in roots} == {
        key: cell for key, cell in expected_retained.items() if key not in roots}
    assert all(store.read(ident) == original.cells[ident] for ident in recent_children)
    assert read_agent_session(store.snapshot(), registry.agent_body.protocol,
        registry.authorization.protocol, session.root_id) == session
    assert read_agent_session(store.snapshot(), registry.agent_body.protocol,
        registry.authorization.protocol, recent.root_id) == recent
    for root in roots:
        # Sidecar-free 2230 reads the compact historical projection; exact
        # originals remain in cold custody, with identical typed meaning.
        for version in original_versions[root]:
            assert _read_authorization_receipt(store.at(version[0]),
                registry.agent_body.protocol, registry.authorization.protocol, root) == before[root]
        assert _read_authorization_receipt(store.snapshot(), registry.agent_body.protocol,
            registry.authorization.protocol, root) == before[root]
    assert history._db.execute('SELECT COUNT(*) FROM trace_sessions WHERE session_id=?', (session.root_id,)).fetchone()[0] == 1
    with closing(archive._open_trace_archive(cold, store.authority_identity, create=False)) as db:
        archived = {row[0]: Cell(row[0], row[1], row[2], bytes(row[3])) for row in db.execute(
            'SELECT cell_id,link0,link1,atom FROM trace_current WHERE session_id=?', (session.root_id,))}
        assert len(archived) == moved+3
        on_demand = Snapshot(store.revision, ChainMap(archived, store.snapshot().cells))
        for root in roots:
            held_versions = tuple(tuple(row) for row in db.execute(
                'SELECT revision,link0,link1,atom FROM trace_versions WHERE cell_id=? ORDER BY revision', (root,)))
            assert held_versions == tuple(tuple(row) for row in original_versions[root])
            assert archived[root] == original_roots[root]
            assert _read_authorization_receipt(on_demand, registry.agent_body.protocol,
                registry.authorization.protocol, root) == before[root]
    print(f'typed-receipt roots=3 before={count_before} graph={graph_count} recent={len(recent_children)} moved={moved} live={len(store.snapshot().cells)} indexed_sessions=1')


def test_transition_requires_byte_identical_live_terminals(server, monkeypatch):
    session = _session(server, monkeypatch)
    store, registry = server.universal_store, server.universal_registry
    snapshot = store.snapshot()
    before, compact, _children = receipts._receipt_shape(snapshot, registry.agent_body.protocol,
        registry.authorization.protocol, session.view_receipt_root, lambda: None)
    transition = Snapshot(snapshot.revision, ChainMap({compact.id: compact}, snapshot.cells))
    assert _read_authorization_receipt(transition, registry.agent_body.protocol,
        registry.authorization.protocol, compact.id) == before
    terminal = snapshot.cells[compact.id+':reason']
    bad = Cell(terminal.id, terminal.link0, terminal.link1, b'different')
    with pytest.raises(Exception, match='receipt content is invalid'):
        _read_authorization_receipt(Snapshot(snapshot.revision,
            ChainMap({compact.id: compact, bad.id: bad}, snapshot.cells)),
            registry.agent_body.protocol, registry.authorization.protocol, compact.id)


def test_eligibility_keeps_recent_but_compacts_stale_logically_active_receipts(server, monkeypatch):
    old = _session(server, monkeypatch)
    recent = _session(server, monkeypatch, label='recent', age=1)
    active = _session(server, monkeypatch, label='stale-active', closed=False)
    recent_active = _session(server, monkeypatch, label='recent-active', age=1, closed=False)
    history = _history(server)
    _prepare(server, history)
    snapshot, protocol = server.universal_store.snapshot(), server.universal_registry.agent_body.protocol
    cutoff = time.time()-20*86400
    assert receipts._eligible_receipt(snapshot, history, protocol, old.view_receipt_root, cutoff)[0] == old.root_id
    assert receipts._eligible_receipt(snapshot, history, protocol, recent.view_receipt_root, cutoff) is None
    assert receipts._eligible_receipt(snapshot, history, protocol, recent_active.view_receipt_root, cutoff) is None
    assert receipts._eligible_receipt(snapshot, history, protocol, active.view_receipt_root, cutoff)[0] == active.root_id
    assert _convert(server, active, active.view_receipt_root)['converted'] == 1
    assert read_agent_session(server.universal_store.snapshot(), protocol,
        server.universal_registry.authorization.protocol, active.root_id) == active


def test_receipt_copy_interruption_keeps_old_root_and_resumes_exactly(server, monkeypatch):
    session = _session(server, monkeypatch)
    store, history = server.universal_store, _history(server)
    root = session.view_receipt_root
    original = store.read(root)
    preserve = receipts.preserve_trace_batch
    def interrupt_after_cold(*args, **kwargs):
        cold, _versions = preserve(*args, **kwargs)
        cold.close()
        raise TimeoutError('synthetic hard-kill after durable cold commit')
    with monkeypatch.context() as killed:
        killed.setattr(receipts, 'preserve_trace_batch', interrupt_after_cold)
        with pytest.raises(TimeoutError):
            _convert(server, session, root)
    assert store.read(root) == original
    server.conversation_content._receipt_conversion = None
    result = _convert(server, session, root)
    assert result['converted'] == 1
    ids = _owned_children(history, session)
    assert ids
    assert history._db.execute('SELECT state FROM trace_migrations WHERE conversation_id=?', (session.root_id,)).fetchone()[0] == 'bound'


def test_large_typed_receipt_copies_bounded_pages_and_reopens_mid_copy(server, monkeypatch):
    import nodelang.universal_cell as kernel
    session = _session(server, monkeypatch)
    store, registry = server.universal_store, server.universal_registry
    protocol, root = registry.agent_body.protocol, session.view_receipt_root
    snapshot = store.snapshot()
    old_members = read_relation(snapshot, root, budget=5000)
    evidence = tuple(Cell('court:resolver-extra:'+str(index), NULL_CELL_ID, NULL_CELL_ID, b'evidence')
        for index in range(200))
    built = compose_relation_cells((*((m.role_id, m.participant_id) for m in old_members),
        *((protocol.role('receipt-resolver-evidence'), cell.id) for cell in evidence)), relation_id=root)
    create = (*evidence, *(cell for cell in built.cells if cell.id not in snapshot.cells))
    replace = tuple(cell for cell in built.cells if cell.id in snapshot.cells and cell != snapshot.cells[cell.id])
    with monkeypatch.context() as clock:
        clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-40*86400))
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='synthetic typed receipt evidence scale'):
            store.commit(store.revision, create=create, replace=replace)
    original = store.read(root)
    history = _history(server)
    first = _convert(server, session, root, once=True)
    assert first['pending'] and first['copied'] <= 256
    assert store.read(root) == original
    cursor = history._db.execute('SELECT cursor FROM trace_migrations WHERE conversation_id=?', (session.root_id,)).fetchone()[0]
    assert cursor
    # The only process-local preparation can be discarded. Durable custody and
    # the existing conversation owner's cursor reconstruct the remaining work.
    server.conversation_content._receipt_conversion = None
    history.close()
    server.conversation_content._history = None
    history = _history(server)
    assert history._db.execute('SELECT cursor FROM trace_migrations WHERE conversation_id=?', (session.root_id,)).fetchone()[0] == cursor
    copied = first['copied']
    for _ in range(1000):
        result = _convert(server, session, root, once=True)
        assert result['copied'] <= 256
        copied += result['copied']
        if result['converted']:
            break
    else:
        pytest.fail('large valid receipt did not complete bounded copy')
    assert copied == len(_owned_children(history, session))+1
    assert read_agent_session(store.snapshot(), protocol, registry.authorization.protocol, session.root_id) == session


@pytest.mark.parametrize('server', (40,), indirect=True)
def test_converted_receipt_reopens_without_archive_reads_and_cold_old_receipt_is_openable(server, monkeypatch):
    session = _session(server, monkeypatch)
    recent = _session(server, monkeypatch, label='recent-bootstrap-control', age=1)
    store, registry = server.universal_store, server.universal_registry
    protocol, authorization = registry.agent_body.protocol, registry.authorization.protocol
    roots = (session.view_receipt_root, session.scope_receipt_root, session.close_receipt_root)
    boot_roots = tuple(root for root in (registry.agent_body.body.creation_receipt_root,
        registry.agent_body.session.view_receipt_root, registry.agent_body.session.scope_receipt_root,
        registry.agent_body.session.close_receipt_root) if root)
    snapshot = store.snapshot()
    expected = {root: _read_authorization_receipt(snapshot, protocol, authorization, root)
        for root in (*roots, *boot_roots)}
    def receipt_cells(receipt_roots):
        return set(receipt_roots).union(*(set(receipts._receipt_shape(snapshot, protocol,
            authorization, root, lambda: None)[2]) for root in receipt_roots))
    boot_ids = receipt_cells(boot_roots)
    old_children = receipt_cells(roots).difference(roots)
    recent_ids = receipt_cells((recent.view_receipt_root, recent.scope_receipt_root,
        recent.close_receipt_root))
    retained = {ident: snapshot.cells[ident] for ident in boot_ids | recent_ids}
    connection, _ = store.sqlite_storage()
    boot_versions = {ident: tuple(connection.execute(
        'SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision', (ident,)))
        for ident in boot_ids}
    cutoff = time.time()-20*86400
    assert all(connection.execute('SELECT r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id=?',
        (ident,)).fetchone()[0] < cutoff for ident in boot_ids), 'bootstrap must be genuinely committed at old synthetic time'
    work = Cell('graph:receipt-bootstrap-saved-work', NULL_CELL_ID, NULL_CELL_ID, b'saved work')
    with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='synthetic saved graph control'):
        store.commit(store.revision, create=(work,))
    monkeypatch.setattr(server.conversation_content._owner, 'last_user_action_monotonic', 0.0, raising=False)
    _history(server)
    context = registry.authorization.session.context()
    converted = 0
    for _ in range(6000):
        prepared = maintain_trace_families(server.conversation_content,
            authentication_context=context, max_cells=256, prepare_only=True)
        if prepared['status'] not in ('family-ready', 'family-complete'):
            continue
        step = receipts.maintain_trace_receipts(server.conversation_content,
            authentication_context=context, max_cells=256)
        converted += step['converted']
        if step['status'] == 'receipts-complete':
            break
    else:
        pytest.fail('public bounded receipt preparation failed to complete')
    assert converted == 3, 'only the independent old session receipts may compact; boot-required roots stay graph content'
    for _ in range(6000):
        step = maintain_trace_families(server.conversation_content,
            authentication_context=context, max_cells=256)
        if step['status'] == 'family-complete':
            break
    else:
        pytest.fail('public bounded family custody failed to complete')
    assert all(ident not in store.snapshot().cells for ident in old_children)
    assert all(store.read(ident) == cell for ident, cell in retained.items())
    assert store.read(work.id) == work
    for ident, versions in boot_versions.items():
        assert tuple(connection.execute('SELECT revision,link0,link1,atom FROM cell_versions WHERE cell_id=? ORDER BY revision',
            (ident,))) == versions
    assert read_agent_session(store.snapshot(), protocol, authorization, session.root_id) == session
    assert read_agent_session(store.snapshot(), protocol, authorization, recent.root_id) == recent
    cold = archive.trace_archive_path(server.conversation_content._path)
    with closing(archive._open_trace_archive(cold, store.authority_identity, create=False)) as db:
        archived = {row[0]: Cell(row[0], row[1], row[2], bytes(row[3])) for row in db.execute(
            'SELECT cell_id,link0,link1,atom FROM trace_current WHERE session_id=?', (session.root_id,))}
        on_demand = Snapshot(store.revision, ChainMap(archived, store.snapshot().cells))
        assert set(archived) == old_children | set(roots)
        for root in roots:
            assert _read_authorization_receipt(on_demand, protocol, authorization, root) == expected[root]
    kwargs = dict(universal_state_path=server._receipt_court_path,
        universal_key_provider=server._receipt_court_keys,
        universal_workspace_root=server._receipt_court_workspace,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server.close()
    for suffix in ('.accelerators', '.accelerators-wal', '.accelerators-shm'):
        server._receipt_court_path.with_name(server._receipt_court_path.name+suffix).unlink(missing_ok=True)
    opened = []
    connect = sqlite3.connect
    def observed(database, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(database):
            opened.append(str(database))
        return connect(database, *args, **kwargs)
    with monkeypatch.context() as no_cold:
        no_cold.setattr(sqlite3, 'connect', observed)
        reopened = ApplicationServer(**kwargs)
        try:
            for root in (*roots, *boot_roots):
                assert _read_authorization_receipt(reopened.universal_store.snapshot(),
                    reopened.universal_registry.agent_body.protocol,
                    reopened.universal_registry.authorization.protocol, root) == expected[root]
            _verify_application_agent_receipts(reopened.universal_store,
                reopened.universal_registry.authorization, reopened.universal_registry.agent_body)
            assert reopened.universal_store.read(work.id) == work
        finally:
            reopened.close()
    assert opened == [], 'startup must open/read/verify zero archived Cells'
    print(f'aged-bootstrap protected_receipts={len(boot_roots)} protected_cells={len(boot_ids)} old_receipts=3 moved={len(old_children)} cold_boot_opens={len(opened)}')


def test_multiple_known_root_rewrites_do_not_repeat_whole_live_retain_scan(server, monkeypatch):
    session = _session(server, monkeypatch)
    store, history = server.universal_store, _history(server)
    _prepare(server, history)
    catalog = store._trace_registry_cache
    assert catalog['complete']
    inspected = 0
    roots = (session.view_receipt_root, session.scope_receipt_root, session.close_receipt_root)
    for root in roots:
        assert _convert(server, session, root)['converted'] == 1
        assert store._trace_registry_cache is catalog
        assert catalog['revision'] == store.revision
        assert _advance_trace_registry(server.conversation_content, history,
            server.universal_registry.authorization.session.context(), lambda: None, 256) is None
        watermark = history._db.execute('SELECT watermark FROM trace_family_state WHERE singleton=1').fetchone()[0]
        assert watermark == store.revision
        step = _advance_family_inventory(store, history, lambda: None, 256)
        assert step['status'] == 'family-ready'
        inspected += step['inspected']
    assert inspected == 0, 'known root-only rewrites must not repeat whole-live retain pages'
    assert history._db.execute('SELECT dirty FROM trace_receipt_state WHERE singleton=1').fetchone()[0] == 1


def test_committed_compact_root_reopens_before_old_children_are_partitioned(server, monkeypatch):
    session = _session(server, monkeypatch)
    root = session.view_receipt_root
    registry = server.universal_registry
    expected = _read_authorization_receipt(server.universal_store.snapshot(), registry.agent_body.protocol,
        registry.authorization.protocol, root)
    assert _convert(server, session, root)['converted'] == 1
    legacy_terminal = server.universal_store.read(root+':reason')
    kwargs = dict(universal_state_path=server._receipt_court_path,
        universal_key_provider=server._receipt_court_keys,
        universal_workspace_root=server._receipt_court_workspace,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server.close()
    reopened = ApplicationServer(**kwargs)
    try:
        assert reopened.universal_store.read(legacy_terminal.id) == legacy_terminal
        assert _read_authorization_receipt(reopened.universal_store.snapshot(),
            reopened.universal_registry.agent_body.protocol,
            reopened.universal_registry.authorization.protocol, root) == expected
        history = _legacy_trace_history(reopened.conversation_content, reopened.universal_store.snapshot())
        assert _owned_children(history, session)
        assert history._db.execute('SELECT dirty FROM trace_receipt_state WHERE singleton=1').fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize('tamper', ('missing', 'current', 'history'))
def test_receipt_progress_cursor_cannot_substitute_for_exact_cold_custody(tmp_path, tamper):
    from tests_replica.test_adopt_archive_p1 import _source
    source = _source()
    cell = Cell('app:agent-session:runtime:custody:view-receipt:reason', NULL_CELL_ID, NULL_CELL_ID, b'explicit-permit')
    source.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)', (cell.id, 1, cell.link0, cell.link1, cell.atom))
    source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)', (1, cell.id, cell.link0, cell.link1, cell.atom))
    path = tmp_path/'cold.sqlite3'
    with closing(archive.preserve_trace_batch(source, path, 'synthetic-authority',
            (cell.id,), {cell.id: 'synthetic-session'}, lambda: None)[0]) as cold:
        if tamper == 'missing':
            cold.execute('DELETE FROM trace_current WHERE cell_id=?', (cell.id,))
        elif tamper == 'current':
            cold.execute('UPDATE trace_current SET atom=? WHERE cell_id=?', (b'changed', cell.id))
        else:
            cold.execute('UPDATE trace_versions SET digest=? WHERE cell_id=?', ('0'*64, cell.id))
        cold.commit()
    proof = receipts._ReceiptCustody(SimpleNamespace(revision=1, authority_identity='synthetic-authority'),
        source, path, (cell,), 'synthetic-session')
    try:
        with pytest.raises(archive.ArchiveConflict, match='custody'):
            proof.advance(lambda: None)
    finally:
        proof.close()
    source.close()


def test_many_version_verification_advances_under_sixteen_check_budget(tmp_path):
    from tests_replica.test_adopt_archive_p1 import _source
    source = _source()
    cells = []
    for number in range(12):
        identifier = 'app:agent-session:runtime:proof:view-receipt:chain:'+str(number)
        for revision in range(35):
            atom = f'{number}:{revision}'.encode()
            source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)',
                (revision, identifier, NULL_CELL_ID, NULL_CELL_ID, atom))
        cell = Cell(identifier, NULL_CELL_ID, NULL_CELL_ID, atom)
        cells.append(cell)
        source.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)',
            (identifier, 34, cell.link0, cell.link1, cell.atom))
    path = tmp_path/'many-version-cold.sqlite3'
    with closing(archive.preserve_trace_batch(source, path, 'synthetic-authority',
            tuple(cell.id for cell in cells), {cell.id:'synthetic-session' for cell in cells}, lambda: None)[0]):
        pass
    proof = receipts._ReceiptCustody(SimpleNamespace(revision=34, authority_identity='synthetic-authority'),
        source, path, cells, 'synthetic-session')
    completed = False
    try:
        for _ in range(100):
            checks = 0
            previous = proof.verified_rows
            def check():
                nonlocal checks
                checks += 1
                if checks > 16:
                    raise TimeoutError('synthetic idle slice exhausted')
            try:
                completed = proof.advance(check)
            except TimeoutError:
                assert 0 < proof.verified_rows-previous <= 16
            if completed:
                break
        assert completed, 'a large valid proof must progress across small idle slices'
        assert proof.verified_rows == 12*(35+2), 'each current/version/end row is verified exactly once'
        service = SimpleNamespace(_receipt_custody=proof, _receipt_conversion=object())
        receipts.close_trace_receipt_preparation(service)
        assert proof.cold is None and proof.witness is None
        assert service._receipt_conversion is None and service._receipt_custody is None
    finally:
        proof.close()
        source.close()


@pytest.mark.parametrize('table', ('trace_current', 'trace_versions'))
def test_pinned_cold_snapshot_cannot_hide_external_tamper_between_slices(tmp_path, table):
    from tests_replica.test_adopt_archive_p1 import _source
    source = _source()
    cell = Cell('app:agent-session:runtime:witness:view-receipt:reason', NULL_CELL_ID, NULL_CELL_ID, b'explicit-permit')
    source.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)', (cell.id, 1, cell.link0, cell.link1, cell.atom))
    source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)', (1, cell.id, cell.link0, cell.link1, cell.atom))
    path = tmp_path/'witness-cold.sqlite3'
    with closing(archive.preserve_trace_batch(source, path, 'synthetic-authority',
            (cell.id,), {cell.id:'synthetic-session'}, lambda: None)[0]):
        pass
    proof = receipts._ReceiptCustody(SimpleNamespace(revision=1, authority_identity='synthetic-authority'),
        source, path, (cell,), 'synthetic-session')
    try:
        assert not proof.advance(lambda: None, max_rows=1)
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE '+table+' SET atom=? WHERE cell_id=?', (b'external-tamper', cell.id))
        with pytest.raises(archive.ArchiveConflict, match='generation changed'):
            proof.advance(lambda: None)
    finally:
        proof.close()
        source.close()


def test_background_created_receipt_proof_closes_on_main_thread_shutdown(tmp_path):
    source = sqlite3.connect(':memory:', check_same_thread=False)
    source.execute('CREATE TABLE current_cells(cell_id TEXT PRIMARY KEY,revision INTEGER,link0 TEXT,link1 TEXT,atom BLOB)')
    source.execute('CREATE TABLE cell_versions(revision INTEGER,cell_id TEXT,link0 TEXT,link1 TEXT,atom BLOB)')
    cell = Cell('app:agent-session:runtime:thread:view-receipt:reason', NULL_CELL_ID, NULL_CELL_ID, b'explicit-permit')
    source.execute('INSERT INTO current_cells VALUES(?,?,?,?,?)', (cell.id, 1, cell.link0, cell.link1, cell.atom))
    source.execute('INSERT INTO cell_versions VALUES(?,?,?,?,?)', (1, cell.id, cell.link0, cell.link1, cell.atom))
    path = tmp_path/'thread-cold.sqlite3'
    with closing(archive.preserve_trace_batch(source, path, 'synthetic-authority',
            (cell.id,), {cell.id:'synthetic-session'}, lambda: None)[0]):
        pass
    service = SimpleNamespace(_receipt_custody=None, _receipt_conversion=object())
    errors = []
    def background():
        try:
            service._receipt_custody = receipts._ReceiptCustody(
                SimpleNamespace(revision=1, authority_identity='synthetic-authority'),
                source, path, (cell,), 'synthetic-session')
            service._receipt_custody.advance(lambda: None, max_rows=1)
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=background)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive() and not errors
    proof = service._receipt_custody
    assert proof is not None
    receipts.close_trace_receipt_preparation(service)
    assert proof.cold is None and proof.witness is None
    assert service._receipt_custody is None and service._receipt_conversion is None
    source.close()


def test_orphan_source_composed_receipt_bypasses_typed_converter_and_archives_generically(tmp_path, monkeypatch):
    import nodelang.universal_cell as kernel
    session = 'app:agent-session:runtime:orphan-owner'
    root = session+':view-receipt'
    with CellStore(tmp_path/'orphan-source.sqlite3') as store:
        graph = tuple(Cell('graph:'+kind+str(number), NULL_CELL_ID, NULL_CELL_ID, kind.encode())
            for number in range(3) for kind in ('role', 'value'))
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='synthetic retained graph facts'):
            store.commit(store.revision, create=graph)
        retained = dict(store.snapshot().cells)
        pairs = tuple(('graph:role'+str(number), 'graph:value'+str(number)) for number in range(3))
        composed = compose_relation_cells(pairs, relation_id=root)
        with monkeypatch.context() as clock, commit_intent.declare(commit_intent.MIGRATION,
                actor='court', reason='synthetic historical orphan relation from actual composer'):
            clock.setattr(kernel, 'time', SimpleNamespace(time=lambda: time.time()-40*86400))
            store.commit(store.revision, create=composed.cells)
        with ConversationHistoryStore(tmp_path/'orphan-content.sqlite3', instance_id='a'*32, create=True) as history:
            history.initialize_trace_maintenance()
            assert session not in store.snapshot().cells
            assert receipts._eligible_receipt(store.snapshot(), history, None, root, time.time()-20*86400) is None
            ids = tuple(cell.id for cell in composed.cells)
            cold_path = archive.trace_archive_path(tmp_path/'orphan-content.sqlite3')
            with closing(archive.preserve_trace_batch(store.sqlite_storage()[0], cold_path,
                    store.authority_identity, ids, {identifier:session for identifier in ids}, lambda: None)[0]):
                pass
            assert partition_archived_trace_batch(store, history, cold_path, ids,
                {identifier:session for identifier in ids}, check=lambda: None) == len(ids)
            assert dict(store.snapshot().cells) == retained
            with closing(archive._open_trace_archive(cold_path, store.authority_identity, create=False)) as cold:
                archived = {row[0]:Cell(row[0], row[1], row[2], bytes(row[3])) for row in cold.execute(
                    'SELECT cell_id,link0,link1,atom FROM trace_current WHERE session_id=?', (session,))}
                members = read_relation(Snapshot(store.revision, ChainMap(archived, store.snapshot().cells)), root)
                assert tuple((member.role_id, member.participant_id) for member in members) == pairs
