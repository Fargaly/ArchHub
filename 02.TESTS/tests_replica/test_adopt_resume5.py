"""RESUME5: an explicitly bound historical owner survives rollback and re-upgrade."""
import pytest
import sqlite3

from nodelang import commit_intent, conversation_archive as archive, persistence
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.unified_authority import audit_authority_history, _current_head_member, _single_member
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID
from tests_replica.test_adopt_review_kernel import _rollback_kernel
from tests_replica.test_adopt_signed_archive import _old_family, _partition, _anchor_historical_owner
from tests_replica import test_ogboot_upgrade_selection as profile_owner
from tests_replica.test_ogboot_upgrade_selection import _closed_backup, _prepare


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    return profile_owner.isolated_profile.__wrapped__(tmp_path, monkeypatch)


def test_historical_signed_owner_2230_save_reupgrade(isolated_profile, tmp_path, monkeypatch):
    root = isolated_profile / 'ArchHub'
    root.mkdir()
    source = isolated_profile / 'ArchHub-Test/archhub-test.universal.sqlite3'
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    keys.add_key('archhub.local.court-attestation', b'c' * 32)
    kwargs = dict(universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server = ApplicationServer(universal_state_path=source, **kwargs)
    try:
        history_id = server.conversation_content._history.instance_id
        cells, sessions = _old_family(server.universal_store, 'app:workshop:resume5-old', monkeypatch)
    finally:
        server.close()
    _closed_backup(source)
    chosen = _prepare(root, key_provider=keys)
    with CellStore(chosen) as store:
        with ConversationHistoryStore(chosen, instance_id=history_id, store=store) as history:
            history.initialize_trace_maintenance()
            _partition(store, history, archive.trace_archive_path(chosen), cells, sessions)
            authority = _anchor_historical_owner(store, keys)
            assert authority is store._signed_commit_authority
            signed_revision = store.revision
    # This is the extracted shipping kernel, not a fake unsigned writer.
    with _rollback_kernel() as old:
        with old.CellStore(chosen) as previous:
            for number in range(3):
                marker = old.Cell('work:2230-resume5:' + str(number), old.NULL_CELL_ID,
                    old.NULL_CELL_ID, b'2230 edit retained')
                previous.commit(previous.revision, create=(marker,))
    opened_cold = []
    connect = sqlite3.connect
    def observed(database, *args, **kwargs):
        if archive.TRACE_ARCHIVE_NAME in str(database):
            opened_cold.append(str(database))
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', observed)
    server = ApplicationServer(universal_state_path=chosen, **kwargs)
    try:
        store = server.universal_store
        assert getattr(store, '_signed_commit_authority', None) is None
        persistence.bind_selected_application_authority(store, keys)
        assert store.revision > signed_revision + 3
        for number in range(3):
            assert store.read('work:2230-resume5:' + str(number)).atom == b'2230 edit retained'
        audit_authority_history(store._signed_commit_authority)
        from nodelang.authority_adoption import _legacy_continuation_id
        bridge = store.read(_legacy_continuation_id(store._signed_commit_authority, signed_revision + 4))
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='reject bridge tamper'):
            with pytest.raises(InvalidCell, match='immutable'):
                store.commit(store.revision, replace=(Cell(bridge.id, bridge.link0, bridge.link1, b'forged'),))
        with commit_intent.declare(commit_intent.MIGRATION, actor='court', reason='post rollback save'):
            store.commit(store.revision, create=(Cell('work:resume5-after', NULL_CELL_ID,
                NULL_CELL_ID, b'new signed save'),))
    finally:
        server.close()
    with _rollback_kernel() as old:
        with old.CellStore(chosen) as previous:
            for number in range(2):
                previous.commit(previous.revision, create=(old.Cell('work:second-rollback:' + str(number),
                    old.NULL_CELL_ID, old.NULL_CELL_ID, b'second legacy save'),))
    server = ApplicationServer(universal_state_path=chosen, **kwargs)
    try:
        assert server.universal_store.read('work:resume5-after').atom == b'new signed save'
        assert server.universal_store.read('work:second-rollback:1').atom == b'second legacy save'
        persistence.bind_selected_application_authority(server.universal_store, keys)
        audit_authority_history(server.universal_store._signed_commit_authority)
        authority = server.universal_store._signed_commit_authority
        snapshot = server.universal_store.snapshot()
        head = _current_head_member(authority, snapshot).participant_id
        value = _single_member(snapshot, head, authority.role('signature'))
        payload = _single_member(snapshot, value, authority.role('payload'))
    finally:
        server.close()
    with _rollback_kernel() as old:
        with old.CellStore(chosen) as previous:
            original = previous.read(payload)
            previous.commit(previous.revision, replace=(old.Cell(original.id,
                original.link0, original.link1, b'"forged legacy signature"'),))
    with CellStore(chosen) as damaged:
        with pytest.raises(InvalidCell, match='immutable signed head records'):
            persistence.bind_selected_application_authority(damaged, keys)
    assert opened_cold == []
    print('ADOPT_RESUME5_ROLLBACK kernel=e41d56aa historical_owner=explicit unsigned_edits=5 bridges=2 reupgrade=PASS signed_save=PASS tamper=REFUSED archived_boot_reads=0')


def test_partitioned_historical_suffix_uses_original_chain(tmp_path):
    from tests_replica.test_adopt_archive_identity import _retire
    from nodelang.universal_cell import revision_chain_digest_step
    path, cold = tmp_path / 'live.sqlite3', tmp_path / 'cold.sqlite3'
    with CellStore(path) as store:
        _retire(store, cold)
        digest = bytes.fromhex(store.revision_chain_digest())
        revision = store.revision
    expected = {}
    with _rollback_kernel() as old:
        with old.CellStore(path) as previous:
            for number in range(3):
                cell = old.Cell('work:delta:' + str(number), old.NULL_CELL_ID, old.NULL_CELL_ID, b'saved')
                previous.commit(previous.revision, create=(cell,))
                revision += 1
                digest = revision_chain_digest_step(digest, revision,
                    (Cell(cell.id, cell.link0, cell.link1, cell.atom),))
                expected[revision] = digest.hex()
    with CellStore(path) as store:
        assert {revision: store.revision_chain_digest(revision) for revision in expected} == expected
