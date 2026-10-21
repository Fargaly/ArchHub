"""The deferred existing anchor releases its journal when the user returns."""
import sqlite3
from types import SimpleNamespace

import pytest

from nodelang import authority_adoption, persistence, unified_authority
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


def test_deferred_anchor_cancels_sql_and_leaves_foreground_writes_usable(tmp_path, monkeypatch):
    path = tmp_path / 'authority.sqlite3'
    monkeypatch.setattr(persistence, 'selected_application_generation', lambda _path: True)
    monkeypatch.setattr(persistence, '_application_generation_directory', lambda _path: tmp_path)
    bound = []
    monkeypatch.setattr(unified_authority, 'bind_signed_commit_owner', bound.append)
    with CellStore(path) as store:
        store.commit(store.revision, create=(Cell('app:authorization-protocol:root',
            NULL_CELL_ID, NULL_CELL_ID, b'synthetic anchor admission'),))
        connection, _ = store.sqlite_storage()
        def anchor(owner, _keys, *, source_history_digest):
            assert source_history_digest == owner.revision_chain_digest()
            connection.execute('WITH RECURSIVE work(x) AS (VALUES(0) UNION ALL '
                'SELECT x+1 FROM work WHERE x<100000) SELECT sum(x) FROM work').fetchone()
            owner.commit(owner.revision, create=(Cell('work:anchored',
                NULL_CELL_ID, NULL_CELL_ID, b'anchored after idle SQL'),))
            return SimpleNamespace(manifest=SimpleNamespace(to_json=lambda: '{}'))
        monkeypatch.setattr(authority_adoption, 'adopt_application_authority', anchor)
        checks = 0
        def user_returned():
            nonlocal checks
            checks += 1
            if checks >= 4:
                raise TimeoutError('user activity resumes')
        before = store.revision
        with pytest.raises(sqlite3.OperationalError, match='interrupted'):
            persistence.finalize_application_adoption(store, None, check=user_returned)
        assert checks >= 4 and store.revision == before
        assert not (tmp_path / 'adoption.json').exists() and bound == []
        store.commit(before, create=(Cell('work:user-edit-after-yield',
            NULL_CELL_ID, NULL_CELL_ID, b'user edit remains usable'),))
        assert store.read('work:user-edit-after-yield').atom == b'user edit remains usable'
        authority = persistence.finalize_application_adoption(store, None)
        assert bound == [authority]
        assert (tmp_path / 'adoption.json').read_text() == '{}'
        assert store.read('work:anchored').atom == b'anchored after idle SQL'


def test_background_batches_do_not_repeat_the_entire_registered_inventory(monkeypatch):
    from contextlib import nullcontext
    import sys
    import threading
    from nodelang import conversation_retention_maintenance as maintenance
    from tests_replica.test_launcher_boot_refusal import _launcher_names
    inventory, phases = [], []
    def registered(**_kwargs):
        inventory.append('registered')
        return dict(status='inventory-complete', next_cursor=None)
    def families(_service, *, prepare_only=False, **_kwargs):
        phases.append(prepare_only)
        return dict(status='family-ready' if prepare_only else 'family-archiving', next_cursor=None)
    monkeypatch.setattr(maintenance, 'maintain_trace_families', families)
    monkeypatch.setitem(sys.modules, 'nodelang.conversation_trace_receipts', SimpleNamespace(
        maintain_trace_receipts=lambda *_args, **_kwargs: dict(status='receipts-complete', next_cursor=None)))
    namespace = _launcher_names('_maintain_legacy_conversations',
        _trace_retention_cursor=None, _trace_retention_status=None, _migration_status=None,
        _update_stop=threading.Event(), _conversation_maintenance_context=lambda: object(),
        _trace_background_priority=nullcontext, _boot_surface=None,
        server=SimpleNamespace(conversation_content=SimpleNamespace(maintain_legacy_trace_inventory=registered)))
    for _ in range(5):
        assert namespace['_maintain_legacy_conversations']() is True
    assert inventory == ['registered']
    assert phases == [True, False] * 5
