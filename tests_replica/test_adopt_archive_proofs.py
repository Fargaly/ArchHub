"""Authentic signed-v1 custody and physical proof-table tamper courts."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

import pytest

from nodelang import commit_intent, conversation_archive as archive, unified_authority as ua
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID, Snapshot
from tests_replica.test_adopt_signed_archive import _old_family, _partition
from tests_replica.test_v2_head_digest import _provision, _recorded_head_digest
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile


@pytest.fixture(autouse=True)
def _private_temporary_files(tmp_path, monkeypatch, isolated_profile):
    temporary = tmp_path / 'TEMP'
    temporary.mkdir()
    monkeypatch.setenv('TEMP', str(temporary))
    monkeypatch.setenv('TMP', str(temporary))
    monkeypatch.setattr(tempfile, 'tempdir', str(temporary))


def _v1_partition(tmp_path, monkeypatch):
    built = _provision(tmp_path)
    authority = built.location.authority
    store = authority.store
    ua.bind_signed_commit_owner(authority)
    def original_v1(auth, base, *, create, replace, blank_atom_roots):
        candidate = ua.overlay_read_snapshot(base, create=tuple(create), replace=tuple(replace))
        return ua._normalized_snapshot_digest(candidate, tuple(blank_atom_roots))
    try:
        with monkeypatch.context() as formula:
            formula.setattr(ua, '_committed_head_digest', original_v1)
            cells, sessions = _old_family(store, 'app:workshop:real-v1-court', monkeypatch)
        recorded = _recorded_head_digest(authority, store.snapshot())
        assert type(recorded) is str and len(recorded) == 64
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='mixed signed-head fixture'):
            store.commit(store.revision, create=(Cell('work:after-v1', NULL_CELL_ID, NULL_CELL_ID, b'new v2 work'),))
        assert _recorded_head_digest(authority, store.snapshot()).startswith('v2:')
        store._journal._trace_chain_schema()
        class BudgetReached(Exception):
            pass
        interrupted = 0
        publication_yielded = False
        for _attempt in range(100):
            remaining = 1
            def short_budget():
                nonlocal remaining
                if remaining == 0:
                    raise BudgetReached()
                remaining -= 1
            try:
                ua.capture_archived_v1_heads(authority, short_budget)
            except BudgetReached:
                interrupted += 1
                state = store._archive_v1_capture
                assert state is not None and getattr(store, '_archive_v1_frontier', None) is None
                publication_yielded |= state['head'] is None and bool(state['pending'])
            else:
                break
        else:
            pytest.fail('signed-head custody did not resume within the bounded passes')
        assert interrupted > 0 and publication_yielded
        assert store._archive_v1_capture is None
        content = tmp_path / 'v1-court.conversations.sqlite3'
        with ConversationHistoryStore(content, instance_id='v1-court') as history:
            history.initialize_trace_maintenance()
            cold = archive.trace_archive_path(content)
            _partition(store, history, cold, cells, sessions)
        return built, Path(store.database_path), cold
    finally:
        store.close()


def test_archived_v1_signed_head_reopens_without_disposable_or_cold_proofs(tmp_path, monkeypatch):
    built, database, cold = _v1_partition(tmp_path, monkeypatch)
    Path(str(database) + '.accelerators').unlink(missing_ok=True)
    opened = []
    connect = sqlite3.connect
    def observed(path, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(path):
            opened.append(str(path))
        return connect(path, *args, **kwargs)
    with monkeypatch.context() as observing:
        observing.setattr(sqlite3, 'connect', observed)
        with CellStore(database) as store:
            authority = ua.open_unified_authority(store, built.location.authority.manifest,
                built.location.authority.key_provider)
            ua.bind_signed_commit_owner(authority)
            ua._HEAD_VERDICT_CACHE.clear()
            ua._verify_current_head(authority, store.snapshot(), None)
        assert opened == []
    assert archive.read_trace_archive(cold, 'app:workshop:real-v1-court')['cells']
    print('ADOPT_V1_ARCHIVED_STARTUP_COLD_OPENS', len(opened))


@pytest.mark.parametrize('table', ('trace_chain_proofs', 'trace_live_proofs', 'trace_set_deltas',
                                  'trace_snapshot_proofs', 'trace_signed_head_proofs'))
def test_raw_replace_cannot_rewrite_archive_proof_custody(tmp_path, monkeypatch, table):
    _built, database, _cold = _v1_partition(tmp_path, monkeypatch)
    def refused(connection):
        rows = connection.execute('SELECT * FROM ' + table + ' ORDER BY revision').fetchall()
        assert rows, 'a real authenticated partition must populate the protected proof table'
        changed = list(rows[0])
        changed[-1] = b'forged' if isinstance(changed[-1], bytes) else 'forged'
        statement = 'INSERT OR REPLACE INTO ' + table + ' VALUES(' + ','.join('?' for _ in changed) + ')'
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(statement, changed)
            connection.commit()
        connection.rollback()
        assert connection.execute('SELECT * FROM ' + table + ' ORDER BY revision').fetchall() == rows
    with CellStore(database) as owner:
        connection, _lock = owner.sqlite_storage()
        refused(connection)
    with closing(sqlite3.connect(database)) as external:
        assert external.execute('PRAGMA recursive_triggers').fetchone()[0] == 0
        refused(external)


def test_exact_accepted_floor_uses_canonical_authenticated_custody(tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.authority_adoption import adopt_application_authority
    from nodelang.unified_authority_runtime import _AcceptedSnapshotProof
    database = tmp_path / 'accepted-floor.sqlite3'
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'f' * 32)
    keys.add_key('archhub.local.court-attestation', b'c' * 32)
    server = ApplicationServer(universal_state_path=database, universal_key_provider=keys,
        universal_workspace_root=tmp_path, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, live_watch=False)
    try:
        cells, sessions = _old_family(server.universal_store,
            'app:workshop:accepted-floor-trace', monkeypatch)
    finally:
        server.close()
    with CellStore(database) as store:
        # The production adoption planner signs the actual receipt-owning
        # application's retained prefix, including this pre-existing trace.
        authority = adopt_application_authority(store, keys,
            source_history_digest=store.revision_chain_digest())
        manifest = authority.manifest
        (tmp_path / 'bootstrap.json').write_text(manifest.to_json(), encoding='utf-8')
        ua.bind_signed_commit_owner(authority)
        with ConversationHistoryStore(tmp_path / 'floor-content.sqlite3', instance_id='floor-court') as history:
            history.initialize_trace_maintenance()
            _partition(store, history, archive.trace_archive_path(tmp_path / 'floor-content.sqlite3'), cells, sessions)
    Path(str(database) + '.accelerators').unlink(missing_ok=True)
    opened = []
    connect = sqlite3.connect
    def observed(path, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(path):
            opened.append(str(path))
        return connect(path, *args, **kwargs)
    with monkeypatch.context() as observing:
        observing.setattr(sqlite3, 'connect', observed)
        with CellStore(database) as store:
            authority = ua.open_unified_authority(store, manifest, keys,
                accepted_proof=_AcceptedSnapshotProof(tmp_path))
            ua._HEAD_VERDICT_CACHE.clear()
            accepted = store.at(manifest.accepted_revision)
            ua.verify_exact_authority_head(authority, accepted)
            foreign = dict(accepted.cells)
            foreign['work:forged-floor'] = Cell('work:forged-floor', NULL_CELL_ID, NULL_CELL_ID, b'forged')
            with pytest.raises(InvalidCell):
                ua.verify_exact_authority_head(authority, Snapshot(accepted.revision, foreign))
        assert opened == []
    print('ADOPT_ACCEPTED_FLOOR_COLD_OPENS', len(opened))
